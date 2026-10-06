"""The APK, built, put on a device with a game library, and the port's checks
run there (specs/android.md 3.14, L12c).

    python tools/android.py build                      # the debug APK
    python tools/android.py install     --serial S
    python tools/android.py push-game   --serial S [<libsoa_game.so>]
    python tools/android.py push-corpus --serial S [build/fifo]
    python tools/android.py push-disc   --serial S [extracted/disc.iso]
    python tools/android.py selftest    --serial S
    python tools/android.py replay      --serial S [--threads 1,2,3,8]
    python tools/android.py run         --serial S [--env K=V ...] [--timeout s] [-- ARGS...]
    python tools/android.py logs        --serial S

build writes the runtime's side of the seam (config/seam.txt, as recompile.py
--split does) into android/app/src/main/cpp/generated/, fetches SDL's AAR
(tools/fetch_sdl.py --android) and Gradle 9.6.0 into vendor/, both pinned,
and runs Gradle: android/app/build/outputs/apk/debug/app-debug.apk.

Every other command needs the device named, by --serial or SOA_ADB_SERIAL,
never taken as the only one attached: another project's emulator may be the
only one. A check runs the app with its environment and arguments in the
intent (SoaActivity), waits for the process to end, and reads soa.log out of
the app's storage with run-as, the debug build's: the report the PC prints,
ending in "[exit] N" when main returned (runtime/android.c). push-game puts a
library where runtime/android.c looks for it, read-only, the one for the
device's ABI from gen/android-<abi>/ unless named; push-corpus the captures,
which are game data and go only to the owner's own devices. replay is
scenario.py replay's sweep, the manifest compared the same way, each replay a
launch of the app.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_sdl  # noqa: E402
import player_build  # noqa: E402
import recompile  # noqa: E402
import scenario  # noqa: E402
from soa import seam, toolchain  # noqa: E402
from soa.hle import load_hle  # noqa: E402

VENDOR = ROOT / "vendor"
PROJECT = ROOT / "android"
GENERATED = PROJECT / "app" / "src" / "main" / "cpp" / "generated"
APK = PROJECT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
PACKAGE = "io.github.bmfrench89.soa.dev"  # a working name until Q-A4 (D-33)
COMPONENT = f"{PACKAGE}/io.github.bmfrench89.soa.SoaActivity"
GRADLE_VERSION = "9.6.0"
GRADLE_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
GRADLE_PIN = "bbaeb2fef8710818cf0e261201dab964c572f92b942812df0c3620d62a529a01"
EXIT = re.compile(r"^\[exit\] (-?\d+)$", re.M)
ABIS = {"x86_64": toolchain.ANDROID_X86_64, "arm64-v8a": toolchain.ANDROID_ARM64}


class AndroidError(Exception):
    pass


# ---- building ------------------------------------------------------------


def seam_files(out: Path = GENERATED) -> None:
    """The runtime's side of the seam for the APK: always --no-decomp, and
    SDL_main exported for SDLActivity (specs/android.md 3.1)."""
    the_seam = seam.read_seam(ROOT / "config" / "seam.txt")
    bound = set(load_hle(ROOT / "config" / "hle.txt")) - recompile.decomp_bound()
    baked = seam.baked_digest(player_build.inputs_record(ROOT))
    out.mkdir(parents=True, exist_ok=True)
    (out / "runtime_seam.c").write_text(
        seam.runtime_seam_c(the_seam, bound, seam.record(True, baked)), encoding="utf-8"
    )
    (out / "runtime.map").write_text(
        seam.version_script(the_seam, bound, extra=("SDL_main",)), encoding="utf-8"
    )


def gradle(vendor: Path = VENDOR, get=None) -> Path:
    """Gradle, fetched once into vendor/ and its archive's sha256 checked."""
    home = vendor / f"gradle-{GRADLE_VERSION}"
    exe = home / "bin" / ("gradle.bat" if os.name == "nt" else "gradle")
    if exe.exists():
        return exe
    print(f"fetching {GRADLE_URL}")
    if get is None:
        with urllib.request.urlopen(GRADLE_URL, timeout=600) as r:  # noqa: S310 - a fixed https URL
            blob = r.read()
    else:
        blob = get(GRADLE_URL)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != GRADLE_PIN:
        raise AndroidError(f"{GRADLE_URL} has sha256 {digest}, not the pinned {GRADLE_PIN}")
    import io

    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(vendor)
    if os.name != "nt":
        exe.chmod(0o755)
    return exe


def sdk() -> Path:
    """The Android SDK: ANDROID_HOME, ANDROID_SDK_ROOT, or the NDK's parent's."""
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env) and Path(os.environ[env]).is_dir():
            return Path(os.environ[env])
    ndk = toolchain.android_ndk()
    if ndk and ndk.parent.name == "ndk":
        return ndk.parent.parent
    raise AndroidError(
        "no Android SDK: set ANDROID_HOME (Android Studio's SDK manager installs one)"
    )


def cmd_build(args: argparse.Namespace) -> int:
    seam_files()
    aar = fetch_sdl.fetch_android(VENDOR)
    print(f"SDL3 for Android: {aar.relative_to(ROOT)}")
    exe = gradle()
    env = dict(os.environ, ANDROID_HOME=str(sdk()))
    proc = subprocess.run(
        [str(exe), "-p", str(PROJECT), "--no-daemon", "assembleDebug"], env=env, check=False
    )
    if proc.returncode != 0:
        return proc.returncode
    print(f"built {APK.relative_to(ROOT)} ({APK.stat().st_size / 2**20:.1f} MiB)")
    return 0


# ---- the device ----------------------------------------------------------


def adb_path() -> str:
    exe = sdk() / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    if not exe.exists():
        raise AndroidError(f"no adb at {exe}")
    return str(exe)


def serial_of(args: argparse.Namespace) -> str:
    serial = args.serial or os.environ.get("SOA_ADB_SERIAL", "")
    if not serial:
        raise AndroidError(
            "name the device with --serial or SOA_ADB_SERIAL (adb devices lists them); "
            "never taken as the only one attached, which may be another project's"
        )
    return serial


def adb(
    serial: str, *cmd: str, timeout: int = 600, check: bool = True
) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [adb_path(), "-s", serial, *cmd],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise AndroidError(f"adb {' '.join(cmd)}: {(proc.stdout + proc.stderr).strip()[-400:]}")
    return proc


def run_as(serial: str, script: str, check: bool = True) -> subprocess.CompletedProcess:
    return adb(serial, "shell", f"run-as {PACKAGE} sh -c '{script}'", check=check)


def put(serial: str, local: Path, remote: str, mode: str = "0644") -> None:
    """A file into the app's own storage (files/<remote>), through /data/local/tmp."""
    tmp = "/data/local/tmp/soa-push"
    adb(serial, "push", str(local), tmp)
    folder = remote.rsplit("/", 1)[0] if "/" in remote else ""
    mkdir = f"mkdir -p files/{folder} && "  # files/ itself is made at the app's first run
    run_as(
        serial,
        f"{mkdir}rm -f files/{remote} && cp {tmp} files/{remote} && chmod {mode} files/{remote}",
    )
    adb(serial, "shell", f"rm -f {tmp}")


def device_abi(serial: str) -> str:
    return adb(serial, "shell", "getprop ro.product.cpu.abi").stdout.strip()


def cmd_install(args: argparse.Namespace) -> int:
    serial = serial_of(args)
    adb(serial, "install", "-r", str(APK))
    print(f"installed {APK.name} on {serial}")
    return 0


def cmd_push_game(args: argparse.Namespace) -> int:
    serial = serial_of(args)
    lib = Path(args.library) if args.library else None
    if lib is None:
        abi = device_abi(serial)
        if abi not in ABIS:
            raise AndroidError(f"{serial} is {abi}; this port builds for {', '.join(ABIS)}")
        lib = ROOT / ABIS[abi].out / seam.GAME_SONAME
    if not lib.exists():
        raise AndroidError(
            f"no {lib}: python tools/recompile.py --cc {ABIS.get(device_abi(serial)).name} --compile --link"
        )
    put(serial, lib, seam.GAME_SONAME, "0444")  # read-only, as Android 17 asks of loaded code
    print(f"pushed {lib} to {serial}'s files/{seam.GAME_SONAME}")
    return 0


def cmd_push_disc(args: argparse.Namespace) -> int:
    """The disc image where main.c looks by default, extracted/ under the data
    root: a check's stand-in for L12d's picker. Game data: the owner's own
    device only."""
    serial = serial_of(args)
    image = Path(args.image)
    if not image.is_file():
        raise AndroidError(f"no {image}: python tools/extract.py <your disc dump>")
    name = "GEAE8P.soadisc" if image.suffix == ".soadisc" else "disc.iso"
    put(serial, image, f"extracted/{name}", "0444")
    print(f"pushed {image} to {serial}'s files/extracted/{name}")
    return 0


def cmd_push_corpus(args: argparse.Namespace) -> int:
    serial = serial_of(args)
    folder = Path(args.fifo)
    captures, partial = scenario.find_captures(folder)
    for line in partial:
        print(f"[android] {line}")
    for base in captures:
        for ext in (".fifo", ".regs", ".ram"):
            put(serial, base.with_suffix(ext), f"fifo/{base.name}{ext}")
        print(f"pushed {base.name}")
    print(f"{len(captures)} capture(s) on {serial}: game data, on the owner's own device only")
    return 0


def launch(
    serial: str, env: dict[str, str], argv: list[str], timeout: int = 300
) -> tuple[int | None, str]:
    """One run of the app, from a stopped process: its exit status from the
    log's "[exit] N" (None when the run ended another way), and the log --
    as far as it got, when the run outlasts `timeout` and is stopped."""
    adb(serial, "shell", f"am force-stop {PACKAGE}")
    pairs = ";".join(f"{k}={v}" for k, v in env.items())
    cmd = ["shell", "am", "start", "-W", "-n", COMPONENT]
    if pairs:
        cmd += ["--es", "env", f"'{pairs}'"]
    if argv:
        cmd += ["--es", "args", f"'{' '.join(argv)}'"]
    adb(serial, *cmd)
    end = time.time() + timeout
    gone = 0
    while time.time() < end:
        # Gone twice in a row, half a second apart: one empty answer has come
        # while the run was still going (a replay's log was read with neither
        # its hash nor its [exit] line in it, under load, L12c), and an app
        # whose process is not yet named for its package answers the same.
        gone = (
            gone + 1
            if adb(serial, "shell", f"pidof {PACKAGE}", check=False).stdout.strip() == ""
            else 0
        )
        if gone == 2:
            break
        time.sleep(0.5)
    else:
        adb(serial, "shell", f"am force-stop {PACKAGE}")
        text = run_as(serial, "cat files/soa.log", check=False).stdout
        return None, f"{text}[android] the run did not end within {timeout} s, so it was stopped\n"
    text = run_as(serial, "cat files/soa.log", check=False).stdout
    m = EXIT.search(text)
    return (int(m.group(1)) if m else None), text


def parse_env(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        k, _, v = pair.partition("=")
        out[k] = v
    return out


def cmd_run(args: argparse.Namespace) -> int:
    code, text = launch(serial_of(args), parse_env(args.env), args.argv, args.timeout)
    sys.stdout.write(text)
    return code if code is not None else 1


def cmd_selftest(args: argparse.Namespace) -> int:
    code, text = launch(serial_of(args), {"SOA_SELFTEST": "1", "SOA_SETTINGS": "0"}, [])
    for line in text.splitlines():
        if line.startswith(("[selftest]", "[game]", "[exit]", "[boot]")):
            print(line)
    return code if code is not None else 1


def cmd_replay(args: argparse.Namespace) -> int:
    serial = serial_of(args)
    captures, partial = scenario.find_captures(ROOT / "build" / "fifo")
    for line in partial:
        print(f"[android] {line}")
    threads = tuple(int(t) for t in args.threads.split(","))

    def run(base: Path, t) -> tuple[int, str]:
        env = {"SOA_HASH": "1", "SOA_THREADS": str(t), "SOA_SETTINGS": "0"}
        code, text = launch(serial, env, ["--replay", f"fifo/{base.name}"])
        return (code if code is not None else 1), text

    first, problems = scenario.sweep(captures, threads, 1, run)
    rows = {
        base.name: (scenario.capture_key(base), first[base.name])
        for base in captures
        if base.name in first
    }
    lines, bad = scenario.compare_manifest(rows, scenario.read_manifest(scenario.MANIFEST))
    for line in lines:
        print(line)
    for p in problems:
        print(f"[android] {p}")
    if bad or problems:
        print(f"[android] FAILED -- {bad} capture(s) differ, {len(problems)} run(s) went wrong")
        return 1
    print(
        f"[android] {len(rows)} captures match {scenario.named(scenario.MANIFEST)} at SOA_THREADS {args.threads} on {serial}"
    )
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    sys.stdout.write(run_as(serial_of(args), "cat files/soa.log", check=False).stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    for name, fn in (("install", cmd_install), ("selftest", cmd_selftest), ("logs", cmd_logs)):
        p = sub.add_parser(name)
        p.add_argument("--serial")
        p.set_defaults(fn=fn)
    p = sub.add_parser("push-game")
    p.add_argument("--serial")
    p.add_argument("library", nargs="?")
    p.set_defaults(fn=cmd_push_game)
    p = sub.add_parser("push-disc")
    p.add_argument("--serial")
    p.add_argument("image", nargs="?", default=str(ROOT / "extracted" / "disc.iso"))
    p.set_defaults(fn=cmd_push_disc)
    p = sub.add_parser("push-corpus")
    p.add_argument("--serial")
    p.add_argument("fifo", nargs="?", default=str(ROOT / "build" / "fifo"))
    p.set_defaults(fn=cmd_push_corpus)
    p = sub.add_parser("replay")
    p.add_argument("--serial")
    p.add_argument("--threads", default="1,2,3,8")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("run")
    p.add_argument("--serial")
    p.add_argument("--env", action="append", help="K=V, repeatable")
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="seconds before the run is stopped (default 300; the x86-64 emulator runs about 9 frames a second)",
    )
    p.add_argument("argv", nargs="*")
    p.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (AndroidError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
