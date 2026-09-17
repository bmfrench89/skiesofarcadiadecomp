"""Does a compiled object match the executable, function by function?

    python tools/matchcheck.py build/src/string.o [--dol extracted/sys/main.dol]

Reads the object's symbol table, finds each function's address (from the
symbol's own ``fn_XXXXXXXX`` name, else by name in config/functions.tsv or
config/names.txt), and compares the instruction words against the executable.
Words that carry a relocation in the object (calls, address materialisations)
are compared by opcode only, since the linker fills those in. Prints a
per-function score, and a count of the local symbols nothing resolved -- the
one way a unit can report "all match" over code that was never compared.
Exit status is non-zero when any function differs. Analysis only: the
executable is read, never written.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soa import dol as D  # noqa: E402
from soa import symbols as S  # noqa: E402


def read_elf(data: bytes):
    """Sections, symbols and relocations of a big-endian ELF32 relocatable."""
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
    relocs: dict[int, dict[int, tuple[int, int]]] = {}
    for s in sections:
        if s["type"] == 2:  # SYMTAB
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
        elif s["type"] == 4:  # RELA
            table = relocs.setdefault(s["info"], {})
            for j in range(s["size"] // 12):
                o = s["off"] + j * 12
                r_off, r_info, addend = struct.unpack(">IIi", data[o : o + 12])
                table[r_off] = (r_info & 0xFF, r_info >> 8)
    return sections, symbols, relocs


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
    if bind == 0:  # STB_LOCAL
        return "static helper, inlined (no executable counterpart)", False
    return "not in the inventory", True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("object", type=Path)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--functions", type=Path, default=Path("config/functions.tsv"))
    ap.add_argument("--names", type=Path, default=Path("config/names.txt"))
    ap.add_argument(
        "--show",
        type=int,
        default=0,
        metavar="N",
        help="list the first N differing instructions side by side",
    )
    args = ap.parse_args()

    dol = D.parse(args.dol.read_bytes())
    inventory = S.load_tsv(args.functions)
    index = name_index(inventory, S.load_names(args.names))
    sections, symbols, relocs = read_elf(args.object.read_bytes())
    data = args.object.read_bytes()
    failures = 0
    skipped = 0
    for sym in symbols:
        if sym["type"] != 2 or sym["size"] == 0:  # STT_FUNC
            continue
        sec = sections[sym["shndx"]]
        ours = data[sec["off"] + sym["value"] : sec["off"] + sym["value"] + sym["size"]]
        addr = resolve_address(sym["name"], inventory, index)
        if addr is None:
            note, fatal = unresolved_reason(sym["name"], sym["bind"])
            print(f"{sym['name']:24s} {note}")
            failures += int(fatal)
            skipped += int(not fatal)
            continue
        # The inventory's name for it, when the source spells it some other way.
        also = inventory[addr]["name"]
        label = (
            sym["name"] if also in (sym["name"], f"fn_{addr:08X}") else f"{sym['name']} ({also})"
        )
        target_size = inventory[addr]["size"]
        theirs = dol.read(addr, target_size)
        rel = relocs.get(sym["shndx"], {})
        n = max(len(ours), len(theirs)) // 4
        same = 0
        diffs = []
        for i in range(n):
            a = ours[4 * i : 4 * i + 4]
            b = theirs[4 * i : 4 * i + 4]
            if len(a) < 4 or len(b) < 4:
                diffs.append(i)
                continue
            off = sym["value"] + 4 * i
            if (
                off in rel or off + 2 in rel
            ):  # linker-filled field (half-word ones sit at +2): compare the opcode only
                if a[0] >> 2 == b[0] >> 2:
                    same += 1
                else:
                    diffs.append(i)
            elif a == b:
                same += 1
            else:
                diffs.append(i)
        ok = not diffs and len(ours) == len(theirs)
        failures += not ok
        where = (
            ""
            if ok
            else " at +"
            + ", +".join(f"{4 * i:X}" for i in diffs[:6])
            + (" ..." if len(diffs) > 6 else "")
        )
        print(
            f"{label:24s} {'MATCH' if ok else 'differs'}  {same}/{n} words  (object {len(ours)} bytes, executable {len(theirs)}){where}"
        )
        if diffs and args.show:
            from soa.ppc.decode import decode as decode_insn  # noqa: PLC0415 - optional detail
            from soa.ppc.fmt import format_insn  # noqa: PLC0415

            for i in diffs[: args.show]:
                a = ours[4 * i : 4 * i + 4]
                b = theirs[4 * i : 4 * i + 4]
                fa = (
                    format_insn(decode_insn(int.from_bytes(a, "big"), addr + 4 * i))
                    if len(a) == 4
                    else "(end)"
                )
                fb = (
                    format_insn(decode_insn(int.from_bytes(b, "big"), addr + 4 * i))
                    if len(b) == 4
                    else "(end)"
                )
                print(f"    +{4 * i:03X}  ours: {fa:32s} theirs: {fb}")
    # Saying so is the point: a local symbol nothing resolves is the one way a
    # unit can report "all match" over code that was never compared, so the
    # number has to be in the log rather than inferred from its absence.
    if skipped:
        print(f"{skipped} local symbol(s) not compared")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
