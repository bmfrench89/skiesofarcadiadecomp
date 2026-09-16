/*
 * The external interface: three channels of chip-selected serial devices.
 *
 *   channel 0, device 0  memory card in slot A (a file, formatted by the game)
 *   channel 0, device 1  the RTC/SRAM (settings and the clock), the IPL ROM (not provided)
 *   channel 1, device 0  slot B: empty
 *   channel 2            nothing
 *
 * Transfers are immediate (1-4 bytes through EXI_DATA) or DMA (EXI_MAR /
 * EXI_LENGTH); each completes at once with TCINT, and the TC interrupt is
 * raised when the SDK enables it. Devices see a byte stream framed by the
 * chip select, which is how the real ones work.
 *
 *   0xCC006800 + 0x14*ch: CSR, MAR, LENGTH, CR, DATA
 *   CSR: EXIINTMSK 0, EXIINT 1, TCINTMSK 2, TCINT 3, CLK 4-6, CS0B 7, CS1B 8, CS2B 9,
 *        EXTINTMSK 10, EXTINT 11, EXT 12 (device present), ROMDIS 13
 *   CR:  TSTART 0, DMA 1, RW 2-3 (0 read, 1 write, 2 read/write), TLEN 4-5 (bytes-1)
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define EXI_BASE 0xCC006800u
#define CSR_TCINTMSK 0x0004u
#define CSR_TCINT 0x0008u
#define CSR_CS_MASK 0x0380u
#define CSR_EXT 0x1000u
#define CSR_W1C 0x080Au /* EXIINT, TCINT, EXTINT */
#define CSR_STORED 0x07F5u /* masks, clock, chip selects -- the mask the SDK itself uses */

typedef struct {
    uint32_t csr, mar, len, cr, data;
    int selected; /* device index or -1 */
    unsigned pos; /* byte position within the current transaction */
    uint32_t cmd; /* the command word being assembled */
} Channel;

static Channel g_ch[3];
static uint64_t g_imm, g_dma, g_card_reads, g_card_writes;

/* ---- memory card ---------------------------------------------------------- */

#define CARD_BYTES (4u << 17) /* 4 Mbit: the 59-block card */
#define CARD_ID 0x00000004u
static uint8_t* g_card;
static uint32_t g_card_addr;
static uint8_t g_card_cmd;
static uint8_t g_card_status = 0x41; /* ready, unlocked */
static int g_card_dirty;
static const char* g_card_path = "build/cards/slotA.raw";

static void card_load(void)
{
    FILE* f;
    if (g_card) return;
    g_card = (uint8_t*)malloc(CARD_BYTES);
    memset(g_card, 0xFF, CARD_BYTES); /* blank flash */
    f = fopen(g_card_path, "rb");
    if (f) {
        size_t n = fread(g_card, 1, CARD_BYTES, f);
        fclose(f);
        fprintf(stderr, "[exi] memory card %s (%zu bytes)\n", g_card_path, n);
    } else {
        fprintf(stderr, "[exi] memory card %s: new blank card\n", g_card_path);
    }
}

void exi_card_save(void)
{
    FILE* f;
    if (!g_card || !g_card_dirty) return;
    f = fopen(g_card_path, "wb");
    if (!f) { fprintf(stderr, "[exi] cannot write %s (mkdir build/cards)\n", g_card_path); return; }
    fwrite(g_card, 1, CARD_BYTES, f);
    fclose(f);
    g_card_dirty = 0;
}

/* One byte in each direction on the card's serial line. */
static uint8_t card_byte(Channel* c, uint8_t in)
{
    uint8_t out = 0xFF;
    card_load();
    if (c->pos == 0) { g_card_cmd = in; c->pos++; return 0xFF; }
    switch (g_card_cmd) {
    case 0x00: /* EXI ID: after the 2-byte command, the 4-byte size code */
        out = c->pos == 5 ? (uint8_t)(CARD_ID >> 8) : (c->pos == 6 ? (uint8_t)CARD_ID : 0x00);
        break;
    case 0x85: /* read ID */
        out = c->pos == 1 ? 0x80 : (c->pos == 2 ? 0xC2 : (c->pos == 3 ? 0x21 : 0x00));
        break;
    case 0x83: /* read status */
        out = g_card_status;
        break;
    case 0x89: /* clear status */
        break;
    case 0x52: /* read array: 4 address bytes, then data by DMA (or serially) */
        if (c->pos == 1) g_card_addr = (uint32_t)in << 17;
        else if (c->pos == 2) g_card_addr |= (uint32_t)in << 9;
        else if (c->pos == 3) g_card_addr |= (uint32_t)(in & 3) << 7;
        else if (c->pos == 4) g_card_addr |= in & 0x7F;
        else if (c->pos >= 9) { out = g_card[g_card_addr % CARD_BYTES]; g_card_addr++; g_card_reads++; }
        break;
    case 0xF2: /* page program: 4 address bytes, then 128 bytes */
        if (c->pos == 1) g_card_addr = (uint32_t)in << 17;
        else if (c->pos == 2) g_card_addr |= (uint32_t)in << 9;
        else if (c->pos == 3) g_card_addr |= (uint32_t)(in & 3) << 7;
        else if (c->pos == 4) g_card_addr |= in & 0x7F;
        else { g_card[g_card_addr % CARD_BYTES] &= in; g_card_addr++; g_card_dirty = 1; g_card_writes++; }
        break;
    case 0xF1: /* sector erase: 2 address bytes (8 KB sectors) */
        if (c->pos == 1) g_card_addr = (uint32_t)in << 17;
        else if (c->pos == 2) {
            g_card_addr |= (uint32_t)in << 9;
            memset(g_card + (g_card_addr % CARD_BYTES), 0xFF, 0x2000);
            g_card_dirty = 1;
        }
        break;
    case 0xF4: /* chip erase */
        if (c->pos == 2) { memset(g_card, 0xFF, CARD_BYTES); g_card_dirty = 1; }
        break;
    case 0x81: /* set interrupt */
    case 0x87: /* wake up */
    case 0x88: /* sleep */
    case 0x86: /* read error buffer */
    default:
        break;
    }
    c->pos++;
    return out;
}

/* DMA against the card: the address the command set, page by page. */
static void card_dma(CpuState* s, uint32_t mar, uint32_t len, int write)
{
    uint32_t i;
    card_load();
    if ((mar & MEM_MASK) + len > MEM1_SIZE) return;
    for (i = 0; i < len; i++) {
        uint32_t a = g_card_addr % CARD_BYTES;
        if (write) { g_card[a] &= mem_r8(s, (mar | 0x80000000u) + i); g_card_dirty = 1; g_card_writes++; }
        else { mem_w8(s, (mar | 0x80000000u) + i, g_card[a]); g_card_reads++; }
        g_card_addr++;
    }
}

/* ---- RTC / SRAM ----------------------------------------------------------- */

static uint8_t g_sram[64];
static int g_sram_init;
static uint32_t g_rtc_cmd;

static void sram_init(void)
{
    uint32_t sum = 0, inv = 0;
    int i;
    if (g_sram_init) return;
    g_sram_init = 1;
    memset(g_sram, 0, sizeof g_sram);
    /* ead0/ead1 0, counterBias 0, displayOffsetH 0, ntd 0, language English, flags: stereo */
    g_sram[23] = 0x04;
    for (i = 8; i < 24; i += 2) {
        uint16_t w = (uint16_t)(((uint16_t)g_sram[i] << 8) | g_sram[i + 1]);
        sum += w;
        inv += (uint16_t)~w;
    }
    g_sram[0] = (uint8_t)(sum >> 24); g_sram[1] = (uint8_t)(sum >> 16); g_sram[2] = (uint8_t)(sum >> 8); g_sram[3] = (uint8_t)sum;
    g_sram[4] = (uint8_t)(inv >> 24); g_sram[5] = (uint8_t)(inv >> 16); g_sram[6] = (uint8_t)(inv >> 8); g_sram[7] = (uint8_t)inv;
}

static uint32_t rtc_seconds(void)
{
    /* seconds since 2000-01-01 00:00:00 local */
    time_t now = time(NULL);
    struct tm t2000;
    memset(&t2000, 0, sizeof t2000);
    t2000.tm_year = 100; t2000.tm_mon = 0; t2000.tm_mday = 1;
    return (uint32_t)(now - mktime(&t2000));
}

static uint8_t rtc_byte(Channel* c, uint8_t in)
{
    uint8_t out = 0;
    sram_init();
    if (c->pos < 4) { g_rtc_cmd = (g_rtc_cmd << 8) | in; c->pos++; return 0; }
    {
        unsigned off = c->pos - 4;
        switch (g_rtc_cmd & 0xFFFFFF00u) {
        case 0x20000000u: { /* read RTC counter */
            uint32_t v = rtc_seconds();
            out = (uint8_t)(v >> (8 * (3 - (off & 3))));
            break;
        }
        case 0x20000100u: /* read SRAM */
            out = off < 64 ? g_sram[off] : 0;
            break;
        case 0xA0000100u: /* write SRAM */
            if (off < 64) g_sram[off] = in;
            break;
        default: /* IPL ROM reads (fonts): not provided */
            out = 0;
            break;
        }
    }
    c->pos++;
    return out;
}

/* ---- channels ---------------------------------------------------------------- */

static uint8_t dev_byte(unsigned ch, Channel* c, uint8_t in)
{
    if (ch == 0 && c->selected == 0) return card_byte(c, in);
    if (ch == 0 && c->selected == 1) return rtc_byte(c, in);
    return 0xFF; /* nothing there */
}

static void transfer(CpuState* s, unsigned ch, Channel* c)
{
    unsigned rw = (c->cr >> 2) & 3;
    if (c->cr & 2) { /* DMA */
        uint32_t len = c->len & ~31u;
        g_dma++;
        if (ch == 0 && c->selected == 0) card_dma(s, c->mar, len, rw == 1);
        else if (ch == 0 && c->selected == 1 && rw == 0) {
            uint32_t i;
            for (i = 0; i < len && (c->mar & MEM_MASK) + i < MEM1_SIZE; i++)
                mem_w8(s, (c->mar | 0x80000000u) + i, rtc_byte(c, 0));
        }
    } else { /* immediate: TLEN+1 bytes through DATA, most significant first */
        unsigned n = ((c->cr >> 4) & 3) + 1, i;
        uint32_t in = c->data, out = 0;
        g_imm++;
        for (i = 0; i < n; i++) {
            uint8_t b = (uint8_t)(in >> (8 * (3 - i)));
            uint8_t r = dev_byte(ch, c, rw == 1 ? b : (rw == 0 ? 0 : b));
            out |= (uint32_t)r << (8 * (3 - i));
        }
        if (rw != 1) c->data = out;
    }
    c->cr &= ~1u;          /* TSTART clears: done */
    c->csr |= CSR_TCINT;   /* transfer complete */
}

int exi_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out)
{
    unsigned ch, reg;
    (void)s;
    if (ea < EXI_BASE || ea >= EXI_BASE + 0x40 || size != 4) return 0;
    ch = (ea - EXI_BASE) / 0x14;
    reg = (ea - EXI_BASE) % 0x14;
    if (ch > 2) return 0;
    switch (reg) {
    case 0x00: *out = g_ch[ch].csr | (ch == 0 ? CSR_EXT : 0); return 1;
    case 0x04: *out = g_ch[ch].mar; return 1;
    case 0x08: *out = g_ch[ch].len; return 1;
    case 0x0C: *out = g_ch[ch].cr; return 1;
    case 0x10: *out = g_ch[ch].data; return 1;
    default: return 0;
    }
}

int exi_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    unsigned ch, reg;
    uint32_t w = (uint32_t)v;
    Channel* c;
    if (ea < EXI_BASE || ea >= EXI_BASE + 0x40 || size != 4) return 0;
    ch = (ea - EXI_BASE) / 0x14;
    reg = (ea - EXI_BASE) % 0x14;
    if (ch > 2) return 0;
    c = &g_ch[ch];
    switch (reg) {
    case 0x00: {
        int sel = -1;
        c->csr = (c->csr & CSR_W1C & ~(w & CSR_W1C)) | (w & CSR_STORED);
        if (w & 0x0080) sel = 0; else if (w & 0x0100) sel = 1; else if (w & 0x0200) sel = 2;
        if (sel != c->selected) { c->selected = sel; c->pos = 0; g_rtc_cmd = 0; }
        return 1;
    }
    case 0x04: c->mar = w & 0x03FFFFE0u; return 1;
    case 0x08: c->len = w & 0x03FFFFE0u; return 1;
    case 0x0C:
        c->cr = w & 0x3Fu;
        if (w & 1) transfer(s, ch, c);
        return 1;
    case 0x10: c->data = w; return 1;
    default: return 1;
    }
}

/* Bit per channel: a completed transfer with its interrupt enabled. */
unsigned exi_irq_pending(void)
{
    unsigned bits = 0, ch;
    for (ch = 0; ch < 3; ch++)
        if ((g_ch[ch].csr & CSR_TCINT) && (g_ch[ch].csr & CSR_TCINTMSK)) bits |= 1u << ch;
    return bits;
}

void exi_report(void)
{
    exi_card_save();
    fprintf(stderr, "[exi] %llu immediate, %llu DMA transfers; card %llu bytes read, %llu written\n",
            (unsigned long long)g_imm, (unsigned long long)g_dma, (unsigned long long)g_card_reads,
            (unsigned long long)g_card_writes);
}
