"""The junk generator behind RVZ junk runs.

No disc is needed: the generator is checked against its own invariants and
against a property every word of real GameCube junk has (Dolphin's seed
recovery relies on it): bits 22-23 of each big-endian word equal bits 24-25.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa.rvz import LFG_BYTES, JunkGenerator, junk_bytes  # noqa: E402

SEED = struct.pack(">17I", *[(0x9E3779B9 * (i + 1)) & 0xFFFFFFFF for i in range(17)])


def test_junk_words_carry_the_disc_invariant():
    data = junk_bytes(SEED, 0, 4 * LFG_BYTES)
    for (w,) in struct.iter_unpack(">I", data):
        assert (w & 0x00C00000) == ((w >> 2) & 0x00C00000)


def test_skip_matches_a_straight_read():
    whole = JunkGenerator(SEED).get(3 * LFG_BYTES + 100)
    for offset in (0, 1, 7, LFG_BYTES - 1, LFG_BYTES, 2 * LFG_BYTES + 5):
        g = JunkGenerator(SEED)
        g.skip(offset)
        assert g.get(64) == whole[offset : offset + 64]


def test_run_offset_is_taken_modulo_the_sector():
    assert junk_bytes(SEED, 0x8000 + 12, 32) == junk_bytes(SEED, 12, 32)
    assert junk_bytes(SEED, 12, 32) != junk_bytes(SEED, 0, 32)


def test_different_seeds_differ():
    other = struct.pack(">17I", *[(0x85EBCA6B * (i + 3)) & 0xFFFFFFFF for i in range(17)])
    assert junk_bytes(SEED, 0, 256) != junk_bytes(other, 0, 256)
