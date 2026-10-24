#!/usr/bin/env python3
"""Who owns which story flags (K1, docs/specs/content-ids.md): the area maps'
exploration grids read off the disc, and T2's pool checked against them.

    python tools/flagmap.py                      # the grids, the free runs, the pool
    python tools/flagmap.py --card card.raw      # and every flag a save has set, accounted for

The field's area map (a `kmap` object, fn_800E1E9C) marks where the player has
walked: flag base + x + 16*z, with x and z the position's 16 x 16 cell (clamped
0..15), so each object owns 256 flags from its base. The base is +64 of the
object's parameter block when the block's version (its first word) is past 15,
else 0. In an MLD, an entry's parameter block is the offset 20 bytes before its
16-byte name. The scripts never set a flag past 4505 by number, so above that
the grids are the game's whole use; T2 hands mods flags from T2_FIRST, above
the last grid.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

FLAGS = 27328  # 0x80310B3C, 854 words
GRID = 256
T2_FIRST = 24576  # runtime/mod.c's FLAG_FIRST
SCRIPT_MAX = 4505  # the highest flag any field script sets by number (K1's scan)


def kmap_bases(mld: bytes) -> list[tuple[int, int]]:
    """(version, base) of every kmap entry in a decompressed MLD."""
    out, at = [], 0
    while (n := mld.find(b"kmap\0", at)) >= 0:
        at = n + 1
        if n < 20:
            continue
        par = struct.unpack(">I", mld[n - 20 : n - 16])[0]
        if not 0 < par <= len(mld) - 68:
            continue
        version = struct.unpack(">I", mld[par : par + 4])[0]
        base = struct.unpack(">I", mld[par + 64 : par + 68])[0] if version > 15 else 0
        out.append((version, base))
    return out


def owned(bases: list[int]) -> set[int]:
    return {f for b in bases for f in range(b, min(b + GRID, FLAGS))}


def free_runs(used: set[int], least: int = GRID) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for f in range(FLAGS):
        if f in used:
            continue
        if runs and runs[-1][1] == f - 1:
            runs[-1][1] = f
        else:
            runs.append([f, f])
    return [(a, b) for a, b in runs if b - a + 1 >= least]


def flags_set(block: bytes) -> set[int]:
    """The flags set in a save block's flag area (+9072, 3416 bytes)."""
    area = block[9072 : 9072 + FLAGS // 8]
    return {
        (i // 4) * 32 + (3 - i % 4) * 8 + bit
        for i in range(len(area))
        for bit in range(8)
        if area[i] >> bit & 1
    }


def disc_grids(data: Path) -> dict[int, set[str]]:
    from soa import aklz, disc

    grids: dict[int, set[str]] = {}
    with disc.open_data(data) as src:
        for p in src.paths():
            if not p.lower().endswith(".mld"):
                continue
            raw = src.read_path(p)
            try:
                d = aklz.decompress(raw)
            except Exception:
                d = raw
            for _, base in kmap_bases(d):
                grids.setdefault(base, set()).add(p.split("/")[-1])
    return grids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=ROOT / "extracted")
    ap.add_argument("--card", type=Path, help="a card whose saves' flags are accounted for")
    args = ap.parse_args(argv)
    grids = disc_grids(args.data)
    used = owned(list(grids))
    print(f"{len(grids)} area-map grids, bases {min(grids)} to {max(grids)}")
    print("free runs of 256 or more:", ", ".join(f"{a}-{b}" for a, b in free_runs(used)))
    clash = sorted(f for f in used if f >= T2_FIRST)
    print(
        f"T2's pool, {T2_FIRST}-{FLAGS - 1}: "
        + ("clear of every grid" if not clash else f"overlaps {clash[:8]}")
    )
    bad = bool(clash)
    if args.card:
        import savext

        for name, data in savext.save_files(args.card):
            fl = flags_set(data[savext.BLOCK_IN_FILE : savext.BLOCK_IN_FILE + savext.BLOCK_LEN])
            stray = sorted(f for f in fl if f > SCRIPT_MAX and f not in used and f < T2_FIRST)
            print(
                f"{name}: {len(fl)} flags set, {len(stray)} past {SCRIPT_MAX} in no grid {stray[:8]}"
            )
            bad = bad or bool(stray)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
