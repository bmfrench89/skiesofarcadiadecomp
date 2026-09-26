/*
 * The picture's layout in a window and its pacing to a display (H19a), and
 * the filters on it (P5a): see picture.h. Plain C, built alone by
 * tools/tests/test_picture.py, whose Python twin of picture_layout checks a
 * windowed run's [window] lines and whose twins of the filters hold them to
 * the spec's formulas.
 */
#include "picture.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

void picture_scale(const uint8_t* src, int w, int h, uint8_t* dst, int dw, int dh, int mode)
{
    PicRect r = picture_layout(w, h, dw, dh, mode);
    int x, y;
    if (dw < 1 || dh < 1) return;
    memset(dst, 0, (size_t)dw * dh * 4);
    for (y = 0; y < r.h; y++) {
        const uint32_t* s = (const uint32_t*)(src + (size_t)((long long)y * h / r.h) * w * 4);
        uint32_t* d = (uint32_t*)(dst + ((size_t)(r.y + y) * dw + r.x) * 4);
        for (x = 0; x < r.w; x++) d[x] = s[(long long)x * w / r.w];
    }
}

/* ---- P5a: the filters (comfort-pack spec 3.13) ---------------------------- */

#define ENC_N 65536 /* the encode table's steps over linear 0-1: 20 to the darkest sRGB step */

/* Machado, Oliveira and Fernandes (2009), severity 1.0, rows multiplying
 * linear (R, G, B); each row sums to 1, so grey stays grey. */
static const double k_sim[3][9] = {
    {0.152286, 1.052583, -0.204868, 0.114503, 0.786281, 0.099216, -0.003882, -0.048116, 1.051998},
    {0.367322, 0.860646, -0.227968, 0.280085, 0.672501, 0.047413, -0.011820, 0.042940, 0.968881},
    {1.255528, -0.076749, -0.178779, -0.078411, 0.930809, 0.147602, 0.004733, 0.691367, 0.303900},
};

/* One pixel's flash history, WCAG's way: the luminance it last turned at (a
 * peak while rising, a trough while falling; before its first turn, the
 * lowest and highest it has shown), the half-flash waiting for its
 * opposite, when its last three flashes ended, and when it last ended a
 * fourth inside a second -- which keeps it counted against the quarter of
 * the picture for a second after. */
typedef struct {
    float ext, hi, pend_t, ends[3], over;
    signed char trend, pend; /* +1 rising, -1 falling, 0 not yet either */
} FlashPixel;

struct PicFilterState {
    PicFilters f;
    float m[9];       /* the colour-blind matrix, correction folded in */
    float lin[256];   /* an sRGB byte in linear light */
    uint8_t gam[256]; /* the gamma table */
    uint8_t* enc;     /* linear, in ENC_N - 1 steps, back to an sRGB byte */
    /* the flash limiter: the frame shown last, and each pixel's own history */
    int w, h, have_prev;
    double t0;        /* the first frame's time: the times below are seconds after it */
    uint8_t *prev, *mix;
    float* lum;
    FlashPixel* px;
    size_t* cand; /* the pixels that would end a fourth flash, for the search */
    unsigned long long frames, held;
    double most_over; /* the largest share of the picture over three flashes in a second */
};

static double srgb_to_linear(double c)
{
    return c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4);
}

static double linear_to_srgb(double l)
{
    return l <= 0.0031308 ? 12.92 * l : 1.055 * pow(l, 1.0 / 2.4) - 0.055;
}

static int set(const char* v)
{
    return v && *v;
}

/* The first refusal is the one named; each key stands alone, so a typo in
 * gamma leaves the flash limiter on. */
static int refuse(char* why, size_t cap, int ok, const char* what, const char* value, const char* want)
{
    if (ok && why && cap) snprintf(why, cap, "%s = %s is not %s; that key is left at its default", what, value, want);
    return 0;
}

int picture_filters_parse(PicFilters* f, const char* gamma, const char* colorblind, const char* mode, const char* flash,
                          char* why, size_t cap)
{
    int ok = 1;
    memset(f, 0, sizeof *f);
    f->gamma = 1.0;
    if (set(gamma)) {
        char* end;
        double g = strtod(gamma, &end);
        if (*end || !(g >= 0.5 && g <= 2.5)) ok = refuse(why, cap, ok, "gamma", gamma, "a number from 0.5 to 2.5");
        else f->gamma = g;
    }
    if (set(colorblind) && strcmp(colorblind, "off") && strcmp(colorblind, "0")) {
        if (!strcmp(colorblind, "protan")) f->colorblind = PIC_CB_PROTAN;
        else if (!strcmp(colorblind, "deutan")) f->colorblind = PIC_CB_DEUTAN;
        else if (!strcmp(colorblind, "tritan")) f->colorblind = PIC_CB_TRITAN;
        else ok = refuse(why, cap, ok, "colorblind", colorblind, "off, protan, deutan or tritan");
    }
    if (set(mode) && strcmp(mode, "correct")) {
        if (!strcmp(mode, "simulate")) f->colorblind_mode = PIC_CB_SIMULATE;
        else ok = refuse(why, cap, ok, "colorblind_mode", mode, "correct or simulate");
    }
    if (set(flash) && strcmp(flash, "0") && strcmp(flash, "off")) {
        if (!strcmp(flash, "1") || !strcmp(flash, "on")) f->flash_limit = 1;
        else ok = refuse(why, cap, ok, "flash_limit", flash, "0 or 1");
    }
    return ok;
}

int picture_filters_any(const PicFilters* f)
{
    return f->gamma != 1.0 || f->colorblind != PIC_CB_OFF || f->flash_limit;
}

void picture_filters_name(const PicFilters* f, char* out, size_t cap)
{
    static const char* const cb[] = {"off", "protan", "deutan", "tritan"};
    snprintf(out, cap, "gamma %.2f, colour-blind %s%s, flash limit %s", f->gamma, cb[f->colorblind & 3],
             f->colorblind ? (f->colorblind_mode == PIC_CB_SIMULATE ? " simulated" : " corrected") : "",
             f->flash_limit ? "on" : "off");
}

PicFilterState* picture_filters_new(const PicFilters* f)
{
    PicFilterState* s = (PicFilterState*)calloc(1, sizeof *s);
    int i, r, c;
    if (!s) return NULL;
    s->f = *f;
    s->enc = (uint8_t*)malloc(ENC_N);
    if (!s->enc) {
        free(s);
        return NULL;
    }
    for (i = 0; i < 256; i++) {
        s->lin[i] = (float)srgb_to_linear(i / 255.0);
        s->gam[i] = (uint8_t)floor(255.0 * pow(i / 255.0, 1.0 / f->gamma) + 0.5);
    }
    for (i = 0; i < ENC_N; i++) s->enc[i] = (uint8_t)floor(255.0 * linear_to_srgb((double)i / (ENC_N - 1)) + 0.5);
    if (f->colorblind) {
        /* Simulation is the matrix. Correction is Fidaner, Lin and Ozguven's
         * error redistribution, rgb + C (rgb - S rgb), which is linear too:
         * (I + C - C S) rgb, with C = [0 0 0; 0.7 1 0; 0.7 0 1]. */
        const double* S = k_sim[(f->colorblind - 1) % 3];
        static const double C[9] = {0, 0, 0, 0.7, 1, 0, 0.7, 0, 1};
        for (r = 0; r < 3; r++)
            for (c = 0; c < 3; c++) {
                double v = S[r * 3 + c];
                if (f->colorblind_mode == PIC_CB_CORRECT) {
                    double cs = C[r * 3 + 0] * S[0 * 3 + c] + C[r * 3 + 1] * S[1 * 3 + c] + C[r * 3 + 2] * S[2 * 3 + c];
                    v = (r == c ? 1.0 : 0.0) + C[r * 3 + c] - cs;
                }
                s->m[r * 3 + c] = (float)v;
            }
    }
    return s;
}

void picture_filters_free(PicFilterState* s)
{
    if (!s) return;
    free(s->enc);
    free(s->prev);
    free(s->mix);
    free(s->lum);
    free(s->px);
    free(s->cand);
    free(s);
}

static uint8_t encode(const PicFilterState* s, float l)
{
    if (!(l > 0.0f)) return 0;
    if (l >= 1.0f) return 255;
    return s->enc[(int)(l * (ENC_N - 1) + 0.5f)];
}

static void colour(const PicFilterState* s, uint8_t* p, size_t n)
{
    const float* m = s->m;
    size_t i;
    for (i = 0; i < n; i++, p += 4) {
        float b = s->lin[p[0]], g = s->lin[p[1]], r = s->lin[p[2]];
        p[2] = encode(s, m[0] * r + m[1] * g + m[2] * b);
        p[1] = encode(s, m[3] * r + m[4] * g + m[5] * b);
        p[0] = encode(s, m[6] * r + m[7] * g + m[8] * b);
    }
}

/* Relative luminance, WCAG's: 0.2126 R + 0.7152 G + 0.0722 B in linear light. */
static void luminance(const PicFilterState* s, const uint8_t* p, size_t n, float* out)
{
    size_t i;
    for (i = 0; i < n; i++, p += 4) out[i] = 0.2126f * s->lin[p[2]] + 0.7152f * s->lin[p[1]] + 0.0722f * s->lin[p[0]];
}

/* The half of a flash a pixel at luminance `l` makes against its history --
 * WCAG's general flash, pixel by pixel: a move of 0.1 or more from where it
 * last turned, the other way from the way it was going, with the darker of
 * the two below 0.8. Before its first turn a fall is measured from the
 * highest it has shown and a rise from the lowest. +1 lighter, -1 darker, 0
 * none. Measured from the turn and not from the frame before, a flash spread
 * over several frames counts, and a cloud moving past, lighter here and
 * darker there, is each pixel's own affair. */
static int half_flash(const FlashPixel* q, float l)
{
    float top = q->trend ? q->ext : q->hi;
    if (q->trend >= 0 && top - l >= 0.1f && l < 0.8f) return -1;
    if (q->trend <= 0 && l - q->ext >= 0.1f && q->ext < 0.8f) return 1;
    return 0;
}

/* A second, and a millisecond more: a flash that ended a second ago to the
 * float still counts, so the limiter errs toward holding. */
#define FLASH_WINDOW 1.001f

/* Whether that half, `d`, would end the pixel's fourth flash in a second. */
static int fourth(const FlashPixel* q, int d, float t)
{
    int k, n = 0;
    if (!d || q->pend != -d || t - q->pend_t >= FLASH_WINDOW) return 0;
    for (k = 0; k < 3; k++) n += t - q->ends[k] < FLASH_WINDOW;
    return n >= 3;
}

/* Whether a pixel ended a fourth flash inside the last second: it is over
 * the limit, and counts against the quarter of the picture until then. */
static int over(const FlashPixel* q, float t)
{
    return t - q->over < FLASH_WINDOW;
}

/* The luminance of one BGRA pixel, before + a (now - before). */
static float blended_luminance(const PicFilterState* s, const uint8_t* before, const uint8_t* now, int k)
{
    int c, v[3];
    for (c = 0; c < 3; c++) {
        int d = ((int)now[c] - (int)before[c]) * k;
        v[c] = before[c] + (d >= 0 ? (d + 128) / 256 : -((-d + 128) / 256));
    }
    return 0.2126f * s->lin[v[2]] + 0.7152f * s->lin[v[1]] + 0.0722f * s->lin[v[0]];
}

/* The frame is shown: each pixel's history takes it. The answer is how many
 * pixels are over the limit after it, for the report. */
static size_t commit(PicFilterState* s, const float* l, size_t n, float t)
{
    size_t i, late = 0;
    for (i = 0; i < n; i++) {
        FlashPixel* q = &s->px[i];
        int d = half_flash(q, l[i]);
        if (d) {
            if (q->pend == -d && t - q->pend_t < FLASH_WINDOW) {
                int o = 0, j;
                if (fourth(q, d, t)) q->over = t;
                for (j = 1; j < 3; j++)
                    if (q->ends[j] < q->ends[o]) o = j; /* the oldest end gives way */
                q->ends[o] = t;
                q->pend = 0;
            } else {
                q->pend = (signed char)d;
                q->pend_t = t;
            }
            q->trend = (signed char)d;
            q->ext = l[i];
        } else if (q->trend > 0) {
            if (l[i] > q->ext) q->ext = l[i]; /* still rising: it turns later */
        } else if (q->trend < 0) {
            if (l[i] < q->ext) q->ext = l[i];
        } else {
            if (l[i] < q->ext) q->ext = l[i];
            if (l[i] > q->hi) q->hi = l[i];
        }
        late += (size_t)over(q, t);
    }
    return late;
}

/* before + a (now - before), a byte at a time, `a` in 1/256ths. */
static void blend(uint8_t* dst, const uint8_t* before, const uint8_t* now, size_t bytes, double a)
{
    int k = (int)(a * 256.0 + 0.5);
    size_t i;
    for (i = 0; i < bytes; i++) {
        int d = ((int)now[i] - (int)before[i]) * k;
        dst[i] = (uint8_t)(before[i] + (d >= 0 ? (d + 128) / 256 : -((-d + 128) / 256)));
    }
}

static void flash_free(PicFilterState* s)
{
    free(s->prev);
    free(s->mix);
    free(s->lum);
    free(s->px);
    free(s->cand);
    s->prev = s->mix = NULL;
    s->lum = NULL;
    s->px = NULL;
    s->cand = NULL;
}

static int flash_buffers(PicFilterState* s, int w, int h)
{
    size_t n = (size_t)w * h;
    if (s->prev && s->w == w && s->h == h) return 1;
    flash_free(s);
    s->prev = (uint8_t*)malloc(n * 4);
    s->mix = (uint8_t*)malloc(n * 4);
    s->lum = (float*)malloc(n * sizeof(float));
    s->px = (FlashPixel*)malloc(n * sizeof(FlashPixel));
    s->cand = (size_t*)malloc(n * sizeof(size_t));
    s->w = w;
    s->h = h;
    s->have_prev = 0;
    if (s->prev && s->mix && s->lum && s->px && s->cand) return 1;
    flash_free(s);
    return 0;
}

/* Over the whole frame of luminance `l`: how many pixels are over the limit
 * already (`lately`), and how many more would end a fourth flash now. The
 * latter are listed in s->cand when `list` is set. */
static size_t fourths(PicFilterState* s, const float* l, size_t n, float t, size_t* lately, int list)
{
    size_t i, now = 0, late = 0;
    for (i = 0; i < n; i++) {
        const FlashPixel* q = &s->px[i];
        if (over(q, t)) {
            late++;
        } else if (q->pend && fourth(q, half_flash(q, l[i]), t)) {
            if (list) s->cand[now] = i;
            now++;
        }
    }
    *lately = late;
    return now;
}

/* Whether a frame breaks the rule: pixels would end a fourth flash, and with
 * those already over the limit in the last second they cover a quarter of
 * the picture or more. */
static int too_much(size_t now, size_t lately, size_t n)
{
    return now && (now + lately) * 4 >= n;
}

/* The flash limiter (WCAG 2.3.1's general flash, Xbox guideline 118): no
 * more than a quarter of the picture flashing more than three times in any
 * second. A pixel that ends a fourth flash inside a second is over the limit
 * for a second after; when the pixels over it, with those that would end a
 * fourth now, would cover a quarter of the frame, the frame is blended
 * toward the one shown before, as far as it can go and stay under. The
 * search looks only at the pixels that would end a fourth at full strength,
 * and the frame it picks is checked whole. */
static double limit_flashes(PicFilterState* s, uint8_t* p, int w, int h, double when)
{
    size_t n = (size_t)w * h, i, now, lately, c;
    double a = 1.0;
    float t;
    if (!flash_buffers(s, w, h)) return 1.0;
    luminance(s, p, n, s->lum);
    if (!s->have_prev) {
        s->have_prev = 1;
        s->t0 = when;
        for (i = 0; i < n; i++) {
            FlashPixel* q = &s->px[i];
            q->ext = q->hi = s->lum[i];
            q->trend = q->pend = 0;
            q->pend_t = q->ends[0] = q->ends[1] = q->ends[2] = q->over = -1e6f;
        }
        memcpy(s->prev, p, n * 4);
        return 1.0;
    }
    t = (float)(when - s->t0);
    now = fourths(s, s->lum, n, t, &lately, 1);
    if (too_much(now, lately, n)) {
        double lo = 0.0, hi = 1.0;
        int k, full = 0;
        for (;;) {
            for (k = 0; k < 8; k++) { /* to the blend's own 1/256 */
                double mid = (lo + hi) / 2.0;
                size_t m = 0;
                if (full) {
                    blend(s->mix, s->prev, p, n * 4, mid);
                    luminance(s, s->mix, n, s->lum);
                    m = fourths(s, s->lum, n, t, &lately, 0);
                } else {
                    int kk = (int)(mid * 256.0 + 0.5);
                    for (c = 0; c < now; c++) {
                        size_t j = s->cand[c];
                        const FlashPixel* q = &s->px[j];
                        m += (size_t)fourth(q, half_flash(q, blended_luminance(s, s->prev + 4 * j, p + 4 * j, kk)), t);
                    }
                }
                if (too_much(m, lately, n)) hi = mid;
                else lo = mid;
            }
            /* the whole frame at the blend chosen: a pixel that was not a
             * candidate at full strength could be one part of the way */
            blend(s->mix, s->prev, p, n * 4, lo);
            luminance(s, s->mix, n, s->lum);
            if (full || !too_much(fourths(s, s->lum, n, t, &lately, 0), lately, n)) break;
            full = 1;
            lo = 0.0;
            hi = 1.0;
        }
        a = lo;
        memcpy(p, s->mix, n * 4);
        s->held++;
    }
    lately = commit(s, s->lum, n, t);
    if ((double)lately / (double)n > s->most_over) s->most_over = (double)lately / (double)n;
    memcpy(s->prev, p, n * 4);
    return a;
}

double picture_filter(PicFilterState* s, uint8_t* p, int w, int h, double t)
{
    size_t n, i;
    if (!s || !p || w < 1 || h < 1) return 1.0;
    n = (size_t)w * h;
    s->frames++;
    if (s->f.colorblind) colour(s, p, n);
    if (s->f.gamma != 1.0)
        for (i = 0; i < n * 4; i += 4) {
            p[i] = s->gam[p[i]];
            p[i + 1] = s->gam[p[i + 1]];
            p[i + 2] = s->gam[p[i + 2]];
        }
    return s->f.flash_limit ? limit_flashes(s, p, w, h, t) : 1.0;
}

void picture_filter_counts(const PicFilterState* s, unsigned long long* frames, unsigned long long* held, double* most_over)
{
    *frames = s ? s->frames : 0;
    *held = s ? s->held : 0;
    *most_over = s ? s->most_over : 0.0;
}
