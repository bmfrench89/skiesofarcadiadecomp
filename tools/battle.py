#!/usr/bin/env python3
"""R0's battle log, checked (docs/specs/battle-harness.md).

    python tools/battle.py check <log> [--double] [--min-hits N]
    python tools/battle.py rewards <log> [--exp K] [--gold K] [--magic K]
    python tools/battle.py info <log>

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

`info` holds mods/battle-info to R0's own reading of the same words (R5's
Done, docs/specs/battle-info.md), battle by battle (R0's `start` lines): the
mod logs `slot S shows H/M` each time a row's numbers change, and each line
of its battle log; R0 logs `slot S hp H/M ... status X` each time an actor's
do, and a `damage ... by slot A on slot T` line for each blow worked out.
The mod reads at a frame end and R0 at the next safe point, so what R0 has
at frame F the mod saw at F - 1 (or F), never later. Every number shown
must be R0's for that slot, an enemy still in the fight (status without
0x2100); every change R0 logs for one must be shown; each blow or heal the
log tells must be R0's change in that slot's HP, and a named striker R0's
last damage line on the target since its HP last moved (a drop with no
striker, one with none); each `down` and `fled`, R0's status bit. So a row
that froze, lagged, showed another slot's numbers or a fallen enemy, and a
log line with the wrong amount or striker, each fail. At least one shows
line, or nothing is proved.
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


SLOT_HP = re.compile(
    r"^\[battle\] frame (\d+) slot (\d+) hp (-?\d+)/(-?\d+) mp \d+ status ([0-9A-F]{8})$"
)
START = re.compile(r"^\[battle\] frame (\d+) start: battle \d+")
SHOWS = re.compile(r"^\[mod\] battle-info: frame (\d+): slot (\d+) shows (-?\d+)/(-?\d+)$")
SAYS = re.compile(
    r"^\[mod\] battle-info: frame (\d+): (?:(P[1-4]|[A-H]) > )?(P[1-4]|[A-H]) ([+-]\d+)$"
)
FELL = re.compile(r"^\[mod\] battle-info: frame (\d+): (P[1-4]|[A-H]) (down|fled)$")
R0_ORDER = re.compile(r"^\[battle\] frame (\d+) order (.*)$")
SHOWN_ORDER = re.compile(
    r"^\[mod\] battle-info: frame (\d+): order ((?:P[1-4]|[A-H])(?: (?:P[1-4]|[A-H]))*)$"
)
PASSED_OVER = 0x6500 | 0x02000000  # a slot phase 3 skips (fn_800708C0): out of the order shown
KO, ESCAPED = 0x100, 0x2000
NOT_PRESENT = KO | ESCAPED  # no row
# The mod reads at a frame end and R0 at the next safe point, which carries the
# next frame's number: what R0 has at frame F the mod saw at F - 1, or at F
# where the two count alike -- never after.
LAGS = (1, 0)


@dataclass(frozen=True)
class Row:
    frame: int
    hp: int
    max: int
    status: int = 0


def slot_of(label: str) -> int:
    """battle-info's label: P1-P4 the party's slots 0-3, A-H the enemies' 4-11."""
    return int(label[1]) - 1 if label[0] == "P" else 4 + ord(label) - ord("A")


def at(rows: list[Row], frame: int, since: int) -> Row | None:
    """The last row at or before `frame` and not before `since`, its battle's start."""
    got = None
    for row in rows:
        if row.frame > frame:
            break
        if row.frame >= since:
            got = row
    return got


def said(row: Row | None, status: bool = True) -> str:
    if row is None:
        return "nothing"
    return f"{row.hp}/{row.max}" + (f" status {row.status:08X}" if status else "")


def check_info(text: str) -> list[str]:
    """The faults, empty when battle-info's rows and log agree with R0's log."""
    r0: dict[int, list[Row]] = {}
    shows: dict[int, list[Row]] = {}
    hits: list[tuple[int, int, int]] = []  # R0's damage lines: frame, attacker, target
    says: list[tuple[int, str | None, str, int]] = []
    fell: list[tuple[int, str, str]] = []
    orders: list[tuple[int, list[int]]] = []  # R0's order lines
    shown_orders: list[tuple[int, list[int]]] = []
    starts = [0]
    for line in text.splitlines():
        line = line.strip()
        if m := START.match(line):
            starts.append(int(m.group(1)))
        elif m := SLOT_HP.match(line):
            f, s, hp, mx = (int(v) for v in m.groups()[:4])
            r0.setdefault(s, []).append(Row(f, hp, mx, int(m.group(5), 16)))
        elif m := DAMAGE.match(line):
            hits.append((int(m.group(1)), int(m.group(5)), int(m.group(6))))
        elif m := SHOWS.match(line):
            f, s, hp, mx = (int(v) for v in m.groups())
            shows.setdefault(s, []).append(Row(f, hp, mx))
        elif m := SAYS.match(line):
            says.append((int(m.group(1)), m.group(2), m.group(3), int(m.group(4))))
        elif m := FELL.match(line):
            fell.append((int(m.group(1)), m.group(2), m.group(3)))
        elif m := R0_ORDER.match(line):
            orders.append((int(m.group(1)), [int(v) for v in m.group(2).split() if v != "(none)"]))
        elif m := SHOWN_ORDER.match(line):
            shown_orders.append((int(m.group(1)), [slot_of(x) for x in m.group(2).split()]))

    def since(frame: int) -> int:
        return max(s for s in starts if s <= frame)

    faults = []
    for s, rows in sorted(
        shows.items()
    ):  # every number shown R0's, for an enemy still in the fight
        for row in rows:
            near = [at(r0.get(s, []), row.frame + d, since(row.frame)) for d in LAGS]
            if not any(
                n and (n.hp, n.max) == (row.hp, row.max) and not n.status & NOT_PRESENT
                for n in near
            ):
                faults.append(
                    f"frame {row.frame}: slot {s} shown at {said(row, False)}; R0 has {said(near[0])}"
                )
    for s, rows in sorted(r0.items()):  # every change R0 logs for one shown, in its battle
        for row in rows:
            if s < 4 or row.status & NOT_PRESENT:
                continue
            near = [at(shows.get(s, []), row.frame - d, since(row.frame)) for d in LAGS]
            if not any(n and (n.hp, n.max) == (row.hp, row.max) for n in near):
                faults.append(
                    f"frame {row.frame}: R0 has slot {s} at {said(row, False)}; the row showed "
                    f"{said(near[0], False)}"
                )
    for f, by, who, delta in says:  # each blow or heal the log tells: R0's change, and its striker
        t = slot_of(who)
        before = at(r0.get(t, []), f, since(f))
        after = at(r0.get(t, []), f + 1, since(f))
        if not before or not after or after.hp - before.hp != delta:
            faults.append(
                f"frame {f}: the log says {who} {delta:+d}; R0 has {said(before)} then {said(after)}"
            )
            continue
        struck = [a for h, a, target in hits if target == t and before.frame < h <= f]
        if by is not None and (not struck or struck[-1] != slot_of(by)):
            faults.append(
                f"frame {f}: the log puts {who}'s {delta} to {by}; R0's striker is {struck[-1:]}"
            )
        elif by is None and delta < 0 and struck:
            faults.append(
                f"frame {f}: the log names no striker for {who}'s {delta}; R0's is slot {struck[-1]}"
            )
    for f, who, what in fell:  # each knock-out and escape the log tells: R0's status bit
        bit = KO if what == "down" else ESCAPED
        near = [at(r0.get(slot_of(who), []), f + d, since(f)) for d in LAGS]
        if not any(n and n.status & bit for n in near):
            faults.append(f"frame {f}: the log says {who} {what}; R0 has {said(near[0])}")
    for f, shown in shown_orders:  # each order shown: a suffix of R0's latest, the fallen left out
        latest = [o for o_f, o in orders if since(f) <= o_f <= f + 1]
        arr = latest[-1] if latest else []

        def standing(s: int, f: int = f) -> bool:
            row = at(r0.get(s, []), f + 1, since(f))
            return row is not None and not row.status & PASSED_OVER

        if not any([s for s in arr[c:] if standing(s)] == shown for c in range(len(arr) + 1)):
            faults.append(
                f"frame {f}: the order shown {shown} is no suffix of R0's {arr}, the fallen left out"
            )
    if not shows:
        faults.append("no shows line: battle-info drew no HP row, so nothing is proved")
    return faults


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
    ap.add_argument("command", choices=("check", "rewards", "info"))
    ap.add_argument("log", type=Path)
    ap.add_argument("--double", action="store_true", help="the doubling mod: R == min(2 O, 9999)")
    ap.add_argument("--min-hits", type=int, default=10)
    for name in ("exp", "gold", "magic"):
        ap.add_argument(f"--{name}", type=multipliers, default=[Fraction(1)], metavar="K[,K...]")
    args = ap.parse_args(argv)
    text = args.log.read_text(encoding="utf-8", errors="replace")
    if args.command == "info":
        faults = check_info(text)
        lines = [x.strip() for x in text.splitlines()]
        rows = sum(1 for x in lines if SHOWS.match(x))
        told = sum(1 for x in lines if SAYS.match(x) or FELL.match(x))
        orders = sum(1 for x in lines if SHOWN_ORDER.match(x))
        print(
            f"battle: {rows} shows, {told} log and {orders} order line(s); "
            + (
                "each R0's, and every change R0 logged shown"
                if not faults
                else f"{len(faults)} fault(s)"
            )
        )
        for f in faults[:20]:
            print(f"FAIL {f}")
        return 1 if faults else 0
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
