"""The APK, built, put on a device with a game library, and the port's checks
run there (specs/android.md 3.14, L12c), the import's among them (L12d).

    python tools/android.py build                      # the debug APK
    python tools/android.py install     --serial S
    python tools/android.py push-game   --serial S [<libsoa_game.so>]
    python tools/android.py push-corpus --serial S [build/fifo]
    python tools/android.py push-disc   --serial S [extracted/disc.iso]
    python tools/android.py provide     --serial S FILE [--as NAME]
    python tools/android.py stage       --serial S FILE [--as NAME]
    python tools/android.py mutants     [--profile P] [--out DIR] [--push --serial S]
    python tools/android.py selftest    --serial S
    python tools/android.py replay      --serial S [--threads 1,2,3,8]
    python tools/android.py run         --serial S [--env K=V ...] [--pick URI ...]
                                        [--tap TEXT] [--key KEYCODE] [--font-scale X] ...
                                        [--kill-before-tap] [--timeout s] [-- ARGS...]
    python tools/android.py player      --serial S [--tap TEXT] [--key KEYCODE] ...
                                        [--font-scale X] [--reimport] [--fresh] [--out DIR]
    python tools/android.py reboot      --serial S
    python tools/android.py grants      --serial S
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
library where runtime/android.c looks for it, no_backup/libsoa_game.so,
read-only, the one for the device's ABI from gen/android-<abi>/ unless named;
push-corpus the captures, which are game data and go only to the owner's own
devices. replay is scenario.py replay's sweep, the manifest compared the same
way, each replay a launch of the app.

The import (L12d) is checked through the debug build's own document provider
and through the system's file picker. provide puts a file where that provider
serves it, content://<package>.testfiles/file/NAME as a file and .../pipe/NAME
through a pipe; stage puts one in the shared Download folder, where the
picker opens, once df says there is room. mutants builds the libraries the
import must refuse (tools/soa/gamefixture.py) against the record the APK was
built with and the executable it plays, and prints the line each must draw.
run --pick answers the app's picks without the picker; --tap and --key drive
the picker while the run is live, from uiautomator's dump of the screen.
player is the player's path: no check extras, the boxes and the picker tapped
by their texts, each step's screen captured. reboot restarts the AVD
soa_x86_64 and no other device, for the grant that must outlive it; grants
lists the URI grants the app holds.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_sdl  # noqa: E402
import player_build  # noqa: E402
import recompile  # noqa: E402
import scenario  # noqa: E402
from soa import dump, seam, toolchain  # noqa: E402
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
TESTFILES = f"{PACKAGE}.testfiles"  # the debug build's own provider (android/app/src/debug)
DOWNLOAD = "/sdcard/Download"  # where the picker opens (SoaActivity's EXTRA_INITIAL_URI)
MARGIN = 512 << 20  # room kept beside a staged file, as the import keeps beside a copy
AVD = "soa_x86_64"  # the port's own emulator: the one device reboot restarts
UI_DUMP = "/data/local/tmp/soa-ui.xml"
SCREENCAP = "/data/local/tmp/soa-cap.png"
# What a first run finds of an import (runtime/android.c): nothing, and no soa.ini.
FRESH = (
    "files/libsoa_game.so",
    "files/soa.ini",
    "no_backup/libsoa_game.so",
    "no_backup/libsoa_game.so.tmp",
    "no_backup/libsoa_game.so.old",
    "no_backup/disc.txt",
    "no_backup/pending_library",
    "no_backup/pending_disc",
    "no_backup/copy",
)


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


def put(serial: str, local: Path, remote: str, mode: str = "0644", base: str = "files") -> None:
    """A file into the app's own storage, <base>/<remote>, through
    /data/local/tmp: files/ (SOA_ROOT: the logs, the card, the debug
    provider's files) or no_backup/ (SOA_NOBACKUP: the imported library, the
    disc's record and its copy), which neither a backup nor a move to a new
    phone takes."""
    if base not in ("files", "no_backup"):
        raise AndroidError(f"{base}/ is not one of the app's folders: files or no_backup")
    tmp = "/data/local/tmp/soa-push"
    adb(serial, "push", str(local), tmp)
    folder = remote.rsplit("/", 1)[0] if "/" in remote else ""
    # made here when missing: no_backup/ exists only once the app has asked for it
    mkdir = f"mkdir -p {base}/{folder} && "
    path = f"{base}/{remote}"
    run_as(serial, f"{mkdir}rm -f {path} && cp {tmp} {path} && chmod {mode} {path}")
    adb(serial, "shell", f"rm -f {tmp}")
    # Held to its size: a push that ran out of room has left a short copy and
    # no error before (L12d's ISO, 1226858496 of 1459978240 bytes), which the
    # next run took for a truncated dump.
    got = run_as(serial, f"stat -c %s {path}", check=False).stdout.strip()
    want = local.stat().st_size
    if got != str(want):
        size = f"{got} bytes" if got.isdigit() else "a size stat could not read"
        raise AndroidError(
            f"{path} on {serial} is {size}, not {want} bytes: did the device run out of room? A push needs "
            "the file's size free twice, in /data/local/tmp and then in the app's storage"
        )


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
    # read-only, as Android 17 asks of loaded code; where an import puts it (L12d)
    put(serial, lib, seam.GAME_SONAME, "0444", base="no_backup")
    print(f"pushed {lib} to {serial}'s no_backup/{seam.GAME_SONAME}")
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


# ---- files for the import (L12d) -------------------------------------------


def file_name(name: str) -> str:
    """A name for a file put on the device. It goes into a shell command and
    a URI unquoted, so it is letters, digits, '.', '_' and '-' alone."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise AndroidError(
            f"{name!r} is not a plain file name (letters, digits, '.', '_' and '-'): name it with --as"
        )
    return name


def provided(name: str, how: str = "file") -> str:
    """The debug provider's URI for files/provider/<name>: `file` hands out a
    file's own descriptor, `pipe` the same bytes through a pipe."""
    return f"content://{TESTFILES}/{how}/{name}"


def pick_uri(value: str) -> str:
    """One --pick: a content:// URI, or file/NAME or pipe/NAME (?truncate=N
    after it, if wanted) for the debug provider's. Never a ';', which
    separates the picks in their extra, nor a quote or a space, which the
    device's shell would read."""
    if value.startswith(("file/", "pipe/")):
        value = f"content://{TESTFILES}/{value}"
    if not value.startswith("content://") or re.search(r"[;'\"\s]", value):
        raise AndroidError(f"--pick {value!r}: a content:// URI with no ';', quote or space")
    return value


def free_bytes(serial: str, path: str) -> int:
    """What df says is available on the file system that holds `path`."""
    out = adb(serial, "shell", f"df -k {path}").stdout
    rows = [line.split() for line in out.splitlines() if line.strip()]
    try:
        return int(rows[-1][-3]) * 1024
    except IndexError, ValueError:
        raise AndroidError(f"df -k {path} on {serial} said {out.strip()!r}") from None


def cmd_provide(args: argparse.Namespace) -> int:
    """A file where the debug build's provider serves it, files/provider/, for
    run --pick file/NAME or pipe/NAME: no picker and no grant, since only the
    app itself may open that provider."""
    serial = serial_of(args)
    src = Path(args.file)
    if not src.is_file():
        raise AndroidError(f"no {src}")
    name = file_name(args.name or src.name)
    put(serial, src, f"provider/{name}")
    print(f"provided {src} on {serial} as {provided(name)} and {provided(name, 'pipe')}")
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    """A file in the shared Download folder, where the system's picker opens:
    the player's way in, picked with run --tap NAME or player. Pushed whole
    and straight there, once df says both the shared storage and the app's
    have room for it and 512 MiB more."""
    serial = serial_of(args)
    src = Path(args.file)
    if not src.is_file():
        raise AndroidError(f"no {src}")
    name = file_name(args.name or src.name)
    need = src.stat().st_size
    for where in ("/sdcard", "/data"):
        free = free_bytes(serial, where)
        if free < need + MARGIN:
            raise AndroidError(
                f"{where} on {serial} has {free / 2**20:,.0f} MiB free, and {name} needs "
                f"{need / 2**20:,.0f} MiB with 512 MiB to spare: free some first (L12c's "
                "files/extracted/disc.iso is 1.4 GB, and push-disc puts it back)"
            )
    adb(serial, "push", str(src), f"{DOWNLOAD}/{name}", timeout=3600)
    print(f"staged {src} on {serial} as {DOWNLOAD}/{name}")
    return 0


RUNTIME_RECORD = re.compile(r'soa_runtime_record\[\]\s*=\s*"((?:[^"\\]|\\.)*)"')


def apk_record(seam_c: Path | None = None) -> str:
    """The record the APK's runtime holds a game library's to: the one build
    wrote into generated/runtime_seam.c and Gradle compiled, not this tree's,
    which may have moved on since."""
    seam_c = seam_c or GENERATED / "runtime_seam.c"
    if not seam_c.is_file():
        raise AndroidError(
            f"no {seam_c}: python tools/android.py build writes it, and builds the APK from it"
        )
    m = RUNTIME_RECORD.search(seam_c.read_text(encoding="utf-8"))
    if not m:
        raise AndroidError(f"{seam_c} has no soa_runtime_record")
    return re.sub(r"\\(.)", r"\1", m.group(1))


def apk_dol() -> str:
    """The executable the APK plays: config.yml's SHA-1, read as
    tools/checkdump.py reads it."""
    try:
        return dump.read_project(dump.DEFAULT_CONFIG).sha1
    except dump.ProjectError as exc:
        raise AndroidError(str(exc)) from None


def cmd_mutants(args: argparse.Namespace) -> int:
    """The libraries the import must refuse, each wrong in one way, built
    against the APK's record and the executable it plays, with the line each
    must draw on the device; --push provides them all, for run --pick
    file/<name>.so. For the device's ABI when pushed, else --profile's,
    else the x86-64 emulator's."""
    from soa import (
        gamefixture,
    )  # llvm-mingw's and the sysroot's builder: only this command needs it

    serial = serial_of(args) if args.push else ""
    profile = args.profile
    if serial:
        abi = device_abi(serial)
        if abi not in ABIS:
            raise AndroidError(f"{serial} is {abi}; this port builds for {', '.join(ABIS)}")
        if profile and profile != ABIS[abi].name:
            raise AndroidError(f"{serial} is {abi}, and --profile {profile} is another's")
        profile = ABIS[abi].name
    record, dol = apk_record(), apk_dol()
    try:
        made = gamefixture.android_mutants(
            Path(args.out), profile or toolchain.ANDROID_X86_64.name, record, dol
        )
    except (
        RuntimeError
    ) as exc:  # no llvm-mingw or sysroot, a compile that failed, or a mutant the phone would take
        raise AndroidError(f"the mutants could not be made: {exc}") from None
    for lib, words in made.values():
        print(f"{lib}\n  [import] refused {lib.name}: {words}")
    if serial:
        for lib, _ in made.values():
            put(serial, lib, f"provider/{file_name(lib.name)}")
        print(f"[android] {len(made)} provided on {serial}, each as {provided('<name>.so')}")
    return 0


# ---- the screen ------------------------------------------------------------


class Stuck(AndroidError):
    """What a step waits for never showed within the run's time."""


class Ended(Exception):
    """The app's process went away while a step waited for the screen: what
    it waited for, and (once drive() has said) the steps never done."""

    def __init__(self, what: str):
        super().__init__(what)
        self.what, self.left = what, []


BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def say(text: str) -> None:
    """Progress while a run is live, kept out of the log the run prints."""
    print(f"[android] {text}", file=sys.stderr, flush=True)


def ui_nodes(text: str) -> list[dict[str, str]]:
    """Every node of a uiautomator dump, its attributes, in the dump's order;
    none when the text holds no whole dump (uiautomator fails while the
    screen is animating, and is asked again)."""
    start, stop = text.find("<hierarchy"), text.rfind("</hierarchy>")
    if start < 0 or stop < 0:
        return []
    try:
        root = ET.fromstring(text[start : stop + len("</hierarchy>")])
    except ET.ParseError:
        return []
    return [dict(node.attrib) for node in root.iter("node")]


def screen(serial: str) -> list[dict[str, str]]:
    """What is on the device's screen now, dumped afresh (ui_nodes)."""
    try:
        out = adb(
            serial,
            "shell",
            f"rm -f {UI_DUMP}; uiautomator dump {UI_DUMP} >/dev/null 2>&1; cat {UI_DUMP}",
            timeout=60,
            check=False,
        ).stdout
    except subprocess.TimeoutExpired:
        return []
    return ui_nodes(out)


def area(node: dict[str, str]) -> tuple[int, int, int, int] | None:
    m = BOUNDS.fullmatch(node.get("bounds", ""))
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1, y1, x2, y2) if x2 > x1 and y2 > y1 else None


def find(nodes: list[dict[str, str]], text: str) -> dict[str, str] | None:
    """The node showing `text`, the first with an area on screen: its text
    exactly, else ignoring case (a button may draw its label in capitals,
    and the dump gives what is drawn), else its description. Never part of
    a longer text: a box's message may name the buttons under it."""
    want = text.casefold()
    for match in (
        lambda n: n.get("text") == text,
        lambda n: n.get("text", "").casefold() == want,
        lambda n: n.get("content-desc", "").casefold() == want,
    ):
        for node in nodes:
            if match(node) and area(node):
                return node
    return None


def centre(node: dict[str, str]) -> tuple[int, int]:
    x1, y1, x2, y2 = area(node)
    return (x1 + x2) // 2, (y1 + y2) // 2


def picker_up(nodes: list[dict[str, str]]) -> dict[str, str] | None:
    """The system's file picker's first node, when it is on screen:
    DocumentsUI, Google's (com.google.android.documentsui) or AOSP's."""
    return next((n for n in nodes if n.get("package", "").endswith(".documentsui")), None)


def shown(nodes: list[dict[str, str]]) -> str:
    texts = [t for t in dict.fromkeys(n.get("text") or n.get("content-desc") for n in nodes) if t]
    return " | ".join(texts[:12]) or "nothing uiautomator could read"


def signature(nodes: list[dict[str, str]]) -> tuple:
    """What a screen shows, as far as a step tells one screen from the next."""
    keys = ("text", "content-desc", "bounds", "focused", "selected")
    return tuple(tuple(n.get(k, "") for k in keys) for n in nodes)


SETTLE = 10  # seconds a step waits for its tap or key to change the screen
BACK_TRIES = 4  # Backs a --key KEYCODE_BACK may take to leave the picker (drive)


def settle(serial: str, before: list[dict[str, str]], end: float) -> None:
    """Waits for the screen to change after a tap or a key, so that the next
    step never acts on what is leaving: a box's button tapped while the box
    closes is lost. Ten seconds at most by the clock, not by a count of
    dumps, each of which can take seconds itself, and never past the run's
    `end`. A dump that fails is no change."""
    was = signature(before)
    stop = min(time.time() + SETTLE, end)
    while True:
        now = screen(serial)
        if now and signature(now) != was:
            return
        if time.time() >= stop:
            return
        time.sleep(0.5)


def pids(serial: str) -> set[str]:
    out = adb(serial, "shell", f"pidof {PACKAGE}", check=False).stdout
    return {p for p in out.split() if p.isdigit()}


def gone_within(serial: str, polls: int) -> bool:
    """The app's process gone, twice in a row (launch()'s rule), within
    `polls` half seconds."""
    empty = 0
    for _ in range(polls):
        empty = empty + 1 if not pids(serial) else 0
        if empty == 2:
            return True
        time.sleep(0.5)
    return False


def wait_screen(serial: str, ready, end: float, what: str, watch: bool = True):
    """Dumps the screen until ready() finds something on it: the nodes, and
    what it found. Ended when `watch` and the app's process is gone twice in
    a row first; Stuck when the time `end` comes first."""
    gone = 0
    while True:
        nodes = screen(serial)
        hit = ready(nodes)
        if hit is not None:
            return nodes, hit
        if watch:
            gone = gone + 1 if not pids(serial) else 0
            if gone == 2:
                raise Ended(what)
        if time.time() >= end:
            raise Stuck(f"{what} never showed; the screen shows {shown(nodes)}")
        time.sleep(0.5)


def end_process(serial: str) -> set[str]:
    """Ends the app's process as Android ends one behind another app's
    (am kill), or, when that leaves it, with kill -9 from the app's own
    user; the pids it had."""
    old = pids(serial)
    if not old:
        raise Stuck("the app's process was gone before it could be killed")
    named = " ".join(sorted(old))
    adb(serial, "shell", f"am kill {PACKAGE}")
    if not gone_within(serial, 10):
        say(f"am kill left the app's process ({named}): kill -9 instead")
        run_as(serial, f"kill -9 {named}", check=False)
        if not gone_within(serial, 20):
            raise Stuck(f"the app's process ({named}) outlived am kill and kill -9")
    say(f"killed the app's process ({named}) with the picker up")
    return old


def wait_new_process(serial: str, old: set[str], end: float) -> None:
    """Waits for the process the pick starts: Android hands the picked file
    to a new one once the old is gone, and runtime/android.c takes it as a
    pick from an earlier process. Asked at least once, however late the
    steps before it left it."""
    while True:
        new = pids(serial) - old
        if new:
            say(f"the app came back as process {' '.join(sorted(new))}")
            return
        if time.time() >= end:
            raise Stuck("no new process for the app after the pick")
        time.sleep(0.5)


def drive(
    serial: str,
    steps: list[tuple[str, str]],
    end: float,
    *,
    picker: bool = False,
    kill: bool = False,
    shot=None,
) -> None:
    """The steps of a run or a player's session, on the screen and in order:
    a tap waits for what shows its text and taps its centre, a key waits for
    the system's file picker, a font scale is put at once. After a tap or a
    key the screen is let change (settle) before the next step, and `shot`,
    when given, captures the screen each acts on. With `picker` the steps
    start once the picker is up; `kill` then ends the app's process before
    them and, after them, waits for the process the pick starts. Stuck when
    `end` comes first; Ended when the app does, holding the steps never
    done."""
    watch, done = True, 0
    old: set[str] = set()
    try:
        if picker:
            wait_screen(serial, picker_up, end, "the system's file picker")
        if kill:
            old = end_process(serial)
            watch = False  # gone on purpose, until the pick brings it back
        for kind, value in steps:
            if kind == "font":
                adb(serial, "shell", f"settings put system font_scale {value}")
                say(f"font_scale {value}")
            elif kind == "key":
                nodes, _ = wait_screen(serial, picker_up, end, "the system's file picker", watch)
                if shot:
                    shot(value)
                # DocumentsUI takes Back as "up a folder" until it is at its
                # top, and the picker opens in Download: backing out of it is
                # Back pressed until the picker goes, as a player presses it
                # (twice on the AVD, measured for L12d), never more than this
                for _ in range(BACK_TRIES if value == "KEYCODE_BACK" else 1):
                    adb(serial, "shell", f"input keyevent {value}")
                    say(f"sent {value}")
                    settle(serial, nodes, end)
                    nodes = screen(serial)
                    if value != "KEYCODE_BACK" or not picker_up(nodes):
                        break
            else:
                nodes, node = wait_screen(
                    serial, lambda ns, t=value: find(ns, t), end, repr(value), watch
                )
                if shot:
                    shot(value)
                x, y = centre(node)
                adb(serial, "shell", f"input tap {x} {y}")
                say(f"tapped {value!r} at {x},{y}")
                settle(serial, nodes, end)
            done += 1
    except Ended as exc:
        # Ended comes only from a wait for the screen, before its step is done,
        # and never after the kill, when nothing watches for the app's end: the
        # kill is among the steps left only when it never happened
        exc.left = ([("kill", "")] if kill and not old else []) + list(steps[done:])
        raise
    if kill:
        wait_new_process(serial, old, end)


OPTION = {"tap": "--tap", "key": "--key", "font": "--font-scale", "kill": "--kill-before-tap"}


def never_done(exc: Ended) -> str:
    """The line a report gains when the app ended before its steps were done.
    Without it a run whose picker never opened reads as one whose picker was
    backed out of: the same log, and the same exit (check 11)."""
    named = [
        OPTION[kind] + (f" {value!r}" if kind == "tap" else f" {value}" if value else "")
        for kind, value in exc.left
    ]
    if len(named) > 1:
        named[-2:] = [f"{named[-2]} and {named[-1]}"]
    verb = "was" if len(exc.left) == 1 else "were"
    return (
        f"[android] the app ended before {exc.what} showed, so {', '.join(named)} {verb} never done"
    )


def screencap(serial: str, local: Path) -> None:
    adb(serial, "shell", f"screencap -p {SCREENCAP}")
    adb(serial, "pull", SCREENCAP, str(local))
    adb(serial, "shell", f"rm -f {SCREENCAP}")


@contextlib.contextmanager
def font_kept(serial: str, used: bool):
    """The device's font_scale, put back as it was when the block ends,
    however it ends; nothing asked of the device when `used` is false."""
    if not used:
        yield
        return
    was = adb(serial, "shell", "settings get system font_scale").stdout.strip()
    try:
        yield
    finally:
        if re.fullmatch(r"\d+(\.\d+)?", was):
            adb(serial, "shell", f"settings put system font_scale {was}", check=False)
        else:  # "null": never set, so the default comes back
            adb(serial, "shell", "settings delete system font_scale", check=False)


# ---- runs ------------------------------------------------------------------


def extras(env: dict[str, str], argv: list[str], pick: list[str] = ()) -> list[str]:
    """The debug build's check extras (SoaActivity); any of them makes the run
    a check run. Each single-quoted: adb hands the line to the device's
    shell, where a ';' would end the command."""
    out = []
    pairs = ";".join(f"{k}={v}" for k, v in env.items())
    if pairs:
        out += ["--es", "env", f"'{pairs}'"]
    if argv:
        out += ["--es", "args", f"'{' '.join(argv)}'"]
    if pick:
        out += ["--es", "pick", f"'{';'.join(pick)}'"]
    return out


def launch(
    serial: str,
    env: dict[str, str],
    argv: list[str],
    timeout: int = 300,
    *,
    pick: list[str] = (),
    steps: list[tuple[str, str]] = (),
    kill: bool = False,
) -> tuple[int | None, str]:
    """One run of the app, from a stopped process: its exit status from the
    log's "[exit] N" (None when the run ended another way), and the log --
    as far as it got, when the run outlasts `timeout` and is stopped.
    `pick` answers the app's picks in order, without the picker. `steps` are
    drive()'s, done while the run is live, from when the picker is up when
    one is a tap or a key; `kill` ends the app's process then, and the wait
    is for the process the pick starts. A run whose app ended before its
    steps were done says so after its log (never_done). A font scale a step
    puts is put back when the run ends."""
    adb(serial, "shell", f"am force-stop {PACKAGE}")
    cmd = ["shell", "am", "start", "-W", "-n", COMPONENT, *extras(env, argv, pick)]
    with font_kept(serial, any(kind == "font" for kind, _ in steps)):
        adb(serial, *cmd)
        end = time.time() + timeout
        if steps or kill:
            try:
                picker = kill or any(kind != "font" for kind, _ in steps)
                drive(serial, steps, end, picker=picker, kill=kill)
            except Ended as exc:
                # gone twice in a row already, the rule the wait below keeps: the
                # log says why it ended, and the line after it what never happened
                text = run_as(serial, "cat files/soa.log", check=False).stdout
                m = EXIT.search(text)
                return (int(m.group(1)) if m else None), f"{text}{never_done(exc)}\n"
            except Stuck as exc:
                adb(serial, "shell", f"am force-stop {PACKAGE}")
                text = run_as(serial, "cat files/soa.log", check=False).stdout
                return None, f"{text}[android] {exc}, so the run was stopped\n"
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
            return (
                None,
                f"{text}[android] the run did not end within {timeout} s, so it was stopped\n",
            )
    text = run_as(serial, "cat files/soa.log", check=False).stdout
    m = EXIT.search(text)
    return (int(m.group(1)) if m else None), text


def parse_env(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        k, _, v = pair.partition("=")
        out[k] = v
    return out


class Step(argparse.Action):
    """--tap, --key and --font-scale, kept in the order given, as (kind, value)."""

    def __call__(self, parser, namespace, values, option_string=None):
        steps = getattr(namespace, self.dest, None) or []
        setattr(namespace, self.dest, [*steps, (self.const, values)])


def keycode(text: str) -> str:
    if not re.fullmatch(r"KEYCODE_[A-Z0-9_]+|\d+", text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a key: KEYCODE_BACK, say, or its number")
    return text


def scale(text: str) -> str:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0.5 <= value <= 3.0:
        raise argparse.ArgumentTypeError(f"{text} is outside 0.5-3.0, Android's font sizes")
    return str(value)


def cmd_run(args: argparse.Namespace) -> int:
    steps = args.steps or []
    if args.kill_before_tap and not any(kind == "tap" for kind, _ in steps):
        raise AndroidError("--kill-before-tap needs a --tap: only a pick brings the app back")
    env = parse_env(args.env)
    if args.kill_before_tap or any(kind != "font" for kind, _ in steps):
        # a pick the queue does not answer opens the picker, rather than counting as cancelled
        env.setdefault("SOA_IMPORT_PICKER", "1")
    pick = [pick_uri(uri) for uri in args.pick or []]
    code, text = launch(
        serial_of(args),
        env,
        args.argv,
        args.timeout,
        pick=pick,
        steps=steps,
        kill=args.kill_before_tap,
    )
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


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "step"


def cmd_player(args: argparse.Namespace) -> int:
    """The player's path (L12d check 10): the app launched as its icon
    launches it, with no check extras (or as the shortcut "Choose the game
    files again" does, --reimport); its boxes and the system's picker driven
    by their texts in order, the screen captured at each step; the game,
    --after seconds on; then the app stopped, and its soa.log and soa.ini
    pulled beside the captures. Game data: the owner's own."""
    serial = serial_of(args)
    steps = args.steps or []
    out = Path(args.out or ROOT / "build" / "android-player" / time.strftime("%Y%m%d-%H%M%S"))
    if out.is_dir() and any(out.iterdir()):
        raise AndroidError(f"{out} is not empty: name another --out")
    out.mkdir(parents=True, exist_ok=True)
    shots: list[Path] = []

    def shot(label: str, name: str = "") -> None:
        path = out / f"{len(shots) + 1:02d}-{name or slug(label)}.png"
        screencap(serial, path)
        shots.append(path)
        print(f"[android] {path.name}: {label}")

    ok = True
    with font_kept(serial, args.font_scale is not None):
        if args.font_scale is not None:
            adb(serial, "shell", f"settings put system font_scale {args.font_scale}")
        adb(serial, "shell", f"am force-stop {PACKAGE}")
        if args.fresh:
            run_as(serial, f"rm -rf {' '.join(FRESH)}")
        reimport = ["--ez", "soa.reimport", "true"] if args.reimport else []
        adb(serial, "shell", "am", "start", "-W", "-n", COMPONENT, *reimport)
        try:
            drive(serial, steps, time.time() + args.timeout, shot=shot)
            time.sleep(args.after)
            shot(f"the game, {args.after} s after the last step", "game")
        except (Stuck, Ended) as exc:
            ok = False
            print(f"[android] {exc}" if isinstance(exc, Stuck) else never_done(exc))
            shot("where it stopped", "stuck")
        finally:
            adb(serial, "shell", f"am force-stop {PACKAGE}")
            for name in ("soa.log", "soa.ini"):
                got = run_as(serial, f"cat files/{name}", check=False)
                if got.returncode == 0:
                    (out / name).write_text(got.stdout, encoding="utf-8", newline="")
                else:
                    print(f"[android] no files/{name} on {serial}")
    print(f"[android] {len(shots)} screencap(s), with soa.log and soa.ini, in {out}")
    return 0 if ok else 1


# ---- the emulator ----------------------------------------------------------


def quiet(serial: str, line: str) -> str:
    """A shell line's answer, or "" when the device cannot give one (it is
    restarting)."""
    try:
        proc = adb(serial, "shell", line, timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def avd_name(serial: str) -> str:
    """The AVD an emulator runs, as its console names it (adb emu avd name);
    "" for a device that is no emulator."""
    try:
        proc = adb(serial, "emu", "avd", "name", timeout=30, check=False)
    except subprocess.TimeoutExpired:
        return ""
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or len(lines) < 2 or lines[-1] != "OK":
        return ""
    return lines[0]


def cmd_reboot(args: argparse.Namespace) -> int:
    """Restarts the port's own emulator and nothing else (a kept grant must
    outlive a restart, L12d), waits for its new boot, then unlocks it and
    holds its screen on as TESTING.md's recipe does. A grant reaches disk
    about 10 s after it is taken: let 15 s pass after the pick."""
    serial = serial_of(args)
    name = avd_name(serial)
    if name != AVD:
        what = f"the AVD {name}" if name else "no emulator adb could name"
        raise AndroidError(
            f"{serial} is {what}, not {AVD}: reboot restarts the port's own emulator and no other device"
        )
    before = quiet(serial, "cat /proc/sys/kernel/random/boot_id")
    if not before:
        raise AndroidError(
            f"{serial} gave no boot id, so its new boot could not be told from this one"
        )
    adb(serial, "reboot")
    end = time.time() + args.timeout
    while time.time() < end:
        # a new boot id, so a boot_completed answered before the restart is never taken
        now = quiet(serial, "cat /proc/sys/kernel/random/boot_id")
        if now and now != before and quiet(serial, "getprop sys.boot_completed") == "1":
            break
        time.sleep(2)
    else:
        raise AndroidError(f"{serial} did not finish booting within {args.timeout} s")
    for line in (
        "svc power stayon true",
        "input keyevent KEYCODE_WAKEUP",
        "wm dismiss-keyguard",
        "settings put secure immersive_mode_confirmations confirmed",
    ):
        adb(serial, "shell", line)
    print(f"[android] {serial} ({AVD}) restarted, unlocked, and its screen held on")
    return 0


GRANT = re.compile(r"UriPermission\{[0-9a-f]+ (\S+)")
HOLDER = re.compile(r"\btargetPkg=(\S+)")
PERSISTED = re.compile(r"\bpersisted=0x([0-9a-f]+)")


def grants_in(text: str) -> list[tuple[str, str, bool]]:
    """The URI grants in dumpsys activity permissions' report: the package
    each was given to (its targetPkg, "" when the report names none), its
    URI, and whether it is kept (persisted, so it outlives a restart)."""
    held: list[list] = []
    for line in text.splitlines():
        if m := GRANT.search(line):
            held.append(["", m.group(1), False])
            continue
        if held and (h := HOLDER.search(line)):
            held[-1][0] = h.group(1)
        if held and (p := PERSISTED.search(line)):
            held[-1][2] = int(p.group(1), 16) != 0
    return [(holder, uri, kept) for holder, uri, kept in held]


def cmd_grants(args: argparse.Namespace) -> int:
    """The URI grants the app holds, each kept or not (checks 6, 8 and 12)."""
    serial = serial_of(args)
    # -p names the app: a package after the command is no filter, read as
    # nothing (ActivityManagerService's dump), and the report then holds every
    # app's grants. Each grant's holder is held to the app's here as well.
    report = adb(serial, "shell", f"dumpsys activity -p {PACKAGE} permissions").stdout
    held = grants_in(report)
    ours = [(uri, kept) for holder, uri, kept in held if holder == PACKAGE]
    for uri, kept in ours:
        print(f"{uri}  {'kept' if kept else 'not kept'}")
    if len(ours) < len(held):
        print(f"[android] left out {len(held) - len(ours)} grant(s) not given to {PACKAGE}")
    print(f"[android] {len(ours)} grant(s) held by {PACKAGE} on {serial}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    for name, fn in (
        ("install", cmd_install),
        ("selftest", cmd_selftest),
        ("logs", cmd_logs),
        ("grants", cmd_grants),
    ):
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
    for name, fn, where in (
        ("provide", cmd_provide, "files/provider/, for run --pick file/NAME or pipe/NAME"),
        ("stage", cmd_stage, f"{DOWNLOAD}/, where the picker opens"),
    ):
        p = sub.add_parser(name)
        p.add_argument("--serial")
        p.add_argument("file")
        p.add_argument("--as", dest="name", help=f"its name in {where} (default its own)")
        p.set_defaults(fn=fn)
    p = sub.add_parser("mutants")
    p.add_argument("--serial")
    p.add_argument("--profile", choices=[a.name for a in toolchain.ANDROID])
    p.add_argument("--out", default=str(ROOT / "build" / "android-mutants"))
    p.add_argument("--push", action="store_true", help="provide each on the device too")
    p.set_defaults(fn=cmd_mutants)
    p = sub.add_parser("replay")
    p.add_argument("--serial")
    p.add_argument("--threads", default="1,2,3,8")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("run")
    p.add_argument("--serial")
    p.add_argument("--env", action="append", help="K=V, repeatable")
    p.add_argument(
        "--pick",
        action="append",
        metavar="URI",
        help="answers the app's next pick without the picker, repeatable and in order: a "
        "content:// URI, or file/NAME or pipe/NAME for a file provide put on the device",
    )
    p.add_argument(
        "--tap",
        dest="steps",
        action=Step,
        const="tap",
        metavar="TEXT",
        help="tap what shows TEXT in the system's file picker once it shows; repeatable, in "
        "order with --key and --font-scale, all from when the picker is up",
    )
    p.add_argument(
        "--key",
        dest="steps",
        action=Step,
        const="key",
        type=keycode,
        metavar="KEYCODE",
        help="send KEYCODE (KEYCODE_BACK, say) once the picker is up; in order with --tap",
    )
    p.add_argument(
        "--font-scale",
        dest="steps",
        action=Step,
        const="font",
        type=scale,
        metavar="X",
        help="put system font_scale X at this point among the steps (at the start, with no "
        "--tap or --key); the device's own is put back when the run ends",
    )
    p.add_argument(
        "--kill-before-tap",
        action="store_true",
        help="once the picker is up, end the app's process (am kill, else kill -9) before the "
        "first --tap, and wait for the new process the pick starts",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="seconds before the run is stopped (default 300; the x86-64 emulator runs about 9 frames a second)",
    )
    p.add_argument("argv", nargs="*")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("player")
    p.add_argument("--serial")
    p.add_argument(
        "--tap",
        dest="steps",
        action=Step,
        const="tap",
        metavar="TEXT",
        help="tap what shows TEXT, a box's button or a file in the picker, once it shows; "
        "repeatable, in order with --key",
    )
    p.add_argument(
        "--key",
        dest="steps",
        action=Step,
        const="key",
        type=keycode,
        metavar="KEYCODE",
        help="send KEYCODE once the system's file picker is up (KEYCODE_BACK backs out of it)",
    )
    p.add_argument("--font-scale", type=scale, help="font_scale for the session, put back after")
    p.add_argument(
        "--reimport",
        action="store_true",
        help='launch as the shortcut "Choose the game files again" does',
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="first remove what an import leaves, and soa.ini, as a first run finds the app",
    )
    p.add_argument(
        "--after",
        type=int,
        default=30,
        help="seconds the game runs after the last step before its capture (default 30)",
    )
    p.add_argument("--out", help="an empty folder (default build/android-player/<date-time>)")
    p.add_argument("--timeout", type=int, default=300, help="seconds the steps may take in all")
    p.set_defaults(fn=cmd_player)
    p = sub.add_parser("reboot")
    p.add_argument("--serial")
    p.add_argument("--timeout", type=int, default=300, help="seconds to wait for the new boot")
    p.set_defaults(fn=cmd_reboot)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (AndroidError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
