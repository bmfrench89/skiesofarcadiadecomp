"""Control-flow recovery tests.

Synthetic DOLs are assembled from encoded words so the suite needs no game data.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import dol as D  # noqa: E402
from soa.ppc import cfg  # noqa: E402

BASE = 0x80003100

BLR = 0x4E800020
NOP = 0x60000000
MFLR_R0 = 0x7C0802A6


def stwu(disp: int) -> int:
    """stwu r1, disp(r1)"""
    return (37 << 26) | (1 << 21) | (1 << 16) | (disp & 0xFFFF)


def bl(delta: int) -> int:
    return (18 << 26) | (delta & 0x03FFFFFC) | 1


def b(delta: int) -> int:
    return (18 << 26) | (delta & 0x03FFFFFC)


def bc(delta: int, bo: int = 12) -> int:
    return (16 << 26) | (bo << 21) | (delta & 0xFFFC)


def make_dol(words, base=BASE, entry=BASE, data_words=(), data_base=0x80400000):
    """Build a DOL image with one text section and optionally one data section."""
    header = bytearray(0x100)
    text = b"".join(struct.pack(">I", w) for w in words)
    data = b"".join(struct.pack(">I", w) for w in data_words)

    struct.pack_into(">I", header, 0x00, 0x100)  # text0 file offset
    struct.pack_into(">I", header, 0x48, base)  # text0 address
    struct.pack_into(">I", header, 0x90, len(text))  # text0 size
    if data:
        struct.pack_into(">I", header, 0x1C, 0x100 + len(text))
        struct.pack_into(">I", header, 0x64, data_base)
        struct.pack_into(">I", header, 0xAC, len(data))
    struct.pack_into(">III", header, 0xD8, 0x80500000, 0, entry)
    return D.parse(bytes(header) + text + data)


# --------------------------------------------------------------------------
# seed discovery
# --------------------------------------------------------------------------


def test_find_bl_targets():
    # at BASE+0: bl +8  -> BASE+8
    dol = make_dol([bl(8), BLR, MFLR_R0, BLR])
    assert cfg.find_bl_targets(dol) == {BASE + 8}


def test_plain_branch_is_not_a_call():
    dol = make_dol([b(8), BLR, MFLR_R0, BLR])
    assert cfg.find_bl_targets(dol) == set()


def test_find_prologues():
    dol = make_dol([stwu(-16), BLR, NOP, stwu(-32), BLR])
    assert cfg.find_prologues(dol) == {BASE, BASE + 12}


def test_positive_stack_adjust_is_not_a_prologue():
    """stwu with a positive displacement is not frame setup."""
    dol = make_dol([stwu(16), BLR])
    assert cfg.find_prologues(dol) == set()


def test_find_code_pointers():
    dol = make_dol([stwu(-16), BLR], data_words=[BASE, 0x00000001, BASE + 4])
    assert cfg.find_code_pointers(dol) == {BASE, BASE + 4}


def test_code_pointers_ignore_out_of_range_words():
    dol = make_dol([BLR], data_words=[0xDEADBEEF, 0x80999999])
    assert cfg.find_code_pointers(dol) == set()


# --------------------------------------------------------------------------
# block and function shape
# --------------------------------------------------------------------------


def test_single_block_function():
    dol = make_dol([stwu(-16), NOP, BLR])
    fns = cfg.build(dol)
    fn = fns[BASE]
    assert len(fn.blocks) == 1
    assert fn.size == 12
    assert fn.returns == 1
    assert fn.has_frame
    assert fn.is_leaf


def test_conditional_branch_splits_blocks():
    #  0: bc +8 (taken -> 8)
    #  4: nop            (fall-through block)
    #  8: blr
    dol = make_dol([bc(8), NOP, BLR])
    fn = cfg.build(dol)[BASE]
    assert len(fn.blocks) >= 2
    assert BASE + 8 in fn.blocks


def test_call_is_recorded_and_flow_continues():
    #  0: stwu ; 4: bl +8 (-> 12) ; 8: blr ; 12: callee
    dol = make_dol([stwu(-16), bl(8), BLR, MFLR_R0, BLR])
    fns = cfg.build(dol)
    caller = fns[BASE]
    assert BASE + 12 in caller.calls
    assert not caller.is_leaf
    # flow continues past the call into the blr
    assert caller.returns == 1


def test_callee_becomes_its_own_function():
    dol = make_dol([stwu(-16), bl(8), BLR, MFLR_R0, BLR])
    fns = cfg.build(dol)
    assert BASE + 12 in fns
    assert fns[BASE + 12].entry == BASE + 12


def test_tail_call_terminates_the_caller():
    """An unconditional b to a known function is a tail call, not inner flow."""
    #  0: stwu ; 4: b +8 (-> 12) ; 8: nop ; 12: callee (a bl target)
    dol = make_dol([stwu(-16), b(8), NOP, MFLR_R0, BLR, bl(-4)])
    fns = cfg.build(dol, extra_seeds={BASE + 12})
    caller = fns[BASE]
    assert BASE + 12 in caller.tail_calls
    # the caller must not swallow the callee
    assert caller.end <= BASE + 12


def test_indirect_branch_is_flagged():
    bctr = 0x4E800420
    dol = make_dol([stwu(-16), bctr])
    fn = cfg.build(dol)[BASE]
    assert fn.has_indirect_branch


def test_extent_stops_at_the_first_hole():
    """end must be contiguous-from-entry, not max(block.end).

    Taking the maximum lets one mis-classified branch make a function appear
    to span the whole text section.
    """
    fn = cfg.Function(entry=0x80000000)
    fn.blocks[0x80000000] = cfg.BasicBlock(start=0x80000000, end=0x80000010)
    fn.blocks[0x80000010] = cfg.BasicBlock(start=0x80000010, end=0x80000020)
    fn.blocks[0x80900000] = cfg.BasicBlock(start=0x80900000, end=0x80900004)  # detached
    assert fn.end == 0x80000020
    assert fn.size == 0x20
    assert fn.detached_blocks == [0x80900000]


def test_function_name_format():
    assert cfg.Function(entry=0x800A1234).name == "fn_800A1234"


# --------------------------------------------------------------------------
# coverage and gaps
# --------------------------------------------------------------------------


def test_coverage_counts_claimed_bytes():
    dol = make_dol([stwu(-16), NOP, BLR])
    cov = cfg.coverage(dol, cfg.build(dol))
    assert cov["functions"] == 1
    assert cov["covered_bytes"] == 12
    assert cov["coverage_pct"] == 100.0


def test_gaps_report_unclaimed_runs():
    # entry function is 2 words; then 6 unreachable words nothing branches to
    dol = make_dol([stwu(-16), BLR] + [NOP] * 6)
    gaps = cfg.find_gaps(dol, cfg.build(dol), min_words=4)
    assert gaps == [(BASE + 8, BASE + 32)]


def test_short_gaps_are_filtered():
    dol = make_dol([stwu(-16), BLR, NOP, NOP])
    assert cfg.find_gaps(dol, cfg.build(dol), min_words=4) == []


# --------------------------------------------------------------------------
# iterative seeding
# --------------------------------------------------------------------------


def test_iterative_recovers_a_function_nothing_calls():
    """A function reached only through a data pointer still gets found."""
    words = [stwu(-16), BLR, stwu(-32), BLR]
    dol = make_dol(words, data_words=[BASE + 8])
    fns, stats = cfg.build_iterative(dol)
    assert BASE + 8 in fns
    assert stats["from_pointers"] >= 1


def test_pointer_into_claimed_code_is_not_promoted():
    """A switch-case label points inside a function body; it is not an entry."""
    #  0: stwu ; 4: nop ; 8: nop ; 12: blr    -- one function, 16 bytes
    #  data points at BASE+8, which lies inside it
    dol = make_dol([stwu(-16), NOP, NOP, BLR], data_words=[BASE + 8])
    fns, _ = cfg.build_iterative(dol)
    assert BASE + 8 not in fns
    assert set(fns) == {BASE}
