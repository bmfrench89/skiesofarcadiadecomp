/*
 * Software GX: the graphics pipeline in C, driven by the command stream the
 * front end (gx.c) parses. Register numbers follow the hardware; comments
 * name the SDK call that writes each one.
 */
#pragma once
#include "cpu.h"

#define EFB_W 640
#define EFB_H 528

typedef struct {
    float r, g, b, a;
} Color4;

/* One vertex after the transform unit. */
typedef struct {
    float x, y, z, w;   /* clip space */
    float sx, sy;       /* EFB position */
    float depth;        /* 0..1 -> 24-bit z */
    Color4 col[2];      /* lit channel colors, 0..1 */
    float tex[8][3];    /* s, t, q */
} Vertex;

/* Front end (gx.c) */
const uint32_t* gx_cp_regs(void);
const uint32_t* gx_xf_regs(void);
const uint32_t* gx_bp_regs(void);

/* Pipeline (gxr.c) */
void gxr_draw(CpuState* s, unsigned op, unsigned count, const uint8_t* verts, unsigned vsize);
void gxr_bp_written(CpuState* s, uint32_t reg, uint32_t value);
int gxr_enabled(void);
void gxr_enable(int on);
void gxr_set_output(const char* png_path);
void gxr_report(void);
void gxr_reset_efb(void);
void gxr_flush(void);
void gxr_texture_hazard(uint32_t addr, uint32_t bytes); /* flush if a queued copy writes there */
const uint8_t* gxr_screen(int* w, int* h);           /* the last frame copied out (RGBA, EFB_W stride) */

/* TEV / textures (gxr_tev.c) */

/* Per-pixel input bank: 0-15 the four colour registers (r,g,b,a each),
 * 16-19 texture colour, 20-23 rasterized colour, 24-27 konst, 28 one,
 * 29 half, 30 zero. Selectors resolve to bank indices once per draw. */
#define BANK_TEX 16
#define BANK_RAS 20
#define BANK_KONST 24
#define BANK_ONE 28
#define BANK_HALF 29
#define BANK_ZERO 30
#define BANK_SIZE 32

typedef struct {
    uint8_t texmap, texcoord, texen, chan;
    uint8_t rswap[4], tswap[4];
    uint8_t ca, cb, cc, cd, aa, ab, ac, ad;
    uint8_t cbias, cop, cclamp, cshift, cdest;
    uint8_t abias, aop, aclamp, ashift, adest;
    int konst[4];
    uint8_t ia[3], ib[3], ic[3], id[3]; /* colour input bank indices per channel */
    uint8_t ja, jb, jc, jd;             /* alpha input bank indices */
} Stage;

#define MAX_MIPS 11

typedef struct {
    const uint8_t* level[MAX_MIPS]; /* decoded RGBA per mip level; level[0] NULL = unused */
    int lw[MAX_MIPS], lh[MAX_MIPS];
    int nlevels;
    int w, h;
    unsigned wrap_s, wrap_t;
    int linear, mip;        /* bilinear within a level; pick a level by lod */
    float lod_bias, min_lod, max_lod;
    float scale_s, scale_t;
} TexCfg;

typedef struct {
    unsigned stages;
    Stage st[16];
    TexCfg tex[8];
    unsigned used_tex;   /* bit per texcoord slot read by an enabled stage */
    unsigned used_chan;  /* bit per rasterized channel read */
    int aref0, aref1;
    unsigned acomp0, acomp1, alogic;
    int reg_init[4][4];
} TevSetup;

void tev_prepare(const uint32_t* bp, TevSetup* out);
void tev_pixel(const TevSetup* T, const int ras[2][4], const float tex[8][4], uint8_t out[4], int* alpha_pass);
void tev_register_written(uint32_t reg, uint32_t v);
void tex_invalidate_all(void);
void tex_graveyard_empty(void); /* frees textures no queued draw can reference any more */
int tex_graveyard_full(void);
void tex_set_memory(CpuState* s);
void tmem_load_tlut(CpuState* s, uint32_t src, uint32_t tmem_off, uint32_t bytes);

extern uint8_t g_efb[EFB_H][EFB_W][4];
extern uint32_t g_efb_z[EFB_H][EFB_W];

int png_write_rgba(const char* path, const uint8_t* rgba, int w, int h, int stride);

/* Phase timers (QueryPerformanceCounter ticks), reported by gxr_report. */
typedef enum { T_DRAW, T_DECODE, T_COPY, T_PNG, T_PREPARE, T_COUNT } GxrTimer;
extern double g_gxr_time[T_COUNT];
double gxr_clock(void);
#define TIMED(which, stmt) do { double _t0 = gxr_clock(); stmt; g_gxr_time[which] += gxr_clock() - _t0; } while (0)
