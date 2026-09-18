/* Dolphin SDK MTX, the paired-single half of the matrix library
 * (src/mtx/ps_matrix.c and ps_vec.c in the SDK), as the game links it.
 * Sixteen routines, every paired-single body in 0x80238B00-0x80239638:
 *
 *   fn_80238B00 identity      fn_80238B2C copy         fn_80238B60 concat
 *   fn_80238C2C transpose     fn_80238C7C inverse      fn_80238FB4 trans
 *   fn_80238FE8 scale         fn_80239010 from quat    fn_802390B4 mult vec
 *   fn_80239108 mult vec []   fn_80239194 mult vec SR  fn_802391E8 mult SR []
 *   fn_802393A4 vec subtract  fn_8023940C square mag   fn_80239468 dot
 *   fn_80239488 cross
 *
 * These are not compiled C in the SDK and they cannot be recovered as C: the
 * bodies are hand-scheduled Gekko paired-single code, with the frame stores
 * interleaved into the load stream (concat) and callee-saved f14/f15/f31 used
 * as scratch.  The same routines written as ordinary C float assignments
 * compile (1.2.5n, -O4,p) to scalar lfs/stfs pairs -- no psq_l, psq_st or
 * ps_* anywhere -- so the SDK's `asm` bodies are reproduced here as `asm`
 * bodies, which is also how the SDK ships them.
 *
 * Two more paired-single leaves in the range, 0x802393C8 (vector normalize)
 * and 0x80239424 (vector magnitude), are left out on purpose: they read a
 * second 0.5f/3.0f pair at 0x8034C7E0, which is 0x18 past this file's own
 * .sdata2 constants, because four floats belonging to the non-paired-single
 * functions of the same translation unit sit in between.  A file holding only
 * these sixteen cannot lay that pool out, so both come out with two wrong
 * displacements; they belong with the rest of ps_matrix.c.
 *
 * Prebuilt SDK library: matches with mwcc 1.2.5n at -O4,p, not the 1.3.2 the
 * game's own code uses.
 */
typedef float f32;
typedef f32 Mtx[3][4];
typedef f32 (*MtxPtr)[4];

/* The {0.0f, 1.0f} pair PSMTXConcat multiplies the fourth column by, and the
 * two scalars the other routines splat with lfs.  Addressed the way the SDK's
 * asm addresses them: Unit01 with a lis/addi pair, the scalars off r2. */
static f32 Unit01[2] = { 0.0F, 1.0F };

/* The 1.0f / 0.0f the splatting lfs pairs read, at 0x8034C7C0 and 0x8034C7C4.
 * They are one adjacent pair in the executable with 1.0f first, but 0.0f is
 * the one this file uses first, and mwcc lays .sdata2 out in order of first
 * use -- two separate constants here come out in the other order.  Writing
 * them as one two-element object pins the layout; the +4 addend is why the
 * two lfs fields read "need a link" rather than verified. */
static const f32 Unit10[2] = { 1.0F, 0.0F };

/* PSMTXIdentity */
asm void fn_80238B00(register MtxPtr m)
{
    nofralloc
    lfs         f0, Unit10+4(r2)
    lfs         f1, Unit10(r2)
    psq_st      f0, 8(r3), 0, 0
    ps_merge01  f2, f0, f1
    psq_st      f0, 24(r3), 0, 0
    ps_merge10  f1, f1, f0
    psq_st      f0, 32(r3), 0, 0
    psq_st      f2, 16(r3), 0, 0
    psq_st      f1, 0(r3), 0, 0
    psq_st      f1, 40(r3), 0, 0
    blr
}

/* PSMTXCopy */
asm void fn_80238B2C(register const MtxPtr src, register MtxPtr dst)
{
    nofralloc
    psq_l       f0, 0(r3), 0, 0
    psq_st      f0, 0(r4), 0, 0
    psq_l       f1, 8(r3), 0, 0
    psq_st      f1, 8(r4), 0, 0
    psq_l       f2, 16(r3), 0, 0
    psq_st      f2, 16(r4), 0, 0
    psq_l       f3, 24(r3), 0, 0
    psq_st      f3, 24(r4), 0, 0
    psq_l       f4, 32(r3), 0, 0
    psq_st      f4, 32(r4), 0, 0
    psq_l       f5, 40(r3), 0, 0
    psq_st      f5, 40(r4), 0, 0
    blr
}

/* PSMTXConcat */
asm void fn_80238B60(register const MtxPtr a, register const MtxPtr b,
                     register MtxPtr ab)
{
    nofralloc
    stwu        r1, -64(r1)
    psq_l       f0, 0(r3), 0, 0
    stfd        f14, 8(r1)
    psq_l       f6, 0(r4), 0, 0
    lis         r6, Unit01@ha
    psq_l       f7, 8(r4), 0, 0
    stfd        f15, 16(r1)
    addi        r6, r6, Unit01@l
    stfd        f31, 40(r1)
    psq_l       f8, 16(r4), 0, 0
    ps_muls0    f12, f6, f0
    psq_l       f2, 16(r3), 0, 0
    ps_muls0    f13, f7, f0
    psq_l       f31, 0(r6), 0, 0
    ps_muls0    f14, f6, f2
    psq_l       f9, 24(r4), 0, 0
    ps_muls0    f15, f7, f2
    psq_l       f1, 8(r3), 0, 0
    ps_madds1   f12, f8, f0, f12
    psq_l       f3, 24(r3), 0, 0
    ps_madds1   f14, f8, f2, f14
    psq_l       f10, 32(r4), 0, 0
    ps_madds1   f13, f9, f0, f13
    psq_l       f11, 40(r4), 0, 0
    ps_madds1   f15, f9, f2, f15
    psq_l       f4, 32(r3), 0, 0
    psq_l       f5, 40(r3), 0, 0
    ps_madds0   f12, f10, f1, f12
    ps_madds0   f13, f11, f1, f13
    ps_madds0   f14, f10, f3, f14
    ps_madds0   f15, f11, f3, f15
    psq_st      f12, 0(r5), 0, 0
    ps_muls0    f2, f6, f4
    ps_madds1   f13, f31, f1, f13
    ps_muls0    f0, f7, f4
    psq_st      f14, 16(r5), 0, 0
    ps_madds1   f15, f31, f3, f15
    psq_st      f13, 8(r5), 0, 0
    ps_madds1   f2, f8, f4, f2
    ps_madds1   f0, f9, f4, f0
    ps_madds0   f2, f10, f5, f2
    lfd         f14, 8(r1)
    psq_st      f15, 24(r5), 0, 0
    ps_madds0   f0, f11, f5, f0
    psq_st      f2, 32(r5), 0, 0
    ps_madds1   f0, f31, f5, f0
    lfd         f15, 16(r1)
    psq_st      f0, 40(r5), 0, 0
    lfd         f31, 40(r1)
    addi        r1, r1, 64
    blr
}

/* PSMTXTranspose */
asm void fn_80238C2C(register const MtxPtr src, register MtxPtr xPose)
{
    nofralloc
    lfs         f0, Unit10+4(r2)
    psq_l       f1, 0(r3), 0, 0
    stfs        f0, 44(r4)
    psq_l       f2, 16(r3), 0, 0
    ps_merge00  f4, f1, f2
    psq_l       f3, 8(r3), 1, 0
    ps_merge11  f5, f1, f2
    psq_l       f2, 24(r3), 1, 0
    psq_st      f4, 0(r4), 0, 0
    psq_l       f1, 32(r3), 0, 0
    ps_merge00  f2, f3, f2
    psq_st      f5, 16(r4), 0, 0
    ps_merge00  f4, f1, f0
    psq_st      f2, 32(r4), 0, 0
    ps_merge10  f5, f1, f0
    psq_st      f4, 8(r4), 0, 0
    lfs         f3, 40(r3)
    psq_st      f5, 24(r4), 0, 0
    stfs        f3, 40(r4)
    blr
}

/* PSMTXInverse */
asm int fn_80238C7C(register const MtxPtr src, register MtxPtr inv)
{
    nofralloc
    psq_l       f0, 0(r3), 1, 0
    psq_l       f1, 4(r3), 0, 0
    psq_l       f2, 16(r3), 1, 0
    ps_merge10  f6, f1, f0
    psq_l       f3, 20(r3), 0, 0
    psq_l       f4, 32(r3), 1, 0
    ps_merge10  f7, f3, f2
    psq_l       f5, 36(r3), 0, 0
    ps_mul      f11, f3, f6
    ps_mul      f13, f5, f7
    ps_merge10  f8, f5, f4
    ps_msub     f11, f1, f7, f11
    ps_mul      f12, f1, f8
    ps_msub     f13, f3, f8, f13
    ps_mul      f10, f3, f4
    ps_msub     f12, f5, f6, f12
    ps_mul      f9, f0, f5
    ps_mul      f8, f1, f2
    ps_sub      f6, f6, f6
    ps_msub     f10, f2, f5, f10
    ps_mul      f7, f0, f13
    ps_msub     f9, f1, f4, f9
    ps_madd     f7, f2, f12, f7
    ps_msub     f8, f0, f3, f8
    ps_madd     f7, f4, f11, f7
    ps_cmpo0    cr0, f7, f6
    bne         _det_ok
    li          r3, 0
    blr
_det_ok:
    fres        f0, f7
    ps_add      f6, f0, f0
    ps_mul      f5, f0, f0
    ps_nmsub    f0, f7, f5, f6
    lfs         f1, 12(r3)
    ps_muls0    f13, f13, f0
    lfs         f2, 28(r3)
    ps_muls0    f12, f12, f0
    lfs         f3, 44(r3)
    ps_muls0    f11, f11, f0
    ps_merge00  f5, f13, f12
    ps_muls0    f10, f10, f0
    ps_merge11  f4, f13, f12
    ps_muls0    f9, f9, f0
    psq_st      f5, 0(r4), 0, 0
    ps_mul      f6, f13, f1
    psq_st      f4, 16(r4), 0, 0
    ps_muls0    f8, f8, f0
    ps_madd     f6, f12, f2, f6
    psq_st      f10, 32(r4), 1, 0
    ps_nmadd    f6, f11, f3, f6
    psq_st      f9, 36(r4), 1, 0
    ps_mul      f7, f10, f1
    ps_merge00  f5, f11, f6
    psq_st      f8, 40(r4), 1, 0
    ps_merge11  f4, f11, f6
    psq_st      f5, 8(r4), 0, 0
    ps_madd     f7, f9, f2, f7
    psq_st      f4, 24(r4), 0, 0
    ps_nmadd    f7, f8, f3, f7
    li          r3, 1
    psq_st      f7, 44(r4), 1, 0
    blr
}

typedef struct { f32 x, y, z; } Vec;

/* PSVECAdd's sibling: subtract, a - b -> ab  (probably PSVECSubtract) */
asm void fn_802393A4(register const Vec* a, register const Vec* b,
                     register Vec* ab)
{
    nofralloc
    psq_l       f2, 0(r3), 0, 0
    psq_l       f4, 0(r4), 0, 0
    ps_sub      f6, f2, f4
    psq_st      f6, 0(r5), 0, 0
    psq_l       f3, 8(r3), 1, 0
    psq_l       f5, 8(r4), 1, 0
    ps_sub      f7, f3, f5
    psq_st      f7, 8(r5), 1, 0
    blr
}

/* x*x + y*y + z*z  (probably PSVECSquareMag) */
asm f32 fn_8023940C(register const Vec* v)
{
    nofralloc
    psq_l       f0, 0(r3), 0, 0
    ps_mul      f0, f0, f0
    lfs         f1, 8(r3)
    ps_madd     f1, f1, f1, f0
    ps_sum0     f1, f1, f0, f0
    blr
}

/* a . b  (probably PSVECDotProduct) */
asm f32 fn_80239468(register const Vec* a, register const Vec* b)
{
    nofralloc
    psq_l       f2, 4(r3), 0, 0
    psq_l       f3, 4(r4), 0, 0
    ps_mul      f2, f2, f3
    psq_l       f5, 0(r3), 0, 0
    psq_l       f4, 0(r4), 0, 0
    ps_madd     f3, f5, f4, f2
    ps_sum0     f1, f3, f2, f2
    blr
}

/* a x b -> axb  (probably PSVECCrossProduct) */
asm void fn_80239488(register const Vec* a, register const Vec* b,
                     register Vec* axb)
{
    nofralloc
    psq_l       f1, 0(r4), 0, 0
    lfs         f2, 8(r3)
    psq_l       f0, 0(r3), 0, 0
    ps_merge10  f6, f1, f1
    lfs         f3, 8(r4)
    ps_mul      f4, f1, f2
    ps_muls0    f7, f1, f0
    ps_msub     f5, f0, f3, f4
    ps_msub     f8, f0, f6, f7
    ps_merge11  f9, f5, f5
    ps_merge01  f10, f5, f8
    psq_st      f9, 0(r5), 1, 0
    ps_neg      f10, f10
    psq_st      f10, 4(r5), 0, 0
    blr
}

/* m * src -> dst, translation included  (probably PSMTXMultVec) */
asm void fn_802390B4(register const MtxPtr m, register const Vec* src,
                     register Vec* dst)
{
    nofralloc
    psq_l       f0, 0(r4), 0, 0
    psq_l       f2, 0(r3), 0, 0
    psq_l       f1, 8(r4), 1, 0
    ps_mul      f4, f2, f0
    psq_l       f3, 8(r3), 0, 0
    ps_madd     f5, f3, f1, f4
    psq_l       f8, 16(r3), 0, 0
    ps_sum0     f6, f5, f6, f5
    psq_l       f9, 24(r3), 0, 0
    ps_mul      f10, f8, f0
    psq_st      f6, 0(r5), 1, 0
    ps_madd     f11, f9, f1, f10
    psq_l       f2, 32(r3), 0, 0
    ps_sum0     f12, f11, f12, f11
    psq_l       f3, 40(r3), 0, 0
    ps_mul      f4, f2, f0
    psq_st      f12, 4(r5), 1, 0
    ps_madd     f5, f3, f1, f4
    ps_sum0     f6, f5, f6, f5
    psq_st      f6, 8(r5), 1, 0
    blr
}

/* m * src -> dst, the row-dot form  (probably PSMTXMultVecSR's sibling) */
asm void fn_80239194(register const MtxPtr m, register const Vec* src,
                     register Vec* dst)
{
    nofralloc
    psq_l       f0, 0(r3), 0, 0
    psq_l       f6, 0(r4), 0, 0
    psq_l       f2, 16(r3), 0, 0
    ps_mul      f8, f0, f6
    psq_l       f4, 32(r3), 0, 0
    ps_mul      f10, f2, f6
    psq_l       f7, 8(r4), 1, 0
    ps_mul      f12, f4, f6
    psq_l       f3, 24(r3), 0, 0
    ps_sum0     f8, f8, f8, f8
    psq_l       f5, 40(r3), 0, 0
    ps_sum0     f10, f10, f10, f10
    psq_l       f1, 8(r3), 0, 0
    ps_sum0     f12, f12, f12, f12
    ps_madd     f9, f1, f7, f8
    psq_st      f9, 0(r5), 1, 0
    ps_madd     f11, f3, f7, f10
    psq_st      f11, 4(r5), 1, 0
    ps_madd     f13, f5, f7, f12
    psq_st      f13, 8(r5), 1, 0
    blr
}

/* m * srcBase[count] -> dstBase[count]  (probably PSMTXMultVecArray) */
asm void fn_80239108(register const MtxPtr m, register const Vec* srcBase,
                     register Vec* dstBase, register unsigned long count)
{
    nofralloc
    psq_l       f13, 0(r3), 0, 0
    psq_l       f12, 16(r3), 0, 0
    addi        r6, r6, -1
    psq_l       f11, 8(r3), 0, 0
    ps_merge00  f0, f13, f12
    addi        r5, r5, -4
    psq_l       f10, 24(r3), 0, 0
    ps_merge11  f1, f13, f12
    mtctr       r6
    psq_l       f4, 32(r3), 0, 0
    ps_merge00  f2, f11, f10
    psq_l       f5, 40(r3), 0, 0
    ps_merge11  f3, f11, f10
    psq_l       f6, 0(r4), 0, 0
    psq_lu      f7, 8(r4), 1, 0
    ps_madds0   f8, f0, f6, f3
    ps_mul      f9, f4, f6
    ps_madds1   f8, f1, f6, f8
    ps_madd     f10, f5, f7, f9
_loop:
    psq_lu      f6, 4(r4), 0, 0
    ps_madds0   f12, f2, f7, f8
    psq_lu      f7, 8(r4), 1, 0
    ps_sum0     f13, f10, f9, f10
    ps_madds0   f8, f0, f6, f3
    ps_mul      f9, f4, f6
    psq_stu     f12, 4(r5), 0, 0
    ps_madds1   f8, f1, f6, f8
    psq_stu     f13, 8(r5), 1, 0
    ps_madd     f10, f5, f7, f9
    bdnz        _loop
    ps_madds0   f12, f2, f7, f8
    ps_sum0     f13, f10, f9, f10
    psq_stu     f12, 4(r5), 0, 0
    psq_stu     f13, 8(r5), 1, 0
    blr
}

typedef struct { f32 x, y, z, w; } Quaternion;

/* rotation matrix from a unit quaternion  (probably PSMTXQuat) */
asm void fn_80239010(register MtxPtr m, register const Quaternion* q)
{
    nofralloc
    lfs         f1, Unit10(r2)
    psq_l       f4, 0(r4), 0, 0
    psq_l       f5, 8(r4), 0, 0
    fsubs       f0, f1, f1
    fadds       f2, f1, f1
    ps_mul      f6, f4, f4
    ps_merge10  f9, f4, f4
    ps_madd     f8, f5, f5, f6
    ps_mul      f7, f5, f5
    ps_sum0     f3, f8, f8, f8
    ps_muls1    f10, f9, f5
    fres        f11, f3
    ps_sum1     f8, f7, f8, f6
    ps_nmsub    f3, f3, f11, f2
    ps_muls1    f7, f5, f5
    ps_mul      f3, f11, f3
    ps_sum0     f6, f6, f6, f6
    fmuls       f3, f3, f2
    ps_madd     f11, f4, f9, f7
    ps_msub     f7, f4, f9, f7
    psq_st      f0, 12(r3), 1, 0
    ps_nmsub    f6, f6, f3, f1
    ps_nmsub    f8, f8, f3, f1
    psq_st      f0, 44(r3), 1, 0
    ps_mul      f11, f11, f3
    ps_mul      f7, f7, f3
    psq_st      f6, 40(r3), 1, 0
    ps_madds0   f9, f4, f5, f10
    ps_merge00  f5, f11, f8
    ps_nmsub    f10, f10, f2, f9
    ps_merge10  f4, f8, f7
    psq_st      f5, 16(r3), 0, 0
    ps_mul      f9, f9, f3
    ps_mul      f10, f10, f3
    psq_st      f4, 0(r3), 0, 0
    psq_st      f9, 8(r3), 1, 0
    ps_merge10  f7, f10, f0
    ps_merge01  f11, f10, f9
    psq_st      f7, 24(r3), 0, 0
    psq_st      f11, 32(r3), 0, 0
    blr
}

/* the rotation-only array form  (probably PSMTXMultVecArraySR) */
asm void fn_802391E8(register const MtxPtr m, register const Vec* srcBase,
                     register Vec* dstBase, register unsigned long count)
{
    nofralloc
    psq_l       f13, 0(r3), 0, 0
    psq_l       f12, 16(r3), 0, 0
    addi        r6, r6, -1
    psq_l       f11, 8(r3), 1, 0
    ps_merge00  f0, f13, f12
    addi        r5, r5, -4
    psq_l       f10, 24(r3), 1, 0
    ps_merge11  f1, f13, f12
    mtctr       r6
    psq_l       f3, 32(r3), 0, 0
    ps_merge00  f2, f11, f10
    psq_l       f4, 40(r3), 1, 0
    psq_l       f6, 0(r4), 0, 0
    psq_lu      f7, 8(r4), 1, 0
    ps_muls0    f8, f0, f6
    ps_mul      f9, f3, f6
    ps_madds1   f8, f1, f6, f8
    ps_madd     f10, f4, f7, f9
_loop2:
    psq_lu      f6, 4(r4), 0, 0
    ps_madds0   f12, f2, f7, f8
    psq_lu      f7, 8(r4), 1, 0
    ps_sum0     f13, f10, f9, f9
    ps_muls0    f8, f0, f6
    ps_mul      f9, f3, f6
    psq_stu     f12, 4(r5), 0, 0
    ps_madds1   f8, f1, f6, f8
    psq_stu     f13, 8(r5), 1, 0
    ps_madd     f10, f4, f7, f9
    bdnz        _loop2
    ps_madds0   f12, f2, f7, f8
    ps_sum0     f13, f10, f9, f9
    psq_stu     f12, 4(r5), 0, 0
    psq_stu     f13, 8(r5), 1, 0
    blr
}

/* translation matrix  (probably PSMTXTrans) */
asm void fn_80238FB4(register MtxPtr m, register f32 x, register f32 y,
                     register f32 z)
{
    nofralloc
    lfs         f0, Unit10+4(r2)
    lfs         f4, Unit10(r2)
    stfs        f1, 12(r3)
    stfs        f2, 28(r3)
    psq_st      f0, 4(r3), 0, 0
    psq_st      f0, 32(r3), 0, 0
    stfs        f0, 16(r3)
    stfs        f4, 20(r3)
    stfs        f0, 24(r3)
    stfs        f4, 40(r3)
    stfs        f3, 44(r3)
    stfs        f4, 0(r3)
    blr
}

/* scale matrix  (probably PSMTXScale) */
asm void fn_80238FE8(register MtxPtr m, register f32 x, register f32 y,
                     register f32 z)
{
    nofralloc
    lfs         f0, Unit10+4(r2)
    stfs        f1, 0(r3)
    psq_st      f0, 4(r3), 0, 0
    psq_st      f0, 12(r3), 0, 0
    stfs        f2, 20(r3)
    psq_st      f0, 24(r3), 0, 0
    psq_st      f0, 32(r3), 0, 0
    stfs        f3, 40(r3)
    stfs        f0, 44(r3)
    blr
}
