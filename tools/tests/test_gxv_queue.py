"""The GPU backend on a thread of its own (specs/gpu-backend.md V6a).

`python tools/gpuspike.py queue` draws one synthetic frame through the real
parser and producer: 64 quads each sampling the same texture slot at a new
generation, all in one GPU submission, then 656,000 vertices that fill the
producer's 48 MB vertex arena twice. On the GPU, on its own thread three
times, inline (V5's path) and with the consumer stalled 2 ms before every draw,
the frame must be the CPU's to the hash, every quad its own texture, and the
arena drained twice. Two mutations must fail it: gxv rewriting a slot's pool
allocation under draws already recorded (pool-in-place), and the consumer
counting a command before it runs (count-early, a variant build, stalled).
They need MSVC, vendor/ and a Vulkan device, and skip saying which without.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gpuspike  # noqa: E402


def run_queue(*extra):
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", "queue", *extra],
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


def test_the_queue_frame_is_the_cpus_on_the_thread_inline_and_stalled():
    proc = run_queue()
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    cpu = next(ln for ln in out.splitlines() if ln.startswith("cpu: "))
    assert cpu.startswith("cpu: 64 of 64 quads right") and cpu.endswith("2 arena drains")
    frame = cpu.split("hash ")[1].split(",")[0]
    gpu = [ln for ln in out.splitlines() if ln.startswith("gpu ")]
    assert [ln.split(":")[0] for ln in gpu] == ["gpu thread"] * 3 + ["gpu inline", "gpu stalled"]
    for ln in gpu:
        assert f"64 of 64 quads right, hash {frame}" in ln, ln
    assert all(ln.endswith("2 arena drains") for ln in gpu if "inline" not in ln)


@pytest.mark.parametrize("mutation", ["pool-in-place", "count-early"])
def test_each_queue_mutation_fails_it(mutation):
    """pool-in-place leaves one quad of 64 right; count-early lets the
    producer free what the stalled consumer has yet to read, and the run
    does not finish its frame."""
    proc = run_queue("--mutate", mutation)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "PROBLEM gpu stalled" in proc.stdout


def queue_pipelines(env: dict, out: Path) -> tuple[int, int, str]:
    """One queue frame on the GPU: (pipelines made, how many the cache had, the line)."""
    import re

    from soa import toolchain

    proc = subprocess.run(
        [
            str(gpuspike.exe_path(toolchain.MSVC)),
            "--backend",
            "gpu",
            "--out",
            str(out),
            "--queue",
            "1",
        ],
        cwd=ROOT,
        env={**gpuspike.clean_env(), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout + proc.stderr
    m = re.search(
        r"^\[gxv\] pipelines: (\d+) made, (?:(\d+) of them from the cache|the device not saying).*$",
        text,
        re.M,
    )
    assert proc.returncode == 0 and m, text[-2000:]
    return int(m.group(1)), int(m.group(2) or 0), m.group(0)


def test_the_disk_cache_gives_every_pipeline_back_to_the_next_run(tmp_path):
    """V7: the pipelines a run makes go to SOA_GPU_PIPELINES at a frame's end,
    and the next run's driver finds every one of them there; a file of junk
    gives none back, so the count is not one the driver always reports."""
    from soa import toolchain

    if gpuspike.ready(toolchain.MSVC) is not None:
        pytest.skip("the spike cannot be built here")
    cache = tmp_path / "pipelines.bin"
    env = {"SOA_GPU_PIPELINES": str(cache)}
    made, _, line = queue_pipelines(env, tmp_path)
    if "the device not saying" in line:
        pytest.skip("this device has no VK_EXT_pipeline_creation_feedback")
    assert made > 0 and cache.stat().st_size > 0, line
    again, hits, line = queue_pipelines(env, tmp_path)
    assert again == made and hits == made, line
    cache.write_bytes(b"not a pipeline cache" * 64)
    _, hits, line = queue_pipelines(env, tmp_path)
    assert hits == 0, line
