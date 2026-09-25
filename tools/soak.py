#!/usr/bin/env python3
"""Generate a soak-test controller script, and judge the logs soaks leave.

    python tools/soak.py --seed 7 --first 3200 --last 33000
    $env:SOA_PAD = (python tools/soak.py --seed 7)
    $env:SOA_POKE = (python tools/soak.py --pokes --warp 116c --encounter-every 600)
    python tools/soak.py check build/scenario-soakG.log [LOG...] [--json summary.json]
    python tools/soak.py check LOG --expect-map 116a --expect-reach 116c --frames build/job/frames

Prints an `SOA_PAD` script: the presses that walk a Continue from the title
(so the run should load a save -- see HANDOFF, "Start a run from a save"),
then, from `--first` to `--last`, a stream of steps drawn from a fixed-seed
generator -- the stick held in one of eight directions for 40-120 frames (60%
of steps), A (25%), B (10%), or a visit to the menu and back out (5%).

What it is for: the censuses load every map, but only for ten or twenty seconds
each, and a map that loads can still fault minutes into play. Twenty minutes of
this in Esperanza on 2026-09-23 ran clean under `SOA_STRICT=1` and walked Vyse
through an exit into the next map -- the first map change in this project a
player's input made. Run it with `SOA_STRICT=1`, and the same seed replays the
same input, so a fault it finds can be repeated.

`--pokes` prints the job's SOA_POKE instead (PLAN S3): `--warp NNNx`, the
game's own warp by script name, and `--encounter-every K`, the encounter
accelerator -- the step counter 0x80346D28 re-poked to 100000 every K frames,
since every map load and battle resets it. The accelerator only shortens the
wait: every gate, the story's included, runs before the counter is read
(docs/research/soak.md 1b), so it cannot make a battle the story forbids.
The six-word battle request, which skips those gates, is never poked.
`--encounter-every` leaves the pad script alone, so an accelerated job and its
baseline press the same buttons; `--warp` moves random play's default start
to after the warp. `--peeks` prints an SOA_PEEK of the counter
the frame after each accelerator poke.

`check` reads what a soak printed and turns "the run finished" into a verdict,
one of three, per log:

    FAIL                        an invariant broke: the run did not exit 0 at its
                                frame limit, an [mmio!] line, unknown FIFO bytes,
                                bad vertex refs, a [trap]/[spin]/[unimplemented]/
                                [watchdog] stop, any [mem] line, no [gx] report,
                                a pad script or poke list the port did not
                                understand, a card the game would not accept, or
                                a landing map other than --expect-map's
    did not test what it says   the run was healthy and soaked something other
                                than its claim: a battle job that fought no
                                battle, a run that never left the title's attract
                                demo, or one no input drove
    pass                        neither

and, besides, what it saw -- battles, game overs with their frame, the field
maps in order, the landing map -- and QUESTIONS, which never fail a run: the
[gxr] BP_MASK tripwire and every other one-time [gxr] warning. The exit status
is 1 if any log FAILs and 0 otherwise; "did not test" and questions are for a
person to read, not for the exit code.

How each reading is made, and why:

- **A battle is `/battle/stsicon.mld`, once per battle.** Every battle logs it
  twice -- `LoadCrew "/battle/" "stsicon.mld"`, then `LoadAsset` from inside
  that call -- so counting lines doubles every battle. Lines belong to one
  battle until a field map loads (the game reloads the field after every
  battle, and a lost one loads `a090a`) or until the pad's frame stamps have
  moved more than BATTLE_GAP frames between them. `/field/stsicon.mld` is not a
  battle: it loads with every 5xx ship stage (`scenario-ships1.log`).
- **A frame is the nearest `[si]`, `[poke]` or `[peek] frame N` line before
  the event**, so it is a lower bound: si.c prints a line only when the pad
  changes, every 50-130 frames in a soak.
- **The landing map is the first field map that is not the title's attract
  demo** (`a299a`, `a297a`); the title loads `a299a` at boot, before any
  Continue.
- **A battle claim is the `--battle` mix, or `--expect-battles`.** The mix is
  recognised from the log itself: its single-step d-pad presses show as `[si]`
  lines with a d-pad bit, and the walk mix never presses the d-pad. The
  scenario a soak ran under is not a claim: all twelve soaks of 2026-09-23 ran
  as `scenario.py run battle` for its environment, and the six walk-mix ones
  were written up as random play in a map (FINDINGS), never as battle soaks.
- **A wrong landing map FAILs; zero battles only "did not test".** The landing
  map follows from the card and the warp, so a wrong one is a broken job whose
  every figure is about the wrong map. Encounters are chance -- the RNG is
  reseeded from OSGetTick on every map load -- so a battle job that met none
  soaked something real, just not what it said.
- **The card is verified only when it is the job's own.** A card every job
  shares (`build/savetest/work.raw`, which the 2026-09-23 soaks all copied their
  save into, or the default `build/cards/slotA.raw`) holds whichever run wrote
  it last, so its check is "not available"; any other card is run through
  cardformat.verify, and one the game would not accept FAILs.

The `run_*.log` a shell leaves by tee-ing `scenario.py run` is accepted too: it
adds the exit code and the generated pad count, and leaves out the [trace]
lines battles and maps are read from, which are then reported as unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import scenario  # tools/ is sys.path[0] when this runs as a script

DIRECTIONS = [
    "sup",
    "sdown",
    "sleft",
    "sright",
    "sup+sleft",
    "sup+sright",
    "sdown+sleft",
    "sdown+sright",
]
CONTINUE = [
    "1600:start",
    "1640:a",
    "1800:start",
    "1840:a",
    "2000:start",
    "2040:a",
    "2240:a",
    "2440:a",
    "2640:a",
]
MAX_EVENTS = 1000  # si.c holds 1024; leave room


PAD = ["up#4", "down#4", "left#4", "right#4"]  # single steps: a plain press moves a menu two slots


def script(seed: int, first: int = 3200, last: int = 33000, battle: bool = False) -> str:
    """The pad script, as one string. Deterministic in its arguments.

    `battle` adds single-step d-pad presses to the mix, so the battle wheel
    turns to a random command before an A commits it -- Magic, Focus, S-move,
    Item, Guard and Run instead of the Attack it opens on. The default mix is
    unchanged, so a seed replays the script it always did."""
    if battle:
        return _battle(seed, first, last)
    state = seed

    def rnd(n: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF  # the C library's LCG
        return (state >> 8) % n

    ev, f = list(CONTINUE), first
    while f < last and len(ev) < MAX_EVENTS - 3:
        r = rnd(20)
        if r < 12:
            ev.append(f"{f}:{DIRECTIONS[rnd(8)]}#{40 + rnd(80)}")
            f += 130
        elif r < 17:
            ev.append(f"{f}:a")
            f += 50
        elif r < 19:
            ev.append(f"{f}:b")
            f += 50
        else:
            ev += [f"{f}:start", f"{f + 90}:b", f"{f + 160}:b"]
            f += 220
    return ",".join(ev)


def _battle(seed: int, first: int, last: int) -> str:
    """Stick 40%, A 35%, a d-pad single step 20%, B 5%. Steps are spaced 70
    frames or more: a single step that arrives while the wheel is still
    turning is dropped (FINDINGS: a third step 60 frames after the second)."""
    state = seed

    def rnd(n: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return (state >> 8) % n

    ev, f = list(CONTINUE), first
    while f < last and len(ev) < MAX_EVENTS - 1:
        r = rnd(20)
        if r < 8:
            ev.append(f"{f}:{DIRECTIONS[rnd(8)]}#{40 + rnd(80)}")
            f += 130
        elif r < 15:
            ev.append(f"{f}:a")
            f += 70
        elif r < 19:
            ev.append(f"{f}:{PAD[rnd(4)]}")
            f += 70
        else:
            ev.append(f"{f}:b")
            f += 70
    return ",".join(ev)


# --------------------------------------------------------------------------
# pokes: a warp by name, and the encounter accelerator (PLAN S3)
# --------------------------------------------------------------------------

WARP_NAME = 0x80305CF0  # the destination script's name, "MEnnnX.SCT", three words
CAME_FROM = 0x8030E420  # sys[15]: 0 takes the map's default entrance
FIELD_STATE = 0x80311AEC  # 15 is the game's own warp; poked last, after the name
STEP_COUNTER = 0x80346D28  # frames the player has moved since the last encounter
ACCELERATE = 100000  # makes the roll succeed; every gate still runs before the read
# The six-word battle request's flag. Never poked by a soak: it skips every
# gate, the story's included, and on a101b it left a black field
# (docs/research/soak.md 1b). A test holds the generator to this.
FORCED_BATTLE = 0x803473D4
WARP_FRAME = 3300  # the Continue lands at 2650
WARP_SETTLE = 400  # frames from the warp poke to a map worth soaking
POKE_MAX = 256  # main.c's POKE_MAX and PEEK_MAX: the rest would be refused


def warp_words(name: str) -> list[int]:
    """`116a` or `a116a` -> the three words of "ME116A.SCT", NUL-padded."""
    name = map_name(name)
    b = f"ME{name[1:4]}{name[4].upper()}.SCT".encode("ascii").ljust(12, b"\0")
    return [int.from_bytes(b[i : i + 4], "big") for i in range(0, 12, 4)]


def accelerator_frames(start: int, last: int, every: int) -> list[int]:
    return list(range(start, last + 1, every))


def pokes(
    warp: str | None = None,
    warp_frame: int = WARP_FRAME,
    encounter_every: int | None = None,
    first: int = 3200,
    last: int = 33000,
) -> str:
    """The SOA_POKE list, as one string: the warp (name, entrance, then the
    state that starts it, in that order -- pokes in one frame fire in list
    order) and a re-poke of the step counter every `encounter_every` frames
    from `first`, since the counter resets on every map load and battle."""
    items = []
    if warp is not None:
        for i, w in enumerate(warp_words(warp)):
            items.append((warp_frame, WARP_NAME + 4 * i, w))
        items += [(warp_frame, CAME_FROM, 0), (warp_frame, FIELD_STATE, 15)]
    if encounter_every is not None:
        items += [
            (f, STEP_COUNTER, ACCELERATE) for f in accelerator_frames(first, last, encounter_every)
        ]
    if len(items) > POKE_MAX:
        raise ValueError(
            f"{len(items)} pokes; the port holds {POKE_MAX} and would refuse the rest -- "
            "raise --encounter-every or shorten the run"
        )
    assert all(a != FORCED_BATTLE for _, a, _ in items)
    return ",".join(f"{f}:0x{a:08X}={v:#x}" for f, a, v in items)


def peeks(first: int, last: int, encounter_every: int) -> str:
    """SOA_PEEK of the step counter the frame after every accelerator poke:
    100000 or more there says the poke landed and nothing reset it."""
    frames = accelerator_frames(first, last, encounter_every)
    if len(frames) > POKE_MAX:
        raise ValueError(f"{len(frames)} peeks; the port holds {POKE_MAX}")
    return ",".join(f"0x{STEP_COUNTER:08X}@{f + 1}" for f in frames)


# --------------------------------------------------------------------------
# check: what a soak's log says about the run
# --------------------------------------------------------------------------

PASS, FAIL, SKIP = scenario.PASS, scenario.FAIL, scenario.SKIP
DID_NOT_TEST = "did not test what it says"
NOT_AVAILABLE = "not available"

ATTRACT = ("a299a", "a297a")  # the title's attract demo; a299a also loads at boot
GAME_OVER = "a090a"
# One battle's two stsicon lines are the same call, so no pad change falls
# between them; two battles are a fight apart, and no fight takes five seconds.
BATTLE_GAP = 150
DPAD = 0x000F  # si.c BTN_LEFT | BTN_RIGHT | BTN_DOWN | BTN_UP
ROOT = scenario.ROOT

# Paths as the port prints them (relative to ROOT, where scenario.py runs it).
SHARED_CARDS = {
    "build/savetest/work.raw": "the one card every soak job of 2026-09-23 copied its save "
    "into, so what it holds now is the last job's card, not this run's",
    "build/cards/slotA.raw": "the default card (no SOA_CARD), which every such run writes, "
    "so what it holds now is not this run's",
}

RE_STAMP = re.compile(r"^\[(?:si|poke|peek)\] frame (\d+)")
RE_BUTTONS = re.compile(r"^\[si\] frame \d+ \(retrace \d+\): buttons ([0-9A-Fa-f]{4})")
RE_FIELD_MAP = re.compile(r'"/field/(a\d{3}[a-z])\.mld"')
RE_BATTLE_HUD = re.compile(r'"/battle/(?:"\s*")?stsicon\.mld"')
RE_MEM = re.compile(r"^\[mem\] ")
RE_BP_MASK = re.compile(r"^\[gxr\] BP_MASK ")
# The [gxr] lines every rendering run prints: its report, its snapshots, the
# worker count, SOA_HASH's frame hashes. Every other [gxr] line is a
# WARN_ONCE, a tripwire or a complaint, and is raised as a question.
RE_GXR_ROUTINE = re.compile(
    r"^\[gxr\] (?:wrote |rasterizing on |producer over |workers: |time: |textures: |waits: |fences: |\d+ draw tokens came |\d+ triangles, "
    r"|\d+ decoded textures waited |\d+ draws sampled a texture |frame \d+ \d+x\d+ hash )"
)
RE_CARD = re.compile(r"^\[exi\] memory card (.+?)(?: \(\d+ bytes\)|: new blank card)$")
RE_CARD_IO = re.compile(r"^\[exi\] .*\bcard (\d+) bytes read, (\d+) written")
RE_CARD_CANNOT = re.compile(r"^\[exi\] cannot write ")
RE_RUN = re.compile(r"^\[run\] (\d+) game frames,.*?([\d.]+) wall seconds")
RE_PAD_FILE = re.compile(r"^\[pad\] replaying (\d+) state changes")
RE_PAD_FILE_TROUBLE = re.compile(r"^\[pad\] (?:cannot read |\S+:\d+ is not )")
RE_POKE_TROUBLE = re.compile(r"^\[(?:poke|peek)\] SOA_(?:POKE|PEEK): stopped at")
# What scenario.py itself prints (cmd_run), which only the run_*.log echo has.
RE_SCENARIO_EXIT = re.compile(r"^\[scenario\] \S+ exited (-?\d+):")
RE_SCENARIO_KILLED = re.compile(r"^\[scenario\] \S+ killed after ([\d.]+)s")
RE_SCENARIO_EVENTS = re.compile(r"^\[scenario\] \d+ frames, (\d+) pad events;")
RE_MAP_NAME = re.compile(r"a?(\d{3}[a-z])")


@dataclass
class Seen:
    """What a soak log says happened, as opposed to whether the run was healthy.

    Every frame here is a lower bound (see the module docstring), and None
    where no stamp came before the event."""

    traced: bool = False  # any [trace] line; the run_*.log echo has none
    echo: bool = False  # [scenario] lines: this is scenario.py's echo
    maps: list[tuple[str, int | None]] = field(default_factory=list)
    battles: list[int | None] = field(default_factory=list)
    # The field map each battle returned to, and the frame, one per battle;
    # None for a battle the log ends inside.
    after_battle: list[tuple[str, int | None] | None] = field(default_factory=list)
    dpad_presses: int = 0
    # (line, frame, the field map loaded last) -- the map is what places a
    # warning: all three BP_MASK lines of 2026-09-23 follow a090a.
    bp_mask: list[tuple[str, int | None, str | None]] = field(default_factory=list)
    gxr_warnings: list[tuple[str, int | None, str | None]] = field(default_factory=list)
    mem_lines: list[str] = field(default_factory=list)
    card_path: str | None = None
    card_read: int | None = None
    card_written: int | None = None
    card_unwritable: str | None = None
    exit_code: int | None = None
    killed_after: float | None = None
    generated_events: int | None = None
    pad_file_changes: int | None = None
    pad_file_trouble: str | None = None
    poke_trouble: str | None = None
    frames: int | None = None
    wall_seconds: float | None = None

    @property
    def game_overs(self) -> list[int | None]:
        return [f for m, f in self.maps if m == GAME_OVER]

    @property
    def landing(self) -> tuple[str, int | None] | None:
        return next(((m, f) for m, f in self.maps if m not in ATTRACT), None)


def read_seen(text: str) -> Seen:
    """One pass over the log, keeping what the verdict and the summary need."""
    s = Seen()
    frame: int | None = None
    in_battle, last_hud = False, None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = RE_STAMP.match(line)
        if m:
            frame = int(m.group(1))
            b = RE_BUTTONS.match(line)
            if b and int(b.group(1), 16) & DPAD:
                s.dpad_presses += 1
            continue
        if line.startswith("[trace] "):
            s.traced = True
            m = RE_FIELD_MAP.search(line)
            if m:
                if in_battle and s.after_battle and s.after_battle[-1] is None:
                    s.after_battle[-1] = (m.group(1), frame)
                in_battle = False
                if not s.maps or s.maps[-1][0] != m.group(1):
                    s.maps.append((m.group(1), frame))
            elif RE_BATTLE_HUD.search(line):
                apart = frame is not None and last_hud is not None and frame - last_hud > BATTLE_GAP
                if not in_battle or apart:
                    s.battles.append(frame)
                    s.after_battle.append(None)
                in_battle, last_hud = True, frame
            continue
        if RE_MEM.match(line):
            s.mem_lines.append(line)
        elif line.startswith("[gxr] "):
            last_map = s.maps[-1][0] if s.maps else None
            if RE_BP_MASK.match(line):
                s.bp_mask.append((line, frame, last_map))
            elif not RE_GXR_ROUTINE.match(line):
                s.gxr_warnings.append((line, frame, last_map))
        elif line.startswith("[scenario] "):
            s.echo = True
            if m := RE_SCENARIO_EXIT.match(line):
                s.exit_code = int(m.group(1))
            elif m := RE_SCENARIO_KILLED.match(line):
                s.killed_after = float(m.group(1))
            elif m := RE_SCENARIO_EVENTS.match(line):
                s.generated_events = int(m.group(1))
        elif m := RE_CARD.match(line):
            s.card_path = m.group(1)
        elif m := RE_CARD_IO.match(line):
            s.card_read, s.card_written = int(m.group(1)), int(m.group(2))
        elif RE_CARD_CANNOT.match(line):
            s.card_unwritable = line
        elif m := RE_RUN.match(line):
            s.frames, s.wall_seconds = int(m.group(1)), float(m.group(2))
        elif m := RE_PAD_FILE.match(line):
            s.pad_file_changes = int(m.group(1))
        elif RE_PAD_FILE_TROUBLE.match(line) and s.pad_file_trouble is None:
            s.pad_file_trouble = line
        elif RE_POKE_TROUBLE.match(line) and s.poke_trouble is None:
            s.poke_trouble = line
    return s


def map_name(text: str) -> str:
    """`116a` or `a116a`, as the plan and the logs spell a map, to `a116a`."""
    m = RE_MAP_NAME.fullmatch(text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r} is not a map name like 116a or a116a")
    return "a" + m.group(1)


def at(frame: int | None) -> str:
    return f"frame {frame}" if frame is not None else "an unstamped frame"


def _canon(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def card_check(s: Seen) -> tuple[scenario.Check, list[str]]:
    """The card the run ends with, and any question it raises."""
    name = "the card is one the game accepts"
    if s.card_unwritable:
        return scenario.Check(name, FAIL, s.card_unwritable), []
    if s.card_path is None:
        return scenario.Check(name, NOT_AVAILABLE, "the log names no memory card"), []
    card = Path(s.card_path)
    where = card if card.is_absolute() else ROOT / card
    for shared, why in SHARED_CARDS.items():
        if _canon(where) == _canon(ROOT / shared):
            wrote = f"; this run wrote {s.card_written} bytes to it" if s.card_written else ""
            return scenario.Check(name, NOT_AVAILABLE, f"{s.card_path} is {why}{wrote}"), []
    if not where.is_file():
        return scenario.Check(name, NOT_AVAILABLE, f"no card at {s.card_path} any more"), []
    import cardformat  # only a job's own card needs it

    verdict = cardformat.verify(cardformat.load_image(where))
    result = cardformat.RESULT_NAMES.get(verdict.result, str(verdict.result))
    if verdict.result == 0:
        return scenario.Check(name, PASS, f"{s.card_path}: READY"), []
    if verdict.accepted:
        why = (
            f"{s.card_path} verifies {result}, which the game repairs on its next mount: "
            "was a save cut off by the frame limit?"
        )
        return scenario.Check(name, PASS, f"{s.card_path}: {result}, repairable"), [why]
    return scenario.Check(name, FAIL, f"{s.card_path}: {result}, which the game refuses"), []


def pad_check(r: scenario.Report, s: Seen) -> scenario.Check:
    """scenario.py's pad check, plus a recording (SOA_PAD_FILE) as a source,
    and the echo's generated count as the number to match."""
    name = "the pad script was understood"
    trouble = r.pad_trouble or s.pad_file_trouble
    if trouble:
        return scenario.Check(name, FAIL, trouble, False)
    if r.scripted_events is not None:
        want = s.generated_events
        if want is not None and r.scripted_events != want:
            said = f"the port read {r.scripted_events} events where scenario.py sent {want}"
            return scenario.Check(name, FAIL, said, False)
        of = f" of {want} generated" if want is not None else ""
        return scenario.Check(name, PASS, f"{r.scripted_events} events{of}", False)
    if s.pad_file_changes is not None:
        return scenario.Check(name, PASS, f"{s.pad_file_changes} recorded state changes", False)
    return scenario.Check(name, SKIP, "no [si] or [pad] line: no input was scripted", False)


# After each battle the field reloads, and the snapshots that follow must show
# it: a101b's forced battle came back to a black field (docs/research/soak.md
# 1b). The window is wide because the reload's frame is a lower bound (up to
# 130 frames early) and the field then fades in over about 30 frames.
AFTER_BATTLE_WINDOW = 400
BRIGHT = 32  # a channel value above this is not black
BLACK_SHARE = 0.005  # fewer bright channel values than this share, and it is black
_DARK = bytes(0 if i <= BRIGHT else 1 for i in range(256))


def snapshots(frames_dir: Path) -> dict[int, Path]:
    """`NNNN.png` by frame number, as SOA_SNAP names them."""
    return {int(p.stem): p for p in frames_dir.glob("*.png") if p.stem.isdigit()}


def is_black(path: Path) -> bool:
    """Whether a snapshot is black. The port's own PNGs only (runtime/png.c:
    8-bit RGBA, filter 0 on every row), and anything else is refused rather
    than guessed at."""
    d = path.read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    i, idat, w = 8, [], 0
    while i + 8 <= len(d):
        n = int.from_bytes(d[i : i + 4], "big")
        tag, body = d[i + 4 : i + 8], d[i + 8 : i + 8 + n]
        if tag == b"IHDR":
            w, h, depth, colour = body[0:4], body[4:8], body[8], body[9]
            w, h = int.from_bytes(w, "big"), int.from_bytes(h, "big")
            if (depth, colour) != (8, 6):
                raise ValueError(f"{path}: not 8-bit RGBA, so not a port snapshot")
        elif tag == b"IDAT":
            idat.append(body)
        i += 12 + n
    if not w:
        raise ValueError(f"{path}: no IHDR")
    raw = zlib.decompress(b"".join(idat))
    stride = 1 + w * 4
    if any(raw[y * stride] for y in range(h)):
        raise ValueError(f"{path}: a filtered row, so not a port snapshot")
    rgba = b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(h))
    bright = sum(len(c) - c.translate(_DARK).count(0) for c in (rgba[0::4], rgba[1::4], rgba[2::4]))
    return bright < BLACK_SHARE * 3 * w * h


def after_battle_questions(s: Seen, frames_dir: Path) -> tuple[list[str], list[dict]]:
    """A question for every battle whose return to the field shows only black
    snapshots, and the evidence for summary.json. A battle lost to a game over
    returns to a090a, not the field, and is not asked about."""
    shots = snapshots(frames_dir)
    questions, rows = [], []
    for battle, after in zip(s.battles, s.after_battle, strict=True):
        if after is None or after[1] is None or after[0] == GAME_OVER:
            continue
        m, f = after
        window = sorted(n for n in shots if f < n <= f + AFTER_BATTLE_WINDOW)
        black = [n for n in window if is_black(shots[n])]
        rows.append({"battle": battle, "map": m, "frame": f, "snapshots": window, "black": black})
        where = f"the return to {m} after the battle at {at(battle)} ({at(f)})"
        if not window:
            questions.append(
                f"no snapshot within {AFTER_BATTLE_WINDOW} frames of {where}, so nothing shows the "
                f"field came back ({frames_dir})"
            )
        elif len(black) == len(window):
            questions.append(
                f"black after battle: every snapshot of {where}, frames {window[0]}-{window[-1]}, "
                "is black"
            )
    return questions, rows


def judge(
    text: str,
    log: str,
    expect_battles: int | None = None,
    expect_map: str | None = None,
    expect_reach: str | None = None,
    frames_dir: Path | None = None,
) -> dict:
    """Everything `check` says about one log, as the object summary.json holds."""
    r = scenario.parse_report(text)
    s = read_seen(text)
    checks = [
        c
        for c in scenario.check_report(
            r, s.exit_code, r.rendered, s.generated_events, s.killed_after
        )
        if c.name != "the pad script was understood"
    ]
    checks.append(pad_check(r, s))
    if r.stop_lines:
        checks.append(scenario.Check("no stop line", FAIL, r.stop_lines[0]))
    else:
        checks.append(
            scenario.Check("no stop line", PASS, "no [trap], [spin], [unimplemented] or [watchdog]")
        )
    if s.mem_lines:
        more = f" (and {len(s.mem_lines) - 1} more)" if len(s.mem_lines) > 1 else ""
        checks.append(scenario.Check("no [mem] line", FAIL, s.mem_lines[0][:200] + more))
    else:
        checks.append(scenario.Check("no [mem] line", PASS, "the tripwire never fired"))
    if s.poke_trouble:
        checks.append(scenario.Check("the pokes were understood", FAIL, s.poke_trouble))
    landing = s.landing
    if expect_map is not None:
        name = f"the run landed on {expect_map}"
        if not s.traced:
            why = (
                "--expect-map asks for a landing map, and this log has no [trace] line to read one"
            )
            checks.append(scenario.Check(name, FAIL, why))
        elif landing is None or landing[0] != expect_map:
            got = f"{landing[0]} at {at(landing[1])}" if landing else "no field map past the title"
            checks.append(scenario.Check(name, FAIL, f"it landed on {got}"))
        else:
            checks.append(scenario.Check(name, PASS, f"at {at(landing[1])}"))
    if expect_reach is not None:
        # A warp job: the save lands somewhere else first, and the warp's own
        # map has to follow. One that never loaded soaked the wrong map.
        name = f"the run reached {expect_reach}"
        reached = [f for m, f in s.maps if m == expect_reach]
        if not s.traced:
            why = "--expect-reach asks for a map, and this log has no [trace] line to read one"
            checks.append(scenario.Check(name, FAIL, why))
        elif not reached:
            seen = " > ".join(m for m, _ in s.maps) or "no field map at all"
            checks.append(scenario.Check(name, FAIL, f"it never loaded; maps: {seen}"))
        else:
            checks.append(scenario.Check(name, PASS, f"at {at(reached[0])}"))
    card, card_questions = card_check(s)
    checks.append(card)

    setup: list[scenario.Check] = []
    if r.scripted_events is None and s.pad_file_changes is None and not r.pad_trouble:
        setup.append(
            scenario.Check("input drove the run", DID_NOT_TEST, "no pad script and no recording")
        )
    no_trace = "no [trace] lines (a run_*.log echo leaves them out; SOA_TRACE=1 prints them)"
    if not s.traced:
        setup.append(scenario.Check("the run left the title", SKIP, no_trace))
    elif landing is None:
        demo = " > ".join(m for m, _ in s.maps) or "no field map at all"
        setup.append(
            scenario.Check("the run left the title", DID_NOT_TEST, f"only the attract demo: {demo}")
        )
    else:
        setup.append(
            scenario.Check("the run left the title", PASS, f"{landing[0]} at {at(landing[1])}")
        )
    if expect_battles is not None:
        claim = f"--expect-battles {expect_battles}"
    elif s.dpad_presses:
        claim = f"the --battle mix ({s.dpad_presses} d-pad presses)"
    else:
        claim = None
    wanted = expect_battles or 1
    battles = len(s.battles) if s.traced else None
    if claim is None:
        setup.append(
            scenario.Check("it fought what it claims", SKIP, "no battle claim: walk mix, no flag")
        )
    elif battles is None:
        setup.append(scenario.Check("it fought what it claims", SKIP, f"{claim}; {no_trace}"))
    elif battles < wanted:
        said = f"{claim}, and {battles} battle(s) where it wants {wanted}"
        setup.append(scenario.Check("it fought what it claims", DID_NOT_TEST, said))
    else:
        setup.append(scenario.Check("it fought what it claims", PASS, f"{claim}: {battles}"))

    def placed(line: str, frame: int | None, last_map: str | None) -> str:
        where = f"after {last_map} loaded" if last_map else "before any field map"
        return f"{line} ({at(frame)}, {where})"

    questions = [placed(*q) for q in s.bp_mask]
    seen_warning: set[str] = set()
    for q in s.gxr_warnings:
        # A debug switch can repeat one warning with new numbers every frame.
        key = re.sub(r"\b[0-9A-Fa-f]*\d[0-9A-Fa-f.]*\b", "#", q[0])
        if key not in seen_warning:
            seen_warning.add(key)
            questions.append(placed(*q))
    questions += card_questions
    after_rows = None
    if frames_dir is not None and s.traced:
        more, after_rows = after_battle_questions(s, frames_dir)
        questions += more

    if any(c.status == FAIL for c in checks):
        verdict = FAIL
    elif any(c.status == DID_NOT_TEST for c in setup):
        verdict = DID_NOT_TEST
    else:
        verdict = PASS
    overs = s.game_overs if s.traced else None
    return {
        "log": log,
        "kind": "scenario.py echo" if s.echo else "port log",
        "verdict": verdict,
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
        "setup": [{"name": c.name, "status": c.status, "detail": c.detail} for c in setup],
        "questions": questions,
        "battle_claim": claim,
        "battles": battles,
        "battle_frames": s.battles if s.traced else None,
        "after_battle": after_rows,
        "game_over_frame": overs[0] if overs else None,
        "game_over_frames": overs,
        "maps": [{"map": m, "frame": f} for m, f in s.maps] if s.traced else None,
        "landing_map": landing[0] if landing else None,
        "landing_frame": landing[1] if landing else None,
        "card": {
            "path": s.card_path,
            "status": card.status,
            "detail": card.detail,
            "bytes_read": s.card_read,
            "bytes_written": s.card_written,
        },
        "frames": s.frames,
        "wall_seconds": s.wall_seconds,
        "pad_events": r.scripted_events,
    }


def missing(log: str) -> dict:
    """A log that is not there fails: a job whose log vanished proved nothing."""
    empty = judge("", log)
    empty["verdict"] = FAIL
    empty["checks"] = [{"name": "the log exists", "status": FAIL, "detail": f"no file at {log}"}]
    return empty


def short_name(log: str) -> str:
    stem = Path(log).stem
    return stem.removeprefix("scenario-")


def print_result(res: dict) -> None:
    print(f"== {res['log']} ({res['kind']})")
    rows = [("check", c) for c in res["checks"]] + [("setup", c) for c in res["setup"]]
    width = max(len(c["name"]) for _, c in rows)
    for tag, c in rows:
        print(f"[{tag}] {c['name']:<{width}}  {c['status']:<4}  {c['detail']}")
    if res["battles"] is not None:
        frames = ", ".join(str(f) for f in res["battle_frames"])
        print(f"[seen] {res['battles']} battle(s)" + (f" at frames {frames}" if frames else ""))
        overs = res["game_over_frames"]
        print("[seen] game over " + (", ".join(at(f) for f in overs) if overs else "none"))
        print("[seen] maps " + (" > ".join(m["map"] for m in res["maps"]) or "none"))
    else:
        print("[seen] battles and maps not available: this log has no [trace] lines")
    for q in res["questions"]:
        print(f"[question] {q}")
    tail = []
    if res["battles"] is not None:
        tail.append(f"{res['battles']} battle(s)")
    if res["game_over_frame"] is not None:
        tail.append(f"game over at frame {res['game_over_frame']}")
    if res["landing_map"]:
        tail.append(f"landed on {res['landing_map']}")
    if res["questions"]:
        tail.append(f"{len(res['questions'])} question(s)")
    print(
        f"{short_name(res['log'])}: {res['verdict']}" + (f" -- {', '.join(tail)}" if tail else "")
    )
    print()


def print_table(results: list[dict]) -> None:
    head = ("log", "verdict", "battles", "game over", "landing", "card", "questions")
    rows = [
        (
            short_name(r["log"]),
            r["verdict"],
            "-" if r["battles"] is None else str(r["battles"]),
            "-" if r["game_over_frame"] is None else str(r["game_over_frame"]),
            r["landing_map"] or "-",
            r["card"]["status"],
            str(len(r["questions"])),
        )
        for r in results
    ]
    widths = [max(len(row[i]) for row in [head, *rows]) for i in range(len(head))]
    for row in [head, *rows]:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())


def cmd_check(args: argparse.Namespace) -> int:
    results = []
    for log in args.logs:
        path = Path(log)
        if not path.is_file():
            res = missing(log)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            frames = Path(args.frames) if args.frames else None
            res = judge(text, log, args.expect_battles, args.expect_map, args.expect_reach, frames)
        print_result(res)
        results.append(res)
    if len(results) > 1:
        print_table(results)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
    return 1 if any(r["verdict"] == FAIL for r in results) else 0


def at_least_one(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError(
            "--expect-battles is a floor of 1 or more; a run that must fight none is a "
            "different check"
        )
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="`python tools/soak.py check --help` for the log checker",
    )
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--first",
        type=int,
        default=None,
        help="first frame of random play and of the accelerator (default 3200, after the save "
        "loads; with --warp, WARP_SETTLE frames after the warp)",
    )
    p.add_argument("--last", type=int, default=33000, help="no new step starts after this frame")
    p.add_argument(
        "--battle", action="store_true", help="add d-pad steps, to turn the battle wheel"
    )
    p.add_argument(
        "--warp",
        type=map_name,
        metavar="NNNx",
        help="warp there by name at --warp-frame (random play then starts WARP_SETTLE frames later)",
    )
    p.add_argument("--warp-frame", type=int, default=WARP_FRAME, metavar="F")
    p.add_argument(
        "--encounter-every",
        type=int,
        metavar="K",
        help=f"re-poke the step counter to {ACCELERATE} every K frames from --first",
    )
    out = p.add_mutually_exclusive_group()
    out.add_argument("--pokes", action="store_true", help="print SOA_POKE instead of SOA_PAD")
    out.add_argument(
        "--peeks",
        action="store_true",
        help="print SOA_PEEK of the step counter the frame after each accelerator poke",
    )
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="judge soak logs: invariants, setup, battles, questions")
    c.add_argument("logs", nargs="+", metavar="LOG", help="a scenario log, or a run_*.log echo")
    c.add_argument(
        "--expect-battles",
        type=at_least_one,
        metavar="N",
        help="the job claims at least N battles (the --battle mix claims 1 without it)",
    )
    c.add_argument(
        "--expect-map",
        type=map_name,
        metavar="NNNx",
        help="the landing map; any other FAILs",
    )
    c.add_argument(
        "--expect-reach",
        type=map_name,
        metavar="NNNx",
        help="a map the run must load after landing, as a warp job's destination; none FAILs",
    )
    c.add_argument(
        "--frames",
        metavar="DIR",
        help="the job's own snapshots: a return to the field after a battle whose snapshots "
        "are all black is a question",
    )
    c.add_argument("--json", metavar="PATH", help="write one object per log to PATH")
    a = p.parse_args(argv)
    if a.cmd == "check":
        return cmd_check(a)
    if a.first is None:
        a.first = a.warp_frame + WARP_SETTLE if a.warp else 3200
    try:
        if a.pokes:
            print(pokes(a.warp, a.warp_frame, a.encounter_every, a.first, a.last))
            return 0
        if a.peeks:
            if a.encounter_every is None:
                p.error(
                    "--peeks reads the step counter after each accelerator poke; give --encounter-every"
                )
            print(peeks(a.first, a.last, a.encounter_every))
            return 0
    except ValueError as e:
        p.error(str(e))
    print(script(a.seed, a.first, a.last, a.battle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
