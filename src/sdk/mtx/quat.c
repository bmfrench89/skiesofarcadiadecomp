/* Dolphin SDK MTX library -- quaternion spherical interpolation, the whole of
 * the SDK's quat.c that the game links.
 *
 * It sits in its own translation unit because of the .sdata2 pool: the
 * executable's constants run 1.0/0.0/0.5/3.0 for ps_matrix.c, 1.0/2.0/0.0/-1.0
 * for the Mtx44 builders in mtx.c and 0.5/3.0 for ps_vec.c before this file's
 * 0.0/1.0/0.99999 at 0x8034C7E8.  Folding this into any of those would give its
 * 0.0f and 1.0f the earlier file's addresses.
 *
 * The pool's own order is the one thing here that cannot be read off this
 * function.  mwcc allocates a float literal when it first meets it in the
 * source, and this function meets 1.0f first, yet the executable has 0.0f
 * first -- so some earlier function of quat.c used 0.0f before Slerp was ever
 * reached.  The game links none of them, and the linker dropped their code but
 * not their place in the pool.  The static below stands in for whichever one
 * it was: it is inlined away and contributes no code, only the 0.0f.
 *
 * Prebuilt SDK library: mwcc 1.2.5n at -O4,p, not the game's own 1.3.2.
 */
#include "types.h"

typedef struct {
    f32 x, y, z, w;
} Quaternion;

f32 fn_80262A10(f32 x); /* sinf */
f32 fn_80262A58(f32 x); /* acosf */

/* Stands in for the entry points of quat.c the game does not link, the first
 * of which reached 0.0f before this one did.  Nothing calls it and nothing is
 * emitted for it. */
static f32 pool_order_seed(f32 a)
{
    return a < 0.0f ? -a : a;
}

/* C_QUATSlerp */
void fn_802394C4(const Quaternion* p, const Quaternion* q, Quaternion* r, f32 t)
{
    f32 theta, sinTheta, cosTheta;
    f32 sclp, sclq;

    cosTheta = p->x * q->x + p->y * q->y + p->z * q->z + p->w * q->w;
    sclq = 1.0f;
    if (cosTheta < 0.0f) {
        cosTheta = -cosTheta;
        sclq = -sclq;
    }

    /* Past this the two quaternions are close enough that the sines below
     * divide by something near zero, so fall back to the straight lerp. */
    if (cosTheta <= 0.99999f) {
        theta = fn_80262A58(cosTheta);
        sinTheta = fn_80262A10(theta);
        sclp = fn_80262A10((1.0f - t) * theta) / sinTheta;
        sclq = sclq * (fn_80262A10(t * theta) / sinTheta);
    } else {
        sclp = 1.0f - t;
        sclq = sclq * t;
    }

    r->x = sclp * p->x + sclq * q->x;
    r->y = sclp * p->y + sclq * q->y;
    r->z = sclp * p->z + sclq * q->z;
    r->w = sclp * p->w + sclq * q->w;
}
