"""Does a compiled object match the executable, function by function?

    python tools/matchcheck.py build/src/string.o [--dol extracted/sys/main.dol]

Reads the object's symbol table, finds each function's address in the
inventory (config/functions.tsv, by name), and compares the instruction words
against the executable. Words that carry a relocation in the object (calls,
address materialisations) are compared by opcode only, since the linker fills
those in. Prints a per-function score; exit status is non-zero when any
function differs. Analysis only: the executable is read, never written.
"""

from __future__ import annotations

import argparse
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
                    {"name": nm, "value": value, "size": size, "type": info & 0xF, "shndx": shndx}
                )
        elif s["type"] == 4:  # RELA
            table = relocs.setdefault(s["info"], {})
            for j in range(s["size"] // 12):
                o = s["off"] + j * 12
                r_off, r_info, addend = struct.unpack(">IIi", data[o : o + 12])
                table[r_off] = (r_info & 0xFF, r_info >> 8)
    return sections, symbols, relocs


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("object", type=Path)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--functions", type=Path, default=Path("config/functions.tsv"))
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
    by_name = {row["name"]: addr for addr, row in inventory.items()}
    sections, symbols, relocs = read_elf(args.object.read_bytes())
    data = args.object.read_bytes()
    failures = 0
    for sym in symbols:
        if sym["type"] != 2 or sym["size"] == 0:  # STT_FUNC
            continue
        sec = sections[sym["shndx"]]
        ours = data[sec["off"] + sym["value"] : sec["off"] + sym["value"] + sym["size"]]
        addr = by_name.get(sym["name"])
        if addr is None:
            print(f"{sym['name']:24s} not in the inventory")
            failures += 1
            continue
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
            f"{sym['name']:24s} {'MATCH' if ok else 'differs'}  {same}/{n} words  (object {len(ours)} bytes, executable {len(theirs)}){where}"
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
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
