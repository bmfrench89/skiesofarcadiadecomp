#!/usr/bin/env python3
"""The save extension's container (X2, docs/specs/save-extension.md), read off a
card image without launching the port.

    python tools/savext.py show build/cards/slotA.raw            # every save file
    python tools/savext.py show card.raw --file 1                # SA_LEGENDS.001

For each save file: whether the game's own check passes (the XOR of the block's
first 3,199 words, stored at +12796), the block's SHA-1 (what `SOA_SAVE_LOG=1`
prints at the image hook), and the mods' chunks, by id and size, from the
block's gap and the file's tail. The layout is runtime/savext.c's, which this
file mirrors; build() makes a container for the tests, independently of it.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import cardformat  # tools/ is sys.path[0] when this runs as a script

FILE_LEN = 24576
BLOCK_IN_FILE = 5184
BLOCK_LEN = 12800
GAP_OFF = 5916  # in the block
GAP_LEN = 3156
TAIL_OFF = 17984  # in the file
TAIL_LEN = 6592
GAP_HEAD = 36
TAIL_HEAD = 32
VERSION = 1
ID_MAX = 31
SAVE_NAME = "SA_LEGENDS.00{}"


class SavextError(Exception):
    pass


@dataclass
class Container:
    """What a save file holds for mods; empty for a vanilla one."""

    present: bool = False
    save_id: bytes = b""
    chunks: list[tuple[str, bytes]] = field(default_factory=list)
    in_gap: int = 0
    in_tail: int = 0
    problems: list[str] = field(default_factory=list)


def xor_ok(block: bytes) -> bool:
    """The game's check (fn_801A41EC 0x801A429C, the load menu's 0x8019F4C0)."""
    words = struct.unpack(">3200I", block[:BLOCK_LEN])
    acc = 0
    for w in words[:3199]:
        acc ^= w
    return acc == words[3199]


def _chunks(raw: bytes, count: int) -> list[tuple[str, bytes]]:
    out, at = [], 0
    for _ in range(count):
        if at >= len(raw):
            raise SavextError("a chunk runs off the end of its area")
        n = raw[at]
        if not 1 <= n <= ID_MAX or at + 1 + n + 4 > len(raw):
            raise SavextError(f"a chunk's id length is {n}")
        name = raw[at + 1 : at + 1 + n].decode("ascii", "replace")
        (size,) = struct.unpack(">I", raw[at + 1 + n : at + 5 + n])
        start = at + 5 + n
        if start + size > len(raw):
            raise SavextError(f"{name}'s chunk claims {size} bytes past its area")
        out.append((name, raw[start : start + size]))
        at = start + size
    return out


def parse(block: bytes, tail: bytes) -> Container:
    """The container in a block's gap and a file's tail, as savext_load reads it."""
    c = Container()
    gap = block[GAP_OFF : GAP_OFF + GAP_LEN]
    if gap[:4] != b"SOAX":
        return c
    c.present = True
    version, in_gap, in_tail, _ = struct.unpack(">4H", gap[4:12])
    c.save_id = gap[12:28]
    crc, length = struct.unpack(">II", gap[28:36])
    if version != VERSION or length > GAP_LEN - GAP_HEAD:
        c.problems.append(f"the gap's header is version {version}, length {length}")
        return c
    body = gap[GAP_HEAD : GAP_HEAD + length]
    if zlib.crc32(body) != crc:
        c.problems.append("the gap's CRC does not match: the port ignores this container")
        return c
    c.in_gap, c.in_tail = in_gap, in_tail
    c.chunks = _chunks(body, in_gap)
    if in_tail:
        t = tail[:TAIL_LEN]
        tcrc, tlen = struct.unpack(">II", t[24:32])
        if t[:4] != b"SOAT" or t[8:24] != c.save_id or tlen > TAIL_LEN - TAIL_HEAD:
            c.problems.append(
                f"the gap names {in_tail} chunk(s) in the tail, which does not hold them"
            )
        elif zlib.crc32(t[TAIL_HEAD : TAIL_HEAD + tlen]) != tcrc:
            c.problems.append("the tail's CRC does not match")
        else:
            c.chunks += _chunks(t[TAIL_HEAD : TAIL_HEAD + tlen], in_tail)
    return c


def _put(name: str, data: bytes) -> bytes:
    raw = name.encode("ascii")
    assert 1 <= len(raw) <= ID_MAX
    return bytes([len(raw)]) + raw + struct.pack(">I", len(data)) + data


def build(chunks: list[tuple[str, bytes]], save_id: bytes = bytes(16)) -> tuple[bytes, bytes]:
    """(gap, tail) holding `chunks`: whole ones in the gap while they fit, the
    rest in the tail, as savext_snapshot packs them. The tail is b"" when
    nothing overflows."""
    gap_body, tail_body, in_gap, in_tail = b"", b"", 0, 0
    for name, data in chunks:
        one = _put(name, data)
        if not tail_body and GAP_HEAD + len(gap_body) + len(one) <= GAP_LEN:
            gap_body += one
            in_gap += 1
        else:
            tail_body += one
            in_tail += 1
    gap = (
        b"SOAX"
        + struct.pack(">4H", VERSION, in_gap, in_tail, 0)
        + save_id
        + struct.pack(">II", zlib.crc32(gap_body), len(gap_body))
        + gap_body
    )
    tail = b""
    if in_tail:
        tail = (
            b"SOAT"
            + struct.pack(">2H", VERSION, in_tail)
            + save_id
            + struct.pack(">II", zlib.crc32(tail_body), len(tail_body))
            + tail_body
        )
    return gap, tail


def save_files(card: Path, file: int | None = None) -> list[tuple[str, bytes]]:
    """(name, the 24,576 bytes) of each of the game's save files on `card`."""
    image = cardformat.load_image(card)
    out = []
    for e in image.entries():
        if not e.name.startswith("SA_LEGENDS.00"):
            continue
        if file is not None and e.name != SAVE_NAME.format(file):
            continue
        data = b"".join(image.block(b) for b in e.chain)[:FILE_LEN]
        if len(data) < FILE_LEN:
            raise SavextError(f"{e.name} is {len(data)} bytes, not {FILE_LEN}")
        out.append((e.name, data))
    return out


def describe(name: str, data: bytes) -> list[str]:
    block = data[BLOCK_IN_FILE : BLOCK_IN_FILE + BLOCK_LEN]
    c = parse(block, data[TAIL_OFF:])
    lines = [
        f"{name}: the game's check {'passes' if xor_ok(block) else 'FAILS'}; "
        f"block sha1 {hashlib.sha1(block).hexdigest()}"
    ]
    if not c.present:
        lines.append(
            "  no mod container: a vanilla save, or one made without mods that keep a chunk"
        )
    else:
        lines.append(
            f"  container: save id {c.save_id.hex()}, {c.in_gap} chunk(s) in the gap, {c.in_tail} in the tail"
        )
        for chunk_name, chunk in c.chunks:
            lines.append(
                f"  {chunk_name}: {len(chunk)} bytes, sha1 {hashlib.sha1(chunk).hexdigest()[:16]}"
            )
        lines += [f"  problem: {p}" for p in c.problems]
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show", help="the game's check and the mods' chunks of each save file")
    show.add_argument("card")
    show.add_argument("--file", type=int, help="SA_LEGENDS.00N only")
    args = ap.parse_args(argv)
    try:
        files = save_files(Path(args.card), args.file)
    except (OSError, cardformat.CardFormatError, SavextError) as e:
        print(f"savext: {e}", file=sys.stderr)
        return 1
    if not files:
        print(
            "no save files on the card"
            + (f" named {SAVE_NAME.format(args.file)}" if args.file is not None else "")
        )
        return 1
    for name, data in files:
        print("\n".join(describe(name, data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
