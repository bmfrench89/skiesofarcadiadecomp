"""Tests for the GPU spike (tools/gpuspike.py, tools/fetch_gpu.py; V3a, V3b).

Three kinds. The judge that compares a CPU scene with a GPU one, copydiff's
comparison of two runs, and the copy of the render recipe in
tools/gpuspike/driver.c are text and arithmetic and run everywhere.
fetch_gpu.py's record is checked against vendor/, and a copy of vendor/ with
one byte changed must fail it. The self test, tevdiff and copydiff build the
spike and run on this machine's GPU, and so do the mutations each must fail
on; those need MSVC, vendor/ and a Vulkan device, and without one they skip
saying which -- pytest -rs shows it -- never quietly.
"""

import re
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


def copy_row(
    combo=5, tpf=3, texfmt=3, seeded="a" * 16, ram="b" * 16, image="c" * 16, screen="d" * 16
):
    return (
        f"{combo} 0 {tpf} 0 0 1 10 20 31 7 0 00100000 {texfmt} 256 {seeded} {ram} {image} {screen}"
    )


def test_copydiff_counts_each_kind_of_difference():
    rows = [copy_row(combo=i) for i in range(4)]
    problems, mismatches = gpuspike.compare_copies(rows, list(rows))
    assert not problems and not mismatches
    gpu = [copy_row(combo=0, ram="e" * 16), copy_row(combo=1, image="e" * 16), rows[2], rows[3]]
    gpu[3] = copy_row(combo=3, screen="e" * 16)
    problems, mismatches = gpuspike.compare_copies(rows, gpu)
    assert not problems
    assert {k[0] for k in mismatches} == {"ram", "image", "screen"}


def test_copydiff_refuses_a_refused_copy_that_wrote_and_runs_that_disagree():
    """A copy the CPU refuses (texfmt 99) must leave RAM as it was on both
    sides, which equal hashes alone would not show; and two runs whose cases
    differ, or one cut short, compare nothing and must say so."""
    refused = copy_row(texfmt=99, seeded="a" * 16, ram="a" * 16)
    wrote = copy_row(texfmt=99, seeded="a" * 16, ram="f" * 16)
    assert gpuspike.compare_copies([refused], [refused]) == ([], gpuspike.Counter())
    assert gpuspike.compare_copies([wrote], [wrote])[0]
    assert gpuspike.compare_copies([copy_row()], [copy_row(tpf=4)])[0]
    assert gpuspike.compare_copies([copy_row(), copy_row()], [copy_row()])[0]
    assert gpuspike.compare_copies([], [])[0], "an empty run compares vacuously"


def run_spike(command, *extra):
    if toolchain.compiler_path(toolchain.MSVC) is None:
        reason = "no MSVC (tools/soa/toolchain.py compiler_path): the spike is built with cl"
        print(f"skip: {reason}")
        pytest.skip(reason)
    need_vendor()
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", command, *extra],
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


def run_selftest(*extra):
    return run_spike("selftest", *extra)


def test_the_gpu_draws_what_the_cpu_draws():
    proc = run_selftest()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "[gpuspike] every check passes" in out
    assert out.count('render full-screen quad      ok    got "307200 of 307200 red"') == 2, out
    for name in gpuspike.SCENES:
        assert f"ok   {name}:" in out, name
    assert out.count("invariance first ") == 2 and "left red 0 ok" in out, (
        "the strip drawn twice must cover itself"
    )
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


def test_the_tev_on_the_gpu_is_tev_pixel():
    """V3b: 100,000 setups from random registers, each through tev_pixel as
    prepared and with its fast shape off, and through tev.glsl: no mismatch,
    and every path counted at least 100 times."""
    proc = run_spike("tevdiff")
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "tevdiff 100000 cases, seed 1: 0 mismatches; 0 paths under 100 hits" in out
    assert "fastc2=" in out and "ccmp7=" in out and "alogic3=" in out


def test_a_flipped_clamp_fails_tevdiff():
    proc = run_spike("tevdiff", "--cases", "20000", "--mutate", "clamp")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "mismatch case" in proc.stdout


def test_the_copies_on_the_gpu_are_the_cpus():
    """V3b: 128 combinations of format, intensity, half scale and filter, 200
    random rectangles each: the same bytes in RAM, the same decoded image and
    the same screen copy, and every refused copy leaving RAM alone."""
    proc = run_spike("copydiff")
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "25600 copies, 12000 of them refused" in out
    assert "Differences: ram 0, image 0, screen 0" in out


@pytest.mark.parametrize(
    ("mutation", "breaks"),
    [
        ("rounding", ("ram", "image", "screen")),
        ("intensity", ("ram", "image")),
        ("unseeded", ("ram",)),
    ],
)
def test_each_copy_mutation_fails_copydiff(mutation, breaks):
    proc = run_spike("copydiff", "--rects", "10", "--mutate", mutation)
    out = proc.stdout
    assert proc.returncode == 1, out + proc.stderr
    totals = re.search(r"Differences: ram (\d+), image (\d+), screen (\d+)", out)
    assert totals, out
    for what, n in zip(("ram", "image", "screen"), totals.groups(), strict=True):
        assert (int(n) > 0) == (what in breaks), (mutation, what, out)


def test_a_replay_sees_no_soa_variable_but_its_own(monkeypatch):
    """3.12: nothing set for another run reaches a replay the oracle runs."""
    monkeypatch.setenv("SOA_GPU", "1")
    monkeypatch.setenv("SOA_THREADS", "3")
    env = gpuspike.clean_env()
    assert {k for k in env if k.startswith("SOA_")} == {"SOA_SETTINGS"}
    assert env["SOA_SETTINGS"] == "0"


def test_a_mutation_applies_by_the_pixels_it_changes(tmp_path):
    a = scene(tmp_path, "a", square)
    b = scene(tmp_path, "b", lambda x, y: (201, 40, 40) if (x, y) == (25, 18) else square(x, y))
    assert gpuspike.changed_fraction(a, a) == 0.0
    assert gpuspike.changed_fraction(a, b) == 1 / (W * H)
    assert 1 / (W * H) < gpuspike.APPLIES, "one pixel in a frame must not count as applying"


ORACLE_DATA = (ROOT / "build" / "fifo").exists() and (ROOT / "build" / "perfset").exists()


def test_the_captures_without_copies_pass_v0_on_the_gpu():
    """V4a: the 21 captures with no copy to a texture, each replayed on the
    CPU -- a reference that must be the manifest's or V0's, byte for byte --
    and on the GPU, and V0's verdict: all pass."""
    if not ORACLE_DATA:
        reason = "no build/fifo or build/perfset: the captures are on the owner's machine only"
        print(f"skip: {reason}")
        pytest.skip(reason)
    proc = run_spike("oracle")
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "21 captures without copies to a texture" in out
    assert "[gpuspike] oracle: 21 of 21 pass V0" in out
