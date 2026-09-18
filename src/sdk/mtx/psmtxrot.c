/* Dolphin SDK MTX library -- the four rotation routines of ps_matrix.c: the
 * two radian-argument entry points, which are the only ordinary C in that SDK
 * file, and the two paired-single workers they hand a sine and cosine to.
 *
 * All four belong in psmtx.c with the rest of ps_matrix.c, and they are apart
 * from it for two reasons.  The C pair needs `-opt nopeep`: the peephole pass
 * folds away the redundant `fmr f1, f31` that reloads the angle out of its
 * home register and rewrites the register copies from `mr` to `addi rD, rA,
 * 0`, which comes out four bytes short and wrong in six words.  And the asm
 * pair needs the file's whole .sdata2 pool below, which psmtx.c declares only
 * the first half of.  Nothing in psmtx.c can tell `-opt nopeep` from `-O4,p`,
 * since `asm` bodies are emitted verbatim, so the units can be merged once
 * that one carries the option and drops its own Unit10.  mtx.c cannot take
 * them: its Mtx44 builders do need the peephole pass.
 *
 * Prebuilt SDK library: mwcc 1.2.5n, not the game's own 1.3.2.
 */
#include "types.h"

typedef f32 (*MtxPtr)[4];

typedef struct {
    f32 x, y, z;
} Vec;

/* ps_matrix.c's .sdata2 pool, at 0x8034C7C0.  mwcc lays these out in the
 * order the code first reads them, not the order they are declared, and the
 * rotation body below reads 0.0 before 1.0 -- so the pair has to be one object
 * to come out 1.0 first the way the executable has it.  Two objects rather
 * than one keep 0.5 checkable at a zero addend; the +4 halves of each pair are
 * the two words the oracle can only settle by linking. */
static const f32 Unit10[2] = { 1.0F, 0.0F };
static const f32 NewtonRaphson[2] = { 0.5F, 3.0F };

f32 fn_80262A10(f32 x);                                  /* sinf */
f32 fn_80262A34(f32 x);                                  /* cosf */

/* The axis-aligned rotation, from a sine and cosine rather than an angle.  The
 * `ori r0, r4, 0x20` folds 'X' onto 'x' before the three comparisons, so the
 * axis letter may be given in either case  (probably PSMTXRotTrig) */
asm void fn_80238DE4(register MtxPtr m, register u8 axis, register f32 sinA,
                     register f32 cosA)
{
    nofralloc
    frsp        f5, f1
    frsp        f4, f2
    lfs         f0, Unit10+4(r2)
    lfs         f1, Unit10(r2)
    ori         r0, r4, 0x20
    ps_neg      f2, f5
    cmplwi      r0, 120
    beq         _x
    cmplwi      r0, 121
    beq         _y
    cmplwi      r0, 122
    beq         _z
    b           _end
_x:
    psq_st      f1, 0(r3), 1, 0
    psq_st      f0, 4(r3), 0, 0
    ps_merge00  f3, f5, f4
    psq_st      f0, 12(r3), 0, 0
    ps_merge00  f1, f4, f2
    psq_st      f0, 28(r3), 0, 0
    psq_st      f0, 44(r3), 1, 0
    psq_st      f3, 36(r3), 0, 0
    psq_st      f1, 20(r3), 0, 0
    b           _end
_y:
    ps_merge00  f3, f4, f0
    ps_merge00  f1, f0, f1
    psq_st      f0, 24(r3), 0, 0
    psq_st      f3, 0(r3), 0, 0
    ps_merge00  f2, f2, f0
    ps_merge00  f0, f5, f0
    psq_st      f3, 40(r3), 0, 0
    psq_st      f1, 16(r3), 0, 0
    psq_st      f0, 8(r3), 0, 0
    psq_st      f2, 32(r3), 0, 0
    b           _end
_z:
    psq_st      f0, 8(r3), 0, 0
    ps_merge00  f3, f5, f4
    ps_merge00  f2, f4, f2
    psq_st      f0, 24(r3), 0, 0
    psq_st      f0, 32(r3), 0, 0
    ps_merge00  f1, f1, f0
    psq_st      f3, 16(r3), 0, 0
    psq_st      f2, 0(r3), 0, 0
    psq_st      f1, 40(r3), 0, 0
_end:
    blr
}

/* Rotation about an arbitrary axis, which is normalized on the way in -- the
 * frsqrte estimate plus one Newton-Raphson step is where the 0.5 and 3.0 go,
 * and `fadds f8, f10, f10` and `fsubs f1, f10, f10` make the 1.0 and 0.0 the
 * body needs out of the 0.5 already loaded  (probably
 * __PSMTXRotAxisRadInternal) */
asm void fn_80238E94(register MtxPtr m, register const Vec* axis,
                     register f32 sinA, register f32 cosA)
{
    nofralloc
    lfs         f10, NewtonRaphson(r2)
    lfs         f9, NewtonRaphson+4(r2)
    frsp        f11, f2
    psq_l       f2, 0(r4), 0, 0
    frsp        f12, f1
    lfs         f3, 8(r4)
    ps_mul      f4, f2, f2
    fadds       f8, f10, f10
    ps_madd     f5, f3, f3, f4
    fsubs       f1, f10, f10
    ps_sum0     f6, f5, f3, f4
    fsubs       f0, f8, f11
    frsqrte     f7, f6
    fmuls       f4, f7, f7
    fmuls       f5, f7, f10
    fnmsubs     f4, f4, f6, f9
    fmuls       f7, f4, f5
    ps_merge00  f11, f11, f11
    ps_muls0    f2, f2, f7
    ps_muls0    f3, f3, f7
    ps_muls0    f6, f2, f0
    ps_muls0    f10, f2, f12
    ps_muls0    f7, f3, f0
    ps_muls1    f5, f6, f2
    ps_muls0    f4, f6, f2
    ps_muls0    f6, f6, f3
    fnmsubs     f0, f3, f12, f5
    fmadds      f8, f3, f12, f5
    ps_neg      f2, f10
    ps_sum0     f9, f6, f1, f10
    ps_sum0     f4, f4, f0, f11
    ps_sum1     f5, f11, f8, f5
    ps_sum0     f0, f2, f1, f6
    psq_st      f9, 8(r3), 0, 0
    ps_sum0     f2, f6, f6, f2
    psq_st      f4, 0(r3), 0, 0
    ps_muls0    f7, f7, f3
    psq_st      f5, 16(r3), 0, 0
    ps_sum1     f6, f10, f2, f6
    psq_st      f0, 24(r3), 0, 0
    ps_sum0     f7, f7, f1, f11
    psq_st      f6, 32(r3), 0, 0
    psq_st      f7, 40(r3), 0, 0
    blr
}

/* PSMTXRotRad */
void fn_80238D74(MtxPtr m, u8 axis, f32 rad)
{
    f32 sinA, cosA;

    sinA = fn_80262A10(rad);
    cosA = fn_80262A34(rad);
    fn_80238DE4(m, axis, sinA, cosA);
}

/* PSMTXRotAxisRad */
void fn_80238F44(MtxPtr m, const Vec* axis, f32 rad)
{
    f32 sinA, cosA;

    sinA = fn_80262A10(rad);
    cosA = fn_80262A34(rad);
    fn_80238E94(m, axis, sinA, cosA);
}

