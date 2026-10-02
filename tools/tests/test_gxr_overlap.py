"""Tests for the ordering around EFB copies (PLAN-60FPS-MODS H14).

A copy that reads rows other workers own -- a filtered one, which is every copy
the game makes -- has to see every earlier draw finished on every row it reads,
and nothing later may write those rows until every worker has read them.
Anything the producer reads of guest memory a copy writes -- a texture, a
palette, an indexed vertex colour -- has to wait for that copy. Until H14 two
full drains around every such copy were what ordered all of it.

A race here depends on which worker gets where first, so a plain run passes by
luck as often as not; the sweep that found PLAN C3's race needed four. So the
workers are made to lag on purpose: SOA_GXR_STALL=<worker>:<kind>:<us> holds
one worker back before every command of a kind (0 a draw, 1 a copy, 2 a
clear). A worker held before its draws reaches a copy late, so a copy that
does not wait for it reads rows it has not drawn; a worker held before its
copies is still reading taps when a copy that does not hold the others back
lets them draw over them.

The oracle is the one-worker run. Every other thread count and stall must
leave the same copied memory, the same screen, the same EFB and the same
decoded textures, frame for frame -- and the frames must differ from each
other, or matching proves nothing. A draw that samples a copy's own texture
takes the copy's image (FINDINGS "Copy images"), the one-worker run included,
so for those the SOA_GXR_DRAIN=1 runs, which make no images and read memory,
are what the image is held to. Built like test_gxr_queue.py: the renderer
on its own, a synthetic stream, no disc and no game data. The driver includes
gxr_tev.c itself, to hash what the texture cache decoded.
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
# One copy of the driver and its runs, which tools/citest/queue_check.py also
# builds under other compilers and on ARM64 (portability.md L8).
from queue_check import OVERLAP_DRIVER as DRIVER  # noqa: E402
from queue_check import OVERLAP_FINAL as FINAL  # noqa: E402
from queue_check import OVERLAP_RUNS as RUNS  # noqa: E402
from queue_check import OVERLAP_SOURCES as SOURCES  # noqa: E402

RUNTIME = ROOT / "runtime"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("overlap")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "overlap.exe"
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
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    results = {}
    for threads, stall, hashed, other in RUNS:
        extra = {"SOA_THREADS": threads}
        if other:
            k, v = other.split("=")
            extra[k] = v
        if stall:
            extra["SOA_GXR_STALL"] = stall
        if hashed:
            extra["SOA_HASH"] = hashed
        run = subprocess.run(
            [str(exe)], capture_output=True, text=True, env={**env, **extra}, cwd=out, timeout=300
        )
        text = run.stdout + run.stderr
        assert run.returncode == 0, f"{threads} {stall}: exit {run.returncode}\n{text}"
        results[(threads, stall, hashed, other)] = {
            "final": {
                k: re.search(rf"\[overlap\] {k} (\w+)", text)[1] for k in (*FINAL, "token reads")
            },
            "frames": re.findall(r"\[gxr\] frame \d+ \d+x\d+ hash (\w+)", text),
            "text": text,
        }
    return results


needs_msvc = pytest.mark.skipif(
    toolchain.cl_path() is None, reason="no MSVC: the renderer cannot be built here"
)


@needs_msvc
def test_the_frames_differ_and_the_second_pass_repeats_the_first(runs):
    """A test whose frames were all alike would pass whatever the order."""
    frames = runs[("1", "", "1", "")]["frames"]
    assert len(frames) == 12, frames
    assert len(set(frames[:6])) == 6, frames
    assert frames[:6] == frames[6:], frames


@needs_msvc
@pytest.mark.parametrize(
    "key",
    [r for r in RUNS if r != ("1", "", "1", "")],
    ids=lambda r: "-".join((x or "_").replace("SOA_GXR_", "") for x in r),
)
def test_every_order_leaves_what_one_worker_leaves(runs, key):
    """Copied memory, the screen, the EFB, every decoded texture and what the
    CPU read after GXDrawDone, against the one-worker run; with SOA_HASH,
    every frame's hash; and where a token waits, or the copies drain, what
    the CPU read after each token."""
    want, got = runs[("1", "", "1", "")], runs[key]
    ordered = key[2] or key[3] in ("SOA_GXR_TOKENWAIT=1", "SOA_GXR_DRAIN=1")
    for k in (*FINAL, "token reads") if ordered else FINAL:
        assert got["final"][k] == want["final"][k], f"{key}: {k} differs\n{got['text'][-3000:]}"
    if key[2]:
        assert got["frames"] == want["frames"], key


def waits(text: str) -> dict:
    m = re.search(r"\[gxr\] waits: (.*?); \d+ drains", text)
    return {w: int(n) for w, n in re.findall(r"([\w/ -]+?) [\d.]+s \((\d+)\)", m[1])} if m else {}


@needs_msvc
def test_the_copies_were_fenced_not_drained(runs):
    """What makes the runs above a test of H14 and not of the old drains: at two
    or more workers the copies were fenced, no copy was drained around, the
    producer's reads of copy destinations waited for their copy, and the frame
    gate did the one drain a frame."""
    for (threads, stall, hashed, other), res in runs.items():
        w = {k.strip(): n for k, n in waits(res["text"]).items()}
        if other == "SOA_GXR_DRAIN=1":  # the drains are back, and nothing of H14 runs
            assert w.get("copy-after", 0) >= 12 * 5 and not w.get("gate"), w
            continue
        assert not {"copy-first", "copy-before", "copy-after"} & set(w), (threads, stall, w)
        if threads != "1":
            m = re.search(r"\[gxr\] fences: (\d+) fenced commands", res["text"])
            assert m and int(m[1]) >= 12 * 4, (threads, stall, res["text"][-2000:])
        if not hashed:  # 12 frames, less the two a GXDrawDone ended with a drain
            assert w.get("gate", 0) >= 8, (threads, stall, w)
        if stall == "2:1:20000":
            # A token waits only under SOA_GXR_TOKENWAIT, and with SOA_HASH the
            # screen copy has drained before it, so it finds every copy done.
            tok = other == "SOA_GXR_TOKENWAIT=1" and not hashed
            want = ("hazard", "tlut", "source") + (("token",) if tok else ())
            assert all(w.get(k, 0) for k in want), (threads, hashed, w)


def images(text: str):
    m = re.search(
        r"(\d+) copy images made, sampled by (\d+) lookups; (\d+) retired and (\d+) overwritten",
        text,
    )
    return tuple(int(x) for x in m.groups()) if m else None


@needs_msvc
def test_the_copy_images_were_taken_where_they_should_be(runs):
    """Copy images (FINDINGS "Copy images"), counted by the producer, so the
    same at any timing but one: every copy to memory makes one, 12 a frame
    over 12 frames. The A and K draws sample theirs; G's is overwritten by a
    newer copy first; M's is retired by GXDrawDone and Q's by a hook's wait;
    N's is retired by the token when the token finds the copies done, which
    SOA_GXR_TOKENWAIT makes certain and timing decides otherwise. SOA_GXR_DRAIN=1 makes none. Without
    this, the image path could stop being taken and every comparison above
    would still pass."""
    for (threads, stall, _hashed, other), res in runs.items():
        got = images(res["text"])
        if other == "SOA_GXR_DRAIN=1":
            assert got is None, (threads, stall, got)
            continue
        assert got, (threads, stall, res["text"][-2000:])
        made, used, retired, overwritten = got
        assert made == 12 * 12 and overwritten == 12, (threads, stall, got)
        if other == "SOA_GXR_TOKENWAIT=1":
            assert (used, retired) == (24, 36), (threads, stall, got)
        else:
            assert used >= 24 and retired >= 24 and used + retired == 60, (threads, stall, got)


@needs_msvc
def test_the_stalls_were_in_force(runs):
    """A stall that never happened would make every run above the plain one."""
    for key, res in runs.items():
        if key[1]:
            assert "SOA_GXR_STALL: 1 stall in force" in res["text"], key
