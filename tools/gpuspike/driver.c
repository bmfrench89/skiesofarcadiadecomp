/*
 * The GPU spike's driver (specs/gpu-backend.md V3a): the renderer with no
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
 * Exit status: 0 when every check here passed, 1 when one failed, 3 when gpu
 * mode found no Vulkan device (a skip, which the caller reports as one).
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "gxr.h"
#include "gxr_cmd.h"
#include "gxv.h"
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

int main(int argc, char** argv)
{
    CpuState s;
    char got[128];
    const char* mutate = NULL;
    int failures, i;

    for (i = 1; i + 1 < argc; i++) {
        if (!strcmp(argv[i], "--backend")) g_gpu = !strcmp(argv[++i], "gpu");
        else if (!strcmp(argv[i], "--out")) g_out = argv[++i];
        else if (!strcmp(argv[i], "--mutate")) mutate = argv[++i];
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
        gxv_set_upload_hook(upload_hook);
        gxr_set_backend(gxv_backend());
        printf("device %s\n", gxv_device_name());
    }
    memset(&s, 0, sizeof s);
    s.mem = (uint8_t*)calloc(1, MEM1_SIZE);
    if (!s.mem) {
        fprintf(stderr, "[gpuspike] cannot allocate MEM1\n");
        return 2;
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
