"""Tests for the GPU spike (tools/gpuspike.py, tools/fetch_gpu.py; V3a).

Three kinds. The judge that compares a CPU scene with a GPU one, and the
copy of the render recipe in tools/gpuspike/driver.c, are text and arithmetic
and run everywhere. fetch_gpu.py's record is checked against vendor/, and a
copy of vendor/ with one byte changed must fail it. The self test itself
builds the spike and draws on this machine's GPU, and so does its mutation,
which must fail; those need MSVC, vendor/ and a Vulkan device, and without
one they skip saying which -- pytest -rs shows it -- never quietly.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_gpu  # noqa: E402
import gpuspike  # noqa: E402
from soa import png, toolchain  # noqa: E402

W, H = 64, 48


def scene(tmp_path: Path, name: str, paint) -> Path:
    """A black W x H image with paint(x, y) -> (r, g, b) or None at each pixel."""
    rgba = bytearray(W * H * 4)
    for y in range(H):
        for x in range(W):
            c = paint(x, y)
            if c:
                rgba[(y * W + x) * 4 : (y * W + x) * 4 + 4] = bytes((*c, 255))
    path = tmp_path / f"{name}.png"
    png.write_rgba(path, W, H, bytes(rgba))
    return path


def square(x, y):
    return (200, 40, 40) if 10 <= x < 40 and 8 <= y < 30 else None


def test_the_judge_passes_a_pixel_moved_at_an_edge_and_fails_one_inside(tmp_path):
    """The edge band is what lets a different fill rule through; it must not
    let anything else through. Moving the square's last column out by one is
    an edge difference; a hole in its middle is not; nor is a colour one step
    off where none is allowed."""
    cpu = scene(tmp_path, "cpu", square)
    wider = scene(
        tmp_path,
        "wider",
        lambda x, y: square(x, y) or ((200, 40, 40) if x == 40 and 8 <= y < 30 else None),
    )
    hole = scene(tmp_path, "hole", lambda x, y: None if (x, y) == (25, 18) else square(x, y))
    step = scene(
        tmp_path, "step", lambda x, y: (201, 40, 40) if (x, y) == (25, 18) else square(x, y)
    )
    for edges_by in ("colour", "coverage"):
        assert gpuspike.judge("t", ("area", 0, edges_by), cpu, cpu)[0]
        assert gpuspike.judge("t", ("area", 0, edges_by), cpu, wider)[0]
        assert not gpuspike.judge("t", ("area", 0, edges_by), cpu, hole)[0]
        assert not gpuspike.judge("t", ("area", 0, edges_by), cpu, step)[0]
        assert gpuspike.judge("t", ("area", 1, edges_by), cpu, step)[0]


def test_colour_edges_take_in_where_two_colours_meet(tmp_path):
    """A depth test's crossing line is a change of colour, not of coverage:
    judged by colour, a one-pixel shift of it is an edge difference; judged by
    coverage alone it would be an interior one."""

    def halves(split):
        return lambda x, y: (40, 200, 40) if x < split else (40, 40, 200)

    a, b = scene(tmp_path, "a", halves(32)), scene(tmp_path, "b", halves(33))
    assert gpuspike.judge("t", ("area", 0, "colour"), a, b)[0]
    assert not gpuspike.judge("t", ("area", 0, "coverage"), a, b)[0]


def test_cull3_must_cover_nothing_and_the_other_scenes_something(tmp_path):
    empty = scene(tmp_path, "empty", lambda x, y: None)
    cpu = scene(tmp_path, "cpu", square)
    assert gpuspike.judge("cull3", ("area", 0, "colour"), empty, empty)[0]
    assert not gpuspike.judge("cull3", ("area", 0, "colour"), cpu, cpu)[0]
    assert not gpuspike.judge("cull0", ("area", 0, "colour"), empty, empty)[0], (
        "an empty scene compares vacuously"
    )


def test_lines_may_move_one_pixel_and_no_further(tmp_path):
    line = scene(tmp_path, "line", lambda x, y: (255, 200, 0) if y == 20 and 5 <= x < 60 else None)
    near = scene(
        tmp_path,
        "near",
        lambda x, y: (255, 200, 0) if y == (21 if x > 30 else 20) and 5 <= x < 60 else None,
    )
    far = scene(
        tmp_path,
        "far",
        lambda x, y: (255, 200, 0) if y == (22 if x > 30 else 20) and 5 <= x < 60 else None,
    )
    assert gpuspike.judge("lines", ("lines",), line, near)[0]
    assert not gpuspike.judge("lines", ("lines",), line, far)[0]


def test_points_must_land_exactly(tmp_path):
    a = scene(tmp_path, "a", lambda x, y: (60, 255, 120) if (x, y) == (10, 10) else None)
    b = scene(tmp_path, "b", lambda x, y: (60, 255, 120) if (x, y) == (11, 10) else None)
    assert gpuspike.judge("points", ("points",), a, a)[0]
    assert not gpuspike.judge("points", ("points",), a, b)[0]


def test_the_spike_driver_still_runs_the_ports_own_checks():
    """tools/gpuspike/driver.c carries the render recipe verbatim from
    runtime/selftest.c, as tools/citest/render_driver.c does, so that "307200
    of 307200 red" on the GPU is the port's own assertion."""
    driver = (ROOT / "tools" / "gpuspike" / "driver.c").read_text(encoding="utf-8")
    original = (ROOT / "runtime" / "selftest.c").read_text(encoding="utf-8")
    copied = driver.split("BEGIN COPY")[1].split("\n", 1)[1].split("/* ---- END COPY")[0]
    assert copied.strip(), "the markers are there but the block between them is empty"
    assert copied.strip() in original, (
        "the copy in tools/gpuspike/driver.c no longer matches runtime/selftest.c"
    )
    assert "render full-screen quad" in copied and "render triangle rows" in copied


def test_every_scene_the_driver_writes_is_judged():
    """A scene drawn and never compared would be a check that passes by not
    running; a judged name the driver never writes fails the self test."""
    driver = (ROOT / "tools" / "gpuspike" / "driver.c").read_text(encoding="utf-8")
    import re

    written = set(re.findall(r'finish_scene\(s, "(\w+)"\)', driver))
    written |= {"cull0", "cull1", "cull2", "cull3"}  # named by snprintf
    written |= set(re.findall(r'scene_clip\(s, "(\w+)"', driver))
    assert written == set(gpuspike.SCENES), written ^ set(gpuspike.SCENES)


def need_vendor():
    if not (ROOT / "vendor" / fetch_gpu.RECORD).exists():
        reason = "no vendor/GPU.sha256: run python tools/fetch_gpu.py (it fetches the pinned Vulkan-Headers and glslang)"
        print(f"skip: {reason}")
        pytest.skip(reason)


def test_the_fetched_files_are_as_recorded():
    need_vendor()
    proc = subprocess.run(
        [sys.executable, "tools/fetch_gpu.py", "--verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert " unchanged" in proc.stdout


def test_one_changed_byte_or_a_missing_file_fails_the_record(tmp_path):
    need_vendor()
    copy = tmp_path / "vendor"
    shutil.copytree(ROOT / "vendor", copy)
    assert fetch_gpu.verify(copy) == []
    header = copy / "vulkan-headers" / "include" / "vulkan" / "vulkan_core.h"
    data = bytearray(header.read_bytes())
    data[len(data) // 2] ^= 0x01
    header.write_bytes(bytes(data))
    (copy / "vulkan-headers" / "LICENSE.md").unlink()
    bad = fetch_gpu.verify(copy)
    assert any("vulkan_core.h: sha256 differs" in b for b in bad), bad
    assert any("LICENSE.md: recorded but missing" in b for b in bad), bad
    assert fetch_gpu.main(["--vendor", str(copy), "--verify"]) == 1


def run_selftest(*extra):
    if toolchain.compiler_path(toolchain.MSVC) is None:
        reason = "no MSVC (tools/soa/toolchain.py compiler_path): the spike is built with cl"
        print(f"skip: {reason}")
        pytest.skip(reason)
    need_vendor()
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", "selftest", *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == gpuspike.SKIP:
        reason = next(
            (ln[6:] for ln in proc.stdout.splitlines() if ln.startswith("skip: ")), "skipped"
        )
        print(f"skip: {reason}")
        pytest.skip(reason)
    return proc


def test_the_gpu_draws_what_the_cpu_draws():
    proc = run_selftest()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "[gpuspike] every check passes" in out
    assert out.count('render full-screen quad      ok    got "307200 of 307200 red"') == 2, out
    for name in gpuspike.SCENES:
        assert f"ok   {name}:" in out, name
    assert out.count(" ok\n") >= 4 and "rebuilt 0" not in out, (
        "every clip scene must rebuild a draw"
    )


def test_uploading_unclipped_fails_it():
    proc = run_selftest("--mutate", "unclipped")
    out = proc.stdout
    assert proc.returncode == 1, out + proc.stderr
    for name in ("clip_near_ortho", "clip_far_ortho", "clip_near_persp", "clip_far_persp"):
        assert f"clip {name} " in out and f"FAIL {name}:" in out, name
    assert "FAIL cull" not in out, "the mutation touches clipping only"
