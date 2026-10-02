/*
 * threads_check's driver (portability.md L7): runtime/threads.c's park and
 * resume on the stack the guest runs on, with no recompiled code and no disc.
 *
 * SelectThread is the only caller of OSSaveContext, and the recompiler wraps
 * the call as cpu.h describes: setjmp at guest_savepoint, the save on the way
 * in, guest_resumed on the way back. A thread that loads its own context --
 * the only kind a run off Windows has, with no second fiber -- must land back
 * at that setjmp with the saved registers and r3 = 1. round_trip() below is
 * that call site, run on plat_run_on_big_stack exactly as main.c runs the
 * guest, twice over the same context.
 *
 * On Linux it also reads the guest thread's stack back: the guest's call
 * depth is the host's, and a thread left at the default 8 MB would be a crash
 * deep in some battle rather than a failed check. Exits 0 when everything
 * holds; threads.c's own failures exit 6.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "plat.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(__linux__)
#include <pthread.h>
#endif

#ifndef GUEST_STACK_BYTES
#error "threads_check.py passes main.c's GUEST_STACK_BYTES"
#endif

/* threads.c's calls into irq.c, and what cpu.h's memory accessors and the
 * fiber entry reach: nothing here is an interrupt, a device or a watch. */
uint32_t irq_interrupted_context(void) { return 0; }
void irq_return_from_handler(void) {}
void irq_abandon_delivery(void) {}
void dispatch(CpuState* s, uint32_t a) { (void)s; (void)a; }
uint32_t g_watch_addr, g_watch_len;
void watch_hit(CpuState* s, uint32_t e, unsigned n, uint64_t v) { (void)s; (void)e; (void)n; (void)v; }
void gx_pipe_write(CpuState* s, unsigned n, uint64_t v) { (void)s; (void)n; (void)v; }
uint8_t mmio_read8(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
uint16_t mmio_read16(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
uint32_t mmio_read32(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
uint64_t mmio_read64(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
void mmio_write8(CpuState* s, uint32_t e, uint8_t v) { (void)s; (void)e; (void)v; }
void mmio_write16(CpuState* s, uint32_t e, uint16_t v) { (void)s; (void)e; (void)v; }
void mmio_write32(CpuState* s, uint32_t e, uint32_t v) { (void)s; (void)e; (void)v; }
void mmio_write64(CpuState* s, uint32_t e, uint64_t v) { (void)s; (void)e; (void)v; }

void threads_init(CpuState* s);
void threads_report(void);
void fn_80233544(CpuState* s); /* OSSaveContext */
void fn_802335C4(CpuState* s); /* OSLoadContext: never returns */

#define CTX 0x80300000u   /* a guest OSContext, anywhere in MEM1 */
#define STACK 0x80400000u /* r1 at the save */

static int g_bad;

static void expect(int ok, const char* what, uint32_t got, uint32_t want)
{
    if (ok) return;
    printf("[threads_check] %s: %08X, wanted %08X\n", what, got, want);
    g_bad++;
}

/* One save, a clobber, and a load of the same context: the shape of a
 * thread that SelectThread picks again. `phase` lives across the longjmp, so
 * it is volatile; the CpuState is memory threads.c rewrites, not a local. */
static void round_trip(CpuState* s, uint32_t tag)
{
    volatile int phase = 0;
    s->gpr[1] = STACK;
    s->gpr[3] = CTX;
    s->gpr[31] = tag;
    s->lr = 0x80237BA8u;
    if (setjmp(*guest_savepoint(s)) == 0) {
        fn_80233544(s);
        expect(s->gpr[3] == 0, "OSSaveContext's first return", s->gpr[3], 0);
        phase = 1;
        /* What the scheduler does between the save and the load. */
        s->gpr[1] = STACK - 0x100u;
        s->gpr[31] = 0xDEADBEEFu;
        s->gpr[3] = CTX;
        fn_802335C4(s);
        printf("[threads_check] OSLoadContext returned\n");
        exit(1);
    }
    guest_resumed(s);
    expect(phase == 1, "resumed without a save", (uint32_t)phase, 1);
    expect(s->gpr[3] == 1, "OSSaveContext's second return", s->gpr[3], 1);
    expect(s->gpr[31] == tag, "r31 after the resume", s->gpr[31], tag);
    expect(s->gpr[1] == STACK, "r1 after the resume", s->gpr[1], STACK);
    expect(mem_r32(s, CTX + 4 * 31) == tag, "r31 in the guest's OSContext", mem_r32(s, CTX + 4 * 31), tag);
}

static int guest(void* p)
{
    CpuState* s = (CpuState*)p;
#if defined(__linux__)
    {
        pthread_attr_t a;
        size_t got = 0;
        if (pthread_getattr_np(pthread_self(), &a) == 0) {
            pthread_attr_getstacksize(&a, &got);
            pthread_attr_destroy(&a);
        }
        printf("[threads_check] the guest's stack: %zu bytes, asked for %zu\n", got, (size_t)GUEST_STACK_BYTES);
        if (got < (size_t)GUEST_STACK_BYTES || got < ((size_t)32 << 20)) {
            printf("[threads_check] the guest's stack is smaller than main.c asks for\n");
            g_bad++;
        }
    }
#else
    printf("[threads_check] the guest's stack: the main thread's, sized by the link's /STACK\n");
#endif
    round_trip(s, 0x1234u);
    round_trip(s, 0x5678u); /* the same context and jmp_buf, a second time */
    return 0;
}

int main(void)
{
    static CpuState s;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    if (!s.mem) return 2;
    threads_init(&s);
    plat_run_on_big_stack(guest, &s, (size_t)GUEST_STACK_BYTES);
    threads_report();
    if (g_bad) {
        printf("[threads_check] %d check(s) failed\n", g_bad);
        return 1;
    }
    printf("[threads_check] ok: two same-stack OSSaveContext/OSLoadContext round trips\n");
    return 0;
}
