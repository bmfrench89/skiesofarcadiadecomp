#!/usr/bin/env python3
"""Which battle status bits the game uses (K12): every bit tested, set or
cleared on a word loaded from +28, the battle actor's status, and the bits
nothing touches.

    python tools/statusbits.py              # the masks battle code tests, the bits, the free ones

For each `lwz rV, 28(rB)` in the executable, rV and its copies are followed
for up to 24 instructions in its function: `andi.`, `andis.` and a narrow
`rlwinm` (four bits or fewer) on it are tests; `ori`, `oris`, or an `or` with a
constant, stored back to 28(rB), are sets; an `and`/`andc`/`rlwinm` stored back
is a clear. +28 is a field of other structures too, so a test outside battle
code (0x80008000-0x800B0000) is counted but not trusted, and a bit is free
only with no set anywhere and no test in battle code. Whole-word stores to +28
were read by hand (FINDINGS "K12"): the spawn writes 0, and a party member's
comes from 0x8030B4D4 + 120 * member, +20, which only the battle's end and
clears write. Static, so a bit set through a computed mask would hide; none
was seen.
"""

from __future__ import annotations

import bisect
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from soa.ppc.decode import decode  # noqa: E402
from soa.ppc.regs import gpr_defs  # noqa: E402

BATTLE = (0x80008000, 0x800B0000)
OFFSET = 28
WINDOW = 24
_WRITES_RA = ("andi.", "andis.", "rlwinm", "ori", "oris", "or", "and", "andc")


def _mask(mb: int, me: int) -> int:
    m, i = 0, mb
    while True:
        m |= 1 << (31 - i)
        if i == me:
            return m
        i = (i + 1) % 32


def _rotr(x: int, n: int) -> int:
    n %= 32
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


class Scan:
    """tests/sets/clears: bit -> sites; masks: tested mask -> sites."""

    def __init__(self) -> None:
        self.tests: dict[int, list[int]] = collections.defaultdict(list)
        self.sets: dict[int, list[int]] = collections.defaultdict(list)
        self.clears: dict[int, list[int]] = collections.defaultdict(list)
        self.masks: dict[int, list[int]] = collections.defaultdict(list)

    def _bits(self, d: dict[int, list[int]], mask: int, site: int) -> None:
        for b in range(32):
            if mask >> b & 1:
                d[1 << b].append(site)

    def follow(self, word, a: int, end: int) -> None:
        """The load at `a` (`lwz rV, 28(rB)`), followed to `end`."""
        i = decode(word(a), a)
        base = i.ra
        vals: dict[int, tuple[str, int] | None] = {i.rd: None}
        consts: dict[int, int] = {}
        for k in range(1, WINDOW + 1):
            b = a + 4 * k
            if b >= end:
                return
            j = decode(word(b), b)
            m = j.mnemonic
            other = j.rb if j.rd in vals else j.rd
            if m in ("andi.", "andis.") and j.rd in vals:
                mask = j.imm if m == "andi." else (j.imm << 16) & 0xFFFFFFFF
                vals[j.ra] = ("clear", mask)
                self.masks[mask].append(b)
                self._bits(self.tests, mask, b)
            elif m == "rlwinm" and j.rd in vals:
                mask = _rotr(_mask(j.mb, j.me), j.imm)
                vals[j.ra] = ("clear", mask) if j.imm == 0 else None
                if bin(mask).count("1") <= 4:
                    self.masks[mask].append(b)
                    self._bits(self.tests, mask, b)
            elif m in ("ori", "oris") and j.rd in vals:
                vals[j.ra] = ("set", j.imm if m == "ori" else (j.imm << 16) & 0xFFFFFFFF)
            elif m == "or" and j.rb == j.rd and j.rd in vals:  # mr
                vals[j.ra] = vals[j.rd]
            elif m == "or" and (j.rd in vals or j.rb in vals) and other in consts:
                vals[j.ra] = ("set", consts[other])
            elif m == "and" and (j.rd in vals or j.rb in vals) and other in consts:
                vals[j.ra] = ("clear", consts[other])
            elif m == "andc" and j.rd in vals and j.rb in consts:
                vals[j.ra] = ("clear", ~consts[j.rb] & 0xFFFFFFFF)
            elif m == "stw" and j.imm == OFFSET and j.ra == base:
                op = vals.get(j.rd)
                if op and op[0] == "set":
                    self._bits(self.sets, op[1], b)
                elif op and op[0] == "clear":
                    self._bits(self.clears, ~op[1] & 0xFFFFFFFF, b)
                return
            elif m == "addi" and j.ra == 0:
                consts[j.rd] = j.imm & 0xFFFFFFFF
            elif m == "addis" and j.ra == 0:
                consts[j.rd] = (j.imm << 16) & 0xFFFFFFFF
            elif m == "addi" and j.ra in consts:
                consts[j.rd] = (consts[j.ra] + j.imm) & 0xFFFFFFFF
            defs = gpr_defs(j)
            kept = j.ra if m in _WRITES_RA else -99
            for r in defs:
                if r != kept:
                    vals.pop(r, None)
                if r != kept and not (m in ("addi", "addis") and (j.ra == 0 or j.ra in consts)):
                    consts.pop(r, None)
            if base in defs:
                return

    def run(self, word, start: int, end: int, func_end) -> None:
        for a in range(start, end, 4):
            i = decode(word(a), a)
            if i.mnemonic == "lwz" and i.imm == OFFSET and i.ra not in (0, 1):
                fe = func_end(a)
                if fe:
                    self.follow(word, a, fe)

    def free(self) -> list[int]:
        """Bits with no set anywhere and no test in battle code."""
        return [
            1 << b
            for b in range(32)
            if not self.sets.get(1 << b)
            and not any(BATTLE[0] <= s < BATTLE[1] for s in self.tests.get(1 << b, []))
        ]


def main() -> int:
    import gamedata as GD

    dol, _ = GD.open_dol(GD.DOL)
    fs = []
    for line in (ROOT / "config" / "functions.tsv").read_text(encoding="utf-8").splitlines()[1:]:
        a, s = line.split("\t")[:2]
        fs.append((int(a, 16), int(s)))
    fs.sort()
    starts = [f[0] for f in fs]

    def func_end(a: int) -> int | None:
        i = bisect.bisect_right(starts, a) - 1
        return fs[i][0] + fs[i][1] if i >= 0 and a < fs[i][0] + fs[i][1] else None

    scan = Scan()
    for sec in dol.text:
        scan.run(dol.word, sec.address, sec.address + sec.size, func_end)
    print("masks battle code tests on +28, with their sites:")
    for mk in sorted(scan.masks):
        sites = [s for s in scan.masks[mk] if BATTLE[0] <= s < BATTLE[1]]
        if sites:
            print(f"  0x{mk:08X}: " + " ".join(f"{s:08X}" for s in sites))
    print("each bit: tests in battle code, sets, clears (sites):")
    for b in range(32):
        bit = 1 << b
        t = [s for s in scan.tests.get(bit, []) if BATTLE[0] <= s < BATTLE[1]]
        st, cl = scan.sets.get(bit, []), scan.clears.get(bit, [])
        print(
            f"  0x{bit:08X}: tests {len(t)}, sets {len(st)} "
            f"({' '.join(f'{s:08X}' for s in st[:4])}), clears {len(cl)}"
        )
    print(
        "free (no set anywhere, no test in battle code):",
        " ".join(f"0x{b:08X}" for b in scan.free()),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
