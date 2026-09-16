/*
 * Call recompiled library functions directly, outside the game's control
 * flow, and check what they produce. SOA_SELFTEST=1 runs these instead of
 * the game: a wrong answer here is a translation bug with a tiny repro.
 *
 * The C library is position-independent enough for this -- sprintf needs
 * nothing but the small-data bases the startup code sets in r2 and r13.
 */
#include "cpu.h"
#include <stdio.h>
#include <string.h>

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

    fprintf(stderr, "[selftest] %d failure(s)\n", failures);
    return failures;
}
