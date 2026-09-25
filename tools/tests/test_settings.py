"""runtime/settings.c: the player's soa.ini beside soa.exe (PLAN-60FPS-MODS M5).

A key stands for one README switch and sets it only where the environment has
not, so a command line always overrides a player's file; a key the port does
not know is reported with its line, never dropped in silence; `disc` names the
extracted directory; and SOA_SETTINGS=0 -- which scenario.py, its replay and
perfbench.py all set -- turns the file off, so a player's settings can never
move a check.

settings.c is built alone with a driver that prints what it did; soa.ini is
written beside that driver, which is where settings.c looks.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
const char* settings_load(void);
const char* settings_recorded(char* out, size_t cap);
void settings_record_as(const char* key, const char* value);
int main(int argc, char** argv)
{
    static const char* names[] = {"SOA_RENDER", "SOA_WINDOW", "SOA_SCALE", "SOA_THREADS", "SOA_MODS",
                                  "SOA_CARD", "SOA_PAD_RECORD", "SOA_NOSOUND", "SOA_UNCAP", "SOA_SEED"};
    const char* disc;
    unsigned i;
    char rec[320];
    if (argc > 1 && !strcmp(argv[1], "recorded")) {
        settings_load();
        if (argc > 2) settings_record_as("seed", argv[2]); /* what seed.c says is in effect */
        printf("recorded [%s]\n", settings_recorded(rec, sizeof rec));
        return 0;
    }
    disc = settings_load();
    printf("disc %s\n", disc ? disc : "-");
    for (i = 0; i < sizeof names / sizeof names[0]; i++)
        printf("%s=%s\n", names[i], getenv(names[i]) ? getenv(names[i]) : "-");
    return 0;
}
"""


@pytest.fixture
def driver(tmp_path):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    (tmp_path / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = tmp_path / "settings.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            str(ROOT / "runtime" / "settings.c"),
            str(tmp_path / "driver.c"),
            "/Fo" + str(tmp_path) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=tmp_path,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def run(exe, **env_set):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    got = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    disc = next(
        line.split(" ", 1)[1] for line in proc.stdout.splitlines() if line.startswith("disc ")
    )
    return disc, got, proc.stderr


@needs_msvc
def test_no_file_changes_nothing(driver):
    disc, got, err = run(driver)
    assert disc == "-" and set(got.values()) == {"-"} and err == "", (got, err)


@needs_msvc
def test_each_key_sets_its_switch_and_disc_names_the_directory(driver):
    (driver.parent / "soa.ini").write_text(
        "# a player's file\n"
        "disc = C:\\Games\\Skies\\extracted\n"
        "render = 1\nwindow = 1\nscale = 3\nthreads = 6\nmods = C:\\Games\\mods\n"
        "card = C:\\Games\\card.raw\nrecord = play.pad\nnosound = 1\nuncap = 3300\nseed = 12345\n",
        encoding="utf-8",
    )
    disc, got, err = run(driver)
    assert disc == "C:\\Games\\Skies\\extracted", disc
    assert got == {
        "SOA_RENDER": "1",
        "SOA_WINDOW": "1",
        "SOA_SCALE": "3",
        "SOA_THREADS": "6",
        "SOA_MODS": "C:\\Games\\mods",
        "SOA_CARD": "C:\\Games\\card.raw",
        "SOA_PAD_RECORD": "play.pad",
        "SOA_NOSOUND": "1",
        "SOA_UNCAP": "3300",
        "SOA_SEED": "12345",
    }, got
    assert "10 setting(s) applied, 0 overridden" in err, err


@needs_msvc
def test_the_environment_wins_and_says_so(driver):
    (driver.parent / "soa.ini").write_text("render = 1\nscale = 3\n", encoding="utf-8")
    _, got, err = run(driver, SOA_RENDER="0")
    assert got["SOA_RENDER"] == "0" and got["SOA_SCALE"] == "3", got
    assert "render = 1 is overridden by SOA_RENDER=0 in the environment" in err, err


@needs_msvc
def test_an_unknown_key_is_reported_with_its_line_and_the_rest_still_apply(driver):
    """A typo is the likeliest mistake in a hand-edited file; it is named,
    not swallowed, and does not take the good lines with it."""
    (driver.parent / "soa.ini").write_text("render = 1\nrendr = 1\njust words\n", encoding="utf-8")
    _, got, err = run(driver)
    assert got["SOA_RENDER"] == "1", got
    assert "soa.ini:2: `rendr` is not a setting this port knows" in err, err
    assert "soa.ini:3: `just words` is not `key = value`" in err, err


@needs_msvc
def test_checks_turn_the_file_off(driver):
    (driver.parent / "soa.ini").write_text("render = 1\nmods = x\ndisc = y\n", encoding="utf-8")
    disc, got, err = run(driver, SOA_SETTINGS="0")
    assert disc == "-" and set(got.values()) == {"-"} and err == "", (got, err)


def test_every_check_runs_with_the_file_off():
    """scenario.py's runs and replays and perfbench.py set SOA_SETTINGS=0, so
    a player's soa.ini can never move a pinned hash or a check."""
    scenario = (ROOT / "tools" / "scenario.py").read_text(encoding="utf-8")
    assert scenario.count('"SOA_SETTINGS"] = "0"') == 2, (
        "scenario.py's run and replay must both turn it off"
    )
    assert '"SOA_SETTINGS": "0"' in (ROOT / "tools" / "perfbench.py").read_text(encoding="utf-8")


def test_the_file_is_documented():
    assert "soa.ini" in (ROOT / "README.md").read_text(encoding="utf-8")


def recorded(exe, *in_effect, **env_set) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(exe), "recorded", *in_effect],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return next(ln for ln in proc.stdout.splitlines() if ln.startswith("recorded ["))[10:-1]


@needs_msvc
def test_only_what_changes_the_game_is_recorded(driver):
    """settings_recorded names a recorded setting only when it is set -- from
    the environment or soa.ini -- so a run with none keeps the recording's
    line as it was; the display switches are never in it."""
    assert recorded(driver) == ""
    assert recorded(driver, SOA_SEED="12345", SOA_RENDER="1", SOA_SCALE="3") == "seed=12345"
    (driver.parent / "soa.ini").write_text("seed = 0x3039\nwindow = 1\n", encoding="utf-8")
    assert recorded(driver) == "seed=0x3039"


@needs_msvc
def test_a_recorded_setting_too_long_for_the_line_is_left_out_and_said(driver):
    """No half a value: a replay would read a cut seed as a different seed.
    The driver's buffer is 320 bytes, so a 400-digit value cannot fit."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env["SOA_SEED"] = "9" * 400
    proc = subprocess.run(
        [str(driver), "recorded"], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "recorded []" in proc.stdout, proc.stdout
    assert "[pad] the config line was cut at 0 bytes, before seed" in proc.stderr, proc.stderr


@needs_msvc
def test_the_recording_names_the_seed_in_effect_not_the_text(driver):
    """seed.c says what it pinned, and that is what is recorded: a refused
    value records nothing, and 0x3039 records as the 12345 it is, so a
    replay with either spelling agrees with the recording."""
    assert recorded(driver, "12345", SOA_SEED="0x3039") == "seed=12345"
    assert recorded(driver, "", SOA_SEED="12x") == ""
    assert recorded(driver, SOA_SEED="12x") == "seed=12x"  # the mutation: no owner, the raw text
