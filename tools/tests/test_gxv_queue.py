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
V7 adds the pipeline cache on disk, and the compiler thread's accounting of
the pipelines specialised on the TEV's shape.
They need MSVC, vendor/ and a Vulkan device, and skip saying which without.
"""

import re
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


def queue_report(env: dict, out: Path, *mutate: str) -> str:
    """One queue frame on the GPU: what gxv said."""
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
            *(("--mutate", *mutate) if mutate else ()),
        ],
        cwd=ROOT,
        env={**gpuspike.clean_env(), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout + proc.stderr
    assert proc.returncode == 0, text[-2000:]
    return text


def queue_pipelines(env: dict, out: Path) -> tuple[int, int, str]:
    """One queue frame on the GPU: (pipelines made on the draw path, how many
    the cache had, the line)."""
    text = queue_report(env, out)
    m = re.search(
        r"^\[gxv\] pipelines: (\d+) made on the draw path, "
        r"(?:(\d+) of them from the cache|the device not saying).*$",
        text,
        re.M,
    )
    assert m, text[-2000:]
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


def stalled_frame(env: dict, out: Path, *mutate: str) -> tuple[float, int, str]:
    """The queue frame with every compile 200 ms late (SOA_GPU_COMPILE_STALL):
    (the consumer's ms for the frame, specialised pipelines still to make,
    what gxv said)."""
    text = queue_report({**env, "SOA_GPU_COMPILE_STALL": "200"}, out, *mutate)
    bg = re.search(r"the compiler thread: \d+ made, .* failed, (\d+) still to make", text)
    consumer = re.search(
        r"a frame, over 1 frame: consumer ms p50 [\d.]+ p95 [\d.]+ p99 ([\d.]+)", text
    )
    assert bg and consumer, text[-2000:]
    return float(consumer.group(1)), int(bg.group(1)), text


def test_the_compiler_thread_accounts_for_every_specialised_pipeline(tmp_path):
    """V7: by default the pipelines specialised on the TEV's shape are made on
    a thread of their own, the interpreter drawing meanwhile. Each one asked
    for is made, failed or still to make, none fails, and some draws were the
    interpreter's; with every compile stalled the frame is the same and its
    draw path waits for none. SOA_GPU_SPECIALIZE=wait makes them on the draw
    path, and 0 none at all. The frame itself is held to the CPU's by the
    test above."""
    from soa import toolchain

    if gpuspike.ready(toolchain.MSVC) is not None:
        pytest.skip("the spike cannot be built here")
    env = {"SOA_GPU_PIPELINES": "off"}
    text = queue_report(env, tmp_path)
    spec = re.search(r"specialised on the TEV's shape: (\d+) for (\d+) distinct shapes", text)
    bg = re.search(
        r"the compiler thread: (\d+) made, .*; (\d+) failed, (\d+) still to make; "
        r"(\d+) draws drawn by the interpreter",
        text,
    )
    assert spec and bg and "made on the compiler thread" in text, text[-2000:]
    made, failed, left, interim = (int(g) for g in bg.groups())
    assert int(spec.group(1)) > 0 and made + failed + left == int(spec.group(1)), bg.group(0)
    assert failed == 0 and interim > 0, bg.group(0)
    frame = re.search(r"frame hash ([0-9a-f]{16})", text)
    # Every compile 200 ms late, as on a driver with no cache of its own: the
    # draw path does not wait -- the frame's consumer time stays under the
    # stall, the pipelines are still to make -- and the frame is the same.
    p99, left, stalled = stalled_frame(env, tmp_path)
    assert frame and f"frame hash {frame.group(1)}" in stalled, stalled[-2000:]
    assert left > 0 and p99 < 200, stalled[-2000:]
    text = queue_report({**env, "SOA_GPU_SPECIALIZE": "wait"}, tmp_path)
    assert (
        "made on the draw path (SOA_GPU_SPECIALIZE=wait)" in text and "compiler thread:" not in text
    )
    text = queue_report({**env, "SOA_GPU_SPECIALIZE": "0"}, tmp_path)
    assert "the TEV is interpreted" in text and "specialised on the TEV's shape:" not in text


def test_a_draw_path_that_waits_for_the_compiler_fails_it(tmp_path):
    """compile-wait: the draw path waits for each specialised pipeline it
    asks for, and the stalled frame's consumer time is then the stalls'."""
    from soa import toolchain

    if gpuspike.ready(toolchain.MSVC) is not None:
        pytest.skip("the spike cannot be built here")
    p99, left, text = stalled_frame({"SOA_GPU_PIPELINES": "off"}, tmp_path, "compile-wait")
    assert p99 >= 200 and left == 0, text[-2000:]
