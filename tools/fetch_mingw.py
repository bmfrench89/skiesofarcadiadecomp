"""Fetch llvm-mingw, the compiler that builds soa.exe with no Microsoft compiler, into vendor/.

    python tools/fetch_mingw.py           # fetch it when missing, then record
    python tools/fetch_mingw.py --verify  # check what is on disk against the record

specs/distribution.md R1 (Q-D1, answered 2026-10-04: fetch it): llvm-mingw
targets x86_64-w64-mingw32 against the UCRT, with mingw-w64's headers and
libraries, so a Windows build needs no Visual Studio. The release is pinned,
and so is its archive's sha256, which a release asset keeps and a different
one is refused; GitHub records the same digest beside each asset.

- On Windows, the Windows-hosted build: the compiler that builds soa.exe here,
  and the one a player's package carries as toolchain/.
- On Linux, the Ubuntu-hosted build of the same release: CI's job compiling
  every runtime file for Windows with it.

It lands in vendor/llvm-mingw, gitignored, pruned to what an x86-64 Windows
build uses: the other targets' sysroots (i686, armv7, aarch64), the bundled
Python, the debugger and the editor tools are left in the archive.
vendor/MINGW.sha256 records the sha256 of every file kept (a symbolic link as
its target), in sha256sum's format with the source as a comment, as
vendor/GPU.sha256 does for the GPU's; --verify reports any file missing or
changed. Nothing here touches game data.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RECORD = "MINGW.sha256"
DEST = "llvm-mingw"
RELEASE = "20260922"  # LLVM 23.1.2
BASE = f"https://github.com/mstorsjo/llvm-mingw/releases/download/{RELEASE}/"
ASSETS = {
    "Windows": (
        BASE + f"llvm-mingw-{RELEASE}-ucrt-x86_64.zip",
        "e3ad77d117a4bea19a7a3b333341824d79a5a371004a10e25b8504e7b3047666",
    ),
    "Linux": (
        BASE + f"llvm-mingw-{RELEASE}-ucrt-ubuntu-22.04-x86_64.tar.xz",
        "bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21",
    ),
}
# Left in the archive: the other targets, the bundled Python and busybox, and
# in bin/ the debugger, the editor tools and the other targets' wrappers.
SKIP_TOP = {
    "python",
    "busybox",
    "share",
    "i686-w64-mingw32",
    "armv7-w64-mingw32",
    "aarch64-w64-mingw32",
    "arm64ec-w64-mingw32",
}
SKIP_BIN = (
    "lldb",
    "liblldb",
    "clangd",
    "clang-tidy",
    "libpython",
    "i686-",
    "armv7-",
    "aarch64-",
    "arm64ec-",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=600) as r:  # noqa: S310 - fixed https URLs
        return r.read()


def kept(rel: PurePosixPath) -> bool:
    """Whether a path inside the release's top folder is kept."""
    parts = rel.parts
    if not parts or parts[0] in SKIP_TOP:
        return False
    return not (parts[0] == "bin" and len(parts) == 2 and parts[1].startswith(SKIP_BIN))


def entry_digest(p: Path) -> str:
    """A file's sha256, or a symbolic link's target, as the record holds it."""
    if p.is_symlink():
        return "link:" + p.readlink().as_posix()
    return sha256(p.read_bytes())


def read_record(path: Path) -> tuple[dict[str, str], list[str]]:
    """(relative path -> sha256 or link:target, the comment lines)."""
    files: dict[str, str] = {}
    comments: list[str] = []
    if not path.exists():
        return files, comments
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            comments.append(line)
        elif line.strip():
            digest, _, name = line.partition("  ")
            files[name.strip()] = digest.strip()
    return files, comments


def write_record(path: Path, files: dict[str, str], source: str) -> None:
    lines = [
        "# llvm-mingw, which builds soa.exe with no Microsoft compiler "
        "(tools/fetch_mingw.py, specs/distribution.md R1).",
        source,
    ]
    lines += [f"{d}  {n}" for n, d in sorted(files.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(vendor: Path) -> list[str]:
    files, _ = read_record(vendor / RECORD)
    if not files:
        return [f"no {vendor / RECORD}: run tools/fetch_mingw.py first"]
    bad = []
    for name, digest in sorted(files.items()):
        p = vendor / name
        if not p.exists() and not p.is_symlink():
            bad.append(f"{name}: recorded but missing")
        elif entry_digest(p) != digest:
            bad.append(f"{name}: differs from the record")
    return bad


def unpack(blob: bytes, url: str, dest: Path) -> list[Path]:
    """The kept part of the release, its top folder stripped, into dest."""
    out: list[Path] = []
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for info in z.infolist():
                rel = PurePosixPath(*PurePosixPath(info.filename).parts[1:])
                if info.is_dir() or not kept(rel):
                    continue
                p = dest / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(z.read(info))
                out.append(p)
        return out
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as t:
        for m in t.getmembers():
            rel = PurePosixPath(*PurePosixPath(m.name).parts[1:])
            if m.isdir() or not kept(rel):
                continue
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if m.issym():
                if p.is_symlink() or p.exists():
                    p.unlink()
                p.symlink_to(m.linkname)
            elif m.isfile():
                f = t.extractfile(m)
                assert f is not None
                p.write_bytes(f.read())
                p.chmod(0o755 if m.mode & 0o111 else 0o644)
            else:
                continue
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--vendor", type=Path, default=ROOT / "vendor")
    ap.add_argument(
        "--verify", action="store_true", help="only check what is on disk against the record"
    )
    args = ap.parse_args(argv)
    vendor = args.vendor

    if args.verify:
        bad = verify(vendor)
        for line in bad[:20]:
            print(line, file=sys.stderr)
        if len(bad) > 20:
            print(f"... and {len(bad) - 20} more", file=sys.stderr)
        files, _ = read_record(vendor / RECORD)
        print(f"{len(files) - len(bad)} of {len(files)} recorded llvm-mingw file(s) unchanged")
        return 1 if bad else 0

    host = platform.system()
    if host not in ASSETS:
        print(f"error: no llvm-mingw release is pinned for {host}", file=sys.stderr)
        return 1
    url, pin = ASSETS[host]
    dest = vendor / DEST
    clang = dest / "bin" / ("clang.exe" if host == "Windows" else "clang")
    if clang.exists() and (vendor / RECORD).exists():
        print(f"{dest} is there; --verify checks it")
        return 0
    blob = fetch(url)
    digest = sha256(blob)
    if digest != pin:
        print(f"error: {url} has sha256 {digest}, not the pinned {pin}", file=sys.stderr)
        return 1
    paths = unpack(blob, url, dest)
    files = {p.relative_to(vendor).as_posix(): entry_digest(p) for p in paths}
    write_record(vendor / RECORD, files, f"# llvm-mingw {RELEASE}: {url} (sha256 {digest}, pinned)")
    print(f"recorded {len(files)} file(s) in {vendor / RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
