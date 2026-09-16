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

    fprintf(stderr, "[selftest] %d failure(s)\n", failures);
    return failures;
}
