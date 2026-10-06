"""Fetch SDL3 and build it for this host into vendor/sdl3, which is gitignored.

    python tools/fetch_sdl.py            # fetch the source, build it, record
    python tools/fetch_sdl.py --verify   # check what is on disk against the record
    python tools/fetch_sdl.py --console  # no window system: compile checks only
    python tools/fetch_sdl.py --headers  # the source alone, no build: compiling against it, any host (CI)
    python tools/fetch_sdl.py --android  # SDL's own Android build, its AAR, for the APK (any host)

specs/portability.md L10, G2 (SDL3: yes): off Windows, the window, the pads
and the sound come from SDL3, fetched at a pinned release and never
committed. Windows keeps its Win32 window (D2), so this is for Linux, and at
L12 Android. One thing comes down: SDL3-3.4.18.tar.gz, the release's source,
whose sha256 is pinned here; a different one is refused. It is built with
CMake into a static library under vendor/sdl3/<system>-<machine>, so
gen/linux/soa needs no libSDL3.so beside it: SDL itself loads X11 or Wayland,
and PipeWire, PulseAudio or ALSA, when it runs, from whatever the system has.

The build needs CMake, a C compiler, and the development headers of a window
system. Without them SDL's own configure stops, and this names the packages
(SDL's docs/README-linux.md has every distribution's list). --console builds
SDL with no window system (SDL_UNIX_CONSOLE_BUILD): enough to compile and link
the window against, never to open one. recompile.py's --link builds the
window and the sound in whenever vendor/sdl3 holds this host's build.
--headers stops after unpacking the pinned source, whose include/ is all
tools/citest/compile_runtime.py needs to compile window_sdl.c and
audio_sdl.c as the backend they are, on any host and with no CMake.

--android fetches the same release's SDL3-devel-3.4.18-android.zip, its
sha256 pinned, and keeps the AAR inside it -- libSDL3.so for every Android ABI,
16 KB-aligned and built by SDL for NDK 28, with SDLActivity -- in
vendor/sdl3/android, for the APK's Gradle build (specs/android.md 3.5, L12c).

vendor/SDL.sha256 records the sha256 of every installed file, as GPU.sha256
does for fetch_gpu.py, with the source as a comment and which video and audio
drivers the build has; --verify reports any file missing or changed. Nothing
here touches game data.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = "SDL.sha256"
VERSION = "3.4.18"
URL = f"https://github.com/libsdl-org/SDL/releases/download/release-{VERSION}/SDL3-{VERSION}.tar.gz"
PIN = "9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3"
# SDL's own Android build of the same release (specs/android.md 3.5).
ANDROID_URL = f"https://github.com/libsdl-org/SDL/releases/download/release-{VERSION}/SDL3-devel-{VERSION}-android.zip"
ANDROID_PIN = "e09e4d6593335d089ba124375e8b8abd0fd75173dffcd2c17012b45af121d4e9"
ANDROID_AAR = f"SDL3-{VERSION}.aar"
# What a window and sound need on Debian and Ubuntu: X11 and Wayland, the
# three sound servers, udev for pads plugged in while running. SDL's
# docs/README-linux.md has the full list for every distribution.
DEBIAN = (
    "cmake libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxfixes-dev libxi-dev "
    "libxss-dev libxtst-dev libxkbcommon-dev libwayland-dev libdecor-0-dev libegl-dev "
    "libgl-dev libasound2-dev libpulse-dev libpipewire-0.3-dev libudev-dev libdbus-1-dev"
)
# A video driver that puts a window on a desktop; offscreen and dummy do not.
DESKTOP_VIDEO = ("x11", "wayland")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def host_name() -> str:
    """vendor/sdl3's folder for this host: linux-x86_64, linux-aarch64."""
    machine = platform.machine().lower()
    return f"{platform.system().lower()}-{'x86_64' if machine == 'amd64' else machine}"


def host_dir(vendor: Path) -> Path:
    return vendor / "sdl3" / host_name()


def headers(vendor: Path) -> Path:
    """The pinned source's include/, which holds SDL3/SDL.h once fetched."""
    return vendor / "sdl3" / f"SDL3-{VERSION}" / "include"


def available(vendor: Path) -> bool:
    """This host's SDL3 is built and installed under vendor/sdl3."""
    h = host_dir(vendor)
    return (h / "include" / "SDL3" / "SDL.h").exists() and (h / "lib" / "libSDL3.a").exists()


def pc_libs(text: str) -> list[str]:
    """What a static libSDL3.a needs after it on a link line: the -l and
    -pthread flags of sdl3.pc, other than SDL3's own -- on Libs: in a
    static-only build, Libs.private: where SDL also built a shared library
    (3.4.18 on glibc: -pthread -lm)."""
    libs: list[str] = []
    for line in text.splitlines():
        if line.startswith(("Libs:", "Libs.private:")):
            for w in line.split(":", 1)[1].split():
                if w.startswith(("-l", "-pthread")) and w != "-lSDL3" and w not in libs:
                    libs.append(w)
    return libs


def link_args(vendor: Path) -> tuple[list[str], list[str]]:
    """(the compile's flags, what goes after the objects) for a runtime built
    with SDL3: SOA_SDL=1 and the headers, then the library and its needs."""
    h = host_dir(vendor)
    pc = h / "lib" / "pkgconfig" / "sdl3.pc"
    libs = pc_libs(pc.read_text(encoding="utf-8")) if pc.exists() else ["-lm", "-pthread"]
    return ["/DSOA_SDL=1", f"/I{h / 'include'}"], [str(h / "lib" / "libSDL3.a"), *libs]


# A driver's name has no underscore; SDL_VIDEO_DRIVER_X11_XRANDR and the like
# are a driver's features, and the _DYNAMIC ones name a library, not 1.
_DRIVER = re.compile(r"^#define SDL_(VIDEO|AUDIO)_DRIVER_([A-Z0-9]+) 1\s*$", re.M)


def drivers(config_text: str) -> dict[str, list[str]]:
    """The video and audio drivers an SDL_build_config.h says were built."""
    found: dict[str, list[str]] = {"video": [], "audio": []}
    for kind, name in _DRIVER.findall(config_text):
        found[kind.lower()].append(name.lower())
    return found


def read_record(path: Path) -> tuple[dict[str, str], list[str]]:
    """(relative path -> sha256, the comment lines)."""
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


def write_record(path: Path, files: dict[str, str], comments: list[str]) -> None:
    lines = [
        "# SDL3 for the window and sound off Windows (tools/fetch_sdl.py, portability L10).",
        *comments,
    ]
    lines += [f"{d}  {n}" for n, d in sorted(files.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(vendor: Path) -> list[str]:
    """Every recorded file of this host's build that is missing or changed."""
    files, _ = read_record(vendor / RECORD)
    prefix = f"sdl3/{host_name()}/"
    mine = {n: d for n, d in files.items() if n.startswith(prefix)}
    if not mine:
        return [f"no {host_name()} build in {vendor / RECORD}: run tools/fetch_sdl.py first"]
    bad = []
    for name, digest in sorted(mine.items()):
        p = vendor / name
        if not p.exists():
            bad.append(f"{name}: recorded but missing")
        elif sha256(p.read_bytes()) != digest:
            bad.append(f"{name}: sha256 differs from the record")
    return bad


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=300) as r:  # noqa: S310 - a fixed https URL
        return r.read()


def unpack(blob: bytes, dest: Path) -> Path:
    """The archive into dest; its one top-level folder, SDL3-<version>."""
    import io

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
        t.extractall(dest, filter="data")
    return dest / f"SDL3-{VERSION}"


def source(vendor: Path, get=None) -> Path:
    """The pinned source under vendor/sdl3, fetched and unpacked when it is
    not there; ValueError when what came down is not the pinned archive."""
    src = vendor / "sdl3" / f"SDL3-{VERSION}"
    if (src / "CMakeLists.txt").exists():
        return src
    blob = (get or fetch)(URL)
    digest = sha256(blob)
    if digest != PIN:
        raise ValueError(f"{URL} has sha256 {digest}, not the pinned {PIN}")
    (vendor / "sdl3").mkdir(parents=True, exist_ok=True)
    return unpack(blob, vendor / "sdl3")


def android_aar(vendor: Path) -> Path:
    """Where --android keeps SDL's AAR."""
    return vendor / "sdl3" / "android" / ANDROID_AAR


def fetch_android(vendor: Path, get=None) -> Path:
    """SDL's AAR from the pinned devel archive into vendor/sdl3/android,
    recorded; ValueError when the archive is not the pinned one or holds no
    AAR. Fetched again only when missing or not as recorded."""
    import io
    import zipfile

    aar = android_aar(vendor)
    files, comments = read_record(vendor / RECORD)
    rel = aar.relative_to(vendor).as_posix()
    if aar.exists() and files.get(rel) == sha256(aar.read_bytes()):
        return aar
    blob = (get or fetch)(ANDROID_URL)
    digest = sha256(blob)
    if digest != ANDROID_PIN:
        raise ValueError(f"{ANDROID_URL} has sha256 {digest}, not the pinned {ANDROID_PIN}")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == ANDROID_AAR), None)
        if name is None:
            raise ValueError(f"{ANDROID_URL} holds no {ANDROID_AAR}")
        aar.parent.mkdir(parents=True, exist_ok=True)
        aar.write_bytes(z.read(name))
    files[rel] = sha256(aar.read_bytes())
    comments = [c for c in comments if "sdl3 android" not in c]
    comments.append(f"# sdl3 android: {ANDROID_URL} (sha256 {ANDROID_PIN}, pinned)")
    write_record(vendor / RECORD, files, comments)
    return aar


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    print("  " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--vendor", type=Path, default=ROOT / "vendor")
    ap.add_argument(
        "--verify", action="store_true", help="only check what is on disk against the record"
    )
    ap.add_argument(
        "--console",
        action="store_true",
        help="build SDL with no window system (SDL_UNIX_CONSOLE_BUILD): compile checks, never a window",
    )
    ap.add_argument(
        "--headers",
        action="store_true",
        help="fetch and unpack the pinned source only, for compiling against it (any host, no CMake)",
    )
    ap.add_argument(
        "--android",
        action="store_true",
        help="fetch SDL's own Android build (its AAR) for the APK, pinned, on any host",
    )
    args = ap.parse_args(argv)
    vendor = args.vendor

    if args.android:
        try:
            aar = fetch_android(vendor)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"SDL3 {VERSION} for Android: {aar} (from the devel archive, sha256 pinned)")
        return 0

    if args.headers:
        try:
            src = source(vendor)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"SDL3 {VERSION}'s headers: {headers(vendor)} (from {src.name}, sha256 pinned)")
        return 0

    if args.verify:
        bad = verify(vendor)
        for line in bad:
            print(line, file=sys.stderr)
        files, _ = read_record(vendor / RECORD)
        mine = [n for n in files if n.startswith(f"sdl3/{host_name()}/")]
        print(
            f"{len(mine) - len(bad) if mine else 0} of {len(mine)} recorded SDL3 file(s) unchanged"
        )
        return 1 if bad else 0

    if platform.system() == "Windows":
        print(
            "error: Windows keeps its own window and waveOut (D2); SDL3 is for Linux, and at L12 Android",
            file=sys.stderr,
        )
        return 1
    cmake = shutil.which("cmake")
    if not cmake:
        print(
            f"error: SDL3 builds with CMake, and there is none here. On Debian or Ubuntu: sudo apt install {DEBIAN}",
            file=sys.stderr,
        )
        return 1

    work = vendor / "sdl3"
    try:
        src = source(vendor)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    prefix = host_dir(vendor)
    build = work / f"build-{host_name()}"
    if build.exists():
        shutil.rmtree(build)
    if prefix.exists():
        shutil.rmtree(prefix)
    configure = [
        cmake,
        "-S",
        str(src),
        "-B",
        str(build),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DSDL_SHARED=OFF",
        "-DSDL_STATIC=ON",
        "-DSDL_TEST_LIBRARY=OFF",
        "-DSDL_TESTS=OFF",
        "-DSDL_EXAMPLES=OFF",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
        *(["-DSDL_UNIX_CONSOLE_BUILD=ON"] if args.console else []),
    ]
    proc = run(configure)
    if proc.returncode != 0:
        tail = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()][-12:]
        print("\n".join(tail), file=sys.stderr)
        print(
            f"\nerror: SDL3's configure stopped. A window needs X11 or Wayland's development headers; "
            f"on Debian or Ubuntu: sudo apt install {DEBIAN}\n(SDL's {src.name}/docs/README-linux.md "
            "lists every distribution's; --console builds without a window system, for compile checks)",
            file=sys.stderr,
        )
        return 1
    jobs = str(os.cpu_count() or 2)
    for step in (
        [cmake, "--build", str(build), "--parallel", jobs],
        [cmake, "--install", str(build)],
    ):
        proc = run(step)
        if proc.returncode != 0:
            print((proc.stdout + proc.stderr)[-3000:], file=sys.stderr)
            return 1

    config = next(build.rglob("SDL_build_config.h"), None)
    found = drivers(config.read_text(encoding="utf-8")) if config else {"video": [], "audio": []}
    desktop = [v for v in found["video"] if v in DESKTOP_VIDEO]
    print(
        f"SDL3 {VERSION}: video {', '.join(found['video']) or 'none'}; audio {', '.join(found['audio']) or 'none'}"
    )
    if not desktop and not args.console:
        print(
            f"error: the build has no X11 or Wayland, so no window could open; sudo apt install {DEBIAN}",
            file=sys.stderr,
        )
        return 1

    files, comments = read_record(vendor / RECORD)
    stale = f"sdl3/{host_name()}/"
    files = {n: d for n, d in files.items() if not n.startswith(stale)}
    for p in sorted(prefix.rglob("*")):
        if p.is_file() and "cmake" not in p.relative_to(prefix).parts:
            files[p.relative_to(vendor).as_posix()] = sha256(p.read_bytes())
    comments = [c for c in comments if host_name() not in c and "sdl3 source" not in c]
    comments.append(f"# sdl3 source: {URL} (sha256 {PIN}, pinned)")
    comments.append(
        f"# {host_name()}: video {', '.join(found['video']) or 'none'}; audio {', '.join(found['audio']) or 'none'}"
        + ("; a console build, no window system" if args.console else "")
    )
    write_record(vendor / RECORD, files, comments)
    shutil.rmtree(build)
    print(f"built into {prefix}; recorded {len(files)} file(s) in {vendor / RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
