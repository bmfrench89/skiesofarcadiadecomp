"""Gekko instruction decoder tests.

Encodings here are hand-derived from the PowerPC 750CL manual and cross-checked
against words actually present in the game binary (noted where that applies).
No game data is required to run these.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa.ppc import decode  # noqa: E402
from soa.ppc.decode import sign_extend, spr_number  # noqa: E402
from soa.ppc.isa import Form  # noqa: E402


# --------------------------------------------------------------------------
# field helpers
# --------------------------------------------------------------------------


def test_sign_extend():
    assert sign_extend(0x7FFF, 16) == 32767
    assert sign_extend(0x8000, 16) == -32768
    assert sign_extend(0xFFFF, 16) == -1
    assert sign_extend(0xFFF, 12) == -1
    assert sign_extend(0x800, 12) == -2048


def test_spr_number_halves_are_swapped():
    """SPR fields store the low 5 bits first. mflr r0 = 0x7C0802A6 -> SPR 8."""
    assert spr_number(0x7C0802A6) == 8  # LR
    assert spr_number(0x7DC903A6) == 9  # CTR
    # SPR 912 (GQR0) = 0b1110010000: low=0b10000 (16), high=0b11100 (28)
    word = (31 << 26) | (16 << 16) | (28 << 11)
    assert spr_number(word) == 912


# --------------------------------------------------------------------------
# instructions observed in the real binary
# --------------------------------------------------------------------------


def test_mflr():
    i = decode(0x7C0802A6)
    assert i.valid and i.mnemonic == "mfspr"
    assert i.spr == 8 and i.rd == 0


def test_mtctr_sets_ctr():
    i = decode(0x7DC903A6)
    assert i.mnemonic == "mtspr" and i.spr == 9
    assert i.rd == 14
    assert i.writes_ctr


def test_stwu_negative_displacement():
    """stwu r1, -8(r1) — the standard prologue."""
    i = decode(0x9421FFF8)
    assert i.mnemonic == "stwu"
    assert i.rd == 1 and i.ra == 1 and i.imm == -8


def test_nop():
    i = decode(0x60000000)
    assert i.mnemonic == "ori"
    assert i.rd == 0 and i.ra == 0 and i.imm == 0


def test_lis():
    i = decode(0x3C608000)
    assert i.mnemonic == "addis"
    assert i.rd == 3 and i.ra == 0
    assert i.imm == sign_extend(0x8000, 16)


# --------------------------------------------------------------------------
# branches
# --------------------------------------------------------------------------


def test_blr_is_a_return():
    i = decode(0x4E800020)
    assert i.mnemonic == "bclr"
    assert i.bo == 20
    assert i.is_return
    assert i.is_indirect_branch
    assert not i.is_call


def test_bctrl_is_an_indirect_call():
    i = decode(0x4E800421)
    assert i.mnemonic == "bcctr"
    assert i.lk_bit
    assert i.is_call and i.is_indirect_branch
    assert not i.is_return


def test_relative_branch_target():
    i = decode(0x48000100, addr=0x80000000)
    assert i.mnemonic == "b" and not i.lk_bit
    assert i.target == 0x80000100


def test_backward_branch_target():
    # b -4  => LI = 0x03FFFFFC (-4 sign-extended)
    i = decode(0x4BFFFFFC, addr=0x80001000)
    assert i.target == 0x80000FFC


def test_branch_and_link_is_a_call():
    i = decode(0x48000101, addr=0x80000000)
    assert i.mnemonic == "b" and i.lk_bit and i.is_call
    assert i.target == 0x80000100


def test_absolute_branch_ignores_pc():
    i = decode(0x48000102, addr=0x80000000)  # AA=1
    assert i.aa_bit and i.target == 0x100


def test_conditional_branch_fields():
    # bc 12, 0, +8  -> BO=12, BI=0
    word = (16 << 26) | (12 << 21) | (0 << 16) | 8
    i = decode(word, addr=0x80000000)
    assert i.mnemonic == "bc" and i.bo == 12 and i.target == 0x80000008
    assert not i.is_unconditional


def test_unconditional_bc():
    word = (16 << 26) | (20 << 21) | 8
    assert decode(word).is_unconditional


# --------------------------------------------------------------------------
# Gekko paired singles
# --------------------------------------------------------------------------


def test_ps_add():
    # ps_add f1, f2, f3 — opcode 4, 5-bit extended opcode 21, A-form
    word = (4 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (21 << 1)
    i = decode(word)
    assert i.mnemonic == "ps_add" and i.form is Form.A
    assert i.rd == 1 and i.ra == 2 and i.rb == 3
    assert i.is_paired_single


def test_ps_madd_uses_frc():
    # ps_madd f1, f2, f4, f3 — frC lives in bits 6-10
    word = (4 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (4 << 6) | (29 << 1)
    i = decode(word)
    assert i.mnemonic == "ps_madd"
    assert i.rc == 4


def test_ps_merge_uses_10bit_opcode():
    word = (4 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (528 << 1)
    assert decode(word).mnemonic == "ps_merge00"


def test_dcbz_l():
    word = (4 << 26) | (1014 << 1)
    assert decode(word).mnemonic == "dcbz_l"


def test_psq_l_fields():
    """psq_l f1, 8(r3), W=0, GQR=2 — 12-bit displacement, not 16."""
    word = (56 << 26) | (1 << 21) | (3 << 16) | (0 << 15) | (2 << 12) | 8
    i = decode(word)
    assert i.mnemonic == "psq_l" and i.form is Form.PSQ
    assert i.rd == 1 and i.ra == 3
    assert i.gqr == 2 and i.quant_w == 0 and i.imm == 8
    assert i.is_paired_single


def test_psq_st_negative_displacement():
    word = (60 << 26) | (1 << 21) | (3 << 16) | (1 << 15) | (5 << 12) | 0xFF8
    i = decode(word)
    assert i.mnemonic == "psq_st"
    assert i.quant_w == 1 and i.gqr == 5 and i.imm == -8


def test_psq_lx_uses_6bit_opcode():
    """psq_lx is X-form with GQR in bits 7-9 and W in bit 10."""
    word = (4 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (1 << 10) | (4 << 7) | (6 << 1)
    i = decode(word)
    assert i.mnemonic == "psq_lx" and i.form is Form.PSQX
    assert i.rd == 1 and i.ra == 2 and i.rb == 3
    assert i.quant_w == 1 and i.gqr == 4


def test_gqr_write_is_flagged():
    # mtspr GQR0 (912), r3
    word = (31 << 26) | (3 << 21) | (16 << 16) | (28 << 11) | (467 << 1)
    i = decode(word)
    assert i.spr == 912 and i.writes_gqr


# --------------------------------------------------------------------------
# other forms
# --------------------------------------------------------------------------


def test_rlwinm_mask_fields():
    # rlwinm r3, r4, 8, 16, 31
    word = (21 << 26) | (4 << 21) | (3 << 16) | (8 << 11) | (16 << 6) | (31 << 1)
    i = decode(word)
    assert i.mnemonic == "rlwinm"
    assert i.rd == 4 and i.ra == 3 and i.imm == 8
    assert i.mb == 16 and i.me == 31


def test_record_bit():
    add = (31 << 26) | (3 << 21) | (4 << 16) | (5 << 11) | (266 << 1)
    assert not decode(add).rc_bit
    assert decode(add | 1).rc_bit


def test_overflow_bit():
    add = (31 << 26) | (3 << 21) | (4 << 16) | (5 << 11) | (266 << 1)
    assert not decode(add).oe_bit
    assert decode(add | (1 << 10)).oe_bit


def test_unsigned_immediate_not_sign_extended():
    ori = (24 << 26) | (3 << 21) | (3 << 16) | 0xFFFF
    assert decode(ori).imm == 0xFFFF
    addi = (14 << 26) | (3 << 21) | (3 << 16) | 0xFFFF
    assert decode(addi).imm == -1


def test_float_a_form():
    word = (63 << 26) | (1 << 21) | (2 << 16) | (3 << 11) | (4 << 6) | (29 << 1)
    i = decode(word)
    assert i.mnemonic == "fmadd" and i.rc == 4


def test_float_x_form():
    word = (63 << 26) | (1 << 21) | (3 << 11) | (72 << 1)
    assert decode(word).mnemonic == "fmr"


# --------------------------------------------------------------------------
# invalid input
# --------------------------------------------------------------------------


def test_decoder_is_total_on_garbage():
    """Text sections contain embedded data; decoding must never raise."""
    for word in (0x00000000, 0x4D657472, 0xFFFFFFFF, 0x6F776572):
        i = decode(word, addr=0x80003400)
        assert isinstance(i.valid, bool)


def test_opcode_zero_is_invalid():
    assert not decode(0x00000000).valid


def test_ascii_text_does_not_decode_as_op19():
    """0x4D657472 is ASCII and must not be mistaken for a branch."""
    assert not decode(0x4D657472).valid
