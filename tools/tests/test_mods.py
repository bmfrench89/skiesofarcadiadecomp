"""runtime/mod.c: mods as data patches (PLAN-60FPS-MODS M1), with no disc.

A mod is a folder under SOA_MODS with a mod.ini (name, api, the DOL's SHA-1)
and a patches.txt of `trigger address = value [when condition...]` lines. A
mod with any fault is refused whole and says why, with the file and line --
the binding lists drop a misspelled address without a word, and a mod that
silently lost a line would be a mod that silently does something else.

These build mod.c on its own with a driver that plays the game's side: a
fake DOL with one code section, and a script of memory writes and frame ends
on stdin. That the patches do what they say in the game is a run: FINDINGS
"M1" records the encounters-off pair.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]

TEXT_START, TEXT_LEN = 0x80003100, 0x1000

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "mod.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* What cpu.h's accessors can reach: none of it is, since every address a
 * patch may name is memory. */
uint32_t g_watch_addr, g_watch_len;
void watch_hit(CpuState* s, uint32_t e, unsigned n, uint64_t v) { (void)s; (void)e; (void)n; (void)v; }
void gx_pipe_write(CpuState* s, unsigned n, uint64_t v) { (void)s; (void)n; (void)v; }
uint8_t mmio_read8(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
uint32_t mmio_read32(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
void mmio_write8(CpuState* s, uint32_t e, uint8_t v) { (void)s; (void)e; (void)v; }
void mmio_write32(CpuState* s, uint32_t e, uint32_t v) { (void)s; (void)e; (void)v; }

/* mods.exe MODSDIR DOLFILE, then commands on stdin:
 *   set ADDR VALUE     store a word       setb ADDR VALUE   store a byte
 *   frame              one frame end      get ADDR          print a word
 *   report             mod_report()       describe          mod_describe() */
int main(int argc, char** argv)
{
    static CpuState s;
    static uint8_t dol[0x2000];
    char cmd[64];
    unsigned frame = 0, a, v;
    FILE* f = fopen(argv[2], "rb");
    size_t n = fread(dol, 1, sizeof dol, f);
    fclose(f);
    (void)argc;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    printf("loaded %d\n", mod_load(&s, argv[1], dol, n));
    while (scanf("%63s", cmd) == 1) {
        if (!strcmp(cmd, "set") && scanf("%x %x", &a, &v) == 2) mem_w32(&s, a, v);
        else if (!strcmp(cmd, "setb") && scanf("%x %x", &a, &v) == 2) mem_w8(&s, a, (uint8_t)v);
        else if (!strcmp(cmd, "frame")) mod_frame(&s, frame++);
        else if (!strcmp(cmd, "get") && scanf("%x", &a) == 1) printf("%08X=%08X\n", a, mem_r32(&s, a));
        else if (!strcmp(cmd, "report")) { fflush(stdout); mod_report(); fflush(stderr); }
        else if (!strcmp(cmd, "describe")) printf("describe [%s]\n", mod_describe());
    }
    return 0;
}
"""


def fake_dol() -> bytes:
    """A DOL header with one code section at 0x80003100 and one data
    section, and bytes behind them -- enough for mod.c's text check."""
    head = bytearray(0x100)
    head[0x00:0x04] = (0x100).to_bytes(4, "big")  # text 0: file offset
    head[0x48:0x4C] = TEXT_START.to_bytes(4, "big")
    head[0x90:0x94] = TEXT_LEN.to_bytes(4, "big")
    head[0x1C:0x20] = (0x1100).to_bytes(4, "big")  # data 0
    head[0x64:0x68] = (0x80346000).to_bytes(4, "big")
    head[0xAC:0xB0] = (0x100).to_bytes(4, "big")
    return bytes(head) + bytes(range(256)) * 17


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("mods")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "mods.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "mod.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    dol = out / "fake.dol"
    dol.write_bytes(fake_dol())
    return exe, dol


SHA = hashlib.sha1(fake_dol()).hexdigest()
PATCH = "every_frame 0x80346d28 = 0 when scene=6\n"


def mod(root: Path, name: str, patches: str | None = PATCH, ini: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if ini is None:
        ini = f"name = {name}\napi = 1\ndol_sha1 = {SHA}\n"
    (d / "mod.ini").write_text(ini, encoding="utf-8")
    if patches is not None:
        (d / "patches.txt").write_text(patches, encoding="utf-8")
    return d


def play(driver, mods: Path, script: str = "") -> tuple[str, str]:
    exe, dol = driver
    proc = subprocess.run(
        [str(exe), str(mods), str(dol)],
        input=script,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


@needs_msvc
def test_a_good_mod_loads_and_says_so(driver, tmp_path):
    mod(tmp_path, "encounters-off")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert "[mod] loaded encounters-off" in err and "1 patch(es)" in err, err


@needs_msvc
@pytest.mark.parametrize(
    "line, why",
    [
        ("every_frame 0X80346d28 = 0", "is not an address"),
        ("every_frame 0x80346d2 = 0", "is not an address"),
        ("every_frame 80346d28 = 0", "is not an address"),
        ("every_frame 0x080346d28 = 0", "is not an address"),
        ("every_frame 0xcc008000 = 0", "hardware window"),
        ("every_frame 0x81800000 = 0", "outside the console's 24 MB"),
        ("every_frame 0x00346d28 = 0", "outside the console's 24 MB"),
        ("every_frame 0x80346d2a = 0", "not word-aligned"),
        ("every_frame 0x80003100 = 0", "inside the game's code"),
        ("every_frame 0x800040fc = 0", "inside the game's code"),
        ("every_frame 0x80346d28 = 0x1g", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = -1", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 4294967296", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 007", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 0x123456789", "is not a 32-bit value"),
        ("sometimes 0x80346d28 = 0", "is not a trigger"),
        ("every_frame 0x80346d28 0", "a patch is"),
        ("every_frame 0x80346d28 = 0 scene=6", "after the value comes `when`"),
        ("every_frame 0x80346d28 = 0 when", "after the value comes `when`"),
        ("every_frame 0x80346d28 = 0 when zone=1", "is not a condition this port knows"),
        ("every_frame 0x80346d28 = 0 when scene", "is not a condition"),
        ("every_frame 0x80346d28 = 0 when scene=six", "is not a number for scene"),
        ("every_frame 0x80346d28 = 0 when map=11a", "is not a map"),
        ("every_frame 0x80346d28 = 0 when map=116A", "is not a map"),
    ],
)
def test_each_fault_refuses_the_whole_mod_out_loud(driver, tmp_path, line, why):
    """A good line first and the fault second: the mod is refused whole, so
    the good line never applies either, and the message names file and line."""
    mod(tmp_path, "m", patches=f"# a comment\n{PATCH}{line}\n")
    out, err = play(driver, tmp_path, "set 803475cc 6 set 80346d28 1234 frame get 80346d28")
    assert "loaded 0" in out, err
    assert why in err and "patches.txt:3:" in err and "the mod is not loaded" in err, err
    assert "80346D28=00001234" in out, out


@needs_msvc
@pytest.mark.parametrize(
    "ini, why",
    [
        (f"name = m\napi = 2\ndol_sha1 = {SHA}\n", "this port speaks api 1"),
        (f"name = m\napi = 1\ndol_sha1 = {'0' * 40}\n", f"and this is {SHA}"),
        (f"name = m\napi = 1\ndol_sha1 = {SHA}\nauthor = me\n", "is not a mod.ini key"),
        (f"api = 1\ndol_sha1 = {SHA}\n", "no `name = `"),
        (f"name = m\ndol_sha1 = {SHA}\n", "no `api = 1`"),
        ("name = m\napi = 1\n", "no `dol_sha1 = `"),
        (f"name = m\napi = 1\ndol_sha1 = {SHA}\njust words\n", "is not `key = value`"),
    ],
    ids=["api", "other-dol", "unknown-key", "no-name", "no-api", "no-sha", "not-kv"],
)
def test_a_bad_mod_ini_is_refused(driver, tmp_path, ini, why):
    """The DOL check is what the SHA-1 is for: a patch list is addresses, and
    another build of the game puts other things there."""
    mod(tmp_path, "m", ini=ini)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and why in err, err


@needs_msvc
def test_the_sha1_is_the_dol_s(driver, tmp_path):
    """What the refusal quotes is the real SHA-1 of the bytes booted, so a mod
    author can copy it; hashlib agrees with mod.c's own implementation."""
    mod(tmp_path, "m", ini="name = m\napi = 1\ndol_sha1 = 0\n")
    _, err = play(driver, tmp_path)
    assert f"and this is {SHA}" in err, err
    mod(tmp_path, "m", ini=f"name = m\napi = 1\ndol_sha1 = {SHA.upper()}\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err


@needs_msvc
def test_no_patches_and_an_empty_list_are_refused(driver, tmp_path):
    mod(tmp_path / "a", "m", patches=None)
    out, err = play(driver, tmp_path / "a")
    assert "loaded 0" in out and "no patches.txt" in err, err
    mod(tmp_path / "b", "m", patches="# nothing yet\n\n")
    out, err = play(driver, tmp_path / "b")
    assert "loaded 0" in out and "no patches in it" in err, err


@needs_msvc
def test_one_bad_mod_does_not_take_a_good_one_with_it(driver, tmp_path):
    mod(tmp_path, "b-good")
    mod(tmp_path, "a-bad", patches="every_frame 0x80346d29 = 0\n")
    mod(tmp_path, "c-good", patches="once 0x80346d2c = 5\n")
    (tmp_path / "not-a-mod").mkdir()
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 2" in out, err
    # name order, so two runs apply them the same way; the recording names
    # each by folder with a hash of what it holds
    assert "describe [mods=b-good:" in out and ",c-good:" in out, out


@needs_msvc
def test_every_frame_applies_only_while_its_conditions_hold(driver, tmp_path):
    mod(tmp_path, "m")
    script = """
        set 80346d28 1234 set 803475cc 7 frame get 80346d28
        set 803475cc 6 frame get 80346d28
        set 80346d28 99 frame get 80346d28
        set 803475cc 7 set 80346d28 99 frame get 80346d28
        report
    """
    out, err = play(driver, tmp_path, script)
    assert [line for line in out.splitlines() if line.startswith("80346D28")] == [
        "80346D28=00001234",  # battle: not applied
        "80346D28=00000000",  # field: applied
        "80346D28=00000000",  # and again next frame
        "80346D28=00000099",  # battle again: left alone
    ]
    assert "every_frame 80346D28 = 00000000 applied 2 time(s), first at frame 1" in err, err


@needs_msvc
def test_once_applies_the_first_frame_its_conditions_hold(driver, tmp_path):
    mod(tmp_path, "m", patches="once 0x80346d28 = 0x186a0 when state=8\n")
    script = """
        set 80311aec 3 frame get 80346d28
        set 80311aec 8 frame get 80346d28
        set 80346d28 7 frame get 80346d28
    """
    out, _ = play(driver, tmp_path, script)
    got = [line for line in out.splitlines() if line.startswith("80346D28")]
    assert got == ["80346D28=00000000", "80346D28=000186A0", "80346D28=00000007"]


@needs_msvc
def test_on_map_load_fires_once_per_map_entered_and_never_compounds(driver, tmp_path):
    """Keyed on the committed map (0x80311AC0, letter byte at 0x80311AC8),
    once the field is running: the reload after a battle is the same map and
    does not fire again; leaving and coming back does."""
    mod(tmp_path, "m", patches="on_map_load 0x80346d28 = 1 when map=116a\n")

    def at(number, letter, state):
        return f"set 80311ac0 {number:x} setb 80311ac8 {ord(letter):x} set 80311aec {state:x} "

    step = "set 80346d28 0 frame get 80346d28 "
    script = (
        at(116, "a", 3)
        + step  # loading: not yet
        + at(116, "a", 8)
        + step  # running in 116a: fires
        + at(116, "a", 8)
        + step  # still there: no
        + at(116, "a", 3)
        + step  # battle and reload of the same map
        + at(116, "a", 8)
        + step  # same map again: no
        + at(116, "b", 8)
        + step  # another map: condition fails
        + at(116, "a", 8)
        + step  # back in 116a: fires
    )
    out, _ = play(driver, tmp_path, script)
    got = [line[-1] for line in out.splitlines() if line.startswith("80346D28")]
    assert got == ["0", "1", "0", "0", "0", "0", "1"], out


@needs_msvc
def test_a_patch_that_never_applied_says_so(driver, tmp_path):
    mod(tmp_path, "m", patches="every_frame 0x80346d28 = 0 when scene=99\n")
    out, err = play(driver, tmp_path, "frame frame report")
    assert "never applied: its conditions never held" in err, err


@needs_msvc
def test_a_folder_that_is_not_there_says_so(driver, tmp_path):
    out, err = play(driver, tmp_path / "nope")
    assert "loaded 0" in out and "is not a folder this port can read" in err, err


def test_the_example_mod_parses_under_the_documented_grammar():
    """The example in mods/ is what a mod author copies, so it has to be one
    this parser would load: its DOL SHA-1 is the one config.yml pins."""
    ini = (ROOT / "mods" / "encounters-off" / "mod.ini").read_text(encoding="utf-8")
    pinned = next(
        line.split(":", 1)[1].strip()
        for line in (ROOT / "config" / "GEAE8P" / "config.yml").read_text().splitlines()
        if line.startswith("hash:")
    )
    assert f"dol_sha1 = {pinned}" in ini
    patches = (ROOT / "mods" / "encounters-off" / "patches.txt").read_text(encoding="utf-8")
    assert "every_frame 0x80346d28 = 0 when scene=6" in patches


def test_the_switch_is_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`SOA_MODS=" in readme
