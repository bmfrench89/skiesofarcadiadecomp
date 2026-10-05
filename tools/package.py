#!/usr/bin/env python3
"""Stage the player's package: what a release zip holds, laid out in a folder.

    python tools/package.py stage <folder>
    python tools/package.py --out <dir> [--version V]   # the release zip

specs/distribution.md R3, whose staging R2 tests with. --out stages into
<dir>/soa-<version>-windows-x64/, zips it beside, and writes the zip's
sha256 beside that; the version is --version, else GITHUB_REF_NAME on a tag,
else `git describe`. A package holds no
translated or decompiled game code and no game data (SPEC section 2 rule 5;
3.6), only what builds the game on the player's machine from their own disc:

    python/     CPython's embeddable distribution for Windows x64, pinned and
                hashed (3.5), which runs the build's tools
    toolchain/  llvm-mingw, as tools/fetch_mingw.py keeps it (3.2)
    source/     runtime/, config/, the tools the build runs, the mods' text,
                vendor/'s GPU build files, README.md, LICENSE and NOTICE
    licenses/   the third parties' texts: CPython, LLVM, llvm-mingw, mingw-w64,
                Vulkan-Headers and glslang

Never src/, include/, gen/, extracted/ or build/. The player runs
python\\python.exe source\\tools\\player_build.py --disc <image> --root <folder>
(R4's setup window does it for them).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch_gpu  # noqa: E402
import fetch_mingw  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
PYTHON_VERSION = "3.14.8"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"
PYTHON_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"

# The tools the build runs (tools/player_build.py and what it imports), and
# soa/ whole.
TOOLS = ("player_build.py", "recompile.py", "extract.py", "decomp.py", "fetch_gpu.py")
TOP = ("README.md", "LICENSE", "NOTICE", "pyproject.toml")
MOD_FILES = ("mod.c", "mod.ini", "patches.txt")
# The licences that are not in what the package carries already, fetched at
# the pinned releases' tags and held to their hashes.
LICENSE_URLS = {
    "llvm-mingw.txt": (
        f"https://raw.githubusercontent.com/mstorsjo/llvm-mingw/{fetch_mingw.RELEASE}/LICENSE.txt",
        "8e5db0129069005be2a07be3297e198888fd72fad62a13a611504660c6b7e3c7",
    ),
    "glslang.txt": (
        f"https://raw.githubusercontent.com/KhronosGroup/glslang/{fetch_gpu.GLSLANG_VERSION}/LICENSE.txt",
        "17e70c676e1521ff3e4686f04a2053d93a7e28a33be8de7ec37ab0ff72feb677",
    ),
}
# And the ones it carries, by where they are in the package.
LICENSE_COPIES = {
    "cpython.txt": "python/LICENSE.txt",
    "llvm.txt": "toolchain/LICENSE.TXT",
    "mingw-w64.txt": "toolchain/x86_64-w64-mingw32/share/mingw32/COPYING.MinGW-w64.txt",
    "mingw-w64-runtime.txt": "toolchain/x86_64-w64-mingw32/share/mingw32/COPYING.MinGW-w64-runtime.txt",
    "winpthreads.txt": "toolchain/x86_64-w64-mingw32/share/mingw32/COPYING.winpthreads.txt",
    "vulkan-headers.md": "source/vendor/vulkan-headers/LICENSE.md",
}

# Never in a package, wherever they appear under what is copied.
NEVER = {"src", "include", "gen", "extracted", "build", "__pycache__", ".pytest_cache"}


def python_zip() -> Path:
    """The embeddable CPython, fetched once into vendor/ and held to its pin."""
    path = VENDOR / PYTHON_ZIP
    if not path.exists():
        print(f"fetching {PYTHON_URL}")
        with urllib.request.urlopen(PYTHON_URL, timeout=300) as r:  # noqa: S310 - fixed https URL
            blob = r.read()
        VENDOR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        raise SystemExit(f"error: {path} has sha256 {digest}, not the pinned {PYTHON_SHA256}")
    return path


def copy_tree(src: Path, dest: Path, suffixes: tuple[str, ...] | None = None) -> int:
    """Every file under src into dest, skipping NEVER's names; only `suffixes`
    when given. The answer is how many."""
    n = 0
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if not f.is_file() or NEVER & set(rel.parts):
            continue
        if suffixes is not None and f.suffix not in suffixes:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, out)
        n += 1
    return n


def stage(dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"error: {dest} is not empty")
    bad = fetch_mingw.verify(VENDOR) + fetch_gpu.verify(VENDOR)
    if bad:
        raise SystemExit(f"error: vendor/ is not as recorded ({bad[0]})")
    with zipfile.ZipFile(python_zip()) as z:
        z.extractall(dest / "python")
    shutil.copytree(VENDOR / "llvm-mingw", dest / "toolchain", symlinks=True)
    source = dest / "source"
    copy_tree(ROOT / "runtime", source / "runtime")
    copy_tree(ROOT / "config", source / "config")
    copy_tree(ROOT / "tools" / "soa", source / "tools" / "soa", (".py",))
    for name in TOOLS:
        shutil.copyfile(ROOT / "tools" / name, source / "tools" / name)
    for name in TOP:
        shutil.copyfile(ROOT / name, source / name)
    for folder in ("mods", "examples/mods"):
        for mod in sorted((ROOT / folder).iterdir()):
            for name in MOD_FILES:
                if (mod / name).is_file():
                    (source / folder / mod.name).mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(mod / name, source / folder / mod.name / name)
    for name in ("vulkan-headers", "glslang"):
        shutil.copytree(VENDOR / name, source / "vendor" / name)
    shutil.copyfile(VENDOR / fetch_gpu.RECORD, source / "vendor" / fetch_gpu.RECORD)
    licenses(dest)
    print(f"staged {dest}")


def licenses(dest: Path) -> None:
    """dest/licenses: the third parties' texts, copied from the package or
    fetched at their pinned tags into vendor/licenses/ once."""
    out = dest / "licenses"
    out.mkdir(parents=True, exist_ok=True)
    for name, rel in LICENSE_COPIES.items():
        shutil.copyfile(dest / rel, out / name)
    cache = VENDOR / "licenses"
    for name, (url, pin) in LICENSE_URLS.items():
        path = cache / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - fixed https URL
                blob = r.read()
            cache.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pin:
            raise SystemExit(f"error: {url} has sha256 {digest}, not the pinned {pin}")
        shutil.copyfile(path, out / name)


def version() -> str:
    """The release's version: a tag the workflow runs on, else git's own
    description of the commit."""
    ref = os.environ.get("GITHUB_REF_NAME", "")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and ref:
        return ref
    proc = subprocess.run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() or "dev"


def build_zip(out: Path, ver: str) -> Path:
    """Stage into out/<name>, zip it as out/<name>.zip, its sha256 beside."""
    name = f"soa-{ver}-windows-x64"
    staged = out / name
    if staged.exists():
        shutil.rmtree(staged)
    stage(staged)
    zpath = out / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(staged.rglob("*")):
            if f.is_file():
                z.write(f, f"{name}/{f.relative_to(staged).as_posix()}")
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (out / f"{name}.zip.sha256").write_text(f"{digest}  {zpath.name}\n", encoding="utf-8")
    unpacked = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file())
    print(
        f"package {zpath.name}: {zpath.stat().st_size:,} bytes, {unpacked:,} unpacked, sha256 {digest}"
    )
    return zpath


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, help="stage, zip and hash the package into this folder")
    ap.add_argument("--version", default=None, help="the package's version (default: version())")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("stage", help="lay a package out in an empty folder")
    s.add_argument("dest", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "stage":
        stage(args.dest.resolve())
    elif args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        build_zip(args.out.resolve(), args.version or version())
    else:
        ap.error("stage <folder>, or --out <dir>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
