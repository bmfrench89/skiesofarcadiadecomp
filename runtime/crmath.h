/*
 * Correctly rounded exp2f and log2f for the renderer (portability.md 3.8, L6).
 *
 * UCRT's exp2f and log2f are not correctly rounded: over the domains the
 * renderer feeds them, 74,154 and 313,550 of their outputs differ from the
 * true value rounded (2.5), and glibc's and bionic's differ on other inputs.
 * Fog and texture LOD would then draw differently by platform. A correctly
 * rounded function has one answer on every platform, whatever its code does
 * inside. These are CORE-MATH's binary32 exp2f and log2f
 * (https://core-math.gitlabpages.inria.fr/, commit 8ea8ea35 of 2026-02-21),
 * by Alexei Sibidanov, under the MIT licence reproduced above each one and
 * named in NOTICE. tools/citest/libm_check.py holds them to correct rounding
 * over every input the renderer can give them, and their outputs to
 * config/libm.tsv.
 *
 * Changed from upstream, and nothing else (the substitutions are listed one
 * by one in the commit that added this file):
 * - static, renamed soa_exp2f and soa_log2f, and each one's as_special named
 *   for its function;
 * - the GCC builtins behind CM_EXPECT, CM_NOINLINE and cm_clz, and fmax for
 *   __builtin_fmax, so that MSVC builds them;
 * - the constants upstream makes by dividing by zero or overflowing (to raise
 *   floating-point exceptions) written as the bits they produce: MSVC refuses
 *   a constant division by zero. The NaN is the positive quiet one;
 * - an explicit (float) wherever upstream converts double to float
 *   implicitly, which MSVC warns about (C4244) and which converts the same;
 * - no #pragma STDC FENV_ACCESS and no errno: the renderer reads neither the
 *   exception flags nor errno, and the values are the same under the default
 *   rounding mode;
 * - the two files' typedefs shared.
 * A header of static functions, so the renderer still links alone (3.1).
 */
#ifndef SOA_CRMATH_H
#define SOA_CRMATH_H
#include <math.h>
#include <stdint.h>

#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#define CM_EXPECT(x, v) (x)
#define CM_NOINLINE __declspec(noinline)
static __inline int cm_clz(uint32_t x) /* x is never 0 here */
{
    unsigned long i;
    _BitScanReverse(&i, x);
    return 31 - (int)i;
}
#else
#define CM_EXPECT(x, v) __builtin_expect((x), (v))
#define CM_NOINLINE __attribute__((noinline))
#define cm_clz(x) __builtin_clz(x)
#endif

typedef union {float f; uint32_t u;} b32u32_u;
typedef union {double f; uint64_t u;} b64u64_u;

static float cm_bits(uint32_t u)
{
    b32u32_u t;
    t.u = u;
    return t.f;
}

/* ---- CORE-MATH's exp2f ------------------------------------------------- */
/* Correctly-rounded 2^x function for binary32 value.

Copyright (c) 2023-2025 Alexei Sibidanov.

This file is part of the CORE-MATH project
(https://core-math.gitlabpages.inria.fr/).

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
// deal with x=nan, x < -149 and x >= 128
static float cm_exp2f_special(float x){
  b32u32_u t = {.f = x};
  uint32_t ux = t.u<<1;
  if(ux >= 0xffu<<24) { // x is inf or nan
    if(ux > 0xffu<<24) return x + x; // x = nan
    static const b32u32_u ir[] = {{.u = 0x7f800000u}, {.u = 0}};
    return ir[t.u>>31].f; // x = +-inf
  }
  if(t.u>=0xc3150000u){ // x < -149
    double z = x, y = 0x1p-149 + (z + 149)*0x1p-150;
    y = fmax(y, 0x1p-151);
    float r = (float)y;
    return r;
  }
  // now x >= 128
  float r = cm_bits(0x7f800000u); // upstream 0x1p127f * 0x1p127f, to raise overflow
  return r;
}

static float soa_exp2f(float x){
  static const b64u64_u tb[] =
    {{0x1.0000000000000p+0}, {0x1.02c9a3e778061p+0}, {0x1.059b0d3158574p+0}, {0x1.0874518759bc8p+0},
     {0x1.0b5586cf9890fp+0}, {0x1.0e3ec32d3d1a2p+0}, {0x1.11301d0125b51p+0}, {0x1.1429aaea92de0p+0},
     {0x1.172b83c7d517bp+0}, {0x1.1a35beb6fcb75p+0}, {0x1.1d4873168b9aap+0}, {0x1.2063b88628cd6p+0},
     {0x1.2387a6e756238p+0}, {0x1.26b4565e27cddp+0}, {0x1.29e9df51fdee1p+0}, {0x1.2d285a6e4030bp+0},
     {0x1.306fe0a31b715p+0}, {0x1.33c08b26416ffp+0}, {0x1.371a7373aa9cbp+0}, {0x1.3a7db34e59ff7p+0},
     {0x1.3dea64c123422p+0}, {0x1.4160a21f72e2ap+0}, {0x1.44e086061892dp+0}, {0x1.486a2b5c13cd0p+0},
     {0x1.4bfdad5362a27p+0}, {0x1.4f9b2769d2ca7p+0}, {0x1.5342b569d4f82p+0}, {0x1.56f4736b527dap+0},
     {0x1.5ab07dd485429p+0}, {0x1.5e76f15ad2148p+0}, {0x1.6247eb03a5585p+0}, {0x1.6623882552225p+0},
     {0x1.6a09e667f3bcdp+0}, {0x1.6dfb23c651a2fp+0}, {0x1.71f75e8ec5f74p+0}, {0x1.75feb564267c9p+0},
     {0x1.7a11473eb0187p+0}, {0x1.7e2f336cf4e62p+0}, {0x1.82589994cce13p+0}, {0x1.868d99b4492edp+0},
     {0x1.8ace5422aa0dbp+0}, {0x1.8f1ae99157736p+0}, {0x1.93737b0cdc5e5p+0}, {0x1.97d829fde4e50p+0},
     {0x1.9c49182a3f090p+0}, {0x1.a0c667b5de565p+0}, {0x1.a5503b23e255dp+0}, {0x1.a9e6b5579fdbfp+0},
     {0x1.ae89f995ad3adp+0}, {0x1.b33a2b84f15fbp+0}, {0x1.b7f76f2fb5e47p+0}, {0x1.bcc1e904bc1d2p+0},
     {0x1.c199bdd85529cp+0}, {0x1.c67f12e57d14bp+0}, {0x1.cb720dcef9069p+0}, {0x1.d072d4a07897cp+0},
     {0x1.d5818dcfba487p+0}, {0x1.da9e603db3285p+0}, {0x1.dfc97337b9b5fp+0}, {0x1.e502ee78b3ff6p+0},
     {0x1.ea4afa2a490dap+0}, {0x1.efa1bee615a27p+0}, {0x1.f50765b6e4540p+0}, {0x1.fa7c1819e90d8p+0}};

  b32u32_u t = {.f = x};
  if(CM_EXPECT((t.u&0xffff)==0, 0)){ // x maybe integer
    int k = ((t.u>>23)&0xff)-127; // 2^k <= |x| < 2^(k+1)
    if(CM_EXPECT(k>=0 && k<9 && (t.u<<(9+k)) == 0, 0)){
      // x integer, with 1 <= |x| < 2^9
      int msk = (int)t.u>>31;
      int m = ((t.u&0x7fffff)|(1<<23))>>(23-k);
      m = (m^msk) - msk + 127;
      if(m>0 && m<255){
	t.u = m<<23;
	return t.f;
      } else if(m<=0 && m>-23){
        /* If f(x) underflows but is exact, no underflow exception should be
           raised (cf IEEE 754-2019). */
	t.u = 1<<(22+m);
        return t.f;
      }
    }
  }
  uint32_t ux = t.u<<1;
  if (CM_EXPECT(ux>=0x86000000u || ux<0x65000000u, 0)){
    // |x| >= 128 or x=nan or |x| < 0x1p-26
    if(CM_EXPECT(ux<0x65000000u, 1)) return 1.0f + x; // |x| < 0x1p-26
    // if x < -149 or 128 <= x we call as_special()
    if(!(t.u>=0xc3000000u && t.u<0xc3150000u)) return cm_exp2f_special(x);
  }
  double offd = 0x1.8p46, xd = x, h = xd - ((xd + offd) - offd), h2 = h*h;
  b32u32_u u = {.f = x + 0x1.8p17f};
  b64u64_u sv = tb[u.u&0x3f];
  sv.u += (uint64_t)(u.u>>6)<<52;
  static const double b[] = {1, 0x1.62e42fef4c4e7p-1, 0x1.ebfd1b232f475p-3, 0x1.c6b19384ecd93p-5};
  double r = sv.f*((b[0] + h*b[1]) + h2*(b[2] + h*b[3])), eps = 0x1.3d8p-33;
  float ub = (float)r, lb = (float)(r - r*eps);
  if(CM_EXPECT(ub != lb, 1)){
    if(CM_EXPECT(ux<=0x79e7526eu, 0)){
      if(t.u == 0x3b429d37u) return 0x1.00870ap+0f - 0x1p-25f;
      if(t.u == 0xbcf3a937u) return 0x1.f58d62p-1f - 0x1p-26f;
      if(t.u == 0xb8d3d026u) return 0x1.fff6d2p-1f + 0x1p-26f;
    }
    static const double c[] =
      {0x1.62e42fefa39efp-1, 0x1.ebfbdff82c58fp-3, 0x1.c6b08d702e0edp-5, 0x1.3b2ab6fb92e5ep-7,
       0x1.5d886e6d54203p-10, 0x1.430976b8ce6efp-13};
    r = sv.f + (sv.f*h)*((c[0] + h*c[1]) + h2*((c[2] + h*c[3]) + h2*(c[4] + h*c[5])));
    ub = (float)r;
  }
  return ub;
}

/* ---- CORE-MATH's log2f ------------------------------------------------- */
/* Correctly-rounded binary logarithm function for binary32 value.

Copyright (c) 2022-2026 Alexei Sibidanov <sibid@uvic.ca>

This file is part of the CORE-MATH project
(https://core-math.gitlabpages.inria.fr/).

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
CM_NOINLINE static float cm_log2f_special(float x){
  b32u32_u t = {.f = x};
  uint32_t ux = t.u, ax = ux<<1;
  if(ax == 0u){ // +/-0.0
    return cm_bits(0xff800000u); // upstream -1.0f/0.0f, to raise FE_DIVBYZERO
  }
  if(ux == 0x7f800000u) return x; // +inf
  if(ax > 0xff000000u) return x + x; // nan
  return cm_bits(0x7fc00000u); // upstream 0.0f/0.0f, to raise FE_INVALID and return nan
}

static float soa_log2f(float x) {
  static const double ix[] = {
    0x1p+0, 0x1.f81f82p-1, 0x1.f07c1fp-1, 0x1.e9131acp-1,
    0x1.e1e1e1ep-1, 0x1.dae6077p-1, 0x1.d41d41dp-1, 0x1.cd85689p-1,
    0x1.c71c71cp-1, 0x1.c0e0704p-1, 0x1.bacf915p-1, 0x1.b4e81b5p-1,
    0x1.af286bdp-1, 0x1.a98ef6p-1, 0x1.a41a41ap-1, 0x1.9ec8e95p-1,
    0x1.999999ap-1, 0x1.948b0fdp-1, 0x1.8f9c19p-1, 0x1.8acb90fp-1,
    0x1.8618618p-1, 0x1.8181818p-1, 0x1.7d05f41p-1, 0x1.78a4c81p-1,
    0x1.745d174p-1, 0x1.702e05cp-1, 0x1.6c16c17p-1, 0x1.6816817p-1,
    0x1.642c859p-1, 0x1.605816p-1, 0x1.5c9882cp-1, 0x1.58ed231p-1,
    0x1.5555555p-1, 0x1.51d07ebp-1, 0x1.4e5e0a7p-1, 0x1.4afd6ap-1,
    0x1.47ae148p-1, 0x1.446f865p-1, 0x1.4141414p-1, 0x1.3e22cbdp-1,
    0x1.3b13b14p-1, 0x1.3813814p-1, 0x1.3521cfbp-1, 0x1.323e34ap-1,
    0x1.2f684bep-1, 0x1.2c9fb4ep-1, 0x1.29e412ap-1, 0x1.27350b9p-1,
    0x1.2492492p-1, 0x1.21fb781p-1, 0x1.1f7047ep-1, 0x1.1cf06aep-1,
    0x1.1a7b961p-1, 0x1.1811812p-1, 0x1.15b1e5fp-1, 0x1.135c811p-1,
    0x1.1111111p-1, 0x1.0ecf56cp-1, 0x1.0c9715p-1, 0x1.0a6810ap-1,
    0x1.0842108p-1, 0x1.0624dd3p-1, 0x1.041041p-1, 0x1.0204081p-1, 0.5};

  static const double lix[] = {
    0x0p+0, -0x1.6e7966ead8ac5p-6, -0x1.6bad38119a13ap-5, -0x1.0eb389ee9f56p-4,
    -0x1.663f6fc3a678dp-4, -0x1.bc8423d408321p-4, -0x1.08c588e79f8e9p-3, -0x1.32ae9e28fc362p-3,
    -0x1.5c01a3cde7f74p-3, -0x1.84c2bccf005a9p-3, -0x1.acf5e2c156d8fp-3, -0x1.d49ee4b90c47cp-3,
    -0x1.fbc16b67c143bp-3, -0x1.11307dc445fecp-2, -0x1.24407abf4dc03p-2, -0x1.37124cede831fp-2,
    -0x1.49a784a5bc715p-2, -0x1.5c01a3965cc38p-2, -0x1.6e221cc2bb868p-2, -0x1.800a564aa10b6p-2,
    -0x1.91bba8a906b7fp-2, -0x1.a33760adbb56ep-2, -0x1.b47ebf91d417cp-2, -0x1.c592faf028f8ep-2,
    -0x1.d6753e1a43e85p-2, -0x1.e726aa2157f61p-2, -0x1.f7a8567cd1cbdp-2, -0x1.03fda8a93ea1cp-1,
    -0x1.0c10500ed4feep-1, -0x1.140c9fb5a8f7fp-1, -0x1.1bf311daefb44p-1, -0x1.23c41d317edc1p-1,
    -0x1.2b80347f8250cp-1, -0x1.3327c6a752222p-1, -0x1.3abb3fb080128p-1, -0x1.423b07f5114e5p-1,
    -0x1.49a784b14715p-1, -0x1.5101187e9b871p-1, -0x1.5848226c6c7c3p-1, -0x1.5f7cff3de8f2ap-1,
    -0x1.66a008d8ede91p-1, -0x1.6db19694a04aap-1, -0x1.74b1fd6b5e715p-1, -0x1.7ba18f99ce2a5p-1,
    -0x1.82809d4d79ba9p-1, -0x1.894f749cf5047p-1, -0x1.900e615bac2f7p-1, -0x1.96bdad16f516p-1,
    -0x1.9d5d9fe08baefp-1, -0x1.a3ee7f3e4a7ebp-1, -0x1.aa708f4de7fep-1, -0x1.b0e4125ca68fep-1,
    -0x1.b74948f9a72bp-1, -0x1.bda071b77c9e2p-1, -0x1.c3e9ca4193f99p-1, -0x1.ca258dd397814p-1,
    -0x1.d053f6d543325p-1, -0x1.d6753dfedaa39p-1, -0x1.dc899aa874b31p-1, -0x1.e29142f2e8b3dp-1,
    -0x1.e88c6b41b14aep-1, -0x1.ee7b4718b4414p-1, -0x1.f45e08c87b09p-1, -0x1.fa34e117d8785p-1,
    -0x1p+0
  };
  static const double b[] = {
    0x1.7154765bab2b5p+0, -0x1.71574d6939f6cp-1, 0x1.ec60b584ca47fp-2};
  static const double c[] = {
    0x1.71547652b8314p+0, -0x1.71547652b7f67p-1, 0x1.ec709db872c63p-2,
    -0x1.715476b064cdfp-2, 0x1.277c72c15441fp-2, -0x1.ec4ff35b64c31p-3};

  b32u32_u t = {.f = x};
  uint32_t ux = t.u;
  if(CM_EXPECT(ux >= 0x7f800000u, 0)) return cm_log2f_special(x); // <=-0, nan, inf
  if(CM_EXPECT(ux<(1u<<23), 0)){ // subnormal
    if(CM_EXPECT(ux == 0u, 0)) return cm_log2f_special(x); // +0
    int n = cm_clz(ux) - 8;
    ux <<= n;
    ux -= n<<23;
  }
  int e = ((int32_t)ux>>23) - 0x7f;
  uint32_t m = ux&(~0u>>9);
  if(CM_EXPECT(!m, 0)) return (float)e;
  int32_t j = (m + (1<<(23-7)))>>(23-6);
  b64u64_u xd = {.u = (uint64_t)m<<(52-23) | 0x3ffull<<52};
  double z = xd.f*ix[j] - 1.0, z2 = z*z, el = e - lix[j];
  double f = (el + z*b[0]) + z2*(b[1] + z*b[2]);
  float lb = (float)f , ub = (float)(f + 0x1.661p-32);
  if(CM_EXPECT(lb==ub, 1)) return lb;
  double c0 = c[0] + z*c[1];
  double c2 = c[2] + z*c[3];
  double c4 = c[4] + z*c[5];
  c0 += z2*(c2 + z2*c4);
  return (float)(el + z*c0);
}

#endif
