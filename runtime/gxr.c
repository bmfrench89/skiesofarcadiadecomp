/*
 * Software GX: vertex decode, transform unit (matrices, lighting, texgen),
 * clipping, rasterization, depth/blend into the embedded framebuffer, and
 * EFB copies (to textures in memory, or to the "screen" as a PNG).
 *
 * Correctness first, speed later: every pixel runs the full TEV. The point
 * is a frame we can look at, produced from the exact command stream the
 * game emits, so every deviation from the real console is ours to find.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "gxr.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <direct.h>
#include <windows.h>
#else
#include <sys/stat.h>
#endif

uint64_t g_gxr_ticks[T_COUNT];
uint64_t g_gxr_phase_last;
int g_gxr_phase = T_HOST;
int g_gxr_tsc = -1;

static double qpc_hz(void)
{
#ifdef _WIN32
    static double freq;
    if (freq == 0.0) { LARGE_INTEGER f; QueryPerformanceFrequency(&f); freq = (double)f.QuadPart; }
    return freq;
#else
    return 0.0;
#endif
}

uint64_t gxr_qpc(void)
{
#ifdef _WIN32
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return (uint64_t)c.QuadPart;
#else
    return 0;
#endif
}

double gxr_clock(void)
{
    double hz = qpc_hz();
    return hz > 0.0 ? (double)gxr_qpc() / hz : 0.0;
}

/* Both clocks are read together at the first phase boundary and again at the
 * report, and the tick rate is the ratio of the two spans -- this run's own
 * rate over this run's own duration, rather than a nominal frequency that a
 * power state can make a lie. Four extra clock reads in a whole run. */
static uint64_t g_cal_tick0, g_cal_qpc0, g_cal_span;
static double g_ticks_hz, g_cal_seconds;

void gxr_timing_init(void)
{
    if (g_gxr_tsc >= 0) return;
#ifdef _WIN32
    {
        const char* env = getenv("SOA_TSC");
        int r[4], ok = 0;
        __cpuid(r, 0x80000000);
        if ((unsigned)r[0] >= 0x80000007u) {
            __cpuid(r, 0x80000007);
            ok = (r[3] >> 8) & 1; /* invariant TSC */
        }
        if (env && !atoi(env)) ok = 0; /* SOA_TSC=0: measure with QueryPerformanceCounter */
        g_gxr_tsc = ok;
    }
#else
    g_gxr_tsc = 0;
#endif
    g_cal_qpc0 = gxr_qpc();
    g_cal_tick0 = gxr_ticks();
    g_gxr_phase_last = g_cal_tick0;
}

void gxr_timing_finish(void)
{
    uint64_t qpc1, tick1;
    double hz = qpc_hz();
    if (g_ticks_hz > 0.0 || g_gxr_tsc < 0) return; /* already fixed, or nothing was ever timed */
    qpc1 = gxr_qpc();
    tick1 = gxr_ticks();
    g_cal_span = tick1 - g_cal_tick0;
    g_cal_seconds = hz > 0.0 ? (double)(qpc1 - g_cal_qpc0) / hz : 0.0;
    if (!g_gxr_tsc) g_ticks_hz = hz;
    else if (g_cal_seconds > 0.001 && g_cal_span) g_ticks_hz = (double)g_cal_span / g_cal_seconds;
}

double gxr_seconds(uint64_t ticks) { return g_ticks_hz > 0.0 ? (double)ticks / g_ticks_hz : 0.0; }

/* The span the buckets partition: the producer's wall time from the first
 * phase boundary to the report, which is not the process's -- nothing is
 * timed until the first draw. */
double gxr_producer_span(void) { return g_cal_seconds; }

uint8_t g_efb[EFB_H][EFB_W][4];
uint32_t g_efb_z[EFB_H][EFB_W];

static int g_enabled = -1;
static unsigned g_snap_every; /* SOA_SNAP=n; frames are numbered by gx_frame_count() so the PNG names agree with SOA_FRAMES and SOA_PAD */
static int g_draw_every;      /* a window is open: draw every frame, snapshots or not */
static char g_png_path[512];
static uint64_t g_tris, g_lines, g_points, g_clipped, g_verts_bad;
static uint64_t g_copies_tex, g_copies_xfb, g_rej_bary;

/* Rasterization is row-parallel: worker threads each take every Nth row of
 * every triangle in a draw, and the main thread is participant 0. Counters
 * touched per pixel are per thread. */
#define MAX_THREADS 16
static int g_nthreads = 1;
static __declspec(thread) int t_tid;
/* Indexed by t_tid, which is 1..MAX_THREADS for a worker and 0 for the thread
 * that produces, so there are MAX_THREADS + 1 of them: at SOA_THREADS=16 the
 * last worker used to write one element past these.
 *
 * A cache line each. The three counters are touched once per shaded pixel and
 * the two timers twice per queued command, so packed -- which is how the
 * counters used to sit, three arrays of eight-byte elements, all eight
 * workers inside two lines -- every increment is a line handed between cores.
 * Measured on this machine with eight threads: 4.8 ns an increment packed
 * against 0.8 ns a line apart, in a path that runs billions of times a run.
 * The padding is not tidiness, and the timers had to be padded anyway. */
typedef struct {
    uint64_t pixels, rej_depth, rej_alpha;
    uint64_t busy; /* ticks inside draw_command */
    uint64_t idle; /* ticks spinning for the next command */
    uint64_t last; /* when this thread's current stretch began */
    uint64_t pad[2];
} ThreadState;
static __declspec(align(64)) ThreadState g_ts[MAX_THREADS + 1];
/* The alignment above only puts the array on a line; what puts each element
 * on its own is the size, and a field added without shrinking the padding
 * would quietly undo the whole point of it. */
_Static_assert(sizeof(ThreadState) == 64, "one worker's counters must be one cache line");
static uint64_t g_pool_t0; /* when the worker pool came up: what busy + idle is measured against */
#define g_pixels g_ts[t_tid].pixels
#define g_rej_depth g_ts[t_tid].rej_depth
#define g_rej_alpha g_ts[t_tid].rej_alpha

/* Close this thread's open stretch and charge it. The clamp is the same one
 * gxr_phase makes: a thread that moved to a core whose counter is behind
 * reads backwards, and charging nothing beats charging a wrap. */
static void charge(ThreadState* W, uint64_t* acc)
{
    uint64_t n = gxr_ticks();
    if (n > W->last) *acc += n - W->last;
    W->last = n;
}
static int g_cull_flip, g_debug;
static int g_dbg_x = -1, g_dbg_y = -1; /* SOA_GXR_PIXEL=x,y: narrate every fragment landing on one pixel */
static int g_debug_lights;
static unsigned g_draw_limit, g_draw_no;
static int g_hash; /* SOA_HASH set to anything: hash every frame the port presents */

int gxr_enabled(void)
{
    if (g_enabled < 0) {
        const char* env = getenv("SOA_RENDER");
        const char* snap = getenv("SOA_SNAP");
        g_enabled = env && atoi(env) ? 1 : 0;
        g_snap_every = snap ? (unsigned)atoi(snap) : 0;
        g_cull_flip = getenv("SOA_CULLFLIP") ? 1 : 0;
        if (getenv("SOA_GXR_PIXEL")) sscanf(getenv("SOA_GXR_PIXEL"), "%d,%d", &g_dbg_x, &g_dbg_y);
        g_debug = getenv("SOA_GXR_DEBUG") ? atoi(getenv("SOA_GXR_DEBUG")) : 0;
        g_debug_lights = getenv("SOA_GXR_LIGHTS") ? atoi(getenv("SOA_GXR_LIGHTS")) : 0;
        g_draw_limit = getenv("SOA_GXR_DRAWS") ? (unsigned)atoi(getenv("SOA_GXR_DRAWS")) : 0;
        g_hash = getenv("SOA_HASH") ? 1 : 0;
    }
    return g_enabled;
}

/* ---- tripwires -----------------------------------------------------------
 *
 * This rasterizer does not implement everything the hardware does, and where
 * it falls short it draws something plausible and says nothing -- which makes
 * a missing feature look exactly like a bug in a feature we do have. Each
 * condition below speaks the first time the game asks for what we do not
 * model, naming the register and value it asked with and what we do instead.
 *
 * Once per condition, not once overall: every call site keeps its own flag,
 * so one going off leaves the rest armed. A line that repeats every frame is
 * a line nobody reads.
 *
 * Every tripwire here runs on the guest thread that parses the command stream
 * -- BP writes, draw setup and copies all do, and the rasterizer's workers
 * reach none of it -- so the flags need no lock.
 *
 * Decoding all 23 captures config/fifo_manifest.tsv pins and running these
 * conditions over their streams sets none of them off, and none is expected
 * to fire in normal play; a line here is news. The EFB copy's vertical filter
 * used to be the one thing the game really asked for that we really did not
 * do, and it was deliberately kept out of this channel rather than put in it:
 * the game programs it before the first frame of every run and leaves it
 * there, so a tripwire for it would have been in every log, and a channel
 * with a line in it every time stops meaning anything. gxr_report stated it
 * once at the end instead. PLAN C3 implemented the filter, so both the
 * counter and that line are gone; the reasoning is kept because the next
 * unmodelled-but-always-on feature will pose the same question.
 *
 * Two trigger shapes, and the difference matters when reading a replay: the
 * BP tripwires fire on a *write*, the draw and copy ones on the *state* a
 * draw or copy reads. gx_replay loads a capture's frame-start register
 * snapshot straight into the shadow without passing it through
 * gxr_bp_written, so a feature a capture merely inherited -- zfreeze, ZTEX2,
 * a non-RGB8 EFB -- is rendered wrong and says nothing. A silent corpus is
 * evidence that nothing was *asked for* in those windows, not that nothing
 * was in force. SOA_SNAP narrows the draw tripwires and not the BP ones for
 * the same reason the other way round: gxr_draw_inner returns before
 * draw_tripwire on a frame it is skipping, so a line, a point or a
 * destination-alpha blend on such a frame says nothing -- correctly, since
 * nothing was drawn and there is no picture to be wrong. What the game asked
 * for is still caught on every frame that is written.
 */
#define WARN_ONCE(...)                    \
    do {                                  \
        static int said;                  \
        if (!said) {                      \
            said = 1;                     \
            fprintf(stderr, __VA_ARGS__); \
        }                                 \
    } while (0)

/* BP_MASK (BP 0xFE) says the next BP write changes only the bits it names,
 * and we apply all 24 of them. That is only wrong when the write really
 * carries a bit outside the mask that differs from what the register already
 * holds -- and the SDK's one use of it, GXSetCoPlanar (mask 080000, then
 * GEN_MODE), writes the whole shadowed GEN_MODE back, so every bit outside
 * the mask is already what it says. The game does that from its first frame,
 * so warning on the mask write itself is a line in every log of a port that
 * renders correctly. Our own copy of the previous value is what tells the two
 * apart; g_bp_seen keeps a register whose first write is masked from being
 * compared against a zero we never saw written. */
static uint32_t g_bp_prev[256];
static uint8_t g_bp_seen[256];
static uint32_t g_bp_mask = 0xFFFFFFu;

/* The BP registers whose value alone says the game wants something we do not
 * have. Called for every BP write, after the shadow has taken it. */
static void bp_tripwire(const uint32_t* bp, uint32_t reg, uint32_t v)
{
    uint32_t mask = g_bp_mask, prev = g_bp_prev[reg & 0xFFu];
    int seen = g_bp_seen[reg & 0xFFu];
    g_bp_prev[reg & 0xFFu] = v;
    g_bp_seen[reg & 0xFFu] = 1;
    g_bp_mask = 0xFFFFFFu; /* the mask covers one write, then lapses */
    if (reg == 0xFE) {
        g_bp_mask = v & 0xFFFFFFu;
        return;
    }
    if (mask != 0xFFFFFFu && seen && ((v ^ prev) & ~mask & 0xFFFFFFu))
        WARN_ONCE("[gxr] BP_MASK %06X was in force for BP %02X %06X, which also changes %06X outside the mask; we apply all 24 bits, so those changed too and the register now differs from the hardware's by that much\n",
                  mask, reg, v, (v ^ prev) & ~mask & 0xFFFFFFu);
    switch (reg) {
    case 0x00: /* GEN_MODE */
        if ((v >> 16) & 7)
            WARN_ONCE("[gxr] GEN_MODE %06X asks for %u indirect texture stage(s); indirect textures are not modelled, so the stages are dropped and each direct coordinate is sampled unperturbed\n",
                      v, (v >> 16) & 7);
        if ((v >> 19) & 1)
            WARN_ONCE("[gxr] GEN_MODE %06X turns zfreeze on; the frozen depth plane is not modelled and depth stays per-triangle\n", v);
        break;
    case 0x43: /* PE_CONTROL */
        if (v & 7)
            WARN_ONCE("[gxr] PE_CONTROL %06X selects EFB pixel format %u; only RGB8 (0) is modelled, so the EFB keeps eight bits a channel whatever the game asked for\n",
                      v, v & 7);
        if ((v >> 3) & 7)
            WARN_ONCE("[gxr] PE_CONTROL %06X selects EFB depth format %u; only linear 24-bit Z (0) is modelled, so compressed depth is stored and compared linear\n",
                      v, (v >> 3) & 7);
        break;
    case 0x63: /* PRELOAD_MODE: writing it runs the preload, and the SDK writes zero to arm nothing */
        if (v)
            WARN_ONCE("[gxr] TMEM preload (BP 63 %06X from BP 60 %06X into BP 61 %06X / BP 62 %06X) is not modelled; every texture is decoded from main memory when a draw samples it, so one the game only preloads reads whatever is left at its address\n",
                      v, bp[0x60], bp[0x61], bp[0x62]);
        break;
    case 0xE8: /* FOGRANGE */
        if ((v >> 10) & 1)
            WARN_ONCE("[gxr] FOGRANGE (BP E8 %06X) enables fog range adjustment about x=%u; the adjustment is not modelled and fog uses eye depth alone, so the edges of the screen fog too little\n",
                      v, v & 0x3FF);
        break;
    case 0xF5: /* ZTEX2 */
        if ((v >> 2) & 3)
            WARN_ONCE("[gxr] ZTEX2 (BP F5 %06X) turns Z textures on (op %u, format %u); they are not modelled and a fragment's depth stays the interpolated one\n",
                      v, (v >> 2) & 3, v & 3);
        break;
    default: break;
    }
}

/* What a draw asks for that the pixel and primitive paths do not do. Called
 * once per draw, from the setup that reads the same registers. */
static void draw_tripwire(const uint32_t* bp, unsigned prim)
{
    uint32_t lp = bp[0x22], cmode = bp[0x41];
    /* GXSetLineWidth and GXSetPointSize count in sixths of a pixel, so 6 is
     * the one pixel raster_line and raster_point actually draw. The threshold
     * is two pixels, not "anything but exactly one": the game programs
     * linesize 7 -- 1.17 px -- in three of the captures, and drawing that one
     * pixel wide is a rounding, not a missing feature. Twice the width it
     * asked for is where the picture is visibly wrong. */
    if ((prim == 0xA8 || prim == 0xB0) && (lp & 0xFF) >= 12)
        WARN_ONCE("[gxr] LINEPTWIDTH (BP 22 %06X) asks for lines %.2f pixels wide; lines are drawn one pixel wide\n",
                  lp, (double)(lp & 0xFF) / 6.0);
    if (prim == 0xB8 && ((lp >> 8) & 0xFF) >= 12)
        WARN_ONCE("[gxr] LINEPTWIDTH (BP 22 %06X) asks for points %.2f pixels across; points are drawn as single pixels\n",
                  lp, (double)((lp >> 8) & 0xFF) / 6.0);
    /* GX_BL_DSTALPHA and its inverse read the EFB alpha plane, which RGB8
     * does not have: the console reads 1.0 there. We keep an alpha byte per
     * EFB pixel and blend against that, which is a different picture. */
    if ((cmode & 1) && (bp[0x43] & 7) == 0) {
        unsigned sfac = (cmode >> 8) & 7, dfac = (cmode >> 5) & 7;
        if (sfac >= 6 || dfac >= 6)
            WARN_ONCE("[gxr] PE_CMODE0 %06X blends with a destination-alpha factor (src %u, dst %u) at EFB format RGB8, where the console has no alpha plane and reads 1.0; we blend against the alpha we kept\n",
                      cmode, sfac, dfac);
    }
}

/* The EFB persists across frames on the console; a replay starts from the
 * state the previous frame's clear left: the clear color and z from the
 * captured registers. */
void gxr_reset_efb(void)
{
    gxr_flush();
    const uint32_t* bp = gx_bp_regs();
    uint32_t ar = bp[0x4F], gb = bp[0x50], z = bp[0x51] & 0xFFFFFFu;
    uint8_t col[4] = {(uint8_t)(ar & 0xFF), (uint8_t)((gb >> 8) & 0xFF), (uint8_t)(gb & 0xFF), (uint8_t)((ar >> 8) & 0xFF)};
    int x, y;
    for (y = 0; y < EFB_H; y++)
        for (x = 0; x < EFB_W; x++) { memcpy(g_efb[y][x], col, 4); g_efb_z[y][x] = z ? z : 0xFFFFFFu; }
}

void gxr_enable(int on)
{
    gxr_enabled();
    g_enabled = on;
}

void gxr_set_output(const char* png_path)
{
    snprintf(g_png_path, sizeof g_png_path, "%s", png_path);
}

/* SOA_SNAP skips the frames it is not writing, which is what makes a
 * snapshot run fast -- but the XFB copy still clears and presents every
 * frame, so with a window that skip shows the clear colour all but one frame
 * in N. main calls this when it opens a window anyway (SOA_WINDOW=1 with
 * SOA_SNAP set). */
void gxr_draw_every_frame(void)
{
    g_draw_every = 1;
}

static float xff(const uint32_t* xf, unsigned i)
{
    float f;
    uint32_t v = xf[i];
    memcpy(&f, &v, 4);
    return f;
}

static uint16_t be16(const uint8_t* p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }
static uint32_t be32(const uint8_t* p) { return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }

/* ---- vertex attributes ------------------------------------------------- */

typedef struct {
    float pos[3];
    float nrm[3];
    Color4 col[2];
    float tex[8][2];
    unsigned posidx, texidx[8];
    int has_nrm, has_col[2], has_tex[8];
} VertexIn;

static unsigned comp_bytes(unsigned fmt) { return fmt == 4 ? 4 : (fmt >= 2 ? 2 : 1); }

static float read_comp(const uint8_t* p, unsigned fmt, unsigned frac)
{
    float scale = 1.0f / (float)(1u << frac);
    switch (fmt) {
    case 0: return (float)p[0] * scale;
    case 1: return (float)(int8_t)p[0] * scale;
    case 2: return (float)be16(p) * scale;
    case 3: return (float)(int16_t)be16(p) * scale;
    default: { float f; uint32_t v = be32(p); memcpy(&f, &v, 4); return f; }
    }
}

static unsigned color_bytes(unsigned fmt)
{
    static const unsigned t[8] = {2, 3, 4, 2, 3, 4, 4, 4};
    return t[fmt & 7];
}

static void read_color(const uint8_t* p, unsigned fmt, Color4* c)
{
    unsigned v;
    switch (fmt) {
    case 0: /* RGB565 */
        v = be16(p);
        c->r = (float)((v >> 11) & 31) / 31.0f; c->g = (float)((v >> 5) & 63) / 63.0f; c->b = (float)(v & 31) / 31.0f; c->a = 1.0f;
        break;
    case 1: case 2: /* RGB888, RGBX8888 */
        c->r = p[0] / 255.0f; c->g = p[1] / 255.0f; c->b = p[2] / 255.0f; c->a = 1.0f;
        break;
    case 3: /* RGBA4444 */
        v = be16(p);
        c->r = (float)((v >> 12) & 15) / 15.0f; c->g = (float)((v >> 8) & 15) / 15.0f; c->b = (float)((v >> 4) & 15) / 15.0f; c->a = (float)(v & 15) / 15.0f;
        break;
    case 4: /* RGBA6666 */
        v = ((unsigned)p[0] << 16) | ((unsigned)p[1] << 8) | p[2];
        c->r = (float)((v >> 18) & 63) / 63.0f; c->g = (float)((v >> 12) & 63) / 63.0f; c->b = (float)((v >> 6) & 63) / 63.0f; c->a = (float)(v & 63) / 63.0f;
        break;
    default: /* RGBA8888 */
        c->r = p[0] / 255.0f; c->g = p[1] / 255.0f; c->b = p[2] / 255.0f; c->a = p[3] / 255.0f;
        break;
    }
}

/* Where an attribute's data lives: inline in the stream, or in the array
 * the index selects (CP ARRAY_BASE/ARRAY_STRIDE, GXSetArray). */
static const uint8_t* attr_data(CpuState* s, const uint32_t* cp, unsigned mode, const uint8_t** p, unsigned array, unsigned direct_size)
{
    const uint8_t* d;
    uint32_t idx, base, stride, addr;
    switch (mode) {
    case 0: return NULL;
    case 1: d = *p; *p += direct_size; return d;
    case 2: idx = **p; *p += 1; break;
    default: idx = be16(*p); *p += 2; break;
    }
    base = cp[0xA0 + array] & 0x1FFFFFFFu;
    stride = cp[0xB0 + array] & 0xFFu;
    addr = base + idx * stride;
    if ((addr & MEM_MASK) + direct_size > MEM1_SIZE) { g_verts_bad++; return NULL; }
    return mem_ptr(s, addr | 0x80000000u);
}

static const uint8_t* decode_vertex(CpuState* s, const uint8_t* p, unsigned vat, VertexIn* v)
{
    const uint32_t* cp = gx_cp_regs();
    const uint32_t* xf = gx_xf_regs();
    uint32_t lo = cp[0x50], hi = cp[0x60], a = cp[0x70 + vat], b = cp[0x80 + vat], c = cp[0x90 + vat];
    unsigned i;
    const uint8_t* d;
    unsigned tc[8][3] = {
        {(a >> 21) & 1, (a >> 22) & 7, (a >> 25) & 31}, {(b >> 0) & 1, (b >> 1) & 7, (b >> 4) & 31},
        {(b >> 9) & 1, (b >> 10) & 7, (b >> 13) & 31},  {(b >> 18) & 1, (b >> 19) & 7, (b >> 22) & 31},
        {(b >> 27) & 1, (b >> 28) & 7, (c >> 0) & 31},  {(c >> 5) & 1, (c >> 6) & 7, (c >> 9) & 31},
        {(c >> 14) & 1, (c >> 15) & 7, (c >> 18) & 31}, {(c >> 23) & 1, (c >> 24) & 7, (c >> 27) & 31},
    };

    memset(v, 0, sizeof *v);
    v->posidx = (lo & 1) ? *p++ : (xf[0x1018] & 0x3F);
    for (i = 0; i < 8; i++) {
        unsigned dflt = i < 4 ? (xf[0x1018] >> (6 + 6 * i)) & 0x3F : (xf[0x1019] >> (6 * (i - 4))) & 0x3F;
        v->texidx[i] = ((lo >> (1 + i)) & 1) ? *p++ : dflt;
    }
    /* position */
    {
        unsigned cnt = (a & 1) ? 3 : 2, fmt = (a >> 1) & 7, frac = (a >> 4) & 31, nb = comp_bytes(fmt);
        d = attr_data(s, cp, (lo >> 9) & 3, &p, 0, cnt * nb);
        if (d) for (i = 0; i < cnt; i++) v->pos[i] = read_comp(d + i * nb, fmt, fmt == 4 ? 0 : frac);
    }
    /* normal */
    {
        unsigned mode = (lo >> 11) & 3, elems = (a >> 9) & 1, fmt = (a >> 10) & 7, nb = comp_bytes(fmt);
        unsigned frac = fmt == 1 ? 6 : (fmt == 3 ? 14 : 0);
        if (mode >= 2 && elems && ((a >> 31) & 1)) {
            /* NBT with three indices: read the normal, skip the other two */
            d = attr_data(s, cp, mode, &p, 1, 3 * nb);
            if (d) for (i = 0; i < 3; i++) v->nrm[i] = read_comp(d + i * nb, fmt, frac);
            attr_data(s, cp, mode, &p, 1, 3 * nb);
            attr_data(s, cp, mode, &p, 1, 3 * nb);
            v->has_nrm = 1;
        } else if (mode) {
            d = attr_data(s, cp, mode, &p, 1, (elems ? 9 : 3) * nb);
            if (d) for (i = 0; i < 3; i++) v->nrm[i] = read_comp(d + i * nb, fmt, frac);
            v->has_nrm = 1;
        }
    }
    /* colors */
    for (i = 0; i < 2; i++) {
        unsigned mode = (lo >> (13 + 2 * i)) & 3, fmt = i == 0 ? (a >> 14) & 7 : (a >> 18) & 7;
        d = attr_data(s, cp, mode, &p, 2 + i, color_bytes(fmt));
        if (d) { read_color(d, fmt, &v->col[i]); v->has_col[i] = 1; }
    }
    /* texture coordinates */
    for (i = 0; i < 8; i++) {
        unsigned mode = (hi >> (2 * i)) & 3, cnt = tc[i][0] ? 2 : 1, fmt = tc[i][1], frac = tc[i][2], nb = comp_bytes(fmt);
        unsigned k;
        d = attr_data(s, cp, mode, &p, 4 + i, cnt * nb);
        if (d) {
            for (k = 0; k < cnt; k++) v->tex[i][k] = read_comp(d + k * nb, fmt, fmt == 4 ? 0 : frac);
            v->has_tex[i] = 1;
        }
    }
    return p;
}

/* ---- transform unit ----------------------------------------------------- */

static void mat_mul_3x4(const uint32_t* xf, unsigned row0, const float in[4], float out[3])
{
    unsigned r;
    for (r = 0; r < 3; r++)
        out[r] = xff(xf, row0 + 4 * r) * in[0] + xff(xf, row0 + 4 * r + 1) * in[1] +
                 xff(xf, row0 + 4 * r + 2) * in[2] + xff(xf, row0 + 4 * r + 3) * in[3];
}

static void normalize3(float v[3])
{
    float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (len > 1e-12f) { v[0] /= len; v[1] /= len; v[2] /= len; }
}

static float clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

/* GX lighting for one channel (color: chan, alpha: chan). Register layout
 * per GXSetChanCtrl; light data per GXInitLight*. */
static void light_channel(const uint32_t* xf, unsigned chan, int alpha, const VertexIn* in, const float pos[3], const float nrm[3], float out[4])
{
    uint32_t ctl = xf[(alpha ? 0x1010 : 0x100E) + chan];
    uint32_t amb_reg = xf[0x100A + chan], mat_reg = xf[0x100C + chan];
    int matsrc = ctl & 1, enable = (ctl >> 1) & 1, ambsrc = (ctl >> 6) & 1;
    unsigned diffuse = (ctl >> 7) & 3, attnfn = (ctl >> 9) & 3;
    unsigned mask = ((ctl >> 2) & 15) | (((ctl >> 11) & 15) << 4);
    float mat[4], amb[4], acc[4];
    unsigned li, k;
    const Color4* vc = &in->col[chan];

    mat[0] = matsrc ? vc->r : ((mat_reg >> 24) & 255) / 255.0f;
    mat[1] = matsrc ? vc->g : ((mat_reg >> 16) & 255) / 255.0f;
    mat[2] = matsrc ? vc->b : ((mat_reg >> 8) & 255) / 255.0f;
    mat[3] = matsrc ? vc->a : (mat_reg & 255) / 255.0f;
    if (matsrc && !in->has_col[chan]) { mat[0] = mat[1] = mat[2] = mat[3] = 1.0f; }
    if (!enable) { memcpy(out, mat, sizeof mat); return; }

    if (g_debug_lights > 0) {
        unsigned li2;
        g_debug_lights--;
        fprintf(stderr, "[gxr] chan%u %s ctl %08X mat %08X amb %08X mask %02X diffuse %u attn %u\n", chan, alpha ? "alpha" : "color", ctl, mat_reg, amb_reg, mask, diffuse, attnfn);
        for (li2 = 0; li2 < 8; li2++) {
            const uint32_t* L2 = xf + 0x600 + 16 * li2;
            if (!((mask >> li2) & 1)) continue;
            fprintf(stderr, "[gxr]   light %u color %08X att %g %g %g / %g %g %g pos %g %g %g dir %g %g %g\n", li2, L2[3],
                    xff(xf, 0x600 + 16 * li2 + 4), xff(xf, 0x600 + 16 * li2 + 5), xff(xf, 0x600 + 16 * li2 + 6),
                    xff(xf, 0x600 + 16 * li2 + 7), xff(xf, 0x600 + 16 * li2 + 8), xff(xf, 0x600 + 16 * li2 + 9),
                    xff(xf, 0x600 + 16 * li2 + 10), xff(xf, 0x600 + 16 * li2 + 11), xff(xf, 0x600 + 16 * li2 + 12),
                    xff(xf, 0x600 + 16 * li2 + 13), xff(xf, 0x600 + 16 * li2 + 14), xff(xf, 0x600 + 16 * li2 + 15));
        }
    }
    amb[0] = ambsrc ? vc->r : ((amb_reg >> 24) & 255) / 255.0f;
    amb[1] = ambsrc ? vc->g : ((amb_reg >> 16) & 255) / 255.0f;
    amb[2] = ambsrc ? vc->b : ((amb_reg >> 8) & 255) / 255.0f;
    amb[3] = ambsrc ? vc->a : (amb_reg & 255) / 255.0f;
    memcpy(acc, amb, sizeof acc);

    for (li = 0; li < 8; li++) {
        const uint32_t* L;
        uint32_t color;
        float lcol[4], lpos[3], ldir[3], dir[3], attn = 1.0f, diff = 1.0f;
        if (!((mask >> li) & 1)) continue;
        L = xf + 0x600 + 16 * li;
        color = L[3];
        lcol[0] = ((color >> 24) & 255) / 255.0f; lcol[1] = ((color >> 16) & 255) / 255.0f;
        lcol[2] = ((color >> 8) & 255) / 255.0f; lcol[3] = (color & 255) / 255.0f;
        lpos[0] = xff(xf, 0x600 + 16 * li + 10); lpos[1] = xff(xf, 0x600 + 16 * li + 11); lpos[2] = xff(xf, 0x600 + 16 * li + 12);
        dir[0] = xff(xf, 0x600 + 16 * li + 13); dir[1] = xff(xf, 0x600 + 16 * li + 14); dir[2] = xff(xf, 0x600 + 16 * li + 15);

        if (attnfn == 1) { /* specular: light "position" is a direction, half-angle in dir */
            float nl;
            ldir[0] = lpos[0]; ldir[1] = lpos[1]; ldir[2] = lpos[2];
            normalize3(ldir);
            nl = nrm[0] * ldir[0] + nrm[1] * ldir[1] + nrm[2] * ldir[2];
            if (nl >= 0.0f) {
                float hd[3] = {dir[0], dir[1], dir[2]}, nh, ca, da;
                normalize3(hd);
                nh = nrm[0] * hd[0] + nrm[1] * hd[1] + nrm[2] * hd[2];
                if (nh < 0.0f) nh = 0.0f;
                ca = xff(xf, 0x600 + 16 * li + 4) + xff(xf, 0x600 + 16 * li + 5) * nh + xff(xf, 0x600 + 16 * li + 6) * nh * nh;
                da = xff(xf, 0x600 + 16 * li + 7) + xff(xf, 0x600 + 16 * li + 8) * nh + xff(xf, 0x600 + 16 * li + 9) * nh * nh;
                attn = (da != 0.0f) ? (ca < 0.0f ? 0.0f : ca) / da : 0.0f;
            } else attn = 0.0f;
        } else {
            ldir[0] = lpos[0] - pos[0]; ldir[1] = lpos[1] - pos[1]; ldir[2] = lpos[2] - pos[2];
            if (attnfn == 3) { /* spot */
                float dist2 = ldir[0] * ldir[0] + ldir[1] * ldir[1] + ldir[2] * ldir[2];
                float dist = sqrtf(dist2), cosv, ca, da;
                if (dist > 1e-12f) { ldir[0] /= dist; ldir[1] /= dist; ldir[2] /= dist; }
                cosv = ldir[0] * dir[0] + ldir[1] * dir[1] + ldir[2] * dir[2];
                if (cosv < 0.0f) cosv = 0.0f;
                ca = xff(xf, 0x600 + 16 * li + 4) + xff(xf, 0x600 + 16 * li + 5) * cosv + xff(xf, 0x600 + 16 * li + 6) * cosv * cosv;
                da = xff(xf, 0x600 + 16 * li + 7) + xff(xf, 0x600 + 16 * li + 8) * dist + xff(xf, 0x600 + 16 * li + 9) * dist2;
                attn = (da != 0.0f) ? (ca < 0.0f ? 0.0f : ca) / da : 0.0f;
            } else {
                normalize3(ldir);
            }
        }
        if (diffuse != 0) {
            diff = nrm[0] * ldir[0] + nrm[1] * ldir[1] + nrm[2] * ldir[2];
            if (diffuse == 2 && diff < 0.0f) diff = 0.0f;
        }
        for (k = 0; k < 4; k++) acc[k] += lcol[k] * attn * diff;
    }
    for (k = 0; k < 4; k++) out[k] = mat[k] * clamp01(acc[k]);
}

static void transform(CpuState* s, const VertexIn* in, Vertex* out)
{
    const uint32_t* xf = gx_xf_regs();
    float pos4[4] = {in->pos[0], in->pos[1], in->pos[2], 1.0f};
    float view[3], nrm[3] = {0, 0, 1};
    unsigned i;
    (void)s;

    mat_mul_3x4(xf, 4 * (in->posidx & 0x3F), pos4, view);
    if (in->has_nrm) {
        unsigned nb = 0x400 + 3 * (in->posidx & 0x3F);
        unsigned r;
        for (r = 0; r < 3; r++)
            nrm[r] = xff(xf, nb + 3 * r) * in->nrm[0] + xff(xf, nb + 3 * r + 1) * in->nrm[1] + xff(xf, nb + 3 * r + 2) * in->nrm[2];
        normalize3(nrm);
    }

    /* projection (XF 0x1020-0x1026, GXSetProjection) */
    {
        float p0 = xff(xf, 0x1020), p1 = xff(xf, 0x1021), p2 = xff(xf, 0x1022), p3 = xff(xf, 0x1023), p4 = xff(xf, 0x1024), p5 = xff(xf, 0x1025);
        if (xf[0x1026] & 1) { /* orthographic */
            out->x = p0 * view[0] + p1;
            out->y = p2 * view[1] + p3;
            out->z = p4 * view[2] + p5;
            out->w = 1.0f;
        } else {
            out->x = p0 * view[0] + p1 * view[2];
            out->y = p2 * view[1] + p3 * view[2];
            out->z = p4 * view[2] + p5;
            out->w = -view[2];
        }
    }

    /* color channels (XF 0x1009 numColorChans, 0x100E.. controls) */
    for (i = 0; i < 2; i++) {
        float c[4], a[4];
        light_channel(xf, i, 0, in, view, nrm, c);
        light_channel(xf, i, 1, in, view, nrm, a);
        out->col[i].r = c[0]; out->col[i].g = c[1]; out->col[i].b = c[2]; out->col[i].a = a[3];
    }

    /* texture coordinate generation (XF 0x103F count, 0x1040+ GXSetTexCoordGen) */
    {
        unsigned n = xf[0x103F] & 15;
        for (i = 0; i < 8; i++) {
            uint32_t info = xf[0x1040 + i];
            unsigned proj = (info >> 1) & 1, form = (info >> 2) & 1, type = (info >> 4) & 7, src = (info >> 7) & 31;
            float in4[4] = {0, 0, 1, 1}, o[3] = {0, 0, 1};
            if (i >= n) { out->tex[i][0] = out->tex[i][1] = 0; out->tex[i][2] = 1; continue; }
            if (src == 0) { in4[0] = in->pos[0]; in4[1] = in->pos[1]; in4[2] = form ? in->pos[2] : 1.0f; }
            else if (src == 1) { in4[0] = in->nrm[0]; in4[1] = in->nrm[1]; in4[2] = form ? in->nrm[2] : 1.0f; }
            else if (src >= 5 && src < 13) { in4[0] = in->tex[src - 5][0]; in4[1] = in->tex[src - 5][1]; in4[2] = 1.0f; }
            if (type == 2 || type == 3) {
                const Color4* cc = &out->col[type - 2];
                o[0] = cc->r; o[1] = cc->g; o[2] = 1.0f;
            } else if (type == 0) {
                unsigned row0 = 4 * (in->texidx[i] & 0x3F);
                if (proj) mat_mul_3x4(xf, row0, in4, o);
                else {
                    float t[3];
                    mat_mul_3x4(xf, row0, in4, t);
                    o[0] = t[0]; o[1] = t[1]; o[2] = 1.0f;
                }
            } else { /* emboss: pass the source through */
                o[0] = in4[0]; o[1] = in4[1]; o[2] = 1.0f;
            }
            if (xf[0x1012] & 1) { /* dual transform (GXSetTexCoordGen2 post matrix) */
                uint32_t post = xf[0x1050 + i];
                unsigned pidx = post & 0x3F;
                float t4[4] = {o[0], o[1], o[2], 1.0f}, r[3];
                if ((post >> 8) & 1) { float v3[3] = {o[0], o[1], o[2]}; normalize3(v3); t4[0] = v3[0]; t4[1] = v3[1]; t4[2] = v3[2]; }
                mat_mul_3x4(xf, 0x500 + 4 * pidx, t4, r);
                o[0] = r[0]; o[1] = r[1]; o[2] = r[2];
            }
            out->tex[i][0] = o[0]; out->tex[i][1] = o[1]; out->tex[i][2] = proj ? o[2] : 1.0f;
        }
    }
}

/* ---- draw commands ------------------------------------------------------
 * A draw is parsed, transformed and queued by the main thread; worker
 * threads rasterize queued draws in order, each taking every Nth row, so
 * per-pixel ordering is preserved and the game keeps running meanwhile.
 * EFB copies and clears wait for the queue to drain (gxr_flush). */

#define QUEUE_CAP 4096
#define QMASK (QUEUE_CAP - 1) /* commands are numbered, not indexed, so the capacity is a power of two */
#define ARENA_BYTES (48u << 20)

typedef struct { int x0, y0, x1, y1; } Rect;

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
} PixelCfg;

/* The 20-bit floats in the fog registers: sign, 8-bit exponent, 11-bit mantissa. */
static float fog_float(uint32_t v)
{
    uint32_t bits = ((v >> 19) & 1) << 31 | ((v >> 11) & 0xFF) << 23 | (v & 0x7FF) << 12;
    float f;
    memcpy(&f, &bits, 4);
    return f;
}

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
    int kind; /* 0 draw, 1 EFB copy, 2 the EFB clear that followed one */
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
    CpuState* s;
} DrawCmd;

static void scissor_rect(const uint32_t* bp, Rect* r)
{
    uint32_t tl = bp[0x20], br = bp[0x21], off = bp[0x59];
    int xoff = (int)((off & 0x3FF) * 2), yoff = (int)(((off >> 10) & 0x3FF) * 2);
    r->x0 = (int)((tl >> 12) & 0x7FF) - xoff;
    r->y0 = (int)(tl & 0x7FF) - yoff;
    r->x1 = (int)((br >> 12) & 0x7FF) - xoff;
    r->y1 = (int)(br & 0x7FF) - yoff;
    if (r->x0 < 0) r->x0 = 0;
    if (r->y0 < 0) r->y0 = 0;
    if (r->x1 > EFB_W - 1) r->x1 = EFB_W - 1;
    if (r->y1 > EFB_H - 1) r->y1 = EFB_H - 1;
}

static void raster_prepare(const uint32_t* xf, const uint32_t* bp, RasterCfg* rc)
{
    uint32_t off = bp[0x59];
    scissor_rect(bp, &rc->scissor);
    rc->cull = (bp[0] >> 14) & 3;
    rc->wd = xff(xf, 0x101A); rc->ht = xff(xf, 0x101B); rc->zrange = xff(xf, 0x101C);
    rc->xorig = xff(xf, 0x101D) - (float)((off & 0x3FF) * 2);
    rc->yorig = xff(xf, 0x101E) - (float)(((off >> 10) & 0x3FF) * 2);
    rc->farz = xff(xf, 0x101F);
}

static void pixel_prepare(const uint32_t* bp, PixelCfg* px)
{
    uint32_t cmode = bp[0x41], cmode1 = bp[0x42], zmode = bp[0x40];
    px->blend_en = cmode & 1; px->logic_en = (cmode >> 1) & 1;
    px->col_upd = (cmode >> 3) & 1; px->alpha_upd = (cmode >> 4) & 1;
    px->dfac = (cmode >> 5) & 7; px->sfac = (cmode >> 8) & 7;
    px->subtract = (cmode >> 11) & 1; px->lop = (cmode >> 12) & 15;
    px->const_alpha = (cmode1 & 0x100) ? (int)(cmode1 & 0xFF) : -1;
    px->z_en = zmode & 1; px->z_func = (zmode >> 1) & 7; px->z_upd = (zmode >> 4) & 1;
    px->ztop = (bp[0x43] >> 6) & 1;
    px->fog_type = (bp[0xF1] >> 21) & 7;
    px->fog_proj = (bp[0xF1] >> 20) & 1;
    px->fog_a = fog_float(bp[0xEE]);
    px->fog_c = fog_float(bp[0xF1]);
    px->fog_b_mag = bp[0xEF] & 0xFFFFFFu;
    px->fog_b_shift = bp[0xF0] & 0x1F;
    px->fog_color[0] = (uint8_t)((bp[0xF2] >> 16) & 0xFF);
    px->fog_color[1] = (uint8_t)((bp[0xF2] >> 8) & 0xFF);
    px->fog_color[2] = (uint8_t)(bp[0xF2] & 0xFF);
}

/* Fog blends the TEV output toward the fog colour by a function of eye
 * distance recovered from the 24-bit screen z, as the pixel engine does. */
static inline void fog_apply(const PixelCfg* px, uint8_t out[4], float depth)
{
    float ze, f;
    int fi, i;
    uint32_t zs = (uint32_t)(depth < 0.0f ? 0.0f : (depth > 1.0f ? 16777215.0f : depth * 16777215.0f));
    if (px->fog_type == 0) return;
    if (!px->fog_proj) {
        int32_t denom = (int32_t)px->fog_b_mag - (int32_t)(zs >> px->fog_b_shift);
        if (denom == 0) return;
        ze = (px->fog_a * 16777215.0f) / (float)denom;
    } else {
        ze = px->fog_a * ((float)zs / 16777215.0f);
    }
    f = ze - px->fog_c;
    if (f < 0.0f) f = 0.0f;
    if (f > 1.0f) f = 1.0f;
    switch (px->fog_type) {
    case 2: break;                                     /* linear */
    case 4: f = 1.0f - exp2f(-8.0f * f); break;        /* exp */
    case 5: f = 1.0f - exp2f(-8.0f * f * f); break;    /* exp2 */
    case 6: f = exp2f(-8.0f * (1.0f - f)); break;      /* backward exp */
    case 7: f = exp2f(-8.0f * (1.0f - f) * (1.0f - f)); break;
    default: return;
    }
    fi = (int)(f * 256.0f);
    if (fi > 256) fi = 256;
    for (i = 0; i < 3; i++) out[i] = (uint8_t)((out[i] * (256 - fi) + px->fog_color[i] * fi) >> 8);
}

static void to_screen(const RasterCfg* rc, Vertex* v)
{
    float iw = v->w != 0.0f ? 1.0f / v->w : 0.0f;
    v->sx = rc->xorig + v->x * iw * rc->wd;
    v->sy = rc->yorig + v->y * iw * rc->ht;
    v->depth = (rc->farz + v->z * iw * rc->zrange) / 16777216.0f;
}

/* ---- pixels --------------------------------------------------------------- */

static inline void blend_pixel(const PixelCfg* px, int x, int y, const uint8_t src[4])
{
    uint8_t* dst = g_efb[y][x];
    int out[4], i;
    int sa = px->const_alpha >= 0 ? px->const_alpha : src[3], da = dst[3];

    if (px->blend_en) {
        int sf, df;
        switch (px->sfac) {
        case 0: sf = 0; break; case 1: sf = 255; break; case 2: sf = -1; break; case 3: sf = -2; break;
        case 4: sf = src[3]; break; case 5: sf = 255 - src[3]; break; case 6: sf = da; break; default: sf = 255 - da; break;
        }
        switch (px->dfac) {
        case 0: df = 0; break; case 1: df = 255; break; case 2: df = -1; break; case 3: df = -2; break;
        case 4: df = src[3]; break; case 5: df = 255 - src[3]; break; case 6: df = da; break; default: df = 255 - da; break;
        }
        for (i = 0; i < 3; i++) {
            int s_f = sf == -1 ? dst[i] : (sf == -2 ? 255 - dst[i] : sf);
            int d_f = df == -1 ? src[i] : (df == -2 ? 255 - src[i] : df);
            int r = px->subtract ? dst[i] - src[i] : (src[i] * s_f + dst[i] * d_f + 127) / 255;
            out[i] = r < 0 ? 0 : (r > 255 ? 255 : r);
        }
    } else if (px->logic_en) {
        for (i = 0; i < 3; i++) {
            int sv = src[i], dv = dst[i], r;
            switch (px->lop) {
            case 0: r = 0; break; case 1: r = sv & dv; break; case 2: r = sv & ~dv; break; case 3: r = sv; break;
            case 4: r = ~sv & dv; break; case 5: r = dv; break; case 6: r = sv ^ dv; break; case 7: r = sv | dv; break;
            case 8: r = ~(sv | dv); break; case 9: r = ~(sv ^ dv); break; case 10: r = ~dv; break; case 11: r = sv | ~dv; break;
            case 12: r = ~sv; break; case 13: r = ~sv | dv; break; case 14: r = ~(sv & dv); break; default: r = 255; break;
            }
            out[i] = r & 255;
        }
    } else {
        out[0] = src[0]; out[1] = src[1]; out[2] = src[2];
    }
    if (px->col_upd) { dst[0] = (uint8_t)out[0]; dst[1] = (uint8_t)out[1]; dst[2] = (uint8_t)out[2]; }
    if (px->alpha_upd) dst[3] = (uint8_t)sa;
}

static inline int depth_test(const PixelCfg* px, int x, int y, float depth)
{
    uint32_t z = (uint32_t)(depth < 0.0f ? 0.0f : (depth > 1.0f ? 16777215.0f : depth * 16777215.0f));
    uint32_t cur = g_efb_z[y][x];
    int pass;
    if (!px->z_en) return 1;
    switch (px->z_func) {
    case 0: pass = 0; break; case 1: pass = z < cur; break; case 2: pass = z == cur; break; case 3: pass = z <= cur; break;
    case 4: pass = z > cur; break; case 5: pass = z != cur; break; case 6: pass = z >= cur; break; default: pass = 1; break;
    }
    if (pass && px->z_upd) g_efb_z[y][x] = z;
    return pass;
}

static inline void shade(const DrawCmd* D, int x, int y, const int col[2][4], const float tex[8][4], float depth)
{
    uint8_t out[4];
    int alpha_ok = 1;
    if (x == g_dbg_x && y == g_dbg_y) {
        uint8_t o[4]; int ok = 1;
        extern int g_tev_narrate;
        g_tev_narrate = 1;
        tev_pixel(&D->tev, col, tex, o, &ok);
        g_tev_narrate = 0;
        fprintf(stderr, "[gxr] pixel %d,%d: col0 %d,%d,%d,%d tex0 %.3f,%.3f lod %.2f depth %.6f z-buf %.6f -> tev %d,%d,%d,%d alpha_ok %d blend %d z_en %d z_func %u\n",
                x, y, col[0][0], col[0][1], col[0][2], col[0][3], tex[0][0], tex[0][1], tex[0][3], depth,
                (float)g_efb_z[y][x] / 16777215.0f, o[0], o[1], o[2], o[3], ok, D->px.blend_en, D->px.z_en, D->px.z_func);
    }
    /* Z before texturing (PE_CONTROL ztop) or after: order matters only for
     * alpha-tested pixels; test late unless ztop is set. */
    if (D->px.ztop && !depth_test(&D->px, x, y, depth)) { g_rej_depth++; return; }
    tev_pixel(&D->tev, col, tex, out, &alpha_ok);
    if (!alpha_ok) { g_rej_alpha++; return; }
    if (!D->px.ztop && !depth_test(&D->px, x, y, depth)) { g_rej_depth++; return; }
    fog_apply(&D->px, out, depth);
    blend_pixel(&D->px, x, y, out);
    g_pixels++;
}

/* Plane equation of a value linear in screen space: v = a*x + b*y + c. */
typedef struct { float a, b, c; } Plane;

static Plane plane_of(const Vertex* v0, const Vertex* v1, const Vertex* v2, float p0, float p1, float p2, float inv_area)
{
    Plane P;
    float dx1 = v1->sx - v0->sx, dy1 = v1->sy - v0->sy, dx2 = v2->sx - v0->sx, dy2 = v2->sy - v0->sy;
    float dp1 = p1 - p0, dp2 = p2 - p0;
    P.a = (dp1 * dy2 - dp2 * dy1) * inv_area;
    P.b = (dp2 * dx1 - dp1 * dx2) * inv_area;
    P.c = p0 - P.a * v0->sx - P.b * v0->sy;
    return P;
}

#define MAX_ATTR (2 + 8 + 8 * 3) /* depth, 1/w, two colours, eight texcoords */

/* log2 of the texel footprint of one pixel for a texcoord slot, from the
 * screen-space derivatives of s = (S/w)/(1/w) and t. */
static float span_lod(const Plane* attr, int wi, int ti, float px, float py, float scale_s, float scale_t)
{
    float W = attr[wi].a * px + attr[wi].b * py + attr[wi].c;
    float S = attr[ti].a * px + attr[ti].b * py + attr[ti].c;
    float T = attr[ti + 1].a * px + attr[ti + 1].b * py + attr[ti + 1].c;
    float Q = attr[ti + 2].a * px + attr[ti + 2].b * py + attr[ti + 2].c;
    float iw2, dsdx, dsdy, dtdx, dtdy, q, fx, fy, f;
    if (W == 0.0f) return 0.0f;
    iw2 = 1.0f / (W * W);
    q = Q / W;
    if (q == 0.0f) q = 1.0f;
    /* d(S/W)/dx = (S_a W - S W_a) / W^2, likewise for y and for T; divide by q */
    dsdx = (attr[ti].a * W - S * attr[wi].a) * iw2 / q * scale_s;
    dsdy = (attr[ti].b * W - S * attr[wi].b) * iw2 / q * scale_s;
    dtdx = (attr[ti + 1].a * W - T * attr[wi].a) * iw2 / q * scale_t;
    dtdy = (attr[ti + 1].b * W - T * attr[wi].b) * iw2 / q * scale_t;
    fx = dsdx * dsdx + dtdx * dtdx;
    fy = dsdy * dsdy + dtdy * dtdy;
    f = fx > fy ? fx : fy;
    if (f <= 1e-12f) return -16.0f;
    return 0.5f * log2f(f);
}

static void raster_triangle(const DrawCmd* D, const Vertex* a, const Vertex* b, const Vertex* c)
{
    const Rect* sc = &D->rc.scissor;
    float area = (b->sx - a->sx) * (c->sy - a->sy) - (c->sx - a->sx) * (b->sy - a->sy);
    unsigned cull = D->rc.cull;
    int minx, miny, maxx, maxy, x, y;
    float inv_area;
    Plane e0, e1, e2;                 /* barycentric weights, positive inside */
    Plane attr[MAX_ATTR];             /* perspective-corrected attributes (value/w) */
    int nattr = 0, ci[2], ti[8], di, wi;
    unsigned i, k;
    const Vertex* v[3];
    float lod[8] = {0, 0, 0, 0, 0, 0, 0, 0}, dlod[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    /* One slot per texcoord: s, t, q and the level of detail. A TEV stage may
     * name any of the eight whether this draw supplies it or not, and what it
     * reads then is defined -- the console keeps eight coordinates and only
     * refreshes the ones the XF generates. This renderer's transform unit
     * writes (0, 0, 1) into every ungenerated slot, so hold the unsupplied
     * ones at that value here as well: a stage naming one samples texel (0, 0)
     * of its map, the same result the line and point paths already give,
     * rather than whatever the stack held, which made the frame depend on how
     * many worker threads were rasterizing. */
    float tex[8][4];

    if (area == 0.0f) return;
    if (g_cull_flip) area = -area;
    if ((cull == 1 && area < 0.0f) || (cull == 2 && area > 0.0f) || cull == 3) return; /* back = negative here */
    if (g_cull_flip) area = -area;

    if (g_debug && t_tid <= 1 && (g_tris <= 8 || (g_debug > 1 && g_draw_no >= (unsigned)g_debug))) /* SOA_GXR_DEBUG=N: also every triangle from draw N on */
        fprintf(stderr, "[gxr] tri (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) (%.1f,%.1f,%.3f) area %.1f scissor %d,%d-%d,%d\n",
                a->sx, a->sy, a->depth, b->sx, b->sy, b->depth, c->sx, c->sy, c->depth, area, sc->x0, sc->y0, sc->x1, sc->y1);
    /* Clamp in float first: a vertex just past the near plane can sit millions of
     * pixels off screen, and a huge value converted to int becomes INT_MIN. */
    minx = (int)fmaxf(-1e6f, floorf(fminf(a->sx, fminf(b->sx, c->sx))));
    maxx = (int)fminf(1e6f, ceilf(fmaxf(a->sx, fmaxf(b->sx, c->sx))));
    miny = (int)fmaxf(-1e6f, floorf(fminf(a->sy, fminf(b->sy, c->sy))));
    maxy = (int)fminf(1e6f, ceilf(fmaxf(a->sy, fmaxf(b->sy, c->sy))));
    if (minx < sc->x0) minx = sc->x0;
    if (miny < sc->y0) miny = sc->y0;
    if (maxx > sc->x1) maxx = sc->x1;
    if (maxy > sc->y1) maxy = sc->y1;
    if (minx > maxx || miny > maxy) return;

    /* Orient so the weights are positive inside. */
    v[0] = a; v[1] = b; v[2] = c;
    if (area < 0.0f) { v[1] = c; v[2] = b; area = -area; }
    inv_area = 1.0f / area;
    e0 = plane_of(v[0], v[1], v[2], 1.0f, 0.0f, 0.0f, inv_area);
    e1 = plane_of(v[0], v[1], v[2], 0.0f, 1.0f, 0.0f, inv_area);
    e2 = plane_of(v[0], v[1], v[2], 0.0f, 0.0f, 1.0f, inv_area);

    {
        float iw0 = v[0]->w != 0.0f ? 1.0f / v[0]->w : 1.0f;
        float iw1 = v[1]->w != 0.0f ? 1.0f / v[1]->w : 1.0f;
        float iw2 = v[2]->w != 0.0f ? 1.0f / v[2]->w : 1.0f;
        di = nattr; attr[nattr++] = plane_of(v[0], v[1], v[2], v[0]->depth, v[1]->depth, v[2]->depth, inv_area);
        wi = nattr; attr[nattr++] = plane_of(v[0], v[1], v[2], iw0, iw1, iw2, inv_area);
        for (i = 0; i < 2; i++) {
            const float* c0 = &v[0]->col[i].r; const float* c1 = &v[1]->col[i].r; const float* c2 = &v[2]->col[i].r;
            ci[i] = nattr;
            if (!((D->nchan >> i) & 1)) continue;
            for (k = 0; k < 4; k++)
                attr[nattr++] = plane_of(v[0], v[1], v[2], c0[k] * iw0, c1[k] * iw1, c2[k] * iw2, inv_area);
        }
        for (i = 0; i < 8; i++) {
            tex[i][0] = 0.0f; tex[i][1] = 0.0f; tex[i][2] = 1.0f; tex[i][3] = 0.0f;
            ti[i] = -1;
            if (!((D->ntex >> i) & 1)) continue;
            ti[i] = nattr;
            for (k = 0; k < 3; k++)
                attr[nattr++] = plane_of(v[0], v[1], v[2], v[0]->tex[i][k] * iw0, v[1]->tex[i][k] * iw1, v[2]->tex[i][k] * iw2, inv_area);
        }
    }

    for (y = miny; y <= maxy; y++) {
        float py = (float)y + 0.5f;
        float av[MAX_ATTR];
        float px0;
        int n, xs = minx, xe = maxx;
        if (g_nthreads > 1 && (unsigned)y % (unsigned)g_nthreads != (unsigned)(t_tid - 1)) continue;
        /* The row's span: each weight w = a*x + b*y + c must be >= 0. */
        {
            const Plane* e[3] = {&e0, &e1, &e2};
            int j;
            for (j = 0; j < 3; j++) {
                float base = e[j]->b * py + e[j]->c; /* w at x = 0 */
                /* Compare in float before converting: a nearly horizontal edge has an x
                 * coefficient that is a rounding crumb, and -base/a runs to billions,
                 * which an int conversion turns into INT_MIN and an empty row. */
                if (e[j]->a > 0.0f) { float lim = ceilf(-base / e[j]->a - 0.5f); if (lim > (float)xs) xs = lim > 1e8f ? xe + 1 : (int)lim; }
                else if (e[j]->a < 0.0f) { float lim = floorf(-base / e[j]->a - 0.5f); if (lim < (float)xe) xe = lim < -1e8f ? xs - 1 : (int)lim; }
                else if (base < 0.0f) { xs = xe + 1; break; }
            }
        }
        if (g_dbg_x >= 0 && y == g_dbg_y)
            fprintf(stderr, "[gxr] row %d of tri (%.1f,%.1f)(%.1f,%.1f)(%.1f,%.1f): span %d..%d; e0 %g,%g,%g e1 %g,%g,%g e2 %g,%g,%g box %d..%d\n",
                    y, v[0]->sx, v[0]->sy, v[1]->sx, v[1]->sy, v[2]->sx, v[2]->sy, xs, xe, e0.a, e0.b, e0.c, e1.a, e1.b, e1.c, e2.a, e2.b, e2.c, minx, maxx);
        if (xs > xe) continue;
        px0 = (float)xs + 0.5f;
        for (n = 0; n < nattr; n++) av[n] = attr[n].a * px0 + attr[n].b * py + attr[n].c;
        /* Level of detail per texcoord slot: log2 of the texel footprint of
         * one pixel, evaluated at both ends of the span and interpolated. */
        for (i = 0; i < 8; i++) {
            float l0, l1;
            if (ti[i] < 0 || !((D->miptex >> i) & 1)) continue;
            l0 = span_lod(attr, wi, ti[i], px0, py, D->tev.tex[D->texmap_of[i]].scale_s, D->tev.tex[D->texmap_of[i]].scale_t);
            l1 = span_lod(attr, wi, ti[i], (float)xe + 0.5f, py, D->tev.tex[D->texmap_of[i]].scale_s, D->tev.tex[D->texmap_of[i]].scale_t);
            lod[i] = l0;
            dlod[i] = xe > xs ? (l1 - l0) / (float)(xe - xs) : 0.0f;
        }
        for (x = xs; x <= xe; x++) {
            float w = av[wi] != 0.0f ? 1.0f / av[wi] : 0.0f;
            float w255 = w * 255.0f;
            int col[2][4];
            for (i = 0; i < 2; i++) {
                if (!((D->nchan >> i) & 1)) { col[i][0] = col[i][1] = col[i][2] = col[i][3] = 0; continue; }
                for (k = 0; k < 4; k++) {
                    int cv = (int)(av[ci[i] + k] * w255 + 0.5f);
                    col[i][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv);
                }
            }
            for (i = 0; i < 8; i++) {
                if (ti[i] < 0) continue;
                tex[i][0] = av[ti[i]] * w; tex[i][1] = av[ti[i] + 1] * w; tex[i][2] = av[ti[i] + 2] * w;
                tex[i][3] = lod[i];
                lod[i] += dlod[i];
            }
            shade(D, x, y, col, tex, av[di]);
            for (n = 0; n < nattr; n++) av[n] += attr[n].a;
        }
    }
}

static void raster_line(const DrawCmd* D, const Vertex* a, const Vertex* b)
{
    const Rect* sc = &D->rc.scissor;
    float dx = b->sx - a->sx, dy = b->sy - a->sy;
    float len = fmaxf(fabsf(dx), fabsf(dy));
    int n = (int)ceilf(len), i;
    unsigned t, k;
    g_lines++;
    if (n < 1) n = 1;
    for (i = 0; i <= n; i++) {
        float f = (float)i / (float)n;
        int x = (int)floorf(a->sx + dx * f), y = (int)floorf(a->sy + dy * f);
        int col[2][4];
        float tex[8][4];
        if (x < sc->x0 || x > sc->x1 || y < sc->y0 || y > sc->y1) continue;
        for (t = 0; t < 2; t++) {
            const float* ca = &a->col[t].r; const float* cb = &b->col[t].r;
            for (k = 0; k < 4; k++) {
                int cv = (int)((ca[k] + (cb[k] - ca[k]) * f) * 255.0f + 0.5f);
                col[t][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv);
            }
        }
        for (t = 0; t < 8; t++) {
            for (k = 0; k < 3; k++) tex[t][k] = a->tex[t][k] + (b->tex[t][k] - a->tex[t][k]) * f;
            tex[t][3] = 0.0f;
        }
        shade(D, x, y, col, tex, a->depth + (b->depth - a->depth) * f);
    }
}

static void raster_point(const DrawCmd* D, const Vertex* a)
{
    const Rect* sc = &D->rc.scissor;
    int x = (int)floorf(a->sx), y = (int)floorf(a->sy);
    int col[2][4];
    unsigned t, k;
    g_points++;
    if (x < sc->x0 || x > sc->x1 || y < sc->y0 || y > sc->y1) return;
    float tex[8][4];
    for (t = 0; t < 2; t++) {
        const float* ca = &a->col[t].r;
        for (k = 0; k < 4; k++) { int cv = (int)(ca[k] * 255.0f + 0.5f); col[t][k] = cv < 0 ? 0 : (cv > 255 ? 255 : cv); }
    }
    for (t = 0; t < 8; t++) { tex[t][0] = a->tex[t][0]; tex[t][1] = a->tex[t][1]; tex[t][2] = a->tex[t][2]; tex[t][3] = 0.0f; }
    shade(D, x, y, col, tex, a->depth);
}

/* ---- clipping ----------------------------------------------------------- */

static void lerp_vertex(const Vertex* a, const Vertex* b, float t, Vertex* o)
{
    unsigned i, k;
    o->x = a->x + (b->x - a->x) * t;
    o->y = a->y + (b->y - a->y) * t;
    o->z = a->z + (b->z - a->z) * t;
    o->w = a->w + (b->w - a->w) * t;
    for (i = 0; i < 2; i++) {
        o->col[i].r = a->col[i].r + (b->col[i].r - a->col[i].r) * t;
        o->col[i].g = a->col[i].g + (b->col[i].g - a->col[i].g) * t;
        o->col[i].b = a->col[i].b + (b->col[i].b - a->col[i].b) * t;
        o->col[i].a = a->col[i].a + (b->col[i].a - a->col[i].a) * t;
    }
    for (i = 0; i < 8; i++) for (k = 0; k < 3; k++) o->tex[i][k] = a->tex[i][k] + (b->tex[i][k] - a->tex[i][k]) * t;
}

/* Clip space on this hardware: -w <= z <= 0 is visible, the volume Dolphin's
 * software clipper uses. A polygon is clipped against the near plane
 * (z + w >= 0), against w > 0, and against the far plane (z <= 0); the guard
 * band in x and y is still left to the scissor.
 *
 * The far plane used to be left to the scissor as well, which does not cover
 * it: a vertex past the far plane comes out of to_screen with a depth above
 * 1.0, depth_test clamps that to 0xFFFFFF, and LEQUAL against a buffer
 * cleared to 0xFFFFFF passes -- so geometry behind the far plane painted
 * over geometry in front of it.
 *
 * The slack below is load-bearing, and it is why the far test is not a bare
 * z <= 0. The game draws its whole 2D layer -- HUD, dialogue, menus, the
 * title -- as orthographic quads sitting exactly on the far plane: its ortho
 * projection leaves XF 0x1024 = -0.00999999978 and 0x1025 = -1.0 (near 0,
 * far 100) and the quads are at view z = -100, so z is fl(-0.00999999978 *
 * -100) - 1.0 and that product rounds to exactly 1.0f. Ten of the
 * twenty-three captured frames hold between 18 and 2652 such vertices, all of
 * them landing on z == 0.0f, which an inclusive test keeps. But the two terms
 * are a reciprocal and that reciprocal times a distance, computed separately
 * by the guest, so a scene whose numbers round the other way puts the 2D
 * layer one ulp past the plane -- and a bare z <= 0 would erase it. One ulp
 * at that scale is two units of the 24-bit depth buffer, so everything the
 * slack admits already has the deepest depth the buffer can hold and cannot
 * draw over anything the clip exists to protect. */
#define Z_FAR_SLACK (1.0f / 8388608.0f) /* 2^-23: one float32 ulp where the two projection terms cancel */

typedef enum { CLIP_NEAR, CLIP_W, CLIP_FAR } ClipPlane;

/* Signed distance to a clip plane, positive inside. Each one is linear in the
 * homogeneous coordinates, which is what makes the edge parameter below an
 * exact split of the edge rather than an approximation of one. */
static float clip_dist(const Vertex* v, ClipPlane plane)
{
    switch (plane) {
    case CLIP_NEAR: return v->z + v->w;
    case CLIP_W: return v->w - 1e-5f;
    default: return v->w * Z_FAR_SLACK - v->z;
    }
}

static unsigned clip_against(const Vertex* in, unsigned n, Vertex* out, ClipPlane plane)
{
    unsigned m = 0, i;
    for (i = 0; i < n; i++) {
        const Vertex* a = &in[i];
        const Vertex* b = &in[(i + 1) % n];
        float da = clip_dist(a, plane), db = clip_dist(b, plane);
        if (da >= 0.0f) out[m++] = *a;
        if ((da >= 0.0f) != (db >= 0.0f)) {
            float t = da / (da - db);
            lerp_vertex(a, b, t, &out[m++]);
        }
        if (m >= 14) break;
    }
    return m;
}

/* Whether the fast path may rasterize a vertex without running the clipper.
 * The w test is deliberately looser than the clipper's: this one asks only
 * that the vertex is in front of the eye, while the clipper's 1e-5 is there
 * to keep to_screen's reciprocal finite. Tightening it here would start
 * clipping triangles the renderer draws today, which is a separate question
 * from the far plane. */
static int vertex_unclipped(const Vertex* v)
{
    return clip_dist(v, CLIP_NEAR) >= 0.0f && v->w > 0.0f && clip_dist(v, CLIP_FAR) >= 0.0f;
}

static unsigned clip_polygon(Vertex* in, unsigned n, Vertex* out)
{
    Vertex tmp[16];
    n = clip_against(in, n, out, CLIP_NEAR);
    n = clip_against(out, n, tmp, CLIP_W);
    return clip_against(tmp, n, out, CLIP_FAR);
}

static void emit_triangle(const DrawCmd* D, const Vertex* a, const Vertex* b, const Vertex* c)
{
    Vertex in[3], out[16];
    unsigned n, i;
    int inside = vertex_unclipped(a) && vertex_unclipped(b) && vertex_unclipped(c);
    if (g_debug > 1 && t_tid <= 1 && g_draw_no >= (unsigned)g_debug)
        fprintf(stderr, "[gxr] draw %u clip-space (%.3f,%.3f,%.3f,%.3f) (%.3f,%.3f,%.3f,%.3f) (%.3f,%.3f,%.3f,%.3f) tex0 (%.3f,%.3f) (%.3f,%.3f) (%.3f,%.3f)\n",
                g_draw_no, a->x, a->y, a->z, a->w, b->x, b->y, b->z, b->w, c->x, c->y, c->z, c->w,
                a->tex[0][0], a->tex[0][1], b->tex[0][0], b->tex[0][1], c->tex[0][0], c->tex[0][1]);
    if (inside) {
        in[0] = *a; in[1] = *b; in[2] = *c;
        for (i = 0; i < 3; i++) to_screen(&D->rc, &in[i]);
        raster_triangle(D, &in[0], &in[1], &in[2]);
        return;
    }
    in[0] = *a; in[1] = *b; in[2] = *c;
    n = clip_polygon(in, 3, out);
    if (n < 3) {
        if (t_tid <= 1) g_clipped++;
        if (g_debug && t_tid <= 1 && g_clipped <= 6)
            fprintf(stderr, "[gxr] clipped: (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f) (%.2f,%.2f,%.2f,%.2f)\n",
                    a->x, a->y, a->z, a->w, b->x, b->y, b->z, b->w, c->x, c->y, c->z, c->w);
        return;
    }
    for (i = 0; i < n; i++) to_screen(&D->rc, &out[i]);
    for (i = 1; i + 1 < n; i++) raster_triangle(D, &out[0], &out[i], &out[i + 1]);
}

static void run_copy(const DrawCmd* D);
static void run_copy_clear(const DrawCmd* D);
static void filter_sample(const DrawCmd* D, int sx, int sy, int ytop, int ybot, uint8_t* o);
static void workers_start(void);
void gxr_flush(void);

static void draw_command(const DrawCmd* D)
{
    const Vertex* v = D->v;
    unsigned count = D->count, i;
    if (D->kind == 1) { run_copy(D); return; }
    if (D->kind == 2) { run_copy_clear(D); return; }
    switch (D->prim) {
    case 0x80: /* quads */
        for (i = 0; i + 3 < count; i += 4) {
            emit_triangle(D, &v[i], &v[i + 1], &v[i + 2]);
            emit_triangle(D, &v[i], &v[i + 2], &v[i + 3]);
        }
        break;
    case 0x90: /* triangles */
        for (i = 0; i + 2 < count; i += 3) emit_triangle(D, &v[i], &v[i + 1], &v[i + 2]);
        break;
    case 0x98: /* strip */
        for (i = 2; i < count; i++) {
            if (i & 1) emit_triangle(D, &v[i - 1], &v[i - 2], &v[i]);
            else emit_triangle(D, &v[i - 2], &v[i - 1], &v[i]);
        }
        break;
    case 0xA0: /* fan */
        for (i = 2; i < count; i++) emit_triangle(D, &v[0], &v[i - 1], &v[i]);
        break;
    case 0xA8: /* lines: one thread only */
        if (t_tid > 1) break;
        for (i = 0; i + 1 < count; i += 2) {
            Vertex a = v[i], b = v[i + 1];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(&D->rc, &a); to_screen(&D->rc, &b);
            raster_line(D, &a, &b);
        }
        break;
    case 0xB0: /* line strip */
        if (t_tid > 1) break;
        for (i = 1; i < count; i++) {
            Vertex a = v[i - 1], b = v[i];
            if (a.w <= 0.0f || b.w <= 0.0f) continue;
            to_screen(&D->rc, &a); to_screen(&D->rc, &b);
            raster_line(D, &a, &b);
        }
        break;
    case 0xB8: /* points */
        if (t_tid > 1) break;
        for (i = 0; i < count; i++) {
            Vertex a = v[i];
            if (a.w <= 0.0f) continue;
            to_screen(&D->rc, &a);
            raster_point(D, &a);
        }
        break;
    default: break;
    }
}

/* ---- the queue and its workers ----------------------------------------- */

/* Commands are numbered rather than indexed, and the numbering is never reset.
 * Command n lives in slot n & QMASK. Three rules follow, and they are one rule
 * seen three ways:
 *
 *  - every count here has exactly one writer and only ever goes up.
 *    g_published is the producer's; g_ran[id] is worker id's. Nothing resets
 *    either, so a stale read is always too small, and too small can only make
 *    a thread wait longer than it had to.
 *  - a worker's decision to run a command reads exactly one word another
 *    thread writes -- g_published -- against a count it keeps to itself. There
 *    is no second shared load for a compiler to order against the first, which
 *    is the pair gxr_flush used to be racing when it rewound both of them.
 *  - gxr_flush leaves the numbering alone. It waits for every g_ran[] to reach
 *    g_published, which puts every worker back in its spin with nothing left
 *    to run, and only then recycles the vertex arena, the copy hazard list and
 *    the texture graveyard -- none of which any worker can still reach. So
 *    what the flush writes and what a running worker reads are disjoint sets,
 *    and that is checkable by finding the writes rather than by reasoning
 *    about where each thread is at the time.
 *
 * Two live commands would share a slot only if they were QUEUE_CAP apart, and
 * queued() >= QUEUE_CAP forces a full drain before the producer can get that
 * far ahead. DrawCmd::seq is the check on that arithmetic rather than a
 * comment about it.
 *
 * Counted in 64 bits because nothing resets them and a single run is long:
 * build/boot_field.log records 138,619,966 draws in one process, and
 * build/boot_perf.log 3,176,974 over 4,210 presented frames -- 755 a frame,
 * which reaches the end of a signed 32-bit count in about a day of play.
 *
 * Every gxr_flush caller is on the thread that produces (the one parsing the
 * guest's command stream); the watchdog thread only calls gxr_report, which
 * does not flush. That is what lets the flush read g_published once and treat
 * it as fixed: it is the only writer. */
static DrawCmd* g_queue;
static volatile LONGLONG g_published;            /* commands published, ever */
static volatile LONGLONG g_ran[MAX_THREADS + 1]; /* per worker: commands finished, ever */
static long long g_drained;                      /* producer only: g_published as of the last drain */
static uint64_t g_flushes;                       /* producer only: drains, so a nested one can be seen */
static uint8_t* g_arena;
static size_t g_arena_used;
static int g_workers; /* worker threads; the main thread (tid 0) only produces */
/* Where a draw's TEV setup is built, before the slot it will be queued in has
 * been chosen. Only the thread that parses the command stream touches it. */
static TevSetup g_prep;
static uint64_t g_prepare_flushes; /* draws whose setup had to wait for a queued copy */

/* Commands published since the last drain, which is what the ring's capacity
 * is measured against. Producer only: a worker has no use for it, and
 * g_drained is not published. */
static long long queued(void) { return g_published - g_drained; }

#ifdef _WIN32
static DWORD WINAPI worker(LPVOID arg)
{
    int id = (int)(intptr_t)arg; /* 1..workers */
    /* This worker's own count, kept here rather than read back out of g_ran so
     * the spin below has one shared word in it. Zero because the pool is
     * created before the first command is published. */
    long long mine = 0;
    ThreadState* W = &g_ts[id];
    t_tid = id;
    /* Every worker's clock starts when the pool did, so busy + idle can be
     * compared against one span for the whole pool. */
    W->last = g_pool_t0;
    for (;;) {
        const DrawCmd* D;
        unsigned spins = 0;
        while (mine >= g_published) {
            /* Charging the wait as it goes rather than only when it ends is
             * what lets a pool parked for twenty seconds under the watchdog
             * still add up to the span the report divides by: the backoff
             * bounds how much of an idle worker's time is unaccounted when
             * the report reads these. One clock read per 4000 spins. */
            if (++spins > 4000) { charge(W, &W->idle); Sleep(0); spins = 0; }
            else YieldProcessor();
        }
        charge(W, &W->idle);
        /* The producer fills a slot before it publishes the count, and this
         * machine does not reorder two loads, so the command is there. The
         * barrier is against the compiler alone, stopping it from reading the
         * command's fields before the spin ends; it emits nothing. */
        _ReadWriteBarrier();
        D = &g_queue[mine & QMASK];
        if (D->seq != mine)
            WARN_ONCE("[gxr] queue slot %lld holds command %lld, not command %lld, which is the one this worker is on: the producer got %d commands ahead of it without draining and built over it, so the command is skipped and this frame is wrong\n",
                      mine & QMASK, D->seq, mine, QUEUE_CAP);
        else
            draw_command(D);
        /* The two readings bracketing the command are inside what they
         * measure, so a command this worker owns no rows of is charged their
         * cost -- about 14 ns against a command that does nothing. The report
         * says so rather than hide it. */
        charge(W, &W->busy);
        mine++;
        InterlockedExchange64(&g_ran[id], mine);
    }
}
#endif

static void workers_start(void)
{
    const char* env = getenv("SOA_THREADS");
    int n = env ? atoi(env) : 0, i;
    /* Before the threads, so every one of them starts its busy/idle clock at
     * the same reading the report measures the pool's span from. */
    if (g_gxr_tsc < 0) gxr_timing_init();
    g_pool_t0 = gxr_ticks();
    g_queue = (DrawCmd*)malloc(sizeof(DrawCmd) * QUEUE_CAP);
    g_arena = (uint8_t*)malloc(ARENA_BYTES);
#ifdef _WIN32
    if (n <= 0) {
        SYSTEM_INFO si;
        GetSystemInfo(&si);
        n = (int)si.dwNumberOfProcessors / 2;
        if (n < 1) n = 1;
    }
    if (n > MAX_THREADS) n = MAX_THREADS;
    for (i = 1; i <= n; i++) {
        HANDLE h = CreateThread(NULL, 0, worker, (LPVOID)(intptr_t)i, 0, NULL);
        if (!h) { n = i - 1; break; }
        CloseHandle(h);
    }
#else
    n = 0;
#endif
    g_workers = n;
    g_nthreads = n > 0 ? n : 1;
    fprintf(stderr, "[gxr] rasterizing on %d worker thread%s\n", n, n == 1 ? "" : "s");
}

static int g_pending_n; /* queued copy destinations (defined with the copies below) */
static int g_started;   /* worker pool created */

/* Wait for every queued draw to finish, then recycle the queue.
 *
 * Nothing below the wait is written that a worker reads: the numbering is left
 * where it is and only producer-private storage is handed out again. A worker
 * that has reached g_published cannot run anything else, because the thread
 * inside this function is the only one that publishes. */
void gxr_flush(void)
{
    long long target;
    unsigned spins = 0;
    int i, prev;
    if (!g_queue) return;
    /* Read once: this thread is the only writer, so the target cannot move. */
    target = g_published;
    /* The wait is the producer's idle, and it used to be charged to whichever
     * of draw, prepare and copies happened to enclose the call -- and to
     * nothing at all from GXDrawDone. It is its own bucket now, and it is the
     * number that says whether the guest thread or the rasterizer is the one
     * holding the run up. */
    prev = gxr_phase(T_WAIT);
    /* Backing off matters here for the reason it does in the worker's own
     * spin, which this copies: at SOA_THREADS near the core count the producer
     * and the workers compete for the same cores, and a bare YieldProcessor()
     * takes one away from the very threads being waited on. With four of these
     * processes sharing sixteen cores, 400 flushes of a full-screen draw at
     * SOA_THREADS=16 cost 3.1-3.5s and 12-15s of CPU each without it, and
     * 1.5-1.6s and 5.6-7.4s with it. */
    for (i = 1; i <= g_workers; i++)
        while (g_ran[i] < target) { if (++spins > 4000) { Sleep(0); spins = 0; } else YieldProcessor(); }
    gxr_phase(prev);
    g_drained = target;
    g_flushes++;
    g_arena_used = 0;
    g_pending_n = 0;
    tex_graveyard_empty();
}

static void gxr_draw_inner(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize);

void gxr_draw(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize)
{
    TIMED(T_SETUP, gxr_draw_inner(s, op, count, verts, vsize));
}

static void gxr_draw_inner(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize)
{
    const uint32_t* xf = gx_xf_regs();
    const uint32_t* bp = gx_bp_regs();
    unsigned prim = op & 0xF8, vat = op & 7, i;
    const uint8_t* p = verts;
    Vertex* v;
    DrawCmd* D;
    (void)vsize;
    if (!gxr_enabled() || count == 0) return;
    ++g_draw_no;
    if (g_draw_limit && g_draw_no > g_draw_limit) return; /* SOA_GXR_DRAWS=N: stop after N draws */
    /* Headless snapshots (SOA_SNAP=N): only the frames being written are
     * worth rasterizing; the game then runs at full speed between them. A
     * window (g_draw_every) or a replay (g_png_path) wants every frame it
     * shows, whatever the interval says. */
    if (g_snap_every && !g_draw_every && !g_png_path[0] && (gx_frame_count() % g_snap_every) != 0) return;
    if (!g_started) { g_started = 1; workers_start(); }
    tex_set_memory(s);

    if (queued() >= QUEUE_CAP || g_arena_used + sizeof(Vertex) * count > ARENA_BYTES || tex_graveyard_full()) gxr_flush();
    draw_tripwire(bp, prim);
    /* Nothing of the queue's is claimed until tev_prepare has returned.
     * Resolving a texture read from a destination a queued copy has not
     * written yet makes it flush, and a flush takes the vertex arena back to
     * the start: a vertex pointer taken before the call would name storage
     * that is about to be handed out again. That is now the whole of the
     * reason. The other half of it was the slot, and the numbering has
     * retired that half -- a flush no longer moves the command number, so the
     * slot this draw goes in is the same either side of one -- but the arena
     * reset is untouched, so the order still has to hold. The check above has
     * left room for this draw, and a flush inside the call only ever leaves
     * more.
     *
     * Counting flushes rather than watching the number move is not a
     * translation: the numbering deliberately does not move across a flush, so
     * the old test would now always say no, and the counter whose whole job is
     * to report whether a run took this path would read zero on a run that
     * took it. */
    {
        uint64_t flushes = g_flushes;
        TIMED(T_PREPARE, tev_prepare(bp, &g_prep));
        if (g_flushes != flushes) g_prepare_flushes++;
    }
    v = (Vertex*)(g_arena + g_arena_used);
    g_arena_used += (sizeof(Vertex) * count + 15) & ~(size_t)15;
    D = &g_queue[g_published & QMASK];
    D->seq = g_published;
    D->kind = 0;
    D->tev = g_prep;
    pixel_prepare(bp, &D->px);
    raster_prepare(xf, bp, &D->rc);
    D->ntex = D->tev.used_tex & ((1u << (xf[0x103F] & 15)) - 1u);
    D->nchan = D->tev.used_chan;
    D->miptex = 0;
    memset(D->texmap_of, 0, sizeof D->texmap_of);
    {
        unsigned st;
        for (st = 0; st < D->tev.stages; st++) {
            const Stage* S = &D->tev.st[st];
            if (!S->texen) continue;
            D->texmap_of[S->texcoord] = S->texmap;
            if (D->tev.tex[S->texmap].mip && D->tev.tex[S->texmap].nlevels > 1) D->miptex |= 1u << S->texcoord;
        }
    }
    D->prim = prim; D->count = count; D->v = v;
    for (i = 0; i < count; i++) {
        VertexIn in;
        p = decode_vertex(s, p, vat, &in);
        transform(s, &in, &v[i]);
    }
    if (prim <= 0xA0) g_tris += prim == 0x80 ? (count / 4) * 2 : (prim == 0x90 ? count / 3 : (count >= 2 ? count - 2 : 0));
    if (g_workers > 0) {
        InterlockedIncrement64(&g_published); /* publish: the workers pick it up */
    } else {
        t_tid = 1;
        /* Without workers the rasterizer runs on the producer, so it needs a
         * bucket of its own here or its time would be booked as vertex setup. */
        TIMED(T_RASTER, draw_command(D));
        /* Run here and drained here, so the numbering still advances and the
         * arena is free again. */
        InterlockedIncrement64(&g_published);
        g_drained = g_published;
        g_arena_used = 0;
    }
}

/* ---- EFB copy and clear ---------------------------------------------------- */

/* Rows this thread owns: every Nth when workers exist, all otherwise. */
static inline int my_row(int y)
{
    return g_nthreads <= 1 || (unsigned)y % (unsigned)g_nthreads == (unsigned)(t_tid - 1);
}

static void efb_clear(uint32_t ar, uint32_t gb, uint32_t zreg, int x0, int y0, int w, int h)
{
    uint32_t z = zreg & 0xFFFFFFu;
    uint8_t col[4] = {(uint8_t)(ar & 0xFF), (uint8_t)((gb >> 8) & 0xFF), (uint8_t)(gb & 0xFF), (uint8_t)((ar >> 8) & 0xFF)};
    int x, y;
    for (y = y0; y < y0 + h && y < EFB_H; y++) {
        if (y < 0 || !my_row(y)) continue;
        for (x = x0; x < x0 + w && x < EFB_W; x++) {
            if (x < 0) continue;
            memcpy(g_efb[y][x], col, 4);
            g_efb_z[y][x] = z;
        }
    }
}

/* Write an EFB rectangle into memory as a texture (GXCopyTex). Tiled like
 * the formats the sampler decodes. */
static void copy_to_texture(const DrawCmd* D, CpuState* s, uint32_t dest_reg, uint32_t v, int x0, int y0, int w, int h)
{
    uint32_t dest = (dest_reg & 0x1FFFFFu) << 5;
    unsigned tpf = (v >> 3) & 15;
    unsigned fmt = tpf / 2 + (tpf & 1) * 8; /* EFBCopyFormat */
    int intensity = (v >> 15) & 1, half = (v >> 9) & 1;
    int ow = half ? w / 2 : w, oh = half ? h / 2 : h;
    /* Texture copies are filtered too. BP 0x53/0x54 are global PE state with
     * no per-copy enable: GXCopyDisp and GXCopyTex each read-modify-write only
     * their own shadow of the 0x52 command word and touch neither filter
     * register, and GXSetCopyClamp writes the filter's edge control into the
     * texture-copy shadow as well, which it would have no reason to do if a
     * texture copy were unfiltered. */
    int filtered = !(D->cp_f_up == 0 && D->cp_f_dn == 0 && D->cp_f_mid == 64);
    int ytop = y0 < 0 ? 0 : y0;
    int ybot = y0 + h - 1 > EFB_H - 1 ? EFB_H - 1 : y0 + h - 1;
    int x, y;
    unsigned tw, th, bpt;
    uint8_t* base;

    /* map copy formats onto texture formats; anything else is left alone
     * rather than written at a guessed size */
    unsigned texfmt, chan_a = 0, chan_b = 3; /* source channels for single/dual-channel copies */
    if (intensity) texfmt = fmt == 0 ? 0 : fmt == 1 ? 1 : fmt == 2 ? 2 : fmt == 3 ? 3 : 99;
    else switch (fmt) {
    case 0: texfmt = 0; break;                       /* R4 */
    case 1: case 8: texfmt = 1; break;               /* R8 */
    case 9: texfmt = 1; chan_a = 1; break;           /* G8 */
    case 10: texfmt = 1; chan_a = 2; break;          /* B8 */
    case 7: texfmt = 1; chan_a = 3; break;           /* A8 */
    case 2: texfmt = 2; break;                       /* RA4 */
    case 3: texfmt = 3; break;                       /* RA8 */
    case 11: texfmt = 3; chan_a = 0; chan_b = 1; break; /* RG8: like IA8 with (g, r)? keep (b=g, a=r) */
    case 12: texfmt = 3; chan_a = 1; chan_b = 2; break; /* GB8 */
    case 4: texfmt = 4; break;
    case 5: texfmt = 5; break;
    case 6: texfmt = 6; break;
    default: texfmt = 99; break;
    }
    if (g_debug && g_copies_tex < 16)
        fprintf(stderr, "[gxr] copy to texture: dest %08X %dx%d from (%d,%d) fmt %u intensity %d half %d -> texfmt %u" "\n",
                dest, w, h, x0, y0, fmt, intensity, half, texfmt);
    if (texfmt == 99) { g_copies_tex++; return; }

    switch (texfmt) {
    case 0: tw = 8; th = 8; bpt = 32; break;
    case 1: case 2: tw = 8; th = 4; bpt = 32; break;
    case 3: case 4: case 5: tw = 4; th = 4; bpt = 32; break;
    default: tw = 4; th = 4; bpt = 64; texfmt = 6; break;
    }
    /* A half-scale copy already averages two rows, and no source in this tree
     * settles whether the console filters before or after that box, so it is
     * left unfiltered and says so. No capture sets half scale: bit 9 is clear
     * on all 39 copies in the corpus. */
    if (half && filtered)
        WARN_ONCE("[gxr] half-scale EFB copy with the vertical filter programmed; the box filter is applied and the vertical filter is not, because their order is not established\n");
    if ((dest & MEM_MASK) + (size_t)((oh + th - 1) / th) * ((ow + tw - 1) / tw) * bpt > MEM1_SIZE) return;
    base = mem_ptr(s, dest | 0x80000000u);
    for (y = 0; y < oh; y++) {
        if (!my_row(half ? 2 * y : y) && !(half && my_row(2 * y + 1))) continue;
        if (half && !my_row(2 * y)) continue; /* half-scale rows are flushed before queueing */
        for (x = 0; x < ow; x++) {
            int sx = x0 + (half ? 2 * x : x), sy = y0 + (half ? 2 * y : y);
            uint8_t px[4] = {0, 0, 0, 255};
            unsigned tiles_w = (ow + tw - 1) / tw;
            uint8_t* tile = base + ((y / th) * tiles_w + x / tw) * bpt;
            unsigned ix = x % tw, iy = y % th;
            unsigned I;
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) {
                if (half && sx + 1 < EFB_W && sy + 1 < EFB_H) {
                    int k;
                    for (k = 0; k < 4; k++)
                        px[k] = (uint8_t)((g_efb[sy][sx][k] + g_efb[sy][sx + 1][k] + g_efb[sy + 1][sx][k] + g_efb[sy + 1][sx + 1][k]) / 4);
                } else {
                    /* Filter before the format conversion below: for RGB565,
                     * RGB5A3 and R4 , blending the quantised values gives a
                     * different answer from quantising the blend. Alpha keeps
                     * the centre row's -- the console has no alpha plane to
                     * filter here, PE_CONTROL being RGB8_Z24 in every capture. */
                    memcpy(px, g_efb[sy][sx], 4);
                    if (filtered) filter_sample(D, sx, sy, ytop, ybot, px);
                }
            }
            if (intensity) {
                I = (unsigned)(0.257f * px[0] + 0.504f * px[1] + 0.098f * px[2] + 16.0f);
                if (I > 255) I = 255;
            } else {
                I = px[chan_a]; /* single-channel copies take that channel; dual ones pair it with chan_b */
                if (texfmt == 2 || texfmt == 3) px[3] = px[chan_b];
            }
            switch (texfmt) {
            case 0: { uint8_t* b = &tile[iy * 4 + ix / 2]; unsigned n = I >> 4; if (ix & 1) *b = (uint8_t)((*b & 0xF0) | n); else *b = (uint8_t)((*b & 0x0F) | (n << 4)); break; }
            case 1: tile[iy * 8 + ix] = (uint8_t)I; break;
            case 2: tile[iy * 8 + ix] = (uint8_t)((px[3] & 0xF0) | (I >> 4)); break;
            case 3: tile[(iy * 4 + ix) * 2] = px[3]; tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)I; break;
            case 4: { unsigned c = ((px[0] >> 3) << 11) | ((px[1] >> 2) << 5) | (px[2] >> 3); tile[(iy * 4 + ix) * 2] = (uint8_t)(c >> 8); tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)c; break; }
            case 5: { unsigned c;
                if (px[3] >= 224) c = 0x8000 | ((px[0] >> 3) << 10) | ((px[1] >> 3) << 5) | (px[2] >> 3);
                else c = ((px[3] >> 5) << 12) | ((px[0] >> 4) << 8) | ((px[1] >> 4) << 4) | (px[2] >> 4);
                tile[(iy * 4 + ix) * 2] = (uint8_t)(c >> 8); tile[(iy * 4 + ix) * 2 + 1] = (uint8_t)c; break; }
            default:
                tile[(iy * 4 + ix) * 2] = px[3]; tile[(iy * 4 + ix) * 2 + 1] = px[0];
                tile[32 + (iy * 4 + ix) * 2] = px[1]; tile[32 + (iy * 4 + ix) * 2 + 1] = px[2];
                break;
            }
        }
    }
    g_copies_tex++;
}

static uint8_t g_screen[EFB_H][EFB_W][4]; /* the last frame copied out, RGBA */
static int g_screen_w = EFB_W, g_screen_h = 480;
static volatile LONG g_frames_presented; /* copies to the screen completed by all rows */

/* One filtered EFB sample: the three rows the copy filter reads, weighted and
 * divided by 64.
 *
 * The taps are clamped to the COPY RECTANGLE, not to the EFB. EFB_H is 528 and
 * every copy this game makes is 480 rows, so clamping to EFB_H-1 would pull
 * rows from below the rectangle -- whatever the last clear and scissor left
 * there -- into the bottom row of every frame, and only an edge test would
 * ever catch it. BP 0x52's bits 0 and 1 are the hardware's own clamp_top and
 * clamp_bottom and are set on every copy in the corpus; when one is clear we
 * clamp anyway and say so, because nothing in this tree establishes what the
 * hardware reads instead and a guess should be visible rather than silent.
 *
 * Truncating (>> 6) rather than rounding is a decision, not an accident: it is
 * what Dolphin does, and whichever rule is compiled is what the frame manifest
 * pins, so a later tidy-up to round-half-up would move all 23 hashes with no
 * behavioural reason to. */
static void filter_sample(const DrawCmd* D, int sx, int sy, int ytop, int ybot, uint8_t* o)
{
    int ya = sy - 1 < ytop ? ytop : sy - 1;
    int yb = sy + 1 > ybot ? ybot : sy + 1;
    unsigned up = D->cp_f_up, mid = D->cp_f_mid, dn = D->cp_f_dn;
    int k;
    for (k = 0; k < 3; k++) {
        unsigned v = up * g_efb[ya][sx][k] + mid * g_efb[sy][sx][k] + dn * g_efb[yb][sx][k];
        v >>= 6;
        o[k] = (uint8_t)(v > 255u ? 255u : v);
    }
}

static void copy_to_screen(const DrawCmd* D, int x0, int y0, int w, int h)
{
    int x, y;
    int filtered = !(D->cp_f_up == 0 && D->cp_f_dn == 0 && D->cp_f_mid == 64);
    int ytop = y0 < 0 ? 0 : y0;
    int ybot = y0 + h - 1 > EFB_H - 1 ? EFB_H - 1 : y0 + h - 1;
    if (filtered && (D->cp_v & 3u) != 3u)
        WARN_ONCE("[gxr] EFB copy asks for the vertical filter with clamp_top/clamp_bottom (BP 52 %06X) not both set; the taps are clamped to the copy rectangle anyway\n",
                  D->cp_v & 0xFFFFFFu);
    for (y = 0; y < h && y < EFB_H; y++) {
        int sy = y0 + y;
        if (!my_row(y)) continue;
        for (x = 0; x < w && x < EFB_W; x++) {
            int sx = x0 + x;
            uint8_t* o = g_screen[y][x];
            if (sx >= 0 && sy >= 0 && sx < EFB_W && sy < EFB_H) {
                if (filtered) filter_sample(D, sx, sy, ytop, ybot, o);
                else memcpy(o, g_efb[sy][sx], 3);
                o[3] = 255;
            } else { o[0] = o[1] = o[2] = 0; o[3] = 255; }
        }
    }
}

/* Whether this copy reads EFB rows the worker running it did not write: a
 * vertical filter reaches one row either side, and a half-scale copy pairs
 * rows. Both make the fused clear unsafe, so enqueue_copy publishes the clear
 * separately and this says so from the command alone. */
static int copy_is_foreign(int half, int filtered, int y0)
{
    /* The third case: the copy picks its rows by destination y and reads
     * source row y0 + y, while the rasterizer owns rows by absolute y, so the
     * two coincide only when y0 is a multiple of the worker count. Found by
     * reading the code, not by a sweep, which is the reason it can hide. */
    return half || filtered || (g_nthreads > 1 && (unsigned)y0 % (unsigned)g_nthreads != 0);
}

static int copy_reads_foreign_rows(const DrawCmd* D)
{
    int half = (D->cp_v >> 9) & 1;
    int filtered = !(D->cp_f_up == 0 && D->cp_f_dn == 0 && D->cp_f_mid == 64);
    return copy_is_foreign(half, filtered, (int)((D->cp_tl >> 10) & 0x3FF));
}

static void run_copy(const DrawCmd* D)
{
    int x0 = (int)(D->cp_tl & 0x3FF), y0 = (int)((D->cp_tl >> 10) & 0x3FF);
    int w = (int)(D->cp_wh & 0x3FF) + 1, h = (int)((D->cp_wh >> 10) & 0x3FF) + 1;
    if (D->cp_v & 0x4000u) copy_to_screen(D, x0, y0, w, h);
    else copy_to_texture(D, D->s, D->cp_dest, D->cp_v, x0, y0, w, h);
    if ((D->cp_v & 0x800u) && !copy_reads_foreign_rows(D))
        efb_clear(D->cp_ar, D->cp_gb, D->cp_z, x0, y0, w, h);
    if (D->cp_v & 0x4000u) InterlockedIncrement(&g_frames_presented);
}

/* The deferred half of the command above, published after a drain. */
static void run_copy_clear(const DrawCmd* D)
{
    int x0 = (int)(D->cp_tl & 0x3FF), y0 = (int)((D->cp_tl >> 10) & 0x3FF);
    int w = (int)(D->cp_wh & 0x3FF) + 1, h = (int)((D->cp_wh >> 10) & 0x3FF) + 1;
    efb_clear(D->cp_ar, D->cp_gb, D->cp_z, x0, y0, w, h);
}

/* Copy destinations still in the queue: a texture decoded from one of
 * them must wait for it. */
typedef struct { uint32_t addr, bytes; } Pending;
static Pending g_pending[QUEUE_CAP];
static int g_pending_n;

void gxr_texture_hazard(uint32_t addr, uint32_t bytes)
{
    int i;
    addr &= MEM_MASK;
    for (i = 0; i < g_pending_n; i++)
        if (addr < g_pending[i].addr + g_pending[i].bytes && addr + bytes > g_pending[i].addr) { gxr_flush(); return; }
}

long gxr_presented(void)
{
    return g_workers > 0 ? g_frames_presented / g_workers : g_frames_presented;
}

const uint8_t* gxr_screen(int* w, int* h)
{
    *w = g_screen_w; *h = g_screen_h;
    return &g_screen[0][0][0];
}

static uint64_t fnv1a(uint64_t h, const uint8_t* p, size_t n)
{
    while (n--) { h ^= *p++; h *= 1099511628211ULL; }
    return h;
}

/* FNV-1a over the pixels the port would present, so two runs can be compared
 * without keeping a PNG of either. The size goes in first -- a frame that
 * changes shape is a different frame -- then the rows in screen order, only
 * the part of each row this frame covers. Nothing here depends on which
 * worker produced a row, so the value is the same at any SOA_THREADS, and
 * every caller hashes after gxr_flush() so the frame is finished. */
uint64_t gxr_screen_hash(void)
{
    uint8_t dim[4] = {(uint8_t)(g_screen_w >> 8), (uint8_t)g_screen_w,
                      (uint8_t)(g_screen_h >> 8), (uint8_t)g_screen_h};
    uint64_t h = fnv1a(14695981039346656037ULL, dim, sizeof dim);
    int y;
    for (y = 0; y < g_screen_h; y++) h = fnv1a(h, g_screen[y][0], (size_t)g_screen_w * 4);
    return h;
}

/* Nothing else creates build/frames, so the first SOA_SNAP run on a clean
 * tree used to write nothing and say only that it could not. */
static void ensure_frames_dir(void)
{
    static int done;
    if (done) return;
    done = 1;
#ifdef _WIN32
    _mkdir("build");
    _mkdir("build/frames");
#else
    mkdir("build", 0777);
    mkdir("build/frames", 0777);
#endif
}

static void write_frame_png(const char* path, int w, int h)
{
    if (!png_write_rgba(path, &g_screen[0][0][0], w, h, EFB_W * 4)) fprintf(stderr, "[gxr] cannot write %s\n", path);
    else fprintf(stderr, "[gxr] wrote %s (%dx%d)\n", path, w, h);
}

/* The EFB copy's vertical filter (BP 0x53/0x54), collapsed onto the rows it
 * actually reads.
 *
 * The seven six-bit weights are NOT seven rows. They are vertical sub-samples:
 * two belong to the row above, three to the row itself and two to the row
 * below, which is why seven taps span three pixels. So the game's
 * 8,8,10,12,10,8,8 is 16/64 above, 32/64 centre, 16/64 below -- a 1:2:1
 * deflicker blur -- and nothing lands two or three rows away.
 *
 * The source for that grouping is patent US6999100B1, the hardware's own
 * description ("seven samples from three vertically arranged pixels ... Three
 * samples are taken from the current pixel, two samples ... immediately above
 * ... two ... immediately below"), corroborated by libogc, whose vfilter
 * tables are labelled "line n-1 through n+1". It is deliberately not derived
 * from the SDK's filter-off set {0,0,21,22,21,0,0} -- GXSetCopyFilter is
 * fn_8024EF50 and its vf == 0 arm at 0x8024F138 loads exactly that. That set
 * proves taps 2,3,4 land on the current row, since nothing else makes it an
 * identity, and so kills any reading of seven distinct rows; but it is equally
 * an identity under a FIVE-row window, which would give 8/8/32/8/8 instead.
 * The register layout cannot settle this. Reading it and assuming the rest is
 * how PLAN C3's acceptance criterion came to be wrong for two days. */
static void copy_filter(uint32_t f0, uint32_t f1, uint8_t* up, uint8_t* mid, uint8_t* dn)
{
    unsigned w0 = f0 & 0x3F, w1 = (f0 >> 6) & 0x3F, w2 = (f0 >> 12) & 0x3F, w3 = (f0 >> 18) & 0x3F;
    unsigned w4 = f1 & 0x3F, w5 = (f1 >> 6) & 0x3F, w6 = (f1 >> 12) & 0x3F;
    *up = (uint8_t)(w0 + w1);
    *mid = (uint8_t)(w2 + w3 + w4);
    *dn = (uint8_t)(w5 + w6);
    /* All seven zero is not a request for a filter that multiplies every pixel
     * by nothing: it is the register never having been written, which means a
     * synthetic stream rather than the game. Copy unfiltered, exactly as the
     * Y-scale check below reads a zero there. Getting this wrong copies a
     * black frame, and it is the renderer's own selftest that says so --
     * "render full-screen quad: 0 of 307200 red". */
    if ((*up | *mid | *dn) == 0) { *mid = 64; return; }
    /* A set that does not sum to 64 scales every copied pixel's brightness,
     * and it would sail past a "the neighbours are zero" test. Nothing the
     * game programs can trip this; a synthetic stream can, which is the point
     * -- an oracle that cannot fail is worse than none. */
    if ((unsigned)*up + *mid + *dn != 64u)
        WARN_ONCE("[gxr] EFB copy filter weights (BP 53 %06X, BP 54 %06X) sum to %u, not 64, so the copy would rescale every pixel's brightness; applied as given\n",
                  f0, f1, (unsigned)*up + *mid + *dn);
}

static void enqueue_copy(CpuState* s, const uint32_t* bp, uint32_t v)
{
    DrawCmd* D;
    int x0 = (int)(bp[0x49] & 0x3FF), y0 = (int)((bp[0x49] >> 10) & 0x3FF);
    int w = (int)(bp[0x4A] & 0x3FF) + 1, h = (int)((bp[0x4A] >> 10) & 0x3FF) + 1;
    int to_screen = (v & 0x4000u) != 0, half = (v >> 9) & 1;
    uint8_t f_up, f_mid, f_dn;
    int filtered, foreign;
    /* Filtered iff the collapsed kernel is not the exact identity. Asking the
     * weights rather than masking the registers is what makes this right: the
     * mask here was 0x03FFFF against both words, which takes w3 alone for the
     * centre row and so calls the SDK's own filter-off set filtered, since
     * that set is w2 = 21, w3 = 22, w4 = 21. Testing the sum as well means a
     * set that does not total 64 takes the filtered path and is scaled, rather
     * than being waved through as "near enough to the identity". */
    copy_filter(bp[0x53], bp[0x54], &f_up, &f_mid, &f_dn);
    filtered = !(f_up == 0 && f_dn == 0 && f_mid == 64);
    /* Copy Y-scale (BP 4E) is 1.8 fixed point over the whole 24-bit field,
     * and 000100 is the identity -- all the game has ever programmed, and it
     * cannot move a pixel -- so this warns only when the copy is asked to
     * rescale and we ignore it. Comparing the whole field matters both ways:
     * a nine-bit compare would read 000300 as the identity and say nothing,
     * and print 000200 as 0.000 while warning. Zero is not a request: it is
     * the register never having been written, which is a synthetic stream
     * rather than the game, and a scale of zero would copy nothing. */
    if ((bp[0x4E] & 0xFFFFFFu) && (bp[0x4E] & 0xFFFFFFu) != 0x100u)
        WARN_ONCE("[gxr] EFB copy Y-scale (BP 4E %06X) is %.3f, not 1.0; the copy is not scaled vertically, so the destination keeps the source's height\n",
                  bp[0x4E], (double)(bp[0x4E] & 0xFFFFFFu) / 256.0);
    if (!g_started) { g_started = 1; workers_start(); }
    tex_set_memory(s);
    /* Both of these read EFB rows this worker does not own. my_row is strided
     * -- y % nthreads == tid-1 -- and the plain copy is safe only because the
     * row it reads is the row it wrote: the rasterizer partitions by absolute
     * EFB row and the copy by destination row, which coincide at y0 = 0. A
     * filtered output row reads y-1 and y+1, which belong to the two
     * neighbouring workers, and workers advance independently. Without this
     * the frame depends on SOA_THREADS. */
    foreign = copy_is_foreign(half, filtered, y0);
    if (foreign) gxr_flush();
    if (queued() >= QUEUE_CAP) gxr_flush();
    D = &g_queue[g_published & QMASK];
    D->seq = g_published;
    D->kind = 1; D->s = s;
    D->cp_v = v; D->cp_tl = bp[0x49]; D->cp_wh = bp[0x4A]; D->cp_dest = bp[0x4B]; D->cp_stride = bp[0x4D];
    D->cp_ar = bp[0x4F]; D->cp_gb = bp[0x50]; D->cp_z = bp[0x51];
    D->cp_f_up = f_up; D->cp_f_mid = f_mid; D->cp_f_dn = f_dn;
    if (to_screen) { g_screen_w = w > EFB_W ? EFB_W : w; g_screen_h = h > EFB_H ? EFB_H : h; g_copies_xfb++; }
    else {
        if (g_pending_n < QUEUE_CAP) {
            g_pending[g_pending_n].addr = ((bp[0x4B] & 0x1FFFFFu) << 5) & MEM_MASK;
            g_pending[g_pending_n].bytes = (uint32_t)w * (uint32_t)h * 4u; /* generous */
            g_pending_n++;
        }
        g_copies_tex++;
    }
    if (g_workers > 0) {
        InterlockedIncrement64(&g_published);
    } else {
        t_tid = 1;
        TIMED(T_RASTER, draw_command(D));
        InterlockedIncrement64(&g_published);
        g_drained = g_published;
        g_arena_used = 0;
    }
    /* A copy that samples rows it does not own is bracketed by two drains, not
     * one, and the second is the one that is easy to miss.
     *
     * The drain before it orders the producer's earlier draws. The drain after
     * it stops anything *later* from running ahead into the rows the copy is
     * still sampling: workers advance through the queue independently, so the
     * worker that finishes its share of the copy first would otherwise start
     * on the next draw -- or on the clear -- and write EFB rows its neighbours
     * are still reading as filter taps.
     *
     * This was measured, not reasoned about. With only the clear split out,
     * four captures disagreed with themselves at SOA_THREADS=8 on one sweep in
     * four -- 1550, 4500, 6000 and 16300, which are four of the eight captures
     * that copy to a texture. Screen copies hid it: they set the clear bit, so
     * the clear's own drain happened to serve as this one. Texture copies do
     * not, so nothing stopped the next draw. Three green sweeps in a row had
     * already run before the fourth caught it.
     *
     * The clear then goes in its own command rather than riding inside
     * run_copy, where a worker would have cleared rows its neighbours were
     * still sampling. A barrier inside a command is the shape PLAN C0 removed
     * and is not coming back.
     *
     * An unfiltered, unscaled copy reads only rows the worker wrote itself, so
     * it keeps the fused clear and its exact previous behaviour. */
    if (foreign) {
        gxr_flush();
        if (v & 0x800u) {
            D = &g_queue[g_published & QMASK];
            D->seq = g_published;
            D->kind = 2; D->s = s;
            D->cp_v = v; D->cp_tl = bp[0x49]; D->cp_wh = bp[0x4A];
            D->cp_ar = bp[0x4F]; D->cp_gb = bp[0x50]; D->cp_z = bp[0x51];
            if (g_workers > 0) {
                InterlockedIncrement64(&g_published);
            } else {
                t_tid = 1;
                TIMED(T_RASTER, draw_command(D));
                InterlockedIncrement64(&g_published);
                g_drained = g_published;
                g_arena_used = 0;
            }
        }
    }

    if (to_screen) {
        char path[512];
        int want = 0;
        unsigned frame = gx_frame_count(); /* the front end increments it after this copy, so this is the frame being presented */
        if (g_png_path[0]) { snprintf(path, sizeof path, "%s", g_png_path); want = 1; }
        else if (g_snap_every && (frame % g_snap_every) == 0) { ensure_frames_dir(); snprintf(path, sizeof path, "build/frames/%04u.png", frame); want = 1; }
        /* The PNG and the hash both describe the finished frame, so wait here
         * for the rows of this copy every other worker owns. The hash is taken
         * from the same buffer the PNG is written from and at the same point,
         * so it does not depend on whether a PNG is being written. */
        if (want || g_hash) gxr_flush();
        if (want) TIMED(T_PNG, write_frame_png(path, g_screen_w, g_screen_h));
        /* One line per presented frame, for a tool to diff between runs:
         * "[gxr] frame <n> <w>x<h> hash <16 hex digits>". Note that SOA_SNAP
         * skips rasterizing the frames it is not writing, so in that mode only
         * the frames that get a PNG have a hash worth comparing. */
        if (g_hash)
            fprintf(stderr, "[gxr] frame %u %dx%d hash %016llx\n", frame, g_screen_w, g_screen_h,
                    (unsigned long long)gxr_screen_hash());
    }
}

void gxr_bp_written(CpuState* s, uint32_t reg, uint32_t v)
{
    const uint32_t* bp = gx_bp_regs();
    /* Only when there is a picture to be wrong: with the renderer off nothing
     * is drawn, so nothing is drawn wrong. */
    if (gxr_enabled()) bp_tripwire(bp, reg, v);
    if (reg >= 0xE0 && reg <= 0xE7) { tev_register_written(reg, v); return; }
    if (reg == 0x65) { /* TLUT load (GXLoadTlut): source from 0x64, tmem address and size here */
        uint32_t src = (bp[0x64] & 0x1FFFFFu) << 5;
        uint32_t tmem = (v & 0x3FFu) << 9, bytes = ((v >> 10) & 0x7FFu) << 5;
        tmem_load_tlut(s, src | 0x80000000u, tmem, bytes);
        return;
    }
    if (reg == 0x52 && gxr_enabled()) { /* EFB copy (GXCopyTex / GXCopyDisp) */
        TIMED(T_COPY, enqueue_copy(s, bp, v));
        return;
    }
    if (reg == 0x45 && (v & 2) && gxr_enabled()) gxr_flush(); /* GXDrawDone: the CPU may read results now */
}

/* Defined in gxr_tev.c. A diagnostic for the report below rather than part of
 * the renderer's interface, so it is declared here and not in gxr.h. */
int tex_graveyard_peak(void);

void gxr_report(void)
{
    /* No flush: the watchdog thread reports while the main thread produces,
     * so every number below is read while its writer may still be moving it.
     * Each one has a single writer and 64-bit alignment, so a read is a value
     * and not a tear; what it is not is a consistent instant, and the
     * workers' unaccounted share below is where that shows. */
    if (!gxr_enabled()) return;
    gxr_timing_finish();
    {
        double span = gxr_producer_span(), rest;
        uint64_t sum = 0;
        int i;
        for (i = 1; i < T_COUNT; i++) sum += g_gxr_ticks[i];
        rest = span - gxr_seconds(sum);
        if (rest < 0.0) rest = 0.0;
        if (span <= 0.0)
            fprintf(stderr, "[gxr] time: %s\n",
                    g_gxr_tsc < 0 ? "nothing was drawn this run, so nothing was timed"
                                  : "this build has no clock, so every phase timer reads zero");
        else
            fprintf(stderr,
                    "[gxr] producer over %.2fs by the %s: setup %.2fs, prepare %.2fs, decode %.2fs, copy %.2fs, png %.2fs, wait %.2fs, raster %.2fs; the other %.2fs is guest code and the command-stream parse, which no clock can afford to separate and the profile below separates by sampling. These are disjoint, so they add up.\n",
                    span, g_gxr_tsc ? "time-stamp counter" : "performance counter",
                    gxr_seconds(g_gxr_ticks[T_SETUP]), gxr_seconds(g_gxr_ticks[T_PREPARE]),
                    gxr_seconds(g_gxr_ticks[T_DECODE]), gxr_seconds(g_gxr_ticks[T_COPY]),
                    gxr_seconds(g_gxr_ticks[T_PNG]), gxr_seconds(g_gxr_ticks[T_WAIT]),
                    gxr_seconds(g_gxr_ticks[T_RASTER]), rest);
    }
    /* The identity the plan asks for: a worker is either running a command or
     * spinning for one, so the two add up to the pool's span times the number
     * of threads. What is left over is each thread's open stretch when this
     * was printed, bounded by one command or one backoff -- so a run that
     * reports more than a few percent has a worker stuck inside a command. */
    if (g_workers > 0 && g_pool_t0 && gxr_producer_span() > 0.0) {
        double pool = gxr_seconds(gxr_ticks() - g_pool_t0), busy = 0.0, idle = 0.0, thread_time;
        int i;
        for (i = 1; i <= g_workers; i++) {
            busy += gxr_seconds(g_ts[i].busy);
            idle += gxr_seconds(g_ts[i].idle);
        }
        thread_time = pool * g_workers;
        fprintf(stderr, "[gxr] workers: %d threads, pool up %.2fs each = %.2fs of thread time; busy %.2fs + idle %.2fs = %.2fs, %.1f%% unaccounted\n",
                g_workers, pool, thread_time, busy, idle, busy + idle,
                thread_time > 0.0 ? 100.0 * (thread_time - busy - idle) / thread_time : 0.0);
    }
    {
        uint64_t px = 0, rd = 0, ra = 0;
        int i;
        for (i = 0; i <= MAX_THREADS; i++) { px += g_ts[i].pixels; rd += g_ts[i].rej_depth; ra += g_ts[i].rej_alpha; }
    fprintf(stderr, "[gxr] %llu triangles, %llu lines, %llu points; %llu pixels shaded (%llu outside, %llu failed alpha, %llu failed depth); %llu clipped away; %llu bad vertex refs; %llu texture copies, %llu screen copies\n",
            (unsigned long long)g_tris, (unsigned long long)g_lines, (unsigned long long)g_points,
            (unsigned long long)px, (unsigned long long)g_rej_bary, (unsigned long long)ra, (unsigned long long)rd, (unsigned long long)g_clipped, (unsigned long long)g_verts_bad,
            (unsigned long long)g_copies_tex, (unsigned long long)g_copies_xfb);
    }
    /* Two facts about lifetimes, stated when they happened at all, because
     * between them they say whether a run took the paths the queue's rules are
     * there for. The first is the only moment the renderer's own state moves
     * under a draw that is being built; the second is how far past a fixed
     * graveyard of 512 this run went, and every texture past that one is one
     * that would have been handed back to the allocator with queued draws
     * still pointing at it. */
    if (g_prepare_flushes)
        fprintf(stderr, "[gxr] %llu draws sampled a texture a queued copy had not written yet, and waited for it in the middle of their setup\n",
                (unsigned long long)g_prepare_flushes);
    if (tex_graveyard_peak())
        fprintf(stderr, "[gxr] %d decoded textures waited to be freed at once, at the most\n", tex_graveyard_peak());
}
