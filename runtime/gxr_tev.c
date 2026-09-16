/*
 * Texture environment: texture decode and sampling, TLUTs in TMEM, and the
 * TEV combiner stages. Register layouts follow the hardware (BP register
 * numbers in comments); the arithmetic follows the documented fixed-point
 * combiner: lerp in 8.8, bias, shift, clamp to 8 or 11 bits.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "gxr.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static CpuState* g_s;
static uint8_t g_tmem[1u << 20];

void tex_set_memory(CpuState* s)
{
    g_s = s;
}

void tmem_load_tlut(CpuState* s, uint32_t src, uint32_t tmem_off, uint32_t bytes)
{
    if (tmem_off + bytes > sizeof g_tmem || (src & MEM_MASK) + bytes > MEM1_SIZE) return;
    memcpy(g_tmem + tmem_off, mem_ptr(s, src), bytes);
}

/* ---- texture decode --------------------------------------------------- */

typedef struct {
    uint32_t addr, fmt, w, h, tlut_off, tlut_fmt;
    uint8_t* rgba; /* w*h*4 */
    uint64_t stamp;
} TexEntry;

#define TEX_CACHE 96
static TexEntry g_cache[TEX_CACHE];
static uint64_t g_stamp;

void tex_invalidate_all(void)
{
    int i;
    for (i = 0; i < TEX_CACHE; i++) { free(g_cache[i].rgba); g_cache[i].rgba = NULL; g_cache[i].addr = 0; }
}

static void tlut_color(uint32_t tlut_off, uint32_t tlut_fmt, unsigned index, uint8_t* out)
{
    const uint8_t* p = g_tmem + ((tlut_off + index * 2) & ((1u << 20) - 1));
    unsigned v = ((unsigned)p[0] << 8) | p[1];
    switch (tlut_fmt) {
    case 0: /* IA8 */
        out[0] = out[1] = out[2] = p[1];
        out[3] = p[0];
        break;
    case 1: /* RGB565 */
        out[0] = (uint8_t)(((v >> 11) & 31) * 255 / 31);
        out[1] = (uint8_t)(((v >> 5) & 63) * 255 / 63);
        out[2] = (uint8_t)((v & 31) * 255 / 31);
        out[3] = 255;
        break;
    default: /* RGB5A3 */
        if (v & 0x8000) {
            out[0] = (uint8_t)(((v >> 10) & 31) * 255 / 31);
            out[1] = (uint8_t)(((v >> 5) & 31) * 255 / 31);
            out[2] = (uint8_t)((v & 31) * 255 / 31);
            out[3] = 255;
        } else {
            out[0] = (uint8_t)(((v >> 8) & 15) * 17);
            out[1] = (uint8_t)(((v >> 4) & 15) * 17);
            out[2] = (uint8_t)((v & 15) * 17);
            out[3] = (uint8_t)(((v >> 12) & 7) * 255 / 7);
        }
        break;
    }
}

static void rgb565(unsigned v, uint8_t* out)
{
    out[0] = (uint8_t)(((v >> 11) & 31) * 255 / 31);
    out[1] = (uint8_t)(((v >> 5) & 63) * 255 / 63);
    out[2] = (uint8_t)((v & 31) * 255 / 31);
    out[3] = 255;
}

static void decode_cmpr_block(const uint8_t* p, uint8_t* out, unsigned ox, unsigned oy, unsigned w, unsigned h)
{
    unsigned c0 = ((unsigned)p[0] << 8) | p[1], c1 = ((unsigned)p[2] << 8) | p[3];
    uint8_t pal[4][4];
    unsigned y, x;
    rgb565(c0, pal[0]);
    rgb565(c1, pal[1]);
    if (c0 > c1) {
        int i;
        for (i = 0; i < 3; i++) {
            pal[2][i] = (uint8_t)((2 * pal[0][i] + pal[1][i]) / 3);
            pal[3][i] = (uint8_t)((pal[0][i] + 2 * pal[1][i]) / 3);
        }
        pal[2][3] = pal[3][3] = 255;
    } else {
        int i;
        for (i = 0; i < 3; i++) {
            pal[2][i] = (uint8_t)((pal[0][i] + pal[1][i]) / 2);
            pal[3][i] = 0;
        }
        pal[2][3] = 255;
        pal[3][3] = 0;
    }
    for (y = 0; y < 4; y++) {
        unsigned row = p[4 + y];
        for (x = 0; x < 4; x++) {
            unsigned idx = (row >> (6 - 2 * x)) & 3;
            unsigned px = ox + x, py = oy + y;
            if (px < w && py < h) memcpy(out + (py * w + px) * 4, pal[idx], 4);
        }
    }
}

static uint8_t* decode_texture(uint32_t addr, uint32_t fmt, uint32_t w, uint32_t h, uint32_t tlut_off, uint32_t tlut_fmt)
{
    uint8_t* out = (uint8_t*)calloc((size_t)w * h, 4);
    const uint8_t* base;
    unsigned tw, th, bytes_per_tile, tiles_w;
    unsigned x, y;
    if (!out || !g_s) return out;
    if ((addr & MEM_MASK) >= MEM1_SIZE) return out;
    base = mem_ptr(g_s, addr);

    switch (fmt) {
    case 0: case 8: tw = 8; th = 8; bytes_per_tile = 32; break;       /* I4, C4 */
    case 1: case 2: case 9: tw = 8; th = 4; bytes_per_tile = 32; break; /* I8, IA4, C8 */
    case 3: case 4: case 5: case 10: tw = 4; th = 4; bytes_per_tile = 32; break; /* IA8 565 5A3 C14X2 */
    case 6: tw = 4; th = 4; bytes_per_tile = 64; break;                /* RGBA8 */
    case 14: tw = 8; th = 8; bytes_per_tile = 32; break;               /* CMPR */
    default: tw = 4; th = 4; bytes_per_tile = 32; break;
    }
    tiles_w = (w + tw - 1) / tw;

    if (fmt == 14) {
        unsigned by, bx;
        for (by = 0; by < (h + 7) / 8; by++)
            for (bx = 0; bx < tiles_w; bx++) {
                const uint8_t* blk = base + (by * tiles_w + bx) * 32;
                if ((size_t)(blk - g_s->mem) + 32 > MEM1_SIZE) continue;
                decode_cmpr_block(blk, out, bx * 8, by * 8, w, h);
                decode_cmpr_block(blk + 8, out, bx * 8 + 4, by * 8, w, h);
                decode_cmpr_block(blk + 16, out, bx * 8, by * 8 + 4, w, h);
                decode_cmpr_block(blk + 24, out, bx * 8 + 4, by * 8 + 4, w, h);
            }
        return out;
    }

    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            const uint8_t* tile = base + ((y / th) * tiles_w + x / tw) * bytes_per_tile;
            unsigned ix = x % tw, iy = y % th;
            uint8_t* o = out + (y * w + x) * 4;
            unsigned v;
            if ((size_t)(tile - g_s->mem) + bytes_per_tile > MEM1_SIZE) continue;
            switch (fmt) {
            case 0: /* I4 */
                v = tile[iy * 4 + ix / 2];
                v = (ix & 1) ? (v & 15) : (v >> 4);
                o[0] = o[1] = o[2] = o[3] = (uint8_t)(v * 17);
                break;
            case 1: /* I8 */
                v = tile[iy * 8 + ix];
                o[0] = o[1] = o[2] = o[3] = (uint8_t)v;
                break;
            case 2: /* IA4 */
                v = tile[iy * 8 + ix];
                o[0] = o[1] = o[2] = (uint8_t)((v & 15) * 17);
                o[3] = (uint8_t)((v >> 4) * 17);
                break;
            case 3: /* IA8 */
                o[3] = tile[(iy * 4 + ix) * 2];
                o[0] = o[1] = o[2] = tile[(iy * 4 + ix) * 2 + 1];
                break;
            case 4: /* RGB565 */
                v = ((unsigned)tile[(iy * 4 + ix) * 2] << 8) | tile[(iy * 4 + ix) * 2 + 1];
                rgb565(v, o);
                break;
            case 5: /* RGB5A3 */
                v = ((unsigned)tile[(iy * 4 + ix) * 2] << 8) | tile[(iy * 4 + ix) * 2 + 1];
                if (v & 0x8000) {
                    o[0] = (uint8_t)(((v >> 10) & 31) * 255 / 31);
                    o[1] = (uint8_t)(((v >> 5) & 31) * 255 / 31);
                    o[2] = (uint8_t)((v & 31) * 255 / 31);
                    o[3] = 255;
                } else {
                    o[0] = (uint8_t)(((v >> 8) & 15) * 17);
                    o[1] = (uint8_t)(((v >> 4) & 15) * 17);
                    o[2] = (uint8_t)((v & 15) * 17);
                    o[3] = (uint8_t)(((v >> 12) & 7) * 255 / 7);
                }
                break;
            case 6: /* RGBA8: 16 AR pairs then 16 GB pairs */
                o[3] = tile[(iy * 4 + ix) * 2];
                o[0] = tile[(iy * 4 + ix) * 2 + 1];
                o[1] = tile[32 + (iy * 4 + ix) * 2];
                o[2] = tile[32 + (iy * 4 + ix) * 2 + 1];
                break;
            case 8: /* C4 */
                v = tile[iy * 4 + ix / 2];
                v = (ix & 1) ? (v & 15) : (v >> 4);
                tlut_color(tlut_off, tlut_fmt, v, o);
                break;
            case 9: /* C8 */
                tlut_color(tlut_off, tlut_fmt, tile[iy * 8 + ix], o);
                break;
            case 10: /* C14X2 */
                v = ((unsigned)tile[(iy * 4 + ix) * 2] << 8) | tile[(iy * 4 + ix) * 2 + 1];
                tlut_color(tlut_off, tlut_fmt, v & 0x3FFF, o);
                break;
            default:
                o[0] = 255; o[1] = 0; o[2] = 255; o[3] = 255; /* unsupported: magenta */
                break;
            }
        }
    }
    return out;
}

static const TexEntry* texture(uint32_t addr, uint32_t fmt, uint32_t w, uint32_t h, uint32_t tlut_off, uint32_t tlut_fmt)
{
    int i, victim = 0;
    uint64_t oldest = ~0ull;
    for (i = 0; i < TEX_CACHE; i++) {
        TexEntry* e = &g_cache[i];
        if (e->rgba && e->addr == addr && e->fmt == fmt && e->w == w && e->h == h && e->tlut_off == tlut_off && e->tlut_fmt == tlut_fmt) {
            e->stamp = ++g_stamp;
            return e;
        }
        if (e->stamp < oldest) { oldest = e->stamp; victim = i; }
    }
    {
        TexEntry* e = &g_cache[victim];
        free(e->rgba);
        e->addr = addr; e->fmt = fmt; e->w = w; e->h = h; e->tlut_off = tlut_off; e->tlut_fmt = tlut_fmt;
        e->rgba = decode_texture(addr, fmt, w, h, tlut_off, tlut_fmt);
        e->stamp = ++g_stamp;
        return e;
    }
}

/* ---- sampling ----------------------------------------------------------- */

static int wrap(int i, int size, unsigned mode)
{
    if (size <= 0) return 0;
    switch (mode) {
    case 0: return i < 0 ? 0 : (i >= size ? size - 1 : i); /* clamp */
    case 1: i %= size; return i < 0 ? i + size : i;         /* repeat */
    default: {                                              /* mirror */
        int period = 2 * size;
        i %= period;
        if (i < 0) i += period;
        return i < size ? i : period - 1 - i;
    }
    }
}

static void sample(const uint32_t* bp, unsigned map, float s, float t, uint8_t out[4])
{
    unsigned rb = map < 4 ? map : 0x20 + (map - 4);
    uint32_t mode0 = bp[0x80 + rb], image0 = bp[0x88 + rb], image3 = bp[0x94 + rb], tlut = bp[0x98 + rb];
    uint32_t w = (image0 & 0x3FF) + 1, h = ((image0 >> 10) & 0x3FF) + 1, fmt = (image0 >> 20) & 15;
    uint32_t addr = (image3 & 0x1FFFFF) << 5;
    uint32_t tlut_off = (tlut & 0x3FF) << 9, tlut_fmt = (tlut >> 10) & 3;
    const TexEntry* te = texture(addr, fmt, w, h, tlut_off, tlut_fmt);
    unsigned wrap_s = mode0 & 3, wrap_t = (mode0 >> 2) & 3;
    int linear = (mode0 >> 4) & 1;
    /* Texture coordinate scale (SU_TS0/TS1, GXSetTexCoordScaleManually / GXLoadTexObj). */
    float u = s * (float)((bp[0x30 + 2 * map] & 0xFFFF) + 1);
    float v = t * (float)((bp[0x31 + 2 * map] & 0xFFFF) + 1);

    if (!te->rgba) { out[0] = out[1] = out[2] = out[3] = 0; return; }
    if (!linear) {
        int x = wrap((int)floorf(u), (int)w, wrap_s), y = wrap((int)floorf(v), (int)h, wrap_t);
        memcpy(out, te->rgba + ((size_t)y * w + x) * 4, 4);
    } else {
        float fu = u - 0.5f, fv = v - 0.5f;
        int x0 = (int)floorf(fu), y0 = (int)floorf(fv);
        float ax = fu - (float)x0, ay = fv - (float)y0;
        int xa = wrap(x0, (int)w, wrap_s), xb = wrap(x0 + 1, (int)w, wrap_s);
        int ya = wrap(y0, (int)h, wrap_t), yb = wrap(y0 + 1, (int)h, wrap_t);
        const uint8_t* p00 = te->rgba + ((size_t)ya * w + xa) * 4;
        const uint8_t* p10 = te->rgba + ((size_t)ya * w + xb) * 4;
        const uint8_t* p01 = te->rgba + ((size_t)yb * w + xa) * 4;
        const uint8_t* p11 = te->rgba + ((size_t)yb * w + xb) * 4;
        int i;
        for (i = 0; i < 4; i++) {
            float top = p00[i] + (p10[i] - p00[i]) * ax;
            float bot = p01[i] + (p11[i] - p01[i]) * ax;
            float val = top + (bot - top) * ay;
            out[i] = (uint8_t)(val + 0.5f);
        }
    }
}

/* ---- TEV ---------------------------------------------------------------- */

/* Color and konst registers are written through BP 0xE0-0xE7; bit 23 of the
 * RA half says which set. Kept here, latched as the writes arrive. */
static int16_t g_tev_reg[4][4];  /* r g b a, s11 */
static uint8_t g_tev_konst[4][4];

void tev_register_written(uint32_t reg, uint32_t v)
{
    unsigned i = (reg - 0xE0) >> 1;
    int is_konst = (v >> 23) & 1;
    if (reg & 1) { /* BG */
        if (is_konst) { g_tev_konst[i][2] = (uint8_t)(v & 0xFF); g_tev_konst[i][1] = (uint8_t)((v >> 12) & 0xFF); }
        else {
            g_tev_reg[i][2] = (int16_t)((int32_t)((v & 0x7FF) << 21) >> 21);
            g_tev_reg[i][1] = (int16_t)((int32_t)(((v >> 12) & 0x7FF) << 21) >> 21);
        }
    } else { /* RA */
        if (is_konst) { g_tev_konst[i][0] = (uint8_t)(v & 0xFF); g_tev_konst[i][3] = (uint8_t)((v >> 12) & 0xFF); }
        else {
            g_tev_reg[i][0] = (int16_t)((int32_t)((v & 0x7FF) << 21) >> 21);
            g_tev_reg[i][3] = (int16_t)((int32_t)(((v >> 12) & 0x7FF) << 21) >> 21);
        }
    }
}

static int clamp255(int v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }
static int clamp_s11(int v) { return v < -1024 ? -1024 : (v > 1023 ? 1023 : v); }

static void swap_apply(const uint32_t* bp, unsigned table, const uint8_t in[4], uint8_t out[4])
{
    uint32_t k0 = bp[0xF6 + 2 * table], k1 = bp[0xF7 + 2 * table];
    unsigned sel[4] = {k0 & 3, (k0 >> 2) & 3, k1 & 3, (k1 >> 2) & 3};
    int i;
    for (i = 0; i < 4; i++) out[i] = in[sel[i]];
}

static int konst_value(unsigned sel, const uint8_t konst[4][4], int channel)
{
    if (sel < 8) { int v = (8 - (int)sel) * 32; return v > 255 ? 255 : v; }
    if (sel >= 12 && sel < 16) return channel < 3 ? konst[sel - 12][channel] : konst[sel - 12][3];
    if (sel >= 16 && sel < 32) return konst[(sel - 16) & 3][(sel - 16) >> 2];
    return 0;
}

static int compare(unsigned mode, int a, int b)
{
    switch (mode) {
    case 0: return 0;
    case 1: return a < b;
    case 2: return a == b;
    case 3: return a <= b;
    case 4: return a > b;
    case 5: return a != b;
    case 6: return a >= b;
    default: return 1;
    }
}

/* Runs the stages for one pixel. ras[]: rasterized channel colors 0..1;
 * tex[]: texture coordinates per texcoord slot. Writes RGBA 0..255. */
void tev_pixel(const uint32_t* bp, const Color4 ras[2], const float tex[8][3], uint8_t out[4], int* alpha_pass)
{
    unsigned stages = ((bp[0] >> 10) & 15) + 1, st;
    int reg[4][4];
    int i, j;
    for (i = 0; i < 4; i++) for (j = 0; j < 4; j++) reg[i][j] = g_tev_reg[i][j];

    for (st = 0; st < stages; st++) {
        uint32_t tref = bp[0x28 + st / 2] >> ((st & 1) * 12);
        unsigned texmap = tref & 7, texcoord = (tref >> 3) & 7, texen = (tref >> 6) & 1, chan = (tref >> 7) & 7;
        uint32_t cenv = bp[0xC0 + 2 * st], aenv = bp[0xC1 + 2 * st];
        uint32_t ksel = bp[0xF6 + st / 2];
        unsigned kc = (st & 1) ? (ksel >> 14) & 31 : (ksel >> 4) & 31;
        unsigned ka = (st & 1) ? (ksel >> 19) & 31 : (ksel >> 9) & 31;
        unsigned rswap = aenv & 3, tswap = (aenv >> 2) & 3;
        uint8_t texc[4] = {0, 0, 0, 0}, rasc[4] = {0, 0, 0, 0}, tmp[4];
        int konstc[4];
        int in_c[16][3], in_a[8];
        int sel_d = cenv & 15, sel_c = (cenv >> 4) & 15, sel_b = (cenv >> 8) & 15, sel_a = (cenv >> 12) & 15;
        unsigned bias = (cenv >> 16) & 3, op = (cenv >> 18) & 1, clamp = (cenv >> 19) & 1, shift = (cenv >> 20) & 3, dest = (cenv >> 22) & 3;
        int asel_d = (aenv >> 4) & 7, asel_c = (aenv >> 7) & 7, asel_b = (aenv >> 10) & 7, asel_a = (aenv >> 13) & 7;
        unsigned abias = (aenv >> 16) & 3, aop = (aenv >> 18) & 1, aclamp = (aenv >> 19) & 1, ashift = (aenv >> 20) & 3, adest = (aenv >> 22) & 3;

        if (texen) {
            float q = tex[texcoord][2];
            float s = q != 0.0f ? tex[texcoord][0] / q : tex[texcoord][0];
            float t = q != 0.0f ? tex[texcoord][1] / q : tex[texcoord][1];
            sample(bp, texmap, s, t, tmp);
            swap_apply(bp, tswap, tmp, texc);
        }
        if (chan < 2) {
            tmp[0] = (uint8_t)clamp255((int)(ras[chan].r * 255.0f + 0.5f));
            tmp[1] = (uint8_t)clamp255((int)(ras[chan].g * 255.0f + 0.5f));
            tmp[2] = (uint8_t)clamp255((int)(ras[chan].b * 255.0f + 0.5f));
            tmp[3] = (uint8_t)clamp255((int)(ras[chan].a * 255.0f + 0.5f));
            swap_apply(bp, rswap, tmp, rasc);
        }
        for (i = 0; i < 3; i++) konstc[i] = konst_value(kc, g_tev_konst, i);
        konstc[3] = konst_value(ka, g_tev_konst, 3);

        for (i = 0; i < 3; i++) {
            in_c[0][i] = reg[0][i]; in_c[1][i] = reg[0][3];
            in_c[2][i] = reg[1][i]; in_c[3][i] = reg[1][3];
            in_c[4][i] = reg[2][i]; in_c[5][i] = reg[2][3];
            in_c[6][i] = reg[3][i]; in_c[7][i] = reg[3][3];
            in_c[8][i] = texc[i];   in_c[9][i] = texc[3];
            in_c[10][i] = rasc[i];  in_c[11][i] = rasc[3];
            in_c[12][i] = 255;      in_c[13][i] = 128;
            in_c[14][i] = konstc[i]; in_c[15][i] = 0;
        }
        in_a[0] = reg[0][3]; in_a[1] = reg[1][3]; in_a[2] = reg[2][3]; in_a[3] = reg[3][3];
        in_a[4] = texc[3]; in_a[5] = rasc[3]; in_a[6] = konstc[3]; in_a[7] = 0;

        /* Color */
        if (bias != 3) {
            for (i = 0; i < 3; i++) {
                int a = in_c[sel_a][i] & 0xFF, b = in_c[sel_b][i] & 0xFF, c = in_c[sel_c][i] & 0xFF, d = in_c[sel_d][i];
                int cc = c + (c >> 7);
                int lerp = a * (256 - cc) + b * cc;
                int v = (lerp + 128) >> 8;
                int r;
                if (op) v = -v;
                r = d + v + (bias == 1 ? 128 : bias == 2 ? -128 : 0);
                if (shift == 1) r <<= 1; else if (shift == 2) r <<= 2; else if (shift == 3) r >>= 1;
                reg[dest][i] = clamp ? clamp255(r) : clamp_s11(r);
            }
        } else {
            unsigned cmp = (shift << 1) | op;
            int a[3], b[3], c[3], d[3], res;
            for (i = 0; i < 3; i++) { a[i] = in_c[sel_a][i] & 0xFF; b[i] = in_c[sel_b][i] & 0xFF; c[i] = in_c[sel_c][i]; d[i] = in_c[sel_d][i]; }
            switch (cmp >> 1) {
            case 0: res = cmp & 1 ? a[0] == b[0] : a[0] > b[0]; break;
            case 1: { int av = (a[1] << 8) | a[0], bv = (b[1] << 8) | b[0]; res = cmp & 1 ? av == bv : av > bv; break; }
            case 2: { int av = (a[2] << 16) | (a[1] << 8) | a[0], bv = (b[2] << 16) | (b[1] << 8) | b[0]; res = cmp & 1 ? av == bv : av > bv; break; }
            default: res = -1; break;
            }
            for (i = 0; i < 3; i++) {
                int r = res == -1 ? ((cmp & 1 ? a[i] == b[i] : a[i] > b[i]) ? c[i] : 0) : (res ? c[i] : 0);
                r += d[i];
                reg[dest][i] = clamp ? clamp255(r) : clamp_s11(r);
            }
        }
        /* Alpha */
        if (abias != 3) {
            int a = in_a[asel_a] & 0xFF, b = in_a[asel_b] & 0xFF, c = in_a[asel_c] & 0xFF, d = in_a[asel_d];
            int cc = c + (c >> 7);
            int lerp = a * (256 - cc) + b * cc;
            int v = (lerp + 128) >> 8, r;
            if (aop) v = -v;
            r = d + v + (abias == 1 ? 128 : abias == 2 ? -128 : 0);
            if (ashift == 1) r <<= 1; else if (ashift == 2) r <<= 2; else if (ashift == 3) r >>= 1;
            reg[adest][3] = aclamp ? clamp255(r) : clamp_s11(r);
        } else {
            unsigned cmp = (ashift << 1) | aop;
            int a = in_a[asel_a] & 0xFF, b = in_a[asel_b] & 0xFF, c = in_a[asel_c], d = in_a[asel_d];
            int res;
            switch (cmp >> 1) { /* the wide compares use the color inputs; approximate with alpha */
            default: res = cmp & 1 ? a == b : a > b; break;
            }
            reg[adest][3] = aclamp ? clamp255(d + (res ? c : 0)) : clamp_s11(d + (res ? c : 0));
        }
    }

    for (i = 0; i < 4; i++) out[i] = (uint8_t)clamp255(reg[0][i]);

    /* Alpha compare (PE_ALPHA_COMPARE, GXSetAlphaCompare). */
    {
        uint32_t ac = bp[0xF3];
        int ref0 = ac & 0xFF, ref1 = (ac >> 8) & 0xFF;
        unsigned comp0 = (ac >> 16) & 7, comp1 = (ac >> 19) & 7, logic = (ac >> 22) & 3;
        int p0 = compare(comp0, out[3], ref0), p1 = compare(comp1, out[3], ref1);
        switch (logic) {
        case 0: *alpha_pass = p0 && p1; break;
        case 1: *alpha_pass = p0 || p1; break;
        case 2: *alpha_pass = p0 != p1; break;
        default: *alpha_pass = p0 == p1; break;
        }
    }
}
