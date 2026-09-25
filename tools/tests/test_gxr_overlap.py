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
other, or matching proves nothing. Built like test_gxr_queue.py: the renderer
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

RUNTIME = ROOT / "runtime"
SOURCES = ["gx.c", "gxr.c", "png.c"]  # gxr_tev.c comes in through the driver

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "gxr_tev.c" /* the texture cache's statics, to hash its decodes */

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

#define W 128
#define H 96
#define FRAMES 6
#define A_BASE 0x00400000u /* frame f's first copy at A_BASE + f * SLOT */
#define B_BASE 0x00600000u
#define SLOT 0x10000u      /* 128 x 96 RGBA8 is 48 KB */
#define C4_TEX 0x00300000u
#define XFB 0x00100000u

static void setup(CpuState* s)
{
    static const float viewport[6] = {320.0f, -240.0f, 16777215.0f, 662.0f, 582.0f, 16777215.0f};
    static const float ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
    static const float view[12] = {1, 0, 0, -320, 0, -1, 0, 240, 0, 0, 1, -100};
    static const uint32_t one = 1, matidx = 0x3CF3CF00u, chan = 0x441u, zero = 0, texgen = 0;
    bp_w(s, 0x59, 0x02ACABu); bp_w(s, 0x20, 0x156156u); bp_w(s, 0x21, 0x3D5335u);
    xf_f(s, 0x101A, 6, viewport);
    xf_f(s, 0x1020, 6, ortho); xf_w(s, 0x1026, 1, &one);
    xf_f(s, 0x0000, 12, view);
    cp_w(s, 0x30, matidx); xf_w(s, 0x1018, 1, &matidx);
    xf_w(s, 0x1009, 1, &one); xf_w(s, 0x100E, 1, &chan); xf_w(s, 0x1010, 1, &chan);
    xf_w(s, 0x103F, 1, &one); xf_w(s, 0x1040, 1, &texgen); xf_w(s, 0x1008, 1, &one);
    (void)zero;
    bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu); bp_w(s, 0xC1, 0x08BFF0u); bp_w(s, 0x00, 0x000011u);
    bp_w(s, 0xF6, 0x018064u); bp_w(s, 0xF7, 0x01806Eu); bp_w(s, 0xF8, 0x018060u); bp_w(s, 0xF9, 0x01806Cu);
    bp_w(s, 0xFA, 0x018065u); bp_w(s, 0xFB, 0x01806Du); bp_w(s, 0xFC, 0x01806Au); bp_w(s, 0xFD, 0x01806Eu);
    bp_w(s, 0x40, 0x17); bp_w(s, 0x41, 0x18); bp_w(s, 0xF3, 0x3F0000u); bp_w(s, 0x43, 0x40);
    cp_w(s, 0x50, 0x2200); cp_w(s, 0x60, 0); cp_w(s, 0x70, 0x41377009u); cp_w(s, 0x80, 0xC8241209u); cp_w(s, 0x90, 0x04824120u);
    bp_w(s, 0x4E, 0x000100u);
    bp_w(s, 0x53, 0x30A208u); bp_w(s, 0x54, 0x00820Au); /* the game's deflicker: every copy reads three rows */
    bp_w(s, 0x4F, 0x00FF20u); bp_w(s, 0x50, 0x002040u); bp_w(s, 0x51, 0xFFFFFFu);
}

static uint32_t colour(int i, int f)
{
    return ((uint32_t)((i * 37 + f * 53) & 0xFF) << 24) | ((uint32_t)((i * 91 + f * 17) & 0xFF) << 16) |
           ((uint32_t)((i * 13 + f * 101) & 0xFF) << 8) | 0xFFu;
}

static void vertex(CpuState* s, float x, float y, uint32_t rgba) { gpf(s, x); gpf(s, y); gpf(s, 50.0f); gp32(s, rgba); }

static void quad(CpuState* s, float x0, float y0, float x1, float y1, uint32_t rgba)
{
    gp8(s, 0x80); gp16(s, 4);
    vertex(s, x0, y0, rgba); vertex(s, x1, y0, rgba); vertex(s, x1, y1, rgba); vertex(s, x0, y1, rgba);
}

static void untextured(CpuState* s) { bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu); }

/* Stage 0 outputs the texel, through a texture matrix that spreads the texture
 * over the quad, so what a draw sampled reaches the EFB. */
static void textured(CpuState* s, uint32_t addr, unsigned fmt, unsigned w, unsigned h, float x0, float y0, float qw, float qh)
{
    const float m[12] = {1.0f / qw, 0, 0, -x0 / qw, 0, 1.0f / qh, 0, -y0 / qh, 0, 0, 1, 0};
    xf_f(s, 240, 12, m); /* texture matrix 60, which MATIDX gives texcoord 0 */
    bp_w(s, 0x80, 0); bp_w(s, 0x84, 0);
    bp_w(s, 0x88, ((fmt & 15) << 20) | ((h - 1) << 10) | (w - 1));
    bp_w(s, 0x94, (addr >> 5) & 0x1FFFFFu);
    bp_w(s, 0x98, 0); /* TLUT at TMEM 0, IA8 */
    bp_w(s, 0x30, w - 1); bp_w(s, 0x31, h - 1);
    bp_w(s, 0x28, 0x40);
    bp_w(s, 0xC0, 0x088FFFu); /* the texel, not the vertex colour */
}

static void copy_tex(CpuState* s, uint32_t dest)
{
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, ((H - 1) << 10) | (W - 1)); bp_w(s, 0x4D, 0x28);
    bp_w(s, 0x4B, (dest >> 5) & 0x1FFFFFu);
    bp_w(s, 0x52, 0x000063u); /* RGBA8 to memory, no clear */
}

static void screen_copy(CpuState* s)
{
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, ((H - 1) << 10) | (W - 1)); bp_w(s, 0x4D, 0x28);
    bp_w(s, 0x4B, (XFB >> 5) & 0x1FFFFFu);
    bp_w(s, 0x52, 0x004803u); /* to the screen, and clear */
}

static void frame(CpuState* s, int f)
{
    uint32_t a = A_BASE + (uint32_t)f * SLOT, b = B_BASE + (uint32_t)f * SLOT;
    int i;
    untextured(s);
    for (i = 0; i < 24; i++) {
        float x = (float)((i * 13 + f * 7) % (W - 20)), y = (float)((i * 29 + f * 11) % (H - 16));
        quad(s, x, y, x + 20, y + 14, colour(i, f));
    }
    for (i = 0; i < H; i += 24) quad(s, 0, (float)i, W, (float)i + 1, colour(i + 50, f)); /* worker 1's rows, heavier */
    copy_tex(s, a);                                   /* reads rows every worker owns */
    quad(s, 0, 0, W, H, colour(99, f));               /* writes every row the copy just read */
    for (i = 0; i < 8; i++) quad(s, (float)(i * 16), (float)(i * 11), (float)(i * 16 + 30), (float)(i * 11 + 20), colour(i + 200, f));
    copy_tex(s, b);
    bp_w(s, 0x66, 0x001000u); bp_w(s, 0x66, 0x001100u); /* GXInvalidateTexAll */
    textured(s, a, 6, W, H, 0, 0, W / 2, H / 2);        /* samples the first copy */
    quad(s, 0, 0, W / 2, H / 2, 0xFFFFFFFFu);
    bp_w(s, 0x64, (b >> 5) & 0x1FFFFFu); bp_w(s, 0x65, 0x000400u); /* a palette from inside the second copy */
    textured(s, C4_TEX, 8, 8, 8, W / 2, 0, W / 2, H / 2);
    quad(s, W / 2, 0, W, H / 2, 0xFFFFFFFFu);
    untextured(s);                                   /* colours indexed from inside the second copy */
    cp_w(s, 0x50, 0x4200); cp_w(s, 0xA2, (b + 256) & 0x1FFFFFFFu); cp_w(s, 0xB2, 4);
    gp8(s, 0x80); gp16(s, 4);
    gpf(s, 0); gpf(s, H / 2); gpf(s, 50); gp8(s, 0);
    gpf(s, W); gpf(s, H / 2); gpf(s, 50); gp8(s, 5);
    gpf(s, W); gpf(s, H); gpf(s, 50); gp8(s, 9);
    gpf(s, 0); gpf(s, H); gpf(s, 50); gp8(s, 14);
    cp_w(s, 0x50, 0x2200);
    screen_copy(s);
}

static uint64_t fnv(uint64_t h, const uint8_t* p, size_t n)
{
    while (n--) { h ^= *p++; h *= 1099511628211ull; }
    return h;
}

int main(int argc, char** argv)
{
    static CpuState s;
    int cap, f, i;
    uint64_t h;
    (void)argc; (void)argv;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    if (!s.mem) return 2;
    for (i = 0; i < 32; i++) s.mem[C4_TEX + i] = (uint8_t)(i * 37 + 11);
    _putenv("SOA_RENDER=1");
    _putenv("SOA_SNAP=");
    if (!gxr_enabled()) return 3;
    for (cap = 0; cap < 2; cap++) {
        setup(&s); /* first: the reset clears to the clear colour it sets */
        gxr_reset_efb();
        for (f = 0; f < FRAMES; f++) frame(&s, f);
    }
    gxr_flush();
    h = 1469598103934665603ull;
    for (f = 0; f < FRAMES; f++) h = fnv(h, s.mem + A_BASE + (uint32_t)f * SLOT, W * H * 4);
    printf("[overlap] first copies %016llx\n", (unsigned long long)h);
    h = 1469598103934665603ull;
    for (f = 0; f < FRAMES; f++) h = fnv(h, s.mem + B_BASE + (uint32_t)f * SLOT, W * H * 4);
    printf("[overlap] second copies %016llx\n", (unsigned long long)h);
    printf("[overlap] screen %016llx\n", (unsigned long long)gxr_screen_hash());
    printf("[overlap] efb %016llx\n", (unsigned long long)fnv(1469598103934665603ull, &g_efb[0][0][0], sizeof g_efb));
    h = 1469598103934665603ull;
    for (i = 0; i < g_cache_used; i++)
        if (g_cache[i].rgba && g_cache[i].level[0])
            h = fnv(fnv(h, (const uint8_t*)&g_cache[i].addr, 4), g_cache[i].level[0], (size_t)g_cache[i].lw[0] * g_cache[i].lh[0] * 4);
    printf("[overlap] decodes %016llx\n", (unsigned long long)h);
    gxr_report();
    fflush(stdout);
    return 0;
}
"""

# (threads, SOA_GXR_STALL, SOA_HASH): the one-worker run first, as the oracle.
RUNS = [
    ("1", "", "1"),
    ("1", "", ""),
    ("2", "", ""),
    ("3", "", ""),
    ("8", "", ""),
    ("8", "", "1"),
    ("2", "2:0:300", ""),
    ("3", "2:0:300", ""),
    ("8", "2:0:300", ""),
    ("2", "2:1:20000", ""),
    ("3", "2:1:20000", ""),
    ("8", "2:1:20000", ""),
    ("3", "2:2:20000", ""),
    ("8", "2:1:20000", "1"),
]
FINAL = ("first copies", "second copies", "screen", "efb", "decodes")


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
    for threads, stall, hashed in RUNS:
        extra = {"SOA_THREADS": threads}
        if stall:
            extra["SOA_GXR_STALL"] = stall
        if hashed:
            extra["SOA_HASH"] = hashed
        run = subprocess.run(
            [str(exe)], capture_output=True, text=True, env={**env, **extra}, cwd=out, timeout=300
        )
        text = run.stdout + run.stderr
        assert run.returncode == 0, f"{threads} {stall}: exit {run.returncode}\n{text}"
        results[(threads, stall, hashed)] = {
            "final": {k: re.search(rf"\[overlap\] {k} (\w+)", text)[1] for k in FINAL},
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
    frames = runs[("1", "", "1")]["frames"]
    assert len(frames) == 12, frames
    assert len(set(frames[:6])) == 6, frames
    assert frames[:6] == frames[6:], frames


@needs_msvc
@pytest.mark.parametrize(
    "key", [r for r in RUNS if r != ("1", "", "1")], ids=lambda r: "-".join(x or "_" for x in r)
)
def test_every_order_leaves_what_one_worker_leaves(runs, key):
    """Copied memory, the screen, the EFB and every decoded texture, against
    the one-worker run; and with SOA_HASH, every frame's hash."""
    want, got = runs[("1", "", "1")], runs[key]
    for k in FINAL:
        assert got["final"][k] == want["final"][k], f"{key}: {k} differs\n{got['text'][-3000:]}"
    if key[2]:
        assert got["frames"] == want["frames"], key


@needs_msvc
def test_the_stalls_were_in_force(runs):
    """A stall that never happened would make every run above the plain one."""
    for key, res in runs.items():
        if key[1]:
            assert "SOA_GXR_STALL: 1 stall in force" in res["text"], key
