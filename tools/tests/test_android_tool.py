"""tools/android.py, the parts that need no device (specs/android.md 3.14, L12c
and L12d).

The runtime's side of the seam that the APK is built from: exactly the seam's
runtime names, the bindings a build with no src/ leaves to the runtime (the
decompiled ones are the game's own there), soa_run and SDL_main, under the
record a game library built now would carry. The device is never chosen for
the caller: a check with neither --serial nor SOA_ADB_SERIAL is refused,
because another project's emulator may be the only one attached. A run's exit
status is the log's "[exit] N" line and nothing else, and a run that outlasts
its time is stopped with its log kept. Gradle is the pinned archive or
nothing. And every way the runtime leaves goes through runtime/android.c,
which drains the log first: without that the report's last lines and the
[exit] line were lost on every run that ended at its frame limit.

For the import (L12d): a file goes into files/ or no_backup/ as named, and
push-game into no_backup/, where the import puts the library; provide puts a
file where the debug provider serves it, and stage one in Download only when
df leaves room. The picks go in one quoted extra, in order. reboot restarts
the AVD soa_x86_64 and no other, and only a new boot ends its wait.
uiautomator's dump is read for a picker's file and a box's button, never a
word inside a longer text. The mutants are built against the record the APK
was built with and the executable it plays. player taps through the boxes and
the picker with no check extras, waiting for each screen to go before the
next tap, and captures each step. A run's font scales come in order with its
taps and the device's own comes back; and a kill before the tap is followed
into the process the pick starts, not taken for the run's end. A step waits
for the screen by the clock and never past the run's end, and a run whose app
ended before its steps were done says so, which neither its log nor its exit
can. grants counts the app's own grants, never another app's.
"""

import argparse
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import android  # noqa: E402
import player_build  # noqa: E402
import recompile  # noqa: E402
import soa  # noqa: E402
from soa import seam  # noqa: E402
from soa.hle import load_hle  # noqa: E402

CP = subprocess.CompletedProcess


def exported(version_script: str) -> set[str]:
    m = re.search(r"global:(.*?)local:", version_script, re.S)
    assert m, version_script
    return {name.strip() for name in m.group(1).split(";") if name.strip()}


def test_the_apk_runtime_exports_the_seam_the_no_decomp_bindings_and_sdl_main(tmp_path):
    android.seam_files(tmp_path)
    the_seam = seam.read_seam(ROOT / "config" / "seam.txt")
    decomp = recompile.decomp_bound()
    runtime_bound = set(load_hle(ROOT / "config" / "hle.txt")) - decomp
    names = exported((tmp_path / "runtime.map").read_text(encoding="utf-8"))
    assert names == {
        *the_seam.runtime,
        *(f"fn_{a:08X}" for a in runtime_bound),
        "soa_run",
        "SDL_main",
    }
    assert decomp and not names & {f"fn_{a:08X}" for a in decomp}
    assert "fn_80241DA0" in names  # __AI_SRC_INIT: the runtime's in every build

    src = (tmp_path / "runtime_seam.c").read_text(encoding="utf-8")
    baked = seam.baked_digest(player_build.inputs_record(ROOT))
    assert f'"{seam.record(True, baked)}"' in src
    for a in the_seam.twins:
        name = f"recomp_fn_{a:08X}" if a in runtime_bound else f"fn_{a:08X}"
        assert f"void {name}(CpuState* s) {{ soa_game_table->twin(0x{a:08X}u)(s); }}" in src


def test_parse_env_keeps_everything_after_the_first_equals():
    assert android.parse_env(["SOA_PAD=1600:start,1640:a", "SOA_X=a=b", "EMPTY"]) == {
        "SOA_PAD": "1600:start,1640:a",
        "SOA_X": "a=b",
        "EMPTY": "",
    }
    assert android.parse_env(None) == {}


def test_the_exit_status_is_the_logs_exit_line_alone():
    assert android.EXIT.search("[boot] up\n[exit] -1\n").group(1) == "-1"
    assert android.EXIT.search("[selftest] [exit] 3\n") is None
    assert android.EXIT.search("[exit] 3 frames\n") is None
    assert android.EXIT.search("[boot] 30 frames done (SOA_FRAMES)\n") is None


def test_a_check_names_its_device(monkeypatch, capsys):
    monkeypatch.delenv("SOA_ADB_SERIAL", raising=False)
    with pytest.raises(android.AndroidError, match="another project"):
        android.serial_of(argparse.Namespace(serial=None))
    assert android.main(["run", "--env", "SOA_RENDER=1"]) == 1
    assert "--serial or SOA_ADB_SERIAL" in capsys.readouterr().err
    monkeypatch.setenv("SOA_ADB_SERIAL", "emulator-5556")
    assert android.serial_of(argparse.Namespace(serial=None)) == "emulator-5556"
    assert android.serial_of(argparse.Namespace(serial="R5CT")) == "R5CT"


class FakeDevice:
    """adb as launch() uses it: the app's process there for `alive` polls of
    pidof and then gone, and soa.log as given."""

    def __init__(self, log: str, alive: int):
        self.log, self.alive, self.calls = log, alive, []

    def adb(self, serial, *cmd, timeout=600, check=True):
        self.calls.append(cmd)
        out = ""
        if cmd[0] == "shell" and cmd[1].startswith("pidof"):
            out = "4242\n" if self.alive > 0 else ""
            self.alive -= 1
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def run_as(self, serial, script, check=True):
        return subprocess.CompletedProcess(script, 0, self.log, "")


@pytest.fixture
def device(monkeypatch):
    def make(log: str, alive: int) -> FakeDevice:
        dev = FakeDevice(log, alive)
        monkeypatch.setattr(android, "adb", dev.adb)
        monkeypatch.setattr(android, "run_as", dev.run_as)
        monkeypatch.setattr(android.time, "sleep", lambda s: None)
        return dev

    return make


def test_launch_starts_from_a_stopped_app_and_reads_the_exit_line(device):
    dev = device("[boot] up\n[exit] 3\n", alive=2)
    code, text = android.launch(
        "emu", {"SOA_RENDER": "1", "SOA_PAD": "1600:start"}, ["--replay", "fifo/a"]
    )
    assert (code, text) == (3, "[boot] up\n[exit] 3\n")
    assert dev.calls[0] == ("shell", f"am force-stop {android.PACKAGE}")
    start = next(c for c in dev.calls if c[:3] == ("shell", "am", "start"))
    assert "'SOA_RENDER=1;SOA_PAD=1600:start'" in start
    assert "'--replay fifo/a'" in start
    # two polls with it there, then two with it gone: one empty answer is not an end
    assert sum(1 for c in dev.calls if c[1].startswith("pidof")) == 4


def test_one_empty_answer_from_pidof_is_not_the_end_of_the_run(device, monkeypatch):
    """The answer that once ended a replay's wait while it was still running,
    so its log was read with neither its hash nor its [exit] line in it."""
    dev = device("[boot] up\n[exit] 0\n", alive=0)
    answers = iter(["4242\n", "", "4242\n", "4242\n", "", ""])

    def adb(serial, *cmd, timeout=600, check=True):
        dev.calls.append(cmd)
        out = next(answers) if cmd[1].startswith("pidof") else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(android, "adb", adb)
    assert android.launch("emu", {}, [])[0] == 0
    assert sum(1 for c in dev.calls if c[1].startswith("pidof")) == 6


def test_a_run_that_outlasts_its_time_is_stopped_with_its_log(device):
    dev = device("[boot] up\n[gxr] wrote build/frames/0050.png (640x480)\n", alive=10**9)
    code, text = android.launch("emu", {}, [], timeout=0)
    assert code is None
    assert text.startswith("[boot] up\n[gxr] wrote build/frames/0050.png")
    assert text.endswith("[android] the run did not end within 0 s, so it was stopped\n")
    assert dev.calls[-1] == ("shell", f"am force-stop {android.PACKAGE}")


def test_gradle_is_the_pinned_archive_or_nothing(tmp_path):
    with pytest.raises(android.AndroidError, match=android.GRADLE_PIN):
        android.gradle(tmp_path, get=lambda url: b"not gradle")
    assert not (tmp_path / f"gradle-{android.GRADLE_VERSION}").exists()

    exe = tmp_path / f"gradle-{android.GRADLE_VERSION}" / "bin"
    exe /= "gradle.bat" if os.name == "nt" else "gradle"
    exe.parent.mkdir(parents=True)
    exe.write_text("")

    def no_fetch(url):
        raise AssertionError(f"fetched {url} with Gradle already in vendor/")

    assert android.gradle(tmp_path, get=no_fetch) == exe


def test_every_way_the_runtime_leaves_drains_the_log_on_android():
    """Each exit function a runtime file calls is wrapped in the APK's link
    and answered by runtime/android.c, which prints [exit] N and drains the
    log before the real _exit. A new one (quick_exit, say) fails here until
    it is wrapped too."""
    called = set()
    for path in (ROOT / "runtime").glob("*.c"):
        if path.name == "android.c":
            continue
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        called |= set(re.findall(r"(?<![\w.>])(exit|_exit|_Exit|quick_exit)\s*\(", text))
    assert called == {"exit", "_exit", "_Exit"}
    cmake = (ROOT / "android" / "app" / "src" / "main" / "cpp" / "CMakeLists.txt").read_text(
        encoding="utf-8"
    )
    shell = (ROOT / "runtime" / "android.c").read_text(encoding="utf-8")
    for name in sorted(called):
        assert f"-Wl,--wrap={name}\n" in cmake
        assert f"void __wrap_{name}(int status) {{ finish(status); }}" in shell
    assert "__real__exit(rc);" in shell


# ---- the import (L12d) -----------------------------------------------------


class Shell:
    """adb answering from a table: the first key a command's words start with
    gives its (status, output); everything else succeeds and says nothing."""

    def __init__(self, answers=None, short=0):
        self.answers, self.calls = dict(answers or {}), []
        # the last push's size, and how many bytes it falls short by
        self.pushed, self.short = 0, short

    def adb(self, serial, *cmd, timeout=600, check=True):
        self.calls.append(cmd)
        if cmd[0] == "push":
            self.pushed = os.path.getsize(cmd[1]) - self.short
        line = " ".join(cmd)
        for key, (status, out) in self.answers.items():
            if line.startswith(key):
                if check and status:
                    raise android.AndroidError(f"adb {line}: {out}")
                return CP(cmd, status, out, "")
        return CP(cmd, 0, "", "")

    def run_as(self, serial, script, check=True):
        self.calls.append(("run-as", script))
        if script.startswith("stat -c %s "):
            return CP(script, 0, f"{self.pushed}\n", "")
        return CP(script, 0, "", "")


@pytest.fixture
def shell(monkeypatch):
    def make(answers=None, short=0) -> Shell:
        sh = Shell(answers, short)
        monkeypatch.setattr(android, "adb", sh.adb)
        monkeypatch.setattr(android, "run_as", sh.run_as)
        monkeypatch.setattr(android.time, "sleep", lambda s: None)
        return sh

    return make


def scripts(calls) -> list[str]:
    return [c[1] for c in calls if c[0] == "run-as"]


def test_put_writes_into_the_folder_named_and_push_game_into_no_backup(shell, tmp_path, capsys):
    """files/ is the data root (the logs, the card, the debug provider's
    files); no_backup/ holds the imported library, which neither a backup nor
    a move to a new phone may take, and is made when the app has none yet."""
    sh = shell()
    lib = tmp_path / "libsoa_game.so"
    lib.write_bytes(b"\x7fELF a stand-in")
    android.put("emu", lib, "provider/a.so")
    android.put("emu", lib, "libsoa_game.so", "0444", base="no_backup")
    assert scripts(sh.calls) == [
        "mkdir -p files/provider && rm -f files/provider/a.so && "
        "cp /data/local/tmp/soa-push files/provider/a.so && chmod 0644 files/provider/a.so",
        "stat -c %s files/provider/a.so",
        "mkdir -p no_backup/ && rm -f no_backup/libsoa_game.so && "
        "cp /data/local/tmp/soa-push no_backup/libsoa_game.so && chmod 0444 no_backup/libsoa_game.so",
        "stat -c %s no_backup/libsoa_game.so",
    ]
    made = len(sh.calls)
    with pytest.raises(android.AndroidError, match="files or no_backup"):
        android.put("emu", lib, "libsoa_game.so", base="cache")
    assert len(sh.calls) == made  # refused before anything reached the device

    assert android.main(["push-game", "--serial", "emu", str(lib)]) == 0
    assert scripts(sh.calls)[-2:] == scripts(sh.calls)[2:4]
    assert "emu's no_backup/libsoa_game.so" in capsys.readouterr().out


def test_a_push_that_comes_up_short_is_refused_with_both_sizes(shell, tmp_path, capsys):
    """L12d's session put an ISO back with push-disc and was left a copy
    1226858496 of 1459978240 bytes long, with no error; the next run refused
    it as a truncated dump. Each push is now held to the file's size."""
    shell(short=4096)
    image = tmp_path / "disc.iso"
    image.write_bytes(b"\0" * 10000)
    said = "is 5904 bytes, not 10000 bytes: did the device run out of room"
    with pytest.raises(android.AndroidError, match=said):
        android.put("emu", image, "extracted/disc.iso", "0444")
    assert android.main(["push-disc", "--serial", "emu", str(image)]) == 1
    assert "run out of room" in capsys.readouterr().err


def test_provide_puts_a_file_where_the_debug_provider_serves_it(shell, tmp_path, capsys):
    sh = shell()
    store = tmp_path / "GTSE01.soadisc"
    store.write_bytes(b"SOADISC1")
    assert android.main(["provide", "--serial", "emu", str(store)]) == 0
    assert ("push", str(store), "/data/local/tmp/soa-push") in sh.calls
    assert "cp /data/local/tmp/soa-push files/provider/GTSE01.soadisc" in scripts(sh.calls)[-2]
    out = capsys.readouterr().out
    assert "content://io.github.bmfrench89.soa.dev.testfiles/file/GTSE01.soadisc" in out
    assert "content://io.github.bmfrench89.soa.dev.testfiles/pipe/GTSE01.soadisc" in out

    assert android.main(["provide", "--serial", "emu", str(store), "--as", "other.soadisc"]) == 0
    assert scripts(sh.calls)[-2].endswith("chmod 0644 files/provider/other.soadisc")
    made = len(sh.calls)
    assert android.main(["provide", "--serial", "emu", str(store), "--as", "my disc.soadisc"]) == 1
    assert "not a plain file name" in capsys.readouterr().err
    assert len(sh.calls) == made


DF = (
    "Filesystem      1K-blocks    Used Available Use% Mounted on\n"
    "/dev/block/dm-5   5944880 2853228 {free:>9}  49% {mount}\n"
)


def df(mib: int, mount: str) -> tuple[int, str]:
    return 0, DF.format(free=mib * 1024, mount=mount)


def test_stage_pushes_into_download_only_when_df_leaves_room(shell, tmp_path, capsys):
    """Both the shared storage and the app's are asked before a byte moves:
    on the emulator they are one 6 GB partition, and a 1.4 GB store, its copy
    and L12c's ISO do not all fit in it."""
    store = tmp_path / "GEAE8P.soadisc"
    store.write_bytes(bytes(1 << 20))
    sh = shell(
        {"shell df -k /sdcard": df(600, "/storage/emulated"), "shell df -k /data": df(400, "/data")}
    )
    assert android.main(["stage", "--serial", "emu", str(store)]) == 1
    said = capsys.readouterr().err
    assert (
        "/data on emu has 400 MiB free, and GEAE8P.soadisc needs 1 MiB with 512 MiB to spare"
        in said
    )
    assert not any(c[0] == "push" for c in sh.calls)

    sh.answers["shell df -k /data"] = df(600, "/data")
    assert android.main(["stage", "--serial", "emu", str(store)]) == 0
    asked = [c for c in sh.calls if c[0] == "push" or c[1].startswith("df ")]
    assert asked[-3:] == [
        ("shell", "df -k /sdcard"),
        ("shell", "df -k /data"),
        ("push", str(store), "/sdcard/Download/GEAE8P.soadisc"),
    ]


def test_picks_go_to_the_app_in_one_quoted_extra_in_order(device, capsys):
    """A ';' separates the picks in their extra, and the device's shell would
    end the command at one: the extra is single-quoted whole, the debug
    provider's short names are spelled out, and with no --tap or --key
    nothing asks the app to open the picker."""
    dev = device("[import] refused arm64.so: ...\n[exit] 1\n", alive=0)
    disc = "content://com.android.externalstorage.documents/document/primary%3ADownload%2FGEAE8P.soadisc"
    argv = ["run", "--serial", "emu", "--env", "SOA_IMPORT=1", "--env", "SOA_SETTINGS=0"]
    argv += ["--pick", "file/arm64.so", "--pick", "pipe/GTSE01.soadisc?truncate=65536"]
    assert android.main([*argv, "--pick", disc]) == 1
    start = next(c for c in dev.calls if c[:3] == ("shell", "am", "start"))
    at = start.index("pick")
    ours = "content://io.github.bmfrench89.soa.dev.testfiles"
    assert start[at - 1 : at + 2] == (
        "--es",
        "pick",
        f"'{ours}/file/arm64.so;{ours}/pipe/GTSE01.soadisc?truncate=65536;{disc}'",
    )
    assert "'SOA_IMPORT=1;SOA_SETTINGS=0'" in start
    capsys.readouterr()
    for bad in ("content://a;b", "content://it's", "content://a b", "/sdcard/Download/x.iso"):
        assert android.main(["run", "--serial", "emu", "--pick", bad]) == 1
        assert "a content:// URI with no ';', quote or space" in capsys.readouterr().err
    assert android.main(["run", "--serial", "emu", "--kill-before-tap"]) == 1
    assert "needs a --tap" in capsys.readouterr().err


class Emulator:
    """adb as reboot uses it. The console names the AVD (or fails, for a
    phone); after `adb reboot` the device first answers as the boot it was,
    its sys.boot_completed still 1, then not at all, then as a new boot not
    yet finished, then finished."""

    def __init__(self, name="soa_x86_64", phone=False):
        self.name, self.phone, self.calls = name, phone, []
        self.now, self.timeline, self.held_on_in = ("boot-1", "1"), [], None

    def adb(self, serial, *cmd, timeout=600, check=True):
        self.calls.append(cmd)
        if cmd[:3] == ("emu", "avd", "name"):
            if self.phone:
                return CP(cmd, 1, "", "error: not an emulator")
            return CP(cmd, 0, f"{self.name}\nOK\n", "")
        if cmd == ("reboot",):
            self.timeline = [("boot-1", "1"), None, None, ("boot-2", ""), ("boot-2", "1")]
            return CP(cmd, 0, "", "")
        line = " ".join(cmd[1:])
        if line == "cat /proc/sys/kernel/random/boot_id" and self.timeline:
            self.now = self.timeline.pop(0)
        if line in ("cat /proc/sys/kernel/random/boot_id", "getprop sys.boot_completed"):
            if self.now is None:
                return CP(cmd, 1, "", "error: device offline")
            return CP(cmd, 0, self.now[0 if "boot_id" in line else 1] + "\n", "")
        if line == "svc power stayon true":
            self.held_on_in = self.now
        return CP(cmd, 0, "", "")


@pytest.mark.parametrize(
    "made, said",
    [
        ({"name": "foundfirst_pixel"}, "is the AVD foundfirst_pixel, not soa_x86_64"),
        ({"phone": True}, "is no emulator adb could name, not soa_x86_64"),
    ],
)
def test_reboot_restarts_the_ports_own_emulator_and_no_other(monkeypatch, capsys, made, said):
    emulator = Emulator(**made)
    monkeypatch.setattr(android, "adb", emulator.adb)
    assert android.main(["reboot", "--serial", "emulator-5554"]) == 1
    assert said in capsys.readouterr().err
    assert emulator.calls == [("emu", "avd", "name")]


def test_reboot_waits_for_a_new_boot_then_unlocks_and_holds_the_screen_on(monkeypatch):
    """A boot_completed of 1 answered before the restart has taken is the old
    boot's: only a new boot id ends the wait."""
    emulator = Emulator()
    monkeypatch.setattr(android, "adb", emulator.adb)
    monkeypatch.setattr(android.time, "sleep", lambda s: None)
    assert android.main(["reboot", "--serial", "emulator-5556"]) == 0
    assert emulator.calls[0] == ("emu", "avd", "name")
    assert emulator.held_on_in == ("boot-2", "1")
    rest = emulator.calls[emulator.calls.index(("reboot",)) + 1 :]
    assert [c[1] for c in rest if not c[1].startswith(("cat ", "getprop "))] == [
        "svc power stayon true",
        "input keyevent KEYCODE_WAKEUP",
        "wm dismiss-keyguard",
        "settings put secure immersive_mode_confirmations confirmed",
    ]


# dumpsys activity permissions' report as Android 14 prints it, every app's
# grants (UriPermission.dump): another app's first, as the lower UID, then the
# port's two, one kept and one still owned by the activity that was given it.
PHOTO = "content://com.android.providers.media.photopicker/media/picker/0/com.android.providers.media.photopicker/media/1000000018"
DISC = (
    "content://com.android.externalstorage.documents/document/primary%3ADownload%2FGEAE8P.soadisc"
)
MSF = "content://com.android.providers.downloads.documents/document/msf%3A31"
PERMISSIONS = f"""\
ACTIVITY MANAGER URI PERMISSIONS (dumpsys activity permissions)
  Granted Uri Permissions:
  * UID 10155 holds:
    UriPermission{{1a2b3c4 {PHOTO} [user 0]}}
      targetUserId=0 sourcePkg=com.android.providers.media.module targetPkg=com.google.android.apps.photos
      mode=0x1 owned=0x0 global=0x0 persistable=0x1 persisted=0x1 persistedCreate=1759740000000
  * UID 10190 holds:
    UriPermission{{7a1c2b3 {DISC} [user 0]}}
      targetUserId=0 sourcePkg=com.android.externalstorage targetPkg=io.github.bmfrench89.soa.dev
      mode=0x1 owned=0x0 global=0x1 persistable=0x3 persisted=0x1 persistedCreate=1759740000000
    UriPermission{{1b2c3d4 {MSF} [user 0]}}
      targetUserId=0 sourcePkg=com.android.providers.downloads targetPkg=io.github.bmfrench89.soa.dev
      mode=0x1 owned=0x1 global=0x0 persistable=0x3 persisted=0x0
      readOwners:
        * ActivityRecord{{c0ffee1 u0 io.github.bmfrench89.soa.dev/io.github.bmfrench89.soa.SoaActivity t12}}
"""


def test_grants_are_the_apps_own_with_whether_each_is_kept(shell, capsys):
    """Checks 6 and 12 want exactly one grant, kept. The package goes to
    dumpsys as -p: named after the command it is no filter, and the report
    holds every app's grants. Each grant's holder is checked here as well,
    so a report that lists another app's (this one, as a device asked
    without -p gives it) never counts that grant as the app's."""
    app = "io.github.bmfrench89.soa.dev"
    assert android.grants_in(PERMISSIONS) == [
        ("com.google.android.apps.photos", PHOTO, True),
        (app, DISC, True),
        (app, MSF, False),
    ]
    assert android.grants_in(PERMISSIONS.split("  Granted")[0] + "  (nothing)\n") == []
    sh = shell({"shell dumpsys activity": (0, PERMISSIONS)})
    assert android.main(["grants", "--serial", "emu"]) == 0
    assert [c for c in sh.calls if "dumpsys" in " ".join(c)] == [
        ("shell", f"dumpsys activity -p {app} permissions")
    ]
    assert capsys.readouterr().out == (
        f"{DISC}  kept\n"
        f"{MSF}  not kept\n"
        f"[android] left out 1 grant(s) not given to {app}\n"
        f"[android] 2 grant(s) held by {app} on emu\n"
    )


# uiautomator's dumps as android-34 gives them: DocumentsUI's Downloads, two
# rows; and a box whose buttons draw their labels in capitals, under a message
# that names one of them, with uiautomator's own line after the dump.
DOCS_DUMP = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    '<hierarchy rotation="0">'
    '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
    'package="com.google.android.documentsui" content-desc="" checkable="false" checked="false" '
    'clickable="false" enabled="true" focusable="false" focused="false" scrollable="false" '
    'long-clickable="false" password="false" selected="false" bounds="[0,0][1080,2400]">'
    '<node index="0" text="Downloads" resource-id="" class="android.widget.TextView" '
    'package="com.google.android.documentsui" content-desc="" bounds="[189,145][493,219]" />'
    '<node index="1" text="" resource-id="com.google.android.documentsui:id/dir_list" '
    'class="androidx.recyclerview.widget.RecyclerView" package="com.google.android.documentsui" '
    'content-desc="" scrollable="true" bounds="[0,357][1080,2337]">'
    '<node index="0" text="" resource-id="com.google.android.documentsui:id/item_root" '
    'class="android.widget.LinearLayout" package="com.google.android.documentsui" '
    'content-desc="" clickable="true" focusable="true" bounds="[0,357][1080,525]">'
    '<node index="0" text="" resource-id="com.google.android.documentsui:id/icon_thumb" '
    'class="android.widget.ImageView" package="com.google.android.documentsui" '
    'content-desc="" bounds="[42,399][126,483]" />'
    '<node index="1" text="GEAE8P.soadisc" resource-id="android:id/title" '
    'class="android.widget.TextView" package="com.google.android.documentsui" '
    'content-desc="" bounds="[168,385][1038,441]" />'
    '<node index="2" text="1.33 GB, 11:58 AM" '
    'resource-id="com.google.android.documentsui:id/metadata" class="android.widget.TextView" '
    'package="com.google.android.documentsui" content-desc="" bounds="[168,441][1038,497]" />'
    "</node>"
    '<node index="1" text="" resource-id="com.google.android.documentsui:id/item_root" '
    'class="android.widget.LinearLayout" package="com.google.android.documentsui" '
    'content-desc="" clickable="true" focusable="true" bounds="[0,525][1080,693]">'
    '<node index="1" text="libsoa_game.so" resource-id="android:id/title" '
    'class="android.widget.TextView" package="com.google.android.documentsui" '
    'content-desc="" bounds="[168,553][1038,609]" />'
    "</node></node></node></hierarchy>"
)
BOX_DUMP = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
    '<hierarchy rotation="1">'
    '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
    'package="io.github.bmfrench89.soa.dev" content-desc="" bounds="[0,0][2400,1080]">'
    '<node index="0" text="" resource-id="" class="android.widget.ScrollView" '
    'package="io.github.bmfrench89.soa.dev" content-desc="" bounds="[600,180][1800,700]">'
    '<node index="0" text="The game library you picked could not be used: it was built for '
    '64-bit ARM. Pick the libsoa_game.so that Setup made for this device." resource-id="" '
    'class="android.widget.TextView" package="io.github.bmfrench89.soa.dev" content-desc="" '
    'bounds="[660,220][1740,660]" /></node>'
    '<node index="1" text="Hidden" resource-id="" class="android.widget.TextView" '
    'package="io.github.bmfrench89.soa.dev" content-desc="" bounds="[0,0][0,0]" />'
    '<node index="2" text="QUIT" resource-id="android:id/button2" class="android.widget.Button" '
    'package="io.github.bmfrench89.soa.dev" content-desc="" clickable="true" '
    'bounds="[1290,760][1480,880]" />'
    '<node index="3" text="PICK" resource-id="android:id/button1" class="android.widget.Button" '
    'package="io.github.bmfrench89.soa.dev" content-desc="" clickable="true" focused="true" '
    'bounds="[1500,760][1740,880]" />'
    "</node></hierarchy>\nUI hierchary dumped to: /dev/tty\n"
)


def test_the_screen_is_read_from_uiautomators_dump():
    files = android.ui_nodes(DOCS_DUMP)
    assert android.picker_up(files)
    assert android.centre(android.find(files, "GEAE8P.soadisc")) == (603, 413)
    assert android.centre(android.find(files, "libsoa_game.so")) == (603, 581)
    assert android.find(files, "1.33 GB") is None  # never a part of a longer text

    box = android.ui_nodes(BOX_DUMP)
    assert android.picker_up(box) is None
    pick = android.find(box, "Pick")  # drawn PICK, under a message that says Pick
    assert pick["resource-id"] == "android:id/button1"
    assert android.centre(pick) == (1620, 820)
    assert android.find(box, "Hidden") is None  # no area on the screen
    for broken in ("ERROR: could not get idle state.", DOCS_DUMP[:-40], ""):
        assert android.ui_nodes(broken) == []


def fake_fixture(monkeypatch, words: str) -> list[tuple]:
    """Stands in for tools/soa/gamefixture.py, which needs the NDK: what
    android.py asks of it, and one library with `words` as its refusal."""
    asked = []

    def android_mutants(out, profile, record, dol):
        asked.append((Path(out), profile, record, dol))
        Path(out).mkdir(parents=True, exist_ok=True)
        lib = Path(out) / "arm64.so"
        lib.write_bytes(b"\x7fELF a stand-in")
        return {"arm64": (lib, words)}

    fake = types.ModuleType("soa.gamefixture")
    fake.android_mutants = android_mutants
    monkeypatch.setitem(sys.modules, "soa.gamefixture", fake)
    monkeypatch.setattr(soa, "gamefixture", fake, raising=False)
    return asked


def apk_seam(monkeypatch, tmp_path) -> str:
    """generated/runtime_seam.c as build writes it, under another build's
    record than this tree's: the record a mutant must be built against."""
    record = seam.record(True, "ab" * 32)
    the_seam = seam.read_seam(ROOT / "config" / "seam.txt")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "runtime_seam.c").write_text(
        seam.runtime_seam_c(the_seam, set(), record), encoding="utf-8"
    )
    monkeypatch.setattr(android, "GENERATED", tmp_path / "generated")
    return record


def config_dol() -> str:
    """config.yml's executable hash, read here on its own."""
    text = (ROOT / "config" / "GEAE8P" / "config.yml").read_text(encoding="utf-8")
    return re.search(r"^hash:\s*([0-9a-f]{40})\s*$", text, re.M).group(1)


WORDS = (
    "this library was built for 64-bit ARM (AArch64), not this device (x86-64): "
    "rebuild it for this device with Setup"
)


def test_the_mutants_are_built_against_the_record_the_apk_was_built_with(
    monkeypatch, tmp_path, capsys
):
    """The record is generated/runtime_seam.c's, which Gradle compiled into
    the APK, not this tree's, which may have moved on since; the executable
    is config.yml's. Another record would draw the record refusal from every
    mutant instead of the refusal each is made for."""
    record = apk_seam(monkeypatch, tmp_path)
    asked = fake_fixture(monkeypatch, WORDS)
    assert android.main(["mutants", "--out", str(tmp_path / "m")]) == 0
    assert asked == [(tmp_path / "m", "android-x86_64", record, config_dol())]
    assert f"\n  [import] refused arm64.so: {WORDS}\n" in capsys.readouterr().out

    monkeypatch.setattr(android, "GENERATED", tmp_path / "none")
    assert android.main(["mutants", "--out", str(tmp_path / "m")]) == 1
    assert "python tools/android.py build writes it" in capsys.readouterr().err

    def no_ndk(out, profile, record, dol):
        raise RuntimeError("no android-x86_64 compiler here")  # as toolchain.cc says it

    monkeypatch.setattr(android, "GENERATED", tmp_path / "generated")
    monkeypatch.setattr(soa.gamefixture, "android_mutants", no_ndk)
    assert android.main(["mutants", "--out", str(tmp_path / "m")]) == 1
    said = capsys.readouterr().err
    assert "error: the mutants could not be made: no android-x86_64 compiler here" in said


def test_the_mutants_record_is_the_one_this_pcs_apk_was_built_with(monkeypatch, tmp_path):
    seam_c = android.GENERATED / "runtime_seam.c"
    if not seam_c.is_file():
        pytest.skip("no APK built here: python tools/android.py build writes runtime_seam.c")
    lines = seam_c.read_text(encoding="utf-8").splitlines()
    line = next(x for x in lines if x.startswith("const char soa_runtime_record[]"))
    asked = fake_fixture(monkeypatch, WORDS)
    assert android.main(["mutants", "--out", str(tmp_path / "m")]) == 0
    assert asked[0][2:] == (line[line.index('"') + 1 : line.rindex('"')], config_dol())


def test_mutants_push_provides_each_for_the_devices_abi(shell, monkeypatch, tmp_path, capsys):
    apk_seam(monkeypatch, tmp_path)
    sh = shell({"shell getprop ro.product.cpu.abi": (0, "x86_64\n")})
    asked = fake_fixture(monkeypatch, WORDS)
    out = str(tmp_path / "m")
    assert android.main(["mutants", "--push", "--serial", "emu", "--out", out]) == 0
    assert asked[0][1] == "android-x86_64"
    assert "cp /data/local/tmp/soa-push files/provider/arm64.so" in scripts(sh.calls)[-2]
    argv = ["mutants", "--push", "--serial", "emu", "--profile", "android-arm64", "--out", out]
    assert android.main(argv) == 1
    assert "--profile android-arm64 is another's" in capsys.readouterr().err


APP = android.PACKAGE
DOCS = "com.google.android.documentsui"
PICKER = (
    DOCS,
    (
        ("Downloads", "[40,60][400,140]"),
        ("libsoa_game.so", "[189,441][700,497]"),
        ("GEAE8P.soadisc", "[189,609][700,665]"),
    ),
)
GAME = (APP, ())  # SDL's surface: nothing uiautomator can read


def box(message: str, *buttons: tuple[str, str]) -> tuple:
    return APP, ((message, "[300,200][2100,600]"), *buttons)


def window(package: str, *items: tuple[str, str]) -> str:
    """uiautomator's dump of one window: its frame, and a node for each (text, bounds)."""
    nodes = "".join(
        f'<node index="{i}" text="{text}" resource-id="" class="android.widget.TextView" '
        f'package="{package}" content-desc="" clickable="true" enabled="true" focused="false" '
        f'selected="false" bounds="{bounds}" />'
        for i, (text, bounds) in enumerate(items)
    )
    return (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
        f'<hierarchy rotation="1"><node index="0" text="" class="android.widget.FrameLayout" '
        f'package="{package}" content-desc="" bounds="[0,0][2400,1080]">{nodes}</node></hierarchy>'
    )


class Phone:
    """adb as the import's commands use it, over screens that taps and keys
    move between: `moves` says where (a screen, the text tapped or the key)
    leads, and (a screen, None) where one goes by itself. A move lands `lag`
    dumps after its press, and a press on a screen already leaving is lost,
    as on a device. The app's process is `pid` ("" when there is none); on the
    screen `last` pidof answers `tail` in turn, and its last answer after."""

    def __init__(self, screens, first, moves, *, log="[exit] 0\n", last="game", tail=(), lag=0):
        self.screens, self.at, self.moves = screens, first, moves
        self.log, self.ini, self.last, self.tail, self.lag = log, "render = 1\n", last, [*tail], lag
        self.pid, self.font, self.pending, self.ignore_kill = "", "1.0", None, False
        self.calls, self.answers, self.taps, self.lost, self.pulled = [], [], [], [], []

    def run_as(self, serial, script, check=True):
        self.calls.append(("run-as", script))
        if script.startswith("kill -9"):
            self.pid = ""
        files = {"cat files/soa.log": self.log, "cat files/soa.ini": self.ini}
        return CP(script, 0, files.get(script, ""), "")

    def adb(self, serial, *cmd, timeout=600, check=True):
        self.calls.append(cmd)
        if cmd[0] == "pull":
            Path(cmd[2]).write_bytes(b"\x89PNG a capture")
            self.pulled.append(Path(cmd[2]).name)
        line = " ".join(cmd[1:]) if cmd[0] == "shell" else ""
        out = ""
        if line.startswith("am start"):
            self.pid = "4242"
        elif line.startswith("am force-stop") or (
            line.startswith("am kill") and not self.ignore_kill
        ):
            self.pid = ""
        elif line.startswith("pidof"):
            if self.at == self.last and self.tail:
                self.pid = self.tail.pop(0)
            out = self.pid
            self.answers.append(out)
        elif "uiautomator dump" in line:
            out = self.dump()
        elif line.startswith("input tap"):
            x, y = (int(v) for v in line.split()[2:])
            self.press(self.text_at(x, y))
        elif line.startswith("input keyevent"):
            self.press(line.split()[2])
        elif line == "settings get system font_scale":
            out = self.font
        elif line.startswith("settings put system font_scale "):
            self.font = line.split()[-1]
        elif line == "settings delete system font_scale":
            self.font = "null"
        return CP(cmd, 0, out, "")

    def dump(self) -> str:
        if self.pending is not None:
            where, left = self.pending
            self.pending = (where, left - 1) if left else None
            if not left:
                self.at = where
        elif (self.at, None) in self.moves:
            self.pending = (self.moves[(self.at, None)], 0)
        package, items = self.screens[self.at]
        return window(package, *items)

    def press(self, what: str) -> None:
        if self.pending is not None:
            self.lost.append(what)
            return
        self.taps.append((self.at, what))
        self.pending = (self.moves[(self.at, what)], self.lag)

    def text_at(self, x: int, y: int) -> str:
        for text, bounds in self.screens[self.at][1]:
            x1, y1, x2, y2 = (int(v) for v in re.findall(r"-?\d+", bounds))
            if x1 <= x < x2 and y1 <= y < y2:
                return text
        raise AssertionError(f"a tap at {x},{y} on {self.at} hits nothing")


@pytest.fixture
def phone(monkeypatch):
    def make(*args, **kw) -> Phone:
        p = Phone(*args, **kw)
        monkeypatch.setattr(android, "adb", p.adb)
        monkeypatch.setattr(android, "run_as", p.run_as)
        monkeypatch.setattr(android.time, "sleep", lambda s: None)
        return p

    return make


@pytest.mark.parametrize("am_kill_ends_it", [True, False])
def test_a_kill_before_the_tap_is_followed_into_the_process_the_pick_starts(phone, am_kill_ends_it):
    """Check 12: the app's process ended with the picker up, the file tapped,
    and the run followed into the process the result starts. The empty
    answers after the kill are not the run's end: here the new process comes
    two answers after the tap, and a wait that took those for the end would
    read a log the new process had not yet written."""
    p = phone(
        {"picker": PICKER, "game": GAME},
        "picker",
        {("picker", "GEAE8P.soadisc"): "game"},
        log="[import] pending disc pick from an earlier process: content://x\n[exit] 0\n",
        tail=["", "", "4343", "4343", "4343", ""],
    )
    p.ignore_kill = not am_kill_ends_it
    argv = ["run", "--serial", "emu", "--timeout", "5", "--env", "SOA_IMPORT=disc"]
    argv += ["--kill-before-tap"]
    assert android.main([*argv, "--tap", "GEAE8P.soadisc"]) == 0
    start = next(c for c in p.calls if c[:3] == ("shell", "am", "start"))
    assert "'SOA_IMPORT=disc;SOA_IMPORT_PICKER=1'" in start
    kill = p.calls.index(("shell", f"am kill {android.PACKAGE}"))
    assert kill < p.calls.index(("shell", "input tap 444 637"))
    assert (("run-as", "kill -9 4242") in p.calls) is not am_kill_ends_it
    assert p.taps == [("picker", "GEAE8P.soadisc")]
    assert p.answers[-5:] == ["4343", "4343", "4343", "", ""]


@pytest.mark.parametrize(
    "was, back",
    [("1.0", "settings put system font_scale 1.0"), ("null", "settings delete system font_scale")],
)
def test_font_scales_come_in_order_with_the_taps_and_the_devices_own_comes_back(phone, was, back):
    """Check 13: one font scale while the picker is up, another once the file
    is tapped, and the device's own (or none) when the run has ended."""
    p = phone(
        {"picker": PICKER, "game": GAME},
        "picker",
        {("picker", "GEAE8P.soadisc"): "game"},
        tail=["4242", "4242", ""],
    )
    p.font = was
    argv = ["run", "--serial", "emu", "--timeout", "5", "--env", "SOA_IMPORT=disc"]
    argv += ["--font-scale", "1.15"]
    assert android.main([*argv, "--tap", "GEAE8P.soadisc", "--font-scale", "1.3"]) == 0
    c = p.calls
    shell_lines = [" ".join(x[1:]) if x[0] == "shell" else "" for x in c]
    start = next(i for i, x in enumerate(c) if x[:3] == ("shell", "am", "start"))
    first = shell_lines.index("settings put system font_scale 1.15")
    dumps = [i for i, line in enumerate(shell_lines) if "uiautomator dump" in line]
    tap = shell_lines.index("input tap 444 637")
    second = shell_lines.index("settings put system font_scale 1.3")
    polls = [i for i, line in enumerate(shell_lines) if line.startswith("pidof")]
    assert shell_lines.index("settings get system font_scale") < start < dumps[0] < first
    assert first < tap < second < polls[-1] < shell_lines.index(back)
    assert "'SOA_IMPORT=disc;SOA_IMPORT_PICKER=1'" in c[start]


def test_a_tap_whose_text_never_shows_stops_the_run_and_says_what_showed(phone):
    p = phone({"picker": PICKER}, "picker", {}, log="[boot] up\n")
    code, text = android.launch("emu", {"SOA_IMPORT": "disc"}, [], 0, steps=[("tap", "x.so")])
    assert code is None
    assert text == (
        "[boot] up\n[android] 'x.so' never showed; the screen shows "
        "Downloads | libsoa_game.so | GEAE8P.soadisc, so the run was stopped\n"
    )
    assert p.calls[-2:] == [
        ("shell", f"am force-stop {android.PACKAGE}"),
        ("run-as", "cat files/soa.log"),
    ]


class Clock:
    """time as android.py reads it, moved on by each sleep and by each
    uiautomator dump, which takes `dump` seconds; a screen that never
    changes, and the app's process `pid`."""

    def __init__(self, dump: float, pid: str = "4242"):
        self.now, self.dump, self.pid, self.dumps, self.polls = 1000.0, dump, pid, 0, 0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def adb(self, serial, *cmd, timeout=600, check=True):
        line = " ".join(cmd[1:])
        out = ""
        if "uiautomator dump" in line:
            self.now += self.dump
            self.dumps += 1
            out = window(APP, ("Loading", "[0,0][300,100]"))
        elif line.startswith("pidof"):
            self.polls += 1
            out = self.pid
        return CP(cmd, 0, out, "")


def test_a_step_waits_for_the_screen_by_the_clock_and_never_past_the_runs_end(monkeypatch):
    """A tap that changes nothing on the screen is let settle for ten seconds
    of the clock, not twenty dumps, each of which waits for an idle screen
    first, and only until the run's end when that comes sooner. The wait for
    the process a pick starts then asks for it at least once, however late
    the steps left it, where it gave up unasked with the new process running."""
    clock = Clock(dump=3)
    monkeypatch.setattr(android, "adb", clock.adb)
    monkeypatch.setattr(android, "time", types.SimpleNamespace(time=clock.time, sleep=clock.sleep))
    same = android.screen("emu")
    start, clock.dumps = clock.now, 0
    android.settle("emu", same, start + 300)
    assert (clock.dumps, clock.now - start) == (3, 10)
    start, clock.dumps = clock.now, 0
    android.settle("emu", same, start + 4)
    assert (clock.dumps, clock.now - start) == (2, 6.5)

    clock.pid = "4343"
    android.wait_new_process("emu", {"4242"}, clock.now - 1)
    assert clock.polls == 1
    clock.pid = "4242"
    with pytest.raises(android.Stuck, match="no new process for the app after the pick"):
        android.wait_new_process("emu", {"4242"}, clock.now - 1)
    assert clock.polls == 2


def test_a_run_that_ends_before_the_picker_shows_says_its_steps_were_never_done(phone):
    """A refusal ends a check run before any picker opens: its log says why,
    and the report's last line which steps never happened, the kill among
    them."""
    refused = "[import] refused arm64.so: ...\n[exit] 1\n"
    p = phone({"box": box("unused")}, "box", {}, log=refused, last="box", tail=["4242", "", ""])
    code, text = android.launch("emu", {"SOA_IMPORT": "library"}, [], steps=[("tap", "a.so")])
    assert (code, text) == (
        1,
        f"{refused}[android] the app ended before the system's file picker showed, "
        "so --tap 'a.so' was never done\n",
    )
    assert not [c for c in p.calls if c[0] == "shell" and c[1].startswith("input")]

    p = phone({"box": box("unused")}, "box", {}, log=refused, last="box", tail=["", ""])
    steps = [("tap", "Downloads"), ("font", "1.3"), ("tap", "GEAE8P.soadisc")]
    code, text = android.launch("emu", {"SOA_IMPORT": "disc"}, [], steps=steps, kill=True)
    assert code == 1
    assert text.endswith(
        "[android] the app ended before the system's file picker showed, so --kill-before-tap, "
        "--tap 'Downloads', --font-scale 1.3 and --tap 'GEAE8P.soadisc' were never done\n"
    )
    assert not [c for c in p.calls if c[0] == "shell" and c[1].startswith(("am kill", "input"))]


def test_back_in_the_picker_is_told_from_a_picker_that_never_opened(phone, capsys):
    """Check 11. Back sent in the picker, and a picker that never opened (the
    app answered its pick as cancelled at once), leave the same log and the
    same exit: only the report's last line tells them apart."""
    log = "[import] box: ... / Pick / Quit\n[import] cancelled (disc)\n[exit] 1\n"
    argv = ["run", "--serial", "emu", "--timeout", "5", "--env", "SOA_IMPORT=disc"]
    argv += ["--key", "KEYCODE_BACK"]
    back = phone(
        {"picker": PICKER, "gone": GAME},
        "picker",
        {("picker", "KEYCODE_BACK"): "gone"},
        log=log,
        last="gone",
        tail=["", ""],
    )
    assert android.main(argv) == 1
    assert capsys.readouterr().out == log
    assert back.taps == [("picker", "KEYCODE_BACK")]

    never = phone({"box": box("unused")}, "box", {}, log=log, last="box", tail=["", "", ""])
    assert android.main(argv) == 1
    assert capsys.readouterr().out == (
        f"{log}[android] the app ended before the system's file picker showed, "
        "so --key KEYCODE_BACK was never done\n"
    )
    assert never.taps == []


def test_back_is_pressed_until_the_picker_goes(phone, capsys):
    """Check 11 on the AVD: the picker opens in Download, where DocumentsUI
    takes the first Back as up a folder, and only the second closes it. The
    run presses Back until the picker is gone, as a player does."""
    log = "[import] cancelled (disc)\n[exit] 1\n"
    argv = ["run", "--serial", "emu", "--timeout", "5", "--env", "SOA_IMPORT=disc"]
    p = phone(
        {
            "picker": PICKER,
            "top": (DOCS, (("Files on the phone", "[40,60][400,140]"),)),
            "gone": GAME,
        },
        "picker",
        {("picker", "KEYCODE_BACK"): "top", ("top", "KEYCODE_BACK"): "gone"},
        log=log,
        last="gone",
        tail=["", ""],
    )
    assert android.main([*argv, "--key", "KEYCODE_BACK"]) == 1
    assert capsys.readouterr().out.endswith(log)
    assert p.taps == [("picker", "KEYCODE_BACK"), ("top", "KEYCODE_BACK")]


LIBRARY_BOX = box(
    "Choose libsoa_game.so, the game library Setup made. Mods are not on Android yet.",
    ("QUIT", "[1100,800][1300,900]"),
    ("PICK", "[1500,800][1700,900]"),
)
DISC_BOX = box(
    "Choose your disc: GEAE8P.soadisc, or its ISO.",
    ("QUIT", "[1100,800][1300,900]"),
    ("PICK", "[1500,800][1700,900]"),
)
FRESH = {
    "files/libsoa_game.so",
    "files/soa.ini",
    "no_backup/libsoa_game.so",
    "no_backup/libsoa_game.so.tmp",
    "no_backup/libsoa_game.so.old",
    "no_backup/disc.txt",
    "no_backup/pending_library",
    "no_backup/pending_disc",
    "no_backup/copy",
}


def test_player_taps_through_the_boxes_and_the_picker_with_no_check_extras(phone, tmp_path, capsys):
    """Check 10's script: Pick, Back once, Pick, the library, Pick, the store,
    on an app launched as its icon launches it, from what a first run finds,
    at a font scale put back after; each step's screen captured, then the
    game's, then soa.log and soa.ini pulled as the device has them."""
    p = phone(
        {
            "library": LIBRARY_BOX,
            "pick-library": PICKER,
            "disc": DISC_BOX,
            "pick-disc": PICKER,
            "game": GAME,
        },
        "library",
        {
            ("library", "PICK"): "pick-library",
            ("pick-library", "KEYCODE_BACK"): "library",
            ("pick-library", "libsoa_game.so"): "disc",
            ("disc", "PICK"): "pick-disc",
            ("pick-disc", "GEAE8P.soadisc"): "game",
        },
        log="[android] disc GEAE8P.soadisc: content://x, grant kept\n[window] open at 0,0\n",
        lag=1,
    )
    out = tmp_path / "player"
    argv = ["player", "--serial", "emu", "--timeout", "5", "--fresh", "--font-scale", "1.3"]
    argv += ["--out", str(out)]
    argv += ["--tap", "Pick", "--key", "KEYCODE_BACK", "--tap", "Pick", "--tap", "libsoa_game.so"]
    assert android.main([*argv, "--tap", "Pick", "--tap", "GEAE8P.soadisc"]) == 0
    assert p.taps == [
        ("library", "PICK"),
        ("pick-library", "KEYCODE_BACK"),
        ("library", "PICK"),
        ("pick-library", "libsoa_game.so"),
        ("disc", "PICK"),
        ("pick-disc", "GEAE8P.soadisc"),
    ]
    assert p.lost == []
    assert p.pulled == [
        "01-pick.png",
        "02-keycode-back.png",
        "03-pick.png",
        "04-libsoa-game-so.png",
        "05-pick.png",
        "06-geae8p-soadisc.png",
        "07-game.png",
    ]
    assert all((out / name).is_file() for name in p.pulled)
    c = p.calls
    stop = ("shell", f"am force-stop {android.PACKAGE}")
    fresh = next(x[1] for x in c if x[0] == "run-as" and x[1].startswith("rm -rf "))
    assert set(fresh.split()[2:]) == FRESH
    assert [x for x in c if x[:3] == ("shell", "am", "start")] == [
        ("shell", "am", "start", "-W", "-n", android.COMPONENT)  # not a check run
    ]
    font = c.index(("shell", "settings put system font_scale 1.3"))
    started = c.index(("shell", "am", "start", "-W", "-n", android.COMPONENT))
    last_stop = max(i for i, x in enumerate(c) if x == stop)
    assert font < c.index(stop) < c.index(("run-as", fresh)) < started < last_stop
    assert last_stop < c.index(("run-as", "cat files/soa.log"))
    assert c.index(("run-as", "cat files/soa.ini")) < c.index(
        ("shell", "settings put system font_scale 1.0")
    )
    assert (out / "soa.log").read_bytes() == p.log.encode()
    assert (out / "soa.ini").read_bytes() == b"render = 1\n"


def test_player_waits_for_each_box_to_go_before_the_next_tap(phone, tmp_path):
    """The shortcut's run: "Keep this one" twice, on two boxes with the
    button in the same place and the library loading between them. A tap
    made while the first box is still closing is lost, and the second box
    would never be answered."""
    keep = ("Keep this one", "[1100,800][1400,900]")
    p = phone(
        {
            "library": box(
                "The game library is in place.", ("Pick a new one", "[700,800][1000,900]"), keep
            ),
            "loading": GAME,
            "disc": box("GEAE8P.soadisc is in place.", ("Pick", "[700,800][1000,900]"), keep),
            "game": GAME,
        },
        "library",
        {
            ("library", "Keep this one"): "loading",
            ("loading", None): "disc",
            ("disc", "Keep this one"): "game",
        },
        lag=2,
    )
    argv = ["player", "--serial", "emu", "--timeout", "5", "--reimport", "--after", "0"]
    argv += ["--out", str(tmp_path / "p"), "--tap", "Keep this one", "--tap", "Keep this one"]
    assert android.main(argv) == 0
    assert p.taps == [("library", "Keep this one"), ("disc", "Keep this one")]
    assert p.lost == []
    started = [x for x in p.calls if x[:3] == ("shell", "am", "start")]
    assert started == [
        ("shell", "am", "start", "-W", "-n", android.COMPONENT, "--ez", "soa.reimport", "true")
    ]


def test_a_player_step_that_never_shows_is_captured_where_it_stopped(phone, tmp_path, capsys):
    p = phone({"library": LIBRARY_BOX}, "library", {})
    out = tmp_path / "p"
    argv = ["player", "--serial", "emu", "--out", str(out), "--timeout", "0", "--tap", "Keep"]
    assert android.main(argv) == 1
    assert p.pulled == ["01-stuck.png"]
    assert "'Keep' never showed; the screen shows Choose libsoa_game.so" in capsys.readouterr().out
    assert (out / "soa.log").is_file()
    assert android.main(argv) == 1  # the same folder again: not empty
    assert "is not empty: name another --out" in capsys.readouterr().err


def test_a_player_whose_app_ends_mid_way_says_which_steps_were_never_done(phone, tmp_path, capsys):
    p = phone(
        {"library": LIBRARY_BOX, "gone": GAME},
        "library",
        {("library", "PICK"): "gone"},
        last="gone",
        tail=["", ""],
    )
    argv = ["player", "--serial", "emu", "--out", str(tmp_path / "p"), "--timeout", "5"]
    assert android.main([*argv, "--tap", "Pick", "--tap", "GEAE8P.soadisc"]) == 1
    assert p.pulled == ["01-pick.png", "02-stuck.png"]
    assert (
        "[android] the app ended before 'GEAE8P.soadisc' showed, "
        "so --tap 'GEAE8P.soadisc' was never done\n"
    ) in capsys.readouterr().out
