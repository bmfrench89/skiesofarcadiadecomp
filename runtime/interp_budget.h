/*
 * H17b's budget (docs/specs/interp-live.md): how many in-between images does
 * the next frame get? Fed the game's own frame time, from one screen copy to
 * the next (a 30 fps frame is 33.4 ms), and `top`, the most the display's
 * rate asks for -- one for `interp = 1`, two at 85 Hz, four at 144.
 *
 * The test is the median of the last 31 frames, about a second: over 35.5 ms,
 * the in-between work is slowing the game, so one image a frame is taken
 * away (H17k) -- a slice of the GPU's work -- and at none the stream stops. A
 * median, because the game's frame times jitter without any of this: a
 * battle in a window with interpolation off runs 1 frame in 20 over 36 ms and
 * 1 in 100 over 43, often three in a row. The rule before this one (three in
 * a row over 35) stopped that battle in display mode twice in its first 4000
 * frames, where the game keeps its pace with the images on, and headless,
 * with them on throughout, first at frame 1453; this rule first at 4137, the
 * cutscene where they do slow the game (FINDINGS "H17e"). A loading hitch of
 * any length moves a median by one place, and a device that holds the game at
 * 36 ms -- 93% speed, which three-over-40 would never catch -- steps down
 * within the 31.
 *
 * An image is given back once frames are back on time: a count of 30 frames,
 * doubling after each try that failed -- a step down from the display's full
 * rate, or one that undoes a step back up; never the further steps of one
 * walk down, which H17k first doubled at too, so that one slow spell at 120
 * Hz or more left the climb back waiting 240 frames a step (the review of
 * 2026-10-26) -- up to 960 (back to 30 once the stream has held ten seconds
 * at the display's rate), down one a frame under 34.5 ms and up two a slower
 * one, so never while the game is slow without it (FINDINGS "V12"); the next
 * step up waits the count again. Coming back by the median instead brought
 * the stream back into stretches too heavy for it, to step down again within
 * the 31 each time (FINDINGS "H17i"). When the display's rate changes (the
 * window moved to another monitor) with images taken away, the images the
 * device was holding stay given, as many as the new rate has, rather than
 * the number taken; at the full rate it keeps the new full rate.
 *
 * Pure, and a header, so gxr.c and its test (test_picture.py) share the one
 * copy. All zero is the starting state: every image given, the count at 30.
 */
#ifndef SOA_INTERP_BUDGET_H
#define SOA_INTERP_BUDGET_H

#define INTERP_BUDGET_N 31u          /* frames the median is taken over */
#define INTERP_BUDGET_SLOW 35.5      /* ms: a median over this takes an image away */
#define INTERP_BUDGET_ON_TIME 34.5   /* ms: a frame under this counts down to giving one back */
#define INTERP_BUDGET_TRIES 5u       /* the count doubles at most this often, 30 to 960 */

typedef struct InterpBudget {
    double last[INTERP_BUDGET_N]; /* the latest frame times while the stream is on, a ring */
    unsigned n, at;               /* how many it holds, where the next goes */
    unsigned cut;                 /* images a frame taken away; at `top` the stream is off */
    unsigned top;                 /* the most the display asked for last frame, 0 before the first */
    unsigned tries;               /* the count is 30 << tries frames */
    unsigned down;                /* the last step was down: another is the same walk, not a failed try */
    unsigned wait, held;          /* the count to the next image back; frames held at the display's rate */
    unsigned long long stops, frames_off, frames_cut; /* steps down; frames off; frames with some taken */
} InterpBudget;

/* The median of the last 31 frames, ms in, once the ring holds 31; -1 until. */
static inline double interp_budget_push(InterpBudget* b, double ms)
{
    double s[INTERP_BUDGET_N];
    unsigned i, j;
    b->last[b->at] = ms;
    b->at = (b->at + 1u) % INTERP_BUDGET_N;
    if (b->n < INTERP_BUDGET_N) b->n++;
    if (b->n < INTERP_BUDGET_N) return -1.0;
    for (i = 0; i < INTERP_BUDGET_N; i++) { /* 31 values: an insertion sort */
        double v = b->last[i];
        for (j = i; j > 0 && s[j - 1] > v; j--) s[j] = s[j - 1];
        s[j] = v;
    }
    return s[INTERP_BUDGET_N / 2u];
}

/* One frame of `ms`, the display asking for `top` images a frame: how many
 * the next frame gets, 0 for none, the stream off. */
static inline int interp_budget_step(InterpBudget* b, double ms, unsigned top)
{
    if (top == 0) top = 1;
    if (b->top && top != b->top && b->cut) {
        /* the display's rate changed with images taken: what was given stays
         * given, as many as the new rate has -- not what was taken, which at
         * a lower rate could take every image from a device holding some. A
         * device at the full rate keeps the new full rate. */
        unsigned given = b->cut < b->top ? b->top - b->cut : 0u;
        b->cut = top - (given < top ? given : top);
    }
    b->top = top;
    if (b->cut < top) {
        if (interp_budget_push(b, ms) > INTERP_BUDGET_SLOW) {
            b->cut++;
            b->n = b->at = 0;
            b->wait = 30u << b->tries;
            if (!b->down && b->tries < INTERP_BUDGET_TRIES) b->tries++;
            b->down = 1;
            b->stops++;
            return (int)(top - b->cut);
        }
        if (b->cut == 0) {
            if (++b->held == 300) b->tries = 0;
            return (int)top;
        }
        b->frames_cut++;
    } else {
        b->frames_off++;
    }
    /* Some taken away: the count to the next one back */
    if (ms > INTERP_BUDGET_ON_TIME) {
        unsigned most = 2u * (30u << b->tries);
        b->wait = b->wait + 2u > most ? most : b->wait + 2u;
    } else if (b->wait > 0) {
        b->wait--;
    } else {
        b->cut--;
        b->held = 0;
        b->down = 0;
        b->n = b->at = 0;
        b->wait = 30u << b->tries;
    }
    return (int)(top - b->cut);
}

#endif
