/*
 * Boot the recompiled program.
 *
 * Builds the MEM1 image the console's boot code and apploader would have left
 * behind -- the DOL's sections at their virtual addresses, BSS zeroed, the
 * FST parked below the arena, the low-memory globals the OS reads at start
 * -- then jumps to the DOL entry point exactly as the apploader would.
 *
 *     soa.exe [extracted-dir]
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef ENTRY_FN
#define ENTRY_FN fn_80003140 /* __start */
#endif
#define STR2(x) #x
#define STR(x) STR2(x)
void ENTRY_FN(CpuState* s);
void hle_report(void);
void hle_dump(CpuState* s, uint32_t pc);
void threads_init(CpuState* s);
void dvd_init(const char* path);
int irq_in_handler(void);

/* A loop that never touches hardware never trips the MMIO spin detector, so
 * a second thread waits SOA_WATCHDOG seconds (default 20) and then reports
 * the block the guest is in. */
#ifdef _WIN32
#include <process.h>
#include <windows.h>
static CpuState* g_state;

/* Sample the guest's block address every millisecond while waiting, so the
 * report is a profile of what the guest spent its time in, not one snapshot. */
#define SAMPLES 8192
static uint32_t g_samples[SAMPLES];

static int cmp_desc(const void* a, const void* b)
{
    const uint32_t* x = (const uint32_t*)a;
    const uint32_t* y = (const uint32_t*)b;
    return x[1] < y[1] ? 1 : x[1] > y[1] ? -1 : 0;
}

static void profile_report(unsigned n)
{
    static uint32_t hist[SAMPLES][2]; /* addr, count */
    unsigned i, j, k = 0, shown;
    for (i = 0; i < n; i++) {
        for (j = 0; j < k; j++)
            if (hist[j][0] == g_samples[i]) { hist[j][1]++; break; }
        if (j == k) { hist[k][0] = g_samples[i]; hist[k][1] = 1; k++; }
    }
    qsort(hist, k, sizeof hist[0], cmp_desc);
    fprintf(stderr, "[profile] %u samples over %u blocks; top (H = inside an interrupt handler):\n",
            n, k);
    shown = k < 16 ? k : 16;
    for (i = 0; i < shown; i++)
        fprintf(stderr, "  %5.1f%%  %08X %s\n", 100.0 * hist[i][1] / n, hist[i][0] & ~1u,
                (hist[i][0] & 1u) ? "H" : "");
}

static unsigned __stdcall watchdog(void* arg)
{
    unsigned secs = (unsigned)(uintptr_t)arg;
    unsigned n = 0;
    ULONGLONG t0 = GetTickCount64();
    /* Sleep(1) is really ~15 ms at the default timer resolution, so pace the
     * wait by the clock rather than by counting sleeps. */
    while (GetTickCount64() - t0 < (ULONGLONG)secs * 1000u) {
        Sleep(1);
        /* Block addresses are 4-aligned; bit 0 tags samples taken in a handler. */
        if (n < SAMPLES) g_samples[n++] = g_state->pc | (irq_in_handler() ? 1u : 0u);
    }
    fprintf(stderr, "[watchdog] still running after %us; last block %08X\n", secs, g_state->pc);
    hle_dump(g_state, g_state->pc);
    profile_report(n);
    hle_report();
    _exit(5);
    return 0;
}
static void start_watchdog(CpuState* s)
{
    const char* env = getenv("SOA_WATCHDOG");
    unsigned secs = env ? (unsigned)atoi(env) : 20u;
    g_state = s;
    if (secs) _beginthreadex(NULL, 0, watchdog, (void*)(uintptr_t)secs, 0, NULL);
}
#else
static void start_watchdog(CpuState* s) { (void)s; }
#endif

#define ARENA_HI 0x81700000u
#define GEKKO_PVR 0x00083214u

static void w32(uint8_t* mem, uint32_t ea, uint32_t v)
{
    v = BSWAP32(v);
    memcpy(mem + (ea & MEM_MASK), &v, 4);
}
static uint32_t be32(const uint8_t* p)
{
    uint32_t v;
    memcpy(&v, p, 4);
    return BSWAP32(v);
}

static uint8_t* slurp(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    uint8_t* buf;
    long n;
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return NULL; }
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    buf = (uint8_t*)malloc((size_t)n);
    if (fread(buf, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(buf); return NULL; }
    fclose(f);
    *size = (size_t)n;
    return buf;
}

/* DOL header: 7 text + 11 data sections, then BSS and the entry point. */
static int load_dol(uint8_t* mem, const uint8_t* dol, size_t size)
{
    int i;
    for (i = 0; i < 18; i++) {
        uint32_t off = be32(dol + i * 4);
        uint32_t addr = be32(dol + 0x48 + i * 4);
        uint32_t len = be32(dol + 0x90 + i * 4);
        if (!len) continue;
        if (off + len > size || (addr & MEM_MASK) + len > MEM1_SIZE) {
            fprintf(stderr, "DOL section %d out of range\n", i);
            return 0;
        }
        memcpy(mem + (addr & MEM_MASK), dol + off, len);
    }
    /* BSS is already zero: the image came from calloc. */
    return 1;
}

/* What the boot ROM and apploader leave in the OS low-memory area. Values
 * follow the GameCube's documented layout; the OS reads several of them
 * during OSInit. */
static void setup_low_memory(uint8_t* mem, const uint8_t* boot, uint32_t fst_addr, uint32_t fst_max)
{
    memcpy(mem, boot, 0x20); /* game ID, maker, disc, version, streaming, magic */
    w32(mem, 0x80000020u, 0x0D15EA5Eu); /* standard boot code magic */
    w32(mem, 0x80000024u, 0x00000001u); /* version */
    w32(mem, 0x80000028u, MEM1_SIZE);   /* physical memory size */
    w32(mem, 0x8000002Cu, 0x00000003u); /* console type: retail production board */
    w32(mem, 0x80000030u, 0x00000000u); /* arena lo: let the OS derive it */
    w32(mem, 0x80000034u, ARENA_HI);    /* arena hi */
    w32(mem, 0x80000038u, fst_addr);    /* FST location */
    w32(mem, 0x8000003Cu, fst_max);     /* FST max size */
    w32(mem, 0x800000CCu, 0x00000000u); /* video mode: NTSC */
    w32(mem, 0x800000D0u, MEM1_SIZE);   /* simulated memory size (mirror) */
    w32(mem, 0x800000F0u, MEM1_SIZE);   /* simulated memory size */
    w32(mem, 0x800000F8u, 0x09A7EC80u); /* bus clock, 162 MHz */
    w32(mem, 0x800000FCu, 0x1CF7C580u); /* CPU clock, 486 MHz */
}

int main(int argc, char** argv)
{
    const char* dir = argc > 1 ? argv[1] : "extracted";
    char path[1024];
    uint8_t *dol, *boot, *fst;
    size_t dol_size, boot_size, fst_size;
    uint32_t fst_addr, fst_max;
    static CpuState s;

    s.mem = (uint8_t*)calloc(1, MEM1_SIZE);
    if (!s.mem) { fprintf(stderr, "cannot allocate MEM1\n"); return 1; }

    snprintf(path, sizeof path, "%s/sys/main.dol", dir);
    dol = slurp(path, &dol_size);
    snprintf(path, sizeof path, "%s/sys/boot.bin", dir);
    boot = slurp(path, &boot_size);
    snprintf(path, sizeof path, "%s/sys/fst.bin", dir);
    fst = slurp(path, &fst_size);
    if (!dol || !boot || !fst) return 1;

    if (!load_dol(s.mem, dol, dol_size)) return 1;

    /* The apploader parks the FST just under the arena, 32-byte aligned. */
    fst_max = be32(boot + 0x42C);
    fst_addr = (ARENA_HI - (uint32_t)fst_size) & ~31u;
    memcpy(s.mem + (fst_addr & MEM_MASK), fst, fst_size);
    setup_low_memory(s.mem, boot, fst_addr, fst_max);

    s.spr[287] = GEKKO_PVR;
    s.msr = 0x00002030u; /* FP | IR | DR -- __init_hardware rewrites it anyway */

    fprintf(stderr, "[boot] DOL %zu bytes, FST %zu bytes at %08X; entering %s\n", dol_size,
            fst_size, fst_addr, STR(ENTRY_FN));
    snprintf(path, sizeof path, "%s/disc.iso", dir);
    dvd_init(path);
    threads_init(&s);
    start_watchdog(&s);
    ENTRY_FN(&s);

    fprintf(stderr, "[boot] entry point returned\n");
    hle_report();
    return 0;
}
