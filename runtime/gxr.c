/*
 * Software GX: vertex decode, transform unit (matrices, lighting, texgen),
 * clipping, rasterization, depth/blend into the embedded framebuffer, and
 * EFB copies (to textures in memory, or to the "screen" as a PNG).
 *
 * Correctness first, speed later: every pixel runs the full TEV. The point
 * is a frame we can look at, produced from the exact command stream the
 * game emits, so every deviation from the real console is ours to find.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "gxr.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#endif

double g_gxr_time[T_COUNT];
double gxr_clock(void)
{
#ifdef _WIN32
    static double freq;
    LARGE_INTEGER c;
    if (freq == 0.0) { LARGE_INTEGER f; QueryPerformanceFrequency(&f); freq = (double)f.QuadPart; }
    QueryPerformanceCounter(&c);
    return (double)c.QuadPart / freq;
#else
    return 0.0;
#endif
}

uint8_t g_efb[EFB_H][EFB_W][4];
uint32_t g_efb_z[EFB_H][EFB_W];

static int g_enabled = -1;
static unsigned g_frames_every, g_frame_no;
static char g_png_path[512];
static uint64_t g_tris, g_lines, g_points, g_clipped, g_verts_bad;
static uint64_t g_copies_tex, g_copies_xfb, g_rej_bary;

/* Rasterization is row-parallel: worker threads each take every Nth row of
 * every triangle in a draw, and the main thread is participant 0. Counters
 * touched per pixel are per thread. */
#define MAX_THREADS 16
static int g_nthreads = 1;
static __declspec(thread) int t_tid;
static uint64_t g_pixels_t[MAX_THREADS], g_rej_depth_t[MAX_THREADS], g_rej_alpha_t[MAX_THREADS];
#define g_pixels g_pixels_t[t_tid]
#define g_rej_depth g_rej_depth_t[t_tid]
#define g_rej_alpha g_rej_alpha_t[t_tid]
static int g_cull_flip, g_debug;
static unsigned g_draw_limit, g_draw_no;

int gxr_enabled(void)
{
    if (g_enabled < 0) {
        const char* env = getenv("SOA_RENDER");
        const char* every = getenv("SOA_FRAMES");
        g_enabled = env && atoi(env) ? 1 : 0;
        g_frames_every = every ? (unsigned)atoi(every) : 0;
        g_cull_flip = getenv("SOA_CULLFLIP") ? 1 : 0;
        g_debug = getenv("SOA_GXR_DEBUG") ? 1 : 0;
        g_draw_limit = getenv("SOA_GXR_DRAWS") ? (unsigned)atoi(getenv("SOA_GXR_DRAWS")) : 0;
    }
    return g_enabled;
}

/* The EFB persists across frames on the console; a replay starts from the
 * state the previous frame's clear left: the clear color and z from the
 * captured registers. */
void gxr_reset_efb(void)
{
    gxr_flush();
    const uint32_t* bp = gx_bp_regs();
    uint32_t ar = bp[0x4F], gb = bp[0x50], z = bp[0x51] & 0xFFFFFFu;
    uint8_t col[4] = {(uint8_t)(ar & 0xFF), (uint8_t)((gb >> 8) & 0xFF), (uint8_t)(gb & 0xFF), (uint8_t)((ar >> 8) & 0xFF)};
    int x, y;
    for (y = 0; y < EFB_H; y++)
        for (x = 0; x < EFB_W; x++) { memcpy(g_efb[y][x], col, 4); g_efb_z[y][x] = z ? z : 0xFFFFFFu; }
}

void gxr_enable(int on)
{
    gxr_enabled();
    g_enabled = on;
}

void gxr_set_output(const char* png_path)
{
    snprintf(g_png_path, sizeof g_png_path, "%s", png_path);
}

static float xff(const uint32_t* xf, unsigned i)
{
    float f;
    uint32_t v = xf[i];
    memcpy(&f, &v, 4);
    return f;
}

static uint16_t be16(const uint8_t* p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }
static uint32_t be32(const uint8_t* p) { return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }

/* ---- vertex attributes ------------------------------------------------- */

typedef struct {
    float pos[3];
    float nrm[3];
    Color4 col[2];
    float tex[8][2];
    unsigned posidx, texidx[8];
    int has_nrm, has_col[2], has_tex[8];
} VertexIn;

static unsigned comp_bytes(unsigned fmt) { return fmt == 4 ? 4 : (fmt >= 2 ? 2 : 1); }

static float read_comp(const uint8_t* p, unsigned fmt, unsigned frac)
{
    float scale = 1.0f / (float)(1u << frac);
    switch (fmt) {
    case 0: return (float)p[0] * scale;
    case 1: return (float)(int8_t)p[0] * scale;
    case 2: return (float)be16(p) * scale;
    case 3: return (float)(int16_t)be16(p) * scale;
    default: { float f; uint32_t v = be32(p); memcpy(&f, &v, 4); return f; }
    }
}

static unsigned color_bytes(unsigned fmt)
{
    static const unsigned t[8] = {2, 3, 4, 2, 3, 4, 4, 4};
    return t[fmt & 7];
}

static void read_color(const uint8_t* p, unsigned fmt, Color4* c)
{
    unsigned v;
    switch (fmt) {
    case 0: /* RGB565 */
        v = be16(p);
        c->r = (float)((v >> 11) & 31) / 31.0f; c->g = (float)((v >> 5) & 63) / 63.0f; c->b = (float)(v & 31) / 31.0f; c->a = 1.0f;
        break;
    case 1: case 2: /* RGB888, RGBX8888 */
        c->r = p[0] / 255.0f; c->g = p[1] / 255.0f; c->b = p[2] / 255.0f; c->a = 1.0f;
        break;
    case 3: /* RGBA4444 */
        v = be16(p);
        c->r = (float)((v >> 12) & 15) / 15.0f; c->g = (float)((v >> 8) & 15) / 15.0f; c->b = (float)((v >> 4) & 15) / 15.0f; c->a = (float)(v & 15) / 15.0f;
        break;
    case 4: /* RGBA6666 */
        v = ((unsigned)p[0] << 16) | ((unsigned)p[1] << 8) | p[2];
        c->r = (float)((v >> 18) & 63) / 63.0f; c->g = (float)((v >> 12) & 63) / 63.0f; c->b = (float)((v >> 6) & 63) / 63.0f; c->a = (float)(v & 63) / 63.0f;
        break;
    default: /* RGBA8888 */
        c->r = p[0] / 255.0f; c->g = p[1] / 255.0f; c->b = p[2] / 255.0f; c->a = p[3] / 255.0f;
        break;
    }
}

/* Where an attribute's data lives: inline in the stream, or in the array
 * the index selects (CP ARRAY_BASE/ARRAY_STRIDE, GXSetArray). */
static const uint8_t* attr_data(CpuState* s, const uint32_t* cp, unsigned mode, const uint8_t** p, unsigned array, unsigned direct_size)
{
    const uint8_t* d;
    uint32_t idx, base, stride, addr;
    switch (mode) {
    case 0: return NULL;
    case 1: d = *p; *p += direct_size; return d;
    case 2: idx = **p; *p += 1; break;
    default: idx = be16(*p); *p += 2; break;
    }
    base = cp[0xA0 + array] & 0x1FFFFFFFu;
    stride = cp[0xB0 + array] & 0xFFu;
    addr = base + idx * stride;
    if ((addr & MEM_MASK) + direct_size > MEM1_SIZE) { g_verts_bad++; return NULL; }
    return mem_ptr(s, addr | 0x80000000u);
}

static const uint8_t* decode_vertex(CpuState* s, const uint8_t* p, unsigned vat, VertexIn* v)
{
    const uint32_t* cp = gx_cp_regs();
    const uint32_t* xf = gx_xf_regs();
    uint32_t lo = cp[0x50], hi = cp[0x60], a = cp[0x70 + vat], b = cp[0x80 + vat], c = cp[0x90 + vat];
    unsigned i;
    const uint8_t* d;
    unsigned tc[8][3] = {
        {(a >> 21) & 1, (a >> 22) & 7, (a >> 25) & 31}, {(b >> 0) & 1, (b >> 1) & 7, (b >> 4) & 31},
        {(b >> 9) & 1, (b >> 10) & 7, (b >> 13) & 31},  {(b >> 18) & 1, (b >> 19) & 7, (b >> 22) & 31},
        {(b >> 27) & 1, (b >> 28) & 7, (c >> 0) & 31},  {(c >> 5) & 1, (c >> 6) & 7, (c >> 9) & 31},
        {(c >> 14) & 1, (c >> 15) & 7, (c >> 18) & 31}, {(c >> 23) & 1, (c >> 24) & 7, (c >> 27) & 31},
    };

    memset(v, 0, sizeof *v);
    v->posidx = (lo & 1) ? *p++ : (xf[0x1018] & 0x3F);
    for (i = 0; i < 8; i++) {
        unsigned dflt = i < 4 ? (xf[0x1018] >> (6 + 6 * i)) & 0x3F : (xf[0x1019] >> (6 * (i - 4))) & 0x3F;
        v->texidx[i] = ((lo >> (1 + i)) & 1) ? *p++ : dflt;
    }
    /* position */
    {
        unsigned cnt = (a & 1) ? 3 : 2, fmt = (a >> 1) & 7, frac = (a >> 4) & 31, nb = comp_bytes(fmt);
        d = attr_data(s, cp, (lo >> 9) & 3, &p, 0, cnt * nb);
        if (d) for (i = 0; i < cnt; i++) v->pos[i] = read_comp(d + i * nb, fmt, fmt == 4 ? 0 : frac);
    }
    /* normal */
    {
        unsigned mode = (lo >> 11) & 3, elems = (a >> 9) & 1, fmt = (a >> 10) & 7, nb = comp_bytes(fmt);
        unsigned frac = fmt == 1 ? 6 : (fmt == 3 ? 14 : 0);
        if (mode >= 2 && elems && ((a >> 31) & 1)) {
            /* NBT with three indices: read the normal, skip the other two */
            d = attr_data(s, cp, mode, &p, 1, 3 * nb);
            if (d) for (i = 0; i < 3; i++) v->nrm[i] = read_comp(d + i * nb, fmt, frac);
            attr_data(s, cp, mode, &p, 1, 3 * nb);
            attr_data(s, cp, mode, &p, 1, 3 * nb);
            v->has_nrm = 1;
        } else if (mode) {
            d = attr_data(s, cp, mode, &p, 1, (elems ? 9 : 3) * nb);
            if (d) for (i = 0; i < 3; i++) v->nrm[i] = read_comp(d + i * nb, fmt, frac);
            v->has_nrm = 1;
        }
    }
    /* colors */
    for (i = 0; i < 2; i++) {
        unsigned mode = (lo >> (13 + 2 * i)) & 3, fmt = i == 0 ? (a >> 14) & 7 : (a >> 18) & 7;
        d = attr_data(s, cp, mode, &p, 2 + i, color_bytes(fmt));
        if (d) { read_color(d, fmt, &v->col[i]); v->has_col[i] = 1; }
    }
    /* texture coordinates */
    for (i = 0; i < 8; i++) {
        unsigned mode = (hi >> (2 * i)) & 3, cnt = tc[i][0] ? 2 : 1, fmt = tc[i][1], frac = tc[i][2], nb = comp_bytes(fmt);
        unsigned k;
        d = attr_data(s, cp, mode, &p, 4 + i, cnt * nb);
        if (d) {
            for (k = 0; k < cnt; k++) v->tex[i][k] = read_comp(d + k * nb, fmt, fmt == 4 ? 0 : frac);
            v->has_tex[i] = 1;
        }
    }
    return p;
}

/* ---- transform unit ----------------------------------------------------- */

static void mat_mul_3x4(const uint32_t* xf, unsigned row0, const float in[4], float out[3])
{
    unsigned r;
    for (r = 0; r < 3; r++)
        out[r] = xff(xf, row0 + 4 * r) * in[0] + xff(xf, row0 + 4 * r + 1) * in[1] +
                 xff(xf, row0 + 4 * r + 2) * in[2] + xff(xf, row0 + 4 * r + 3) * in[3];
}

static void normalize3(float v[3])
{
    float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (len > 1e-12f) { v[0] /= len; v[1] /= len; v[2] /= len; }
}

static float clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

/* GX lighting for one channel (color: chan, alpha: chan). Register layout
 * per GXSetChanCtrl; light data per GXInitLight*. */
static void light_channel(const uint32_t* xf, unsigned chan, int alpha, const VertexIn* in, const float pos[3], const float nrm[3], float out[4])
{
    uint32_t ctl = xf[(alpha ? 0x1010 : 0x100E) + chan];
    uint32_t amb_reg = xf[0x100A + chan], mat_reg = xf[0x100C + chan];
    int matsrc = ctl & 1, enable = (ctl >> 1) & 1, ambsrc = (ctl >> 6) & 1;
    unsigned diffuse = (ctl >> 7) & 3, attnfn = (ctl >> 9) & 3;
    unsigned mask = ((ctl >> 2) & 15) | (((ctl >> 11) & 15) << 4);
    float mat[4], amb[4], acc[4];
    unsigned li, k;
    const Color4* vc = &in->col[chan];

    mat[0] = matsrc ? vc->r : ((mat_reg >> 24) & 255) / 255.0f;
    mat[1] = matsrc ? vc->g : ((mat_reg >> 16) & 255) / 255.0f;
    mat[2] = matsrc ? vc->b : ((mat_reg >> 8) & 255) / 255.0f;
    mat[3] = matsrc ? vc->a : (mat_reg & 255) / 255.0f;
    if (matsrc && !in->has_col[chan]) { mat[0] = mat[1] = mat[2] = mat[3] = 1.0f; }
    if (!enable) { memcpy(out, mat, sizeof mat); return; }

    amb[0] = ambsrc ? vc->r : ((amb_reg >> 24) & 255) / 255.0f;
    amb[1] = ambsrc ? vc->g : ((amb_reg >> 16) & 255) / 255.0f;
    amb[2] = ambsrc ? vc->b : ((amb_reg >> 8) & 255) / 255.0f;
    amb[3] = ambsrc ? vc->a : (amb_reg & 255) / 255.0f;
    memcpy(acc, amb, sizeof acc);

    for (li = 0; li < 8; li++) {
        const uint32_t* L;
        uint32_t color;
        float lcol[4], lpos[3], ldir[3], dir[3], attn = 1.0f, diff = 1.0f;
        if (!((mask >> li) & 1)) continue;
        L = xf + 0x600 + 16 * li;
        color = L[3];
        lcol[0] = ((color >> 24) & 255) / 255.0f; lcol[1] = ((color >> 16) & 255) / 255.0f;
        lcol[2] = ((color >> 8) & 255) / 255.0f; lcol[3] = (color & 255) / 255.0f;
        lpos[0] = xff(xf, 0x600 + 16 * li + 10); lpos[1] = xff(xf, 0x600 + 16 * li + 11); lpos[2] = xff(xf, 0x600 + 16 * li + 12);
        dir[0] = xff(xf, 0x600 + 16 * li + 13); dir[1] = xff(xf, 0x600 + 16 * li + 14); dir[2] = xff(xf, 0x600 + 16 * li + 15);

        if (attnfn == 1) { /* specular: light "position" is a direction, half-angle in dir */
            float nl;
            ldir[0] = lpos[0]; ldir[1] = lpos[1]; ldir[2] = lpos[2];
            normalize3(ldir);
            nl = nrm[0] * ldir[0] + nrm[1] * ldir[1] + nrm[2] * ldir[2];
            if (nl >= 0.0f) {
                float hd[3] = {dir[0], dir[1], dir[2]}, nh, ca, da;
                normalize3(hd);
                nh = nrm[0] * hd[0] + nrm[1] * hd[1] + nrm[2] * hd[2];
                if (nh < 0.0f) nh = 0.0f;
                ca = xff(xf, 0x600 + 16 * li + 4) + xff(xf, 0x600 + 16 * li + 5) * nh + xff(xf, 0x600 + 16 * li + 6) * nh * nh;
                da = xff(xf, 0x600 + 16 * li + 7) + xff(xf, 0x600 + 16 * li + 8) * nh + xff(xf, 0x600 + 16 * li + 9) * nh * nh;
                attn = (da != 0.0f) ? (ca < 0.0f ? 0.0f : ca) / da : 0.0f;
            } else attn = 0.0f;
        } else {
            ldir[0] = lpos[0] - pos[0]; ldir[1] = lpos[1] - pos[1]; ldir[2] = lpos[2] - pos[2];
            if (attnfn == 3) { /* spot */
                float dist2 = ldir[0] * ldir[0] + ldir[1] * ldir[1] + ldir[2] * ldir[2];
                float dist = sqrtf(dist2), cosv, ca, da;
                if (dist > 1e-12f) { ldir[0] /= dist; ldir[1] /= dist; ldir[2] /= dist; }
                cosv = ldir[0] * dir[0] + ldir[1] * dir[1] + ldir[2] * dir[2];
                if (cosv < 0.0f) cosv = 0.0f;
                ca = xff(xf, 0x600 + 16 * li + 4) + xff(xf, 0x600 + 16 * li + 5) * cosv + xff(xf, 0x600 + 16 * li + 6) * cosv * cosv;
                da = xff(xf, 0x600 + 16 * li + 7) + xff(xf, 0x600 + 16 * li + 8) * dist + xff(xf, 0x600 + 16 * li + 9) * dist2;
                attn = (da != 0.0f) ? (ca < 0.0f ? 0.0f : ca) / da : 0.0f;
            } else {
                normalize3(ldir);
            }
        }
        if (diffuse != 0) {
            diff = nrm[0] * ldir[0] + nrm[1] * ldir[1] + nrm[2] * ldir[2];
            if (diffuse == 2 && diff < 0.0f) diff = 0.0f;
        }
        for (k = 0; k < 4; k++) acc[k] += lcol[k] * attn * diff;
    }
    for (k = 0; k < 4; k++) out[k] = mat[k] * clamp01(acc[k]);
}

static void transform(CpuState* s, const VertexIn* in, Vertex* out)
{
    const uint32_t* xf = gx_xf_regs();
    float pos4[4] = {in->pos[0], in->pos[1], in->pos[2], 1.0f};
    float view[3], nrm[3] = {0, 0, 1};
    unsigned i;
    (void)s;

    mat_mul_3x4(xf, 4 * (in->posidx & 0x3F), pos4, view);
    if (in->has_nrm) {
        unsigned nb = 0x400 + 3 * (in->posidx & 0x3F);
        unsigned r;
        for (r = 0; r < 3; r++)
            nrm[r] = xff(xf, nb + 3 * r) * in->nrm[0] + xff(xf, nb + 3 * r + 1) * in->nrm[1] + xff(xf, nb + 3 * r + 2) * in->nrm[2];
        normalize3(nrm);
    }

    /* projection (XF 0x1020-0x1026, GXSetProjection) */
    {
        float p0 = xff(xf, 0x1020), p1 = xff(xf, 0x1021), p2 = xff(xf, 0x1022), p3 = xff(xf, 0x1023), p4 = xff(xf, 0x1024), p5 = xff(xf, 0x1025);
        if (xf[0x1026] & 1) { /* orthographic */
            out->x = p0 * view[0] + p1;
            out->y = p2 * view[1] + p3;
            out->z = p4 * view[2] + p5;
            out->w = 1.0f;
        } else {
            out->x = p0 * view[0] + p1 * view[2];
            out->y = p2 * view[1] + p3 * view[2];
            out->z = p4 * view[2] + p5;
            out->w = -view[2];
        }
    }

    /* color channels (XF 0x1009 numColorChans, 0x100E.. controls) */
    for (i = 0; i < 2; i++) {
        float c[4], a[4];
        light_channel(xf, i, 0, in, view, nrm, c);
        light_channel(xf, i, 1, in, view, nrm, a);
        out->col[i].r = c[0]; out->col[i].g = c[1]; out->col[i].b = c[2]; out->col[i].a = a[3];
    }

    /* texture coordinate generation (XF 0x103F count, 0x1040+ GXSetTexCoordGen) */
    {
        unsigned n = xf[0x103F] & 15;
        for (i = 0; i < 8; i++) {
            uint32_t info = xf[0x1040 + i];
            unsigned proj = (info >> 1) & 1, form = (info >> 2) & 1, type = (info >> 4) & 7, src = (info >> 7) & 31;
            float in4[4] = {0, 0, 1, 1}, o[3] = {0, 0, 1};
            if (i >= n) { out->tex[i][0] = out->tex[i][1] = 0; out->tex[i][2] = 1; continue; }
            if (src == 0) { in4[0] = in->pos[0]; in4[1] = in->pos[1]; in4[2] = form ? in->pos[2] : 1.0f; }
            else if (src == 1) { in4[0] = in->nrm[0]; in4[1] = in->nrm[1]; in4[2] = form ? in->nrm[2] : 1.0f; }
            else if (src >= 5 && src < 13) { in4[0] = in->tex[src - 5][0]; in4[1] = in->tex[src - 5][1]; in4[2] = 1.0f; }
            if (type == 2 || type == 3) {
                const Color4* cc = &out->col[type - 2];
                o[0] = cc->r; o[1] = cc->g; o[2] = 1.0f;
            } else if (type == 0) {
                unsigned row0 = 4 * (in->texidx[i] & 0x3F);
                if (proj) mat_mul_3x4(xf, row0, in4, o);
                else {
                    float t[3];
                    mat_mul_3x4(xf, row0, in4, t);
                    o[0] = t[0]; o[1] = t[1]; o[2] = 1.0f;
                }
            } else { /* emboss: pass the source through */
                o[0] = in4[0]; o[1] = in4[1]; o[2] = 1.0f;
            }
            if (xf[0x1012] & 1) { /* dual transform (GXSetTexCoordGen2 post matrix) */
                uint32_t post = xf[0x1050 + i];
                unsigned pidx = post & 0x3F;
                float t4[4] = {o[0], o[1], o[2], 1.0f}, r[3];
                if ((post >> 8) & 1) { float v3[3] = {o[0], o[1], o[2]}; normalize3(v3); t4[0] = v3[0]; t4[1] = v3[1]; t4[2] = v3[2]; }
                mat_mul_3x4(xf, 0x500 + 4 * pidx, t4, r);
                o[0] = r[0]; o[1] = r[1]; o[2] = r[2];
            }
            out->tex[i][0] = o[0]; out->tex[i][1] = o[1]; out->tex[i][2] = proj ? o[2] : 1.0f;
        }
    }
}

/* ---- draw commands ------------------------------------------------------
 * A draw is parsed, transformed and queued by the main thread; worker
 * threads rasterize queued draws in order, each taking every Nth row, so
 * per-pixel ordering is preserved and the game keeps running meanwhile.
 * EFB copies and clears wait for the queue to drain (gxr_flush). */

#define QUEUE_CAP 4096
#define ARENA_BYTES (48u << 20)

typedef struct { int x0, y0, x1, y1; } Rect;

typedef struct {
    int blend_en, logic_en, col_upd, alpha_upd, subtract;
    unsigned sfac, dfac, lop;
    int const_alpha; /* -1 when not enabled */
    int z_en, z_upd, ztop;
    unsigned z_func;
} PixelCfg;

typedef struct {
    Rect scissor;
    unsigned cull;
    float wd, ht, zrange, xorig, yorig, farz; /* viewport, offsets applied */
} RasterCfg;

typedef struct {
    int kind; /* 0 draw, 1 EFB copy (with optional clear) */
    TevSetup tev;
    PixelCfg px;
    RasterCfg rc;
    unsigned ntex, nchan, prim, count;
    const Vertex* v;
    /* copy: the registers as they were, and the command word */
    uint32_t cp_v, cp_tl, cp_wh, cp_dest, cp_stride, cp_ar, cp_gb, cp_z;
    CpuState* s;
} DrawCmd;

static void scissor_rect(const uint32_t* bp, Rect* r)
{
    uint32_t tl = bp[0x20], br = bp[0x21], off = bp[0x59];
    int xoff = (int)((off & 0x3FF) * 2), yoff = (int)(((off >> 10) & 0x3FF) * 2);
    r->x0 = (int)((tl >> 12) & 0x7FF) - xoff;
    r->y0 = (int)(tl & 0x7FF) - yoff;
    r->x1 = (int)((br >> 12) & 0x7FF) - xoff;
    r->y1 = (int)(br & 0x7FF) - yoff;
    if (r->x0 < 0) r->x0 = 0;
    if (r->y0 < 0) r->y0 = 0;
    if (r->x1 > EFB_W - 1) r->x1 = EFB_W - 1;
    if (r->y1 > EFB_H - 1) r->y1 = EFB_H - 1;
}

static void raster_prepare(const uint32_t* xf, const uint32_t* bp, RasterCfg* rc)
{
    uint32_t off = bp[0x59];
    scissor_rect(bp, &rc->scissor);
    rc->cull = (bp[0] >> 14) & 3;
    rc->wd = xff(xf, 0x101A); rc->ht = xff(xf, 0x101B); rc->zrange = xff(xf, 0x101C);
    rc->xorig = xff(xf, 0x101D) - (float)((off & 0x3FF) * 2);
    rc->yorig = xff(xf, 0x101E) - (float)(((off >> 10) & 0x3FF) * 2);
    rc->farz = xff(xf, 0x101F);
}

static void pixel_prepare(const uint32_t* bp, PixelCfg* px)
{
    uint32_t cmode = bp[0x41], cmode1 = bp[0x42], zmode = bp[0x40];
    px->blend_en = cmode & 1; px->logic_en = (cmode >> 1) & 1;
    px->col_upd = (cmode >> 3) & 1; px->alpha_upd = (cmode >> 4) & 1;
    px->dfac = (cmode >> 5) & 7; px->sfac = (cmode >> 8) & 7;
    px->subtract = (cmode >> 11) & 1; px->lop = (cmode >> 12) & 15;
    px->const_alpha = (cmode1 & 0x100) ? (int)(cmode1 & 0xFF) : -1;
    px->z_en = zmode & 1; px->z_func = (zmode >> 1) & 7; px->z_upd = (zmode >> 4) & 1;
    px->ztop = (bp[0x43] >> 6) & 1;
}

static void to_screen(const RasterCfg* rc, Vertex* v)
{
    float iw = v->w != 0.0f ? 1.0f / v->w : 0.0f;
    v->sx = rc->xorig + v->x * iw * rc->wd;
    v->sy = rc->yorig + v->y * iw * rc->ht;
    v->depth = (rc->farz + v->z * iw * rc->zrange) / 16777216.0f;
}

/* ---- pixels --------------------------------------------------------------- */

static inline void blend_pixel(const PixelCfg* px, int x, int y, const uint8_t src[4])
{
    uint8_t* dst = g_efb[y][x];
    int out[4], i;
    int sa = px->const_alpha >= 0 ? px->const_alpha : src[3], da = dst[3];

    if (px->blend_en) {
        int sf, df;
        switch (px->sfac) {
        case 0: sf = 0; break; case 1: sf = 255; break; case 2: sf = -1; break; case 3: sf = -2; break;
        case 4: sf = src[3]; break; case 5: sf = 255 - src[3]; break; case 6: sf = da; break; default: sf = 255 - da; break;
        }
        switch (px->dfac) {
        case 0: df = 0; break; case 1: df = 255; break; case 2: df = -1; break; case 3: df = -2; break;
        case 4: df = src[3]; break; case 5: df = 255 - src[3]; break; case 6: df = da; break; default: df = 255 - da; break;
        }
        for (i = 0; i < 3; i++) {
            int s_f = sf == -1 ? dst[i] : (sf == -2 ? 255 - dst[i] : sf);
            int d_f = df == -1 ? src[i] : (df == -2 ? 255 - src[i] : df);
            int r = px->subtract ? dst[i] - src[i] : (src[i] * s_f + dst[i] * d_f + 127) / 255;
            out[i] = r < 0 ? 0 : (r > 255 ? 255 : r);
        }
    } else if (px->logic_en) {
        for (i = 0; i < 3; i++) {
            int sv = src[i], dv = dst[i], r;
            switch (px->lop) {
            case 0: r = 0; break; case 1: r = sv & dv; break; case 2: r = sv & ~dv; break; case 3: r = sv; break;
            case 4: r = ~sv & dv; break; case 5: r = dv; break; case 6: r = sv ^ dv; break; case 7: r = sv | dv; break;
            case 8: r = ~(sv | dv); break; case 9: r = ~(sv ^ dv); break; case 10: r = ~dv; break; case 11: r = sv | ~dv; break;
            case 12: r = ~sv; break; case 13: r = ~sv | dv; break; case 14: r = ~(sv & dv); break; default: r = 255; break;
            }
            out[i] = r & 255;
        }
    } else {
        out[0] = src[0]; out[1] = src[1]; out[2] = src[2];
    }
    if (px->col_upd) { dst[0] = (uint8_t)out[0]; dst[1] = (uint8_t)out[1]; dst[2] = (uint8_t)out[2]; }
    if (px->alpha_upd) dst[3] = (uint8_t)sa;
}

static inline int depth_test(const PixelCfg* px, int x, int y, float depth)
{
    uint32_t z = (uint32_t)(depth < 0.0f ? 0.0f : (depth > 1.0f ? 16777215.0f : depth * 16777215.0f));
    uint32_t cur = g_efb_z[y][x];
    int pass;
    if (!px->z_en) return 1;
    switch (px->z_func) {
    case 0: pass = 0; break; case 1: pass = z < cur; break; case 2: pass = z == cur; break; case 3: pass = z <= cur; break;
    case 4: pass = z > cur; break; case 5: pass = z != cur; break; case 6: pass = z >= cur; break; default: pass = 1; break;
    }
    if (pass && px->z_upd) g_efb_z[y][x] = z;
    return pass;
}

static inline void shade(const DrawCmd* D, int x, int y, const int col[2][4], const float tex[8][3], float depth)
{
    uint8_t out[4];
    int alpha_ok = 1;
    /* Z before texturing (PE_CONTROL ztop) or after: order matters only for
     * alpha-tested pixels; test late unless ztop is set. */
    if (D->px.ztop && !depth_test(&D->px, x, y, depth)) { g_rej_depth++; return; }
    tev_pixel(&D->tev, col, tex, out, &alpha_ok);
    if (!alpha_ok) { g_rej_alpha++; return; }
    if (!D->px.ztop && !depth_test(&D->px, x, y, depth)) { g_rej_depth++; return; }
    blend_pixel(&D->px, x, y, out);
    g_pixels++;
}

/* Plane equation of a value linear in screen space: v = a*x + b*y + c. */
typedef struct { float a, b, c; } Plane;

static Plane plane_of(const Vertex* v0, const Vertex* v1, const Vertex* v2, float p0, float p1, float p2, float inv_area)
{
    Plane P;
    float dx1 = v1->sx - v0->sx, dy1 = v1->sy - v0->sy, dx2 = v2->sx - v0->sx, dy2 = v2->sy - v0->sy;
    float dp1 = p1 - p0, dp2 = p2 - p0;
    P.a = (dp1 * dy2 - dp2 * dy1) * inv_area;
    P.b = (dp2 * dx1 - dp1 * dx2) * inv_area;
    P.c = p0 - P.a * v0->sx - P.b * v0->sy;
    return P;
}

#define MAX_ATTR (2 + 8 + 8 * 3) /* depth, 1/w, two colours, eight texcoords */

static void raster_triangle(const DrawCmd* D, const Vertex* a, const Vertex* b, const Vertex* c)
{
    const Rect* sc = &D->rc.scissor;
    float area = (b->sx - a->sx) * (c->sy - a->sy) - (c->sx - a->sx) * (b->sy - a->sy);
    unsigned cull = D->rc.cull;
    int minx, miny, maxx, maxy, x, y;
    float inv_area;
    Plane e0, e1, e2;                 /* barycentric weights, positive inside */
    Plane attr[MAX_ATTR];             /* perspective-corrected attributes (value/w) */
    int nattr = 0, ci[2], ti[8], di, wi;
    unsigned i, k;
    const Vertex* v[3];

    if (area == 0.0f) return;
    if (g_cull_flip) area = -area;
    if ((cull == 1 && area < 0.0f) || (cull == 2 && area > 0.0f) || cull == 3) return; /* back = negative here */
    if (g_cull_flip) area = -area;

    if (g_debug && t_tid <= 1 && g_tris <= 8)
        fprintf(stderr, "[gxr] tri (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) area %.1f scissor %d,%d-%d,%d\n",
                a->sx, a->sy, a->depth, b->sx, b->sy, b->depth, c->sx, c->sy, c->depth, area, sc->x0, sc->y0, sc->x1, sc->y1);
    minx = (int)floorf(fminf(a->sx, fminf(b->sx, c->sx)));
    maxx = (int)ceilf(fmaxf(a->sx, fmaxf(b->sx, c->sx)));
    miny = (int)floorf(fminf(a->sy, fminf(b->sy, c->sy)));
    maxy = (int)ceilf(fmaxf(a->sy, fmaxf(b->sy, c->sy)));
    if (minx < sc->x0) minx = sc->x0;
    if (miny < sc->y0) miny = sc->y0;
    if (maxx > sc->x1) maxx = sc->x1;
    if (maxy > sc->y1) maxy = sc->y1;
    if (minx > maxx || miny > maxy) return;

    /* Orient so the weights are positive inside. */
    v[0] = a; v[1] = b; v[2] = c;
    if (area < 0.0f) { v[1] = c; v[2] = b; area = -area; }
    inv_area = 1.0f / area;
    e0 = plane_of(v[0], v[1], v[2], 1.0f, 0.0f, 0.0f, inv_area);
    e1 = plane_of(v[0], v[1], v[2], 0.0f, 1.0f, 0.0f, inv_area);
    e2 = plane_of(v[0], v[1], v[2], 0.0f, 0.0f, 1.0f, inv_area);

    {
        float iw0 = v[0]->w != 0.0f ? 1.0f / v[0]->w : 1.0f;
        float iw1 = v[1]->w != 0.0f ? 1.0f / v[1]->w : 1.0f;
        float iw2 = v[2]->w != 0.0f ? 1.0f / v[2]->w : 1.0f;
        di = nattr; attr[nattr++] = plane_of(v[0], v[1], v[2], v[0]->depth, v[1]->depth, v[2]->depth, inv_area);
        wi = nattr; attr[nattr++] = plane_of(v[0], v[1], v[2], iw0, iw1, iw2, inv_area);
        for (i = 0; i < 2; i++) {
            const float* c0 = &v[0]->col[i].r; const float* c1 = &v[1]->col[i].r; const float* c2 = &v[2]->col[i].r;
            ci[i] = nattr;
            if (!((D->nchan >> i) & 1)) continue;
            for (k = 0; k < 4; k++)
                attr[nattr++] = plane_of(v[0], v[1], v[2], c0[k] * iw0, c1[k] * iw1, c2[k] * iw2, inv_area);
        }
        for (i = 0; i < 8; i++) {
            ti[i] = -1;
            if (!((D->ntex >> i) & 1)) continue;
            ti[i] = nattr;
            for (k = 0; k < 3; k++)
                attr[nattr++] = plane_of(v[0], v[1], v[2], v[0]->tex[i][k] * iw0, v[1]->tex[i][k] * iw1, v[2]->tex[i][k] * iw2, inv_area);
        }
    }

    for (y = miny; y <= maxy; y++) {
        float py = (float)y + 0.5f;
        float av[MAX_ATTR];
        float px0;
        int n, xs = minx, xe = maxx;
        if (g_nthreads > 1 && (unsigned)y % (unsigned)g_nthreads != (unsigned)(t_tid - 1)) continue;
        /* The row's span: each weight w = a*x + b*y + c must be >= 0. */
        {
            const Plane* e[3] = {&e0, &e1, &e2};
            int j;
            for (j = 0; j < 3; j++) {
                float base = e[j]->b * py + e[j]->c; /* w at x = 0 */
                if (e[j]->a > 0.0f) { int lim = (int)ceilf(-base / e[j]->a - 0.5f); if (lim > xs) xs = lim; }
                else if (e[j]->a < 0.0f) { int lim = (int)floorf(-base / e[j]->a - 0.5f); if (lim < xe) xe = lim; }
                else if (base < 0.0f) { xs = xe + 1; break; }
            }
        }
        if (xs > xe) continue;
        px0 = (float)xs + 0.5f;
        for (n = 0; n < nattr; n++) av[n] = attr[n].a * px0 + attr[n].b * py + attr[n].c;
        for (x = xs; x <= xe; x++) {
            float w = av[wi] != 0.0f ? 1.0f / av[wi] : 0.0f;
            float w255 = w * 255.0f;
            int col[2][4];
            float tex[8][3];
            for (i = 0; i < 2; i++) {
                if (!((D->nchan >> i) & 1)) { col[i][0] = col[i][1] = col[i][2] = col[i][3] = 0; continue; }
                for (k = 0; k < 4; k++) {
                    int cv = (int)(av[ci[i] + k] * w255 + 0.5f);
                    col[i][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv);
                }
            }
            for (i = 0; i < 8; i++) {
                if (ti[i] < 0) continue;
                tex[i][0] = av[ti[i]] * w; tex[i][1] = av[ti[i] + 1] * w; tex[i][2] = av[ti[i] + 2] * w;
            }
            shade(D, x, y, col, tex, av[di]);
            for (n = 0; n < nattr; n++) av[n] += attr[n].a;
        }
    }
}

static void raster_line(const DrawCmd* D, const Vertex* a, const Vertex* b)
{
    const Rect* sc = &D->rc.scissor;
    float dx = b->sx - a->sx, dy = b->sy - a->sy;
    float len = fmaxf(fabsf(dx), fabsf(dy));
    int n = (int)ceilf(len), i;
    unsigned t, k;
    g_lines++;
    if (n < 1) n = 1;
    for (i = 0; i <= n; i++) {
        float f = (float)i / (float)n;
        int x = (int)floorf(a->sx + dx * f), y = (int)floorf(a->sy + dy * f);
        int col[2][4];
        float tex[8][3];
        if (x < sc->x0 || x > sc->x1 || y < sc->y0 || y > sc->y1) continue;
        for (t = 0; t < 2; t++) {
            const float* ca = &a->col[t].r; const float* cb = &b->col[t].r;
            for (k = 0; k < 4; k++) {
                int cv = (int)((ca[k] + (cb[k] - ca[k]) * f) * 255.0f + 0.5f);
                col[t][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv);
            }
        }
        for (t = 0; t < 8; t++)
            for (k = 0; k < 3; k++) tex[t][k] = a->tex[t][k] + (b->tex[t][k] - a->tex[t][k]) * f;
        shade(D, x, y, col, tex, a->depth + (b->depth - a->depth) * f);
    }
}

static void raster_point(const DrawCmd* D, const Vertex* a)
{
    const Rect* sc = &D->rc.scissor;
    int x = (int)floorf(a->sx), y = (int)floorf(a->sy);
    int col[2][4];
    unsigned t, k;
    g_points++;
    if (x < sc->x0 || x > sc->x1 || y < sc->y0 || y > sc->y1) return;
    for (t = 0; t < 2; t++) {
        const float* ca = &a->col[t].r;
        for (k = 0; k < 4; k++) { int cv = (int)(ca[k] * 255.0f + 0.5f); col[t][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv); }
    }
    shade(D, x, y, col, a->tex, a->depth);
}

/* ---- clipping ----------------------------------------------------------- */

static void lerp_vertex(const Vertex* a, const Vertex* b, float t, Vertex* o)
{
    unsigned i, k;
    o->x = a->x + (b->x - a->x) * t;
    o->y = a->y + (b->y - a->y) * t;
    o->z = a->z + (b->z - a->z) * t;
    o->w = a->w + (b->w - a->w) * t;
    for (i = 0; i < 2; i++) {
        o->col[i].r = a->col[i].r + (b->col[i].r - a->col[i].r) * t;
        o->col[i].g = a->col[i].g + (b->col[i].g - a->col[i].g) * t;
        o->col[i].b = a->col[i].b + (b->col[i].b - a->col[i].b) * t;
        o->col[i].a = a->col[i].a + (b->col[i].a - a->col[i].a) * t;
    }
    for (i = 0; i < 8; i++) for (k = 0; k < 3; k++) o->tex[i][k] = a->tex[i][k] + (b->tex[i][k] - a->tex[i][k]) * t;
}

/* Clip space on this hardware: -w <= z <= 0 is visible. Clip a polygon
 * against the near plane (z + w >= 0) and w > 0; the far side and the
 * guard band are handled by the scissor. */
static unsigned clip_polygon(Vertex* in, unsigned n, Vertex* out)
{
    Vertex tmp[16];
    unsigned m = 0, i;
    for (i = 0; i < n; i++) {
        const Vertex* a = &in[i];
        const Vertex* b = &in[(i + 1) % n];
        float da = a->z + a->w, db = b->z + b->w;
        if (da >= 0.0f) tmp[m++] = *a;
        if ((da >= 0.0f) != (db >= 0.0f)) {
            float t = da / (da - db);
            lerp_vertex(a, b, t, &tmp[m++]);
        }
        if (m >= 14) break;
    }
    n = m; m = 0;
    for (i = 0; i < n; i++) {
        const Vertex* a = &tmp[i];
        const Vertex* b = &tmp[(i + 1) % n];
        float da = a->w - 1e-5f, db = b->w - 1e-5f;
        if (da >= 0.0f) out[m++] = *a;
        if ((da >= 0.0f) != (db >= 0.0f)) {
            float t = da / (da - db);
            lerp_vertex(a, b, t, &out[m++]);
        }
        if (m >= 14) break;
    }
    return m;
}

static void emit_triangle(const DrawCmd* D, const Vertex* a, const Vertex* b, const Vertex* c)
{
    Vertex in[3], out[16];
    unsigned n, i;
    int inside = (a->z + a->w >= 0.0f && a->w > 0.0f) && (b->z + b->w >= 0.0f && b->w > 0.0f) && (c->z + c->w >= 0.0f && c->w > 0.0f);
    if (inside) {
        in[0] = *a; in[1] = *b; in[2] = *c;
        for (i = 0; i < 3; i++) to_screen(&D->rc, &in[i]);
        raster_triangle(D, &in[0], &in[1], &in[2]);
        return;
    }
    in[0] = *a; in[1] = *b; in[2] = *c;
    n = clip_polygon(in, 3, out);
    if (n < 3) {
        if (t_tid <= 1) g_clipped++;
        if (g_debug && t_tid <= 1 && g_clipped <= 6)
            fprintf(stderr, "[gxr] clipped: (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f)\n",
                    a->x, a->y, a->z, a->w, b->x, b->y, b->z, b->w, c->x, c->y, c->z, c->w);
        return;
    }
    for (i = 0; i < n; i++) to_screen(&D->rc, &out[i]);
    for (i = 1; i + 1 < n; i++) raster_triangle(D, &out[0], &out[i], &out[i + 1]);
}

static void run_copy(const DrawCmd* D);
static void workers_start(void);
void gxr_flush(void);

static void draw_command(const DrawCmd* D)
{
    const Vertex* v = D->v;
    unsigned count = D->count, i;
    if (D->kind == 1) { run_copy(D); return; }
    switch (D->prim) {
    case 0x80: /* quads */
        for (i = 0; i + 3 < count; i += 4) {
            emit_triangle(D, &v[i], &v[i + 1], &v[i + 2]);
            emit_triangle(D, &v[i], &v[i + 2], &v[i + 3]);
        }
        break;
    case 0x90: /* triangles */
        for (i = 0; i + 2 < count; i += 3) emit_triangle(D, &v[i], &v[i + 1], &v[i + 2]);
        break;
    case 0x98: /* strip */
        for (i = 2; i < count; i++) {
            if (i & 1) emit_triangle(D, &v[i - 1], &v[i - 2], &v[i]);
            else emit_triangle(D, &v[i - 2], &v[i - 1], &v[i]);
        }
        break;
    case 0xA0: /* fan */
        for (i = 2; i < count; i++) emit_triangle(D, &v[0], &v[i - 1], &v[i]);
        break;
    case 0xA8: /* lines: one thread only */
        if (t_tid > 1) break;
        for (i = 0; i + 1 < count; i += 2) {
            Vertex a = v[i], b = v[i + 1];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(&D->rc, &a); to_screen(&D->rc, &b);
            raster_line(D, &a, &b);
        }
        break;
    case 0xB0: /* line strip */
        if (t_tid > 1) break;
        for (i = 1; i < count; i++) {
            Vertex a = v[i - 1], b = v[i];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(&D->rc, &a); to_screen(&D->rc, &b);
            raster_line(D, &a, &b);
        }
        break;
    case 0xB8: /* points */
        if (t_tid > 1) break;
        for (i = 0; i < count; i++) {
            Vertex a = v[i];
            if (a.w <= 0.0f) continue;
            to_screen(&D->rc, &a);
            raster_point(D, &a);
        }
        break;
    default: break;
    }
}

/* ---- the queue and its workers ----------------------------------------- */

static DrawCmd* g_queue;
static volatile LONG g_q_tail;                 /* commands published */
static volatile LONG g_cursor[MAX_THREADS + 1]; /* per worker: next command to run */
static uint8_t* g_arena;
static size_t g_arena_used;
static int g_workers; /* worker threads; the main thread (tid 0) only produces */

#ifdef _WIN32
static DWORD WINAPI worker(LPVOID arg)
{
    int id = (int)(intptr_t)arg; /* 1..workers */
    t_tid = id;
    for (;;) {
        unsigned spins = 0;
        while (g_cursor[id] >= g_q_tail) { if (++spins > 4000) { Sleep(0); spins = 0; } else YieldProcessor(); }
        draw_command(&g_queue[g_cursor[id]]);
        InterlockedIncrement(&g_cursor[id]);
    }
}
#endif

static void workers_start(void)
{
    const char* env = getenv("SOA_THREADS");
    int n = env ? atoi(env) : 0, i;
    g_queue = (DrawCmd*)malloc(sizeof(DrawCmd) * QUEUE_CAP);
    g_arena = (uint8_t*)malloc(ARENA_BYTES);
#ifdef _WIN32
    if (n <= 0) {
        SYSTEM_INFO si;
        GetSystemInfo(&si);
        n = (int)si.dwNumberOfProcessors / 2;
        if (n < 1) n = 1;
    }
    if (n > MAX_THREADS) n = MAX_THREADS;
    for (i = 1; i <= n; i++) {
        HANDLE h = CreateThread(NULL, 0, worker, (LPVOID)(intptr_t)i, 0, NULL);
        if (!h) { n = i - 1; break; }
        CloseHandle(h);
    }
#else
    n = 0;
#endif
    g_workers = n;
    g_nthreads = n > 0 ? n : 1;
    fprintf(stderr, "[gxr] rasterizing on %d worker thread%s\n", n, n == 1 ? "" : "s");
}

static int g_pending_n; /* queued copy destinations (defined with the copies below) */
static int g_started;   /* worker pool created */

/* Wait for every queued draw to finish, then recycle the queue. */
void gxr_flush(void)
{
    int i;
    if (!g_queue) return;
    for (i = 1; i <= g_workers; i++)
        while (g_cursor[i] < g_q_tail) YieldProcessor();
    g_q_tail = 0;
    for (i = 1; i <= g_workers; i++) g_cursor[i] = 0;
    g_arena_used = 0;
    g_pending_n = 0;
    tex_graveyard_empty();
}

static void gxr_draw_inner(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize);

void gxr_draw(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize)
{
    TIMED(T_DRAW, gxr_draw_inner(s, op, count, verts, vsize));
}

static void gxr_draw_inner(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize)
{
    const uint32_t* xf = gx_xf_regs();
    const uint32_t* bp = gx_bp_regs();
    unsigned prim = op & 0xF8, vat = op & 7, i;
    const uint8_t* p = verts;
    Vertex* v;
    DrawCmd* D;
    (void)vsize;
    if (!gxr_enabled() || count == 0) return;
    if (g_draw_limit && ++g_draw_no > g_draw_limit) return; /* SOA_GXR_DRAWS=N: stop after N draws */
    /* Headless snapshots (SOA_FRAMES=N): only the frames being written are
     * worth rasterizing; the game then runs at full speed between them. */
    if (g_frames_every && !g_png_path[0] && (g_frame_no % g_frames_every) != 0) return;
    if (!g_started) { g_started = 1; workers_start(); }
    tex_set_memory(s);

    if (g_q_tail >= QUEUE_CAP || g_arena_used + sizeof(Vertex) * count > ARENA_BYTES || tex_graveyard_full()) gxr_flush();
    v = (Vertex*)(g_arena + g_arena_used);
    g_arena_used += (sizeof(Vertex) * count + 15) & ~(size_t)15;
    D = &g_queue[g_q_tail];
    D->kind = 0;
    TIMED(T_PREPARE, tev_prepare(bp, &D->tev));
    pixel_prepare(bp, &D->px);
    raster_prepare(xf, bp, &D->rc);
    D->ntex = D->tev.used_tex & ((1u << (xf[0x103F] & 15)) - 1u);
    D->nchan = D->tev.used_chan;
    D->prim = prim; D->count = count; D->v = v;
    for (i = 0; i < count; i++) {
        VertexIn in;
        p = decode_vertex(s, p, vat, &in);
        transform(s, &in, &v[i]);
    }
    if (prim <= 0xA0) g_tris += prim == 0x80 ? (count / 4) * 2 : (prim == 0x90 ? count / 3 : (count >= 2 ? count - 2 : 0));
    if (g_workers > 0) {
        InterlockedIncrement(&g_q_tail); /* publish: the workers pick it up */
    } else {
        t_tid = 1;
        draw_command(D);
        g_q_tail = 0;
        g_arena_used = 0;
    }
}

/* ---- EFB copy and clear ---------------------------------------------------- */

/* Rows this thread owns: every Nth when workers exist, all otherwise. */
static inline int my_row(int y)
{
    return g_nthreads <= 1 || (unsigned)y % (unsigned)g_nthreads == (unsigned)(t_tid - 1);
}

static void efb_clear(uint32_t ar, uint32_t gb, uint32_t zreg, int x0, int y0, int w, int h)
{
    uint32_t z = zreg & 0xFFFFFFu;
    uint8_t col[4] = {(uint8_t)(ar & 0xFF), (uint8_t)((gb >> 8) & 0xFF), (uint8_t)(gb & 0xFF), (uint8_t)((ar >> 8) & 0xFF)};
    int x, y;
    for (y = y0; y < y0 + h && y < EFB_H; y++) {
        if (y < 0 || !my_row(y)) continue;
        for (x = x0; x < x0 + w && x < EFB_W; x++) {
            if (x < 0) continue;
            memcpy(g_efb[y][x], col, 4);
            g_efb_z[y][x] = z;
        }
    }
}

/* Write an EFB rectangle into memory as a texture (GXCopyTex). Tiled like
 * the formats the sampler decodes. */
static void copy_to_texture(CpuState* s, uint32_t dest_reg, uint32_t v, int x0, int y0, int w, int h)
{
    uint32_t dest = (dest_reg & 0x1FFFFFu) << 5;
    unsigned tpf = (v >> 3) & 15;
    unsigned fmt = tpf / 2 + (tpf & 1) * 8; /* EFBCopyFormat */
    int intensity = (v >> 15) & 1, half = (v >> 9) & 1;
    int ow = half ? w / 2 : w, oh = half ? h / 2 : h;
    int x, y;
    unsigned tw, th, bpt;
    uint8_t* base;

    /* map copy formats onto texture formats; anything else is left alone
     * rather than written at a guessed size */
    unsigned texfmt, chan_a = 0, chan_b = 3; /* source channels for single/dual-channel copies */
    if (intensity) texfmt = fmt == 0 ? 0 : fmt == 1 ? 1 : fmt == 2 ? 2 : fmt == 3 ? 3 : 99;
    else switch (fmt) {
    case 0: texfmt = 0; break;                       /* R4 */
    case 1: case 8: texfmt = 1; break;               /* R8 */
    case 9: texfmt = 1; chan_a = 1; break;           /* G8 */
    case 10: texfmt = 1; chan_a = 2; break;          /* B8 */
    case 7: texfmt = 1; chan_a = 3; break;           /* A8 */
    case 2: texfmt = 2; break;                       /* RA4 */
    case 3: texfmt = 3; break;                       /* RA8 */
    case 11: texfmt = 3; chan_a = 0; chan_b = 1; break; /* RG8: like IA8 with (g, r)? keep (b=g, a=r) */
    case 12: texfmt = 3; chan_a = 1; chan_b = 2; break; /* GB8 */
    case 4: texfmt = 4; break;
    case 5: texfmt = 5; break;
    case 6: texfmt = 6; break;
    default: texfmt = 99; break;
    }
    if (g_debug && g_copies_tex < 16)
        fprintf(stderr, "[gxr] copy to texture: dest %08X %dx%d from (%d,%d) fmt %u intensity %d half %d -> texfmt %u" "\n",
                dest, w, h, x0, y0, fmt, intensity, half, texfmt);
    if (texfmt == 99) { g_copies_tex++; return; }

    switch (texfmt) {
    case 0: tw = 8; th = 8; bpt = 32; break;
    case 1: case 2: tw = 8; th = 4; bpt = 32; break;
    case 3: case 4: case 5: tw = 4; th = 4; bpt = 32; break;
    default: tw = 4; th = 4; bpt = 64; texfmt = 6; break;
    }
    if ((dest & MEM_MASK) + (size_t)((oh + th - 1) / th) * ((ow + tw - 1) / tw) * bpt > MEM1_SIZE) return;
    base = mem_ptr(s, dest | 0x80000000u);
    for (y = 0; y < oh; y++) {
        if (!my_row(half ? 2 * y : y) && !(half && my_row(2 * y + 1))) continue;
        if (half && !my_row(2 * y)) continue; /* half-scale rows are flushed before queueing */
        for (x = 0; x < ow; x++) {
            int sx = x0 + (half ? 2 * x : x), sy = y0 + (half ? 2 * y : y);
            uint8_t px[4] = {0, 0, 0, 255};
            unsigned tiles_w = (ow + tw - 1) / tw;
            uint8_t* tile = base + ((y / th) * tiles_w + x / tw) * bpt;
            unsigned ix = x % tw, iy = y % th;
            unsigned I;
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) {
                if (half && sx + 1 < EFB_W && sy + 1 < EFB_H) {
                    int k;
                    for (k = 0; k < 4; k++)
                        px[k] = (uint8_t)((g_efb[sy][sx][k] + g_efb[sy][sx + 1][k] + g_efb[sy + 1][sx][k] + g_efb[sy + 1][sx + 1][k]) / 4);
                } else memcpy(px, g_efb[sy][sx], 4);
            }
            if (intensity) {
                I = (unsigned)(0.257f * px[0] + 0.504f * px[1] + 0.098f * px[2] + 16.0f);
                if (I > 255) I = 255;
            } else {
                I = px[chan_a]; /* single-channel copies take that channel; dual ones pair it with chan_b */
                if (texfmt == 2 || texfmt == 3) px[3] = px[chan_b];
            }
            switch (texfmt) {
            case 0: { uint8_t* b = &tile[iy * 4 + ix / 2]; unsigned n = I >> 4; if (ix & 1) *b = (uint8_t)((*b & 0xF0) | n); else *b = (uint8_t)((*b & 0x0F) | (n << 4)); break; }
            case 1: tile[iy * 8 + ix] = (uint8_t)I; break;
            case 2: tile[iy * 8 + ix] = (uint8_t)((px[3] & 0xF0) | (I >> 4)); break;
            case 3: tile[(iy * 4 + ix) * 2] = px[3]; tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)I; break;
            case 4: { unsigned c = ((px[0] >> 3) << 11) | ((px[1] >> 2) << 5) | (px[2] >> 3); tile[(iy * 4 + ix) * 2] = (uint8_t)(c >> 8); tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)c; break; }
            case 5: { unsigned c;
                if (px[3] >= 224) c = 0x8000 | ((px[0] >> 3) << 10) | ((px[1] >> 3) << 5) | (px[2] >> 3);
                else c = ((px[3] >> 5) << 12) | ((px[0] >> 4) << 8) | ((px[1] >> 4) << 4) | (px[2] >> 4);
                tile[(iy * 4 + ix) * 2] = (uint8_t)(c >> 8); tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)c; break; }
            default:
                tile[(iy * 4 + ix) * 2] = px[3]; tile[(iy * 4 + ix) * 2 + 1] = px[0];
                tile[32 + (iy * 4 + ix) * 2] = px[1]; tile[32 + (iy * 4 + ix) * 2 + 1] = px[2];
                break;
            }
        }
    }
    g_copies_tex++;
}

static uint8_t g_screen[EFB_H][EFB_W][4]; /* the last frame copied out, RGBA */
static int g_screen_w = EFB_W, g_screen_h = 480;
static volatile LONG g_frames_presented; /* copies to the screen completed by all rows */

static void copy_to_screen(int x0, int y0, int w, int h)
{
    int x, y;
    for (y = 0; y < h && y < EFB_H; y++) {
        int sy = y0 + y;
        if (!my_row(y)) continue;
        for (x = 0; x < w && x < EFB_W; x++) {
            int sx = x0 + x;
            uint8_t* o = g_screen[y][x];
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) { memcpy(o, g_efb[sy][sx], 3); o[3] = 255; }
            else { o[0] = o[1] = o[2] = 0; o[3] = 255; }
        }
    }
}

static void run_copy(const DrawCmd* D)
{
    int x0 = (int)(D->cp_tl & 0x3FF), y0 = (int)((D->cp_tl >> 10) & 0x3FF);
    int w = (int)(D->cp_wh & 0x3FF) + 1, h = (int)((D->cp_wh >> 10) & 0x3FF) + 1;
    if (D->cp_v & 0x4000u) copy_to_screen(x0, y0, w, h);
    else copy_to_texture(D->s, D->cp_dest, D->cp_v, x0, y0, w, h);
    if (D->cp_v & 0x800u) efb_clear(D->cp_ar, D->cp_gb, D->cp_z, x0, y0, w, h);
    if (D->cp_v & 0x4000u) InterlockedIncrement(&g_frames_presented);
}

/* Copy destinations still in the queue: a texture decoded from one of
 * them must wait for it. */
typedef struct { uint32_t addr, bytes; } Pending;
static Pending g_pending[QUEUE_CAP];
static int g_pending_n;

void gxr_texture_hazard(uint32_t addr, uint32_t bytes)
{
    int i;
    addr &= MEM_MASK;
    for (i = 0; i < g_pending_n; i++)
        if (addr < g_pending[i].addr + g_pending[i].bytes && addr + bytes > g_pending[i].addr) { gxr_flush(); return; }
}

const uint8_t* gxr_screen(int* w, int* h)
{
    *w = g_screen_w; *h = g_screen_h;
    return &g_screen[0][0][0];
}

static void write_frame_png(const char* path, int w, int h)
{
    if (!png_write_rgba(path, &g_screen[0][0][0], w, h, EFB_W * 4)) fprintf(stderr, "[gxr] cannot write %s\n", path);
    else fprintf(stderr, "[gxr] wrote %s (%dx%d)\n", path, w, h);
}

static void enqueue_copy(CpuState* s, const uint32_t* bp, uint32_t v)
{
    DrawCmd* D;
    int x0 = (int)(bp[0x49] & 0x3FF), y0 = (int)((bp[0x49] >> 10) & 0x3FF);
    int w = (int)(bp[0x4A] & 0x3FF) + 1, h = (int)((bp[0x4A] >> 10) & 0x3FF) + 1;
    int to_screen = (v & 0x4000u) != 0, half = (v >> 9) & 1;
    if (!g_started) { g_started = 1; workers_start(); }
    tex_set_memory(s);
    if (half) gxr_flush(); /* a half-scale copy reads rows other workers own */
    if (g_q_tail >= QUEUE_CAP) gxr_flush();
    D = &g_queue[g_q_tail];
    D->kind = 1; D->s = s;
    D->cp_v = v; D->cp_tl = bp[0x49]; D->cp_wh = bp[0x4A]; D->cp_dest = bp[0x4B]; D->cp_stride = bp[0x4D];
    D->cp_ar = bp[0x4F]; D->cp_gb = bp[0x50]; D->cp_z = bp[0x51];
    if (to_screen) { g_screen_w = w > EFB_W ? EFB_W : w; g_screen_h = h > EFB_H ? EFB_H : h; g_copies_xfb++; }
    else {
        if (g_pending_n < QUEUE_CAP) {
            g_pending[g_pending_n].addr = ((bp[0x4B] & 0x1FFFFFu) << 5) & MEM_MASK;
            g_pending[g_pending_n].bytes = (uint32_t)w * (uint32_t)h * 4u; /* generous */
            g_pending_n++;
        }
        g_copies_tex++;
    }
    if (g_workers > 0) InterlockedIncrement(&g_q_tail);
    else { t_tid = 1; draw_command(D); g_q_tail = 0; g_arena_used = 0; }

    if (to_screen) {
        char path[512];
        int want = 0;
        if (g_png_path[0]) { snprintf(path, sizeof path, "%s", g_png_path); want = 1; }
        else if (g_frames_every && (g_frame_no % g_frames_every) == 0) { snprintf(path, sizeof path, "build/frames/%04u.png", g_frame_no); want = 1; }
        g_frame_no++;
        if (want) { gxr_flush(); TIMED(T_PNG, write_frame_png(path, g_screen_w, g_screen_h)); }
    }
}

void gxr_bp_written(CpuState* s, uint32_t reg, uint32_t v)
{
    const uint32_t* bp = gx_bp_regs();
    if (reg >= 0xE0 && reg <= 0xE7) { tev_register_written(reg, v); return; }
    if (reg == 0x65) { /* TLUT load (GXLoadTlut): source from 0x64, tmem address and size here */
        uint32_t src = (bp[0x64] & 0x1FFFFFu) << 5;
        uint32_t tmem = (v & 0x3FFu) << 9, bytes = ((v >> 10) & 0x7FFu) << 5;
        tmem_load_tlut(s, src | 0x80000000u, tmem, bytes);
        return;
    }
    if (reg == 0x52 && gxr_enabled()) { /* EFB copy (GXCopyTex / GXCopyDisp) */
        TIMED(T_COPY, enqueue_copy(s, bp, v));
        return;
    }
    if (reg == 0x45 && (v & 2) && gxr_enabled()) gxr_flush(); /* GXDrawDone: the CPU may read results now */
}

void gxr_report(void)
{
    /* No flush: the watchdog thread reports while the main thread produces. */
    if (!gxr_enabled()) return;
    fprintf(stderr, "[gxr] time: draw %.2fs (prepare %.2fs, decode %.2fs), copies %.2fs, png %.2fs\n",
            g_gxr_time[T_DRAW], g_gxr_time[T_PREPARE], g_gxr_time[T_DECODE], g_gxr_time[T_COPY], g_gxr_time[T_PNG]);
    {
        uint64_t px = 0, rd = 0, ra = 0;
        int i;
        for (i = 0; i < MAX_THREADS; i++) { px += g_pixels_t[i]; rd += g_rej_depth_t[i]; ra += g_rej_alpha_t[i]; }
    fprintf(stderr, "[gxr] %llu triangles, %llu lines, %llu points; %llu pixels shaded (%llu outside, %llu failed alpha, %llu failed depth); %llu clipped away; %llu bad vertex refs; %llu texture copies, %llu screen copies\n",
            (unsigned long long)g_tris, (unsigned long long)g_lines, (unsigned long long)g_points,
            (unsigned long long)px, (unsigned long long)g_rej_bary, (unsigned long long)ra, (unsigned long long)rd, (unsigned long long)g_clipped, (unsigned long long)g_verts_bad,
            (unsigned long long)g_copies_tex, (unsigned long long)g_copies_xfb);
    }
}
