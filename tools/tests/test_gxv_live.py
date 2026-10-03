"""A live run with the GPU drawing, judged on its own log (specs/gpu-backend.md V5).

`python tools/scenario.py run title --check --env SOA_GPU=vulkan` adds a fifth
invariant, "the GPU drew the run": the backend's start line once, no fallback,
and a [gxv] report whose counts are what the renderer handed it and what
gxr_report counted copying. These tests hold that check to canned logs, each
wrong in one way. A real log is checked by the tool itself, which applies the
same invariant to any log the backend wrote in:

    python tools/scenario.py run title --check --env SOA_GPU=vulkan --log build/title-gpu.log
    python tools/scenario.py check build/title-gpu.log --name title
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import scenario  # noqa: E402

START = (
    "[gxv] Vulkan 1.4.344 on AMD Radeon Graphics (driver 0x800184): logicOp yes; "
    "EFB 640x528 RGBA8 + D32F; logic ops native; timestamps on"
)
GXR = (
    "[gxr] 112306 triangles, 0 lines, 0 points; 0 pixels shaded (0 outside, 0 failed alpha, "
    "0 failed depth); 0 clipped away; 0 bad vertex refs; 152 texture copies, 2000 screen copies"
)
SENT = "[gxr] vulkan backend: 26336 draws, 2152 copies, 2000 clears"
GXV = (
    "[gxv] 26336 draws (13578 rebuilt by clipping), 107323 vertices, 2000 clears, 2000 screen "
    "copies, 152 copies to a texture (0 refused), 25 pipelines, 4156 submissions, GPU 475.582 ms"
)
FALLBACK = (
    "[gxv] fallback: no Vulkan loader: LoadLibrary(nonexistent.dll) failed (error 126); "
    "the CPU draws"
)


def log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_a_run_the_gpu_drew_whole_passes():
    problems, drew = scenario.gpu_problems(log(START, GXR, SENT, GXV))
    assert problems == []
    assert drew.startswith("26336 draws, 2000 screen copies, 152 copies to a texture, as sent")
    assert "AMD Radeon Graphics" in drew


def test_a_fallback_fails_it_while_the_cpu_draws():
    """SOA_GPU_LOADER=nonexistent.dll: the run is fine on the CPU, and this
    check is what says the GPU never drew."""
    problems, _ = scenario.gpu_problems(log(FALLBACK, GXR))
    assert any("start lines" in p for p in problems)
    assert FALLBACK in problems
    assert "no [gxv] report" in problems and "no [gxr] backend line" in problems


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ((GXV, GXV.replace("26336 draws", "26335 draws")), "draws"),
        ((GXV, GXV.replace("152 copies to a texture", "151 copies to a texture")), "copies"),
        ((GXV, GXV.replace("2000 clears", "1999 clears")), "clears"),
        ((GXR, GXR.replace("2000 screen copies", "1999 screen copies")), "screen copies"),
        ((SENT, SENT.replace("vulkan backend", "passthrough backend")), "passthrough"),
    ],
)
def test_each_count_the_gpu_reports_is_held_to_the_renderers(change, says):
    old, new = change
    text = log(START, GXR, SENT, GXV).replace(old, new)
    problems, _ = scenario.gpu_problems(text)
    assert problems and any(says in p for p in problems), problems


def test_a_run_that_drew_nothing_or_started_twice_fails():
    empty = log(
        START,
        GXR.replace("152 texture copies, 2000 screen copies", "0 texture copies, 0 screen copies"),
        "[gxr] vulkan backend: 0 draws, 0 copies, 0 clears",
        GXV.replace("26336 draws", "0 draws")
        .replace("2000 clears", "0 clears")
        .replace("2000 screen copies", "0 screen copies")
        .replace("152 copies", "0 copies"),
    )
    assert any("drew 0 draws" in p for p in scenario.gpu_problems(empty)[0])
    twice = log(START, START, GXR, SENT, GXV)
    assert any("2 '[gxv] Vulkan" in p for p in scenario.gpu_problems(twice)[0])


def test_the_last_report_is_the_runs():
    """The watchdog can print the reports while the run is going; the run's
    own are the last."""
    early = GXV.replace("26336 draws", "100 draws")
    assert scenario.gpu_problems(log(START, early, GXR, SENT, GXV))[0] == []


def test_the_fifth_invariant_is_there_only_with_the_gpu(capsys):
    r = scenario.parse_report(log(START, GXR, SENT, GXV))
    without = scenario.check_report(r, 0, True, None)
    assert "the GPU drew the run" not in [c.name for c in without]
    with_gpu = scenario.check_report(r, 0, True, None, None, True)
    gpu = next(c for c in with_gpu if c.name == "the GPU drew the run")
    assert gpu.status == scenario.PASS and gpu.invariant
