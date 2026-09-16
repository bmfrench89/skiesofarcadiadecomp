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

/* TEV / textures (gxr_tev.c) */
void tev_pixel(const uint32_t* bp, const Color4 ras[2], const float tex[8][3], uint8_t out[4], int* alpha_pass);
void tev_register_written(uint32_t reg, uint32_t v);
void tex_invalidate_all(void);
void tex_set_memory(CpuState* s);
void tmem_load_tlut(CpuState* s, uint32_t src, uint32_t tmem_off, uint32_t bytes);

extern uint8_t g_efb[EFB_H][EFB_W][4];
extern uint32_t g_efb_z[EFB_H][EFB_W];

int png_write_rgba(const char* path, const uint8_t* rgba, int w, int h, int stride);
