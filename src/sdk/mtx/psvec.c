/* Dolphin SDK MTX library -- the two paired-single vector routines that carry
 * their own .sdata2 constants (src/mtx/ps_vec.c in the SDK).
 *
 * The other four ps_vec bodies the game links -- subtract, square magnitude,
 * dot and cross -- reference no constants at all, so psmtx.c already holds
 * them and they are not repeated here.  These two do: both run the Gekko
 * frsqrte estimate through one Newton-Raphson step, which needs 0.5 and 3.0,
 * and in the executable that pair sits at 0x8034C7E0, after ps_matrix.c's four
 * constants and mtx.c's four.  A file has to own the pair to put it first in
 * its own .sdata2, which is why these two cannot live in psmtx.c.
 *
 * Hand-scheduled paired-single code, as `asm` here because it is `asm` in the
 * SDK: no C expression produces psq_l or ps_madd from mwcc 1.2.5n.
 *
 * Prebuilt SDK library: mwcc 1.2.5n at -O4,p, not the game's own 1.3.2.
 */
typedef float f32;

typedef struct {
    f32 x, y, z;
} Vec;

/* The Newton-Raphson pair, separate objects rather than one array so every
 * reference carries a zero addend and can be checked outright. */
static const f32 Half = 0.5F;
static const f32 Three = 3.0F;

/* v / |v| -> unit  (probably PSVECNormalize) */
asm void fn_802393C8(register const Vec* v, register Vec* unit)
{
    nofralloc
    lfs         f0, Half(r2)
    lfs         f1, Three(r2)
    psq_l       f2, 0(r3), 0, 0
    ps_mul      f5, f2, f2
    psq_l       f3, 8(r3), 1, 0
    ps_madd     f4, f3, f3, f5
    ps_sum0     f4, f4, f3, f5
    frsqrte     f5, f4
    fmuls       f6, f5, f5
    fmuls       f0, f5, f0
    fnmsubs     f6, f6, f4, f1
    fmuls       f5, f6, f0
    ps_muls0    f2, f2, f5
    psq_st      f2, 0(r4), 0, 0
    ps_muls0    f3, f3, f5
    psq_st      f3, 8(r4), 1, 0
    blr
}

/* |v|, and exactly zero when the square magnitude is exactly zero, since the
 * reciprocal-square-root estimate has no answer there  (probably PSVECMag) */
asm f32 fn_80239424(register const Vec* v)
{
    nofralloc
    lfs         f4, Half(r2)
    psq_l       f0, 0(r3), 0, 0
    ps_mul      f0, f0, f0
    lfs         f1, 8(r3)
    fsubs       f2, f4, f4
    ps_madd     f1, f1, f1, f0
    ps_sum0     f1, f1, f0, f0
    fcmpu       cr0, f1, f2
    beq         _done
    frsqrte     f0, f1
    lfs         f3, Three(r2)
    fmuls       f2, f0, f0
    fmuls       f0, f0, f4
    fnmsubs     f2, f2, f1, f3
    fmuls       f0, f2, f0
    fmuls       f1, f1, f0
_done:
    blr
}
