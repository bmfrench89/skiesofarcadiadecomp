#!/usr/bin/env python3
"""Exhaustive AKLZ decode gate over an extracted disc.

    python tools/validate_assets.py [--root extracted] [--jobs N]

Decompresses every AKLZ container on the disc and asserts each yields exactly
its declared uncompressed size. Also asserts no decompressed payload contains
PowerPC code, which is the evidence backing the "no runtime-loaded code"
premise in docs/SPEC.md -- a premise the original reasoning ("no .rel files on
the disc") did not actually establish, since two thirds of the disc is
compressed and a raw byte scan could not see inside it.

Walks the disc's file table and reads each file through `<root>/disc.iso`
(`--root` may also name an image); an extraction without an image is read as
its loose tree, `sys/` aside.

Reports structural statistics only; no asset content is emitted.
"""

import argparse
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa.aklz import AklzError, decompress, is_aklz, parse_header  # noqa: E402
from soa.disc import open_data  # noqa: E402

BLR = 0x4E800020  # the PowerPC return instruction, our code-density probe
MFLR_R0 = 0x7C0802A6


def read_extent(file: str, offset: int, size: int) -> bytes:
    """`size` bytes of `file` from `offset`; the whole file when size < 0."""
    with open(file, "rb") as f:
        f.seek(offset)
        return f.read() if size < 0 else f.read(size)


def scan_one(job: tuple[str, str, int, int]) -> dict:
    """Decompress one file if needed and measure PowerPC code density. `job`
    is (path on the disc, host file, offset, length): a slice of the image,
    or a whole loose file (offset 0, length -1)."""
    name, file, offset, size = job
    raw = read_extent(file, offset, size)
    result = {
        "path": name,
        "compressed": False,
        "ok": True,
        "error": "",
        "size_in": len(raw),
        "size_out": len(raw),
        "blr": 0,
        "mflr": 0,
    }
    if size >= 0 and len(raw) != size:
        result["ok"] = False
        result["error"] = f"read {len(raw)} bytes, the file table says {size}"
        return result

    data = raw
    if is_aklz(raw):
        result["compressed"] = True
        try:
            declared = parse_header(raw).uncompressed_size
            data = decompress(raw)
            result["size_out"] = len(data)
            if len(data) != declared:
                result["ok"] = False
                result["error"] = f"size {len(data)} != declared {declared}"
        except (AklzError, IndexError, struct.error) as exc:
            result["ok"] = False
            result["error"] = str(exc)
            return result

    # Aligned-word scan for PowerPC return / link-register save.
    blr = mflr = 0
    for i in range(0, len(data) - 3, 4):
        word = int.from_bytes(data[i : i + 4], "big")
        if word == BLR:
            blr += 1
        elif word == MFLR_R0:
            mflr += 1
    result["blr"] = blr
    result["mflr"] = mflr
    return result


def collect(mapped, total: int) -> list[dict]:
    results = []
    for n, r in enumerate(mapped, 1):
        results.append(r)
        if n % 250 == 0 or n == total:
            print(f"\r  {n:>5}/{total}", end="", flush=True)
    print()
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("extracted"))
    ap.add_argument("--jobs", type=int, default=0, help="0 = cpu_count; 1 = in this process")
    args = ap.parse_args(argv)

    if not args.root.exists():
        print(f"error: {args.root} not found; run tools/extract.py first", file=sys.stderr)
        return 1
    try:
        with open_data(args.root) as data:
            jobs = [(p, str(f), o, s) for p, f, o, s in data.extents()]
            source = data.source
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not jobs:
        print(f"error: no files in {source}; run tools/extract.py first", file=sys.stderr)
        return 1
    print(f"scanning {len(jobs):,} files in {source}")

    if args.jobs == 1:
        results = collect(map(scan_one, jobs), len(jobs))
    else:
        with ProcessPoolExecutor(max_workers=args.jobs or None) as pool:
            results = collect(pool.map(scan_one, jobs, chunksize=8), len(jobs))

    compressed = [r for r in results if r["compressed"]]
    failed = [r for r in results if not r["ok"]]
    with_code = [r for r in results if r["blr"] or r["mflr"]]
    total_out = sum(r["size_out"] for r in results)

    print(f"\n  AKLZ containers   {len(compressed):,} of {len(results):,}")
    print(f"  decoded bytes     {total_out:,} ({total_out / 1024**3:.2f} GiB)")
    print(f"  decode failures   {len(failed)}")
    print(f"  files w/ PPC code {len(with_code)}")

    for r in failed[:10]:
        print(f"    FAIL {r['path']}: {r['error']}")
    for r in with_code[:10]:
        print(f"    CODE {r['path']}: blr={r['blr']} mflr={r['mflr']}")

    if failed:
        print("\nFAILED: some containers did not decode to their declared size", file=sys.stderr)
        return 1

    # A handful of chance hits is expected across a gigabyte of entropy-dense
    # data; a real code blob shows both blr AND mflr in quantity.
    suspicious = [r for r in with_code if r["blr"] >= 8 and r["mflr"] >= 8]
    if suspicious:
        print(f"\nFAILED: {len(suspicious)} files look like they contain code", file=sys.stderr)
        return 1

    print("\nPASS: every container decodes exactly; no PowerPC code in any asset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
