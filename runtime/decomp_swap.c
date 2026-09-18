/*
 * Decompiled functions swapped in for their recompiled twins.
 *
 * Each function here is bound in config/hle.txt, so dispatch() reaches the
 * adapter instead of the translation; the translation survives as
 * recomp_fn_XXXXXXXX and the selftest keeps comparing the two. The adapters
 * marshal the EABI call (arguments in r3..r5, the result in r3) onto the
 * natively compiled decompiled C, which works on the same guest memory
 * through host pointers.
 *
 * What may be swapped in is what config/GEAE8P/units.txt calls native: the
 * unit compiles under MSVC, reads nothing whose meaning depends on byte order,
 * touches no memory-mapped register, and calls nothing undecompiled. A routine
 * that loads whole words out of a string is fine -- strcpy stores each word
 * back at the same alignment, so the bytes land unchanged either way round,
 * and strcmp's one ordering comparison is guarded in the unit itself. A
 * routine that reads a field of one of the game's structures is not, and waits
 * for byte-order-aware accessors over guest memory.
 */
#include "cpu.h"
#include <stddef.h>

size_t dc_strlen(const char* str);
char* dc_strchr(const char* str, int chr);
void* dc_memchr(const void* src, int val, size_t n);
void* dc___memrchr(const void* src, int val, size_t n);
int dc_strncmp(const char* a, const char* b, size_t n);
char* dc_strcat(char* dst, const char* src);
char* dc_strncpy(char* dst, const char* src, size_t n);
void* dc_memcpy(void* dst, const void* src, size_t n);
void* dc_memset(void* dst, int val, size_t n);
char* dc_strcpy(char* dst, const char* src);
char* dc_strstr(const char* str, const char* pat);
int dc_fn_8025EF88(const char* a, const char* b); /* strcmp; the dump has no name for it */

static uint32_t guest(CpuState* s, const void* p) { return p ? 0x80000000u + (uint32_t)((const uint8_t*)p - s->mem) : 0u; }

/* guest() the other way round, for an argument the callee is allowed to be
 * handed as NULL. mem_ptr maps guest address 0 to the first byte of MEM1,
 * which is a real byte, so a callee that tests its argument against NULL --
 * strstr does -- would never see the case it defends against. */
static const void* host(CpuState* s, uint32_t ea) { return ea ? mem_ptr(s, ea) : NULL; }

/* Each adapter stores its own entry address into s->pc before it does any
 * work, so that a sample taken inside the native routine names the routine
 * rather than whoever called it. The recompiled twin these replace stores pc
 * at every basic block -- once per character in strlen's byte loop -- so this
 * is one store per call where there used to be one per iteration, into a
 * cache line the call site has just written s->lr into. memcpy and memset are
 * among the hottest things the game does, and without this their time is
 * charged to the caller's last block, which is worse than invisible: it makes
 * an innocent block look expensive.
 *
 * Deliberately not restored on the way out. The generated call sites do not
 * restore it either -- a caller's straight-line tail after a call is charged
 * to the callee until the caller reaches its next block header -- so a
 * store-only adapter has exactly the attribution shape of the translation it
 * replaces, and costs one store rather than a load, a live register across
 * the call and a second store. Interrupts are the other case and argue the
 * other way: irq.c saves and restores pc around a handler, because
 * interrupted code really is still mid-block. A call is not an interrupt. */
void fn_8025F1D8(CpuState* s) { s->pc = 0x8025F1D8u; s->gpr[3] = (uint32_t)dc_strlen((const char*)mem_ptr(s, s->gpr[3])); }      /* strlen */
void fn_8025EF18(CpuState* s) { s->pc = 0x8025EF18u; s->gpr[3] = guest(s, dc_strchr((const char*)mem_ptr(s, s->gpr[3]), (int)s->gpr[4])); } /* strchr */
void fn_8025C73C(CpuState* s) { s->pc = 0x8025C73Cu; s->gpr[3] = guest(s, dc_memchr(mem_ptr(s, s->gpr[3]), (int)s->gpr[4], s->gpr[5])); }   /* memchr */
void fn_8025C710(CpuState* s) { s->pc = 0x8025C710u; s->gpr[3] = guest(s, dc___memrchr(mem_ptr(s, s->gpr[3]), (int)s->gpr[4], s->gpr[5])); } /* __memrchr */
void fn_8025EF48(CpuState* s) { s->pc = 0x8025EF48u; s->gpr[3] = (uint32_t)dc_strncmp((const char*)mem_ptr(s, s->gpr[3]), (const char*)mem_ptr(s, s->gpr[4]), s->gpr[5]); } /* strncmp */
void fn_8025F0B0(CpuState* s) { s->pc = 0x8025F0B0u; s->gpr[3] = guest(s, dc_strcat((char*)mem_ptr(s, s->gpr[3]), (const char*)mem_ptr(s, s->gpr[4]))); } /* strcat */
void fn_8025F0DC(CpuState* s) { s->pc = 0x8025F0DCu; s->gpr[3] = guest(s, dc_strncpy((char*)mem_ptr(s, s->gpr[3]), (const char*)mem_ptr(s, s->gpr[4]), s->gpr[5])); } /* strncpy */
void fn_80005520(CpuState* s) { s->pc = 0x80005520u; s->gpr[3] = guest(s, dc_memcpy(mem_ptr(s, s->gpr[3]), mem_ptr(s, s->gpr[4]), s->gpr[5])); } /* memcpy */
void fn_80005434(CpuState* s) { s->pc = 0x80005434u; s->gpr[3] = guest(s, dc_memset(mem_ptr(s, s->gpr[3]), (int)s->gpr[4], s->gpr[5])); }        /* memset */
void fn_8025F120(CpuState* s) { s->pc = 0x8025F120u; s->gpr[3] = guest(s, dc_strcpy((char*)mem_ptr(s, s->gpr[3]), (const char*)mem_ptr(s, s->gpr[4]))); } /* strcpy */
void fn_8025EF88(CpuState* s) { s->pc = 0x8025EF88u; s->gpr[3] = (uint32_t)dc_fn_8025EF88((const char*)mem_ptr(s, s->gpr[3]), (const char*)mem_ptr(s, s->gpr[4])); } /* strcmp */
/* Only the pattern goes through host(): the original returns str unread when
 * pat is NULL, and dereferences str without ever testing it. */
void fn_8025ED74(CpuState* s) { s->pc = 0x8025ED74u; s->gpr[3] = guest(s, dc_strstr((const char*)mem_ptr(s, s->gpr[3]), (const char*)host(s, s->gpr[4]))); } /* strstr */
