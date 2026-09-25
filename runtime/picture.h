/*
 * How the picture is laid out in a window and paced to a display
 * (PLAN-GAMEPLAY-MODS H19a; P5a adds its options here). Pure functions: no
 * window, no Windows, so test_picture.py builds this file alone and an SDL or
 * Android front end can use it as it is.
 */
#ifndef SOA_PICTURE_H
#define SOA_PICTURE_H

typedef struct {
    int x, y, w, h;
} PicRect;

enum { PICTURE_INTEGER = 0, PICTURE_FIT = 1 };

/* Where a src_w x src_h image goes in a dst_w x dst_h client, centred:
 * PICTURE_INTEGER, the largest whole multiple that fits (and, when not even
 * one does, the fit); PICTURE_FIT, the largest rectangle of the image's shape
 * that fits. The rest of the client is black bars. */
PicRect picture_layout(int src_w, int src_h, int dst_w, int dst_h, int mode);

/* How many refreshes each frame is held at `fps` on a display of `hz`: the
 * whole number hz/fps is within 0.02 of, or 1 when it is near none,
 * clamped to 1-4 -- 2 at 60 Hz, 4 at 120, 1 at 85 and 144 (H8's rule). */
unsigned present_interval(double hz, int fps);

#endif
