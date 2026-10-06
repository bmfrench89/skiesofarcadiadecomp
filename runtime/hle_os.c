/*
 * Native replacements for the SDK functions listed in config/hle.txt.
 *
 * Each has the recompiled ABI (SPEC section 4.3): arguments in s->gpr[3..10],
 * the return value in s->gpr[3]. The recompiled original is still linked as
 * recomp_fn_XXXXXXXX so the two can be run against each other.
 */
#include "cpu.h"

void device_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v);

/* __OSInitAudioSystem (0x80232B90). Copies a 128-byte DSP program to
 * 0x81000000, DMAs it into ARAM, un-halts the DSP, waits for its mailbox
 * reply, then halts and resets it and restores the memory it borrowed. The
 * program only clears ARAM. The DSP is high-level emulated and ARAM starts
 * zeroed, so only the register state it leaves behind matters: AR_SIZE set,
 * the DSP halted with DSPINIT, and a reset issued -- after which the ROM
 * has announced itself in the outgoing mailbox, which DSPInit relies on. */
void fn_80232B90(CpuState* s)
{
    device_write(s, 0xCC005012u, 2, 0x43);
    device_write(s, 0xCC00500Au, 2, 0x8AC);
    device_write(s, 0xCC00500Au, 2, 0x8AD);
}

/* __OSStopAudioSystem (0x80232D4C). The shutdown counterpart. */
void fn_80232D4C(CpuState* s)
{
    (void)s;
}

/* __AI_SRC_INIT (0x80241DA0), which the three sample-rate setters call, two
 * of them from AIInit. It times the sample-rate converter: restart the sample
 * counter at 32 kHz, spin until it ticks and read the timebase; switch to 48
 * kHz, spin until it ticks again and read the timebase; stop; and start over
 * until the gap between the two reads is under 28.5 us or between 34.5 and
 * 39 us, then wait 42 or 63 us past the second. The gap spans at least seven
 * timebase reads, so where one read of the host's clock costs more than about
 * 3 us neither window can be reached and the loop never ends: 8 us on the
 * x86-64 Android emulator, which sat in it for good (FINDINGS "L12c"). Here
 * the counter runs at 48 kHz off the timebase whatever the rate bit says, and
 * nothing keeps the verdict once the wait is over, so what is left is one
 * round's register traffic: the same read-modify-writes of AICR, in the same
 * order, without the spins. The self test holds it to the twin wherever the
 * twin can finish. */
static void aicr_rmw(CpuState* s, uint32_t keep, uint32_t set)
{
    mmio_write32(s, 0xCC006C00u, (mmio_read32(s, 0xCC006C00u) & keep) | set);
}

void fn_80241DA0(CpuState* s)
{
    s->pc = 0x80241DA0u; /* first, as the translation's block head does (test_hle_pc) */
    aicr_rmw(s, ~0x20u, 0x20u); /* SCRESET: the sample counter restarts */
    aicr_rmw(s, ~0x02u, 0);     /* 32 kHz */
    aicr_rmw(s, ~0x01u, 0x01u); /* play */
    aicr_rmw(s, ~0x02u, 0x02u); /* 48 kHz */
    aicr_rmw(s, ~0x01u, 0x01u); /* play */
    aicr_rmw(s, ~0x02u, 0);     /* 32 kHz */
    aicr_rmw(s, ~0x01u, 0);     /* stop */
}

/* The data-cache range calls (PLAN-60FPS-MODS H13b): DCInvalidateRange
 * (0x80232E38), DCFlushRange (0x80232E64), DCStoreRange (0x80232E94),
 * DCFlushRangeNoSync (0x80232EC4) and DCStoreRangeNoSync (0x80232EF0). There
 * is no data cache here -- dcbi, dcbf and dcbst translate to nothing -- so
 * each was a loop that walked its range 32 bytes at a time doing nothing but
 * count and poll for interrupts: DCInvalidateRange alone was 2.5% of the guest
 * thread in the Dangral base drawn every frame, 5.2% with the drawing out of
 * the way (FINDINGS "H13, first steps"). What the loop leaves in r3-r5, CTR
 * and CR0 is volatile across a call. The two that end in `sc` still make
 * it, for a non-empty range as the original does, so the report's syscall
 * count is unchanged; the self test holds all five to their twins. */
void fn_80232E38(CpuState* s) { s->pc = 0x80232E38u; }
void fn_80232E64(CpuState* s) { s->pc = 0x80232E64u; if (s->gpr[4]) guest_syscall(s, 0x80232E8Cu); }
void fn_80232E94(CpuState* s) { s->pc = 0x80232E94u; if (s->gpr[4]) guest_syscall(s, 0x80232EBCu); }
void fn_80232EC4(CpuState* s) { s->pc = 0x80232EC4u; }
void fn_80232EF0(CpuState* s) { s->pc = 0x80232EF0u; }
