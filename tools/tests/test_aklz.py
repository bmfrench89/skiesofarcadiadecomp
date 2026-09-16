"""AKLZ container tests.

Streams are hand-built so the suite runs without game data. The encoding is
Okumura LZSS: a flag byte supplies 8 control bits LSB-first, 1 = literal byte,
0 = a two-byte back-reference (12-bit ring offset, 4-bit length-3).
"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa.aklz import (  # noqa: E402
    MAGIC,
    RING_START,
    AklzError,
    decompress,
    is_aklz,
    maybe_decompress,
    parse_header,
)


def container(payload: bytes, declared: int, ratio: float = 0.5) -> bytes:
    return MAGIC + struct.pack(">fI", ratio, declared) + payload


def literals(data: bytes) -> bytes:
    """Encode bytes as all-literal LZSS groups."""
    out = bytearray()
    for i in range(0, len(data), 8):
        chunk = data[i : i + 8]
        out.append((1 << len(chunk)) - 1)  # one set flag bit per literal
        out += chunk
    return bytes(out)


def backref(offset: int, length: int) -> bytes:
    """Encode a back-reference; length must be 3..18."""
    lo = offset & 0xFF
    hi = ((offset >> 4) & 0xF0) | (length - THRESHOLD_PLUS_1)
    return bytes([lo, hi])


THRESHOLD_PLUS_1 = 3


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------


def test_is_aklz():
    assert is_aklz(container(b"", 0))
    assert not is_aklz(b"NMLD" + b"\0" * 32)
    assert not is_aklz(b"")


def test_parse_header():
    h = parse_header(container(b"", 1234, ratio=0.25))
    assert h.uncompressed_size == 1234
    assert h.ratio == pytest.approx(0.25)
    assert h.data_offset == 0x10


def test_parse_header_rejects_foreign_data():
    with pytest.raises(AklzError, match="not an AKLZ"):
        parse_header(b"\0" * 32)


def test_parse_header_rejects_truncation():
    with pytest.raises(AklzError, match="truncated"):
        parse_header(MAGIC + b"\0\0")


# --------------------------------------------------------------------------
# decompression
# --------------------------------------------------------------------------


def test_all_literals():
    payload = b"Hello, GameCube!"
    blob = container(literals(payload), len(payload))
    assert decompress(blob) == payload


def test_literals_spanning_multiple_flag_groups():
    payload = bytes(range(32))  # 4 flag groups
    assert decompress(container(literals(payload), len(payload))) == payload


def test_backreference_repeats_earlier_bytes():
    """Four literals then a 3-byte match pointing at where they landed."""
    stream = bytearray()
    stream.append(0b00001111)  # L L L L M
    stream += b"ABCD"
    stream += backref(RING_START, 3)
    expected = b"ABCDABC"
    assert decompress(container(bytes(stream), len(expected))) == expected


def test_backreference_can_overlap_itself():
    """A match may read bytes it is still writing — the classic RLE idiom.

    One literal 'X' lands at RING_START. The match then reads from RING_START
    while writing just ahead of its own read cursor, so each iteration copies
    the byte the previous one produced: a 5-byte match yields five more X's.
    """
    stream = bytearray()
    stream.append(0b00000001)  # L M
    stream += b"X"
    stream += backref(RING_START, 5)
    assert decompress(container(bytes(stream), 6)) == b"XXXXXX"


def test_output_is_clamped_to_declared_size():
    """A match that would overrun the declared size stops exactly at it."""
    stream = bytearray()
    stream.append(0b00001111)
    stream += b"ABCD"
    stream += backref(RING_START, 18)  # would emit far past the limit
    assert decompress(container(bytes(stream), 6)) == b"ABCDAB"


def test_strict_mode_rejects_short_stream():
    blob = container(literals(b"abc"), declared=99)
    with pytest.raises(AklzError, match="decoded 3 bytes"):
        decompress(blob)


def test_non_strict_returns_partial():
    blob = container(literals(b"abc"), declared=99)
    assert decompress(blob, strict=False) == b"abc"


def test_empty_payload():
    assert decompress(container(b"", 0)) == b""


def test_decompress_rejects_foreign_data():
    with pytest.raises(AklzError):
        decompress(b"NMLD" + b"\0" * 32)


# --------------------------------------------------------------------------
# passthrough
# --------------------------------------------------------------------------


def test_maybe_decompress_handles_both():
    raw = b"NMLD raw payload"
    assert maybe_decompress(raw) == raw
    payload = b"compressed!"
    assert maybe_decompress(container(literals(payload), len(payload))) == payload
