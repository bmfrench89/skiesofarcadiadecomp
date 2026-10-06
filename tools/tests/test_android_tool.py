"""tools/android.py, the parts that need no device (specs/android.md 3.14, L12c).

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
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import android  # noqa: E402
import player_build  # noqa: E402
import recompile  # noqa: E402
from soa import seam  # noqa: E402
from soa.hle import load_hle  # noqa: E402


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
