"""The addresses tools/disasm.py writes beside a load or a store.

annotate() follows the registers a lis has put a constant in, so that
`lbz r0, 8(r3)` reads as `@ 0x80311AC8` instead of as arithmetic to do by
hand. A wrong annotation is worse than none: it names a real-looking global
that the instruction does not touch, and the reader has no reason to doubt
it. Three ways it was wrong, each tested here on instruction words built by
hand, the way test_regs.py builds them:

- update-form loads and stores (lwzu, stwu, ...) were not recognised, so
  they neither said what they read nor moved their base register, and every
  access through that register afterwards was annotated from the old base;
- ori, or/mr, rlwinm and the rest keep their source in the rD field and
  write rA, and this read them the other way round -- losing the register
  that survived and keeping the one that was overwritten;
- rA=0 in addi (li) and in a D-form load or store is the literal 0, not r0,
  so a lis into r0 leaked into every li that followed.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import disasm  # noqa: E402
from soa.ppc import decode  # noqa: E402

BASE = 0x801019AC

ADDI, ADDIS, ORI = 14, 15, 24
LWZ, LWZU, LBZ, LBZU, STW, STWU, STB, STBU = 32, 33, 34, 35, 36, 37, 38, 39
LHZ, LHZU, LHA, LHAU, STH, STHU = 40, 41, 42, 43, 44, 45
LFS, LFSU, LFD, LFDU, STFS, STFSU, STFD, STFDU = 48, 49, 50, 51, 52, 53, 54, 55


def d(op: int, rd: int, ra: int, imm: int) -> int:
    """A D-form word: the rD (or rS) field, then rA, then the immediate."""
    return (op << 26) | (rd << 21) | (ra << 16) | (imm & 0xFFFF)


def lis(rd: int, imm: int) -> int:
    return d(ADDIS, rd, 0, imm)


def mr(ra: int, rs: int) -> int:
    """or rA, rS, rS -- the destination in the rA field."""
    return (31 << 26) | (rs << 21) | (ra << 16) | (rs << 11) | (444 << 1)


def rlwinm(ra: int, rs: int, sh: int, mb: int, me: int) -> int:
    return (21 << 26) | (rs << 21) | (ra << 16) | (sh << 11) | (mb << 6) | (me << 1)


class Code:
    """What annotate() asks of cfg.CodeView: at(addr) -> Insn."""

    def __init__(self, words: list[int]):
        self.insns = {BASE + 4 * k: decode(w, BASE + 4 * k) for k, w in enumerate(words)}

    def at(self, addr: int):
        return self.insns.get(addr)


def notes(*words: int) -> list[str]:
    end = BASE + 4 * len(words)
    return [note for _, _, note in disasm.annotate(Code(list(words)), {}, BASE, end)]


# --------------------------------------------------------------------------
# (a) update forms
# --------------------------------------------------------------------------


def test_the_update_load_at_801019b4():
    """The case that was found: r3 = 0x80310000, `lwzu r0, 6848(r3)` reads
    0x80311AC0 and leaves r3 there, so the `lbz r0, 8(r3)` after it reads
    0x80311AC8. This printed 0x80310008 for it."""
    got = notes(lis(3, 0x8031), d(LWZU, 0, 3, 6848), d(LBZ, 0, 3, 8))
    assert got == ["", "@ 0x80311AC0", "@ 0x80311AC8"]


UPDATE_FORMS = {
    "lwzu": LWZU,
    "lbzu": LBZU,
    "lhzu": LHZU,
    "lhau": LHAU,
    "stwu": STWU,
    "stbu": STBU,
    "sthu": STHU,
    "lfsu": LFSU,
    "lfdu": LFDU,
    "stfsu": STFSU,
    "stfdu": STFDU,
}


@pytest.mark.parametrize("op", list(UPDATE_FORMS.values()), ids=list(UPDATE_FORMS))
def test_every_update_form_says_where_it_went_and_moves_its_base(op):
    got = notes(lis(3, 0x8031), d(op, 5, 3, 0x100), d(LWZ, 6, 3, 8))
    assert got[1:] == ["@ 0x80310100", "@ 0x80310108"]


def test_an_update_load_still_overwrites_the_register_it_loads():
    got = notes(lis(5, 0x8031), lis(3, 0x8032), d(LWZU, 5, 3, 4), d(LWZ, 6, 5, 0))
    assert got[2:] == ["@ 0x80320004", ""]


# --------------------------------------------------------------------------
# (b) the instructions whose destination is rA
# --------------------------------------------------------------------------


def test_ori_reads_the_rd_field_and_writes_ra():
    """`ori r5, r4, 0x1234`: the source r4 sits in the rD field."""
    got = notes(lis(4, 0x8031), d(ORI, 4, 5, 0x1234), d(LWZ, 6, 5, 0), d(LWZ, 7, 4, 8))
    assert got[1:] == ["= 0x80311234", "@ 0x80311234", "@ 0x80310008"]


def test_ori_is_an_or_not_an_add():
    got = notes(lis(4, 0x8031), d(ADDI, 4, 4, 0x10), d(ORI, 4, 5, 0x11))
    assert got[1:] == ["= 0x80310010", "= 0x80310011"]


def test_mr_and_rlwinm_overwrite_ra_and_leave_their_source_alone():
    """`mr r4, r3` is `or r4, r3, r3`; `rlwinm r5, r3, ...` writes r5. r3 is
    read by both and written by neither, and was the one forgotten."""
    got = notes(
        lis(3, 0x8031),
        lis(4, 0x8032),
        lis(5, 0x8033),
        mr(4, 6),  # r4 now holds whatever r6 did
        rlwinm(5, 3, 2, 0, 29),  # r5 now holds r3 shifted
        d(LWZ, 0, 3, 8),
        d(LWZ, 0, 4, 0),
        d(LWZ, 0, 5, 0),
    )
    assert got[5:] == ["@ 0x80310008", "", ""]


# --------------------------------------------------------------------------
# (c) rA = 0
# --------------------------------------------------------------------------


def test_ra_zero_is_the_literal_zero_in_addi_and_a_load_or_store():
    """lis into r0 is ordinary code. `li r3, 8` is `addi r3, 0, 8` and means
    8; `lwz r5, 16(0)` means address 16. Neither involves r0 -- but ori's
    source field is a register, so `ori r8, r0, 4` does read it."""
    got = notes(
        lis(0, 0x8031),
        d(ADDI, 3, 0, 8),  # li r3, 8
        d(LWZ, 4, 3, 0),
        d(LWZ, 5, 0, 16),
        d(STW, 6, 0, 16),
        d(ORI, 0, 8, 4),
    )
    assert got[1:] == ["", "", "", "", "= 0x80310004"]
