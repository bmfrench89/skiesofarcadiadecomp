/*
 * Minimal runtime: logging MMIO stubs, traps and a real timebase.
 *
 * Enough to boot the recompiled program until it touches hardware we have
 * not modelled -- and to say exactly what it touched, which is how the
 * device models get prioritised. Reads return zero; writes are counted per
 * register and the first few of each are printed.
 */
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define MMIO_BASE 0xCC000000u
#define MMIO_SLOTS 0x2000u /* 32 KB of registers, one slot per word */
#define LOG_PER_REG 6

static uint32_t g_hits[MMIO_SLOTS];
static uint64_t g_gp_bytes;
static uint64_t g_syscalls;

void hle_report(void);

/* A poll loop against a register we answer with zero never ends. Instead of
 * timing out, notice it: a long run of reads with no write in between, or
 * the same register read over and over, is a spin -- report which one. */
#define SPIN_SAME 200000u
#define SPIN_READS 2000000u
static uint32_t g_spin_ea, g_spin_same, g_reads_since_write;

void guest_backtrace(CpuState* s, uint32_t sp);

static void spin_check(CpuState* s, uint32_t ea, int is_write)
{
    if (is_write) {
        g_spin_same = 0;
        g_reads_since_write = 0;
        return;
    }
    if (ea == g_spin_ea) g_spin_same++;
    else { g_spin_ea = ea; g_spin_same = 0; }
    g_reads_since_write++;
    if (g_spin_same > SPIN_SAME || g_reads_since_write > SPIN_READS) {
        fprintf(stderr, "[spin] polling %08X: %u consecutive reads, %u reads since the last write\n",
                ea, g_spin_same, g_reads_since_write);
        fprintf(stderr, "[spin] pc %08X lr %08X; backtrace:", s->pc, s->lr);
        guest_backtrace(s, s->gpr[1]);
        hle_report();
        exit(4);
    }
}

static const char* peripheral(uint32_t ea)
{
    uint32_t off = ea - MMIO_BASE;
    if (off < 0x1000) return "CP";
    if (off < 0x2000) return "PE";
    if (off < 0x3000) return "VI";
    if (off < 0x4000) return "PI";
    if (off < 0x5000) return "MI";
    if (off < 0x6000) return "DSP";
    if (off < 0x6400) return "DI";
    if (off < 0x6800) return "SI";
    if (off < 0x6C00) return "EXI";
    if (off < 0x7000) return "AI";
    if (off < 0x8100) return "GP";
    return "??";
}

static void note(CpuState* s, const char* dir, uint32_t ea, unsigned size, uint64_t v)
{
    uint32_t slot;
    if (ea >= MMIO_BASE + 0x8000u && ea < MMIO_BASE + 0x8100u) {
        g_gp_bytes += size; /* write-gather pipe: counted, not logged */
        return;
    }
    spin_check(s, ea, dir[0] == 'w');
    if (ea < MMIO_BASE || ea >= MMIO_BASE + MMIO_SLOTS * 4u) {
        static int strict = -1, shown;
        if (strict < 0) strict = getenv("SOA_STRICT") ? 1 : 0;
        if (shown++ < 20 || strict)
            fprintf(stderr, "[mmio] %s %08X/%u = %llx (outside modelled range)\n", dir, ea, size,
                    (unsigned long long)v);
        if (strict) { /* almost always a garbage pointer: stop at the first one, with the stack */
            fprintf(stderr, "[strict] pc %08X lr %08X; backtrace:", s->pc, s->lr);
            guest_backtrace(s, s->gpr[1]);
            hle_report();
            exit(8);
        }
        return;
    }
    slot = (ea - MMIO_BASE) >> 2;
    if (g_hits[slot]++ < LOG_PER_REG)
        fprintf(stderr, "[mmio] %-3s %s %08X/%u = %llx\n", peripheral(ea), dir, ea, size,
                (unsigned long long)v);
}

/* Modelled devices (irq.c) get first refusal; everything else reads as zero. */
int device_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out);
void device_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v);

#define MMIO_READ(T, N)                                        \
    T mmio_read##N(CpuState* s, uint32_t ea)                   \
    {                                                          \
        uint64_t v = 0;                                        \
        int handled = device_read(s, ea, sizeof(T), &v);       \
        note(s, handled ? "RD" : "rd", ea, sizeof(T), v);         \
        return (T)v;                                           \
    }
#define MMIO_WRITE(T, N)                                       \
    void mmio_write##N(CpuState* s, uint32_t ea, T v)          \
    {                                                          \
        note(s, "wr", ea, sizeof(T), v);                          \
        device_write(s, ea, sizeof(T), v);                     \
    }

MMIO_READ(uint8_t, 8)
MMIO_READ(uint16_t, 16)
MMIO_READ(uint32_t, 32)
MMIO_READ(uint64_t, 64)
MMIO_WRITE(uint8_t, 8)
MMIO_WRITE(uint16_t, 16)
MMIO_WRITE(uint32_t, 32)
MMIO_WRITE(uint64_t, 64)

void irq_report(void);
void threads_report(void);

void hle_report(void)
{
    uint32_t i, distinct = 0;
    uint64_t total = 0;
    irq_report();
    threads_report();
    for (i = 0; i < MMIO_SLOTS; i++) {
        if (g_hits[i]) { distinct++; total += g_hits[i]; }
    }
    fprintf(stderr, "[hle] %llu MMIO accesses over %u registers; %llu bytes to the gather pipe; "
            "%llu syscalls\n", (unsigned long long)total, distinct,
            (unsigned long long)g_gp_bytes, (unsigned long long)g_syscalls);
    /* The busiest registers say what the guest is waiting on. */
    {
        uint32_t shown;
        for (shown = 0; shown < 12; shown++) {
            uint32_t best = 0, best_i = 0;
            for (i = 0; i < MMIO_SLOTS; i++)
                if (g_hits[i] > best) { best = g_hits[i]; best_i = i; }
            if (!best) break;
            fprintf(stderr, "  %10u  %s %08X\n", best, peripheral(MMIO_BASE + best_i * 4),
                    MMIO_BASE + best_i * 4);
            g_hits[best_i] = 0;
        }
    }
}

void hle_dump(CpuState* s, uint32_t pc)
{
    int i;
    fprintf(stderr, "  pc=%08X lr=%08X ctr=%08X cr=%08X xer=%08X msr=%08X\n", pc, s->lr, s->ctr,
            s->cr, s->xer, s->msr);
    for (i = 0; i < 32; i += 4)
        fprintf(stderr, "  r%-2d=%08X r%-2d=%08X r%-2d=%08X r%-2d=%08X\n", i, s->gpr[i], i + 1,
                s->gpr[i + 1], i + 2, s->gpr[i + 2], i + 3, s->gpr[i + 3]);
}

void guest_trap(CpuState* s, uint32_t pc)
{
    fprintf(stderr, "[trap] at %08X\n", pc);
    hle_dump(s, pc);
    fprintf(stderr, "  backtrace from r1:");
    guest_backtrace(s, s->gpr[1]);
    hle_report();
    exit(3);
}

void guest_unimplemented(CpuState* s, uint32_t pc, const char* what)
{
    fprintf(stderr, "[unimplemented] %s at %08X\n", what, pc);
    hle_dump(s, pc);
    hle_report();
    exit(2);
}

void guest_syscall(CpuState* s, uint32_t pc)
{
    (void)s;
    if (g_syscalls++ < LOG_PER_REG) fprintf(stderr, "[sc] at %08X\n", pc);
}

/* The Gekko timebase ticks at a quarter of the 162 MHz bus clock. */
#define TB_HZ 40500000ull

static uint64_t timebase(void)
{
    struct timespec ts;
    static uint64_t origin;
    static unsigned speed; /* SOA_SPEED=n: guest time runs n times faster than the wall clock */
    uint64_t ns;
    timespec_get(&ts, TIME_UTC);
    ns = (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
    if (!origin) {
        const char* env = getenv("SOA_SPEED");
        origin = ns;
        speed = env && atoi(env) > 0 ? (unsigned)atoi(env) : 1u;
    }
    ns = (ns - origin) * speed;
    return ns / 1000000000ull * TB_HZ + ns % 1000000000ull * TB_HZ / 1000000000ull;
}

uint32_t guest_timebase_lo(CpuState* s) { (void)s; return (uint32_t)timebase(); }
uint32_t guest_timebase_hi(CpuState* s) { (void)s; return (uint32_t)(timebase() >> 32); }
