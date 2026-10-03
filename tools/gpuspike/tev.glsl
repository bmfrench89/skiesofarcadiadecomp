// The TEV, transcribed from tev_pixel's general path (runtime/gxr_tev.c):
// specs/gpu-backend.md 3.4. All integer, so the transcription can be exact,
// and V3b's tevdiff holds it exact against the C over setups tev_prepare
// built from random registers. The H15c fast shapes are not here: they give
// the same numbers, which tevdiff also checks.
//
// The includer provides two functions:
//   uint  tev_word(uint i)               word i of the draw's packed setup
//   ivec4 tev_sample(uint map, uint tc)  the texel a stage samples, 0..255
// The setup is what gxv_pack_tev writes from a TevSetup:
//   word 0          the stage count
//   word 1          the alpha compare: aref0 | aref1 << 8 | acomp0 << 16 |
//                   acomp1 << 19 | alogic << 22
//   words 2-17      reg_init[4][4], s11, as ints
//   words 18-       five a stage:
//     0  ia[0..2] | ib[0..2] << 15, five bits each (input bank indices)
//     1  ic[0..2] | id[0..2] << 15
//     2  ja | jb << 5 | jc << 10 | jd << 15 | texmap << 20 | texcoord << 23 |
//        texen << 26 | chan << 27
//     3  cbias | cop << 2 | cclamp << 3 | cshift << 4 | cdest << 6 |
//        abias << 8 | aop << 10 | aclamp << 11 | ashift << 12 | adest << 14 |
//        rswap << 16 | tswap << 24 (two bits a channel)
//     4  konst r | g << 8 | b << 16 | a << 24

// The input bank (gxr.h): the four registers, then the texel, the raster
// colour, the konst, and the constants one, half and zero.
const int TEV_BANK_TEX = 16, TEV_BANK_RAS = 20, TEV_BANK_KONST = 24;
const int TEV_BANK_ONE = 28, TEV_BANK_HALF = 29, TEV_BANK_ZERO = 30;

int tev_clamp255(int v) { return clamp(v, 0, 255); }
int tev_clamp_s11(int v) { return clamp(v, -1024, 1023); }

// The clamp a stage asks for; GXV_MUTATE_CLAMP flips it, which tevdiff
// must catch.
int tev_clamped(uint clamp_bit, int r)
{
#ifdef GXV_MUTATE_CLAMP
    return clamp_bit != 0u ? tev_clamp_s11(r) : tev_clamp255(r);
#else
    return clamp_bit != 0u ? tev_clamp255(r) : tev_clamp_s11(r);
#endif
}

bool tev_compare(uint mode, int a, int b)
{
    switch (mode) {
    case 0u: return false;
    case 1u: return a < b;
    case 2u: return a == b;
    case 3u: return a <= b;
    case 4u: return a > b;
    case 5u: return a != b;
    case 6u: return a >= b;
    default: return true;
    }
}

// alpha_passes: the two compares and their logic.
bool tev_alpha_passes(uint ac, int alpha)
{
    bool p0 = tev_compare((ac >> 16) & 7u, alpha, int(ac & 255u));
    bool p1 = tev_compare((ac >> 19) & 7u, alpha, int((ac >> 8) & 255u));
    switch ((ac >> 22) & 3u) {
    case 0u: return p0 && p1;
    case 1u: return p0 || p1;
    case 2u: return p0 != p1;
    default: return p0 == p1;
    }
}

// The shift a stage's result takes: 1 and 2 left, 3 a halving.
int tev_shifted(uint shift, int r)
{
    if (shift == 1u) return r << 1;
    if (shift == 2u) return r << 2;
    if (shift == 3u) return r >> 1;
    return r;
}

// The lerp: (a(256 - c') + b c' + 128) >> 8, c' = c + (c >> 7), on the low
// bytes of a, b and c, negated for subtract.
int tev_lerp(int a, int b, int c, uint op)
{
    int cc = c + (c >> 7);
    int v = (a * (256 - cc) + b * cc + 128) >> 8;
    return op != 0u ? -v : v;
}

void tev_run(ivec4 ras0, ivec4 ras1, out ivec4 outc, out bool pass)
{
    int bank[32];
    uint i, st;
    for (i = 0u; i < 16u; i++) bank[i] = int(tev_word(2u + i));
    for (i = 16u; i < 32u; i++) bank[i] = 0;
    bank[TEV_BANK_ONE] = 255;
    bank[TEV_BANK_HALF] = 128;
    bank[TEV_BANK_ZERO] = 0;

    uint stages = tev_word(0u);
    for (st = 0u; st < stages; st++) {
        uint o = 18u + st * 5u;
        uint w0 = tev_word(o), w1 = tev_word(o + 1u), w2 = tev_word(o + 2u), w3 = tev_word(o + 3u), w4 = tev_word(o + 4u);
        uint texmap = (w2 >> 20) & 7u, texcoord = (w2 >> 23) & 7u, texen = (w2 >> 26) & 1u, chan = (w2 >> 27) & 7u;
        uint cbias = w3 & 3u, cop = (w3 >> 2) & 1u, cclamp = (w3 >> 3) & 1u, cshift = (w3 >> 4) & 3u, cdest = (w3 >> 6) & 3u;
        uint abias = (w3 >> 8) & 3u, aop = (w3 >> 10) & 1u, aclamp = (w3 >> 11) & 1u, ashift = (w3 >> 12) & 3u, adest = (w3 >> 14) & 3u;

        if (texen != 0u) {
            ivec4 t = tev_sample(texmap, texcoord);
            for (i = 0u; i < 4u; i++) bank[TEV_BANK_TEX + int(i)] = t[(w3 >> (24u + 2u * i)) & 3u];
        }
        if (chan < 2u) {
            ivec4 r = chan == 0u ? ras0 : ras1;
            for (i = 0u; i < 4u; i++) bank[TEV_BANK_RAS + int(i)] = r[(w3 >> (16u + 2u * i)) & 3u];
        }
        for (i = 0u; i < 4u; i++) bank[TEV_BANK_KONST + int(i)] = int((w4 >> (8u * i)) & 255u);

        // Colour
        int res[3];
        if (cbias != 3u) {
            int bias = cbias == 1u ? 128 : cbias == 2u ? -128 : 0;
            for (i = 0u; i < 3u; i++) {
                int a = bank[(w0 >> (5u * i)) & 31u] & 255, b = bank[(w0 >> (15u + 5u * i)) & 31u] & 255;
                int c = bank[(w1 >> (5u * i)) & 31u] & 255, d = bank[(w1 >> (15u + 5u * i)) & 31u];
                res[i] = tev_clamped(cclamp, tev_shifted(cshift, d + tev_lerp(a, b, c, cop) + bias));
            }
        } else {
            // The compare modes: (cshift << 1) | cop. R8, GR16 and BGR24
            // compare the low channels as one number; RGB8 per channel.
            uint cmp = (cshift << 1) | cop;
            int a[3], b[3], c[3], d[3];
            for (i = 0u; i < 3u; i++) {
                a[i] = bank[(w0 >> (5u * i)) & 31u] & 255;
                b[i] = bank[(w0 >> (15u + 5u * i)) & 31u] & 255;
                c[i] = bank[(w1 >> (5u * i)) & 31u];
                d[i] = bank[(w1 >> (15u + 5u * i)) & 31u];
            }
            int r3 = -1;
            uint mode = cmp >> 1;
            bool eq = (cmp & 1u) != 0u;
            if (mode == 0u) {
                r3 = (eq ? a[0] == b[0] : a[0] > b[0]) ? 1 : 0;
            } else if (mode == 1u) {
                int av = (a[1] << 8) | a[0], bv = (b[1] << 8) | b[0];
                r3 = (eq ? av == bv : av > bv) ? 1 : 0;
            } else if (mode == 2u) {
                int av = (a[2] << 16) | (a[1] << 8) | a[0], bv = (b[2] << 16) | (b[1] << 8) | b[0];
                r3 = (eq ? av == bv : av > bv) ? 1 : 0;
            }
            for (i = 0u; i < 3u; i++) {
                bool take = r3 == -1 ? (eq ? a[i] == b[i] : a[i] > b[i]) : r3 != 0;
                res[i] = tev_clamped(cclamp, (take ? c[i] : 0) + d[i]);
            }
        }
        bank[cdest * 4u] = res[0];
        bank[cdest * 4u + 1u] = res[1];
        bank[cdest * 4u + 2u] = res[2];

        // Alpha
        int ja = bank[w2 & 31u] & 255, jb = bank[(w2 >> 5) & 31u] & 255;
        int jc = bank[(w2 >> 10) & 31u], jd = bank[(w2 >> 15) & 31u];
        int ra;
        if (abias != 3u) {
            int bias = abias == 1u ? 128 : abias == 2u ? -128 : 0;
            ra = tev_clamped(aclamp, tev_shifted(ashift, jd + tev_lerp(ja, jb, jc & 255, aop) + bias));
        } else {
            uint cmp = (ashift << 1) | aop;
            bool take = (cmp & 1u) != 0u ? ja == jb : ja > jb;
            ra = tev_clamped(aclamp, jd + (take ? jc : 0));
        }
        bank[adest * 4u + 3u] = ra;
    }
    outc = ivec4(tev_clamp255(bank[0]), tev_clamp255(bank[1]), tev_clamp255(bank[2]), tev_clamp255(bank[3]));
    pass = tev_alpha_passes(tev_word(1u), outc.a);
}
