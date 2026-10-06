"""A game library checked as a file (specs/android.md 3.3, L12b): the Python
twin of runtime/elfcheck.c, so the PC that built a library can say, before it
goes to a phone, what the phone's runtime would say of it, in the same words.

    from soa import elfcheck
    elfcheck.problems(elfcheck.read(path), machine=183, exports=..., libc=..., record=...)
    elfcheck.verdict(path, machine=183, ..., dol=..., android=True, name="picked.so")

read() parses a 64-bit little-endian ELF shared object's headers: its machine
and type, every PT_LOAD's alignment, DT_NEEDED, DT_SONAME and text
relocations, the record in .note.soa, and its dynamic symbols; as far as they
can be read, saying where reading stopped (Elf.damage), since elfcheck.c
refuses a damaged file only after the machine, the class and the type. A file
that is no ELF at all is NotElf, in elfcheck.c's words, a Windows file named
as one. problems() lists what elfcheck.c would refuse, first refusal first,
and, stricter than the phone (which needs only its own table), any export but
soa_game; verdict() is the phone's one answer, word for word.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from soa import seam

MACHINES = {3: "32-bit x86", 40: "32-bit ARM", 62: "x86-64", 183: "64-bit ARM (AArch64)"}
EM_ARM, EM_AARCH64, EM_X86_64 = 40, 183, 62
# A Windows file's machine, from its COFF header, as the ELF number MACHINES
# knows it by: x86, ARM (and its Thumb and Windows RT forms), x86-64, ARM64.
PE_MACHINES = {0x14C: 3, 0x1C0: 40, 0x1C2: 40, 0x1C4: 40, 0x8664: 62, 0xAA64: 183}
PE_DLL = 0x2000  # IMAGE_FILE_DLL
MIN_ALIGN = 16384
PT_LOAD, SHT_DYNAMIC, SHT_DYNSYM = 1, 6, 11
DT_NEEDED, DT_SONAME, DT_TEXTREL, DT_FLAGS, DF_TEXTREL = 1, 14, 22, 30, 4
STB_WEAK = 2
C_LIBRARIES = ("libc.so", "libm.so", "libdl.so")
READ_CAP = 64 << 20  # elfcheck.c's read_at reads no section larger
# elfcheck.c's buffers: the record's first 511 bytes are read, and of each of
# its values the first 127, so a longer record is judged by that much alone
RECORD_CAP, FIELD_CAP = 511, 127
PC_ONLY = "its functions are not hidden"  # the one refusal the phone never makes


class NotElf(ValueError):
    """A file that is no ELF at all; its message is elfcheck.c's refusal."""


@dataclass
class Elf:
    machine: int
    type: int
    load_aligns: list[int] = field(default_factory=list)
    needed: list[str] = field(default_factory=list)
    soname: str = ""
    textrel: bool = False
    record: str | None = None  # as elfcheck.c reads it: its first RECORD_CAP bytes, printable
    imports: list[tuple[str, bool]] = field(default_factory=list)  # (name, weak)
    exports: list[str] = field(default_factory=list)
    wide: bool = True  # 64-bit and little-endian; nothing more is read otherwise
    # where reading stopped: "headers" (before the program headers were read),
    # "names" (the section-name table), "symbols" (the dynamic symbols)
    damage: str = ""


def _cstr(blob: bytes, at: int) -> str:
    end = blob.find(b"\0", at)
    return blob[at : end if end >= 0 else len(blob)].decode("utf-8", "replace")


def _at(data: bytes, off: int, n: int) -> bytes | None:
    """`n` bytes at `off`, or None when they are not all in the file: read_at."""
    if off > len(data) or n > len(data) - off or n > READ_CAP:
        return None
    return data[off : off + n]


def _note_record(blob: bytes) -> str | None:
    at = 0
    while at + 12 <= len(blob):
        namesz, descsz, _ = struct.unpack_from("<III", blob, at)
        name = at + 12
        desc = name + ((namesz + 3) & ~3)
        if desc + descsz > len(blob):
            return None
        if namesz == 4 and blob[name : name + 4] == b"SOA\0":
            raw = blob[desc : desc + descsz].split(b"\0", 1)[0][:RECORD_CAP]
            # printable, as elfcheck.c's note_record makes it: the words quote it
            return bytes(c if 0x20 <= c <= 0x7E else 0x3F for c in raw).decode("ascii")
        at = desc + ((descsz + 3) & ~3)
    return None


def _not_elf(data: bytes, shown: str) -> str:
    """elfcheck.c's words for a file with no ELF magic: a Windows file ("MZ",
    then "PE\\0\\0" where e_lfanew says) by its kind and machine."""
    if data[:2] == b"MZ" and len(data) >= 64:
        pe = _at(data, struct.unpack_from("<I", data, 60)[0], 24)
        if pe is not None and pe[:4] == b"PE\0\0":
            machine, chars = struct.unpack_from("<H", pe, 4)[0], struct.unpack_from("<H", pe, 22)[0]
            kind = "library" if chars & PE_DLL else "program"
            name = MACHINES.get(PE_MACHINES.get(machine, 0), "another machine")
            return (
                f"{shown} is a Windows {kind} for {name}, not a game library for this device: "
                "pick the libsoa_game.so that Setup makes for this device"
            )
    return f"{shown} is not a library for this system"


def read(path: Path, name: str | None = None) -> Elf:
    """The headers of an ELF shared object, as far as elfcheck.c would read
    them; NotElf when it is no ELF at all. `name` stands for the path in
    NotElf's words, as a picked file is shown by its own name."""
    shown = str(path) if name is None else name
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise NotElf(_not_elf(data, shown))
    # the machine in the file's own byte order, before the class is known
    machine = struct.unpack_from(">H" if data[5] == 2 else "<H", data, 18)[0]
    elf = Elf(machine=machine, type=struct.unpack_from("<H", data, 16)[0])
    if data[4] != 2 or data[5] != 1:
        elf.wide = False
        return elf
    phoff, shoff = struct.unpack_from("<QQ", data, 32)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from("<HHHHH", data, 54)
    ph = _at(data, phoff, phnum * 56)
    sh = _at(data, shoff, shnum * 64)
    if phentsize != 56 or shentsize != 64 or ph is None or sh is None or shstrndx >= shnum:
        elf.damage = "headers"
        return elf
    for i in range(phnum):
        if struct.unpack_from("<I", ph, i * 56)[0] == PT_LOAD:
            elf.load_aligns.append(struct.unpack_from("<Q", ph, i * 56 + 48)[0])
    sections = []
    for i in range(shnum):
        sname, kind = struct.unpack_from("<II", sh, i * 64)
        off, size = struct.unpack_from("<QQ", sh, i * 64 + 24)
        link = struct.unpack_from("<I", sh, i * 64 + 40)[0]
        sections.append((sname, kind, off, size, link))
    _, _, stroff, strsize, _ = sections[shstrndx]
    shstr = _at(data, stroff, strsize)
    if not shstr or shstr[-1] != 0:  # elfcheck.c reads names only from a table ending in NUL
        elf.damage = "names"
        return elf
    dynamic = dynsym = dynstr = note = None
    for sname, kind, off, size, link in sections:  # the first of each, as elfcheck.c takes
        if kind == SHT_DYNAMIC and dynamic is None:
            dynamic = _at(data, off, size)
        elif kind == SHT_DYNSYM and dynsym is None:
            dynsym = _at(data, off, size)
            if dynsym is not None and link < shnum:
                dynstr = _at(data, sections[link][2], sections[link][3])
        elif note is None and sname < len(shstr) and _cstr(shstr, sname) == ".note.soa":
            note = _at(data, off, size)
    if dynamic is None or dynsym is None or not dynstr or dynstr[-1] != 0:
        elf.damage = "symbols"
        return elf
    if note is not None:
        elf.record = _note_record(note)
    for at in range(0, len(dynamic) - 15, 16):
        tag, val = struct.unpack_from("<qQ", dynamic, at)
        if tag == 0:
            break
        if tag == DT_NEEDED:
            elf.needed.append(_cstr(dynstr, val))
        elif tag == DT_SONAME:
            elf.soname = _cstr(dynstr, val)
        elif tag == DT_TEXTREL or (tag == DT_FLAGS and val & DF_TEXTREL):
            elf.textrel = True
    for at in range(0, len(dynsym) - 23, 24):
        st_name, st_info, _, st_shndx = struct.unpack_from("<IBBH", dynsym, at)
        sym = _cstr(dynstr, st_name)
        if not sym:
            continue
        if st_shndx == 0:
            elf.imports.append((sym, (st_info >> 4) == STB_WEAK))
        else:
            elf.exports.append(sym)
    return elf


def _c_library(name: str) -> int:
    """2 for libc.so, libm.so or libdl.so by its bare name (bionic's), 1 with a
    version after it (glibc's libc.so.6), 0 for neither."""
    for lib in C_LIBRARIES:
        if name == lib:
            return 2
        if name.startswith(lib + "."):
            return 1
    return 0


def _field(rec: str, key: str) -> str:
    """key's value, as elfcheck.c's elf_record_field reads it: the fields
    apart by spaces alone, the first with an "=" after the key, its value cut
    at FIELD_CAP; "" for none."""
    for part in rec.split(" "):
        k, eq, v = part.partition("=")
        if k == key and eq:
            return v[:FIELD_CAP]
    return ""


def problems(
    elf: Elf,
    *,
    machine: int,
    exports: set[str] | list[str],
    libc: set[str] | tuple[str, ...],
    record: str,
    dol: str | None = None,
    android: bool = False,
    path: str = "this library",
) -> list[str]:
    """What runtime/elfcheck.c would refuse, in its words, first refusal
    first; and then, for the PC's own check, any export but soa_game.
    `dol` is the executable the runtime plays (None holds the record's dol=
    to nothing, as a NULL ElfWant.dol does); `android` takes the C libraries
    only by bionic's names, as an Android runtime does."""
    if elf.machine != machine:
        return [
            f"this library was built for {MACHINES.get(elf.machine, 'another machine')}, not this device "
            f"({MACHINES.get(machine, 'another machine')}): rebuild it for this device with Setup"
        ]
    if not elf.wide:
        return [f"{path} is not a 64-bit library for this system"]
    if elf.type != 3:
        return [f"{path} is a program, not a game library"]
    damaged = f"{path} is damaged: its headers are not where it says"
    if elf.damage == "headers":
        return [damaged]
    out: list[str] = []
    for a in elf.load_aligns:
        if a < MIN_ALIGN:
            out.append(
                f"this library was built for {a}-byte pages, and devices may use 16 KB ones: rebuild it with "
                "this package's Setup"
            )
            break
    if elf.damage == "names":
        return [*out, damaged]
    if elf.damage == "symbols":
        return [*out, f"{path} has no dynamic symbols: it is not a library this package built"]
    if elf.textrel:
        out.append(
            "this library has text relocations, which Android refuses to load: rebuild it with this package"
        )
    for name in elf.needed:
        if name == seam.RUNTIME_SONAME:
            continue
        kind = _c_library(name)
        if android and kind == 1:
            out.append(
                f"this library was built for Linux (it needs {name}), not Android: rebuild it for this "
                "device with Setup"
            )
        elif not kind:
            out.append(
                f"this library needs {name}, which this app does not have: rebuild it with this package"
            )
    if seam.RUNTIME_SONAME not in elf.needed:
        out.append(
            f"this library was not built against this app's runtime (it does not need {seam.RUNTIME_SONAME}): "
            "rebuild it with this package"
        )
    if elf.record is None:
        out.append("this library carries no build record: it was not made by this package's Setup")
    else:
        for key in ("abi", "mode", "baked"):
            theirs, mine = _field(elf.record, key), _field(record, key)
            if theirs != mine:
                # baked as "build", twelve digits of it: elfcheck.c's words
                label, n = ("build", 12) if key == "baked" else (key, None)
                out.append(
                    f"this game library and this app come from different releases (its {label} is "
                    f"{theirs[:n] if theirs else 'missing'}, the app's {mine[:n]}): install the app and "
                    "run Setup from the same release"
                )
                break
        theirs = _field(elf.record, "dol")
        if dol and not theirs:
            out.append(
                "this game library does not say which disc's executable it was made from (this app plays "
                f"{dol[:12]}): rebuild it with Setup from your own disc"
            )
        elif dol and theirs != dol:
            out.append(
                f"this game library was made from another disc's executable ({theirs[:12]}, this app plays "
                f"{dol[:12]}): rebuild it with Setup from your own disc"
            )
    allowed = set(exports) | set(libc)
    for name, weak in elf.imports:
        if not weak and name not in allowed:
            out.append(
                f"this library needs {name}, which this app's runtime does not have: rebuild it with this "
                "package's Setup"
            )
    if "soa_game" not in elf.exports:
        out.append(f"{path} has no soa_game table: it is not a game library")
    extra = sorted(set(elf.exports) - {"soa_game", "_init", "_fini"})
    if extra:
        out.append(f"{path} exports {', '.join(extra[:5])} beside soa_game: {PC_ONLY}")
    return out


def verdict(
    path: Path,
    *,
    machine: int,
    exports: set[str] | list[str],
    libc: set[str] | tuple[str, ...],
    record: str,
    dol: str | None = None,
    android: bool = False,
    name: str | None = None,
) -> str:
    """What runtime/elfcheck.c says of the file at `path`, word for word: its
    first refusal, or "ok". `name` stands for the path in the words, as the
    phone shows a picked file by its display name."""
    shown = str(path) if name is None else name
    try:
        elf = read(path, shown)
    except NotElf as exc:
        return str(exc)
    except OSError:
        return f"cannot open {shown}"
    found = [
        p
        for p in problems(
            elf,
            machine=machine,
            exports=exports,
            libc=libc,
            record=record,
            dol=dol,
            android=android,
            path=shown,
        )
        if not p.endswith(PC_ONLY)
    ]
    return found[0] if found else "ok"
