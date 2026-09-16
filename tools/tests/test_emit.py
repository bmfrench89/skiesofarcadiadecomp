"""Recompiler emitter tests.

The first group checks generated C textually. The last one is the real
thing: it translates a synthetic function, compiles it with MSVC against
runtime/cpu.h, runs it, and checks the guest registers and memory came out
right. It skips itself where MSVC is not installed.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import toolchain  # noqa: E402
from soa.ppc import cfg  # noqa: E402
from soa.recomp import Emitter, c_name  # noqa: E402
from soa.recomp.emit import crm_mask, ppc_mask  # noqa: E402
from test_cfg import (  # noqa: E402
    BASE,
    BLR,
    NOP,
    bc,
    bl,
    make_dol,
    rlwinm_x4,
    stw,
    stwu,
)

RUNTIME = Path(__file__).resolve().parents[2] / "runtime"


def emit(words, data_words=(), data_base=0x80400000):
    dol = make_dol(words, data_words=data_words, data_base=data_base)
    fns, _ = cfg.build_iterative(dol)
    tables = cfg.find_jump_tables(dol)
    em = Emitter(dol, fns, tables)
    return {a: em.function_c(f) for a, f in fns.items()}, em.stats


def add(rd, ra, rb):
    return (31 << 26) | (rd << 21) | (ra << 16) | (rb << 11) | (266 << 1)


def lwz(rd, ra, d):
    return (32 << 26) | (rd << 21) | (ra << 16) | (d & 0xFFFF)


# --------------------------------------------------------------------------
# masks
# --------------------------------------------------------------------------


def test_ppc_mask():
    assert ppc_mask(0, 31) == 0xFFFFFFFF
    assert ppc_mask(16, 31) == 0x0000FFFF
    assert ppc_mask(0, 15) == 0xFFFF0000
    assert ppc_mask(0, 29) == 0xFFFFFFFC
    assert ppc_mask(31, 31) == 0x00000001
    # wrapping mask: mb > me
    assert ppc_mask(28, 3) == 0xF000000F


def test_crm_mask():
    assert crm_mask(0x80) == 0xF0000000
    assert crm_mask(0x01) == 0x0000000F
    assert crm_mask(0xFF) == 0xFFFFFFFF


# --------------------------------------------------------------------------
# generated text
# --------------------------------------------------------------------------


def test_function_shape():
    cs, st = emit([stwu(-16), add(3, 3, 4), BLR])
    c = cs[BASE]
    assert c.startswith(f"void {c_name(BASE)}(CpuState* s)")
    assert "s->gpr[3] = s->gpr[3] + s->gpr[4];" in c
    assert "return;" in c
    assert st.coverage_pct == 100.0


def test_r0_as_base_reads_zero():
    cs, _ = emit([lwz(3, 0, 0x100), BLR])
    assert "mem_r32(s, (0u + 0x00000100u))" in cs[BASE]


def test_negative_displacement_is_two_complement():
    cs, _ = emit([stwu(-16), BLR])
    assert "0xFFFFFFF0u" in cs[BASE]
    assert "s->gpr[1] = ea;" in cs[BASE]


def test_call_sets_lr_and_calls_target():
    #  0: stwu ; 4: bl +8 (-> 12) ; 8: blr ; 12: callee: blr
    cs, _ = emit([stwu(-16), bl(8), BLR, BLR])
    assert f"s->lr = 0x{BASE + 8:08X}u; {c_name(BASE + 12)}(s);" in cs[BASE]
    assert BASE + 12 in cs


def test_local_branch_is_goto_and_label():
    cs, _ = emit([bc(8, bo=12) | (2 << 16), NOP, BLR])
    c = cs[BASE]
    assert f"goto L_{BASE + 8:08X};" in c
    assert f"L_{BASE + 8:08X}:;" in c
    assert "(cr_bit(s, 2) == 1)" in c


def test_ctr_decrement_branch():
    bdnz = bc(-4, bo=16)  # decrement CTR, branch if nonzero
    cs, _ = emit([NOP, bdnz, BLR])
    c = cs[BASE]
    assert "s->ctr--;" in c
    assert "(s->ctr != 0)" in c


def test_conditional_return():
    beqlr = (19 << 26) | (12 << 21) | (2 << 16) | (16 << 1)
    cs, _ = emit([beqlr, NOP, BLR])
    assert "if ((cr_bit(s, 2) == 1)) return;" in cs[BASE]


def test_switch_table_becomes_switch():
    from test_cfg import switch_dol

    dol, targets = switch_dol(0x80400000)
    fns, _ = cfg.build_iterative(dol)
    em = Emitter(dol, fns, cfg.find_jump_tables(dol))
    c = em.function_c(fns[BASE])
    assert "switch (s->ctr) {" in c
    for t in targets:
        assert f"case 0x{t:08X}u: goto L_{t:08X};" in c
    assert em.stats.unsupported == {}


def test_unresolved_bctr_is_counted():
    cs, st = emit([stwu(-16), 0x4E800420])
    assert 'guest_unimplemented(s, 0x80003104u, "bctr-unresolved");' in cs[BASE]
    assert st.unsupported["bcctr"] == 1


def test_paired_single_reads_before_it_writes():
    """ps_add f1, f1, f3: rD aliases a source, so both inputs go to temporaries."""
    ps_add = (4 << 26) | (1 << 21) | (1 << 16) | (3 << 11) | (21 << 1)
    cs, st = emit([ps_add, BLR])
    c = cs[BASE]
    assert "double t0 = (double)(float)(s->fpr[1].ps0 + s->fpr[3].ps0);" in c
    assert "double t1 = (double)(float)(s->fpr[1].ps1 + s->fpr[3].ps1);" in c
    assert "s->fpr[1].ps0 = t0; s->fpr[1].ps1 = t1;" in c
    assert st.coverage_pct == 100.0


def test_ps_muls0_broadcasts_c_ps0():
    ps_muls0 = (4 << 26) | (1 << 21) | (2 << 16) | (0 << 11) | (3 << 6) | (12 << 1)
    cs, _ = emit([ps_muls0, BLR])
    c = cs[BASE]
    assert "(s->fpr[2].ps0 * s->fpr[3].ps0)" in c
    assert "(s->fpr[2].ps1 * s->fpr[3].ps0)" in c


def test_ps_merge10_swaps_halves():
    ps_merge10 = (4 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (592 << 1)
    cs, _ = emit([ps_merge10, BLR])
    c = cs[BASE]
    assert "double t0 = (double)(float)(s->fpr[2].ps1);" in c
    assert "double t1 = (double)(float)(s->fpr[3].ps0);" in c


def test_psq_load_and_store_forms():
    psq_l = (56 << 26) | (1 << 21) | (6 << 16) | (0 << 15) | (2 << 12) | 8  # f1, 8(r6), W=0, GQR2
    psq_stu = (61 << 26) | (1 << 21) | (6 << 16) | (1 << 15) | (5 << 12) | 0xFF0  # W=1, GQR5, -16
    cs, st = emit([psq_l, psq_stu, BLR])
    c = cs[BASE]
    assert "psq_load(s, 1, (s->gpr[6] + 0x00000008u), 2, 0);" in c
    assert "psq_store(s, 1, ea, 5, 1); s->gpr[6] = ea;" in c
    assert st.coverage_pct == 100.0


def test_rlwinm_uses_precomputed_mask():
    cs, _ = emit([rlwinm_x4(0, 3), BLR])
    assert "s->gpr[0] = rotl32(s->gpr[3], 2) & 0xFFFFFFFCu;" in cs[BASE]


def test_single_precision_fills_both_halves():
    fadds = (59 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (21 << 1)
    fadd = (63 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (21 << 1)
    cs, _ = emit([fadds, fadd, BLR])
    c = cs[BASE]
    assert "s->fpr[1].ps0 = s->fpr[1].ps1 = (double)(float)(s->fpr[2].ps0 + s->fpr[3].ps0);" in c
    assert "s->fpr[1].ps0 = s->fpr[2].ps0 + s->fpr[3].ps0;" in c


def test_fused_multiply_add_uses_fma():
    fmadd = (63 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (4 << 6) | (29 << 1)
    cs, _ = emit([fmadd, BLR])
    assert "fma(s->fpr[2].ps0, s->fpr[4].ps0, s->fpr[3].ps0)" in cs[BASE]


def test_cr_logical_uses_all_three_slots():
    # crxor crb6, crb6, crb6  == crclr 6
    crxor = (19 << 26) | (6 << 21) | (6 << 16) | (6 << 11) | (193 << 1)
    cs, _ = emit([crxor, BLR])
    assert "cr_set_bit(s, 6, (cr_bit(s, 6) ^ cr_bit(s, 6)) & 1);" in cs[BASE]


# --------------------------------------------------------------------------
# end to end: translate, compile with MSVC, run
# --------------------------------------------------------------------------

STUBS = r"""
#include "cpu.h"
#include <stdio.h>
uint8_t  mmio_read8 (CpuState* s, uint32_t ea){(void)s;(void)ea;return 0;}
uint16_t mmio_read16(CpuState* s, uint32_t ea){(void)s;(void)ea;return 0;}
uint32_t mmio_read32(CpuState* s, uint32_t ea){(void)s;(void)ea;return 0;}
uint64_t mmio_read64(CpuState* s, uint32_t ea){(void)s;(void)ea;return 0;}
void mmio_write8 (CpuState* s, uint32_t ea, uint8_t v){(void)s;(void)ea;(void)v;}
void mmio_write16(CpuState* s, uint32_t ea, uint16_t v){(void)s;(void)ea;(void)v;}
void mmio_write32(CpuState* s, uint32_t ea, uint32_t v){(void)s;(void)ea;(void)v;}
void mmio_write64(CpuState* s, uint32_t ea, uint64_t v){(void)s;(void)ea;(void)v;}
void dispatch(CpuState* s, uint32_t a){(void)s;(void)a;}
void irq_poll(CpuState* s){(void)s;}
uint32_t g_watch_addr, g_watch_len;
void watch_hit(CpuState* s, uint32_t ea, unsigned size, uint64_t v){(void)s;(void)ea;(void)size;(void)v;}
void guest_trap(CpuState* s, uint32_t pc){(void)s;(void)pc;}
void guest_syscall(CpuState* s, uint32_t pc){(void)s;(void)pc;}
void guest_unimplemented(CpuState* s, uint32_t pc, const char* w){(void)s;(void)pc;(void)w;}
uint32_t guest_timebase_lo(CpuState* s){(void)s;return 0;}
uint32_t guest_timebase_hi(CpuState* s){(void)s;return 0;}
"""

MAIN = r"""
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
void FN(CpuState* s);
int main(void) {
    static CpuState s;
    s.mem = (uint8_t*)calloc(1, 0x20000);
    s.gpr[3] = 40; s.gpr[4] = 2; s.gpr[6] = 0x80001000u;
    FN(&s);
    printf("r3=%u r5=%u m=%02x%02x%02x%02x\n", s.gpr[3], s.gpr[5],
           s.mem[0x1000], s.mem[0x1001], s.mem[0x1002], s.mem[0x1003]);
    return (s.gpr[3] == 42 && s.gpr[5] == 2 && s.mem[0x1003] == 2 && s.mem[0x1000] == 0) ? 0 : 1;
}
"""


PS_MAIN = r"""
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
void FN(CpuState* s);
static void put_f32(uint8_t* p, float f) { uint32_t b; memcpy(&b, &f, 4); b = BSWAP32(b); memcpy(p, &b, 4); }
static float get_f32(const uint8_t* p) { uint32_t b; memcpy(&b, p, 4); b = BSWAP32(b); float f; memcpy(&f, &b, 4); return f; }
int main(void) {
    static CpuState s;
    s.mem = (uint8_t*)calloc(1, 0x20000);
    s.gpr[6] = 0x80001000u;
    s.gqr[0] = 0;              /* f32, scale 0 */
    s.gqr[1] = 0x08040804u;    /* u8, scale 8 both ways -- the game's real GQR1 */
    put_f32(s.mem + 0x1000, 1.5f); put_f32(s.mem + 0x1004, 2.5f);
    FN(&s);
    float a = get_f32(s.mem + 0x1008), b = get_f32(s.mem + 0x100C);
    printf("ps=(%g,%g) f32=(%g,%g) u8=(%u,%u)\n", s.fpr[1].ps0, s.fpr[1].ps1, a, b,
           s.mem[0x1010], s.mem[0x1011]);
    return (a == 3.0f && b == 5.0f && s.mem[0x1010] == 255 && s.mem[0x1011] == 128) ? 0 : 1;
}
"""


@pytest.mark.skipif(toolchain.msvc_env() is None, reason="MSVC not installed")
def test_paired_singles_compile_and_run(tmp_path):
    """psq_l f1,0(r6),0,GQR0 ; ps_add f1,f1,f1 ; psq_st f1,8(r6),0,GQR0 ;
    psq_st f2,16(r6),0,GQR1 ; blr  -- with f2 = (1.0, 0.5) quantized to u8 x256.

    Checks the float path doubles (1.5,2.5) into (3,5) in memory, and the
    quantized store scales and saturates: 1.0*256 -> 255, 0.5*256 -> 128.
    """
    psq_l = (56 << 26) | (1 << 21) | (6 << 16) | (0 << 15) | (0 << 12) | 0
    ps_add = (4 << 26) | (1 << 21) | (1 << 16) | (1 << 11) | (21 << 1)
    psq_st = (60 << 26) | (1 << 21) | (6 << 16) | (0 << 15) | (0 << 12) | 8
    psq_st_u8 = (60 << 26) | (2 << 21) | (6 << 16) | (0 << 15) | (1 << 12) | 16
    cs, st = emit([psq_l, ps_add, psq_st, psq_st_u8, BLR])
    assert st.coverage_pct == 100.0

    fn_src = cs[BASE].replace(
        f"void {c_name(BASE)}(CpuState* s)\n{{",
        f"void {c_name(BASE)}(CpuState* s)\n{{\n    s->fpr[2].ps0 = 1.0; s->fpr[2].ps1 = 0.5;",
    )
    (tmp_path / "fn.c").write_text('#include "cpu.h"\n' + fn_src, encoding="utf-8")
    (tmp_path / "stubs.c").write_text(STUBS, encoding="utf-8")
    (tmp_path / "main.c").write_text(PS_MAIN.replace("FN", c_name(BASE)), encoding="utf-8")

    proc = toolchain.cl(
        [*toolchain.CFLAGS, f"/I{RUNTIME}", "fn.c", "stubs.c", "main.c", "/Fe:t.exe"], cwd=tmp_path
    )
    assert proc.returncode == 0, proc.stdout
    run = subprocess.run([str(tmp_path / "t.exe")], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout
    assert "ps=(3,5) f32=(3,5) u8=(255,128)" in run.stdout


@pytest.mark.skipif(toolchain.msvc_env() is None, reason="MSVC not installed")
def test_translate_compile_and_run(tmp_path):
    """stw r4,0(r6); lwz r5,0(r6); add r3,r3,r5; blr  -- run natively."""
    words = [stw(4, 6, 0), lwz(5, 6, 0), add(3, 3, 5), BLR]
    cs, st = emit(words)
    assert st.coverage_pct == 100.0

    (tmp_path / "fn.c").write_text('#include "cpu.h"\n' + cs[BASE], encoding="utf-8")
    (tmp_path / "stubs.c").write_text(STUBS, encoding="utf-8")
    (tmp_path / "main.c").write_text(MAIN.replace("FN", c_name(BASE)), encoding="utf-8")

    proc = toolchain.cl(
        [*toolchain.CFLAGS, f"/I{RUNTIME}", "fn.c", "stubs.c", "main.c", "/Fe:t.exe"], cwd=tmp_path
    )
    assert proc.returncode == 0, proc.stdout
    run = subprocess.run([str(tmp_path / "t.exe")], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stdout
    assert "r3=42 r5=2 m=00000002" in run.stdout
