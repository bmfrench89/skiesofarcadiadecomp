"""AKLZ container decoding.

65% of the disc's files (3,633 of 5,552) are wrapped in a Sega container whose
magic is ``AKLZ~?Qd``. The body is Okumura LZSS -- the classic public-domain
LZSS variant, with a 4096-byte ring buffer, 18-byte maximum match and a
threshold of 2.

  offset  size  field
  0x00    8     magic ``AKLZ~?Qd``
  0x08    4     big-endian f32, compressed/uncompressed ratio (informational)
  0x0C    4     big-endian u32, uncompressed size
  0x10    ..    LZSS stream

The port itself never needs this: the game's own recompiled code decompresses
its assets. We need it for *observability* -- to confirm the bytes we serve a
read are the bytes the game expected, and to write content-level tests.
"""

import struct
from dataclasses import dataclass

MAGIC = b"AKLZ~?Qd"
HEADER_SIZE = 0x10

# Okumura LZSS parameters.
RING_SIZE = 4096
MAX_MATCH = 18
THRESHOLD = 2
RING_START = RING_SIZE - MAX_MATCH  # 0xFEE


class AklzError(Exception):
    pass


@dataclass(frozen=True)
class AklzHeader:
    uncompressed_size: int
    ratio: float

    @property
    def data_offset(self) -> int:
        return HEADER_SIZE


def is_aklz(data: bytes) -> bool:
    return data[:8] == MAGIC


def parse_header(data: bytes) -> AklzHeader:
    if not is_aklz(data):
        raise AklzError("not an AKLZ container")
    if len(data) < HEADER_SIZE:
        raise AklzError("truncated header")
    ratio, size = struct.unpack(">fI", data[8:HEADER_SIZE])
    return AklzHeader(uncompressed_size=size, ratio=ratio)


def decompress(data: bytes, *, strict: bool = True) -> bytes:
    """Decompress an AKLZ container.

    With ``strict`` (the default) a stream that does not yield exactly the
    declared size raises. Callers surveying possibly-corrupt data can pass
    ``strict=False`` to get whatever decoded.
    """
    header = parse_header(data)
    want = header.uncompressed_size

    ring = bytearray(RING_SIZE)
    r = RING_START
    out = bytearray()
    pos = HEADER_SIZE
    end = len(data)
    flags = 0

    while len(out) < want and pos < end:
        flags >>= 1
        if not (flags & 0x100):
            # Refill: the high byte marks how many flag bits remain valid.
            flags = data[pos] | 0xFF00
            pos += 1
            if pos > end:
                break

        if flags & 1:  # literal byte
            if pos >= end:
                break
            byte = data[pos]
            pos += 1
            out.append(byte)
            ring[r] = byte
            r = (r + 1) & (RING_SIZE - 1)
        else:  # back-reference: 12-bit offset, 4-bit length
            if pos + 1 >= end:
                break
            lo, hi = data[pos], data[pos + 1]
            pos += 2
            offset = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + THRESHOLD + 1
            for k in range(length):
                byte = ring[(offset + k) & (RING_SIZE - 1)]
                out.append(byte)
                ring[r] = byte
                r = (r + 1) & (RING_SIZE - 1)
                if len(out) >= want:
                    break

    if strict and len(out) != want:
        raise AklzError(f"decoded {len(out)} bytes, header declares {want}")
    return bytes(out)


def maybe_decompress(data: bytes) -> bytes:
    """Decompress if the payload is AKLZ, otherwise return it unchanged."""
    return decompress(data) if is_aklz(data) else data
