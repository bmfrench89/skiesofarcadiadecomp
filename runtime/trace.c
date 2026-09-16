/*
 * Tracepoints. Addresses listed in config/trace.txt call trace_hit before
 * the instruction there; with SOA_TRACE set each site prints its first few
 * hits with the registers that matter for a call boundary.
 */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PER_SITE 1000

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
    fprintf(stderr, "[trace] %-24s pc %08X lr %08X msr %08X r3 %08X r4 %08X r5 %08X r6 %08X r7 %08X r31 %08X r1 %08X", name, pc,
            s->lr, s->msr, s->gpr[3], s->gpr[4], s->gpr[5], s->gpr[6], s->gpr[7], s->gpr[31], s->gpr[1]);
    show_string(s, s->gpr[3]);
    show_string(s, s->gpr[4]);
    {
        /* SOA_TRACE_DUMP=1 shows 12 words at r3; a site named "Thing@r7" dumps at r7 instead. */
        static int dump = -1;
        const char* at = strrchr(name, '@');
        unsigned reg = at && at[1] == 'r' ? (unsigned)atoi(at + 2) & 31u : 3u;
        uint32_t base = s->gpr[reg];
        if (dump < 0) dump = getenv("SOA_TRACE_DUMP") ? 1 : 0;
        if (dump && base >= 0x80000000u && base < 0x81800000u - 64) {
            unsigned i;
            fprintf(stderr, " r%u[", reg);
            for (i = 0; i < 12; i++) fprintf(stderr, "%s%08X", i ? " " : "", mem_r32(s, base + 4 * i));
            fprintf(stderr, "]");
        }
    }
    if (enabled > 1) { fprintf(stderr, ";"); guest_backtrace(s, s->gpr[1]); }
    else fprintf(stderr, "\n");
}

uint32_t g_watch_addr, g_watch_len;

void watch_init(void)
{
    const char* env = getenv("SOA_WATCH");
    const char* text = env;
    if (!env) return;
    g_watch_addr = (uint32_t)strtoul(env, (char**)&env, 0);
    g_watch_len = *env == ',' ? (uint32_t)strtoul(env + 1, NULL, 0) : 4u;
    /* The watchdog's own message says "SOA_WATCHDOG=0 disables it", and half
     * remembering it as SOA_WATCH=0 used to install a watchpoint over guest
     * address zero, print a line that looks like success, and leave the
     * watchdog armed. Guest addresses start at 0x80000000. */
    if (g_watch_addr < 0x80000000u) {
        fprintf(stderr, "[watch] SOA_WATCH=\"%s\" is not a guest address (did you mean SOA_WATCHDOG?); "
                        "no watchpoint set\n", text);
        g_watch_len = 0;
        g_watch_addr = 0;
        return;
    }
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
