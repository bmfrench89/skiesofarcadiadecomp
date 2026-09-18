/* Dolphin SDK MTX library -- the Mtx44 projection builders, which are the
 * plain-C part of it.
 *
 * config/GEAE8P/splits.txt gives 0x80238A14-0x80239638 to sdk/db/db.c, but
 * only the first four functions there are the debugger. From 0x80238B00 on
 * it is the matrix library, and nearly all of that is paired-single `asm`
 * the SDK writes by hand: PSMTXIdentity (0x80238B00), PSMTXCopy
 * (0x80238B2C), PSMTXConcat (0x80238B60), PSMTXTranspose (0x80238C2C),
 * PSMTXInverse (0x80238C7C), PSMTXRotTrig (0x80238DE4),
 * __PSMTXRotAxisRadInternal (0x80238E94), PSMTXTrans (0x80238FB4),
 * PSMTXScale (0x80238FE8), PSMTXQuat (0x80239010), PSMTXMultVec
 * (0x802390B4), PSMTXMultVecArray (0x80239108), PSMTXMultVecSR
 * (0x80239194), PSMTXMultVecArraySR (0x802391E8), PSVECSubtract
 * (0x802393A4), PSVECNormalize (0x802393C8), PSVECSquareMag (0x8023940C),
 * PSVECMag (0x80239424), PSVECDotProduct (0x80239468) and PSVECCrossProduct
 * (0x80239488). None of those can be written in C.
 *
 * This is a prebuilt SDK library, not game code: it matches with mwcc 1.2.5n
 * at -O4,p, whose old-style prologue (mflr; stw r0,4(r1); stwu) the game's
 * own 1.3.2 build does not produce.
 *
 * The float literals below land in .sdata2 in the order they first appear,
 * and the executable's pool proves where the original file boundaries fell:
 * 1.0/0.0/0.5/3.0 for the PSMTX file, then 1.0/2.0/0.0/-1.0 for this pair of
 * Mtx44 builders (mtx44.c), then 0.5/3.0 for the PSVEC file, then
 * 0.0/1.0/0.99999 for C_QUATSlerp at 0x802394C4. So C_QUATSlerp cannot live
 * in this translation unit -- its 1.0f and 0.0f would be folded into this
 * file's literals and then solve to two different addresses -- and it wants
 * a quat.c of its own.
 */
#include "types.h"

typedef f32 Mtx44[4][4];

/* C_MTXFrustum */
void fn_80239270(Mtx44 m, f32 t, f32 b, f32 l, f32 r, f32 n, f32 f)
{
    f32 tmp;

    tmp = 1.0f / (r - l);
    m[0][0] = (2 * n) * tmp;
    m[0][1] = 0.0f;
    m[0][2] = (r + l) * tmp;
    m[0][3] = 0.0f;

    tmp = 1.0f / (t - b);
    m[1][0] = 0.0f;
    m[1][1] = (2 * n) * tmp;
    m[1][2] = (t + b) * tmp;
    m[1][3] = 0.0f;

    tmp = 1.0f / (f - n);
    m[2][0] = 0.0f;
    m[2][1] = 0.0f;
    m[2][2] = -(n)*tmp;
    m[2][3] = -(f * n) * tmp;

    m[3][0] = 0.0f;
    m[3][1] = 0.0f;
    m[3][2] = -1.0f;
    m[3][3] = 0.0f;
}

/* C_MTXOrtho */
void fn_8023930C(Mtx44 m, f32 t, f32 b, f32 l, f32 r, f32 n, f32 f)
{
    f32 tmp;

    tmp = 1.0f / (r - l);
    m[0][0] = 2.0f * tmp;
    m[0][1] = 0.0f;
    m[0][2] = 0.0f;
    m[0][3] = -(r + l) * tmp;

    tmp = 1.0f / (t - b);
    m[1][0] = 0.0f;
    m[1][1] = 2.0f * tmp;
    m[1][2] = 0.0f;
    m[1][3] = -(t + b) * tmp;

    tmp = 1.0f / (f - n);
    m[2][0] = 0.0f;
    m[2][1] = 0.0f;
    m[2][2] = -(1.0f) * tmp;
    m[2][3] = -(f)*tmp;

    m[3][0] = 0.0f;
    m[3][1] = 0.0f;
    m[3][2] = 0.0f;
    m[3][3] = 1.0f;
}
