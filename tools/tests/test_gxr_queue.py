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

RUNTIME = ROOT / "runtime"
SOURCES = ["gx.c", "gxr.c", "gxr_tev.c", "png.c"]
GXR = (RUNTIME / "gxr.c").read_text(encoding="utf-8")

# The stream drives the flush in every shape the queue has: a copy to memory
# followed by a draw sampling that destination (the flush that fires from
# inside tev_prepare with a draw half built), GXDrawDone, the screen copy, and
# gxr_reset_efb between captures. Positions and colours move with the frame so
# a frame drawn out of order, twice, or not at all does not hash the same as
# the one before it.
DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "gxr.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint32_t mmio_read32(CpuState* s, uint32_t ea) { (void)s; (void)ea; return 0; }
void hle_report(void) {}

static void gp8(CpuState* s, unsigned v) { gx_pipe_write(s, 1, v); }
static void gp16(CpuState* s, unsigned v) { gx_pipe_write(s, 2, v); }
static void gp32(CpuState* s, uint32_t v) { gx_pipe_write(s, 4, v); }
static void gpf(CpuState* s, float f) { uint32_t u; memcpy(&u, &f, 4); gp32(s, u); }
static void bp_w(CpuState* s, unsigned reg, uint32_t v) { gp8(s, 0x61); gp32(s, ((uint32_t)reg << 24) | (v & 0xFFFFFFu)); }
static void cp_w(CpuState* s, unsigned reg, uint32_t v) { gp8(s, 0x08); gp8(s, reg); gp32(s, v); }
static void xf_w(CpuState* s, unsigned addr, unsigned n, const uint32_t* w)
{
    unsigned i;
    gp8(s, 0x10); gp16(s, n - 1); gp16(s, addr);
    for (i = 0; i < n; i++) gp32(s, w[i]);
}
static void xf_f(CpuState* s, unsigned addr, unsigned n, const float* f)
{
    unsigned i;
    gp8(s, 0x10); gp16(s, n - 1); gp16(s, addr);
    for (i = 0; i < n; i++) gpf(s, f[i]);
}
static void vertex(CpuState* s, float x, float y, float z, uint32_t rgba) { gpf(s, x); gpf(s, y); gpf(s, z); gp32(s, rgba); }

static void setup(CpuState* s)
{
    static const float viewport[6] = {320.0f, -240.0f, 16777215.0f, 662.0f, 582.0f, 16777215.0f};
    static const float ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
    static const float view[12] = {1, 0, 0, -320, 0, -1, 0, 240, 0, 0, 1, -100};
    static const uint32_t one = 1, matidx = 0x3CF3CF00u, chan = 0x441u, zero = 0;
    bp_w(s, 0x59, 0x02ACABu); bp_w(s, 0x20, 0x156156u); bp_w(s, 0x21, 0x3D5335u);
    xf_f(s, 0x101A, 6, viewport);
    xf_f(s, 0x1020, 6, ortho); xf_w(s, 0x1026, 1, &one);
    xf_f(s, 0x0000, 12, view);
    cp_w(s, 0x30, matidx); xf_w(s, 0x1018, 1, &matidx);
    xf_w(s, 0x1009, 1, &one); xf_w(s, 0x100E, 1, &chan); xf_w(s, 0x1010, 1, &chan);
    xf_w(s, 0x103F, 1, &zero); xf_w(s, 0x1008, 1, &one);
    bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu); bp_w(s, 0xC1, 0x08BFF0u); bp_w(s, 0x00, 0x000010u);
    bp_w(s, 0xF6, 0x018064u); bp_w(s, 0xF7, 0x01806Eu); bp_w(s, 0xF8, 0x018060u); bp_w(s, 0xF9, 0x01806Cu);
    bp_w(s, 0xFA, 0x018065u); bp_w(s, 0xFB, 0x01806Du); bp_w(s, 0xFC, 0x01806Au); bp_w(s, 0xFD, 0x01806Eu);
    bp_w(s, 0x40, 0x17); bp_w(s, 0x41, 0x18); bp_w(s, 0xF3, 0x3F0000u); bp_w(s, 0x43, 0x40);
    cp_w(s, 0x50, 0x2200); cp_w(s, 0x60, 0); cp_w(s, 0x70, 0x41377009u); cp_w(s, 0x80, 0xC8241209u); cp_w(s, 0x90, 0x04824120u);
    bp_w(s, 0x4E, 0x000100u);
}

/* Stage 0 samples map 0 and passes the rasterized colour through, so every
 * draw decodes a texture the next flush frees without the texels reaching a
 * pixel: the picture says which draws ran, not what they sampled. */
static void use_texture(CpuState* s, uint32_t addr, unsigned fmt, unsigned w, unsigned h)
{
    bp_w(s, 0x80, 0); bp_w(s, 0x84, 0);
    bp_w(s, 0x88, ((fmt & 15) << 20) | ((h - 1) << 10) | (w - 1));
    bp_w(s, 0x94, (addr >> 5) & 0x1FFFFFu);
    bp_w(s, 0x98, 0);
    bp_w(s, 0x30, w - 1); bp_w(s, 0x31, h - 1);
    bp_w(s, 0x28, 0x40);
}

static void quad(CpuState* s, float x0, float y0, float x1, float y1, uint32_t rgba)
{
    gp8(s, 0x80); gp16(s, 4);
    vertex(s, x0, y0, 50.0f, rgba); vertex(s, x1, y0, 50.0f, rgba);
    vertex(s, x1, y1, 50.0f, rgba); vertex(s, x0, y1, 50.0f, rgba);
}

static void copy_to_memory(CpuState* s, uint32_t dest, unsigned w, unsigned h)
{
    bp_w(s, 0x49, 0);
    bp_w(s, 0x4A, ((h - 1) << 10) | (w - 1));
    bp_w(s, 0x4D, 0x28);
    bp_w(s, 0x4B, (dest >> 5) & 0x1FFFFFu);
    bp_w(s, 0x52, 0x000043u);
}

static void present(CpuState* s)
{
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, 0x077E7F); bp_w(s, 0x4D, 0x28);
    bp_w(s, 0x4B, (0x81100000u & 0x1FFFFFFFu) >> 5);
    bp_w(s, 0x52, 0x4003);
    gxr_flush();
}

#define CAPTURES 2
#define FRAMES 5

int main(void)
{
    static CpuState s;
    int cap, f, i;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    if (!s.mem) return 2;
    _putenv("SOA_RENDER=1");
    _putenv("SOA_SNAP=");
    _putenv("SOA_GXR_DRAWS=");
    if (!gxr_enabled()) return 3;

    for (cap = 0; cap < CAPTURES; cap++) {
        gxr_reset_efb(); /* a replay renders several captures in one process */
        setup(&s);
        for (f = 0; f < FRAMES; f++) {
            for (i = 0; i < 40; i++) {
                float x = (float)(8 + (i * 13 + f * 7) % 560), y = (float)(8 + (i * 29 + f * 11) % 400);
                uint32_t col = ((uint32_t)((i * 7 + f * 5) & 0xFF) << 24) | ((uint32_t)((i * 31 + f * 3) & 0xFF) << 16) |
                               ((uint32_t)((f * 9 + i) & 0xFF) << 8) | 0xFFu;
                use_texture(&s, 0x00400000u + (uint32_t)((cap * 997 + f * 61 + i) * 512), 9, 16, 16);
                quad(&s, x, y, x + 60.0f, y + 40.0f, col);
                if ((i & 3) == 3) {
                    /* The draw after this copy samples what the copy has not
                     * written yet, so tev_prepare flushes with the draw half
                     * built. */
                    copy_to_memory(&s, 0x00300000u + (uint32_t)(i * 4096), 32, 32);
                    use_texture(&s, 0x00300000u + (uint32_t)(i * 4096), 4, 32, 32);
                    quad(&s, (float)(100 + i + f), (float)(60 + i), (float)(140 + i + f), (float)(100 + i), 0x00FF00FFu);
                }
                if ((i % 17) == 16) bp_w(&s, 0x45, 2); /* GXDrawDone: flushes */
            }
            present(&s);
            printf("[queue] cap %d frame %d hash %016llx\n", cap, f, (unsigned long long)gxr_screen_hash());
        }
    }
    gxr_report();
    fprintf(stderr, "[queue] done\n");
    return 0;
}
"""

THREAD_COUNTS = ("1", "2", "3", "8")


needs_msvc = pytest.mark.skipif(
    toolchain.cl_path() is None, reason="no MSVC: the renderer cannot be built here"
)


def worker_body() -> str:
    """The text of gxr.c's worker(), which is the only rasterizer-side reader."""
    start = GXR.index("static DWORD WINAPI worker(LPVOID arg)")
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
    for name, op in (("g_published", "InterlockedIncrement64"), ("g_ran", "InterlockedExchange64")):
        writes = re.findall(rf"{op}\(&{name}", body)
        assert writes, f"{name} is no longer published with {op}"


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
