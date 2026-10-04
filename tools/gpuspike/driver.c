/*
 * The GPU spike's driver (specs/gpu-backend.md V3a, V3b): the renderer with no
 * game, no disc and no recompiled code, drawing a set of scenes through the
 * real GX front end either on the CPU (--backend cpu, the worker pool on one
 * thread) or through gxv, the Vulkan backend (--backend gpu). Each scene's
 * screen copy is written to <out>/<scene>.png and its covered pixels counted;
 * tools/gpuspike.py runs both and compares them.
 *
 * The block between the COPY markers is verbatim from runtime/selftest.c (the
 * render recipe and its two checks), as in tools/citest/render_driver.c, and
 * tools/tests/test_gpuspike.py holds it to the original. Here it runs on
 * whichever backend was asked for, so "307200 of 307200 red" on the GPU is
 * the CPU's own assertion passing there.
 *
 * In gpu mode the clip scenes also check what the consumer uploaded: each
 * draw's vertices, after any rebuild, against this file's own walk of the
 * draw through gxr_clip_polygon, field by field. --mutate unclipped tells gxv
 * to upload every draw as it is, which both that check and the pixels must
 * catch.
 *
 * Two more modes are V3b's exact differentials. --tevdiff N runs tev_pixel
 * and tev.glsl over N setups from random registers in this one process (gpu
 * only) and counts mismatches and the paths taken. --copydiff N makes the
 * same random copies, N rectangles for each of 128 combinations, through
 * whichever backend was asked for, and writes a line a copy to
 * <out>/copydiff.txt for tools/gpuspike.py to hold the two runs' lines
 * against each other. --seed picks the cases; the same seed makes the same
 * ones in both processes. --loddiff N (V5, gpu only) holds lod.glsl, the
 * fragment stage's level of detail, against the sampler's own and span_lod
 * over N cases of each kind.
 *
 * --replay BASE runs a capture (BASE.fifo, .regs, .ram) on either backend and
 * prints the frame's hash; --png writes the frame, --dump-ram the RAM it left
 * and --dump-depth the depth buffer, as 24-bit values. --logicop picks how
 * gxv draws logic ops. --png-full (V9a, gpu only) writes the last screen
 * copy as drawn at SOA_GPU_SCALE, S times the frame's size.
 *
 * Exit status: 0 when every check here passed, 1 when one failed, 3 when gpu
 * mode found no Vulkan device (a skip, which the caller reports as one).
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "gxr.h"
#include "gxr_cmd.h"
#include "gxv.h"
#include "picture.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* As in render_driver.c: nothing drawn here points into the hardware window,
 * so a call is counted rather than answered. */
static unsigned g_mmio_reads;

uint32_t mmio_read32(CpuState* s, uint32_t ea)
{
    (void)s;
    (void)ea;
    g_mmio_reads++;
    return 0;
}

void hle_report(void) {}

/* gx.c's capture replay, which no header declares: the port reaches it from
 * main.c, and tools/tests/test_gxr_backend.py's driver declares it too. */
int gx_replay(CpuState* s, const char* base);

/* One thread, as the port's own self test has it: the CPU images are then
 * the ones that test pins. */
static void render_env(void)
{
    plat_setenv("SOA_RENDER", "1");
    plat_setenv("SOA_THREADS", "1");
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

/* ---- the scenes --------------------------------------------------------- */

static const char* g_out = "build/gpuspike/out";
static int g_gpu;

static unsigned covered(const uint8_t* screen, int w, int h)
{
    unsigned n = 0;
    int x, y;
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            const uint8_t* p = screen + ((size_t)y * EFB_W + x) * 4;
            if (p[0] | p[1] | p[2]) n++;
        }
    return n;
}

/* The frame drawn so far, presented, written and counted. The EFB is cleared
 * to black (every clear register is zero), which no scene draws with. */
static int finish_scene(CpuState* s, const char* name)
{
    char path[512];
    const uint8_t* screen;
    int w = 0, h = 0;
    present(s);
    screen = gxr_screen(&w, &h);
    snprintf(path, sizeof path, "%s/%s.png", g_out, name);
    if (!png_write_rgba(path, screen, w, h, EFB_W * 4)) {
        fprintf(stderr, "[gpuspike] cannot write %s\n", path);
        return 1;
    }
    printf("scene %s %dx%d covered %u\n", name, w, h, covered(screen, w, h));
    return 0;
}

static void tri(CpuState* s, const float* p, uint32_t c0, uint32_t c1, uint32_t c2)
{
    vertex(s, p[0], p[1], p[2], c0);
    vertex(s, p[3], p[4], p[5], c1);
    vertex(s, p[6], p[7], p[8], c2);
}

/* Four triangle shapes, each in both windings, plus a strip and a fan in
 * both, and a quad in both, under GEN_MODE's cull mode m. Columns 128 wide:
 * shapes 0-3 in columns 0-3 (one winding above, the other below), the strip
 * and a quad in column 4 above, the fan and the other quad below. */
static int scene_cull(CpuState* s, unsigned m)
{
    static const float shape[4][6] = {
        {8, 10, 120, 30, 32, 220},      /* large */
        {4, 5, 124, 120, 8, 40},        /* a sliver */
        {8, 100, 120, 100.3f, 64, 230}, /* an edge a crumb off horizontal */
        {64, 10, 64, 230, 120, 120},    /* a vertical edge */
    };
    static const uint32_t col[4] = {0xFF4020FFu, 0x20FF40FFu, 0x4020FFFFu, 0xFFFF20FFu};
    char name[32];
    unsigned k, row;
    gxr_reset_efb();
    bp_w(s, 0x00, 0x10u | (m << 14));
    gp8(s, 0x90);
    gp16(s, 4 * 2 * 3);
    for (k = 0; k < 4; k++)
        for (row = 0; row < 2; row++) {
            float x0 = 128.0f * (float)k, y0 = 240.0f * (float)row;
            float a[2] = {x0 + shape[k][0], y0 + shape[k][1]}, b[2] = {x0 + shape[k][2], y0 + shape[k][3]},
                  c[2] = {x0 + shape[k][4], y0 + shape[k][5]};
            uint32_t cc = row ? col[k] ^ 0x80808000u : col[k];
            if (row) {
                vertex(s, a[0], a[1], 50, cc); vertex(s, c[0], c[1], 50, cc); vertex(s, b[0], b[1], 50, cc);
            } else {
                vertex(s, a[0], a[1], 50, cc); vertex(s, b[0], b[1], 50, cc); vertex(s, c[0], c[1], 50, cc);
            }
        }
    /* A strip of four triangles: draw_command reverses every other one so all
     * four keep the first one's winding, which Vulkan's strip order does too. */
    gp8(s, 0x98);
    gp16(s, 6);
    vertex(s, 520, 10, 50, 0xE0E0E0FFu); vertex(s, 530, 100, 50, 0xE0E0E0FFu); vertex(s, 560, 15, 50, 0xE0E0E0FFu);
    vertex(s, 570, 105, 50, 0xE0E0E0FFu); vertex(s, 600, 12, 50, 0xE0E0E0FFu); vertex(s, 630, 110, 50, 0xE0E0E0FFu);
    gp8(s, 0x80);
    gp16(s, 4);
    vertex(s, 520, 130, 50, 0x80E0E0FFu); vertex(s, 630, 130, 50, 0x80E0E0FFu);
    vertex(s, 630, 230, 50, 0x80E0E0FFu); vertex(s, 520, 230, 50, 0x80E0E0FFu);
    /* A fan of four triangles, the other winding, and the other quad. */
    gp8(s, 0xA0);
    gp16(s, 6);
    vertex(s, 575, 300, 50, 0xE0E080FFu); vertex(s, 520, 260, 50, 0xE0E080FFu); vertex(s, 520, 345, 50, 0xE0E080FFu);
    vertex(s, 575, 350, 50, 0xE0E080FFu); vertex(s, 630, 340, 50, 0xE0E080FFu); vertex(s, 630, 255, 50, 0xE0E080FFu);
    gp8(s, 0x80);
    gp16(s, 4);
    vertex(s, 520, 370, 50, 0xE080E0FFu); vertex(s, 520, 470, 50, 0xE080E0FFu);
    vertex(s, 630, 470, 50, 0xE080E0FFu); vertex(s, 630, 370, 50, 0xE080E0FFu);
    bp_w(s, 0x00, 0x10u);
    snprintf(name, sizeof name, "cull%u", m);
    return finish_scene(s, name);
}

/* ---- clipping ----------------------------------------------------------- */

/* The upload check: each draw's vertices as gxv uploaded them, against this
 * file's own walk of the draw (triangle lists only, which is all the clip
 * scenes draw) through the renderer's clip_polygon. Only the fields
 * lerp_vertex writes are compared: sx, sy and depth are to_screen's, and a
 * vertex clip_polygon makes leaves them as its scratch array had them. */
static int g_clip_on;
static unsigned g_clip_draws, g_clip_rebuilt, g_clip_bad, g_clip_verts;

static int same_vertex(const Vertex* a, const Vertex* b)
{
    return !memcmp(&a->x, &b->x, 4 * sizeof(float)) && !memcmp(a->col, b->col, sizeof a->col) &&
           !memcmp(a->tex, b->tex, sizeof a->tex);
}

static void upload_hook(const DrawCmd* D, const Vertex* up, unsigned n, int rebuilt)
{
    static Vertex want[4096];
    unsigned m = 0, i, k;
    if (!g_clip_on) return;
    g_clip_draws++;
    g_clip_rebuilt += rebuilt != 0;
    g_clip_verts += n;
    if (D->prim != 0x90) { fprintf(stderr, "[gpuspike] clip scene drew primitive %#x\n", D->prim); g_clip_bad++; return; }
    for (i = 0; i + 2 < D->count; i += 3) {
        const Vertex* t = &D->v[i];
        Vertex in[3], out[16];
        unsigned c;
        if (gxr_vertex_unclipped(&t[0]) && gxr_vertex_unclipped(&t[1]) && gxr_vertex_unclipped(&t[2])) {
            for (k = 0; k < 3 && m < 4096; k++) want[m++] = t[k];
            continue;
        }
        in[0] = t[0]; in[1] = t[1]; in[2] = t[2];
        c = gxr_clip_polygon(in, 3, out);
        for (k = 1; k + 1 < c && m + 3 <= 4096; k++) {
            want[m++] = out[0];
            want[m++] = out[k];
            want[m++] = out[k + 1];
        }
    }
    if (m != n) {
        fprintf(stderr, "[gpuspike] draw %u: uploaded %u vertices where clip_polygon's walk gives %u\n", g_clip_draws, n, m);
        g_clip_bad++;
        return;
    }
    for (i = 0; i < n; i++)
        if (!same_vertex(&up[i], &want[i])) {
            fprintf(stderr, "[gpuspike] draw %u: uploaded vertex %u differs from clip_polygon's\n", g_clip_draws, i);
            g_clip_bad++;
            return;
        }
}

/* The ortho recipe puts z_clip = -0.01 * z: the near plane (z_clip = -1) is
 * at z = 100 and the far plane (z_clip = 0) at z = 0, so a vertex at 150 is
 * past the near plane and one at -50 past the far. */
static const float g_ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
/* A perspective projection that draws z = 0 where the ortho one does (w =
 * 100 there), with near 10 and far 1000 in view space: view z = z - 100, so
 * the near plane is at z = 90, the eye at z = 100 and the far plane at -900.
 * GX's depth runs -w..0, so p4 = -n/(f-n) and p5 = -nf/(f-n). */
static const float g_persp[6] = {0.3125f, 0.0f, 0.41666667f, 0.0f, -0.01010101f, -10.10101f};

static void projection(CpuState* s, const float* p, int ortho)
{
    uint32_t type = ortho ? 1u : 0u;
    xf_f(s, 0x1020, 6, p);
    xf_w(s, 0x1026, 1, &type);
}

static int scene_clip(CpuState* s, const char* name, int ortho, const float* tris, unsigned ntri)
{
    static const uint32_t col[3] = {0xFF2020FFu, 0x20FF20FFu, 0x2020FFFFu};
    unsigned i;
    int bad;
    gxr_reset_efb();
    projection(s, ortho ? g_ortho : g_persp, ortho);
    g_clip_on = 1;
    g_clip_draws = g_clip_rebuilt = g_clip_bad = g_clip_verts = 0;
    gp8(s, 0x90);
    gp16(s, (unsigned)(3 * ntri));
    for (i = 0; i < ntri; i++) tri(s, tris + 9 * i, col[0], col[1], col[2]);
    bad = finish_scene(s, name);
    g_clip_on = 0;
    projection(s, g_ortho, 1);
    if (g_gpu) {
        int ok = g_clip_draws > 0 && g_clip_rebuilt > 0 && !g_clip_bad;
        printf("clip %s draws %u rebuilt %u uploaded %u mismatched %u %s\n", name, g_clip_draws, g_clip_rebuilt,
               g_clip_verts, g_clip_bad, ok ? "ok" : "FAIL");
        bad |= !ok;
    }
    return bad;
}

static int clip_scenes(CpuState* s)
{
    /* Ortho, w = 1: the near plane cuts one triangle to a quad (one vertex
     * out) and another to a triangle (two out); the far plane the same. */
    static const float near_o[] = {40, 40, 50, 300, 60, 50, 150, 400, 150, 340, 40, 150, 600, 60, 150, 450, 400, 50};
    static const float far_o[] = {40, 40, 50, 300, 60, 50, 150, 400, -50, 340, 40, -50, 600, 60, -50, 450, 400, 50};
    /* Perspective: one vertex between the eye and the near plane, one behind
     * the eye (which the W plane cuts as well), and one past the far plane,
     * near the centre so their projections stay on the screen. */
    static const float near_p[] = {60, 60, 0, 280, 80, 0, 315, 250, 95, 360, 60, 0, 600, 90, 0, 330, 260, 150};
    static const float far_p[] = {60, 60, 0, 280, 80, 0, 300, 230, -1100, 360, 400, 0, 600, 420, 0, 330, 250, -1100};
    int bad = 0;
    bad |= scene_clip(s, "clip_near_ortho", 1, near_o, 2);
    bad |= scene_clip(s, "clip_far_ortho", 1, far_o, 2);
    bad |= scene_clip(s, "clip_near_persp", 0, near_p, 2);
    bad |= scene_clip(s, "clip_far_persp", 0, far_p, 2);
    return bad;
}

/* ---- depth --------------------------------------------------------------- */

static void quad(CpuState* s, float x0, float y0, float x1, float y1, float z, uint32_t c)
{
    gp8(s, 0x80);
    gp16(s, 4);
    vertex(s, x0, y0, z, c); vertex(s, x1, y0, z, c); vertex(s, x1, y1, z, c); vertex(s, x0, y1, z, c);
}

/* What the depth path must get exactly (3.4): in the recipe's ortho, depth
 * is about 1 - 0.01z, so a larger z is nearer.
 *  - A red quad at z 50, then a green triangle through it (z 20 to 80):
 *    the two must meet where the CPU has them meet.
 *  - The red quad again, blue, under EQUAL: every pixel of it still in front
 *    turns blue only if the second pipeline places it at exactly the depth
 *    the first stored (invariant positions, one quantisation).
 *  - A yellow quad on the far plane (z 0) under LESS, against the cleared
 *    0xFFFFFF: its depth 16777215/2^24 quantises to 16777214, which is less;
 *    unquantised it would equal what the clear stored, and not draw. */
static int scene_depth(CpuState* s)
{
    gxr_reset_efb();
    quad(s, 40, 40, 400, 300, 50, 0xFF2020FFu);
    gp8(s, 0x90);
    gp16(s, 3);
    vertex(s, 100, 100, 20, 0x20FF20FFu); vertex(s, 500, 150, 80, 0x20FF20FFu); vertex(s, 200, 420, 80, 0x20FF20FFu);
    bp_w(s, 0x40, 0x15); /* z on, EQUAL, update */
    quad(s, 40, 40, 400, 300, 50, 0x2020FFFFu);
    bp_w(s, 0x40, 0x13); /* LESS */
    quad(s, 450, 320, 620, 460, 0, 0xFFFF20FFu);
    bp_w(s, 0x40, 0x17); /* the recipe's LEQUAL */
    return finish_scene(s, "depth");
}

/* In perspective, a plane leaning away (w from 80 at the bottom to 200 at
 * the top) and a triangle facing the eye at w 140: they cross where their
 * screen depths are equal, row 240. The CPU interpolates screen depth
 * linearly in screen space, which is what the depth varying's noperspective
 * reproduces; interpolated with perspective correction, the line moves to row
 * 193. The triangle is level because its own depth then has no such error: a
 * first version leaned it the other way, both planes shifted alike, and the
 * line stayed on row 240 under that mutation. */
static int scene_depth_persp(CpuState* s)
{
    gxr_reset_efb();
    projection(s, g_persp, 0);
    gp8(s, 0x80);
    gp16(s, 4);
    vertex(s, 60, 60, -100, 0xC04040FFu); vertex(s, 580, 60, -100, 0xC04040FFu);
    vertex(s, 580, 420, 20, 0xC04040FFu); vertex(s, 60, 420, 20, 0xC04040FFu);
    gp8(s, 0x90);
    gp16(s, 3);
    vertex(s, 150, 60, -40, 0x40C0C0FFu); vertex(s, 490, 60, -40, 0x40C0C0FFu); vertex(s, 320, 420, -40, 0x40C0C0FFu);
    projection(s, g_ortho, 1);
    return finish_scene(s, "depth_persp");
}

/* The scissor (BP 0x20/0x21, less BP 0x59's offset of 342), a different
 * one for each of two full-screen quads, so it is per draw; then the
 * recipe's own. */
static void scissor(CpuState* s, unsigned x0, unsigned y0, unsigned x1, unsigned y1)
{
    bp_w(s, 0x20, ((x0 + 342u) << 12) | (y0 + 342u));
    bp_w(s, 0x21, ((x1 + 342u) << 12) | (y1 + 342u));
}

static int scene_scissor(CpuState* s)
{
    gxr_reset_efb();
    scissor(s, 100, 80, 539, 399);
    quad(s, 0, 0, 640, 480, 50, 0xFF8040FFu);
    scissor(s, 300, 200, 620, 470);
    quad(s, 0, 0, 640, 480, 60, 0x4080FFFFu);
    scissor(s, 0, 0, 639, 479);
    return finish_scene(s, "scissor");
}

/* A quad with four corner colours, not a rectangle: which diagonal it is
 * split along decides every colour inside, so draw_command's (0, 1, 2) and
 * (0, 2, 3) must be the GPU's too. Flat quads cannot show it. */
static int scene_quad_gradient(CpuState* s)
{
    gxr_reset_efb();
    gp8(s, 0x80);
    gp16(s, 4);
    vertex(s, 60, 60, 50, 0xFF0000FFu); vertex(s, 580, 90, 50, 0x00FF00FFu);
    vertex(s, 540, 420, 50, 0x0000FFFFu); vertex(s, 90, 380, 50, 0xFFFFFFFFu);
    return finish_scene(s, "quad_gradient");
}

/* V4a's invariance check: one strip in perspective, drawn twice with depth
 * LEQUAL and update -- first red through the vertex colour with no blend,
 * then a konst blue added to it (blend ONE, ONE), a different TEV and a
 * different pipeline. The second pass passes the depth test only where it
 * places every vertex exactly where the first did, so every red pixel must
 * turn magenta: as many as the first pass drew, above zero, none left red.
 * GXV_MUTATE_NOINVARIANT (--mutate noinvariant) asks whether this GPU needs
 * `invariant gl_Position` for that. */
static unsigned count_rgb(const uint8_t* screen, int w, int h, uint8_t r, uint8_t g, uint8_t b)
{
    unsigned n = 0;
    int x, y;
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            const uint8_t* p = screen + ((size_t)y * EFB_W + x) * 4;
            n += p[0] == r && p[1] == g && p[2] == b;
        }
    return n;
}

static void invariance_strip(CpuState* s)
{
    unsigned k;
    gp8(s, 0x98);
    gp16(s, 12);
    for (k = 0; k < 12; k++) {
        float x = 80.0f + 44.0f * (float)k, y = (k & 1) ? 380.0f : 110.0f, z = (k % 3 == 0) ? -60.0f : (k % 3 == 1 ? 10.0f : -25.0f);
        vertex(s, x, y, z, 0xFF0000FFu);
    }
}

static int scene_invariance(CpuState* s)
{
    const uint8_t* screen;
    int w = 0, h = 0;
    unsigned first, second, left;
    gxr_reset_efb();
    projection(s, g_persp, 0);
    invariance_strip(s);
    present(s);
    screen = gxr_screen(&w, &h);
    first = count_rgb(screen, w, h, 255, 0, 0);
    bp_w(s, 0xE0, 0x800000u | (0xFFu << 12)); /* konst 0: red 0, alpha 255 */
    bp_w(s, 0xE1, 0x800000u | 0xFFu);         /* konst 0: blue 255, green 0 */
    bp_w(s, 0xF6, 0x0180C4u);                 /* stage 0's konst colour: konst 0 (the recipe's swaps kept) */
    bp_w(s, 0xC0, 0x08FFFEu);                 /* stage 0 colour: the konst, clamped */
    bp_w(s, 0x41, 0x139u);                    /* blend ONE, ONE; colour and alpha written */
    invariance_strip(s);
    bp_w(s, 0x41, 0x18u);
    bp_w(s, 0xC0, 0x08AFFFu);
    bp_w(s, 0xF6, 0x018064u);
    projection(s, g_ortho, 1);
    if (finish_scene(s, "invariance")) return 1;
    screen = gxr_screen(&w, &h);
    second = count_rgb(screen, w, h, 255, 0, 255);
    left = count_rgb(screen, w, h, 255, 0, 0);
    printf("invariance first %u second %u left red %u %s\n", first, second, left,
           first > 0 && first == second && left == 0 ? "ok" : "FAIL");
    return !(first > 0 && first == second && left == 0);
}

/* Logic ops as the mask effect draws them (FINDINGS "V4"): a quad of a known
 * colour, then OR (255, 0, 0), AND (0, 255, 255) and OR (128, 0, 0), each a
 * quad over part of the last, through PE_CMODE0's logic op with blending off.
 * Every gxv mode (--logicop) must draw what blend_pixel does. */
static int scene_logic(CpuState* s)
{
    gxr_reset_efb();
    quad(s, 40, 40, 600, 440, 50, 0xFF6E77FFu);
    bp_w(s, 0x41, 0x701Au); /* logic OR, colour and alpha written */
    quad(s, 80, 60, 560, 300, 50, 0xFF0000FFu);
    bp_w(s, 0x41, 0x101Au); /* logic AND */
    quad(s, 120, 100, 520, 400, 50, 0x00FFFFFFu);
    bp_w(s, 0x41, 0x701Au); /* logic OR */
    quad(s, 160, 140, 480, 420, 50, 0x800000FFu);
    bp_w(s, 0x41, 0x18u);
    return finish_scene(s, "logic");
}

/* A copy's clear (its own command with a backend, kind 2): a grey quad at z
 * 50, then a screen copy of a 300x200 rectangle with the clear bit, clearing
 * it to (0x30, 0x60, 0x90) and depth 0x400000 (a quarter: nearer than the
 * quad). An orange quad at z 60 then draws everywhere but the cleared
 * rectangle, which is nearer than it; a white one at z 90 draws over both.
 * The registers go back to zero after, because gxr_reset_efb reads them. */
static int scene_clear(CpuState* s)
{
    gxr_reset_efb();
    quad(s, 20, 20, 620, 460, 50, 0x808080FFu);
    bp_w(s, 0x4F, 0x8030); /* alpha 0x80, red 0x30 */
    bp_w(s, 0x50, 0x6090); /* green 0x60, blue 0x90 */
    bp_w(s, 0x51, 0x400000);
    bp_w(s, 0x49, (80u << 10) | 100u);
    bp_w(s, 0x4A, (199u << 10) | 299u);
    bp_w(s, 0x52, 0x4803); /* to the screen, clamped, and clear */
    quad(s, 50, 50, 600, 400, 60, 0xFF8020FFu);
    quad(s, 300, 150, 500, 440, 90, 0xFFFFFFFFu);
    bp_w(s, 0x4F, 0);
    bp_w(s, 0x50, 0);
    bp_w(s, 0x51, 0);
    return finish_scene(s, "clear");
}

/* ---- lines and points ---------------------------------------------------- */

static int scene_lines(CpuState* s)
{
    static const float seg[][4] = {
        {20.25f, 30.5f, 300.75f, 30.5f},    /* horizontal */
        {40.5f, 60.25f, 40.5f, 300.75f},    /* vertical */
        {80.3f, 60.3f, 300.3f, 280.3f},     /* 45 degrees */
        {100.6f, 320.2f, 600.4f, 380.7f},   /* shallow */
        {400.2f, 20.6f, 460.7f, 300.1f},    /* steep */
        {620.4f, 460.6f, 330.3f, 400.2f},   /* right to left, up */
    };
    unsigned i;
    gxr_reset_efb();
    gp8(s, 0xA8);
    gp16(s, (unsigned)(2 * (sizeof seg / sizeof seg[0])));
    for (i = 0; i < sizeof seg / sizeof seg[0]; i++) {
        vertex(s, seg[i][0], seg[i][1], 50, 0xFFC040FFu);
        vertex(s, seg[i][2], seg[i][3], 50, 0xFFC040FFu);
    }
    gp8(s, 0xB0);
    gp16(s, 4);
    vertex(s, 480.4f, 40.6f, 50, 0x40C0FFFFu); vertex(s, 600.2f, 90.3f, 50, 0x40C0FFFFu);
    vertex(s, 520.7f, 200.4f, 50, 0x40C0FFFFu); vertex(s, 630.1f, 250.8f, 50, 0x40C0FFFFu);
    /* In perspective: one segment in front of the eye, and one from there to
     * behind it (w -50), which draw_command skips whole and the GPU's own
     * clipper would cut and draw toward the screen's edge. */
    projection(s, g_persp, 0);
    gp8(s, 0xA8);
    gp16(s, 4);
    vertex(s, 60.3f, 420.6f, 0, 0xC0FF40FFu); vertex(s, 300.7f, 470.2f, 0, 0xC0FF40FFu);
    vertex(s, 100.4f, 400.6f, 0, 0xFF40C0FFu); vertex(s, 200.2f, 300.3f, 150, 0xFF40C0FFu);
    projection(s, g_ortho, 1);
    return finish_scene(s, "lines");
}

/* Points, each a pixel's fraction 0.2 to 0.8 from its edges in x and y:
 * there floor() and a one-pixel point's coverage agree by definition. On an
 * edge they need not -- a point at x = 554.0 exactly lit 554 on the CPU and
 * 553 on the GPU, where Vulkan leaves the choice to the implementation -- and
 * the projection moves positions by a few hundredths of a pixel. */
static int scene_points(CpuState* s)
{
    static const float frac[5] = {0.2f, 0.35f, 0.5f, 0.65f, 0.8f};
    unsigned i;
    gxr_reset_efb();
    gp8(s, 0xB8);
    gp16(s, 64);
    for (i = 0; i < 64; i++)
        vertex(s, 10.0f + 9.0f * (float)i + frac[i % 5], 20.0f + 7.0f * (float)i + frac[(i + 2) % 5], 50, 0x40FF80FFu);
    return finish_scene(s, "points");
}

/* ---- V3b: the two exact differentials ------------------------------------- */

/* splitmix64: the same sequence in both processes, from --seed and the case.
 * A first version seeded xorshift32 with the case number almost as it was,
 * and xorshift is linear: neighbouring cases came out correlated, and the
 * alpha logic's four values each took exactly 25,000 of 100,000 cases. */
static uint64_t g_rng;

static uint32_t rnd(void)
{
    uint64_t z = (g_rng += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return (uint32_t)((z ^ (z >> 31)) >> 32);
}

static void seed_rng(uint32_t seed, uint32_t salt)
{
    g_rng = (uint64_t)seed << 32 | salt;
}

static uint64_t fnv(uint64_t h, const uint8_t* p, size_t n)
{
    while (n--) {
        h ^= *p++;
        h *= 1099511628211ULL;
    }
    return h;
}
#define FNV0 14695981039346656037ULL

/* tevdiff: random register sets through tev_prepare, each run by tev_pixel
 * twice -- as prepared, and with its fast shape turned off -- and by
 * tev.glsl once, through the same packed setup. The registers are those
 * the spec names (C0-DF, E0-E7, F3, F6-FD, GEN_MODE) and the texture orders
 * 0x28-0x2F, without which every stage would sample map 0 with texturing
 * off. One case in eight is built as one of H15c's fast shapes, which random
 * words almost never make. Every map is a 1x1 nearest texture, so a stage
 * samples the case's texel for that map wherever it looks. */
enum {
    H_CCMP = 0,         /* 8: colour compare modes, (cshift << 1) | cop, where cbias is 3 */
    H_ACMP = 8,         /* 8: alpha compare modes */
    H_CSHIFT = 16,      /* 4 */
    H_ASHIFT = 20,      /* 4 */
    H_CCLAMP = 24,      /* 2 */
    H_ACLAMP = 26,      /* 2 */
    H_CBIAS = 28,       /* 3 */
    H_ABIAS = 31,       /* 3 */
    H_COP = 34,         /* 2 */
    H_AOP = 36,         /* 2 */
    H_ALOGIC = 38,      /* 4: per case */
    H_ACOMP = 42,       /* 8: acomp0, per case */
    H_TEXEN = 50,       /* 2 */
    H_CHAN = 52,        /* 2: a raster colour, or none */
    H_FASTC = 54,       /* 3: fast_c 0, 1, 2, per case */
    H_FASTA = 57,       /* 4: fast_a 0-3, per case */
    H_N = 61
};
static const char* const g_hit_name[H_N] = {
    "ccmp0", "ccmp1", "ccmp2", "ccmp3", "ccmp4", "ccmp5", "ccmp6", "ccmp7",
    "acmp0", "acmp1", "acmp2", "acmp3", "acmp4", "acmp5", "acmp6", "acmp7",
    "cshift0", "cshift1", "cshift2", "cshift3", "ashift0", "ashift1", "ashift2", "ashift3",
    "cclamp0", "cclamp1", "aclamp0", "aclamp1", "cbias0", "cbias1", "cbias2", "abias0", "abias1", "abias2",
    "cop0", "cop1", "aop0", "aop1", "alogic0", "alogic1", "alogic2", "alogic3",
    "acomp0", "acomp1", "acomp2", "acomp3", "acomp4", "acomp5", "acomp6", "acomp7",
    "texen0", "texen1", "ras", "noras", "fastc0", "fastc1", "fastc2", "fasta0", "fasta1", "fasta2", "fasta3"};

/* A fast shape's registers: one stage, identity swaps, colour channel 0. */
static void fast_shape(uint32_t* bp)
{
    static const uint32_t color[4] = {0x08AFFFu, 0x08FFFAu, 0x08F8AFu, 0x18F8AFu};  /* RASC, RASC as d, TEXC*RASC, doubled */
    static const uint32_t alpha[4] = {0x08DFF0u, 0x08BFF0u, 0x08FFD0u, 0x08F2F0u};  /* KONST, RASA, RASA as d, TEXA*RASA */
    unsigned c = rnd() & 3, a = rnd() & 3, k;
    bp[0] = 0; /* one stage */
    bp[0xC0] = color[c];
    bp[0xC1] = alpha[a];
    for (k = 0; k < 8; k++) bp[0xF6 + k] = (rnd() & 0xFFFFF0u) | ((k & 1) ? 0xEu : 0x4u);
    bp[0x28] = (rnd() & 0x3Fu) | ((c >= 2 || a == 3) ? 0x40u : 0u); /* map, coord; texturing when sampled; channel 0 */
}

static int tevdiff(CpuState* s, unsigned n, uint32_t seed)
{
    uint32_t* setups = (uint32_t*)calloc((size_t)n, GXV_TEV_WORDS * 4);
    uint32_t* inputs = (uint32_t*)calloc((size_t)n, 40);
    uint32_t* results = (uint32_t*)calloc((size_t)n, 8);
    uint32_t* cpu = (uint32_t*)calloc((size_t)n, 16);
    uint8_t texel[8][4];
    unsigned long long hits[H_N];
    unsigned i, k, st, bad = 0, low = 0, shown = 0;
    if (!setups || !inputs || !results || !cpu) { fprintf(stderr, "[tevdiff] out of memory\n"); return 1; }
    memset(hits, 0, sizeof hits);
    tex_set_memory(s);
    for (i = 0; i < n; i++) {
        uint32_t bp[256];
        TevSetup T;
        int ras[2][4], pass;
        float tc[8][4];
        uint8_t out[4];
        seed_rng(seed, i);
        memset(bp, 0, sizeof bp);
        bp[0] = rnd() & 0xFFFFFFu;
        for (k = 0xC0; k <= 0xDF; k++) bp[k] = rnd() & 0xFFFFFFu;
        for (k = 0x28; k <= 0x2F; k++) bp[k] = rnd() & 0xFFFFFFu;
        for (k = 0xF6; k <= 0xFD; k++) bp[k] = rnd() & 0xFFFFFFu;
        bp[0xF3] = rnd() & 0xFFFFFFu;
        for (k = 0xE0; k <= 0xE7; k++) {
            tev_register_written(k, rnd() & 0x7FFFFFu);           /* a colour register */
            tev_register_written(k, (rnd() & 0x7FFFFFu) | 0x800000u); /* a konst */
        }
        if (rnd() % 8 == 0) fast_shape(bp);
        tev_prepare(bp, &T);
        for (k = 0; k < 8; k++) {
            TexCfg* C = &T.tex[k];
            uint32_t t = rnd();
            memcpy(texel[k], &t, 4);
            memset(C, 0, sizeof *C);
            C->level[0] = texel[k];
            C->lw[0] = C->lh[0] = 1;
            C->nlevels = 1;
            C->w = C->h = 1;
            C->scale_s = C->scale_t = 1.0f;
            C->su0 = C->sv0 = 1.0f;
            tc[k][0] = 0.25f + 0.5f * (float)(rnd() & 1);
            tc[k][1] = 0.25f;
            tc[k][2] = 1.0f;
            tc[k][3] = 0.0f;
        }
        for (k = 0; k < 8; k++) ras[k / 4][k % 4] = (int)(rnd() & 255);
        tev_pixel(&T, (const int (*)[4])ras, (const float (*)[4])tc, out, &pass);
        memcpy(&cpu[i * 4], out, 4);
        cpu[i * 4 + 1] = (uint32_t)pass;
        hits[H_FASTC + T.fast_c]++;
        hits[H_FASTA + T.fast_a]++;
        T.fast_c = T.fast_a = 0;
        tev_pixel(&T, (const int (*)[4])ras, (const float (*)[4])tc, out, &pass);
        memcpy(&cpu[i * 4 + 2], out, 4);
        cpu[i * 4 + 3] = (uint32_t)pass;
        gxv_pack_tev(&T, setups + (size_t)i * GXV_TEV_WORDS);
        for (k = 0; k < 2; k++)
            inputs[i * 10 + k] = (uint32_t)ras[k][0] | (uint32_t)ras[k][1] << 8 | (uint32_t)ras[k][2] << 16 | (uint32_t)ras[k][3] << 24;
        for (k = 0; k < 8; k++) memcpy(&inputs[i * 10 + 2 + k], texel[k], 4);
        hits[H_ALOGIC + T.alogic]++;
        hits[H_ACOMP + T.acomp0]++;
        for (st = 0; st < T.stages; st++) {
            const Stage* S = &T.st[st];
            if (S->cbias == 3) hits[H_CCMP + ((S->cshift << 1) | S->cop)]++;
            else { hits[H_CSHIFT + S->cshift]++; hits[H_CBIAS + S->cbias]++; hits[H_COP + S->cop]++; }
            if (S->abias == 3) hits[H_ACMP + ((S->ashift << 1) | S->aop)]++;
            else { hits[H_ASHIFT + S->ashift]++; hits[H_ABIAS + S->abias]++; hits[H_AOP + S->aop]++; }
            hits[H_CCLAMP + S->cclamp]++;
            hits[H_ACLAMP + S->aclamp]++;
            hits[H_TEXEN + S->texen]++;
            hits[H_CHAN + (S->chan < 2 ? 0 : 1)]++;
        }
    }
    if (!gxv_tev_run(setups, inputs, results, n)) return 1;
    for (i = 0; i < n; i++) {
        uint32_t g = results[i * 2], gp = results[i * 2 + 1];
        int a = g != cpu[i * 4] || gp != cpu[i * 4 + 1], b = g != cpu[i * 4 + 2] || gp != cpu[i * 4 + 3];
        if (!a && !b) continue;
        bad++;
        if (shown++ < 8)
            printf("mismatch case %u: gpu %08x pass %u; tev_pixel as prepared %08x pass %u, general %08x pass %u\n", i, g, gp,
                   cpu[i * 4], cpu[i * 4 + 1], cpu[i * 4 + 2], cpu[i * 4 + 3]);
    }
    printf("hits");
    for (k = 0; k < H_N; k++) {
        printf(" %s=%llu", g_hit_name[k], hits[k]);
        if (hits[k] < 100) low++;
    }
    printf("\n");
    /* fast_c 0 with fast_a 0 is the general path; the two fast counts that
     * matter are the shapes, which the one-in-eight cases make. */
    printf("tevdiff %u cases, seed %u: %u mismatch%s; %u path%s under 100 hits\n", n, seed, bad, bad == 1 ? "" : "es", low,
           low == 1 ? "" : "s");
    free(setups);
    free(inputs);
    free(results);
    free(cpu);
    return bad || low;
}

/* ---- V6a's queue frame ------------------------------------------------------
 *
 * test_gxv_queue.py's stream (specs/gpu-backend.md V6a), one frame through the
 * real parser and producer and whichever backend: 64 quads 32 pixels square,
 * each drawn after the one 8x4 I8 texture's bytes were rewritten and the game's
 * invalidate sent -- one cache slot, a new generation each, all 64 recorded in
 * one GPU submission -- then 164 draws of 1,000 one-pixel quads, 656,000
 * vertices, which fill the producer's 48 MB vertex arena twice (a draw is
 * kept under the parser's 64 KB pipe buffer, as the game's are). Each
 * textured quad's centre must be its own texture's value. The recipe is
 * tools/tests/test_gxr_backend.py's. */
#define QUEUE_TEX 0x00100000u

static void queue_recipe(CpuState* s, int textured)
{
    static const float viewport[6] = {320.0f, -240.0f, 16777215.0f, 662.0f, 582.0f, 16777215.0f};
    static const float ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
    static const float view[12] = {1, 0, 0, -320, 0, -1, 0, 240, 0, 0, 1, -100};
    static const float ident[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
    static const uint32_t one = 1, matidx = 0x3CF3CF00u, chan = 0x441u, zero = 0, texgen = 5u << 7;
    bp_w(s, 0x59, 0x02ACABu); bp_w(s, 0x20, 0x156156u); bp_w(s, 0x21, 0x3D5335u);
    xf_f(s, 0x101A, 6, viewport);
    xf_f(s, 0x1020, 6, ortho); xf_w(s, 0x1026, 1, &one);
    xf_f(s, 0x0000, 12, view);
    cp_w(s, 0x30, matidx); xf_w(s, 0x1018, 1, &matidx);
    xf_w(s, 0x1009, 1, &one); xf_w(s, 0x100E, 1, &chan); xf_w(s, 0x1010, 1, &chan);
    xf_w(s, 0x1008, 1, &one);
    bp_w(s, 0xC1, 0x08BFF0u); bp_w(s, 0x00, textured ? 0x11 : 0x10);
    bp_w(s, 0xF6, 0x018064u); bp_w(s, 0xF7, 0x01806Eu); bp_w(s, 0xF8, 0x018060u); bp_w(s, 0xF9, 0x01806Cu);
    bp_w(s, 0xFA, 0x018065u); bp_w(s, 0xFB, 0x01806Du); bp_w(s, 0xFC, 0x01806Au); bp_w(s, 0xFD, 0x01806Eu);
    bp_w(s, 0x40, 0x17); bp_w(s, 0x41, 0x18); bp_w(s, 0xF3, 0x3F0000u); bp_w(s, 0x43, 0x40);
    cp_w(s, 0x50, 0x2200); cp_w(s, 0x70, 0x41377009u); cp_w(s, 0x80, 0xC8241209u); cp_w(s, 0x90, 0x04824120u);
    if (textured) {
        cp_w(s, 0x60, 1);
        xf_w(s, 0x103F, 1, &one); xf_w(s, 0x1040, 1, &texgen); xf_f(s, 4 * 60, 12, ident);
        bp_w(s, 0x28, 0x40); bp_w(s, 0xC0, 0x08F8AFu);
        bp_w(s, 0x30, 7); bp_w(s, 0x31, 3); bp_w(s, 0x80, 0); bp_w(s, 0x84, 0);
        bp_w(s, 0x88, 0x100C07u); bp_w(s, 0x94, QUEUE_TEX >> 5);
    } else {
        cp_w(s, 0x60, 0); xf_w(s, 0x103F, 1, &zero);
        bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu);
    }
}

static int scene_queue(CpuState* s)
{
    char path[512];
    const uint8_t* screen;
    int w = 0, h = 0, k, d, q, right = 0;
    gxr_reset_efb();
    queue_recipe(s, 1);
    for (k = 0; k < 64; k++) {
        static const float corner[4][2] = {{0, 0}, {32, 0}, {32, 32}, {0, 32}};
        float x0 = (float)(k % 8 * 32), y0 = (float)(k / 8 * 32);
        int i;
        memset(s->mem + QUEUE_TEX, k * 4 + 3, 32);
        bp_w(s, 0x66, 0); /* the game's texture invalidate: hashed again at its next use */
        gp8(s, 0x80); gp16(s, 4);
        for (i = 0; i < 4; i++) {
            gpf(s, x0 + corner[i][0]); gpf(s, y0 + corner[i][1]); gpf(s, 50); gp32(s, 0xFFFFFFFFu);
            gpf(s, corner[i][0] / 32.0f); gpf(s, corner[i][1] / 32.0f);
        }
    }
    queue_recipe(s, 0);
    for (d = 0; d < 164; d++) {
        gp8(s, 0x80); gp16(s, 1000 * 4);
        for (q = 0; q < 1000; q++) {
            unsigned n = (unsigned)(d * 1000 + q);
            float x = 256.0f + (float)(n % 384), y = (float)(n / 384);
            uint32_t c = (n * 2654435761u) | 0xFFu;
            vertex(s, x, y, 50, c); vertex(s, x + 1, y, 50, c); vertex(s, x + 1, y + 1, 50, c); vertex(s, x, y + 1, 50, c);
        }
    }
    present(s);
    screen = gxr_screen(&w, &h);
    for (k = 0; k < 64; k++) {
        const uint8_t* p = screen + ((size_t)(k / 8 * 32 + 16) * EFB_W + (size_t)(k % 8 * 32 + 16)) * 4;
        int v = k * 4 + 3;
        if (p[0] == v && p[1] == v && p[2] == v) right++;
    }
    snprintf(path, sizeof path, "%s/queue.png", g_out);
    if (!png_write_rgba(path, screen, w, h, EFB_W * 4)) {
        fprintf(stderr, "[gpuspike] cannot write %s\n", path);
        return 1;
    }
    printf("queue textured quads right %d of 64; frame hash %016llx\n", right, (unsigned long long)gxr_screen_hash());
    gxr_report();
    return right != 64;
}

/* ---- V7's copy image ----------------------------------------------------
 *
 * test_gxv_copyimage.py's frame (specs/gpu-backend.md V7): sixteen quads of
 * sixteen colours drawn into the EFB's top-left 64x64, copied to an RGBA8
 * texture, and a 64x64 quad at (128, 128) sampling that texture, nearest and
 * one texel a pixel, in the same frame. The GPU samples the image the copy
 * wrote into its texel pool, the CPU the copy image its workers decode as
 * they copy (FINDINGS "Copy images"). Each of the quad's sixteen cells must
 * be the colour its source cell was drawn in. */
#define COPY_TEX 0x00200000u

static int scene_copyimage(CpuState* s)
{
    static const float corner[4][2] = {{0, 0}, {64, 0}, {64, 64}, {0, 64}};
    char path[512];
    const uint8_t* screen;
    int w = 0, h = 0, k, i, right = 0;
    gxr_reset_efb();
    queue_recipe(s, 0);
    for (k = 0; k < 16; k++) {
        float x = (float)(k % 4 * 16), y = (float)(k / 4 * 16);
        uint32_t c = (uint32_t)(k * 16 + 8) << 24 | (uint32_t)(255 - k * 16) << 16 | (uint32_t)(k * 37 & 255) << 8 | 0xFFu;
        gp8(s, 0x80); gp16(s, 4);
        vertex(s, x, y, 50, c); vertex(s, x + 16, y, 50, c); vertex(s, x + 16, y + 16, 50, c); vertex(s, x, y + 16, 50, c);
    }
    /* The copy: (0, 0), 64x64, to an RGBA8 texture at COPY_TEX, no clear. */
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, 63u << 10 | 63u); bp_w(s, 0x4D, 0); bp_w(s, 0x4B, COPY_TEX >> 5);
    bp_w(s, 0x52, 12u << 3 | 3u);
    queue_recipe(s, 1);
    bp_w(s, 0x88, 63u | 63u << 10 | 6u << 20); bp_w(s, 0x94, COPY_TEX >> 5);
    bp_w(s, 0x30, 63); bp_w(s, 0x31, 63); /* the coordinates' scale: 64 texels each way */
    gp8(s, 0x80); gp16(s, 4);
    for (i = 0; i < 4; i++) {
        gpf(s, 128 + corner[i][0]); gpf(s, 128 + corner[i][1]); gpf(s, 50); gp32(s, 0xFFFFFFFFu);
        gpf(s, corner[i][0] / 64.0f); gpf(s, corner[i][1] / 64.0f);
    }
    present(s);
    screen = gxr_screen(&w, &h);
    for (k = 0; k < 16; k++) {
        size_t sx = (size_t)(k % 4 * 16 + 8), sy = (size_t)(k / 4 * 16 + 8);
        const uint8_t* a = screen + (sy * EFB_W + sx) * 4;
        const uint8_t* b = screen + ((sy + 128) * EFB_W + sx + 128) * 4;
        if (a[0] == b[0] && a[1] == b[1] && a[2] == b[2]) right++;
    }
    snprintf(path, sizeof path, "%s/copyimage.png", g_out);
    if (!png_write_rgba(path, screen, w, h, EFB_W * 4)) {
        fprintf(stderr, "[gpuspike] cannot write %s\n", path);
        return 1;
    }
    printf("copyimage cells right %d of 16; frame hash %016llx\n", right, (unsigned long long)gxr_screen_hash());
    gxr_report();
    return right != 16;
}

/* ---- V10's logic ops --------------------------------------------------------
 *
 * test_gxv_logicop.py's scenes (specs/gpu-backend.md V10), depth off:
 *   1  a quad of 0x55 ORed into a quad of 0xAA: 0xFF where the op is done
 *      exactly, 198 from the blend approximation (src(1 - dst) + dst);
 *   2  two triangles of 0xF0, overlapping, XORed onto black: each fragment
 *      must see the one before it, so the overlap comes back black. A route
 *      that reads a snapshot taken before the draw leaves it 0xF0.
 * PE_CMODE0 (BP 0x41): colour and alpha update 0x18, logic enable 2, the op
 * at bit 12. */
static int scene_logictest(CpuState* s, int which)
{
    char path[512];
    const uint8_t* screen;
    int w = 0, h = 0;
    gxr_reset_efb();
    queue_recipe(s, 0);
    bp_w(s, 0x40, 0); /* no depth test: the interlock route takes no depth */
    if (which == 1) {
        gp8(s, 0x80); gp16(s, 4);
        vertex(s, 0, 0, 50, 0xAAAAAAFFu); vertex(s, 640, 0, 50, 0xAAAAAAFFu);
        vertex(s, 640, 480, 50, 0xAAAAAAFFu); vertex(s, 0, 480, 50, 0xAAAAAAFFu);
        bp_w(s, 0x41, 0x18u | 2u | 7u << 12); /* OR */
        gp8(s, 0x80); gp16(s, 4);
        vertex(s, 220, 140, 50, 0x555555FFu); vertex(s, 420, 140, 50, 0x555555FFu);
        vertex(s, 420, 340, 50, 0x555555FFu); vertex(s, 220, 340, 50, 0x555555FFu);
    } else {
        bp_w(s, 0x41, 0x18u | 2u | 6u << 12); /* XOR */
        gp8(s, 0x90); gp16(s, 6);
        vertex(s, 100, 100, 50, 0xF0F0F0FFu); vertex(s, 400, 100, 50, 0xF0F0F0FFu); vertex(s, 100, 400, 50, 0xF0F0F0FFu);
        vertex(s, 160, 160, 50, 0xF0F0F0FFu); vertex(s, 460, 160, 50, 0xF0F0F0FFu); vertex(s, 160, 460, 50, 0xF0F0F0FFu);
    }
    bp_w(s, 0x41, 0x18);
    present(s);
    screen = gxr_screen(&w, &h);
    snprintf(path, sizeof path, "%s/logic%d.png", g_out, which);
    if (!png_write_rgba(path, screen, w, h, EFB_W * 4)) {
        fprintf(stderr, "[gpuspike] cannot write %s\n", path);
        return 1;
    }
    if (which == 1) {
        const uint8_t* c = screen + ((size_t)240 * EFB_W + 320) * 4;
        printf("logictest or: centre %u %u %u; frame hash %016llx\n", c[0], c[1], c[2], (unsigned long long)gxr_screen_hash());
    } else {
        const uint8_t* o = screen + ((size_t)200 * EFB_W + 200) * 4; /* both triangles */
        const uint8_t* a = screen + ((size_t)120 * EFB_W + 120) * 4; /* the first alone */
        printf("logictest xor: overlap %u, first alone %u; frame hash %016llx\n", o[0], a[0],
               (unsigned long long)gxr_screen_hash());
    }
    gxr_report();
    return 0;
}

/* ---- V8's presenter ----------------------------------------------------------
 *
 * test_gxv_present.py's check (specs/gpu-backend.md V8): two synthetic screen
 * copies, 640x480 and 640x448, every pixel its own colour, through the
 * presenter's pass into targets of eight sizes -- the window at 1x to 4x, a
 * 16:9 and a 21:9 client, odd sizes and one smaller than the picture -- at
 * both layouts, against picture_scale on the same image (runtime/picture.c,
 * what the CPU presenter draws). Every pixel's colour must be the CPU's: the
 * scaler is nearest neighbour by integer arithmetic, so there is nothing to
 * round. Alpha is not compared: the black bars are opaque on the GPU and
 * zero on the CPU, and the swap chain ignores alpha.
 *
 * With SOA_GPU_SCALE at 2 or 3 (V9a), each copy is drawn at that scale,
 * (k*w) x (k*h), and the reference is picture_scale_area: the presenter's
 * averaging where the picture shrinks, by the same integer arithmetic. */
static int present_check(void)
{
    static const int targets[][2] = {{640, 480}, {1280, 960}, {2560, 1440}, {1920, 1080}, {1000, 700},
                                     {641, 481}, {300, 200}, {1024, 1600}};
    static const int sources[][2] = {{640, 480}, {640, 448}};
    int k = gxv_scale();
    size_t most = 640u * 480u * 4u * (size_t)(k * k);
    uint8_t* src = (uint8_t*)malloc(most);
    uint8_t* bgra = (uint8_t*)malloc(most);
    uint8_t* ref = (uint8_t*)malloc(2560u * 1600u * 4u);
    uint8_t* got = (uint8_t*)malloc(2560u * 1600u * 4u);
    unsigned si, ti, mode, i, exact = 0, total = 0, shown = 0;
    if (!src || !bgra || !ref || !got) return 1;
    for (si = 0; si < 2; si++) {
        int w = sources[si][0], h = sources[si][1];
        for (i = 0; i < (unsigned)(w * h * k * k); i++) {
            uint32_t v = i * 2654435761u ^ (si * 0x9E3779B9u);
            src[i * 4 + 0] = (uint8_t)v;
            src[i * 4 + 1] = (uint8_t)(v >> 8);
            src[i * 4 + 2] = (uint8_t)(v >> 16);
            src[i * 4 + 3] = 255;
            bgra[i * 4 + 0] = src[i * 4 + 2];
            bgra[i * 4 + 1] = src[i * 4 + 1];
            bgra[i * 4 + 2] = src[i * 4 + 0];
            bgra[i * 4 + 3] = 255;
        }
        for (ti = 0; ti < sizeof targets / sizeof targets[0]; ti++)
            for (mode = 0; mode < 2; mode++) {
                int dw = targets[ti][0], dh = targets[ti][1];
                unsigned bad = 0, px;
                PicRect r = picture_layout(w, h, dw, dh, (int)mode);
                total++;
                if (!gxv_present_check(bgra, w, h, k, dw, dh, (int)mode, got)) {
                    printf("present %dx%d into %dx%d (%s): the check could not run\n", w, h, dw, dh, mode ? "fit" : "integer");
                    continue;
                }
                if (k > 1) picture_scale_area(bgra, w, h, k, ref, dw, dh, (int)mode);
                else picture_scale(bgra, w, h, ref, dw, dh, (int)mode);
                for (px = 0; px < (unsigned)(dw * dh); px++)
                    if (memcmp(got + px * 4, ref + px * 4, 3)) bad++;
                if (!bad) exact++;
                else if (shown++ < 8)
                    printf("present %dx%d into %dx%d (%s, rect %d,%d %dx%d): %u pixels differ\n", w, h, dw, dh,
                           mode ? "fit" : "integer", r.x, r.y, r.w, r.h, bad);
            }
    }
    printf("present %u of %u layouts exact, at scale %d\n", exact, total, k);
    free(src);
    free(bgra);
    free(ref);
    free(got);
    return exact != total;
}

/* loddiff (V5): the level of detail, which V0 cannot hold to a level -- LOD
 * +1 passes it on three distinct frames (FINDINGS "V4"). Two kinds of case,
 * n of each:
 *
 * The level: a random level of detail, bias, clamps, level count, texture
 * size, scale and coordinate through tex_level (the sampler's own
 * SAMPLE_AT) and lod.glsl's gx_level and gx_level_uv, which must agree bit
 * for bit in the level and the scaled u and v. The registers' own ranges are
 * used (bias in 32nds, clamps in 16ths); one case in four puts the biased
 * level of detail within a few ULPs of a rounding boundary, and one in 64 is
 * a NaN, which span_lod returns for a degenerate triangle.
 *
 * The formula: random planes of 1/w, s/w, t/w and q/w and a pixel, through
 * span_lod (gxr_span_lod) and gx_lod given the derivatives of s and t worked
 * in double from the same planes. The derivatives themselves differ by
 * design (the GPU's come from a pixel quad, 3.4), so only the formula is
 * held, within LOD_TOL. A case whose float derivative cancels badly, or
 * whose footprint sits by span_lod's 1e-12 floor, is left out and counted. */
#define LOD_TOL (1.0 / 1024.0)
enum { L_LEVEL0, L_LEVELN, L_TOP, L_MIN, L_MAX, L_NAN, L_EDGE, L_NOMIP, L_NPOT, L_N };
static const char* const g_lod_hit[L_N] = {"level0", "level1+", "top", "min", "max", "nan", "boundary", "nomip", "npot"};

static float rnd_range(float lo, float hi) { return lo + (hi - lo) * (float)(rnd() >> 8) / 16777216.0f; }

static int loddiff(unsigned n, uint32_t seed)
{
    uint32_t* in = (uint32_t*)calloc((size_t)n, GXV_LOD_WORDS * 4);
    uint32_t* out = (uint32_t*)calloc((size_t)n, 12);
    uint32_t* cpu = (uint32_t*)calloc((size_t)n, 12);
    unsigned long long hits[L_N];
    unsigned i, k, bad = 0, shown = 0, low = 0, over = 0, left = 0, kept = 0;
    double worst = 0.0;
    if (!in || !out || !cpu) { fprintf(stderr, "[loddiff] out of memory\n"); return 1; }
    memset(hits, 0, sizeof hits);
    for (i = 0; i < n; i++) {
        uint32_t* w = in + (size_t)i * GXV_LOD_WORDS;
        TexCfg C;
        float lod, s, t, u, v;
        int l;
        seed_rng(seed, i);
        memset(&C, 0, sizeof C);
        C.w = rnd() % 8 == 0 ? (int)(1 + rnd() % 1024) : 1 << (rnd() % 11);
        C.h = rnd() % 8 == 0 ? (int)(1 + rnd() % 1024) : 1 << (rnd() % 11);
        C.mip = rnd() % 8 != 0;
        C.nlevels = C.mip ? (int)(1 + rnd() % MAX_MIPS) : 1;
        for (k = 0; k < MAX_MIPS; k++) {
            C.lw[k] = C.w >> k ? C.w >> k : 1;
            C.lh[k] = C.h >> k ? C.h >> k : 1;
        }
        C.lod_bias = (float)(int8_t)(rnd() & 0xFF) / 32.0f;
        C.min_lod = (float)(rnd() & 0xFF) / 16.0f;
        C.max_lod = (float)(rnd() & 0xFF) / 16.0f;
        if (rnd() % 2) C.min_lod = 0.0f; /* the usual setting, so the level of detail decides */
        C.scale_s = rnd() % 8 == 0 ? (float)(1 + rnd() % 1024) : (float)C.w;
        C.scale_t = rnd() % 8 == 0 ? (float)(1 + rnd() % 1024) : (float)C.h;
        C.su0 = C.scale_s * (float)C.lw[0] / (float)C.w; /* tev_prepare's expression */
        C.sv0 = C.scale_t * (float)C.lh[0] / (float)C.h;
        lod = rnd_range(-4.0f, 14.0f);
        if (rnd() % 4 == 0) { /* within a few ULPs of a .5 once biased */
            uint32_t b;
            lod = (float)(rnd() % 12) + 0.5f - C.lod_bias;
            memcpy(&b, &lod, 4);
            b += (rnd() % 9) - 4;
            memcpy(&lod, &b, 4);
            hits[L_EDGE]++;
        }
        if (rnd() % 64 == 0) {
            uint32_t nan = 0x7FC00000u;
            memcpy(&lod, &nan, 4);
            hits[L_NAN]++;
        }
        s = rnd_range(-4.0f, 4.0f);
        t = rnd_range(-4.0f, 4.0f);
        l = tex_level(&C, s, t, lod, &u, &v);
        cpu[i * 3] = (uint32_t)l;
        memcpy(&cpu[i * 3 + 1], &u, 4);
        memcpy(&cpu[i * 3 + 2], &v, 4);
        if (!C.mip || C.nlevels <= 1) hits[L_NOMIP]++;
        else if (lod == lod) {
            float L = lod + C.lod_bias;
            if (L < C.min_lod) hits[L_MIN]++;
            else if (L > C.max_lod) hits[L_MAX]++;
            if (l == C.nlevels - 1) hits[L_TOP]++;
        }
        hits[l ? L_LEVELN : L_LEVEL0]++;
        if ((C.w & (C.w - 1)) || (C.h & (C.h - 1))) hits[L_NPOT]++;
        memcpy(&w[0], &lod, 4);
        memcpy(&w[1], &C.lod_bias, 4);
        memcpy(&w[2], &C.min_lod, 4);
        memcpy(&w[3], &C.max_lod, 4);
        w[4] = (uint32_t)C.nlevels | (uint32_t)C.mip << 8;
        memcpy(&w[5], &s, 4);
        memcpy(&w[6], &t, 4);
        memcpy(&w[7], &C.su0, 4);
        memcpy(&w[8], &C.sv0, 4);
        memcpy(&w[9], &C.scale_s, 4);
        memcpy(&w[10], &C.scale_t, 4);
        w[11] = (uint32_t)C.w;
        w[12] = (uint32_t)C.h;
        for (k = 0; k < MAX_MIPS; k++) {
            w[13 + k] = (uint32_t)C.lw[k];
            w[24 + k] = (uint32_t)C.lh[k];
        }
    }
    if (!gxv_lod_run(0, in, out, n)) return 1;
    for (i = 0; i < n; i++) {
        if (!memcmp(&out[i * 3], &cpu[i * 3], 12)) continue;
        bad++;
        if (shown++ < 8) {
            float lod, gu, gv, cu, cv;
            memcpy(&lod, &in[(size_t)i * GXV_LOD_WORDS], 4);
            memcpy(&gu, &out[i * 3 + 1], 4);
            memcpy(&gv, &out[i * 3 + 2], 4);
            memcpy(&cu, &cpu[i * 3 + 1], 4);
            memcpy(&cv, &cpu[i * 3 + 2], 4);
            printf("level mismatch case %u: lod %.9g; gpu level %u u %.9g v %.9g; tex_level level %u u %.9g v %.9g\n", i, lod,
                   out[i * 3], gu, gv, cpu[i * 3], cu, cv);
        }
    }
    printf("lodhits");
    for (k = 0; k < L_N; k++) {
        printf(" %s=%llu", g_lod_hit[k], hits[k]);
        if (hits[k] < 100) low++;
    }
    printf("\n");
    printf("loddiff level %u cases, seed %u: %u mismatch%s; %u path%s under 100 hits\n", n, seed, bad, bad == 1 ? "" : "es", low,
           low == 1 ? "" : "s");

    /* The formula. */
    shown = 0;
    for (i = 0; i < n; i++) {
        uint32_t* w = in + (size_t)kept * GXV_LOD_WORDS;
        float planes[4][3], px, py, sc_s, sc_t, f[7];
        double W, S, T, Q, ds[2], dt[2], q, cond, fx, fy;
        seed_rng(seed ^ 0x10D10Du, i);
        px = (float)(rnd() % 640) + 0.5f;
        py = (float)(rnd() % 528) + 0.5f;
        for (k = 0; k < 4; k++) {
            planes[k][0] = rnd_range(-1.0f, 1.0f) * (k ? 0.05f : 1e-4f);
            planes[k][1] = rnd_range(-1.0f, 1.0f) * (k ? 0.05f : 1e-4f);
        }
        W = rnd_range(1e-3f, 1.0f);
        planes[0][2] = (float)(W - planes[0][0] * (double)px - planes[0][1] * (double)py);
        planes[1][2] = rnd_range(-50.0f, 50.0f);
        planes[2][2] = rnd_range(-50.0f, 50.0f);
        if (rnd() % 4) { /* q is 1: an ST texgen */
            planes[3][0] = planes[0][0];
            planes[3][1] = planes[0][1];
            planes[3][2] = planes[0][2];
        } else {
            planes[3][2] = rnd_range(-2.0f, 2.0f);
        }
        sc_s = (float)(1 << (rnd() % 11));
        sc_t = (float)(1 << (rnd() % 11));
        W = planes[0][0] * (double)px + planes[0][1] * py + planes[0][2];
        S = planes[1][0] * (double)px + planes[1][1] * py + planes[1][2];
        T = planes[2][0] * (double)px + planes[2][1] * py + planes[2][2];
        Q = planes[3][0] * (double)px + planes[3][1] * py + planes[3][2];
        if (W <= 1e-6) { left++; continue; }
        q = Q / W;
        if (q == 0.0) q = 1.0;
        /* d(S/W)/dx and the rest, and how badly the CPU's float subtraction
         * of the same two products can cancel. */
        cond = 0.0;
        for (k = 0; k < 2; k++) {
            double sa = planes[1][k], ta = planes[2][k], wa = planes[0][k];
            ds[k] = (sa * W - S * wa) / (W * W);
            dt[k] = (ta * W - T * wa) / (W * W);
            if (ds[k] != 0.0 && (fabs(sa * W) + fabs(S * wa)) / fabs(sa * W - S * wa) > cond) cond = (fabs(sa * W) + fabs(S * wa)) / fabs(sa * W - S * wa);
            if (dt[k] != 0.0 && (fabs(ta * W) + fabs(T * wa)) / fabs(ta * W - T * wa) > cond) cond = (fabs(ta * W) + fabs(T * wa)) / fabs(ta * W - T * wa);
        }
        fx = (ds[0] / q * sc_s) * (ds[0] / q * sc_s) + (dt[0] / q * sc_t) * (dt[0] / q * sc_t);
        fy = (ds[1] / q * sc_s) * (ds[1] / q * sc_s) + (dt[1] / q * sc_t) * (dt[1] / q * sc_t);
        if (cond > 1000.0 || fabs(fx > fy ? fx : fy) < 1e-10) { left++; continue; }
        f[0] = (float)ds[0];
        f[1] = (float)dt[0];
        f[2] = (float)ds[1];
        f[3] = (float)dt[1];
        f[4] = (float)q;
        f[5] = sc_s;
        f[6] = sc_t;
        memset(w, 0, GXV_LOD_WORDS * 4);
        memcpy(w, f, sizeof f);
        {
            float c = gxr_span_lod((const float (*)[3])planes, px, py, sc_s, sc_t);
            memcpy(&cpu[kept * 3], &c, 4);
        }
        kept++;
    }
    if (kept && !gxv_lod_run(1, in, out, kept)) return 1;
    for (i = 0; i < kept; i++) {
        float g, c;
        double d;
        memcpy(&g, &out[i * 3], 4);
        memcpy(&c, &cpu[i * 3], 4);
        d = fabs((double)g - (double)c);
        if (d > worst || d != d) worst = d;
        if (d <= LOD_TOL) continue;
        over++;
        if (shown++ < 8) printf("formula over case %u: gpu %.9g span_lod %.9g\n", i, g, c);
    }
    printf("loddiff formula %u cases, seed %u: %u over 1/1024 (largest %.3g); %u left out\n", kept, seed, over, worst, left);
    free(in);
    free(out);
    free(cpu);
    return bad || low || over || !kept;
}

/* copydiff: every copy command format (BP 0x52's four bits, 0-15), intensity
 * on and off, half scale on and off, filter on and off -- 128 combinations
 * -- each over `rects` random rectangles, with a random EFB per combination
 * and random bytes around the destination before each copy. The same seed
 * makes the same copies in both processes; each writes a line per copy:
 * its parameters, then hashes of the destination before and after (64 bytes
 * either side included), of the decoded image, and of a screen copy of the
 * same rectangle. tools/gpuspike.py compares the two files. */
static void copy_shape(unsigned texfmt, unsigned* tw, unsigned* th, unsigned* bpt)
{
    switch (texfmt) {
    case 0: *tw = 8; *th = 8; *bpt = 32; break;
    case 1: case 2: *tw = 8; *th = 4; *bpt = 32; break;
    case 3: case 4: case 5: *tw = 4; *th = 4; *bpt = 32; break;
    default: *tw = 4; *th = 4; *bpt = 64; break;
    }
}

/* copy_texfmt as gxr.c has it: which texture format a command word makes. */
static unsigned harness_texfmt(uint32_t v)
{
    unsigned tpf = (v >> 3) & 15, fmt = tpf / 2 + (tpf & 1) * 8;
    if ((v >> 15) & 1) return fmt <= 3 ? fmt : 99;
    switch (fmt) {
    case 0: return 0;
    case 1: case 7: case 8: case 9: case 10: return 1;
    case 2: return 2;
    case 3: case 11: case 12: return 3;
    case 4: case 5: case 6: return fmt;
    default: return 99;
    }
}

/* V9a: whether a picture at scale k, (k*w) x (k*h) at stride k*w, is the
 * native one (w x h at `stride` bytes) with each pixel replicated k x k --
 * what a copy at scale is when every sample of a pixel is the same. */
static int replicated(const uint8_t* big, const uint8_t* small, unsigned w, unsigned h, size_t stride, unsigned k)
{
    unsigned x, y;
    for (y = 0; y < h * k; y++) {
        const uint32_t* b = (const uint32_t*)(big + (size_t)y * w * k * 4);
        const uint32_t* n = (const uint32_t*)(small + (size_t)(y / k) * stride);
        for (x = 0; x < w * k; x++)
            if (b[x] != n[x / k]) return 0;
    }
    return 1;
}

static int copydiff(CpuState* s, unsigned rects, uint32_t seed)
{
    char path[512];
    FILE* f;
    uint8_t* efb = (uint8_t*)malloc((size_t)EFB_W * EFB_H * 4);
    uint8_t* img = (uint8_t*)malloc(1024u * 1024u * 4u);
    unsigned combo, r, k;
    unsigned long long pool_n = 0, pool_bad = 0, full_n = 0, full_bad = 0;
    snprintf(path, sizeof path, "%s/copydiff.txt", g_out);
    f = fopen(path, "w");
    if (!f || !efb || !img) { fprintf(stderr, "[copydiff] cannot write %s\n", path); return 1; }
    for (combo = 0; combo < 128; combo++) {
        unsigned tpf = combo & 15, intensity = (combo >> 4) & 1, half = (combo >> 5) & 1, filt = (combo >> 6) & 1;
        uint32_t f0 = 0, f1 = 0;
        seed_rng(seed, 0x10000u + combo);
        for (k = 0; k < (unsigned)EFB_W * EFB_H; k++) {
            uint32_t v = rnd();
            memcpy(efb + 4 * k, &v, 4);
        }
        gxr_flush();
        if (g_gpu) {
            if (!gxv_load_efb(efb)) return 1;
        } else {
            memcpy(g_efb, efb, (size_t)EFB_W * EFB_H * 4);
        }
        if (filt) {
            /* Seven weights; mostly near a sum of 64, as a game programs them,
             * and now and then anything at all, which clamps. */
            int wide = rnd() % 4 == 0;
            for (k = 0; k < 4; k++) f0 |= (rnd() % (wide ? 64u : 19u)) << (6 * k);
            for (k = 0; k < 3; k++) f1 |= (rnd() % (wide ? 64u : 19u)) << (6 * k);
            if (!f0 && !f1) f0 = 22u << 18;
        }
        bp_w(s, 0x53, f0);
        bp_w(s, 0x54, f1);
        for (r = 0; r < rects; r++) {
            uint32_t pick = rnd() % 10, x0 = rnd() % 656, y0 = rnd() % 544, w, h, v, stride = 0, dest, extent = 0, lo, hi;
            unsigned texfmt, tw, th, bpt, ow, oh;
            uint64_t h_seed, h_ram, h_img = 0, h_scr;
            if (pick < 6) { w = 1 + rnd() % 64; h = 1 + rnd() % 64; }
            else if (pick < 9) { w = 1 + rnd() % 640; h = 1 + rnd() % 528; }
            else { w = 1 + rnd() % 1024; h = 1 + rnd() % 1024; }
            if (x0 + w > 1024) w = 1024 - x0;
            if (y0 + h > 1024) h = 1024 - y0;
            v = (tpf << 3) | (intensity << 15) | (half << 9) | 3u;
            texfmt = harness_texfmt(v);
            ow = half ? w / 2 : w;
            oh = half ? h / 2 : h;
            copy_shape(texfmt, &tw, &th, &bpt);
            if (rnd() % 4 == 0) stride = (ow + tw - 1) / tw * bpt / 32 + rnd() % 64;
            dest = (0x00100000u + (rnd() % 0x00800000u)) & ~31u;
            if (texfmt != 99 && ow && oh) {
                uint32_t natural = (ow + tw - 1) / tw * bpt, row = stride * 32 > natural ? stride * 32 : natural;
                extent = ((oh + th - 1) / th - 1) * row + (ow + tw - 1) / tw * bpt;
            }
            lo = dest - 64;
            hi = dest + (extent ? extent : 256) + 64;
            if (hi > MEM1_SIZE) hi = MEM1_SIZE;
            for (k = lo; k < hi; k++) s->mem[k] = (uint8_t)rnd();
            h_seed = fnv(FNV0, s->mem + lo, hi - lo);
            bp_w(s, 0x49, (y0 << 10) | x0);
            bp_w(s, 0x4A, ((h - 1) << 10) | (w - 1));
            bp_w(s, 0x4B, dest >> 5);
            bp_w(s, 0x4D, stride);
            bp_w(s, 0x52, v);
            gxr_flush();
            h_ram = fnv(FNV0, s->mem + lo, hi - lo);
            /* The decoded image: on the GPU, the copy shader's own; on the CPU,
             * tex_decode_row over the bytes, each row of tiles where the
             * stride put it. */
            if (extent && dest + extent <= MEM1_SIZE) {
                uint32_t natural = (ow + tw - 1) / tw * bpt, row = stride * 32 > natural ? stride * 32 : natural, y;
                if (g_gpu) {
                    unsigned gw, gh, pw, ph;
                    int sc;
                    const uint8_t* gi = gxv_last_copy_image(&gw, &gh);
                    h_img = gw == ow && gh == oh ? fnv(FNV0, gi, (size_t)ow * oh * 4) : 0;
                    if (gxv_scale() > 1) {
                        /* The pool's image (V9a): on this EFB, the native one replicated. */
                        const uint8_t* pi = gxv_last_copy_pool(&pw, &ph, &sc);
                        pool_n++;
                        if (gw != ow || gh != oh || pw != ow * (unsigned)sc || ph != oh * (unsigned)sc ||
                            !replicated(pi, gi, ow, oh, (size_t)ow * 4, (unsigned)sc))
                            pool_bad++;
                    }
                } else {
                    for (y = 0; y < oh; y++)
                        tex_decode_row(img, s->mem + dest + (y / th) * (row - natural), texfmt, ow, y);
                    h_img = fnv(FNV0, img, (size_t)ow * oh * 4);
                }
            }
            bp_w(s, 0x52, 0x4003u); /* the same rectangle to the screen */
            gxr_flush();
            h_scr = gxr_screen_hash();
            if (g_gpu && gxv_scale() > 1) {
                /* The screen at scale (V9a): on this EFB, g_screen replicated. */
                int fw, fh, sc, nw, nh;
                const uint8_t* full = gxv_screen_full(&fw, &fh, &sc);
                const uint8_t* nat = gxr_screen(&nw, &nh);
                full_n++;
                if (fw != nw || fh != nh || !replicated(full, nat, (unsigned)nw, (unsigned)nh, (size_t)EFB_W * 4, (unsigned)sc))
                    full_bad++;
            }
            fprintf(f, "%u %u %u %u %u %u %u %u %u %u %u %08x %u %u %016llx %016llx %016llx %016llx\n", combo, r, tpf, intensity,
                    half, filt, x0, y0, w, h, stride, dest, texfmt, extent, (unsigned long long)h_seed,
                    (unsigned long long)h_ram, (unsigned long long)h_img, (unsigned long long)h_scr);
        }
    }
    bp_w(s, 0x53, 0);
    bp_w(s, 0x54, 0);
    fclose(f);
    free(efb);
    free(img);
    printf("copydiff %u combinations x %u rectangles, seed %u: %s\n", 128u, rects, seed, path);
    if (g_gpu && gxv_scale() > 1)
        printf("copydiff at scale %d: the pool's image is the native one replicated in %llu of %llu copies, the "
               "full screen g_screen replicated in %llu of %llu\n",
               gxv_scale(), pool_n - pool_bad, pool_n, full_n - full_bad, full_n);
    return 0;
}

int main(int argc, char** argv)
{
    CpuState s;
    char got[128];
    const char* mutate = NULL;
    const char* replay = NULL;
    const char* png = NULL;
    const char* png_full = NULL;
    const char* logicop = NULL;
    const char* dump_ram = NULL;
    const char* dump_depth = NULL;
    unsigned tev_cases = 0, copy_rects = 0, lod_cases = 0, queue = 0, copyimage = 0, present = 0, logictest = 0;
    uint32_t seed = 1;
    int failures, i;

    for (i = 1; i + 1 < argc; i++) {
        if (!strcmp(argv[i], "--backend")) g_gpu = !strcmp(argv[++i], "gpu");
        else if (!strcmp(argv[i], "--out")) g_out = argv[++i];
        else if (!strcmp(argv[i], "--mutate")) mutate = argv[++i];
        else if (!strcmp(argv[i], "--tevdiff")) tev_cases = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--copydiff")) copy_rects = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--loddiff")) lod_cases = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--queue")) queue = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--copyimage")) copyimage = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--present")) present = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--logictest")) logictest = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--seed")) seed = (uint32_t)strtoul(argv[++i], NULL, 0);
        else if (!strcmp(argv[i], "--replay")) replay = argv[++i];
        else if (!strcmp(argv[i], "--png")) png = argv[++i];
        else if (!strcmp(argv[i], "--png-full")) png_full = argv[++i];
        else if (!strcmp(argv[i], "--logicop")) logicop = argv[++i];
        else if (!strcmp(argv[i], "--dump-ram")) dump_ram = argv[++i];
        else if (!strcmp(argv[i], "--dump-depth")) dump_depth = argv[++i];
    }
    if ((tev_cases || lod_cases) && !g_gpu) {
        fprintf(stderr, "[gpuspike] --tevdiff and --loddiff run both sides themselves, and need --backend gpu\n");
        return 2;
    }
    if (g_gpu) {
        char why[256];
        if (!gxv_init(why, sizeof why)) {
            printf("skip: %s\n", why);
            fprintf(stderr, "[gpuspike] no Vulkan: %s\n", why);
            return 3;
        }
        if (mutate && !gxv_set_mutation(mutate)) {
            fprintf(stderr, "[gpuspike] no mutation %s\n", mutate);
            return 2;
        }
        if (logicop && !gxv_set_logicop(logicop)) {
            fprintf(stderr, "[gpuspike] no logic-op mode %s (native, blend, snapshot)\n", logicop);
            return 2;
        }
        gxv_set_upload_hook(upload_hook);
        if (!tev_cases && !lod_cases) gxr_set_backend(gxv_backend());
        printf("device %s\n", gxv_device_name());
    }
    if (present) {
        /* V8's presenter check alone: no renderer, no frame. */
        if (!g_gpu) {
            fprintf(stderr, "[gpuspike] --present wants --backend gpu\n");
            return 2;
        }
        failures = present_check();
        gxv_shutdown();
        return failures ? 1 : 0;
    }
    memset(&s, 0, sizeof s);
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    if (!s.mem) {
        fprintf(stderr, "[gpuspike] cannot allocate MEM1\n");
        return 2;
    }
    if (replay) {
        /* A capture through the real front end, as the port's --replay runs
         * it: its registers, its RAM and its command stream. The frame is
         * the last screen copy; its hash is gxr_screen_hash, the manifest's. */
        const uint8_t* screen;
        int w = 0, h = 0, r;
        render_env();
        if (!gxr_enabled()) {
            fprintf(stderr, "[gpuspike] the renderer is off\n");
            return 2;
        }
        r = gx_replay(&s, replay);
        screen = gxr_screen(&w, &h);
        printf("frame %dx%d hash %016llx\n", w, h, (unsigned long long)gxr_screen_hash());
        if (png && !png_write_rgba(png, screen, w, h, EFB_W * 4)) {
            fprintf(stderr, "[gpuspike] cannot write %s\n", png);
            r = 1;
        }
        if (png_full && g_gpu) {
            int fw, fh, k;
            const uint8_t* full = gxv_screen_full(&fw, &fh, &k);
            printf("full frame %dx%d at scale %d\n", fw * k, fh * k, k);
            if (!png_write_rgba(png_full, full, fw * k, fh * k, fw * k * 4)) {
                fprintf(stderr, "[gpuspike] cannot write %s\n", png_full);
                r = 1;
            }
        }
        /* MEM1 as the frame left it, for chain and ramdiff: what each copy to
         * a texture wrote is in it. */
        if (dump_ram) {
            FILE* f = fopen(dump_ram, "wb");
            if (!f || fwrite(s.mem, 1, MEM1_SIZE, f) != MEM1_SIZE) {
                fprintf(stderr, "[gpuspike] cannot write %s\n", dump_ram);
                r = 1;
            }
            if (f) fclose(f);
        }
        /* The depth buffer as 24-bit values, 640x528 little-endian words:
         * the CPU's g_efb_z, or the GPU's read back. */
        if (dump_depth) {
            static uint32_t z[EFB_H][EFB_W];
            FILE* f = fopen(dump_depth, "wb");
            if (g_gpu) {
                if (!gxv_read_depth(&z[0][0])) r = 1;
            } else {
                memcpy(z, g_efb_z, sizeof z);
            }
            if (!f || fwrite(z, 1, sizeof z, f) != sizeof z) {
                fprintf(stderr, "[gpuspike] cannot write %s\n", dump_depth);
                r = 1;
            }
            if (f) fclose(f);
        }
        if (g_gpu) gxv_shutdown(); /* gx_replay's report printed gxv's, the backend's own */
        free(s.mem);
        return r ? 1 : 0;
    }
    if (tev_cases || copy_rects || lod_cases) {
        render_env();
        if (!gxr_enabled()) {
            fprintf(stderr, "[gpuspike] the renderer is off\n");
            return 2;
        }
        failures = tev_cases ? tevdiff(&s, tev_cases, seed)
                 : lod_cases ? loddiff(lod_cases, seed)
                             : copydiff(&s, copy_rects, seed);
        if (g_gpu) {
            gxv_report();
            gxv_shutdown();
        }
        free(s.mem);
        return failures ? 1 : 0;
    }
    if (queue || copyimage || logictest) {
        /* V6a's queue frame, V7's copy image or a V10 logic scene, alone;
         * gxr_report prints the backend's report. */
        render_env();
        failures = queue ? scene_queue(&s) : copyimage ? scene_copyimage(&s) : scene_logictest(&s, (int)logictest);
        if (g_gpu) gxv_shutdown();
        free(s.mem);
        return failures ? 1 : 0;
    }
    failures = render_selftest(&s, got, sizeof got);
    printf("recipes %s\n", failures ? "FAIL" : "ok");
    for (i = 0; i < 4; i++) failures += scene_cull(&s, (unsigned)i);
    failures += clip_scenes(&s);
    failures += scene_depth(&s);
    failures += scene_depth_persp(&s);
    failures += scene_scissor(&s);
    failures += scene_quad_gradient(&s);
    failures += scene_clear(&s);
    failures += scene_logic(&s);
    failures += scene_invariance(&s);
    failures += scene_lines(&s);
    failures += scene_points(&s);
    if (g_mmio_reads) fprintf(stderr, "[gpuspike] %u MMIO reads, which these frames should not need\n", g_mmio_reads);
    if (g_gpu) {
        gxv_report();
        gxv_shutdown();
    }
    free(s.mem);
    return failures ? 1 : 0;
}
