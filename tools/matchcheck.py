"""Does a compiled object match the executable, function by function?

    python tools/matchcheck.py build/src/string.o [--dol extracted/sys/main.dol]

Reads the object's symbol table, finds each symbol's address (from the symbol's
own ``fn_XXXXXXXX`` name, else by name in config/functions.tsv or
config/names.txt), and compares its bytes against the executable's.

A word that carries a relocation is not a free pass. The linker fills in only
the field the relocation names; every other bit is the compiler's, and the
field itself has a right answer whenever the relocation's symbol has an address
this project knows. So each such word is one of three things:

  verified    the bits outside the field are identical and the field in the
              executable points where the relocation says it should;
  differs     one of those is wrong -- a call to the wrong function, or a
              register allocated differently in an address materialisation,
              both of which used to report MATCH;
  unverified  the bits outside the field are identical, but nothing here knows
              the target's address, so only a link could decide. Never counted
              as a match.

Data objects are compared too, not just STT_FUNC. A unit's own globals have no
address until something places them, so their addresses are recovered from the
fields the executable already has, which is how ``__ARVersion`` leads to the
SDK banner it points at and the banner gets compared like anything else. Two
references to one symbol must agree, and two symbols in one input section must
keep their distance, since the linker places an input section as one run.

Exit status: 0 when everything was compared and everything verified, 1 when
anything differs or a symbol makes a claim about the executable that is wrong,
3 when nothing differs but something was left undecided -- a word only a link
can settle, a symbol nothing placed, or bytes no symbol covers. Analysis only:
the executable is read, never written.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soa import dol as D  # noqa: E402
from soa import symbols as S  # noqa: E402

EXIT_OK, EXIT_DIFFERS, EXIT_UNVERIFIED = 0, 1, 3

SHT_PROGBITS, SHT_SYMTAB, SHT_RELA = 1, 2, 4
SHF_ALLOC, SHF_EXECINSTR = 0x2, 0x4
STT_OBJECT, STT_FUNC = 1, 2
STB_LOCAL = 0
SHN_UNDEF, SHN_LORESERVE = 0, 0xFF00


def read_elf(data: bytes):
    """Sections, symbols and relocations of a big-endian ELF32 relocatable.

    Relocations come back keyed by the *word* they patch -- a 16-bit field sits
    at the odd halfword, and mwcc records an SDA21 there too -- as
    ``{section: {word_offset: (type, symbol_index, addend)}}``.
    """
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 2:
        raise ValueError("not a big-endian ELF32 object")
    shoff, shentsize, shnum, shstrndx = (
        struct.unpack(">I", data[0x20:0x24])[0],
        *struct.unpack(">HHH", data[0x2E:0x34]),
    )
    sections = []
    for i in range(shnum):
        o = shoff + i * shentsize
        name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack(
            ">IIIIIIIIII", data[o : o + 40]
        )
        sections.append(
            {
                "name": name,
                "type": typ,
                "flags": flags,
                "off": off,
                "size": size,
                "link": link,
                "info": info,
                "entsize": entsize,
            }
        )
    strtab = sections[shstrndx]
    for s in sections:
        s["name"] = data[strtab["off"] + s["name"] :].split(b"\0", 1)[0].decode()
    symbols = []
    relocs: dict[int, dict[int, tuple[int, int, int]]] = {}
    for s in sections:
        if s["type"] == SHT_SYMTAB:
            st = sections[s["link"]]
            for j in range(s["size"] // 16):
                o = s["off"] + j * 16
                n, value, size, info, other, shndx = struct.unpack(">IIIBBH", data[o : o + 16])
                nm = data[st["off"] + n :].split(b"\0", 1)[0].decode()
                symbols.append(
                    {
                        "name": nm,
                        "value": value,
                        "size": size,
                        "type": info & 0xF,
                        "bind": info >> 4,
                        "shndx": shndx,
                    }
                )
        elif s["type"] == SHT_RELA:
            table = relocs.setdefault(s["info"], {})
            for j in range(s["size"] // 12):
                o = s["off"] + j * 12
                r_off, r_info, addend = struct.unpack(">IIi", data[o : o + 12])
                table[r_off & ~3] = (r_info & 0xFF, r_info >> 8, addend)
    return sections, symbols, relocs


# --------------------------------------------------------------------------
# which executable symbol does an object symbol stand for
# --------------------------------------------------------------------------

_FN_ADDRESS = re.compile(r"fn_([0-9A-Fa-f]{8})\Z")


def name_index(inventory: dict[int, dict], names: dict[int, tuple[str, str]] | None = None) -> dict:
    """``name -> address``, from the inventory and from config/names.txt.

    names.txt runs ahead of the inventory -- it is where a recovered name is
    written first -- so a source that already spells a function the recovered
    way resolves before the next regeneration, not after it. A name two
    addresses claim resolves to neither: an ambiguous answer here would score
    a function against someone else's bytes.
    """
    index: dict[str, int | None] = {}
    for source in (
        {addr: row["name"] for addr, row in inventory.items()},
        {addr: name for addr, (name, _) in (names or {}).items()},
    ):
        for addr, name in source.items():
            if index.setdefault(name, addr) != addr:
                index[name] = None
    return {name: addr for name, addr in index.items() if addr is not None}


def object_index(symbols: list[S.Symbol]) -> dict[str, int]:
    """``name -> address`` for the non-function symbols of a dtk symbol file.

    Data is what a relocation points at half the time, and the function
    inventory has nothing to say about it. Placeholder names carry no claim,
    and a name two addresses share resolves to neither, for the same reason as
    above.
    """
    index: dict[str, int | None] = {}
    for sym in symbols:
        if sym.kind == "function" or sym.is_placeholder:
            continue
        if index.setdefault(sym.name, sym.address) != sym.address:
            index[sym.name] = None
    return {name: addr for name, addr in index.items() if addr is not None}


def resolve_address(symbol: str, inventory: dict[int, dict], index: dict[str, int]) -> int | None:
    """Which executable function does an object's symbol stand for?

    The address wins when the symbol carries one, because a unit that names a
    function after its address means that address whatever config calls it
    today -- config/functions.tsv is regenerated from the binary on its own
    schedule, and a rename there must not unmatch a source nobody touched.
    """
    m = _FN_ADDRESS.match(symbol)
    if m:
        address = int(m.group(1), 16)
        return address if address in inventory else None
    return index.get(symbol)


def unresolved_reason(symbol: str, bind: int) -> tuple[str, bool]:
    """Why a symbol has no executable counterpart, and whether that is an error.

    A symbol spelled after an address is a claim about the executable, so no
    function starting there is a wrong claim whatever the symbol's binding says
    -- not a helper to pass over. A local the compiler inlined at every call
    site really does have no counterpart, and is the one case that is skipped;
    anything else global is a name the inventory has never heard of.
    """
    if _FN_ADDRESS.match(symbol):
        return "names an address where no function starts", True
    if bind == STB_LOCAL:
        return "static helper, inlined (no executable counterpart)", False
    return "not in the inventory", True


# --------------------------------------------------------------------------
# relocations: what the linker fills in, and what it should fill in with
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Kind:
    """One PowerPC relocation type: its name, the bits it leaves alone, and
    how to read back what the linker wrote into the bits it does not."""

    name: str
    fixed: int  # mask of the bits the linker never touches
    field: str


RELOC_KINDS = {
    1: Kind("ADDR32", 0x00000000, "abs32"),
    2: Kind("ADDR24", 0xFC000003, "abs24"),
    3: Kind("ADDR16", 0xFFFF0000, "lo"),
    4: Kind("ADDR16_LO", 0xFFFF0000, "lo"),
    5: Kind("ADDR16_HI", 0xFFFF0000, "hi"),
    6: Kind("ADDR16_HA", 0xFFFF0000, "ha"),
    7: Kind("ADDR14", 0xFFFF0003, "abs14"),
    8: Kind("ADDR14_BRTAKEN", 0xFFFF0003, "abs14"),
    9: Kind("ADDR14_BRNTAKEN", 0xFFFF0003, "abs14"),
    10: Kind("REL24", 0xFC000003, "rel24"),
    11: Kind("REL14", 0xFFFF0003, "rel14"),
    12: Kind("REL14_BRTAKEN", 0xFFFF0003, "rel14"),
    13: Kind("REL14_BRNTAKEN", 0xFFFF0003, "rel14"),
    32: Kind("SDAREL16", 0xFFFF0000, "sdarel"),
    109: Kind("EMB_SDA21", 0xFFE00000, "sda21"),
    116: Kind("EMB_RELSDA", 0xFFFF0000, "sdarel"),
}

# A type nothing here models: the opcode is still the compiler's, so hold it to
# that much and call the rest undecided rather than guessing at the field.
UNKNOWN_KIND = Kind("?", 0xFC000000, "unknown")


def kind_of(reloc_type: int) -> Kind:
    return RELOC_KINDS.get(reloc_type, UNKNOWN_KIND)


def _sext(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def filled_target(kind: Kind, word: int, at: int, sda: dict[int, int]) -> int | None:
    """The address the linker's field points at, or None when the field alone
    cannot say -- ``@ha`` and ``@l`` are each half an address."""
    if kind.field == "abs32":
        return word
    if kind.field == "abs24":
        return _sext(word & 0x03FFFFFC, 26) & 0xFFFFFFFF
    if kind.field == "abs14":
        return _sext(word & 0xFFFC, 16) & 0xFFFFFFFF
    if kind.field == "rel24":
        delta = _sext(word & 0x03FFFFFC, 26)
        return (delta if word & 2 else at + delta) & 0xFFFFFFFF
    if kind.field == "rel14":
        delta = _sext(word & 0xFFFC, 16)
        return (delta if word & 2 else at + delta) & 0xFFFFFFFF
    if kind.field in ("sda21", "sdarel"):
        base = sda.get((word >> 16) & 31)
        return None if base is None else (base + _sext(word & 0xFFFF, 16)) & 0xFFFFFFFF
    return None


def target_agrees(
    kind: Kind, word: int, at: int, expected: int, sda: dict[int, int]
) -> bool | None:
    """Does the executable's field point at ``expected``? None if undecidable.

    ``@l`` on its own pins sixteen bits of the answer and no more; its ``@ha``
    partner carries the other sixteen, and mwcc always emits the pair.
    """
    got = filled_target(kind, word, at, sda)
    if got is not None:
        return got == expected & 0xFFFFFFFF
    if kind.field == "lo":
        return (word & 0xFFFF) == (expected & 0xFFFF)
    if kind.field == "hi":
        return (word & 0xFFFF) == ((expected >> 16) & 0xFFFF)
    if kind.field == "ha":
        return (word & 0xFFFF) == (((expected >> 16) + ((expected >> 15) & 1)) & 0xFFFF)
    return None


def sda_bases(dol, limit: int = 64) -> dict[int, int]:
    """``{2: sda2, 13: sda}`` as ``__init_registers`` sets them.

    The two small-data bases are the only way to read an SDA21 field back as an
    address, and they are in the executable rather than in a constant here: the
    entry point's first branch lands on the routine that loads them, as a
    ``lis``/``ori`` pair per register.
    """
    try:
        start = dol.entry_point
        word = dol.word(start)
        if word >> 26 == 18 and not word & 2:  # b/bl, relative
            start += _sext(word & 0x03FFFFFC, 26)
        out: dict[int, int] = {}
        pending: dict[int, int] = {}
        for i in range(limit):
            word = dol.word(start + 4 * i)
            if word == 0x4E800020:  # blr: past the end of the routine
                break
            op, rd, ra, imm = word >> 26, (word >> 21) & 31, (word >> 16) & 31, word & 0xFFFF
            if op == 15 and ra == 0 and rd in (2, 13):  # lis rD, imm
                pending[rd] = imm << 16
            elif op == 24 and rd in (2, 13) and ra == rd and rd in pending:  # ori rD, rD, imm
                out[rd] = pending.pop(rd) | imm
        return out
    except ValueError:  # an executable laid out some other way: say nothing
        return {}


# --------------------------------------------------------------------------
# the check itself
# --------------------------------------------------------------------------


def location(sym: dict, addend: int) -> tuple:
    """Where a relocation points, in the object's own terms.

    A symbol defined here is an offset into one of its sections, so two
    relocations that land on the same bytes share a location whatever they call
    it; an undefined one is only a name, and the name is the location.
    """
    if sym["shndx"] == SHN_UNDEF or sym["shndx"] >= SHN_LORESERVE:
        return ("name", sym["name"])
    return ("section", sym["shndx"], sym["value"] + addend)


@dataclass
class Unit:
    """One object being checked against the executable."""

    dol: object
    data: bytes
    sections: list
    symbols: list
    relocs: dict
    inventory: dict
    index: dict
    objects: dict
    sda: dict
    placed: dict = field(default_factory=dict)  # location -> address
    placed_by: dict = field(default_factory=dict)  # location -> the symbol that placed it
    bases: dict = field(default_factory=dict)  # section index -> address of its offset 0
    based_by: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)  # human-readable layout errors
    bad_words: set = field(default_factory=set)  # (section, offset) of the words that caused them

    # -- object geography ---------------------------------------------------

    def describe(self, loc: tuple) -> str:
        if loc[0] == "name":
            return loc[1]
        return f"{self.sections[loc[1]]['name']}+0x{loc[2]:X}"

    def bytes_of(self, shndx: int, off: int, size: int) -> bytes:
        s = self.sections[shndx]
        return self.data[s["off"] + off : s["off"] + off + size]

    def compared_sections(self) -> list[int]:
        """The sections that end up in the executable and have bytes to compare."""
        return [
            i
            for i, s in enumerate(self.sections)
            if s["type"] == SHT_PROGBITS and s["flags"] & SHF_ALLOC and s["size"]
        ]

    # -- placement ----------------------------------------------------------

    def place(self, loc: tuple, address: int, via: str, site: tuple) -> None:
        """Record where the executable puts an object location, and complain if
        it has already been put somewhere else."""
        known = self.placed.get(loc)
        if known is None:
            self.placed[loc] = address
            self.placed_by[loc] = via
        elif known != address:
            self.conflicts.append(
                f"{self.describe(loc)} is 0x{known:08X} via {self.placed_by[loc]} "
                f"but 0x{address:08X} via {via}"
            )
            self.bad_words.add(site)
            return
        if loc[0] != "section":
            return
        shndx = loc[1]
        if self.sections[shndx]["flags"] & SHF_EXECINSTR:
            # This project's units group functions by subject, not by the object
            # the original build compiled them in, so their .text is under no
            # obligation to be one run in the executable.
            return
        base = (address - loc[2]) & 0xFFFFFFFF
        seen = self.bases.get(shndx)
        if seen is None:
            self.bases[shndx] = base
            self.based_by[shndx] = via
        elif seen != base:
            self.conflicts.append(
                f"{self.sections[shndx]['name']} is not one run in the executable: "
                f"{self.based_by[shndx]} puts its start at 0x{seen:08X}, {via} at 0x{base:08X}"
            )
            self.bad_words.add(site)

    def address_of(self, loc: tuple) -> int | None:
        if loc in self.placed:
            return self.placed[loc]
        if loc[0] == "section" and loc[1] in self.bases:
            return (self.bases[loc[1]] + loc[2]) & 0xFFFFFFFF
        return None

    def expected_target(self, sym: dict, addend: int) -> int | None:
        """The address a relocation's target has in the executable, when this
        project knows it without looking at the executable's own field."""
        base = resolve_address(sym["name"], self.inventory, self.index)
        if base is None:
            base = self.objects.get(sym["name"])
        return None if base is None else (base + addend) & 0xFFFFFFFF

    def witnesses(self, shndx: int, off: int, size: int, address: int, via: str) -> None:
        """Read what the executable already filled in for one symbol's
        relocations, and let each field say where its target went."""
        table = self.relocs.get(shndx, {})
        for site in range(off, off + size, 4):
            entry = table.get(site)
            if entry is None:
                continue
            typ, symidx, addend = entry
            kind = kind_of(typ)
            try:
                word = self.dol.word(address + site - off)
            except ValueError:
                continue
            target = filled_target(kind, word, address + site - off, self.sda)
            if target is not None:
                self.place(location(self.symbols[symidx], addend), target, via, (shndx, site))

    # -- comparison ---------------------------------------------------------

    def compare(self, shndx: int, off: int, address: int, ours: bytes, theirs: bytes):
        """Word by word, with every relocated field held to what it should be.

        Returns ``(verified, unverified, differing_offsets)`` counted in words
        for code and in bytes for data, plus the relocated words nothing could
        decide.
        """
        table = self.relocs.get(shndx, {})
        code = bool(self.sections[shndx]["flags"] & SHF_EXECINSTR)
        step = 4 if code else 1
        verified = unverified = 0
        diffs: list[int] = []
        i = 0
        total = max(len(ours), len(theirs))
        while i < total:
            site = off + i
            entry = table.get(site) if site % 4 == 0 else None
            width = 4 if entry is not None or code else step
            a, b = ours[i : i + width], theirs[i : i + width]
            scored = 1 if code else width
            if len(a) < width or len(b) < width:
                diffs.append(i)
                i += width
                continue
            if entry is None:
                if a == b:
                    verified += scored
                else:
                    diffs.append(i)
                i += width
                continue
            typ, symidx, addend = entry
            kind = kind_of(typ)
            ours_word, theirs_word = struct.unpack(">I", a)[0], struct.unpack(">I", b)[0]
            target = location(self.symbols[symidx], addend)
            expected = self.expected_target(self.symbols[symidx], addend)
            # An address this project knows settles the word. One recovered
            # from the executable's own other references to the same symbol
            # settles nothing on its own -- but the word still has to agree
            # with it, because one symbol is in one place.
            independent = expected is not None
            if not independent:
                expected = self.address_of(target)
            decided = (
                None
                if expected is None
                else target_agrees(kind, theirs_word, address + i, expected, self.sda)
            )
            if (
                ours_word & kind.fixed != theirs_word & kind.fixed
                or (shndx, site) in self.bad_words
                or decided is False
            ):
                diffs.append(i)
            elif decided is True and independent:
                verified += scored
            else:
                unverified += scored
            i += width
        return verified, unverified, diffs

    def relocation_note(self, shndx: int, off: int, i: int) -> str:
        entry = self.relocs.get(shndx, {}).get(off + i)
        if entry is None:
            return ""
        typ, symidx, _ = entry
        return f"{kind_of(typ).name} -> {self.symbols[symidx]['name'] or '(anonymous)'}"


def defined(sym: dict, sections: list) -> bool:
    return (
        sym["shndx"] != SHN_UNDEF
        and sym["shndx"] < SHN_LORESERVE
        and sym["shndx"] < len(sections)
        and sym["size"] > 0
    )


def coverage_gaps(unit: Unit, covered: dict[int, list[tuple[int, int]]]) -> list[str]:
    """Bytes of a section that no symbol we compared accounts for.

    A section is only as checked as the symbols over it: anything between them
    was never looked at, and saying so is the difference between "all match"
    and "all the parts anyone named match".
    """
    out = []
    for shndx in unit.compared_sections():
        size = unit.sections[shndx]["size"]
        seen = bytearray(size)
        for start, length in covered.get(shndx, []):
            for k in range(start, min(start + length, size)):
                seen[k] = 1
        gap = size - sum(seen)
        if gap:
            out.append(f"{unit.sections[shndx]['name']}: {gap} byte(s) no symbol covers")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("object", type=Path)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--functions", type=Path, default=Path("config/functions.tsv"))
    ap.add_argument("--names", type=Path, default=Path("config/names.txt"))
    ap.add_argument(
        "--dtk-symbols",
        type=Path,
        default=Path("config/GEAE8P/symbols.txt"),
        help="dtk symbol file to take data addresses from",
    )
    ap.add_argument(
        "--show",
        type=int,
        default=0,
        metavar="N",
        help="list the first N differing instructions side by side",
    )
    args = ap.parse_args(argv)

    dol = D.parse(args.dol.read_bytes())
    inventory = S.load_tsv(args.functions)
    index = name_index(inventory, S.load_names(args.names))
    objects = object_index(S.load_dtk(args.dtk_symbols)) if args.dtk_symbols.exists() else {}
    data = args.object.read_bytes()
    sections, symbols, relocs = read_elf(data)
    unit = Unit(dol, data, sections, symbols, relocs, inventory, index, objects, sda_bases(dol))

    failures = unverified_symbols = skipped = 0
    unverified_words = unverified_bytes = 0
    # Every symbol that names bytes counts as covering them, whether or not it
    # could be compared: the gap report is about bytes nothing names at all.
    covered: dict[int, list[tuple[int, int]]] = {}
    for sym in symbols:
        if sym["type"] in (STT_FUNC, STT_OBJECT) and defined(sym, sections):
            covered.setdefault(sym["shndx"], []).append((sym["value"], sym["size"]))

    # Functions first: their addresses come from the inventory, and the fields
    # the executable filled in for them are what places everything else.
    todo = []
    for sym in symbols:
        if sym["type"] != STT_FUNC or not defined(sym, sections):
            continue
        addr = resolve_address(sym["name"], inventory, index)
        if addr is None:
            note, fatal = unresolved_reason(sym["name"], sym["bind"])
            print(f"{sym['name']:24s} {note}")
            failures += int(fatal)
            skipped += int(not fatal)
            continue
        todo.append((sym, addr))
        unit.place(("section", sym["shndx"], sym["value"]), addr, sym["name"], (sym["shndx"], -1))
        unit.witnesses(
            sym["shndx"], sym["value"], min(sym["size"], inventory[addr]["size"]), addr, sym["name"]
        )

    # Then data, which places more data: __ARVersion is a pointer the code's
    # relocations located, and the banner it points at is only reachable
    # through it.
    data_syms = [s for s in symbols if s["type"] == STT_OBJECT and defined(s, sections)]
    data_todo: list[tuple[dict, int]] = []
    for _ in range(len(data_syms) + 1):
        grew = False
        for sym in data_syms:
            if any(sym is s for s, _ in data_todo):
                continue
            addr = unit.address_of(("section", sym["shndx"], sym["value"]))
            if addr is None or sections[sym["shndx"]]["type"] != SHT_PROGBITS:
                continue
            data_todo.append((sym, addr))
            unit.witnesses(sym["shndx"], sym["value"], sym["size"], addr, sym["name"])
            grew = True
        if not grew:
            break

    for sym, addr in todo:
        also = inventory[addr]["name"]
        label = (
            sym["name"] if also in (sym["name"], f"fn_{addr:08X}") else f"{sym['name']} ({also})"
        )
        ours = unit.bytes_of(sym["shndx"], sym["value"], sym["size"])
        try:
            theirs = dol.read(addr, inventory[addr]["size"])
        except ValueError:
            print(f"{label:24s} 0x{addr:08X} is not mapped in the executable")
            failures += 1
            continue
        good, undecided, diffs = unit.compare(sym["shndx"], sym["value"], addr, ours, theirs)
        n = max(len(ours), len(theirs)) // 4
        ok = not diffs and len(ours) == len(theirs)
        failures += not ok
        unverified_words += undecided
        unverified_symbols += int(ok and bool(undecided))
        where = (
            ""
            if ok
            else " at +"
            + ", +".join(f"{i:X}" for i in diffs[:6])
            + (" ..." if len(diffs) > 6 else "")
        )
        link = f", {undecided} need a link" if undecided else ""
        print(
            f"{label:24s} {'MATCH' if ok else 'differs'}  {good}/{n} words{link}  "
            f"(object {len(ours)} bytes, executable {len(theirs)}){where}"
        )
        if diffs and args.show:
            from soa.ppc.decode import decode as decode_insn  # noqa: PLC0415 - optional detail
            from soa.ppc.fmt import format_insn  # noqa: PLC0415

            for i in diffs[: args.show]:
                a, b = ours[i : i + 4], theirs[i : i + 4]
                fa = (
                    format_insn(decode_insn(int.from_bytes(a, "big"), addr + i))
                    if len(a) == 4
                    else "(end)"
                )
                fb = (
                    format_insn(decode_insn(int.from_bytes(b, "big"), addr + i))
                    if len(b) == 4
                    else "(end)"
                )
                note = unit.relocation_note(sym["shndx"], sym["value"], i)
                print(
                    f"    +{i:03X}  ours: {fa:32s} theirs: {fb}" + (f"   [{note}]" if note else "")
                )

    for sym, addr in data_todo:
        ours = unit.bytes_of(sym["shndx"], sym["value"], sym["size"])
        try:
            theirs = dol.read(addr, sym["size"])
        except ValueError:
            print(f"{sym['name']:24s} 0x{addr:08X} is not mapped in the executable")
            failures += 1
            continue
        good, undecided, diffs = unit.compare(sym["shndx"], sym["value"], addr, ours, theirs)
        ok = not diffs and len(ours) == len(theirs)
        failures += not ok
        unverified_bytes += undecided
        unverified_symbols += int(ok and bool(undecided))
        via = unit.placed_by.get(("section", sym["shndx"], sym["value"]), "?")
        where = (
            ""
            if ok
            else " at +"
            + ", +".join(f"{i:X}" for i in diffs[:6])
            + (" ..." if len(diffs) > 6 else "")
        )
        link = f", {undecided} need a link" if undecided else ""
        print(
            f"{sym['name'] or '(anonymous)':24s} {'MATCH' if ok else 'differs'}  "
            f"{good}/{len(ours)} bytes{link}  (data at 0x{addr:08X} via {via}){where}"
        )

    for sym in data_syms:
        if (
            not any(sym is s for s, _ in data_todo)
            and sections[sym["shndx"]]["type"] == SHT_PROGBITS
        ):
            print(f"{sym['name'] or '(anonymous)':24s} nothing in the unit places it")
            unverified_symbols += 1

    for message in unit.conflicts:
        print(f"  layout: {message}")
    failures += len(unit.conflicts)

    gaps = coverage_gaps(unit, covered)
    for message in gaps:
        print(f"  {message}")

    # Saying so is the point: a symbol nothing compared, and a word only a link
    # could decide, are the two ways a unit reports "all match" over code that
    # was never really checked, so both numbers go in the log.
    if skipped:
        print(f"{skipped} local symbol(s) not compared")
    if unverified_words or unverified_bytes or unverified_symbols:
        amounts = [f"{unverified_words} word(s)"] if unverified_words else []
        amounts += [f"{unverified_bytes} data byte(s)"] if unverified_bytes else []
        print(
            f"{' and '.join(amounts) or 'nothing'} only a link can decide, "
            f"across {unverified_symbols} otherwise-matching symbol(s)"
        )
    if failures:
        return EXIT_DIFFERS
    if unverified_words or unverified_bytes or unverified_symbols or skipped or gaps:
        return EXIT_UNVERIFIED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
