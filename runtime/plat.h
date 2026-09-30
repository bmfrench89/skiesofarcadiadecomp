/*
 * The platform layer (docs/specs/portability.md 3.2): what the runtime asks
 * of a compiler and an operating system, named once, so the files that use it
 * test a meaning (PLAT_X86_64) instead of a compiler (_MSC_VER). Every name is
 * plat_* or PLAT_*. Nothing here includes cpu.h and cpu.h never includes this,
 * so editing it is a --link, never a retranslation.
 *
 * L2a created it with the platform tests and the SIMD section; L2 adds the
 * atomics, waits, clocks and threads. Header-only until L7 adds plat.c: the
 * renderer links on its own (render_check.py), so nothing here may need a
 * second object file yet.
 */
#ifndef SOA_PLAT_H
#define SOA_PLAT_H

/* ---- platform tests ------------------------------------------------------
 * Each is 0 or 1, so `#if PLAT_X86_64` reads the same on every compiler.
 * ARM64EC defines _M_X64 for source compatibility but runs ARM64 code, and
 * clang-cl defines _MSC_VER while taking GNU attributes and __atomic
 * builtins: those two are why the tests are not the compilers' own macros. */
#if (defined(_M_X64) && !defined(_M_ARM64EC)) || defined(__x86_64__)
#define PLAT_X86_64 1
#else
#define PLAT_X86_64 0
#endif

#if defined(_M_ARM64) || defined(__aarch64__)
#define PLAT_ARM64 1
#else
#define PLAT_ARM64 0
#endif

#if defined(_MSC_VER) && !defined(__clang__)
#define PLAT_MSVC 1 /* MSVC itself: its intrinsics, __forceinline */
#else
#define PLAT_MSVC 0
#endif

#if defined(__GNUC__) || defined(__clang__)
#define PLAT_GNU 1 /* gcc and every clang, clang-cl included: attributes, __atomic */
#else
#define PLAT_GNU 0
#endif

/* ---- SIMD (L2a) ----------------------------------------------------------
 * PLAT_TARGET_SSE41 marks a function that may use SSE4.1 while the file is
 * built for baseline x86-64. gcc and clang will not inline an SSE4.1
 * intrinsic into a function without it (the error clang-cl gave on
 * gxr_tev.c since b377b1f), and a file-wide -msse4.1 would let them use it
 * anywhere, which makes the run-time check below meaningless. MSVC needs
 * neither: it emits any intrinsic anywhere.
 *
 * plat_cpu_has_sse41: CPUID leaf 1, ECX bit 19; 0 off x86-64. Whenever
 * _MSC_VER is defined (MSVC and clang-cl) it is __cpuid from <intrin.h>, not
 * __builtin_cpu_supports, which under clang-cl linked by link.exe needs
 * compiler-rt's __cpu_model and fails with LNK2019. Every other x86-64
 * build uses <cpuid.h>, which is header-only. */
#if PLAT_GNU
#define PLAT_TARGET_SSE41 __attribute__((target("sse4.1")))
#else
#define PLAT_TARGET_SSE41
#endif

#if PLAT_X86_64 && defined(_MSC_VER)
#include <intrin.h>
#elif PLAT_X86_64
#include <cpuid.h>
#endif

static inline int plat_cpu_has_sse41(void)
{
#if PLAT_X86_64 && defined(_MSC_VER)
    int r[4];
    __cpuid(r, 1);
    return (r[2] >> 19) & 1;
#elif PLAT_X86_64
    unsigned a, b, c, d;
    if (!__get_cpuid(1, &a, &b, &c, &d)) return 0;
    return (int)((c >> 19) & 1);
#else
    return 0;
#endif
}

#endif
