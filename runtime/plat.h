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
#include <stdio.h>
#include <stdlib.h>
#if PLAT_MSVC || (PLAT_X86_64 && defined(_MSC_VER))
#include <intrin.h> /* MSVC's intrinsics, and clang-cl's __cpuid and __rdtsc */
#elif PLAT_X86_64
#include <cpuid.h>
#endif
#ifdef _WIN32
#include <process.h>
#else
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
#endif

/* ---- storage classes (L2) ------------------------------------------------ */
#ifdef _MSC_VER
#define PLAT_THREAD_LOCAL __declspec(thread) /* clang-cl accepts it too */
#define PLAT_ALIGN(n) __declspec(align(n))
#else
#define PLAT_THREAD_LOCAL _Thread_local
#define PLAT_ALIGN(n) __attribute__((aligned(n)))
#endif

/* ---- the Win32 calls this header makes -----------------------------------
 * Declared here exactly as the SDK's headers declare them, so a file that
 * includes <windows.h> as well still compiles, and one that does not is not
 * handed it: <windows.h> brings min, max, near and far, and mmsystem's
 * MMIO_READ, which hle.c's own names collide with -- and gxr.h, which main.c,
 * window.c and selftest.c include, includes this. The union's tag is declared
 * at file scope first, so it is the SDK's LARGE_INTEGER whichever header
 * comes first. */
#ifdef _WIN32
union _LARGE_INTEGER;
/* No WINBASEAPI on these two in synchapi.h: they come from the
 * Synchronization.lib API set, not kernel32's imports, and declaring them
 * dllimport here is MSVC's C4273 wherever <windows.h> follows. */
int __stdcall WaitOnAddress(volatile void* Address, void* CompareAddress, size_t AddressSize,
                            unsigned long dwMilliseconds);
void __stdcall WakeByAddressAll(void* Address);
__declspec(dllimport) void __stdcall Sleep(unsigned long dwMilliseconds);
__declspec(dllimport) int __stdcall QueryPerformanceCounter(union _LARGE_INTEGER* lpPerformanceCount);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(union _LARGE_INTEGER* lpFrequency);
__declspec(dllimport) unsigned long __stdcall GetActiveProcessorCount(unsigned short GroupNumber);
#ifdef _MSC_VER
#pragma comment(lib, "Synchronization.lib") /* WaitOnAddress */
#endif
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
/* A value only its owner writes and other threads read with plat_load64, where
 * nothing else orders the two -- the pool's idle timers, charged by a worker
 * still parked when the report reads them (L8). Relaxed: a plain mov on x64
 * and ARM64, and ThreadSanitizer sees an atomic access instead of a race. */
PLAT_INLINE void plat_store64_relaxed(plat_a64* p, int64_t v) { __atomic_store_n(p, v, __ATOMIC_RELAXED); }
PLAT_INLINE int32_t plat_cas32(plat_a32* p, int32_t expect, int32_t want) /* returns the old value */
{
    int32_t e = expect;
    __atomic_compare_exchange_n(p, &e, want, 0, __ATOMIC_SEQ_CST, __ATOMIC_SEQ_CST);
    return e;
}
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
PLAT_INLINE int32_t plat_cas32(plat_a32* p, int32_t expect, int32_t want) /* returns the old value */
{
    return _InterlockedCompareExchange((long volatile*)p, want, expect);
}
#if PLAT_ARM64
PLAT_INLINE void plat_store64_relaxed(plat_a64* p, int64_t v) { __iso_volatile_store64((__int64 volatile*)p, v); }
#else
PLAT_INLINE void plat_store64_relaxed(plat_a64* p, int64_t v) { *p = v; }
#endif
PLAT_INLINE void plat_compiler_barrier(void) { _ReadWriteBarrier(); }
#else
#error "plat.h: no atomics for this compiler"
#endif

/* ---- spinning and sleeping (L2) ------------------------------------------ */
PLAT_INLINE void plat_relax(void) /* one spin-wait pause: YieldProcessor's instruction */
{
#if PLAT_X86_64 && PLAT_GNU
    __builtin_ia32_pause();
#elif PLAT_X86_64
    _mm_pause();
#elif PLAT_ARM64 && PLAT_MSVC
    __yield();
#elif PLAT_ARM64
    __asm__ __volatile__("yield");
#endif
}

PLAT_INLINE void plat_yield(void) /* give the core to any thread that is ready */
{
#ifdef _WIN32
    Sleep(0);
#else
    sched_yield();
#endif
}

PLAT_INLINE void plat_sleep_ms(unsigned ms)
{
#ifdef _WIN32
    Sleep(ms);
#else
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000);
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
#endif
}

/* ---- waits (L2): spin, then sleep on a word (H11's pattern) ---------------
 * plat_wait64 sleeps while *p still equals seen, at most timeout_ms, and may
 * return early for no reason; plat_wake_all64 wakes every thread asleep on p.
 * Windows: WaitOnAddress and WakeByAddressAll. Linux and Android: a private
 * futex on the counter's low 32 bits -- the counters only rise and a wait
 * lasts at most 50 ms, so a false match needs 2^32 increments inside one.
 * Anywhere else a wait is a 1 ms sleep, said once. */
#ifdef _WIN32
PLAT_INLINE void plat_wait64(plat_a64* p, int64_t seen, unsigned timeout_ms)
{
    WaitOnAddress((volatile void*)p, &seen, sizeof seen, timeout_ms);
}
PLAT_INLINE void plat_wake_all64(plat_a64* p) { WakeByAddressAll((void*)p); }
#elif defined(__linux__)
#include <limits.h>
#include <linux/futex.h>
#include <sys/syscall.h>
static inline volatile uint32_t* plat_low32(plat_a64* p)
{
#if defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    return (volatile uint32_t*)p + 1;
#else
    return (volatile uint32_t*)p;
#endif
}
PLAT_INLINE void plat_wait64(plat_a64* p, int64_t seen, unsigned timeout_ms)
{
    struct timespec ts;
    ts.tv_sec = (time_t)(timeout_ms / 1000);
    ts.tv_nsec = (long)(timeout_ms % 1000) * 1000000L;
    syscall(SYS_futex, plat_low32(p), FUTEX_WAIT_PRIVATE, (uint32_t)seen, &ts, NULL, 0);
}
PLAT_INLINE void plat_wake_all64(plat_a64* p) { syscall(SYS_futex, plat_low32(p), FUTEX_WAKE_PRIVATE, INT_MAX, NULL, NULL, 0); }
#else
static inline void plat_wait64(plat_a64* p, int64_t seen, unsigned timeout_ms)
{
    static int said;
    (void)p;
    (void)seen;
    (void)timeout_ms;
    if (!said) {
        said = 1;
        fprintf(stderr, "[plat] no futex here; waits poll every 1 ms\n");
    }
    plat_sleep_ms(1);
}
PLAT_INLINE void plat_wake_all64(plat_a64* p) { (void)p; }
#endif

/* ---- clocks (L2) ---------------------------------------------------------
 * plat_mono_raw counts at plat_mono_hz: QueryPerformanceCounter on Windows,
 * CLOCK_MONOTONIC nanoseconds elsewhere. plat_cycles is the cheap counter
 * gxr.c's timers read twice per queued command -- the TSC on x86-64,
 * CNTVCT_EL0 on ARM64 -- whose rate gxr.c measures against plat_mono_raw
 * rather than trusting; plat_cycles_invariant says whether it runs at one
 * rate across cores and power states (CPUID 80000007 EDX bit 8 on x86-64;
 * the ARM generic timer always does). */
PLAT_INLINE uint64_t plat_mono_raw(void)
{
#ifdef _WIN32
    int64_t v;
    QueryPerformanceCounter((union _LARGE_INTEGER*)&v);
    return (uint64_t)v;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
#endif
}

static inline double plat_mono_hz(void)
{
#ifdef _WIN32
    int64_t f;
    QueryPerformanceFrequency((union _LARGE_INTEGER*)&f);
    return (double)f;
#else
    return 1e9;
#endif
}

PLAT_INLINE uint64_t plat_cycles(void)
{
#if PLAT_X86_64 && defined(_MSC_VER)
    return __rdtsc();
#elif PLAT_X86_64
    return __builtin_ia32_rdtsc();
#elif PLAT_ARM64 && PLAT_MSVC
    return (uint64_t)_ReadStatusReg(0x5F02); /* ARM64_SYSREG(3, 3, 14, 0, 2): CNTVCT_EL0 */
#elif PLAT_ARM64
    uint64_t v;
    __asm__ __volatile__("mrs %0, cntvct_el0" : "=r"(v));
    return v;
#else
    return plat_mono_raw();
#endif
}

static inline int plat_cycles_invariant(void)
{
#if PLAT_X86_64 && defined(_MSC_VER)
    int r[4];
    __cpuid(r, 0x80000000);
    if ((unsigned)r[0] < 0x80000007u) return 0;
    __cpuid(r, 0x80000007);
    return (r[3] >> 8) & 1;
#elif PLAT_X86_64
    unsigned a, b, c, d;
    if (!__get_cpuid(0x80000007, &a, &b, &c, &d)) return 0;
    return (int)((d >> 8) & 1);
#elif PLAT_ARM64
    return 1;
#else
    return 0;
#endif
}

/* ---- threads (L2) --------------------------------------------------------
 * plat_thread_start runs fn(arg) on a new thread and returns 1, or 0 if none
 * could be made; stack_bytes 0 is the platform's default. PlatThread.os is
 * the HANDLE on Windows, kept for SOA_HOSTPROF, which samples through it. A
 * small heap block carries fn and arg across, once per thread. */
typedef struct {
    void* os;
} PlatThread;

typedef struct {
    void (*fn)(void*);
    void* arg;
} PlatThreadStart;

#ifdef _WIN32
static inline unsigned __stdcall plat_thread_main(void* p)
{
    PlatThreadStart s = *(PlatThreadStart*)p;
    free(p);
    s.fn(s.arg);
    return 0;
}
#else
static inline void* plat_thread_main(void* p)
{
    PlatThreadStart s = *(PlatThreadStart*)p;
    free(p);
    s.fn(s.arg);
    return NULL;
}
#endif

static inline int plat_thread_start(PlatThread* t, void (*fn)(void*), void* arg, size_t stack_bytes)
{
    PlatThreadStart* s = (PlatThreadStart*)malloc(sizeof *s);
    if (!s) return 0;
    s->fn = fn;
    s->arg = arg;
#ifdef _WIN32
    t->os = (void*)_beginthreadex(NULL, (unsigned)stack_bytes, plat_thread_main, s, 0, NULL);
    if (!t->os) {
        free(s);
        return 0;
    }
    return 1;
#else
    {
        pthread_t id;
        pthread_attr_t attr;
        int ok;
        pthread_attr_init(&attr);
        if (stack_bytes) pthread_attr_setstacksize(&attr, stack_bytes);
        ok = pthread_create(&id, &attr, plat_thread_main, s) == 0;
        pthread_attr_destroy(&attr);
        if (!ok) {
            free(s);
            return 0;
        }
        pthread_detach(id);
        t->os = NULL;
        return 1;
    }
#endif
}

static inline int plat_cpu_count(void) /* logical processors, at least 1 */
{
#ifdef _WIN32
    int n = (int)GetActiveProcessorCount(0xFFFF); /* ALL_PROCESSOR_GROUPS */
#else
    int n = (int)sysconf(_SC_NPROCESSORS_ONLN);
#endif
    return n > 0 ? n : 1;
}

/* ---- files and environment (L2) ------------------------------------------
 * plat_setenv(name, NULL) or (name, "") removes the variable: unsetenv on
 * POSIX, _putenv_s with an empty value on Windows. That matters, because a
 * presence-only switch (SOA_CULLFLIP, SOA_GXR_NOTEX) reads a set-but-empty
 * variable as on. */
static inline int plat_fseek64(FILE* f, int64_t off) /* from the start of the file */
{
#ifdef _WIN32
    return _fseeki64(f, off, SEEK_SET);
#else
    return fseeko(f, (off_t)off, SEEK_SET);
#endif
}

static inline int plat_setenv(const char* name, const char* value)
{
#ifdef _WIN32
    return _putenv_s(name, value ? value : "");
#else
    if (!value || !*value) return unsetenv(name);
    return setenv(name, value, 1);
#endif
}

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
