"""The window's picture from the GPU (specs/gpu-backend.md V8).

`python tools/gpuspike.py present` draws two synthetic screen copies, 640x480
and 640x448, through the GPU presenter's pass into eight target sizes -- the
window at 1x to 4x, 16:9 and 21:9 clients, odd sizes and one smaller than the
picture -- at both layouts, and holds every pixel's colour to picture_scale's
(runtime/picture.c), which is what the CPU presenter draws. The scaler is
nearest neighbour by integer arithmetic, so the two must agree exactly. The
mutation, present.frag one column over, must fail it. They need MSVC,
vendor/ and a Vulkan device, and skip saying which without.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gpuspike  # noqa: E402


def run_present(*extra):
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", "present", *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == gpuspike.SKIP:
        reason = next(
            (ln[6:] for ln in proc.stdout.splitlines() if ln.startswith("skip: ")), "skipped"
        )
        pytest.skip(reason)
    return proc


def test_the_gpu_presents_what_picture_scale_draws():
    proc = run_present()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "present 32 of 32 layouts exact, at scale 1" in proc.stdout


def test_a_presenter_one_column_over_fails_it():
    proc = run_present("--mutate", "present")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "present 0 of 32 layouts exact, at scale 1" in proc.stdout
