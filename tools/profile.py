#!/usr/bin/env python3
"""Read the timing a run prints and check what PLAN A4 asks of it.

    python tools/profile.py build/run.log
    python tools/profile.py build/run-a.log build/run-b.log

The port prints its own measurements at the end of every run; this reads them
back and asserts the four things the plan says a truthful profile does. Three
of them are properties of one log:

  * every worker is either running a command or spinning for one, so busy plus
    idle comes to the pool's span times the number of threads, within 5%;
  * the sampled function table sums to 100% of the run, the printed rows and
    the "other entries" line included;
  * game frames, guest seconds and wall seconds are three separate numbers.

The fourth needs two runs of the same scenario: their top tens have to name
the same functions. Order inside the ten is not asserted -- at a hundred
thousand samples two neighbours a tenth of a point apart can legitimately
swap -- so it is compared as a set, and the tool prints the two orders next to
each other for a person to read.

The wording of those report lines is an interface, not prose: changing a line
in runtime/ without changing the pattern here breaks this tool, and the tests
in tools/tests/test_profile.py hold the pair together.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PASS, FAIL, SKIP = "pass", "FAIL", "skip"

# The five lines this reads, in the spelling runtime/ prints them.
RUN = re.compile(
    r"^\[run\] (\d+) game frames, (\d+) VI retraces.*?; "
    r"([\d.]+) guest seconds at SOA_SPEED=(\d+), ([\d.]+) wall seconds"
)
PRODUCER = re.compile(
    r"^\[gxr\] producer over ([\d.]+)s by the (.+?): setup ([\d.]+)s, prepare ([\d.]+)s, "
    r"decode ([\d.]+)s, copy ([\d.]+)s, png ([\d.]+)s, wait ([\d.]+)s, raster ([\d.]+)s; "
    r"the other ([\d.]+)s"
)
WORKERS = re.compile(
    r"^\[gxr\] workers: (\d+) threads, pool up ([\d.]+)s each = ([\d.]+)s of thread time; "
    r"busy ([\d.]+)s \+ idle ([\d.]+)s = ([\d.]+)s, (-?[\d.]+)% unaccounted"
)
PROFILE = re.compile(r"^\[profile\] (\d+) samples at ([\d.]+) Hz over ([\d.]+)s")
ROW = re.compile(r"^ {2}\s*(-?[\d.]+)% {2}(?:([0-9A-F]{8}) )?\s*(.*?)\s*$")

PHASES = ("setup", "prepare", "decode", "copy", "png", "wait", "raster")


@dataclass
class Row:
    """One line of the sampled table: its share, and what it names."""

    share: float
    addr: str | None
    label: str


@dataclass
class Profile:
    """What one run's report says about itself. None means the line was absent."""

    path: str = ""
    frames: int | None = None
    retraces: int | None = None
    guest_s: float | None = None
    wall_s: float | None = None
    speed: int | None = None
    producer_span: float | None = None
    clock: str | None = None
    phases: dict[str, float] = field(default_factory=dict)
    producer_rest: float | None = None
    threads: int | None = None
    pool_s: float | None = None
    busy_s: float | None = None
    idle_s: float | None = None
    samples: int | None = None
    rate_hz: float | None = None
    sampled_s: float | None = None
    rows: list[Row] = field(default_factory=list)

    @property
    def top(self) -> list[str]:
        """The ten heaviest entries, by the label the report gave them.

        The report prints them in order and ends with one aggregate row for
        everything it did not show; that row is what makes the shares add up,
        and it is not an entry, so it is not in the ten."""
        return [r.label for r in self.rows if not r.label.startswith("the other ")][:10]


@dataclass
class Check:
    name: str
    status: str
    detail: str


def parse(text: str, path: str = "") -> Profile:
    """Pull the timing out of a run's log. Anything absent stays None."""
    p = Profile(path=path)
    in_table = False
    for line in text.splitlines():
        if m := RUN.match(line):
            p.frames = int(m[1])
            p.retraces = int(m[2])
            p.guest_s = float(m[3])
            p.speed = int(m[4])
            p.wall_s = float(m[5])
        elif m := PRODUCER.match(line):
            p.producer_span = float(m[1])
            p.clock = m[2]
            p.phases = {name: float(m[3 + i]) for i, name in enumerate(PHASES)}
            p.producer_rest = float(m[10])
        elif m := WORKERS.match(line):
            p.threads = int(m[1])
            p.pool_s = float(m[2])
            p.busy_s = float(m[4])
            p.idle_s = float(m[5])
        elif m := PROFILE.match(line):
            # The second [profile] line is the timers-against-sampler check,
            # which has no rows under it.
            if p.samples is None:
                p.samples = int(m[1])
                p.rate_hz = float(m[2])
                p.sampled_s = float(m[3])
                in_table = True
        elif in_table and (m := ROW.match(line)):
            p.rows.append(Row(float(m[1]), m[2], m[3]))
        else:
            in_table = False
    return p


def check(p: Profile) -> list[Check]:
    """The three invariants one log can carry on its own."""
    checks: list[Check] = []

    # 1. busy + idle against the pool's span times the threads.
    if p.threads is None or p.pool_s is None:
        checks.append(
            Check(
                "busy + idle is the pool's time",
                SKIP,
                "no [gxr] workers line: this run rendered on the producer, or not at all",
            )
        )
    else:
        thread_time = p.pool_s * p.threads
        got = (p.busy_s or 0.0) + (p.idle_s or 0.0)
        off = abs(thread_time - got) / thread_time * 100 if thread_time else 0.0
        checks.append(
            Check(
                "busy + idle is the pool's time",
                PASS if off <= 5.0 else FAIL,
                f"{p.threads} threads x {p.pool_s:.2f}s = {thread_time:.2f}s against "
                f"busy {p.busy_s:.2f}s + idle {p.idle_s:.2f}s = {got:.2f}s, {off:.1f}% apart "
                f"(5% allowed; what is left over is each thread's open stretch at the report)",
            )
        )

    # 2. the sampled table sums to the whole run.
    if not p.rows:
        checks.append(Check("the table sums to 100%", SKIP, "no [profile] table in this log"))
    else:
        total = sum(r.share for r in p.rows)
        # Every row is printed to one decimal, so the sum can miss by half a
        # tenth per row before anything is actually wrong.
        slack = 0.05 * len(p.rows) + 0.05
        checks.append(
            Check(
                "the table sums to 100%",
                PASS if abs(total - 100.0) <= slack else FAIL,
                f"{len(p.rows)} rows sum to {total:.1f}%, "
                f"{'within' if abs(total - 100.0) <= slack else 'outside'} the "
                f"{slack:.2f} point rounding slack of one decimal place a row",
            )
        )

    # 3. three clocks, separately.
    have = [
        name
        for name, v in (
            ("game frames", p.frames),
            ("guest seconds", p.guest_s),
            ("wall seconds", p.wall_s),
        )
        if v is not None
    ]
    if len(have) < 3:
        checks.append(
            Check(
                "frames, guest and wall are separate",
                FAIL,
                f"the [run] line gives {', '.join(have) or 'none of the three'}",
            )
        )
    else:
        # Guest seconds are wall seconds times SOA_SPEED by construction, so
        # the interesting part is that the report does not pretend otherwise.
        expect = (p.wall_s or 0.0) * (p.speed or 1)
        near = abs(expect - (p.guest_s or 0.0)) <= max(0.5, 0.1 * expect)
        checks.append(
            Check(
                "frames, guest and wall are separate",
                PASS,
                f"{p.frames} frames, {p.guest_s:.1f} guest seconds, {p.wall_s:.1f} wall seconds "
                f"at SOA_SPEED={p.speed}"
                + (
                    ""
                    if near
                    else f" -- but guest is not wall x speed ({expect:.1f}s expected), so one clock "
                    "started late or the run changed speed"
                ),
            )
        )
    return checks


def compare(a: Profile, b: Profile) -> Check:
    """The fourth invariant: two runs of one scenario name the same ten."""
    if not a.rows or not b.rows:
        return Check("the same top ten twice", SKIP, "one of the two logs has no [profile] table")
    ta, tb = a.top, b.top
    only_a = [x for x in ta if x not in tb]
    only_b = [x for x in tb if x not in ta]
    if only_a or only_b:
        return Check(
            "the same top ten twice",
            FAIL,
            f"{len(only_a)} of ten differ: only in {a.path or 'the first'}: "
            f"{', '.join(only_a)}; only in {b.path or 'the second'}: {', '.join(only_b)}",
        )
    moved = sum(1 for i, x in enumerate(ta) if tb[i] != x)
    return Check(
        "the same top ten twice",
        PASS,
        f"the same ten entries; {moved} of them in a different order, which is sampling noise "
        f"at {a.samples or 0} and {b.samples or 0} samples",
    )


def report(checks: list[Check]) -> int:
    for c in checks:
        print(f"  {c.status:5}  {c.name}")
        print(f"         {c.detail}")
    return 1 if any(c.status == FAIL for c in checks) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "logs", type=Path, nargs="+", help="one run's log, or two to compare their top tens"
    )
    args = ap.parse_args(argv)
    if len(args.logs) > 2:
        print("at most two logs: one to check, two to compare", file=sys.stderr)
        return 2
    profiles = [parse(p.read_text(encoding="utf-8", errors="replace"), str(p)) for p in args.logs]
    rc = 0
    for p in profiles:
        print(p.path)
        rc |= report(check(p))
    if len(profiles) == 2:
        print("both")
        rc |= report([compare(*profiles)])
        width = max((len(x) for x in profiles[0].top), default=0)
        for i, (x, y) in enumerate(zip(profiles[0].top, profiles[1].top, strict=False)):
            print(f"  {i + 1:2}  {x:<{width}}  {y}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
