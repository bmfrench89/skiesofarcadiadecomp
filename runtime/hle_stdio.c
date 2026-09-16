/*
 * Guest printf: the game's debug output, brought back.
 *
 * The retail build stubs its own debug print (0x801DBE1C: saves the varargs
 * and returns) and OSReport goes to a console nobody is reading. Both are
 * bound to guest_printf here, which formats the guest's arguments the way
 * the EABI lays them out -- the format in r3, integer arguments in r4..r10
 * then on the caller's stack from 8(r1), doubles in f1..f8 -- so the game's
 * own messages ("memory reallocate error -1") appear in our log, tagged.
 */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int g_enabled = -1;

typedef struct {
    CpuState* s;
    int gpr;    /* next integer argument register, 4..10, then the stack */
    int fpr;    /* next floating argument register, 1..8 */
    uint32_t stack; /* next overflow slot */
} VaList;

static uint32_t next_u32(VaList* va)
{
    if (va->gpr <= 10) return va->s->gpr[va->gpr++];
    { uint32_t v = mem_r32(va->s, va->stack); va->stack += 4; return v; }
}

static uint64_t next_u64(VaList* va)
{
    uint64_t hi, lo;
    if (va->gpr & 1) va->gpr++; /* 64-bit integers take an even/odd pair */
    if (va->gpr <= 9) { hi = va->s->gpr[va->gpr]; lo = va->s->gpr[va->gpr + 1]; va->gpr += 2; return (hi << 32) | lo; }
    va->gpr = 11;
    va->stack = (va->stack + 7) & ~7u;
    hi = mem_r32(va->s, va->stack); lo = mem_r32(va->s, va->stack + 4); va->stack += 8;
    return (hi << 32) | lo;
}

static double next_f64(VaList* va)
{
    if (va->fpr <= 8) return va->s->fpr[va->fpr++].ps0;
    va->stack = (va->stack + 7) & ~7u;
    { double v = mem_rf64(va->s, va->stack); va->stack += 8; return v; }
}

static void guest_string(CpuState* s, uint32_t addr, char* out, size_t cap)
{
    size_t n = 0;
    if (!addr) { snprintf(out, cap, "(null)"); return; }
    while (n + 1 < cap) {
        char c = (char)mem_r8(s, addr + (uint32_t)n);
        if (!c) break;
        out[n++] = c;
    }
    out[n] = 0;
}

/* Formats the guest's printf(fmt, ...) with fmt in gpr[first] and the
 * arguments after it. Returns the text; the caller decides where it goes. */
void guest_format(CpuState* s, int first, char* out, size_t cap)
{
    char fmt[1024], spec[32], item[512], sbuf[512];
    size_t o = 0;
    const char* p;
    VaList va;

    guest_string(s, s->gpr[first], fmt, sizeof fmt);
    va.s = s;
    va.gpr = first + 1;
    va.fpr = 1;
    va.stack = s->gpr[1] + 8;

    for (p = fmt; *p && o + 1 < cap;) {
        if (*p != '%') { out[o++] = *p++; continue; }
        {
            const char* start = p++;
            int longs = 0;
            size_t n;
            while (*p && strchr("-+ #0", *p)) p++;
            while (*p && (*p >= '0' && *p <= '9')) p++;
            if (*p == '*') p++;
            if (*p == '.') { p++; while (*p && ((*p >= '0' && *p <= '9') || *p == '*')) p++; }
            while (*p == 'l' || *p == 'h' || *p == 'L') { if (*p == 'l') longs++; p++; }
            if (!*p) break;
            n = (size_t)(p - start) + 1;
            if (n >= sizeof spec) n = sizeof spec - 1;
            memcpy(spec, start, n);
            spec[n] = 0;
            item[0] = 0;
            switch (*p) {
            case '%': snprintf(item, sizeof item, "%%"); break;
            case 'd': case 'i':
                if (longs >= 2) snprintf(item, sizeof item, "%lld", (long long)next_u64(&va));
                else { spec[n - 1] = 'd'; snprintf(item, sizeof item, spec, (int)next_u32(&va)); }
                break;
            case 'u': case 'x': case 'X': case 'o':
                if (longs >= 2) snprintf(item, sizeof item, *p == 'u' ? "%llu" : "%llx", (unsigned long long)next_u64(&va));
                else snprintf(item, sizeof item, spec, (unsigned)next_u32(&va));
                break;
            case 'c': snprintf(item, sizeof item, "%c", (int)next_u32(&va)); break;
            case 'p': snprintf(item, sizeof item, "%08X", next_u32(&va)); break;
            case 's':
                guest_string(s, next_u32(&va), sbuf, sizeof sbuf);
                snprintf(item, sizeof item, spec, sbuf);
                break;
            case 'f': case 'e': case 'g': case 'E': case 'G':
                snprintf(item, sizeof item, spec, next_f64(&va));
                break;
            default: snprintf(item, sizeof item, "%s", spec); break;
            }
            p++;
            for (n = 0; item[n] && o + 1 < cap; n++) out[o++] = item[n];
        }
    }
    out[o] = 0;
}

static void emit(CpuState* s, const char* tag)
{
    char text[2048];
    size_t len;
    if (g_enabled < 0) {
        const char* env = getenv("SOA_QUIET_GUEST");
        g_enabled = !(env && atoi(env));
    }
    if (!g_enabled) return;
    guest_format(s, 3, text, sizeof text);
    len = strlen(text);
    if (len && text[len - 1] == '\n') text[len - 1] = 0;
    fprintf(stderr, "[%s] %s\n", tag, text);
}

/* OSReport (0x802AC75C). */
void fn_802AC75C(CpuState* s)
{
    emit(s, "OSReport");
}

/* The game's own debug print (0x801DBE1C), a no-op in the retail build. */
void fn_801DBE1C(CpuState* s)
{
    emit(s, "game");
}
