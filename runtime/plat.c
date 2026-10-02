/*
 * The platform layer's cold half (docs/specs/portability.md 3.3): what only
 * main.c and the device files ask of an operating system. The renderer needs
 * none of it, so render_check.py's renderer-only build still links without
 * this file. Each function lands with its first caller -- L7's are the MEM1
 * image's guard and the guest's stack -- so nothing here is compiled and
 * never run.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE /* REG_ERR in ucontext, on glibc */
#endif
#define _CRT_SECURE_NO_WARNINGS
#include "plat.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sys/mman.h>
#include <ucontext.h>
#endif

/* ---- address space ------------------------------------------------------ */

#ifdef _WIN32
void* plat_reserve(size_t bytes) { return VirtualAlloc(NULL, bytes, MEM_RESERVE, PAGE_NOACCESS); }
int plat_commit(void* p, size_t bytes) { return VirtualAlloc(p, bytes, MEM_COMMIT, PAGE_READWRITE) != NULL; }
void plat_release(void* p, size_t bytes)
{
    (void)bytes;
    VirtualFree(p, 0, MEM_RELEASE);
}
unsigned long plat_last_error(void) { return (unsigned long)GetLastError(); }
#else
void* plat_reserve(size_t bytes)
{
    void* p = mmap(NULL, bytes, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    return p == MAP_FAILED ? NULL : p;
}
/* Anonymous pages are zero, as VirtualAlloc's committed ones are. The start
 * must be page-aligned; the length is rounded up to whole pages. */
int plat_commit(void* p, size_t bytes) { return mprotect(p, bytes, PROT_READ | PROT_WRITE) == 0; }
void plat_release(void* p, size_t bytes) { munmap(p, bytes); }
unsigned long plat_last_error(void) { return (unsigned long)errno; }
#endif

/* ---- the guard on a reserved range ---------------------------------------
 * One guard per process: main.c's MEM1 image is the only caller. The report
 * main.c's callback prints uses fprintf, which is not async-signal-safe; the
 * Windows handler does the same from a vectored handler, and it fires once a
 * run, on the faulting thread, in generated code rather than inside stdio
 * (3.3, "one shortcut, stated"). */
static uint8_t* g_guard_base;
static size_t g_guard_lo, g_guard_hi;
static PlatFaultFn g_guard_fn;

#ifdef _WIN32
static DWORD g_guard_owner;

static LONG CALLBACK guard_veh(EXCEPTION_POINTERS* ep)
{
    const EXCEPTION_RECORD* er = ep->ExceptionRecord;
    uintptr_t off;
    /* Every other fault in the process belongs to somebody else. The
     * subtraction is unsigned, so an address below the range gives a huge
     * offset and falls out of the test with it. */
    if (er->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || er->NumberParameters < 2 || !g_guard_base)
        return EXCEPTION_CONTINUE_SEARCH;
    off = (uintptr_t)er->ExceptionInformation[1] - (uintptr_t)g_guard_base;
    if (off < g_guard_lo || off >= g_guard_hi) return EXCEPTION_CONTINUE_SEARCH;
    return g_guard_fn((size_t)off, er->ExceptionInformation[0] != 0, GetCurrentThreadId() == g_guard_owner)
               ? EXCEPTION_CONTINUE_EXECUTION
               : EXCEPTION_CONTINUE_SEARCH;
}

int plat_guard_install(void* base, size_t lo, size_t hi, PlatFaultFn fn)
{
    g_guard_lo = lo;
    g_guard_hi = hi;
    g_guard_fn = fn;
    g_guard_owner = GetCurrentThreadId();
    g_guard_base = (uint8_t*)base;
    if (AddVectoredExceptionHandler(1, guard_veh)) return 1;
    g_guard_base = NULL;
    return 0;
}

void plat_guard_owner(void) { g_guard_owner = GetCurrentThreadId(); }
#else
static struct sigaction g_guard_prev;
static pthread_t g_guard_owner_id;
static int g_guard_owner_set;

/* Whether the faulting access was a store: the page fault's error code on
 * x86-64 (bit 1), and on AArch64 the ESR the kernel puts in the signal
 * frame's records (ESR_MAGIC), bit 6 (WnR). -1 where neither is to hand. The
 * AArch64 record's layout is the kernel's ABI, spelled out here rather than
 * taken from <asm/sigcontext.h>, which clashes with glibc's own. */
static int fault_storing(void* ucp)
{
#if defined(__x86_64__) && defined(REG_ERR)
    const ucontext_t* uc = (const ucontext_t*)ucp;
    return (uc->uc_mcontext.gregs[REG_ERR] & 2) != 0;
#elif defined(__aarch64__) && defined(__linux__)
    struct rec {
        uint32_t magic, size;
    };
    const ucontext_t* uc = (const ucontext_t*)ucp;
    const uint8_t* p = (const uint8_t*)uc->uc_mcontext.__reserved;
    const uint8_t* end = p + sizeof uc->uc_mcontext.__reserved;
    while (p + sizeof(struct rec) <= end) {
        const struct rec* r = (const struct rec*)p;
        if (r->magic == 0 || r->size < sizeof *r) break;
        if (r->magic == 0x45535201u /* ESR_MAGIC */ && r->size >= sizeof *r + 8) {
            uint64_t esr;
            memcpy(&esr, p + sizeof *r, 8);
            return (int)((esr >> 6) & 1);
        }
        p += r->size;
    }
    return -1;
#else
    (void)ucp;
    return -1;
#endif
}

static void guard_segv(int sig, siginfo_t* si, void* uc)
{
    uintptr_t off = (uintptr_t)si->si_addr - (uintptr_t)g_guard_base;
    if (g_guard_base && off >= g_guard_lo && off < g_guard_hi) {
        int owner = g_guard_owner_set && pthread_equal(pthread_self(), g_guard_owner_id);
        if (g_guard_fn((size_t)off, fault_storing(uc), owner)) return; /* the access runs again */
    }
    /* Not this guard's, or not fixable: the handler before it decides. With
     * none, the default comes back and the fault, run again, ends the process
     * as it would have without the guard. */
    if ((g_guard_prev.sa_flags & SA_SIGINFO) && g_guard_prev.sa_sigaction) {
        g_guard_prev.sa_sigaction(sig, si, uc);
        return;
    }
    if (!(g_guard_prev.sa_flags & SA_SIGINFO) && g_guard_prev.sa_handler != SIG_DFL &&
        g_guard_prev.sa_handler != SIG_IGN) {
        g_guard_prev.sa_handler(sig);
        return;
    }
    signal(sig, SIG_DFL);
}

/* The handler runs on an alternate stack where one has been set, so a fault
 * on a stack with no room left can still be reported. Per thread: the
 * installer's here, and the owner's when plat_guard_owner names another. */
static void alt_stack(void)
{
    stack_t ss;
    size_t n = 64 * 1024;
    ss.ss_sp = malloc(n);
    if (!ss.ss_sp) return;
    ss.ss_size = n;
    ss.ss_flags = 0;
    if (sigaltstack(&ss, NULL) != 0) free(ss.ss_sp);
}

int plat_guard_install(void* base, size_t lo, size_t hi, PlatFaultFn fn)
{
    struct sigaction sa;
    g_guard_lo = lo;
    g_guard_hi = hi;
    g_guard_fn = fn;
    g_guard_owner_id = pthread_self();
    g_guard_owner_set = 1;
    g_guard_base = (uint8_t*)base;
    alt_stack();
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = guard_segv;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGSEGV, &sa, &g_guard_prev) == 0) return 1;
    g_guard_base = NULL;
    return 0;
}

void plat_guard_owner(void)
{
    g_guard_owner_id = pthread_self();
    g_guard_owner_set = 1;
    alt_stack();
}
#endif

/* ---- the guest's stack ---------------------------------------------------
 * The recompiled code recurses as deeply as the game does, on the host stack:
 * the Windows build links with a large /STACK for the main thread, and
 * elsewhere the guest gets a thread whose stack is made that size. */
#ifdef _WIN32
int plat_run_on_big_stack(int (*fn)(void*), void* arg, size_t bytes)
{
    (void)bytes;
    return fn(arg);
}
#else
typedef struct {
    int (*fn)(void*);
    void* arg;
    int rc;
} BigStack;

static void* big_stack_main(void* p)
{
    BigStack* b = (BigStack*)p;
    b->rc = b->fn(b->arg);
    return NULL;
}

int plat_run_on_big_stack(int (*fn)(void*), void* arg, size_t bytes)
{
    pthread_attr_t attr;
    pthread_t id;
    BigStack b;
    int made;
    b.fn = fn;
    b.arg = arg;
    b.rc = 0;
    pthread_attr_init(&attr);
    made = pthread_attr_setstacksize(&attr, bytes) == 0 && pthread_create(&id, &attr, big_stack_main, &b) == 0;
    pthread_attr_destroy(&attr);
    if (!made) {
        fprintf(stderr, "[plat] cannot start a thread with a %zu MB stack; running on this one\n", bytes >> 20);
        return fn(arg);
    }
    pthread_join(id, NULL);
    return b.rc;
}
#endif
