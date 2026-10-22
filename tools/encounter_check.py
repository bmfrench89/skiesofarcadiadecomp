#!/usr/bin/env python3
"""P1b's encounter contrast, judged from a run's log (the comfort-pack spec, P1b).

    python tools/encounter_check.py LOG [--rate 20]

mods/encounter-rate's test mode (SOA_ENCOUNTERS_TEST=1) logs one line a
trial, `trial n kind zone0 rate0 zone1 rate1 moved battle|clear|stuck`, the
kinds 0.5, 1, 2, 0 and hold in turn, each from a step counter of 480. This
reads them and applies P1b's rules:

- a trial counts when the zone's rate it logged is --rate at both ends, and
  it did not stick;
- r(k), battles per 1000 moving frames over the counted trials of kind k, is
  the rate estimate for trials cut at 600 moving frames;
- it passes when each of 0.5, 1 and 2 has at least 40 counted trials and
  r(2) > r(1) > r(0.5); at least 40 counted k = 0 trials and 20 hold trials
  each reach 600 moving frames with no battle; and no more than 10% of all
  trials stuck.

--rate is the rate of the zones the run walks in: 20 in a101b's zones 2 and 3,
for which the spec worked the figures; 45 in a116a's (FINDINGS "R5c and M6 on
the PC"). The chance that a mod working as it should fails the ordering rule
is printed for the rate and the counts the run had, from the roll's own
model (docs/research/encounters.md): each moving frame at counter N >= 480
wins with probability f31 * N / 8000, f31 = (N - 30) * rate / 14400 * m / 2,
m the multiplier over 50 (0.5, 1, 2). Exit status 0 on a pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LINE = re.compile(
    r"encounter-rate: trial (\d+) (0\.5|1|2|0|hold) (\d+) (\d+) (\d+) (\d+) (\d+) (battle|clear|stuck)\b"
)
KINDS = ("0.5", "1", "2", "0", "hold")
MOVES = 600
START = 480
MIN_NONZERO, MIN_ZERO, MIN_HOLD = 40, 40, 20
MAX_STUCK = 0.10


@dataclass
class Trial:
    n: int
    kind: str
    zone0: int
    rate0: int
    zone1: int
    rate1: int
    moved: int
    end: str


def read(text: str) -> list[Trial]:
    out = []
    for m in LINE.finditer(text):
        n, kind, z0, r0, z1, r1, moved, end = m.groups()
        out.append(Trial(int(n), kind, int(z0), int(r0), int(z1), int(r1), int(moved), end))
    return out


def counted(trials: list[Trial], rate: int) -> list[Trial]:
    return [t for t in trials if t.rate0 == rate and t.rate1 == rate and t.end != "stuck"]


def r_of(trials: list[Trial], kind: str) -> float | None:
    """Battles per 1000 moving frames over `trials` of `kind`."""
    ts = [t for t in trials if t.kind == kind]
    moved = sum(t.moved for t in ts)
    return 1000.0 * sum(t.end == "battle" for t in ts) / moved if moved else None


def judge(trials: list[Trial], rate: int) -> tuple[bool, list[str]]:
    """The verdict and the lines that say why."""
    lines: list[str] = []
    ok = True
    if not trials:
        return False, [
            "no trial lines: was SOA_ENCOUNTERS_TEST=1 set, and mods/encounter-rate loaded?"
        ]
    c = counted(trials, rate)
    stuck = sum(t.end == "stuck" for t in trials)
    lines.append(f"{len(trials)} trial(s), {len(c)} counted at rate {rate}, {stuck} stuck")
    r = {}
    for k in KINDS:
        ts = [t for t in c if t.kind == k]
        r[k] = r_of(c, k)
        rk = "-" if r[k] is None else f"{r[k]:.2f}"
        lines.append(
            f"  k={k}: {len(ts)} counted, {sum(t.end == 'battle' for t in ts)} battle(s), r = {rk}"
        )
    for k in ("0.5", "1", "2"):
        n = sum(t.kind == k for t in c)
        if n < MIN_NONZERO:
            ok = False
            lines.append(f"FAIL: k={k} has {n} counted trials, under {MIN_NONZERO}")
    if all(r[k] is not None for k in ("0.5", "1", "2")) and not (r["2"] > r["1"] > r["0.5"]):
        ok = False
        lines.append(
            f"FAIL: r(2) > r(1) > r(0.5) does not hold: {r['2']:.2f}, {r['1']:.2f}, {r['0.5']:.2f}"
        )
    for k, need in (("0", MIN_ZERO), ("hold", MIN_HOLD)):
        ts = [t for t in c if t.kind == k]
        if len(ts) < need:
            ok = False
            lines.append(f"FAIL: k={k} has {len(ts)} counted trials, under {need}")
        bad = [t for t in ts if t.end != "clear" or t.moved < MOVES]
        if bad:
            ok = False
            lines.append(
                f"FAIL: k={k}: trial {bad[0].n} ended `{bad[0].end}` at {bad[0].moved} moving frames"
            )
    if stuck > MAX_STUCK * len(trials):
        ok = False
        lines.append(f"FAIL: {stuck} of {len(trials)} trials stuck, over {MAX_STUCK:.0%}")
    return ok, lines


def p_battle(n: int, rate: int, m: float) -> float:
    """The roll's chance at step counter n (>= 480), multiplier m over 50."""
    f31 = max((n - 30) * rate / 14400.0 * m, 0.0) * 0.5
    return min(f31 * n / 8000.0, 1.0)


def simulate(kind_m: float, rate: int, rng: random.Random) -> Trial:
    for moved in range(1, MOVES + 1):
        if rng.random() < p_battle(START + moved, rate, kind_m):
            return Trial(0, "", 0, rate, 0, rate, moved, "battle")
    return Trial(0, "", 0, rate, 0, rate, MOVES, "clear")


def false_failure(counts: dict[str, int], rate: int, runs: int = 400, seed: int = 1) -> float:
    """How often the ordering rule fails for a mod that works, at these
    counts and this rate, by simulating the roll's model."""
    rng = random.Random(seed)
    fails = 0
    for _ in range(runs):
        r = {}
        for k, m in (("0.5", 0.5), ("1", 1.0), ("2", 2.0)):
            ts = [simulate(m, rate, rng) for _ in range(max(counts.get(k, 0), 1))]
            r[k] = 1000.0 * sum(t.end == "battle" for t in ts) / sum(t.moved for t in ts)
        fails += not (r["2"] > r["1"] > r["0.5"])
    return fails / runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("log", type=Path)
    ap.add_argument(
        "--rate", type=int, default=20, help="the zone rate trials must log to count (default 20)"
    )
    args = ap.parse_args(argv)
    trials = read(args.log.read_text(encoding="utf-8", errors="replace"))
    ok, lines = judge(trials, args.rate)
    print("\n".join(lines))
    c = counted(trials, args.rate)
    if c:
        counts = {k: sum(t.kind == k for t in c) for k in ("0.5", "1", "2")}
        ff = false_failure(counts, args.rate)
        print(
            f"a working mod fails the ordering rule at these counts and rate {args.rate} about {ff:.1%} of the time"
        )
    print("pass" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
