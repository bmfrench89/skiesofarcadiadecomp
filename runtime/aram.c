/*
 * Auxiliary RAM (ARAM) and the DSP-side registers that drive it.
 *
 * 16 MB of memory only the DSP and its DMA engine can reach. The game keeps
 * audio samples there (SPEC: the stock AX ucode reads voices out of ARAM) and
 * the SDK's ARQ queue moves data in and out with the DMA engine below. DMA
 * completes instantly and raises the ARAM interrupt in the DSP status
 * register.
 *
 *   0xCC00500A  DSP_CSR     RES, PIINT, HALT, AIDINT/MSK, ARINT/MSK, DSPINT/MSK, DMAINT, DSPINIT
 *   0xCC005012  AR_SIZE
 *   0xCC005016  AR_MODE     bit 0 reads back set: the controller is ready
 *   0xCC00501A  AR_REFRESH
 *   0xCC005020  AR_DMA_MMADDR  main-memory address (u32)
 *   0xCC005024  AR_DMA_ARADDR  ARAM address (u32)
 *   0xCC005028  AR_DMA_CNT     bit 31 direction (1 = ARAM to main memory), length below
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ARAM_SIZE (16u << 20)
#define ARAM_MASK (ARAM_SIZE - 1)

#define CSR_RES 0x0001u
#define CSR_PIINT 0x0002u
#define CSR_HALT 0x0004u
#define CSR_AIDINT 0x0008u
#define CSR_AIDINTMSK 0x0010u
#define CSR_ARINT 0x0020u
#define CSR_ARINTMSK 0x0040u
#define CSR_DSPINT 0x0080u
#define CSR_DSPINTMSK 0x0100u
#define CSR_W1C (CSR_PIINT | CSR_AIDINT | CSR_ARINT | CSR_DSPINT)
#define CSR_DSPINITCODE 0x0400u
#define CSR_DSPINIT 0x0800u
#define CSR_STORED (CSR_HALT | CSR_AIDINTMSK | CSR_ARINTMSK | CSR_DSPINTMSK | CSR_DSPINITCODE | CSR_DSPINIT)

void dsp_reset(void);
void dsp_stub_boot(void);

static uint8_t* g_aram;
static uint16_t g_csr = CSR_HALT | CSR_DSPINIT, g_ar_size, g_ar_mode, g_ar_refresh;
static uint32_t g_mmaddr, g_araddr;
static uint16_t g_cnt_hi; /* the register bank is 16-bit; the low half of CNT starts the DMA */
static uint64_t g_dmas, g_dma_bytes;

static void dma(CpuState* s, uint32_t cnt)
{
    uint32_t len = cnt & 0x7FFFFFFFu;
    int to_main = (cnt >> 31) & 1;
    if (!g_aram) g_aram = (uint8_t*)calloc(1, ARAM_SIZE);
    if ((g_araddr & ARAM_MASK) + len > ARAM_SIZE || (g_mmaddr & MEM_MASK) + len > MEM1_SIZE) {
        fprintf(stderr, "[aram] DMA out of range: mm %08X ar %08X len %u\n", g_mmaddr, g_araddr, len);
    } else if (to_main) {
        memcpy(mem_ptr(s, g_mmaddr), g_aram + (g_araddr & ARAM_MASK), len);
    } else {
        memcpy(g_aram + (g_araddr & ARAM_MASK), mem_ptr(s, g_mmaddr), len);
    }
    g_dmas++;
    g_dma_bytes += len;
    g_csr |= CSR_ARINT; /* complete: raise the ARAM interrupt */
}

int aram_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out)
{
    (void)s;
    if (ea < 0xCC005000u || ea >= 0xCC005040u) return 0;
    switch (ea - 0xCC005000u) {
    case 0x0A: if (size != 2) return 0; *out = g_csr; return 1;
    case 0x12: if (size != 2) return 0; *out = g_ar_size; return 1;
    case 0x16: if (size != 2) return 0; *out = g_ar_mode | 1u; return 1; /* ready */
    case 0x1A: if (size != 2) return 0; *out = g_ar_refresh; return 1;
    case 0x20: *out = size == 4 ? g_mmaddr : (g_mmaddr >> 16); return 1;
    case 0x22: if (size != 2) return 0; *out = g_mmaddr & 0xFFFFu; return 1;
    case 0x24: *out = size == 4 ? g_araddr : (g_araddr >> 16); return 1;
    case 0x26: if (size != 2) return 0; *out = g_araddr & 0xFFFFu; return 1;
    case 0x28: case 0x2A: *out = 0; return 1; /* DMA never in progress */
    default: return 0;
    }
}

int aram_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    uint16_t was;
    if (ea < 0xCC005000u || ea >= 0xCC005040u) return 0;
    switch (ea - 0xCC005000u) {
    case 0x0A:
        if (size != 2) return 0;
        /* RES self-clears; interrupt bits are write-one-to-clear; the rest is stored. */
        was = g_csr;
        g_csr = (uint16_t)((g_csr & CSR_W1C & ~(v & CSR_W1C)) | (v & CSR_STORED));
        if (v & CSR_RES) dsp_reset();
        if ((was & CSR_DSPINIT) && !(v & CSR_DSPINIT)) { /* boot from ARAM: the stub runs */
            g_csr |= CSR_DSPINITCODE;
            dsp_stub_boot();
        }
        return 1;
    case 0x12: if (size != 2) return 0; g_ar_size = (uint16_t)v; return 1;
    case 0x16: if (size != 2) return 0; g_ar_mode = (uint16_t)v; return 1;
    case 0x1A: if (size != 2) return 0; g_ar_refresh = (uint16_t)v; return 1;
    case 0x20:
        g_mmaddr = size == 4 ? (uint32_t)v : ((g_mmaddr & 0xFFFFu) | ((uint32_t)v << 16));
        return 1;
    case 0x22: if (size != 2) return 0; g_mmaddr = (g_mmaddr & 0xFFFF0000u) | ((uint32_t)v & 0xFFFFu); return 1;
    case 0x24:
        g_araddr = size == 4 ? (uint32_t)v : ((g_araddr & 0xFFFFu) | ((uint32_t)v << 16));
        return 1;
    case 0x26: if (size != 2) return 0; g_araddr = (g_araddr & 0xFFFF0000u) | ((uint32_t)v & 0xFFFFu); return 1;
    case 0x28: /* a full write starts the transfer; a half write waits for the low half */
        if (size == 4) { dma(s, (uint32_t)v); return 1; }
        g_cnt_hi = (uint16_t)v;
        return 1;
    case 0x2A: if (size != 2) return 0; dma(s, ((uint32_t)g_cnt_hi << 16) | ((uint32_t)v & 0xFFFFu)); return 1;
    default: return 0;
    }
}

uint8_t* aram_memory(void)
{
    if (!g_aram) g_aram = (uint8_t*)calloc(1, ARAM_SIZE);
    return g_aram;
}

/* True when a finished DMA has an enabled, unacknowledged interrupt. */
int aram_irq_pending(void)
{
    return (g_csr & CSR_ARINT) && (g_csr & CSR_ARINTMSK);
}

/* The mailbox and AI DMA models (dsp.c) raise their interrupt bits here. */
void dsp_csr_raise(uint16_t bits)
{
    g_csr |= bits;
}

int dsp_irq_pending(void)
{
    return (g_csr & CSR_DSPINT) && (g_csr & CSR_DSPINTMSK);
}

int ai_dma_irq_pending(void)
{
    return (g_csr & CSR_AIDINT) && (g_csr & CSR_AIDINTMSK);
}

void aram_report(void)
{
    fprintf(stderr, "[aram] %llu DMAs, %llu bytes\n", (unsigned long long)g_dmas,
            (unsigned long long)g_dma_bytes);
}
