/*
 * H17b's budget (docs/specs/interp-live.md): does the next frame get its
 * in-between images? Fed the game's own frame time, from one screen copy to
 * the next; a 30 fps frame is 33.4 ms.
 *
 * The test is the median of the last 31 frames, about a second: over 35.5 ms,
 * the in-between work is slowing the game, so it stops. A median, because the
 * game's frame times jitter without any of this: a battle in a window with
 * interpolation off runs 1 frame in 20 over 36 ms and 1 in 100 over 43, often
 * three in a row. The rule before this one (three in a row over 35) stopped
 * that battle in display mode twice in its first 4000 frames, where the game
 * keeps its pace with the images on, and headless, with them on throughout,
 * first at frame 1453; this rule first at 4137, the cutscene where they do
 * slow the game (FINDINGS "H17e"). A loading hitch of any length moves a
 * median by one place, and a device that holds the game at 36 ms -- 93%
 * speed, which three-over-40 would never catch -- stops within the 31.
 *
 * It starts again once frames are back on time: a count of 30 frames,
 * doubling after each try that failed up to 960 (back to 30 once a try has
 * held ten seconds), down one a frame under 34.5 ms and up two a slower one,
 * so never while the game is slow without it (FINDINGS "V12").
 *
 * Pure, and a header, so gxr.c and its test (test_picture.py) share the one
 * copy. All zero is the starting state: on, the count at 30.
 */
#ifndef SOA_INTERP_BUDGET_H
#define SOA_INTERP_BUDGET_H

#define INTERP_BUDGET_N 31u          /* frames the median is taken over */
#define INTERP_BUDGET_SLOW 35.5      /* ms: a median over this stops the images */
#define INTERP_BUDGET_ON_TIME 34.5   /* ms: while stopped, a frame under this counts down */
#define INTERP_BUDGET_TRIES 5u       /* the count doubles at most this often, 30 to 960 */

typedef struct InterpBudget {
    double last[INTERP_BUDGET_N]; /* the latest frame times while on, a ring */
    unsigned n, at;               /* how many it holds, where the next goes */
    unsigned off;                 /* the images stopped */
    unsigned tries;               /* the count is 30 << tries frames */
    unsigned wait, held;          /* the count while off; frames on since the last start */
    unsigned long long stops, frames_off;
} InterpBudget;

/* One frame of `ms`: 1 if the next frame builds its in-between images. */
static inline int interp_budget_step(InterpBudget* b, double ms)
{
    if (!b->off) {
        b->last[b->at] = ms;
        b->at = (b->at + 1u) % INTERP_BUDGET_N;
        if (b->n < INTERP_BUDGET_N) b->n++;
        if (b->n == INTERP_BUDGET_N) {
            double s[INTERP_BUDGET_N];
            unsigned i, j;
            for (i = 0; i < INTERP_BUDGET_N; i++) { /* 31 values: an insertion sort */
                double v = b->last[i];
                for (j = i; j > 0 && s[j - 1] > v; j--) s[j] = s[j - 1];
                s[j] = v;
            }
            if (s[INTERP_BUDGET_N / 2u] > INTERP_BUDGET_SLOW) {
                b->off = 1;
                b->n = b->at = 0;
                b->wait = 30u << b->tries;
                if (b->tries < INTERP_BUDGET_TRIES) b->tries++;
                b->stops++;
                return 0;
            }
        }
        if (++b->held == 300) b->tries = 0;
        return 1;
    }
    b->frames_off++;
    if (ms > INTERP_BUDGET_ON_TIME) {
        unsigned most = 2u * (30u << b->tries);
        b->wait = b->wait + 2u > most ? most : b->wait + 2u;
    } else if (b->wait > 0) {
        b->wait--;
    } else {
        b->off = 0;
        b->held = 0;
        return 1;
    }
    return 0;
}

#endif
