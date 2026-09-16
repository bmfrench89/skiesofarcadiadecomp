#!/usr/bin/env python3
"""Disassemble recovered functions with symbol names and materialized addresses.

    python tools/disasm.py OSInit                 # by name (config/functions.tsv)
    python tools/disasm.py 0x8028134C             # by entry address
    python tools/disasm.py 0x802813F8 --around    # the function containing the address
    python tools/disasm.py 0x80003140 0x80003200  # a raw range

Branch targets are shown with their function names, and lis/addi(s)/ori
pairs are annotated with the 32-bit value they build so MMIO and global
addresses read at a glance. Analysis only: prints nothing but the
instructions in the local DOL, which never leaves this machine.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import dol as D  # noqa: E402
from soa import symbols as S  # noqa: E402
from soa.ppc import cfg  # noqa: E402
from soa.ppc.fmt import format_insn  # noqa: E402

MMIO = {
    0xCC000000: "CP",
    0xCC001000: "PE",
    0xCC002000: "VI",
    0xCC003000: "PI",
    0xCC004000: "MI",
    0xCC005000: "DSP",
    0xCC006000: "DI",
    0xCC006400: "SI",
    0xCC006800: "EXI",
    0xCC006C00: "AI",
    0xCC008000: "GATHER",
}


def _mmio_name(addr: int) -> str:
    base = addr & 0xFFFFFC00
    if base == 0xCC006000 and addr >= 0xCC006400:
        base = 0xCC006400
    if base == 0xCC006800 and addr >= 0xCC006C00:
        base = 0xCC006C00
    tag = MMIO.get(base)
    return f"{tag}+{addr - base:X}" if tag else ""


_MEM_OPS = ("lwz", "lhz", "lha", "lbz", "stw", "sth", "stb", "lfs", "lfd", "stfs", "stfd")


def _fn_name(addr: int, rows: dict[int, dict]) -> str:
    row = rows.get(addr)
    if row:
        return row["name"]
    for a, r in rows.items():
        if a <= addr < a + r["size"]:
            return f"{r['name']}+0x{addr - a:X}"
    return f"{addr:08X}"


def annotate(code, rows, start, end):
    """Yield (addr, text, note) with symbolic notes."""
    hi = {}  # reg -> value after a lis (cleared when the register is redefined)
    for a in range(start, end, 4):
        i = code.at(a)
        note = ""
        if i is None or not i.valid:
            yield a, format_insn(i), ""
            continue
        m = i.mnemonic
        if m == "addis" and i.ra == 0:
            hi[i.rd] = (i.imm & 0xFFFF) << 16
        elif m in ("addi", "ori") and i.ra in hi:
            val = (hi[i.ra] + (i.imm & 0xFFFF if m == "ori" else i.imm)) & 0xFFFFFFFF
            tag = _mmio_name(val)
            note = f"= 0x{val:08X}" + (f" ({tag})" if tag else "")
            hi[i.rd] = val
        elif m in _MEM_OPS and i.ra in hi:
            val = (hi[i.ra] + i.imm) & 0xFFFFFFFF
            tag = _mmio_name(val)
            note = f"@ 0x{val:08X}" + (f" ({tag})" if tag else "")
            if m.startswith("l") and i.rd in hi:
                hi.pop(i.rd, None)
        elif i.is_direct_branch and ((m == "b" and i.lk_bit) or not start <= i.target < end):
            note = _fn_name(i.target, rows)
        elif i.rd in hi and i.form is not None and not m.startswith("st"):
            hi.pop(i.rd, None)  # any other definition of the register loses the value
        yield a, format_insn(i), note


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", nargs="+", help="function name, entry address, or start end")
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--functions", type=Path, default=Path("config/functions.tsv"))
    ap.add_argument("--around", action="store_true", help="the function containing the address")
    args = ap.parse_args()

    dol = D.parse(args.dol.read_bytes())
    rows = S.load_tsv(args.functions)
    by_name = {r["name"]: a for a, r in rows.items()}
    code = cfg.CodeView(dol)

    if len(args.target) == 2 and all(t.lower().startswith("0x") for t in args.target):
        start, end = (int(t, 16) for t in args.target)
        title = f"{start:08X}..{end:08X}"
    else:
        t = args.target[0]
        addr = int(t, 16) if t.lower().startswith("0x") else by_name.get(t)
        if addr is None:
            print(f"error: unknown function {t!r}", file=sys.stderr)
            return 1
        if args.around or addr not in rows:
            owner = next((a for a, r in rows.items() if a <= addr < a + r["size"]), None)
            if owner is None:
                print(f"error: {addr:08X} is not inside a recovered function", file=sys.stderr)
                return 1
            addr = owner
        row = rows[addr]
        start, end = addr, addr + row["size"]
        title = f"{row['name']} ({addr:08X}, {row['size']} bytes)"

    print(title)
    for a, text, note in annotate(code, rows, start, end):
        print(f"  {a:08X}  {text:<40} {note}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
