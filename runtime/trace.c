/*
 * Tracepoints. Addresses listed in config/trace.txt call trace_hit before
 * the instruction there; with SOA_TRACE set each site prints its first few
 * hits with the registers that matter for a call boundary.
 */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>

#define PER_SITE 40

void guest_backtrace(CpuState* s, uint32_t sp);

/* An argument that points at printable text is probably a string: show it. */
static void show_string(CpuState* s, uint32_t addr)
{
    char buf[48];
    unsigned n;
    if (addr < 0x80000000u || addr >= 0x81800000u - sizeof buf) return;
    for (n = 0; n < sizeof buf - 1; n++) {
        uint8_t c = mem_r8(s, addr + n);
        if (!c) break;
        if (c < 0x20 || c > 0x7E) return;
        buf[n] = (char)c;
    }
    if (n < 2) return;
    buf[n] = 0;
    fprintf(stderr, " \"%s\"", buf);
}

void trace_hit(CpuState* s, uint32_t pc, const char* name)
{
    static int enabled = -1;
    static uint32_t last_pc;
    static unsigned hits;
    if (enabled < 0) {
        const char* env = getenv("SOA_TRACE");
        enabled = env && atoi(env) ? atoi(env) : 0;
    }
    if (!enabled) return;
    if (pc == last_pc) { if (++hits > PER_SITE) return; } else { last_pc = pc; hits = 1; }
    fprintf(stderr, "[trace] %-24s pc %08X lr %08X msr %08X r3 %08X r4 %08X r5 %08X r6 %08X r7 %08X r1 %08X", name, pc,
            s->lr, s->msr, s->gpr[3], s->gpr[4], s->gpr[5], s->gpr[6], s->gpr[7], s->gpr[1]);
    show_string(s, s->gpr[3]);
    show_string(s, s->gpr[4]);
    if (enabled > 1) { fprintf(stderr, ";"); guest_backtrace(s, s->gpr[1]); }
    else fprintf(stderr, "\n");
}

uint32_t g_watch_addr, g_watch_len;

void watch_init(void)
{
    const char* env = getenv("SOA_WATCH");
    if (!env) return;
    g_watch_addr = (uint32_t)strtoul(env, (char**)&env, 0);
    g_watch_len = *env == ',' ? (uint32_t)strtoul(env + 1, NULL, 0) : 4u;
    fprintf(stderr, "[watch] %08X..%08X\n", g_watch_addr, g_watch_addr + g_watch_len);
}

void watch_hit(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    static unsigned hits;
    if (hits++ > 200) return;
    fprintf(stderr, "[watch] %08X/%u = %llx at block %08X lr %08X r1 %08X;", ea, size,
            (unsigned long long)v, s->pc, s->lr, s->gpr[1]);
    guest_backtrace(s, s->gpr[1]);
}
