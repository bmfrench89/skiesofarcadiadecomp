"""A copy sampled in its own frame, from the GPU's image (specs/gpu-backend.md V7).

`python tools/gpuspike.py copyimage` draws sixteen coloured cells, copies
them to an RGBA8 texture and draws a quad sampling that texture in the same
frame, through the real parser and producer, on the CPU and on the GPU. The
GPU must give the CPU's frame hash and all sixteen cells, serve the sampler
from the image the copy wrote into its texel pool, and land the copy in
guest RAM with the frame's own submission, not a wait of its own. Two
mutations must fail it: the producer's copy image sampled before the copy
has landed in it (cimg-cpu), and a wait to land every copy at the copy, as
V6 did (land-at-copy). They need MSVC, vendor/ and a Vulkan device, and skip
saying which without.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gpuspike  # noqa: E402


def run_copyimage(*extra):
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", "copyimage", *extra],
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


def test_a_copy_sampled_in_its_frame_is_the_gpus_own_image():
    proc = run_copyimage()
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    cpu = next(ln for ln in out.splitlines() if ln.startswith("cpu: "))
    gpu = next(ln for ln in out.splitlines() if ln.startswith("gpu: "))
    frame = cpu.split("hash ")[1]
    assert cpu.startswith("cpu: 16 of 16 cells right")
    assert gpu.startswith(f"gpu: 16 of 16 cells right, hash {frame};"), gpu
    assert "1 copies to a texture, 0 readback waits, 1 samplers served by a copy image" in gpu


def test_the_producers_image_before_it_lands_is_a_different_picture():
    """cimg-cpu: what the GPU would draw had it uploaded the producer's copy
    image, which the copy fills only when it lands."""
    proc = run_copyimage("--mutate", "cimg-cpu")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PROBLEM gpu: 0 of 16, hash" in proc.stdout


def test_waiting_to_land_every_copy_fails_it():
    """land-at-copy: V6's protocol, a wait at every copy, which leaves the
    pool's image unused and the waits as many as the copies."""
    proc = run_copyimage("--mutate", "land-at-copy")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PROBLEM gpu: 1 readback waits for 1 copies, not fewer" in proc.stdout
