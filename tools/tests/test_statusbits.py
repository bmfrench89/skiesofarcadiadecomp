"""tools/statusbits.py, K12's account of the battle status bits, on hand-assembled
PowerPC words: no DOL."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import statusbits  # noqa: E402

BASE = 0x80010000  # inside battle code


def lwz(d, a, off):
    return (32 << 26) | (d << 21) | (a << 16) | (off & 0xFFFF)


def stw(s, a, off):
    return (36 << 26) | (s << 21) | (a << 16) | (off & 0xFFFF)


def andi_(a, s, imm):
    return (28 << 26) | (s << 21) | (a << 16) | imm


def oris(a, s, imm):
    return (25 << 26) | (s << 21) | (a << 16) | imm


def rlwinm(a, s, sh, mb, me):
    return (21 << 26) | (s << 21) | (a << 16) | (sh << 11) | (mb << 6) | (me << 1)


def scan(words: list[int], at: int = BASE) -> statusbits.Scan:
    mem = {at + 4 * k: w for k, w in enumerate(words)}
    s = statusbits.Scan()
    s.run(lambda a: mem.get(a, 0x60000000), at, at + 4 * len(words), lambda a: at + 4 * len(words))
    return s


def test_a_test_a_set_and_a_clear_are_told_apart():
    s = scan(
        [
            lwz(4, 31, 28),
            andi_(0, 4, 0x0040),  # tests 0x40
            oris(5, 4, 0x0200),  # sets 0x02000000
            stw(5, 31, 28),
            lwz(6, 31, 28),
            rlwinm(6, 6, 0, 31, 29),  # keeps all but 0x2: clears it
            stw(6, 31, 28),
        ]
    )
    assert s.tests[0x40] == [BASE + 4]
    assert s.sets[0x02000000] == [BASE + 12]
    assert s.clears[0x2] == [BASE + 24]
    assert 0x40 not in s.sets and 0x02000000 not in s.tests


def test_a_store_to_another_base_or_offset_sets_nothing():
    s = scan(
        [
            lwz(4, 31, 28),
            oris(5, 4, 0x0400),
            stw(5, 30, 28),
            lwz(4, 31, 28),
            oris(5, 4, 0x0400),
            stw(5, 31, 32),
        ]
    )
    assert not s.sets


def test_free_means_no_set_anywhere_and_no_test_in_battle_code():
    s = scan(
        [lwz(4, 31, 28), andi_(0, 4, 0x0020), lwz(4, 31, 28), oris(5, 4, 0x8000), stw(5, 31, 28)]
    )
    free = s.free()
    assert 0x20 not in free  # tested in battle code
    assert 0x80000000 not in free  # set
    assert 0x10 in free and 0x40000000 in free
    outside = scan([lwz(4, 31, 28), andi_(0, 4, 0x0020)], at=0x80200000)
    assert 0x20 in outside.free()  # a test outside battle code is not trusted
