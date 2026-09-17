#!/usr/bin/env python3
"""The scenario library: the scripted runs this port is judged by, and a checker.

    python tools/scenario.py list
    python tools/scenario.py show battle
    python tools/scenario.py run title --check
    python tools/scenario.py check build/scenario-title.log
    python tools/scenario.py replay --bless

Every result this port has ever claimed came from a headless run driven by an
SOA_PAD script, and until now those scripts lived in one person's shell
history: build/ holds 31 boot logs and not one scenario. config/scenarios/
holds them instead -- button names and frame numbers, which are metadata, not
game data. `list` names them, `show` prints the exact command line for one,
`run` runs it, and `--check` reads the run's own report and asserts the four
invariants that cannot drift. `replay` is the other half, and the only check
here that looks at a pixel: it renders the captured frames in build/fifo at
several thread counts and compares their hashes with config/fifo_manifest.tsv.

Scenario format (config/scenarios/<name>.scn, one `key: value` per line,
blank lines and #-comments ignored, keys repeatable):

    name:      must match the file stem; what `run` and `show` take
    summary:   one line, what the script drives
    frames:    SOA_FRAMES -- how many video frames to run, then stop and report
    pad:       SOA_PAD, the controller script; several lines are joined with
               commas so a long script can be wrapped
    env:       NAME=VALUE, one per line, the rest of the environment
    shows:     what the run is supposed to demonstrate, in prose
    evidence:  where the script was recovered from -- a log in build/, a
               section of docs/FINDINGS.md -- so a reader can check it
    note:      anything else worth knowing, including what could not be
               recovered

The pad grammar is script_init() in runtime/si.c: `frame:buttons` presses those
buttons at that game frame for ten frames; `+` combines them; `@N` repeats the
press every N frames forever; `#H` holds it H frames instead of ten. The buttons
are a b x y z l r start up down left right, and sup/sdown/sleft/sright deflect
the main stick. This tool parses the same grammar and refuses the scripts si.c
accepts without doing what whoever wrote them meant: a name si.c does not know
contributes no button and is not an error there, and an item it cannot parse at
all ends the script with the rest ignored. A hold longer than its own repeat is
not one of those -- buttons_now() in si.c takes the frame modulo the repeat, so
the button goes down at that frame and never comes up again -- so it parses
here, and `show` says that is what it means.

What --check asserts, and the report lines it reads:

    the process exits 0             frame_end() in gx.c _exit(0)s at SOA_FRAMES
    no MMIO outside the model       "[mmio!] ... (outside modelled range)", hle.c note()
    no unknown FIFO bytes           "N unknown bytes" in the [gx] line, gx_report()
    no bad vertex references        "N bad vertex refs" in the [gxr] line, gxr_report()

The last two fail on a zero counter with nothing behind it as well. A run that
pushed no bytes to the GP, or a rendering run that drew no triangle, has both
counters at zero and has checked nothing -- a renderer that painted every pixel
black would pass all four. These checks are the cheap invariants; what a frame
actually contains is `replay`.

--check also sets SOA_STRICT=1, and that is a judgement call worth stating.
Without it (note() in hle.c) an access outside the modelled range prints the
first twenty such lines and carries on with the access ignored; with it the
run stops at the first one, printing the guest pc, lr and a backtrace, and
exits 8. An unmodelled access is almost always a garbage pointer, so what
follows it is noise, and knowing where beats knowing how many -- so the
checker turns it on and reads exit 8 as the MMIO invariant failing rather than
as the exit-status invariant: the exit check reports it as skipped and points
at the MMIO check, so one broken thing is named once. `--no-strict` runs the
scenario to its frame limit instead and counts the lines, which is what you
want when a bad access is already known and the other three invariants are the
question.

The fourth invariant needs a renderer: gxr_report() in gxr.c returns without
printing a thing when SOA_RENDER is unset, so a headless scenario like
`capture` has that check reported as skipped rather than passed. A scenario
that does set SOA_RENDER and still prints no [gxr] line fails it. Note what
SOA_SNAP does to that number: gxr_draw_inner() in gxr.c rasterizes only the
frames a snapshot is being written for, so a scenario with SOA_SNAP=100 has
counters covering one frame in a hundred. They are the frames the PNGs show.

`replay` renders the captured frames instead of running the game:

    python tools/scenario.py replay --bless   # write config/fifo_manifest.tsv
    python tools/scenario.py replay           # and check against it afterwards

Each capture in build/fifo is a command stream, the register shadows it began
with and a 24 MB image of MEM1 (SOA_FIFO_DUMP in gx.c). `gen/soa.exe --replay
<base>` renders one with no game running, and SOA_HASH=1 makes it print
"[gxr] frame N WxH hash <16 hex>" -- FNV-1a over the pixels it would present.
The sweep replays every capture at SOA_THREADS 1, 2, 3 and 8, twice, which is
what turns a hash into evidence: a value that moves with the thread count is a
race in the rasterizer, not a rendering. The manifest's middle column is
sha256 over the capture's own three files, because the captures are game data
and can never be committed -- without it a row could not be told from a typo
on any machine but the one that blessed it. --replay overwrites <base>.png, so
the first sweep copies the reference PNGs to build/fifo/ref-before first.

SOA_HASH is for replays and nothing else: in a live run it forces a
gxr_flush() on every frame the port presents, which is a frame rate
measurement spoiled, and SOA_SNAP skips rasterizing the frames it is not
writing, so most of those hashes would be of a frame nothing drew.

With no gen/soa.exe or no extracted disc, `run` names exactly what is missing
and exits 2. A failed invariant exits 1. Nothing here writes into the
repository: the log goes to build/, which is gitignored, and the manifest is
frame hashes and file hashes, which are not.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "config" / "scenarios"
DEFAULT_EXE = "gen/soa.exe"
DEFAULT_DATA = "extracted"

# What main() in main.c and dvd_init() in dvd.c need out of the extracted disc.
NEEDED_FILES = ("sys/main.dol", "sys/boot.bin", "sys/fst.bin", "disc.iso")

# runtime/si.c button_named() -- the twelve buttons a script can name, plus the
# four stick deflections script_init() understands.
BUTTONS = ("a", "b", "x", "y", "z", "l", "r", "start", "up", "down", "left", "right")
STICKS = ("sup", "sdown", "sleft", "sright")
HOLD_FRAMES = 10  # si.c HOLD_FRAMES, the hold an event gets without #H
MAX_EVENTS = 1024  # si.c g_script[], which silently keeps only the first 1024

# Every way the port stops, so a failure names its cause instead of a number.
EXIT_MEANINGS = {
    0: "the frame limit, or a closed window",
    1: "the extracted disc did not load (main.c)",
    2: "the guest reached something unimplemented (guest_unimplemented, hle.c)",
    3: "a guest trap (guest_trap, hle.c)",
    4: "a spin on a register the runtime answers with zero (spin_check, hle.c)",
    5: "the watchdog: no video frame for its timeout (main.c)",
    6: "the guest thread model gave up (threads.c)",
    7: "SOA_SELFTEST failed (main.c)",
    8: "SOA_STRICT: an MMIO access outside the modelled range (note, hle.c)",
}

KEYS = ("name", "summary", "frames", "pad", "env", "shows", "evidence", "note")

# Lines worth echoing while a run is in flight: everything except the two
# tracing firehoses, which belong in the log and nowhere else.
NOISE = re.compile(r"^\[(mmio|trace)\] ")


class ScenarioError(Exception):
    """A scenario file, or a pad script, that cannot be used as written."""


LEADING_INT = re.compile(r"\s*([+-]?\d+)")


def c_atoi(value: str) -> int:
    """C atoi(), which is how the runtime reads every one of these switches.

    gxr_enabled() (gxr.c) takes SOA_RENDER through atoi(), so SOA_RENDER=yes
    turns nothing on. Judging a scenario by Python's idea of truth would have
    this tool demand a [gxr] line the run was never going to print.
    """
    m = LEADING_INT.match(value)
    return int(m.group(1)) if m else 0


# --------------------------------------------------------------------------
# the pad script
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PadEvent:
    frame: int
    buttons: tuple[str, ...]
    sticks: tuple[str, ...]
    every: int  # 0 = once
    hold: int


ITEM = re.compile(r"^(\d+):([a-z+]+)((?:[@#]\d+)*)$")


def parse_pad(script: str) -> list[PadEvent]:
    """Parse an SOA_PAD script the way script_init() in si.c does, but strictly.

    si.c stops at the first item it cannot parse and says so on stderr, and an
    unknown button name inside an item it simply drops without a word. A
    scenario that silently drove half its script, or pressed nothing at all,
    would be worse than no scenario, so both raise here. What si.c does
    understand, this accepts, however odd it looks.
    """
    events: list[PadEvent] = []
    for raw in script.split(","):
        item = raw.strip()
        if not item:
            continue
        m = ITEM.match(item)
        if not m:
            raise ScenarioError(f"{item!r} is not frame:buttons[@repeat][#hold]")
        frame, names, suffixes = int(m.group(1)), m.group(2), m.group(3)
        buttons, sticks = [], []
        for token in names.split("+"):
            if token in BUTTONS:
                buttons.append(token)
            elif token in STICKS:
                sticks.append(token)
            elif not token:
                # si.c reads "a+" as "a" (the '+' only advances its cursor), so
                # this is a typo rather than a script that drives the wrong
                # thing -- but a scenario file is meant to say what ran.
                spelled = "+".join(t for t in names.split("+") if t)
                raise ScenarioError(
                    f"{item!r} has a '+' with no button after it; si.c reads that as "
                    + (
                        f"{frame}:{spelled}{suffixes}, so write it that way"
                        if spelled
                        else "an event that presses nothing"
                    )
                )
            else:
                raise ScenarioError(
                    f"{item!r} names {token!r}, which si.c does not know; "
                    f"buttons are {' '.join(BUTTONS)} and the stick is {' '.join(STICKS)}"
                )
        every, hold = 0, HOLD_FRAMES
        for kind, n in re.findall(r"([@#])(\d+)", suffixes):
            if kind == "@":
                every = int(n)
            else:
                hold = int(n)
        events.append(PadEvent(frame, tuple(buttons), tuple(sticks), every, hold))
    if len(events) > MAX_EVENTS:
        raise ScenarioError(f"{len(events)} events; si.c keeps only the first {MAX_EVENTS} of them")
    return events


def describe_event(e: PadEvent) -> str:
    what = " + ".join(e.buttons + e.sticks) or "nothing"
    when = f"frame {e.frame}"
    held = "" if e.hold == HOLD_FRAMES else f", held {e.hold} frames"
    if e.every and e.hold >= e.every:
        # buttons_now() takes the frame modulo the repeat before comparing it
        # with the hold, so a hold at least as long as the period is always
        # inside it: the button goes down here and stays down.
        return f"frame {e.frame} onward: {what}, held down for good ({e.hold} >= {e.every})"
    if e.every:
        when += f" and every {e.every} frames after"
    return f"{when}: {what}{held}"


# --------------------------------------------------------------------------
# the scenario files
# --------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    summary: str
    frames: int
    pad: str
    path: Path
    env: dict[str, str] = field(default_factory=dict)
    shows: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def events(self) -> list[PadEvent]:
        return parse_pad(self.pad)

    @property
    def rendering(self) -> bool:
        """Does this scenario draw? Only then does the renderer report at all."""
        return c_atoi(self.env.get("SOA_RENDER", "0")) != 0


def parse_scenario(text: str, path: Path) -> Scenario:
    """Parse one .scn file. Raises ScenarioError naming the line at fault."""
    values: dict[str, list[str]] = {k: [] for k in KEYS}
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep or key not in KEYS:
            raise ScenarioError(
                f"{path}:{n}: not a 'key: value' line, or unknown key: {stripped!r}"
            )
        values[key].append(value.strip())
    for required in ("name", "summary", "frames", "pad"):
        if not values[required]:
            raise ScenarioError(f"{path}: no {required}:")
    for single in ("name", "summary", "frames"):
        if len(values[single]) > 1:
            raise ScenarioError(f"{path}: {single}: given {len(values[single])} times")
    name = values["name"][0]
    if name != path.stem:
        raise ScenarioError(f"{path}: name: {name!r} does not match the file name")
    try:
        frames = int(values["frames"][0])
    except ValueError:
        raise ScenarioError(f"{path}: frames: {values['frames'][0]!r} is not a number") from None
    if frames <= 0:
        raise ScenarioError(f"{path}: frames: must be positive")
    pad = ",".join(part.strip(",") for part in values["pad"] if part.strip(","))
    env: dict[str, str] = {}
    for item in values["env"]:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ScenarioError(f"{path}: env: {item!r} is not NAME=VALUE")
        if key in ("SOA_PAD", "SOA_FRAMES"):
            raise ScenarioError(f"{path}: env: {key} comes from pad:/frames:, not from env:")
        env[key.strip()] = value.strip()
    try:
        parse_pad(pad)
    except ScenarioError as e:
        raise ScenarioError(f"{path}: pad: {e}") from None
    return Scenario(
        name=name,
        summary=values["summary"][0],
        frames=frames,
        pad=pad,
        path=path,
        env=env,
        shows=values["shows"],
        evidence=values["evidence"],
        notes=values["note"],
    )


def load_scenario(name: str, directory: Path = SCENARIO_DIR) -> Scenario:
    path = directory / f"{name}.scn"
    if not path.exists():
        known = ", ".join(s.name for s in load_all(directory)) or "none"
        raise ScenarioError(f"no scenario {name!r} in {directory}; there is: {known}")
    return parse_scenario(path.read_text(encoding="utf-8"), path)


def load_all(directory: Path = SCENARIO_DIR) -> list[Scenario]:
    out = []
    for path in sorted(directory.glob("*.scn")):
        out.append(parse_scenario(path.read_text(encoding="utf-8"), path))
    return out


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------


def run_env(sc: Scenario, extra: dict[str, str] | None = None, strict: bool = False) -> dict:
    """The environment this scenario means, in the order a reader wants it."""
    env = {"SOA_PAD": sc.pad, "SOA_FRAMES": str(sc.frames)}
    env.update(sc.env)
    if strict:
        env["SOA_STRICT"] = "1"
    if extra:
        env.update(extra)
    return env


def command_lines(env: dict[str, str], exe: str, data: str, shell: str) -> list[str]:
    """The exact commands to reproduce a run, for a person to paste."""
    windows_exe = exe.replace("/", "\\")
    if shell == "powershell":
        lines = [f"$env:{k}='{v}'" for k, v in env.items()]
        lines.append(f"{windows_exe} {data}")
    elif shell == "cmd":
        lines = [f"set {k}={v}" for k, v in env.items()]
        lines.append(f"{windows_exe} {data}")
    else:
        lines = [f"{k}='{v}' \\" for k, v in env.items()]
        lines.append(f"{exe} {data}")
    return lines


def named(path: Path) -> str:
    """A path as someone standing in the repository would type it."""
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else str(resolved)


def missing_inputs(exe: Path, data: Path) -> list[str]:
    """Everything a run needs and does not have, said plainly."""
    missing = []
    if not exe.exists():
        missing.append(
            f"{named(exe)}: the port is not built -- python tools/recompile.py --compile --link"
        )
    if not data.is_dir():
        missing.append(
            f"{named(data)}/: no extracted disc -- python tools/extract.py <your disc dump> --iso"
        )
    else:
        for rel in NEEDED_FILES:
            if not (data / rel).exists():
                why = (
                    "every asset read would return zeros"
                    if rel.endswith(".iso")
                    else "the boot path needs it"
                )
                missing.append(f"{named(data / rel)}: missing -- {why} (tools/extract.py --iso)")
    return missing


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------

RE_MMIO_BANG = re.compile(r"^\[mmio!\] .*\(outside modelled range\)")
RE_STRICT = re.compile(r"^\[strict\] pc ")
RE_GX = re.compile(r"^\[gx\] (\d+) pipe bytes,")
RE_UNKNOWN = re.compile(r"(\d+) unknown bytes")
RE_VERTS = re.compile(r"\((\d+) vertices\)")
RE_GXR = re.compile(r"^\[gxr\] (\d+) triangles,")
RE_BAD_VERTS = re.compile(r"(\d+) bad vertex refs")
RE_FRAMES_DONE = re.compile(r"^\[boot\] (\d+) frames done \(SOA_FRAMES\)")
RE_EVENTS = re.compile(r"^\[si\] (\d+) scripted controller events")
RE_PAD_TROUBLE = re.compile(r"^\[si\] SOA_PAD")
# The lines that mean the run ended where they were printed. Not every
# [watchdog] line is one: main.c prints "cannot start the watchdog thread" and
# "no window after all; arming the headless default" while a run is starting
# normally, and reading either as a termination would name a healthy notice as
# the cause of a failure. "still running after Ns" is the older watchdog's
# version of "no video frame for Ns" -- gone from runtime/, but the terminal
# line in all 31 saved logs in build/, which is what `check` is pointed at.
RE_STOP = re.compile(r"^\[(spin|trap|unimplemented)\]|^\[watchdog\] (no video frame|still running)")


@dataclass
class Report:
    """What a run said about itself. Every field is read from stderr."""

    unmodelled: int = 0
    first_unmodelled: str | None = None
    strict_stopped: bool = False
    unknown_bytes: int | None = None
    pipe_bytes: int | None = None
    vertices: int | None = None
    bad_vertex_refs: int | None = None
    triangles: int | None = None
    rendered: bool = False
    frames_done: int | None = None
    scripted_events: int | None = None
    pad_trouble: str | None = None
    stop_lines: list[str] = field(default_factory=list)


def parse_report(text: str) -> Report:
    """Read a run's stderr. Absent counters stay None: missing is not zero."""
    r = Report()
    for line in text.splitlines():
        line = line.rstrip()
        if RE_MMIO_BANG.match(line):
            r.unmodelled += 1
            if r.first_unmodelled is None:
                r.first_unmodelled = line
            continue
        if RE_STRICT.match(line):
            r.strict_stopped = True
            continue
        m = RE_GX.match(line)
        if m:
            r.pipe_bytes = int(m.group(1))
            unknown = RE_UNKNOWN.search(line)
            verts = RE_VERTS.search(line)
            r.unknown_bytes = int(unknown.group(1)) if unknown else None
            r.vertices = int(verts.group(1)) if verts else None
            continue
        m = RE_GXR.match(line)
        if m:
            r.rendered = True
            r.triangles = int(m.group(1))
            bad = RE_BAD_VERTS.search(line)
            r.bad_vertex_refs = int(bad.group(1)) if bad else None
            continue
        if line.startswith("[gxr] "):
            r.rendered = True
            continue
        m = RE_FRAMES_DONE.match(line)
        if m:
            r.frames_done = int(m.group(1))
            continue
        m = RE_EVENTS.match(line)
        if m:
            r.scripted_events = int(m.group(1))
            continue
        if RE_PAD_TROUBLE.match(line) and r.pad_trouble is None:
            r.pad_trouble = line
            continue
        if RE_STOP.match(line):
            r.stop_lines.append(line)
    return r


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

PASS, FAIL, SKIP = "pass", "FAIL", "skip"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    invariant: bool = True  # false for the check on the input rather than the run


def check_report(
    r: Report,
    exit_code: int | None = None,
    expect_render: bool | None = None,
    expect_events: int | None = None,
    killed_after: float | None = None,
) -> list[Check]:
    """The four invariants, plus one sanity check on the input.

    `exit_code` is None when reading a saved log, where the run's own words
    have to stand in for it. `expect_render` says whether the scenario asked
    for a renderer, which is what makes a missing [gxr] line a failure rather
    than a scenario that never draws. `killed_after` is --timeout's doing, and
    has to be told apart from the exit code it leaves behind.
    """
    checks: list[Check] = []

    # 1. exit status.
    if killed_after is not None:
        # Popen.kill() leaves exit code 1 on Windows, which EXIT_MEANINGS reads
        # as a disc that would not load. The tool knows better: it did this.
        checks.append(
            Check(
                "the run exits 0",
                FAIL,
                f"killed after {killed_after:g}s by --timeout, short of its frame limit",
            )
        )
    elif exit_code is None:
        if r.frames_done is not None:
            checks.append(
                Check(
                    "the run exits 0",
                    PASS,
                    f"reached its frame limit at {r.frames_done} frames, which exits 0",
                )
            )
        elif r.stop_lines:
            checks.append(
                Check(
                    "the run exits 0",
                    FAIL,
                    f"no frame limit reached; the run ended at: {r.stop_lines[0]}",
                )
            )
        else:
            checks.append(Check("the run exits 0", SKIP, "this log does not say how the run ended"))
    elif exit_code == 0:
        done = f", {r.frames_done} frames" if r.frames_done is not None else ""
        checks.append(Check("the run exits 0", PASS, f"exit 0{done}"))
    elif exit_code == 8:
        # --check asks for SOA_STRICT, so exit 8 is this tool's own doing and
        # says exactly one thing: the MMIO invariant below broke. Failing here
        # as well would report two broken things where there is one.
        checks.append(
            Check(
                "the run exits 0",
                SKIP,
                "exit 8: SOA_STRICT stopped the run, which the MMIO invariant below has",
            )
        )
    else:
        why = EXIT_MEANINGS.get(exit_code, "an exit code the runtime does not document")
        checks.append(Check("the run exits 0", FAIL, f"exit {exit_code}: {why}"))

    # 2. MMIO inside the modelled range.
    if exit_code == 8 or r.strict_stopped:
        first = r.first_unmodelled or "see the [strict] backtrace in the log"
        checks.append(
            Check("no MMIO outside the modelled range", FAIL, f"SOA_STRICT stopped at {first}")
        )
    elif r.unmodelled:
        checks.append(
            Check(
                "no MMIO outside the modelled range",
                FAIL,
                f"{r.unmodelled} access(es), the first {r.first_unmodelled}",
            )
        )
    else:
        checks.append(Check("no MMIO outside the modelled range", PASS, "no [mmio!] lines"))

    # 3. the FIFO parser understood every byte.
    if r.unknown_bytes is None:
        checks.append(
            Check("no unknown FIFO bytes", FAIL, "no [gx] line: the run never reached its report")
        )
    elif r.unknown_bytes:
        checks.append(
            Check("no unknown FIFO bytes", FAIL, f"{r.unknown_bytes} unknown bytes in the stream")
        )
    elif not r.pipe_bytes:
        checks.append(
            Check(
                "no unknown FIFO bytes",
                FAIL,
                "0 pipe bytes: nothing reached the GP, so nothing was understood",
            )
        )
    else:
        total = f" of {r.pipe_bytes}" if r.pipe_bytes is not None else ""
        checks.append(Check("no unknown FIFO bytes", PASS, f"0 unknown bytes{total}"))

    # 4. no vertex the renderer could not resolve.
    if r.bad_vertex_refs is None:
        if expect_render:
            why = (
                "a [gxr] line with no bad-vertex-ref count in it"
                if r.rendered
                else "no [gxr] line, though SOA_RENDER was set"
            )
            checks.append(Check("no bad vertex references", FAIL, why))
        else:
            checks.append(
                Check(
                    "no bad vertex references",
                    SKIP,
                    "nothing was rendered (no SOA_RENDER), so gxr_report prints nothing",
                )
            )
    elif r.bad_vertex_refs:
        checks.append(
            Check("no bad vertex references", FAIL, f"{r.bad_vertex_refs} bad vertex refs")
        )
    elif expect_render and not r.triangles:
        # Zero of zero. The counter is right and the check is empty, and saying
        # so is the difference between a renderer that works and one that ran.
        checks.append(
            Check(
                "no bad vertex references",
                FAIL,
                "0 bad vertex refs over 0 triangles: this run drew nothing",
            )
        )
    else:
        total = f" over {r.vertices} vertices" if r.vertices is not None else ""
        drew = f", {r.triangles} triangles" if r.triangles is not None else ""
        checks.append(Check("no bad vertex references", PASS, f"0 bad vertex refs{total}{drew}"))

    # And the input itself: a script the port did not understand makes the
    # four above true about a run that drove nothing.
    if r.pad_trouble:
        checks.append(Check("the pad script was understood", FAIL, r.pad_trouble, False))
    elif r.scripted_events is None:
        checks.append(
            Check("the pad script was understood", SKIP, "no [si] line: no script ran", False)
        )
    elif expect_events is not None and r.scripted_events != expect_events:
        checks.append(
            Check(
                "the pad script was understood",
                FAIL,
                f"the port read {r.scripted_events} events where the scenario has {expect_events}",
                False,
            )
        )
    else:
        checks.append(
            Check("the pad script was understood", PASS, f"{r.scripted_events} events", False)
        )
    return checks


def print_checks(checks: list[Check], label: str) -> int:
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"[check] {c.name:<{width}}  {c.status:<4}  {c.detail}")
    failed = [c for c in checks if c.status == FAIL]
    invariants = [c for c in checks if c.invariant and c.status == PASS]
    if failed:
        print(f"{label}: FAILED -- " + "; ".join(f"{c.name}: {c.detail}" for c in failed))
        return 1
    skipped = [c for c in checks if c.invariant and c.status == SKIP]
    tail = f" ({len(skipped)} skipped: {', '.join(c.name for c in skipped)})" if skipped else ""
    print(f"{label}: {len(invariants)} of 4 invariants hold{tail}")
    return 0


# --------------------------------------------------------------------------
# running one
# --------------------------------------------------------------------------


def stream_run(
    argv: list[str], env: dict, log: Path, echo: str, timeout: float
) -> tuple[int, str, bool]:
    """Run the port, tee stderr into the log, and return (exit, text, killed).

    The third value is what --timeout did: a killed child's exit code is the
    operating system's, not the runtime's, and reading it as one of
    EXIT_MEANINGS would blame the port for a deadline this tool set.
    """
    lines: list[str] = []
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    killed = False

    def give_up():
        nonlocal killed
        killed = True
        proc.kill()

    killer = threading.Timer(timeout, give_up) if timeout else None
    if killer:
        killer.start()
    try:
        with log.open("w", encoding="utf-8", newline="\n") as fh:
            for line in proc.stdout:
                line = line.rstrip("\r\n")
                lines.append(line)
                fh.write(line + "\n")
                # A long scenario prints little, so a buffered log stays empty
                # for minutes: the one thing you want from a soak is to see it
                # is still moving.
                fh.flush()
                if echo == "all" or (echo == "some" and not NOISE.match(line)):
                    print(line)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        print("[scenario] interrupted; the log up to here is in", named(log))
        raise
    finally:
        if killer:
            killer.cancel()
    return code, "\n".join(lines), killed


def cmd_run(args: argparse.Namespace) -> int:
    sc = load_scenario(args.name, Path(args.dir))
    exe, data = ROOT / args.exe, ROOT / args.data
    missing = missing_inputs(exe, data)
    if missing:
        print(f"[scenario] {sc.name} cannot run; missing:")
        for m in missing:
            print("  " + m)
        return 2
    if args.frames:
        sc.frames = args.frames
    extra = {}
    for pair in args.env:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ScenarioError(f"--env {pair!r} is not NAME=VALUE")
        extra[key] = value
    strict = args.check and not args.no_strict
    env = run_env(sc, extra, strict)
    # What the checks are about is the run that happens, not the file it came
    # from: --env SOA_PAD=... really does replace the script, and expecting the
    # scenario's own event count then fails a check that is measuring the wrong
    # thing. Read both back out of the environment the port will be given.
    events = parse_pad(env["SOA_PAD"])
    rendering = c_atoi(env.get("SOA_RENDER", "0")) != 0
    # The scenario's environment is the whole of it: an SOA_* left over in the
    # shell would quietly make the run mean something else.
    full = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    full.update(env)
    # The capture path and the memory card write into directories they expect to
    # exist already (gx.c frame_end, exi.c). A scenario that captures says where
    # with SOA_FIFO_DIR, and says somewhere other than build/fifo: that corpus is
    # what config/fifo_manifest.tsv pins, the streams are not in the repository,
    # and a run that overwrites one invalidates its blessed hash with nothing to
    # restore from.
    for sub in ("frames", "fifo", "cards"):
        (ROOT / "build" / sub).mkdir(parents=True, exist_ok=True)
    if env.get("SOA_FIFO_DIR"):
        (ROOT / env["SOA_FIFO_DIR"]).mkdir(parents=True, exist_ok=True)
    log = Path(args.log) if args.log else ROOT / "build" / f"scenario-{sc.name}.log"
    print(f"[scenario] {sc.name}: {sc.summary}")
    print(f"[scenario] {args.exe} {args.data}  ({', '.join(f'{k}={v}' for k, v in env.items())})")
    print(f"[scenario] {env['SOA_FRAMES']} frames, {len(events)} pad events; log: {named(log)}")
    echo = "all" if args.verbose else ("none" if args.quiet else "some")
    code, text, killed = stream_run([str(exe), args.data], full, log, echo, args.timeout)
    report = parse_report(text)
    if not args.check:
        if killed:
            print(f"[scenario] {sc.name} killed after {args.timeout:g}s; log in {named(log)}")
            return 1
        why = EXIT_MEANINGS.get(code, "an exit code the runtime does not document")
        print(f"[scenario] {sc.name} exited {code}: {why}; log in {named(log)}")
        return 0 if code == 0 else 1
    return print_checks(
        check_report(report, code, rendering, len(events), args.timeout if killed else None),
        sc.name,
    )


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.log)
    if not path.exists():
        print(f"[scenario] no log at {path}")
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    expect_render, expect_events = None, None
    if args.name:
        sc = load_scenario(args.name, Path(args.dir))
        expect_render, expect_events = sc.rendering, len(sc.events)
    return print_checks(
        check_report(parse_report(text), None, expect_render, expect_events), path.name
    )


# --------------------------------------------------------------------------
# the replay sweep: the captured frames, rendered again and hashed
# --------------------------------------------------------------------------

FIFO_DIR = ROOT / "build" / "fifo"
MANIFEST = ROOT / "config" / "fifo_manifest.tsv"
PARTS = (".fifo", ".regs", ".ram")  # gx.c frame capture writes all three
DEFAULT_THREADS = (1, 2, 3, 8)
KEY_DIGITS = 16
RE_FRAME_HASH = re.compile(r"^\[gxr\] frame \d+ \d+x\d+ hash ([0-9a-f]{16})$")

MANIFEST_NOTE = """\
# Frame hashes for the captures in build/fifo, written by
#     python tools/scenario.py replay --bless
# and checked by the same command without --bless. Columns: the capture's
# name, sha256 over its .fifo, .regs and .ram files, and FNV-1a over the
# frame gen/soa.exe --replay renders from them (gxr_screen_hash, gxr.c).
# The captures themselves are game data and stay out of the repository, so
# the middle column is what ties a row to the bytes it was measured from.
"""


def part(base: Path, ext: str) -> Path:
    """One file of a capture. Not with_suffix(): a name with a dot in it would
    lose the part after it."""
    return base.parent / (base.name + ext)


def capture_key(base: Path) -> str:
    """sha256 over one capture's three files, to 16 hex digits."""
    h = hashlib.sha256()
    for ext in PARTS:
        with part(base, ext).open("rb") as fh:
            while block := fh.read(1 << 20):
                h.update(block)
    return h.hexdigest()[:KEY_DIGITS]


def find_captures(directory: Path) -> tuple[list[Path], list[str]]:
    """Every complete capture in a directory, and a word about the rest."""
    captures, partial = [], []
    for fifo in sorted(directory.glob("*.fifo")):
        base = fifo.parent / fifo.name[: -len(".fifo")]
        missing = [ext for ext in PARTS if not part(base, ext).exists()]
        if missing:
            partial.append(f"{base.name}: no {', '.join(missing)}; --replay would not load it")
        else:
            captures.append(base)
    return captures, partial


def frame_hashes(text: str) -> list[str]:
    """The hash lines a replay printed. A replay presents exactly one frame."""
    return [m.group(1) for line in text.splitlines() if (m := RE_FRAME_HASH.match(line.strip()))]


def replay_once(exe: Path, base: Path, threads: int) -> tuple[int, str]:
    """One `gen/soa.exe --replay <base>` with the hash switch on."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env["SOA_HASH"] = "1"
    env["SOA_THREADS"] = str(threads)
    proc = subprocess.run(
        [str(exe), "--replay", str(base)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def sweep(
    captures: list[Path],
    threads: tuple[int, ...],
    passes: int,
    run,
    echo=print,
) -> tuple[dict[str, str], list[str]]:
    """Replay each capture at each thread count, `passes` times over.

    Returns the hash each capture settled on and everything that went wrong.
    A capture whose hash moves between runs is the point of the exercise: the
    row ownership rule in gxr.c is what makes a frame independent of how many
    workers drew it, and a value that moves is that rule broken.
    """
    first: dict[str, str] = {}
    where: dict[str, str] = {}
    problems: list[str] = []
    for p in range(1, passes + 1):
        for t in threads:
            echo(f"[replay] pass {p}, SOA_THREADS={t}")
            for base in captures:
                code, text = run(base, t)
                got = frame_hashes(text)
                at = f"{base.name} at SOA_THREADS={t} (pass {p})"
                if code != 0:
                    problems.append(f"{at}: exit {code}")
                if len(got) != 1:
                    # gx_replay returns 1 and says why when a file will not
                    # open; counting the lines is what tells a replay that
                    # rendered nothing from one that rendered a frame.
                    problems.append(f"{at}: {len(got)} hash lines, expected exactly 1")
                    continue
                if base.name not in first:
                    first[base.name] = got[0]
                    where[base.name] = at
                elif got[0] != first[base.name]:
                    problems.append(
                        f"{at}: hash {got[0]}, but {where[base.name]} gave {first[base.name]}"
                    )
    return first, problems


def read_manifest(path: Path) -> dict[str, tuple[str, str]]:
    """{capture: (input key, frame hash)} from a manifest, comments dropped."""
    rows: dict[str, tuple[str, str]] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise ScenarioError(f"{named(path)}:{n}: not three tab-separated columns: {line!r}")
        rows[parts[0]] = (parts[1], parts[2])
    return rows


def write_manifest(path: Path, rows: dict[str, tuple[str, str]]) -> None:
    lines = [MANIFEST_NOTE]
    lines += [f"{name}\t{key}\t{value}\n" for name, (key, value) in sorted(rows.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8", newline="\n")


def compare_manifest(
    rows: dict[str, tuple[str, str]], manifest: dict[str, tuple[str, str]]
) -> tuple[list[str], int]:
    """This sweep against the blessed one, line by line. Returns (lines, bad)."""
    out, bad = [], 0
    for name in sorted(set(rows) | set(manifest)):
        mine, theirs = rows.get(name), manifest.get(name)
        if mine is None:
            out.append(f"  gone  {name}: in the manifest, not in build/fifo")
            bad += 1
        elif theirs is None:
            out.append(f"  new   {name}: {mine[1]} (not in the manifest; --bless adds it)")
            bad += 1
        elif mine[0] != theirs[0]:
            out.append(
                f"  input {name}: this capture hashes {mine[0]}, the manifest was blessed "
                f"from {theirs[0]} -- a different capture, so the frame hash means nothing"
            )
            bad += 1
        elif mine[1] != theirs[1]:
            out.append(f"  DIFFS {name}: {mine[1]}, manifest {theirs[1]}")
            bad += 1
        else:
            out.append(f"  ok    {name}: {mine[1]}")
    return out, bad


def keep_reference_pngs(directory: Path, echo=print) -> None:
    """--replay overwrites <base>.png (main.c), and 13 of those are the only
    reference frames anyone has. Put a copy somewhere the sweep will not reach
    before the first one runs."""
    keep = directory / "ref-before"
    if keep.exists():
        return
    pngs = sorted(directory.glob("*.png"))
    if not pngs:
        return
    keep.mkdir(parents=True)
    for png in pngs:
        shutil.copy2(png, keep / png.name)
    echo(f"[replay] kept {len(pngs)} reference PNG(s) in {named(keep)} before overwriting them")


def cmd_replay(args: argparse.Namespace) -> int:
    exe, fifo = ROOT / args.exe, Path(args.fifo)
    # --replay takes the capture as its argument, so main.c falls back to the
    # literal directory "extracted" for the disc it still wants to open.
    missing = missing_inputs(exe, ROOT / DEFAULT_DATA)
    if missing:
        print("[replay] cannot run; missing:")
        for m in missing:
            print("  " + m)
        return 2
    captures, partial = find_captures(fifo)
    for line in partial:
        print(f"[replay] {line}")
    if not captures:
        print(f"[replay] no complete captures in {named(fifo)}: run the capture scenario first")
        return 2
    try:
        threads = tuple(int(t) for t in args.threads.split(","))
    except ValueError:
        raise ScenarioError(f"--threads {args.threads!r} is not a list like 1,2,3,8") from None
    total = len(captures) * len(threads) * args.passes
    print(
        f"[replay] {len(captures)} captures x {len(threads)} thread counts x {args.passes} "
        f"passes = {total} replays, each loading a 24 MB memory image"
    )
    keep_reference_pngs(fifo)
    hashes, problems = sweep(captures, threads, args.passes, lambda b, t: replay_once(exe, b, t))
    rows = {
        base.name: (capture_key(base), hashes[base.name])
        for base in captures
        if base.name in hashes
    }
    for line in problems:
        print(f"[replay] {line}")
    if args.bless:
        if problems:
            print("[replay] not blessing a sweep that did not agree with itself")
            return 1
        write_manifest(MANIFEST, rows)
        print(f"[replay] blessed {len(rows)} captures into {named(MANIFEST)}")
        return 0
    if not MANIFEST.exists():
        print(f"[replay] no {named(MANIFEST)} yet; --bless writes it from a clean sweep")
        return 1
    lines, bad = compare_manifest(rows, read_manifest(MANIFEST))
    for line in lines:
        print(line)
    if bad or problems:
        print(f"[replay] FAILED -- {bad} capture(s) differ, {len(problems)} run(s) went wrong")
        return 1
    print(f"[replay] {len(rows)} captures match {named(MANIFEST)} at SOA_THREADS {args.threads}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    scenarios = load_all(Path(args.dir))
    if not scenarios:
        print(f"[scenario] no .scn files in {args.dir}")
        return 2
    width = max(len(s.name) for s in scenarios)
    for sc in scenarios:
        print(
            f"{sc.name:<{width}}  {sc.frames:>7} frames  {len(sc.events):>3} events  {sc.summary}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    sc = load_scenario(args.name, Path(args.dir))
    env = run_env(sc, strict=args.check)
    if not args.command:
        print(f"{sc.name}: {sc.summary}")
        print(f"  from {named(sc.path)}")
        for line in sc.shows:
            print(f"  shows     {line}")
        for line in sc.evidence:
            print(f"  evidence  {line}")
        for line in sc.notes:
            print(f"  note      {line}")
        print(f"  script    {len(sc.events)} events, {sc.frames} frames")
        for e in sc.events[: args.events]:
            print(f"    {describe_event(e)}")
        if len(sc.events) > args.events:
            print(f"    ... {len(sc.events) - args.events} more (--events N for all of them)")
        print()
    for line in command_lines(env, args.exe, args.data, args.shell):
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(SCENARIO_DIR), help="where the .scn files are")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="name every scenario")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="print one scenario and the command that runs it")
    p.add_argument("name")
    p.add_argument("--command", action="store_true", help="the command line and nothing else")
    p.add_argument("--check", action="store_true", help="include SOA_STRICT=1, as --check would")
    p.add_argument("--shell", choices=("powershell", "cmd", "sh"), default="powershell")
    p.add_argument("--events", type=int, default=8, help="how many pad events to spell out")
    p.add_argument("--exe", default=DEFAULT_EXE)
    p.add_argument("--data", default=DEFAULT_DATA)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("run", help="run one scenario")
    p.add_argument("name")
    p.add_argument("--check", action="store_true", help="assert the four invariants afterwards")
    p.add_argument("--no-strict", action="store_true", help="--check without SOA_STRICT=1")
    p.add_argument("--frames", type=int, help="override the scenario's frame count")
    p.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    p.add_argument("--exe", default=DEFAULT_EXE)
    p.add_argument("--data", default=DEFAULT_DATA)
    p.add_argument(
        "--log", help="where to write the run's output (default build/scenario-NAME.log)"
    )
    p.add_argument("--timeout", type=float, default=0, help="kill the run after N seconds")
    p.add_argument("-q", "--quiet", action="store_true", help="echo nothing; the log has it all")
    p.add_argument("-v", "--verbose", action="store_true", help="echo every line, tracing included")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("replay", help="render the captured frames again and hash them")
    p.add_argument("--bless", action="store_true", help="write the manifest from this sweep")
    p.add_argument(
        "--threads",
        default=",".join(str(t) for t in DEFAULT_THREADS),
        help="SOA_THREADS values to sweep; a frame that moves between them is a race",
    )
    p.add_argument("--passes", type=int, default=2, help="how many times over (default 2)")
    p.add_argument("--fifo", default=str(FIFO_DIR), help="where the captures are")
    p.add_argument("--exe", default=DEFAULT_EXE)
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("check", help="apply the same checks to a log already written")
    p.add_argument("log")
    p.add_argument("--name", help="the scenario it came from, which sharpens two checks")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ScenarioError as e:
        print(f"[scenario] {e}")
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
