"""tools/soak.py: the soak-test script has to repeat exactly and has to be one
si.c reads whole -- a fault found by seed 7 is only useful if seed 7 replays
the same presses, and a script si.c stops parsing halfway through would soak
nothing and say so only in the log."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import cardformat  # noqa: E402
import scenario  # noqa: E402
import soak  # noqa: E402


def test_the_same_seed_gives_the_same_script():
    assert soak.script(7) == soak.script(7)
    assert soak.script(7) != soak.script(11)


def test_the_script_passes_the_strict_pad_grammar():
    """parse_pad refuses everything si.c would stop at or silently drop."""
    for seed in (1, 7, 11, 12345):
        events = scenario.parse_pad(soak.script(seed))
        assert len(events) > 100, seed


def test_it_starts_with_the_continue_presses_and_stays_in_bounds():
    events = scenario.parse_pad(soak.script(7, first=3200, last=9000))
    frames = [e.frame for e in events]
    assert frames[:9] == [1600, 1640, 1800, 1840, 2000, 2040, 2240, 2440, 2640]
    assert all(3200 <= f < 9000 + 220 for f in frames[9:])
    assert frames == sorted(frames)


def test_it_never_exceeds_what_si_c_holds():
    """si.c keeps 1024 events and drops the rest without a word."""
    assert len(scenario.parse_pad(soak.script(3, first=3200, last=10**7))) <= 1000


def test_the_step_mix_is_the_documented_one():
    """Mostly stick, some A, less B, a few menu visits -- all four present."""
    text = soak.script(7, 3200, 60000)
    assert "#" in text and ":a," in text and ":b," in text and ":start," in text


def test_the_battle_mix_turns_the_wheel_and_still_parses():
    """Single-step d-pad presses, so the wheel lands on commands other than
    Attack; and the default mix is untouched by the option existing."""
    text = soak.script(21, 3200, 33000, battle=True)
    events = scenario.parse_pad(text)
    assert len(events) > 100 and len(events) <= 1000
    assert any(t in text for t in ("left#4", "right#4", "up#4", "down#4"))
    assert soak.script(7) == soak.script(7, battle=False)


def test_the_command_line_still_prints_the_script(capsys):
    """`check` is a subcommand; `soak.py --seed 7` must print what it always did,
    because the soaks in build/ were made by exactly that invocation."""
    assert soak.main(["--seed", "7"]) == 0
    assert capsys.readouterr().out.strip() == soak.script(7)
    assert soak.main(["--seed", "21", "--battle"]) == 0
    assert capsys.readouterr().out.strip() == soak.script(21, battle=True)


# --------------------------------------------------------------------------
# check: synthetic logs in the runtime's own line formats. A clean one first,
# which has to pass, or the mutations after it prove nothing.
# --------------------------------------------------------------------------

LOAD = '[trace] LoadStart                pc 801C63EC lr 801CBEF8 msr 00008032 "{}"'
CREW = '[trace] LoadCrew                 pc 8006EB88 lr 8006E968 "/battle/" "stsicon.mld"'
ASSET = '[trace] LoadAsset                pc 801DB244 lr 8006ED78 "/battle/stsicon.mld"'
MMIO = "[mmio!] rd CC008018/2 = 0 (outside modelled range)"
MEM = (
    "[mem] a load from block 80012340 reached 81800010, past the console's 24 MB of RAM; the "
    "port keeps zeroed scratch up there so that it does not reach the host heap. An address "
    "up there means the port is not modelling something. Reported once."
)
BP_MASK = (
    "[gxr] BP_MASK 080000 was in force for BP 00 000001, which also changes 000011 outside "
    "the mask; we apply all 24 bits, so those changed too and the register now differs from "
    "the hardware's by that much"
)
GX = (
    "[gx] 1000000 pipe bytes, 5000 commands: 100 BP, 100 XF, 100 CP loads, 10 display lists, "
    "500 draws (3000 vertices); 2 draw-dones, 10 tokens, 10 EFB copies, 0 unknown bytes"
)


def si(frame: int, buttons: str = "0000") -> str:
    return f"[si] frame {frame} (retrace {frame * 2}): buttons {buttons}"


def field_map(name: str) -> str:
    return LOAD.format(f"/field/{name}.mld")


# One battle on a116a, logged the way every real one is: LoadCrew, then
# LoadAsset from inside it, then the field reloads.
ONE_BATTLE = [si(4723), CREW, ASSET, si(5100, "0100"), LOAD.format("/player.mld")]
ONE_BATTLE.append(field_map("a116a"))


def soak_log(play=ONE_BATTLE, card="build/savetest/work.raw", land="a116a") -> str:
    lines = [
        "[boot] DOL 3166656 bytes, FST 134426 bytes at 816DF2E0; entering fn_80003140",
        "[run] headless, a snapshot to build/frames every 1000 frames; stopping after 6000 frames",
        f"[exi] memory card {card} (524288 bytes)",
        "[si] 12 scripted controller events",
        "[gxr] rasterizing on 8 worker threads",
        field_map("a299a"),
        si(1600, "1000"),
        si(2640, "0100"),
        LOAD.format("/player.mld"),
        field_map(land),
        si(3200),
        *play,
        "[boot] 6000 frames done (SOA_FRAMES)",
        "[run] 6000 game frames, 12000 VI retraces (2.00 per frame); 200.0 guest seconds at "
        "SOA_SPEED=1, 200.0 wall seconds",
        GX,
        "[gxr] 900 triangles, 0 lines, 0 points; 5000 pixels shaded; 0 bad vertex refs; "
        "5 texture copies, 6 screen copies",
        "[exi] 1071 immediate, 385 DMA transfers; card 172032 bytes read, 0 written, 0 interrupts",
    ]
    return "\n".join(lines) + "\n"


def status(res: dict, name: str) -> str:
    return next(c["status"] for c in res["checks"] + res["setup"] if c["name"] == name)


def test_a_clean_log_passes_and_says_what_it_saw():
    """The baseline every mutation below is measured against: it has to pass,
    and what it reports has to be what the synthetic log holds."""
    res = soak.judge(soak_log(), "clean.log", expect_map="a116a")
    assert res["verdict"] == "pass", res["checks"]
    assert res["battles"] == 1 and res["battle_frames"] == [4723]
    assert res["landing_map"] == "a116a" and res["landing_frame"] == 2640
    assert [m["map"] for m in res["maps"]] == ["a299a", "a116a"]
    assert res["game_over_frame"] is None and res["questions"] == []


@pytest.mark.parametrize(
    "mutate, expect_map, broken",
    [
        (lambda t: t.replace(GX, GX + "\n" + MMIO), None, "no MMIO outside the modelled range"),
        (lambda t: t.replace("0 unknown bytes", "5 unknown bytes"), None, "no unknown FIFO bytes"),
        (lambda t: t.replace(GX, MEM + "\n" + GX), None, "no [mem] line"),
        (lambda t: t.replace(GX + "\n", ""), None, "no unknown FIFO bytes"),
        (
            lambda t: t.replace(field_map("a116a"), field_map("a018a")),
            "a116a",
            "the run landed on a116a",
        ),
    ],
    ids=["mmio", "unknown-bytes", "mem-tripwire", "no-gx-line", "wrong-landing-map"],
)
def test_each_injected_mutation_fails(mutate, expect_map, broken):
    """The oracle has to be able to say no: each fault S1 names, injected into
    the clean log, turns the verdict to FAIL through the check it belongs to.
    A missing [gx] line is the run dying before its report."""
    res = soak.judge(mutate(soak_log()), "mutated.log", expect_map=expect_map)
    assert res["verdict"] == "FAIL"
    assert status(res, broken) == "FAIL"


def test_a_stop_line_fails_even_beside_a_frame_limit():
    """The exit check reads the frame limit; a [trap] line must fail on its own."""
    text = soak_log().replace(GX, "[trap] at 80012340\n" + GX)
    assert status(soak.judge(text, "trap.log"), "no stop line") == "FAIL"


def test_a_battle_logged_twice_is_one_battle():
    """Every battle logs stsicon.mld twice (LoadCrew, then LoadAsset), so the
    count is of battles, not lines; a field reload or a long gap between two
    loads is what makes a second one."""
    assert soak.judge(soak_log(), "x.log")["battles"] == 1
    two = ONE_BATTLE + [si(9000), CREW, ASSET, field_map("a116a")]
    assert soak.judge(soak_log(two), "x.log")["battle_frames"] == [4723, 9000]
    # Back to back, no field in between: the pad moved 300 frames, so two.
    back_to_back = [si(4723), CREW, ASSET, si(5023), CREW, ASSET, field_map("a116a")]
    assert soak.judge(soak_log(back_to_back), "x.log")["battles"] == 2


def test_the_ship_hud_is_not_a_battle():
    """/field/stsicon.mld loads with every 5xx ship stage, not with a battle."""
    ship = [si(4000), field_map("a500a"), '[trace] LoadAsset pc 801DB244 "/field/stsicon.mld"']
    assert soak.judge(soak_log(ship), "x.log")["battles"] == 0


def test_game_over_is_found_with_its_frame():
    """a090a is the game-over map; its frame is the last pad stamp before it."""
    lost = ONE_BATTLE + [si(20730), si(20792), LOAD.format("/player.mld"), field_map("a090a")]
    lost += [field_map("a299a"), field_map("a297a")]
    res = soak.judge(soak_log(lost), "x.log")
    assert res["game_over_frame"] == 20792 and res["verdict"] == "pass"
    assert res["landing_map"] == "a116a"  # the attract demo after it is not a landing


def test_a_battle_job_that_met_no_battle_did_not_test_what_it_says(tmp_path):
    """The --battle mix is recognised by its d-pad presses; with no stsicon
    load it is healthy but untested, which is neither pass nor FAIL, and does
    not fail the exit status."""
    walk = [si(4000), si(4004, "0008"), si(4100)]
    res = soak.judge(soak_log(walk), "x.log")
    assert res["verdict"] == soak.DID_NOT_TEST
    assert res["battle_claim"].startswith("the --battle mix")
    log = tmp_path / "scenario-bsoak.log"
    log.write_text(soak_log(walk), encoding="utf-8")
    assert soak.main(["check", str(log)]) == 0


def test_a_walk_soak_claims_no_battle_whatever_its_scenario():
    """No d-pad, no --expect-battles: zero battles is simply what happened.
    Asked for with --expect-battles, the same log did not test what it says."""
    res = soak.judge(soak_log([si(4000)]), "x.log")
    assert res["verdict"] == "pass" and res["battles"] == 0 and res["battle_claim"] is None
    res = soak.judge(soak_log([si(4000)]), "x.log", expect_battles=1)
    assert res["verdict"] == soak.DID_NOT_TEST


def test_the_attract_demo_is_not_a_landing():
    """A run that missed the Continue soaks the title's attract demo and still
    exits 0 clean; it must not read as a pass."""
    res = soak.judge(soak_log([si(4000), field_map("a297a")], land="a299a"), "x.log")
    assert res["landing_map"] is None and res["verdict"] == soak.DID_NOT_TEST


def test_bp_mask_is_a_question_not_a_failure():
    """A tripwire that may or may not matter is for a person to look at, with
    where it happened; it must not fail the run."""
    text = soak_log(ONE_BATTLE + [si(20792), field_map("a090a"), BP_MASK])
    res = soak.judge(text, "x.log")
    assert res["verdict"] == "pass"
    assert res["questions"] == [f"{BP_MASK} (frame 20792, after a090a loaded)"]


def test_the_shared_card_is_not_available_and_a_jobs_own_is_verified(tmp_path):
    """work.raw held whichever job ran last, so it says nothing about this one;
    a job's own card is verified, and one the game refuses fails the run."""
    res = soak.judge(soak_log(), "x.log")
    assert res["card"]["status"] == soak.NOT_AVAILABLE and res["verdict"] == "pass"
    geom = cardformat.RUNTIME_GEOMETRY
    good, bad = tmp_path / "good.raw", tmp_path / "bad.raw"
    good.write_bytes(bytes(cardformat.format_image()))
    image = cardformat.format_image()
    cardformat.damage(image, geom, "dir")
    cardformat.damage(image, geom, "fat")
    bad.write_bytes(bytes(image))
    assert soak.judge(soak_log(card=str(good)), "x.log")["card"]["status"] == "pass"
    res = soak.judge(soak_log(card=str(bad)), "x.log")
    assert res["card"]["status"] == "FAIL" and res["verdict"] == "FAIL"


def test_the_run_echo_is_read_for_its_exit_and_pad_count():
    """scenario.py's echo has the exit code and the generated pad count, and no
    [trace] lines, so battles are unavailable rather than zero."""
    port = [line for line in soak_log().splitlines() if not line.startswith("[trace]")]
    head = ["[scenario] battle: a summary", "[scenario] 6000 frames, 12 pad events; log: x.log"]
    tail = ["[scenario] battle exited 0: the frame limit, or a closed window; log in x.log"]
    echo = "\n".join(head + port + tail)
    res = soak.judge(echo, "run_x.log")
    assert res["verdict"] == "pass" and res["battles"] is None and res["maps"] is None
    assert res["kind"] == "scenario.py echo"
    miscounted = soak.judge(echo.replace("12 pad", "13 pad"), "x")
    assert status(miscounted, "the pad script was understood") == "FAIL"
    assert soak.judge(echo.replace("exited 0:", "exited 5:"), "x")["verdict"] == "FAIL"


def test_check_exits_1_on_a_failure_and_writes_one_object_per_log(tmp_path):
    """The exit status is what a batch runner reads; summary.json is what a
    report is built from, so a missing log gets an object too."""
    clean, bad = tmp_path / "clean.log", tmp_path / "bad.log"
    clean.write_text(soak_log(), encoding="utf-8")
    bad.write_text(soak_log().replace("0 unknown bytes", "5 unknown bytes"), encoding="utf-8")
    out = tmp_path / "summary.json"
    assert soak.main(["check", str(clean), "--json", str(out)]) == 0
    gone = str(tmp_path / "gone.log")
    assert soak.main(["check", str(clean), str(bad), gone, "--json", str(out)]) == 1
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert [r["verdict"] for r in summary] == ["pass", "FAIL", "FAIL"]


# --------------------------------------------------------------------------
# S3: the warp and the encounter accelerator, and what check makes of them
# --------------------------------------------------------------------------


def poke_items(text: str) -> list[tuple[int, int, int]]:
    """SOA_POKE back into (frame, address, value), as main.c's parser reads it."""
    out = []
    for item in text.split(","):
        frame, rest = item.split(":")
        addr, value = rest.split("=")
        out.append((int(frame), int(addr, 0), int(value, 0)))
    return out


@pytest.mark.parametrize(
    "kw",
    [
        {"encounter_every": 600},
        {"warp": "116c", "encounter_every": 600, "first": 3700},
        {"warp": "a101b", "encounter_every": 300, "first": 3700, "last": 40000},
        {"warp": "099a"},
        {"encounter_every": 1, "first": 3200, "last": 3300},
    ],
)
def test_no_soak_poke_ever_names_the_forced_battle_flag(kw):
    """0x803473D4 starts a battle past every gate the story sets -- on a101b
    it came back to a black field. A soak only shortens the wait for the
    battles the game itself would allow (docs/research/soak.md 1b)."""
    text = soak.pokes(**kw)
    assert "803473d4" not in text.lower()
    assert all(a != 0x803473D4 for _, a, _ in poke_items(text))


def test_the_warp_spells_the_script_name_and_starts_it_last():
    """The name, then sys[15]=0 for the default entrance, then field state 15
    -- in that order within the frame, since state 15 is what reads the name.
    The words are the ones the ship-battle captures warped with (FINDINGS H4)."""
    items = poke_items(soak.pokes(warp="550a"))
    assert items == [
        (3300, 0x80305CF0, 0x4D453535),
        (3300, 0x80305CF4, 0x30412E53),
        (3300, 0x80305CF8, 0x43540000),
        (3300, 0x8030E420, 0),
        (3300, 0x80311AEC, 15),
    ]
    assert poke_items(soak.pokes(warp="099a"))[1][2] == 0x39412E53  # "9A.S"


def test_the_accelerator_repeats_every_k_frames():
    """The counter resets on every map load and battle, so it is re-poked;
    at K=600 that is the 50 pokes per 30k frames the plan counts on."""
    items = poke_items(soak.pokes(encounter_every=600, first=3200, last=33000))
    assert len(items) == 50
    assert [f for f, _, _ in items] == list(range(3200, 33000, 600))
    assert {(a, v) for _, a, v in items} == {(0x80346D28, 100000)}


def test_more_pokes_than_the_port_holds_is_refused():
    """main.c holds 256 pokes and refuses the rest; a job whose accelerator
    stops halfway would read as a map with few encounters."""
    with pytest.raises(ValueError, match="299 pokes"):
        soak.pokes(encounter_every=100)
    with pytest.raises(SystemExit):
        soak.main(["--pokes", "--encounter-every", "100"])


def test_the_accelerator_leaves_the_pad_script_alone(capsys):
    """An accelerated job and its baseline must press the same buttons, or a
    difference in battles is a difference in input."""
    assert soak.main(["--seed", "33", "--encounter-every", "600"]) == 0
    assert capsys.readouterr().out.strip() == soak.script(33)


def test_with_a_warp_random_play_waits_for_it(capsys):
    """Random input during the warp's load would soak the loading screen."""
    assert soak.main(["--seed", "7", "--warp", "116c"]) == 0
    assert capsys.readouterr().out.strip() == soak.script(7, first=3300 + soak.WARP_SETTLE)
    assert soak.main(["--pokes", "--warp", "116c", "--encounter-every", "600"]) == 0
    first_accel = poke_items(capsys.readouterr().out.strip())[5]
    assert first_accel == (3300 + soak.WARP_SETTLE, 0x80346D28, 100000)


def test_the_peeks_read_the_counter_the_frame_after_each_poke(capsys):
    assert soak.main(["--peeks", "--encounter-every", "600"]) == 0
    text = capsys.readouterr().out.strip()
    assert text.split(",")[:2] == ["0x80346D28@3201", "0x80346D28@3801"]
    assert len(text.split(",")) == 50
    with pytest.raises(SystemExit):
        soak.main(["--peeks"])


def test_a_warp_job_must_reach_its_map():
    """The save lands first, and the warp's map has to follow it."""
    warped = [si(3300), field_map("a116c"), *ONE_BATTLE]
    res = soak.judge(soak_log(warped), "warp.log", expect_map="a116a", expect_reach="a116c")
    assert status(res, "the run reached a116c") == "pass", res["checks"]
    res = soak.judge(soak_log(), "nowarp.log", expect_map="a116a", expect_reach="a116c")
    assert res["verdict"] == "FAIL"
    assert status(res, "the run reached a116c") == "FAIL"


def snapshot(path: Path, rgb: tuple[int, int, int], w: int = 16, h: int = 8) -> None:
    """A PNG the way runtime/png.c writes one: 8-bit RGBA, filter 0 rows."""
    import struct
    import zlib

    row = b"\0" + bytes([*rgb, 255]) * w

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * h))
        + chunk(b"IEND", b"")
    )


def test_a_field_that_comes_back_black_after_a_battle_is_a_question(tmp_path):
    """ONE_BATTLE returns to a116a at frame 5100; the snapshots after it are
    what show the field came back. All black is the a101b class of problem,
    raised as a question; one lit snapshot in the window answers it."""
    for n in (5000, 5200, 5300, 5400, 5500):
        snapshot(tmp_path / f"{n:04d}.png", (0, 0, 0))
    res = soak.judge(soak_log(), "x.log", frames_dir=tmp_path)
    assert any(q.startswith("black after battle") for q in res["questions"]), res["questions"]
    assert res["verdict"] == "pass"  # a question, not a failure
    assert res["after_battle"][0]["snapshots"] == [5200, 5300, 5400, 5500]

    snapshot(tmp_path / "5400.png", (90, 120, 60))
    res = soak.judge(soak_log(), "x.log", frames_dir=tmp_path)
    assert not any("black after battle" in q for q in res["questions"]), res["questions"]
    assert res["after_battle"][0]["black"] == [5200, 5300, 5500]


def test_no_snapshot_after_a_battle_is_a_question_too(tmp_path):
    res = soak.judge(soak_log(), "x.log", frames_dir=tmp_path)
    assert any(q.startswith("no snapshot within") for q in res["questions"]), res["questions"]


def test_a_battle_lost_to_a_game_over_is_not_asked_about(tmp_path):
    """It returns to a090a, which is not the field; the map list reports it."""
    lost = [si(4723), CREW, ASSET, si(5000), field_map("a090a")]
    res = soak.judge(soak_log(lost), "x.log", frames_dir=tmp_path)
    assert res["after_battle"] == [] and res["questions"] == []


def test_a_snapshot_the_port_did_not_write_is_refused(tmp_path):
    """Guessing at another encoder's PNG could call a lit frame black."""
    p = tmp_path / "5200.png"
    snapshot(p, (0, 0, 0))
    d = bytearray(p.read_bytes())
    d[24:26] = bytes([8, 2])  # IHDR: 8-bit RGB, not RGBA
    p.write_bytes(bytes(d))
    with pytest.raises(ValueError, match="not 8-bit RGBA"):
        soak.is_black(p)
