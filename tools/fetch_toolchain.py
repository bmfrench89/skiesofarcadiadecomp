"""Fetch the Metrowerks compilers the game was built with (and the object
diff tool) into vendor/, which is gitignored.

    python tools/fetch_toolchain.py [--versions 1.3.2,1.2.5n] [--verify]

With no --versions, every compiler config/GEAE8P/units.txt names is fetched:
the list is a property of the units, and a default of "1.3.2" left a fresh
checkout unable to build the four units that want 1.2.5n.

The compilers come from the decompilation community's archive
(files.decomp.dev/compilers_latest.zip, about 80 MB). That archive is mutable
and unversioned, so what it holds today is not necessarily what produced the
bytes this project calls a match. There is nothing to pin it against, so this
records instead: the sha256 of the archive and of every compiler unpacked out
of it go into vendor/TOOLCHAIN.sha256, in the same format as sha256sum, and a
later run checks what is on disk against that record. A compiler that has
changed under a match is then a fact with a date on it rather than a mystery.
``--expect-sha256`` refuses an archive whose hash is not the one given.

Nothing here touches game data.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ARCHIVE = "https://files.decomp.dev/compilers_latest.zip"
OBJDIFF = (
    "https://github.com/encounter/objdiff/releases/download/v3.8.1/objdiff-cli-windows-x86_64.exe"
)
RECORD = "TOOLCHAIN.sha256"


def versions_from_units(path: Path) -> list[str]:
    """The compiler versions units.txt names, in first-seen order."""
    out: list[str] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) > 1 and parts[1].strip() and parts[1].strip() not in out:
            out.append(parts[1].strip())
    return out


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url) as r:  # noqa: S310 - fixed https URLs
        return r.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_record(path: Path) -> dict[str, str]:
    """``relative path -> sha256`` from a sha256sum-format file."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if digest and name:
            out[name.strip().replace("\\", "/")] = digest.strip()
    return out


def read_sources(path: Path) -> dict[str, str]:
    """The ``# name: url`` provenance comments of an existing record.

    A run that downloads nothing still rewrites the file, and dropping where
    the bytes came from would leave the hashes unattributable.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, url = line.removeprefix("#").strip().partition(": ")
        if line.startswith("#") and sep and "://" in url:
            out[name] = url
    return out


def write_record(path: Path, entries: dict[str, str], sources: dict[str, str]) -> None:
    lines = [
        "# What this checkout's toolchain actually is. Written by",
        "# tools/fetch_toolchain.py; the compilers' archive is mutable and",
        "# unversioned, so this is the only record of what produced a match.",
    ]
    lines += [f"# {name}: {url}" for name, url in sorted(sources.items())]
    lines += [f"{digest}  {name}" for name, digest in sorted(entries.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify(vendor: Path, record: dict[str, str]) -> list[str]:
    """Which recorded files are gone or no longer what they were."""
    bad = []
    for name, digest in sorted(record.items()):
        target = vendor / name
        if not target.exists():
            bad.append(f"{name}: recorded but missing")
        elif sha256(target.read_bytes()) != digest:
            bad.append(f"{name}: sha256 differs from the record")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--versions",
        default=None,
        help="comma-separated GameCube compiler versions (default: every version units.txt names)",
    )
    ap.add_argument("--units", type=Path, default=Path("config/GEAE8P/units.txt"))
    ap.add_argument("--vendor", type=Path, default=Path("vendor"))
    ap.add_argument("--objdiff", action="store_true", help="also fetch objdiff-cli")
    ap.add_argument("--expect-sha256", default=None, help="refuse an archive with another hash")
    ap.add_argument(
        "--verify", action="store_true", help="only check what is on disk against the record"
    )
    args = ap.parse_args(argv)

    dest = args.vendor / "mwcc"
    record_path = args.vendor / RECORD
    record = read_record(record_path)

    if args.verify:
        if not record:
            print(f"error: no {record_path}; nothing to verify against", file=sys.stderr)
            return 1
        bad = verify(args.vendor, record)
        for message in bad:
            print(message, file=sys.stderr)
        print(f"{len(record) - len(bad)} of {len(record)} recorded file(s) unchanged")
        return 1 if bad else 0

    if args.versions:
        versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    else:
        versions = versions_from_units(args.units)
        if not versions:
            print(f"error: no compiler versions in {args.units}", file=sys.stderr)
            return 1
        print(f"versions from {args.units}: {', '.join(versions)}")

    dest.mkdir(parents=True, exist_ok=True)
    entries = dict(record)
    sources = read_sources(record_path)
    missing = [v for v in versions if not (dest / "GC" / v / "mwcceppc.exe").exists()]
    if missing:
        blob = fetch(ARCHIVE)
        digest = sha256(blob)
        if args.expect_sha256 and digest != args.expect_sha256:
            print(
                f"error: archive sha256 {digest} is not the expected {args.expect_sha256}",
                file=sys.stderr,
            )
            return 1
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            members = [n for n in z.namelist() if any(n.startswith(f"GC/{v}/") for v in missing)]
            if not members:
                print(f"error: none of {missing} in the archive", file=sys.stderr)
                return 1
            z.extractall(dest, members=members)
        print(f"unpacked {', '.join(missing)} into {dest / 'GC'} (archive sha256 {digest})")
        sources["compilers_latest.zip"] = f"{ARCHIVE} sha256 {digest}"
    else:
        print(f"compilers present: {', '.join(versions)}")

    # Record every compiler we were asked for, whether this run unpacked it or
    # found it: the point is to say what is on disk under today's matches.
    for version in versions:
        exe = dest / "GC" / version / "mwcceppc.exe"
        if exe.exists():
            entries[f"mwcc/GC/{version}/mwcceppc.exe"] = sha256(exe.read_bytes())

    if args.objdiff:
        exe = args.vendor / "objdiff-cli.exe"
        if not exe.exists():
            exe.write_bytes(fetch(OBJDIFF))
            print(f"wrote {exe}")
            sources["objdiff-cli.exe"] = OBJDIFF
        entries["objdiff-cli.exe"] = sha256(exe.read_bytes())

    changed = [n for n, d in entries.items() if n in record and record[n] != d]
    for name in changed:
        print(f"warning: {name} is not the file {record_path} recorded", file=sys.stderr)
    write_record(record_path, entries, sources)
    print(f"recorded {len(entries)} file(s) in {record_path}")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
