"""tools/flagmap.py, K1's account of the story flags (docs/specs/content-ids.md),
on synthetic MLD bytes and save blocks: no disc."""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import flagmap  # noqa: E402


def mld_with(entries: list[tuple[int, int]]) -> bytes:
    """An MLD-like buffer: per entry, an offset 20 bytes before a `kmap` name,
    pointing at a parameter block (version, ..., base at +64)."""
    d = bytearray(0x1000)
    for k, (version, base) in enumerate(entries):
        name_at = 0x40 + k * 0x60
        par = 0x800 + k * 0x80
        d[name_at - 20 : name_at - 16] = struct.pack(">I", par)
        d[name_at : name_at + 5] = b"kmap\0"
        d[par : par + 4] = struct.pack(">I", version)
        d[par + 64 : par + 68] = struct.pack(">I", base)
    return bytes(d)


def test_a_grid_s_base_is_read_past_version_15_and_is_0_before():
    assert flagmap.kmap_bases(mld_with([(17, 7616), (16, 3520), (13, 999)])) == [
        (17, 7616),
        (16, 3520),
        (13, 0),
    ]


def test_grids_own_256_flags_and_the_free_runs_are_what_is_left():
    used = flagmap.owned([3520, 24000])
    assert (
        3520 in used and 3775 in used and 3776 not in used and 24255 in used and 24256 not in used
    )
    runs = flagmap.free_runs(used)
    assert (0, 3519) in runs and (24256, flagmap.FLAGS - 1) in runs


def test_flags_in_a_save_block_decode_as_the_game_numbers_them():
    block = bytearray(12800)
    # flag n is bit n % 32 of the big-endian word n // 32
    for n in (0, 31, 7653, 27327):
        w = 9072 + (n // 32) * 4
        word = struct.unpack(">I", block[w : w + 4])[0] | (1 << (n % 32))
        block[w : w + 4] = struct.pack(">I", word)
    assert flagmap.flags_set(bytes(block)) == {0, 31, 7653, 27327}


def test_t2_s_pool_is_the_runtime_s():
    """runtime/mod.c hands claims out from FLAG_FIRST; this file checks that pool
    against the disc's grids. The two numbers are one decision."""
    source = (ROOT / "runtime" / "mod.c").read_text(encoding="utf-8")
    first = int(re.search(r"#define FLAG_FIRST (\d+)u", source).group(1))
    last = int(re.search(r"#define FLAG_LAST (\d+)u", source).group(1))
    assert first == flagmap.T2_FIRST and last == flagmap.FLAGS - 1
