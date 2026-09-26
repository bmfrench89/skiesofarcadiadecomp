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

/* ---- P5a: filters on the frame at its own size, before it is scaled ----
 * The frame is BGRA, 8 bits a channel, as window.c presents it. In order:
 * the colour-blind model in linear light, then gamma, then the flash limiter
 * on what the first two made, since what flashes is what is shown. */
#include <stddef.h>
#include <stdint.h>

enum { PIC_CB_OFF = 0, PIC_CB_PROTAN = 1, PIC_CB_DEUTAN = 2, PIC_CB_TRITAN = 3 };
enum { PIC_CB_CORRECT = 0, PIC_CB_SIMULATE = 1 };

typedef struct {
    double gamma;        /* 1 is the picture as the game made it; above 1 lighter, 0.5 to 2.5 */
    int colorblind;      /* PIC_CB_OFF, _PROTAN, _DEUTAN or _TRITAN */
    int colorblind_mode; /* PIC_CB_CORRECT or PIC_CB_SIMULATE */
    int flash_limit;     /* 1: no more than three flashes in any second */
} PicFilters;

/* The four keys' values, NULL or "" for unset. 1 when every one reads;
 * otherwise 0 and why the first did not in `why`, with that key at its
 * default and the others in `f` as they were given. */
int picture_filters_parse(PicFilters* f, const char* gamma, const char* colorblind, const char* mode, const char* flash,
                          char* why, size_t cap);
int picture_filters_any(const PicFilters* f);
void picture_filters_name(const PicFilters* f, char* out, size_t cap); /* "gamma 1.2, deutan correction, ..." */

typedef struct PicFilterState PicFilterState;
PicFilterState* picture_filters_new(const PicFilters* f); /* its tables, and the flash limiter's memory */
void picture_filters_free(PicFilterState* s);

/* Filters a w x h frame in place, shown at `t` seconds. The answer is the
 * flash limiter's blend: 1 the frame as filtered, less when it was held back
 * toward the frame before. */
double picture_filter(PicFilterState* s, uint8_t* bgra, int w, int h, double t);
/* Frames filtered, frames the flash limiter held back, and the largest
 * share of the picture that was ever over three flashes in a second (the
 * limit keeps it under a quarter). */
void picture_filter_counts(const PicFilterState* s, unsigned long long* frames, unsigned long long* held,
                           double* most_over);

/* A w x h frame into a dw x dh buffer where picture_layout puts it, nearest
 * neighbour, black round it: the present's scaler, and the replay's. */
void picture_scale(const uint8_t* src, int w, int h, uint8_t* dst, int dw, int dh, int mode);

#endif
