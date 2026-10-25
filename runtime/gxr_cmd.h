/*
 * The renderer's commands: what the producer builds from the command stream
 * and a consumer runs -- the worker pool, or a backend that draws them
 * instead (specs/gpu-backend.md 3.1, V2). Out of gxr.c so that a backend can
 * be written against them; nothing here is the CPU rasterizer's own.
 */
#ifndef SOA_GXR_CMD_H
#define SOA_GXR_CMD_H

#include "gxr.h"

typedef struct { int x0, y0, x1, y1; } Rect;

#define GXR_MID_MAX 8 /* in-between images a frame, at most (H17c) */

typedef struct {
    int blend_en, logic_en, col_upd, alpha_upd, subtract;
    unsigned sfac, dfac, lop;
    int const_alpha; /* -1 when not enabled */
    int z_en, z_upd, ztop;
    unsigned z_func;
    /* fog (BP 0xEE-0xF2, GXSetFog): type 0 off, 2 linear, 4 exp, 5 exp2, 6/7 backwards */
    unsigned fog_type, fog_proj;
    float fog_a, fog_c;
    uint32_t fog_b_mag;
    unsigned fog_b_shift;
    uint8_t fog_color[3];
    /* blend_pixel's case, decided once a draw (H15c): 0 the general one, 1 no
     * blend and no logic op, 2 the source-alpha blend (GX_BL_SRCALPHA,
     * GX_BL_INVSRCALPHA, adding), which 57% of the H6 set's pixels use. */
    unsigned blend_kind;
} PixelCfg;

typedef struct {
    Rect scissor;
    unsigned cull;
    float wd, ht, zrange, xorig, yorig, farz; /* viewport, offsets applied */
} RasterCfg;

typedef struct {
    /* The number this command was published as. A worker asking for command n
     * finds it in slot n & QMASK and checks this before running it, so the day
     * a change lets the producer get QUEUE_CAP commands ahead of a worker, the
     * run says so instead of rasterizing a command built over the one it
     * wanted. See the queue's declarations for why it cannot happen today. */
    long long seq;
    /* A fence (H14): no worker starts this command until every other worker
     * has finished every command numbered below it. 0 is none; never above
     * seq, so the worker furthest behind can always run. fence_near is the
     * same, asked only of the worker's two neighbours -- the workers that own
     * the rows either side of its own -- which is all a filtered copy reads
     * (FINDINGS "Neighbour fences"); 0 when fence covers it. */
    long long fence, fence_near;
    int kind; /* 0 draw, 1 EFB copy, 2 the EFB clear that followed one */
    /* The EFB the command is for: 0 the real frame, 1 an in-between image
     * (H17). Set by claim_slot from the producer's target, and read by every
     * consumer from the command itself -- never from global state, because a
     * consumer runs behind the producer and real and in-between commands
     * interleave in one queue (3.1). */
    uint8_t efb;
    TevSetup tev;
    PixelCfg px;
    RasterCfg rc;
    unsigned ntex, nchan, prim, count;
    unsigned miptex;      /* texcoord slots whose map has mipmaps */
    uint8_t texmap_of[8]; /* the map a texcoord slot feeds (first stage using it) */
    const Vertex* v;
    /* copy: the registers as they were, and the command word */
    uint32_t cp_v, cp_tl, cp_wh, cp_dest, cp_stride, cp_ar, cp_gb, cp_z;
    /* The copy filter, already collapsed onto the three rows it reads, so a
     * worker never touches BP 0x53/0x54 itself: the producer keeps writing
     * those while workers run, and a worker reading them would apply whichever
     * copy's coefficients happened to have arrived last. This game programs one
     * set for the whole run, so that bug would be invisible in every capture we
     * have and would wait for the first stream that reprograms the filter. */
    uint8_t cp_f_up, cp_f_mid, cp_f_dn;
    /* H17b's screen ring: CP_LAST on the screen copy that ends its frame (the
     * in-between one when there is one), CP_MID when that frame has an
     * in-between image. 0 on every other command (claim_slot). */
    uint8_t cp_ring;
#define CP_LAST 1 /* the screen copy that ends its frame */
#define CP_MID 2  /* ...and its frame has an in-between image */
#define CP_CUT 4  /* ...which is a camera cut's, not to be shown */
    uint8_t* cp_image; /* a copy to memory's image, which each worker decodes its rows into; or NULL */
    CpuState* s;
    /* H17c (specs/interp-display.md): on a command with efb 1, the frame's
     * in-between weights, ascending in (0, 1), an image each (claim_slot);
     * none on a real command. A draw for a backend that draws slices carries
     * F's positions too -- x, y, z, w a vertex, as the pair tables keep them --
     * or NULL where it matched nothing, and its v is F+1's: the backend draws
     * it once per weight, lerping. Every other in-between draw's v is lerped
     * already, at the one weight. */
    uint8_t mid_n;
    float mid_t[GXR_MID_MAX];
    const float (*prev)[4];
} DrawCmd;

/* A backend draws the queue's commands instead of the worker pool (GPU spec
 * V2). Set before the first command is built; the pool is then never started
 * and every command runs on the producer, in order, through it. A 0 return is
 * a failure the backend has logged; the renderer says so and stops the run. */
typedef struct GxrBackend {
    const char* name;
    int (*draw)(const DrawCmd* D);  /* kind 0 */
    int (*copy)(const DrawCmd* D);  /* kind 1: to texture (guest RAM and its image) or to the screen; never clears */
    int (*clear)(const DrawCmd* D); /* kind 2: a copy's clear, always its own command when a backend is set */
    void (*reset_efb)(const uint32_t* bp); /* gxr_reset_efb's fill, on the backend's EFB; may be NULL */
    void (*finish)(void); /* every command so far has run and its RAM writes have landed; may be NULL */
    void (*report)(void); /* its own lines, printed after gxr_report's; may be NULL */
    /* 1: the backend is the ring's one consumer, on a thread of its own (V6a,
     * 3.7); finish is then never called, since a command it has counted is
     * done. 0: every command runs on the producer, as built (V2). */
    int own_thread;
    /* 1: a copy's bytes may reach guest RAM after the copy is counted (V7,
     * 3.6). The backend says when with gxr_backend_landed, and every wait for
     * what a copy wrote -- the hazards, a token, a drain -- waits for that as
     * well. own_thread only. */
    int lands_late;
    /* Called on the backend's own thread when it has nothing to run, before
     * it sleeps: where a backend that lands late lands what it holds, since a
     * producer waiting for a landing publishes nothing more. May be NULL. */
    void (*idle)(void);
    /* Draws a command with efb 1 into an EFB of its own (V12), so H17's
     * in-between stream can run on it; SOA_INTERP is refused with any other. */
    int two_efbs;
    /* H17c: how many in-between images a frame it draws, each in an EFB of
     * its own, from a draw's F+1 vertices and F's positions; 0 for a backend
     * that draws one, already lerped, as V12 did. */
    int slices;
} GxrBackend;

void gxr_set_backend(const GxrBackend* b); /* NULL: the worker pool */
void gxr_backend_screen(const uint8_t* rgba, int w, int h); /* a screen copy's pixels, exactly g_screen's size */
void gxr_backend_screen_mid(const uint8_t* rgba, int w, int h); /* an in-between screen copy's, into g_screen_mid (V12) */
/* H17c: in-between image k's (0 the first weight's), for its PNG; k 0 is g_screen_mid as well. */
void gxr_backend_screen_slice(int k, const uint8_t* rgba, int w, int h);
int gxr_interp(void); /* SOA_INTERP: a backend sizes its EFB for two at start (V12) */
/* H17c: the in-between images a frame may ask for (SOA_INTERP_WEIGHTS' count, else 1), for a backend's sizing. */
int gxr_interp_slices(void);
/* H17c: v's x, y, z, w moved to (1 - t) * prev + t * v, as the pair tables lerp them. */
void gxr_lerp_positions(Vertex* v, const float (*prev)[4], unsigned count, float t);
/* lands_late: every command below `through` has its guest RAM writes in
 * place. Raised only, by whichever thread runs the backend. */
void gxr_backend_landed(long long through);
/* The CPU renderer's own clipping and its command runner, for a consumer that
 * clips before upload (3.3) and for the passthrough backend. */
int gxr_vertex_unclipped(const Vertex* v);
unsigned gxr_clip_polygon(Vertex* in, unsigned n, Vertex* out);
/* Which EFB the commands built from now on are for (H17's g_target). The
 * producer's alone; exported for the backend test until H17a calls it. */
void gxr_set_target(int efb);

#endif
