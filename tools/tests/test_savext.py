"""tools/savext.py, X2's container read off a save file (docs/specs/save-extension.md),
on synthetic files: no disc, no card, no compiler. test_mods.py holds the same
layout against runtime/savext.c from the other side."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import savext  # noqa: E402


def sealed(block: bytearray) -> bytes:
    """The block with the game's XOR stored at +12796."""
    words = struct.unpack(">3199I", bytes(block[:12796]))
    acc = 0
    for w in words:
        acc ^= w
    block[12796:12800] = struct.pack(">I", acc)
    return bytes(block)


def save_file(chunks: list[tuple[str, bytes]]) -> bytes:
    block = bytearray(savext.BLOCK_LEN)
    block[:4] = b"\x12\x34\x56\x78"  # something of the game's
    gap, tail = savext.build(chunks, save_id=bytes(range(16)))
    block[savext.GAP_OFF : savext.GAP_OFF + len(gap)] = gap
    data = bytearray(savext.FILE_LEN)
    data[savext.BLOCK_IN_FILE : savext.BLOCK_IN_FILE + savext.BLOCK_LEN] = sealed(block)
    data[savext.TAIL_OFF : savext.TAIL_OFF + len(tail)] = tail
    return bytes(data)


def parts(data: bytes) -> tuple[bytes, bytes]:
    return data[savext.BLOCK_IN_FILE : savext.BLOCK_IN_FILE + savext.BLOCK_LEN], data[
        savext.TAIL_OFF :
    ]


def test_the_games_check_passes_and_a_flipped_byte_fails_it():
    block = bytearray(savext.BLOCK_LEN)
    block[100] = 7
    good = sealed(block)
    assert savext.xor_ok(good)
    assert not savext.xor_ok(good[:5000] + bytes([good[5000] ^ 1]) + good[5001:])


def test_chunks_round_trip_through_the_gap_and_the_tail():
    big = bytes(i & 0xFF for i in range(4000))
    c = savext.parse(
        *parts(save_file([("counter", b"\x00\x00\x00\x07"), ("big", big), ("after", b"x")]))
    )
    assert c.present and not c.problems
    assert (c.in_gap, c.in_tail) == (1, 2)  # once one overflows, the rest follow it
    assert c.chunks == [("counter", b"\x00\x00\x00\x07"), ("big", big), ("after", b"x")]
    assert c.save_id == bytes(range(16))


def test_a_vanilla_file_has_no_container():
    data = bytearray(savext.FILE_LEN)
    data[savext.BLOCK_IN_FILE : savext.BLOCK_IN_FILE + savext.BLOCK_LEN] = sealed(
        bytearray(savext.BLOCK_LEN)
    )
    c = savext.parse(*parts(bytes(data)))
    assert not c.present and not c.chunks
    assert any(
        "no mod container" in line for line in savext.describe("SA_LEGENDS.000", bytes(data))
    )


def test_a_damaged_gap_or_a_tail_that_does_not_match_is_reported():
    data = bytearray(save_file([("counter", b"\x00\x00\x00\x07")]))
    data[savext.BLOCK_IN_FILE + savext.GAP_OFF + savext.GAP_HEAD + 2] ^= 1  # inside the chunk
    c = savext.parse(*parts(bytes(data)))
    assert c.present and not c.chunks and "CRC" in c.problems[0]
    data = bytearray(save_file([("a", bytes(3200))]))  # too big for the gap: in the tail
    data[savext.TAIL_OFF + 8] ^= 1  # the tail's copy of the save's id
    c = savext.parse(*parts(bytes(data)))
    assert c.chunks == [] and "does not hold them" in c.problems[0]


def test_describe_says_what_a_player_needs():
    lines = savext.describe("SA_LEGENDS.001", save_file([("counter", b"\x00\x00\x00\x07")]))
    assert lines[0].startswith("SA_LEGENDS.001: the game's check passes; block sha1 ")
    assert "1 chunk(s) in the gap, 0 in the tail" in lines[1]
    assert lines[2].startswith("  counter: 4 bytes")
