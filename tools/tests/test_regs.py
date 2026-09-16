"""Register-definition tests: which GPR an instruction actually writes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa.ppc import decode  # noqa: E402
from soa.ppc.regs import gpr_defs, is_mr  # noqa: E402


def test_add_writes_rd():
    add = (31 << 26) | (3 << 21) | (4 << 16) | (5 << 11) | (266 << 1)
    assert gpr_defs(decode(add)) == {3}


def test_addi_writes_rd():
    assert gpr_defs(decode((14 << 26) | (7 << 21) | (1 << 16) | 8)) == {7}


def test_logical_ops_write_ra_not_rd():
    """or rA, rS, rB -- the destination is in the rA field."""
    orr = (31 << 26) | (3 << 21) | (4 << 16) | (5 << 11) | (444 << 1)  # or r4, r3, r5
    assert gpr_defs(decode(orr)) == {4}
    ori = (24 << 26) | (3 << 21) | (9 << 16) | 0x10  # ori r9, r3, 0x10
    assert gpr_defs(decode(ori)) == {9}
    rlwinm = (21 << 26) | (3 << 21) | (6 << 16) | (2 << 11) | (29 << 1)
    assert gpr_defs(decode(rlwinm)) == {6}


def test_store_writes_nothing():
    stw = (36 << 26) | (3 << 21) | (1 << 16) | 8
    assert gpr_defs(decode(stw)) == frozenset()


def test_update_store_writes_only_ra():
    stwu = (37 << 26) | (1 << 21) | (1 << 16) | 0xFFF0
    assert gpr_defs(decode(stwu)) == {1}


def test_update_load_writes_rd_and_ra():
    lwzu = (33 << 26) | (5 << 21) | (6 << 16) | 4  # lwzu r5, 4(r6)
    assert gpr_defs(decode(lwzu)) == {5, 6}


def test_float_update_load_writes_only_ra():
    lfsu = (49 << 26) | (1 << 21) | (6 << 16) | 4
    assert gpr_defs(decode(lfsu)) == {6}


def test_lmw_writes_a_range():
    lmw = (46 << 26) | (29 << 21) | (1 << 16) | 0x14  # lmw r29, 0x14(r1)
    assert gpr_defs(decode(lmw)) == {29, 30, 31}


def test_compare_and_branch_write_nothing():
    assert gpr_defs(decode((10 << 26) | (3 << 16) | 2)) == frozenset()  # cmpli
    assert gpr_defs(decode(0x4E800020)) == frozenset()  # blr


def test_mfspr_writes_rd():
    assert gpr_defs(decode(0x7C0802A6)) == {0}  # mflr r0


def test_is_mr():
    mr = (31 << 26) | (4 << 21) | (3 << 16) | (4 << 11) | (444 << 1)  # or r3, r4, r4
    assert is_mr(decode(mr))
    orr = (31 << 26) | (4 << 21) | (3 << 16) | (5 << 11) | (444 << 1)  # or r3, r4, r5
    assert not is_mr(decode(orr))


def test_invalid_writes_nothing():
    assert gpr_defs(decode(0)) == frozenset()
