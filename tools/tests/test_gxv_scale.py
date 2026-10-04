"""The EFB at two and three times the console's size (specs/gpu-backend.md V9a).

At SOA_GPU_SCALE=S each native pixel is S x S samples, and a copy is the
native copy run once per sample's phase: its RAM bytes, its decoded image
and g_screen are one phase (the centre at S = 3, the mean at S = 2), its
image in the pool and the presenter's screen are all of them.

- `copydiff --scale 3` loads a random EFB with every pixel's samples alike:
  the bytes, image and screen must be the CPU's, and the pool's image and the
  full screen the native ones replicated. The copy filter's taps one sample
  apart instead of S (taps) must fail it.
- `copyimage --scale 3` samples a copy at scale in its own frame: the centre
  samples must give the CPU's frame. Sampling the scaled image as if it were
  native (copy-scale) must fail it.
- `present --scale 3` holds the presenter's averaging, where a scaled picture
  shrinks into the window, to picture_scale_area; one column over (present)
  must fail it.

The oracle at scale -- the captures, judged on their centre samples -- is
`python tools/gpuspike.py oracle --scale 3`, too long for here. These need
MSVC, vendor/ and a Vulkan device, and skip saying which without.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gpuspike  # noqa: E402


def spike(*args):
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", *args],
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


def test_copies_at_scale_3_are_the_native_ones_where_every_sample_is_alike():
    proc = spike("copydiff", "--scale", "3", "--rects", "20")
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "Differences: ram 0, image 0, screen 0" in out
    line = next(ln for ln in out.splitlines() if "copydiff at scale 3:" in ln)
    copies, screens = line.split(" replicated in ")[1:]
    n, of = copies.split(" copies")[0].split(" of ")
    assert n == of and int(n) > 0, line
    n, of = screens.split(" of ")
    assert n == of and int(n) > 0, line


def test_filter_taps_one_sample_apart_fail_it():
    proc = spike("copydiff", "--scale", "3", "--rects", "20", "--mutate", "taps")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL at scale 3: the pool's image replicated in" in proc.stdout


def test_a_copy_at_scale_3_sampled_in_its_frame_gives_the_cpus_frame():
    proc = spike("copyimage", "--scale", "3")
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    cpu = next(ln for ln in out.splitlines() if ln.startswith("cpu: "))
    gpu = next(ln for ln in out.splitlines() if ln.startswith("gpu: "))
    assert gpu.startswith(f"gpu: 16 of 16 cells right, hash {cpu.split('hash ')[1]};"), gpu
    assert "1 samplers served by a copy image" in gpu


def test_the_scaled_image_sampled_as_if_native_fails_it():
    proc = spike("copyimage", "--scale", "3", "--mutate", "copy-scale")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PROBLEM gpu:" in proc.stdout


def test_the_presenter_averages_a_scaled_picture_as_picture_scale_area_does():
    proc = spike("present", "--scale", "3")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "present 32 of 32 layouts exact, at scale 3" in proc.stdout


def test_a_scaled_presenter_one_column_over_fails_it():
    proc = spike("present", "--scale", "3", "--mutate", "present")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "present 0 of 32 layouts exact, at scale 3" in proc.stdout
