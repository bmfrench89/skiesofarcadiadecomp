/* Dolphin SDK PPCArch: the whole library, 0x802319E0-0x80231AD0.  Seventeen
 * leaves that move a special-purpose register, which the SDK writes as
 * Metrowerks function-level `asm` blocks -- there is no C for `mfmsr` or
 * `mtfsf` -- plus one ordinary C function, PPCDisableSpeculation, which is
 * the only one here with a prologue.
 *
 * This is a prebuilt SDK library, not game code: it matches with mwcc 1.2.5n
 * at -O4,p, whose old-style prologue (mflr r0; stw r0,4(r1); stwu) the game's
 * own 1.3.2 build does not produce.
 *
 * Three of the seventeen are unnamed in config/functions.tsv, so they keep
 * their fn_ names here; the comment above each gives the SDK's name. */
#include "types.h"

/* SPR numbers, as the assembler wants them (the split 5+5 encoding is the
 * assembler's problem, not ours). */
#define SPR_DEC   22
#define SPR_HID0  1008
#define SPR_L2CR  1017
#define SPR_HID2  920
#define SPR_WPAR  921

asm u32 PPCMfmsr(void)
{
    nofralloc
    mfmsr r3
    blr
}

asm void PPCMtmsr(register u32 newMSR)
{
    nofralloc
    mtmsr newMSR
    blr
}

asm u32 PPCMfhid0(void)
{
    nofralloc
    mfspr r3, SPR_HID0
    blr
}

/* PPCMthid0 */
asm void fn_802319F8(register u32 newHID0)
{
    nofralloc
    mtspr SPR_HID0, newHID0
    blr
}

asm u32 PPCMfl2cr(void)
{
    nofralloc
    mfspr r3, SPR_L2CR
    blr
}

asm void PPCMtl2cr(register u32 newL2cr)
{
    nofralloc
    mtspr SPR_L2CR, newL2cr
    blr
}

asm void PPCMtdec(register u32 newDec)
{
    nofralloc
    mtspr SPR_DEC, newDec
    blr
}

/* PPCSync -- `sc`, not `sync`: the SDK's PPCSync traps to the exception
 * handler rather than ordering the store queue. */
asm void fn_80231A18(void)
{
    nofralloc
    sc
    blr
}

asm void PPCHalt(void)
{
    nofralloc
    sync
_halt:
    nop
    li r3, 0
    nop
    b _halt
}

/* The FPSCR is a floating-point register, so reading it into r3 means a round
 * trip through the stack: mffs writes the low word of an f64. */
asm u32 PPCMffpscr(void)
{
    nofralloc
    stwu r1, -24(r1)
    stfd f31, 16(r1)
    mffs f31
    stfd f31, 8(r1)
    lwz r3, 12(r1)
    lfd f31, 16(r1)
    addi r1, r1, 24
    blr
}

asm void PPCMtfpscr(register u32 newFPSCR)
{
    nofralloc
    stwu r1, -32(r1)
    stfd f31, 24(r1)
    li r4, 0
    stw r4, 16(r1)
    stw newFPSCR, 20(r1)
    lfd f31, 16(r1)
    mtfsf 255, f31
    lfd f31, 24(r1)
    addi r1, r1, 32
    blr
}

asm u32 PPCMfhid2(void)
{
    nofralloc
    mfspr r3, SPR_HID2
    blr
}

asm void PPCMthid2(register u32 newHID2)
{
    nofralloc
    mtspr SPR_HID2, newHID2
    blr
}

/* PPCMfwpar -- the sync drains the write-gather pipe before the read. */
asm u32 fn_80231A8C(void)
{
    nofralloc
    sync
    mfspr r3, SPR_WPAR
    blr
}

asm void PPCMtwpar(register u32 newWPAR)
{
    nofralloc
    mtspr SPR_WPAR, newWPAR
    blr
}

/* HID0[SPD], bit 22: disable speculative cache access. */
#define HID0_SPD 0x00000200

void PPCDisableSpeculation(void)
{
    u32 hid0;

    hid0 = PPCMfhid0();
    hid0 |= HID0_SPD;
    fn_802319F8(hid0);
}

asm void PPCSetFpNonIEEEMode(void)
{
    nofralloc
    mtfsb1 29
    blr
}
