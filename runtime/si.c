/*
 * Serial interface: the four controller ports, as the SDK's SI and PAD
 * drivers see them. One standard controller in port 1; nothing elsewhere.
 *
 * Two paths reach the controller. Direct transfers (SITransfer): the CPU
 * puts a command in the I/O buffer at 0xCC006480, writes SICOMCSR with
 * TSTART, and gets the response back in the same buffer with TCINT and an
 * SI interrupt. Polling (SIEnablePolling): once SIPOLL enables a channel
 * the hardware sends that channel's OUTBUF command every field and lands
 * the 8-byte reply in INBUFH/INBUFL with RDST set in SISR, optionally
 * interrupting. PADRead reads INBUF; reading INBUFL clears RDST.
 *
 * Input comes from the window when there is one, else from a script
 * (SOA_PAD="frame:buttons,..." -- e.g. "1700:start,1800:a+sup" holds
 * START from the game's frame 1700, and A with the stick up from 1800,
 * each for 10 frames; sup/sdown/sleft/sright move the stick; "3600:a@150"
 * presses A at frame 3600 and again every 150 frames after that).
 *
 *   0xCC006400 + 12*ch  SICnOUTBUF   0xCC006404 + 12*ch  SICnINBUFH   +8 INBUFL
 *   0xCC006430  SIPOLL      0xCC006434  SICOMCSR    0xCC006438  SISR
 *   0xCC00643C  SIEXILK     0xCC006480..0xCC0064FF  I/O buffer
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SI_BASE 0xCC006400u
#define COMCSR_TSTART 0x00000001u
#define COMCSR_RDSTINTMSK 0x08000000u
#define COMCSR_RDSTINT 0x10000000u
#define COMCSR_TCINTMSK 0x40000000u
#define COMCSR_TCINT 0x80000000u
#define SISR_WR 0x80000000u

#define BTN_LEFT 0x0001
#define BTN_RIGHT 0x0002
#define BTN_DOWN 0x0004
#define BTN_UP 0x0008
#define BTN_Z 0x0010
#define BTN_R 0x0020
#define BTN_L 0x0040
#define BTN_A 0x0100
#define BTN_B 0x0200
#define BTN_X 0x0400
#define BTN_Y 0x0800
#define BTN_START 0x1000

static uint32_t g_outbuf[4], g_inbuf_hi[4], g_inbuf_lo[4];
static uint32_t g_poll, g_comcsr, g_sr, g_exilk;
static uint8_t g_iobuf[128];
static uint64_t g_transfers, g_polls, g_reads;
static int g_present[4] = {1, 0, 0, 0};

/* ---- scripted controller ------------------------------------------------ */

typedef struct { unsigned frame, every, hold; uint16_t buttons; uint8_t stick[2]; } PadEvent;
static PadEvent g_script[1024]; /* "F:buttons" once at frame F; "@N" again every N frames; "#H" held H frames */
static int g_script_n = -1;
#define HOLD_FRAMES 10

static uint16_t button_named(const char* name, size_t len)
{
    static const struct { const char* n; uint16_t b; } t[] = {
        {"a", BTN_A}, {"b", BTN_B}, {"x", BTN_X}, {"y", BTN_Y}, {"z", BTN_Z}, {"l", BTN_L}, {"r", BTN_R},
        {"start", BTN_START}, {"up", BTN_UP}, {"down", BTN_DOWN}, {"left", BTN_LEFT}, {"right", BTN_RIGHT},
    };
    size_t i;
    for (i = 0; i < sizeof t / sizeof t[0]; i++)
        if (strlen(t[i].n) == len && strncmp(t[i].n, name, len) == 0) return t[i].b;
    return 0;
}

static void script_init(void)
{
    const char* p = getenv("SOA_PAD");
    g_script_n = 0;
    while (p && *p && g_script_n < (int)(sizeof g_script / sizeof g_script[0])) {
        char* end;
        unsigned frame = (unsigned)strtoul(p, &end, 10), every = 0, hold = HOLD_FRAMES;
        uint16_t buttons = 0;
        if (end == p || *end != ':') break;
        p = end + 1;
        uint8_t stick[2] = {128, 128};
        while (*p && *p != ',' && *p != '@' && *p != '#') {
            const char* q = p;
            size_t len;
            while (*q && *q != ',' && *q != '+' && *q != '@' && *q != '#') q++;
            len = (size_t)(q - p);
            /* sup/sdown/sleft/sright move the main stick; everything else is a button */
            if (len == 3 && strncmp(p, "sup", 3) == 0) stick[1] = 255;
            else if (len == 5 && strncmp(p, "sdown", 5) == 0) stick[1] = 0;
            else if (len == 5 && strncmp(p, "sleft", 5) == 0) stick[0] = 0;
            else if (len == 6 && strncmp(p, "sright", 6) == 0) stick[0] = 255;
            else buttons |= button_named(p, len);
            p = *q == '+' ? q + 1 : q;
        }
        while (*p == '@' || *p == '#') {
            unsigned n = (unsigned)strtoul(p + 1, &end, 10);
            if (*p == '@') every = n; else hold = n;
            p = end;
        }
        g_script[g_script_n].frame = frame;
        g_script[g_script_n].every = every;
        g_script[g_script_n].hold = hold;
        g_script[g_script_n].buttons = buttons;
        g_script[g_script_n].stick[0] = stick[0];
        g_script[g_script_n].stick[1] = stick[1];
        g_script_n++;
        if (*p == ',') p++;
    }
    if (g_script_n) fprintf(stderr, "[si] %d scripted controller events\n", g_script_n);
}

uint64_t irq_retrace_count(void);

unsigned gx_frame_count(void);

static uint16_t buttons_now(uint8_t stick[2])
{
    static uint16_t last;
    uint64_t frame = gx_frame_count(); /* the game's frames, not fields: deterministic against its logic */
    uint16_t b = 0;
    int i;
    stick[0] = stick[1] = 128;
    if (g_script_n < 0) script_init();
    for (i = 0; i < g_script_n; i++) {
        uint64_t rel;
        if (frame < g_script[i].frame) continue;
        rel = frame - g_script[i].frame;
        if (g_script[i].every) rel %= g_script[i].every;
        if (rel < g_script[i].hold) {
            b |= g_script[i].buttons;
            if (g_script[i].stick[0] != 128) stick[0] = g_script[i].stick[0];
            if (g_script[i].stick[1] != 128) stick[1] = g_script[i].stick[1];
        }
    }
    if (b != last) {
        fprintf(stderr, "[si] frame %llu (retrace %llu): buttons %04X\n", (unsigned long long)frame, (unsigned long long)irq_retrace_count(), b);
        last = b;
    }
    return b;
}

int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]);

/* The 8-byte controller report: buttons, main stick, C stick, triggers.
 * Live input from the window when there is one, else the script. */
static void pad_report(uint8_t out[8])
{
    uint16_t b;
    uint8_t stick[2] = {128, 128}, cstick[2] = {128, 128}, trig[2] = {0, 0};
    if (!window_pad(&b, stick, cstick, trig)) b = buttons_now(stick);
    out[0] = (uint8_t)((b >> 8) & 0x1F);           /* 0 0 1? S Y X B A -- bit 5 (use origin) clear */
    out[1] = (uint8_t)(0x80 | (b & 0x7F));         /* 1 L R Z U D R L */
    out[2] = stick[0]; out[3] = stick[1];          /* main stick */
    out[4] = cstick[0]; out[5] = cstick[1];        /* C stick */
    out[6] = trig[0]; out[7] = trig[1];            /* triggers */
}

/* ---- transfers -------------------------------------------------------- */

static void run_command(unsigned chan)
{
    uint8_t cmd = g_iobuf[0];
    uint8_t rep[10];
    unsigned n = 0;
    if (!g_present[chan]) { /* no device: the transfer errors out */
        g_sr |= 0x08000000u >> (8 * chan); /* NOREP */
        g_comcsr |= 0x20000000u;           /* COMERR */
        return;
    }
    switch (cmd) {
    case 0x00: case 0xFF: /* ID */
        rep[0] = 0x09; rep[1] = 0x00; rep[2] = 0x00; n = 3;
        break;
    case 0x41: case 0x42: /* origin / calibrate: 10 bytes, sticks centred */
        pad_report(rep);
        rep[8] = 0; rep[9] = 0;
        n = 10;
        break;
    case 0x40: /* direct poll */
        pad_report(rep);
        n = 8;
        break;
    default:
        pad_report(rep);
        n = 8;
        break;
    }
    memcpy(g_iobuf, rep, n);
    g_transfers++;
}

/* Called once per field by the interrupt code: hardware polling. */
void si_poll(void)
{
    unsigned chan;
    for (chan = 0; chan < 4; chan++) {
        uint8_t rep[8];
        if (!((g_poll >> (7 - chan)) & 1)) continue;
        if (!g_present[chan]) { g_sr |= 0x08000000u >> (8 * chan); continue; } /* NOREP */
        pad_report(rep);
        g_inbuf_hi[chan] = ((uint32_t)rep[0] << 24) | ((uint32_t)rep[1] << 16) | ((uint32_t)rep[2] << 8) | rep[3];
        g_inbuf_lo[chan] = ((uint32_t)rep[4] << 24) | ((uint32_t)rep[5] << 16) | ((uint32_t)rep[6] << 8) | rep[7];
        g_sr |= 0x20000000u >> (8 * chan); /* RDST */
        g_polls++;
    }
    if (g_sr & 0x20202020u) g_comcsr |= COMCSR_RDSTINT;
}

int si_irq_pending(void)
{
    return ((g_comcsr & COMCSR_TCINT) && (g_comcsr & COMCSR_TCINTMSK)) ||
           ((g_comcsr & COMCSR_RDSTINT) && (g_comcsr & COMCSR_RDSTINTMSK));
}

int si_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out)
{
    (void)s;
    if (ea < SI_BASE || ea >= SI_BASE + 0x100 || size != 4) return 0;
    if (ea >= SI_BASE + 0x80) {
        unsigned off = ea - SI_BASE - 0x80;
        *out = ((uint32_t)g_iobuf[off] << 24) | ((uint32_t)g_iobuf[off + 1] << 16) | ((uint32_t)g_iobuf[off + 2] << 8) | g_iobuf[off + 3];
        return 1;
    }
    switch (ea - SI_BASE) {
    case 0x00: case 0x0C: case 0x18: case 0x24: *out = g_outbuf[(ea - SI_BASE) / 12]; return 1;
    case 0x04: case 0x10: case 0x1C: case 0x28: *out = g_inbuf_hi[(ea - SI_BASE) / 12]; g_reads++; return 1;
    case 0x08: case 0x14: case 0x20: case 0x2C: {
        unsigned chan = (ea - SI_BASE) / 12;
        *out = g_inbuf_lo[chan];
        g_sr &= ~(0x20000000u >> (8 * chan)); /* reading INBUFL clears RDST */
        if (!(g_sr & 0x20202020u)) g_comcsr &= ~COMCSR_RDSTINT;
        return 1;
    }
    case 0x30: *out = g_poll; return 1;
    case 0x34: *out = g_comcsr; return 1;
    case 0x38: *out = g_sr; return 1;
    case 0x3C: *out = g_exilk; return 1;
    default: *out = 0; return 1;
    }
}

int si_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    uint32_t w = (uint32_t)v;
    (void)s;
    if (ea < SI_BASE || ea >= SI_BASE + 0x100 || size != 4) return 0;
    if (ea >= SI_BASE + 0x80) {
        unsigned off = ea - SI_BASE - 0x80;
        g_iobuf[off] = (uint8_t)(w >> 24); g_iobuf[off + 1] = (uint8_t)(w >> 16);
        g_iobuf[off + 2] = (uint8_t)(w >> 8); g_iobuf[off + 3] = (uint8_t)w;
        return 1;
    }
    switch (ea - SI_BASE) {
    case 0x00: case 0x0C: case 0x18: case 0x24: g_outbuf[(ea - SI_BASE) / 12] = w; return 1;
    case 0x30: g_poll = w; return 1;
    case 0x34: {
        /* TCINT and RDSTINT are write-one-to-clear; the masks and the
         * transfer parameters are stored; TSTART runs the transfer now. */
        uint32_t keep = g_comcsr & (COMCSR_TCINT | COMCSR_RDSTINT | 0x20000000u);
        if (w & COMCSR_TCINT) keep &= ~COMCSR_TCINT;
        if (w & COMCSR_RDSTINT) keep &= ~COMCSR_RDSTINT;
        g_comcsr = (w & ~(COMCSR_TCINT | COMCSR_RDSTINT | COMCSR_TSTART | 0x20000000u)) | keep;
        if (w & COMCSR_TSTART) {
            unsigned chan = (w >> 1) & 3;
            g_comcsr &= ~0x20000000u;
            run_command(chan);
            g_comcsr |= COMCSR_TCINT; /* complete: TSTART reads back clear */
        }
        return 1;
    }
    case 0x38:
        /* WR latches the OUTBUF commands (nothing to do); error bits are w1c */
        g_sr &= ~(w & 0x0F0F0F0Fu);
        return 1;
    case 0x3C: g_exilk = w; return 1;
    default: return 1;
    }
}

void si_report(void)
{
    fprintf(stderr, "[si] %llu direct transfers, %llu polls, %llu input reads; poll reg %08X\n",
            (unsigned long long)g_transfers, (unsigned long long)g_polls, (unsigned long long)g_reads, g_poll);
}
