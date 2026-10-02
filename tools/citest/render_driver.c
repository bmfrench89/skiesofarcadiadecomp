/*
 * Run the renderer's own pixel checks with no game, no disc and no recompiled
 * code, so CI can run them.
 *
 * runtime/selftest.c already draws two frames through the real GX front end
 * and counts the pixels that come out, but it can only run inside the port:
 * SOA_SELFTEST=1 needs gen/, which needs the user's disc. The renderer does
 * not -- gx.c, gxr.c, gxr_tev.c and png.c reach exactly two symbols outside
 * themselves, stubbed below -- so the same two checks link into a binary of
 * their own, and a push that breaks the rasterizer fails on the runner rather
 * than in someone's eye a week later.
 *
 * The block between the COPY markers is verbatim from runtime/selftest.c
 * (the render recipe and the two checks). It is a copy because the original
 * is static inside a file full of recompiled-code checks that cannot link
 * here; tools/tests/test_citest.py compares the two texts, so the copy cannot
 * quietly drift from what the port itself runs.
 *
 * Since L6 it also holds plat_f2i to its contract and draws a frame whose
 * pixels come out of out-of-range conversions, with its hash pinned.
 *
 * Exit status is the number of checks that failed.
 */
#define _CRT_SECURE_NO_WARNINGS
/* This file's plat_f2i is the range test every non-x86 target compiles, so
 * that f2i_checks() can hold it to the instruction; the renderer's own files
 * keep the instruction on x86. -DPLAT_F2I_SATURATE overrides both (L6). */
#define PLAT_F2I_GENERIC
#include "cpu.h"
#include "gxr.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* The renderer reads guest memory through mem_r32, which routes the hardware
 * window to the runtime's device models; nothing in these two frames is a
 * pointer into that window, so a call here means the test drew something it
 * was not asked to. Counted rather than silently answered with zero. */
static unsigned g_mmio_reads;

uint32_t mmio_read32(CpuState* s, uint32_t ea)
{
    (void)s;
    (void)ea;
    g_mmio_reads++;
    return 0;
}

/* gx.c's frame_end() calls this when SOA_FRAMES stops a run; nothing sets a
 * frame limit here, so it exists only to satisfy the linker. */
void hle_report(void) {}

/* What the copied checks need from the environment, defined outside the
 * copy because runtime/selftest.c has its own: there the thread count is
 * always one, and here it is --threads (render_check.py asserts the renderer
 * started that many). SOA_SNAP is removed: an interval left in the
 * environment would skip the one frame the checks draw. */
static int g_threads = 1;

static void render_env(void)
{
    char n[16];
    snprintf(n, sizeof n, "%d", g_threads);
    plat_setenv("SOA_RENDER", "1");
    plat_setenv("SOA_THREADS", n);
    plat_setenv("SOA_SNAP", NULL);
}

/* ---- BEGIN COPY of runtime/selftest.c: check() and the render checks ---- */
static int check(const char* what, const char* got, const char* want)
{
    int ok = strcmp(got, want) == 0;
    fprintf(stderr, "[selftest] %-28s %s  got \"%s\"%s%s%s\n", what, ok ? "ok  " : "FAIL", got,
            ok ? "" : " want \"", ok ? "" : want, ok ? "" : "\"");
    return !ok;
}

/* ---- the software renderer, through the real GX pipe --------------------
 * The register recipe is the one the game uses for its full-screen fades
 * (orthographic, 640x480, one colour channel from the vertex), so this also
 * pins down the command encodings the front end parses. */
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

static void present(CpuState* s)
{
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, 0x077E7F); bp_w(s, 0x4D, 0x28); bp_w(s, 0x4B, (0x81100000u & 0x1FFFFFFFu) >> 5);
    bp_w(s, 0x52, 0x4003); /* copy to the XFB: the frame is done */
    gxr_flush();
}

static unsigned count_color(const uint8_t* screen, int w, int h, uint8_t r, uint8_t g, uint8_t b)
{
    unsigned n = 0;
    int x, y;
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            const uint8_t* p = screen + ((size_t)y * EFB_W + x) * 4;
            if (p[0] == r && p[1] == g && p[2] == b) n++;
        }
    return n;
}

static int render_selftest(CpuState* s, char* got, size_t cap)
{
    static const float viewport[6] = {320.0f, -240.0f, 16777215.0f, 662.0f, 582.0f, 16777215.0f};
    static const float ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
    static const float view[12] = {1, 0, 0, -320, 0, -1, 0, 240, 0, 0, 1, -100};
    static const uint32_t one = 1, matidx = 0x3CF3CF00u, chan = 0x441u, zero = 0;
    const uint8_t* screen;
    int w = 0, h = 0, failures = 0;

    render_env();
    if (!gxr_enabled()) { fprintf(stderr, "[selftest] renderer disabled; skipping render checks\n"); return 0; }
    gxr_reset_efb();

    bp_w(s, 0x59, 0x02ACABu); bp_w(s, 0x20, 0x156156u); bp_w(s, 0x21, 0x3D5335u); /* scissor: the full 640x480 */
    xf_f(s, 0x101A, 6, viewport);
    xf_f(s, 0x1020, 6, ortho); xf_w(s, 0x1026, 1, &one);
    xf_f(s, 0x0000, 12, view);
    cp_w(s, 0x30, matidx); xf_w(s, 0x1018, 1, &matidx);
    xf_w(s, 0x1009, 1, &one); xf_w(s, 0x100E, 1, &chan); xf_w(s, 0x1010, 1, &chan); xf_w(s, 0x103F, 1, &zero); xf_w(s, 0x1008, 1, &one);
    bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu); bp_w(s, 0xC1, 0x08BFF0u); bp_w(s, 0x00, 0x10);
    /* swap tables (GXSetTevSwapModeTable): identity for the rasterized and texture colours */
    bp_w(s, 0xF6, 0x018064u); bp_w(s, 0xF7, 0x01806Eu); bp_w(s, 0xF8, 0x018060u); bp_w(s, 0xF9, 0x01806Cu);
    bp_w(s, 0xFA, 0x018065u); bp_w(s, 0xFB, 0x01806Du); bp_w(s, 0xFC, 0x01806Au); bp_w(s, 0xFD, 0x01806Eu);
    bp_w(s, 0x40, 0x17); bp_w(s, 0x41, 0x18); bp_w(s, 0xF3, 0x3F0000u); bp_w(s, 0x43, 0x40);
    cp_w(s, 0x50, 0x2200); cp_w(s, 0x60, 0); cp_w(s, 0x70, 0x41377009u); cp_w(s, 0x80, 0xC8241209u); cp_w(s, 0x90, 0x04824120u);

    /* A full-screen red quad covers every pixel. */
    gp8(s, 0x80); gp16(s, 4);
    vertex(s, 0, 0, 50, 0xFF0000FFu); vertex(s, 640, 0, 50, 0xFF0000FFu);
    vertex(s, 640, 480, 50, 0xFF0000FFu); vertex(s, 0, 480, 50, 0xFF0000FFu);
    present(s);
    screen = gxr_screen(&w, &h);
    snprintf(got, cap, "%u of %d red", screen ? count_color(screen, w, h, 255, 0, 0) : 0u, w * h);
    failures += check("render full-screen quad", got, "307200 of 307200 red");

    /* The title screen's cloud triangle: (320.5,-22.1) (789.1,-22.1) (789.1,530.2).
     * Its top edge is off horizontal by a sub-pixel amount (as the perspective
     * divide leaves it): its x coefficient is a crumb, and the span code
     * once divided by it, overflowed the int conversion and dropped rows. The part
     * inside the screen is right of the diagonal, about 53,300 pixels. */
    gxr_reset_efb();
    gp8(s, 0x90); gp16(s, 3);
    vertex(s, 320.5f, -22.1f, 50, 0x00FF00FFu); vertex(s, 789.1f, -22.09999f, 50, 0x00FF00FFu); vertex(s, 789.1f, 530.2f, 50, 0x00FF00FFu);
    present(s);
    screen = gxr_screen(&w, &h);
    {
        unsigned green = screen ? count_color(screen, w, h, 0, 255, 0) : 0u;
#define G(x, y) (screen && screen[((size_t)(y) * EFB_W + (x)) * 4 + 1] == 255)
        int ok = green > 52000 && green < 54500 && G(600, 300) && G(630, 10) && G(500, 100) && !G(360, 60) && !G(600, 340) && !G(100, 200);
#undef G
        snprintf(got, cap, "%s, %u px", ok ? "complete" : "holes", green);
        failures += check("render triangle rows", got, ok ? got : "complete, ~53300 px");
    }
    return failures;
}
/* ---- END COPY ---------------------------------------------------------- */

/* ---- plat_f2i's contract (L6) --------------------------------------------
 * x86's cvttss2si on every target: truncation, and INT32_MIN for NaN and
 * anything outside [-2^31, 2^31). The table runs everywhere; on x86 the
 * range test is also held to the instruction over all 2^32 bit patterns.
 * The unsigned depth casts fog_apply and depth_test make are not plat_f2i:
 * their clamp passes only a NaN, and the check below is that NaN gives 0. */
static uint32_t depth_cast(float depth) /* fog_apply's and depth_test's expression */
{
    return (uint32_t)(depth < 0.0f ? 0.0f : (depth > 1.0f ? 16777215.0f : depth * 16777215.0f));
}

static float from_bits(uint32_t u)
{
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static int f2i_checks(void)
{
    static const struct {
        uint32_t bits;
        int32_t want;
        const char* name;
    } T[] = {
        {0x7FC00000u, INT32_MIN, "NaN"},          {0xFFC00001u, INT32_MIN, "-NaN"},
        {0x7F800000u, INT32_MIN, "+inf"},         {0xFF800000u, INT32_MIN, "-inf"},
        {0x4F000000u, INT32_MIN, "2^31"},         {0xCF000000u, INT32_MIN, "-2^31, exact"},
        {0x4EFFFFFFu, 2147483520, "2^31-128"},    {0xCF000001u, INT32_MIN, "-2^31-256"},
        {0x501502F9u, INT32_MIN, "1e10"},         {0xD01502F9u, INT32_MIN, "-1e10"},
        {0x3FC00000u, 1, "1.5"},                  {0xBFC00000u, -1, "-1.5"},
        {0x3F7FFFFFu, 0, "the float below 1"},    {0x80000000u, 0, "-0"},
    };
    volatile float vd;
    unsigned i, bad = 0;
    for (i = 0; i < sizeof T / sizeof T[0]; i++) {
        int32_t got = plat_f2i(from_bits(T[i].bits));
        if (got != T[i].want) {
            fprintf(stderr, "[render] plat_f2i(%s) = %ld, wanted %ld\n", T[i].name, (long)got, (long)T[i].want);
            bad++;
        }
    }
    /* volatile, so that no compiler folds a NaN conversion at build time */
    vd = from_bits(0x7FC00000u);
    if (depth_cast(vd) != 0) { fprintf(stderr, "[render] the unsigned depth cast of a NaN is %lu, not 0\n", (unsigned long)depth_cast(vd)); bad++; }
    vd = 0.5f;
    if (depth_cast(vd) != 8388607u) { fprintf(stderr, "[render] the unsigned depth cast of 0.5 is %lu\n", (unsigned long)depth_cast(vd)); bad++; }
#if PLAT_X86_64
    {
        uint32_t u = 0, first = 0;
        uint64_t differ = 0;
        do {
            float f = from_bits(u);
            if (plat_f2i(f) != _mm_cvtt_ss2si(_mm_set_ss(f)) && differ++ == 0) first = u;
        } while (++u != 0);
        if (differ) {
            fprintf(stderr, "[render] plat_f2i's range test and cvttss2si differ on %llu floats, the first %08lX\n",
                    (unsigned long long)differ, (unsigned long)first);
            bad++;
        }
        fprintf(stderr, "[render] plat_f2i: %u table cases, the unsigned depth cast, and all 4294967296 floats against cvttss2si: %s\n",
                (unsigned)(sizeof T / sizeof T[0]), bad ? "FAIL" : "ok");
    }
#else
    fprintf(stderr, "[render] plat_f2i: %u table cases and the unsigned depth cast: %s\n",
            (unsigned)(sizeof T / sizeof T[0]), bad ? "FAIL" : "ok");
#endif
    return bad != 0;
}

/* ---- an EFB copy's destination stride ------------------------------------
 * BP 0x4D is the distance from one row of tiles to the next where a copy
 * writes, in 32-byte units: GXSetTexCopyDst sets it from the texture the copy
 * makes, which can be wider than the copy. The battle transition copies the
 * 640-wide screen into a 1024-wide RGB5A3 texture, and a renderer that packed
 * the rows drew it as streaks (FINDINGS "V1"). Here a 16x8 red block is
 * copied as RGB565 with rows 512 bytes apart, four times its own 128: both
 * rows of tiles must be red where the stride puts them, and the bytes between
 * must keep the 0xA5 they were given. */
#define STRIDE_DEST 0x00200000u

static int copy_stride_check(CpuState* s)
{
    uint8_t* d = s->mem + STRIDE_DEST;
    int bad = 0, i;
    memset(d, 0xA5, 2048);
    gxr_reset_efb();
    gp8(s, 0x80); gp16(s, 4);
    vertex(s, 0, 0, 50, 0xFF0000FFu); vertex(s, 640, 0, 50, 0xFF0000FFu);
    vertex(s, 640, 480, 50, 0xFF0000FFu); vertex(s, 0, 480, 50, 0xFF0000FFu);
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, (7u << 10) | 15u); bp_w(s, 0x4D, 512 / 32);
    bp_w(s, 0x4B, STRIDE_DEST >> 5);
    bp_w(s, 0x52, 8u << 3); /* RGB565 to memory, no clear */
    gxr_flush();
    for (i = 0; i < 128; i++) {
        uint8_t want = (i & 1) ? 0x00 : 0xF8; /* 0xF800, big-endian */
        if (d[i] != want || d[512 + i] != want) bad++;
    }
    for (i = 128; i < 512; i++)
        if (d[i] != 0xA5) bad++;
    fprintf(stderr, "[render] copy stride: rows of tiles 512 bytes apart, the gap untouched: %s\n",
            bad ? "FAIL" : "ok");
    if (bad) fprintf(stderr, "[render] copy stride: %d bytes wrong; the first row's start %02X %02X, at 128 %02X, at 512 %02X\n",
                     bad, d[0], d[1], d[128], d[512]);
    return bad != 0;
}

/* ---- a frame drawn from out-of-range conversions (L6) --------------------
 * Six blocks of the screen, each a quad with one texture coordinate at all
 * four corners, so every pixel of a block samples the same point and the
 * block is one value worked out by hand. The texture is one 8x4 I8 tile
 * from an LCG, bilinear and repeating; TEXC times a white RASC is the texel
 * unchanged. Rows 0 and 1 of it, which every block below reads:
 *     220   4 101 170  31 173  29  90
 *     218 229 172  27  30  95  19 112
 * A coordinate beyond int range makes fast_floor INT32_MIN, which repeats
 * to texel 0 (row 0, column 0), and its weight 0 (sample_level). On x86:
 *   A  s 0.61, t 0.33   both in range: x0 4, ax 97; y0 0, ay 209      60
 *   B  s 0.61, t 1e10   t out: rows 0 and 1, ay 0                      85
 *   C  s 1e10, t 0.33   s out: columns 0 and 1, ax 0                  218
 *   D  s 1e10, t 1e10   both out: texel (0, 0)                        220
 *   E  s -1e10, t 0.33  below -2^31 fast_floor's i - 1 wraps to
 *                       INT32_MAX: columns 7 and 0, ax 0              108
 *   F  s NaN, t 0.33    NaN is INT32_MIN too; and the texture matrix
 *                       makes t 0 * NaN + t, NaN as well: texel (0, 0) 220
 * ARM64's saturating conversion, which PLAT_F2I_SATURATE stands in for,
 * puts B on rows 3 and 0 (19), C on columns 7 and 0 (108) and D on texel
 * (7, 3) (70). Before L6 the SIMD path also drew B as 0 where the scalar
 * path drew 85: B's weight along s is odd and its 2x2 texels sum odd, which
 * is where their wrapped arithmetic parted. No vertex colour can leave
 * [0, 1] through GX -- read_color decodes bytes and light_channel clamps --
 * so nothing here converts an out-of-range colour. SOA_RENDER_PNG=<path>
 * writes the frame, to look at before re-pinning the hash. */
/* Pinned 2026-10-02 after every block was checked against the values above,
 * with the SIMD path, the scalar path and the range test, and the owner had
 * looked at the frame. */
#define F2I_FRAME_HASH 0xaa535458106bed0eull
#define TEX_ADDR 0x00100000u

static void tex_block(CpuState* s, float x0, float y0, float x1, float y1, float sc, float tc)
{
    float x[4] = {x0, x1, x1, x0}, y[4] = {y0, y0, y1, y1};
    int i;
    for (i = 0; i < 4; i++) {
        vertex(s, x[i], y[i], 50, 0xFFFFFFFFu);
        gpf(s, sc);
        gpf(s, tc);
    }
}

static int f2i_frame(CpuState* s)
{
    static const uint32_t one = 1, texgen = 5u << 7; /* one texgen: TEX0, regular, through its matrix */
    static const float ident[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    static const struct {
        int x0, y0, x1, y1;
        float s, t;
        unsigned want;
        const char* name;
    } B[] = {
        {0, 0, 213, 240, 0.61f, 0.33f, 60, "A, in range"},
        {213, 0, 427, 240, 0.61f, 1e10f, 85, "B, t out of range"},
        {427, 0, 640, 240, 1e10f, 0.33f, 218, "C, s out of range"},
        {0, 240, 213, 480, 1e10f, 1e10f, 220, "D, both out of range"},
        {213, 240, 427, 480, -1e10f, 0.33f, 108, "E, s -1e10"},
        {427, 240, 640, 480, 0.0f, 0.33f, 220, "F, s NaN"},
    };
    const char* png = getenv("SOA_RENDER_PNG");
    const uint8_t* screen;
    int w = 0, h = 0, bad = 0;
    unsigned i;
    uint32_t lcg;
    uint64_t hash;
    for (i = 0, lcg = 12345u; i < 32; i++) {
        lcg = lcg * 1103515245u + 12345u;
        s->mem[TEX_ADDR + i] = (uint8_t)(lcg >> 16);
    }
    gxr_reset_efb();
    cp_w(s, 0x60, 1);                      /* VCD_HI: TEX0 direct; the recipe's VAT already says F32 s,t */
    xf_w(s, 0x103F, 1, &one);              /* one texgen */
    xf_w(s, 0x1040, 1, &texgen);
    xf_f(s, 4 * 60, 12, ident);            /* texture matrix 60, which the recipe's MATINDEX names for TEX0 */
    bp_w(s, 0x00, 0x11);                   /* GENMODE: one texgen, one colour channel */
    bp_w(s, 0x28, 0x40);                   /* TREF0: stage 0 samples map 0 through coord 0, colour channel 0 */
    bp_w(s, 0xC0, 0x08F8AFu);              /* stage 0 colour: TEXC times RASC, clamped */
    bp_w(s, 0x30, 7); bp_w(s, 0x31, 3);    /* SU_SSIZE0, SU_TSIZE0: 8 by 4 */
    bp_w(s, 0x80, 0x95);                   /* SETMODE0: repeat both ways, bilinear */
    bp_w(s, 0x84, 0);                      /* SETMODE1: no LOD range */
    bp_w(s, 0x88, 0x100C07u);              /* SETIMAGE0: 8 by 4, I8 */
    bp_w(s, 0x94, TEX_ADDR >> 5);          /* SETIMAGE3: where it is */
    gp8(s, 0x80); gp16(s, 4 * (sizeof B / sizeof B[0]));
    for (i = 0; i < sizeof B / sizeof B[0]; i++)
        tex_block(s, (float)B[i].x0, (float)B[i].y0, (float)B[i].x1, (float)B[i].y1,
                  i == 5 ? from_bits(0x7FC00000u) : B[i].s, B[i].t);
    present(s);
    screen = gxr_screen(&w, &h);
    hash = gxr_screen_hash();
    if (screen && png && *png && !png_write_rgba(png, screen, w, h, EFB_W * 4)) fprintf(stderr, "[render] cannot write %s\n", png);
    for (i = 0; i < sizeof B / sizeof B[0]; i++) {
        unsigned off = 0, first = 0;
        int x, y;
        for (y = B[i].y0; y < B[i].y1; y++)
            for (x = B[i].x0; x < B[i].x1; x++) {
                unsigned r = screen ? screen[((size_t)y * EFB_W + x) * 4] : 256u;
                if (r != B[i].want && off++ == 0) first = r;
            }
        if (off) {
            fprintf(stderr, "[render] block %s: %u pixels are not %u (the first is %u)\n", B[i].name, off, B[i].want, first);
            bad++;
        }
    }
    fprintf(stderr, "[render] out-of-range frame: %d of 6 blocks as worked out by hand; hash %016llx, pinned %016llx: %s\n",
            6 - bad, (unsigned long long)hash, F2I_FRAME_HASH, !bad && hash == F2I_FRAME_HASH ? "ok" : "FAIL");
    return bad || hash != F2I_FRAME_HASH;
}

int main(int argc, char** argv)
{
    CpuState s;
    char got[128];
    int failures, i;

    for (i = 1; i + 1 < argc; i++)
        if (!strcmp(argv[i], "--threads")) g_threads = atoi(argv[++i]);
    if (g_threads < 1) g_threads = 1;
    memset(&s, 0, sizeof s);
    s.mem = (uint8_t*)calloc(1, MEM1_SIZE);
    if (!s.mem) {
        fprintf(stderr, "[render] cannot allocate MEM1\n");
        return 2;
    }
    failures = render_selftest(&s, got, sizeof got);
    /* Printed, not asserted: the span arithmetic rounds with ceilf and floorf,
     * and whether two MSVC versions agree on a boundary pixel is exactly what
     * nobody has checked yet. The counts above are the assertion; this is here
     * so the day someone wants to compare two machines, the number is in the
     * log of every run since. */
    fprintf(stderr, "[render] second frame hash %016llx (not asserted)\n",
            (unsigned long long)gxr_screen_hash());
    failures += f2i_checks();
    if (gxr_enabled()) failures += copy_stride_check(&s);
    if (gxr_enabled()) failures += f2i_frame(&s);
    if (g_mmio_reads) fprintf(stderr, "[render] %u MMIO reads, which these frames should not need\n", g_mmio_reads);
    fprintf(stderr, "[render] %s\n", failures ? "FAILED" : "every render check passes");
    free(s.mem);
    return failures;
}
