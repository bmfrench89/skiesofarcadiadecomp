/*
 * Texture environment: texture decode and sampling, TLUTs in TMEM, and the
 * TEV combiner stages. Register layouts follow the hardware (BP register
 * numbers in comments); the arithmetic follows the documented fixed-point
 * combiner: lerp in 8.8, bias, shift, clamp to 8 or 11 bits.
 *
 * Everything that can be decided per draw is decided once, in
 * tev_prepare: stage selectors, konst values, swap tables, and the decoded
 * textures with their scale and wrap modes. The per-pixel path then only
 * indexes.
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

/* ---- texture cache ------------------------------------------------------ */

typedef struct {
    uint32_t addr, fmt, w, h, tlut_off, tlut_fmt;
    uint8_t* rgba; /* every level, consecutively; level 0 first */
    const uint8_t* level[MAX_MIPS];
    int lw[MAX_MIPS], lh[MAX_MIPS], nlevels;
    uint64_t stamp;
    uint32_t hash;
} TexEntry;

#define TEX_CACHE 256
static TexEntry g_cache[TEX_CACHE];
static uint64_t g_stamp;

/* Queued draws hold pointers into the cache, so nothing is freed until the
 * queue has drained: freed textures wait here. */
#define GRAVE_CAP 512
static uint8_t* g_grave[GRAVE_CAP];
static int g_grave_n;

static void tex_free_later(uint8_t* p)
{
    if (!p) return;
    if (g_grave_n < GRAVE_CAP) g_grave[g_grave_n++] = p;
    else free(p); /* only after the caller ignored tex_graveyard_full */
}

int tex_graveyard_full(void) { return g_grave_n >= GRAVE_CAP - 64; }

void tex_graveyard_empty(void)
{
    int i;
    for (i = 0; i < g_grave_n; i++) free(g_grave[i]);
    g_grave_n = 0;
}

void tex_invalidate_all(void)
{
    int i;
    for (i = 0; i < TEX_CACHE; i++) { tex_free_later(g_cache[i].rgba); g_cache[i].rgba = NULL; g_cache[i].addr = 0; }
}

/* Bytes a texture occupies in memory, from its tiled layout. */
static uint32_t texture_bytes(uint32_t fmt, uint32_t w, uint32_t h)
{
    unsigned tw, th, bpt;
    switch (fmt) {
    case 0: case 8: tw = 8; th = 8; bpt = 32; break;
    case 1: case 2: case 9: tw = 8; th = 4; bpt = 32; break;
    case 6: tw = 4; th = 4; bpt = 64; break;
    case 14: tw = 8; th = 8; bpt = 32; break;
    default: tw = 4; th = 4; bpt = 32; break;
    }
    return ((w + tw - 1) / tw) * ((h + th - 1) / th) * bpt;
}

/* A cheap fingerprint of the source bytes (and the palette): 64 words
 * spread over the data. Catches textures the game rewrites in place. */
static uint32_t source_hash(uint32_t addr, uint32_t fmt, uint32_t w, uint32_t h, uint32_t tlut_off)
{
    uint32_t bytes = texture_bytes(fmt, w, h), hsh = 2166136261u, i;
    const uint8_t* base;
    if (!g_s || (addr & MEM_MASK) + bytes > MEM1_SIZE) return 0;
    base = mem_ptr(g_s, addr);
    for (i = 0; i < 64; i++) {
        uint32_t off = (uint32_t)(((uint64_t)bytes * i) / 64) & ~3u;
        uint32_t wv;
        if (off + 4 > bytes) break;
        memcpy(&wv, base + off, 4);
        hsh = (hsh ^ wv) * 16777619u;
    }
    if (fmt == 8 || fmt == 9 || fmt == 10) {
        uint32_t n = fmt == 8 ? 32 : (fmt == 9 ? 512 : 32768);
        for (i = 0; i < 64; i++) {
            uint32_t off = (tlut_off + ((n * i) / 64 & ~3u)) & ((1u << 20) - 1);
            uint32_t wv;
            memcpy(&wv, g_tmem + off, 4);
            hsh = (hsh ^ wv) * 16777619u;
        }
    }
    return hsh;
}

void tmem_load_tlut(CpuState* s, uint32_t src, uint32_t tmem_off, uint32_t bytes)
{
    int i;
    if (tmem_off + bytes > sizeof g_tmem || (src & MEM_MASK) + bytes > MEM1_SIZE) return;
    memcpy(g_tmem + tmem_off, mem_ptr(s, src), bytes);
    /* palettised textures decoded through this range are stale now */
    for (i = 0; i < TEX_CACHE; i++) {
        TexEntry* e = &g_cache[i];
        if (e->rgba && (e->fmt == 8 || e->fmt == 9 || e->fmt == 10) && e->tlut_off < tmem_off + bytes && e->tlut_off + 32768 > tmem_off) {
            tex_free_later(e->rgba); e->rgba = NULL; e->addr = 0;
        }
    }
}

/* ---- texture decode --------------------------------------------------- */

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

static void decode_level(uint8_t* out, uint32_t addr, uint32_t fmt, uint32_t w, uint32_t h, uint32_t tlut_off, uint32_t tlut_fmt)
{
    const uint8_t* base;
    unsigned tw, th, bytes_per_tile, tiles_w;
    unsigned x, y;
    if (!out || !g_s) return;
    if ((addr & MEM_MASK) >= MEM1_SIZE) return;
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
        return;
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
}

/* Decode a texture and up to `nlevels` of its mipmaps, which follow the
 * base level in memory, each tiled at its own size. */
static void decode_texture(TexEntry* e, int nlevels)
{
    uint32_t w = e->w, h = e->h, addr = e->addr;
    size_t total = 0;
    int l;
    uint8_t* out;
    if (nlevels < 1) nlevels = 1;
    if (nlevels > MAX_MIPS) nlevels = MAX_MIPS;
    e->nlevels = 0;
    for (l = 0; l < nlevels; l++) {
        e->lw[l] = (int)w; e->lh[l] = (int)h;
        total += (size_t)w * h * 4;
        e->nlevels++;
        if (w == 1 && h == 1) break;
        w = w > 1 ? w / 2 : 1; h = h > 1 ? h / 2 : 1;
    }
    out = (uint8_t*)calloc(total, 1);
    e->rgba = out;
    if (!out) return;
    for (l = 0; l < e->nlevels; l++) {
        e->level[l] = out;
        decode_level(out, addr, e->fmt, (uint32_t)e->lw[l], (uint32_t)e->lh[l], e->tlut_off, e->tlut_fmt);
        addr += texture_bytes(e->fmt, (uint32_t)e->lw[l], (uint32_t)e->lh[l]);
        out += (size_t)e->lw[l] * e->lh[l] * 4;
    }
    for (; l < MAX_MIPS; l++) e->level[l] = NULL;
}

static const TexEntry* texture(uint32_t addr, uint32_t fmt, uint32_t w, uint32_t h, uint32_t tlut_off, uint32_t tlut_fmt, int nlevels)
{
    int i, victim = 0;
    uint64_t oldest = ~0ull;
    uint32_t hsh;
    gxr_texture_hazard(addr, texture_bytes(fmt, w, h));
    hsh = source_hash(addr, fmt, w, h, tlut_off);
    for (i = 0; i < TEX_CACHE; i++) {
        TexEntry* e = &g_cache[i];
        if (e->rgba && e->addr == addr && e->fmt == fmt && e->w == w && e->h == h && e->tlut_off == tlut_off && e->tlut_fmt == tlut_fmt) {
            e->stamp = ++g_stamp;
            if (e->hash != hsh || e->nlevels < nlevels) { /* rewritten in place, or more levels wanted */
                tex_free_later(e->rgba);
                TIMED(T_DECODE, decode_texture(e, nlevels > e->nlevels ? nlevels : e->nlevels));
                e->hash = hsh;
            }
            return e;
        }
        if (e->stamp < oldest) { oldest = e->stamp; victim = i; }
    }
    {
        TexEntry* e = &g_cache[victim];
        tex_free_later(e->rgba);
        e->addr = addr; e->fmt = fmt; e->w = w; e->h = h; e->tlut_off = tlut_off; e->tlut_fmt = tlut_fmt;
        TIMED(T_DECODE, decode_texture(e, nlevels));
        e->hash = hsh;
        e->stamp = ++g_stamp;
        return e;
    }
}

/* ---- per-draw setup ------------------------------------------------------ */

static uint8_t color_index(unsigned sel, int i)
{
    switch (sel) {
    case 0: return (uint8_t)i;       case 1: return 3;
    case 2: return (uint8_t)(4 + i); case 3: return 7;
    case 4: return (uint8_t)(8 + i); case 5: return 11;
    case 6: return (uint8_t)(12 + i); case 7: return 15;
    case 8: return (uint8_t)(BANK_TEX + i); case 9: return BANK_TEX + 3;
    case 10: return (uint8_t)(BANK_RAS + i); case 11: return BANK_RAS + 3;
    case 12: return BANK_ONE; case 13: return BANK_HALF;
    case 14: return (uint8_t)(BANK_KONST + i); default: return BANK_ZERO;
    }
}

static uint8_t alpha_index(unsigned sel)
{
    switch (sel) {
    case 0: return 3; case 1: return 7; case 2: return 11; case 3: return 15;
    case 4: return BANK_TEX + 3; case 5: return BANK_RAS + 3; case 6: return BANK_KONST + 3; default: return BANK_ZERO;
    }
}

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

static int konst_value(unsigned sel, int channel)
{
    if (sel < 8) { int v = (8 - (int)sel) * 32; return v > 255 ? 255 : v; }
    if (sel >= 12 && sel < 16) return channel < 3 ? g_tev_konst[sel - 12][channel] : g_tev_konst[sel - 12][3];
    if (sel >= 16 && sel < 32) return g_tev_konst[(sel - 16) & 3][(sel - 16) >> 2];
    return 0;
}

void tev_prepare(const uint32_t* bp, TevSetup* T)
{
    unsigned st, i, j;
    uint32_t ac = bp[0xF3];

    T->stages = ((bp[0] >> 10) & 15) + 1;
    T->used_tex = 0;
    T->used_chan = 0;
    for (i = 0; i < 4; i++) for (j = 0; j < 4; j++) T->reg_init[i][j] = g_tev_reg[i][j];
    T->aref0 = ac & 0xFF; T->aref1 = (ac >> 8) & 0xFF;
    T->acomp0 = (ac >> 16) & 7; T->acomp1 = (ac >> 19) & 7; T->alogic = (ac >> 22) & 3;

    for (st = 0; st < T->stages; st++) {
        Stage* S = &T->st[st];
        uint32_t tref = bp[0x28 + st / 2] >> ((st & 1) * 12);
        uint32_t cenv = bp[0xC0 + 2 * st], aenv = bp[0xC1 + 2 * st];
        uint32_t ksel = bp[0xF6 + st / 2];
        unsigned kc = (st & 1) ? (ksel >> 14) & 31 : (ksel >> 4) & 31;
        unsigned ka = (st & 1) ? (ksel >> 19) & 31 : (ksel >> 9) & 31;
        unsigned rs = aenv & 3, ts = (aenv >> 2) & 3;
        uint32_t k0, k1;
        S->texmap = tref & 7; S->texcoord = (tref >> 3) & 7; S->texen = (tref >> 6) & 1; S->chan = (tref >> 7) & 7;
        S->cd = cenv & 15; S->cc = (cenv >> 4) & 15; S->cb = (cenv >> 8) & 15; S->ca = (cenv >> 12) & 15;
        S->cbias = (cenv >> 16) & 3; S->cop = (cenv >> 18) & 1; S->cclamp = (cenv >> 19) & 1; S->cshift = (cenv >> 20) & 3; S->cdest = (cenv >> 22) & 3;
        S->ad = (aenv >> 4) & 7; S->ac = (aenv >> 7) & 7; S->ab = (aenv >> 10) & 7; S->aa = (aenv >> 13) & 7;
        S->abias = (aenv >> 16) & 3; S->aop = (aenv >> 18) & 1; S->aclamp = (aenv >> 19) & 1; S->ashift = (aenv >> 20) & 3; S->adest = (aenv >> 22) & 3;
        k0 = bp[0xF6 + 2 * rs]; k1 = bp[0xF7 + 2 * rs];
        S->rswap[0] = k0 & 3; S->rswap[1] = (k0 >> 2) & 3; S->rswap[2] = k1 & 3; S->rswap[3] = (k1 >> 2) & 3;
        k0 = bp[0xF6 + 2 * ts]; k1 = bp[0xF7 + 2 * ts];
        S->tswap[0] = k0 & 3; S->tswap[1] = (k0 >> 2) & 3; S->tswap[2] = k1 & 3; S->tswap[3] = (k1 >> 2) & 3;
        for (i = 0; i < 3; i++) S->konst[i] = konst_value(kc, (int)i);
        S->konst[3] = konst_value(ka, 3);
        for (i = 0; i < 3; i++) {
            S->ia[i] = color_index(S->ca, (int)i); S->ib[i] = color_index(S->cb, (int)i);
            S->ic[i] = color_index(S->cc, (int)i); S->id[i] = color_index(S->cd, (int)i);
        }
        S->ja = alpha_index(S->aa); S->jb = alpha_index(S->ab); S->jc = alpha_index(S->ac); S->jd = alpha_index(S->ad);
        if (S->texen) T->used_tex |= 1u << S->texcoord;
        if (S->chan < 2) T->used_chan |= 1u << S->chan;
    }

    /* textures: decode (cached) and resolve sampling state per map used */
    for (i = 0; i < 8; i++) T->tex[i].level[0] = NULL;
    for (st = 0; st < T->stages; st++) {
        Stage* S = &T->st[st];
        unsigned map = S->texmap, rb;
        TexCfg* C;
        uint32_t mode0, mode1, image0, image3, tlut, w, h, fmt, addr, tlut_off, tlut_fmt;
        unsigned minf;
        int nlevels, l;
        const TexEntry* te;
        if (!S->texen) continue;
        C = &T->tex[map];
        if (C->level[0]) continue;
        rb = map < 4 ? map : 0x20 + (map - 4);
        mode0 = bp[0x80 + rb]; mode1 = bp[0x84 + rb]; image0 = bp[0x88 + rb]; image3 = bp[0x94 + rb]; tlut = bp[0x98 + rb];
        w = (image0 & 0x3FF) + 1; h = ((image0 >> 10) & 0x3FF) + 1; fmt = (image0 >> 20) & 15;
        addr = (image3 & 0x1FFFFF) << 5;
        tlut_off = (tlut & 0x3FF) << 9; tlut_fmt = (tlut >> 10) & 3;
        minf = (mode0 >> 5) & 7;
        C->mip = (minf == 1 || minf == 2 || minf == 5 || minf == 6);
        C->min_lod = (float)(mode1 & 0xFF) / 16.0f;
        C->max_lod = (float)((mode1 >> 8) & 0xFF) / 16.0f;
        C->lod_bias = (float)(int8_t)((mode0 >> 9) & 0xFF) / 32.0f;
        nlevels = C->mip ? (int)(C->max_lod + 0.999f) + 1 : 1;
        te = texture(addr, fmt, w, h, tlut_off, tlut_fmt, nlevels);
        C->nlevels = te->nlevels;
        for (l = 0; l < MAX_MIPS; l++) { C->level[l] = te->level[l]; C->lw[l] = te->lw[l]; C->lh[l] = te->lh[l]; }
        C->w = (int)w; C->h = (int)h;
        C->wrap_s = mode0 & 3; C->wrap_t = (mode0 >> 2) & 3;
        C->linear = (mode0 >> 4) & 1;
        /* SU_SSIZE/TSIZE are indexed by texture *coordinate*, not by map: the SDK
         * writes the dimensions of the map a stage samples into the registers of
         * the coordinate that stage uses (a glyph on map 7 read through coord 0
         * scales by SU0). */
        C->scale_s = (float)((bp[0x30 + 2 * S->texcoord] & 0xFFFF) + 1);
        C->scale_t = (float)((bp[0x31 + 2 * S->texcoord] & 0xFFFF) + 1);
    }
}

/* ---- sampling ----------------------------------------------------------- */

static inline int fast_floor(float f)
{
    int i = (int)f;
    return f < (float)i ? i - 1 : i;
}

static inline int wrap(int i, int size, int mask, unsigned mode)
{
    switch (mode) {
    case 0: return i < 0 ? 0 : (i >= size ? size - 1 : i);
    case 1:
        if (mask >= 0) return i & mask;
        i %= size; return i < 0 ? i + size : i;
    default: {
        int period = 2 * size;
        if (mask >= 0) { i &= period - 1; return i < size ? i : period - 1 - i; }
        i %= period;
        if (i < 0) i += period;
        return i < size ? i : period - 1 - i;
    }
    }
}

static int g_notex = -1;

static inline void sample_level(const TexCfg* C, int l, float u, float v, uint8_t out[4])
{
    const uint8_t* img = C->level[l];
    int w = C->lw[l], h = C->lh[l];
    int mask_s = (w & (w - 1)) == 0 ? w - 1 : -1, mask_t = (h & (h - 1)) == 0 ? h - 1 : -1;
    if (!C->linear) {
        int x = wrap(fast_floor(u), w, mask_s, C->wrap_s), y = wrap(fast_floor(v), h, mask_t, C->wrap_t);
        memcpy(out, img + ((size_t)y * w + x) * 4, 4);
    } else {
        float fu = u - 0.5f, fv = v - 0.5f;
        int x0 = fast_floor(fu), y0 = fast_floor(fv);
        int ax = (int)((fu - (float)x0) * 256.0f), ay = (int)((fv - (float)y0) * 256.0f);
        int xa = wrap(x0, w, mask_s, C->wrap_s), xb = wrap(x0 + 1, w, mask_s, C->wrap_s);
        int ya = wrap(y0, h, mask_t, C->wrap_t), yb = wrap(y0 + 1, h, mask_t, C->wrap_t);
        const uint8_t* p00 = img + ((size_t)ya * w + xa) * 4;
        const uint8_t* p10 = img + ((size_t)ya * w + xb) * 4;
        const uint8_t* p01 = img + ((size_t)yb * w + xa) * 4;
        const uint8_t* p11 = img + ((size_t)yb * w + xb) * 4;
        int i;
        for (i = 0; i < 4; i++) {
            int top = p00[i] * (256 - ax) + p10[i] * ax;
            int bot = p01[i] * (256 - ax) + p11[i] * ax;
            out[i] = (uint8_t)((top * (256 - ay) + bot * ay + 32768) >> 16);
        }
    }
}

/* lod: log2 of texels per pixel at this pixel, from the rasterizer. */
static inline void sample(const TexCfg* C, float s, float t, float lod, uint8_t out[4])
{
    int l = 0;
    float u, v;
    if (g_notex < 0) g_notex = getenv("SOA_GXR_NOTEX") ? 1 : 0;
    if (g_notex) { out[0] = out[1] = out[2] = out[3] = 200; return; }
    if (!C->level[0] || C->w <= 0 || C->h <= 0) { out[0] = out[1] = out[2] = out[3] = 0; return; }
    if (C->mip && C->nlevels > 1) {
        float L = lod + C->lod_bias;
        if (L < C->min_lod) L = C->min_lod;
        if (L > C->max_lod) L = C->max_lod;
        l = (int)(L + 0.5f);
        if (l >= C->nlevels) l = C->nlevels - 1;
        if (l < 0) l = 0;
    }
    u = s * (C->scale_s * (float)C->lw[l] / (float)C->w);
    v = t * (C->scale_t * (float)C->lh[l] / (float)C->h);
    sample_level(C, l, u, v, out);
}

/* ---- TEV ---------------------------------------------------------------- */

static inline int clamp255(int v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }
static inline int clamp_s11(int v) { return v < -1024 ? -1024 : (v > 1023 ? 1023 : v); }

static inline int compare(unsigned mode, int a, int b)
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

int g_tev_narrate; /* set by the renderer's SOA_GXR_PIXEL hook: print every stage of one pixel */

/* Runs the stages for one pixel. ras[]: rasterized channel colors 0..255;
 * tex[]: texture coordinates per texcoord slot (s, t, q). */
void tev_pixel(const TevSetup* T, const int ras[2][4], const float tex[8][4], uint8_t out[4], int* alpha_pass)
{
    unsigned st;
    int bank[BANK_SIZE];
    int i;
    memcpy(bank, T->reg_init, sizeof(int) * 16);
    bank[BANK_ONE] = 255; bank[BANK_HALF] = 128; bank[BANK_ZERO] = 0;
    bank[BANK_TEX] = bank[BANK_TEX + 1] = bank[BANK_TEX + 2] = bank[BANK_TEX + 3] = 0;
    bank[BANK_RAS] = bank[BANK_RAS + 1] = bank[BANK_RAS + 2] = bank[BANK_RAS + 3] = 0;

    for (st = 0; st < T->stages; st++) {
        const Stage* S = &T->st[st];
        uint8_t tmp[4];
        int* dc = &bank[S->cdest * 4];

        if (S->texen) {
            const float* tc = tex[S->texcoord];
            float q = tc[2];
            float s = q != 0.0f ? tc[0] / q : tc[0];
            float tt = q != 0.0f ? tc[1] / q : tc[1];
            sample(&T->tex[S->texmap], s, tt, tc[3], tmp);
            for (i = 0; i < 4; i++) bank[BANK_TEX + i] = tmp[S->tswap[i]];
        }
        if (S->chan < 2) {
            const int* r = ras[S->chan];
            for (i = 0; i < 4; i++) bank[BANK_RAS + i] = r[S->rswap[i]];
        }
        bank[BANK_KONST] = S->konst[0]; bank[BANK_KONST + 1] = S->konst[1];
        bank[BANK_KONST + 2] = S->konst[2]; bank[BANK_KONST + 3] = S->konst[3];

        /* Colour */
        if (S->cbias != 3) {
            int bias = S->cbias == 1 ? 128 : S->cbias == 2 ? -128 : 0;
            int res[3];
            for (i = 0; i < 3; i++) {
                int a = bank[S->ia[i]] & 0xFF, b = bank[S->ib[i]] & 0xFF, c = bank[S->ic[i]] & 0xFF, d = bank[S->id[i]];
                int cc = c + (c >> 7);
                int v = (a * (256 - cc) + b * cc + 128) >> 8;
                int r;
                if (S->cop) v = -v;
                r = d + v + bias;
                if (S->cshift == 1) r <<= 1; else if (S->cshift == 2) r <<= 2; else if (S->cshift == 3) r >>= 1;
                res[i] = S->cclamp ? clamp255(r) : clamp_s11(r);
            }
            dc[0] = res[0]; dc[1] = res[1]; dc[2] = res[2];
        } else {
            unsigned cmp = (S->cshift << 1) | S->cop;
            int a[3], b[3], c[3], d[3], res;
            for (i = 0; i < 3; i++) {
                a[i] = bank[S->ia[i]] & 0xFF; b[i] = bank[S->ib[i]] & 0xFF;
                c[i] = bank[S->ic[i]]; d[i] = bank[S->id[i]];
            }
            switch (cmp >> 1) {
            case 0: res = cmp & 1 ? a[0] == b[0] : a[0] > b[0]; break;
            case 1: { int av = (a[1] << 8) | a[0], bv = (b[1] << 8) | b[0]; res = cmp & 1 ? av == bv : av > bv; break; }
            case 2: { int av = (a[2] << 16) | (a[1] << 8) | a[0], bv = (b[2] << 16) | (b[1] << 8) | b[0]; res = cmp & 1 ? av == bv : av > bv; break; }
            default: res = -1; break;
            }
            for (i = 0; i < 3; i++) {
                int r = res == -1 ? ((cmp & 1 ? a[i] == b[i] : a[i] > b[i]) ? c[i] : 0) : (res ? c[i] : 0);
                r += d[i];
                dc[i] = S->cclamp ? clamp255(r) : clamp_s11(r);
            }
        }
        if (g_tev_narrate)
            fprintf(stderr, "[tev] stage %u: map %u coord %u texel %d,%d,%d,%d ras %d,%d,%d,%d konst %d,%d,%d,%d; color sel %u,%u,%u,%u -> %d,%d,%d (dest %u); alpha sel %u,%u,%u,%u bias %u op %u shift %u (dest %u)\n",
                    st, S->texmap, S->texcoord, bank[BANK_TEX], bank[BANK_TEX + 1], bank[BANK_TEX + 2], bank[BANK_TEX + 3],
                    bank[BANK_RAS], bank[BANK_RAS + 1], bank[BANK_RAS + 2], bank[BANK_RAS + 3], S->konst[0], S->konst[1], S->konst[2], S->konst[3],
                    S->ca, S->cb, S->cc, S->cd, dc[0], dc[1], dc[2], S->cdest, S->aa, S->ab, S->ac, S->ad, S->abias, S->aop, S->ashift, S->adest);
        /* Alpha */
        {
            int* da = &bank[S->adest * 4 + 3];
            if (S->abias != 3) {
                int a = bank[S->ja] & 0xFF, b = bank[S->jb] & 0xFF, c = bank[S->jc] & 0xFF, d = bank[S->jd];
                int cc = c + (c >> 7);
                int v = (a * (256 - cc) + b * cc + 128) >> 8, r;
                if (S->aop) v = -v;
                r = d + v + (S->abias == 1 ? 128 : S->abias == 2 ? -128 : 0);
                if (S->ashift == 1) r <<= 1; else if (S->ashift == 2) r <<= 2; else if (S->ashift == 3) r >>= 1;
                *da = S->aclamp ? clamp255(r) : clamp_s11(r);
            } else {
                unsigned cmp = (S->ashift << 1) | S->aop;
                int a = bank[S->ja] & 0xFF, b = bank[S->jb] & 0xFF, c = bank[S->jc], d = bank[S->jd];
                int res = cmp & 1 ? a == b : a > b;
                *da = S->aclamp ? clamp255(d + (res ? c : 0)) : clamp_s11(d + (res ? c : 0));
            }
        }
    }

    for (i = 0; i < 4; i++) out[i] = (uint8_t)clamp255(bank[i]);

    /* Alpha compare (PE_ALPHA_COMPARE, GXSetAlphaCompare). */
    {
        int p0 = compare(T->acomp0, out[3], T->aref0), p1 = compare(T->acomp1, out[3], T->aref1);
        switch (T->alogic) {
        case 0: *alpha_pass = p0 && p1; break;
        case 1: *alpha_pass = p0 || p1; break;
        case 2: *alpha_pass = p0 != p1; break;
        default: *alpha_pass = p0 == p1; break;
        }
    }
}
