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


# --------------------------------------------------------------------------
# switch tables and returns
# --------------------------------------------------------------------------

BCTR = 0x4E800420


def cmpli(ra: int, uimm: int) -> int:
    return (10 << 26) | (ra << 16) | (uimm & 0xFFFF)


def addis(rd: int, imm: int) -> int:
    return (15 << 26) | (rd << 21) | (imm & 0xFFFF)


def addi(rd: int, ra: int, imm: int) -> int:
    return (14 << 26) | (rd << 21) | (ra << 16) | (imm & 0xFFFF)


def rlwinm_x4(ra: int, rs: int) -> int:
    """rlwinm ra, rs, 2, 0, 29 -- multiply an index by four."""
    return (21 << 26) | (rs << 21) | (ra << 16) | (2 << 11) | (0 << 6) | (29 << 1)


def lwzx(rd: int, ra: int, rb: int) -> int:
    return (31 << 26) | (rd << 21) | (ra << 16) | (rb << 11) | (23 << 1)


def mtctr(rs: int) -> int:
    return (31 << 26) | (rs << 21) | (9 << 16) | (467 << 1)


def bclr(bo: int, bi: int = 0) -> int:
    return (19 << 26) | (bo << 21) | (bi << 16) | (16 << 1)


def switch_dol(table_addr: int):
    """A function that dispatches through a 3-entry mwcc switch table.

    The table sits at `table_addr`, chosen so the @ha/@l split needs the
    negative-low-half carry: hi must be rounded up when lo is negative.
    """
    lo = table_addr & 0xFFFF
    if lo & 0x8000:
        lo -= 0x10000
    hi = (table_addr - lo) >> 16
    words = [
        stwu(-16),  # 0
        cmpli(3, 2),  # 4   three cases: 0, 1, 2
        bc(32, bo=12) | (1 << 16),  # 8   bgt -> default at +40
        addis(5, hi),  # 12
        rlwinm_x4(0, 3),  # 16
        addi(5, 5, lo),  # 20
        lwzx(0, 5, 0),  # 24
        mtctr(0),  # 28
        BCTR,  # 32
        BLR,  # 36  case 0
        BLR,  # 40  case 1 / default
        BLR,  # 44  case 2
    ]
    targets = [BASE + 36, BASE + 40, BASE + 44]
    return make_dol(words, data_words=targets, data_base=table_addr), targets


def test_find_jump_tables_resolves_the_mwcc_idiom():
    dol, targets = switch_dol(0x8040FFF0)  # forces the @ha carry
    tables = cfg.find_jump_tables(dol)
    assert set(tables) == {BASE + 32}
    table = tables[BASE + 32]
    assert table.base == 0x8040FFF0
    assert table.targets == targets
    assert table.count == 3


def test_jump_table_targets_are_intra_function():
    """Case labels become successors of the dispatching function, not entries."""
    dol, targets = switch_dol(0x80400000)
    fns = cfg.build(dol)
    assert set(fns) == {BASE}
    fn = fns[BASE]
    assert fn.jump_tables == [BASE + 32]
    assert not fn.has_indirect_branch
    for t in targets:
        assert t in fn.blocks
    assert fn.returns == 3
    assert fn.end == BASE + 48


def test_case_labels_are_never_promoted_to_functions():
    """Even though every case label is a data-section code pointer."""
    dol, _ = switch_dol(0x80400000)
    fns, stats = cfg.build_iterative(dol)
    assert set(fns) == {BASE}
    assert stats["jump_tables"] == 1
    assert stats["case_labels"] == 3


def test_bctr_without_a_table_is_unresolved():
    dol = make_dol([stwu(-16), BCTR])
    fn = cfg.build(dol)[BASE]
    assert fn.unresolved_indirect == 1
    assert fn.has_indirect_branch
    assert fn.jump_tables == []


def test_conditional_return_falls_through():
    """beqlr returns on one path and continues on the other."""
    #  0: stwu ; 4: beqlr ; 8: nop ; 12: blr
    dol = make_dol([stwu(-16), bclr(12, 2), NOP, BLR])
    fn = cfg.build(dol)[BASE]
    assert fn.returns == 2
    assert fn.end == BASE + 16
    assert BASE + 8 in fn.blocks


def test_unconditional_return_does_not_fall_through():
    dol = make_dol([stwu(-16), BLR, NOP, NOP, NOP, NOP])
    fn = cfg.build(dol)[BASE]
    assert fn.returns == 1
    assert fn.end == BASE + 8


def test_iterative_promotes_a_frameless_leaf_after_a_return():
    """li r3,0 ; blr has no prologue and nothing references it -- still a function."""
    li_r3_0 = (14 << 26) | (3 << 21)
    dol = make_dol([stwu(-16), BLR, li_r3_0, BLR])
    fns, stats = cfg.build_iterative(dol)
    assert set(fns) == {BASE, BASE + 8}
    assert stats["from_gaps"] == 1


LI_R3_0 = (14 << 26) | (3 << 21)


def test_back_to_back_unreferenced_functions_surface_in_one_round():
    """A run of unreferenced leaves used to be discovered one per round."""
    dol = make_dol([stwu(-16), BLR] + [LI_R3_0, BLR] * 6)
    fns, stats = cfg.build_iterative(dol)
    assert len(fns) == 7
    assert stats["rounds"] <= 2


def test_mid_function_label_is_reabsorbed_not_promoted():
    """A block reached only by a branch from inside its owner is not a function.

    The owner's walk follows the branch (a gap start never terminates a walk),
    which places the label inside the owner's extent, and it is pruned.
    """
    #  0: stwu ; 4: b +12 (-> 16) ; 8: nop ; 12: blr ; 16: nop ; 20: b -12 (-> 8)
    dol = make_dol([stwu(-16), b(12), NOP, BLR, NOP, b(-12)])
    fns, stats = cfg.build_iterative(dol)
    assert set(fns) == {BASE}
    assert fns[BASE].end == BASE + 24
    assert BASE + 8 not in fns and BASE + 16 not in fns


def test_dead_branch_inside_a_function_is_absorbed():
    """mwcc leaves a stray `b` behind an unconditional branch; nothing reaches it.

    The owner's blocks run up to the hole and resume after it, so it is the
    owner's dead code, not a new function.
    """
    #  0: stwu ; 4: beq -> 20 ; 8: nop ; 12: b -> 24 ; 16: b -> 8 (DEAD) ; 20: nop ; 24: blr
    beq_20 = bc(16, bo=12) | (2 << 16)
    dol = make_dol([stwu(-16), beq_20, NOP, b(12), b(-8), NOP, BLR])
    fns, stats = cfg.build_iterative(dol)
    assert set(fns) == {BASE}
    assert fns[BASE].end == BASE + 28
    assert stats["absorbed"] == 1
    assert fns[BASE].blocks[BASE + 16].terminator == "dead"


def test_dead_branch_at_function_tail_is_absorbed():
    """A dead `b` after the final return, jumping back into its own function."""
    #  0: stwu ; 4: nop ; 8: blr ; 12: b -> 4 (DEAD) ; 16: stwu ; 20: blr   (16 is a pointer target)
    dol = make_dol([stwu(-16), NOP, BLR, b(-8), stwu(-32), BLR], data_words=[BASE + 16])
    fns, stats = cfg.build_iterative(dol)
    assert set(fns) == {BASE, BASE + 16}
    assert fns[BASE].end == BASE + 16
    assert stats["absorbed"] >= 1
    assert fns[BASE].blocks[BASE + 12].terminator == "dead"


def test_materialized_pointer_is_a_function_boundary():
    """A function whose address is taken with lis/addi is an entry, and a `b`
    into it from the function before it is a tail call, not inner flow."""
    #  0: stwu ; 4: lis r3,hi ; 8: addi r3,r3,lo (= BASE+20) ; 12: blr
    # 16: b +4 (-> 20) -- a preceding function tail-calling into it
    # 20: stwu ; 24: blr   -- the handler; nothing bl-calls it, no data word holds it
    target = BASE + 20
    hi, lo = target >> 16, target & 0xFFFF
    if lo & 0x8000:
        hi += 1
    words = [stwu(-16), addis(3, hi), addi(3, 3, lo), BLR, b(4), stwu(-32), BLR]
    dol = make_dol(words)
    assert target in cfg.find_materialized_pointers(dol)
    fns, _ = cfg.build_iterative(dol)
    assert target in fns
    assert fns[BASE + 16].end == BASE + 20  # the tail-caller stops at the boundary


def test_tail_called_frameless_leaf_merges_into_caller():
    """Documented limitation: a leaf reached only by `b` and nothing else is
    walked as part of its caller, so no separate boundary is recovered.
    Coverage is complete either way."""
    #  0: stwu ; 4: b +4 (-> 8) ; 8: li r3,0 ; 12: blr
    dol = make_dol([stwu(-16), b(4), LI_R3_0, BLR])
    fns, _ = cfg.build_iterative(dol)
    assert set(fns) == {BASE}
    assert fns[BASE].end == BASE + 16


# --------------------------------------------------------------------------
# switch-table register variants
# --------------------------------------------------------------------------


def or_(ra: int, rs: int, rb: int) -> int:
    return (31 << 26) | (rs << 21) | (ra << 16) | (rb << 11) | (444 << 1)


def stw(rs: int, ra: int, d: int) -> int:
    return (36 << 26) | (rs << 21) | (ra << 16) | (d & 0xFFFF)


def _switch_variant(prefix, tail_regs, table_addr=0x80400000):
    """Build a switch whose table-address materialisation is `prefix`
    (a list of words), ending with the table in register `tail_regs[0]` and
    the scaled index in `tail_regs[1]`."""
    t, i = tail_regs
    words = [stwu(-16)] + prefix + [lwzx(0, t, i), mtctr(0), BCTR, BLR, BLR, BLR]
    n = len(words)
    bctr_at = BASE + 4 * (n - 4)
    targets = [BASE + 4 * (n - 3), BASE + 4 * (n - 2), BASE + 4 * (n - 1)]
    dol = make_dol(words, data_words=targets, data_base=table_addr)
    return dol, bctr_at, targets


def _bgt_to(default_delta: int) -> int:
    return bc(default_delta, bo=12) | (1 << 16)


def test_table_halves_in_different_registers():
    """addis r4 ; addi r3, r4, lo -- @ha and @l allocated to different registers."""
    hi, lo = 0x8040, 0
    prefix = [cmpli(3, 2), _bgt_to(28), addis(4, hi), rlwinm_x4(0, 3), addi(3, 4, lo)]
    dol, site, targets = _switch_variant(prefix, (3, 0))
    tables = cfg.find_jump_tables(dol)
    assert site in tables and tables[site].targets == targets


def test_bound_check_hoisted_above_stores():
    prefix = [
        cmpli(3, 2),
        stw(7, 1, 0x30),
        stw(6, 1, 0x34),
        stw(5, 1, 0x38),
        _bgt_to(24),
        addis(4, 0x8040),
        rlwinm_x4(0, 3),
        addi(4, 4, 0),
    ]
    dol, site, targets = _switch_variant(prefix, (4, 0))
    tables = cfg.find_jump_tables(dol)
    assert site in tables and tables[site].targets == targets


def test_table_register_copied_through_mr():
    prefix = [
        cmpli(3, 2),
        _bgt_to(28),
        addis(4, 0x8040),
        addi(4, 4, 0),
        or_(5, 4, 4),  # mr r5, r4
        rlwinm_x4(0, 3),
    ]
    dol, site, targets = _switch_variant(prefix, (5, 0))
    tables = cfg.find_jump_tables(dol)
    assert site in tables and tables[site].targets == targets


def test_table_offset_from_a_pooled_base():
    """addi r3, r31, off where r31 = lis/addi pool base -- resolves to absolute."""
    pool = 0x80400000 - 0x100
    prefix = [
        addis(31, 0x8040),
        addi(31, 31, -0x100),  # r31 = pool base
        cmpli(3, 2),
        _bgt_to(20),
        rlwinm_x4(0, 3),
        addi(3, 31, 0x100),  # r3 = pool + 0x100 = table
    ]
    dol, site, targets = _switch_variant(prefix, (3, 0))
    tables = cfg.find_jump_tables(dol)
    assert site in tables
    assert tables[site].base == pool + 0x100
    assert tables[site].targets == targets


def test_table_operands_swapped():
    """lwzx rC, rI, rT -- index in rA, table in rB."""
    prefix = [cmpli(3, 2), _bgt_to(28), addis(4, 0x8040), rlwinm_x4(0, 3), addi(4, 4, 0)]
    dol, site, targets = _switch_variant(prefix, (0, 4))
    tables = cfg.find_jump_tables(dol)
    assert site in tables and tables[site].targets == targets


def test_table_register_loaded_from_memory_is_unresolved():
    """A table address that comes from a load is not a link-time constant."""
    lwz_r3 = (32 << 26) | (3 << 21) | (1 << 16) | 8  # lwz r3, 8(r1)
    prefix = [cmpli(3, 2), _bgt_to(20), lwz_r3, rlwinm_x4(0, 3)]
    dol, site, _ = _switch_variant(prefix, (3, 0))
    assert site not in cfg.find_jump_tables(dol)


def test_record_form_between_compare_and_bgt_is_unresolved():
    """An intervening `add.` clobbers CR0, so the cmpli no longer bounds the switch."""
    add_dot = (31 << 26) | (9 << 21) | (9 << 16) | (9 << 11) | (266 << 1) | 1
    prefix = [cmpli(3, 2), add_dot, _bgt_to(24), addis(4, 0x8040), rlwinm_x4(0, 3), addi(4, 4, 0)]
    dol, site, _ = _switch_variant(prefix, (4, 0))
    assert site not in cfg.find_jump_tables(dol)
