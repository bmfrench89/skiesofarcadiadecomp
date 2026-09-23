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
from soa.ppc.regs import gpr_defs  # noqa: E402

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
# The same accesses with update: rA is left holding the address they used.
_MEM_UPDATE = tuple(m + "u" for m in _MEM_OPS)


def _value_note(kind: str, val: int) -> str:
    tag = _mmio_name(val)
    return f"{kind} 0x{val:08X}" + (f" ({tag})" if tag else "")


def _fn_name(addr: int, rows: dict[int, dict]) -> str:
    row = rows.get(addr)
    if row:
        return row["name"]
    for a, r in rows.items():
        if a <= addr < a + r["size"]:
            return f"{r['name']}+0x{addr - a:X}"
    return f"{addr:08X}"


def annotate(code, rows, start, end):
    """Yield (addr, text, note) with symbolic notes.

    ``hi`` holds the registers known to contain a constant a lis started.
    What each instruction overwrites comes from gpr_defs() in soa/ppc/regs.py,
    where the PowerPC's scattered destinations are tabulated once: ori, or/mr,
    rlwinm and the other logical ops keep their *source* in the rD field and
    write rA, and update-form accesses write rA as well. This used to assume
    rD, which forgot the register that survived and kept the one that was
    overwritten -- and an annotation from a stale base names a real-looking
    global the instruction never touches. rA=0 in addi (li) and in a D-form
    access is the literal 0, not r0, so r0's value is never the base there.
    """
    hi = {}  # reg -> the constant it holds
    for a in range(start, end, 4):
        i = code.at(a)
        note = ""
        if i is None or not i.valid:
            yield a, format_insn(i), ""
            continue
        m = i.mnemonic
        known = {}  # reg -> the constant this instruction leaves in it
        if m == "addis" and i.ra == 0:
            known[i.rd] = (i.imm & 0xFFFF) << 16
        elif m == "addi" and i.ra != 0 and i.ra in hi:
            val = (hi[i.ra] + i.imm) & 0xFFFFFFFF
            note = _value_note("=", val)
            known[i.rd] = val
        elif m == "ori" and i.rd in hi:
            # ori rA, rS, UIMM: rS sits in the rD field, and is a register
            # even when it is r0. An OR, which is an add only while the low
            # half of rS is clear.
            val = hi[i.rd] | i.imm
            note = _value_note("=", val)
            known[i.ra] = val
        elif (m in _MEM_OPS or m in _MEM_UPDATE) and i.ra != 0 and i.ra in hi:
            val = (hi[i.ra] + i.imm) & 0xFFFFFFFF
            note = _value_note("@", val)
            if m in _MEM_UPDATE:
                known[i.ra] = val  # rA += d: the next access through rA starts here
        elif i.is_direct_branch and ((m == "b" and i.lk_bit) or not start <= i.target < end):
            note = _fn_name(i.target, rows)
        for reg in gpr_defs(i):
            hi.pop(reg, None)  # any other definition of the register loses the value
        hi.update(known)
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
