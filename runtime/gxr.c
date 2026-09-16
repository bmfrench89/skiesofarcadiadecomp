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

uint8_t g_efb[EFB_H][EFB_W][4];
uint32_t g_efb_z[EFB_H][EFB_W];

static int g_enabled = -1;
static unsigned g_frames_every, g_frame_no;
static char g_png_path[512];
static uint64_t g_tris, g_pixels, g_lines, g_points, g_clipped, g_verts_bad;
static uint64_t g_copies_tex, g_copies_xfb, g_rej_depth, g_rej_alpha, g_rej_bary;
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

/* ---- viewport, scissor -------------------------------------------------- */

typedef struct { int x0, y0, x1, y1; } Rect;

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

static void to_screen(const uint32_t* xf, const uint32_t* bp, Vertex* v)
{
    float wd = xff(xf, 0x101A), ht = xff(xf, 0x101B), zrange = xff(xf, 0x101C);
    float xorig = xff(xf, 0x101D), yorig = xff(xf, 0x101E), farz = xff(xf, 0x101F);
    uint32_t off = bp[0x59];
    float xoff = (float)((off & 0x3FF) * 2), yoff = (float)(((off >> 10) & 0x3FF) * 2);
    float iw = v->w != 0.0f ? 1.0f / v->w : 0.0f;
    v->sx = xorig - xoff + v->x * iw * wd;
    v->sy = yorig - yoff + v->y * iw * ht;
    v->depth = (farz + v->z * iw * zrange) / 16777216.0f;
}

/* ---- rasterization ------------------------------------------------------ */

static void blend_pixel(const uint32_t* bp, int x, int y, const uint8_t src[4])
{
    uint32_t cmode = bp[0x41], cmode1 = bp[0x42];
    uint8_t* dst = g_efb[y][x];
    int blend_en = cmode & 1, logic_en = (cmode >> 1) & 1, col_upd = (cmode >> 3) & 1, alpha_upd = (cmode >> 4) & 1;
    unsigned dfac = (cmode >> 5) & 7, sfac = (cmode >> 8) & 7, subtract = (cmode >> 11) & 1, lop = (cmode >> 12) & 15;
    int out[4], i;
    int sa = src[3], da = dst[3];
    if (cmode1 & 0x100) sa = (int)(cmode1 & 0xFF); /* constant alpha for the destination write */

    if (blend_en) {
        for (i = 0; i < 3; i++) {
            int sf, df, r;
            switch (sfac) {
            case 0: sf = 0; break; case 1: sf = 255; break; case 2: sf = dst[i]; break; case 3: sf = 255 - dst[i]; break;
            case 4: sf = src[3]; break; case 5: sf = 255 - src[3]; break; case 6: sf = da; break; default: sf = 255 - da; break;
            }
            switch (dfac) {
            case 0: df = 0; break; case 1: df = 255; break; case 2: df = src[i]; break; case 3: df = 255 - src[i]; break;
            case 4: df = src[3]; break; case 5: df = 255 - src[3]; break; case 6: df = da; break; default: df = 255 - da; break;
            }
            if (subtract) r = dst[i] - src[i];
            else r = (src[i] * sf + dst[i] * df + 127) / 255;
            out[i] = r < 0 ? 0 : (r > 255 ? 255 : r);
        }
    } else if (logic_en) {
        for (i = 0; i < 3; i++) {
            int sv = src[i], dv = dst[i], r;
            switch (lop) {
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
    if (col_upd) { dst[0] = (uint8_t)out[0]; dst[1] = (uint8_t)out[1]; dst[2] = (uint8_t)out[2]; }
    if (alpha_upd) dst[3] = (uint8_t)sa;
}

static int depth_test(const uint32_t* bp, int x, int y, float depth)
{
    uint32_t zmode = bp[0x40];
    uint32_t z = (uint32_t)(depth < 0.0f ? 0.0f : (depth > 1.0f ? 16777215.0f : depth * 16777215.0f));
    uint32_t cur = g_efb_z[y][x];
    int pass;
    if (!(zmode & 1)) return 1;
    switch ((zmode >> 1) & 7) {
    case 0: pass = 0; break; case 1: pass = z < cur; break; case 2: pass = z == cur; break; case 3: pass = z <= cur; break;
    case 4: pass = z > cur; break; case 5: pass = z != cur; break; case 6: pass = z >= cur; break; default: pass = 1; break;
    }
    if (pass && ((zmode >> 4) & 1)) g_efb_z[y][x] = z;
    return pass;
}

static void shade(const uint32_t* bp, int x, int y, const Color4 col[2], const float tex[8][3], float depth)
{
    uint8_t out[4];
    int alpha_ok = 1;
    /* Z before texturing (PE_CONTROL ztop) or after: order matters only for
     * alpha-tested pixels; test late unless ztop is set. */
    int ztop = (bp[0x43] >> 6) & 1;
    if (ztop && !depth_test(bp, x, y, depth)) { g_rej_depth++; return; }
    tev_pixel(bp, col, tex, out, &alpha_ok);
    if (!alpha_ok) { g_rej_alpha++; return; }
    if (!ztop && !depth_test(bp, x, y, depth)) { g_rej_depth++; return; }
    blend_pixel(bp, x, y, out);
    g_pixels++;
}

static void raster_triangle(const uint32_t* bp, const Vertex* a, const Vertex* b, const Vertex* c)
{
    Rect sc;
    float area = (b->sx - a->sx) * (c->sy - a->sy) - (c->sx - a->sx) * (b->sy - a->sy);
    unsigned cull = (bp[0] >> 14) & 3;
    int minx, miny, maxx, maxy, x, y;
    float ia, iwa, iwb, iwc;
    unsigned ntex = gx_xf_regs()[0x103F] & 15, i, k;

    if (area == 0.0f) return;
    if (g_cull_flip) area = -area;
    if ((cull == 1 && area < 0.0f) || (cull == 2 && area > 0.0f) || cull == 3) return; /* back = negative here */
    if (g_cull_flip) area = -area;
    g_tris++;

    scissor_rect(bp, &sc);
    if (g_debug && g_tris <= 8)
        fprintf(stderr, "[gxr] tri (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) area %.1f scissor %d,%d-%d,%d\n",
                a->sx, a->sy, a->depth, b->sx, b->sy, b->depth, c->sx, c->sy, c->depth, area, sc.x0, sc.y0, sc.x1, sc.y1);
    minx = (int)floorf(fminf(a->sx, fminf(b->sx, c->sx)));
    maxx = (int)ceilf(fmaxf(a->sx, fmaxf(b->sx, c->sx)));
    miny = (int)floorf(fminf(a->sy, fminf(b->sy, c->sy)));
    maxy = (int)ceilf(fmaxf(a->sy, fmaxf(b->sy, c->sy)));
    if (minx < sc.x0) minx = sc.x0;
    if (miny < sc.y0) miny = sc.y0;
    if (maxx > sc.x1) maxx = sc.x1;
    if (maxy > sc.y1) maxy = sc.y1;
    if (minx > maxx || miny > maxy) return;

    ia = 1.0f / area;
    iwa = a->w != 0.0f ? 1.0f / a->w : 1.0f;
    iwb = b->w != 0.0f ? 1.0f / b->w : 1.0f;
    iwc = c->w != 0.0f ? 1.0f / c->w : 1.0f;

    for (y = miny; y <= maxy; y++) {
        float py = (float)y + 0.5f;
        for (x = minx; x <= maxx; x++) {
            float px = (float)x + 0.5f;
            float w0 = ((b->sx - px) * (c->sy - py) - (c->sx - px) * (b->sy - py)) * ia;
            float w1 = ((c->sx - px) * (a->sy - py) - (a->sx - px) * (c->sy - py)) * ia;
            float w2 = 1.0f - w0 - w1;
            float pa, pb, pc, denom, depth;
            Color4 col[2];
            float tex[8][3];
            if (w0 < 0.0f || w1 < 0.0f || w2 < 0.0f) { g_rej_bary++; continue; }
            /* perspective-correct weights */
            pa = w0 * iwa; pb = w1 * iwb; pc = w2 * iwc;
            denom = pa + pb + pc;
            if (denom == 0.0f) continue;
            pa /= denom; pb /= denom; pc /= denom;
            depth = w0 * a->depth + w1 * b->depth + w2 * c->depth;
            for (i = 0; i < 2; i++) {
                col[i].r = pa * a->col[i].r + pb * b->col[i].r + pc * c->col[i].r;
                col[i].g = pa * a->col[i].g + pb * b->col[i].g + pc * c->col[i].g;
                col[i].b = pa * a->col[i].b + pb * b->col[i].b + pc * c->col[i].b;
                col[i].a = pa * a->col[i].a + pb * b->col[i].a + pc * c->col[i].a;
            }
            for (i = 0; i < 8; i++) {
                if (i >= ntex) { tex[i][0] = tex[i][1] = 0; tex[i][2] = 1; continue; }
                for (k = 0; k < 3; k++) tex[i][k] = pa * a->tex[i][k] + pb * b->tex[i][k] + pc * c->tex[i][k];
            }
            shade(bp, x, y, col, tex, depth);
        }
    }
}

static void raster_line(const uint32_t* bp, const Vertex* a, const Vertex* b)
{
    Rect sc;
    float dx = b->sx - a->sx, dy = b->sy - a->sy;
    float len = fmaxf(fabsf(dx), fabsf(dy));
    int n = (int)ceilf(len), i;
    unsigned ntex = gx_xf_regs()[0x103F] & 15, t, k;
    scissor_rect(bp, &sc);
    g_lines++;
    if (n < 1) n = 1;
    for (i = 0; i <= n; i++) {
        float f = (float)i / (float)n;
        int x = (int)floorf(a->sx + dx * f), y = (int)floorf(a->sy + dy * f);
        Color4 col[2];
        float tex[8][3];
        if (x < sc.x0 || x > sc.x1 || y < sc.y0 || y > sc.y1) continue;
        for (t = 0; t < 2; t++) {
            col[t].r = a->col[t].r + (b->col[t].r - a->col[t].r) * f;
            col[t].g = a->col[t].g + (b->col[t].g - a->col[t].g) * f;
            col[t].b = a->col[t].b + (b->col[t].b - a->col[t].b) * f;
            col[t].a = a->col[t].a + (b->col[t].a - a->col[t].a) * f;
        }
        for (t = 0; t < 8; t++) {
            if (t >= ntex) { tex[t][0] = tex[t][1] = 0; tex[t][2] = 1; continue; }
            for (k = 0; k < 3; k++) tex[t][k] = a->tex[t][k] + (b->tex[t][k] - a->tex[t][k]) * f;
        }
        shade(bp, x, y, col, tex, a->depth + (b->depth - a->depth) * f);
    }
}

static void raster_point(const uint32_t* bp, const Vertex* a)
{
    Rect sc;
    int x = (int)floorf(a->sx), y = (int)floorf(a->sy);
    scissor_rect(bp, &sc);
    g_points++;
    if (x < sc.x0 || x > sc.x1 || y < sc.y0 || y > sc.y1) return;
    shade(bp, x, y, a->col, a->tex, a->depth);
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
    /* near: z + w >= 0 */
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
    /* w > epsilon */
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

static void emit_triangle(const uint32_t* xf, const uint32_t* bp, const Vertex* a, const Vertex* b, const Vertex* c)
{
    Vertex in[3], out[16];
    unsigned n, i;
    int inside = (a->z + a->w >= 0.0f && a->w > 0.0f) && (b->z + b->w >= 0.0f && b->w > 0.0f) && (c->z + c->w >= 0.0f && c->w > 0.0f);
    if (inside) {
        in[0] = *a; in[1] = *b; in[2] = *c;
        for (i = 0; i < 3; i++) to_screen(xf, bp, &in[i]);
        raster_triangle(bp, &in[0], &in[1], &in[2]);
        return;
    }
    in[0] = *a; in[1] = *b; in[2] = *c;
    n = clip_polygon(in, 3, out);
    if (n < 3) {
        g_clipped++;
        if (g_debug && g_clipped <= 6)
            fprintf(stderr, "[gxr] clipped: (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f)" "\n",
                    a->x, a->y, a->z, a->w, b->x, b->y, b->z, b->w, c->x, c->y, c->z, c->w);
        return;
    }
    for (i = 0; i < n; i++) to_screen(xf, bp, &out[i]);
    for (i = 1; i + 1 < n; i++) raster_triangle(bp, &out[0], &out[i], &out[i + 1]);
}

/* ---- draw ---------------------------------------------------------------- */

void gxr_draw(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize)
{
    const uint32_t* xf = gx_xf_regs();
    const uint32_t* bp = gx_bp_regs();
    unsigned prim = op & 0xF8, vat = op & 7, i;
    const uint8_t* p = verts;
    Vertex* v;
    (void)vsize;
    if (!gxr_enabled() || count == 0) return;
    if (g_draw_limit && ++g_draw_no > g_draw_limit) return; /* SOA_GXR_DRAWS=N: stop after N draws */
    tex_set_memory(s);
    v = (Vertex*)malloc(sizeof(Vertex) * count);
    if (!v) return;
    for (i = 0; i < count; i++) {
        VertexIn in;
        p = decode_vertex(s, p, vat, &in);
        transform(s, &in, &v[i]);
    }
    switch (prim) {
    case 0x80: /* quads */
        for (i = 0; i + 3 < count; i += 4) {
            emit_triangle(xf, bp, &v[i], &v[i + 1], &v[i + 2]);
            emit_triangle(xf, bp, &v[i], &v[i + 2], &v[i + 3]);
        }
        break;
    case 0x90: /* triangles */
        for (i = 0; i + 2 < count; i += 3) emit_triangle(xf, bp, &v[i], &v[i + 1], &v[i + 2]);
        break;
    case 0x98: /* strip */
        for (i = 2; i < count; i++) {
            if (i & 1) emit_triangle(xf, bp, &v[i - 1], &v[i - 2], &v[i]);
            else emit_triangle(xf, bp, &v[i - 2], &v[i - 1], &v[i]);
        }
        break;
    case 0xA0: /* fan */
        for (i = 2; i < count; i++) emit_triangle(xf, bp, &v[0], &v[i - 1], &v[i]);
        break;
    case 0xA8: /* lines */
        for (i = 0; i + 1 < count; i += 2) {
            Vertex a = v[i], b = v[i + 1];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(xf, bp, &a); to_screen(xf, bp, &b);
            raster_line(bp, &a, &b);
        }
        break;
    case 0xB0: /* line strip */
        for (i = 1; i < count; i++) {
            Vertex a = v[i - 1], b = v[i];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(xf, bp, &a); to_screen(xf, bp, &b);
            raster_line(bp, &a, &b);
        }
        break;
    case 0xB8: /* points */
        for (i = 0; i < count; i++) {
            Vertex a = v[i];
            if (a.w <= 0.0f) continue;
            to_screen(xf, bp, &a);
            raster_point(bp, &a);
        }
        break;
    default: break;
    }
    free(v);
}

/* ---- EFB copy and clear ---------------------------------------------------- */

static void efb_clear(const uint32_t* bp, int x0, int y0, int w, int h)
{
    uint32_t ar = bp[0x4F], gb = bp[0x50], z = bp[0x51] & 0xFFFFFFu;
    uint8_t col[4] = {(uint8_t)(ar & 0xFF), (uint8_t)((gb >> 8) & 0xFF), (uint8_t)(gb & 0xFF), (uint8_t)((ar >> 8) & 0xFF)};
    int x, y;
    for (y = y0; y < y0 + h && y < EFB_H; y++)
        for (x = x0; x < x0 + w && x < EFB_W; x++) {
            if (x < 0 || y < 0) continue;
            memcpy(g_efb[y][x], col, 4);
            g_efb_z[y][x] = z;
        }
}

/* Write an EFB rectangle into memory as a texture (GXCopyTex). Tiled like
 * the formats the sampler decodes. */
static void copy_to_texture(CpuState* s, const uint32_t* bp, uint32_t v, int x0, int y0, int w, int h)
{
    uint32_t dest = (bp[0x4B] & 0x1FFFFFu) << 5;
    unsigned tpf = (v >> 3) & 15;
    unsigned fmt = tpf / 2 + (tpf & 1) * 8; /* EFBCopyFormat */
    int intensity = (v >> 15) & 1, half = (v >> 9) & 1;
    int ow = half ? w / 2 : w, oh = half ? h / 2 : h;
    int x, y;
    unsigned tw, th, bpt;
    uint8_t* base;

    /* map copy formats onto texture formats */
    unsigned texfmt;
    if (intensity) texfmt = fmt == 0 ? 0 : fmt == 1 ? 1 : fmt == 2 ? 2 : fmt == 3 ? 3 : 1;
    else texfmt = fmt == 4 ? 4 : fmt == 5 ? 5 : fmt == 6 ? 6 : fmt == 3 ? 3 : fmt == 1 ? 1 : 6;

    switch (texfmt) {
    case 0: tw = 8; th = 8; bpt = 32; break;
    case 1: case 2: tw = 8; th = 4; bpt = 32; break;
    case 3: case 4: case 5: tw = 4; th = 4; bpt = 32; break;
    default: tw = 4; th = 4; bpt = 64; texfmt = 6; break;
    }
    if ((dest & MEM_MASK) + (size_t)((oh + th - 1) / th) * ((ow + tw - 1) / tw) * bpt > MEM1_SIZE) return;
    base = mem_ptr(s, dest | 0x80000000u);
    for (y = 0; y < oh; y++) {
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
            I = (unsigned)(0.257f * px[0] + 0.504f * px[1] + 0.098f * px[2] + 16.0f);
            if (I > 255) I = 255;
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

static void copy_to_screen(int x0, int y0, int w, int h)
{
    char path[512];
    static uint8_t* buf;
    int x, y;
    g_copies_xfb++;
    if (g_png_path[0]) snprintf(path, sizeof path, "%s", g_png_path);
    else if (g_frames_every && (g_frame_no % g_frames_every) == 0) snprintf(path, sizeof path, "build/frames/%04u.png", g_frame_no);
    else { g_frame_no++; return; }
    g_frame_no++;
    if (!buf) buf = (uint8_t*)malloc((size_t)EFB_W * EFB_H * 4);
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            int sx = x0 + x, sy = y0 + y;
            uint8_t* o = buf + ((size_t)y * w + x) * 4;
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) { memcpy(o, g_efb[sy][sx], 3); o[3] = 255; }
            else { o[0] = o[1] = o[2] = 0; o[3] = 255; }
        }
    if (!png_write_rgba(path, buf, w, h, w * 4)) fprintf(stderr, "[gxr] cannot write %s\n", path);
    else fprintf(stderr, "[gxr] wrote %s (%dx%d)\n", path, w, h);
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
        int x0 = (int)(bp[0x49] & 0x3FF), y0 = (int)((bp[0x49] >> 10) & 0x3FF);
        int w = (int)(bp[0x4A] & 0x3FF) + 1, h = (int)((bp[0x4A] >> 10) & 0x3FF) + 1;
        tex_set_memory(s);
        if (v & 0x4000u) copy_to_screen(x0, y0, w, h);
        else copy_to_texture(s, bp, v, x0, y0, w, h);
        if (v & 0x800u) efb_clear(bp, x0, y0, w, h);
        if (v & 0x4000u) tex_invalidate_all(); /* textures may have been rewritten by now */
    }
}

void gxr_report(void)
{
    if (!gxr_enabled()) return;
    fprintf(stderr, "[gxr] %llu triangles, %llu lines, %llu points; %llu pixels shaded (%llu outside, %llu failed alpha, %llu failed depth); %llu clipped away; %llu bad vertex refs; %llu texture copies, %llu screen copies\n",
            (unsigned long long)g_tris, (unsigned long long)g_lines, (unsigned long long)g_points,
            (unsigned long long)g_pixels, (unsigned long long)g_rej_bary, (unsigned long long)g_rej_alpha, (unsigned long long)g_rej_depth, (unsigned long long)g_clipped, (unsigned long long)g_verts_bad,
            (unsigned long long)g_copies_tex, (unsigned long long)g_copies_xfb);
}
