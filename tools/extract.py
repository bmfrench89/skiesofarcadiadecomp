#!/usr/bin/env python3
"""Extract a Skies of Arcadia Legends disc image into a working directory.

    python tools/extract.py <disc.rvz|disc.iso> [--out extracted/]

You must supply your own dump of a disc you own. Nothing extracted here is
redistributable; the output directory is gitignored.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa.disc import Disc  # noqa: E402
from soa.dump import ProjectError, verify  # noqa: E402
from soa.rvz import RVZ  # noqa: E402

EXPECTED_GAME_ID = "GEAE8P"


class RawImage:
    """Plain .iso/.gcm reader with the same interface as RVZ."""

    def __init__(self, path):
        # held open for the object's lifetime, mirroring RVZ
        self.f = open(path, "rb")  # noqa: SIM115

    def read(self, offset: int, length: int) -> bytes:
        self.f.seek(offset)
        return self.f.read(length)


def check_build(out: Path, force: bool = False) -> int:
    """Is what we just unpacked the build `config/` describes?

    Asked here because this is the moment the answer first exists and this is
    the one command everybody runs; `tools/checkdump.py` asks the same
    question later, when an `extracted/` has been sitting around and nobody
    remembers which dump made it. A mismatch is fatal without --force: every
    address in `config/` belongs to one build, and nothing downstream of here
    -- the recompiler, dtk, the decompilation match, the port itself -- looks
    at the executable's identity again.
    """
    try:
        verdict = verify(dol=out / "sys" / "main.dol")
    except ProjectError as exc:
        # A config.yml this cannot read is not the user's fault and must not
        # throw away an extraction that otherwise went fine.
        print(f"warning: cannot check the build: {exc}", file=sys.stderr)
        return 0
    print(verdict.report(), file=sys.stdout if verdict.ok else sys.stderr)
    if verdict.ok or force:
        return 0
    print("(--force accepts it anyway.)", file=sys.stderr)
    return 1


def open_image(path: Path):
    if path.suffix.lower() == ".rvz":
        return RVZ(str(path))
    return RawImage(str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", type=Path, help="disc image (.rvz, .iso, .gcm)")
    ap.add_argument("--out", type=Path, default=Path("extracted"))
    ap.add_argument(
        "--force",
        action="store_true",
        help="allow a non-GEAE8P disc, and report rather than refuse an unexpected executable",
    )
    ap.add_argument(
        "--iso",
        action="store_true",
        help="also write <out>/disc.iso, the flat image the runtime's DVD model reads from",
    )
    args = ap.parse_args()

    if not args.image.exists():
        print(f"error: {args.image} not found", file=sys.stderr)
        return 1

    disc = Disc(open_image(args.image))
    b = disc.boot
    print(f'{b.game_id}  "{b.title}"  (disc {b.disc_number}, rev {b.version})')

    if b.game_id != EXPECTED_GAME_ID and not args.force:
        print(
            f"error: expected {EXPECTED_GAME_ID}, got {b.game_id}. Use --force to override.",
            file=sys.stderr,
        )
        return 1

    fst = disc.fst
    print(f"{len(fst.files):,} files, {len(fst.dirs)} directories, {fst.total_bytes:,} bytes")
    print(f"extracting to {args.out.resolve()}\n")

    started = time.time()
    last = [0.0]

    def progress(n, total, entry, written):
        now = time.time()
        if now - last[0] < 0.5 and n != total:
            return
        last[0] = now
        pct = 100.0 * n / total
        mb = written / 1024**2
        rate = mb / max(now - started, 0.001)
        print(
            f"\r  [{n:>5}/{total}] {pct:5.1f}%  {mb:8.1f} MB  {rate:6.1f} MB/s  {entry.path[:44]:<44}",
            end="",
            flush=True,
        )

    written = disc.extract(args.out, progress=progress)
    elapsed = time.time() - started

    print(f"\n\ndone: {written:,} bytes in {elapsed:.1f}s")
    if written != fst.total_bytes:
        print(f"WARNING: expected {fst.total_bytes:,} bytes", file=sys.stderr)
        return 1

    if args.iso:
        # DVDRead works in disc offsets, so the runtime wants the disc flat.
        image = open_image(args.image)
        total = getattr(image, "iso_size", None) or args.image.stat().st_size
        chunk = 4 << 20
        started = time.time()
        with open(args.out / "disc.iso", "wb") as out:
            done = 0
            while done < total:
                n = min(chunk, total - done)
                out.write(image.read(done, n))
                done += n
        print(f"disc.iso: {done:,} bytes in {time.time() - started:.1f}s")
    print(f"system files in {args.out / 'sys'}/ (boot.bin, bi2.bin, main.dol, fst.bin)")
    return check_build(args.out, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
