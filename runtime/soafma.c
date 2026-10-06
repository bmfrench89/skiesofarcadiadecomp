/*
 * The guest's fused multiply-add inside the exe (specs/distribution.md R1,
 * 3.3).
 *
 * Every fmadd, fmsub and ps_madd the translator emits is a call to fma(),
 * which must round once, as the Gekko does: 2,457 calls (portability.md).
 * An MSVC build takes fma from its static CRT, so the code that runs is in
 * soa.exe. A MinGW build would import it from the UCRT DLL, which under
 * Proton is Wine's, and then the Steam Deck would run other math than
 * Windows does. So there cpu.h names soa_fma instead, which is here:
 *
 * - on an x86-64 CPU with FMA3 (every PC in scope: Haswell and Piledriver
 *   onward, the Steam Deck, the Ally X), the instruction itself, which
 *   rounds once by definition;
 * - otherwise soa_fma_soft, musl's fma, which computes the exact sum in
 *   integers and rounds it once.
 *
 * x86-64 Android takes the same path: bionic's fma there rounds a negative
 * result that underflows to +0 rather than -0 (FINDINGS "L12c"). Elsewhere
 * soa_fma is the C library's fma: MSVC's static one, glibc's on Linux, and on
 * ARM64 Android bionic's, the instruction, all exact. The self test holds soa_fma_soft to the build's fma, and a
 * translated guest function's fmadds to its fused answer.
 *
 * soa_fma_soft is musl's src/math/fma.c (https://musl.libc.org/, commit
 * 9683bd62 of 2024-03-14, by Szabolcs Nagy), under musl's MIT licence,
 * reproduced below and named in NOTICE. Changed from upstream, and nothing
 * else:
 * - renamed soa_fma_soft, with normalize and mul static as before;
 * - a_clz_64 (musl's atomic.h) written as clz64, from the compiler's
 *   builtin or MSVC's _BitScanReverse64;
 * - no #pragma STDC FENV_ACCESS: the guest's fma reads no exception flag,
 *   and the value is the same under the default rounding mode;
 * - unsigned negation written 0 - x, which MSVC warns about (C4146) and
 *   which negates the same.
 */
#include <float.h>
#include <math.h>
#include <stdint.h>
#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#endif

double soa_fma_soft(double x, double y, double z);
double soa_fma(double a, double b, double c);

/* ---- musl's fma -------------------------------------------------------------
 *
 * Copyright (c) 2005-2020 Rich Felker, et al.
 *
 * Permission is hereby granted, free of charge, to any person obtaining
 * a copy of this software and associated documentation files (the
 * "Software"), to deal in the Software without restriction, including
 * without limitation the rights to use, copy, modify, merge, publish,
 * distribute, sublicense, and/or sell copies of the Software, and to
 * permit persons to whom the Software is furnished to do so, subject to
 * the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
 * IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
 * CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
 * TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
 * SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

#define ASUINT64(x) ((union {double f; uint64_t i;}){x}).i
#define ZEROINFNAN (0x7ff-0x3ff-52-1)

static int clz64(uint64_t x)
{
#if defined(_MSC_VER) && !defined(__clang__)
	unsigned long i;
	_BitScanReverse64(&i, x);
	return 63 - (int)i;
#else
	return __builtin_clzll(x);
#endif
}

struct num { uint64_t m; int e; int sign; };

static struct num normalize(double x)
{
	uint64_t ix = ASUINT64(x);
	int e = ix>>52;
	int sign = e & 0x800;
	e &= 0x7ff;
	if (!e) {
		ix = ASUINT64(x*0x1p63);
		e = ix>>52 & 0x7ff;
		e = e ? e-63 : 0x800;
	}
	ix &= (1ull<<52)-1;
	ix |= 1ull<<52;
	ix <<= 1;
	e -= 0x3ff + 52 + 1;
	return (struct num){ix,e,sign};
}

static void mul(uint64_t *hi, uint64_t *lo, uint64_t x, uint64_t y)
{
	uint64_t t1,t2,t3;
	uint64_t xlo = (uint32_t)x, xhi = x>>32;
	uint64_t ylo = (uint32_t)y, yhi = y>>32;

	t1 = xlo*ylo;
	t2 = xlo*yhi + xhi*ylo;
	t3 = xhi*yhi;
	*lo = t1 + (t2<<32);
	*hi = t3 + (t2>>32) + (t1 > *lo);
}

double soa_fma_soft(double x, double y, double z)
{
	/* normalize so top 10bits and last bit are 0 */
	struct num nx, ny, nz;
	nx = normalize(x);
	ny = normalize(y);
	nz = normalize(z);

	if (nx.e >= ZEROINFNAN || ny.e >= ZEROINFNAN)
		return x*y + z;
	if (nz.e >= ZEROINFNAN) {
		if (nz.e > ZEROINFNAN) /* z==0 */
			return x*y;
		return z;
	}

	/* mul: r = x*y */
	uint64_t rhi, rlo, zhi, zlo;
	mul(&rhi, &rlo, nx.m, ny.m);
	/* either top 20 or 21 bits of rhi and last 2 bits of rlo are 0 */

	/* align exponents */
	int e = nx.e + ny.e;
	int d = nz.e - e;
	/* shift bits z<<=kz, r>>=kr, so kz+kr == d, set e = e+kr (== ez-kz) */
	if (d > 0) {
		if (d < 64) {
			zlo = nz.m<<d;
			zhi = nz.m>>64-d;
		} else {
			zlo = 0;
			zhi = nz.m;
			e = nz.e - 64;
			d -= 64;
			if (d == 0) {
			} else if (d < 64) {
				rlo = rhi<<64-d | rlo>>d | !!(rlo<<64-d);
				rhi = rhi>>d;
			} else {
				rlo = 1;
				rhi = 0;
			}
		}
	} else {
		zhi = 0;
		d = -d;
		if (d == 0) {
			zlo = nz.m;
		} else if (d < 64) {
			zlo = nz.m>>d | !!(nz.m<<64-d);
		} else {
			zlo = 1;
		}
	}

	/* add */
	int sign = nx.sign^ny.sign;
	int samesign = !(sign^nz.sign);
	int nonzero = 1;
	if (samesign) {
		/* r += z */
		rlo += zlo;
		rhi += zhi + (rlo < zlo);
	} else {
		/* r -= z */
		uint64_t t = rlo;
		rlo -= zlo;
		rhi = rhi - zhi - (t < rlo);
		if (rhi>>63) {
			rlo = 0-rlo;
			rhi = 0-rhi-!!rlo;
			sign = !sign;
		}
		nonzero = !!rhi;
	}

	/* set rhi to top 63bit of the result (last bit is sticky) */
	if (nonzero) {
		e += 64;
		d = clz64(rhi)-1;
		/* note: d > 0 */
		rhi = rhi<<d | rlo>>64-d | !!(rlo<<d);
	} else if (rlo) {
		d = clz64(rlo)-1;
		if (d < 0)
			rhi = rlo>>1 | (rlo&1);
		else
			rhi = rlo<<d;
	} else {
		/* exact +-0 */
		return x*y + z;
	}
	e -= d;

	/* convert to double */
	int64_t i = rhi; /* i is in [1<<62,(1<<63)-1] */
	if (sign)
		i = -i;
	double r = i; /* |r| is in [0x1p62,0x1p63] */

	if (e < -1022-62) {
		/* result is subnormal before rounding */
		if (e == -1022-63) {
			double c = 0x1p63;
			if (sign)
				c = -c;
			if (r == c) {
				/* min normal after rounding, underflow depends
				   on arch behaviour which can be imitated by
				   a double to float conversion */
				float fltmin = 0x0.ffffff8p-63*FLT_MIN * r;
				return DBL_MIN/FLT_MIN * fltmin;
			}
			/* one bit is lost when scaled, add another top bit to
			   only round once at conversion if it is inexact */
			if (rhi << 53) {
				i = rhi>>1 | (rhi&1) | 1ull<<62;
				if (sign)
					i = -i;
				r = i;
				r = 2*r - c; /* remove top bit */

				/* raise underflow portably, such that it
				   cannot be optimized away */
				{
					double_t tiny = DBL_MIN/FLT_MIN * r;
					r += (double)(tiny*tiny) * (r-r);
				}
			}
		} else {
			/* only round once when scaled */
			d = 10;
			i = ( rhi>>d | !!(rhi<<64-d) ) << d;
			if (sign)
				i = -i;
			r = i;
		}
	}
	return scalbn(r, e);
}

/* ---- what the guest calls ------------------------------------------------- */

#if (defined(__MINGW32__) || defined(__ANDROID__)) && defined(__x86_64__)
/* The instruction, compiled for FMA3 alone; called only where the CPU has it. */
__attribute__((target("fma"))) static double hw_fma(double a, double b, double c)
{
	return __builtin_fma(a, b, c);
}

/* __builtin_cpu_supports reads what compiler-rt's constructor found: one load. */
double soa_fma(double a, double b, double c)
{
	return __builtin_cpu_supports("fma") ? hw_fma(a, b, c) : soa_fma_soft(a, b, c);
}
#else
double soa_fma(double a, double b, double c)
{
	return fma(a, b, c);
}
#endif
