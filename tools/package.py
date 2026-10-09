#!/usr/bin/env python3
"""Stage the player's package: what a release zip holds, laid out in a folder.

    python tools/package.py stage <folder>
    python tools/package.py --out <dir> [--version V]   # the release zip
    python tools/package.py check <package folder> [--commit REV]

specs/distribution.md R3, whose staging R2 tests with. --out stages into
<dir>/soa-<version>-windows-x64/, zips it beside, and writes the zip's
sha256 beside that; the version is --version, else GITHUB_REF_NAME on a tag,
else `git describe`. A package holds no
translated or decompiled game code and no game data (SPEC section 2 rule 5;
3.6), only what builds the game on the player's machine from their own disc:

    Setup.exe   the setup window (R4), built here from tools/setup/ with the
                package's own compiler
    python/     CPython's embeddable distribution for Windows x64, pinned and
                hashed (3.5), which runs the build's tools
    toolchain/  llvm-mingw, as tools/fetch_mingw.py keeps it (3.2)
    source/     runtime/, config/, the tools the build runs, the mods' text,
                vendor/'s GPU build files, bionic's 44 pinned files the
                phone's sysroot is built from on the player's PC
                (vendor/android-sysroot-src, R5b), VERSION, README.md,
                LICENSE and NOTICE
    licenses/   the third parties' texts: CPython, LLVM, llvm-mingw, mingw-w64,
                Vulkan-Headers, glslang, the Android sysroot's notices
                (bionic's own words, generated from those files), and Linux's
                GPL-2.0 and syscall note, which its kernel headers are under

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
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch_android_sysroot  # noqa: E402
import fetch_gpu  # noqa: E402
import fetch_mingw  # noqa: E402
import player_build  # noqa: E402
from soa import seam, toolchain  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
SETUP = ROOT / "tools" / "setup"
PYTHON_VERSION = "3.14.8"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"
PYTHON_SHA256 = "a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310"

# The tools the build runs (tools/player_build.py and what it imports), and
# soa/ whole. recompile.py imports fetch_sdl at its top (L10): a package
# without it stopped there, which test_package.py now holds. An Android
# target runs fetch_android_sysroot.py to build the sysroot (R5b).
TOOLS = (
    "player_build.py",
    "recompile.py",
    "extract.py",
    "decomp.py",
    "fetch_gpu.py",
    "fetch_sdl.py",
    "fetch_android_sysroot.py",
)
TOP = ("README.md", "LICENSE", "NOTICE", "pyproject.toml")
MOD_FILES = ("mod.c", "mod.ini", "patches.txt")
# The kernel the Android sysroot's Linux headers were generated from: bionic's
# pinned linux/version.h says 6.19.0 (LINUX_VERSION_CODE 398080), which
# test_package.py derives, so a new bionic commit with newer headers fails it.
LINUX_TAG = "v6.19"
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
    "linux-gpl-2.0.txt": (
        f"https://raw.githubusercontent.com/torvalds/linux/{LINUX_TAG}/LICENSES/preferred/GPL-2.0",
        "8780e78a1a737e127f25a65f6d95269bffd36158dc261114de7859b490bfc5aa",
    ),
    "linux-syscall-note.txt": (
        f"https://raw.githubusercontent.com/torvalds/linux/{LINUX_TAG}/LICENSES/exceptions/Linux-syscall-note",
        "8e378ab93586eb55135d3bc119cce787f7324f48394777d00c34fa3d0be3303f",
    ),
}
# Generated at staging from the package's own sources, held to the pin of the
# sysroot's NOTICE.txt: the same text the player's PC writes into the tree.
SYSROOT_LICENSE = "android-sysroot.txt"
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
# Where bionic's pinned files go in a package: under the guard's third-party
# allowance (source/vendor/), so their libc/include/ passes guard.py --tree.
SYSROOT_SOURCES = Path("source") / "vendor" / fetch_android_sysroot.CACHE
# The deepest path a build writes under a package's folder, each under the
# longest name its tool writes it, which Setup.exe leaves room for too:
# gen-android-x86_64/stub/libsoa_runtime.so (41) and lld's temporary suffix
# (11); source/vendor/ (14) and the sysroot's own deepest, 73 (R5b).
BUILD_DEEPEST = max(
    len("gen-android-x86_64/stub/libsoa_runtime.so") + 11,
    len("source/vendor/") + fetch_android_sysroot.longest_written(),
)


def fetch(url: str) -> bytes:
    """One download, through the sysroot tool's fetch(): paced, its transport
    failures tried again, a 429's wait honoured, and refused in its words."""
    print(f"fetching {url}")
    try:
        return fetch_android_sysroot.fetch(url)
    except fetch_android_sysroot.Refused as exc:
        raise SystemExit(f"error: {exc}") from None


def python_zip() -> Path:
    """The embeddable CPython, fetched once into vendor/ and held to its pin."""
    path = VENDOR / PYTHON_ZIP
    if not path.exists():
        blob = fetch(PYTHON_URL)
        VENDOR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != PYTHON_SHA256:
        raise SystemExit(f"error: {path} has sha256 {digest}, not the pinned {PYTHON_SHA256}")
    return path


def build_setup(out: Path, defines: tuple[str, ...] = ()) -> Path:
    """Setup.exe from tools/setup/, with llvm-mingw (the package's compiler)
    and its manifest; no timestamp and no symbols, so one source makes one
    file. ``defines`` are -D flags, for the mutations."""
    cc = toolchain.compiler_path(toolchain.MINGW)
    if cc is None:
        raise SystemExit("error: no llvm-mingw; python tools/fetch_mingw.py fetches it")
    windres = Path(cc).with_name(Path(cc).name.replace("clang", "windres"))
    res = out.with_suffix(".res")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(windres), "setup.rc", "-O", "coff", "-o", str(res)], cwd=SETUP, check=True)
    cmd = [cc, "-std=c17", "-O2", "-Wall", "-mwindows", "-municode", "-s"]
    cmd += [f"-D{d}" for d in defines]
    cmd += [str(SETUP / "setup.c"), str(res), "-o", str(out), "-Wl,--no-insert-timestamp"]
    cmd += ["-lcomctl32", "-lcomdlg32", "-lshell32", "-ladvapi32", "-lole32", "-luuid"]
    subprocess.run(cmd, check=True)
    res.unlink()
    return out


def deepest(folder: Path) -> int:
    """The longest path under ``folder`` as Windows spells it from there, and
    never less than what a build writes under it (BUILD_DEEPEST): what
    Setup.exe leaves room for."""
    paths = (len(str(f.relative_to(folder))) for f in folder.rglob("*") if f.is_file())
    return max(max(paths, default=0), BUILD_DEEPEST)


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


def stage_source(source: Path, ver: str | None = None) -> None:
    """A package's source/: runtime/, config/, the tools the build runs with
    soa/ whole, the top-level texts, each mod's text, and VERSION, which the
    build reads (player_build.package_version) and an Android library's
    record carries as package= (version() when `ver` is None)."""
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
    # the version and LF, read stripped; no suffix, so the guard takes it for
    # the text it is
    (source / "VERSION").write_bytes(f"{version() if ver is None else ver}\n".encode())


def stage_vendor(vendor: Path, dest: Path) -> None:
    """A package's source/vendor: the GPU build files and their record, and
    exactly bionic's 44 pinned files the sysroot is built from, each held to
    both its pins -- never copy_tree, which drops every path through a folder
    named include, and never the cache's check files."""
    for name in ("vulkan-headers", "glslang"):
        shutil.copytree(vendor / name, dest / name)
    shutil.copyfile(vendor / fetch_gpu.RECORD, dest / fetch_gpu.RECORD)
    try:
        fetch_android_sysroot.stage_sources(
            vendor / fetch_android_sysroot.CACHE, dest / fetch_android_sysroot.CACHE
        )
    except fetch_android_sysroot.Refused as exc:
        raise SystemExit(f"error: {exc}") from None


def stage(dest: Path, ver: str | None = None) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"error: {dest} is not empty")
    fetch_android_sysroot.new_run()
    cache = VENDOR / fetch_android_sysroot.CACHE
    sources = [
        f"{fetch_android_sysroot.CACHE}/{p}" for p in fetch_android_sysroot.cache_problems(cache)
    ]
    bad = fetch_mingw.verify(VENDOR) + fetch_gpu.verify(VENDOR) + sources
    if bad:
        raise SystemExit(
            f"error: vendor/ is not as recorded ({bad[0]}): python tools/fetch_mingw.py, "
            "tools/fetch_gpu.py and tools/fetch_android_sysroot.py fetch it"
        )
    ver = version() if ver is None else ver
    with zipfile.ZipFile(python_zip()) as z:
        z.extractall(dest / "python")
    shutil.copytree(VENDOR / "llvm-mingw", dest / "toolchain", symlinks=True)
    source = dest / "source"
    stage_source(source, ver)
    stage_vendor(VENDOR, source / "vendor")
    licenses(dest)
    # last, so it knows the deepest path it must leave room for
    build_setup(dest / "Setup.exe", (f"SETUP_DEEPEST={deepest(dest)}",))
    print(f"staged {dest}")


def licenses(dest: Path) -> None:
    """dest/licenses: the third parties' texts, copied from the package or
    fetched at their pinned tags into vendor/licenses/ once, and the Android
    sysroot's notices, generated from the sources the package carries."""
    out = dest / "licenses"
    out.mkdir(parents=True, exist_ok=True)
    for name, rel in LICENSE_COPIES.items():
        shutil.copyfile(dest / rel, out / name)
    cache = VENDOR / "licenses"
    for name, (url, pin) in LICENSE_URLS.items():
        path = cache / name
        if not path.exists():
            blob = fetch(url)
            cache.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pin:
            raise SystemExit(f"error: {url} has sha256 {digest}, not the pinned {pin}")
        shutil.copyfile(path, out / name)
    notice = fetch_android_sysroot.notice_text(dest / SYSROOT_SOURCES).encode("utf-8")
    want = fetch_android_sysroot.OUTPUTS["NOTICE.txt"]
    if hashlib.sha256(notice).hexdigest() != want:
        raise SystemExit(
            f"error: {SYSROOT_LICENSE} made from {SYSROOT_SOURCES.as_posix()} is not the "
            f"pinned NOTICE.txt ({want[:12]})"
        )
    (out / SYSROOT_LICENSE).write_bytes(notice)


def git_blob(rev: str, name: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{name}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def commit_inputs(rev: str = "HEAD") -> dict[str, str]:
    """player_build.inputs_record's, of a commit rather than a folder: each
    BAKED file as git holds it at `rev`, a folder's *.py as inputs_record
    takes them, read with CRLF as LF as it reads them."""
    out: dict[str, str] = {}
    for rel in player_build.BAKED:
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", rev, "--", rel],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        for name in names:
            if name == rel or name.endswith(".py"):
                blob = git_blob(rev, name).replace(b"\r\n", b"\n")
                out[name] = hashlib.sha256(blob).hexdigest()
    return out


def check(folder: Path, rev: str = "HEAD") -> int:
    """A package's baked inputs held to a commit's (R5-0): baked=, which its
    soa.exe and libsoa_game.so will carry and a phone holds the library to,
    must be the commit's whatever the checkout did to line endings."""
    source = folder / "source"
    if not source.is_dir():
        print(f"error: {folder} holds no source/: not a package")
        return 1
    # R5b: a package's VERSION is the version its folder, and its zip, are
    # named for, since an Android library's record carries it as package=
    named = folder.name.removeprefix("soa-").removesuffix("-windows-x64")
    if named != folder.name and player_build.package_version(source) != named:
        print(
            f"{source}: VERSION says {player_build.package_version(source)!r}, "
            f"and the package is named for {named!r}"
        )
        return 1
    got, want = player_build.inputs_record(source), commit_inputs(rev)
    if got == want:
        a, b = seam.baked_digest(got), seam.baked_digest(want)
        print(f"baked inputs of {source}: {a[:12]}, and of {rev}: {b[:12]}, the same")
        return 0
    name = next(n for n in sorted(set(got) | set(want)) if got.get(n) != want.get(n))
    if name not in got:
        print(f"{source}: {name} is missing; the commit has it")
    elif name not in want:
        print(f"{source}: {name} is not in the commit")
    else:
        ours, theirs = (source / name).read_bytes(), git_blob(rev, name)
        hint = ""
        if ours.replace(b"\r", b"") == theirs.replace(b"\r", b""):
            hint = " (the checkout converted its line endings?)"
        print(f"{source}: {name} is not the commit's{hint}")
    return 1


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
    stage(staged, ver)
    zpath = out / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(staged.rglob("*")):
            if f.is_file():
                z.write(f, f"{name}/{f.relative_to(staged).as_posix()}")
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    # LF on every host: sha256sum -c takes a CR for part of the file's name
    (out / f"{name}.zip.sha256").write_bytes(f"{digest}  {zpath.name}\n".encode())
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
    c = sub.add_parser("check", help="a package's baked inputs against a commit's")
    c.add_argument("folder", type=Path)
    c.add_argument("--commit", default="HEAD", help="the commit it was made from (default HEAD)")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        return check(args.folder.resolve(), args.commit)
    if args.cmd == "stage":
        stage(args.dest.resolve(), args.version)
    elif args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        build_zip(args.out.resolve(), args.version or version())
    else:
        ap.error("stage <folder>, or --out <dir>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
