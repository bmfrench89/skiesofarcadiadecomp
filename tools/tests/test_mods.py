"""runtime/mod.c: mods as data patches (PLAN-60FPS-MODS M1), with no disc.

A mod is a folder under SOA_MODS with a mod.ini (manifest 2's id and version,
name, api, the DOL's SHA-1)
and a patches.txt of `trigger address = value [when condition...]` lines. A
mod with any fault is refused whole and says why, with the file and line --
the binding lists drop a misspelled address without a word, and a mod that
silently lost a line would be a mod that silently does something else.

These build mod.c on its own with a driver that plays the game's side: a
fake DOL with one code section, and a script of memory writes and frame ends
on stdin. The driver and every test mod are built by the toolchain profile
SOA_CC names (MSVC when it is unset; gcc and clang on CI's Linux legs, where
a mod's library is mod.so), so they run wherever runtime/mod.c does. That the patches do what they say in the game is a run: FINDINGS
"M1" records the encounters-off pair.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import test_memguard  # noqa: F401  (it puts tools/ on the path)

# isort: split
import savext  # noqa: E402  (X2's container, read and built from Python)
from soa import modkit, toolchain  # noqa: E402
from soa.modkit import DRIVER, TEXT_LEN, TEXT_START, fake_dol  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[2]

# The compiler the fake guest and the test mods are built with: SOA_CC's
# profile, MSVC when it is unset. Until 2026-10-14 these were MSVC's alone,
# so 67 of them ran on Windows only; a mod's library is mod.so off Windows.
PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
needs_cc = pytest.mark.skipif(
    toolchain.compiler_path(PROFILE) is None,
    reason=f"no {PROFILE.name}: the fake guest cannot be built here",
)
LIB = modkit.lib_name(PROFILE)

# The fake guest -- DRIVER, the game's side of it, and fake_dol -- lives in
# tools/soa/modkit.py, which tools/mod.py's `check` and `test` build too (T10).


def cc(args: list[str], cwd: Path) -> None:
    """PROFILE's compiler, the arguments in cl's grammar (toolchain.cc)."""
    proc = toolchain.cc(args, cwd, PROFILE)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def build_driver(tmp_path_factory, *defines: str):
    """The fake guest, modkit's, built by PROFILE's compiler."""
    if toolchain.compiler_path(PROFILE) is None:
        pytest.skip(f"no {PROFILE.name}")
    return modkit.build_driver(tmp_path_factory.mktemp("mods"), PROFILE, *defines)


def library(folder: Path, source: Path, *defines: str, include: Path = ROOT / "runtime") -> None:
    """`source` built as a mod's library in `folder`, against the soa_mod.h in
    `include`, with `defines` as /D switches."""
    modkit.build_library(folder, source, PROFILE, *defines, include=include)


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    return build_driver(tmp_path_factory)


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


def play(driver, mods: Path, script: str = "", **env_set) -> tuple[str, str]:
    """One run of the fake guest. The environment is this process's with
    every SOA_ switch taken out, so a mod that reads one sees only what the
    test sets."""
    exe, dol = driver
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(exe), str(mods), str(dol)],
        input=script,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


@needs_cc
def test_a_good_mod_loads_and_says_so(driver, tmp_path):
    mod(tmp_path, "encounters-off")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert "[mod] loaded encounters-off" in err and "1 patch(es)" in err, err


@needs_cc
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


@needs_cc
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


@needs_cc
def test_the_sha1_is_the_dol_s(driver, tmp_path):
    """What the refusal quotes is the real SHA-1 of the bytes booted, so a mod
    author can copy it; hashlib agrees with mod.c's own implementation."""
    mod(tmp_path, "m", ini="name = m\napi = 1\ndol_sha1 = 0\n")
    _, err = play(driver, tmp_path)
    assert f"and this is {SHA}" in err, err
    mod(tmp_path, "m", ini=f"name = m\napi = 1\ndol_sha1 = {SHA.upper()}\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err


@needs_cc
def test_no_patches_and_an_empty_list_are_refused(driver, tmp_path):
    mod(tmp_path / "a", "m", patches=None)
    out, err = play(driver, tmp_path / "a")
    assert "loaded 0" in out and "no patches.txt" in err, err
    mod(tmp_path / "b", "m", patches="# nothing yet\n\n")
    out, err = play(driver, tmp_path / "b")
    assert "loaded 0" in out and "no patches in it" in err, err


@needs_cc
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


@needs_cc
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


@needs_cc
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


@needs_cc
def test_on_map_load_fires_on_every_load_of_its_map(driver, tmp_path):
    """Keyed on the committed map (0x80311AC0, letter byte at 0x80311AC8),
    once the field is running after a load: the reload after a battle puts
    the map's words back as the disc has them, so it fires again (the review
    of 2026-09-25: the old rule left the rest of the stay unpatched); a map
    whose condition fails does not fire; coming back does."""
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
        + step  # running again after the reload: fires
        + at(116, "b", 8)
        + step  # another map: condition fails
        + at(116, "a", 8)
        + step  # back in 116a: fires
    )
    out, _ = play(driver, tmp_path, script)
    got = [line[-1] for line in out.splitlines() if line.startswith("80346D28")]
    assert got == ["0", "1", "0", "0", "1", "0", "1"], out


@needs_cc
def test_a_patch_that_never_applied_says_so(driver, tmp_path):
    mod(tmp_path, "m", patches="every_frame 0x80346d28 = 0 when scene=99\n")
    out, err = play(driver, tmp_path, "frame frame report")
    assert "never applied: its conditions never held" in err, err


@needs_cc
def test_a_folder_that_is_not_there_says_so(driver, tmp_path):
    out, err = play(driver, tmp_path / "nope")
    assert "loaded 0" in out and "is not a folder this port can read" in err, err


def test_the_example_mod_parses_under_the_documented_grammar():
    """The example in examples/mods/ is what a mod author copies, so it has to
    be one this parser would load: its DOL SHA-1 is the one config.yml pins."""
    ini = (ROOT / "examples" / "mods" / "encounters-off" / "mod.ini").read_text(encoding="utf-8")
    pinned = next(
        line.split(":", 1)[1].strip()
        for line in (ROOT / "config" / "GEAE8P" / "config.yml").read_text().splitlines()
        if line.startswith("hash:")
    )
    assert f"dol_sha1 = {pinned}" in ini
    patches = (ROOT / "examples" / "mods" / "encounters-off" / "patches.txt").read_text(
        encoding="utf-8"
    )
    assert "every_frame 0x80346d28 = 0 when scene=6" in patches


def test_the_switch_is_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`SOA_MODS=" in readme


# --------------------------------------------------------------------------
# M6: widths, pointers, runs of targets and *= (PLAN-60FPS-MODS M6), on the
# encounter table's layout (docs/research/encounters.md): the word at
# 0x803474BC points to eight zones of 132 bytes, each one's rate the u16 at +2.
# --------------------------------------------------------------------------

TABLE = 0x80400000  # free RAM in the fake guest, standing in for a map's .ect
POINTER = "803474bc"
RATES = "on_map_load u16 [0x803474bc]+2+z*132 *= {k} for z=0..7\n"


def at_map(number: int, letter: str = "a", state: int = 8) -> str:
    """The field at a map, in a state: loading (3 or 5) or running (8)."""
    return (
        f"set 803475cc 6 set 80311aec {state:x} set 80311ac0 {number:x} "
        f"setb 80311ac8 {ord(letter):x} "
    )


def load(number: int, letter: str = "a", state: int = 3) -> str:
    """A map load as mod.c sees one: a frame loading, then one running."""
    return at_map(number, letter, state) + "frame " + at_map(number, letter) + "frame "


def table(rates: list[int]) -> str:
    """The pointer at a table whose zones' rates are `rates`, each zone's
    stage, the u16 before it, 0x0011."""
    words = (f"set {TABLE + z * 132:x} {0x00110000 | r:x} " for z, r in enumerate(rates))
    return f"set {POINTER} {TABLE:x} " + "".join(words)


def gets() -> str:
    return "".join(f"get {TABLE + z * 132:x} " for z in range(8))


def read_rates(out: str) -> list[list[int]]:
    """Each gets()'s eight rates; every zone's stage must be untouched."""
    words = [int(v, 16) for v in re.findall(r"^8040[0-9A-F]{4}=([0-9A-F]{8})$", out, re.M)]
    assert all(w >> 16 == 0x0011 for w in words), out
    return [[w & 0xFFFF for w in words[i : i + 8]] for i in range(0, len(words), 8)]


@needs_cc
def test_m6_scales_each_zones_rate_once_a_load_and_never_compounds(driver, tmp_path):
    """The eight rates halved at a load, each logged `address: was -> now`.
    A reload that left the table as the patch made it is not halved again --
    the mutation, the patch's memory of what it wrote taken out, halves them
    twice -- and a reload that put the disc's table back is halved once."""
    mod(tmp_path, "rates", patches=RATES.format(k="0.5"))
    disc = [100, 50, 7, 1, 0, 300, 65535, 2]
    script = (
        table(disc)
        + load(116)
        + gets()
        + load(116, state=5)  # back from a battle, the table left as it was
        + gets()
        + table(disc)
        + load(116, state=5)  # back from a battle, the table loaded again
        + gets()
        + "report"
    )
    out, err = play(driver, tmp_path, script)
    first, kept, again = read_rates(out)
    assert first == [50, 25, 3, 0, 0, 150, 32767, 1], out
    assert kept == first and again == first, out
    logged = [ln.split(": ", 1)[1] for ln in err.splitlines() if "rates patches.txt:1: 8040" in ln]
    assert logged[:2] == ["80400002: 0064 -> 0032", "80400086: 0032 -> 0019"], err
    # eight at the first load, and seven at the third: zone 4's rate is 0, and
    # 0 halved is what the patch wrote there already, so it is left alone
    assert len(logged) == 15 and "80400212: 0000 -> 0000" in logged[:8], err
    assert "80400212: 0000 -> 0000" not in logged[8:], err
    assert (
        "rates patches.txt:1: on_map_load u16 [803474BC]+2+z*132 *= 0.5 for z=0..7 applied 2 time(s)"
        in err
    ), err


# T9 (docs/specs/game-names.md): a name wherever an address goes, from
# config/gamedata.txt. party.character is 92-byte records from 0x8030B7F4, hp
# the s16 at +24; party.gold the s32 at 0x8030BB40; battle.context a pointer to
# a record whose gold is the s32 at +52.
BY_NAME = (
    "once party.gold = 1234\n"
    "once party.character[1].hp = 500\n"
    "once battle.context.gold = 77\n"
    "on_map_load encounter.table[z].rate *= 0.5 for z=0..7\n"
)
BY_ADDRESS = (
    "once s32 0x8030bb40 = 1234\n"
    f"once s16 0x{0x8030B7F4 + 92 + 24:08x} = 500\n"
    "once s32 [0x80347390]+52 = 77\n" + RATES.format(k="0.5")
)
CONTEXT = 0x80410000  # where the fake guest's battle context pointer points


@needs_cc
def test_t9_a_name_writes_the_bytes_its_address_does(driver, tmp_path):
    """The same four patches by name and by address, one run each on the same
    script, leave the same words: a scalar, a field of an array's record, a
    field through a pointer, and a run of fields through a pointer. The
    mutation, k_names' party.gold moved, would have the gold word differ."""
    script = (
        table([100, 50, 7, 1, 0, 300, 65535, 2])
        + f"set 80347390 {CONTEXT:x} "
        + load(116)
        + gets()
        + f"get 8030bb40 get {0x8030B7F4 + 92 + 24:x} get {CONTEXT + 52:x} "
        + "report"
    )
    outs = []
    for name, patches in (("byname", BY_NAME), ("byaddress", BY_ADDRESS)):
        root = tmp_path / name
        mod(root, name, patches=patches)
        out, err = play(driver, root, script)
        assert "refused" not in err.lower(), err
        outs.append(re.findall(r"^[0-9A-F]{8}=[0-9A-F]{8}$", out, re.M))
    assert outs[0] == outs[1] and len(outs[0]) == 11, outs
    gold, hp_word, ctx_gold = (int(w.split("=")[1], 16) for w in outs[0][8:])
    assert gold == 1234 and hp_word >> 16 == 500 and ctx_gold == 77, outs[0]


HEADER_SOURCE = r"""
#include "soa_mod.h"
#include "soa_gamedata.h"
#include <stdio.h>

static const SoaModApi* A;

static void sp(void* u)
{
    static int once;
    char b[200];
    int32_t gold = 0, cgold = 0;
    int16_t hp = 0;
    uint16_t rate = 0;
    uint32_t raw = 0;
    int g1, g2, g3, g4, s1;
    (void)u;
    if (once++) return;
    g1 = soa_party_gold_get(A, &gold);
    g2 = soa_battle_context_gold_get(A, &cgold);
    g3 = soa_party_character_hp_get(A, 1, &hp);
    g4 = soa_encounter_table_rate_get(A, 2, &rate);
    s1 = soa_party_gold_set(A, -5);
    A->read32(SOA_PARTY_GOLD, &raw);
    snprintf(b, sizeof b, "gold %d %ld ctx %d %ld hp %d %d rate %d %u set %d %08lX", g1, (long)gold, g2,
             (long)cgold, g3, (int)hp, g4, (unsigned)rate, s1, (unsigned long)raw);
    A->log(b);
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    api->on_safe_point(sp, NULL);
    return 0;
}
"""


@needs_cc
def test_t9_the_header_s_accessors_read_and_write_what_they_name(driver, tmp_path):
    """A DLL built against runtime/soa_gamedata.h reads a scalar, a field of
    an array's record, a field through a pointer and a field of a pointer's
    array, each what the script put there, and writes the gold big-endian."""
    d = mod(tmp_path, "header", patches=None)
    (d / "mod_src.c").write_text(HEADER_SOURCE, encoding="utf-8")
    library(d, d / "mod_src.c")
    script = (
        table([100, 50, 7, 1, 0, 300, 65535, 2])
        + f"set 80347390 {CONTEXT:x} set {CONTEXT + 52:x} 4d "
        + "set 8030bb40 4d2 "
        + f"set {0x8030B7F4 + 92 + 24:x} 1f40000 "
        + "safe"
    )
    out, err = play(driver, tmp_path, script)
    assert "loaded 1" in out, err
    assert "[mod] header: gold 1 1234 ctx 1 77 hp 1 500 rate 1 7 set 1 FFFFFFFB" in err, err


@needs_cc
@pytest.mark.parametrize(
    "line",
    [
        "once party.goldd = 1",  # no such name
        "once party.character.hp = 1",  # an array's field without its index
        "once party.gold[2] = 1",  # an index where none goes
    ],
)
def test_t9_a_name_the_game_s_data_lacks_is_refused_with_its_line(driver, tmp_path, line):
    mod(tmp_path, "unknown", patches=line + "\n")
    _, err = play(driver, tmp_path, "frame report")
    assert "unknown/patches.txt:1:" in err and "is not a name the game's data has" in err, err


@needs_cc
def test_m6_writes_each_width_at_its_own_bytes_big_endian(driver, tmp_path):
    mod(
        tmp_path,
        "widths",
        patches=(
            "once u8 0x80346d29 = 0xaa\n"
            "once u16 0x80346d2e = 0xbeef\n"
            "once s16 0x80346d30 = -2\n"
            "once s8 0x80346d37 = -128\n"
            "every_frame u16 0x80346d38+z*2 = 0x0102 for z=0..3\n"
        ),
    )
    script = (
        "set 80346d28 11223344 set 80346d2c 55667788 set 80346d30 99aabbcc "
        "set 80346d34 ddeeff00 frame "
        "get 80346d28 get 80346d2c get 80346d30 get 80346d34 get 80346d38 get 80346d3c"
    )
    out, err = play(driver, tmp_path, script)
    for word in ("11AA3344", "5566BEEF", "FFFEBBCC", "DDEEFF80"):
        assert word in out, out
    assert "80346D38=01020102" in out and "80346D3C=01020102" in out, out
    assert " -> " not in err, err  # only a map load's M6 patches log what they wrote


@needs_cc
def test_m6_multiplies_clamped_to_the_width_signed_or_not(driver, tmp_path):
    mod(
        tmp_path,
        "clamp",
        patches=(
            "on_map_load u8 0x80346d28 *= 2\n"  # 0x90 -> 0xff, clamped
            "on_map_load s8 0x80346d29 *= 2\n"  # 80 -> 127
            "on_map_load s8 0x80346d2a *= 2\n"  # -80 -> -128
            "on_map_load s16 0x80346d2c *= 0.25\n"  # -100 -> -25, toward zero
            "on_map_load u32 0x80346d30 *= 1.5\n"  # 3 -> 4
            "on_map_load u16 0x80346d34 *= 0\n"
        ),
    )
    script = (
        "set 80346d28 9050b000 set 80346d2c ff9c1234 set 80346d30 3 set 80346d34 ffff5678 "
        + load(116)
        + "get 80346d28 get 80346d2c get 80346d30 get 80346d34"
    )
    out, _ = play(driver, tmp_path, script)
    for word in (
        "80346D28=FF7F8000",
        "80346D2C=FFE71234",
        "80346D30=00000004",
        "80346D34=00005678",
    ):
        assert word in out, out


@needs_cc
def test_m6_passes_over_a_null_pointer_the_world_map_and_a_target_in_code(driver, tmp_path):
    """A map with no table has a null pointer; map 099 keeps a table of its
    own; a pointer into the game's code is never written through. Each is
    passed over, the last two said once, and the report says why the patch
    never applied."""
    mod(tmp_path, "rates", patches=RATES.format(k="2"))
    script = (
        f"set {POINTER} 0 "
        + load(116)
        + table([1] * 8)
        + load(99, "a")
        + load(99, "a")
        + gets()
        + f"set {POINTER} 80003100 "
        + load(117)
        + load(118)
        + "report"
    )
    out, err = play(driver, tmp_path, script)
    assert read_rates(out) == [[1] * 8], out
    assert err.count("not applied on map 099") == 1, err
    assert err.count("in the game's code: not written") == 1, err
    report = next(ln for ln in err.splitlines() if "never applied" in ln)
    assert (
        "its pointer was null 1 time(s); passed over on map 099; a target it may not write passed over"
        in report
    ), report


@needs_cc
@pytest.mark.parametrize(
    "line, why",
    [
        ("every_frame u8 0x80346d28 = 256", "is not a value a u8 holds"),
        ("every_frame s8 0x80346d28 = 128", "is not a value a s8 holds"),
        ("every_frame s8 0x80346d28 = -129", "is not a value a s8 holds"),
        ("every_frame u16 0x80346d29 = 1", "is not aligned for a u16"),
        ("every_frame u32 0x80346d2a = 1", "not word-aligned"),
        ("every_frame u16 [0x803474bc]+2 *= 2", "runs once a map load"),
        ("on_map_load u16 0x80346d28 *= 65536", "is not a factor"),
        ("on_map_load u16 0x80346d28 *= 0.12345", "is not a factor"),
        ("on_map_load u16 0x80346d28 *= 05", "is not a factor"),
        ("on_map_load u16 0x80346d28 *= 2.", "is not a factor"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= 2", "no `for z=A..B`"),
        ("on_map_load u16 [0x803474bc]+2 *= 2 for z=0..7", "has none"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= 2 for z=0..64", "more than 64 targets"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= 2 for z=7..0", "`for` takes z=A..B"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= 2 for 0..7", "`for` takes z=A..B"),
        ("on_map_load u16 [0x803474bd]+2 = 1", "a pointer is a whole 32-bit word"),
        ("on_map_load u16 [0x803474bc]+3 = 1", "cannot start on"),
        ("on_map_load u16 [0x803474bc]+2+z*131 = 1 for z=0..7", "cannot start on"),
        (
            "on_map_load u16 [0x803474bc]+2 = 1 when map=099a",
            "map 099 keeps its encounter table apart",
        ),
        ("on_map_load u16 [0x803474bc]+0x1000000 = 1", "is not an address"),
        ("every_frame u32 0x80346d28+4 = 1", "is not an address"),
        ("every_frame u32 0x80346d28+z*4 = 1 for z=0..2 when", "after the value comes `when`"),
        ("every_frame u16 0x80003100 = 1", "inside the game's code"),
        ("every_frame u8 0x800030fc+z*1 = 1 for z=0..7", "inside the game's code"),
        ("every_frame u32 0x817ffff0+z*4 = 1 for z=0..7", "runs outside the console's 24 MB"),
        ("every_frame u64 0x80346d28 = 1", "`u64` is not a width"),
        ("every_frame [0xcc008000] = 1", "hardware window"),
    ],
)
def test_m6_each_fault_refuses_the_mod_out_loud(driver, tmp_path, line, why):
    mod(tmp_path, "bad", patches=line + "\n")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and why in err, err


@needs_cc
def test_the_m6_example_halves_the_rates(driver, tmp_path):
    """examples/mods/encounter-scale is the grammar's example: it parses
    under the DOL config.yml pins and does what its comment says."""
    src = ROOT / "examples" / "mods" / "encounter-scale"
    pinned = next(
        line.split(":", 1)[1].strip()
        for line in (ROOT / "config" / "GEAE8P" / "config.yml").read_text().splitlines()
        if line.startswith("hash:")
    )
    ini = (src / "mod.ini").read_text(encoding="utf-8")
    assert f"dol_sha1 = {pinned}" in ini
    d = tmp_path / "encounter-scale"
    d.mkdir()
    (d / "mod.ini").write_text(ini.replace(pinned, SHA), encoding="utf-8")
    (d / "patches.txt").write_text(
        (src / "patches.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out, err = play(driver, tmp_path, table([40] * 8) + load(116) + gets())
    assert "loaded 1" in out, err
    assert read_rates(out) == [[20] * 8], out


# --------------------------------------------------------------------------
# M3: mod.dll on SoaModApi. Each test DLL is built here from one source with
# a few switches, against runtime/soa_mod.h, the header a mod author uses.
# --------------------------------------------------------------------------

DLL_SOURCE = r"""
#include "soa_mod.h"
#include <stdio.h>
#include <string.h>

#ifndef RC
#define RC 0
#endif
#ifndef INIT
#define INIT soa_mod_init
#endif

static const SoaModApi* A;
static char b[160];

static void fe(void* u) { uint32_t v; (void)u; if (A->read32(0x80346D28, &v)) A->write32(0x80346D28, v + 1); }
static void sp(void* u) { (void)u; snprintf(b, sizeof b, "safe point, scene %u", A->scene()); A->log(b); }
static void ml(void* u, uint32_t map) { (void)u; snprintf(b, sizeof b, "map loaded %08X", map); A->log(b); }
static void sc(void* u, uint32_t f, uint32_t t) { (void)u; snprintf(b, sizeof b, "scene %u -> %u", f, t); A->log(b); }
#ifdef PROJ
/* a wider view: perspective x scaled by 3/4, orthographic (the 2D layer) left alone */
static void wide(void* u, float p[6], int ortho) { (void)u; if (!ortho) p[0] *= 0.75f; }
#endif
#ifdef TEX
/* textures whose hash ends in TEX become a 2x2 of one colour; the rest stay */
static const uint8_t k_img[16] = {TEX, 0, 0, 255, TEX, 0, 0, 255, TEX, 0, 0, 255, TEX, 0, 0, 255};
static int tex(void* u, uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h, const uint8_t* rgba, SoaImage* out)
{
    (void)u; (void)fmt; (void)w; (void)h; (void)rgba;
    if ((hash & 0xFF) != 0x42) return 0;
#ifdef BIG
    out->w = 5000; out->h = 5000; out->rgba = k_img; /* refused before it is read */
#else
    out->w = 2; out->h = 2; out->rgba = k_img;
#endif
    return 1;
}
#endif
#ifdef LATE
/* registers a pad filter from a frame end, after soa_mod_init has returned */
static void late_pad(void* u, uint32_t f, SoaPad* p) { (void)u; (void)f; p->buttons = 0; }
static void late(void* u)
{
    static int once;
    (void)u;
    if (once++) return;
    snprintf(b, sizeof b, "late registration %d", A->pad_filter(late_pad, NULL));
    A->log(b);
}
#endif
#ifdef CALL
static void callsp(void* u)
{
    uint32_t two[2] = {40, 2}, r = 0;
    int ok;
    (void)u;
    ok = A->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL);
    snprintf(b, sizeof b, "call at safe point %d -> %u", ok, r);
    A->log(b);
    ok = A->call_guest(0x80003104u, two, 2, NULL, 0, &r, NULL);
    snprintf(b, sizeof b, "call mid-function %d", ok);
    A->log(b);
}
static void callfe(void* u)
{
    uint32_t two[2] = {1, 1}, r = 0;
    (void)u;
    snprintf(b, sizeof b, "call at frame end %d", A->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL));
    A->log(b);
}
#endif
#ifdef READPAD
/* pad 2 at each frame end; ports 1 and 3 must say nothing is there */
static void padfe(void* u)
{
    SoaPad p;
    int one = A->read_pad(1, &p), three = A->read_pad(3, &p), two = A->read_pad(2, &p);
    (void)u;
    snprintf(b, sizeof b, "read_pad 1:%d 3:%d 2:%d %04X", one, three, two, p.buttons);
    A->log(b);
}
#endif
#ifdef HOST
/* the host buttons at each frame end, when the port's table has them */
static void hostfe(void* u) { (void)u; snprintf(b, sizeof b, "host %X", A->host_buttons()); A->log(b); }
#endif
#ifdef PADF
/* from frame 10, START never reaches the game; everything else does */
static void pf(void* u, uint32_t frame, SoaPad* p) { (void)u; if (frame >= 10) p->buttons &= ~SOA_PAD_START; }
#endif

SOA_MOD_EXPORT int INIT(const SoaModApi* api, uint32_t version)
{
    uint32_t v = 0;
    uint8_t c = 0;
    float x = 0.0f;
    A = api;
    snprintf(b, sizeof b, "init version %u size %u", version, api->size);
    api->log(b);
    /* refused: code, the hardware window, unaligned, past RAM, a bulk write over code, below RAM */
    snprintf(b, sizeof b, "refusals %d%d%d%d%d%d", api->write32(0x80003100u, 1), api->write32(0xCC008000u, 1),
             api->read32(0x80346D2Au, &v), api->read32(0x81800000u, &v),
             api->write_bytes(0x800030F0u, "abcdefghijklmnopqrst", 20), api->read8(0x7FFFFFFFu, &c));
    api->log(b);
    /* big-endian, as the console keeps it; floats as their bits */
    api->write32(0x80346D20u, 0x11223344u);
    api->read8(0x80346D20u, &c);
    api->write_f32(0x80346D24u, 1.5f);
    api->read32(0x80346D24u, &v);
    api->read_f32(0x80346D24u, &x);
    snprintf(b, sizeof b, "bytes %02X float %08X %.2f", c, v, x);
    api->log(b);
    api->write32(0x80310BBCu, 2u); /* flag 1025: bit 1 of the word at 0x80310B3C + 32 * 4 */
    snprintf(b, sizeof b, "flags %d %d", api->story_flag(1025), api->story_flag(1024));
    api->log(b);
    api->on_frame_end(fe, NULL);
    api->on_safe_point(sp, NULL);
    api->on_map_loaded(ml, NULL);
    api->on_scene_change(sc, NULL);
#ifdef PADF
    api->pad_filter(pf, NULL);
#endif
#ifdef CALL
    {
        uint32_t two[2] = {2, 3}, r = 0;
        snprintf(b, sizeof b, "call in init %d", api->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL));
        api->log(b);
    }
    api->on_safe_point(callsp, NULL);
    api->on_frame_end(callfe, NULL);
#endif
#ifdef LATE
    api->on_frame_end(late, NULL);
#endif
#ifdef HOST
    if (api->size >= SOA_MOD_HAS(host_buttons)) api->on_frame_end(hostfe, NULL);
#endif
#ifdef READPAD
    if (api->size >= SOA_MOD_HAS(read_pad)) api->on_frame_end(padfe, NULL);
#endif
#ifdef PROJ
    api->projection_filter(wide, NULL);
#endif
#ifdef TEX
    api->texture_provider(tex, NULL);
#endif
    return RC;
}
"""


def dll(tmp_path: Path, name: str, *defines: str, patches: str | None = None) -> Path:
    """A mod folder holding mod.ini and a library built from DLL_SOURCE."""
    d = mod(tmp_path, name, patches=patches)
    (d / "mod_src.c").write_text(DLL_SOURCE, encoding="utf-8")
    library(d, d / "mod_src.c", *defines)
    return d


@needs_cc
def test_a_mod_dll_loads_and_the_api_refuses_what_a_patch_would(driver, tmp_path):
    """The same refusals as a patches.txt line, made at the call: code,
    the hardware window, unaligned, outside RAM, a bulk write over code.
    Memory is big-endian as the console keeps it."""
    dll(tmp_path, "native")
    out, err = play(driver, tmp_path, "get 80346D20")
    assert "loaded 1" in out, err
    assert "loaded native (" in err and f"and {LIB}" in err, err
    assert "[mod] native: init version 1 size " in err, err
    assert "[mod] native: refusals 000000" in err, err
    assert "[mod] native: bytes 11 float 3FC00000 1.50" in err, err
    assert "[mod] native: flags 1 0" in err, err
    assert "80346D20=11223344" in out, out


@needs_cc
def test_the_callbacks_fire_where_they_say(driver, tmp_path):
    """on_frame_end from the frame hook; on_safe_point, a scene change, and a
    map load -- the field running after a load state -- from the top of the
    loop. A reload of the same map after a battle is a load too."""
    dll(tmp_path, "native")

    def at(scene, state, number=116, letter="a"):
        return (
            f"set 803475cc {scene:x} set 80311aec {state:x} "
            f"set 80311ac0 {number:x} setb 80311ac8 {ord(letter):x} safe "
        )

    script = (
        "set 80346d28 5 frame frame get 80346d28 "
        + at(6, 3)  # loading
        + at(6, 8)  # running: a map load
        + at(6, 8)  # still running: nothing
        + at(7, 9)  # battle: a scene change
        + at(6, 5)  # the field reloading
        + at(6, 8)  # running again: the same map, loaded again
        + "report"
    )
    out, err = play(driver, tmp_path, script)
    assert "80346D28=00000007" in out, out  # two frame ends, each adding one
    loads = [line for line in err.splitlines() if "map loaded" in line]
    assert loads == ["[mod] native: map loaded 00007461"] * 2, err
    assert "[mod] native: scene 6 -> 7" in err and "[mod] native: scene 7 -> 6" in err, err
    assert err.count("[mod] native: safe point") == 6, err
    assert "[mod] the safe point saw 2 map load(s)" in err, err
    assert f"[mod] native {LIB}: 4 callback(s)" in err, err


@needs_cc
def test_a_dll_that_refuses_itself_takes_its_callbacks_and_patches_with_it(driver, tmp_path):
    dll(tmp_path, "shy", "RC=3", patches=PATCH)
    out, err = play(driver, tmp_path, "set 803475cc 6 set 80346d28 1234 frame safe get 80346d28")
    assert "loaded 0" in out, err
    assert "its soa_mod_init refused, returning 3" in err, err
    assert "80346D28=00001234" in out and "safe point" not in err, err


@needs_cc
def test_a_dll_without_the_export_is_refused(driver, tmp_path):
    dll(tmp_path, "mute", "INIT=something_else")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "it exports no soa_mod_init" in err, err


@needs_cc
def test_a_dll_mod_is_named_in_the_recording_with_its_bytes(driver, tmp_path):
    """The hash covers mod.dll, so a rebuilt DLL is a different mod to a
    recording made with the old one."""
    d = dll(tmp_path, "native")
    first, _ = play(driver, tmp_path, "describe")
    (d / LIB).write_bytes((d / LIB).read_bytes() + b"\0")
    second, _ = play(driver, tmp_path, "describe")
    h1 = first.split("describe [mods=native:")[1][:8]
    h2 = second.split("describe [mods=native:")[1][:8]
    assert h1 != h2, (first, second)


@needs_cc
def test_the_example_dll_builds_and_loads(driver, tmp_path):
    """examples/mods/map-log is the template a mod author copies: it has to
    build against runtime/soa_mod.h and load under this port."""
    d = tmp_path / "map-log"
    d.mkdir()
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "map-log" / "mod.c")
    script = (
        "set 803475cc 6 set 80311aec 3 safe set 80311aec 8 set 80311ac0 74 setb 80311ac8 61 safe"
    )
    out, err = play(driver, tmp_path, script)
    assert "loaded 1" in out, err
    assert "[mod] map-log: map-log loaded" in err and "[mod] map-log: entered a116a" in err, err


def lab(tmp_path: Path) -> Path:
    """examples/mods/lab (docs/specs/reach.md U0), built into tmp_path/lab
    with the fake DOL's hash in its mod.ini."""
    d = tmp_path / "lab"
    d.mkdir()
    ini = (ROOT / "examples" / "mods" / "lab" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "lab" / "mod.c")
    return d


@needs_cc
def test_the_lab_follows_a_pointer_chain_and_logs_each_change(driver, tmp_path):
    """`0x80347390*+56` is the word the pointer at 0x80347390 names, plus 56:
    the battle's inventory copy. It is logged at the first read and again only
    when it changes, inside its frames; a peek of one frame reads once."""
    lab(tmp_path)
    script = (
        "set 80347390 80400000 set 80400038 00f00105 safe frame safe "
        "set 80400038 ffff0000 frame safe frame safe frame safe"
    )
    chain = "peek:0-2:0x80347390*+56"
    out, err = play(driver, tmp_path, script, SOA_LAB=f"{chain};peek:0:0x80347390")
    assert "loaded 1" in out, err
    lines = [x for x in err.splitlines() if x.startswith("[mod] lab: peek ")]
    assert lines == [
        f"[mod] lab: peek {chain}: frame 0: 80400038 = 00F00105",
        "[mod] lab: peek peek:0:0x80347390: frame 0: 80347390 = 80400000",
        f"[mod] lab: peek {chain}: frame 2: 80400038 = FFFF0000",
    ], err


@needs_cc
def test_the_lab_starts_an_entry_only_where_the_a_press_could(driver, tmp_path):
    """An entry waits, saying why each time the reason changes: outside the
    running field, while flag 1087 (an event) is set, and while no live hit
    volume carries its id. With one there it asks the game's own condition,
    fn_8021067C, which the fake guest does not have, so the call is refused
    out loud and nothing is started."""
    lab(tmp_path)
    script = (
        "set 803475cc 7 safe "
        "set 803475cc 6 set 80311aec 8 set 80310bc0 80000000 safe "
        "set 80310bc0 0 safe "
        "set 80347524 80400100 set 80400108 fa5 set 80400114 ffff0000 safe "
        "set 80400114 0 safe"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="entry:0:4005")
    assert "loaded 1" in out, err
    waits = [x.split(": ", 3)[-1] for x in err.splitlines() if "lab: entry 4005: waiting" in x]
    assert waits == [
        "the field is not running",
        "an event runs (flag 1087)",
        "no live hit volume has this id",
    ], err
    assert "call_guest(8021067C) refused" in err, err
    assert "started" not in err, err


@needs_cc
def test_the_lab_holds_only_the_standing_partys_hp_and_only_in_battle(driver, tmp_path):
    """hold-hp: in scene 7, a party actor still standing (status & 0x2100
    clear) has HP put back to its maximum; one who is out is left out, an
    empty slot is passed over, the field is never touched, and the battle's
    top-ups are counted when it ends."""
    lab(tmp_path)
    actors = (
        "set 80309de4 80400000 set 80309de8 80400200 set 80309dec 0 set 80309df0 0 "
        "set 80400014 5 set 80400018 64 set 8040001c 0 "
        "set 80400214 7 set 80400218 32 set 8040021c 2000 "
    )
    script = (
        actors + "set 803475cc 6 safe get 80400014 "
        "set 803475cc 7 safe get 80400014 get 80400214 "
        "set 80400014 9 safe get 80400014 set 803475cc 6 safe"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="hold-hp:0-100")
    assert "loaded 1" in out, err
    reads = [x for x in out.splitlines() if x.startswith("80400")]
    assert reads == [
        "80400014=00000005",  # the field: untouched
        "80400014=00000064",  # standing: 5 -> 100
        "80400214=00000007",  # out (0x2000): left at 7
        "80400014=00000064",  # hit again, held again
    ], out
    assert "hold-hp: the battle ended by frame 0; 2 top-up(s)" in err, err


@needs_cc
def test_the_lab_holds_the_players_ship_in_a_ship_battle(driver, tmp_path):
    """hold-hp on a 5xx stage: the ship record the driver takes B[261] from
    (the one of *0x8034729C at 0x80308EF8 whose *(*(rec)+36)+378 halfword
    is the id at 0x803472B0) and the ship object's HP (*0x8034727C+32, +24
    against +20) go back to their maximum; another ship's record is left
    alone; the top-ups are counted when the stage is left."""
    lab(tmp_path)
    ships = (
        "set 8034729c 2 set 803472b0 7 "
        # record 0: id 7, ours (q + 378 = 0x80400100 + 0x17A, the halfword's word at 0x80400278)
        "set 80308ef8 80400000 set 80400024 80400100 set 80400278 7 "
        "set 80308f00 64 set 80308f04 7b2 "  # HP 100 of 1970
        "set 80308f0c 80400400 set 80400424 80400500 set 80400678 9 "  # record 1: the enemy
        "set 80308f14 32 set 80308f18 7b2 "
        "set 8034727c 80400200 set 80400220 80400300 set 80400314 7b2 set 80400318 32 "
    )
    script = (
        ships + "set 803475cc 6 set 80311aec 8 set 80311ac0 1f5 setb 80311ac8 61 safe "
        "get 80308f00 get 80308f14 get 80400318 "
        "set 80311ac0 4 frame safe"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="hold-hp:0-100")
    assert "loaded 1" in out, err
    reads = [x for x in out.splitlines() if x.startswith(("80308F", "80400318"))]
    assert reads == ["80308F00=000007B2", "80308F14=00000032", "80400318=000007B2"], out
    assert (
        "hold-hp: a ship battle from frame 0: the player's ship's HP is held at its maximum" in err
    ), err
    assert "hold-hp: the battle ended by frame 1; 2 top-up(s)" in err, err


@needs_cc
def test_the_lab_wanders_its_map_for_the_fields_own_encounters(driver, tmp_path):
    """wander:F-G:MAP holds the stick one way, then a quarter turn on, every
    90 frames, while MAP's field is free: a017a, the deserted island, goes on
    only once Vyse has gathered the meat its battles drop, and the walker
    never moves the player. Not during an event, nor on another map, nor
    over the person's own press."""
    lab(tmp_path)
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 11 setb 80311ac8 61 "
        "padall 100 0 padall 200 0 "  # legs 1 and 2
        "set 80310bc0 80000000 padall 300 0 set 80310bc0 0 "  # an event: left alone
        "padall 400 100 "  # the person's A: left alone
        "setb 80311ac8 62 padall 500 0"  # a017b: left alone
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="wander:0-1000:017a")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("padall")] == [
        "padall 100 00 00 FF 80 33 44 55 66",
        "padall 200 00 00 80 00 33 44 55 66",
        "padall 300 00 00 11 22 33 44 55 66",
        "padall 400 00 01 11 22 33 44 55 66",
        "padall 500 00 00 11 22 33 44 55 66",
    ], out
    assert "wander: on a017a from frame 100, a quarter turn every 90 frames" in err, err


@needs_cc
def test_the_lab_finishes_a_battle_that_has_gone_on_too_long_once(driver, tmp_path):
    """finish:F-G:FRAMES: in scene 7, once the battle has gone FRAMES frames,
    each enemy still standing (slots 4 to 11) goes to 1 HP and is held
    there, a heal put back; one already out, one at 1 and the party are left
    alone; said once a battle, the put-backs counted at its end, and again
    in the next one."""
    lab(tmp_path)
    actors = (
        "set 80309de4 80400000 set 80400014 64 "  # the party's slot 0: 100 HP
        "set 80309df4 80400100 set 80400114 1388 "  # slot 4: 5000 HP
        "set 80309df8 80400200 set 80400214 50 set 8040021c 2000 "  # slot 5: out
        "set 80309dfc 80400300 set 80400314 1 "  # slot 6: 1 HP already
    )
    script = (
        actors + "set 803475cc 7 safe frame frame safe get 80400114 "  # 2 frames in: not yet
        "frame safe get 80400114 get 80400014 get 80400214 "  # 3: finished
        "set 80400114 1388 frame safe get 80400114 "  # healed: put back
        "set 803475cc 6 frame safe set 803475cc 7 set 80400114 1388 frame safe get 80400114 "
        "frame frame frame safe get 80400114"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="finish:0-100:3")
    assert "loaded 1" in out, err
    reads = [x for x in out.splitlines() if x.startswith("80400")]
    assert reads == [
        "80400114=00001388",
        "80400114=00000001",
        "80400014=00000064",
        "80400214=00000050",
        "80400114=00000001",  # a heal, put back
        "80400114=00001388",  # the next battle, 1 frame in
        "80400114=00000001",  # 3 frames in
    ], out
    lines = [x.split("lab: ", 1)[1] for x in err.splitlines() if "lab: finish:" in x]
    assert lines == [
        "finish: the battle from frame 0 has gone 3 frames: 1 enemy(s) held at 1 HP from now, "
        "so the game's own next blows end it",
        "finish: the battle ended by frame 5; 1 enemy HP put back to 1",
        "finish: the battle from frame 6 has gone 3 frames: 1 enemy(s) held at 1 HP from now, "
        "so the game's own next blows end it",
    ], err


@needs_cc
def test_the_lab_finishes_a_ship_battle_that_has_gone_on_too_long(driver, tmp_path):
    """finish on a 5xx stage: once the ship battle has gone FRAMES frames, the
    enemy ship's record (the one of *0x8034729C at 0x80308EF8 whose
    *(*(rec)+36)+378 halfword is the id at 0x803472AC, B[262]'s source) and
    its object (*0x8034727C+36, +24) go to 1 HP and are held there, a repair
    put back; the player's record is left alone, and so is an enemy already
    at 0. Part G's gunboat lost half its HP bar in 100,000 frames (u4-G19)."""
    lab(tmp_path)
    ships = (
        "set 8034729c 2 set 803472b0 7 set 803472ac 9 "
        "set 80308ef8 80400000 set 80400024 80400100 set 80400278 7 "  # record 0: ours, id 7
        "set 80308f00 64 set 80308f04 7b2 "
        "set 80308f0c 80400400 set 80400424 80400500 set 80400678 9 "  # record 1: the enemy, id 9
        "set 80308f14 1388 set 80308f18 1388 "  # 5000 of 5000
        "set 8034727c 80400200 set 80400224 80400300 set 80400318 1388 "  # the enemy's object: 5000
    )
    script = (
        ships + "set 803475cc 6 set 80311aec 8 set 80311ac0 209 setb 80311ac8 61 safe "  # a521a
        "frame safe get 80308f14 "  # 1 frame in: not yet
        "frame safe get 80308f14 get 80400318 get 80308f00 "  # 2: held
        "set 80308f14 c8 frame safe get 80308f14 "  # repaired: put back
        "set 80308f14 0 frame safe get 80308f14 "  # sunk: left alone
        "set 80311ac0 4 frame safe"  # the stage left
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="finish:0-100:2")
    assert "loaded 1" in out, err
    reads = [x for x in out.splitlines() if x.startswith(("80308F", "80400318"))]
    assert reads == [
        "80308F14=00001388",
        "80308F14=00000001",
        "80400318=00000001",
        "80308F00=00000064",
        "80308F14=00000001",
        "80308F14=00000000",
    ], out
    lines = [x.split("lab: ", 1)[1] for x in err.splitlines() if "lab: finish:" in x]
    assert lines == [
        "finish: the ship battle from frame 0 has gone 2 frames: the enemy ship held at 1 HP from now "
        "(its record and object), so the crew's next hit ends it",
        "finish: the battle ended by frame 5; 1 enemy HP put back to 1",
    ], err


@needs_cc
def test_the_lab_sinks_a_ship_battles_enemy_no_hit_reaches(driver, tmp_path):
    """An enemy ship held at 1 HP for FRAMES frames more with no hit sinking it
    goes to 0, record and object, said once: a525a's Tenkou Spellship flies
    above where the part card's Prototype Cannons reach. One the crew has
    sunk meanwhile is not sunk again."""
    lab(tmp_path)
    ships = (
        "set 8034729c 2 set 803472b0 7 set 803472ac 9 "
        "set 80308ef8 80400000 set 80400024 80400100 set 80400278 7 "
        "set 80308f00 64 set 80308f04 7b2 "
        "set 80308f0c 80400400 set 80400424 80400500 set 80400678 9 "
        "set 80308f14 61a8 set 80308f18 61a8 "  # 25000 of 25000
        "set 8034727c 80400200 set 80400224 80400300 set 80400318 61a8 "
    )
    script = (
        ships + "set 803475cc 6 set 80311aec 8 set 80311ac0 20d setb 80311ac8 61 safe "  # a525a
        "frame frame safe get 80308f14 "  # 2: held at 1
        "frame safe get 80308f14 "  # 3: still held
        "frame safe get 80308f14 get 80400318 "  # 4: 2 frames at 1, no hit: sunk
        "set 80308f14 1 frame safe get 80308f14"  # sunk once only
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="finish:0-100:2")
    assert "loaded 1" in out, err
    reads = [x for x in out.splitlines() if x.startswith(("80308F", "80400318"))]
    assert reads == [
        "80308F14=00000001",
        "80308F14=00000001",
        "80308F14=00000000",
        "80400318=00000000",
        "80308F14=00000001",
    ], out
    sunk = [x.split("lab: ", 1)[1] for x in err.splitlines() if "with no hit sinking it" in x]
    assert sunk == [
        "finish: the enemy ship has stood at 1 HP for 2 frames with no hit sinking it: sunk at frame 4, in place "
        "of a weapon that reaches it (the part card's Delphinus carries Prototype Cannons only)"
    ], err


@needs_cc
def test_the_lab_plays_a_members_turn_once_a_battle_and_logs_the_commands(driver, tmp_path):
    """turn:F-G:M:SEQ waits for member M's input (scene 7, phase 1, the member
    word M), holds 60 frames of nothing while the wheel turns in, then each
    press for 10 frames with 60 after; what SOA_PAD presses meanwhile is held
    back. Once a battle: M's next input is the person's. At the phase 1 -> 2
    edge the members' command types are logged."""
    lab(tmp_path)
    script = (
        "set 803475cc 7 set 8034733c 1 set 80347330 1 safe pad 90 0100 "  # member 1: not ours
        "set 80347330 0 pad 100 0100 pad 165 0000 pad 175 0000 pad 230 0000 pad 300 0100 "
        "pad 400 0100 "  # done for this battle: passed through
        "set 80309174 5 set 8034733c 2 pad 410 0000 "
        "set 803475cc 6 pad 500 0000 set 803475cc 7 set 8034733c 1 pad 600 0000"  # a new battle
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="turn:0-1000:0:left/a")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 90 0100 filtered",  # another member's input
        "pad 100 0000 filtered",  # the lead-in
        "pad 165 0001 filtered",  # left
        "pad 175 0000 filtered",  # the gap
        "pad 230 0100 filtered",  # a
        "pad 300 0100 filtered",  # finished: the input is the person's again
        "pad 400 0100 filtered",
        "pad 410 0000 filtered",
        "pad 500 0000 filtered",
        "pad 600 0000 filtered",  # a new battle's turn: the lead-in again
    ], out
    assert "lab: turn: member 0's input at frame 100: pressing left/a" in err, err
    assert "lab: peek" not in err, err  # a turn is not a peek at the safe points
    assert "lab: turn: member 0's input at frame 600" in err, err
    assert "lab: commands at frame 410: 0=5" in err, err


@needs_cc
def test_the_lab_plays_a_ship_crew_members_turn_each_time_its_wheel_is_ready(driver, tmp_path):
    """sturn:F-G:M:SEQ keys on 0x80306738: state 9, step 2, member byte M is
    M's wheel, ready. It plays SEQ then, and again the next time that wheel
    comes ready (a ship battle asks every turn); another member's is passed."""
    lab(tmp_path)
    script = (
        "set 80306738 09020100 pad 90 0100 "  # crew 1 ready: not ours
        "set 80306738 09020000 pad 100 0100 pad 165 0000 "  # crew 0: lead-in, then a
        "set 80306738 09050000 pad 300 0200 "  # chose: passed through
        "set 80306738 09020000 pad 400 0000 pad 465 0000"  # ready again: played again
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="sturn:0-1000:0:a")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 90 0100 filtered",
        "pad 100 0000 filtered",
        "pad 165 0100 filtered",
        "pad 300 0200 filtered",
        "pad 400 0000 filtered",
        "pad 465 0100 filtered",
    ], out
    assert err.count("lab: sturn: crew 0's input") == 2, err


@needs_cc
def test_the_lab_saves_at_a_save_point_and_again_a_while_later(driver, tmp_path):
    """save:F-G:SEQ on a quiet field starts a live save point's entry (hit
    type 45, the class word's low half at +18) as the A press would, plays SEQ
    from 120 frames later, and starts one again 60,000 frames after: a long
    run's card holds its latest (u4-H4's one save was 100,000 frames old when
    the run stopped). Not again sooner."""
    lab(tmp_path)
    vol = "set 80347524 80400800 set 80400808 1004 set 80400810 7800002d walkfns game "
    quiet = "set 803475cc 6 set 80311aec 8 set 80311ac0 14 setb 80311ac8 61 "
    script = (
        vol + quiet + "safe frame safe "  # frame 0: started; 1: not again
        "padall 120 0 padall 200 0 "  # the press from 120; played by 200
        + "frame " * 60000
        + "safe "  # 60001: too soon
        + "frame " * 119
        + "safe"  # 60120: 60,000 frames after the presses began
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="save:0-100000:a")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [
        "fn_80210550(4100)"
    ] * 2, out
    starts = [x.split("lab: ", 1)[1] for x in err.splitlines() if "save point" in x]
    assert starts == [
        "save: a020a's save point 4100 started at frame 0; pressing a from frame 120",
        "save: a020a's save point 4100 started at frame 60120; pressing a from frame 60240",
    ], err
    assert "save: a played by frame 200" in err, err


@needs_cc
def test_the_lab_walker_waits_for_a_quiet_field(driver, tmp_path):
    """walk:F-G:IDLE starts nothing while the field is not running or an event
    holds flag 1087, nor until IDLE quiet frames have passed; then it asks the
    game's own condition of each live talk and exit volume once (refused here:
    the fake guest has no fn_8021067C), and starts nothing it was not told is live."""
    lab(tmp_path)
    vol = "set 80347524 80400100 set 80400108 bbb set 80400114 0 set 80400130 80400200 "
    # 3003 (a talk) and 6001 (an exit), then 4100 with class 7800002D: hit type
    # 45, the low half at +18, a save point, which the walker passes over.
    vol += "set 80400208 1771 set 80400214 0 set 80400230 80400300 "
    vol += "set 80400308 1004 set 80400310 7800002d set 80400330 80400400 "
    vol += "set 80400408 1005 set 80400410 7800002c "  # 4101, wallmot (type 44): the other kind
    script = (
        vol + "set 803475cc 7 safe "  # a battle: busy
        "set 803475cc 6 set 80311aec 8 frame safe "  # quiet from frame 1, not IDLE frames yet
        "frame frame frame safe"  # frame 4: IDLE 3 has passed
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-100:3")
    assert "loaded 1" in out, err
    asked = [x for x in err.splitlines() if "call_guest(" in x]
    assert asked and all("call_guest(8021067C) refused" in x for x in asked), err
    assert len(asked) == 2, err  # both candidates asked once, at frame 4 only
    waits = [x.split(": ", 3)[-1] for x in err.splitlines() if "lab: walk: waiting" in x]
    assert waits == [
        "the field is not running (scene 7, state 0)",
        "no live entry: 2 volume(s) in the talk, check and exit ranges, 2 asked",
    ], err
    assert "started" not in err, err


@needs_cc
def test_the_walker_starts_no_entry_whose_cast_is_not_here(driver, tmp_path):
    """Before an entry starts, the actors its scptEnter names, in it and in
    what it CALLs, must be found by op 154's lookup: a008a's dancer (3004)
    calls her night at the inn, which enters 3005, who lives in the inn's own
    MLD, there only inside it. Started from the street, the night waited
    40,000 frames. With 3005 absent the entry is not started, nor asked again
    for a minute; then it is, and starts once 3005 has come (a door can bring
    him meanwhile). With 3005 here, it starts at once. So does one that sets a
    house up first (scptHset, op 65): a door, which loads the house's
    residents itself (a008b's 4000 opens house a and enters 3003, from
    a008ba.mld)."""
    script_ = (
        # Code at 80400000: "loop" at 0, "M03004" at 0x100, "sub" at 0x200.
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 3 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303330 set 8041001c 30340000 "
        "set 80410028 200 set 8041002c 73756200 "
        # M03004: Enter 3004; CALL sub (its offset word at 0x114); RET. sub: Enter 3005; RET.
        "set 80400100 1a set 80400104 04000000 set 80400108 453bc000 set 8040010c 1d "
        "set 80400110 b set 80400114 ec set 80400118 c "
        "set 80400200 1a set 80400204 04000000 set 80400208 453bd000 set 8040020c 1d set 80400210 c "
        # a008a's field, running, the main thread in its loop; a live talk volume for 3004.
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 "
        "set 8030cea4 80400008 set 80347524 80400800 set 80400808 bbc set 80400810 16 "
        "walkfns game "
    )
    lab(tmp_path)
    door = (  # sub: Hset 0, then Enter 3005; RET
        "set 80400200 41 set 80400204 04000000 set 80400208 0 set 8040020c 1d set 80400210 1a "
        "set 80400214 04000000 set 80400218 453bd000 set 8040021c 1d set 80400220 c "
    )
    later = (
        "here 3005 " + "frame " * 1800 + "safe frame frame frame frame safe"
    )  # a minute on, 3005 here
    for here, after, started, refusals in (
        ("here 3004 ", "", False, 1),  # not asked again within the minute
        ("here 3004 ", later, True, 1),
        ("here 3004 here 3005 ", "", True, 0),
        (door + "here 3004 ", "", True, 0),
    ):
        script = (
            script_
            + here
            + "safe frame frame frame frame safe frame frame frame frame safe "
            + after
        )
        out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3")
        assert "loaded 1" in out, err
        assert ("fn_80210550(3004)" in out) == started, out
        refused = "a008a entry 3004 calls on 3005, who is not here (a house's resident, there only inside it)"
        assert err.count(refused) == refusals, err


@needs_cc
def test_a_door_brings_the_residents_an_entry_waited_on(driver, tmp_path):
    """The dancer (3004) is refused while 3005 is not here; the walker then
    opens a door (4050, which sets house 4 up: the inn), and so asks her
    again at once, not a minute on: her night starts."""
    lab(tmp_path)
    script = (
        # "loop" at 0, "M03004" at 0x100 (Enter 3005; RET), "M04050" at 0x200 (Hset 4; RET).
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 3 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303330 set 8041001c 30340000 "
        "set 80410028 200 set 8041002c 4d303430 set 80410030 35300000 "
        "set 80400100 1a set 80400104 04000000 set 80400108 453bd000 set 8040010c 1d set 80400110 c "
        "set 80400200 41 set 80400204 04000000 set 80400208 40800000 set 8040020c 1d set 80400210 c "
        # a008a running, the main thread in its loop; volumes for 3004 and the door.
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 "
        "set 8030cea4 80400008 set 80347524 80400800 set 80400808 bbc set 80400810 16 set 80400830 80400900 "
        "set 80400908 fd2 set 80400910 8 walkfns game "
        "frame frame frame frame safe "  # 4: 3004 refused
        "frame frame frame frame safe "  # 8: the door
        "here 3005 frame frame frame frame safe"  # 12: the dancer again
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [
        "fn_80210550(4050)",
        "fn_80210550(3004)",
    ], out
    assert err.count("entry 3004 calls on 3005, who is not here") == 1, err


@needs_cc
def test_the_walker_stands_on_the_ground_an_entry_is_gated_on(driver, tmp_path):
    """An entry whose label is followed by `IF (B[16] N ==)` (a008a's doors,
    N 0) wants the player on ground N; the walker does not move the player,
    and came into a008a on ground 2, where every door did nothing. So B[16]
    is set to N first, the rest of its word kept, and said so; an entry with
    no such gate leaves it alone."""
    lab(tmp_path)
    script_ = (
        # "loop" at 0, "M04050" at 0x100: EVAL 1; IF (B[16] 0 ==) else ->; RET.
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303430 set 8041001c 35300000 "
        "set 80400100 9 set 80400104 04000000 set 80400108 3f800000 set 8040010c 1d "
        "set 80400110 0 set 80400114 10000010 set 80400118 04000000 set 8040011c 0 "
        "set 80400120 4 set 80400124 1d set 80400128 4 set 8040012c c "
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 "
        "set 8030cea4 80400008 set 80347524 80400800 set 80400808 fd2 set 80400810 8 "
        "set 80310a2c 02112233 walkfns game "  # B[16] 2, B[17..19] beside it
    )
    for gated, word in (("", "80310A2C=00112233"), ("set 80400114 10000011 ", "80310A2C=02112233")):
        out, err = play(
            driver,
            tmp_path,
            script_ + gated + "frame frame frame frame safe get 80310a2c",
            SOA_LAB="walk:0-5000:3",
        )
        assert "loaded 1" in out, err
        assert "fn_80210550(4050)" in out, out
        assert word in out, out
        said = "a008a entry 4050 stands on ground B[16] = 0; the player stood on 2: set, as walking there would"
        assert (said in err) == (not gated), err


@needs_cc
def test_a_story_step_with_no_volume_here_ranks_the_doors(driver, tmp_path):
    """a008a's innkeeper (4410) warps toward 153 but has no volume on the
    street: he is in the inn's own MLD, behind a door. So a door (an entry
    that sets a house up) ranks one step behind him and is started before a
    check, though the check's id is lower. Inside a house where nothing
    ranks, its exit comes before its checks."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text("008a M04410 w203a\n203a loop s153\n", encoding="utf-8")
    script_ = (
        # "loop" at 0, "M04000" at 0x100 (RET), "M04050" at 0x200 (Hset 4; RET).
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 3 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303430 set 8041001c 30300000 "
        "set 80410028 200 set 8041002c 4d303430 set 80410030 35300000 "
        "set 80400100 c set 80400200 41 set 80400204 04000000 set 80400208 40800000 set 8040020c 1d "
        "set 80400210 c "
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 "
        "set 8030cea4 80400008 set 80347524 80400800 set 80400808 fa0 set 80400810 8 "
        "walkfns game "
    )
    outside = "set 80400830 80400900 set 80400908 fd2 set 80400910 8 "  # the door, 4050
    inside = (
        "set 80310bbc 1 set 80400830 80400900 set 80400908 17a2 set 80400910 8 "  # the exit, 6050
    )
    for extra, started in ((outside, "fn_80210550(4050)"), (inside, "fn_80210550(6050)")):
        out, err = play(
            driver,
            tmp_path,
            script_ + extra + "frame frame frame frame safe",
            SOA_LAB="story:150-199;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [started], (out, err)


@needs_cc
def test_the_walker_warps_nowhere_from_inside_a_house(driver, tmp_path):
    """Flag 1024 is set while the party is inside a house (a door sets it, the
    house's exit clears it). From inside, an entry that warps to another map
    is not started, however it ranks: a008b's 4100, out on the street, took
    reach U4's walker to a008a with 1024 still set, and every door there was
    dead. Outside, it is the one started."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text("008b M04100 w008a\n008a M03004 s152\n", encoding="utf-8")
    base = (
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 62 set 803475cc 6 set 80311aec 8 "
        "set 80347524 80400800 set 80400808 1004 set 80400810 8 set 80400830 80400900 "
        "set 80400908 10d6 set 80400910 8 walkfns game "
    )
    for inside, started in (("set 80310bbc 1 ", "fn_80210550(4310)"), ("", "fn_80210550(4100)")):
        out, err = play(
            driver,
            tmp_path,
            base + inside + "frame frame frame frame safe",
            SOA_LAB="story:150-199;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [started], (out, err)


@needs_cc
def test_inside_a_house_its_own_entries_may_warp(driver, tmp_path):
    """The house's own entries are the volumes that came after the walker
    opened its door, and those may warp from inside: a008a's innkeeper (4410)
    takes the party to the night at 203a, and reach U4's walker, refusing
    every warp inside, passed 153 over."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text("008a M04410 w203a\n203a loop s153\n", encoding="utf-8")
    script = (
        # "loop" at 0, "M04050" at 0x100 (Hset 4; RET): the inn's door, its volume alone at first.
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303430 set 8041001c 35300000 "
        "set 80400100 41 set 80400104 04000000 set 80400108 40800000 set 8040010c 1d set 80400110 c "
        "set 80311ac0 8 set 80311ac4 8 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 "
        "set 8030cea4 80400008 set 80347524 80400800 set 80400808 fd2 set 80400810 8 walkfns game "
        "frame frame frame frame safe "  # 4: the door
        "set 80310bbc 1 set 80400830 80400900 set 80400908 113a set 80400910 8 "  # inside; the innkeeper's volume
        "frame frame frame frame safe"  # 8: him
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:150-199;walk:0-5000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [
        "fn_80210550(4050)",
        "fn_80210550(4410)",
    ], (out, err)


@needs_cc
def test_the_walker_does_an_actors_tasks_it_never_took_up(driver, tmp_path):
    """A minute on a starting entry, each live slot waiting on a task queued
    to an actor (the record at +0x0C, the actor's id at +0x24) whose first word
    is still 0 is marked done (2), said so: a019a's Ship Parts Merchant, talked
    to from the pier outside his shop, never took his four up. A task the
    actor has taken up (1), and a slot with no actor, are left alone."""
    lab(tmp_path)
    slots = (
        "set 8030cea8 4 set 8030ceb0 80420000 "
        "set 80420034 1 set 80420040 80430000 set 80420058 bba "  # slot 1: 3002's, queued
        "set 80420068 1 set 80420074 804300a0 set 8042008c bba set 804300a0 1 "  # slot 2: taken up
        "set 8042009c 1 set 804200a8 80430140 "  # slot 3: no actor
    )
    script = (
        slots
        + "set 803475cc 6 set 80311aec 8 set 8030e714 1 safe "
        + "frame " * 1799
        + "safe get 80430000 "  # 1799: not yet
        + "frame safe get 80430000 get 804300a0 get 80430140"  # 1800: done in its place
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("80430")] == [
        "80430000=00000000",
        "80430000=00000002",
        "804300A0=00000001",
        "80430140=00000000",
    ], out
    assert (
        "frame 1800: 1 task(s) queued to actor 3002 never taken up: marked done in its place" in err
    ), err


@needs_cc
def test_the_walker_names_the_threads_a_stuck_entry_waits_on(driver, tmp_path):
    """An entry's RET waits while other script threads live (the s16 at
    0x8030CEAA above 1), and 0x8030E714 stays 1 meanwhile: a minute of it
    logs, once, the count and each live slot's entry and opcode (slots of
    52 bytes at *0x8030CEB0, live while the first word is not 0, the PC at
    +0x1C). a008a's dancer held reach U4's part-D walker 40,000 frames."""
    lab(tmp_path)
    script_ = (
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 "
        "set 80410018 6d653131 set 8041001c 36646330 set 80410020 32000000 "
    )
    # Two alive; slot 0 free, slot 1 live at me116dc02's 0x108, an op 30.
    threads = (
        "set 8030cea8 2 set 8030ceb0 80420000 set 80420034 1 set 80420050 80400108 set 80400108 1e "
    )
    script = (
        script_
        + threads
        + "set 803475cc 6 set 80311aec 8 set 8030cea4 80400008 set 8030e714 1 safe "
        + "frame " * 1799
        + "safe "  # frame 1799: not yet a minute
        + "frame safe "  # 1800
        + "frame " * 100
        + "safe"  # still stuck: not said again
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3")
    assert "loaded 1" in out, err
    said = [x.split("lab: walk: ", 1)[1] for x in err.splitlines() if "lab: walk: " in x]
    assert said == [
        "waiting at frame 0: a script entry is starting (0x8030E714 is 1)",
        "frame 1800: 2 script thread(s) alive with the main one",
        "  thread 1 at 00108 (op 30), in me116dc02",
    ], err


@needs_cc
def test_the_walker_steps_off_a_touch_that_keeps_starting_under_the_player(driver, tmp_path):
    """A touch entry (M06nnn) starts again each frame the player stands in its
    volume, holding the lock (0x8030E714) each time: a018b's 6020 lies under
    the arrival from a242a, and part G's walker, which never moves the player,
    waited 99,000 frames on it. Once the main thread has been in one for 60
    frames with the lock held, the pad filter holds the stick a quarter turn
    every 90 frames, said so, until the lock is free; the person's own press
    is left alone, and so is any other entry holding the lock, and a touch
    that runs on past its first word (a013d's 6005 walks the player a step
    and warps)."""
    lab(tmp_path)
    # The script: code at 80400000; "loop" at 0 and "M06020" at 0x100.
    frames35, frames59 = "frame " * 35, "frame " * 59
    script = (
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 4d303630 set 8041001c 32300000 "
        "set 803475cc 6 set 80311aec 8 set 8030e714 1 "
        f"set 8030cea4 80400008 safe {frames35}safe padall 35 0 "  # the loop holds it: not a touch
        f"set 8030cea4 80400108 safe {frames35}safe padall 70 0 "  # 6020 past its first word: running
        f"set 8030cea4 80400100 safe {frames59}safe padall 129 0 "  # 6020 for 59 frames: not yet
        "frame safe padall 130 0 padall 220 0 padall 230 100 "  # 60: up, then right; the person's A alone
        "set 8030e714 0 set 8030cea4 80400008 frame safe padall 131 0"  # the lock free
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-1000:3")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("padall")] == [
        "padall 35 00 00 11 22 33 44 55 66",
        "padall 70 00 00 11 22 33 44 55 66",
        "padall 129 00 00 11 22 33 44 55 66",
        "padall 130 00 00 80 FF 33 44 55 66",
        "padall 220 00 00 FF 80 33 44 55 66",
        "padall 230 00 01 11 22 33 44 55 66",
        "padall 131 00 00 11 22 33 44 55 66",
    ], out
    said = [
        x.split("lab: walk: ", 1)[1]
        for x in err.splitlines()
        if "lab: walk: " in x and "waiting" not in x
    ]
    assert said == [
        "M06020 has started over since frame 70 with the player in its volume: stepping off at frame 130",
        "off M06020 at frame 131",
    ], err


@needs_cc
def test_the_walker_waits_where_the_players_own_a_press_would_do_nothing(driver, tmp_path):
    """fn_80118204's other gates: the player held (0x80347508 is 1) and the
    field's mode 12 (fn_8009763C: 2 at 0x80346C3C, 12 in the low byte at
    0x80302F18); and a message window on screen (states 2 to 8), a scene
    still talking with flag 1087 clear. Each makes the walker wait, saying
    which; and the map script's main thread anywhere but its loop, which is
    a cutscene the loop called (a116d's clears 1087 first). With none -- the
    window's task there from the map load, waiting for a message in state 1;
    the thread in its loop, or at a RET it is about to leave, or in a touch
    entry (M06nnn), which starts again every frame the player stands on it
    (a018b's 6020 held part G's walker 99,000 frames) -- it looks for an
    entry."""
    lab(tmp_path)
    # The script: code at 80400000; two entries, "loop" at 0 and "me116dc02"
    # at 0x100, indexed at 80410000 (offset, then the name's 16 bytes).
    script_ = (
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 "
        "set 80410018 6d653131 set 8041001c 36646330 set 80410020 32000000 "
    )
    script = (
        script_ + "set 803475cc 6 set 80311aec 8 set 8030cea4 80400008 set 80347508 1 safe "
        "set 80347508 0 set 80346c3c 00020000 set 80302f18 000c0000 safe "
        "set 80346c3c 0 set 80346e4c 80400000 set 80346e64 00040000 safe "
        "set 80346e64 00010000 set 8030cea4 80400104 safe "  # in the cutscene
        "set 80400104 c frame frame frame frame safe "  # at its RET: back to the loop next tick
        "set 80400104 0 safe "  # in the cutscene again
        "set 8030cea4 80400008 frame frame frame frame safe "  # the loop
        "set 80410018 4d303630 set 8041001c 32300000 set 80410020 0 "  # the entry at 0x100 is M06020
        "set 8030cea4 80400104 frame frame frame frame safe"  # a touch: not busy
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-100:3")
    assert "loaded 1" in out, err
    waits = [x.split(": ", 3)[-1] for x in err.splitlines() if "lab: walk: waiting" in x]
    nothing = "no live entry: 0 volume(s) in the talk, check and exit ranges, 0 asked"
    assert waits == [
        "the player is held (0x80347508 is 1)",
        "the field's mode is 12 (fn_8009763C)",
        "a message window is open",
        "the map's script runs me116dc02",
        nothing,
        "the map's script runs me116dc02",
        nothing,
    ], err


@needs_cc
def test_assist_takes_the_next_option_when_the_walker_starts_an_entry_again(driver, tmp_path):
    """a035g's Gilder asks "What do you say?", "not quite finished" first:
    answering the first option every time, the walker passed 316 over. Now the
    first start of an entry answers its choice with the first option, the
    second start with the second (down, then A, thirty frames apart)."""
    lab(tmp_path)
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 23 setb 80311ac8 67 set 8030cea4 80400008 "
        "set 80347524 80400800 set 80400808 bbc set 80400810 16 walkfns game "
        "frame frame frame frame safe "  # Gilder's talk, the first time
        "set 80346e4c 80400000 set 80346e64 00060000 pad 50 0000 pad 80 0000 "  # his choice: A
        "set 80346e4c 0 pad 90 0000 frame frame frame frame safe "  # done; his talk again
        "set 80346e4c 80400000 set 80346e64 00060000 pad 200 0000 pad 230 0000 pad 260 0000"  # down, A
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3;assist:0-5000:150")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [
        "fn_80210550(3004)"
    ] * 2, out
    assert [x for x in out.splitlines() if x.startswith("pad ")] == [
        "pad 50 0000 filtered",
        "pad 80 0100 filtered",
        "pad 90 0000 filtered",
        "pad 200 0000 filtered",
        "pad 230 0004 filtered",
        "pad 260 0100 filtered",
    ], out


@needs_cc
def test_assist_takes_the_next_option_when_a_choice_comes_again_in_one_start(driver, tmp_path):
    """A choice asked again with no start of the walker's between gets the
    option after the last, the third after the second: a019a's Ship Parts
    Merchant asks again after "Talk about various things", and answered so
    every time his talk went on for good (u4-H12)."""
    lab(tmp_path)
    window = "set 80346e4c 80400000 set 80346e64 00060000 "
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 13 setb 80311ac8 61 set 8030cea4 80400008 "
        "set 80347524 80400800 set 80400808 fa2 set 80400810 16 walkfns game "
        "frame frame frame frame safe "  # the merchant's talk
        + window
        + "pad 50 0000 pad 80 0000 set 80346e4c 0 pad 90 0000 "  # A: the first
        + window
        + "pad 200 0000 pad 230 0000 pad 260 0000 set 80346e4c 0 pad 270 0000 "  # down, A
        + window
        + "pad 300 0000 pad 330 0000 pad 360 0000 pad 390 0000"  # down, down, A
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:3;assist:0-5000:150")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == ["fn_80210550(4002)"], (
        out
    )
    assert [x for x in out.splitlines() if x.startswith("pad ")] == [
        "pad 50 0000 filtered",
        "pad 80 0100 filtered",
        "pad 90 0000 filtered",
        "pad 200 0000 filtered",
        "pad 230 0004 filtered",
        "pad 260 0100 filtered",
        "pad 270 0000 filtered",
        "pad 300 0000 filtered",
        "pad 330 0004 filtered",
        "pad 360 0004 filtered",
        "pad 390 0100 filtered",
    ], out


@needs_cc
def test_the_lab_assist_presses_a_only_in_a_battle_or_at_a_choice(driver, tmp_path):
    """assist:F-G:EVERY: on the beat, A in scene 7; and while the field's
    message window (task 0x80346E4C) holds a choice (state 6 at 0x80346E64),
    A for two frames thirty after it came (the first option); never on a
    quiet field, a page that is not a choice, or off the beat."""
    lab(tmp_path)
    script = (
        "set 803475cc 6 pad 100 0000 "  # the field, no window
        "set 80346e4c 80400000 set 80346e64 00040000 pad 150 0000 "  # a page (state 4)
        "set 80346e64 00060000 pad 200 0000 pad 230 0000 pad 231 0000 pad 232 0000 "  # a choice, 30 frames on
        "set 80346e4c 0 set 803475cc 7 pad 250 0000 "  # a battle
        "set 803475cc 6 set 80311aec 4 pad 300 0000 "  # its results screen
        "set 80311aec 8 pad 350 0000 "  # the field running again
        "set 80311ac0 207 setb 80311ac8 61 set 80306738 06000003 pad 400 0000 "  # a519a: waits for A
        "set 80306738 09020003 pad 450 0000 "  # a crew member chooses: sturn's, not assist's
        "set 80306738 060f0103 pad 500 0000 "  # between members: waits for A
        "set 80306738 080f0103 pad 550 0000 "  # the next wheel opening: no A, it could reach it
        "set 80306738 06020203 pad 600 0000"  # between members, another step left over: A
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="assist:0-1000:50")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 100 0000 filtered",
        "pad 150 0000 filtered",
        "pad 200 0000 filtered",
        "pad 230 0100 filtered",
        "pad 231 0100 filtered",
        "pad 232 0000 filtered",
        "pad 250 0100 filtered",
        "pad 300 0100 filtered",
        "pad 350 0000 filtered",
        "pad 400 0100 filtered",
        "pad 450 0000 filtered",
        "pad 500 0100 filtered",
        "pad 550 0000 filtered",
        "pad 600 0100 filtered",
    ], out


@needs_cc
def test_a_ship_members_input_that_changed_nothing_is_played_again_three_times(driver, tmp_path):
    """A wheel still ready when its presses are done had one of them not land:
    played again, three times at most, then left to the person; with the next
    alternative each time where there are several, as a cannon the turn's SP
    will not pay for gives way to Focus (Fina's greyed list in u4-G18)."""
    lab(tmp_path)
    pads = " ".join(f"pad {f} 0000" for f in range(100, 1200, 10))
    out, err = play(driver, tmp_path, "set 80306738 09020000 " + pads, SOA_LAB="sturn:0-5000:0:a")
    assert "loaded 1" in out, err
    assert err.count("lab: sturn: crew 0's input") == 4, err
    assert err.count("is still ready") == 3 and "again (3 of 3)" in err, err
    out, err = play(driver, tmp_path, "set 80306738 09020000 " + pads, SOA_LAB="sturn:0-5000:0:a|b")
    alts = [x.rsplit("(", 1)[1] for x in err.splitlines() if "lab: sturn: crew 0's input" in x]
    assert alts == [
        "alternative 1 of 2)",
        "alternative 2 of 2)",
        "alternative 1 of 2)",
        "alternative 2 of 2)",
    ], err


@needs_cc
def test_assist_keeps_off_a_ship_members_wheel_while_its_turn_plays(driver, tmp_path):
    """State 6 is also a member's wheel after its B. While that member's
    sturn presses play, assist's A would choose for it: so none, even on the
    beat; once the presses are done, state 6 is a wait again and gets its A."""
    lab(tmp_path)
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 207 setb 80311ac8 61 "
        "set 80306738 09020003 pad 100 0000 "  # crew 0 ready: its presses start
        "set 80306738 06020003 pad 180 0000 pad 240 0000 "  # after its B, on assist's beat: no A
        "pad 300 0000 pad 360 0000"  # its presses done (b/right: two slots), a wait: A on the beat
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="sturn:0-1000:0:b/right;assist:0-1000:60")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 100 0000 filtered",
        "pad 180 0000 filtered",
        "pad 240 0000 filtered",
        "pad 300 0000 filtered",
        "pad 360 0100 filtered",
    ], out


@needs_cc
def test_a_ship_members_inputs_take_the_alternatives_in_turn(driver, tmp_path):
    """sturn:...:a|b presses A at the member's first input, B at the next,
    then A again; each new input takes the next alternative."""
    lab(tmp_path)
    turn = "set 80306738 09020000 pad {0} 0000 pad {1} 0000 set 80306738 06000000 pad {2} 0000 "
    script = turn.format(100, 160, 300) + turn.format(400, 460, 600) + turn.format(700, 760, 900)
    out, err = play(driver, tmp_path, script, SOA_LAB="sturn:0-5000:0:a|b")
    assert "loaded 1" in out, err
    pressed = [x for x in out.splitlines() if x.startswith(("pad 160 ", "pad 460 ", "pad 760 "))]
    assert pressed == ["pad 160 0100 filtered", "pad 460 0200 filtered", "pad 760 0100 filtered"], (
        out
    )
    assert "(alternative 2 of 2)" in err, err


@needs_cc
def test_a_lab_press_can_be_held_shorter_than_the_games_repeat(driver, tmp_path):
    """`left#4` is held four frames, under the six after which the game
    repeats a held direction, so a wheel moves one slot, not two."""
    lab(tmp_path)
    script = "set 80306738 09020000 pad 100 0000 " + " ".join(
        f"pad {f} 0000" for f in (160, 163, 164, 169)
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="sturn:0-1000:0:left#4")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 100 0000 filtered",
        "pad 160 0001 filtered",
        "pad 163 0001 filtered",
        "pad 164 0000 filtered",
        "pad 169 0000 filtered",
    ], out


@needs_cc
def test_the_walker_backs_out_of_an_event_that_holds_the_field_a_minute(driver, tmp_path):
    """A shop's menu holds the field (flag 1087) for good: after 1800 frames
    the walker's pad filter presses B every 70, and stops once it is free."""
    lab(tmp_path)
    held = "set 803475cc 6 set 80311aec 8 set 80310bc0 80000000 safe "
    script = (
        held
        + "frame " * 1700
        + "safe pad 1750 0000 "  # 1700 frames held: not yet
        + "frame " * 100
        + "safe pad 1820 0000 pad 1835 0000 "  # 1800 and more: B on the beat, not off it
        + "set 80310bc0 0 safe pad 1890 0000"  # free: no more B
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:300")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 1750 0000 filtered",
        "pad 1820 0200 filtered",
        "pad 1835 0000 filtered",
        "pad 1890 0000 filtered",
    ], out
    assert "held the field, its window unmoved, since frame 0: pressing B" in err, err
    assert "the field is free again at frame 1800" in err, err


@needs_cc
def test_an_entry_backed_out_of_is_started_again_for_its_next_option(driver, tmp_path):
    """An entry whose event needed backing out is started again until its
    starts have taken each of assist's two options, then left alone: a019a's
    Ship Parts Merchant's first is the shop, its second "Proceed to Mt.
    Kazai", the story's way on (358, which part H's walker passed over)."""
    lab(tmp_path)
    vol = "set 80347524 80400800 set 80400808 fa2 set 80400810 8 walkfns game "
    quiet, held = "set 80310bc0 0 ", "set 80310bc0 80000000 "
    one = held + "safe " + "frame " * 1810 + "safe " + quiet + "safe " + "frame " * 4 + "safe "
    script = (
        vol
        + "set 80311ac0 13 setb 80311ac8 61 set 803475cc 6 set 80311aec 8 frame frame frame frame safe "
        + one
        + one
        + "frame " * 4
        + "safe"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-20000:3")
    assert "loaded 1" in out, err
    said = [x.split("lab: walk: ", 1)[1] for x in err.splitlines() if "needed backing out" in x]
    assert said == [
        "a019a entry 4002 needed backing out: started again for its next option",
        "a019a entry 4002 needed backing out: not started again",
    ], err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [
        "fn_80210550(4002)"
    ] * 2, out


@needs_cc
def test_the_walker_presses_the_way_out_of_a_menu_b_does_not_leave(driver, tmp_path):
    """An event that has held the field 5,400 frames, B notwithstanding (the
    Maramba Office's Buy / Sell / Wanted / Exit), gets the way out instead:
    B, B, up, A, B, B, down x3, A, a press every 70 frames (up wraps to the
    last item, Exit)."""
    lab(tmp_path)
    held = "set 803475cc 6 set 80311aec 8 set 80310bc0 80000000 safe "
    script = held + "frame " * 5500 + "safe pad 5600 0000 pad 5740 0000 pad 5810 0000 pad 6020 0000"
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-9000:300")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 5600 0200 filtered",  # beat 80: B
        "pad 5740 0008 filtered",  # beat 82: up
        "pad 5810 0100 filtered",  # beat 83: A
        "pad 6020 0004 filtered",  # beat 86: down
    ], out
    assert "held the field since frame 0: pressing the way out of a menu" in err, err


@needs_cc
def test_assist_leaves_a_shopkeepers_choice_once_the_walker_has_backed_out(driver, tmp_path):
    """After the walker has had to back out of an event (a shop's menu), the
    choice it comes to is a shopkeeper's "what will you do?", whose first
    option opens the shop again (the Mystery Merchant: buy and sell, talk,
    leave). Each time one comes, timed from its coming: down, down, A, then
    the next time up, A. Not on assist's beat: the merchant's talk took 600
    frames, four beats exactly, so its up fell in the talk every time."""
    lab(tmp_path)
    held = "set 803475cc 6 set 80311aec 8 set 80310bc0 80000000 set 80346e4c 80400000 safe "
    script = (
        held
        + "frame " * 1800
        + "safe "  # 1800: a minute unmoved, B
        + "set 80346e64 00060000 safe "  # a choice: the window moved, so no more B
        + "pad 1950 0000 pad 1980 0000 pad 2010 0000 pad 2040 0000 "
        + "set 80346e64 00040000 safe pad 2100 0000 "  # the talk the choice led to
        + "set 80346e64 00060000 safe pad 2250 0000 pad 2280 0000 pad 2310 0000"  # the choice again
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-9000:300;assist:0-9000:150")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == [
        "pad 1950 0000 filtered",  # the choice comes: nothing yet, though on the beat
        "pad 1980 0004 filtered",  # down
        "pad 2010 0004 filtered",  # down
        "pad 2040 0100 filtered",  # A: the third, leave
        "pad 2100 0000 filtered",  # a page, not a choice
        "pad 2250 0000 filtered",  # the choice again, on the beat
        "pad 2280 0008 filtered",  # up: wraps to the last, should the cursor be first
        "pad 2310 0100 filtered",  # A
    ], out


@needs_cc
def test_the_walker_never_backs_out_of_a_ship_battle(driver, tmp_path):
    """A ship battle (a 5xx stage, here a501a) holds flag 1087 throughout
    with its menu, not the message window, on screen: B there answers a
    crew member's wheel, so a minute and more of it is never "stuck"."""
    lab(tmp_path)
    held = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 1f5 setb 80311ac8 61 "
        "set 80310bc0 80000000 safe "
    )
    script = held + "frame " * 1820 + "safe pad 1820 0000 pad 1890 0000"
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-5000:300")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == ["pad 1820 0000 filtered", "pad 1890 0000 filtered"], out
    assert "pressing B" not in err, err


@needs_cc
def test_the_walker_never_backs_out_of_an_event_whose_dialogue_moves_on(driver, tmp_path):
    """A cutscene holds flag 1087 longer than a minute, but its message window
    changes (a page, then a choice): each change starts the minute again, so
    no B is pressed. Once the window stands still a minute, B comes; when it
    moves again, B stops."""
    lab(tmp_path)
    held = "set 803475cc 6 set 80311aec 8 set 80310bc0 80000000 set 80346e4c 80400000 safe "
    script = (
        held
        + "frame " * 1000
        + "set 80346e64 00040000 safe "  # frame 1000: a page
        + "frame " * 1000
        + "set 80346e64 00060000 safe pad 2010 0000 "  # 2000: a choice; 2,000 frames held, no B
        + "frame " * 1800
        + "safe pad 3850 0000 "  # still since 2000: B, on the beat
        + "set 80346e64 00040000 safe pad 3920 0000"  # it moved: no B on the next beat
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="walk:0-9000:300")
    assert "loaded 1" in out, err
    pads = [x for x in out.splitlines() if x.startswith("pad ")]
    assert pads == ["pad 2010 0000 filtered", "pad 3850 0200 filtered", "pad 3920 0000 filtered"], (
        out
    )
    assert "its window unmoved, since frame 2000: pressing B" in err, err
    assert "the event moved on at frame 3800: no more B" in err, err


STORY = """# sct.py --story, cut down to part C's opening (reach U4)
004a M03005 w250a
004a M04010 s58
250a loop s599 w099@ w004a
099f loop s59 w243a
243a loop s100 s102 w116d
116d M04001 s101
355a b s100 s101 s102 s103
"""


@needs_cc
def test_the_lab_story_aims_at_the_next_flag_and_measures_the_way_there(driver, tmp_path):
    """story:LO-HI reads SOA_LAB_STORY's lines and, at each pick, aims at the
    lowest flag of the window still clear that a line sets and the lines
    reach from here, and finds this map's distance in warps to a map that
    sets it: the town's dock talk, the sky over it, the world map (any letter
    is one place), then the cutscene map whose loop sets 100. With 100 and
    102 set (a story sets flags out of order), the aim is 101, one warp
    further off. With 100 to 102 set, 103 is left, which only the part-select
    room sets: no aim, for no place the story goes sets it (reach U4's part-E
    walker spent 30,000 frames on each such flag)."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(STORY, encoding="utf-8")
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 4 setb 80311ac8 61 setb 80310a22 5 "  # B[6] 5: stage f
        "frame frame frame frame safe "  # frame 4: the first pick in a004a
        "set 80310b48 50 frame frame frame safe "  # flags 100 and 102
        "set 80310b48 70 frame frame frame safe "  # 100 to 102
        "set 80310b48 f0 frame frame frame safe"  # and 103
    )
    lab_items = "story:100-149;walk:0-100:3"
    out, err = play(
        driver, tmp_path, script, SOA_LAB=lab_items, SOA_LAB_STORY=str(tmp_path / "story.txt")
    )
    assert "loaded 1" in out, err
    assert "lab: story: 7 line(s), 6 place(s) from" in err, err
    aims = [
        x.split("lab: story: ", 1)[1]
        for x in err.splitlines()
        if "lab: story: " in x and "line(s)" not in x
    ]
    assert aims == [
        "aiming at flag 100 (set in 243a); a004a is 3 warp(s) away",
        "aiming at flag 101 (set in 116d); a004a is 4 warp(s) away",
        "no flag in 100-149 is left for a line to set",
    ], err


@needs_cc
def test_the_walker_stands_in_for_the_ships_arrival_at_a_hook_twice_then_later(driver, tmp_path):
    """On the world map, `099f hook1766 w243a`: the loop warps to 243a, which
    sets the aim, once flag 1766 is set, and no script sets it. With nothing
    live ranked before it the walker sets the flag (the rest of its word
    kept) and says why; cleared again it is set again, after two tries at one
    aim it is left alone, and 9,000 frames after the last it is tried again
    (a002e's exit sets 122 only once a talk there has set 2548)."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "099f loop s59 w243a\n099f hook1766 w243a\n243a loop s100\n", encoding="utf-8"
    )
    script = (
        "set 80310c18 1 set 803475cc 6 set 80311aec 8 set 80311ac0 63 setb 80311ac8 66 "
        "frame frame frame frame safe get 80310c18 "  # frame 4: the hook
        "set 80310c18 1 frame frame frame safe get 80310c18 "  # 7: cleared, set again
        "set 80310c18 1 frame frame frame safe get 80310c18 "  # 10: two tries made
        + "frame " * 9000
        + "safe get 80310c18"  # 9010: 9,003 frames after the last try
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:100-149;walk:0-20000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("80310C18")] == [
        "80310C18=00000041",
        "80310C18=00000041",
        "80310C18=00000001",
        "80310C18=00000041",
    ], out
    hooks = [x.split("lab: walk: ", 1)[1] for x in err.splitlines() if " hook: " in x]
    assert [h.split(" set at frame ")[1].split(",")[0] for h in hooks] == ["4", "7", "9010"], err
    assert hooks[0] == (
        "a099f hook: flag 1766 set at frame 4, in place of the arrival this map's script waits for "
        "(the story's rank toward flag 100: 1)"
    ), err


@needs_cc
def test_the_walker_stands_in_for_the_arrival_a_story_flag_waits_on(driver, tmp_path):
    """`099i hook1781 s352`: a099i's loop calls the cutscene that sets 352,
    part H's first, once flag 1781 is set, and no script sets it; 352 waits
    on it (`req352 r1781`). The requirement holds the walker back no longer,
    and the hook, setting the aim, ranks first: 1781 is set, said so."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "099i loop s352\n099i me099ah03 s352\n099i hook1781 s352\n099i req352 r1781\n",
        encoding="utf-8",
    )
    script = (
        "set 80310c18 1 set 803475cc 6 set 80311aec 8 set 80311ac0 63 setb 80311ac8 69 "
        "frame frame frame frame safe get 80310c18"  # frame 4: the hook
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:350-399;walk:0-20000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("80310C18")] == ["80310C18=00200001"], out
    assert (
        "a099i hook: flag 1781 set at frame 4, in place of the arrival this map's script waits for "
        "(the story's rank toward flag 352: 0)" in err
    ), err


@needs_cc
def test_a_way_into_a_map_whose_loop_sets_the_aim_on_that_arrival_ranks_first(driver, tmp_path):
    """`123d via123b s403`: a123b's loop sets 403 only on the arrival from
    a123d, so a123d is where 403 is set, and its way into a123b (4201) ranks
    first, before a lower id that leads elsewhere (4200). Part I's walker
    stood in a123b, whose loop never sets 403 for an arrival from the world
    map, and took its door instead."""
    lab(tmp_path)
    lines = "123d M04201 w123b|123d M04200 w123a|123d via123b s403|123a M04000 w123b|"
    (tmp_path / "story.txt").write_text(lines.replace("|", "\n"), encoding="utf-8")
    vols = (
        "set 80347524 80400800 set 80400808 1068 set 80400810 8 set 80400830 80400900 "  # 4200
        "set 80400908 1069 set 80400910 8 walkfns game "  # 4201
    )
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 7b setb 80311ac8 64 frame frame frame frame safe"
    out, err = play(
        driver,
        tmp_path,
        vols + here,
        SOA_LAB="story:400-449;walk:0-5000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == ["fn_80210550(4201)"], (
        out
    )
    assert "the story's rank toward flag 403: 0" in err, err


@needs_cc
def test_a_way_in_that_the_loop_sends_straight_back_leads_nowhere(driver, tmp_path):
    """`126b via126c w126b`: a126c's loop sends the party come from a126b
    straight back, so a126b's way into a126c (4212) leads nowhere toward 454,
    set in a126c, and the way round by a126d (4008) ranks instead: part J's
    walker took 4212 four times."""
    lab(tmp_path)
    lines = (
        "126b M04212 w126c|126b M04008 w126d|126d M04001 w126c|126c M04001 s454|126b via126c w126b|"
    )
    (tmp_path / "story.txt").write_text(lines.replace("|", "\n"), encoding="utf-8")
    vols = (
        "set 80347524 80400800 set 80400808 1074 set 80400810 8 set 80400830 80400900 "  # 4212
        "set 80400908 fa8 set 80400910 8 walkfns game "  # 4008
    )
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 7e setb 80311ac8 62 frame frame frame frame safe"
    out, err = play(
        driver,
        tmp_path,
        vols + here,
        SOA_LAB="story:450-499;walk:0-5000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == ["fn_80210550(4008)"], (
        out
    )
    assert "the story's rank toward flag 454: 2" in err, err


@needs_cc
def test_a_hook_waits_for_the_flags_its_block_then_tests(driver, tmp_path):
    """`099l hook1782 w205a r468 x460`: the warp waits on 468 set and 460
    clear past 1782, so with 468 clear the hook is neither used nor a way to
    205a; with it set, it is. Part J's walker set 1782 with 468 clear."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "099l hook1782 w205a r468 x460\n205a M04000 w034a\n205a via034a s469\n", encoding="utf-8"
    )
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 63 setb 80311ac8 6c "
    for flags, used in (
        ("", False),
        ("set 80310b74 100000 ", True),
    ):  # 468: word 0x80310B74, bit 20
        out, err = play(
            driver,
            tmp_path,
            here + flags + "frame frame frame frame safe",
            SOA_LAB="story:450-499;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert ("hook: flag 1782 set" in err) == used, (flags, err)


@needs_cc
def test_an_entry_the_game_starts_is_started_by_name_where_it_sets_the_aim(driver, tmp_path):
    """`127b Fship s463 g`: the game starts Fship as the Delphinus flies
    there, and the walker cannot fly. With nothing live here setting the aim,
    Fship is started by its name in the map script's entry table (the string's
    address, to fn_80210450), said so; a line without g is not."""
    lab(tmp_path)
    # The script's entry table at 80410000: "loop" at 0, "Fship" second.
    table = (
        "set 8030cea0 80400000 set 8030d6c0 80410000 set 8030d6c4 2 "
        "set 80410004 6c6f6f70 set 80410014 100 set 80410018 46736869 set 8041001c 70000000 "
    )
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 7f setb 80311ac8 62 set 8030cea4 80400008 walkfns game "
    for line, started in (("127b Fship s463 g", True), ("127b Fship s463", False)):
        (tmp_path / "story.txt").write_text(line + "\n", encoding="utf-8")
        out, err = play(
            driver,
            tmp_path,
            table + here + "frame frame frame frame safe",
            SOA_LAB="story:450-499;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert ("fn_80210450(80410018)" in out) == started, (line, out)
        assert ("a127b's Fship started by name at frame 4" in err) == started, (line, err)


@needs_cc
def test_a_way_whose_arrival_plays_a_later_scene_is_not_taken_early(driver, tmp_path):
    """`019d via099i s365`: a019d's 4005 to the world map plays 365's scene on
    arrival, and part H's walker, aiming at 358, took it early, which shut
    the betrayal (380) out. A way into a map whose arrival sets a flag of the
    window above the aim, still clear, is no way toward it: the walker goes
    round by a019a (4004) instead; with 365 already set, 4005 is a way again."""
    lab(tmp_path)
    lines = (
        "019d M04005 w099i|019d via099i s365|019d M04004 w019a|"
        "019a M04002 w019b|019b M04000 w121a|099i M04017 w121a|121a M04000 s358|"
    )
    (tmp_path / "story.txt").write_text(lines.replace("|", "\n"), encoding="utf-8")
    vols = (
        "set 80347524 80400800 set 80400808 fa4 set 80400810 8 set 80400830 80400900 "  # 4004
        "set 80400908 fa5 set 80400910 8 walkfns game "  # 4005
    )
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 13 setb 80311ac8 64 "
    for flags, started in (
        ("", "fn_80210550(4004)"),
        ("set 80310b68 2000 ", "fn_80210550(4005)"),
    ):  # 365: bit 13
        out, err = play(
            driver,
            tmp_path,
            vols + here + flags + "frame frame frame frame safe",
            SOA_LAB="story:350-399;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert [x for x in out.splitlines() if x.startswith("fn_80210550")] == [started], (
            flags,
            out,
        )


@needs_cc
def test_a_travel_menus_warps_are_no_way_the_walker_can_take(driver, tmp_path):
    """A line other than a loop that warps to six places or more is a travel
    menu (a034a's rorensu, 25), whose place the walker cannot choose: its
    warps lead nowhere for the distances, and an exit that reached the aim only
    through one ranks nowhere. A loop's warps, which its own conditions pick,
    still count."""
    lab(tmp_path)
    menu = "w122a w002c w004a w008b w010a w013d"
    vol = "set 80347524 80400800 set 80400808 fa1 set 80400810 8 walkfns game "
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 13 setb 80311ac8 61 frame frame frame frame safe"
    for line, rank in (
        (f"034a M03005 {menu}", "the story's rank: none"),
        (f"034a loop {menu}", "the story's rank toward flag 381: 3"),
    ):
        (tmp_path / "story.txt").write_text(
            f"019a M04001 w034a\n{line}\n122a M04000 w122b\n122b M03000 s381\n", encoding="utf-8"
        )
        out, err = play(
            driver,
            tmp_path,
            vol + here,
            SOA_LAB="story:380-399;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        started = [x for x in err.splitlines() if "entry 4001 started" in x]
        assert len(started) == 1 and rank in started[0], (line, err)


@needs_cc
def test_a_warp_to_the_world_map_goes_to_the_letter_b6_holds(driver, tmp_path):
    """`019a M04001 w099@`: the world map loads at the letter B[6] gives, and
    each letter is its own place. With B[6] at 8 (stage i, whose 4022 lands
    on a122a) the exit ranks toward 381, in a122b; at 0 (stage a, no such
    landing) it does not: part H's walker left Yafutoma with B[6] at 0 and
    sailed stage a for 200,000 frames."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "019a M04001 w099@\n099i M04022 w122a\n122a M04000 w122b\n122b M03000 s381\n",
        encoding="utf-8",
    )
    vol = "set 80347524 80400800 set 80400808 fa1 set 80400810 8 walkfns game "
    here = "set 803475cc 6 set 80311aec 8 set 80311ac0 13 setb 80311ac8 61 "
    for b6, rank in ((8, "the story's rank toward flag 381: 3"), (0, "the story's rank: none")):
        out, err = play(
            driver,
            tmp_path,
            vol + here + f"setb 80310a22 {b6:x} frame frame frame frame safe",
            SOA_LAB="story:380-399;walk:0-5000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        started = [x for x in err.splitlines() if "entry 4001 started" in x]
        assert len(started) == 1 and rank in started[0], (b6, err)


@needs_cc
def test_the_walker_lands_where_the_story_goes_though_the_island_is_far(driver, tmp_path):
    """The world map loads its islands by the ship's distance, and the walker
    cannot sail: 099g's 4014 lands on the deserted island, where 317 is set,
    and its volume never came near. On the world map a landing the lines know
    that ranks before every live entry is started without its volume, said
    so; on a map the lines do not have, nothing is."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text("099g M04014 w017a\n017a loop s317\n", encoding="utf-8")
    said = (
        "a099g entry 4014 started at frame 4 with no volume here, in place of the sail there "
        "(the story's rank toward flag 317: 1)"
    )
    for letter, landed in (
        ("67", True),
        ("68", False),
    ):  # 099g, then 099h, which the lines do not have
        script = (
            f"set 803475cc 6 set 80311aec 8 set 80311ac0 63 setb 80311ac8 {letter} walkfns game "
            "frame frame frame frame safe"
        )
        out, err = play(
            driver,
            tmp_path,
            script,
            SOA_LAB="story:317-317;walk:0-1000:3",
            SOA_LAB_STORY=str(tmp_path / "story.txt"),
        )
        assert "loaded 1" in out, err
        assert ("fn_80210550(4014)" in out) == landed, (out, err)
        assert (said in err) == landed, err


@needs_cc
def test_the_lab_gives_the_gold_a_player_would_have_once_on_its_map(driver, tmp_path):
    """gold:MAP:N waits for MAP's field to run with no event, then raises the
    gold (0x8030BB40, the scripts' sys[0]) to N, said so, once: a017a's
    Brabham wants 25,000, which a run from a part card has not gathered. Gold
    already at N or more is left alone."""
    lab(tmp_path)
    script = (
        "set 8030bb40 d10 set 803475cc 6 set 80311aec 8 set 80311ac0 11 setb 80311ac8 62 safe "  # a017b
        "setb 80311ac8 61 set 80310bc0 80000000 safe "  # a017a, an event running
        "set 80310bc0 0 frame safe get 8030bb40 "  # quiet: 3344 -> 25000
        "set 8030bb40 0 frame safe get 8030bb40"  # spent: not given twice
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="gold:017a:25000")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("8030BB40")] == [
        "8030BB40=000061A8",
        "8030BB40=00000000",
    ], out
    assert err.count("lab: gold: ") == 1, err
    assert (
        "gold: 3344 -> 25000 on a017a at frame 1, in place of what a player would have gathered by then"
        in err
    ), err
    out, err = play(
        driver,
        tmp_path,
        script.replace("set 8030bb40 d10", "set 8030bb40 7530", 1),
        SOA_LAB="gold:017a:25000",
    )
    assert "gold: 30000 on a017a at frame 1, already 25000 or more" in err, err


@needs_cc
def test_the_lab_sets_a_flag_once_on_its_map_and_keeps_the_rest_of_the_word(driver, tmp_path):
    """flag:MAP:N waits for MAP's field to run with no event, then sets flag N
    alone (the other bits of its word kept) and says so, once."""
    lab(tmp_path)
    script = (
        "set 80310b48 1 set 803475cc 6 set 80311aec 8 set 80311ac0 74 setb 80311ac8 61 safe "  # a116a
        "set 80311ac0 4 set 80310bc0 80000000 safe "  # a004a, an event running
        "set 80310bc0 0 frame safe get 80310b48 "  # quiet: flag 100, bit 4
        "set 80310b48 1 frame safe get 80310b48"  # cleared again: not set twice
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="flag:004a:100")
    assert "loaded 1" in out, err
    assert [x for x in out.splitlines() if x.startswith("80310B48")] == [
        "80310B48=00000011",
        "80310B48=00000001",
    ], out
    assert err.count("lab: flag: ") == 1, err
    assert "lab: flag: 100 set on a004a at frame 1 (80310B48: 00000001 -> 00000011)" in err, err


@needs_cc
def test_the_lab_story_aims_past_a_flag_still_waiting_on_another(driver, tmp_path):
    """`013b req271 r272`: every place a013b sets 271 waits for 272, so with
    272 clear the aim is 272, and only once it is set, 271; the walker had
    spent 30,000 frames on 271 first."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "013b M06113 s271\n013b M06111 s272\n013b req271 r272\n", encoding="utf-8"
    )
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 d setb 80311ac8 62 "
        "frame frame frame frame safe "  # 4: 272 first
        "set 80310b5c 10000 frame frame frame safe"  # 272 set: now 271
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:271-272;walk:0-1000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    aims = [x.split("lab: story: ", 1)[1] for x in err.splitlines() if "lab: story: aiming" in x]
    assert aims == [
        "aiming at flag 272 (set in 013b); a013b is 0 warp(s) away",
        "aiming at flag 271 (set in 013b); a013b is 0 warp(s) away",
    ], err


@needs_cc
def test_the_lab_story_aims_at_the_field_flag_a_flag_waits_on(driver, tmp_path):
    """`013a req274 r1610`: a013a's loop plays the cutscene that sets 274
    only once field flag 1610 is set, and only a115a's 4000 sets it. So the
    aim is 1610, in 115a, one warp off; once it is set, 274."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(
        "013a loop s274\n013a req274 r1610\n013a M06000 w115a\n115a M04000 s1610 w013a\n",
        encoding="utf-8",
    )
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 d setb 80311ac8 61 "
        "frame frame frame frame safe "  # 4: 1610 first
        "set 80310c04 400 frame frame frame safe"  # 1610 set: now 274
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:274-274;walk:0-1000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    aims = [x.split("lab: story: ", 1)[1] for x in err.splitlines() if "lab: story: aiming" in x]
    assert aims == [
        "aiming at flag 1610 (set in 115a); a013a is 1 warp(s) away",
        "aiming at flag 274 (set in 013a); a013a is 0 warp(s) away",
    ], err


@needs_cc
def test_the_lab_story_starts_an_aims_patience_over_when_the_story_moves(driver, tmp_path):
    """Another flag of the window set while the walker aims at one starts the
    aim's 30,000 frames over, said so: part H's walker passed 358 over while
    Yafutoma's scenes set 366 to 372 around it."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(STORY, encoding="utf-8")
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 4 setb 80311ac8 61 setb 80310a22 5 "  # B[6] 5: stage f
        "frame frame frame frame safe "  # frame 4: aim 100
        + "frame " * 20000
        + "set 80310b48 20 safe "  # 20004: 101 set
        + "frame " * 20000
        + "safe "  # 40004: 20,000 frames since: kept
        + "frame " * 10000
        + "safe"  # 50004: 30,000: passed over
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:100-101;walk:0-200000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    lines = [
        x.split("lab: story: ", 1)[1]
        for x in err.splitlines()
        if "lab: story: " in x and "line(s)" not in x
    ]
    assert lines[:3] == [
        "aiming at flag 100 (set in 243a); a004a is 3 warp(s) away",
        "a flag of 100-101 set by frame 20004: flag 100's patience starts over",
        "flag 100 aimed at since frame 20004 and not set: passed over from frame 50004",
    ], err


@needs_cc
def test_the_lab_story_passes_over_an_aim_not_reached_in_30000_frames(driver, tmp_path):
    """A flag set only in a branch the run did not take, or on a later visit
    (part C's 123), would hold the walker for good: aimed at for 30,000
    frames and still clear, it is passed over, said so, and the next is the
    aim. Once nothing else the lines reach is left, each passed-over flag has
    a second go (a013b's 6113 sets 271 only once 272 is set), and is passed
    over for good only after that."""
    lab(tmp_path)
    (tmp_path / "story.txt").write_text(STORY, encoding="utf-8")
    script = (
        "set 803475cc 6 set 80311aec 8 set 80311ac0 4 setb 80311ac8 61 setb 80310a22 5 "  # B[6] 5: stage f
        "frame frame frame frame safe "  # frame 4: aim 100
        + ("frame " * 30000 + "safe ")
        * 4  # frames 30004, 60004, 90004 and 120004
    )
    out, err = play(
        driver,
        tmp_path,
        script,
        SOA_LAB="story:100-101;walk:0-200000:3",
        SOA_LAB_STORY=str(tmp_path / "story.txt"),
    )
    assert "loaded 1" in out, err
    lines = [
        x.split("lab: story: ", 1)[1]
        for x in err.splitlines()
        if "lab: story: " in x and "line(s)" not in x
    ]
    assert lines == [
        "aiming at flag 100 (set in 243a); a004a is 3 warp(s) away",
        "flag 100 aimed at since frame 4 and not set: passed over from frame 30004",
        "aiming at flag 101 (set in 116d); a004a is 4 warp(s) away",
        "flag 101 aimed at since frame 30004 and not set: passed over from frame 60004",
        "flag 100, passed over before, has a second go: nothing else the lines reach is left",
        "aiming at flag 100 (set in 243a); a004a is 3 warp(s) away",
        "flag 100 aimed at since frame 60004 and not set: passed over from frame 90004",
        "flag 101, passed over before, has a second go: nothing else the lines reach is left",
        "aiming at flag 101 (set in 116d); a004a is 4 warp(s) away",
        "flag 101 aimed at since frame 90004 and not set: passed over from frame 120004",
        "no flag in 100-101 is left for a line to set",
    ], err


@needs_cc
def test_the_lab_story_refuses_a_file_it_cannot_read(driver, tmp_path):
    """No file, a line that is not "MAP ENTRY sN.. wMAP..", a window past the
    flags the scan keeps, or a second story item: each refuses the mod."""
    lab(tmp_path)
    good, bad = tmp_path / "story.txt", tmp_path / "bad.txt"
    good.write_text(STORY, encoding="utf-8")
    bad.write_text("004a M03005 w250a\n004a M03005 x9\n", encoding="utf-8")
    cases = [
        ("story:100-149", tmp_path / "missing.txt", "names no file that can be read"),
        ("story:100-149", bad, "line 2 is not"),
        ("story:100-1024", good, ""),
        ("story:100-149;story:150-199", good, ""),
    ]
    for items, path, why in cases:
        out, err = play(driver, tmp_path, "safe", SOA_LAB=items, SOA_LAB_STORY=str(path))
        assert "loaded 0" in out and "SOA_LAB item not understood: story:" in err, (items, err)
        assert why in err, (items, err)


@needs_cc
def test_the_lab_dumps_from_where_a_chain_ends_once(driver, tmp_path):
    """dump:F:C:N reads N bytes from the address C ends on (a trailing `*`
    takes the word there as the address), eight words a line, once."""
    lab(tmp_path)
    script = (
        "set 8034727c 80400100 set 80400100 11111111 set 8040011c 88888888 set 80400120 99999999 "
        "safe frame safe"
    )
    out, err = play(driver, tmp_path, script, SOA_LAB="dump:0:0x8034727C*:36")
    assert "loaded 1" in out, err
    lines = [x for x in err.splitlines() if "lab: dump" in x]
    assert lines == [
        "[mod] lab: dump dump:0:0x8034727C*:36: frame 0: 36 bytes from 80400100",
        "[mod] lab: dump +0000: 11111111 00000000 00000000 00000000 00000000 00000000 00000000 88888888",
        "[mod] lab: dump +0020: 99999999 00000000 00000000 00000000 00000000 00000000 00000000 00000000",
    ], err


@needs_cc
def test_a_lab_item_it_cannot_read_refuses_the_mod(driver, tmp_path):
    lab(tmp_path)
    bad_items = ("peek:5-2:0x80000000", "entry:1-2:4005", "jump:1:2", "peek:1:0x80000000+")
    bad_items += ("flag:4a:100", "flag:004a:27328", "flag:004a:x", "flag:004A:100")
    bad_items += ("finish:0-9", "finish:0-9:0", "finish:9-0:5", "finish:0-9:x")
    turns = ("turn:0-9:4:a", "turn:0-9:0:", "turn:0-9:0:a/jump", "turn:0-9:0")
    dumps = ("dump:0:0x80000000:6", "dump:0-5:0x80000000:8", "dump:0:0x80000000:9000")
    walks = ("walk:0-9", "walk:0-9:0", "walk:9-0:300", "walk:0-9:x", "assist:0-9:3")
    walks += (
        "save:0-9",
        "save:0-9:",
        "save:0-9:a/jump",
        "turn:0-9:0:a#0",
        "turn:0-9:0:a#x",
    )
    for bad in (*bad_items, "hold-hp:5-2", "hold-hp:x", *turns, *dumps, *walks):
        out, err = play(driver, tmp_path, "safe", SOA_LAB=bad)
        assert "loaded 0" in out and f"SOA_LAB item not understood: {bad}" in err, (bad, err)


@needs_cc
def test_a_pad_filter_changes_what_the_game_reads(driver, tmp_path):
    """The filter sees each read with its frame and may change it: this one
    drops START from frame 10 and leaves A alone. si.c calls it after the
    recording's copy, so a recording holds the input as the person gave it."""
    dll(tmp_path, "nostart", "PADF")
    out, err = play(driver, tmp_path, "pad 5 1100 pad 20 1100 pad 21 0100 report")
    pads = [line for line in out.splitlines() if line.startswith("pad ")]
    assert pads == ["pad 5 1100 filtered", "pad 20 0100 filtered", "pad 21 0100 filtered"], out
    assert "3 controller read(s)" in err, err


@needs_cc
def test_without_a_filter_si_c_is_never_handed_one(driver, tmp_path):
    """A mod that registers none leaves the read path exactly as it was."""
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "pad 20 1100")
    assert "pad 20 1100 unfiltered" in out, out


@needs_cc
def test_a_projection_filter_sees_each_projection_and_may_change_it(driver, tmp_path):
    """gxr.c hands over GXSetProjection's six parameters once per new
    projection; this filter widens the 3D view and leaves the 2D layer,
    which is orthographic, as it was."""
    dll(tmp_path, "wide", "PROJ")
    out, err = play(
        driver, tmp_path, "proj 0 1.5 0 2 0 -1 -0.1 proj 1 0.003 -1 -0.004 1 -1 0 report"
    )
    projs = [line for line in out.splitlines() if line.startswith("proj ")]
    assert projs == [
        "proj 1.1250 0.0000 2.0000 0.0000 -1.0000 -0.1000 filtered",
        "proj 0.0030 -1.0000 -0.0040 1.0000 -1.0000 0.0000 filtered",
    ], out
    assert "2 projection(s)" in err, err


@needs_cc
def test_without_a_projection_filter_gxr_c_is_never_handed_one(driver, tmp_path):
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "proj 0 1.5 0 2 0 -1 -0.1")
    assert "proj 1.5000 0.0000 2.0000 0.0000 -1.0000 -0.1000 unfiltered" in out, out


@needs_cc
def test_a_texture_provider_replaces_by_source_hash(driver, tmp_path):
    """Asked once per decode with the source hash -- the cache's key, stable
    from run to run -- it replaces the textures it knows and leaves the rest;
    the image may be any size."""
    dll(tmp_path, "pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 1234567890ABCD42 8 8 tex 1234567890ABCD43 8 8 report")
    texs = [line for line in out.splitlines() if line.startswith("tex ")]
    assert texs == ["tex replaced 2x2 first C80000FF", "tex kept (asked)"], out
    assert "2 texture(s)" in err, err


@needs_cc
def test_among_providers_the_first_that_answers_wins(driver, tmp_path):
    """Mods load in folder order, and the first provider to answer 1 is the
    one whose image is used; a later one is not asked."""
    dll(tmp_path, "a-pack", "TEX=100")
    dll(tmp_path, "b-pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 42 4 4 report")
    assert "tex replaced 2x2 first 640000FF" in out, out
    assert (
        f"[mod] b-pack {LIB}:" in err and "0 texture(s)" in err.split(f"[mod] b-pack {LIB}:")[1]
    ), err


@needs_cc
def test_without_a_provider_the_renderer_is_never_handed_one(driver, tmp_path):
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "tex 42 4 4")
    assert "tex kept (no provider)" in out, out


# --------------------------------------------------------------------------
# The review of 2026-09-25
# --------------------------------------------------------------------------


@needs_cc
def test_a_callback_registered_after_init_is_refused(driver, tmp_path):
    """The dispatchers are wired when loading ends, so a later registration
    would be accepted and never called; now it returns 0, and the filter it
    offered never touches a read."""
    dll(tmp_path, "latecomer", "LATE")
    out, err = play(driver, tmp_path, "frame pad 5 1100")
    assert "[mod] latecomer: late registration 0" in err, err
    assert "pad 5 1100 unfiltered" in out, out


@needs_cc
def test_a_line_too_long_to_read_whole_is_refused(driver, tmp_path):
    """Cut at 511 characters, `state=18` would read as `state=1`."""
    long_line = "every_frame 0x80346d28 = 0 when scene=6" + " " * 480 + "state=18\n"
    mod(tmp_path, "m", patches=long_line)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "patches.txt:1: a line longer than 511 characters" in err, err


@needs_cc
def test_a_folder_the_table_cannot_hold_is_named(driver, tmp_path):
    name = "a" * 70
    mod(tmp_path, name)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out, err
    assert f"{name}: a mod's folder name has to be under 64 characters; not read" in err, err


@needs_cc
def test_mods_past_the_recording_line_are_counted_not_cut(driver, tmp_path):
    """The config line keeps whole entries and names the rest as a count and
    one hash, never a folder name with half a hash."""
    names = [f"mod-{i:02d}-with-a-long-folder-name" for i in range(12)]
    for n in names:
        mod(tmp_path, n)
    out, _ = play(driver, tmp_path, "describe")
    line = next(x for x in out.splitlines() if x.startswith("describe ["))[len("describe [") : -1]
    entries = line[len("mods=") :].split(",")
    *whole, rest = entries
    assert all(e.split(":")[0] in names and len(e.split(":")[1]) == 8 for e in whole), line
    count, digest = rest.split(":")
    assert count == f"+{12 - len(whole)} more" and len(digest) == 8, line


@needs_cc
def test_an_image_too_large_is_refused_and_the_next_provider_asked(driver, tmp_path):
    dll(tmp_path, "a-huge", "TEX=100", "BIG")
    dll(tmp_path, "b-pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 42 4 4")
    assert "a 5000x5000 image is refused, 4096 on a side is the most" in err, err
    assert "tex replaced 2x2 first C80000FF" in out, out


# --------------------------------------------------------------------------
# M4: calling the game from a mod
# --------------------------------------------------------------------------


@needs_cc
def test_call_guest_runs_at_a_safe_point_and_puts_every_register_back(driver, tmp_path):
    """From a safe-point callback the game's function runs with the
    arguments in r3 and r4 and its answer comes back; what it clobbered --
    r14, f14, a GQR -- is put back, and the GQR is reported."""
    dll(tmp_path, "caller", "CALL")
    out, err = play(driver, tmp_path, "game safe regs")
    assert "[mod] caller: call at safe point 1 -> 42" in err, err
    assert "left a GQR changed; it is put back" in err, err
    assert "r14 14141414 gqr3 00000000 f14 0.0" in out, out


@needs_cc
def test_call_guest_is_refused_everywhere_else(driver, tmp_path):
    """In soa_mod_init, at a frame end (inside the XFB copy), and at an
    address that is not the start of a function -- which dispatched would
    trap and end the run."""
    dll(tmp_path, "caller", "CALL")
    out, err = play(driver, tmp_path, "game frame safe")
    assert "[mod] caller: call in init 0" in err, err
    assert "[mod] caller: call at frame end 0" in err, err
    assert "only a safe-point, scene or map callback may call the game" in err, err
    assert "[mod] caller: call mid-function 0" in err, err
    assert "80003104 is not the start of a function in this program" in err, err
    assert "dispatch of" not in out, out


@needs_cc
def test_call_guest_refuses_when_r2_and_r13_are_not_the_games(driver, tmp_path):
    dll(tmp_path, "caller", "CALL")
    _, err = play(driver, tmp_path, "safe")
    assert "call at safe point 0" in err and "are not the game's 80350000 and 8034E720" in err, err


@needs_cc
def test_call_guest_is_refused_inside_an_interrupt_handler(driver, tmp_path):
    """A safe point reached while a handler runs is not a point where the
    game's code may be called: the handler owns the registers."""
    dll(tmp_path, "caller", "CALL")
    _, err = play(driver, tmp_path, "game irq safe")
    assert "call at safe point 0" in err and "refused: inside an interrupt handler" in err, err


# --------------------------------------------------------------------------
# Manifest 2 (PLAN-GAMEPLAY-MODS.md section F): an id and a version the
# recording names a mod by, api as the least the mod needs, x_ keys kept for
# later ports, and one id to one mod.
# --------------------------------------------------------------------------

V2 = f"manifest = 2\nid = enc\nversion = 1.2\nname = Enc\nauthors = someone\napi = 1\ndol_sha1 = {SHA}\n"


@needs_cc
def test_a_manifest_2_mod_loads_and_the_recording_names_it_by_id(driver, tmp_path):
    mod(tmp_path, "some-folder", ini=V2)
    mod(tmp_path, "v1-folder")
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 2" in out, err
    assert "some-folder, enc@1.2)" in err, err
    line = next(x for x in out.splitlines() if x.startswith("describe ["))
    # name order of the folders; a manifest 2 mod by id@version, a version 1
    # mod by its folder as before, so a recording made before is still read
    assert line.startswith("describe [mods=enc@1.2:") and ",v1-folder:" in line, line


@needs_cc
@pytest.mark.parametrize(
    "ini, why",
    [
        (V2.replace("id = enc\n", ""), "manifest 2 and no `id = `"),
        (V2.replace("version = 1.2\n", ""), "manifest 2 and no `version = `"),
        (V2.replace("id = enc", "id = Enc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = -enc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = e,nc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = " + "e" * 64), "an id is lowercase letters"),
        (V2.replace("version = 1.2", "version = 1,2"), "a version is letters"),
        (V2.replace("version = 1.2", "version = .1"), "a version is letters"),
        (V2.replace("manifest = 2", "manifest = 3"), "this port reads manifests 1 and 2"),
        (
            V2.replace("manifest = 2\n", ""),
            "`id` is a manifest 2 key, and this mod.ini has no `manifest = 2`",
        ),
        (
            V2.replace("manifest = 2", "manifest = 1"),
            "`id` is a manifest 2 key, and this mod.ini has manifest = 1",
        ),
        (V2.replace("api = 1", "api = 0"), "is not a version number"),
        (V2.replace("api = 1", "api = one"), "is not a version number"),
        (V2.replace("api = 1", "api = 2"), "this port speaks api 1"),
        (V2 + "homepage = x\n", "is not a mod.ini key"),
    ],
    ids=[
        "no-id",
        "no-version",
        "upper-id",
        "dash-first",
        "comma-id",
        "long-id",
        "comma-version",
        "dot-first",
        "manifest-3",
        "v2-key-no-manifest",
        "v2-key-manifest-1",
        "api-0",
        "api-word",
        "api-newer",
        "unknown-key",
    ],
)
def test_a_bad_manifest_2_is_refused(driver, tmp_path, ini, why):
    mod(tmp_path, "m", ini=ini)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and why in err and "the mod is not loaded" in err, err


@needs_cc
def test_an_x_key_is_noted_and_the_mod_loads(driver, tmp_path):
    """A key a later port may define: this one says it does not know it and
    loads the mod; a misspelled key without the prefix still refuses it."""
    mod(tmp_path, "m", ini=V2 + "x_homepage = https://example.invalid\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert "mod.ini:8: `x_homepage` is not a key this port knows" in err, err


@needs_cc
def test_two_mods_with_one_id_the_second_is_refused_and_names_the_first(driver, tmp_path):
    mod(tmp_path, "a-first", ini=V2)
    mod(tmp_path, "b-second", ini=V2.replace("version = 1.2", "version = 2.0"))
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 1" in out, err
    assert "b-second/mod.ini: its id, enc, is already the mod's in folder a-first" in err, err
    assert "describe [mods=enc@1.2:" in out, out


def test_the_shipped_mods_are_manifest_2():
    """The folders a mod author copies from carry the manifest a new mod
    should: an id and a version, api as a minimum."""
    for folder in (
        "mods/autotext",
        "mods/battle-boosts",  # R4
        "mods/coop",
        "mods/difficulty",  # R3
        "mods/encounter-rate",
        "examples/mods/encounters-off",
        "examples/mods/map-log",
        "examples/mods/map-alias",  # T1 (disc-layer I6)
        "examples/mods/damage-double",  # R0
        "examples/mods/battle-tally",  # X2
    ):
        keys = {}
        for line in (ROOT / folder / "mod.ini").read_text(encoding="utf-8").splitlines():
            key, eq, value = line.partition("=")
            if eq and not line.lstrip().startswith("#"):
                keys[key.strip()] = value.strip()
        assert keys.get("manifest") == "2" and keys.get("id") == Path(folder).name, (folder, keys)
        assert keys.get("version") and keys.get("api") == "1", (folder, keys)


@pytest.fixture(scope="module")
def driver_api2(tmp_path_factory):
    """The same loader built to speak mod API 2, which no port does yet: the
    only way to show that a manifest's `api` is a minimum, since at API 1 a
    minimum and an exact match accept the same files."""
    return build_driver(tmp_path_factory, "MOD_API=2")


@needs_cc
@pytest.mark.parametrize("need, loads", [("1", True), ("2", True), ("3", False)])
def test_api_is_the_least_the_mod_needs(driver_api2, tmp_path, need, loads):
    mod(tmp_path, "m", ini=V2.replace("api = 1", f"api = {need}"))
    out, err = play(driver_api2, tmp_path)
    assert ("loaded 1" in out) == loads, err
    if not loads:
        assert "api = 3, and this port speaks api 2" in err, err


@needs_cc
def test_a_manifest_2_without_api_is_told_what_is_missing(driver, tmp_path):
    mod(tmp_path, "m", ini=V2.replace("api = 1\n", ""))
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "no `api = `" in err and "no `api = 1`" not in err, err


@needs_cc
def test_a_manifest_2_mod_past_the_recording_line_is_keyed_by_id_not_folder(driver, tmp_path):
    """The `+N more` hash takes each mod by the name the line would have
    given it: renaming the folder of a manifest 2 mod that did not fit --
    same id, version and bytes, same place in the load order -- leaves the
    line as it was, as renaming one that fits does. Keyed by folder (the
    mutation), a recording replayed after the rename would claim another
    configuration."""
    ids = [f"a-manifest-two-mod-with-a-rather-long-id-{i:02d}" for i in range(12)]
    for i, mid in enumerate(ids):
        mod(tmp_path, f"m{i:02d}", ini=V2.replace("id = enc", f"id = {mid}"))
    out, _ = play(driver, tmp_path, "describe")
    before = next(x for x in out.splitlines() if x.startswith("describe ["))
    assert "more:" in before and ids[-1] not in before, before
    (tmp_path / "m11").rename(tmp_path / "m11-renamed")
    out, _ = play(driver, tmp_path, "describe")
    after = next(x for x in out.splitlines() if x.startswith("describe ["))
    assert after == before, (before, after)


# --------------------------------------------------------------------------
# mods/encounter-rate (PLAN-GAMEPLAY-MODS P1a) on the fake guest
# --------------------------------------------------------------------------

ENC = ROOT / "mods" / "encounter-rate"
FIELD = "set 803475cc 6 "
BYTE = "get 8030b7ac "  # the multiplier is the second byte of this word
# Character 0's accessory is the high half of 0x8030B808; accessory 210's
# record's first effect is {84, 0, 100}, 211's {84, 0, 5}.
ACC_210 = "set 8030b808 00d20000 set 802c75f8 54000064 "
ACC_211_ON_1 = "set 8030b864 00d30000 set 802c7620 54000005 "


def shipped(tmp_path: Path, source: str | None = None, folder: Path = ENC) -> Path:
    """A shipped mod (mods/encounter-rate unless `folder` says) built with the
    line --link uses, into a folder whose mod.ini pins the fake DOL -- or,
    given `source`, a mutation of it."""
    import recompile

    d = tmp_path / folder.name
    d.mkdir(parents=True)
    ini = (folder / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    src = d / "mod.c"
    src.write_text(source or (folder / "mod.c").read_text(encoding="utf-8"), encoding="utf-8")
    if PROFILE.style == "msvc":
        cc(recompile.mod_dll_command(src), d)
    else:
        cc(recompile.gnu_mod_dll_command(PROFILE, src, d), d)
    return d


def multipliers(out: str) -> list[int]:
    """The multiplier byte at each `get` of its word, in order."""
    return [
        int(line.split("=")[1], 16) >> 16 & 0xFF
        for line in out.splitlines()
        if line.startswith("8030B7AC=")
    ]


def writes(err: str) -> int:
    line = next(ln for ln in err.splitlines() if f"encounter-rate {LIB}:" in ln)
    return int(line.rsplit(";", 1)[1].split()[0])


def test_every_shipped_mod_is_built_by_link():
    """--link builds each mod.c under mods/ and examples/mods/ (recompile.py's
    list): the shipped mod is among them, beside the example."""
    import recompile

    srcs = {p.parent.relative_to(ROOT).as_posix() for p in recompile.mod_dll_sources()}
    assert {"mods/autotext", "mods/coop", "mods/encounter-rate", "examples/mods/map-log"} <= srcs, (
        srcs
    )


@needs_cc
def test_encounter_rate_unset_writes_nothing(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, FIELD + "frame " * 100 + BYTE + "report")
    assert "loaded 1" in out, err
    assert "[mod] encounter-rate: random battles normal in the field" in err, err
    assert "[mod] encounter-rate: base 50 (none)" in err, err
    assert writes(err) == 0 and multipliers(out) == [0], (out, err)


@needs_cc
def test_encounter_rate_presets_without_an_accessory(driver, tmp_path):
    shipped(tmp_path)
    for preset, want in (("half", 25), ("double", 100), ("off", 0)):
        out, err = play(
            driver,
            tmp_path,
            FIELD + "setb 8030b7ad ff frame " + BYTE + "report",
            SOA_ENCOUNTERS=preset,
        )
        assert multipliers(out) == [want], (preset, out, err)
        assert writes(err) == 1, (preset, err)


@needs_cc
def test_encounter_rate_works_from_the_accessory_as_the_game_does(driver, tmp_path):
    """Base is the effect-84 value of the last character whose accessory has
    one: 210 on character 0 gives 100, and 211 on character 1 after it 5."""
    shipped(tmp_path)
    out, err = play(
        driver, tmp_path, FIELD + ACC_210 + "frame frame " + BYTE, SOA_ENCOUNTERS="half"
    )
    assert multipliers(out) == [50], out
    assert "base 100 (character 0's accessory 210)" in err, err
    out, _ = play(driver, tmp_path, FIELD + ACC_210 + "frame " + BYTE, SOA_ENCOUNTERS="double")
    assert multipliers(out) == [127], out
    out, err = play(
        driver, tmp_path, FIELD + ACC_210 + ACC_211_ON_1 + "frame " + BYTE, SOA_ENCOUNTERS="half"
    )
    assert multipliers(out) == [2] and "base 5 (character 1's accessory 211)" in err, (out, err)


@needs_cc
def test_encounter_rate_writes_only_in_the_field(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(
        driver, tmp_path, "set 803475cc 7 frame frame " + BYTE + "report", SOA_ENCOUNTERS="off"
    )
    assert multipliers(out) == [0] and writes(err) == 0, (out, err)


HOLD = (
    FIELD
    + "setb 8030b7ad ff pad 1 0200 "
    + ("frame " + BYTE) * 30
    + "pad 31 0000 "
    + ("frame " + BYTE) * 5
)


@needs_cc
def test_hold_b_at_normal_writes_zero_then_puts_the_game_s_value_back_once(driver, tmp_path):
    """Thirty frames with B held read 0; the first frame after B is let go
    writes the game's own 0xFF, and after that nothing more is written."""
    shipped(tmp_path)
    out, err = play(driver, tmp_path, HOLD + "report")
    assert multipliers(out) == [0] * 30 + [0xFF] * 5, out
    assert writes(err) == 31, err


@needs_cc
def test_hold_b_restores_the_accessory_s_value_not_ff(driver, tmp_path):
    shipped(tmp_path)
    out, _ = play(driver, tmp_path, ACC_210 + HOLD.replace("setb 8030b7ad ff", "setb 8030b7ad 64"))
    assert multipliers(out)[30:] == [0x64] * 5, out


@needs_cc
def test_hold_b_off_leaves_the_controller_alone(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, HOLD + "report", SOA_ENCOUNTERS_HOLD_B="0")
    assert "pad 1 0200 unfiltered" in out and multipliers(out) == [0xFF] * 35, out
    assert "holding B keeps them away off" in err and writes(err) == 0, err


@needs_cc
def test_a_preset_the_mod_does_not_know_is_the_game_s_rate(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, FIELD + "frame " + BYTE + "report", SOA_ENCOUNTERS="HALF")
    assert "SOA_ENCOUNTERS=HALF is not off, half, normal or double" in err, err
    assert writes(err) == 0 and multipliers(out) == [0], (out, err)


@needs_cc
def test_the_mutations_fail_the_checks(driver, tmp_path):
    """The spec's two mutations: halving the byte read back instead of base
    compounds frame on frame (50, 25, 12, ...), and a build without the
    restore leaves battles off after one press of B."""
    src = (ENC / "mod.c").read_text(encoding="utf-8")
    compound = "    base = base_now(&game, &who, &item);\n"
    assert src.count(compound) == 1
    reread = compound + (
        "    { uint8_t now; if (g_api->read8(MULTIPLIER, &now) && now != 0xFF) base = (int8_t)now; }\n"
    )
    shipped(tmp_path / "a", src.replace(compound, reread))
    out, _ = play(
        driver,
        tmp_path / "a",
        FIELD + ACC_210 + "setb 8030b7ad 64 " + ("frame " + BYTE) * 3,
        SOA_ENCOUNTERS="half",
    )
    assert multipliers(out) == [50, 25, 12], out  # the shipped mod reads 50, 50, 50

    restore = "        if (g_dirty && g_api->write8(MULTIPLIER, (uint8_t)game)) g_dirty = 0;\n"
    assert src.count(restore) == 1
    shipped(tmp_path / "b", src.replace(restore, ""))
    out, _ = play(driver, tmp_path / "b", HOLD)
    assert multipliers(out)[30:] == [0] * 5, out  # the shipped mod reads FF


# --------------------------------------------------------------------------
# mods/autotext (PLAN-GAMEPLAY-MODS P11) on the fake guest
# --------------------------------------------------------------------------

AUTO = ROOT / "mods" / "autotext"


def window(state: int, flags: int = 0, task: int = 0x80400000) -> str:
    """The message window as the game keeps it: the task at 0x80346E4C, its
    context at task + 36, the flags the context's first halfword, and the
    state the s16 at 0x80346E64 (the high half of its word)."""
    ctx = 0x80400100
    return (
        f"set 803475cc 6 set 80346e4c {task:x} set 80400024 {ctx:x} "
        f"set {ctx:x} {flags << 16:x} set 80346e64 {(state & 0xFFFF) << 16:x} "
    )


def reads(first: int, last: int, buttons: int = 0) -> str:
    return "".join(f"pad {f} {buttons:x} " for f in range(first, last + 1))


def pressed(out: str) -> list[int]:
    """The frames whose controller read the game got with A down."""
    got = []
    for line in out.splitlines():
        parts = line.split()
        if parts[:1] == ["pad"] and int(parts[2], 16) & 0x0100:
            got.append(int(parts[1]))
    return got


@needs_cc
def test_autotext_presses_a_once_per_complete_page_after_the_delay(driver, tmp_path):
    """State 4 and no flags: the wait starts at the first read, and 45
    frames on (SOA_AUTOTEXT=on) A goes down for two frames and up for two;
    not again while the page is still up; again on the next page."""
    shipped(tmp_path, folder=AUTO)
    script = window(4) + reads(1, 60) + window(3) + reads(61, 62) + window(4) + reads(63, 120)
    out, err = play(driver, tmp_path, script, SOA_AUTOTEXT="on")
    assert pressed(out) == [46, 47, 108, 109], pressed(out)
    assert "[mod] autotext: frame 46 page advanced after 45 frames" in err, err
    assert "[mod] autotext: frame 108 page advanced after 45 frames" in err, err


@needs_cc
@pytest.mark.parametrize(
    "state, flags, task",
    [
        (4, 0x10, 0x80400000),
        (4, 0x40, 0x80400000),
        (6, 0x10, 0x80400000),  # a choice box carries 0x10, as the game's does
        (8, 0, 0x80400000),
        (4, 0, 0),
    ],
    ids=["after-a-choice", "auto-scroll", "choice", "state-8", "no-window"],
)
def test_autotext_never_presses_where_the_game_decides(driver, tmp_path, state, flags, task):
    shipped(tmp_path, folder=AUTO)
    out, _ = play(driver, tmp_path, window(state, flags, task) + reads(1, 120), SOA_AUTOTEXT="10")
    assert pressed(out) == [], pressed(out)


@needs_cc
def test_autotext_leaves_a_page_the_person_pressed_on(driver, tmp_path):
    shipped(tmp_path, folder=AUTO)
    script = window(4) + reads(1, 5) + reads(6, 6, 0x0100) + reads(7, 60)
    out, _ = play(driver, tmp_path, script, SOA_AUTOTEXT="10")
    assert pressed(out) == [6], pressed(out)  # theirs, and no press of the mod's


@needs_cc
@pytest.mark.parametrize("value", ["0", "", "soon"])
def test_autotext_off_never_presses(driver, tmp_path, value):
    shipped(tmp_path, folder=AUTO)
    out, err = play(driver, tmp_path, window(4) + reads(1, 120), SOA_AUTOTEXT=value)
    assert pressed(out) == [] and "unfiltered" in out, out
    if value == "soon":
        assert "SOA_AUTOTEXT=soon is not 0, 1, on or a number of frames" in err, err


@needs_cc
def test_autotext_mutations_fail_the_checks(driver, tmp_path):
    """Without the flags guard it presses on a page the game turns itself;
    the test switch presses in a choice box."""
    src = (AUTO / "mod.c").read_text(encoding="utf-8")
    guard = " && !(state == STATE_PAGE && (flags & (FLAG_AFTER_CHOICE | FLAG_AUTO_SCROLL)))"
    assert src.count(guard) == 1
    shipped(tmp_path / "a", src.replace(guard, ""), folder=AUTO)
    out, _ = play(driver, tmp_path / "a", window(4, 0x10) + reads(1, 30), SOA_AUTOTEXT="10")
    assert pressed(out) == [11, 12], pressed(out)
    shipped(tmp_path / "b", folder=AUTO)
    out, _ = play(
        driver,
        tmp_path / "b",
        window(6, 0x10) + reads(1, 30),
        SOA_AUTOTEXT="10",
        SOA_AUTOTEXT_TEST="press-in-choice",
    )
    assert pressed(out) == [11, 12], pressed(out)


@needs_cc
def test_host_buttons_reach_a_mod_as_si_gives_them(driver, tmp_path):
    """host_buttons (CH1) is si.c's g_host, through the setter main.c calls:
    here a stub the driver's `host` command sets."""
    dll(tmp_path, "hostmod", "HOST")
    _, err = play(driver, tmp_path, "host 0 frame host 9 frame host 1 frame")
    assert [ln for ln in err.splitlines() if "hostmod: host" in ln] == [
        "[mod] hostmod: host 0",
        "[mod] hostmod: host 9",
        "[mod] hostmod: host 1",
    ], err


@needs_cc
def test_a_mod_built_against_the_header_before_host_buttons_still_loads(driver, tmp_path):
    """The table grows only at the end: map-log built against soa_mod.h as it
    was before CH1 appended host_buttons loads and runs on this port."""

    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (CH1).")
    end = header.index("uint32_t (*host_buttons)(void);", start) + len(
        "uint32_t (*host_buttons)(void);\n"
    )
    old = header[:start] + header[end:]
    assert "(*host_buttons)" not in old and "(*call_guest)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    d = tmp_path / "mods" / "map-log"
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "map-log" / "mod.c", include=inc)
    out, err = play(driver, tmp_path / "mods", "set 803475cc 6 set 80311aec 3 safe")
    assert "loaded 1" in out and "[mod] map-log: map-log loaded" in err, (out, err)


def skipping(state: int, flags: int = 0) -> str:
    return window(state, flags) + "host 1 "


@needs_cc
def test_hold_to_skip_presses_in_states_3_and_4_while_lb_is_held(driver, tmp_path):
    """P11b: with the host LB held, A on the two-on, two-off cadence in state 3
    (text appearing) and 4 (a complete page) -- at once, not after the
    delay -- and nothing once LB is let go but the ordinary auto-advance."""
    shipped(tmp_path, folder=AUTO)
    script = (
        skipping(3)
        + reads(1, 8)
        + skipping(4)
        + reads(9, 12)
        + window(4)
        + "host 0 "
        + reads(13, 80)
    )
    out, err = play(driver, tmp_path, script, SOA_AUTOTEXT="on")
    assert pressed(out)[:6] == [1, 2, 5, 6, 9, 10], pressed(out)
    assert "[mod] autotext: frame 1 skip press in state 3" in err, err
    assert "[mod] autotext: frame 9 skip press in state 4" in err, err
    assert "not in recordings" not in err, err  # they are, since the event track's E2
    # LB let go on a page the skip already pressed: it waits for the next page
    assert pressed(out)[6:] == [], pressed(out)


@needs_cc
@pytest.mark.parametrize(
    "state, flags", [(6, 0x10), (4, 0x10), (4, 0x40), (3, 0x40), (8, 0), (1, 0)]
)
def test_hold_to_skip_never_presses_where_the_game_decides(driver, tmp_path, state, flags):
    shipped(tmp_path, folder=AUTO)
    out, _ = play(driver, tmp_path, skipping(state, flags) + reads(1, 60), SOA_AUTOTEXT="100")
    assert pressed(out) == [], pressed(out)


@needs_cc
def test_without_lb_it_only_auto_advances(driver, tmp_path):
    shipped(tmp_path, folder=AUTO)
    out, err = play(
        driver, tmp_path, window(3) + reads(1, 10) + window(4) + reads(11, 70), SOA_AUTOTEXT="on"
    )
    assert pressed(out) == [56, 57] and "skip press" not in err, (pressed(out), err)


RE_PEEK = re.compile(r"^\[peek\] frame (\d+): ([0-9A-Fa-f]{8}) = ([0-9A-Fa-f]{8})")


def check_p11b(log: str) -> list[str]:
    """P11b's live rules, over a run of P11's with LB held from 3000 and
    SOA_PEEK of the window state and the committed map: a skip press in
    state 3; the first choice (6) after 3002 under 45 frames after the first
    3 after 3002; the choice resting at 6 until 6000; a002b only after the
    A at 7300."""
    state, mapn, letter = {}, {}, {}
    for ln in log.splitlines():
        m = RE_PEEK.match(ln)
        if m:
            f, a, v = int(m.group(1)), int(m.group(2), 16), int(m.group(3), 16)
            if a == 0x80346E64:
                state[f] = v >> 16
            elif a == 0x80311AC0:
                mapn[f] = v
            elif a == 0x80311AC8:
                letter[f] = v >> 24
    problems = []
    if "skip press in state 3" not in log:
        problems.append("no skip press in state 3")
    first3 = next((f for f in sorted(state) if f > 3002 and state[f] == 3), None)
    first6 = next((f for f in sorted(state) if f > 3002 and state[f] == 6), None)
    if first3 is None or first6 is None or first6 - first3 >= 45:
        problems.append(
            f"the first 6 ({first6}) is not under 45 frames after the first 3 ({first3})"
        )
    if first6 is not None and any(state[f] != 6 for f in sorted(state) if first6 <= f < 6000):
        problems.append(f"the choice left 6 before 6000 (from {first6})")
    a002b = next((f for f in sorted(mapn) if mapn[f] == 2 and letter.get(f) == 0x62), None)
    if a002b is None or a002b < 7300:
        problems.append(f"a002b committed at {a002b}, not after 7300")
    return problems


def test_the_p11b_check_fails_each_rule_broken():
    """The live check's own test: a synthetic log that passes, and the same
    log with each rule broken in turn."""

    def log(skip3=True, first6=3100, rest6=True, a002b=7336):
        lines = []
        if skip3:
            lines.append("[mod] autotext: frame 3090 skip press in state 3")
        for f in range(3003, 7400):
            s = 1 if f < 3085 else 3 if f < first6 else 6 if f < 6000 else 1
            if not rest6 and f == 5000:
                s = 4
            lines.append(f"[peek] frame {f}: 80346E64 = {s << 16:08X} (retrace 1)")
            n, letter = (2, 0x62) if f >= a002b else (355, 0x61)
            lines.append(f"[peek] frame {f}: 80311AC0 = {n:08X} (retrace 1)")
            lines.append(f"[peek] frame {f}: 80311AC8 = {letter << 24:08X} (retrace 1)")
        return "\n".join(lines)

    assert check_p11b(log()) == []
    assert check_p11b(log(skip3=False)) == ["no skip press in state 3"]
    assert "not under 45 frames" in check_p11b(log(first6=3140))[0]
    assert "left 6 before 6000" in check_p11b(log(rest6=False))[0]
    assert "a002b committed at 5000" in check_p11b(log(a002b=5000))[0]


RE_SI = re.compile(r"^\[si\] frame (\d+) \(retrace \d+\): buttons ([0-9A-Fa-f]{4})")
RE_COOP = re.compile(r"^\[mod\] coop: frame (\d+) (.*)$")
FOCUS = 0  # two rights from Attack stop at Focus (FINDINGS "P10b's spike")
DIRECTIONS = 0x0003  # left, right


def recorded_presses(pad: str) -> set[int]:
    """The frames a recording shows a button of port 1's going down or held
    in a new combination: every line whose buttons are not "-". The event
    track's `F @kind` lines (pad 2, the host buttons) are not port 1's."""
    got = set()
    for line in pad.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] != "-" and not parts[1].startswith("@"):
            got.add(int(parts[0]))
    return got


def recorded_a(pad: str) -> set[int]:
    got = set()
    for line in pad.splitlines():
        if line and not line.startswith("#"):
            parts = line.split()
            if len(parts) >= 2 and not parts[1].startswith("@") and "a" in parts[1].split("+"):
                got.add(int(parts[0]))
    return got


def check_p10b(log: str, pad: str) -> list[str]:
    """P10b's live rules, over the battle scenario run with SOA_COOP=1 (Aika,
    party slot 1, is pad 2's), a SOA_PAD2 script of two rights and an A on
    her first turn, and SOA_PAD_RECORD:
    - on pad 2's turns the game reads only presses forwarded from pad 2,
      never port 1's A-every-150;
    - her first command is Focus, which two rights reach and port 1's
      script never would;
    - at least one direction was forwarded;
    - outside pad 2's turns the game reads only presses of port 1's, each
      where the recording has it -- so a handover back to port 1 passes
      nothing it was already holding;
    - the recording still holds port 1's A presses during pad 2's turns: it
      is taken before the filter."""
    si, turns, forwarded, commands = [], [], {}, []
    start = None
    for line in log.splitlines():
        m = RE_SI.match(line)
        if m:
            si.append((int(m.group(1)), int(m.group(2), 16)))
            continue
        m = RE_COOP.match(line)
        if not m:
            continue
        f, what = int(m.group(1)), m.group(2)
        if what.startswith("handover: slot") and start is None:
            start = f
        elif what == "handover: back to port 1" and start is not None:
            turns.append((start, f))
            start = None
        elif what.startswith("pad 2 press "):
            forwarded[f] = int(what.split()[3], 16)
        elif what.startswith("commands:"):
            commands.append((f, dict(kv.split("=") for kv in what.split()[1:])))
    if start is not None:
        turns.append((start, 1 << 30))

    def theirs(f: int) -> bool:
        return any(a <= f < b for a, b in turns)

    port1 = recorded_presses(pad)
    problems = []
    if not turns:
        return ["no handover to pad 2: pad 2 never had a turn"]
    for f, b in si:
        if not b:
            continue
        if theirs(f) and f not in forwarded:
            problems.append(
                f"frame {f}: the game read {b:04X} on pad 2's turn, not a press forwarded from pad 2"
            )
        elif not theirs(f) and f not in port1:
            problems.append(
                f"frame {f}: the game read {b:04X} outside pad 2's turns, not a press of port 1's"
            )
    first = next((c for f, c in commands if f >= turns[0][0]), None)
    if first is None or int(first.get("1", "-1")) != FOCUS:
        problems.append(f"Aika's first command was {first and first.get('1')}, not {FOCUS} (Focus)")
    if not any(b & DIRECTIONS and theirs(f) for f, b in forwarded.items()):
        problems.append("no direction forwarded from pad 2 on its turns")
    if not any(theirs(f) for f in recorded_a(pad)):
        problems.append(
            "the recording holds no A of port 1's during pad 2's turns: is it taken after the filter?"
        )
    return problems


def p10b_log(
    forward_right=True, leak_port1=False, focus=True, leak_back=False, keep_a=True
) -> tuple[str, str]:
    """A synthetic run: Vyse's A at 100 and 110, Aika's turn 200-300 with pad
    2's right at 220 and A at 250, Vyse again from 300."""
    log = [
        "[si] frame 100 (retrace 1): buttons 0100",
        "[si] frame 110 (retrace 1): buttons 0000",
        "[mod] coop: frame 200 handover: slot 1 to pad 2",
    ]
    if forward_right:
        log += [
            "[mod] coop: frame 220 pad 2 press 0002 forwarded",
            "[si] frame 220 (retrace 1): buttons 0002",
        ]
        log += ["[si] frame 230 (retrace 1): buttons 0000"]
    if leak_port1:
        log += ["[si] frame 240 (retrace 1): buttons 0100"]
    log += [
        "[mod] coop: frame 250 pad 2 press 0100 forwarded",
        "[si] frame 250 (retrace 1): buttons 0100",
    ]
    log += ["[si] frame 260 (retrace 1): buttons 0000"]
    log += [f"[mod] coop: frame 300 commands: 0=3 1={FOCUS if focus else 3} 2=-1 3=-1"]
    log += ["[mod] coop: frame 300 handover: back to port 1"]
    if leak_back:
        log += ["[si] frame 300 (retrace 1): buttons 0100"]
    log += ["[si] frame 400 (retrace 1): buttons 0100", "[si] frame 410 (retrace 1): buttons 0000"]
    pad = ["# soa pad recording v2", "100 a #r1", "110 - #r1"]
    if keep_a:
        pad += ["240 a #r1", "250 - #r1"]
    pad += ["400 a #r1", "410 - #r1"]
    return "\n".join(log), "\n".join(pad)


def test_the_p10b_check_fails_each_rule_broken():
    """The live check's own test: a synthetic run that passes, and each rule
    broken in turn; with no handover at all (SOA_COOP unset, the Done's
    mutation) it fails outright."""
    assert check_p10b(*p10b_log()) == []
    assert "not a press forwarded from pad 2" in check_p10b(*p10b_log(leak_port1=True))[0]
    assert "no direction forwarded" in check_p10b(*p10b_log(forward_right=False))[0]
    assert "not 0 (Focus)" in check_p10b(*p10b_log(focus=False))[0]
    assert "not a press of port 1's" in check_p10b(*p10b_log(leak_back=True))[0]
    assert "no A of port 1's" in check_p10b(*p10b_log(keep_a=False))[0]
    log, pad = p10b_log()
    no_coop = "\n".join(ln for ln in log.splitlines() if "[mod] coop" not in ln)
    assert check_p10b(no_coop, pad) == ["no handover to pad 2: pad 2 never had a turn"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["p11b"] and len(sys.argv) == 3:
        found = check_p11b(Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace"))
        for p in found:
            print(f"[p11b-check] {p}")
        print(f"[p11b-check] {'FAIL' if found else 'ok'}")
        sys.exit(1 if found else 0)
    if sys.argv[1:2] == ["p10b"] and len(sys.argv) == 4:
        found = check_p10b(
            Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace"),
            Path(sys.argv[3]).read_text(encoding="utf-8", errors="replace"),
        )
        for p in found:
            print(f"[p10b-check] {p}")
        print(f"[p10b-check] {'FAIL' if found else 'ok'}")
        sys.exit(1 if found else 0)
    sys.exit("usage: python tools/tests/test_mods.py p11b <log> | p10b <log> <pad recording>")


@needs_cc
def test_read_pad_gives_port_2_and_nothing_else(driver, tmp_path):
    """read_pad (P10a) is si.c's port 2 through the setter main.c calls: here
    the driver's stub. Ports 1 and 3 answer 0; with nothing on port 2, 2 does."""
    dll(tmp_path, "padmod", "READPAD")
    _, err = play(driver, tmp_path, "frame pad2 1100 frame")
    got = [ln.split(": ", 1)[1] for ln in err.splitlines() if "padmod: read_pad" in ln]
    assert got == ["read_pad 1:0 3:0 2:0 0000", "read_pad 1:0 3:0 2:1 1100"], err


@needs_cc
def test_a_mod_built_before_read_pad_still_loads(driver, tmp_path):
    """map-log built against soa_mod.h without the read_pad append loads."""

    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (P10a).")
    end = header.index("int (*read_pad)(uint32_t port, SoaPad* out);", start) + len(
        "int (*read_pad)(uint32_t port, SoaPad* out);\n"
    )
    old = header[:start] + header[end:]
    assert "(*read_pad)" not in old and "(*host_buttons)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    d = tmp_path / "mods" / "map-log"
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "map-log" / "mod.c", include=inc)
    out, err = play(driver, tmp_path / "mods", "set 803475cc 6 set 80311aec 3 safe")
    assert "loaded 1" in out and "[mod] map-log: map-log loaded" in err, (out, err)


COOP = ROOT / "mods" / "coop"


def turn(phase: int, member: int) -> str:
    """A battle (scene 7) at `phase`, party slot `member` choosing."""
    return f"set 803475cc 7 set 8034733c {phase:x} set 80347330 {member:x} "


def buttons_read(out: str) -> dict[int, int]:
    """The buttons the game read, by frame."""
    got = {}
    for line in out.splitlines():
        parts = line.split()
        if parts[:1] == ["pad"]:
            got[int(parts[1])] = int(parts[2], 16)
    return got


@needs_cc
def test_coop_follows_the_member_and_phase_words(driver, tmp_path):
    """SOA_COOP=1: on slot 0's turn port 1's own A reaches the game; from
    slot 1's turn the game reads pad 2 -- neutral while pad 2 still holds
    its left, then pad 2's A and never port 1's; at phase 2 port 1 again,
    once its B is let go. The handovers, the press forwarded and the
    commands at the phase edge are logged."""
    shipped(tmp_path, folder=COOP)
    script = (
        turn(1, 0)
        + "pad2 0 "
        + reads(1, 2, 0x0100)
        + turn(1, 1)
        + "pad2 1 "
        + reads(3, 4, 0x0100)
        + "pad2 0 "
        + reads(5, 5, 0x0100)
        + "pad2 100 "
        + reads(6, 6)
        + "set 80309174 3 set 80309194 4 set 803091b4 ffffffff set 803091d4 ffffffff "
        + turn(2, 1)
        + reads(7, 7, 0x0200)
        + reads(8, 8)
        + reads(9, 9, 0x0100)
        + turn(0, 1)  # an edge into phase 2 that is not from phase 1: no commands line
        + reads(10, 10)
        + turn(2, 1)
        + reads(11, 11)
    )
    out, err = play(driver, tmp_path, script, SOA_COOP="1")
    got = buttons_read(out)
    assert [got[f] for f in range(1, 10)] == [0x100, 0x100, 0, 0, 0, 0x100, 0, 0, 0x100], got
    assert "[mod] coop: frame 3 handover: slot 1 to pad 2" in err, err
    assert "[mod] coop: frame 6 pad 2 press 0100 forwarded" in err, err
    assert "[mod] coop: frame 7 commands: 0=3 1=4 2=-1 3=-1" in err, err
    assert "[mod] coop: frame 7 handover: back to port 1" in err, err
    assert "not in recordings" not in err, err  # pad 2 is, since the event track's E2
    assert err.count(" commands: ") == 1, err  # the 1 -> 2 edge, and only that
    assert err.count(" forwarded") == 1, err


@needs_cc
def test_coop_handover_holds_neutral_while_the_incoming_pad_holds_a(driver, tmp_path):
    """The turn passes to pad 2 with its A down, a thumb resting on it: the
    game reads neutral until a read with every button up, and only the next
    A goes through. Without the handover rule (the mutation) the held A
    confirms the member's command at once."""
    script = (
        turn(1, 0)
        + "pad2 100 "
        + reads(1, 5)
        + turn(1, 1)
        + reads(6, 15)
        + "pad2 0 "
        + reads(16, 16)
        + "pad2 100 "
        + reads(17, 18)
    )
    shipped(tmp_path / "a", folder=COOP)
    out, err = play(driver, tmp_path / "a", script, SOA_COOP="1")
    assert pressed(out) == [17, 18], pressed(out)
    assert err.count(" forwarded") == 1, err  # an A held over 17-18 is one press
    src = (COOP / "mod.c").read_text(encoding="utf-8")
    rule = "        g_hold = 1;\n"
    assert src.count(rule) == 1
    shipped(tmp_path / "b", src.replace(rule, "        g_hold = 0;\n"), folder=COOP)
    out, _ = play(driver, tmp_path / "b", script, SOA_COOP="1")
    assert pressed(out)[:1] == [6], pressed(out)


@needs_cc
def test_coop_without_pad_2_port_1_plays_everyone(driver, tmp_path):
    shipped(tmp_path, folder=COOP)
    out, err = play(driver, tmp_path, turn(1, 1) + reads(1, 3, 0x0100), SOA_COOP="1")
    assert pressed(out) == [1, 2, 3], out
    assert err.count("pad 2 is not connected: port 1 plays every member") == 1, err


@needs_cc
@pytest.mark.parametrize(
    "value, told",
    [
        ("", "off (SOA_COOP unset)"),
        ("4", "SOA_COOP=4 is not party slots 0 to 3"),
        ("1,1", "SOA_COOP=1,1 is not party slots"),
        ("1;3", "SOA_COOP=1;3 is not party slots"),
    ],
    ids=["unset", "slot-4", "twice", "separator"],
)
def test_coop_off_or_refused_never_filters(driver, tmp_path, value, told):
    shipped(tmp_path, folder=COOP)
    out, err = play(driver, tmp_path, turn(1, 1) + "pad2 100 " + reads(1, 2), SOA_COOP=value)
    assert pressed(out) == [] and "unfiltered" in out, out
    assert told in err, err


@needs_cc
def test_coop_forwards_all_of_pad_2_and_holds_it_all_neutral(driver, tmp_path):
    """Sticks and triggers too: during a handover's hold the game reads all of
    the pad neutral, so port 1's stick cannot turn the next member's wheel;
    on pad 2's turn it reads all of pad 2 and none of port 1. Mutations: a
    neutral() that clears only the buttons, and forwarding only pad 2's
    buttons, each fail."""
    script = turn(1, 1) + "pad2 100 analog2 1e c8 2a 3b 4c 5d padall 1 0 pad2 0 padall 2 0 "
    want = ["padall 1 00 00 80 80 80 80 00 00", "padall 2 00 00 1E C8 2A 3B 4C 5D"]

    def reads_of(folder: Path) -> list[str]:
        out, _ = play(driver, folder, script, SOA_COOP="1")
        return [ln for ln in out.splitlines() if ln.startswith("padall ")]

    shipped(tmp_path / "a", folder=COOP)
    assert reads_of(tmp_path / "a") == want
    src = (COOP / "mod.c").read_text(encoding="utf-8")
    sticks = (
        "    pad->stick[0] = pad->stick[1] = 128;\n"
        "    pad->cstick[0] = pad->cstick[1] = 128;\n"
        "    pad->trig[0] = pad->trig[1] = 0;\n"
    )
    forward = "        *pad = two;\n"
    assert src.count(sticks) == 1 and src.count(forward) == 1
    shipped(tmp_path / "b", src.replace(sticks, ""), folder=COOP)
    assert reads_of(tmp_path / "b")[0] != want[0]
    shipped(
        tmp_path / "c", src.replace(forward, "        pad->buttons = two.buttons;\n"), folder=COOP
    )
    assert reads_of(tmp_path / "c")[1] != want[1]


@needs_cc
def test_coop_only_in_a_battle(driver, tmp_path):
    """Outside scene 7 the phase and member words are leftovers: reading as
    slot 1's party input in the field (scene 6), port 1 keeps its own pad.
    Without the scene gate (the mutation) pad 2 takes port 1 there."""
    script = "set 803475cc 6 set 8034733c 1 set 80347330 1 pad2 0 " + reads(1, 3, 0x0100)
    shipped(tmp_path / "a", folder=COOP)
    out, err = play(driver, tmp_path / "a", script, SOA_COOP="1")
    assert pressed(out) == [1, 2, 3] and "handover" not in err, (out, err)
    src = (COOP / "mod.c").read_text(encoding="utf-8")
    gate = "int battle = g_api->scene() == SCENE_BATTLE,"
    assert src.count(gate) == 1
    shipped(tmp_path / "b", src.replace(gate, "int battle = 1,"), folder=COOP)
    out, _ = play(driver, tmp_path / "b", script, SOA_COOP="1")
    assert pressed(out) != [1, 2, 3], out


# --------------------------------------------------------------------------
# M16: options each mod declares (docs/specs/mod-options.md). mod.ini
# declares them, SOA_MOD_OPT (and soa.ini, through settings.c) sets them,
# patches.txt reads ${NAME} and a DLL the API's option calls.
# --------------------------------------------------------------------------

OPTIONS = (
    "rate int -5..127 32",
    "scenes bool 1",
    "factor enum 0|0.5|1 0.5",
    "tag string field",
    "seed seed 7",
)


def ini2(mod_id: str, *options: str) -> str:
    """A manifest 2 mod.ini for the fake DOL, declaring `options`."""
    head = (
        f"manifest = 2\nid = {mod_id}\nversion = 1.0\nname = {mod_id}\napi = 1\ndol_sha1 = {SHA}\n"
    )
    return head + "".join(f"option = {o}\n" for o in options)


OPTION_SOURCE = r"""
#include "soa_mod.h"
#include <stdio.h>

static const SoaModApi* A;
static const char* const k_names[] = {"rate", "scenes", "factor", "tag", "seed", "nope"};

static void each(const char* when)
{
    char b[160];
    unsigned i;
    for (i = 0; i < sizeof k_names / sizeof k_names[0]; i++) {
        int64_t v = -999;
        const char* t = A->option(k_names[i]);
        int got = A->option_int(k_names[i], &v);
        snprintf(b, sizeof b, "%s %s [%s] %d %lld", when, k_names[i], t ? t : "(null)", got, (long long)v);
        A->log(b);
    }
}

static void sp(void* u)
{
    static int once;
    (void)u;
    if (!once++) each("safe");
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    if (api->size < SOA_MOD_HAS(option_int)) return 1;
    A = api;
    each("init");
    api->on_safe_point(sp, NULL);
    return 0;
}
"""


def option_dll(root: Path, mod_id: str = "opts") -> Path:
    d = mod(root, mod_id, patches=None, ini=ini2(mod_id, *OPTIONS))
    (d / "mod_src.c").write_text(OPTION_SOURCE, encoding="utf-8")
    library(d, d / "mod_src.c")
    return d


def option_reads(err: str, when: str) -> dict[str, str]:
    """What the DLL logged for each name at `when`: `[text] got value`."""
    pre = f"[mod] opts: {when} "
    rows = [line[len(pre) :].split(" ", 1) for line in err.splitlines() if line.startswith(pre)]
    return {name: rest for name, rest in rows}


@needs_cc
def test_m16_every_type_reads_back_through_the_api(driver, tmp_path):
    """Unset, each option is its default; set through SOA_MOD_OPT, its value,
    in one spelling (a seed of 0x3039 reads 12345), from init and from a
    callback alike. An enum or a string is text only; an undeclared name is
    NULL and 0. The mutation, api_option answering the default whatever
    was set, fails the second half."""
    option_dll(tmp_path)
    out, err = play(driver, tmp_path, "safe")
    assert "loaded 1" in out, err
    defaults = {
        "rate": "[32] 1 32",
        "scenes": "[1] 1 1",
        "factor": "[0.5] 0 -999",
        "tag": "[field] 0 -999",
        "seed": "[7] 1 7",
        "nope": "[(null)] 0 -999",
    }
    assert option_reads(err, "init") == defaults, err
    assert option_reads(err, "safe") == defaults, err
    assert "from SOA_MOD_OPT" not in err, err
    opt = "opts.rate=-5 opts.scenes=0 opts.factor=1 opts.tag=a.b+c opts.seed=0x3039"
    out, err = play(driver, tmp_path, "safe", SOA_MOD_OPT=opt)
    assert "loaded 1" in out, err
    values = {
        "rate": "[-5] 1 -5",
        "scenes": "[0] 1 0",
        "factor": "[1] 0 -999",
        "tag": "[a.b+c] 0 -999",
        "seed": "[12345] 1 12345",
        "nope": "[(null)] 0 -999",
    }
    assert option_reads(err, "init") == values, err
    assert option_reads(err, "safe") == values, err
    assert "[mod] opts: option seed = 12345, from SOA_MOD_OPT (its default 7)" in err, err


@needs_cc
@pytest.mark.parametrize(
    "option, why",
    [
        ("rate", "an option is `option = NAME TYPE [DOMAIN] DEFAULT`"),
        ("Rate bool 1", "a name is a lowercase letter"),
        ("_rate bool 1", "a name is a lowercase letter"),
        ("ra-te bool 1", "a name is a lowercase letter"),
        ("a" * 32 + " bool 1", "under 32"),
        ("rate float 1", "`float` is not an option's type"),
        ("rate int 32", "an int or enum is NAME TYPE DOMAIN DEFAULT"),
        ("rate bool 0..1 1", "a bool, string or seed is NAME TYPE DEFAULT"),
        ("rate int 5..1 3", "`5..1` is not a range"),
        ("rate int 0..3000000000 3", "is not a range"),
        ("rate int 00..5 3", "is not a range"),
        ("rate int 0..127 128", "its default, 128, is not a whole number from 0 to 127"),
        ("rate int 0..127 -0", "its default, -0, is not"),
        ("rate bool 2", "its default, 2, is not 0 or 1"),
        ("rate enum a|b c", "its default, c, is not one of a|b"),
        ("rate enum a|b|a a", "is not a list of choices"),
        ("rate enum a||b a", "is not a list of choices"),
        ("rate enum a|b$ a", "is not a list of choices"),
        ("rate enum " + "|".join(f"c{i}" for i in range(17)) + " c0", "is not a list of choices"),
        ("rate string a,b", "its default, a,b, is not 1 to 63"),
        ("rate seed 0x123456789", "its default, 0x123456789, is not a 32-bit number"),
    ],
)
def test_m16_a_bad_declaration_refuses_the_mod_with_its_line(driver, tmp_path, option, why):
    """Each fault of section 1, on mod.ini's line 7. The mutation, the
    default's domain check dropped, fails the `its default` cases."""
    mod(tmp_path, "bad", ini=ini2("bad", option))
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out, err
    assert "bad/mod.ini:7: " in err and why in err, err


@needs_cc
def test_m16_declaring_the_same_name_twice_or_seventeen_is_refused(driver, tmp_path):
    mod(tmp_path / "a", "twice", ini=ini2("twice", "rate bool 1", "rate bool 0"))
    out, err = play(driver, tmp_path / "a")
    assert "loaded 0" in out and "twice/mod.ini:8: option `rate` is declared twice" in err, err
    many = [f"o{i} bool 1" for i in range(17)]
    mod(tmp_path / "b", "many", ini=ini2("many", *many))
    out, err = play(driver, tmp_path / "b")
    assert "loaded 0" in out, err
    assert "many/mod.ini:23: more than 16 options; option `o16`" in err, err
    mod(tmp_path / "c", "sixteen", ini=ini2("sixteen", *many[:16]))
    out, err = play(driver, tmp_path / "c")
    assert "loaded 1" in out, err


@needs_cc
def test_m16_an_option_is_a_manifest_2_key(driver, tmp_path):
    ini = f"name = old\napi = 1\ndol_sha1 = {SHA}\noption = rate bool 1\n"
    mod(tmp_path, "old", ini=ini)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "`option` is a manifest 2 key" in err, err


@needs_cc
@pytest.mark.parametrize(
    "entry, why",
    [
        ("opts.rate=128", "`opts.rate=128`: the value is not a whole number from 0 to 127"),
        ("opts.rate=12a", "the value is not a whole number"),
        ("opts.rate=", "the value is not a whole number"),
        ("opts.factor=2", "`opts.factor=2`: the value is not one of 0|0.5|1"),
        ("opts.factor=0.50", "the value is not one of 0|0.5|1"),
        ("opts.scenes=yes", "the value is not 0 or 1"),
        ("opts.tag=a;b", "the value is not 1 to 63"),
        ("opts.seed=-1", "the value is not a 32-bit number"),
        ("opts.speed=1", "`opts.speed=1`: the mod declares no option `speed`"),
        ("opts.rate=1 opts.rate=2", "`opts.rate=2`: option `rate` is given twice"),
    ],
)
def test_m16_a_bad_value_refuses_the_mod_naming_the_entry(driver, tmp_path, entry, why):
    """A mod run with defaults when a value was asked for would be doing
    something else. The mutation, the values' domain check skipped, loads
    the out-of-range cases."""
    options = ("rate int 0..127 32", *OPTIONS[1:])
    mod(tmp_path, "opts", ini=ini2("opts", *options))
    out, err = play(driver, tmp_path, SOA_MOD_OPT=entry)
    assert "loaded 0" in out, err
    line = next((ln for ln in err.splitlines() if "the mod is not loaded" in ln), "")
    assert line.startswith("[mod] SOA_MOD_OPT: `") and why in line, err


@needs_cc
def test_m16_an_entry_for_no_mod_is_said_and_the_rest_load(driver, tmp_path):
    """An entry naming an id no mod has does nothing and says so; one that
    is not ID.NAME=VALUE is passed over with a line; another mod's entry
    leaves this one alone. An id may hold '.', so the name is after the last."""
    mod(tmp_path, "a.b", ini=ini2("a.b", "rate int 0..9 1"), patches=RATES.format(k="1"))
    opt = "ghost.rate=3 junk a.b.rate=4 =x"
    out, err = play(driver, tmp_path, "describe", SOA_MOD_OPT=opt)
    assert "loaded 1" in out, err
    assert (
        "SOA_MOD_OPT: `ghost.rate=3`: no mod with id `ghost` is loaded; it does nothing" in err
    ), err
    assert "SOA_MOD_OPT: `junk` is not ID.NAME=VALUE; passed over" in err, err
    assert "SOA_MOD_OPT: `=x` is not ID.NAME=VALUE" in err, err
    assert "option rate = 4, from SOA_MOD_OPT" in err, err
    assert re.search(r"describe \[mods=a\.b@1\.0:[0-9a-f]{8}\[rate=4\]\]", out), out


def encounter_scale(root: Path) -> Path:
    """The shipped examples/mods/encounter-scale, made for the fake DOL."""
    src = ROOT / "examples" / "mods" / "encounter-scale"
    ini = (src / "mod.ini").read_text(encoding="utf-8")
    pinned = ini.split("dol_sha1 = ")[1].split()[0]
    d = root / "encounter-scale"
    d.mkdir(parents=True)
    (d / "mod.ini").write_text(ini.replace(pinned, SHA), encoding="utf-8")
    (d / "patches.txt").write_text(
        (src / "patches.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return d


@needs_cc
def test_m16_the_example_s_factor_is_its_option(driver, tmp_path):
    """encounter-scale's `*= ${factor}`: halved by default, zeroed at 0,
    left at 1, doubled at 2. The mutation, ${NAME} replaced by the default,
    fails every value set."""
    encounter_scale(tmp_path)
    script = table([40] * 8) + load(116) + gets()
    got = {}
    for value in (None, "0", "1", "2"):
        env = {"SOA_MOD_OPT": f"encounter-scale.factor={value}"} if value else {}
        out, err = play(driver, tmp_path, script, **env)
        assert "loaded 1" in out, err
        got[value] = read_rates(out)[0]
    assert got == {None: [20] * 8, "0": [0] * 8, "1": [40] * 8, "2": [80] * 8}, got


@needs_cc
@pytest.mark.parametrize(
    "line, why",
    [
        ("on_map_load u16 [0x803474bc]+2+z*132 *= ${speed} for z=0..7", "`${speed}` names no"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= $factor for z=0..7", "a `$` begins ${NAME}"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= ${factor for z=0..7", "a `$` begins ${NAME}"),
        ("on_map_load u16 [0x803474bc]+2+z*132 *= ${} for z=0..7", "a `$` begins ${NAME}"),
        ("every_frame u8 0x80346d28 = ${tag}", "`field` is not a value a u8 holds"),
        ("every_frame 0x80346d28 = 0" + " " * 450 + "${long}", "longer than 511 characters once"),
    ],
)
def test_m16_a_bad_substitution_refuses_the_mod_at_its_line(driver, tmp_path, line, why):
    ini = ini2("subs", "factor enum 0|0.5 0.5", "tag string field", "long string " + "x" * 63)
    mod(tmp_path, "subs", ini=ini, patches=line + "\n")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out, err
    assert "subs/patches.txt:1: " in err and why in err, err


@needs_cc
def test_m16_a_comment_s_dollar_is_left_alone(driver, tmp_path):
    patches = "# costs $5, see ${nothing}\nevery_frame 0x80346d28 = ${v} when scene=6 # ${nope}\n"
    mod(tmp_path, "c", ini=ini2("c", "v int 0..9 3"), patches=patches)
    out, err = play(driver, tmp_path, "set 803475cc 6 frame get 80346d28")
    assert "loaded 1" in out and "80346D28=00000003" in out, (out, err)


@needs_cc
def test_m16_the_recording_names_the_values_that_are_not_defaults(driver, tmp_path):
    """At its defaults a mod reads as it always did, so old recordings still
    match; away from them, its values follow its hash, and a value equal to
    the default is no change. The mutation, the values left out, fails the
    third run."""
    encounter_scale(tmp_path)
    plain, _ = play(driver, tmp_path, "describe")
    assert re.search(r"describe \[mods=encounter-scale@1\.0:[0-9a-f]{8}\]$", plain, re.M), plain
    same, _ = play(driver, tmp_path, "describe", SOA_MOD_OPT="encounter-scale.factor=0.5")
    assert same == plain
    zero, _ = play(driver, tmp_path, "describe", SOA_MOD_OPT="encounter-scale.factor=0")
    assert "[factor=0]]" in zero and zero.replace("[factor=0]]", "]") == plain, (plain, zero)


@needs_cc
def test_m16_the_example_dll_s_option_leaves_scene_changes_out(driver, tmp_path):
    """examples/mods/map-log declares `scenes`; at 0 it logs no scene change."""
    d = tmp_path / "map-log"
    d.mkdir()
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "map-log" / "mod.c")
    script = "set 803475cc 6 safe set 803475cc 7 safe"
    _, on = play(driver, tmp_path, script)
    _, off = play(driver, tmp_path, script, SOA_MOD_OPT="map-log.scenes=0")
    assert "[mod] map-log: scene 6 -> 7" in on, on
    assert "scene 6 -> 7" not in off and "logs map entries, and changes nothing" in off, off


# --------------------------------------------------------------------------
# M17: the order mods load in, mods turned off, and two mods writing the same
# bytes (docs/specs/mod-order.md).
# --------------------------------------------------------------------------


def two(root: Path, a: str, b: str, a_extra: str = "", b_extra: str = "") -> None:
    """Mods `a` and `b` (folders and ids alike), each one patches.txt line."""
    mod(root, "a", ini=ini2("a") + a_extra, patches=a + "\n")
    mod(root, "b", ini=ini2("b") + b_extra, patches=b + "\n")


def order_of(out: str) -> list[str]:
    line = next(x for x in out.splitlines() if x.startswith("describe ["))
    return [e.split("@")[0] for e in line[len("describe [mods=") : -1].split(",") if e]


@needs_cc
def test_m17_the_list_orders_the_mods_and_turns_them_off(driver, tmp_path):
    """Listed first in the list's order, the rest by folder name; -ID is off.
    The mutation, the list ignored, leaves folder order."""
    for i, name in enumerate("abc"):
        mod(tmp_path, name, ini=ini2(name), patches=f"every_frame 0x8034{0x6D28 + 4 * i:04x} = 1\n")
    out, err = play(driver, tmp_path, "describe")
    assert order_of(out) == ["a", "b", "c"], out
    out, err = play(driver, tmp_path, "describe", SOA_MOD_ORDER="c, a")
    assert order_of(out) == ["c", "a", "b"], out
    out, err = play(driver, tmp_path, "describe", SOA_MOD_ORDER="c,-b,zz,c")
    assert order_of(out) == ["c", "a"], out
    assert "/b is turned off by SOA_MOD_ORDER; not loaded" in err, err
    assert "SOA_MOD_ORDER: `zz` names no mod in" in err, err
    assert "SOA_MOD_ORDER: `c` is named twice; its second place is passed over" in err, err


@needs_cc
def test_m17_a_version_1_mod_is_listed_by_its_folder(driver, tmp_path):
    mod(tmp_path, "old-one", patches="every_frame 0x80346d28 = 1\n")
    mod(tmp_path, "new", ini=ini2("new"), patches="every_frame 0x80346d2c = 1\n")
    out, _ = play(driver, tmp_path, "describe", SOA_MOD_ORDER="old-one")
    assert order_of(out) == ["old-one:" + order_of(out)[0].split(":")[1], "new"], out


@needs_cc
@pytest.mark.parametrize(
    "a, b, at",
    [
        (
            "every_frame 0x80346d28 = 0 when scene=6",
            "every_frame 0x80346d28 = 1 when scene=6",
            "80346D28",
        ),
        ("once 0x80346d28 = 0", "every_frame 0x80346d28 = 1 when map=116a", "80346D28"),
        ("every_frame 0x80346d28 = 5", "every_frame u8 0x80346d2b = 1", "80346D2B"),
        ("every_frame 0x80346d30 = 5", "every_frame u16 0x80346d28+z*4 = 1 for z=0..3", "80346D30"),
        (
            "on_map_load u16 [0x803474bc]+2+z*132 *= 0.5 for z=0..7",
            "on_map_load u16 [0x803474bc]+134 = 9",
            "[803474BC]+134",
        ),
    ],
)
def test_m17_two_mods_on_the_same_bytes_refuse_the_later(driver, tmp_path, a, b, at):
    """Both places named. The mutation, the byte test always false, loads
    every pair."""
    two(tmp_path, a, b)
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert (
        f"b/patches.txt:1: it writes {at}, as a/patches.txt:1 does, and both can apply on one frame"
        in err
    ), err


@needs_cc
@pytest.mark.parametrize(
    "a, b",
    [
        ("every_frame 0x80346d28 = 0 when scene=6", "every_frame 0x80346d28 = 1 when scene=7"),
        ("every_frame 0x80346d28 = 0 when state=3", "every_frame 0x80346d28 = 1 when state=8"),
        ("every_frame 0x80346d28 = 0 when map=116a", "every_frame 0x80346d28 = 1 when map=117a"),
        ("every_frame u16 0x80346d28 = 1", "every_frame u16 0x80346d2a = 1"),
        ("every_frame 0x80400000 = 1", "on_map_load u16 [0x803474bc]+2 = 1"),
        ("on_map_load u16 [0x803474bc]+2 = 1", "on_map_load u16 [0x80347400]+2 = 1"),
        ("every_frame 0x80346d28 = 0 when scene=6", "once 0x80346d28 = 0"),
    ],
)
def test_m17_what_cannot_meet_loads_both(driver, tmp_path, a, b):
    """Conditions that cannot both hold, bytes side by side, what cannot be
    compared before the game runs, and the same value at the same place. The
    mutation, the condition test always true, refuses the first three."""
    two(tmp_path, a, b)
    out, err = play(driver, tmp_path)
    assert "loaded 2" in out, err


@needs_cc
def test_m17_one_mod_s_own_patches_may_meet(driver, tmp_path):
    mod(tmp_path, "a", ini=ini2("a"), patches="every_frame 0x80346d28 = 1\nonce 0x80346d28 = 2\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err


@needs_cc
def test_m17_overrides_lets_it_through_and_loads_it_last(driver, tmp_path):
    """b overrides a: listed first, it loads second, its value is the one a
    frame leaves, and the pair is said. The mutation, the reordering
    skipped, leaves a's value."""
    line_a, line_b = "every_frame 0x80346d28 = 1", "every_frame 0x80346d28 = 2"
    two(tmp_path, line_a, line_b, b_extra="overrides = a\n")
    out, err = play(driver, tmp_path, "describe frame get 80346d28", SOA_MOD_ORDER="b,a")
    assert "loaded 2" in out, err
    assert order_of(out) == ["a", "b"] and "80346D28=00000002" in out, out
    assert "/b loads after a, which it overrides" in err, err
    assert "[mod] b/patches.txt:1 overrides a/patches.txt:1 at 80346D28" in err, err


@needs_cc
def test_m17_mods_that_override_each_other_are_both_refused(driver, tmp_path):
    two(
        tmp_path,
        "every_frame 0x80346d28 = 1",
        "every_frame 0x80346d28 = 2",
        a_extra="overrides = b\n",
        b_extra="overrides = x, a\n",
    )
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out, err
    assert "each name the other in `overrides`, so which wins cannot be known" in err, err


@needs_cc
@pytest.mark.parametrize(
    "line, why",
    [
        ("overrides = A", "overrides: `A` is not an id"),
        ("overrides =", "`overrides` names the ids"),
    ],
)
def test_m17_a_bad_overrides_refuses_the_mod(driver, tmp_path, line, why):
    mod(tmp_path, "a", ini=ini2("a") + line + "\n")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "a/mod.ini:7: " + why in err, err


@needs_cc
def test_m17_overrides_is_a_manifest_2_key(driver, tmp_path):
    mod(tmp_path, "old", ini=f"name = old\napi = 1\ndol_sha1 = {SHA}\noverrides = a\n")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "`overrides` is a manifest 2 key" in err, err


@needs_cc
def test_m17_each_mod_s_writes_and_callbacks_are_listed(driver, tmp_path):
    mod(tmp_path / "p", "zero", ini=ini2("zero"), patches=PATCH + RATES.format(k="0.5"))
    _, err = play(driver, tmp_path / "p")
    assert (
        "[mod] zero writes, patches.txt:1: every_frame u32 80346D28 = 00000000 when scene=6" in err
    ), err
    assert (
        "[mod] zero writes, patches.txt:2: on_map_load u16 [803474BC]+2+z*132 *= 0.5 for z=0..7"
        in err
    ), err
    dll(tmp_path / "d", "native")
    _, err = play(driver, tmp_path / "d")
    assert "[mod] native registers: frame end, safe point, map load, scene change" in err, err


# P1b's test mode (comfort-pack 3.4): trials the check reads.
TRIAL_FIELD = "set 803475cc 6 set 80311aec 8 set 803474bc 80400000 set 8034740c 3 set 80400108 14 "
# Controller reads in a battle's phase 1 from frame 100, and the buttons the
# test mode gives each: 60 frames of nothing, then up (4 frames) at 160, 230
# and 300, and A (10 frames) at 370, each beat 70 frames.
WHEEL = (100, 159, 160, 163, 164, 230, 300, 303, 304, 370, 379, 380, 440)
WHEEL_WANT = (0, 0, 8, 8, 0, 8, 8, 8, 0, 0x100, 0x100, 0, 8)


def trials(err: str) -> list[str]:
    return [
        ln.split("encounter-rate: ", 1)[1]
        for ln in err.splitlines()
        if "encounter-rate: trial " in ln
    ]


@needs_cc
def test_encounter_rate_test_mode_runs_its_trials(driver, tmp_path):
    """Each kind in turn from a counter of 480: a clear at 600 moving frames,
    a battle, a stuck trial at 3000 frames; the multiplier each kind sets; B
    held in a hold trial; and in a battle the escape held at 100 and Run
    pressed: up three times, then A."""
    shipped(tmp_path)
    moved = "set 80346d28 438 frame "  # 480 + 600
    script = (
        TRIAL_FIELD
        + "frame get 80346d28 "  # trial 0 (0.5) starts: the counter at 480
        + "frame " + BYTE + moved  # half's byte, then 600 moving frames
        + "frame set 80346d28 212 frame set 803475cc 7 frame get 8030b7a8 "  # trial 1 (1): 50, then a battle
        + "set 8034733c 1 " + "".join(f"padall {f} 0 " for f in WHEEL) + "set 8034733c 0 padall 1 0 "
        + "set 803475cc 6 frame " + "frame " * 3000  # trial 2 (2) starts, and sticks
        + "frame " + BYTE + moved  # trial 3 (0): off's byte, a clear
        + "setb 8030b7ad ff frame " + BYTE + "pad 9 0 " + moved  # trial 4 (hold): 0 at once, then B held
    )  # fmt: skip
    out, err = play(driver, tmp_path, script, SOA_ENCOUNTERS_TEST="1")
    assert "test mode: trials of 0.5, 1, 2, 0 and hold" in err, err
    assert "80346D28=000001E0" in out, out
    assert trials(err) == [
        "trial 0 0.5 3 20 3 20 600 clear",
        "trial 1 1 3 20 3 20 50 battle",
        "trial 2 2 3 20 3 20 0 stuck",
        "trial 3 0 3 20 3 20 600 clear",
        "trial 4 hold 3 20 3 20 600 clear",
    ], err
    assert multipliers(out) == [25, 0, 0], out  # half; off; hold from its first frame end
    assert "8030B7A8=00000064" in out, out  # the escape override, 100
    pads = [x.split()[1:] for x in out.splitlines() if x.startswith("padall ")]
    got = [(int(f), int(b1 + b0, 16), sx + sy) for f, b0, b1, sx, sy, *_ in pads]
    assert got[:-1] == [(f, b, "8080") for f, b in zip(WHEEL, WHEEL_WANT, strict=True)], got
    # out of phase 1, still in the battle: A every 30 frames, the sticks centred
    assert got[-1] == (1, 0x100, "8080"), got
    assert "pad 9 0200" in out, out


@needs_cc
def test_encounter_rate_test_mode_presses_on_through_the_results_and_not_the_title(
    driver, tmp_path
):
    """The results screen after a battle is no field and no battle, and
    waits for A: once the field has been seen, A every 30 frames there. On
    the title, before any field, the pad is left as it came. The mutation,
    the field gate dropped, presses A on the title."""
    shipped(tmp_path)
    # the title's attract demo runs as a field on map 299: no trial there,
    # and its presses left alone
    attract = TRIAL_FIELD + "set 80311ac0 12b frame set 803475cc 3 padall 1 0 "
    script = (
        attract
        + TRIAL_FIELD
        + "set 80311ac0 74 frame set 803475cc 9 padall 31 0 padall 35 0"
        + " set 803475cc 6 set 80311aec 5 padall 61 0 set 80311aec 8 padall 91 0"
    )
    out, err = play(driver, tmp_path, script, SOA_ENCOUNTERS_TEST="1")
    pads = [x.split()[1:] for x in out.splitlines() if x.startswith("padall ")]
    got = [(int(f), int(b1 + b0, 16), sx + sy) for f, b0, b1, sx, sy, *_ in pads]
    # the results screen: scene 6 with the field not running, A there too;
    # the running field gets the pad as it came
    assert got == [
        (1, 0, "1122"),
        (31, 0x100, "8080"),
        (35, 0, "8080"),
        (61, 0x100, "8080"),
        (91, 0, "1122"),
    ], got
    assert trials(err) == [], err  # one trial started, on 116, and none ended


@needs_cc
def test_encounter_rate_test_mode_reads_the_world_map_s_zone_where_the_roll_does(driver, tmp_path):
    """On map 99 the zone is the low half of the word at 0x80346CD4, not the
    u16 at 0x8034740E (0x800C1F70); the rate still comes through the table
    pointer, which fn_800C1A50 sets to the region's sub-table. The mutation,
    the field's zone read on map 99, logs zone 3 here."""
    shipped(tmp_path)
    world = TRIAL_FIELD + "set 80311ac0 63 setb 80311ac8 6c set 80346cd4 5 set 80400210 1e "
    out, err = play(
        driver, tmp_path, world + "frame set 80346d28 438 frame", SOA_ENCOUNTERS_TEST="1"
    )
    assert trials(err) == ["trial 0 0.5 5 30 5 30 600 clear"], err


@needs_cc
def test_encounter_rate_without_the_test_mode_runs_no_trial(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, TRIAL_FIELD + "frame frame get 80346d28")
    assert not trials(err) and "80346D28=00000000" in out, (out, err)


# M16b: the shipped mods' settings as declared options, the old switches
# still winning where set.


@needs_cc
def test_m16b_encounter_rate_s_options_set_it_and_its_switch_still_wins(driver, tmp_path):
    """`encounter-rate.rate=half` halves the base 50 to 25 with no
    SOA_ENCOUNTERS; with SOA_ENCOUNTERS=double as well, the switch wins
    (100) and says so. The mutation, the option read and dropped, writes
    nothing at half."""
    shipped(tmp_path)
    script = FIELD + "setb 8030b7ad ff frame " + BYTE
    out, err = play(driver, tmp_path, script, SOA_MOD_OPT="encounter-rate.rate=half")
    assert multipliers(out) == [25], (out, err)
    out, err = play(
        driver, tmp_path, script, SOA_MOD_OPT="encounter-rate.rate=half", SOA_ENCOUNTERS="double"
    )
    assert multipliers(out) == [100], (out, err)
    assert "SOA_ENCOUNTERS=double is set, and wins over the option rate = half" in err, err
    out, err = play(driver, tmp_path, "", SOA_MOD_OPT="encounter-rate.hold_b=0")
    assert "holding B keeps them away off" in err, err


@needs_cc
def test_m16b_autotext_s_option_sets_it_and_its_switch_still_wins(driver, tmp_path):
    shipped(tmp_path, folder=AUTO)
    _, err = play(driver, tmp_path, "", SOA_MOD_OPT="autotext.wait=1")
    assert "a complete page turns itself after 45 frames" in err, err
    _, err = play(driver, tmp_path, "", SOA_MOD_OPT="autotext.wait=90", SOA_AUTOTEXT="30")
    assert (
        "after 30 frames" in err
        and "SOA_AUTOTEXT=30 is set, and wins over the option wait = 90" in err
    ), err
    _, err = play(driver, tmp_path, "")
    assert "off (SOA_AUTOTEXT unset or 0)" in err, err


@needs_cc
def test_m16b_coop_s_option_sets_it_and_its_switch_still_wins(driver, tmp_path):
    shipped(tmp_path, folder=COOP)
    _, err = play(driver, tmp_path, "", SOA_MOD_OPT="coop.slots=1+3")
    assert "pad 2 chooses the commands of party slot(s) 1 3 in battle" in err, err
    _, err = play(driver, tmp_path, "", SOA_MOD_OPT="coop.slots=1+3", SOA_COOP="2")
    assert (
        "party slot(s) 2 in battle" in err and "SOA_COOP=2 is set, and wins over the option" in err
    ), err
    out, err = play(driver, tmp_path, "", SOA_MOD_OPT="coop.slots=1,3")
    assert "loaded 0" in out and "the value is not one of off|0|1|2|3" in err, err


# --------------------------------------------------------------------------
# T1, the virtual disc (disc-layer I6): a mod's files.txt, read before the
# file table is parked (mod_scan_files, which the fake guest calls before
# mod_load as main.c does). The rebuild itself is disc_check.py's.
# --------------------------------------------------------------------------


def files_mod(
    root: Path, name: str = "placer", files: str = "", sources: dict | None = None
) -> Path:
    d = mod(root, name, patches=None, ini=ini2(name))
    (d / "files.txt").write_text(files, encoding="utf-8")
    for rel, data in (sources or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    return d


@needs_cc
def test_i6_a_mod_of_files_txt_alone_loads_and_is_recorded(driver, tmp_path):
    """mod.ini and files.txt, nothing else: it loads, its lines are read, and
    the recording names it. The mutation, load_one's old condition put back,
    refuses it as one that would do nothing."""
    files_mod(
        tmp_path,
        files="replace title/t00.dat build/t00.dat\nalias field/a045a.mld field/a002a.mld\n",
        sources={"build/t00.dat": b"\x01\x02\x03"},
    )
    out, err = play(driver, tmp_path, "describe")
    assert "files 2" in out and "loaded 1" in out, err
    assert "loaded placer (" in err and "and files.txt" in err, err
    assert re.search(r"describe \[mods=placer@1\.0:[0-9a-f]{8}\]", out), out


@needs_cc
def test_i6_a_mod_of_mod_ini_alone_is_still_refused_in_the_new_words(driver, tmp_path):
    mod(tmp_path, "empty", patches=None, ini=ini2("empty"))
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 0" in out, err
    assert (
        "no patches.txt, no mod.dll and no files.txt beside it, so it would do nothing"
        in err.replace("mod.so", "mod.dll")
    ), err


@needs_cc
def test_i6_the_recorded_hash_follows_files_txt_and_every_source(driver, tmp_path):
    """One byte of files.txt, or one of a source, changes the mod's recorded
    hash: what it places on the disc is part of what a recording depends on."""

    def recorded(files: str, source: bytes) -> str:
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        files_mod(root, files=files, sources={"build/x.dat": source})
        out, err = play(driver, root, "describe")
        m = re.search(r"describe \[mods=placer@1\.0:([0-9a-f]{8})\]", out)
        assert m, out + err
        return m.group(1)

    base = recorded("replace title/t00.dat build/x.dat\n", b"abc")
    assert recorded("replace title/t00.dat build/x.dat\n", b"abc") == base
    assert recorded("replace title/t01.dat build/x.dat\n", b"abc") != base
    assert recorded("replace title/t00.dat build/x.dat\n", b"abd") != base


@needs_cc
@pytest.mark.parametrize(
    "files, words",
    [
        ("delta field/x.sct d.delta\n", "`delta` is not built yet (I7)"),
        ("swap battle/x.dat x.dat when map=101b\n", "`swap` is not built yet (I8)"),
        ("move field/x.dat y.dat\n", "`move` is not a verb"),
        ("replace field/x.dat\n", "a line is `replace <path on the disc> <file in this folder>`"),
        ("replace field/x.dat ../outside.dat\n", "is not a file in this folder"),
        ("replace field/x.dat missing.dat\n", "cannot read"),
    ],
)
def test_i6_a_faulty_files_txt_refuses_the_mod_with_its_line(driver, tmp_path, files, words):
    files_mod(tmp_path, files=files)
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 0" in out and "placer/files.txt:1:" in err and words in err, err


# --------------------------------------------------------------------------
# R0: on_damage (docs/specs/battle-harness.md), driven through mod_damage as
# runtime/battle.c drives it from the game's damage call.
# --------------------------------------------------------------------------

ADD_ONE = r"""
#include "soa_mod.h"
static uint32_t f(void* u, uint32_t v, uint32_t b, uint32_t a, uint32_t t, uint32_t e)
{ (void)u; (void)b; (void)a; (void)t; (void)e; return v + 1; }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{ (void)version; return api->on_damage(f, 0) ? 0 : 1; }
"""


def damage_double(root: Path, name: str = "damage-double") -> Path:
    d = root / name
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "damage-double" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "damage-double" / "mod.c")
    return d


@needs_cc
def test_r0_the_example_doubles_each_damage_and_holds_9999(driver, tmp_path):
    damage_double(tmp_path)
    out, err = play(
        driver, tmp_path, "damage 100 90 80309000 80309100 0 damage 6000 0 0 0 0 damage 0 0 0 0 0"
    )
    assert "loaded 1" in out, err
    assert re.findall(r"^damage \d+ -> \d+$", out, re.M) == [
        "damage 100 -> 200",
        "damage 6000 -> 9999",
        "damage 0 -> 0",
    ]


@needs_cc
def test_r0_mods_chain_in_load_order(driver, tmp_path):
    """a-plus-one loads before b-double: each sees what the one before
    returned, so 10 becomes (10 + 1) x 2, not 10 x 2 + 1. With no mod the
    value passes through."""
    d = mod(tmp_path, "a-plus-one", patches=None, ini=ini2("a-plus-one"))
    (d / "mod_src.c").write_text(ADD_ONE, encoding="utf-8")
    library(d, d / "mod_src.c")
    damage_double(tmp_path, "b-double")
    out, err = play(driver, tmp_path, "damage 10 0 0 0 0")
    assert "loaded 2" in out and "damage 10 -> 22" in out, (out, err)
    empty = tmp_path / "none"
    empty.mkdir()
    out, _ = play(driver, empty, "damage 10 0 0 0 0")
    assert "damage 10 -> 10" in out, out


@needs_cc
def test_r0_a_mod_built_before_on_damage_still_loads(driver, tmp_path):
    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (R0,")
    end = header.index("} SoaModApi;", start)
    old = header[:start] + header[end:]
    assert "(*on_damage)" not in old and "(*option_int)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    d = tmp_path / "mods" / "map-log"
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "map-log" / "mod.c", include=inc)
    out, err = play(
        driver, tmp_path / "mods", "set 803475cc 6 set 80311aec 3 safe damage 7 0 0 0 0"
    )
    assert "loaded 1" in out and "damage 7 -> 7" in out, (out, err)


# --------------------------------------------------------------------------
# R1: the battle's other events (docs/specs/battle-events.md), driven through
# mod.c's dispatchers as runtime/battle.c's wrappers drive them.
# --------------------------------------------------------------------------

EVERY_EVENT = r"""
#include "soa_mod.h"
#include <stdio.h>
static const SoaModApi* A;
static uint32_t heal(void* u, uint32_t v, int s, int t) { (void)u; (void)s; (void)t; return v * 2; }
static void spawn(void* u, uint32_t actor, uint32_t record)
{ (void)u; (void)record; A->write32(actor + 20, 77); }
static uint32_t action(void* u, uint32_t type, int slot, uint32_t cmd)
{ (void)u; (void)type; (void)slot; A->write16(cmd + 6, 5); return 4; }
static void order(void* u, int8_t o[12])
{
    int n = 0, i;
    (void)u;
    while (n < 12 && o[n] >= 0) n++;
    for (i = 0; i < n / 2; i++) { int8_t t = o[i]; o[i] = o[n - 1 - i]; o[n - 1 - i] = t; }
}
static int32_t spirit(void* u, int32_t a) { (void)u; return a + 5; }
static int escape(void* u, int s, int slot) { (void)u; (void)s; (void)slot; return 1; }
static void rewards(void* u, SoaRewards* r) { (void)u; r->exp *= 10; r->gold *= 10; r->magic_exp += 200; }
static int effect(void* u, int t, int16_t* e, int32_t* v)
{ (void)u; (void)t; if (*e == 0) *v = 0; return *e == 99; }
static void round_end(void* u, uint32_t r) { char line[32]; (void)u; snprintf(line, sizeof line, "round %u", r); A->log(line); }
static uint32_t ship(void* u, uint32_t v) { (void)u; return v * 2; }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(on_ship_damage)) return 1;
    return api->on_heal(heal, 0) && api->on_enemy_spawn(spawn, 0) && api->on_enemy_action(action, 0) &&
           api->on_turn_order(order, 0) && api->on_spirit_gain(spirit, 0) && api->on_escape(escape, 0) &&
           api->on_rewards(rewards, 0) && api->on_effect(effect, 0) && api->on_round_end(round_end, 0) &&
           api->on_ship_damage(ship, 0) ? 0 : 1;
}
"""


def source_mod(root: Path, name: str, source: str, include: Path = ROOT / "runtime") -> Path:
    d = mod(root, name, patches=None, ini=ini2(name))
    (d / "mod_src.c").write_text(source, encoding="utf-8")
    library(d, d / "mod_src.c", include=include)
    return d


@needs_cc
def test_r1_every_event_reaches_its_mod(driver, tmp_path):
    source_mod(tmp_path, "every", EVERY_EVENT)
    out, err = play(
        driver,
        tmp_path,
        "events heal 30 4 1 heal 6000 4 1 spawn 80309000 80309300 get 80309014 "
        "action 1 5 803091d4 get 803091d8 order 1 0 4 5 -1 -1 -1 -1 -1 -1 -1 -1 "
        "spirit 9 escape 0 2 rewards 120 300 3 effect 0 0 45 effect 0 99 45 effect 0 7 45 "
        "roundend 3 ship 40 report",
    )
    assert "loaded 1" in out, err
    assert "events 0 1 1 1 1 1 1 1 1 1 1" in out, out
    for want in (
        "heal 30 -> 60",
        "heal 6000 -> 9999",  # held, as the damage is
        "80309014=0000004D",  # the actor's HP, written by the mod
        "action 1 -> 4",
        "803091D8=00000005",  # cmd+6 = 5: the low half of the word at +4
        "order 5 4 0 1 -1 -1 -1 -1 -1 -1 -1 -1",
        "spirit 9 -> 14",
        "escape 0 -> 1",
        "rewards 120 300 3 -> 1200 3000 203",  # battle.c clamps magic EXP, not the dispatcher
        "effect 0 45 -> 0 0",
        "effect 99 45 -> 99 45 cancelled",
        "effect 7 45 -> 7 45",
        "round 3 ended",
        "ship 40 -> 80",
    ):
        assert want in out, (want, out)
    assert "[mod] every: round 3" in err, err
    assert (
        "[mod] every registers: on_heal, on_enemy_spawn, on_enemy_action, on_turn_order, on_spirit_gain, "
        "on_escape, on_rewards, on_effect, on_round_end, on_ship_damage\n" in err
    ), err
    assert re.search(
        r"\[mod\] every on_heal: 2 call\(s\), [\d.]+ us in all, max [\d.]+ us, p99 ", err
    ), err
    assert re.search(r"\[mod\] every on_effect: 3 call\(s\)", err), err


SPIRIT_DOUBLE_AND_EFFECT = r"""
#include "soa_mod.h"
static int32_t spirit(void* u, int32_t a) { (void)u; return a * 2; }
static int effect(void* u, int t, int16_t* e, int32_t* v) { (void)u; (void)t; (void)e; *v = 1234; return 0; }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{ (void)version; return api->on_spirit_gain(spirit, 0) && api->on_effect(effect, 0) ? 0 : 1; }
"""


@needs_cc
def test_r1_mods_chain_in_load_order_and_a_cancel_ends_the_chain(driver, tmp_path):
    """a-every adds 5 to the spirit, then b-double doubles it: (10 + 5) x 2.
    a-every cancels effect 99, so b never sets its value to 1234; on effect 7
    a passes it on and b does."""
    source_mod(tmp_path, "a-every", EVERY_EVENT)
    source_mod(tmp_path, "b-double", SPIRIT_DOUBLE_AND_EFFECT)
    out, err = play(driver, tmp_path, "spirit 10 effect 0 99 45 effect 0 7 45 report")
    assert "loaded 2" in out, err
    assert "spirit 10 -> 30" in out, out
    assert "effect 99 45 -> 99 45 cancelled" in out and "effect 7 45 -> 7 1234" in out, out
    assert re.search(r"\[mod\] b-double on_effect: 1 call\(s\)", err), err


@needs_cc
def test_r1_with_no_mod_every_event_passes_through(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, _ = play(
        driver,
        empty,
        "events heal 30 4 1 spirit 9 escape 0 2 effect 0 99 45 ship 40 "
        "order 1 0 4 5 -1 -1 -1 -1 -1 -1 -1 -1",
    )
    assert "events 0 0 0 0 0 0 0 0 0 0 0" in out, out
    for want in (
        "heal 30 -> 30",
        "spirit 9 -> 9",
        "escape 0 -> 0",
        "effect 99 45 -> 99 45",
        "ship 40 -> 40",
        "order 1 0 4 5 -1",
    ):
        assert want in out, (want, out)
    assert "cancelled" not in out


@needs_cc
def test_r1_a_mod_built_before_the_events_still_loads(driver, tmp_path):
    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (R1,")
    end = header.index("} SoaModApi;", start)
    old = header[:start] + header[end:]
    assert "(*on_heal)" not in old and "(*on_damage)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    d = tmp_path / "mods"
    damage = d / "plus-one"
    mod(d, "plus-one", patches=None, ini=ini2("plus-one"))
    (damage / "mod_src.c").write_text(ADD_ONE, encoding="utf-8")
    library(damage, damage / "mod_src.c", include=inc)
    out, err = play(driver, d, "events damage 7 0 0 0 0 heal 7 4 1")
    assert "loaded 1" in out and "damage 7 -> 8" in out and "heal 7 -> 7" in out, (out, err)
    assert "events 1 0 0 0 0 0 0 0 0 0 0" in out, out


FAULT_IN_HEAL = r"""
#include "soa_mod.h"
static uint32_t heal(void* u, uint32_t v, int s, int t)
{ volatile uint32_t* p = (volatile uint32_t*)u; (void)s; (void)t; return *p + v; }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{ (void)version; return api->on_heal(heal, 0) ? 0 : 1; }
"""


@needs_cc
def test_r1_a_fault_in_an_event_stops_the_run_and_names_its_mod(driver, tmp_path):
    """The mod reads through its null user pointer inside on_heal: exit 10, the
    mod and the event named, and nothing after the call runs."""
    source_mod(tmp_path, "faulty", FAULT_IN_HEAL)
    exe, dol = driver
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    proc = subprocess.run(
        [str(exe), str(tmp_path), str(dol)],
        input="heal 30 4 1 describe",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 10, (proc.returncode, proc.stdout, proc.stderr)
    assert re.search(r"\[mod\] faulty faulted in on_heal: an access violation at ", proc.stderr), (
        proc.stderr
    )
    assert "heal 30 ->" not in proc.stdout and "describe [" not in proc.stdout, proc.stdout


# --------------------------------------------------------------------------
# X2: the save extension (docs/specs/save-extension.md), driven through
# runtime/savext.c as its hooks drive it. The block sits at 0x80400000 in its
# image at 0x803FEBC0; a "card" copy of the image goes to 0x80500000, its
# block at 0x80501440. tools/savext.py reads what the C wrote, and builds what
# the C reads, so the format is held from both sides.
# --------------------------------------------------------------------------

BLOCK, IMAGE, CARD, CARD_BLOCK = 0x80400000, 0x803FEBC0, 0x80500000, 0x80501440
SAVE_THEN_CARD = f"snapshot {BLOCK:x} image {IMAGE:x} copy {IMAGE:x} {CARD:x} 6000 "

COUNTER = r"""
#include "soa_mod.h"
static const SoaModApi* A;
static int32_t save(void* u, uint8_t* buf, uint32_t cap)
{
    uint32_t v = 0;
    (void)u;
    if (cap < 4 || !A->read32(0x80300000u, &v)) return -1;
    buf[0] = (uint8_t)(v >> 24), buf[1] = (uint8_t)(v >> 16), buf[2] = (uint8_t)(v >> 8), buf[3] = (uint8_t)v;
    return 4;
}
static void load(void* u, const uint8_t* d, uint32_t n)
{
    (void)u;
    A->write32(0x80300004u, d && n == 4 ? (uint32_t)d[0] << 24 | (uint32_t)d[1] << 16 | (uint32_t)d[2] << 8 | d[3]
                                        : 0xFFFFFFFFu);
}
static void fresh(void* u)
{
    uint32_t v = 0;
    (void)u;
    A->read32(0x80300008u, &v);
    A->write32(0x80300008u, v + 1);
}
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(on_new_game)) return 1;
    return api->on_save(save, 0) && api->on_load(load, 0) && api->on_new_game(fresh, 0) ? 0 : 1;
}
"""

BIG = r"""
#include "soa_mod.h"
static const SoaModApi* A;
static int32_t save(void* u, uint8_t* buf, uint32_t cap)
{
    uint32_t n = 0, i;
    (void)u;
    A->read32(0x80300010u, &n);
    if (n > cap) return (int32_t)n; /* more than the room: the port says so */
    for (i = 0; i < n; i++) buf[i] = (uint8_t)i;
    return (int32_t)n;
}
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{ (void)version; A = api; return api->on_save(save, 0) ? 0 : 1; }
"""


def block_and_tail(out: str, block_at: int = BLOCK) -> tuple[bytes, bytes]:
    """The hex dumps of a block and of its image's tail, from `out`."""
    dumps = dict(re.findall(r"^hex ([0-9A-F]{8}) ([0-9A-F]*)$", out, re.M))
    block = bytes.fromhex(dumps[f"{block_at:08X}"])
    tail = bytes.fromhex(dumps.get(f"{block_at + savext.BLOCK_LEN:08X}", ""))
    return block, tail


DUMP = f"hex {BLOCK:x} 3200 hex {BLOCK + savext.BLOCK_LEN:x} 19c0 "


def put(at: int, data: bytes) -> str:
    return f"puthex {at:x} {len(data):x} {data.hex()} "


@needs_cc
def test_x2_a_counter_survives_a_save_and_a_load(driver, tmp_path):
    """The counter is 7 at the save and 9 afterwards; the load of the card's copy
    hands the mod 7. New Game tells it, once."""
    source_mod(tmp_path, "counter", COUNTER)
    out, err = play(
        driver,
        tmp_path,
        "set 80300000 7 "
        + SAVE_THEN_CARD
        + DUMP
        + f"set 80300000 9 loadsave {CARD_BLOCK:x} get 80300004 "
        "newgame get 80300008 report",
    )
    assert "loaded 1" in out, err
    block, tail = block_and_tail(out)
    c = savext.parse(block, tail)
    assert c.present and not c.problems and c.chunks == [("counter", b"\x00\x00\x00\x07")], c
    assert c.in_gap == 1 and c.in_tail == 0 and not any(tail), c
    assert "80300004=00000007" in out and "80300008=00000001" in out, out
    assert "[mod] counter registers: on_save, on_load, on_new_game" in err, err


@needs_cc
def test_x2_chunks_overflow_into_the_tail_and_one_too_big_is_refused(driver, tmp_path):
    source_mod(tmp_path, "a-counter", COUNTER)
    source_mod(tmp_path, "b-big", BIG)
    out, err = play(driver, tmp_path, "set 80300000 7 set 80300010 fa0 " + SAVE_THEN_CARD + DUMP)
    block, tail = block_and_tail(out)
    c = savext.parse(block, tail)
    assert not c.problems and c.in_gap == 1 and c.in_tail == 1, c
    assert c.chunks == [
        ("a-counter", b"\x00\x00\x00\x07"),
        ("b-big", bytes(i & 0xFF for i in range(4000))),
    ]
    out, err = play(driver, tmp_path, "set 80300000 7 set 80300010 4e20 " + SAVE_THEN_CARD + DUMP)
    assert "[mod] b-big: its save chunk does not fit" in err, err
    c = savext.parse(*block_and_tail(out))
    assert [name for name, _ in c.chunks] == ["a-counter"], c


@needs_cc
def test_x2_an_unloaded_mods_chunk_is_carried_through_a_save(driver, tmp_path):
    """A save holding counter's chunk, loaded with only big-ish other mod on,
    then saved again: counter's chunk is in the new save, byte for byte."""
    source_mod(tmp_path, "other", BIG)
    gap, _ = savext.build([("counter", b"\x00\x00\x00\x2a")], save_id=bytes(range(16)))
    out, err = play(
        driver,
        tmp_path,
        put(CARD_BLOCK + savext.GAP_OFF, gap)
        + f"loadsave {CARD_BLOCK:x} set 80300010 3 snapshot {BLOCK:x} "
        + DUMP,
    )
    assert "this save holds data for counter, which is not loaded: kept" in err, err
    c = savext.parse(*block_and_tail(out))
    assert ("counter", b"\x00\x00\x00\x2a") in c.chunks and (
        "other",
        b"\x00\x01\x02",
    ) in c.chunks, c
    # a New Game drops it: the next save carries nothing of counter's
    out, _ = play(
        driver,
        tmp_path,
        put(CARD_BLOCK + savext.GAP_OFF, gap)
        + f"loadsave {CARD_BLOCK:x} newgame set 80300010 3 snapshot {BLOCK:x} "
        + DUMP,
    )
    assert [n for n, _ in savext.parse(*block_and_tail(out)).chunks] == ["other"]


@needs_cc
def test_x2_a_damaged_container_or_a_vanilla_save_gives_the_mod_none(driver, tmp_path):
    source_mod(tmp_path, "counter", COUNTER)
    gap, _ = savext.build([("counter", b"\x00\x00\x00\x07")])
    bad = gap[:-1] + bytes([gap[-1] ^ 1])
    out, err = play(
        driver,
        tmp_path,
        put(CARD_BLOCK + savext.GAP_OFF, bad)
        + f"loadsave {CARD_BLOCK:x} get 80300004 loadsave 80600000 get 80300004",
    )
    assert "mod container is damaged" in err, err
    assert out.count("80300004=FFFFFFFF") == 2, out


@needs_cc
def test_x2_with_no_mod_that_saves_nothing_is_written(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, _ = play(driver, empty, SAVE_THEN_CARD + DUMP + f"loadsave {CARD_BLOCK:x}")
    block, tail = block_and_tail(out)
    assert not any(block) and not any(tail)


@needs_cc
def test_x2_a_mod_without_an_id_keeps_no_chunk(driver, tmp_path):
    d = mod(tmp_path, "anon", patches=None)  # manifest 1: no id
    (d / "mod_src.c").write_text(BIG, encoding="utf-8")
    library(d, d / "mod_src.c")
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 0" in out, (out, err)  # its init's on_save returned 0, so it refused itself


@needs_cc
def test_x2_a_mod_built_before_the_save_members_still_loads(driver, tmp_path):
    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (X2,")
    end = header.index("} SoaModApi;", start)
    old = header[:start] + header[end:]
    assert "(*on_save)" not in old and "(*on_ship_damage)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    source_mod(tmp_path / "mods", "every", EVERY_EVENT, include=inc)
    out, err = play(driver, tmp_path / "mods", "heal 30 4 1 " + SAVE_THEN_CARD + DUMP)
    assert "loaded 1" in out and "heal 30 -> 60" in out, (out, err)
    assert not any(block_and_tail(out)[0])


FAULT_IN_SAVE = r"""
#include "soa_mod.h"
static int32_t save(void* u, uint8_t* buf, uint32_t cap)
{ volatile uint8_t* p = (volatile uint8_t*)u; (void)buf; (void)cap; return *p; }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{ (void)version; return api->on_save(save, 0) ? 0 : 1; }
"""


@needs_cc
def test_x2_a_fault_in_on_save_stops_the_run_and_names_its_mod(driver, tmp_path):
    source_mod(tmp_path, "faulty", FAULT_IN_SAVE)
    exe, dol = driver
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    proc = subprocess.run(
        [str(exe), str(tmp_path), str(dol)],
        input=f"snapshot {BLOCK:x} describe",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 10, (proc.returncode, proc.stdout, proc.stderr)
    assert "[mod] faulty faulted in on_save: an access violation" in proc.stderr, proc.stderr
    assert "snapshot\n" not in proc.stdout, proc.stdout


@needs_cc
def test_x2_the_example_keeps_its_tally_in_the_save(driver, tmp_path):
    """examples/mods/battle-tally: two victories, saved; a third, then the card's
    copy loaded brings back two; New Game, none."""
    d = tmp_path / "battle-tally"
    d.mkdir()
    ini = (ROOT / "examples" / "mods" / "battle-tally" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    library(d, ROOT / "examples" / "mods" / "battle-tally" / "mod.c")
    out, err = play(
        driver,
        tmp_path,
        "rewards 6 10 2 rewards 6 10 2 "
        + SAVE_THEN_CARD
        + DUMP
        + f"rewards 6 10 2 loadsave {CARD_BLOCK:x} newgame rewards 6 10 2",
    )
    assert "loaded 1" in out, err
    assert savext.parse(*block_and_tail(out)).chunks == [("battle-tally", b"\x00\x00\x00\x02")]
    said = re.findall(r"\[mod\] battle-tally: (.*)", err)
    assert said == [
        "a victory: 1 battle(s) won in this save",
        "a victory: 2 battle(s) won in this save",
        "a victory: 3 battle(s) won in this save",
        "loaded: 2 battle(s) won in this save",
        "a victory: 1 battle(s) won in this save",
    ], err
    assert "rewards 6 10 2 -> 6 10 2" in out  # it reads the rewards, never changes them


# --------------------------------------------------------------------------
# T2: content ids claimed by name (docs/specs/content-ids.md). mods.lock is
# written beside the mods, which in these tests is tmp_path itself.
# --------------------------------------------------------------------------


def claimer(root: Path, name: str, *flags: str) -> Path:
    """A mod claiming `flags`, saying each number `claim` gives it."""
    d = mod(
        root, name, patches=None, ini=ini2(name) + "".join(f"claim = flag {f}\n" for f in flags)
    )
    asks = "".join(
        f'    if (!api->claim("flag", "{f}", &n)) return 1;\n'
        f'    snprintf(line, sizeof line, "my flag {f} is %u", n);\n'
        "    api->log(line);\n"
        for f in flags
    )
    (d / "mod_src.c").write_text(
        '#include "soa_mod.h"\n#include <stdio.h>\n'
        "SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)\n{\n"
        "    uint32_t n = 0;\n    char line[96];\n    (void)version;\n"
        "    if (api->size < SOA_MOD_HAS(claim)) return 1;\n"
        f'{asks}    return api->claim("flag", "not-mine", &n) ? 1 : 0;\n}}\n',
        encoding="utf-8",
    )
    library(d, d / "mod_src.c")
    return d


def lock_lines(root: Path) -> list[str]:
    return [
        line
        for line in (root / "mods.lock").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


@needs_cc
def test_t2_two_mods_claiming_a_flag_get_different_numbers_and_keep_them(driver, tmp_path):
    """Two mods ask for the same name: each gets its own number, the same every
    run. With the first removed, a third's new claim takes neither number."""
    claimer(tmp_path, "a-quest", "bounty.accepted")
    claimer(tmp_path, "b-quest", "bounty.accepted", "bounty.done")
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 2" in out, err
    assert "[mod] a-quest: my flag bounty.accepted is 24576" in err, err
    assert "[mod] b-quest: my flag bounty.accepted is 24577" in err
    assert "[mod] b-quest: my flag bounty.done is 24578" in err
    assert "[mod] a-quest: flag bounty.accepted is 24576 (new)" in err
    assert lock_lines(tmp_path) == [
        "next flag 24579",
        "flag a-quest bounty.accepted 24576",
        "flag b-quest bounty.accepted 24577",
        "flag b-quest bounty.done 24578",
    ]
    out, err = play(driver, tmp_path, "describe")
    assert "[mod] b-quest: my flag bounty.done is 24578" in err and "(new)" not in err, err
    shutil.rmtree(tmp_path / "a-quest")
    claimer(tmp_path, "c-new", "x")
    out, err = play(driver, tmp_path, "describe")
    assert (
        "[mod] c-new: my flag x is 24579" in err
        and "[mod] b-quest: my flag bounty.accepted is 24577" in err
    ), err
    assert "flag a-quest bounty.accepted 24576" in lock_lines(tmp_path)  # never handed out again


@needs_cc
def test_t2_a_save_from_an_install_that_numbered_a_claim_differently_says_so(driver, tmp_path):
    claimer(tmp_path, "b-quest", "bounty.accepted")
    out, err = play(driver, tmp_path, SAVE_THEN_CARD + DUMP)
    c = savext.parse(*block_and_tail(out))
    assert ("soa.claims", b"flag b-quest bounty.accepted 24576\n") in c.chunks, c
    gap = savext.build(c.chunks)[0]
    # the same lock: nothing to say (the mutation)
    out, err = play(
        driver, tmp_path, put(CARD_BLOCK + savext.GAP_OFF, gap) + f"loadsave {CARD_BLOCK:x}"
    )
    assert "in this save and" not in err and "holds data for soa.claims" not in err, err
    # another install, where the claim came out 25000
    (tmp_path / "mods.lock").write_text(
        "next flag 25001\nflag b-quest bounty.accepted 25000\n", encoding="utf-8"
    )
    out, err = play(
        driver, tmp_path, put(CARD_BLOCK + savext.GAP_OFF, gap) + f"loadsave {CARD_BLOCK:x}"
    )
    assert (
        "[mod] b-quest's flag bounty.accepted is 24576 in this save and 25000 on this install (mods.lock)"
        in err
    ), err
    # a vanilla save names none
    out, err = play(driver, tmp_path, "loadsave 80600000")
    assert "this save names no claims" in err, err


@needs_cc
def test_t2_a_damaged_lock_refuses_only_the_mods_that_claim(driver, tmp_path):
    claimer(tmp_path, "b-quest", "bounty.accepted")
    mod(tmp_path, "plain")  # a patch, no claim
    (tmp_path / "mods.lock").write_text(
        "next flag 24577\nflag b-quest bounty.accepted lots\n", encoding="utf-8"
    )
    out, err = play(driver, tmp_path, "describe")
    assert "mods.lock:2: not `flag <mod id> <name> <number>`" in err, err
    assert "loaded 1" in out and "b-quest/mod.ini" in err and "it claims numbers" in err, (out, err)


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("claim = map sky_rift", "gives out flags only"),
        ("claim = flag Bad.Name", "a name is lowercase"),
        ("claim = flag", "gives out flags only"),
    ],
)
@needs_cc
def test_t2_a_claim_this_port_cannot_give_refuses_the_mod(driver, tmp_path, line, words):
    mod(tmp_path, "asker", ini=ini2("asker") + line + "\n")
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 0" in out and "asker/mod.ini:" in err and words in err, err


@needs_cc
def test_t2_ids_beginning_soa_are_the_ports(driver, tmp_path):
    mod(tmp_path, "imposter", ini=ini2("soa.claims"))
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 0" in out and "the port's own" in err, err


# --------------------------------------------------------------------------
# M7a: save now (docs/specs/save-now.md), through runtime/savenow.c as the
# safe point and X2's sites drive it. 116a has a save point; 116c has none.
# --------------------------------------------------------------------------

FIELD = "set 803475cc 6 set 80311aec 8 set 80311ac0 74 "  # scene 6, the field running, map 116


def at(letter: str) -> str:
    return f"set 80311ac8 {ord(letter):02x}000000 "


def block_map(letter: str) -> str:
    return f"set {BLOCK + 5808:x} 74 set {BLOCK + 5812:x} {ord(letter):02x}000000 "


@needs_cc
def test_m7a_a_save_now_off_a_save_point_carries_the_last_one_and_comes_back(driver, tmp_path):
    """On 116a, then 116c: the request is written, the save's map letter is a
    (the fallback) and its soa.savenow chunk names c; the card's copy, loaded,
    is put back to c before the game copies it, and sys15 is 0 after."""
    empty = tmp_path / "none"
    empty.mkdir()
    script = (
        FIELD
        + at("a")
        + "savenow_tick "
        + at("c")
        + "savenow_req savenow_tick get 803473b4 "
        + block_map("c")
        + SAVE_THEN_CARD
        + DUMP
        + f"set 8030e420 4e20 loadsave {CARD_BLOCK:x} get {CARD_BLOCK + 5812:x} get 8030e420"
    )
    out, err = play(driver, empty, script)
    assert "803473B4=00000001" in out, (out, err)  # the save menu asked for
    assert "[savenow] frame" in err and "off a save point" in err, err
    block, tail = block_and_tail(out)
    assert block[5808:5812] == b"\x00\x00\x00\x74" and block[5812:5813] == b"a", block[5808:5816]
    c = savext.parse(block, tail)
    assert c.chunks == [("soa.savenow", b"SN1\x00" + b"\x00\x00\x74c" + b"\x00\x00\x74a")], c
    assert f"{CARD_BLOCK + 5812:08X}=63000000" in out, out  # c again, before the game reads it
    assert "8030E420=00000000" in out, out  # the player lands where the save was made
    assert "holds data for soa.savenow" not in err


@needs_cc
def test_m7a_on_a_save_point_the_save_keeps_its_map(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        FIELD + at("a") + "savenow_req savenow_tick " + block_map("a") + SAVE_THEN_CARD + DUMP,
    )
    block, tail = block_and_tail(out)
    assert block[5812:5813] == b"a"
    assert savext.parse(block, tail).chunks == [
        ("soa.savenow", b"SN1\x00" + b"\x00\x00\x74a" + bytes(4))
    ]


@pytest.mark.parametrize(
    ("state", "words"),
    [
        ("set 803475cc 7 ", "in a battle"),
        ("set 80311aec 3 ", "while the field loads"),
        ("set 8030e714 1 ", "during an event"),
        ("set 80310bc0 80000000 ", "during an event"),  # flag 1087: bit 31 of word 33
    ],
)
@needs_cc
def test_m7a_a_save_now_when_the_field_is_not_quiet_is_refused(driver, tmp_path, state, words):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        FIELD + at("a") + state + "savenow_req savenow_tick get 803473b4 " + SAVE_THEN_CARD + DUMP,
    )
    assert "803473B4=00000000" in out and f"save now refused, {words}" in err, (out, err)
    assert not any(block_and_tail(out)[0])  # nothing for the snapshot to write


# --------------------------------------------------------------------------
# M7b: the debug actions (docs/specs/debug-actions.md), through
# runtime/actions.c's queue as the menu and SOA_ACTION fill it. The kinds are
# actions.h's: 1 warp, 2 part, 3 ending, 4 fade, 5 encounters off, 6 on.
# --------------------------------------------------------------------------

WARP_WORDS = "hex 80305cf0 c get 8030e420 get 80311aec "


def script_name(out: str) -> bytes:
    return bytes.fromhex(re.search(r"^hex 80305CF0 ([0-9A-F]*)$", out, re.M).group(1))


@needs_cc
def test_m7b_a_warp_writes_the_name_the_entrance_then_the_state(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver, empty, FIELD + at("a") + "set 8030e420 4e20 act 1 6761 actions_tick " + WARP_WORDS
    )
    assert script_name(out) == b"ME103A.SCT\0\0", out
    assert "8030E420=00000000" in out and "80311AEC=0000000F" in out, out  # sys15 0, the warp state
    assert "[action] frame 0: warp to 103a" in err, err
    out, err = play(driver, empty, FIELD + at("a") + "act 2 0 actions_tick " + WARP_WORDS)
    assert script_name(out) == b"ME355A.SCT\0\0" and "part select" in err, (out, err)


@needs_cc
def test_m7b_the_ending_the_fade_and_the_encounter_toggle(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        FIELD
        + at("a")
        + "act 3 0 actions_tick get 80310a68 "  # B[76], the word's first byte
        + "set 80347518 1 act 4 0 actions_tick get 80347518 "
        + "act 5 0 actions_tick set 80346d28 4d2 actions_tick get 80346d28 "
        + "act 6 0 actions_tick set 80346d28 5 actions_tick get 80346d28",
    )
    assert "80310A68=4C000000" in out, out
    assert "80347518=00000000" in out, out
    gets = re.findall(r"^80346D28=([0-9A-F]{8})$", out, re.M)
    assert gets == ["00000000", "00000005"], out  # held at 0 while off, left alone once on
    assert "encounters off" in err and "encounters on" in err, err


@pytest.mark.parametrize(
    ("state", "kind_map", "words"),
    [
        ("set 803475cc 7 ", "1 6761", "warp to 103a refused, in a battle"),
        ("", "1 1f461", "warp to 500a refused, a ship battle starts through op 210"),
        ("", "1 7478", "warp to 116x refused, no script and geometry by that name"),
        ("set 80311aec 3 ", "3 0", "ending refused, while the field loads"),
    ],
)
@needs_cc
def test_m7b_an_action_it_cannot_take_is_refused_and_writes_nothing(
    driver, tmp_path, state, kind_map, words
):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        FIELD + at("a") + state + f"act {kind_map} actions_tick " + WARP_WORDS + "get 80310a68",
    )
    assert words in err, err
    assert script_name(out) == bytes(12) and "80310A68=00000000" in out, out


@needs_cc
def test_m7b_soa_action_s_grammar_its_frames_and_its_faults(driver, tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        FIELD + at("a") + "set 80347518 1 actions fade@2,warp:a103a@0 actions_tick get 80347518 "
        "frame frame actions_tick get 80347518 " + WARP_WORDS,
    )
    assert "scheduled 2" in out, (out, err)
    assert re.findall(r"^80347518=([0-9A-F]{8})$", out, re.M) == ["00000001", "00000000"], (
        out
    )  # fade at frame 2
    assert script_name(out) == b"ME103A.SCT\0\0", out
    for bad, said in (
        ("warp:zz@1", "a warp names a map like 116c"),
        ("dance@1", "is not warp:NNNx, part"),
        ("fade", "is not NAME[:ARG]@FRAME"),
        ("fade@soon", "the frame is not a number"),
    ):
        out, err = play(driver, empty, f"actions {bad}")
        assert "scheduled -1" in out and said in err, (bad, out, err)


# --------------------------------------------------------------------------
# E3: the event track's actions and save now (docs/specs/event-track.md),
# through actions.c and savenow.c with the fake guest's stand-in track.
# --------------------------------------------------------------------------


def lines_of(out: str, word: str) -> list[str]:
    return [x for x in out.splitlines() if x.startswith(word + " ")]


@needs_cc
def test_e3_what_is_written_is_recorded_and_what_is_refused_is_not(driver, tmp_path):
    """With a track and no replay, a save now, a warp and the encounter toggle
    each become a record at their frame, in SOA_ACTION's names; a refused warp
    records nothing. The mutation, a record before the refusal check, records
    the refused one too."""
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        "track "
        + FIELD
        + at("a")
        + "savenow_req savenow_tick set 803473b4 0 "
        + "act 1 6761 actions_tick act 5 0 actions_tick "
        + "set 803475cc 7 act 1 6761 actions_tick",
    )
    assert lines_of(out, "record") == [
        "record 0 savenow",
        "record 0 action warp:103a",
        "record 0 action encounters:off",
    ], out
    assert "warp to 103a refused, in a battle" in err, err


@needs_cc
def test_e3_during_a_replay_the_recording_s_actions_run_and_nothing_else(driver, tmp_path):
    """A replay is the whole input: SOA_ACTION's fade at frame 0 and a menu
    request asked before the replay was known take nothing, the menu cannot
    ask once it is (the queue empty by then, so the refusal is the replay's),
    and the recording's warp runs at its frame, 2, recorded again for a
    recording made of the replay. Mutations: SOA_ACTION's schedule run during
    a replay (the fade lands at 0); the queued request run (the fade lands);
    the menu's ask not refused (a second "requested 1"); the recording's line
    never taken (no warp at 2)."""
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        "track "
        + FIELD
        + at("a")
        + "set 80347518 1 actions fade@0 act 4 0 replay line action 2 warp:103a "
        + "actions_tick act 4 0 get 80347518 hex 80305cf0 c "
        + "frame frame actions_tick get 80347518 "
        + WARP_WORDS,
    )
    assert "scheduled 1" in out, out
    assert lines_of(out, "requested") == ["requested 1", "requested 0"], out
    assert re.findall(r"^80347518=([0-9A-F]{8})$", out, re.M) == ["00000001", "00000001"], out
    assert "a replay is running: the menu's request takes nothing" in err, err
    names = re.findall(r"^hex 80305CF0 ([0-9A-F]*)$", out, re.M)
    assert [bytes.fromhex(n) for n in names] == [bytes(12), b"ME103A.SCT\0\0"], out
    assert "[action] frame 2: warp to 103a" in err, err
    assert lines_of(out, "record") == ["record 2 action warp:103a"], out


@needs_cc
def test_e3_a_recorded_action_the_replay_cannot_run_leaves_the_recording(driver, tmp_path):
    """Refused where the recording ran it, or not an action this build knows:
    each is the replay leaving its recording, said once, and nothing is
    written or recorded."""
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        "track replay line action 0 warp:103a line action 0 dance "
        + FIELD
        + at("a")
        + "set 803475cc 7 actions_tick "
        + WARP_WORDS,
    )
    assert lines_of(out, "left") == [
        "left 0 action warp:103a, in a battle",
        "left 0 action dance, not an action this build knows",
    ], out
    assert not lines_of(out, "record") and script_name(out) == bytes(12), out


@needs_cc
def test_e3_during_a_replay_save_now_asks_at_the_recording_s_frames_only(driver, tmp_path):
    """SOA_SAVE_NOW at frame 0 and a request asked before the replay was known
    take nothing; the recording's save now at frame 2 opens the save menu and
    is recorded; one at frame 3, the field loading, leaves the recording.
    Mutations: SOA_SAVE_NOW's frame run during a replay (the menu asked at
    0); the queued request run (likewise); the line never taken (nothing at
    2)."""
    empty = tmp_path / "none"
    empty.mkdir()
    out, err = play(
        driver,
        empty,
        "savenow_init track "
        + FIELD
        + at("a")
        + "savenow_req replay line savenow 2 - line savenow 3 - "
        + "savenow_tick get 803473b4 frame frame savenow_tick get 803473b4 "
        + "frame set 80311aec 3 savenow_tick",
        SOA_SAVE_NOW="0",
    )
    assert re.findall(r"^803473B4=([0-9A-F]{8})$", out, re.M) == ["00000000", "00000001"], out
    assert "a replay is running: the request takes nothing" in err, err
    assert lines_of(out, "record") == ["record 2 savenow"], out
    assert lines_of(out, "left") == ["left 3 save now, while the field loads"], out


# --------------------------------------------------------------------------
# mods/battle-boosts (PLAN-GAMEPLAY-MODS R4, docs/specs/battle-mods.md 3) on
# the fake guest: the dispatchers R1's events go through, the battle's memory
# laid out where the game keeps it
# --------------------------------------------------------------------------

BOOSTS = ROOT / "mods" / "battle-boosts"
ACTORS = 0x80309DE4  # battle.actors, ptr[12]
PARTY0, PARTY1, ENEMY4 = 0x80420000, 0x80420200, 0x80420800
BATTLE_CTX = 0x80430000
POISON_WORD = 0x80346BE8  # battle.poison_lethal
# slot 0 and 1 the party, slot 4 an enemy; each at 50 HP and no status
BATTLE = (
    f"set {ACTORS:x} {PARTY0:x} set {ACTORS + 4:x} {PARTY1:x} set {ACTORS + 16:x} {ENEMY4:x} "
    f"set {PARTY0 + 20:x} 32 set {PARTY1 + 20:x} 32 set {ENEMY4 + 20:x} 32 "
)


def boosts(driver, tmp_path, script: str, opts: str = "", **env) -> tuple[str, str]:
    shipped(tmp_path, folder=BOOSTS)
    if opts:
        env["SOA_MOD_OPT"] = " ".join(f"battle-boosts.{o}" for o in opts.split())
    return play(driver, tmp_path, script, **env)


def mod_lines(err: str, name: str = "battle-boosts") -> list[str]:
    """The mod's own log lines, in order: the port's option lines left out."""
    said = [x.split(f"[mod] {name}: ", 1)[1] for x in err.splitlines() if f"[mod] {name}: " in x]
    return [x for x in said if not x.startswith("option ")]


def test_battle_boosts_is_shipped_and_built_by_link():
    import recompile

    srcs = {p.parent.relative_to(ROOT).as_posix() for p in recompile.mod_dll_sources()}
    assert "mods/battle-boosts" in srcs, srcs
    keys = {}
    for line in (BOOSTS / "mod.ini").read_text(encoding="utf-8").splitlines():
        key, eq, value = line.partition("=")
        if eq and not line.lstrip().startswith("#"):
            keys[key.strip()] = value.strip()
    assert (
        keys.get("manifest") == "2" and keys.get("id") == "battle-boosts" and keys.get("api") == "1"
    ), keys


@needs_cc
def test_battle_boosts_at_its_defaults_registers_nothing(driver, tmp_path):
    """Setup installs every folder of mods/ and loads them all, so the
    defaults must be the game's: no handler registered -- the battle events,
    and the safe point the Spirit and the test switch use -- and nothing
    written at a battle's first round or between battles."""
    out, err = boosts(
        driver,
        tmp_path,
        f"set 803475cc 6 set {CHARS + 24:x} 1a401a4 safe "
        + BATTLE
        + spirit_battle()
        + "safe events rewards 120 300 3 escape 0 0 damage 99 9 0 80420000 0 "
        + f"get {BATTLE_CTX + 8:x} get {CHARS + 24:x} get {PARTY0 + 20:x}",
    )
    assert "loaded 1" in out, err
    assert mod_lines(err) == ["every option at its default: nothing registered"], err
    assert "[mod] battle-boosts registers" not in err, err  # the port names every registration
    assert "events 0 0 0 0 0 0 0 0 0 0 0" in out, out
    assert (
        "rewards 120 300 3 -> 120 300 3" in out
        and "escape 0 -> 0" in out
        and "damage 99 -> 99" in out
    ), out
    assert f"{BATTLE_CTX + 8:08X}=00030003" in out and f"{CHARS + 24:08X}=01A401A4" in out, out
    assert f"{PARTY0 + 20:08X}=00000032" in out, out


@needs_cc
def test_battle_boosts_multiplies_rewards_rounding_down(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        "rewards 101 33 40 rewards 7 1 2 rewards 0 99999999 127",
        "exp=1.5 gold=3 magic_exp=4",
    )
    assert mod_lines(err) == ["exp x1.5, gold x3, magic EXP x4"], err
    assert lines_of(out, "rewards") == [
        "rewards 101 33 40 -> 151 99 127",  # 151.5 down; 160 held to 127
        "rewards 7 1 2 -> 10 3 8",
        "rewards 0 99999999 127 -> 0 299999997 127",  # the port and the game hold gold, not the mod
    ], out


@needs_cc
@pytest.mark.parametrize(
    "opt, want",
    [
        ("exp=0", "rewards 50 7 3 -> 0 7 3"),
        ("gold=0.5", "rewards 50 7 3 -> 50 3 3"),
        ("magic_exp=2", "rewards 50 7 3 -> 50 7 6"),
    ],
)
def test_battle_boosts_each_reward_has_its_own_multiplier(driver, tmp_path, opt, want):
    out, err = boosts(driver, tmp_path, "rewards 50 7 3", opt)
    assert want in out, (out, err)


@needs_cc
def test_battle_boosts_escape_is_for_the_party_alone(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        "escape 0 0 escape 0 3 escape 1 2 escape 0 4 escape 1 11 escape 0 7",
        "escape=1",
    )
    assert lines_of(out, "escape") == [
        "escape 0 -> 1",
        "escape 0 -> 1",
        "escape 1 -> 1",
        "escape 0 -> 0",  # an enemy's failed roll stays failed
        "escape 1 -> 1",  # and its success a success
        "escape 0 -> 0",
    ], out
    assert mod_lines(err)[1:] == [
        "escape: slot 0's Run failed its roll; it gets away",
        "escape: slot 3's Run failed its roll; it gets away",
    ], err


@needs_cc
def test_battle_boosts_no_ko_holds_a_blow_on_the_party_to_hp_minus_one(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + "damage 49 9 0 80420000 0 damage 50 9 0 80420000 0 damage 999 9 0 80420200 0 "
        + "damage 999 9 0 80420800 0 damage 0 9 0 80420000 0 "
        + f"set {PARTY0 + 20:x} 1 damage 5 9 0 80420000 0",
        "no_ko=1",
    )
    assert lines_of(out, "damage") == [
        "damage 49 -> 49",  # leaves 1: as it was
        "damage 50 -> 49",
        "damage 999 -> 49",
        "damage 999 -> 999",  # an enemy is knocked out as ever
        "damage 0 -> 0",
        "damage 5 -> 0",  # at 1 HP a blow takes nothing
    ], out
    assert "no knock-out: a blow of 999 on slot 1 held to 49 (HP 50)" in mod_lines(err), err


@needs_cc
def test_battle_boosts_no_ko_rewrites_the_effects_that_knock_out(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + "effect 0 0 80 effect 0 44 80 effect 1 72 50 effect 0 5 0 effect 0 6 80 effect 1 68 30 "
        + "effect 0 31 80 effect 0 66 80 effect 0 3 80 effect 0 0 -20 effect 4 0 80 effect 4 5 0",
        "no_ko=1",
    )
    assert lines_of(out, "effect") == [
        "effect 0 80 -> 0 49",
        "effect 44 80 -> 44 49",  # drain lands as effect 0's damage
        "effect 72 50 -> 72 49",
        "effect 5 0 -> 5 0 cancelled",
        "effect 6 80 -> 0 49",
        "effect 68 30 -> 0 30",  # not lethal: the damage kept, the death dropped
        "effect 31 80 -> 31 80",  # a heal
        "effect 66 80 -> 66 80",  # Blue Rogues heals a party member
        "effect 3 80 -> 3 80",  # a status
        "effect 0 -20 -> 0 -20",
        "effect 0 80 -> 0 80",  # an enemy
        "effect 5 0 -> 5 0",
    ], out
    assert "no knock-out: effect 6 value 80 on slot 0 -> effect 0 value 49 (HP 50)" in mod_lines(
        err
    ), err


# The spec's section 2: the appliers that reach effect 0's (damage, then the
# KO function) from inside their own, and what does not.
LANDS_AS_DAMAGE = (0, 4, 8, 17, 44, 61, 62, 65, 69, 70, 72)


@needs_cc
def test_battle_boosts_no_ko_holds_every_effect_that_lands_as_damage(driver, tmp_path):
    """Each of the eleven held on a party member at a lethal value, and the
    heals (31, 32, and 66, Blue Rogues' on a party member) and a status (3)
    left: a case left out of the mod's list fails here."""
    held = "".join(f"effect 1 {e} 99 " for e in LANDS_AS_DAMAGE)
    left = "".join(f"effect 1 {e} 99 " for e in (31, 32, 66, 3))
    out, err = boosts(driver, tmp_path, BATTLE + held + left, "no_ko=1")
    assert lines_of(out, "effect") == [f"effect {e} 99 -> {e} 49" for e in LANDS_AS_DAMAGE] + [
        f"effect {e} 99 -> {e} 99" for e in (31, 32, 66, 3)
    ], out


@needs_cc
def test_battle_boosts_no_ko_takes_the_party_s_lethal_poison_bits(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + f"set {PARTY0 + 20:x} 7 set {PARTY0 + 28:x} 80 set {POISON_WORD:x} 31 roundend 2 "
        + f"get {POISON_WORD:x} get {PARTY0 + 20:x} get {PARTY0 + 28:x} "
        + f"get {PARTY1 + 20:x} get {PARTY1 + 28:x} set {POISON_WORD:x} 30 roundend 3 get {POISON_WORD:x}",
        "no_ko=1",
    )
    assert re.findall(r"^80346BE8=([0-9A-F]{8})$", out, re.M) == ["00000030", "00000030"], out
    assert f"{PARTY0 + 20:08X}=00000001" in out and f"{PARTY1 + 20:08X}=00000032" in out, out
    # at 1 HP the low-HP bit, as fn_80010474 would give it; slot 1 untouched
    assert f"{PARTY0 + 28:08X}=00008080" in out and f"{PARTY1 + 28:08X}=00000000" in out, out
    assert mod_lines(err)[1:] == [
        "no knock-out: round 2, poison would have knocked out slot 0: HP 7 -> 1",
        "no knock-out: lethal-poison word 00000031 -> 00000030",
    ], err  # the enemies' bits alone: nothing said, nothing written


RESULTS = 0x80309730  # battle.results, 16 bytes a slot, the hit result at +8


@needs_cc
def test_battle_boosts_no_ko_turns_a_death_that_landed_into_a_miss(driver, tmp_path):
    """A death that lands (effect 5, and 6's death branch, which carries no
    value, -1) leaves the target's hit result at KO (5): the assist cancels
    it and makes the result a miss, a death spell that did not land. 68,
    whose damage still lands, becomes effect 0 with its KO result a hit. 6's
    -1 is never applied as effect 0, which would add 1 HP."""
    ko = lambda slot: f"setb {RESULTS + 16 * slot + 8:x} 5 "  # noqa: E731
    result = lambda slot: f"get {RESULTS + 16 * slot + 8:x} "  # noqa: E731
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + ko(0)
        + "effect 0 5 0 "
        + result(0)
        + ko(1)
        + "effect 1 6 -1 "
        + result(1)
        + ko(0)
        + "effect 0 68 30 "
        + result(0)
        + "effect 1 6 -1 "
        + result(1)  # no KO result to unmark: cancelled all the same
        + "effect 1 68 -1 ",  # a 68 with no value: no damage, never a heal
        "no_ko=1",
    )
    assert lines_of(out, "effect") == [
        "effect 5 0 -> 5 0 cancelled",
        "effect 6 -1 -> 6 -1 cancelled",
        "effect 68 30 -> 0 30",
        "effect 6 -1 -> 6 -1 cancelled",
        "effect 68 -1 -> 0 0",
    ], out
    words = re.findall(rf"^({RESULTS + 8:08X}|{RESULTS + 24:08X})=([0-9A-F]{{8}})$", out, re.M)
    # the hit result is the high byte of the word at +8: miss, miss, hit, and the miss left
    assert [int(v, 16) >> 24 for _, v in words] == [0, 0, 1, 0], out
    lines = mod_lines(err)
    assert (
        "no knock-out: effect 5 on slot 0 cancelled, its KO result made a miss (HP 50)" in lines
    ), err
    assert (
        "no knock-out: effect 68 value 30 on slot 0 -> effect 0 value 30, its KO result made a hit (HP 50)"
        in lines
    ), err


def spirit_battle(scene: int = 7, phase: int = 1, sp: int = 0x00030003) -> str:
    """Scene, the context with max SP 10 and SP (and SP free) given, the phase."""
    return (
        f"set 803475cc {scene:x} set 80347390 {BATTLE_CTX:x} set {BATTLE_CTX + 4:x} a "
        f"set {BATTLE_CTX + 8:x} {sp:x} set 8034733c {phase:x} "
    )


@needs_cc
def test_battle_boosts_full_spirit_once_a_battle_at_its_first_round(driver, tmp_path):
    ctx_sp = f"get {BATTLE_CTX + 8:x} "
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + spirit_battle(phase=0)
        + "safe "
        + ctx_sp  # phase 0: not yet
        + "set 8034733c 1 safe "
        + ctx_sp  # filled
        + f"set {BATTLE_CTX + 8:x} 20002 safe "
        + ctx_sp  # spent, and not filled again this battle
        + "set 803475cc 6 safe "
        + spirit_battle(phase=2, sp=0x00010001)
        + "safe "
        + ctx_sp,  # the next battle, after an ambush
        "full_spirit=1",
    )
    assert re.findall(rf"^{BATTLE_CTX + 8:08X}=([0-9A-F]{{8}})$", out, re.M) == [
        "00030003",
        "000A000A",
        "00020002",
        "000A000A",
    ], out
    assert mod_lines(err)[1:] == [
        "full spirit: SP 3 -> 10 of 10",
        "full spirit: SP 1 -> 10 of 10",
    ], err


@needs_cc
def test_battle_boosts_full_spirit_leaves_a_no_spirit_party_alone(driver, tmp_path):
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE + f"set {PARTY1 + 28:x} 10000 " + spirit_battle() + f"safe get {BATTLE_CTX + 8:x}",
        "full_spirit=1",
    )
    assert f"{BATTLE_CTX + 8:08X}=00030003" in out, out
    assert "full spirit: a member's equipment holds SP at 0; left as it is" in mod_lines(err), err
    # an unconscious member's equipment does not count
    out, err = boosts(
        driver,
        tmp_path / "ko",
        BATTLE + f"set {PARTY1 + 28:x} 10100 " + spirit_battle() + f"safe get {BATTLE_CTX + 8:x}",
        "full_spirit=1",
    )
    assert f"{BATTLE_CTX + 8:08X}=000A000A" in out, out
    # nor an escaped one's (0x2000, the other half of the game's "not present")
    out, err = boosts(
        driver,
        tmp_path / "fled",
        BATTLE + f"set {PARTY1 + 28:x} 12000 " + spirit_battle() + f"safe get {BATTLE_CTX + 8:x}",
        "full_spirit=1",
    )
    assert f"{BATTLE_CTX + 8:08X}=000A000A" in out, out


CHARS = 0x8030B7F4  # party.character[6], 92 bytes each, HP the s16 at +24
PARTY2 = 0x80420400


@needs_cc
def test_battle_boosts_test_switch_starts_the_battle_at_one_hp(driver, tmp_path):
    """Between battles the switch holds each character's HP at 1, so the next
    battle's setup brings the members in at 1 (a write to the actors in the
    first round stalled the story's first battle); at the first round `poison`
    poisons the living ones."""
    between = (
        f"set 803475cc 6 set {CHARS + 24:x} 1a401a4 set {CHARS + 92 + 24:x} 1680168 safe "
        + f"set {CHARS + 24:x} 6401a4 safe "  # raised again (a level, an inn): lowered, not said again
        + f"get {CHARS + 24:x} get {CHARS + 92 + 24:x} "
    )
    first_round = (
        BATTLE
        + f"set {ACTORS + 8:x} {PARTY2:x} set {PARTY2 + 20:x} 32 set {PARTY2 + 28:x} 2000 "
        + f"set {PARTY1 + 28:x} 100 "
        + spirit_battle()
        + f"safe get {PARTY0 + 20:x} get {PARTY0 + 28:x} get {PARTY1 + 28:x} get {PARTY2 + 28:x} "
        + f"get {ENEMY4 + 28:x}"
    )
    out, err = boosts(driver, tmp_path, between + first_round, SOA_BOOSTS_TEST="poison")
    # HP 420 of 420 and 360 of 360: each HP to 1, its maximum kept
    assert f"{CHARS + 24:08X}=000101A4" in out and f"{CHARS + 92 + 24:08X}=00010168" in out, out
    assert f"{PARTY0 + 20:08X}=00000032" in out, out  # no actor's HP written
    assert f"{PARTY0 + 28:08X}=00000080" in out, out  # poisoned at the first round
    assert f"{PARTY1 + 28:08X}=00000100" in out, out  # unconscious: left alone
    assert f"{PARTY2 + 28:08X}=00002000" in out, out  # escaped: left alone
    assert f"{ENEMY4 + 28:08X}=00000000" in out, out
    lines = mod_lines(err)
    assert lines.count("test: 2 character(s) at 1 HP from frame 0") == 1, err  # said once
    assert "test: slot 0 at HP 50, poisoned" in lines, err
    # `lowhp` poisons no one
    out, err = boosts(driver, tmp_path / "lowhp", between + first_round, SOA_BOOSTS_TEST="lowhp")
    assert f"{PARTY0 + 28:08X}=00000000" in out and f"{CHARS + 24:08X}=000101A4" in out, out
    assert "test: slot 0 at HP 50" in mod_lines(err), err


# --------------------------------------------------------------------------
# mods/difficulty (PLAN-GAMEPLAY-MODS R3, docs/specs/battle-mods.md 4) on the
# fake guest: an enemy as fn_800770B8 leaves it, then R1's spawn dispatcher
# --------------------------------------------------------------------------

DIFFICULTY = ROOT / "mods" / "difficulty"
FOE, FOE_RECORD = 0x80440000, 0x80450000
# HP 58; level 5 and Will 10 (+128); Quick 15 (+136); Attack 30 and Defense 20
# (+148); MagDef 20 and Hit 80 (+152); the base copies alike (+232, +240, +244)
FOE_SET = {20: 58, 24: 58, 128: 0x5000A, 136: 0xF0000, 148: 0x1E0014, 152: 0x140050}
FOE_SET |= {232: 0x5000A, 240: 0xF001E, 244: 0x140014}
# the record: its max HP (+36) and its Quick, Attack, Defense, MagDef (+100..+107)
RECORD_SET = {36: 58, 100: 0xF001E, 104: 0x140014}


def made(fields: dict[int, int] | None = None) -> str:
    """The script that lays out the enemy and its record, `fields` over FOE_SET."""
    words = FOE_SET | (fields or {})
    return "".join(f"set {FOE + off:x} {v:x} " for off, v in words.items()) + "".join(
        f"set {FOE_RECORD + off:x} {v:x} " for off, v in RECORD_SET.items()
    )


def spawned(out: str, base: int, offsets) -> dict[int, int]:
    words = dict(re.findall(r"^([0-9A-F]{8})=([0-9A-F]{8})$", out, re.M))
    return {off: int(words[f"{base + off:08X}"], 16) for off in offsets}


def want(hp, will, quick, attack, defense, magdef) -> dict[int, int]:
    """FOE_SET's words with the stats given, each base copy the same."""
    return {
        20: hp,
        24: hp,
        128: 5 << 16 | will,
        136: quick << 16,
        148: attack << 16 | defense,
        152: magdef << 16 | 80,
        232: 5 << 16 | will,
        240: quick << 16 | attack,
        244: defense << 16 | magdef,
    }


def difficulty(driver, tmp_path, opts: str = "", fields=None, script: str = "") -> tuple[str, str]:
    shipped(tmp_path, folder=DIFFICULTY)
    env = {}
    if opts:
        env["SOA_MOD_OPT"] = " ".join(f"difficulty.{o}" for o in opts.split())
    gets = "".join(f"get {FOE + off:x} " for off in FOE_SET) + "".join(
        f"get {FOE_RECORD + off:x} " for off in RECORD_SET
    )
    # a battle under way (scene 7, seen at a safe point), so leaving it is a scene change
    battle = "set 803475cc 7 safe " + made(fields)
    return play(driver, tmp_path, battle + f"spawn {FOE:x} {FOE_RECORD:x} " + gets + script, **env)


def test_difficulty_is_shipped_and_built_by_link():
    import recompile

    srcs = {p.parent.relative_to(ROOT).as_posix() for p in recompile.mod_dll_sources()}
    assert "mods/difficulty" in srcs, srcs
    keys = {}
    for line in (DIFFICULTY / "mod.ini").read_text(encoding="utf-8").splitlines():
        key, eq, value = line.partition("=")
        if eq and not line.lstrip().startswith("#"):
            keys[key.strip()] = value.strip()
    assert (
        keys.get("manifest") == "2" and keys.get("id") == "difficulty" and keys.get("api") == "1"
    ), keys


@needs_cc
def test_difficulty_at_normal_registers_nothing(driver, tmp_path):
    out, err = difficulty(driver, tmp_path, script="events rewards 103 10 3")
    assert "loaded 1" in out, err
    assert mod_lines(err, "difficulty") == [
        "normal: hp x1.00 attack x1.00 defense x1.00 magdef x1.00 speed x1.00 rewards x1.00; nothing registered"
    ], err
    assert spawned(out, FOE, FOE_SET) == FOE_SET, out
    assert "events 0 0 0 0 0 0 0 0 0 0 0" in out and "rewards 103 10 3 -> 103 10 3" in out, out


@needs_cc
@pytest.mark.parametrize(
    "preset, stats, said, rewards",
    [
        (
            "easy",
            (29, 7, 15, 22, 20, 20),
            "HP 58 -> 29, Attack 30 -> 22, Will 10 -> 7",
            "rewards 103 10 3 -> 103 10 3",
        ),
        (
            "hard",
            (87, 12, 15, 37, 20, 20),
            "HP 58 -> 87, Attack 30 -> 37, Will 10 -> 12",
            "rewards 103 10 3 -> 128 12 3",
        ),
        (
            "nightmare",
            (116, 15, 18, 45, 25, 25),
            "HP 58 -> 116, Attack 30 -> 45, Will 10 -> 15, Defense 20 -> 25, MagDef 20 -> 25, Quick 15 -> 18",
            "rewards 103 10 3 -> 154 15 4",
        ),
    ],
)
def test_difficulty_each_preset_scales_the_actor_and_its_records_max_hp_for_the_battle(
    driver, tmp_path, preset, stats, said, rewards
):
    """The record's max HP is scaled with the actor's, since the boss music
    (fn_8007D42C) weighs the bosses' HP against it, and put back when the
    scene leaves the battle; nothing else of the record is written."""
    back = f"rewards 103 10 3 set 803475cc 6 safe get {FOE_RECORD + 36:x}"
    out, err = difficulty(driver, tmp_path, f"preset={preset}", script=back)
    assert spawned(out, FOE, FOE_SET) == want(*stats), (out, err)
    record_hp = re.findall(rf"^{FOE_RECORD + 36:08X}=([0-9A-F]{{8}})$", out, re.M)
    assert [int(v, 16) for v in record_hp] == [stats[0], 58], out  # in the battle, then after it
    assert spawned(out, FOE_RECORD, (100, 104)) == {100: RECORD_SET[100], 104: RECORD_SET[104]}, out
    assert rewards in out, out
    lines = mod_lines(err, "difficulty")
    assert f"spawn {FOE:08X}: {said}" in lines, err
    assert f"record {FOE_RECORD:08X}: max HP {stats[0]} put back to 58" in lines, err


FOE2, FOE3, OTHER_RECORD = 0x80441000, 0x80442000, 0x80451000


@needs_cc
def test_difficulty_a_second_enemy_of_the_kind_comes_scaled_and_is_not_scaled_again(
    driver, tmp_path
):
    """The game makes an enemy's HP from its record's max HP, so after the
    first spawn of a kind scaled the record, a second arrives with the scaled
    HP: it is left there, its other stats scaled as ever. Another kind's
    record is scaled at its own first spawn. The mutation, every spawn's HP
    scaled, gives the second 130."""
    second = "".join(
        f"set {FOE2 + off:x} {v:x} " for off, v in (FOE_SET | {20: 87, 24: 87}).items()
    )
    third = "".join(
        f"set {FOE3 + off:x} {v:x} " for off, v in (FOE_SET | {20: 100, 24: 100}).items()
    )
    script = (
        second
        + f"spawn {FOE2:x} {FOE_RECORD:x} get {FOE2 + 20:x} get {FOE2 + 148:x} "
        + third
        + f"set {OTHER_RECORD + 36:x} 64 spawn {FOE3:x} {OTHER_RECORD:x} get {FOE3 + 20:x} "
        + f"get {OTHER_RECORD + 36:x} set 803475cc 6 safe get {FOE_RECORD + 36:x} get {OTHER_RECORD + 36:x}"
    )
    out, err = difficulty(driver, tmp_path, "preset=hard", script=script)
    words = re.findall(r"^([0-9A-F]{8})=([0-9A-F]{8})$", out, re.M)
    got = [(a, int(v, 16)) for a, v in words]
    assert (f"{FOE2 + 20:08X}", 87) in got, out  # made scaled, left
    assert (f"{FOE2 + 148:08X}", 37 << 16 | 20) in got, out  # Attack scaled as ever
    assert (f"{FOE3 + 20:08X}", 150) in got and (f"{OTHER_RECORD + 36:08X}", 150) in got, out
    assert got[-2:] == [(f"{FOE_RECORD + 36:08X}", 58), (f"{OTHER_RECORD + 36:08X}", 100)], out


@needs_cc
def test_difficulty_leaves_a_record_no_longer_holding_its_value(driver, tmp_path):
    """A record whose max HP changed since the spawn (the map freed and reused
    the memory) is not written when the battle ends."""
    script = f"set {FOE_RECORD + 36:x} 1234 set 803475cc 6 safe get {FOE_RECORD + 36:x}"
    out, err = difficulty(driver, tmp_path, "preset=hard", script=script)
    assert re.findall(rf"^{FOE_RECORD + 36:08X}=([0-9A-F]{{8}})$", out, re.M)[-1] == "00001234", out
    assert (
        f"record {FOE_RECORD:08X}: max HP 4660, not this mod's 87 any more; left as it is"
        in mod_lines(err, "difficulty")
    ), err


@needs_cc
def test_difficulty_defense_and_magdef_each_take_their_own_number(driver, tmp_path):
    out, err = difficulty(driver, tmp_path, "defense=2 magdef=0.5")
    assert spawned(out, FOE, FOE_SET) == want(58, 10, 15, 30, 40, 10), (out, err)
    assert spawned(out, FOE_RECORD, RECORD_SET) == RECORD_SET, out  # hp at 1: the record untouched


@needs_cc
def test_difficulty_a_number_wins_over_its_preset(driver, tmp_path):
    out, err = difficulty(
        driver, tmp_path, "preset=hard hp=4 attack=1 rewards=0", script="rewards 103 10 3"
    )
    assert mod_lines(err, "difficulty")[0] == (
        "hard: hp x4.00 attack x1.00 defense x1.00 magdef x1.00 speed x1.00 rewards x0.00"
    ), err
    assert spawned(out, FOE, FOE_SET) == want(232, 10, 15, 30, 20, 20), out
    assert "rewards 103 10 3 -> 0 0 0" in out, out
    # and on a preset of normal, a number alone is enough to register
    out, err = difficulty(driver, tmp_path / "speed", "speed=2")
    assert spawned(out, FOE, FOE_SET) == want(58, 10, 30, 30, 20, 20), out


@needs_cc
def test_difficulty_holds_each_field_to_its_limits(driver, tmp_path):
    # HP 1 at x0.25 stays 1; Attack 30000 at x4 is held to 32767; Defense 0 at x2 stays 0
    fields = {20: 1, 24: 1, 148: 30000 << 16, 240: 15 << 16 | 30000, 244: 0 << 16 | 20}
    out, err = difficulty(driver, tmp_path, "hp=0.25 attack=4 defense=2", fields)
    got = spawned(out, FOE, FOE_SET)
    assert got[20] == 1 and got[24] == 1, out
    assert got[148] == 32767 << 16 and got[240] == 15 << 16 | 32767, out
    assert got[244] == 0 << 16 | 20, out  # base Defense 0 -> 0; MagDef untouched


@needs_cc
def test_difficulty_rewards_round_down_and_hold_magic_exp(driver, tmp_path):
    out, err = difficulty(driver, tmp_path, "rewards=1.5", script="rewards 7 1 100 rewards 1 1 1")
    assert lines_of(out, "rewards") == ["rewards 7 1 100 -> 10 1 127", "rewards 1 1 1 -> 1 1 1"], (
        out
    )
    out, err = difficulty(driver, tmp_path / "half", "rewards=0.5", script="rewards 1 3 1")
    assert "rewards 1 3 1 -> 0 1 0" in out, out  # no floor of 1 on a reward


@needs_cc
def test_difficulty_and_boosts_chain_their_rewards_in_folder_order(driver, tmp_path):
    shipped(tmp_path, folder=BOOSTS)
    shipped(tmp_path, folder=DIFFICULTY)
    out, err = play(
        driver,
        tmp_path,
        "rewards 103 10 3",
        SOA_MOD_OPT="battle-boosts.exp=2 difficulty.preset=hard",
    )
    assert "loaded 2" in out, err
    assert "rewards 103 10 3 -> 257 12 3" in out, out  # 103 x2 = 206, x1.25 = 257.5 -> 257


@needs_cc
def test_battle_boosts_spec_mutations_fail(driver, tmp_path):
    """Two of the spec's mutations, kept as tests: without the damage clamp a
    blow knocks a party member out, and with the round's end leaving the
    poison bits, the game is left to fell the poisoned."""
    src = (BOOSTS / "mod.c").read_text(encoding="utf-8")
    clamp = "    if ((int32_t)value <= most) return value;\n"
    assert src.count(clamp) == 1
    shipped(tmp_path / "a", src.replace(clamp, "    return value;\n"), folder=BOOSTS)
    out, _ = play(
        driver,
        tmp_path / "a",
        BATTLE + "damage 999 9 0 80420000 0",
        SOA_MOD_OPT="battle-boosts.no_ko=1",
    )
    assert "damage 999 -> 999" in out, out  # the shipped mod gives 49

    clear = "        word &= ~(1u << slot);\n"
    assert src.count(clear) == 1
    shipped(tmp_path / "b", src.replace(clear, ""), folder=BOOSTS)
    out, _ = play(
        driver,
        tmp_path / "b",
        BATTLE + f"set {POISON_WORD:x} 1 roundend 1 get {POISON_WORD:x}",
        SOA_MOD_OPT="battle-boosts.no_ko=1",
    )
    assert f"{POISON_WORD:08X}=00000001" in out, out  # the shipped mod reads 0


@needs_cc
def test_difficulty_spec_mutations_fail(driver, tmp_path):
    """Two of the spec's mutations, kept as tests: a build that never puts the
    record back leaves it scaled after the battle, to be scaled again by the
    next; and one that scales the record at every spawn makes a second enemy
    of the kind from a record scaled twice over."""
    src = (DIFFICULTY / "mod.c").read_text(encoding="utf-8")
    restore = "            g_api->write32(g_rec[i].at + RECORD_HP_MAX, g_rec[i].was);\n"
    assert src.count(restore) == 1
    shipped(tmp_path / "a", src.replace(restore, ""), folder=DIFFICULTY)
    out, _ = play(
        driver,
        tmp_path / "a",
        "set 803475cc 7 safe "
        + made()
        + f"spawn {FOE:x} {FOE_RECORD:x} set 803475cc 6 safe get {FOE_RECORD + 36:x}",
        SOA_MOD_OPT="difficulty.preset=hard",
    )
    assert f"{FOE_RECORD + 36:08X}=00000057" in out, out  # 87 left; the shipped mod puts back 58

    seen = "if (g_rec[i].at == record) return 0;"
    assert src.count(seen) == 1
    never = "if (g_rec[i].at == record + 1u) return 0;"  # a record never found again
    shipped(tmp_path / "b", src.replace(seen, never), folder=DIFFICULTY)
    out, _ = play(
        driver,
        tmp_path / "b",
        "set 803475cc 7 safe "
        + made()
        + f"spawn {FOE:x} {FOE_RECORD:x} spawn {FOE:x} {FOE_RECORD:x} get {FOE_RECORD + 36:x}",
        SOA_MOD_OPT="difficulty.preset=hard",
    )
    assert f"{FOE_RECORD + 36:08X}=00000082" in out, (
        out
    )  # 58 -> 87 -> 130; the shipped mod stops at 87


@needs_cc
def test_difficulty_scales_the_next_battles_enemies_again(driver, tmp_path):
    """The record is put back when the battle ends and forgotten, so the next
    battle on the map scales its enemies from the game's value again: 87 each
    time, never 130 or 58."""
    again = (
        f"set 803475cc 6 safe set 803475cc 7 safe set {FOE + 20:x} 3a set {FOE + 24:x} 3a "
        + f"spawn {FOE:x} {FOE_RECORD:x} get {FOE + 20:x} get {FOE_RECORD + 36:x}"
    )
    out, err = difficulty(driver, tmp_path, "preset=hard", script=again)
    words = re.findall(r"^([0-9A-F]{8})=([0-9A-F]{8})$", out, re.M)
    assert words[-2:] == [
        (f"{FOE + 20:08X}", "00000057"),
        (f"{FOE_RECORD + 36:08X}", "00000057"),
    ], out


@needs_cc
def test_battle_boosts_full_spirit_again_after_try_again(driver, tmp_path):
    """Try again rebuilds the battle inside scene 7: the phase back to 0 and
    the round to 1, a new context's SP. Either re-arms the first round, so
    the retried battle starts full as well -- not only one after leaving the
    battle."""
    ctx_sp = f"get {BATTLE_CTX + 8:x} "
    out, err = boosts(
        driver,
        tmp_path,
        spirit_battle()
        + "setb 80347340 2 safe "  # round 2 under way, filled at its first safe point
        + f"set {BATTLE_CTX + 8:x} 20002 set 8034733c 0 safe "  # retried: phase 0 seen (the round alone below)
        + "set 8034733c 1 safe "  # the round still 2: the phase alone re-armed it
        + ctx_sp
        + f"set {BATTLE_CTX + 8:x} 10001 setb 80347340 3 safe setb 80347340 1 safe "  # the round drops alone
        + ctx_sp,
        "full_spirit=1",
    )
    assert re.findall(rf"^{BATTLE_CTX + 8:08X}=([0-9A-F]{{8}})$", out, re.M) == [
        "000A000A",
        "000A000A",
    ], out
    assert [x for x in mod_lines(err) if x.startswith("full spirit: SP")] == [
        "full spirit: SP 3 -> 10 of 10",
        "full spirit: SP 2 -> 10 of 10",
        "full spirit: SP 1 -> 10 of 10",
    ], err


@needs_cc
def test_battle_boosts_no_ko_stands_down_where_losing_carries_the_story_on(driver, tmp_path):
    """Defeat condition 2 (ctx+4; event battle 26 at the home base, where Run
    is not offered either) carries the story on after a loss: the assist
    lets the party fall there, says so once, and guards a battle with Try
    again (1) as any other."""
    battle_26 = f"set 80347390 {BATTLE_CTX:x} set {BATTLE_CTX + 4:x} 201000a "  # defeat 2, escape 1, max SP 10
    try_again = f"set {BATTLE_CTX + 4:x} 100000a "
    out, err = boosts(
        driver,
        tmp_path,
        BATTLE
        + battle_26
        + "damage 999 9 0 80420000 0 effect 0 5 0 "
        + f"set {POISON_WORD:x} 1 roundend 1 get {POISON_WORD:x} damage 998 9 0 80420000 0 "
        + try_again
        + "damage 999 9 0 80420000 0",
        "no_ko=1",
    )
    assert lines_of(out, "damage") == [
        "damage 999 -> 999",
        "damage 998 -> 998",
        "damage 999 -> 49",
    ], out
    assert "effect 5 0 -> 5 0" in out and "cancelled" not in out, out
    assert f"{POISON_WORD:08X}=00000001" in out, out  # left for the game
    said = "no knock-outs stands down for this battle: losing it carries the story on (defeat condition 2)"
    assert mod_lines(err).count(said) == 1, err


# --------------------------------------------------------------------------
# M20: drawing over the picture (docs/specs/mod-overlay.md) on the fake guest
# --------------------------------------------------------------------------

DRAWS = r"""
#include "soa_mod.h"
#include <stdio.h>
static const SoaModApi* A;
static int g_frames;
static void frame_end(void* u)
{
    char line[48];
    int i, ok = 0;
    (void)u;
    g_frames++;
    if (g_frames == 1) {
        A->draw_rect(10, 20, 100, 8, 0x20C040FFu);
        A->draw_text(10, 30, 2, 0xFFFFFFFFu, "HP 58/58");
    }
    if (g_frames == 2) A->draw_rect(0, 0, 640, 480, 0x00000080u);
    /* frame 3 draws nothing, and clears the overlay */
    if (g_frames == 4) {
        for (i = 0; i < 300; i++) ok += A->draw_rect(i, 0, 1, 1, 0xFFFFFFFFu);
        snprintf(line, sizeof line, "drew %d of 300", ok);
        A->log(line);
    }
}
static uint32_t damage(void* u, uint32_t v, uint32_t b, uint32_t a, uint32_t t, uint32_t e)
{
    (void)u; (void)b; (void)a; (void)t; (void)e;
    A->draw_text(0, 0, 1, 0xFF0000FFu, "hit");
    return v;
}
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char line[96];
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(draw_text)) return 1;
    snprintf(line, sizeof line, "from init %d; size 0 %d; size 9 %d; NULL %d", api->draw_rect(0, 0, 1, 1, 0xFFFFFFFFu),
             api->draw_text(0, 0, 0, 0xFFFFFFFFu, "x"), api->draw_text(0, 0, 9, 0xFFFFFFFFu, "x"),
             api->draw_text(0, 0, 1, 0xFFFFFFFFu, NULL));
    api->log(line);
    return api->on_frame_end(frame_end, 0) && api->on_damage(damage, 0) ? 0 : 1;
}
"""


def drawn_blocks(out: str) -> list[str]:
    return re.findall(r"^drawn\n(.*?)^end$", out, re.M | re.S)


@needs_cc
def test_m20_each_frame_s_draws_replace_the_last_and_a_frame_without_clears_them(driver, tmp_path):
    """Draws from on_frame_end and from a battle event make the frame's list;
    each frame end publishes it in place of the last; a frame with no draws
    clears the overlay; init and arguments out of range are refused; past a
    mod's room the rest is refused, said once."""
    source_mod(tmp_path, "draws", DRAWS)
    out, err = play(
        driver,
        tmp_path,
        "frame drawn frame drawn frame drawn damage 5 1 0 0 0 frame drawn frame drawn",
    )
    blocks = drawn_blocks(out)
    assert blocks[0] == "rect 10 20 100 8 20C040FF\ntext 10 30 2 FFFFFFFF HP 58/58\n", out
    assert blocks[1] == "rect 0 0 640 480 00000080\n", out
    assert blocks[2] == "", out
    lines = blocks[3].splitlines()
    assert lines[0] == "text 0 0 1 FF0000FF hit" and len(lines) == 256, (
        lines[:3],
        len(lines),
    )  # the event's, then 255
    assert blocks[4] == "", out
    assert "[mod] draws: from init 0; size 0 0; size 9 0; NULL 0" in err, err
    assert "[mod] draws: drew 255 of 300" in err, err
    assert err.count("past this frame's room to draw") == 1, err


@needs_cc
def test_m20_a_frame_end_with_no_mod_drawing_publishes_nothing_new(driver, tmp_path):
    """With nothing drawn, ever, the window has nothing to take."""
    mod(tmp_path, "patch-only")
    out, err = play(driver, tmp_path, "frame frame drawn")
    assert drawn_blocks(out) == [""], out


BATTLE_HP = ROOT / "examples" / "mods" / "battle-hp"


@needs_cc
def test_m20_the_example_draws_each_living_enemy_s_hp_in_a_battle(driver, tmp_path):
    """examples/mods/battle-hp: a panel, the track, what is left and the
    numbers for each living enemy, only in a battle; outside one its rows
    clear themselves."""
    shipped(tmp_path, folder=BATTLE_HP)
    script = (
        BATTLE
        + f"set {ENEMY4 + 24:x} 64 set 803475cc 7 frame drawn "
        + f"set {ENEMY4 + 28:x} 100 frame drawn "  # unconscious: its row goes
        + "set 803475cc 6 frame drawn"
    )
    out, err = play(driver, tmp_path, script)
    blocks = drawn_blocks(out)
    assert blocks[0] == (
        "rect 6 7 128 22 000000A0\nrect 10 10 120 6 502828FF\nrect 10 10 60 6 38D058FF\n"
        "text 10 18 1 FFFFFFFF 50/100\n"
    ), (out, err)
    assert blocks[1:] == ["", ""], out


SAFE_DRAW = r"""
#include "soa_mod.h"
static const SoaModApi* A;
static void safe(void* u) { (void)u; A->draw_rect(1, 2, 3, 4, 0x11223344u); }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(draw_text)) return 1;
    return api->on_safe_point(safe, 0) ? 0 : 1;
}
"""


RENDERER_DRAW = r"""
#include "soa_mod.h"
#include <stdio.h>
static const SoaModApi* A;
static int provide(void* u, uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h, const uint8_t* rgba, SoaImage* out)
{
    char line[48];
    (void)u; (void)hash; (void)fmt; (void)w; (void)h; (void)rgba; (void)out;
    snprintf(line, sizeof line, "from the provider %d", A->draw_rect(0, 0, 8, 8, 0xFFFFFFFFu));
    A->log(line);
    return 0;
}
static void filter(void* u, float p[6], int orthographic)
{
    char line[48];
    (void)u; (void)p; (void)orthographic;
    snprintf(line, sizeof line, "from the filter %d", A->draw_text(0, 0, 1, 0xFFFFFFFFu, "x"));
    A->log(line);
}
static void frame_end(void* u) { (void)u; A->draw_rect(5, 6, 7, 8, 0x11223344u); }
SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    (void)version;
    A = api;
    if (api->size < SOA_MOD_HAS(draw_text)) return 1;
    return api->texture_provider(provide, 0) && api->projection_filter(filter, 0) && api->on_frame_end(frame_end, 0)
               ? 0 : 1;
}
"""


@needs_cc
def test_m20_the_renderer_s_callbacks_cannot_draw(driver, tmp_path):
    """A texture provider and a projection filter, which the renderer calls
    as often as the game changes a texture or the projection, may not draw:
    each draw from one is refused, and the frame end after each still draws,
    so neither leaves the refusal behind it."""
    source_mod(tmp_path, "renderer-draw", RENDERER_DRAW)
    out, err = play(driver, tmp_path, "tex 1234 4 4 frame drawn proj 0 1 0 1 0 1 0 frame drawn")
    assert "[mod] renderer-draw: from the provider 0" in err, err
    assert "[mod] renderer-draw: from the filter 0" in err, err
    assert drawn_blocks(out) == ["rect 5 6 7 8 11223344\n"] * 2, (out, err)


@needs_cc
def test_m20_draws_from_the_safe_point_alone_are_published_too(driver, tmp_path):
    """A mod with no frame-end callback and no patches takes mod_frame's
    early return; the frame end publishes its draws all the same."""
    source_mod(tmp_path, "safe-draw", SAFE_DRAW)
    out, err = play(driver, tmp_path, "safe frame drawn")
    assert drawn_blocks(out) == ["rect 1 2 3 4 11223344\n"], (out, err)


# --------------------------------------------------------------------------
# mods/battle-info (PLAN-GAMEPLAY-MODS R5, docs/specs/battle-info.md) on the
# fake guest: the battle laid out as for battle-boosts, drawn through M20
# --------------------------------------------------------------------------

INFO = ROOT / "mods" / "battle-info"
ORDER, CURSOR, ACTING, PHASE, ROUND = 0x803092F4, 0x80347335, 0x80347334, 0x8034733C, 0x80347340
IN_BATTLE = "set 803475cc 7 "


def info(driver, tmp_path, script: str, opts: str = "", **env) -> tuple[str, str]:
    shipped(tmp_path, folder=INFO)
    if opts:
        env["SOA_MOD_OPT"] = " ".join(f"battle-info.{o}" for o in opts.split())
    return play(driver, tmp_path, script, **env)


def order(*slots: int, cursor: int = 0) -> str:
    """The turn order as the game keeps it, slots ending at -1, and its cursor."""
    out = "".join(f"setb {ORDER + i:x} {s & 0xFF:x} " for i, s in enumerate([*slots, -1]))
    return out + f"setb {CURSOR:x} {cursor:x} "


def test_battle_info_is_shipped_and_built_by_link():
    import recompile

    srcs = {p.parent.relative_to(ROOT).as_posix() for p in recompile.mod_dll_sources()}
    assert "mods/battle-info" in srcs, srcs


@needs_cc
def test_battle_info_at_its_defaults_registers_nothing(driver, tmp_path):
    """Setup installs every folder of mods/: with every part off the mod
    registers nothing, and a battle frame draws nothing."""
    out, err = info(driver, tmp_path, IN_BATTLE + BATTLE + f"set {ENEMY4 + 24:x} 64 frame drawn")
    assert "loaded 1" in out, err
    assert mod_lines(err, "battle-info") == ["every part off: nothing registered"], err
    assert "[mod] battle-info registers" not in err, err
    assert drawn_blocks(out) == [""], out


@needs_cc
def test_battle_info_hp_draws_each_living_enemy_s_row(driver, tmp_path):
    """hp: a panel ending at y 470, then each enemy's letter, track, what is
    left and numbers, a row each, in game units; a change in the numbers
    logged as shown; nothing once the battle is decided (phase 8, Try
    again's options low and left); the fallen leave the rows (the rest close
    down); a boss's five digits widen the panel; outside a battle nothing."""
    enemy5 = 0x80420C00
    script = (
        IN_BATTLE
        + BATTLE
        + f"set {ACTORS + 20:x} {enemy5:x} set {enemy5 + 20:x} 28 set {enemy5 + 24:x} 28 "  # B, 40 of 40
        # the last battle's 7 still in the phase as this one begins: drawn all the same
        + f"set {PHASE:x} 7 set {ENEMY4 + 24:x} 64 frame drawn "
        + f"set {PHASE:x} 4 set {ENEMY4 + 20:x} 19 frame drawn "  # 25 of 100
        + f"set {PHASE:x} 8 frame drawn "  # lost: the game's Try again owns the screen
        + f"set {PHASE:x} 4 set {ENEMY4 + 28:x} 100 frame drawn "  # A knocked out: no row, B's moves down
        + f"set {enemy5 + 20:x} 2ee0 set {enemy5 + 24:x} 2ee0 frame drawn "  # B at 12000 of 12000
        + "set 803475cc 6 frame drawn"
    )
    out, err = info(driver, tmp_path, script, "hp=1")
    blocks = drawn_blocks(out)
    row_b = "rect 22 {y} 64 4 502828FF\nrect 22 {y} 64 4 38D058FF\ntext 92 {t} 1 FFFFFFFF {n}\n"
    assert blocks[0] == (
        "rect 7 439 148 34 00000090\ntext 10 442 1 FFFFFFFF A\nrect 22 445 64 4 502828FF\n"
        "rect 22 445 32 4 38D058FF\ntext 92 442 1 FFFFFFFF 50/100\n"
        "text 10 458 1 FFFFFFFF B\n" + row_b.format(y=461, t=458, n="40/40")
    ), (out, err)
    assert (
        "rect 22 445 16 4 38D058FF" in blocks[1] and "text 92 442 1 FFFFFFFF 25/100" in blocks[1]
    ), blocks[1]
    assert blocks[2] == "", blocks[2]
    assert blocks[3] == (
        "rect 7 455 148 18 00000090\ntext 10 458 1 FFFFFFFF B\n"
        + row_b.format(y=461, t=458, n="40/40")
    ), blocks[3]
    assert blocks[4] == (  # 11 cells of numbers, past the 9 the panel holds otherwise
        "rect 7 455 160 18 00000090\ntext 10 458 1 FFFFFFFF B\n"
        + row_b.format(y=461, t=458, n="12000/12000")
    ), blocks[4]
    assert blocks[5] == "", out
    shown = [x.split(": ", 1)[1] for x in mod_lines(err, "battle-info") if "shows" in x]
    assert shown == [
        "slot 4 shows 50/100",
        "slot 5 shows 40/40",
        "slot 4 shows 25/100",
        "slot 5 shows 12000/12000",
    ], err


@needs_cc
def test_battle_info_order_runs_from_the_cursor_and_leaves_the_fallen_out(driver, tmp_path):
    """order: from the cursor on, the slot acting in yellow, one cell between
    labels, right-aligned; the fallen left out, and the asleep (phase 3 passes
    over 0x6500); the slot at the cursor fallen in its own turn takes its
    yellow with it; nothing before phase 3; each order shown logged once."""
    script = (
        IN_BATTLE
        + BATTLE
        + order(0, 4, 1)
        + f"set {PHASE:x} 2 frame drawn "  # the order not set yet
        + f"set {PHASE:x} 4 frame drawn "
        + f"setb {CURSOR:x} 1 frame drawn "
        + f"set {PARTY1 + 28:x} 100 frame drawn "  # P2 knocked out
        + f"set {PARTY1 + 28:x} 0 set {ENEMY4 + 28:x} 100 frame drawn "  # A, acting, falls; P2 back
        + f"set {PARTY1 + 28:x} 400 frame drawn"  # P2 asleep
    )
    out, err = info(driver, tmp_path, script, "order=1")
    blocks = drawn_blocks(out)
    assert blocks[0] == "", out
    assert blocks[1] == (
        "rect 585 7 48 15 00000090\ntext 588 10 1 FFE060FF P1\ntext 606 10 1 FFFFFFFF A\n"
        "text 618 10 1 FFFFFFFF P2\n"
    ), blocks[1]
    assert blocks[2] == (
        "rect 603 7 30 15 00000090\ntext 606 10 1 FFE060FF A\ntext 618 10 1 FFFFFFFF P2\n"
    ), blocks[2]
    assert blocks[3] == "rect 621 7 12 15 00000090\ntext 624 10 1 FFE060FF A\n", blocks[3]
    assert blocks[4] == "rect 615 7 18 15 00000090\ntext 618 10 1 FFFFFFFF P2\n", blocks[4]
    assert blocks[5] == "", blocks[5]
    orders = [x.split(": ", 1)[1] for x in mod_lines(err, "battle-info") if ": order " in x]
    assert orders == ["order P1 A P2", "order A P2", "order A", "order P2"], err


@needs_cc
def test_battle_info_log_says_what_each_change_was(driver, tmp_path):
    """log: a blow with its striker, a drop at the round's end with none
    (the slot that acted last is not its striker), a heal, a knock-out, an
    escape and a new round, each a line drawn and a line in the port's log;
    five on screen, the oldest dropped."""
    script = (
        IN_BATTLE
        + BATTLE
        + f"setb {ROUND:x} 1 set {PHASE:x} 4 setb {ACTING:x} 0 frame "  # what is there: nothing logged
        + f"set {ENEMY4 + 20:x} 22 frame "  # P1 strikes A: 50 -> 34
        # the round's end, P1 still in the acting byte: poison takes 5 of P2, A heals 8
        + f"set {PHASE:x} 6 set {PARTY1 + 20:x} 2d set {ENEMY4 + 20:x} 2a frame "
        + f"set {PARTY1 + 28:x} 100 frame "  # P2 down
        + f"setb {ROUND:x} 2 frame "
        + f"set {ENEMY4 + 28:x} 2000 frame "  # A escapes
        + f"set {PHASE:x} 4 setb {ACTING:x} 4 set {PARTY0 + 20:x} 2e frame drawn"  # A strikes P1: 4
    )
    out, err = info(driver, tmp_path, script, "log=1")
    said = [x.split(": ", 1)[1] for x in mod_lines(err, "battle-info") if x.startswith("frame ")]
    assert said == [
        "P1 > A -16",
        "P2 -5",
        "A +8",
        "P2 down",
        "round 2",
        "A fled",
        "A > P1 -4",
    ], err
    block = drawn_blocks(out)[0].splitlines()
    lines = [x.split(" ", 5)[5] for x in block if x.startswith("text ")]
    assert lines == ["A +8", "P2 down", "round 2", "A fled", "A > P1 -4"], out  # the first dropped
    # the panel as wide as the longest line, 9 cells, against the right edge, ending at y 470
    assert block[0] == "rect 573 422 60 51 00000090", block
    assert [x.split(" ")[1:3] for x in block[1:]] == [
        ["576", str(425 + 9 * i)] for i in range(5)
    ], block


@needs_cc
def test_battle_info_starts_the_log_afresh_when_a_battle_begins_again(driver, tmp_path):
    """Try again rebuilds the battle in scene 7, its phase back to 0: the
    log's lines go, and the rebuilt actors' HP is no blow or heal."""
    script = (
        IN_BATTLE
        + BATTLE
        + f"set {PHASE:x} 4 setb {ACTING:x} 0 frame set {ENEMY4 + 20:x} 22 frame drawn "
        + f"set {PHASE:x} 0 set {ENEMY4 + 20:x} 32 frame drawn"
    )
    out, err = info(driver, tmp_path, script, "log=1")
    blocks = drawn_blocks(out)
    assert "P1 > A -16" in blocks[0] and blocks[1] == "", out
    said = [x.split(": ", 1)[1] for x in mod_lines(err, "battle-info") if x.startswith("frame ")]
    assert said == ["P1 > A -16"], err


@needs_cc
def test_battle_info_size_scales_every_part(driver, tmp_path):
    """size 2: the text at size 2, the rows twice as tall, the bar 80 units
    (48 + 16 a size, so the rows leave the log its corner at size 3), both
    panels ending at y 470, the log's as wide as its longest line and
    against the right edge."""
    script = (
        IN_BATTLE
        + BATTLE
        + f"set {ENEMY4 + 24:x} 64 set {PHASE:x} 4 setb {ACTING:x} 0 frame "
        + f"set {ENEMY4 + 20:x} 22 frame drawn"  # P1 strikes A: 50 -> 34
    )
    out, err = info(driver, tmp_path, script, "hp=1 log=1 size=2")
    assert drawn_blocks(out)[0] == (
        "rect 7 443 242 30 00000090\ntext 10 446 2 FFFFFFFF A\nrect 34 452 80 8 502828FF\n"
        "rect 34 452 27 8 38D058FF\ntext 126 446 2 FFFFFFFF 34/100\n"
        "rect 507 449 126 24 00000090\ntext 510 452 2 FFFFFFFF P1 > A -16\n"
    ), out
