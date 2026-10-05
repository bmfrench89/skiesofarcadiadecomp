#!/usr/bin/env python3
"""Extract a Skies of Arcadia Legends disc image into a working directory.

    python tools/extract.py <disc.rvz|disc.iso> [--out extracted/] [--files] [--store [--iso]]
    python tools/extract.py --prune-loose [--dry-run] [--out extracted/]
    python tools/extract.py --check <store>
    python tools/extract.py --compare <store> <disc.iso> [--flip OFFSET]
    python tools/extract.py --sys-only <store> [--out extracted/]

Writes `<out>/disc.iso`, the flat image the runtime reads, and `<out>/sys/`
(boot.bin, bi2.bin, main.dol, fst.bin: 3.3 MB) for the tools, then checks the
executable against config/. That is all the port and the tools need: a tool
that wants one file of the disc reads it through the image
(`soa.disc.open_data`). `--files` also writes every file of the disc loose,
another 1.42 GB, for browsing; nothing reads them.

`--prune-loose` deletes the loose files an earlier extraction left under
`--out`, each only after its bytes have been compared with its slice of
`<out>/disc.iso`. A file that differs is kept and named; directories the
prune empties are removed; `sys/` and the image are never touched.
`--dry-run` compares and reports without deleting anything.

`--store` writes `<out>/GEAE8P.soadisc` instead of disc.iso (disc-layer I4;
`--iso` writes both): every byte of the disc to a mebibyte past its last file,
a table of its extents and a SHA-1 of every 64 KiB block, judged against the
whole disc's pinned hashes in config/GEAE8P/disc.yml. A dump whose files
differ is refused (`--force` accepts it); one whose files match and padding
does not is accepted with a warning. `--check` re-hashes a store, `--compare`
holds it to an ISO byte for byte (`--flip` corrupts one byte of the store's
side in memory, the mutation), and `--sys-only` writes `sys/` from it. NKit,
GCZ, WIA, CISO and WBFS images are named and refused: Dolphin converts each
to ISO or RVZ.

You must supply your own dump of a disc you own. Nothing extracted here is
redistributable; the output directory is gitignored.
"""

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import store  # noqa: E402
from soa.disc import IMAGE_NAME, SYSTEM_DIR, Disc, ImageFile  # noqa: E402
from soa.dump import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_DISC_PINS,
    ProjectError,
    read_disc_pins,
    read_project,
    verify,
)
from soa.rvz import RVZ  # noqa: E402

EXPECTED_GAME_ID = "GEAE8P"
CHUNK = 4 << 20


def check_build(out: Path, force: bool = False) -> int:
    """Is what we just unpacked the build `config/` describes?

    Asked here because this is the moment the answer first exists and this is
    the one command everybody runs; `tools/checkdump.py` asks the same
    question later, when an `extracted/` has been sitting around and nobody
    remembers which dump made it. A mismatch is fatal without --force: every
    address in `config/` belongs to one build, and nothing downstream of here
    -- the recompiler, dtk, the decompilation match -- looks at the
    executable's identity again until the port refuses it at boot.
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
    return ImageFile(path)


# Formats Dolphin reads and this does not (section 3.7.3): each named, with the way out.
UNSUPPORTED = (
    (0, b"\x01\xc0\x0b\xb1", "GCZ"),
    (0, b"WIA\x01", "WIA"),
    (0, b"CISO", "CISO"),
    (0, b"WBFS", "WBFS"),
    (0x200, b"NKIT", "NKit"),
)


def unsupported(path: Path) -> str | None:
    """Why the image at `path` cannot be read here, or None."""
    with open(path, "rb") as f:
        head = f.read(0x210)
    for at, magic, name in UNSUPPORTED:
        if head[at : at + len(magic)] == magic:
            return (
                f"{path} is a {name} image, which this does not read: Dolphin converts it "
                "(right-click the game, Convert File) to ISO or RVZ"
            )
    if ".nkit." in path.name.lower():
        return f"{path} is named as an NKit image: Dolphin converts it to ISO or RVZ"
    return None


def import_store(
    image: Path,
    out: Path,
    force: bool = False,
    pins_path: Path = DEFAULT_DISC_PINS,
    config: Path = DEFAULT_CONFIG,
    game_id: str = EXPECTED_GAME_ID,
) -> int:
    """The store from a dump (section 3.7.3): checked as a disc of this game, written
    beside its destination, read back, and judged against the pinned hashes.
    0 when it is written; 1 when refused, with nothing left behind."""
    why = unsupported(image)
    if why:
        print(f"error: {why}", file=sys.stderr)
        return 1
    reader = open_image(image)
    try:
        try:
            disc = Disc(reader, source=str(image))
        except ValueError as exc:
            print(f"error: {exc}: not a GameCube disc image", file=sys.stderr)
            return 1
        b = disc.boot
        if (b.game_id, b.disc_number, b.version) != (game_id, 0, 0):
            print(
                f"error: {image} is {b.game_id} disc {b.disc_number} revision {b.version}; this port is "
                f"{game_id} disc 0 revision 0, the North American release (European and Japanese "
                "discs are not supported)",
                file=sys.stderr,
            )
            return 1
        want = read_project(config).sha1
        got = hashlib.sha1(disc.read_dol(), usedforsecurity=False).hexdigest()
        if got != want and not force:
            print(
                f"error: {image}'s executable has SHA-1 {got}, not config/'s {want}: another revision "
                "or a patched dump (--force imports it anyway)",
                file=sys.stderr,
            )
            return 1
        try:
            pins = read_disc_pins(pins_path)
        except ProjectError as exc:
            pins = None
            print(f"note: no pinned hashes to judge it by ({exc})")
        dest = out / f"{game_id}{store.STORE_SUFFIX}"
        part = dest.with_name(dest.name + ".part")
        if part.exists():
            print(f"deleting {part}, an unfinished import")
            part.unlink()
        out.mkdir(parents=True, exist_ok=True)
        size = getattr(reader, "iso_size", None) or reader.size
        kind = store.SOURCE_RVZ if isinstance(reader, RVZ) else store.SOURCE_ISO
        started = time.time()
        try:
            w = store.write(reader, size, dest, kind, "tools/extract.py (disc-layer I4)", pins)
        except store.StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    finally:
        if hasattr(reader, "close"):  # an RVZ reader holds no file open
            reader.close()
    h = w.header
    print(
        f"{dest.name}: {dest.stat().st_size:,} bytes in {time.time() - started:.1f}s; "
        f"{h.extent_count:,} extents, {h.block_count:,} blocks, covered to 0x{h.covered_end:X} "
        f"of 0x{h.image_size:X}"
    )
    print(
        f"  image {w.image_sha1}\n  FST   {w.fst_sha1}\n  files {w.files_sha1}\n  DOL   {w.dol_sha1}"
    )
    if pins is None:
        print("verdict: imported; config/GEAE8P/disc.yml pins nothing to compare with")
        return 0
    if str(size) != pins["image_size"]:
        print(
            f"note: the image is {size:,} bytes, and the pinned size is {int(pins['image_size']):,}"
        )
    files_ok, image_ok = w.files_sha1 == pins["files_sha1"], w.image_sha1 == pins["image_sha1"]
    if files_ok and image_ok and w.fst_sha1 == pins["fst_sha1"]:
        print(
            "verdict: a verified dump: the image, its file table and its files are the pinned ones"
        )
        return 0
    if files_ok:
        print(
            "verdict: accepted, with a warning: the files are the game's, and the padding between them "
            "is not the pinned image's (a scrubbed or trimmed dump), so a read past a file's end gets "
            "other bytes than a drive would"
        )
        return 0
    if force:
        print(
            "verdict: accepted under --force: the files are not the pinned ones (a bad or patched dump)"
        )
        return 0
    dest.unlink()
    print(
        "error: the files are not the pinned ones: a bad or patched dump, refused (--force imports it). "
        "Which file differs cannot be named without a per-file list.",
        file=sys.stderr,
    )
    return 1


def check_store(path: Path) -> int:
    try:
        problems = store.check(path)
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    with store.Store(path) as st:
        h = st.header
        print(
            f"{path}: {h.extent_count:,} extents and {h.block_count:,} blocks re-hashed, "
            f"{len(problems)} differ; flags {h.flags} (1 image, 2 files matched their pins at import)"
        )
    return 1 if problems else 0


def compare_store(path: Path, iso: Path, flip: int | None) -> int:
    try:
        differ, where = store.compare(path, iso, flip)
        with store.Store(path) as st:
            end = st.covered_end
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    flipped = f" (one byte flipped at 0x{flip:X})" if flip is not None else ""
    print(f"{path} against {iso} over [0, 0x{end:X}){flipped}: {differ:,} bytes differ")
    if where:
        print("  first at " + ", ".join(f"0x{w:X}" for w in where))
    return 1 if differ else 0


def sys_only(path: Path, out: Path) -> int:
    try:
        with store.Store(path) as st, Disc(st, source=str(path)) as disc:
            written = disc.write_system_files(out)
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {', '.join(p.name for p in written)} in {out / SYSTEM_DIR}/ from {path}")
    return 0


def _key(p: Path) -> str:
    """A path as the file system compares it: absolute, and without regard
    to case on Windows."""
    return os.path.normcase(os.path.abspath(p))


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.exists() and b.exists() and a.samefile(b)
    except OSError:
        return False


def write_image(reader, image_path: Path, out: Path) -> int:
    """Write the dump flat to `<out>/disc.iso`: DVDRead works in disc offsets.
    Written beside the target and renamed, so an interrupted copy never
    leaves a short image where the runtime looks for a whole one."""
    dest = out / IMAGE_NAME
    if _same_file(image_path, dest):
        print(f"{IMAGE_NAME}: {dest} is the image given; left as it is")
        return dest.stat().st_size
    total = getattr(reader, "iso_size", None) or image_path.stat().st_size
    part = dest.with_name(dest.name + ".part")
    started = last = time.time()
    done = 0
    try:
        with open(part, "wb") as f:
            while done < total:
                data = reader.read(done, min(CHUNK, total - done))
                if not data:
                    raise OSError(f"{image_path}: ends at {done:,} bytes of {total:,}")
                f.write(data)
                done += len(data)
                now = time.time()
                if now - last >= 0.5 or done == total:
                    last = now
                    pct, mb = 100.0 * done / total, done / 1024**2
                    print(f"\r  {IMAGE_NAME}  {pct:5.1f}%  {mb:8.1f} MB", end="", flush=True)
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()
    print(f"\r{IMAGE_NAME}: {done:,} bytes in {time.time() - started:.1f}s" + " " * 20)
    return done


def extract(args) -> int:
    if not args.image.exists():
        print(f"error: {args.image} not found", file=sys.stderr)
        return 1
    if args.store:
        status = import_store(args.image, args.out, force=args.force)
        if status:
            return status
        if not args.iso:
            # sys/ for the tools; the port reads the store from disc-layer I5
            with (
                store.Store(args.out / f"{EXPECTED_GAME_ID}{store.STORE_SUFFIX}") as st,
                Disc(st) as disc,
            ):
                disc.write_system_files(args.out)
            print(
                f"system files in {args.out / SYSTEM_DIR}/; until I5 the port reads {IMAGE_NAME}: "
                "add --iso to write it too"
            )
            return check_build(args.out, force=args.force)
    elif args.iso:
        print(f"note: --iso is now the default: {IMAGE_NAME} is always written")
    why = unsupported(args.image)
    if why:
        print(f"error: {why}", file=sys.stderr)
        return 1
    with Disc(open_image(args.image), source=str(args.image)) as disc:
        status = unpack(disc, args)
    return status or check_build(args.out, force=args.force)


def unpack(disc: Disc, args) -> int:
    b = disc.boot
    print(f'{b.game_id}  "{b.title}"  (disc {b.disc_number}, rev {b.version})')

    if b.game_id != EXPECTED_GAME_ID and not args.force:
        print(
            f"error: expected {EXPECTED_GAME_ID}, got {b.game_id}. Use --force to override.",
            file=sys.stderr,
        )
        return 1

    fst = disc.fst
    out = args.out
    print(f"{len(fst.files):,} files, {len(fst.dirs)} directories, {fst.total_bytes:,} bytes")
    print(f"extracting to {out.resolve()}\n")
    out.mkdir(parents=True, exist_ok=True)

    write_image(disc.reader, args.image, out)
    disc.write_system_files(out)
    print(f"system files in {out / SYSTEM_DIR}/ (boot.bin, bi2.bin, main.dol, fst.bin)")

    if not args.files:
        left = sum((out / f.path).is_file() for f in fst.files)
        if left:
            print(
                f"{left:,} loose files from an earlier extraction are still in {out}, and "
                f"nothing reads them: python tools/extract.py --prune-loose --out {out} "
                "deletes each one that equals the image."
            )
        return 0

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

    written = disc.extract_files(out, progress=progress)
    print(f"\nloose files: {written:,} bytes in {time.time() - started:.1f}s")
    if written != fst.total_bytes:
        print(f"WARNING: expected {fst.total_bytes:,} bytes", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------
# --prune-loose
# --------------------------------------------------------------------------


def first_difference(path: Path, disc: Disc, offset: int, size: int) -> str | None:
    """None when the file at `path` holds exactly the image's `size` bytes at
    `offset`; else what differs, in words."""
    have = path.stat().st_size
    if have != size:
        return f"{have:,} bytes, the image's {size:,}"
    done = 0
    with open(path, "rb") as f:
        while done < size:
            n = min(CHUNK, size - done)
            mine, theirs = f.read(n), disc.reader.read(offset + done, n)
            if mine != theirs:
                at = next(
                    (i for i, (x, y) in enumerate(zip(mine, theirs, strict=False)) if x != y),
                    min(len(mine), len(theirs)),
                )
                return f"differs from the image at byte 0x{done + at:X}"
            done += n
    return None


def emptied_dirs(out: Path, going: list[Path]) -> list[Path]:
    """The directories under `out` that hold nothing once the files in
    `going` (each under `out`) are gone, deepest first. `out` itself and
    `sys/` are never among them."""
    gone = {_key(p) for p in going}
    candidates: dict[str, Path] = {}
    for p in going:
        parts = p.relative_to(out).parts
        for i in range(1, len(parts)):
            d = out.joinpath(*parts[:i])
            candidates[_key(d)] = d
    emptied = []
    for d in sorted(candidates.values(), key=lambda p: (-len(p.parts), str(p))):
        if d.relative_to(out).parts[0].lower() == SYSTEM_DIR or not d.is_dir():
            continue
        if all(_key(child) in gone for child in d.iterdir()):
            gone.add(_key(d))
            emptied.append(d)
    return emptied


def prune_loose(out: Path, dry_run: bool = False) -> int:
    image = out / IMAGE_NAME
    if not image.is_file():
        print(
            f"error: {image} not found. --prune-loose compares every loose file with its "
            "slice of the image before deleting it, and there is no image to compare with.\n"
            f"  Write one first: python tools/extract.py <your disc dump> --out {out}",
            file=sys.stderr,
        )
        return 1
    try:
        disc = Disc.from_file(image)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"checking the loose files under {out} against {image}")
    if dry_run:
        print("  (dry run: nothing is deleted)")
    equal: list[Path] = []
    kept: list[tuple[str, str]] = []
    with disc:
        files = sorted(disc.fst.files, key=lambda f: f.offset)  # sequential image reads
        named = {_key(out / f.path) for f in files}
        last = 0.0
        for n, entry in enumerate(files, 1):
            path = out / entry.path
            # sys/ is the tools' and never a loose file, whatever an FST says
            if Path(entry.path).parts[0].lower() == SYSTEM_DIR or _key(path) == _key(image):
                continue
            if path.is_file() and not path.is_symlink():
                why = first_difference(path, disc, entry.offset, entry.size)
                if why is None:
                    equal.append(path)
                else:
                    kept.append((entry.path, why))
            now = time.time()
            if now - last >= 0.5 or n == len(files):
                last = now
                print(f"\r  [{n:>5}/{len(files)}] {entry.path[:50]:<50}", end="", flush=True)
        print()

    total = sum(p.stat().st_size for p in equal)
    dirs = emptied_dirs(out, equal)
    others = [
        p
        for p in out.rglob("*")
        if p.is_file()
        and _key(p) not in named
        and _key(p) != _key(image)
        and p.relative_to(out).parts[0].lower() != SYSTEM_DIR
    ]
    if not dry_run:
        for path in equal:
            path.unlink()
        for d in list(dirs):
            try:
                d.rmdir()
            except OSError as exc:  # something appeared in it, or it is held open
                print(f"  could not remove {d}: {exc.strerror or exc}", file=sys.stderr)
                dirs.remove(d)

    print(f"{len(equal) + len(kept):,} of the image's {len(files):,} files are loose under {out}")
    print(
        f"  {len(equal):,} equal to the image: {'would be deleted' if dry_run else 'deleted'}"
        f" ({total:,} bytes)"
    )
    print(f"  {len(kept):,} differ from the image: kept")
    for path, why in kept:
        print(f"    kept {path}: {why}")
    print(f"  {len(dirs):,} directories emptied: {'would be removed' if dry_run else 'removed'}")
    if others:
        print(f"  {len(others):,} other files under {out} are not in the image's file table: left")
    print(f"  {SYSTEM_DIR}/ and {IMAGE_NAME} are not touched.")
    if kept:
        print(
            f"{len(kept):,} loose files differ from the image and were kept: look at them "
            "(an edit? a mod?) before deleting them by hand.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "image", type=Path, nargs="?", help="disc image (.rvz, .iso, .gcm); none with --prune-loose"
    )
    ap.add_argument("--out", type=Path, default=Path("extracted"))
    ap.add_argument(
        "--force",
        action="store_true",
        help="allow a non-GEAE8P disc, and report rather than refuse an unexpected executable",
    )
    ap.add_argument(
        "--files",
        action="store_true",
        help="also write every file of the disc loose under --out (1.42 GB), for browsing",
    )
    ap.add_argument(
        "--iso",
        action="store_true",
        help=f"accepted for old command lines: {IMAGE_NAME} is now always written",
    )
    ap.add_argument(
        "--prune-loose",
        action="store_true",
        help=f"delete each loose file under --out that equals its slice of {IMAGE_NAME}; "
        f"keep and name any that differ; never touch {SYSTEM_DIR}/",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="with --prune-loose: compare and report only"
    )
    ap.add_argument(
        "--store",
        action="store_true",
        help="write <out>/GEAE8P.soadisc, the checked store (disc-layer I4), with --iso disc.iso too",
    )
    ap.add_argument(
        "--check", type=Path, metavar="STORE", help="re-hash a store's every extent and block"
    )
    ap.add_argument(
        "--compare",
        type=Path,
        nargs=2,
        metavar=("STORE", "ISO"),
        help="a store against an ISO, byte for byte",
    )
    ap.add_argument(
        "--flip",
        type=lambda v: int(v, 0),
        metavar="OFFSET",
        help="with --compare: one store byte corrupted",
    )
    ap.add_argument("--sys-only", type=Path, metavar="STORE", help="write <out>/sys/ from a store")
    args = ap.parse_args(argv)

    if args.check:
        return check_store(args.check)
    if args.compare:
        return compare_store(args.compare[0], args.compare[1], args.flip)
    if args.flip is not None:
        ap.error("--flip goes with --compare")
    if args.sys_only:
        return sys_only(args.sys_only, args.out)

    if args.prune_loose:
        if args.image is not None or args.files or args.iso:
            ap.error(
                "--prune-loose works on what is already in --out, against its own "
                f"{IMAGE_NAME}: run it on its own, without a dump, --files or --iso"
            )
        return prune_loose(args.out, dry_run=args.dry_run)
    if args.dry_run:
        ap.error("--dry-run goes with --prune-loose")
    if args.image is None:
        ap.error("the disc image to extract is required (or --prune-loose)")
    return extract(args)


if __name__ == "__main__":
    raise SystemExit(main())
