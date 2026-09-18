"""tools/profile.py against the report the port prints, and against runtime/.

Two halves. The first feeds the checker a report and asserts it reads the four
things PLAN A4 asks for. The second is the half that matters over time: the
wording of those report lines is an interface between runtime/ and this tool,
and nothing links them, so these tests hold the C format strings themselves.
A line reworded in runtime/ without the pattern in tools/profile.py following
it fails here rather than silently producing a checker that reports SKIP for
the rest of the project's life.

Needs no disc: every report below is written out here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import profile as prof  # noqa: E402

RUNTIME = ROOT / "runtime"

# One healthy run's timing, in the exact shapes runtime/ prints. The numbers
# are build/boot_perf.log's, re-measured the way A4 says they should be.
HEALTHY = """\
[run] 4210 game frames, 8848 VI retraces (2.10 per frame; the game's 30 fps cap wants 2.00); 147.5 guest seconds at SOA_SPEED=10, 14.8 wall seconds
[irq] 8848 VI retraces, 12 DI completions, 4210 PE interrupts delivered; decrementer armed 0 times, fired 0
[gxr] producer over 14.81s by the time-stamp counter: setup 1.78s, prepare 0.95s, decode 2.09s, copy 0.01s, png 0.00s, wait 1.08s, raster 0.00s; the other 8.90s is guest code and the command-stream parse, which no clock can afford to separate and the profile below separates by sampling. These are disjoint, so they add up.
[gxr] workers: 8 threads, pool up 14.13s each = 113.04s of thread time; busy 71.29s + idle 41.61s = 112.90s, 0.1% unaccounted
[hle] 91827364 MMIO accesses over 148 registers; 840689485 bytes to the gather pipe; 0 syscalls
       102938  VI CC002002
[profile] 10412 samples at 703 Hz over 14.8s of wall clock, each weighted by the interval it covers; 1284 entries, 34% of the time named from config/functions.tsv (7144 rows, most of them still fn_XXXXXXXX). H = in an interrupt handler.
   28.4%  80237A5C SelectThread
   18.9%           [gx] command-stream parse
   14.1%           [gxr] texture decode
   12.0%           [gxr] vertex setup
    7.3%           [gxr] waiting for the workers
    6.4%           [gxr] TEV setup
    3.1%  8023F704 (no row in the inventory covers it) H
    2.8%  80232E38 DCInvalidateRange
    1.9%  80005520 memcpy
    1.2%  80005434 memset
    3.9%           the other 1274 entries
[profile] sampler against timers, widest of the 7 renderer phases: [gxr] texture decode 2.09s timed, 2.02s sampled, 0.5% of the run apart
"""


def test_the_checker_reads_a_healthy_report():
    p = prof.parse(HEALTHY, "build/perf.log")
    assert p.frames == 4210 and p.retraces == 8848
    assert p.guest_s == 147.5 and p.wall_s == 14.8 and p.speed == 10
    assert p.threads == 8 and p.busy_s == 71.29 and p.idle_s == 41.61
    assert p.clock == "time-stamp counter"
    assert p.phases["decode"] == 2.09 and p.phases["wait"] == 1.08
    assert p.producer_rest == 8.90
    assert p.samples == 10412 and p.rate_hz == 703.0
    assert len(p.rows) == 11
    assert p.rows[0].addr == "80237A5C" and p.rows[0].label == "SelectThread"
    assert p.rows[1].addr is None and p.rows[1].label == "[gx] command-stream parse"
    # The trailing "other entries" line is a row like any other: it is what
    # makes the printed shares add up to the whole run.
    assert p.rows[-1].label == "the other 1274 entries"


def test_the_three_invariants_one_log_carries():
    got = {c.name: c for c in prof.check(prof.parse(HEALTHY))}
    assert got["busy + idle is the pool's time"].status == prof.PASS
    assert got["the table sums to 100%"].status == prof.PASS
    assert got["frames, guest and wall are separate"].status == prof.PASS


def test_a_worker_stuck_inside_a_command_fails_the_identity():
    """Five per cent is the plan's allowance, and it is an allowance for the
    open stretch at the report -- not for a thread whose time went nowhere."""
    bad = HEALTHY.replace(
        "busy 71.29s + idle 41.61s = 112.90s, 0.1%", "busy 41.29s + idle 41.61s = 82.90s, 26.7%"
    )
    got = {c.name: c for c in prof.check(prof.parse(bad))}
    assert got["busy + idle is the pool's time"].status == prof.FAIL
    assert "26." in got["busy + idle is the pool's time"].detail


def test_a_table_that_does_not_sum_is_a_table_with_something_missing():
    bad = HEALTHY.replace("    3.9%           the other 1274 entries\n", "")
    got = {c.name: c for c in prof.check(prof.parse(bad))}
    assert got["the table sums to 100%"].status == prof.FAIL


def test_rounding_a_row_at_a_time_is_not_a_failure():
    """Sixteen rows printed to one decimal can miss 100.0 by most of a point
    without anything being wrong, and a checker that called that a failure
    would be a checker nobody ran twice."""
    p = prof.parse(HEALTHY)
    p.rows = [prof.Row(6.24, None, f"row {i}") for i in range(16)]
    got = {c.name: c for c in prof.check(p)}
    assert abs(sum(r.share for r in p.rows) - 100.0) > 0.1
    assert got["the table sums to 100%"].status == prof.PASS


def test_a_run_that_never_rendered_skips_the_worker_check_rather_than_failing():
    headless = "\n".join(line for line in HEALTHY.splitlines() if not line.startswith("[gxr]"))
    got = {c.name: c for c in prof.check(prof.parse(headless))}
    assert got["busy + idle is the pool's time"].status == prof.SKIP
    assert got["frames, guest and wall are separate"].status == prof.PASS


def test_the_run_line_survives_a_run_that_presented_no_frame():
    p = prof.parse(
        "[run] 0 game frames, 0 VI retraces; 0.0 guest seconds at SOA_SPEED=1, 3.2 wall seconds\n"
    )
    assert p.frames == 0 and p.wall_s == 3.2 and p.speed == 1


def test_guest_seconds_that_are_not_wall_times_speed_are_called_out():
    """They are the same quantity by construction -- hle.c multiplies a real
    clock -- so a pair that disagrees means one of the two clocks started
    somewhere other than where the report says."""
    odd = HEALTHY.replace("147.5 guest seconds", "3.2 guest seconds")
    got = {c.name: c for c in prof.check(prof.parse(odd))}
    assert got["frames, guest and wall are separate"].status == prof.PASS
    assert "one clock started late" in got["frames, guest and wall are separate"].detail


def test_two_runs_of_one_scenario_name_the_same_ten():
    a = prof.parse(HEALTHY, "a.log")
    lines = HEALTHY.splitlines()
    top = lines.index("   28.4%  80237A5C SelectThread")
    lines[top] = "   28.4%           [gx] command-stream parse"
    lines[top + 1] = "   18.9%  80237A5C SelectThread"
    b = prof.parse("\n".join(lines), "b.log")
    c = prof.compare(a, b)
    assert c.status == prof.PASS
    # The order inside the ten moved; that is sampling noise, not a difference.
    assert a.top[:2] != b.top[:2] and set(a.top) == set(b.top)
    assert "different order" in c.detail


def test_a_top_ten_that_gained_an_entry_is_a_difference():
    a = prof.parse(HEALTHY, "a.log")
    b = prof.parse(HEALTHY.replace("80005434 memset", "801C6248 fn_801C6248"), "b.log")
    c = prof.compare(a, b)
    assert c.status == prof.FAIL
    assert "memset" in c.detail and "fn_801C6248" in c.detail


def test_the_cli_reports_and_exits_nonzero_on_a_failure(tmp_path, capsys):
    good = tmp_path / "a.log"
    good.write_text(HEALTHY, encoding="utf-8")
    assert prof.main([str(good)]) == 0
    bad = tmp_path / "b.log"
    bad.write_text(
        HEALTHY.replace("busy 71.29s + idle 41.61s", "busy 41.29s + idle 41.61s"), encoding="utf-8"
    )
    assert prof.main([str(bad)]) == 1
    assert prof.main([str(good), str(good)]) == 0
    out = capsys.readouterr().out
    assert "the same top ten twice" in out


# --------------------------------------------------------------------------
# the half that holds runtime/ and this tool together
# --------------------------------------------------------------------------

# Each entry: the file that prints it, and a piece of the C format string that
# tools/profile.py's pattern for that line depends on.
WORDING = [
    ("hle.c", '"[run] %u game frames, %llu VI retraces"'),
    ("hle.c", '"; %.1f guest seconds at SOA_SPEED=%u, %.1f wall seconds'),
    (
        "gxr.c",
        '"[gxr] producer over %.2fs by the %s: setup %.2fs, prepare %.2fs, decode %.2fs, '
        "copy %.2fs, png %.2fs, wait %.2fs, raster %.2fs; the other %.2fs is",
    ),
    (
        "gxr.c",
        '"[gxr] workers: %d threads, pool up %.2fs each = %.2fs of thread time; '
        "busy %.2fs + idle %.2fs = %.2fs, %.1f%% unaccounted",
    ),
    ("main.c", '"[profile] %llu samples at %.0f Hz over %.1fs of wall clock'),
    ("main.c", '"  %5.1f%%  %08X %s%s'),
    ("main.c", '"  %5.1f%%           %s'),
]


@pytest.mark.parametrize(("name", "fragment"), WORDING, ids=lambda v: v[:24])
def test_the_report_still_says_what_the_checker_reads(name, fragment):
    assert fragment in (RUNTIME / name).read_text(encoding="utf-8"), (
        f"runtime/{name} no longer prints {fragment!r}; tools/profile.py parses that line, "
        "so the pattern there has to move with it"
    )


def test_the_watchdog_no_longer_owns_the_samples():
    """The old sampler was the watchdog's second job: it zeroed its samples on
    every presented frame and printed only from the stall path, which is why
    all 22 saved profiles cover a stall and no healthy run has one."""
    main_c = (RUNTIME / "main.c").read_text(encoding="utf-8")
    assert "g_samples" not in main_c
    assert "profile_report();" in (RUNTIME / "hle.c").read_text(encoding="utf-8")
