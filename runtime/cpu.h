/*
 * Guest CPU state and memory access for the recompiled program.
 *
 * Generated C (gen/*.c) and hand-written HLE both operate on this one struct
 * (SPEC section 4.3), so a decompiled or HLE'd function can replace a
 * recompiled one at link time without touching its callers.
 *
 * Memory is a single 24 MB big-endian image (SPEC section 5). The cached,
 * uncached and real-mode windows all resolve to it through MEM_MASK, and the
 * hardware range traps to the runtime's device models. Every load and store
 * byte-swaps on access: the image has to stay in console byte order because
 * the game's own structures, DMA buffers and display lists live in it, and
 * nothing tells us the type of any given word.
 */
#pragma once
#include <math.h>
#include <setjmp.h>
#include <stdint.h>
#include <string.h>

#define MEM1_SIZE 0x01800000u
#define MEM_MASK 0x01FFFFFFu

#if defined(_MSC_VER)
#include <stdlib.h>
#define BSWAP16(x) _byteswap_ushort(x)
#define BSWAP32(x) _byteswap_ulong(x)
#define BSWAP64(x) _byteswap_uint64(x)
#else
#define BSWAP16(x) __builtin_bswap16(x)
#define BSWAP32(x) __builtin_bswap32(x)
#define BSWAP64(x) __builtin_bswap64(x)
#endif

typedef struct CpuState CpuState;
typedef void (*GuestFn)(CpuState*);

/* Gekko FPRs are paired singles: ps0 is the scalar half. */
typedef struct {
    double ps0, ps1;
} Fpr;

struct CpuState {
    uint32_t gpr[32];
    Fpr fpr[32];
    uint32_t cr, xer, lr, ctr, fpscr, msr, dec;
    uint32_t pc; /* address of the basic block being executed; diagnostics only */
    uint32_t gqr[8];
    uint32_t hid2, wpar;
    uint32_t spr[1024]; /* everything not modelled explicitly above */
    uint32_t sr[16];    /* segment registers; OS init writes them, nothing reads */
    uint8_t gp_buf[32]; /* write-gather pipe accumulator (SPEC section 7) */
    uint32_t gp_len;
    uint8_t* mem; /* MEM1 backing store, console byte order */
    void* user;   /* runtime-private */
};

/* ---- provided by the runtime ------------------------------------------ */

uint8_t mmio_read8(CpuState* s, uint32_t ea);
uint16_t mmio_read16(CpuState* s, uint32_t ea);
uint32_t mmio_read32(CpuState* s, uint32_t ea);
uint64_t mmio_read64(CpuState* s, uint32_t ea);
void mmio_write8(CpuState* s, uint32_t ea, uint8_t v);
void mmio_write16(CpuState* s, uint32_t ea, uint16_t v);
void mmio_write32(CpuState* s, uint32_t ea, uint32_t v);
void mmio_write64(CpuState* s, uint32_t ea, uint64_t v);

void dispatch(CpuState* s, uint32_t addr); /* call through a computed address */
void guest_trap(CpuState* s, uint32_t pc);
void guest_syscall(CpuState* s, uint32_t pc);
void guest_unimplemented(CpuState* s, uint32_t pc, const char* what);
uint32_t guest_timebase_lo(CpuState* s);
uint32_t guest_timebase_hi(CpuState* s);
void dec_write(CpuState* s, uint32_t v); /* mtspr DEC: arms the decrementer */
uint32_t dec_read(CpuState* s);          /* mfspr DEC: what is left on it */

/* Thread parking (runtime/threads.c). The recompiler wraps the one call to
 * OSSaveContext as
 *     if (setjmp(*guest_savepoint(s)) == 0) fn_OSSaveContext(s); else guest_resumed(s);
 * so a thread's resume point is a live frame in its own SelectThread. */
jmp_buf* guest_savepoint(CpuState* s);
void guest_resumed(CpuState* s);

/* ---- memory ------------------------------------------------------------ */

static inline int is_mmio(uint32_t ea)
{
    uint32_t hi = ea >> 24;
    return hi == 0xCCu || hi == 0xE0u;
}

static inline uint8_t* mem_ptr(CpuState* s, uint32_t ea)
{
    return s->mem + (ea & MEM_MASK);
}

static inline uint8_t mem_r8(CpuState* s, uint32_t ea)
{
    if (is_mmio(ea)) return mmio_read8(s, ea);
    return *mem_ptr(s, ea);
}
static inline uint16_t mem_r16(CpuState* s, uint32_t ea)
{
    uint16_t v;
    if (is_mmio(ea)) return mmio_read16(s, ea);
    memcpy(&v, mem_ptr(s, ea), 2);
    return BSWAP16(v);
}
static inline uint32_t mem_r32(CpuState* s, uint32_t ea)
{
    uint32_t v;
    if (is_mmio(ea)) return mmio_read32(s, ea);
    memcpy(&v, mem_ptr(s, ea), 4);
    return BSWAP32(v);
}
static inline uint64_t mem_r64(CpuState* s, uint32_t ea)
{
    uint64_t v;
    if (is_mmio(ea)) return mmio_read64(s, ea);
    memcpy(&v, mem_ptr(s, ea), 8);
    return BSWAP64(v);
}
static inline void mem_w8(CpuState* s, uint32_t ea, uint8_t v)
{
    if (is_mmio(ea)) { mmio_write8(s, ea, v); return; }
    *mem_ptr(s, ea) = v;
}
static inline void mem_w16(CpuState* s, uint32_t ea, uint16_t v)
{
    if (is_mmio(ea)) { mmio_write16(s, ea, v); return; }
    v = BSWAP16(v);
    memcpy(mem_ptr(s, ea), &v, 2);
}
static inline void mem_w32(CpuState* s, uint32_t ea, uint32_t v)
{
    if (is_mmio(ea)) { mmio_write32(s, ea, v); return; }
    v = BSWAP32(v);
    memcpy(mem_ptr(s, ea), &v, 4);
}
static inline void mem_w64(CpuState* s, uint32_t ea, uint64_t v)
{
    if (is_mmio(ea)) { mmio_write64(s, ea, v); return; }
    v = BSWAP64(v);
    memcpy(mem_ptr(s, ea), &v, 8);
}

static inline float mem_rf32(CpuState* s, uint32_t ea)
{
    uint32_t b = mem_r32(s, ea);
    float f;
    memcpy(&f, &b, 4);
    return f;
}
static inline double mem_rf64(CpuState* s, uint32_t ea)
{
    uint64_t b = mem_r64(s, ea);
    double d;
    memcpy(&d, &b, 8);
    return d;
}
static inline void mem_wf32(CpuState* s, uint32_t ea, float f)
{
    uint32_t b;
    memcpy(&b, &f, 4);
    mem_w32(s, ea, b);
}
static inline void mem_wf64(CpuState* s, uint32_t ea, double d)
{
    uint64_t b;
    memcpy(&b, &d, 8);
    mem_w64(s, ea, b);
}

/* dcbz: zero the 32-byte cache line. The game uses it as a fast memset. */
static inline void mem_zero32(CpuState* s, uint32_t ea)
{
    if (!is_mmio(ea)) memset(mem_ptr(s, ea & ~31u), 0, 32);
}

static inline void ppc_lmw(CpuState* s, int rd, uint32_t ea)
{
    int r;
    for (r = rd; r < 32; r++, ea += 4) s->gpr[r] = mem_r32(s, ea);
}
static inline void ppc_stmw(CpuState* s, int rs, uint32_t ea)
{
    int r;
    for (r = rs; r < 32; r++, ea += 4) mem_w32(s, ea, s->gpr[r]);
}

/* ---- condition register ------------------------------------------------ */

/* CR field f (0..7) occupies bits 28-4f .. 31-4f, PowerPC numbering from the MSB. */
static inline uint32_t cr_get_field(const CpuState* s, int f)
{
    return (s->cr >> (28 - 4 * f)) & 0xFu;
}
static inline void cr_set_field(CpuState* s, int f, uint32_t bits4)
{
    int sh = 28 - 4 * f;
    s->cr = (s->cr & ~(0xFu << sh)) | ((bits4 & 0xFu) << sh);
}
static inline int cr_bit(const CpuState* s, int bi)
{
    return (int)((s->cr >> (31 - bi)) & 1u);
}
static inline void cr_set_bit(CpuState* s, int bi, int v)
{
    uint32_t m = 1u << (31 - bi);
    s->cr = v ? (s->cr | m) : (s->cr & ~m);
}

#define XER_SO 0x80000000u
#define XER_OV 0x40000000u
#define XER_CA 0x20000000u

static inline uint32_t xer_ca(const CpuState* s) { return (s->xer >> 29) & 1u; }
static inline void xer_set_ca(CpuState* s, uint32_t c)
{
    s->xer = c ? (s->xer | XER_CA) : (s->xer & ~XER_CA);
}

static inline void cr_cmp_s(CpuState* s, int f, int32_t a, int32_t b)
{
    uint32_t c = a < b ? 8u : a > b ? 4u : 2u;
    cr_set_field(s, f, c | ((s->xer & XER_SO) ? 1u : 0u));
}
static inline void cr_cmp_u(CpuState* s, int f, uint32_t a, uint32_t b)
{
    uint32_t c = a < b ? 8u : a > b ? 4u : 2u;
    cr_set_field(s, f, c | ((s->xer & XER_SO) ? 1u : 0u));
}
/* Record forms (`add.`, `andi.`) compare the result against zero into CR0. */
#define CR0_RC(s, v) cr_cmp_s((s), 0, (int32_t)(v), 0)

static inline void cr_fcmp(CpuState* s, int f, double a, double b)
{
    uint32_t c;
    if (a != a || b != b) c = 1u;      /* unordered */
    else if (a < b) c = 8u;
    else if (a > b) c = 4u;
    else c = 2u;
    cr_set_field(s, f, c);
    s->fpscr = (s->fpscr & ~0xF000u) | (c << 12); /* FPCC */
}

/* ---- integer helpers --------------------------------------------------- */

static inline uint32_t rotl32(uint32_t v, unsigned n)
{
    n &= 31u;
    return n ? (v << n) | (v >> (32u - n)) : v;
}

/* Carry-producing arithmetic. 64-bit sums keep the carry-out in bit 32. */
static inline uint32_t ppc_addc(CpuState* s, uint32_t a, uint32_t b)
{
    uint64_t r = (uint64_t)a + b;
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_adde(CpuState* s, uint32_t a, uint32_t b)
{
    uint64_t r = (uint64_t)a + b + xer_ca(s);
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_subfc(CpuState* s, uint32_t a, uint32_t b) /* b - a */
{
    uint64_t r = (uint64_t)(~a) + b + 1u;
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_subfe(CpuState* s, uint32_t a, uint32_t b)
{
    uint64_t r = (uint64_t)(~a) + b + xer_ca(s);
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_addze(CpuState* s, uint32_t a)
{
    uint64_t r = (uint64_t)a + xer_ca(s);
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_subfze(CpuState* s, uint32_t a)
{
    uint64_t r = (uint64_t)(~a) + xer_ca(s);
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_addme(CpuState* s, uint32_t a)
{
    uint64_t r = (uint64_t)a + xer_ca(s) + 0xFFFFFFFFu;
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}
static inline uint32_t ppc_subfme(CpuState* s, uint32_t a)
{
    uint64_t r = (uint64_t)(~a) + xer_ca(s) + 0xFFFFFFFFu;
    xer_set_ca(s, (uint32_t)(r >> 32));
    return (uint32_t)r;
}

static inline uint32_t ppc_slw(uint32_t v, uint32_t n)
{
    n &= 63u;
    return n < 32u ? v << n : 0u;
}
static inline uint32_t ppc_srw(uint32_t v, uint32_t n)
{
    n &= 63u;
    return n < 32u ? v >> n : 0u;
}
/* Arithmetic right shift; CA = a negative value lost set bits. */
static inline uint32_t ppc_srawi(CpuState* s, uint32_t v, unsigned sh)
{
    int32_t x = (int32_t)v;
    xer_set_ca(s, (uint32_t)(x < 0 && sh != 0 && (v & ((1u << sh) - 1u)) != 0));
    return (uint32_t)(x >> sh);
}
static inline uint32_t ppc_sraw(CpuState* s, uint32_t v, uint32_t n)
{
    int32_t x = (int32_t)v;
    n &= 63u;
    if (n >= 32u) {
        xer_set_ca(s, (uint32_t)(x < 0));
        return (uint32_t)(x >> 31);
    }
    return ppc_srawi(s, v, n);
}

static inline uint32_t ppc_cntlzw(uint32_t v)
{
    uint32_t n = 0;
    if (!v) return 32;
    while (!(v & 0x80000000u)) { v <<= 1; n++; }
    return n;
}

static inline uint32_t ppc_mulhw(uint32_t a, uint32_t b)
{
    return (uint32_t)(((int64_t)(int32_t)a * (int64_t)(int32_t)b) >> 32);
}
static inline uint32_t ppc_mulhwu(uint32_t a, uint32_t b)
{
    return (uint32_t)(((uint64_t)a * (uint64_t)b) >> 32);
}
/* Division by zero and INT_MIN/-1 are undefined on the hardware; these
 * results match what the reference emulator settled on. */
static inline uint32_t ppc_divw(uint32_t a, uint32_t b)
{
    int32_t x = (int32_t)a, y = (int32_t)b;
    if (y == 0 || (x == INT32_MIN && y == -1)) return (y == 0 && x < 0) ? 0xFFFFFFFFu : 0u;
    return (uint32_t)(x / y);
}
static inline uint32_t ppc_divwu(uint32_t a, uint32_t b)
{
    return b ? a / b : 0u;
}

/* ---- floating point ---------------------------------------------------- */

static inline uint64_t fpr_bits(const CpuState* s, int n)
{
    uint64_t u;
    memcpy(&u, &s->fpr[n].ps0, 8);
    return u;
}
static inline void fpr_set_bits(CpuState* s, int n, uint64_t u)
{
    memcpy(&s->fpr[n].ps0, &u, 8);
}

/* ---- paired-single quantized load/store (Gekko) ------------------------
 *
 * GQR layout: LD_TYPE bits 16-18, LD_SCALE bits 24-29, ST_TYPE bits 0-2,
 * ST_SCALE bits 8-13. Types: 0 = f32, 4 = u8, 5 = u16, 6 = s8, 7 = s16.
 * A scale is a signed 6-bit power of two: loads multiply by 2^-scale, stores
 * by 2^scale. The float type ignores the scale.
 *
 * This binary installs six constant GQRs and never varies them, so these
 * could be specialised at translation time; they are kept generic until the
 * lockstep differ says the semantics are right (slice 3.4 / 3.7).
 */

static inline int psq_sscale(uint32_t six)
{
    int v = (int)(six & 63u);
    return v > 31 ? v - 64 : v;
}

static inline double psq_load1(CpuState* s, uint32_t ea, uint32_t type, double deq, uint32_t* size)
{
    switch (type) {
    case 4: *size = 1; return (double)mem_r8(s, ea) * deq;
    case 5: *size = 2; return (double)mem_r16(s, ea) * deq;
    case 6: *size = 1; return (double)(int8_t)mem_r8(s, ea) * deq;
    case 7: *size = 2; return (double)(int16_t)mem_r16(s, ea) * deq;
    default: *size = 4; return (double)mem_rf32(s, ea);
    }
}

static inline void psq_load(CpuState* s, int frd, uint32_t ea, int gqr, int w)
{
    uint32_t g = s->gqr[gqr];
    uint32_t type = (g >> 16) & 7u;
    double deq = ldexp(1.0, -psq_sscale(g >> 24));
    uint32_t size;
    double v0 = psq_load1(s, ea, type, deq, &size);
    double v1 = w ? 1.0 : psq_load1(s, ea + size, type, deq, &size);
    s->fpr[frd].ps0 = (double)(float)v0;
    s->fpr[frd].ps1 = (double)(float)v1;
}

/* Truncates toward zero and saturates, as the hardware does. */
static inline int32_t psq_clamp(double q, double lo, double hi)
{
    if (q != q) return 0;
    if (q < lo) q = lo;
    if (q > hi) q = hi;
    return (int32_t)q;
}

static inline void psq_store1(CpuState* s, uint32_t ea, uint32_t type, double quant, double v, uint32_t* size)
{
    double q = v * quant;
    switch (type) {
    case 4: *size = 1; mem_w8(s, ea, (uint8_t)psq_clamp(q, 0.0, 255.0)); break;
    case 5: *size = 2; mem_w16(s, ea, (uint16_t)psq_clamp(q, 0.0, 65535.0)); break;
    case 6: *size = 1; mem_w8(s, ea, (uint8_t)(int8_t)psq_clamp(q, -128.0, 127.0)); break;
    case 7: *size = 2; mem_w16(s, ea, (uint16_t)(int16_t)psq_clamp(q, -32768.0, 32767.0)); break;
    default: *size = 4; mem_wf32(s, ea, (float)v); break;
    }
}

static inline void psq_store(CpuState* s, int frs, uint32_t ea, int gqr, int w)
{
    uint32_t g = s->gqr[gqr];
    uint32_t type = g & 7u;
    double quant = ldexp(1.0, psq_sscale(g >> 8));
    uint32_t size;
    psq_store1(s, ea, type, quant, s->fpr[frs].ps0, &size);
    if (!w) psq_store1(s, ea + size, type, quant, s->fpr[frs].ps1, &size);
}

/* fctiw / fctiwz: the integer lands in the low word; the high word is what
 * the hardware leaves there. NaN and out-of-range saturate. */
static inline uint64_t ppc_fctiw(double d, int truncate)
{
    int32_t i;
    if (d != d) i = INT32_MIN;
    else if (d >= 2147483647.0) i = INT32_MAX;
    else if (d <= -2147483648.0) i = INT32_MIN;
    else i = truncate ? (int32_t)d : (int32_t)nearbyint(d);
    return 0xFFF8000000000000ull | (uint64_t)(uint32_t)i;
}
