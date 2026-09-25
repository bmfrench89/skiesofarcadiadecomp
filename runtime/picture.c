/*
 * The picture's layout in a window and its pacing to a display (H19a): see
 * picture.h. Plain C, built alone by tools/tests/test_picture.py, whose
 * Python twin of picture_layout checks a windowed run's [window] lines.
 */
#include "picture.h"

static PicRect centred(int w, int h, int dst_w, int dst_h)
{
    PicRect r;
    r.w = w;
    r.h = h;
    r.x = (dst_w - w) / 2;
    r.y = (dst_h - h) / 2;
    return r;
}

PicRect picture_layout(int src_w, int src_h, int dst_w, int dst_h, int mode)
{
    long long wide;
    if (src_w < 1 || src_h < 1 || dst_w < 1 || dst_h < 1) return centred(0, 0, dst_w > 0 ? dst_w : 0, dst_h > 0 ? dst_h : 0);
    if (mode == PICTURE_INTEGER) {
        int kx = dst_w / src_w, ky = dst_h / src_h, k = kx < ky ? kx : ky;
        if (k >= 1) return centred(src_w * k, src_h * k, dst_w, dst_h);
    }
    /* The fit: whichever side the client is shorter on, relative to the
     * image's shape, sets the scale; the other is rounded down. */
    wide = (long long)dst_w * src_h - (long long)dst_h * src_w;
    if (wide > 0) return centred((int)((long long)dst_h * src_w / src_h), dst_h, dst_w, dst_h);
    return centred(dst_w, (int)((long long)dst_w * src_h / src_w), dst_w, dst_h);
}

unsigned present_interval(double hz, int fps)
{
    double r;
    unsigned n;
    if (!(hz > 0.0) || fps < 1) return 1;
    r = hz / (double)fps;
    n = (unsigned)(r + 0.5);
    if (r - (double)n >= 0.02 || (double)n - r >= 0.02) n = 1;
    if (n < 1) n = 1;
    if (n > 4) n = 4;
    return n;
}
