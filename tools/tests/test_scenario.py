"""Scenario library and run-checker tests.

The checker's job is to read a run's own report, and the report only exists
when the port runs, which needs a disc and a built executable. So the report
text here is synthesised: every line is copied from the fprintf that produces
it -- gx_report() in runtime/gx.c, gxr_report() in runtime/gxr.c, note() in
runtime/hle.c -- with the counters changed. That is what makes the parsing
testable in CI, where there is no game. The replay sweep is tested the same
way: the port is replaced by a function that returns the text a replay would
have printed, so the sweep's own logic is what is under test.
"""

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

spec = importlib.util.spec_from_file_location(
    "scenario", Path(__file__).resolve().parents[1] / "scenario.py"
)
scenario = importlib.util.module_from_spec(spec)
# dataclasses resolve their annotations through sys.modules, so register the
# module before executing it.
sys.modules["scenario"] = scenario
spec.loader.exec_module(scenario)

ScenarioError = scenario.ScenarioError


# --------------------------------------------------------------------------
# fixtures: a report shaped exactly like a real one
# --------------------------------------------------------------------------

GX_LINE = (
    "[gx] {pipe} pipe bytes, 41747507 commands: 16112933 BP, 12646871 XF, 9012939 CP loads, "
    "13280 display lists, 1799367 draws ({verts} vertices); 1 draw-dones, 7514 tokens, "
    "3910 EFB copies, {unknown} unknown bytes"
)
GXR_LINE = (
    "[gxr] 135554 triangles, 0 lines, 0 points; 88991241 pixels shaded (0 outside, "
    "31489057 failed alpha, 713115 failed depth); 54402 clipped away; {bad} bad vertex refs; "
    "243 texture copies, 3758 screen copies"
)


def report_text(
    *,
    events=2,
    pipe=647294778,
    verts=9950430,
    unknown=0,
    bad=0,
    rendered=True,
    frames=2000,
    extra=(),
):
    lines = [
        "[boot] DOL 3166656 bytes, FST 134426 bytes at 816DF2E0; entering fn_80003140",
        "[run] headless; stopping after 2000 frames",
    ]
    if events is not None:
        lines.append(f"[si] {events} scripted controller events")
    lines.extend(extra)
    if frames is not None:
        lines.append(f"[boot] {frames} frames done (SOA_FRAMES)")
    lines.append("[irq] 7824 VI retraces, 345 DI completions, 7515 PE interrupts delivered")
    lines.append(GX_LINE.format(pipe=pipe, verts=verts, unknown=unknown))
    if rendered:
        lines.append(
            "[gxr] time: draw 0.27s (prepare 0.18s, decode 0.13s), copies 1.65s, png 0.51s"
        )
        lines.append(GXR_LINE.format(bad=bad))
    lines.append(
        "[hle] 1228948 MMIO accesses over 85 registers; 647294778 bytes to the gather pipe"
    )
    return "\n".join(lines) + "\n"


SCN = """\
# a comment
name: demo
summary: Two presses and a repeat.
frames: 4000
pad: 1600:start,1640:a
pad: 3600:a@150
env: SOA_RENDER=1
env: SOA_SNAP=50
shows: that the parser keeps prose lines in order.
shows: and joins nothing it should not.
evidence: build/boot_demo.log
note: synthesised for the tests.
"""


def write_scn(tmp_path, text, name="demo.scn"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# the pad grammar (script_init in runtime/si.c)
# --------------------------------------------------------------------------


def test_pad_parses_presses_repeats_holds_and_the_stick():
    events = scenario.parse_pad("1600:start,3600:a@150,9000:sup#120,4000:a+b+sleft@900#300")
    assert [e.frame for e in events] == [1600, 3600, 9000, 4000]
    assert events[0].buttons == ("start",) and events[0].every == 0 and events[0].hold == 10
    assert events[1].every == 150
    assert events[2].sticks == ("sup",) and events[2].hold == 120
    assert events[3].buttons == ("a", "b") and events[3].sticks == ("sleft",)
    assert events[3].every == 900 and events[3].hold == 300


def test_pad_takes_one_trailing_comma_because_si_does():
    """script_init() steps over the comma after each event and then finds the
    end of the string, so "100:a,200:b," is two events there too."""
    assert len(scenario.parse_pad("100:a,200:b,")) == 2
    assert scenario.parse_pad("") == []  # no script: si.c presses nothing and says nothing


@pytest.mark.parametrize(
    "script",
    [
        "5:start ,9:a",  # si.c looks up a button called "start ", finds none, presses nothing
        "5:start, 9:a",
        " 5:start",
        "5: start",
        "5:a\t+b",
        "5:start ",  # at the very end of the script it is still inside the last item
        "5:a#10 ",  # and after a number si.c stops at it, and says it did not understand
        "5:a\n",
    ],
)
def test_pad_refuses_whitespace_because_si_does_not_strip_it(script):
    with pytest.raises(ScenarioError, match="whitespace"):
        scenario.parse_pad(script)


@pytest.mark.parametrize(
    "script",
    [
        "1700:start,,1800:a",  # si.c stops at the empty item: 1800:a never happens
        ",1700:start",  # and here it stops before the first, so nothing is pressed
        "1700:start,,",  # two trailing commas are one trailing comma and an empty item
        ",",
    ],
)
def test_pad_refuses_an_empty_item_because_si_stops_there(script):
    with pytest.raises(ScenarioError, match="empty item"):
        scenario.parse_pad(script)


def test_pad_takes_a_hold_longer_than_its_repeat_and_says_what_it_means():
    """buttons_now() in si.c takes the frame modulo the repeat and compares it
    with the hold, so a hold at least as long as the period never releases.
    That is a script si.c runs exactly as written, not one it drops."""
    (event,) = scenario.parse_pad("1600:a@150#900")
    assert event.every == 150 and event.hold == 900
    assert "held down for good" in scenario.describe_event(event)


@pytest.mark.parametrize(
    "script",
    [
        "1600:fire",  # si.c presses nothing and does not say so
        "1600",  # no colon: si.c stops here, the rest of the script ignored
        "1600:",  # no buttons at all
        "abc:a",  # frame is not a number, so si.c stops here too
        "1600:a#",  # a hold with no number, and a repeat with none
        "1600:a@",
        "1600:a#x",
        "١٦٠٠:a",  # digits to Python's \d and int(), not to strtoul
        "1600:a#١",
    ],
)
def test_pad_refuses_what_si_would_silently_drop(script):
    with pytest.raises(ScenarioError):
        scenario.parse_pad(script)


def test_pad_refuses_a_trailing_plus_and_spells_out_what_si_reads():
    """si.c does run this one, as "a" -- but a scenario file that says
    something other than what ran is the thing this library exists to end."""
    with pytest.raises(ScenarioError, match="1600:a, so write it that way"):
        scenario.parse_pad("1600:a+")


def test_pad_refuses_more_events_than_si_keeps():
    script = ",".join(f"{i}:a" for i in range(scenario.MAX_EVENTS + 1))
    with pytest.raises(ScenarioError):
        scenario.parse_pad(script)


# --------------------------------------------------------------------------
# the scenario file
# --------------------------------------------------------------------------


def test_scenario_parses(tmp_path):
    sc = scenario.parse_scenario(SCN, write_scn(tmp_path, SCN))
    assert sc.name == "demo" and sc.frames == 4000
    assert sc.pad == "1600:start,1640:a,3600:a@150"  # the two pad: lines joined
    assert sc.env == {"SOA_RENDER": "1", "SOA_SNAP": "50"}
    assert sc.rendering is True
    assert len(sc.shows) == 2 and sc.evidence == ["build/boot_demo.log"]
    assert [e.frame for e in sc.events] == [1600, 1640, 3600]


def test_scenario_without_render_does_not_claim_to_draw(tmp_path):
    text = SCN.replace("env: SOA_RENDER=1\n", "")
    assert scenario.parse_scenario(text, write_scn(tmp_path, text)).rendering is False


def test_rendering_means_what_atoi_means(tmp_path):
    """gxr_enabled() in gxr.c reads SOA_RENDER through atoi(), so SOA_RENDER=yes
    draws nothing. Demanding a [gxr] line it will never print would fail the run
    for the tool's reason rather than the run's."""
    text = SCN.replace("env: SOA_RENDER=1", "env: SOA_RENDER=yes")
    assert scenario.parse_scenario(text, write_scn(tmp_path, text)).rendering is False
    assert scenario.c_atoi("0") == 0 and scenario.c_atoi("") == 0
    assert scenario.c_atoi(" 2 workers") == 2 and scenario.c_atoi("-1") == -1


@pytest.mark.parametrize(
    "mutation",
    [
        ("name: demo", "name: other"),  # must match the file stem
        ("frames: 4000", "frames: 0"),
        ("frames: 4000", "frames: soon"),
        ("env: SOA_SNAP=50", "env: SOA_FRAMES=4000"),  # frames: owns that one
        ("env: SOA_SNAP=50", "env: SOA_SNAP"),
        ("summary: Two presses and a repeat.", "sumary: typo."),
        ("pad: 1600:start,1640:a", "pad: 1600:fire"),
        # the pad: lines are joined, and the joined script is what si.c reads
        ("pad: 1600:start,1640:a", "pad: 1600:start ,1640:a"),
        ("pad: 1600:start,1640:a", "pad: 1600:start,,1640:a"),
        ("pad: 3600:a@150", "pad: , 3600:a@150"),
    ],
)
def test_scenario_rejects(tmp_path, mutation):
    text = SCN.replace(*mutation)
    with pytest.raises(ScenarioError):
        scenario.parse_scenario(text, write_scn(tmp_path, text))


def test_scenario_needs_its_required_keys(tmp_path):
    text = SCN.replace("pad: 1600:start,1640:a\npad: 3600:a@150\n", "")
    with pytest.raises(ScenarioError):
        scenario.parse_scenario(text, write_scn(tmp_path, text))


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def test_report_reads_the_counters_out_of_a_clean_run():
    r = scenario.parse_report(report_text())
    assert (r.unknown_bytes, r.bad_vertex_refs, r.unmodelled) == (0, 0, 0)
    assert r.pipe_bytes == 647294778 and r.vertices == 9950430
    assert r.rendered is True and r.frames_done == 2000 and r.scripted_events == 2
    assert r.stop_lines == []


def test_report_counts_unmodelled_accesses_and_keeps_the_first():
    extra = [
        "[mmio!] wr E0C0C2E7/4 = 0 (outside modelled range)",
        "[mmio!] rd E0C0C2EB/4 = 0 (outside modelled range)",
    ]
    r = scenario.parse_report(report_text(extra=extra))
    assert r.unmodelled == 2
    assert r.first_unmodelled.startswith("[mmio!] wr E0C0C2E7")


def test_report_notices_a_strict_stop_and_a_stall():
    strict = scenario.parse_report(
        report_text(
            frames=None,
            extra=[
                "[mmio!] wr E0C0C2E7/4 = 0 (outside modelled range)",
                "[strict] pc 801C3110 lr 801C30E0; backtrace: 801DC4DC",
            ],
        )
    )
    assert strict.strict_stopped is True and strict.frames_done is None
    stalled = scenario.parse_report(
        report_text(frames=None, extra=["[watchdog] no video frame for 20s; 512 frames so far"])
    )
    assert stalled.stop_lines and stalled.stop_lines[0].startswith("[watchdog]")


def test_a_healthy_watchdog_notice_is_not_a_termination():
    """main.c prints both of these while a run is starting normally. Reading
    either as the end of the run names a healthy notice as the cause of a
    failure -- and stop_lines[0] means the first one wins."""
    text = report_text(
        frames=None,
        extra=[
            "[watchdog] cannot start the watchdog thread; nothing will time this run out",
            "[watchdog] no window after all; arming the headless default",
            "[unimplemented] bctr-unresolved at 801C3110",
        ],
    )
    r = scenario.parse_report(text)
    assert r.stop_lines == ["[unimplemented] bctr-unresolved at 801C3110"]
    detail = next(
        c for c in scenario.check_report(r, None, True, 2) if c.name.startswith("the run")
    )
    assert "unimplemented" in detail.detail


def test_the_older_watchdogs_line_still_reads_as_a_stop():
    """Every log in build/ ends at "[watchdog] still running after Ns", which
    runtime/ no longer prints; `check` is pointed at those logs."""
    r = scenario.parse_report(
        report_text(frames=None, extra=["[watchdog] still running after 120s; last block 8029D698"])
    )
    assert r.stop_lines and "still running" in r.stop_lines[0]


def test_report_leaves_absent_counters_as_none_rather_than_zero():
    r = scenario.parse_report("[boot] DOL 3166656 bytes\n")
    assert r.unknown_bytes is None and r.bad_vertex_refs is None
    assert r.rendered is False and r.scripted_events is None


def test_report_sees_a_pad_script_the_port_did_not_understand():
    complaint = '[si] SOA_PAD not understood from "1700:fire" on; that part is ignored'
    r = scenario.parse_report(report_text(extra=[complaint]))
    assert r.pad_trouble == complaint


# --------------------------------------------------------------------------
# the four invariants
# --------------------------------------------------------------------------


def status(checks, name):
    return next(c.status for c in checks if c.name.startswith(name))


def test_a_clean_run_passes_every_invariant():
    checks = scenario.check_report(scenario.parse_report(report_text()), 0, True, 2)
    assert all(c.status == scenario.PASS for c in checks)


def test_unknown_fifo_bytes_fail():
    checks = scenario.check_report(scenario.parse_report(report_text(unknown=12)), 0, True, 2)
    assert status(checks, "no unknown FIFO") == scenario.FAIL


def test_bad_vertex_refs_fail():
    checks = scenario.check_report(scenario.parse_report(report_text(bad=3)), 0, True, 2)
    assert status(checks, "no bad vertex") == scenario.FAIL


def test_an_unmodelled_access_fails_even_when_the_run_finished():
    text = report_text(extra=["[mmio!] wr E0C0C2E7/4 = 0 (outside modelled range)"])
    checks = scenario.check_report(scenario.parse_report(text), 0, True, 2)
    assert status(checks, "the run exits 0") == scenario.PASS
    assert status(checks, "no MMIO outside") == scenario.FAIL


def test_exit_8_is_read_as_the_mmio_invariant_not_just_a_bad_exit():
    text = report_text(
        frames=None,
        extra=[
            "[mmio!] wr E0C0C2E7/4 = 0 (outside modelled range)",
            "[strict] pc 801C3110 lr 801C30E0; backtrace: 801DC4DC",
        ],
    )
    checks = scenario.check_report(scenario.parse_report(text), 8, True, 2)
    mmio = next(c for c in checks if c.name.startswith("no MMIO"))
    assert mmio.status == scenario.FAIL and "E0C0C2E7" in mmio.detail
    # One broken thing, named once: the exit check stands aside and points at it.
    exit_check = next(c for c in checks if c.name.startswith("the run exits"))
    assert exit_check.status == scenario.SKIP and "MMIO invariant" in exit_check.detail
    assert [c.name for c in checks if c.status == scenario.FAIL] == [
        "no MMIO outside the modelled range"
    ]


def test_a_run_that_drew_nothing_does_not_pass_the_renderer_invariant():
    """0 bad vertex refs over 0 triangles is a counter that is right about
    nothing: a renderer that drew every pixel black would have the same one."""
    text = report_text().replace("[gxr] 135554 triangles", "[gxr] 0 triangles")
    checks = scenario.check_report(scenario.parse_report(text), 0, True, 2)
    assert status(checks, "no bad vertex") == scenario.FAIL
    # and with no renderer asked for, there is nothing to say
    assert status(scenario.check_report(scenario.parse_report(text), 0, False, 2), "no bad") == (
        scenario.PASS
    )


def test_a_run_that_pushed_no_commands_does_not_pass_the_fifo_invariant():
    text = report_text(pipe=0)
    assert status(scenario.check_report(scenario.parse_report(text), 0, True, 2), "no unknown") == (
        scenario.FAIL
    )


def test_a_killed_run_is_the_tools_doing_not_the_ports():
    """Popen.kill() leaves exit code 1 on Windows, which is also "the extracted
    disc did not load". --timeout has to say which of the two happened."""
    checks = scenario.check_report(
        scenario.parse_report(report_text(frames=None)), 1, True, 2, 30.0
    )
    exit_check = next(c for c in checks if c.name.startswith("the run exits"))
    assert exit_check.status == scenario.FAIL
    assert "--timeout" in exit_check.detail and "disc" not in exit_check.detail


def test_every_documented_exit_code_is_explained():
    for code in (2, 3, 4, 5, 6):
        checks = scenario.check_report(scenario.parse_report(report_text()), code, True, 2)
        detail = next(c for c in checks if c.name.startswith("the run exits")).detail
        assert scenario.EXIT_MEANINGS[code] in detail


def test_a_headless_scenario_skips_the_renderer_invariant():
    r = scenario.parse_report(report_text(rendered=False))
    assert status(scenario.check_report(r, 0, False, 2), "no bad vertex") == scenario.SKIP
    # but a scenario that asked for a renderer and got no [gxr] line has a problem
    assert status(scenario.check_report(r, 0, True, 2), "no bad vertex") == scenario.FAIL


def test_a_run_that_never_reported_fails_rather_than_passes():
    checks = scenario.check_report(scenario.parse_report("[boot] DOL\n"), 5, False, 2)
    assert status(checks, "no unknown FIFO") == scenario.FAIL


def test_the_script_check_compares_what_the_port_read_with_the_scenario():
    r = scenario.parse_report(report_text(events=17))
    assert status(scenario.check_report(r, 0, True, 19), "the pad script") == scenario.FAIL
    assert status(scenario.check_report(r, 0, True, 17), "the pad script") == scenario.PASS


def test_a_saved_log_without_an_exit_code_is_judged_by_its_own_words():
    finished = scenario.check_report(scenario.parse_report(report_text()), None, True, 2)
    assert status(finished, "the run exits 0") == scenario.PASS
    stalled = scenario.parse_report(
        report_text(frames=None, extra=["[watchdog] no video frame for 20s"])
    )
    assert status(scenario.check_report(stalled, None, True, 2), "the run exits 0") == scenario.FAIL
    quiet = scenario.parse_report(report_text(frames=None))
    assert status(scenario.check_report(quiet, None, True, 2), "the run exits 0") == scenario.SKIP


# --------------------------------------------------------------------------
# the command line, and degrading honestly
# --------------------------------------------------------------------------


def test_command_lines_say_the_same_thing_in_three_shells(tmp_path):
    sc = scenario.parse_scenario(SCN, write_scn(tmp_path, SCN))
    env = scenario.run_env(sc, strict=True)
    assert env["SOA_FRAMES"] == "4000" and env["SOA_STRICT"] == "1"
    ps = scenario.command_lines(env, "gen/soa.exe", "extracted", "powershell")
    assert ps[0] == "$env:SOA_PAD='1600:start,1640:a,3600:a@150'"
    assert ps[-1] == "gen\\soa.exe extracted"
    assert scenario.command_lines(env, "gen/soa.exe", "extracted", "cmd")[0].startswith(
        "set SOA_PAD="
    )
    assert (
        scenario.command_lines(env, "gen/soa.exe", "extracted", "sh")[-1] == "gen/soa.exe extracted"
    )


def test_missing_inputs_names_each_thing_that_is_missing(tmp_path):
    missing = scenario.missing_inputs(tmp_path / "soa.exe", tmp_path / "extracted")
    assert len(missing) == 2
    assert "recompile.py" in missing[0] and "extract.py" in missing[1]
    (tmp_path / "extracted" / "sys").mkdir(parents=True)
    for name in ("main.dol", "boot.bin"):
        (tmp_path / "extracted" / "sys" / name).write_bytes(b"")
    missing = scenario.missing_inputs(tmp_path / "soa.exe", tmp_path / "extracted")
    assert len(missing) == 3  # the executable, then the two files still absent
    assert "fst.bin" in missing[1] and "the boot path needs it" in missing[1]
    assert "disc.iso" in missing[2] and "every asset read would return zeros" in missing[2]


# --------------------------------------------------------------------------
# the library itself
# --------------------------------------------------------------------------


def test_every_committed_scenario_is_usable():
    scenarios = scenario.load_all()
    assert len(scenarios) >= 8, "the library should not lose scenarios silently"
    for sc in scenarios:
        assert sc.name == sc.path.stem
        assert sc.summary and sc.frames > 0
        assert sc.events, f"{sc.name} drives no buttons"
        assert sc.evidence, f"{sc.name} says where it came from"
        assert max(e.frame for e in sc.events) < sc.frames, (
            f"{sc.name} presses buttons after its last frame"
        )


def test_the_title_scenario_is_the_one_in_the_saved_log():
    sc = scenario.load_scenario("title")
    assert sc.pad == "1600:start,1640:a"
    assert [(e.frame, e.buttons) for e in sc.events] == [(1600, ("start",)), (1640, ("a",))]


def test_the_runner_tees_a_child_into_its_log(tmp_path):
    """The run path itself, with a stand-in for the port: it streams, it logs,
    and it hands back both the exit code and the text the checks read."""
    log = tmp_path / "run.log"
    program = (
        "import sys;"
        "print('[boot] DOL 3166656 bytes', file=sys.stderr);"
        "print('[boot] 2000 frames done (SOA_FRAMES)', file=sys.stderr);"
        "sys.exit(3)"
    )
    code, text, killed = scenario.stream_run(
        [sys.executable, "-c", program], os.environ.copy(), log, "none", 0
    )
    assert code == 3 and killed is False
    assert log.read_text(encoding="utf-8").splitlines() == text.splitlines()
    assert scenario.parse_report(text).frames_done == 2000


def test_the_runner_says_when_it_was_the_one_that_ended_the_run(tmp_path):
    """--timeout kills the child; the exit code that leaves behind is the
    operating system's, so the caller is told what really happened."""
    log = tmp_path / "slow.log"
    program = "import time; time.sleep(30)"
    code, _, killed = scenario.stream_run(
        [sys.executable, "-c", program], os.environ.copy(), log, "none", 1.0
    )
    assert killed is True and code != 0


def test_the_checks_are_four_invariants_and_one_look_at_the_input():
    checks = scenario.check_report(scenario.parse_report(report_text()), 0, True, 2)
    assert sum(c.invariant for c in checks) == 4
    assert [c.name for c in checks if not c.invariant] == ["the pad script was understood"]


def run_args(tmp_path, **changes):
    data = tmp_path / "extracted"
    if not data.exists():
        (data / "sys").mkdir(parents=True)
        for rel in scenario.NEEDED_FILES:
            (data / rel).write_bytes(b"")
    args = {
        "name": "title",
        "dir": str(scenario.SCENARIO_DIR),
        "check": True,
        "no_strict": True,
        "frames": 1,
        "env": [],
        "exe": sys.executable,
        "data": str(data),
        "log": str(tmp_path / "run.log"),
        "timeout": 0,
        "quiet": True,
        "verbose": False,
    }
    return argparse.Namespace(**{**args, **changes})


def test_running_a_scenario_against_something_that_is_not_the_port(tmp_path, monkeypatch):
    """cmd_run end to end with the interpreter standing in for gen/soa.exe: the
    prerequisites are found, the child runs, and a child that reports nothing
    fails the checks instead of passing them by default."""
    # cmd_run makes the directories the capture path and the memory card write
    # into, which belong beside the port; point the whole run at tmp_path so
    # the test leaves nothing in the checkout.
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    assert scenario.cmd_run(run_args(tmp_path)) == 1
    assert (tmp_path / "run.log").exists()
    assert (tmp_path / "build" / "fifo").is_dir()


def test_an_env_override_is_what_the_checks_are_told_about(tmp_path, monkeypatch):
    """--env SOA_PAD=... really does replace the script the port reads, so
    expecting the scenario file's own event count would fail a check that is
    measuring the wrong run."""
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    seen = {}

    def fake_run(argv, env, log, echo, timeout):
        seen.update(env)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        return 0, report_text(events=3), False

    monkeypatch.setattr(scenario, "stream_run", fake_run)
    args = run_args(tmp_path, env=["SOA_PAD=1600:start,1640:a,14000:sup#900"], frames=None)
    checks = []
    monkeypatch.setattr(scenario, "print_checks", lambda c, label: checks.extend(c) or 0)
    assert scenario.cmd_run(args) == 0
    assert seen["SOA_PAD"] == "1600:start,1640:a,14000:sup#900"
    assert status(checks, "the pad script") == scenario.PASS


@pytest.mark.parametrize(
    "fifo_dir",
    [
        None,  # dump_dir() in gx.c falls back to build/fifo
        "",  # and so does an empty value
        "build/fifo",
        "build/fifo/",
        "./build/../build/fifo",
        "ABSOLUTE",  # the same directory, spelled from the drive root
    ],
)
def test_a_capture_into_the_pinned_corpus_is_refused(tmp_path, monkeypatch, fifo_dir):
    """The test suite once ran a capture with no SOA_FIFO_DIR and overwrote
    three captures in build/fifo, the corpus config/fifo_manifest.tsv pins.
    They are game data, so nothing could restore them. However the directory
    is spelled, a capture into it never starts."""
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    ran = []
    monkeypatch.setattr(scenario, "stream_run", lambda *a: ran.append(a) or (0, "", False))
    env = ["SOA_FIFO_DUMP=3600"]
    if fifo_dir is not None:
        spelled = str(tmp_path / "build" / "fifo") if fifo_dir == "ABSOLUTE" else fifo_dir
        env.append(f"SOA_FIFO_DIR={spelled}")
    with pytest.raises(ScenarioError, match="SOA_FIFO_DIR"):
        scenario.cmd_run(run_args(tmp_path, env=env, check=False))
    assert ran == [], "the port was started anyway"


def test_a_capture_somewhere_else_runs(tmp_path, monkeypatch):
    """capture.scn as committed: it names build/fifo-new, so it runs, and a
    run that captures nothing may leave SOA_FIFO_DIR alone."""
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    ran = []
    monkeypatch.setattr(scenario, "stream_run", lambda *a: ran.append(a) or (0, "", False))
    assert scenario.cmd_run(run_args(tmp_path, name="capture", check=False)) == 0
    assert scenario.cmd_run(run_args(tmp_path, check=False)) == 0
    assert len(ran) == 2
    # and an --env that points the committed scenario back at the corpus is refused
    with pytest.raises(ScenarioError, match="SOA_FIFO_DIR"):
        scenario.cmd_run(run_args(tmp_path, name="capture", env=["SOA_FIFO_DIR="], check=False))


def test_no_committed_scenario_captures_into_the_corpus():
    for sc in scenario.load_all():
        scenario.refuse_capture_into_corpus(scenario.run_env(sc))


def test_the_command_line_entry_points_work():
    assert scenario.main(["list"]) == 0
    assert scenario.main(["show", "title", "--command"]) == 0
    assert scenario.main(["show", "nosuch"]) == 2
    assert scenario.main(["check", "no/such/log.log"]) == 2


# --------------------------------------------------------------------------
# the replay sweep
# --------------------------------------------------------------------------

# enqueue_copy() in runtime/gxr.c, with the digits changed.
HASH_LINE = "[gxr] frame 3600 640x480 hash 63a57c77609efd77"
REPLAY_TEXT = (
    f"[gxr] rasterizing on 3 worker threads\n{HASH_LINE}\n[gx] replayed 118432 of 118432 bytes\n"
)


def make_capture(directory, name, parts=scenario.PARTS):
    directory.mkdir(parents=True, exist_ok=True)
    for ext in parts:
        (directory / (name + ext)).write_bytes(f"{name}{ext}".encode())
    return directory / name


def test_the_hash_line_is_the_one_the_runtime_prints():
    assert scenario.frame_hashes(REPLAY_TEXT) == ["63a57c77609efd77"]
    assert scenario.frame_hashes("[gxr] 12 triangles, 0 lines\n") == []


def test_a_capture_is_all_three_of_its_files(tmp_path):
    whole = make_capture(tmp_path, "0100")
    make_capture(tmp_path, "0300", parts=(".fifo", ".regs"))
    captures, partial = scenario.find_captures(tmp_path)
    assert [c.name for c in captures] == ["0100"]
    assert partial and "0300" in partial[0] and ".ram" in partial[0]
    # and the key follows the bytes, which is the whole reason it is there
    key = scenario.capture_key(whole)
    assert len(key) == scenario.KEY_DIGITS
    whole.with_suffix(".ram").write_bytes(b"something else")
    assert scenario.capture_key(whole) != key


def test_a_sweep_that_agrees_with_itself_yields_one_hash_per_capture(tmp_path):
    captures = [make_capture(tmp_path, n) for n in ("0100", "0300")]
    hashes, problems = scenario.sweep(
        captures, (1, 8), 2, lambda base, t: (0, REPLAY_TEXT), echo=lambda *a: None
    )
    assert problems == []
    assert set(hashes) == {"0100", "0300"}


def test_a_hash_that_moves_with_the_thread_count_is_the_point(tmp_path):
    """A frame that depends on how many workers drew it is a race in the
    rasterizer's row ownership, which is what sweeping the thread counts is
    for."""
    captures = [make_capture(tmp_path, "0100")]

    def run(base, threads):
        return 0, REPLAY_TEXT.replace(
            "63a57c77609efd77", "ffffffffffffffff" if threads == 8 else "63a57c77609efd77"
        )

    _, problems = scenario.sweep(captures, (1, 8), 1, run, echo=lambda *a: None)
    assert len(problems) == 1 and "SOA_THREADS=8" in problems[0]


def test_a_replay_that_rendered_nothing_is_not_silently_recorded(tmp_path):
    """gx_replay() returns 1 and says which file it could not open; a sweep
    that grepped for a hash would record nothing and call it agreement."""
    captures = [make_capture(tmp_path, "0100")]
    hashes, problems = scenario.sweep(
        captures,
        (1,),
        1,
        lambda base, t: (1, "[gx] cannot open build/fifo/0100.ram\n"),
        echo=lambda *a: None,
    )
    assert hashes == {}
    assert len(problems) == 2 and "exit 1" in problems[0] and "0 hash lines" in problems[1]


def test_the_manifest_round_trips_and_names_every_way_it_can_differ(tmp_path):
    path = tmp_path / "fifo_manifest.tsv"
    blessed = {"0100": ("aaaa000000000000", "1111111111111111"), "0300": ("bbbb", "2222")}
    scenario.write_manifest(path, blessed)
    assert scenario.read_manifest(path) == blessed
    assert path.read_text(encoding="utf-8").startswith("#")

    lines, bad = scenario.compare_manifest(blessed, blessed)
    assert bad == 0 and all(line.startswith("  ok") for line in lines)

    moved = {**blessed, "0300": ("bbbb", "9999")}
    lines, bad = scenario.compare_manifest(moved, blessed)
    assert bad == 1 and any("DIFFS 0300" in line for line in lines)

    other_machine = {**blessed, "0300": ("cccc", "9999")}
    lines, bad = scenario.compare_manifest(other_machine, blessed)
    assert bad == 1 and any("a different capture" in line for line in lines)

    lines, bad = scenario.compare_manifest({"0400": ("dddd", "3333")}, blessed)
    assert bad == 3  # one unblessed capture, and two the manifest has and this machine does not


def test_the_reference_pngs_survive_the_first_sweep(tmp_path):
    """--replay overwrites <base>.png, and 13 of those are the only reference
    frames anyone has."""
    (tmp_path / "0100.png").write_bytes(b"not really a png")
    scenario.keep_reference_pngs(tmp_path, echo=lambda *a: None)
    assert (tmp_path / "ref-before" / "0100.png").read_bytes() == b"not really a png"
    (tmp_path / "0100.png").write_bytes(b"overwritten")
    scenario.keep_reference_pngs(tmp_path, echo=lambda *a: None)  # never a second time
    assert (tmp_path / "ref-before" / "0100.png").read_bytes() == b"not really a png"


def test_replay_blesses_a_clean_sweep_and_then_holds_the_port_to_it(tmp_path, monkeypatch):
    """The whole command, with a stand-in for the port: the first sweep writes
    the manifest, the next one agrees with it, and a frame that comes out
    different afterwards fails."""
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    monkeypatch.setattr(scenario, "MANIFEST", tmp_path / "fifo_manifest.tsv")
    (tmp_path / "gen").mkdir()
    (tmp_path / "gen" / "soa.exe").write_bytes(b"")
    data = tmp_path / "extracted"
    (data / "sys").mkdir(parents=True)
    for rel in scenario.NEEDED_FILES:
        (data / rel).write_bytes(b"")
    fifo = tmp_path / "build" / "fifo"
    make_capture(fifo, "0100")
    monkeypatch.setattr(scenario, "replay_once", lambda exe, base, t: (0, REPLAY_TEXT))
    args = argparse.Namespace(
        exe="gen/soa.exe", fifo=str(fifo), threads="1,2", passes=1, bless=True
    )
    assert scenario.cmd_replay(args) == 0
    assert scenario.MANIFEST.exists()

    args.bless = False
    assert scenario.cmd_replay(args) == 0

    changed = REPLAY_TEXT.replace("63a57c77609efd77", "0000000000000000")
    monkeypatch.setattr(scenario, "replay_once", lambda exe, base, t: (0, changed))
    assert scenario.cmd_replay(args) == 1


def test_bless_from_anywhere_but_the_corpus_is_refused(tmp_path, monkeypatch):
    """The manifest pins build/fifo and nothing else. Blessing a sweep of
    build/fifo-new would rewrite it with that directory's rows alone, and
    every pinned capture would drop out of it without a word."""
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    monkeypatch.setattr(scenario, "MANIFEST", tmp_path / "fifo_manifest.tsv")
    (tmp_path / "gen").mkdir()
    (tmp_path / "gen" / "soa.exe").write_bytes(b"")
    data = tmp_path / "extracted"
    (data / "sys").mkdir(parents=True)
    for rel in scenario.NEEDED_FILES:
        (data / rel).write_bytes(b"")
    make_capture(tmp_path / "build" / "fifo", "0100")
    pinned = {"0100": ("aaaa000000000000", "1111111111111111"), "0300": ("bbbb", "2222")}
    scenario.write_manifest(scenario.MANIFEST, pinned)
    before = scenario.MANIFEST.read_bytes()
    elsewhere = tmp_path / "build" / "fifo-new"
    make_capture(elsewhere, "3600")
    monkeypatch.setattr(scenario, "replay_once", lambda exe, base, t: (0, REPLAY_TEXT))
    args = argparse.Namespace(
        exe="gen/soa.exe", fifo=str(elsewhere), threads="1", passes=1, bless=True
    )
    with pytest.raises(ScenarioError, match="--bless"):
        scenario.cmd_replay(args)
    assert scenario.MANIFEST.read_bytes() == before
    # comparing a different directory against the manifest writes nothing, so it may run
    args.bless = False
    assert scenario.cmd_replay(args) == 1
    assert scenario.MANIFEST.read_bytes() == before


def test_replay_says_what_is_missing_rather_than_failing_oddly(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario, "ROOT", tmp_path)
    args = argparse.Namespace(
        exe="gen/soa.exe", fifo=str(tmp_path / "fifo"), threads="1", passes=1, bless=False
    )
    assert scenario.cmd_replay(args) == 2  # no port, no disc
