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

#include <stddef.h>
#include <stdint.h>
#if PLAT_MSVC
#include <intrin.h>
#endif

/* A helper that must vanish into its caller, so it costs exactly the
 * instruction it stands for: L2's Done compares the queue's x64 code with
 * c8274db's, line for line. */
#if PLAT_MSVC
#define PLAT_INLINE static __forceinline
#elif PLAT_GNU
#define PLAT_INLINE static inline __attribute__((always_inline))
#else
#define PLAT_INLINE static inline
#endif

/* ---- atomics (L2) --------------------------------------------------------
 * The render queue's shared counters stay plain volatile integers; what is
 * shared is that every cross-thread access goes through one of these, which
 * tools/tests/test_gxr_atomics.py enforces over gxr.c (portability.md 3.4).
 * The typedefs are documentation, not wrappers.
 *
 * Loads are sequentially consistent: the sleepers' Dekker re-checks need it
 * (3.4 rule 3), and one kind of load leaves none to choose wrongly. On x64
 * that is a plain mov, which is what <windows.h>'s ReadAcquire64 is there
 * (the SDK's AMD64 section reads *Source and returns it); after a locked RMW
 * it is also a seq_cst load. On ARM64 it is LDAR under both compilers. RMWs
 * are seq_cst: the _Interlocked intrinsics <windows.h>'s Interlocked names
 * expand to on x64, and __atomic under gcc and every clang, clang-cl
 * included. Taken from <intrin.h> rather than <windows.h>, which a header
 * this widely included must not pull in: its min, max, near and far macros,
 * and mmsystem's MMIO_READ, which hle.c's own names collide with.
 *
 * PLAT_TEST_RELAXED_LOADS (test-only, off by default) makes the loads relaxed
 * under PLAT_GNU: L8's mutation. */
typedef volatile int64_t plat_a64;
typedef volatile int32_t plat_a32;

#if PLAT_GNU
#ifdef PLAT_TEST_RELAXED_LOADS
#define PLAT_LOAD_ORDER __ATOMIC_RELAXED
#else
#define PLAT_LOAD_ORDER __ATOMIC_SEQ_CST
#endif
PLAT_INLINE int64_t plat_load64(const plat_a64* p) { return __atomic_load_n(p, PLAT_LOAD_ORDER); }
PLAT_INLINE int32_t plat_load32(const plat_a32* p) { return __atomic_load_n(p, PLAT_LOAD_ORDER); }
PLAT_INLINE int64_t plat_inc64(plat_a64* p) { return __atomic_add_fetch(p, 1, __ATOMIC_SEQ_CST); }
PLAT_INLINE int32_t plat_inc32(plat_a32* p) { return __atomic_add_fetch(p, 1, __ATOMIC_SEQ_CST); }
PLAT_INLINE int32_t plat_dec32(plat_a32* p) { return __atomic_sub_fetch(p, 1, __ATOMIC_SEQ_CST); }
PLAT_INLINE int64_t plat_xchg64(plat_a64* p, int64_t v) { return __atomic_exchange_n(p, v, __ATOMIC_SEQ_CST); }
PLAT_INLINE void plat_compiler_barrier(void) { __asm__ __volatile__("" ::: "memory"); }
#elif PLAT_MSVC
#if PLAT_ARM64
PLAT_INLINE int64_t plat_load64(const plat_a64* p) { return (int64_t)__ldar64((unsigned __int64 volatile*)p); }
PLAT_INLINE int32_t plat_load32(const plat_a32* p) { return (int32_t)__ldar32((unsigned __int32 volatile*)p); }
#else
PLAT_INLINE int64_t plat_load64(const plat_a64* p) { return *p; }
PLAT_INLINE int32_t plat_load32(const plat_a32* p) { return *p; }
#endif
PLAT_INLINE int64_t plat_inc64(plat_a64* p) { return _InterlockedIncrement64((__int64 volatile*)p); }
PLAT_INLINE int32_t plat_inc32(plat_a32* p) { return _InterlockedIncrement((long volatile*)p); }
PLAT_INLINE int32_t plat_dec32(plat_a32* p) { return _InterlockedDecrement((long volatile*)p); }
PLAT_INLINE int64_t plat_xchg64(plat_a64* p, int64_t v) { return _InterlockedExchange64((__int64 volatile*)p, v); }
PLAT_INLINE void plat_compiler_barrier(void) { _ReadWriteBarrier(); }
#else
#error "plat.h: no atomics for this compiler"
#endif

/* ---- waits (L2): spin, then sleep on a word (H11's pattern) ---------------
 * plat_wait64 sleeps while *p still equals seen, at most timeout_ms, and may
 * return early for no reason; plat_wake_all64 wakes every thread asleep on p.
 * On Windows they are WaitOnAddress and WakeByAddressAll, declared here
 * exactly as synchapi.h declares them, so a file that includes <windows.h>
 * as well still compiles and one that does not is not handed it. */
#ifdef _WIN32
__declspec(dllimport) int __stdcall WaitOnAddress(volatile void* Address, void* CompareAddress, size_t AddressSize,
                                                  unsigned long dwMilliseconds);
__declspec(dllimport) void __stdcall WakeByAddressAll(void* Address);
#ifdef _MSC_VER
#pragma comment(lib, "Synchronization.lib")
#endif
PLAT_INLINE void plat_wait64(plat_a64* p, int64_t seen, unsigned timeout_ms)
{
    WaitOnAddress((volatile void*)p, &seen, sizeof seen, timeout_ms);
}
PLAT_INLINE void plat_wake_all64(plat_a64* p) { WakeByAddressAll((void*)p); }
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
