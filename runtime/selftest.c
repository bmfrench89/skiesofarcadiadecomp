/*
 * Call recompiled library functions directly, outside the game's control
 * flow, and check what they produce. SOA_SELFTEST=1 runs these instead of
 * the game: a wrong answer here is a translation bug with a tiny repro.
 *
 * The C library is position-independent enough for this -- sprintf needs
 * nothing but the small-data bases the startup code sets in r2 and r13.
 */
#include "cpu.h"
#include "gxr.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

uint8_t* aram_memory(void);
int device_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out);
void device_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v);

#define SCRATCH 0x81000000u /* above the arena; nothing else is there yet */
#define SDA2_BASE 0x80350000u
#define SDA_BASE 0x8034E720u
#define STACK_TOP 0x8035D4C8u

static void put_string(CpuState* s, uint32_t addr, const char* text)
{
    size_t i;
    for (i = 0; i <= strlen(text); i++) mem_w8(s, addr + (uint32_t)i, (uint8_t)text[i]);
}

static void get_string(CpuState* s, uint32_t addr, char* out, size_t cap)
{
    size_t i;
    for (i = 0; i + 1 < cap; i++) {
        out[i] = (char)mem_r8(s, addr + (uint32_t)i);
        if (!out[i]) return;
    }
    out[i] = 0;
}

static void call(CpuState* s, uint32_t fn)
{
    s->gpr[1] = STACK_TOP - 0x400;
    s->gpr[2] = SDA2_BASE;
    s->gpr[13] = SDA_BASE;
    s->lr = 0;
    s->cr = 0; /* CR bit 6 clear: no floating-point varargs */
    s->msr = 0x00002030u;
    dispatch(s, fn);
}

static int check(const char* what, const char* got, const char* want)
{
    int ok = strcmp(got, want) == 0;
    fprintf(stderr, "[selftest] %-28s %s  got \"%s\"%s%s%s\n", what, ok ? "ok  " : "FAIL", got,
            ok ? "" : " want \"", ok ? "" : want, ok ? "" : "\"");
    return !ok;
}

/* ---- the software renderer, through the real GX pipe --------------------
 * The register recipe is the one the game uses for its full-screen fades
 * (orthographic, 640x480, one colour channel from the vertex), so this also
 * pins down the command encodings the front end parses. */
static void gp8(CpuState* s, unsigned v) { gx_pipe_write(s, 1, v); }
static void gp16(CpuState* s, unsigned v) { gx_pipe_write(s, 2, v); }
static void gp32(CpuState* s, uint32_t v) { gx_pipe_write(s, 4, v); }
static void gpf(CpuState* s, float f) { uint32_t u; memcpy(&u, &f, 4); gp32(s, u); }
static void bp_w(CpuState* s, unsigned reg, uint32_t v) { gp8(s, 0x61); gp32(s, ((uint32_t)reg << 24) | (v & 0xFFFFFFu)); }
static void cp_w(CpuState* s, unsigned reg, uint32_t v) { gp8(s, 0x08); gp8(s, reg); gp32(s, v); }
static void xf_w(CpuState* s, unsigned addr, unsigned n, const uint32_t* w)
{
    unsigned i;
    gp8(s, 0x10); gp16(s, n - 1); gp16(s, addr);
    for (i = 0; i < n; i++) gp32(s, w[i]);
}
static void xf_f(CpuState* s, unsigned addr, unsigned n, const float* f)
{
    unsigned i;
    gp8(s, 0x10); gp16(s, n - 1); gp16(s, addr);
    for (i = 0; i < n; i++) gpf(s, f[i]);
}
static void vertex(CpuState* s, float x, float y, float z, uint32_t rgba) { gpf(s, x); gpf(s, y); gpf(s, z); gp32(s, rgba); }

static void present(CpuState* s)
{
    bp_w(s, 0x49, 0); bp_w(s, 0x4A, 0x077E7F); bp_w(s, 0x4D, 0x28); bp_w(s, 0x4B, (0x81100000u & 0x1FFFFFFFu) >> 5);
    bp_w(s, 0x52, 0x4003); /* copy to the XFB: the frame is done */
    gxr_flush();
}

static unsigned count_color(const uint8_t* screen, int w, int h, uint8_t r, uint8_t g, uint8_t b)
{
    unsigned n = 0;
    int x, y;
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            const uint8_t* p = screen + ((size_t)y * EFB_W + x) * 4;
            if (p[0] == r && p[1] == g && p[2] == b) n++;
        }
    return n;
}

static int render_selftest(CpuState* s, char* got, size_t cap)
{
    static const float viewport[6] = {320.0f, -240.0f, 16777215.0f, 662.0f, 582.0f, 16777215.0f};
    static const float ortho[6] = {0.003125f, -0.0f, 0.004167f, -0.0f, -0.01f, -1.0f};
    static const float view[12] = {1, 0, 0, -320, 0, -1, 0, 240, 0, 0, 1, -100};
    static const uint32_t one = 1, matidx = 0x3CF3CF00u, chan = 0x441u, zero = 0;
    const uint8_t* screen;
    int w = 0, h = 0, failures = 0;

    _putenv("SOA_RENDER=1");
    _putenv("SOA_THREADS=1");
    if (!gxr_enabled()) { fprintf(stderr, "[selftest] renderer disabled; skipping render checks\n"); return 0; }
    gxr_reset_efb();

    bp_w(s, 0x59, 0x02ACABu); bp_w(s, 0x20, 0x156156u); bp_w(s, 0x21, 0x3D5335u); /* scissor: the full 640x480 */
    xf_f(s, 0x101A, 6, viewport);
    xf_f(s, 0x1020, 6, ortho); xf_w(s, 0x1026, 1, &one);
    xf_f(s, 0x0000, 12, view);
    cp_w(s, 0x30, matidx); xf_w(s, 0x1018, 1, &matidx);
    xf_w(s, 0x1009, 1, &one); xf_w(s, 0x100E, 1, &chan); xf_w(s, 0x1010, 1, &chan); xf_w(s, 0x103F, 1, &zero); xf_w(s, 0x1008, 1, &one);
    bp_w(s, 0x28, 0); bp_w(s, 0xC0, 0x08AFFFu); bp_w(s, 0xC1, 0x08BFF0u); bp_w(s, 0x00, 0x10);
    /* swap tables (GXSetTevSwapModeTable): identity for the rasterized and texture colours */
    bp_w(s, 0xF6, 0x018064u); bp_w(s, 0xF7, 0x01806Eu); bp_w(s, 0xF8, 0x018060u); bp_w(s, 0xF9, 0x01806Cu);
    bp_w(s, 0xFA, 0x018065u); bp_w(s, 0xFB, 0x01806Du); bp_w(s, 0xFC, 0x01806Au); bp_w(s, 0xFD, 0x01806Eu);
    bp_w(s, 0x40, 0x17); bp_w(s, 0x41, 0x18); bp_w(s, 0xF3, 0x3F0000u); bp_w(s, 0x43, 0x40);
    cp_w(s, 0x50, 0x2200); cp_w(s, 0x60, 0); cp_w(s, 0x70, 0x41377009u); cp_w(s, 0x80, 0xC8241209u); cp_w(s, 0x90, 0x04824120u);

    /* A full-screen red quad covers every pixel. */
    gp8(s, 0x80); gp16(s, 4);
    vertex(s, 0, 0, 50, 0xFF0000FFu); vertex(s, 640, 0, 50, 0xFF0000FFu);
    vertex(s, 640, 480, 50, 0xFF0000FFu); vertex(s, 0, 480, 50, 0xFF0000FFu);
    present(s);
    screen = gxr_screen(&w, &h);
    snprintf(got, cap, "%u of %d red", screen ? count_color(screen, w, h, 255, 0, 0) : 0u, w * h);
    failures += check("render full-screen quad", got, "307200 of 307200 red");

    /* The title screen's cloud triangle: (320.5,-22.1) (789.1,-22.1) (789.1,530.2).
     * Its top edge is off horizontal by a sub-pixel amount (as the perspective
     * divide leaves it): its x coefficient is a crumb, and the span code
     * once divided by it, overflowed the int conversion and dropped rows. The part
     * inside the screen is right of the diagonal, about 53,300 pixels. */
    gxr_reset_efb();
    gp8(s, 0x90); gp16(s, 3);
    vertex(s, 320.5f, -22.1f, 50, 0x00FF00FFu); vertex(s, 789.1f, -22.09999f, 50, 0x00FF00FFu); vertex(s, 789.1f, 530.2f, 50, 0x00FF00FFu);
    present(s);
    screen = gxr_screen(&w, &h);
    {
        unsigned green = screen ? count_color(screen, w, h, 0, 255, 0) : 0u;
#define G(x, y) (screen && screen[((size_t)(y) * EFB_W + (x)) * 4 + 1] == 255)
        int ok = green > 52000 && green < 54500 && G(600, 300) && G(630, 10) && G(500, 100) && !G(360, 60) && !G(600, 340) && !G(100, 200);
#undef G
        snprintf(got, cap, "%s, %u px", ok ? "complete" : "holes", green);
        failures += check("render triangle rows", got, ok ? got : "complete, ~53300 px");
    }
    return failures;
}

int selftest(CpuState* s)
{
    char got[256];
    int failures = 0;

    /* sprintf(buf, "%s.%s", "abc", "def") -- 0x8025CB24 */
    put_string(s, SCRATCH + 0x100, "%s.%s");
    put_string(s, SCRATCH + 0x200, "abc");
    put_string(s, SCRATCH + 0x300, "def");
    s->gpr[3] = SCRATCH;
    s->gpr[4] = SCRATCH + 0x100;
    s->gpr[5] = SCRATCH + 0x200;
    s->gpr[6] = SCRATCH + 0x300;
    call(s, 0x8025CB24u);
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("sprintf %s.%s", got, "abc.def");

    /* sprintf(buf, "%d|%5u|%-4x|%c|%08X", -42, 7, 255, 'Q', 0xBEEF) */
    put_string(s, SCRATCH + 0x100, "%d|%5u|%-4x|%c|%08X");
    s->gpr[3] = SCRATCH;
    s->gpr[4] = SCRATCH + 0x100;
    s->gpr[5] = (uint32_t)-42;
    s->gpr[6] = 7;
    s->gpr[7] = 255;
    s->gpr[8] = 'Q';
    s->gpr[9] = 0xBEEF;
    call(s, 0x8025CB24u);
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("sprintf integers", got, "-42|    7|ff  |Q|0000BEEF");

    /* sprintf(buf, "%s/%s%03d.%s", "title", "ts", 26, "mld") -- more than 4 args */
    put_string(s, SCRATCH + 0x100, "%s/%s%03d.%s");
    put_string(s, SCRATCH + 0x200, "title");
    put_string(s, SCRATCH + 0x300, "ts");
    put_string(s, SCRATCH + 0x400, "mld");
    s->gpr[3] = SCRATCH;
    s->gpr[4] = SCRATCH + 0x100;
    s->gpr[5] = SCRATCH + 0x200;
    s->gpr[6] = SCRATCH + 0x300;
    s->gpr[7] = 26;
    s->gpr[8] = SCRATCH + 0x400;
    call(s, 0x8025CB24u);
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("sprintf mixed", got, "title/ts026.mld");

    /* sprintf(buf, "%.2f|%g|%5.1f", 3.14159, 2.5, -0.75): the FPU and float varargs */
    put_string(s, SCRATCH + 0x100, "%.2f|%g|%5.1f");
    s->gpr[3] = SCRATCH;
    s->gpr[4] = SCRATCH + 0x100;
    s->fpr[1].ps0 = 3.14159; s->fpr[2].ps0 = 2.5; s->fpr[3].ps0 = -0.75;
    s->gpr[1] = STACK_TOP - 0x400; s->gpr[2] = SDA2_BASE; s->gpr[13] = SDA_BASE; s->lr = 0; s->msr = 0x00002030u;
    s->cr = 0x02000000u; /* CR bit 6: floating-point arguments present */
    dispatch(s, 0x8025CB24u);
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("sprintf floats", got, "3.14|2.5| -0.8");

    /* strcpy / strcat / strcmp / strlen / memset / memcpy */
    put_string(s, SCRATCH + 0x200, "alpha");
    put_string(s, SCRATCH + 0x300, "beta");
    s->gpr[3] = SCRATCH; s->gpr[4] = SCRATCH + 0x200;
    call(s, 0x8025F120u); /* strcpy */
    s->gpr[3] = SCRATCH; s->gpr[4] = SCRATCH + 0x300;
    call(s, 0x8025F0B0u); /* strcat */
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("strcpy+strcat", got, "alphabeta");
    s->gpr[3] = SCRATCH;
    call(s, 0x8025F1D8u); /* strlen */
    snprintf(got, sizeof got, "%u", s->gpr[3]);
    failures += check("strlen", got, "9");
    s->gpr[3] = SCRATCH; s->gpr[4] = SCRATCH + 0x200;
    call(s, 0x8025EF88u); /* strcmp("alphabeta", "alpha") > 0 */
    snprintf(got, sizeof got, "%s", (int32_t)s->gpr[3] > 0 ? "positive" : "other");
    failures += check("strcmp", got, "positive");
    s->gpr[3] = SCRATCH + 0x400; s->gpr[4] = 0x41; s->gpr[5] = 37;
    call(s, 0x80005434u); /* memset 37 bytes of 'A' */
    mem_w8(s, SCRATCH + 0x400 + 37, 0);
    get_string(s, SCRATCH + 0x400, got, sizeof got);
    failures += check("memset", got, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
    s->gpr[3] = SCRATCH + 0x500 + 3; s->gpr[4] = SCRATCH; s->gpr[5] = 10; /* unaligned memcpy incl. the NUL */
    call(s, 0x80005520u);
    get_string(s, SCRATCH + 0x503, got, sizeof got);
    failures += check("memcpy unaligned", got, "alphabeta");

    /* ARAM DMA: the SDK's ARStartDMA writes the direction into CNT_H, reads CNT_H back to
     * merge the length's high bits, then writes CNT_L. The direction must survive that. */
    {
        uint64_t v = 0;
        uint8_t* ar = aram_memory();
        memset(ar + 0x10000, 0x5A, 64);
        mem_w32(s, SCRATCH + 0x600, 0);
        device_write(s, 0xCC005020u, 2, (SCRATCH + 0x600) >> 16);
        device_write(s, 0xCC005022u, 2, (SCRATCH + 0x600) & 0xFFFFu);
        device_write(s, 0xCC005024u, 2, 0x10000u >> 16);
        device_write(s, 0xCC005026u, 2, 0);
        device_write(s, 0xCC005028u, 2, 0x8000u); /* ARAM to main memory */
        device_read(s, 0xCC005028u, 2, &v);
        device_write(s, 0xCC005028u, 2, (v & ~0x3FFull) | 0u);
        device_write(s, 0xCC00502Au, 2, 64);
        snprintf(got, sizeof got, "%08X", mem_r32(s, SCRATCH + 0x600));
        failures += check("ARAM DMA to main memory", got, "5A5A5A5A");
        mem_w32(s, SCRATCH + 0x600, 0xC0FFEE11u);
        device_write(s, 0xCC005024u, 2, 0x10040u >> 16);
        device_write(s, 0xCC005026u, 2, 0x10040u & 0xFFFFu);
        device_write(s, 0xCC005028u, 2, 0); /* main memory to ARAM */
        device_read(s, 0xCC005028u, 2, &v);
        device_write(s, 0xCC005028u, 2, (v & ~0x3FFull) | 0u);
        device_write(s, 0xCC00502Au, 2, 64);
        snprintf(got, sizeof got, "%02X%02X%02X%02X", ar[0x10040], ar[0x10041], ar[0x10042], ar[0x10043]);
        failures += check("ARAM DMA from main memory", got, "C0FFEE11");
    }

    failures += render_selftest(s, got, sizeof got);

    fprintf(stderr, "[selftest] %d failure(s)\n", failures);
    return failures;
}
