#!/usr/bin/env python3
"""R0's battle log, checked (docs/specs/battle-harness.md).

    python tools/battle.py check <log> [--double] [--min-hits N]

A run with SOA_BATTLE_LOG=1 prints a `[battle] ... damage B -> O -> R` line
for every damage the battle worked out: the base the game passed fn_800108EC,
the value it returned, what the game got after every mod's on_damage, and the
target's multiplier for the element and its Guard bit. `check` holds:

  - every returned value to the rule asked for: with no mod R == O; with
    --double (examples/mods/damage-double) R == min(2 O, 9999);
  - every original to the formula's range for its base, multiplier and guard
    (battle-system.md 3.3: x = base in [0.975, 1.025), +1 one time in eight,
    x mult/10 for an element up to 5, halved on a Guard, 9999 at most);
  - at least --min-hits nonzero values, so it cannot pass on a battle with
    no hits.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path

DAMAGE = re.compile(
    r"^\[battle\] frame (\d+) damage (-?\d+) -> (-?\d+) -> (-?\d+) by slot (-?\d+) on slot (-?\d+) "
    r"element (\d+) mult (-?\d+) guard (\d)$"
)


@dataclass(frozen=True)
class Hit:
    frame: int
    base: int
    original: int
    returned: int
    attacker: int
    target: int
    element: int
    mult: int
    guard: int


def hits(text: str) -> list[Hit]:
    out = []
    for line in text.splitlines():
        m = DAMAGE.match(line.strip())
        if m:
            out.append(Hit(*(int(v) for v in m.groups())))
    return out


def formula_range(h: Hit) -> tuple[int, int]:
    """The least and most the formula gives this hit (battle-system.md 3.3)."""
    x = max(h.base, 0)
    lo, hi = x * 0.975, x * 1.025 + 1
    if h.element <= 5:
        lo, hi = lo * h.mult / 10.0, hi * h.mult / 10.0
    if h.guard:
        lo, hi = lo * 0.5, hi * 0.5
    return min(math.floor(lo), 9999), min(math.floor(hi), 9999)


def check(text: str, double: bool, min_hits: int) -> list[str]:
    """The faults, empty when the log keeps every rule."""
    got = hits(text)
    faults = []

    def want(o: int) -> int:
        return min(2 * o, 9999) if double else o

    for h in got:
        if h.returned != want(h.original):
            faults.append(
                f"frame {h.frame}: returned {h.returned} from {h.original}, not {want(h.original)}"
            )
        lo, hi = formula_range(h)
        if not lo <= h.original <= hi:
            faults.append(
                f"frame {h.frame}: {h.original} from base {h.base} (element {h.element}, mult {h.mult}, "
                f"guard {h.guard}) is outside the formula's {lo}..{hi}"
            )
    nonzero = sum(1 for h in got if h.original)
    if nonzero < min_hits:
        faults.append(f"{nonzero} nonzero hits, fewer than {min_hits}: too few to prove anything")
    return faults


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("check",))
    ap.add_argument("log", type=Path)
    ap.add_argument("--double", action="store_true", help="the doubling mod: R == min(2 O, 9999)")
    ap.add_argument("--min-hits", type=int, default=10)
    args = ap.parse_args(argv)
    text = args.log.read_text(encoding="utf-8", errors="replace")
    got = hits(text)
    faults = check(text, args.double, args.min_hits)
    print(
        f"battle: {len(got)} damage calls, {sum(1 for h in got if h.original)} nonzero; "
        + ("every call kept every rule" if not faults else f"{len(faults)} fault(s)")
    )
    for f in faults[:20]:
        print(f"FAIL {f}")
    return 1 if faults else 0


if __name__ == "__main__":
    raise SystemExit(main())
