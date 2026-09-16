#!/usr/bin/env python3
"""Decode a GameCube texture out of a captured RAM image to PNG.

    python tools/tex.py build/fifo/0500.ram 0x8460CC0 --fmt 1 --size 8x8 out.png
    python tools/tex.py build/fifo/0500.ram 0x8C63A00 --fmt 14 --size 256x256 out.png
    python tools/tex.py build/fifo/0500.ram 0x8D1AE0 --fmt 8 --size 256x256 --tlut 0x8D1AC0:2 out.png

Formats: 0 I4, 1 I8, 2 IA4, 3 IA8, 4 RGB565, 5 RGB5A3, 6 RGBA8, 8 C4, 9 C8,
10 C14X2, 14 CMPR. --tlut takes a RAM address and format (0 IA8, 1 RGB565,
2 RGB5A3). Writes an uncompressed PNG. Analysis only.
"""

import argparse
import struct
import sys
import zlib
from pathlib import Path


def rgb565(v):
    return (((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255)


def rgb5a3(v):
    if v & 0x8000:
        return (
            ((v >> 10) & 31) * 255 // 31,
            ((v >> 5) & 31) * 255 // 31,
            (v & 31) * 255 // 31,
            255,
        )
    return (((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 7) * 255 // 7)


def tlut_lookup(tlut: bytes, fmt: int, idx: int):
    v = struct.unpack_from(">H", tlut, idx * 2)[0]
    if fmt == 0:
        return (v & 0xFF, v & 0xFF, v & 0xFF, v >> 8)
    if fmt == 1:
        return rgb565(v)
    return rgb5a3(v)


def decode(data: bytes, fmt: int, w: int, h: int, tlut: bytes | None, tlut_fmt: int):
    out = [[(255, 0, 255, 255)] * w for _ in range(h)]
    tile = {
        0: (8, 8, 32),
        1: (8, 4, 32),
        2: (8, 4, 32),
        3: (4, 4, 32),
        4: (4, 4, 32),
        5: (4, 4, 32),
        6: (4, 4, 64),
        8: (8, 8, 32),
        9: (8, 4, 32),
        10: (4, 4, 32),
        14: (8, 8, 32),
    }[fmt]
    tw, th, bpt = tile
    tiles_w = (w + tw - 1) // tw
    if fmt == 14:
        for by in range((h + 7) // 8):
            for bx in range(tiles_w):
                blk = (by * tiles_w + bx) * 32
                for sub, (ox, oy) in enumerate(((0, 0), (4, 0), (0, 4), (4, 4))):
                    p = data[blk + sub * 8 : blk + sub * 8 + 8]
                    if len(p) < 8:
                        continue
                    c0, c1 = struct.unpack(">HH", p[:4])
                    pal = [rgb565(c0), rgb565(c1)]
                    if c0 > c1:
                        pal.append(
                            tuple((2 * a + b) // 3 for a, b in zip(pal[0], pal[1], strict=True))
                        )
                        pal.append(
                            tuple((a + 2 * b) // 3 for a, b in zip(pal[0], pal[1], strict=True))
                        )
                    else:
                        pal.append(tuple((a + b) // 2 for a, b in zip(pal[0], pal[1], strict=True)))
                        pal.append((0, 0, 0, 0))
                    for y in range(4):
                        row = p[4 + y]
                        for x in range(4):
                            px, py = bx * 8 + ox + x, by * 8 + oy + y
                            if px < w and py < h:
                                out[py][px] = pal[(row >> (6 - 2 * x)) & 3][:3] + (
                                    pal[(row >> (6 - 2 * x)) & 3][3],
                                )
        return out
    for y in range(h):
        for x in range(w):
            t = ((y // th) * tiles_w + x // tw) * bpt
            ix, iy = x % tw, y % th
            if t + bpt > len(data):
                continue
            if fmt == 0:
                v = data[t + iy * 4 + ix // 2]
                v = v & 15 if ix & 1 else v >> 4
                out[y][x] = (v * 17,) * 4
            elif fmt == 1:
                v = data[t + iy * 8 + ix]
                out[y][x] = (v, v, v, v)
            elif fmt == 2:
                v = data[t + iy * 8 + ix]
                out[y][x] = ((v & 15) * 17,) * 3 + ((v >> 4) * 17,)
            elif fmt == 3:
                a, i = data[t + (iy * 4 + ix) * 2], data[t + (iy * 4 + ix) * 2 + 1]
                out[y][x] = (i, i, i, a)
            elif fmt == 4:
                out[y][x] = rgb565(struct.unpack_from(">H", data, t + (iy * 4 + ix) * 2)[0])
            elif fmt == 5:
                out[y][x] = rgb5a3(struct.unpack_from(">H", data, t + (iy * 4 + ix) * 2)[0])
            elif fmt == 6:
                a, r = data[t + (iy * 4 + ix) * 2], data[t + (iy * 4 + ix) * 2 + 1]
                g, b = data[t + 32 + (iy * 4 + ix) * 2], data[t + 32 + (iy * 4 + ix) * 2 + 1]
                out[y][x] = (r, g, b, a)
            elif fmt == 8:
                v = data[t + iy * 4 + ix // 2]
                v = v & 15 if ix & 1 else v >> 4
                out[y][x] = tlut_lookup(tlut, tlut_fmt, v) if tlut else (v * 17,) * 4
            elif fmt == 9:
                v = data[t + iy * 8 + ix]
                out[y][x] = tlut_lookup(tlut, tlut_fmt, v) if tlut else (v, v, v, 255)
            elif fmt == 10:
                v = struct.unpack_from(">H", data, t + (iy * 4 + ix) * 2)[0] & 0x3FFF
                out[y][x] = tlut_lookup(tlut, tlut_fmt, v) if tlut else (0, 0, 0, 255)
    return out


def write_png(path: Path, rows, w: int, h: int) -> None:
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ram", type=Path)
    ap.add_argument("addr", type=lambda s: int(s, 0))
    ap.add_argument("out", type=Path)
    ap.add_argument("--fmt", type=int, required=True)
    ap.add_argument("--size", required=True, help="WxH")
    ap.add_argument("--tlut", default=None, help="ADDR:FMT")
    ap.add_argument("--stats", action="store_true", help="print alpha/colour statistics")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.lower().split("x"))
    ram = args.ram.read_bytes()
    off = args.addr & 0x01FFFFFF
    data = ram[off : off + w * h * 4 + 4096]
    tlut = None
    tlut_fmt = 0
    if args.tlut:
        a, f = args.tlut.split(":")
        tlut = ram[int(a, 0) & 0x01FFFFFF :][: 16384 * 2]
        tlut_fmt = int(f)
    rows = decode(data, args.fmt, w, h, tlut, tlut_fmt)
    if args.stats:
        alphas = [px[3] for row in rows for px in row]
        cols = [px[:3] for row in rows for px in row]
        print(f"alpha min {min(alphas)} max {max(alphas)} mean {sum(alphas) / len(alphas):.1f}")
        print(f"first pixels: {cols[:4]}")
    write_png(args.out, rows, w, h)
    print(f"wrote {args.out} ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
