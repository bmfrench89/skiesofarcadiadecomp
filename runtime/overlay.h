/*
 * M20 (docs/specs/mod-overlay.md): what mods draw over the picture.
 *
 * Two sides. The guest thread, the only one mods run on, adds each mod's
 * rectangles and lines of text to this frame's list (overlay_rect,
 * overlay_text, from mod.c's draw_rect and draw_text), and at each frame end
 * overlay_publish hands the lot to the window thread and starts the next
 * frame empty. The window thread takes the newest published frame at each
 * present (overlay_take) and draws it (overlay_draw): after the picture is
 * scaled and before the menu, in the game's 640x480 units mapped onto the
 * rectangle picture_layout gave the picture. Nothing here reads or writes
 * guest memory, and nothing draws into the game's own picture.
 */
#ifndef SOA_OVERLAY_H
#define SOA_OVERLAY_H

#include <stddef.h>
#include <stdint.h>

#define OVERLAY_MOD_CMDS 256  /* a mod's draws a frame */
#define OVERLAY_MOD_TEXT 4096 /* a mod's bytes of text a frame */
#define OVERLAY_CMDS 1024     /* every mod's draws a frame */
#define OVERLAY_TEXT 16384    /* every mod's bytes of text a frame */

/* The guest thread: one of mod m's draws for this frame. 1, or 0 when past
 * the mod's room or the frame's (nothing added). */
int overlay_rect(int m, int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgba);
int overlay_text(int m, int32_t x, int32_t y, uint32_t size, uint32_t rgba, const char* text);

/* The guest thread, at each frame end: this frame's draws replace the last
 * frame's. Nothing to do when neither frame drew anything. */
void overlay_publish(void);

/* The window thread: the newest published frame made the one overlay_draw
 * draws. 1 when it has anything to draw. */
int overlay_take(void);

/* The window thread: the frame taken, drawn over bgra (w x h pixels, stride
 * bytes a row) with the picture at (px, py, pw, ph). alpha 0: B G R X, each
 * draw blended into the picture there (the CPU presenters); alpha 1: B G R A
 * with straight alpha, composited into a buffer the GPU blends over the
 * picture (Vulkan), which the caller cleared. 1 when anything was drawn. */
int overlay_draw(uint8_t* bgra, int w, int h, int stride, int px, int py, int pw, int ph, int alpha);

/* For the checks: the frame taken, one line a draw ("rect X Y W H RRGGBBAA",
 * "text X Y SIZE RRGGBBAA TEXT"), into out; its length. */
size_t overlay_describe(char* out, size_t cap);

#endif
