/*
 * Native replacements for the SDK functions listed in config/hle.txt.
 *
 * Each has the recompiled ABI (SPEC section 4.3): arguments in s->gpr[3..10],
 * the return value in s->gpr[3]. The recompiled original is still linked as
 * recomp_fn_XXXXXXXX so the two can be run against each other.
 */
#include "cpu.h"

/* __OSInitAudioSystem (0x80232B90). Copies a 128-byte DSP program to
 * 0x81000000, DMAs it into ARAM, un-halts the DSP, waits for its mailbox
 * reply, then halts and resets it and restores the memory it borrowed. The
 * program only clears ARAM. The DSP is high-level emulated and ARAM starts
 * zeroed, so there is nothing to do. */
void fn_80232B90(CpuState* s)
{
    (void)s;
}

/* __OSStopAudioSystem (0x80232D4C). The shutdown counterpart. */
void fn_80232D4C(CpuState* s)
{
    (void)s;
}
