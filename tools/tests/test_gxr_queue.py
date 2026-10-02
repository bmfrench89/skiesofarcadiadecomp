"""Tests for the handshake between gxr_flush and the rasterizer threads.

The queue numbers commands instead of indexing them, and never resets the
numbering. That buys one property, and everything else here follows from it:
*no value a worker reads ever goes down*. A stale read is therefore always too
small, and too small can only make a thread wait.

The bug this replaced was not a missing barrier, it was a pair of loads. The
worker's spin read ``g_cursor[id]`` and ``g_q_tail``, C does not order the two
operands of a comparison, and ``gxr_flush`` rewound both of them under running
workers before freeing that batch's decoded textures -- so a worker that read
the tail from before the reset and its cursor from after it left the spin and
rasterized a command from the batch just drained, whose texture pointers had
gone back to the allocator. It never fired in a shipped binary, because MSVC
happened to emit the cursor first; hoisting the command pointer into a local,
which is the tidy-up that removes the redundant re-load four instructions
later, flips the order.

So the first test below is about the source and not about a run: it checks that
nothing rewinds, and that the worker's decision still reads exactly one word
another thread writes. A run cannot check that -- the fault is a race that a
particular register allocation hides -- but a reader can, and so can a regex.

The second builds the renderer and drives flushes of every shape the queue
supports at four thread counts, which is the part that would catch a numbering
that is monotone but wrong.

Built the way ``test_gxr_lifetimes.py`` builds it: the renderer on its own, a
synthetic command stream, no disc and no game data.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "citest"))
# One copy of the driver, which tools/citest/queue_check.py also builds under
# other compilers and on ARM64 (portability.md L8).
from queue_check import QUEUE_DRIVER as DRIVER  # noqa: E402
from queue_check import QUEUE_SOURCES as SOURCES  # noqa: E402
from queue_check import QUEUE_THREAD_COUNTS as THREAD_COUNTS  # noqa: E402

RUNTIME = ROOT / "runtime"
GXR = (RUNTIME / "gxr.c").read_text(encoding="utf-8")


needs_msvc = pytest.mark.skipif(
    toolchain.cl_path() is None, reason="no MSVC: the renderer cannot be built here"
)


def worker_body() -> str:
    """The text of gxr.c's worker(), which is the only rasterizer-side reader."""
    start = GXR.index("static void worker(void* arg)")
    return GXR[start : GXR.index("\n}\n", start)]


@needs_msvc
def test_nothing_the_workers_read_is_ever_rewound():
    """The whole of the fix is that no number goes down. g_published is written
    only by the producer and only by an increment; g_ran[] only by its own
    worker and only forwards. An assignment to either that is not those is the
    old bug coming back, whatever it looks like at the call site."""
    body = re.sub(r"/\*.*?\*/", "", GXR, flags=re.S)
    # An assignment, not a comparison: not ==, !=, <=, >=.
    assigns = re.findall(r"(?<![=!<>])\s(g_published|g_ran\s*\[[^\]]*\])\s*=(?!=)", body)
    assert assigns == [], f"the numbering is being rewritten in place: {assigns}"
    for name, op in (("g_published", "plat_inc64"), ("g_ran", "plat_xchg64")):
        writes = re.findall(rf"{op}\(&{name}", body)
        assert writes, f"{name} is no longer published with {op}"
    # Since L2 every write is a plat_* call, and an exchange or a decrement
    # through one rewinds the numbering as surely as an assignment would.
    rewinds = re.findall(r"plat_(?:xchg|dec)\w*\(&g_published|plat_dec\w*\(&g_ran", body)
    assert rewinds == [], f"the numbering is being rewound through a helper: {rewinds}"


@needs_msvc
def test_the_worker_decides_on_one_shared_word():
    """What made the old spin unsafe was that it read two variables the producer
    wrote and C leaves the order of the two operands to the compiler. The
    worker now compares a count of its own against one word, so there is no
    pair left to order -- and that is the thing to keep, because it is what a
    reader can check without knowing what any thread is doing at the time."""
    body = re.sub(r"/\*.*?\*/", "", worker_body(), flags=re.S)
    spin = re.search(r"while \((.*?)\)\s*\{\s*if \(\+\+spins", body)
    assert spin, worker_body()
    shared = set(re.findall(r"\bg_[a-z_]+", spin.group(1)))
    assert shared == {"g_published"}, f"the spin reads more than one shared word: {shared}"


@needs_msvc
def test_a_command_is_only_ever_found_in_its_own_slot():
    """Numbering commands means slot reuse, and the only thing keeping two live
    commands out of one slot is that the producer drains before it gets
    QUEUE_CAP ahead. That arithmetic is checked rather than commented: the
    producer stamps the number into the command and the worker compares it. The
    check is only sound if the capacity is a power of two, so that is pinned
    here too."""
    cap = int(re.search(r"#define QUEUE_CAP (\d+)", GXR).group(1))
    assert cap & (cap - 1) == 0, f"QUEUE_CAP {cap} is not a power of two, so QMASK is wrong"
    assert re.search(r"D->seq = g_published;", GXR), "the producer no longer stamps the command"
    assert re.search(r"D->seq != mine", worker_body()), "the worker no longer checks the stamp"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("queue")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "queue.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(RUNTIME),
            *[str(RUNTIME / name) for name in SOURCES],
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("SOA_"):
            env.pop(name)
    results = {}
    for threads in THREAD_COUNTS:
        run = subprocess.run(
            [str(exe)],
            capture_output=True,
            text=True,
            env={**env, "SOA_THREADS": threads},
            cwd=out,
            timeout=600,
            check=False,
        )
        text = run.stdout + run.stderr
        assert run.returncode == 0, f"SOA_THREADS={threads} exit {run.returncode}\n{text}"
        assert "[queue] done" in text, text
        results[threads] = text
    return results


@needs_msvc
def test_every_thread_count_draws_the_same_frames(runs):
    """A worker that leaves its spin early runs a command from the batch just
    drained and then keeps going through the rest of it, so its share of the
    rows of the *new* batch never gets drawn: the symptom is a stale stripe as
    readily as a crash, and it is per thread count. Ten frames across two
    captures, all different from each other, all identical whoever drew them."""
    per_run = {
        t: re.findall(r"\[queue\] cap \d+ frame \d+ hash (\w+)", text) for t, text in runs.items()
    }
    for threads, hashes in per_run.items():
        assert len(hashes) == 10, f"SOA_THREADS={threads} presented {len(hashes)} frames"
    one = per_run["1"]
    assert len(set(one[:5])) == 5, (
        f"the frames do not differ from each other, so this proves nothing: {one}"
    )
    # The two captures draw the same five frames from a reset EFB, so the
    # second reproducing the first is the replay check: nothing the queue
    # carries over from one capture changes what the next one draws.
    assert one[:5] == one[5:], f"the second capture did not reproduce the first: {one}"
    for threads, hashes in per_run.items():
        assert hashes == one, f"SOA_THREADS={threads} drew a different picture:\n{hashes}\n{one}"


@needs_msvc
def test_the_stream_reached_the_flush_paths_it_is_here_to_test(runs):
    """A run of this shape that never flushed from inside a draw's own texture
    lookup would pass every assertion above and test nothing, which is the way
    a queue test quietly stops working. gxr_report says whether the path was
    taken."""
    for threads, text in runs.items():
        m = re.search(r"\[gxr\] (\d+) draws sampled a texture a queued copy writes", text)
        assert m, f"SOA_THREADS={threads} never flushed from inside tev_prepare:\n{text}"
        assert int(m.group(1)) >= 40, text


@needs_msvc
def test_no_worker_was_handed_a_command_built_over_the_one_it_asked_for(runs):
    """The self-check inside the worker. It cannot fire while the producer
    drains before it gets QUEUE_CAP ahead; it exists so that the day something
    lets it get further, the run says which slot and which command rather than
    rasterizing whatever was there."""
    for threads, text in runs.items():
        assert "queue slot" not in text, f"SOA_THREADS={threads}:\n{text}"
