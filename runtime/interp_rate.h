/*
 * H17c-b (docs/specs/interp-display.md): the in-between images a game frame
 * gets on a display of `hz` refreshes a second, the game at 30 frames, RT64's
 * integer accumulator ("Display" mode). Refresh i shows the game at
 * s = i * 30 / hz frames, so frame f's images are the refreshes with s in
 * (f, f + 1], each at weight s - f: with r = (f * hz) mod 30, there are
 * n = (r + hz) / 30 of them, the j-th at (30 * j - r) / hz, the last exactly
 * 1 -- the frame's own real image -- when the frame ends on a refresh. 85 Hz
 * gives 17 refreshes every 6 frames, one frame of 2 images and five of 3;
 * 90 Hz 1/3, 2/3 and 1 every frame; 60 Hz 0.5 and 1.
 *
 * Pure, and a header, so the producer (gxr.c) and its test (test_picture.py)
 * share the one copy.
 */
#ifndef SOA_INTERP_RATE_H
#define SOA_INTERP_RATE_H

#define INTERP_RATE_MIN 30u  /* below the game's own rate there is nothing between frames */
#define INTERP_RATE_MAX 240u /* 8 images a frame, GXR_MID_MAX */

/* Frame f's weights, ascending in (0, 1], into w (room for 8), and their
 * count; *r is frame f's remainder going in and frame f + 1's coming out.
 * hz is held to [INTERP_RATE_MIN, INTERP_RATE_MAX]. */
static inline unsigned interp_rate_weights(unsigned hz, unsigned* r, float* w)
{
    unsigned n, j;
    if (hz < INTERP_RATE_MIN) hz = INTERP_RATE_MIN;
    if (hz > INTERP_RATE_MAX) hz = INTERP_RATE_MAX;
    n = (*r + hz) / 30u;
    for (j = 1; j <= n; j++) w[j - 1] = (float)(30u * j - *r) / (float)hz;
    *r = (*r + hz) % 30u;
    return n;
}

/* A display's refresh as RT64 rounds it: to the nearest whole Hz, and a rate
 * ending in 9 up, so 59, 59.94 and 60 are all 60, 119.88 is 120 and 143.98
 * is 144. */
static inline unsigned interp_rate_round(double hz)
{
    unsigned n = hz > 0.0 ? (unsigned)(hz + 0.5) : 0u;
    if (n % 10u == 9u) n++;
    return n;
}

#endif
