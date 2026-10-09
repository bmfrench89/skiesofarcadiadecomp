#!/usr/bin/env python3
"""Build the game into a folder from a disc image: what a player's setup runs.

    python tools/player_build.py --disc <image.rvz|iso|gcm> --root <folder>
        [--rebuild] [--target windows] [--target android-arm64] [--target android-x86_64]

specs/distribution.md R2, and R5 (specs/android-sysroot.md 6.1). One command,
from the player's own disc image to a folder that plays:

1. **The disc is checked before any work** (3.8): its game id must be GEAE8P
   and its executable's SHA-1 the one config/ describes, each refused by
   name; an image that is not a GameCube disc, and one this cannot check, are
   refused too.
2. **An Android target is checked next,** before anything is written: the
   package's Android files (bionic's pinned sources, or the sysroot built
   from them), its compiler, and the space. A refusal stops every target,
   Windows too. Then the sysroot is built from those sources when it is not
   there, offline (tools/fetch_android_sysroot.py; D-34).
3. **What the game reads is extracted** into <root>/extracted (the image the
   runtime reads, and sys/), as tools/extract.py does.
4. **Never a stale translation:** every input the translated C bakes in is
   hashed, with the package's version, the compiler and its flags, and for
   Android the sysroot, into <gen>/build-inputs.txt. When any differs from
   the last build's, the old translation is thrown away and the game is
   translated again, and the log says which input moved. --rebuild
   translates again whatever the record says: the setup window's Rebuild.
5. **Each target is built,** in the order given (windows when none is):
   recompile.py with the bundled compiler (llvm-mingw: SOA_MINGW, the
   package's toolchain/, or vendor/) and --no-decomp (no src/ in a package,
   3.1), on every core.
   - windows: into <root>/gen, --reproducible; soa.exe and the mods' mod.dll
     go to the top of <root>, and soa.ini is written unless one is there.
   - android-arm64, the phone's: into <root>/gen-android-arm64, against the
     sysroot; libsoa_game.so goes to the top of <root>.
   - android-x86_64, the emulator's: the same into gen-android-x86_64, as
     libsoa_game-x86_64.so. Setup never asks for it.

It prints one machine-readable line per step and translation unit --
`[build] check`, `[build] 7/19 chunk_006.c`, `[build] android 7/19
chunk_006.c` -- which the setup window (R4) reads, and ends each target with
`[build] done soa.exe sha256 <hex>` or `[build] android done libsoa_game.so
sha256 <hex>`. Exit status 0 when every target asked for was built, 1 when a
step failed (the log names the target; a failed Android check stops all of
them before any work), 2 when the disc was refused.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import toolchain  # noqa: E402
from soa.disc import IMAGE_NAME, Disc, ImageFile  # noqa: E402
from soa.dump import ProjectError, read_project  # noqa: E402
from soa.rvz import RVZ  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1]  # the repository, or a package's source/
GAME_ID = "GEAE8P"
REFUSED = 2

# Everything the translated C bakes in (CLAUDE.md, "Relink, or retranslate"):
# what the chunks include, the binding lists, and the translator itself.
BAKED = (
    "runtime/cpu.h",
    "config/hle.txt",
    "config/hooks.txt",
    "config/savepoints.txt",
    "config/trace.txt",
    "config/functions.tsv",
    "runtime/decomp_swap.c",
    "tools/recompile.py",
    "tools/soa/recomp",
    "tools/soa/ppc",
    "tools/soa/hle.py",
    "tools/soa/dol.py",
)

TARGETS = ("windows", "android-arm64", "android-x86_64")
# Where an Android target's library goes at the root's top: the phone's by the
# name its import asks for, the emulator's beside it.
LIBRARY = {"android-arm64": "libsoa_game.so", "android-x86_64": "libsoa_game-x86_64.so"}
MIB = 1 << 20
# The free space an Android target's translation needs beside the root (its
# gen folder and library, about twice over), and a relink's (the link's
# output and the stubs); a translation frees its old folder first.
ANDROID_FREE = 384 * MIB
RELINK_FREE = 64 * MIB


class Refused(Exception):
    """The disc is not one this package builds; the message names why."""


def say(what: str) -> None:
    print(f"[build] {what}", flush=True)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def open_image(path: Path):
    return RVZ(str(path)) if path.suffix.lower() == ".rvz" else ImageFile(path)


def check_disc(image: Path, game_id: str = GAME_ID, dol_sha1: str | None = None) -> None:
    """Refuse an image that is not this game's disc, by name (3.8). dol_sha1
    is config/'s when None; a config that cannot be read is a refusal too,
    never a warning: nothing after this looks at the executable again."""
    if dol_sha1 is None:
        try:
            dol_sha1 = read_project(SOURCE / "config" / "GEAE8P" / "config.yml").sha1
        except (ProjectError, OSError) as exc:
            raise Refused(f"cannot check the disc's executable: {exc}") from exc
    try:
        disc = Disc(open_image(image), source=str(image))
    except (ValueError, OSError, EOFError) as exc:
        raise Refused(f"{image.name} is not a GameCube disc image ({exc})") from exc
    with disc:
        found = disc.boot.game_id
        if found != game_id:
            raise Refused(
                f"this is not the North American GameCube release ({game_id}); "
                f'{image.name} is {found} "{disc.boot.title}"'
            )
        got = hashlib.sha1(disc.read_dol(), usedforsecurity=False).hexdigest()
    if got != dol_sha1:
        raise Refused(
            f"this disc's executable is not the one this package was made for "
            f"(sha1 {got}, wanted {dol_sha1})"
        )


def extract(image: Path, out: Path) -> None:
    """The image the runtime reads and sys/, as tools/extract.py writes them."""
    import extract as ex

    args = argparse.Namespace(image=image, out=out, files=False, iso=False, force=False)
    out.mkdir(parents=True, exist_ok=True)
    with Disc(open_image(image), source=str(image)) as disc:
        if ex.unpack(disc, args):
            raise RuntimeError("extraction failed")


def inputs_record(source: Path | None = None) -> dict[str, str]:
    """sha256 of every input the translation bakes in, by path: under SOURCE,
    read when called, not when this module was imported. Each is read with
    CRLF as LF, since a checkout's line endings are not the commit's: GitHub's
    Windows runner checks out with core.autocrlf on, and every soa.exe and
    libsoa_game.so carries the digest, which a phone holds the library to."""
    source = SOURCE if source is None else source
    out: dict[str, str] = {}
    for rel in BAKED:
        p = source / rel
        files = sorted(p.rglob("*.py")) if p.is_dir() else [p]
        for f in files:
            if f.exists():
                data = f.read_bytes().replace(b"\r\n", b"\n")
                out[f.relative_to(source).as_posix()] = hashlib.sha256(data).hexdigest()
    return out


def package_version(source: Path | None = None) -> str:
    """The package's version, which tools/package.py writes into
    source/VERSION; `checkout` in a clone, which has none."""
    source = SOURCE if source is None else source
    try:
        return (source / "VERSION").read_text(encoding="utf-8").strip() or "checkout"
    except OSError:
        return "checkout"


def packaged() -> bool:
    """Whether this runs from a player's package, whose words name no
    developer's command."""
    return package_version() != "checkout"


def profile_of(target: str) -> toolchain.Profile:
    return toolchain.MINGW if target == "windows" else toolchain.profile(target)


def identity(target: str) -> dict[str, str]:
    """What else a target's translation is made by (distribution 3.8): the
    package, the compiler and its declared flags, and for Android the
    sysroot. Merged into the record, so a change to any translates again."""
    import fetch_android_sysroot
    import recompile

    p = profile_of(target)
    out = {
        "package": sha256(package_version()),
        "compiler": sha256(toolchain.compiler_id(p)),
        "cflags": recompile.cflags_digest(p),
    }
    if toolchain.is_android(p):
        out["sysroot"] = fetch_android_sysroot.sysroot_digest(SOURCE / "vendor")
    return out


def read_record(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    rows = (ln.split("  ", 1) for ln in path.read_text(encoding="utf-8").splitlines() if ln)
    return {name: digest for digest, name in rows}


def stale(gen: Path, now: dict[str, str]) -> list[str]:
    """The inputs that moved since gen/ was translated; every one when there
    is no record, which is a translation never made or never finished."""
    before = read_record(gen / "build-inputs.txt")
    if not before:
        return ["no record of the last translation"]
    return sorted(k for k in set(now) | set(before) if now.get(k) != before.get(k))


def write_record(path: Path, rec: dict[str, str]) -> None:
    path.write_text("".join(f"{d}  {n}\n" for n, d in sorted(rec.items())), encoding="utf-8")


def _size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0


def _nearest(path: Path) -> Path:
    """The nearest folder of path that exists, path itself first: a root
    may not exist yet."""
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def android_preflight(root: Path, targets: list[str]) -> str | None:
    """Why the Android targets asked for cannot be built here, in words, or
    None; read-only, so a refusal comes in seconds with nothing written: the
    sysroot or the sources to build it from, the compiler, and the space."""
    import fetch_android_sysroot as fas

    android = [t for t in targets if t != "windows"]
    if not android:
        return None
    vendor = SOURCE / "vendor"
    try:
        if fas.verify(vendor):
            bad = fas.cache_problems(vendor / fas.CACHE)
            if bad:
                if packaged():
                    return (
                        f"this package's Android files are not as it shipped them "
                        f"({bad[0].split(': ', 1)[0]}): extract the package again, into a new folder"
                    )
                return f"vendor/{fas.CACHE}: {bad[0]}: python tools/fetch_android_sysroot.py fetches it"
        clang = toolchain.mingw_clang()
        if clang is None:
            if packaged():
                return (
                    "this package's compiler is missing (toolchain\\bin\\clang.exe): extract the package "
                    "again, into a new folder; if Windows Security removed it, Virus & threat protection > "
                    "Protection history shows it"
                )
            return "no llvm-mingw here: python tools/fetch_mingw.py fetches it"
        problem = toolchain.mingw_identity_problem(clang)
        if problem:
            if packaged():
                return (
                    f"this package's compiler is not the one it shipped with "
                    f"({toolchain.clang_id(clang) or 'it does not run'}): extract the package again, "
                    "into a new folder"
                )
            return f"{problem}: python tools/fetch_mingw.py fetches it"
        need = sum(max(ANDROID_FREE - _size(root / f"gen-{t}"), RELINK_FREE) for t in android)
        free = shutil.disk_usage(_nearest(root)).free
        if free < need:
            return (
                f"the Android build needs about {-(-need // MIB)} MB free in {root}, and there are "
                f"{free // MIB} MB: free some space and build again"
            )
    except OSError as exc:
        return f"the Android build could not check this folder or the package ({exc})"
    return None


def relay(cmd: list[str], prefix: str = "") -> tuple[int, list[str]]:
    """Run a tool of this folder, its [build] lines passed on with `prefix`
    after "[build] ", every other line indented: (its exit status, its lines)."""
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=SOURCE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        lines.append(line)
        if line.startswith("[build] "):
            print(f"[build] {prefix}{line[len('[build] ') :]}", flush=True)
        elif line:
            print(f"  {line}", flush=True)
    return proc.wait(), lines


def ensure_sysroot() -> str | None:
    """The sysroot, built from the package's own sources by its own clang,
    offline, when it is not there and as recorded: None, or why not."""
    import fetch_android_sysroot as fas

    if not fas.verify(SOURCE / "vendor"):
        return None
    say("android sysroot")
    tool = SOURCE / "tools" / "fetch_android_sysroot.py"
    code, lines = relay([sys.executable, str(tool), "--offline"])
    if code == 0:
        return None
    why = next((ln.removeprefix("error: ") for ln in lines if ln.startswith("error: ")), "")
    why = why or f"it stopped with exit status {code}"
    if packaged():
        return (
            f"the Android files could not be built here ({why}): extract the package again, into a "
            "new folder, and send build\\setup.log with any report"
        )
    return f"{why}: python tools/fetch_android_sysroot.py"


def build(root: Path, gen: Path, retranslate: bool, target: str = "windows") -> str:
    """recompile.py into gen/ for one target, its lines turned into [build]
    lines (`[build] android …` for Android): "" when it built, else why not."""
    windows = target == "windows"
    cmd = [sys.executable, str(SOURCE / "tools" / "recompile.py"), "--cc", profile_of(target).name]
    cmd += ["--no-decomp", *(["--reproducible"] if windows else [])]
    cmd += ["--progress", "--out", str(gen), "--link"]
    if retranslate:
        cmd += ["--compile", "--optimize"]
    # the disc whose system files are built in (disc-layer I3): the player's,
    # not the default's, which would be source/extracted
    cmd += [
        "--dol",
        str(root / "extracted" / "sys" / "main.dol"),
        "--disc",
        str(root / "extracted"),
    ]
    code, lines = relay(cmd, "" if windows else "android ")
    if code == 0:
        return ""
    failed = [ln.split()[1].rstrip(":") for ln in lines if ln.lstrip().startswith("FAIL ")]
    units = [f for f in failed if f.endswith(".c")]
    if units:
        return f"the compile of {units[0]} failed; the lines above say why"
    steps = [ln[len("[build] ") :] for ln in lines if ln.startswith("[build] ")]
    step = steps[-1] if steps else "the build"
    return f"{step} failed (exit status {code}); the lines above say why"


def install(root: Path, gen: Path) -> str:
    """soa.exe and the mods at the top of root; soa.ini when there is none.
    The answer is the exe's sha256."""
    exe = root / "soa.exe"
    shutil.copyfile(gen / "soa.exe", exe)
    mods = gen / "mods"
    if mods.is_dir():
        for folder in sorted(p for p in mods.iterdir() if p.is_dir()):
            dest = root / "mods" / folder.name
            dest.mkdir(parents=True, exist_ok=True)
            for f in folder.iterdir():
                if f.suffix in (".dll", ".ini", ".txt"):
                    shutil.copyfile(f, dest / f.name)
    ini = root / "soa.ini"
    if not ini.exists():
        ini.write_text(
            "# written by tools/player_build.py; an environment variable overrides each key\n"
            "disc = extracted\nrender = 1\ngpu = vulkan\nmods = mods\n",
            encoding="utf-8",
        )
    return hashlib.sha256(exe.read_bytes()).hexdigest()


def install_android(root: Path, gen: Path, target: str) -> str:
    """The game library at the top of root, under LIBRARY's name; recompile
    has run the phone's own check on it. The answer is its sha256."""
    lib = root / LIBRARY[target]
    shutil.copyfile(gen / "libsoa_game.so", lib)
    return hashlib.sha256(lib.read_bytes()).hexdigest()


def build_target(root: Path, target: str, rebuild: bool) -> int:
    """One target: translated again when its record moved, then linked and
    installed. 0 when it was built, 1 when not."""
    windows = target == "windows"
    pre = "" if windows else "android "
    gen = root / ("gen" if windows else f"gen-{target}")
    now = {**inputs_record(), **identity(target)}
    moved = ["Rebuild asked for"] if rebuild else stale(gen, now)
    retranslate = bool(moved)
    if retranslate:
        say(f"{pre}translate: {', '.join(moved[:4])}{' and more' if len(moved) > 4 else ''}")
        if gen.exists():
            shutil.rmtree(gen)
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "build-inputs.txt").unlink(missing_ok=True)
    why = build(root, gen, retranslate, target)
    if why:
        say("failed" if windows else f"android failed: {why}")
        return 1
    write_record(gen / "build-inputs.txt", now)
    if windows:
        say(f"done soa.exe sha256 {install(root, gen)}")
    else:
        say(f"android done {LIBRARY[target]} sha256 {install_android(root, gen, target)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--disc", type=Path, required=True, help="the player's disc image")
    ap.add_argument("--root", type=Path, required=True, help="the folder to build into")
    ap.add_argument(
        "--rebuild", action="store_true", help="translate again from scratch (Setup's Rebuild)"
    )
    ap.add_argument(
        "--target",
        action="append",
        choices=TARGETS,
        help="what to build, once each, in the order given (default windows)",
    )
    args = ap.parse_args(argv)
    root = args.root.resolve()
    targets = list(dict.fromkeys(args.target or ["windows"]))

    say("check")
    try:
        check_disc(args.disc)
    except Refused as exc:
        say(f"refused: {exc}")
        return REFUSED
    if any(t != "windows" for t in targets):
        why = android_preflight(root, targets) or ensure_sysroot()
        if why:
            say(f"android failed: {why}")
            return 1
    say("extract")
    extracted = root / "extracted"
    if not (extracted / IMAGE_NAME).exists():
        extract(args.disc, extracted)
    for target in targets:
        if build_target(root, target, args.rebuild):
            return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
