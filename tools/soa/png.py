"""The port's own PNGs: what runtime/png.c writes, read and written back.

runtime/png.c writes 8-bit RGBA with filter 0 on every row and nothing else,
so this reads exactly that and refuses anything other, rather than carry a
general decoder for images the port never makes. Moved here from
tools/midpoint.py for the frame oracle (specs/gpu-backend.md V0), which
needs the same reader.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
FNV_OFFSET, FNV_PRIME = 14695981039346656037, 1099511628211
MASK64 = (1 << 64) - 1


def read_rgba(path: Path) -> tuple[int, int, bytes]:
    """(width, height, RGBA rows top to bottom) from one of the port's PNGs."""
    d = Path(path).read_bytes()
    if d[:8] != SIGNATURE:
        raise ValueError(f"{path}: not a PNG")
    i, idat, w, h = 8, [], 0, 0
    while i + 8 <= len(d):
        n = int.from_bytes(d[i : i + 4], "big")
        tag, body = d[i + 4 : i + 8], d[i + 8 : i + 8 + n]
        if tag == b"IHDR":
            w, h = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big")
            if (body[8], body[9]) != (8, 6):
                raise ValueError(f"{path}: not 8-bit RGBA, so not the port's")
        elif tag == b"IDAT":
            idat.append(body)
        i += 12 + n
    if not w:
        raise ValueError(f"{path}: no IHDR")
    raw = zlib.decompress(b"".join(idat))
    stride = 1 + w * 4
    if any(raw[y * stride] for y in range(h)):
        raise ValueError(f"{path}: a filtered row, so not the port's")
    return w, h, b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(h))


def write_rgba(path: Path, w: int, h: int, rgba: bytes) -> None:
    """The same format runtime/png.c writes."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body).to_bytes(4, "big")
        return len(body).to_bytes(4, "big") + tag + body + crc

    raw = b"".join(b"\x00" + rgba[y * w * 4 : (y + 1) * w * 4] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    Path(path).write_bytes(
        SIGNATURE
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def fnv1a(h: int, data: bytes) -> int:
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & MASK64
    return h


def screen_hash(w: int, h: int, rgba: bytes) -> str:
    """gxr_screen_hash (runtime/gxr.c) over an image: FNV-1a 64 over the
    width and height as big-endian 16-bit numbers, then every row's RGBA.
    The PNG holds the screen's bytes exactly, so this is the hash the
    replay printed for it, as config/fifo_manifest.tsv pins it."""
    return f"{fnv1a(fnv1a(FNV_OFFSET, bytes([w >> 8, w & 255, h >> 8, h & 255])), rgba):016x}"
