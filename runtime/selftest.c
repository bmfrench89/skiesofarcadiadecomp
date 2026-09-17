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
#include <time.h>

uint8_t* aram_memory(void);
int device_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out);
void device_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v);
unsigned exi_exi_irq_pending(void);
int exi_card_loaded(void);
void exi_card_reset(void);
void exi_card_counters(uint64_t* reads, uint64_t* writes, uint64_t* ints);
/* irq.c: the slot the delivery path reads a handler out of, how many
 * deliveries each interrupt number has had, and the idle-loop hook that is
 * the port's one delivery point. */
uint32_t irq_handler_slot(CpuState* s, unsigned irq);
uint64_t irq_delivered_count(unsigned number);
void hook_80237BA8(CpuState* s);

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
    _putenv("SOA_SNAP="); /* a snapshot interval left in the environment would skip the one frame this draws */
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

/* ---- the memory card, through the EXI registers -------------------------
 * Shaped like the ARAM round-trip further down: drive the device model the
 * way the CARD library drives it and check what comes back. Every command the
 * library sends is here -- device ID, read status, set interrupt, clear
 * status, sector erase, page program and read array -- together with the
 * interrupt each write ends with and the SRAM the mount checksums, because a
 * card that answers most of those and gets one wrong is a game that quietly
 * never saves, which is what every log so far has shown.
 *
 * It runs first, on an image of its own: the flash ID the runtime presents in
 * SRAM is recovered from the card image the first time anything reads SRAM,
 * so the image has to be shaped before that happens. It is written below the
 * render checks rather than above them because tools/citest/render_driver.c
 * copies check() and the render section as one block, which is the only way
 * CI can run them. */
#define EXI0_CSR 0xCC006800u
#define EXI0_MAR 0xCC006804u
#define EXI0_LEN 0xCC006808u
#define EXI0_CR 0xCC00680Cu
#define EXI0_DATA 0xCC006810u
#define EXIINTMSK 0x0001u
#define EXIINT 0x0002u
#define CARD_IMAGE "build/cards/selftest.raw"
/* EXIIntrruptHandler: the handler EXIInit registers for interrupts 9, 12 and
 * 15. It recovers its channel as (number - 9) / 3, clears the channel's EXIINT
 * and calls the channel's EXI callback if one is set -- none is here, so it is
 * the bit-clearing half alone. */
#define EXI_HANDLER 0x802643B8u
/* The traffic the checks below add up to: six 512-byte read-array transfers
 * and one 32-byte read that starts inside the latency, ten 128-byte page
 * programs, and one interrupt for each program or erase the card was allowed
 * to raise one for. */
#define CARD_READS 3100u
#define CARD_WRITES 1280u
#define CARD_INTS 6u

/* EXISelect keeps the three mask bits and sets one chip select; EXIDeselect
 * clears the selects and leaves the masks. Neither writes a one to a
 * write-one-to-clear bit, which is why a latched interrupt survives both. */
static void exi_select(CpuState* s, int dev)
{
    device_write(s, EXI0_CSR, 4, EXIINTMSK | (uint64_t)(0x80u << dev));
}

static void exi_deselect(CpuState* s)
{
    device_write(s, EXI0_CSR, 4, EXIINTMSK);
}

static uint32_t exi_csr(CpuState* s)
{
    uint64_t v = 0;
    device_read(s, EXI0_CSR, 4, &v);
    return (uint32_t)v;
}

static uint32_t exi_imm(CpuState* s, uint32_t data, unsigned len, unsigned type)
{
    uint64_t v = 0;
    device_write(s, EXI0_DATA, 4, data);
    device_write(s, EXI0_CR, 4, 1u | (type << 2) | ((len - 1) << 4));
    device_read(s, EXI0_DATA, 4, &v);
    return (uint32_t)v;
}

static void exi_dma(CpuState* s, uint32_t mar, uint32_t len, unsigned type)
{
    device_write(s, EXI0_MAR, 4, mar);
    device_write(s, EXI0_LEN, 4, len);
    device_write(s, EXI0_CR, 4, 1u | 2u | (type << 2));
}

/* The five-byte address commands, split four and one the way EXIImmEx splits
 * them: the byte position has to carry across the two transfers. */
static void card_addr_cmd(CpuState* s, uint8_t op, uint32_t addr)
{
    exi_imm(s,
            ((uint32_t)op << 24) | (((addr >> 17) & 0x7F) << 16) | (((addr >> 9) & 0xFF) << 8) | ((addr >> 7) & 3), 4,
            1);
    exi_imm(s, (addr & 0x7F) << 24, 1, 1);
}

static void card_erase(CpuState* s, uint32_t addr)
{
    exi_select(s, 0);
    exi_imm(s, 0xF1000000u | (((addr >> 17) & 0x7F) << 16) | (((addr >> 9) & 0xFF) << 8), 3, 1);
    exi_deselect(s);
}

static void card_program(CpuState* s, uint32_t addr, uint32_t src)
{
    exi_select(s, 0);
    card_addr_cmd(s, 0xF2, addr);
    exi_dma(s, src, 128, 1);
    exi_deselect(s);
}

static void card_read(CpuState* s, uint32_t addr, uint32_t dst, uint32_t len)
{
    exi_select(s, 0);
    card_addr_cmd(s, 0x52, addr);
    exi_imm(s, 0, 4, 1); /* the four dummy bytes the ID's latency field asks for */
    exi_dma(s, dst, len, 0);
    exi_deselect(s);
}

/* What __CARDExiHandler does with the interrupt, in its order: clear the CSR
 * bit, then re-select the card to read status and acknowledge it. The card is
 * still asserting for the whole of that -- it only lets go at the
 * acknowledge -- so `midway', read between the two, is the moment that tells
 * a latched interrupt from a level-sensitive one. It must be 0: a runtime
 * that re-derives the bit from the card's line, or re-arms on the deselect
 * that ends the status read, sends the handler round again for ever. */
static uint8_t card_handle_interrupt(CpuState* s, unsigned* midway)
{
    uint8_t status;
    device_write(s, EXI0_CSR, 4, (exi_csr(s) & 0x07F5u) | EXIINT);
    exi_select(s, 0);
    exi_imm(s, 0x83000000u, 2, 1);
    status = (uint8_t)(exi_imm(s, 0, 1, 0) >> 24);
    exi_deselect(s);
    *midway = ((exi_csr(s) & EXIINT) ? 1u : 0u) | ((exi_exi_irq_pending() & 1u) << 1);
    exi_select(s, 0);
    exi_imm(s, 0x89000000u, 1, 1);
    exi_deselect(s);
    return status;
}

/* __CARDCheckSum: a u16 sum and a u16 sum of complements, 0xFFFF folded to 0.
 * Written out again here rather than shared with the runtime, so the two have
 * to agree rather than being wrong together. */
static void card_sum(const uint8_t* p, unsigned bytes, unsigned* sum, unsigned* inv)
{
    unsigned i, s = 0, v = 0;
    for (i = 0; i < bytes; i += 2) {
        unsigned w = ((unsigned)p[i] << 8) | p[i + 1];
        s += w;
        v += (unsigned)(uint16_t)~w;
    }
    *sum = s & 0xFFFFu;
    *inv = v & 0xFFFFu;
    if (*sum == 0xFFFFu) *sum = 0;
    if (*inv == 0xFFFFu) *inv = 0;
}

static int64_t card_rand(int64_t r)
{
    return ((int64_t)((uint64_t)r * 0x41C64E6Du + 12345u)) >> 16;
}

static int card_selftest(CpuState* s, char* got, size_t cap)
{
    /* Any twelve bytes: what matters is that the runtime gives these back. */
    static const uint8_t flash[12] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC};
    const uint32_t SRC = SCRATCH + 0x2000, DST = SCRATCH + 0x3000, SRB = SCRATCH + 0x4000;
    const uint32_t sector = 0x2000, page = sector + 0x100;
    uint8_t id_block[512], sram[64], when[8];
    uint64_t reads, writes, ints, before;
    char want[128];
    FILE* stale;
    int failures = 0, i, bad;
    unsigned sum, inv, midway;
    int64_t rand;
    uint32_t id, stamp;

    /* Redirecting SOA_CARD works only while no card has been opened, because
     * card_load caches the path on first use. Nothing before this point in
     * main() touches EXI today; the day something does, this says so instead
     * of quietly erasing and reformatting whatever card the run was using. */
    if (exi_card_loaded()) {
        failures += check("card untouched at entry", "a card is already open", "nothing opened yet");
        return failures;
    }
    _putenv("SOA_CARD=" CARD_IMAGE);

    /* The checks below describe a card nobody has written, so the image from
     * the last run has to be gone. If it is not -- a stale handle, a
     * read-only file -- every check still passes against those old bytes and
     * the run proves nothing, so fail here instead. */
    remove(CARD_IMAGE);
    stale = fopen(CARD_IMAGE, "rb");
    if (stale) fclose(stale);
    snprintf(got, cap, "%s", stale ? "still there" : "gone");
    failures += check("card image starts absent", got, "gone");

    /* And the image this run writes is not the image the last one wrote: the
     * format time seeds the scrambled serial, so every byte of the ID block
     * downstream of it differs run to run. A check that reads back what a
     * previous run left behind then fails rather than passing. */
    stamp = (uint32_t)time(NULL) ^ (uint32_t)clock();
    memset(when, 0, sizeof when);
    when[4] = (uint8_t)(stamp >> 24); when[5] = (uint8_t)(stamp >> 16);
    when[6] = (uint8_t)(stamp >> 8); when[7] = (uint8_t)stamp;

    /* EXIGetID writes two command bytes and then reads four, so the ID has to
     * land at transaction positions 2 to 5. CARDIsCard reads 0x00000004 as
     * 4 Mbit, 8 KB sectors and four dummy bytes before read data -- the only
     * value the rest of this device model is consistent with. */
    exi_select(s, 0);
    exi_imm(s, 0, 2, 1);
    id = exi_imm(s, 0, 4, 0);
    exi_deselect(s);
    snprintf(got, cap, "%08X", id);
    failures += check("card device ID", got, "00000004");

    exi_select(s, 0);
    exi_imm(s, 0x83000000u, 2, 1);
    snprintf(got, cap, "%02X", (unsigned)(exi_imm(s, 0, 1, 0) >> 24));
    exi_deselect(s);
    failures += check("card read status", got, "41"); /* ready, and unlocked */

    /* An ID block as __CARDFormatRegionAsync writes one: the flash ID with
     * successive values of the scrambling sequence added to it, seeded from
     * the format time, and the block's own checksum pair at 508 and 510. */
    memset(id_block, 0xFF, sizeof id_block);
    memcpy(id_block + 12, when, sizeof when);
    rand = 0;
    for (i = 0; i < 8; i++) rand = (rand << 8) | when[i];
    for (i = 0; i < 12; i++) {
        rand = card_rand(rand);
        id_block[i] = (uint8_t)(flash[i] + (uint8_t)rand);
        rand = card_rand(rand) & 0x7FFF;
    }
    id_block[32] = id_block[33] = 0; /* deviceID */
    id_block[34] = 0; id_block[35] = 4; /* size, in Mbit */
    /* encode: CARDVerifyID compares it against the font encoding CARDInit
     * cached, and returns ENCODING otherwise. OSGetFontEncode answers 0 for a
     * US NTSC console, so the block this builds is one the mount would take
     * rather than one shaped only well enough for the device model. */
    id_block[36] = id_block[37] = 0;
    card_sum(id_block, 508, &sum, &inv);
    id_block[508] = (uint8_t)(sum >> 8); id_block[509] = (uint8_t)sum;
    id_block[510] = (uint8_t)(inv >> 8); id_block[511] = (uint8_t)inv;

    card_erase(s, 0);
    for (i = 0; i < 4; i++) {
        int j;
        for (j = 0; j < 128; j++) mem_w8(s, SRC + (uint32_t)j, id_block[i * 128 + j]);
        card_program(s, (uint32_t)i * 128, SRC);
    }
    card_read(s, 0, DST, 512);
    for (bad = -1, i = 0; i < 512 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != id_block[i]) bad = i;
    if (bad < 0) snprintf(got, cap, "512 bytes match");
    else snprintf(got, cap, "byte %d differs", bad);
    failures += check("card program and read back", got, "512 bytes match");

    /* A DMA is not a second way into the card but the same byte stream the
     * immediate bytes that framed it belong to, and the device ID's latency
     * field says how far into that stream the read data starts: four bytes,
     * which is what __CARDReadSegment sends before its EXIDma. So a DMA that
     * arrives without them must see the latency first and the array after,
     * which is the only place the two halves of the model can be seen to
     * agree -- the game always sends the four, so they agree by accident
     * everywhere else. */
    exi_select(s, 0);
    card_addr_cmd(s, 0x52, 0);
    exi_dma(s, DST, 32, 0);
    exi_deselect(s);
    for (bad = -1, i = 0; i < 32 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != (i < 4 ? 0xFF : id_block[i - 4])) bad = i;
    snprintf(got, cap, "%s", bad < 0 ? "four dummy bytes, then the array" : "wrong");
    failures += check("read latency on the DMA path", got, "four dummy bytes, then the array");

    /* The first read of SRAM, and so the first chance the runtime has to
     * recover the flash ID from the image just written. An image formatted
     * anywhere else verifies only if it does. */
    exi_select(s, 1);
    exi_imm(s, 0x20000100u, 4, 1);
    exi_dma(s, SRB, 64, 0);
    exi_deselect(s);
    for (i = 0; i < 64; i++) sram[i] = mem_r8(s, SRB + (uint32_t)i);
    snprintf(got, cap, "%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X%02X", sram[20], sram[21], sram[22], sram[23],
             sram[24], sram[25], sram[26], sram[27], sram[28], sram[29], sram[30], sram[31]);
    failures += check("SRAM flash ID from image", got, "112233445566778899AABBCC");

    /* CARDDoMount sums those twelve bytes and compares the complement against
     * SRAM 58; a mismatch is IOERROR and the mount ends there. */
    for (sum = 0, i = 0; i < 12; i++) sum += sram[20 + i];
    snprintf(got, cap, "%02X", sram[58]);
    snprintf(want, sizeof want, "%02X", (unsigned)(uint8_t)~sum);
    failures += check("SRAM flash ID checksum", got, want);

    /* The OSSram checksum covers the four u16 at 12, 14, 16 and 18 and stops
     * short of the extended half; byte 19 is the flags OSGetSoundMode reads,
     * whose bit 2 is stereo. Both pin the layout the mount depends on. */
    for (sum = inv = 0, i = 12; i < 20; i += 2) {
        unsigned w = ((unsigned)sram[i] << 8) | sram[i + 1];
        sum += w;
        inv += (unsigned)(uint16_t)~w;
    }
    snprintf(got, cap, "%04X %04X %02X", ((unsigned)sram[0] << 8) | sram[1], ((unsigned)sram[2] << 8) | sram[3],
             sram[19]);
    snprintf(want, sizeof want, "%04X %04X 04", sum & 0xFFFFu, inv & 0xFFFFu);
    failures += check("SRAM checksum and flags", got, want);

    /* The command's offset field names where the payload starts: every write
     * the game makes to the extended half goes through __OSUnlockSramEx,
     * which commits from offset 20. SRAM 56 is the DVD error code, which
     * nothing here reads back. */
    exi_select(s, 1);
    exi_imm(s, 0xA0000100u + (56u << 6), 4, 1); /* UnlockSram adds, and must: the */
    exi_imm(s, 0x5A000000u, 1, 1);              /* shifted offset overlaps the base */
    exi_deselect(s);
    exi_select(s, 1);
    exi_imm(s, 0x20000100u + (20u << 6), 4, 1);
    id = exi_imm(s, 0, 4, 0);
    exi_deselect(s);
    exi_select(s, 1);
    exi_imm(s, 0x20000100u, 4, 1);
    exi_dma(s, SRB, 64, 0);
    exi_deselect(s);
    for (bad = -1, i = 0; i < 64 && bad < 0; i++)
        if (i != 56 && mem_r8(s, SRB + (uint32_t)i) != sram[i]) bad = i;
    snprintf(got, cap, "%02X %08X %s", mem_r8(s, SRB + 56), id, bad < 0 ? "in place" : "moved");
    failures += check("SRAM write and read at offset", got, "5A 11223344 in place");

    /* The same device by DMA, both ways. __OSInitSram reads the 64 bytes by
     * DMA and UnlockSram commits them by immediate, so the write direction has
     * no user in the game today -- but a DMA the device dropped would still
     * clear TSTART and set TCINT, so EXISync and the transfer-complete handler
     * would both report success and the guest would never learn. That is the
     * path CARDDoMount writes the flash ID back through, and a silent drop
     * there looks exactly like the IOERROR the mount has never got past. The
     * bytes are slot B's flash ID and the wireless IDs, which nothing below
     * reads: SRAM is rebuilt from the image at the reload check. */
    for (i = 0; i < 32; i++) mem_w8(s, SRC + (uint32_t)i, (uint8_t)(0xE0 + i));
    exi_select(s, 1);
    exi_imm(s, 0xA0000100u + (32u << 6), 4, 1);
    exi_dma(s, SRC, 32, 1);
    exi_deselect(s);
    exi_select(s, 1);
    exi_imm(s, 0x20000100u + (32u << 6), 4, 1);
    exi_dma(s, DST, 32, 0);
    exi_deselect(s);
    for (bad = -1, i = 0; i < 32 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != (uint8_t)(0xE0 + i)) bad = i;
    snprintf(got, cap, "%s", bad < 0 ? "32 bytes in and back" : "wrong");
    failures += check("SRAM DMA both ways", got, "32 bytes in and back");

    /* The card's own interrupt. __CARDStart arms a 100 ms alarm, sends the
     * command and waits for the card to say it has finished; nothing raising
     * it means every write times out, which is why no log has a byte written. */
    exi_select(s, 0);
    exi_imm(s, 0x81010000u, 2, 1); /* __CARDEnableInterrupt(chan, TRUE) */
    exi_deselect(s);

    for (i = 0; i < 128; i++) mem_w8(s, SRC + (uint32_t)i, (uint8_t)(0xA0 + i));
    card_program(s, page, SRC);
    snprintf(got, cap, "csr %u pending %u", (exi_csr(s) & EXIINT) ? 1u : 0u, exi_exi_irq_pending() & 1u);
    failures += check("program raises the interrupt", got, "csr 1 pending 1");

    /* EXILock clears the enable for as long as the handler holds the channel:
     * a request already latched has to wait for the unlock, not vanish. */
    device_write(s, EXI0_CSR, 4, 0);
    snprintf(got, cap, "csr %u pending %u", (exi_csr(s) & EXIINT) ? 1u : 0u, exi_exi_irq_pending() & 1u);
    failures += check("masked interrupt waits", got, "csr 1 pending 0");

    /* Everything so far reads exi_exi_irq_pending(), which is the predicate
     * under test: it says the device model thinks an interrupt is due, not
     * that one reached the guest. irq.c is the other half of B2 and nothing
     * exercised it -- its whole EXI block could be deleted and every check
     * above would still pass. So install the handler EXIInit installs, in the
     * slots it installs it in, and run the idle-loop hook that is the port's
     * one delivery point. EXIIntrruptHandler is a real handler and clears the
     * CSR bit itself, so this also pins the write-one-to-clear arithmetic
     * against the guest's own code rather than against a second copy of it. */
    s->gpr[1] = STACK_TOP - 0x400; /* the handler has a frame; give it a stack */
    s->gpr[2] = SDA2_BASE;
    s->gpr[13] = SDA_BASE;
    for (i = 0; i < 32; i++) mem_w32(s, irq_handler_slot(s, (unsigned)i), 0);
    mem_w32(s, irq_handler_slot(s, 9), EXI_HANDLER);  /* channel 0 */
    mem_w32(s, irq_handler_slot(s, 12), EXI_HANDLER); /* channel 1 */
    mem_w32(s, irq_handler_slot(s, 15), EXI_HANDLER); /* channel 2 */
    before = irq_delivered_count(9);
    hook_80237BA8(s);
    snprintf(got, cap, "%llu", (unsigned long long)(irq_delivered_count(9) - before));
    failures += check("masked, nothing delivered", got, "0");

    device_write(s, EXI0_CSR, 4, EXIINTMSK);
    hook_80237BA8(s);
    snprintf(got, cap, "9:%llu 12:%llu 15:%llu csr %u",
             (unsigned long long)(irq_delivered_count(9) - before),
             (unsigned long long)irq_delivered_count(12), (unsigned long long)irq_delivered_count(15),
             (exi_csr(s) & EXIINT) ? 1u : 0u);
    failures += check("delivered to interrupt 9", got, "9:1 12:0 15:0 csr 0");

    /* The card is still holding its line -- only clear-status lets go -- so a
     * second pass must not find a second interrupt. A runtime that re-derived
     * the CSR bit from the line instead of latching it would loop here. */
    before = irq_delivered_count(9);
    hook_80237BA8(s);
    snprintf(got, cap, "%llu", (unsigned long long)(irq_delivered_count(9) - before));
    failures += check("cleared, nothing delivered", got, "0");

    sum = card_handle_interrupt(s, &midway);
    snprintf(got, cap, "%02X midway %u", sum, midway);
    failures += check("handler reads status", got, "41 midway 0");
    snprintf(got, cap, "csr %u pending %u", (exi_csr(s) & EXIINT) ? 1u : 0u, exi_exi_irq_pending() & 1u);
    failures += check("handler leaves it quiet", got, "csr 0 pending 0");

    card_read(s, sector, DST, 512);
    for (bad = -1, i = 0; i < 512 && bad < 0; i++) {
        uint8_t b = mem_r8(s, DST + (uint32_t)i);
        if (b != (i >= 0x100 && i < 0x180 ? (uint8_t)(0xA0 + i - 0x100) : 0xFF)) bad = i;
    }
    snprintf(got, cap, "%s", bad < 0 ? "one page in an erased sector" : "wrong");
    failures += check("programmed page reads back", got, "one page in an erased sector");

    /* Sector erase clears its own 8 KB and nothing else: the address names a
     * byte inside the sector, not the sector's start. */
    card_erase(s, page);
    snprintf(got, cap, "pending %u", exi_exi_irq_pending() & 1u);
    failures += check("erase raises the interrupt", got, "pending 1");
    card_handle_interrupt(s, &midway);
    snprintf(got, cap, "midway %u", midway);
    failures += check("erase handler sees a clear bit", got, "midway 0");
    card_read(s, sector, DST, 512);
    for (bad = -1, i = 0; i < 512 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != 0xFF) bad = i;
    card_read(s, 0, DST + 0x200, 512);
    for (i = 0; i < 512 && bad < 0; i++)
        if (mem_r8(s, DST + 0x200 + (uint32_t)i) != id_block[i]) bad = 0x1000 + i;
    snprintf(got, cap, "%s", bad < 0 ? "sector blank, ID block intact" : "wrong");
    failures += check("sector erase", got, "sector blank, ID block intact");

    /* A save is not one program but dozens: __CARDWrite walks a sector as 64
     * page programs, each one waiting on the interrupt the last one raised.
     * The card raises only while its previous request is unacknowledged, so
     * a round of the handler has to fall between them -- it does, because
     * __CARDClearStatus always precedes the next __CARDStart, but that is an
     * argument and this is the check. Four in a row, each with its own
     * interrupt and its own 128 bytes. */
    bad = -1;
    for (i = 0; i < 4; i++) {
        int j;
        for (j = 0; j < 128; j++) mem_w8(s, SRC + (uint32_t)j, (uint8_t)(0x10 * (i + 1) + j));
        card_program(s, sector + 0x800 + (uint32_t)i * 128, SRC);
        if (bad < 0 && !(exi_exi_irq_pending() & 1)) bad = i;
        card_handle_interrupt(s, &midway);
        if (bad < 0 && midway) bad = 0x10 + i;
    }
    card_read(s, sector + 0x800, DST, 512);
    for (i = 0; i < 512 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != (uint8_t)(0x10 * (i / 128 + 1) + i % 128)) bad = 0x100 + i;
    snprintf(got, cap, "%s", bad < 0 ? "four pages, four interrupts" : "wrong");
    failures += check("consecutive page programs", got, "four pages, four interrupts");

    /* With the interrupt turned off the card must not drive the line at all:
     * the mount only turns it on once, at its last step. */
    exi_select(s, 0);
    exi_imm(s, 0x81000000u, 2, 1); /* __CARDEnableInterrupt(chan, FALSE) */
    exi_deselect(s);
    card_program(s, sector + 0x400, SRC);
    snprintf(got, cap, "csr %u pending %u", (exi_csr(s) & EXIINT) ? 1u : 0u, exi_exi_irq_pending() & 1u);
    failures += check("disabled card stays quiet", got, "csr 0 pending 0");

    /* And the bytes are on disk already, not waiting for the run to end: a
     * save is dozens of page programs and a kill in the middle keeps what
     * landed. This also makes the directory, which nothing else creates. */
    {
        FILE* f = fopen(CARD_IMAGE, "rb");
        long size = 0;
        uint8_t head[2] = {0, 0};
        if (f) {
            fseek(f, 0, SEEK_END);
            size = ftell(f);
            fseek(f, 0, SEEK_SET);
            if (fread(head, 1, sizeof head, f) != sizeof head) size = -1;
            fclose(f);
        }
        snprintf(got, cap, "%ld bytes, %02X%02X", size, head[0], head[1]);
        snprintf(want, sizeof want, "524288 bytes, %02X%02X", id_block[0], id_block[1]);
        failures += check("card image flushed to disk", got, want);
    }

    /* Everything above ran against the buffer this run filled. An image the
     * game did not just write -- a Dolphin-formatted blank, which is how B4
     * means to get its first mount -- arrives through card_load's read path,
     * and nothing had ever taken it. Forget the card and read it back the way
     * the next boot would, SRAM included: the flash ID has to survive a
     * restart or the arrangement is no use. */
    exi_card_reset();
    card_read(s, 0, DST, 512);
    for (bad = -1, i = 0; i < 512 && bad < 0; i++)
        if (mem_r8(s, DST + (uint32_t)i) != id_block[i]) bad = i;
    exi_select(s, 1);
    exi_imm(s, 0x20000100u, 4, 1);
    exi_dma(s, SRB, 64, 0);
    exi_deselect(s);
    for (sum = 0, i = 0; i < 12; i++) sum += mem_r8(s, SRB + 20 + (uint32_t)i);
    snprintf(got, cap, "%s %02X%02X..%02X%02X %02X", bad < 0 ? "ID block" : "wrong",
             mem_r8(s, SRB + 20), mem_r8(s, SRB + 21), mem_r8(s, SRB + 30), mem_r8(s, SRB + 31),
             mem_r8(s, SRB + 58));
    snprintf(want, sizeof want, "ID block 1122..BBCC %02X", (unsigned)(uint8_t)~sum);
    failures += check("reloaded from disk", got, want);

    /* What the [exi] line at the end of a run prints. B2's own acceptance test
     * is a non-zero read count there, and until this nothing checked the
     * counters at all: a model that answered reads out of its buffer without
     * counting them would leave every log saying 0 bytes read. The numbers are
     * the bytes the checks above moved, so adding a check moves them. */
    exi_card_counters(&reads, &writes, &ints);
    snprintf(got, cap, "%llu read, %llu written, %llu interrupts", (unsigned long long)reads,
             (unsigned long long)writes, (unsigned long long)ints);
    snprintf(want, sizeof want, "%u read, %u written, %u interrupts", CARD_READS, CARD_WRITES, CARD_INTS);
    failures += check("card counters", got, want);
    return failures;
}

/* ---- decompiled functions against their recompiled twins ----------------
 * src/ is also compiled natively (every function renamed dc_<name>, see
 * tools/recompile.py). Each pair runs on the same bytes in guest memory: the
 * twin through dispatch() with guest addresses, the decompiled C on host
 * pointers into the same memory. Same answers on random inputs, or fail. */
size_t dc_strlen(const char* str);
char* dc_strchr(const char* str, int chr);
void* dc_memchr(const void* src, int val, size_t n);
void* dc___memrchr(const void* src, int val, size_t n);
int dc_strncmp(const char* a, const char* b, size_t n);
char* dc_strcat(char* dst, const char* src);
char* dc_strncpy(char* dst, const char* src, size_t n);
void* dc_memcpy(void* dst, const void* src, size_t n);
void* dc_memset(void* dst, int val, size_t n);

/* The recompiled twins, by name: dispatch() now reaches the adapters in
 * runtime/decomp_swap.c for these addresses (config/hle.txt). */
void recomp_fn_8025F1D8(CpuState* s); void recomp_fn_8025EF18(CpuState* s); void recomp_fn_8025C73C(CpuState* s);
void recomp_fn_8025C710(CpuState* s); void recomp_fn_8025EF48(CpuState* s); void recomp_fn_8025F0B0(CpuState* s);
void recomp_fn_8025F0DC(CpuState* s); void recomp_fn_80005520(CpuState* s); void recomp_fn_80005434(CpuState* s);

static void run_twin(CpuState* s, void (*fn)(CpuState*))
{
    s->gpr[1] = STACK_TOP - 0x400;
    s->gpr[2] = SDA2_BASE;
    s->gpr[13] = SDA_BASE;
    s->lr = 0;
    s->cr = 0;
    s->msr = 0x00002030u;
    fn(s);
}

static uint32_t g_rng = 0x2545F491u;
static uint32_t rnd(void) { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 17; g_rng ^= g_rng << 5; return g_rng; }

static void random_string(CpuState* s, uint32_t addr, unsigned len)
{
    unsigned i;
    for (i = 0; i < len; i++) mem_w8(s, addr + i, (uint8_t)('a' + rnd() % 6)); /* a small alphabet: repeats matter */
    mem_w8(s, addr + len, 0);
}

static int decomp_selftest(CpuState* s, char* got, size_t cap)
{
    const uint32_t A = SCRATCH + 0x1000, B = SCRATCH + 0x1200, DST = SCRATCH + 0x1400;
    int failures = 0, round, bad = 0;
    for (round = 0; round < 200 && !bad; round++) {
        unsigned la = rnd() % 40, lb = rnd() % 40, n = rnd() % 48;
        int chr = 'a' + (int)(rnd() % 8), r1, r2;
        uint32_t p1, p2;
        random_string(s, A, la); random_string(s, B, lb);

        s->gpr[3] = A; run_twin(s, recomp_fn_8025F1D8); /* strlen */
        if (s->gpr[3] != (uint32_t)dc_strlen((const char*)mem_ptr(s, A))) { bad = 1; snprintf(got, cap, "strlen round %d", round); }

        s->gpr[3] = A; s->gpr[4] = (uint32_t)chr; run_twin(s, recomp_fn_8025EF18); /* strchr */
        p1 = s->gpr[3];
        { char* r = dc_strchr((const char*)mem_ptr(s, A), chr); p2 = r ? (uint32_t)(A + (r - (char*)mem_ptr(s, A))) : 0; }
        if (p1 != p2) { bad = 1; snprintf(got, cap, "strchr round %d: twin %08X, C %08X", round, p1, p2); }

        s->gpr[3] = A; s->gpr[4] = (uint32_t)chr; s->gpr[5] = n; run_twin(s, recomp_fn_8025C73C); /* memchr */
        p1 = s->gpr[3];
        { char* r = (char*)dc_memchr(mem_ptr(s, A), chr, n); p2 = r ? (uint32_t)(A + (r - (char*)mem_ptr(s, A))) : 0; }
        if (p1 != p2) { bad = 1; snprintf(got, cap, "memchr round %d: twin %08X, C %08X", round, p1, p2); }

        s->gpr[3] = A; s->gpr[4] = (uint32_t)chr; s->gpr[5] = n; run_twin(s, recomp_fn_8025C710); /* __memrchr */
        p1 = s->gpr[3];
        { char* r = (char*)dc___memrchr(mem_ptr(s, A), chr, n); p2 = r ? (uint32_t)(A + (r - (char*)mem_ptr(s, A))) : 0; }
        if (p1 != p2) { bad = 1; snprintf(got, cap, "memrchr round %d: twin %08X, C %08X", round, p1, p2); }

        s->gpr[3] = A; s->gpr[4] = B; s->gpr[5] = n; run_twin(s, recomp_fn_8025EF48); /* strncmp */
        r1 = (int)s->gpr[3]; r2 = dc_strncmp((const char*)mem_ptr(s, A), (const char*)mem_ptr(s, B), n);
        if (r1 != r2) { bad = 1; snprintf(got, cap, "strncmp round %d: twin %d, C %d", round, r1, r2); }

        /* strcat and strncpy write: run the twin, snapshot, run the C on a fresh copy, compare */
        {
            uint8_t twin[128], native[128];
            memset(mem_ptr(s, DST), 'z', 96); random_string(s, DST, rnd() % 24);
            memcpy(native, mem_ptr(s, DST), 128);
            s->gpr[3] = DST; s->gpr[4] = A; run_twin(s, recomp_fn_8025F0B0); /* strcat */
            memcpy(twin, mem_ptr(s, DST), 128);
            dc_strcat((char*)native, (const char*)mem_ptr(s, A));
            if (memcmp(twin, native, 128) != 0) { bad = 1; snprintf(got, cap, "strcat round %d", round); }

            memset(mem_ptr(s, DST), 'z', 96); mem_w8(s, DST + 96, 0);
            memcpy(native, mem_ptr(s, DST), 128);
            s->gpr[3] = DST; s->gpr[4] = B; s->gpr[5] = n; run_twin(s, recomp_fn_8025F0DC); /* strncpy */
            memcpy(twin, mem_ptr(s, DST), 128);
            dc_strncpy((char*)native, (const char*)mem_ptr(s, B), n);
            if (memcmp(twin, native, 128) != 0) { bad = 1; snprintf(got, cap, "strncpy round %d", round); }

            /* memcpy in both directions over an overlapping region, and memset */
            {
                unsigned off = rnd() % 8, len = rnd() % 40;
                uint32_t from = DST + off, to = DST + (rnd() % 16);
                random_string(s, DST, 60);
                memcpy(native, mem_ptr(s, DST), 128);
                s->gpr[3] = to; s->gpr[4] = from; s->gpr[5] = len; run_twin(s, recomp_fn_80005520); /* memcpy */
                memcpy(twin, mem_ptr(s, DST), 128);
                dc_memcpy(native + (to - DST), native + off, len);
                if (memcmp(twin, native, 128) != 0) { bad = 1; snprintf(got, cap, "memcpy round %d", round); }
                s->gpr[3] = DST + off; s->gpr[4] = (uint32_t)chr; s->gpr[5] = len; run_twin(s, recomp_fn_80005434); /* memset */
                memcpy(twin, mem_ptr(s, DST), 128);
                dc_memset(native + off, chr, len);
                if (memcmp(twin, native, 128) != 0) { bad = 1; snprintf(got, cap, "memset round %d", round); }
            }
        }
    }
    if (!bad) snprintf(got, cap, "9 functions agree over %d rounds", round);
    failures += check("decompiled vs recompiled", got, bad ? "agreement" : got);
    return failures;
}

int selftest(CpuState* s)
{
    char got[256];
    int failures = 0;

    /* First, because it shapes a card image before anything reads SRAM. */
    failures += card_selftest(s, got, sizeof got);

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
    run_twin(s, recomp_fn_8025F0B0); /* strcat */
    get_string(s, SCRATCH, got, sizeof got);
    failures += check("strcpy+strcat", got, "alphabeta");
    s->gpr[3] = SCRATCH;
    run_twin(s, recomp_fn_8025F1D8); /* strlen */
    snprintf(got, sizeof got, "%u", s->gpr[3]);
    failures += check("strlen", got, "9");
    s->gpr[3] = SCRATCH; s->gpr[4] = SCRATCH + 0x200;
    call(s, 0x8025EF88u); /* strcmp("alphabeta", "alpha") > 0 */
    snprintf(got, sizeof got, "%s", (int32_t)s->gpr[3] > 0 ? "positive" : "other");
    failures += check("strcmp", got, "positive");
    s->gpr[3] = SCRATCH + 0x400; s->gpr[4] = 0x41; s->gpr[5] = 37;
    run_twin(s, recomp_fn_80005434); /* memset 37 bytes of 'A' */
    mem_w8(s, SCRATCH + 0x400 + 37, 0);
    get_string(s, SCRATCH + 0x400, got, sizeof got);
    failures += check("memset", got, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
    s->gpr[3] = SCRATCH + 0x500 + 3; s->gpr[4] = SCRATCH; s->gpr[5] = 10; /* unaligned memcpy incl. the NUL */
    run_twin(s, recomp_fn_80005520);
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
    failures += decomp_selftest(s, got, sizeof got);

    fprintf(stderr, "[selftest] %d failure(s)\n", failures);
    return failures;
}
