"""tools/reach.py: the environment a reach run gets (docs/specs/reach.md)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import reach  # noqa: E402
import soak  # noqa: E402


def args(*argv: str):
    """reach.py's own parser, stopped before it runs anything."""
    captured = {}

    def fake(a):
        captured["a"] = a
        return 0

    real = reach.cmd_run
    reach.cmd_run = fake
    try:
        reach.main(["run", "x", "--card", "c.raw", *argv])
    finally:
        reach.cmd_run = real
    return captured["a"]


FOLDER = ROOT / "build" / "reach" / "x"


def test_a_switch_left_in_the_shell_never_reaches_a_run():
    env = reach.environment(
        args(), FOLDER, {"SOA_MODS": "mods", "SOA_ENCOUNTERS": "off", "PATH": "p"}
    )
    assert env["PATH"] == "p"
    assert env["SOA_MODS"] == "build/reach/x/mods"
    assert "SOA_ENCOUNTERS" not in env
    assert env["SOA_CARD"] == "build/reach/x/card.raw"
    assert env["SOA_FRAMES_DIR"] == "build/reach/x/frames"
    for k, v in {
        "SOA_STRICT": "1",
        "SOA_TRACE": "1",
        "SOA_SETTINGS": "0",
        "SOA_RENDER": "1",
    }.items():
        assert env[k] == v
    assert env["SOA_SNAP"] == "100" and "SOA_PAD" not in env and "SOA_LAB" not in env


def test_snap_0_draws_every_frame_and_writes_none():
    assert "SOA_SNAP" not in reach.environment(args("--snap", "0"), FOLDER, {})


def test_the_soak_play_and_the_accelerator_are_soak_pys_own():
    a = args("--soak-seed", "40", "--battle", "--accelerate", "600", "--lab", "objects")
    env = reach.environment(a, FOLDER, {})
    assert env["SOA_PAD"] == soak.script(40, 3200, 33000, battle=True)
    assert env["SOA_POKE"] == soak.pokes(None, soak.WARP_FRAME, 600, 3200, 33000)
    assert env["SOA_PEEK"] == soak.peeks(3200, 33000, 600)
    assert env["SOA_LAB"] == "objects"


def test_a_warp_moves_the_play_and_the_accelerator_past_it():
    a = args("--warp", "106a", "--soak-seed", "40", "--battle", "--accelerate", "600")
    env = reach.environment(a, FOLDER, {})
    first = soak.WARP_FRAME + soak.WARP_SETTLE
    assert env["SOA_POKE"] == soak.pokes("a106a", soak.WARP_FRAME, 600, first, 33000)
    assert env["SOA_PAD"] == soak.script(40, first, 33000, battle=True)
    assert env["SOA_PEEK"] == soak.peeks(first, 33000, 600)


def test_pokes_and_peeks_given_join_the_accelerators():
    a = args("--accelerate", "600", "--poke", "3300:0x803472E4=1", "--peek", "0x80347280@4000")
    env = reach.environment(a, FOLDER, {})
    assert env["SOA_POKE"].startswith("3300:0x803472E4=1,")
    assert env["SOA_PEEK"].startswith("0x80347280@4000,")


def test_env_sets_one_switch_and_refuses_anything_else():
    a = args("--env", "SOA_FIFO_DUMP=4000", "--env", "SOA_FIFO_DIR=build/reach/x/fifo")
    env = reach.environment(a, FOLDER, {})
    assert env["SOA_FIFO_DUMP"] == "4000" and env["SOA_FIFO_DIR"] == "build/reach/x/fifo"
    for bad in ("PATH=x", "SOA_X"):
        with pytest.raises(SystemExit):
            reach.environment(args("--env", bad), FOLDER, {})


def test_story_adds_the_labs_item_and_names_the_runs_own_index():
    env = reach.environment(args("--lab", "walk:3300-90000:300", "--story", "100-149"), FOLDER, {})
    assert env["SOA_LAB"] == "walk:3300-90000:300;story:100-149"
    assert env["SOA_LAB_STORY"] == "build/reach/x/story.txt"
    assert reach.environment(args("--story", "100-149"), FOLDER, {})["SOA_LAB"] == "story:100-149"
    for bad in ("149-100", "100", "100-1024"):
        with pytest.raises(SystemExit):
            args("--story", bad)


def test_a_stale_lab_library_is_refused(tmp_path):
    src, lib = tmp_path / "mod.c", tmp_path / "mod.dll"
    lib.write_text("old")
    src.write_text("new")
    import os

    os.utime(lib, (1, 1))
    with pytest.raises(SystemExit, match="older than"):
        reach.check_fresh(lib, src)
    os.utime(lib, None)
    os.utime(src, (1, 1))
    reach.check_fresh(lib, src)


def test_a_name_that_is_not_a_folder_name_is_refused():
    for bad in ("../x", "a/b", ""):
        with pytest.raises(SystemExit):
            reach.cmd_run(type("A", (), {"name": bad})())
