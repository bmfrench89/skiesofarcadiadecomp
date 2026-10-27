/*
 * M20 (docs/specs/mod-overlay.md): what mods draw over the picture -- the
 * frame's lists built on the guest thread, handed to the window thread
 * through a triple buffer, and drawn there. See overlay.h.
 *
 * The hand-over is the screen ring's pattern (gxr.c): three frames, one the
 * guest thread builds, one the window thread draws, and the third published
 * in one atomic word with a bit that says it is newer than the window
 * thread's. Publishing swaps the built frame into the word; taking swaps the
 * drawn one out, only when the bit says there is a newer one. Each side owns
 * its frame outright between swaps, so nothing else is shared.
 */
#include "overlay.h"
#include "font5x7.h"
#include "plat.h"

#include <stdio.h>
#include <string.h>

#define MODS 32           /* mod.c's MOD_MAX */
#define CMDS OVERLAY_CMDS
#define TEXT OVERLAY_TEXT
#define FRESH 4           /* in g_shared: the frame there is newer than the window thread's */
#define UNITS_W 640       /* the game's picture, the units mods draw in */
#define UNITS_H 480

enum { K_RECT, K_TEXT };

typedef struct {
    int32_t x, y, w, h; /* a rect's; a text's x, y, and its size in w */
    uint32_t rgba;
    uint16_t at, len;   /* a text's bytes in the frame's text */
    uint8_t kind;
} Cmd;

typedef struct {
    int n, used; /* draws, and text bytes used */
    Cmd cmd[CMDS];
    char text[TEXT];
} Frame;

static Frame g_frame[3];
static plat_a64 g_shared = 1;    /* frame 1 published at the start, empty */
static int g_back, g_front = 2;  /* the guest thread's frame, and the window thread's */
static int g_mod_cmds[MODS], g_mod_text[MODS]; /* this frame's, per mod */
static int g_last_n;             /* draws in the frame published last (the guest thread's) */

static int room(int m, int text)
{
    Frame* f = &g_frame[g_back];
    return m >= 0 && m < MODS && f->n < CMDS && g_mod_cmds[m] < OVERLAY_MOD_CMDS && f->used + text <= TEXT &&
           g_mod_text[m] + text <= OVERLAY_MOD_TEXT;
}

int overlay_rect(int m, int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgba)
{
    Cmd* c;
    if (!room(m, 0)) return 0;
    c = &g_frame[g_back].cmd[g_frame[g_back].n++];
    c->kind = K_RECT;
    c->x = x;
    c->y = y;
    c->w = w;
    c->h = h;
    c->rgba = rgba;
    c->at = c->len = 0;
    g_mod_cmds[m]++;
    return 1;
}

int overlay_text(int m, int32_t x, int32_t y, uint32_t size, uint32_t rgba, const char* text)
{
    Frame* f = &g_frame[g_back];
    size_t len = text ? strlen(text) : 0;
    Cmd* c;
    if (size < 1 || size > 8 || len > 255 || !room(m, (int)len)) return 0;
    c = &f->cmd[f->n++];
    c->kind = K_TEXT;
    c->x = x;
    c->y = y;
    c->w = (int32_t)size;
    c->h = 0;
    c->rgba = rgba;
    c->at = (uint16_t)f->used;
    c->len = (uint16_t)len;
    memcpy(f->text + f->used, text, len);
    f->used += (int)len;
    g_mod_cmds[m]++;
    g_mod_text[m] += (int)len;
    return 1;
}

void overlay_publish(void)
{
    Frame* f = &g_frame[g_back];
    if (!f->n && !g_last_n) return; /* nothing then and nothing now */
    g_last_n = f->n;
    g_back = (int)(plat_xchg64(&g_shared, g_back | FRESH) & 3);
    g_frame[g_back].n = g_frame[g_back].used = 0;
    memset(g_mod_cmds, 0, sizeof g_mod_cmds);
    memset(g_mod_text, 0, sizeof g_mod_text);
}

int overlay_take(void)
{
    if (plat_load64(&g_shared) & FRESH) g_front = (int)(plat_xchg64(&g_shared, g_front) & 3);
    return g_frame[g_front].n > 0;
}

/* ---- the drawing (the window thread) -------------------------------------- */

typedef struct {
    uint8_t* px;
    int w, h, stride, alpha;
    int64_t ox, oy, sw, sh; /* the picture's corner and size: game units onto pixels */
} Canvas;

/* A pixel edge held to a pixel past each side of the client before it is
 * narrowed: a game unit near 2^31, times the scale, is far past an int, and
 * would wrap onto the screen instead of being clipped off it. */
static int edge(int64_t v, int size)
{
    return v < -1 ? -1 : v > (int64_t)size + 1 ? size + 1 : (int)v;
}

/* A game x or y onto the client, rounded to the nearest pixel, so two draws
 * that meet in game units meet on the screen whatever the scale. */
static int map_x(const Canvas* c, int64_t gx)
{
    int64_t v = gx * c->sw;
    return edge(c->ox + (v >= 0 ? v + UNITS_W / 2 : v - UNITS_W / 2) / UNITS_W, c->w);
}

static int map_y(const Canvas* c, int64_t gy)
{
    int64_t v = gy * c->sh;
    return edge(c->oy + (v >= 0 ? v + UNITS_H / 2 : v - UNITS_H / 2) / UNITS_H, c->h);
}

/* One pixel: straight alpha over what is there. Into the picture (alpha 0),
 * the colour blended into the picture's; into the GPU's buffer (alpha 1),
 * "over" with what the buffer already holds, so two translucent draws stack
 * as they would on the picture. */
static void blend(uint8_t* p, uint32_t rgba, int alpha)
{
    unsigned a = rgba & 0xFF, s[3] = {rgba >> 8 & 0xFF, rgba >> 16 & 0xFF, rgba >> 24 & 0xFF}; /* B, G, R */
    int k;
    if (a == 255) {
        for (k = 0; k < 3; k++) p[k] = (uint8_t)s[k];
        if (alpha) p[3] = 255;
        return;
    }
    if (!alpha) {
        for (k = 0; k < 3; k++) p[k] = (uint8_t)((s[k] * a + p[k] * (255 - a) + 127) / 255);
        return;
    }
    {
        unsigned da = p[3], under = da * (255 - a) / 255, oa = a + under;
        if (!oa) return;
        for (k = 0; k < 3; k++) p[k] = (uint8_t)((s[k] * a + p[k] * under + oa / 2) / oa);
        p[3] = (uint8_t)oa;
    }
}

/* A rectangle in game units, [gx, gx + gw) x [gy, gy + gh), clipped to the client. */
static int fill(const Canvas* c, int64_t gx, int64_t gy, int64_t gw, int64_t gh, uint32_t rgba)
{
    int x0, y0, x1, y1, x, y;
    if (gw <= 0 || gh <= 0 || !(rgba & 0xFF)) return 0;
    x0 = map_x(c, gx);
    y0 = map_y(c, gy);
    x1 = map_x(c, gx + gw);
    y1 = map_y(c, gy + gh);
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > c->w) x1 = c->w;
    if (y1 > c->h) y1 = c->h;
    for (y = y0; y < y1; y++) {
        uint8_t* row = c->px + (size_t)y * (size_t)c->stride;
        for (x = x0; x < x1; x++) blend(row + (size_t)x * 4, rgba, c->alpha);
    }
    return x1 > x0 && y1 > y0;
}

/* A line of text: menu.c's cells, each font pixel a size x size square in
 * game units, so the cells keep their places in game units at every scale. */
static int text(const Canvas* c, const Cmd* cmd, const char* s)
{
    int64_t size = cmd->w, x = cmd->x;
    int i, r, col, drew = 0;
    for (i = 0; i < cmd->len; i++, x += FONT_CELL_W * size) {
        int ch = (unsigned char)s[i], drop;
        if (ch < 32 || ch > 126) ch = '?';
        drop = ch == 'g' || ch == 'j' || ch == 'p' || ch == 'q' || ch == 'y';
        for (r = 0; r < 7; r++)
            for (col = 0; col < 5; col++)
                if (k_font[ch - 32][r][col] == '#')
                    drew |= fill(c, x + col * size, cmd->y + (r + 1 + drop) * size, size, size, cmd->rgba);
    }
    return drew;
}

int overlay_draw(uint8_t* bgra, int w, int h, int stride, int px, int py, int pw, int ph, int alpha)
{
    const Frame* f = &g_frame[g_front];
    Canvas c;
    int i, drew = 0;
    if (!bgra || w <= 0 || h <= 0 || pw <= 0 || ph <= 0 || !f->n) return 0;
    c.px = bgra;
    c.w = w;
    c.h = h;
    c.stride = stride;
    c.alpha = alpha;
    c.ox = px;
    c.oy = py;
    c.sw = pw;
    c.sh = ph;
    for (i = 0; i < f->n; i++) {
        const Cmd* cmd = &f->cmd[i];
        drew |= cmd->kind == K_RECT ? fill(&c, cmd->x, cmd->y, cmd->w, cmd->h, cmd->rgba)
                                    : text(&c, cmd, f->text + cmd->at);
    }
    return drew;
}

size_t overlay_describe(char* out, size_t cap)
{
    const Frame* f = &g_frame[g_front];
    size_t n = 0;
    int i;
    if (!out || !cap) return 0;
    out[0] = '\0';
    for (i = 0; i < f->n && n < cap; i++) {
        const Cmd* c = &f->cmd[i];
        if (c->kind == K_RECT)
            n += (size_t)snprintf(out + n, cap - n, "rect %d %d %d %d %08X\n", c->x, c->y, c->w, c->h, c->rgba);
        else
            n += (size_t)snprintf(out + n, cap - n, "text %d %d %d %08X %.*s\n", c->x, c->y, c->w, c->rgba, c->len,
                                  f->text + c->at);
    }
    return n < cap ? n : cap - 1;
}
