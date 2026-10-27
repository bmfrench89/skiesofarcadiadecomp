#!/usr/bin/env python3
"""R0's battle log, checked (docs/specs/battle-harness.md).

    python tools/battle.py check <log> [--double] [--min-hits N]
    python tools/battle.py rewards <log> [--exp K] [--gold K] [--magic K]

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

`rewards` holds each `[battle] ... rewards exp A -> B gold C -> D magic exp
E -> F` line (R1's on_rewards, before and after every mod) to the
multipliers the mods were given (docs/specs/battle-mods.md 7): B the
original times each K of --exp in turn, rounded down at each, as the mods
in load order do (`--exp 2,1.25` is battle-boosts' x2, then difficulty's
Hard); gold held to 99,999,999 and magic EXP to 127 as runtime/battle.c holds
them. Every K is 1 unless given, so a run with no mod must pair each value
with itself. There must be one rewards line for each battle that ended in
victory (its end line's last phase 7), and at least one.
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from fractions import Fraction
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


REWARDS = re.compile(
    r"^\[battle\] frame (\d+) rewards exp (-?\d+) -> (-?\d+) gold (-?\d+) -> (-?\d+) "
    r"magic exp (-?\d+) -> (-?\d+)$"
)
END = re.compile(r"^\[battle\] frame (\d+) end: .*, last phase (\d+)$")
VICTORY = 7
# What each mod holds a reward to after its own step (both shipped mods hold
# magic EXP to 127 as they go), and what runtime/battle.c holds it to at the end.
STEP_CAPS = {"exp": 2**31 - 1, "gold": 2**31 - 1, "magic": 127}
CAPS = {"exp": 2**31 - 1, "gold": 99_999_999, "magic": 127}


def multipliers(text: str) -> list[Fraction]:
    """`1.25,2` as the multipliers a reward goes through, in order."""
    return [Fraction(k) for k in text.split(",")]


def paid(value: int, ks: list[Fraction], name: str) -> int:
    """What the mods leave of a reward: times each K in turn, rounded down and
    held to the step's cap at each, then to the port's."""
    for k in ks:
        value = min(math.floor(value * k), STEP_CAPS[name])
    return min(value, CAPS[name])


def check_rewards(text: str, ks: dict[str, list[Fraction]]) -> list[str]:
    """The faults, empty when every rewards line keeps the multipliers."""
    faults = []
    lines = [REWARDS.match(x.strip()) for x in text.splitlines()]
    rows = [tuple(int(v) for v in m.groups()) for m in lines if m]
    for frame, *pairs in rows:
        pairs_of = zip(pairs[::2], pairs[1::2], strict=True)
        for name, (was, got) in zip(("exp", "gold", "magic"), pairs_of, strict=True):
            want = paid(was, ks[name], name)
            if got != want:
                faults.append(f"frame {frame}: {name} {was} -> {got}, not {want}")
    ends = [END.match(x.strip()) for x in text.splitlines()]
    won = sum(1 for m in ends if m and int(m.group(2)) == VICTORY)
    if not rows:
        faults.append("no rewards line: no battle was won, so nothing is proved")
    elif len(rows) != won:
        faults.append(
            f"{len(rows)} rewards line(s) for {won} victory(ies): on_rewards fires once a victory"
        )
    return faults


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("check", "rewards"))
    ap.add_argument("log", type=Path)
    ap.add_argument("--double", action="store_true", help="the doubling mod: R == min(2 O, 9999)")
    ap.add_argument("--min-hits", type=int, default=10)
    for name in ("exp", "gold", "magic"):
        ap.add_argument(f"--{name}", type=multipliers, default=[Fraction(1)], metavar="K[,K...]")
    args = ap.parse_args(argv)
    text = args.log.read_text(encoding="utf-8", errors="replace")
    if args.command == "rewards":
        faults = check_rewards(text, {"exp": args.exp, "gold": args.gold, "magic": args.magic})
        rows = sum(1 for x in text.splitlines() if REWARDS.match(x.strip()))
        print(
            f"battle: {rows} rewards line(s); "
            + ("every one kept the multipliers" if not faults else f"{len(faults)} fault(s)")
        )
        for f in faults[:20]:
            print(f"FAIL {f}")
        return 1 if faults else 0
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
