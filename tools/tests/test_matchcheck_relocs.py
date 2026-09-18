"""What a relocated word is allowed to hide.

The oracle used to compare any word carrying a relocation on its six-bit
primary opcode alone, because the linker fills the rest in. Under that rule a
``bl`` to the wrong function was a MATCH, and so was an address materialised
into the wrong register -- in exactly the code where matching mwcc is hardest.
These tests build their own objects and their own executable, so they need no
disc, and each one is a thing the old rule called a match.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matchcheck as M  # noqa: E402

R_PPC_ADDR32, R_PPC_ADDR16_LO, R_PPC_ADDR16_HA = 1, 4, 6
R_PPC_REL24, R_PPC_EMB_SDA21 = 10, 109

SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB, SHT_RELA = 1, 2, 3, 4
SHF_ALLOC, SHF_EXECINSTR, SHF_WRITE = 0x2, 0x4, 0x1
STT_OBJECT, STT_FUNC = 1, 2
STB_LOCAL, STB_GLOBAL = 0, 1

# One text section and one data section are enough for every case here.
TEXT, CODE, DATA = 0x80003100, 0x80003120, 0x80300000
SDA, SDA2 = 0x80304000, 0x80305000
BLR = 0x4E800020


# --------------------------------------------------------------------------
# a synthetic executable and a synthetic object
# --------------------------------------------------------------------------


def lis(rd: int, imm: int) -> int:
    return (15 << 26) | (rd << 21) | (imm & 0xFFFF)


def ori(rd: int, imm: int) -> int:
    return (24 << 26) | (rd << 21) | (rd << 16) | (imm & 0xFFFF)


def bl(frm: int, to: int) -> int:
    return 0x48000001 | ((to - frm) & 0x03FFFFFC)


def sda_load(rd: int, address: int, base: int = 13) -> int:
    """``lwz rD, address-SDA(r13)`` as the linker would leave it."""
    return (32 << 26) | (rd << 21) | (base << 16) | ((address - SDA) & 0xFFFF)


def sda_store(rs: int, address: int, base: int = 13) -> int:
    return (36 << 26) | (rs << 21) | (base << 16) | ((address - SDA) & 0xFFFF)


def executable(tmp_path: Path, code: bytes, data: bytes = b"") -> Path:
    """A DOL whose entry point is the stub the small-data bases come from.

    Real code starts at CODE, a fixed distance past it, so a test can write
    absolute addresses without counting the stub's words.
    """
    stub = struct.pack(
        ">5I", lis(2, SDA2 >> 16), ori(2, SDA2), lis(13, SDA >> 16), ori(13, SDA), BLR
    )
    text = stub.ljust(CODE - TEXT, b"\0") + code
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x00, 0x100)  # .text file offset
    struct.pack_into(">I", header, 0x48, TEXT)  # .text address
    struct.pack_into(">I", header, 0x90, len(text))  # .text size
    if data:
        struct.pack_into(">I", header, 0x1C, 0x100 + len(text))
        struct.pack_into(">I", header, 0x64, DATA)
        struct.pack_into(">I", header, 0xAC, len(data))
    struct.pack_into(">I", header, 0xE0, TEXT)  # entry point
    path = tmp_path / "main.dol"
    path.write_bytes(bytes(header) + text + data)
    return path


def build_elf(sections, symbols, relocs=None) -> bytes:
    """A big-endian ELF32 relocatable.

    ``sections`` are ``(name, bytes, flags)`` and get indices 1..n; ``symbols``
    are dicts as ``read_elf`` returns them; ``relocs`` maps a section index to
    ``(offset, symbol, type, addend)`` tuples.
    """
    relocs = relocs or {}
    targets = sorted(relocs)
    n_user = len(sections)
    symtab_idx = 1 + n_user + len(targets)
    strtab_idx, shstrtab_idx = symtab_idx + 1, symtab_idx + 2

    strtab = bytearray(b"\0")
    symtab = bytearray(16)  # the null symbol
    for sym in symbols:
        name_off = len(strtab)
        strtab.extend(sym["name"].encode() + b"\0")
        symtab.extend(
            struct.pack(
                ">IIIBBH",
                name_off if sym["name"] else 0,
                sym["value"],
                sym["size"],
                (sym["bind"] << 4) | sym["type"],
                0,
                sym["shndx"],
            )
        )

    blobs, headers = [], []
    shstrtab = bytearray(b"\0")

    def add_name(name: str) -> int:
        off = len(shstrtab)
        shstrtab.extend(name.encode() + b"\0")
        return off

    names = [add_name(name) for name, _, _ in sections]
    rela_names = [add_name(".rela" + sections[t - 1][0]) for t in targets]
    symtab_name, strtab_name, shstrtab_name = (
        add_name(".symtab"),
        add_name(".strtab"),
        add_name(".shstrtab"),
    )

    offset = 52
    headers.append(struct.pack(">10I", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    for (_, body, flags), name_off in zip(sections, names, strict=True):
        blobs.append(body)
        headers.append(
            struct.pack(">10I", name_off, SHT_PROGBITS, flags, 0, offset, len(body), 0, 0, 4, 0)
        )
        offset += len(body)
    for target, name_off in zip(targets, rela_names, strict=True):
        body = b"".join(
            struct.pack(">IIi", off, (sym << 8) | rtype, addend)
            for off, sym, rtype, addend in relocs[target]
        )
        blobs.append(body)
        headers.append(
            struct.pack(
                ">10I",
                name_off,
                SHT_RELA,
                0,
                0,
                offset,
                len(body),
                symtab_idx,
                target,
                4,
                12,
            )
        )
        offset += len(body)
    for name_off, typ, body, link, entsize in (
        (symtab_name, SHT_SYMTAB, bytes(symtab), strtab_idx, 16),
        (strtab_name, SHT_STRTAB, bytes(strtab), 0, 0),
        (shstrtab_name, SHT_STRTAB, bytes(shstrtab), 0, 0),
    ):
        blobs.append(body)
        headers.append(
            struct.pack(">10I", name_off, typ, 0, 0, offset, len(body), link, 0, 1, entsize)
        )
        offset += len(body)

    ehdr = bytearray(52)
    ehdr[0:16] = b"\x7fELF\x01\x02\x01" + b"\0" * 9
    struct.pack_into(">HHI", ehdr, 16, 1, 20, 1)  # REL, EM_PPC, version
    struct.pack_into(">I", ehdr, 0x20, offset)  # e_shoff
    struct.pack_into(">HHHHHH", ehdr, 0x28, 52, 0, 0, 40, len(headers), shstrtab_idx)
    return bytes(ehdr) + b"".join(blobs) + b"".join(headers)


def sym(name, value=0, size=0, type=0, bind=STB_GLOBAL, shndx=0):
    return {"name": name, "value": value, "size": size, "type": type, "bind": bind, "shndx": shndx}


def config(tmp_path: Path, functions: dict[int, tuple[str, int]]):
    """functions.tsv, an empty names.txt and a dtk file that is not there."""
    tsv = tmp_path / "functions.tsv"
    rows = ["\t".join(M.S.TSV_COLUMNS)]
    for address, (name, size) in sorted(functions.items()):
        rows.append(f"0x{address:08X}\t{size}\t{name}\thand\t0\t1\t0\t0\t0\t0")
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    names = tmp_path / "names.txt"
    names.write_text("", encoding="utf-8")
    return tsv, names


def run(tmp_path, obj: bytes, dol: Path, functions, capsys):
    path = tmp_path / "unit.o"
    path.write_bytes(obj)
    tsv, names = config(tmp_path, functions)
    status = M.main(
        [
            str(path),
            "--dol",
            str(dol),
            "--functions",
            str(tsv),
            "--names",
            str(names),
            "--dtk-symbols",
            str(tmp_path / "no-such-file.txt"),
        ]
    )
    return status, capsys.readouterr().out


def one_caller(target_symbol: str):
    """An object whose only function calls ``target_symbol`` and returns."""
    text = struct.pack(">II", 0x48000001, BLR)
    return build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [sym("fn_80003120", 0, 8, STT_FUNC, STB_GLOBAL, 1), sym(target_symbol)],
        {1: [(0, 2, R_PPC_REL24, 0)]},
    )


CALLER_INVENTORY = {
    0x80003120: ("fn_80003120", 8),
    0x80003200: ("fn_80003200", 4),
    0x80003300: ("fn_80003300", 4),
}


# --------------------------------------------------------------------------
# calls
# --------------------------------------------------------------------------


def test_a_call_to_the_right_function_matches(tmp_path, capsys):
    dol = executable(tmp_path, struct.pack(">II", bl(CODE, 0x80003200), BLR))
    status, out = run(tmp_path, one_caller("fn_80003200"), dol, CALLER_INVENTORY, capsys)
    assert "MATCH  2/2 words" in out
    assert status == M.EXIT_OK


def test_a_call_to_the_wrong_function_differs(tmp_path, capsys):
    """The headline: identical opcodes, identical everything the compiler
    chose, and a branch that lands somewhere else entirely."""
    dol = executable(tmp_path, struct.pack(">II", bl(CODE, 0x80003200), BLR))
    status, out = run(tmp_path, one_caller("fn_80003300"), dol, CALLER_INVENTORY, capsys)
    assert "differs" in out and "at +0" in out
    assert status == M.EXIT_DIFFERS


def test_a_call_nothing_can_place_is_not_a_match(tmp_path, capsys):
    """An SDK function no config here names: the word is honestly undecided,
    and undecided is not MATCH -- it is one word short of a comparison and the
    exit status says so."""
    dol = executable(tmp_path, struct.pack(">II", bl(CODE, 0x80003200), BLR))
    status, out = run(tmp_path, one_caller("OSSomethingUnnamed"), dol, CALLER_INVENTORY, capsys)
    assert "1/2 words, 1 need a link" in out
    assert "only a link can decide" in out
    assert status == M.EXIT_UNVERIFIED


# --------------------------------------------------------------------------
# address materialisation
# --------------------------------------------------------------------------


def materialiser(register: int):
    """``lis rD, sym@ha; addi rD, rD, sym@l; blr`` against fn_80003200."""
    text = struct.pack(
        ">III",
        lis(register, 0),
        (14 << 26) | (register << 21) | (register << 16),
        BLR,
    )
    return build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [sym("fn_80003120", 0, 12, STT_FUNC, STB_GLOBAL, 1), sym("fn_80003200")],
        {1: [(2, 2, R_PPC_ADDR16_HA, 0), (6, 2, R_PPC_ADDR16_LO, 0)]},
    )


def linked_materialiser(register: int, address: int) -> bytes:
    return struct.pack(
        ">III",
        lis(register, (address >> 16) + ((address >> 15) & 1)),
        (14 << 26) | (register << 21) | (register << 16) | (address & 0xFFFF),
        BLR,
    )


MATERIALISER_INVENTORY = {0x80003120: ("fn_80003120", 12), 0x80003200: ("fn_80003200", 4)}


def test_an_address_in_the_right_register_matches(tmp_path, capsys):
    dol = executable(tmp_path, linked_materialiser(4, 0x80003200))
    status, out = run(tmp_path, materialiser(4), dol, MATERIALISER_INVENTORY, capsys)
    assert "MATCH  3/3 words" in out
    assert status == M.EXIT_OK


def test_an_address_in_the_wrong_register_differs(tmp_path, capsys):
    """A register-allocation error inside an address materialisation: the
    opcodes are identical, only rD moved, and rD is outside the field the
    linker fills."""
    dol = executable(tmp_path, linked_materialiser(3, 0x80003200))
    status, out = run(tmp_path, materialiser(4), dol, MATERIALISER_INVENTORY, capsys)
    assert "differs" in out and "at +0, +4" in out
    assert status == M.EXIT_DIFFERS


def test_an_address_of_the_wrong_thing_differs(tmp_path, capsys):
    """Right register, right opcodes, and the halves point somewhere else."""
    dol = executable(tmp_path, linked_materialiser(4, 0x80004400))
    status, out = run(tmp_path, materialiser(4), dol, MATERIALISER_INVENTORY, capsys)
    assert "differs" in out
    assert status == M.EXIT_DIFFERS


# --------------------------------------------------------------------------
# small data
# --------------------------------------------------------------------------


def test_the_small_data_bases_come_out_of_the_executable(tmp_path):
    """Not a constant here: the entry point's register-init stub is where the
    two bases are, so an SDA21 field can be read back as an address."""
    dol = M.D.parse(executable(tmp_path, struct.pack(">I", BLR)).read_bytes())
    assert M.sda_bases(dol) == {2: SDA2, 13: SDA}


def sda_reader(register: int):
    text = struct.pack(">II", (32 << 26) | (register << 21), BLR)
    return build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [sym("fn_80003120", 0, 8, STT_FUNC, STB_GLOBAL, 1), sym("someGlobal")],
        {1: [(2, 2, R_PPC_EMB_SDA21, 0)]},
    )


def test_an_sda_load_still_holds_its_destination_register(tmp_path, capsys):
    """The linker fills rA and the displacement of an SDA21, and nothing else.
    rD is the compiler's, so a different rD differs even though the target is
    a global nothing here can place."""
    dol = executable(tmp_path, struct.pack(">II", sda_load(3, SDA - 0x40), BLR))
    status, out = run(tmp_path, sda_reader(4), dol, {0x80003120: ("fn_80003120", 8)}, capsys)
    assert "differs" in out
    assert status == M.EXIT_DIFFERS

    status, out = run(tmp_path, sda_reader(3), dol, {0x80003120: ("fn_80003120", 8)}, capsys)
    assert "MATCH  1/2 words, 1 need a link" in out
    assert status == M.EXIT_UNVERIFIED


def test_two_references_to_one_global_must_agree(tmp_path, capsys):
    """Neither word can be checked against an address, but they can be checked
    against each other: one symbol is in one place."""
    text = struct.pack(">IIII", 32 << 26 | (3 << 21), BLR, 32 << 26 | (3 << 21), BLR)
    obj = build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [
            sym("fn_80003120", 0, 8, STT_FUNC, STB_GLOBAL, 1),
            sym("fn_80003128", 8, 8, STT_FUNC, STB_GLOBAL, 1),
            sym("someGlobal"),
        ],
        {1: [(2, 3, R_PPC_EMB_SDA21, 0), (10, 3, R_PPC_EMB_SDA21, 0)]},
    )
    dol = executable(
        tmp_path,
        struct.pack(">IIII", sda_load(3, SDA - 0x40), BLR, sda_load(3, SDA - 0x80), BLR),
    )
    status, out = run(
        tmp_path,
        obj,
        dol,
        {0x80003120: ("fn_80003120", 8), 0x80003128: ("fn_80003128", 8)},
        capsys,
    )
    assert "layout: someGlobal is" in out
    assert status == M.EXIT_DIFFERS


def test_a_materialised_address_must_agree_with_the_rest_of_the_unit(tmp_path, capsys):
    """An @ha/@l pair to a global nothing here can place is still not free:
    another function's SDA21 field already said where that global is, and one
    symbol is in one place."""
    text = struct.pack(
        ">IIIII", 32 << 26 | (3 << 21), BLR, lis(4, 0), (14 << 26) | (4 << 21) | (4 << 16), BLR
    )
    obj = build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [
            sym("fn_80003120", 0, 8, STT_FUNC, STB_GLOBAL, 1),
            sym("fn_80003128", 8, 12, STT_FUNC, STB_GLOBAL, 1),
            sym("someGlobal"),
        ],
        {1: [(2, 3, R_PPC_EMB_SDA21, 0), (10, 3, R_PPC_ADDR16_HA, 0), (14, 3, R_PPC_ADDR16_LO, 0)]},
    )
    inventory = {0x80003120: ("fn_80003120", 8), 0x80003128: ("fn_80003128", 12)}
    here = SDA - 0x40

    dol = executable(
        tmp_path,
        struct.pack(">II", sda_load(3, here), BLR) + linked_materialiser(4, here),
    )
    status, out = run(tmp_path, obj, dol, inventory, capsys)
    assert "differs" not in out
    assert status == M.EXIT_UNVERIFIED

    dol = executable(
        tmp_path,
        struct.pack(">II", sda_load(3, here), BLR) + linked_materialiser(4, here + 0x2000),
    )
    status, out = run(tmp_path, obj, dol, inventory, capsys)
    differing = [line for line in out.splitlines() if "differs" in line]
    assert len(differing) == 1 and differing[0].startswith("fn_80003128")
    assert status == M.EXIT_DIFFERS


# --------------------------------------------------------------------------
# data, and the constant at the end of a pointer
# --------------------------------------------------------------------------

OURS = b"<< SDK  release build: Nov 10 2003 >>\0"
THEIRS = b"<< SDK  release build: Sep  5 2002 >>\0"
PTR_AT, BANNER_AT = DATA + 0x100, DATA


def banner_unit(text_bytes: bytes):
    """The shape of ar.c: a pointer in .sdata to a string in .data, and a
    function that loads the pointer through r13."""
    return build_elf(
        [
            (".text", text_bytes, SHF_ALLOC | SHF_EXECINSTR),
            (".sdata", b"\0\0\0\0", SHF_ALLOC | SHF_WRITE),
            (".data", OURS, SHF_ALLOC | SHF_WRITE),
        ],
        [
            sym("fn_80003120", 0, 8, STT_FUNC, STB_GLOBAL, 1),
            sym("__SDKVersion", 0, 4, STT_OBJECT, STB_GLOBAL, 2),
            sym("@1", 0, len(OURS), STT_OBJECT, STB_LOCAL, 3),
        ],
        {
            1: [(2, 2, R_PPC_EMB_SDA21, 0)],
            2: [(0, 3, R_PPC_ADDR32, 0)],
        },
    )


def banner_executable(tmp_path, banner: bytes) -> Path:
    data = bytearray(0x104)
    data[0 : len(banner)] = banner
    struct.pack_into(">I", data, 0x100, BANNER_AT)
    return executable(tmp_path, struct.pack(">II", sda_load(3, PTR_AT), BLR), bytes(data))


def test_a_constant_at_the_end_of_a_pointer_is_compared(tmp_path, capsys):
    """Nothing here knows where __SDKVersion lives, but the code's own SDA21
    field says, and the executable's pointer there says where the string is.
    That is enough to compare a constant that never appears in any relocation
    of its own -- the SDK banner case."""
    dol = banner_executable(tmp_path, THEIRS)
    status, out = run(
        tmp_path,
        banner_unit(struct.pack(">II", 32 << 26 | (3 << 21), BLR)),
        dol,
        {0x80003120: ("fn_80003120", 8)},
        capsys,
    )
    assert "__SDKVersion" in out and "via fn_80003120" in out
    assert "@1" in out and "differs" in out and "via __SDKVersion" in out
    assert status == M.EXIT_DIFFERS


def test_the_same_constant_matches(tmp_path, capsys):
    dol = banner_executable(tmp_path, OURS)
    status, out = run(
        tmp_path,
        banner_unit(struct.pack(">II", 32 << 26 | (3 << 21), BLR)),
        dol,
        {0x80003120: ("fn_80003120", 8)},
        capsys,
    )
    assert "@1" in out and "MATCH" in out
    assert "differs" not in out
    assert status == M.EXIT_UNVERIFIED  # the pointer word itself still needs a link


# --------------------------------------------------------------------------
# what was never compared at all
# --------------------------------------------------------------------------


def test_bytes_no_symbol_covers_are_reported(tmp_path, capsys):
    """A section is only as checked as the symbols over it."""
    text = struct.pack(">III", BLR, BLR, BLR)
    obj = build_elf(
        [(".text", text, SHF_ALLOC | SHF_EXECINSTR)],
        [sym("fn_80003120", 0, 4, STT_FUNC, STB_GLOBAL, 1)],
    )
    dol = executable(tmp_path, text)
    status, out = run(tmp_path, obj, dol, {0x80003120: ("fn_80003120", 4)}, capsys)
    assert ".text: 8 byte(s) no symbol covers" in out
    assert status == M.EXIT_UNVERIFIED


def test_a_data_symbol_nothing_places_is_said_so(tmp_path, capsys):
    obj = build_elf(
        [
            (".text", struct.pack(">I", BLR), SHF_ALLOC | SHF_EXECINSTR),
            (".data", b"\1\2\3\4", SHF_ALLOC | SHF_WRITE),
        ],
        [
            sym("fn_80003120", 0, 4, STT_FUNC, STB_GLOBAL, 1),
            sym("aTable", 0, 4, STT_OBJECT, STB_GLOBAL, 2),
        ],
    )
    dol = executable(tmp_path, struct.pack(">I", BLR), b"\1\2\3\4")
    status, out = run(tmp_path, obj, dol, {0x80003120: ("fn_80003120", 4)}, capsys)
    assert "aTable" in out and "nothing in the unit places it" in out
    assert status == M.EXIT_UNVERIFIED
