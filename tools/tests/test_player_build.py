"""The player's build (specs/distribution.md R2).

A player's package holds no src/ or include/ (3.1), so its build leaves out
what uses them: recompile.py --no-decomp drops every binding runtime/
decomp_swap.c answers with decompiled code -- the game's own MSL then runs
translated -- builds no native unit, and links with SOA_NO_DECOMP, which
empties decomp_swap.c and has the self test say its comparison is skipped.
The bindings decomp_swap.c answers must be exactly the ones config/hle.txt
notes as decompiled, so neither can grow without the other.
"""

import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import player_build  # noqa: E402
import recompile  # noqa: E402
from soa import discfixture, toolchain  # noqa: E402
from soa.hle import load_hle  # noqa: E402


def noted_as_decompiled() -> set[int]:
    """hle.txt's entries whose note names a file under src/."""
    out = set()
    for line in (ROOT / "config" / "hle.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(0x[0-9A-Fa-f]{8})\s+\S+\s*#\s*src/", line)
        if m:
            out.add(int(m.group(1), 16))
    return out


def test_the_swapped_bindings_are_the_ones_hle_txt_notes_as_decompiled():
    swapped = recompile.decomp_bound()
    assert len(swapped) == 12
    assert swapped == noted_as_decompiled()
    assert swapped <= set(load_hle(ROOT / "config" / "hle.txt"))


def test_an_adapter_added_without_its_note_is_seen(tmp_path):
    swap = tmp_path / "decomp_swap.c"
    text = (ROOT / "runtime" / "decomp_swap.c").read_text(encoding="utf-8")
    swap.write_text(text + "\nvoid fn_80001234(CpuState* s) { (void)s; }\n", encoding="utf-8")
    assert recompile.decomp_bound(swap) != noted_as_decompiled()


def test_the_no_decomp_link_builds_no_native_unit_and_defines_soa_no_decomp():
    for p in (toolchain.MSVC, toolchain.MINGW):
        plain = recompile.link_plan(p, Path(p.out), ["src/sdk/msl/mem.c"], ["/Dmemset=dc_memset"])
        assert any("src/sdk/msl/mem.c" in cmd for cmd, _ in plain)
        player = recompile.link_plan(p, Path(p.out), [], [], defines=("/DSOA_NO_DECOMP=1",))
        link = next(cmd for cmd, cwd in player if cwd == Path("."))
        assert "/DSOA_NO_DECOMP=1" in link
        assert not any("src/" in a for cmd, _ in player for a in cmd)


def test_the_runtime_keeps_a_no_decomp_branch_where_it_names_decompiled_code():
    """decomp_swap.c is empty and the self test names its skip under
    SOA_NO_DECOMP; the twins it calls are then the plain fn_ names."""
    swap = (ROOT / "runtime" / "decomp_swap.c").read_text(encoding="utf-8")
    assert "#ifndef SOA_NO_DECOMP" in swap
    selftest = (ROOT / "runtime" / "selftest.c").read_text(encoding="utf-8")
    for addr in recompile.decomp_bound():
        assert f"#define recomp_fn_{addr:08X} fn_{addr:08X}" in selftest
    assert "a build without src/: the translated MSL runs" in selftest


# ---- tools/player_build.py: the disc's checks, never a stale gen/, and RVZ ----

EMBED = ROOT / "vendor" / "python-3.14.8-embed-amd64.zip"


@pytest.fixture(scope="module")
def fixture_disc(tmp_path_factory):
    return discfixture.build(tmp_path_factory.mktemp("disc") / "disc.iso")


def test_a_disc_of_another_game_is_refused_by_name(fixture_disc):
    with pytest.raises(
        player_build.Refused, match="not the North American GameCube release.*GTSE01"
    ):
        player_build.check_disc(fixture_disc.path, dol_sha1=fixture_disc.dol_sha1)


def test_an_executable_with_another_sha1_is_refused(fixture_disc):
    game = fixture_disc.game_id
    player_build.check_disc(fixture_disc.path, game_id=game, dol_sha1=fixture_disc.dol_sha1)
    with pytest.raises(
        player_build.Refused, match="executable is not the one this package was made"
    ):
        player_build.check_disc(fixture_disc.path, game_id=game, dol_sha1="0" * 40)


def test_an_image_that_is_not_a_disc_is_refused(tmp_path):
    junk = tmp_path / "holiday.iso"
    junk.write_bytes(bytes(range(256)) * 64)
    with pytest.raises(player_build.Refused, match="is not a GameCube disc image"):
        player_build.check_disc(junk, dol_sha1="0" * 40)


def test_a_disc_this_cannot_check_is_refused_not_warned(fixture_disc, monkeypatch, tmp_path):
    monkeypatch.setattr(player_build, "SOURCE", tmp_path)  # no config/ to read the hash from
    with pytest.raises(player_build.Refused, match="cannot check the disc's executable"):
        player_build.check_disc(fixture_disc.path, game_id=fixture_disc.game_id)


def test_a_refusal_is_a_build_line_and_exit_2(fixture_disc, tmp_path, capsys):
    assert player_build.main(["--disc", str(fixture_disc.path), "--root", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "[build] check" in out and "[build] refused: this is not the North American" in out
    assert not (tmp_path / "extracted").exists()


IDENTITY = {"package": "p" * 64, "compiler": "c" * 64, "cflags": "f" * 64, "sysroot": "s" * 64}


def stand_in(monkeypatch, source, identity=IDENTITY):
    """player_build with the disc's checks, extraction, the build itself and
    the installs stood in for, and its identity a constant, so no test here
    starts a compiler: the (target, retranslate) of each build asked for."""
    asked = []
    monkeypatch.setattr(player_build, "SOURCE", source)
    monkeypatch.setattr(player_build, "check_disc", lambda image: None)
    monkeypatch.setattr(player_build, "extract", lambda image, out: print("extracted"))
    monkeypatch.setattr(player_build, "install", lambda root, gen: "0" * 64)
    monkeypatch.setattr(player_build, "install_android", lambda root, gen, target: "1" * 64)
    monkeypatch.setattr(player_build, "identity", lambda target: dict(identity))

    def build(root_, gen, retranslate, target="windows"):
        asked.append((target, retranslate))
        return ""

    monkeypatch.setattr(player_build, "build", build)
    return asked


def run_main(monkeypatch, root, source, *extra):
    """player_build.main with stand_in's stand-ins: whether it asks the build
    to translate again."""
    asked = stand_in(monkeypatch, source)
    assert player_build.main(["--disc", "x.iso", "--root", str(root), *extra]) == 0
    return asked[0][1]


def test_a_changed_input_retranslates_and_an_unchanged_one_relinks(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source"
    for rel in player_build.BAKED:
        p = source / (rel if "." in Path(rel).name else rel + "/x.py")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rel, encoding="utf-8")
    root = tmp_path / "root"
    assert run_main(monkeypatch, root, source) is True  # no record: a first build
    assert "no record of the last translation" in capsys.readouterr().out
    assert run_main(monkeypatch, root, source) is False  # nothing moved: relink
    (source / "runtime" / "cpu.h").write_text("runtime/cpu.h, one byte on", encoding="utf-8")
    assert run_main(monkeypatch, root, source) is True
    assert "[build] translate: runtime/cpu.h" in capsys.readouterr().out
    # the mutation: without the check a changed cpu.h would only relink
    monkeypatch.setattr(player_build, "stale", lambda gen, now: [])
    (source / "runtime" / "cpu.h").write_text("runtime/cpu.h, two bytes on", encoding="utf-8")
    assert run_main(monkeypatch, root, source) is False


def test_setups_rebuild_translates_again_when_nothing_moved(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source"
    (source / "runtime").mkdir(parents=True)
    (source / "runtime" / "cpu.h").write_text("cpu.h", encoding="utf-8")
    root = tmp_path / "root"
    assert run_main(monkeypatch, root, source) is True
    assert run_main(monkeypatch, root, source) is False  # the record matches
    capsys.readouterr()
    assert run_main(monkeypatch, root, source, "--rebuild") is True  # 3.8: Rebuild retranslates
    assert "[build] translate: Rebuild asked for" in capsys.readouterr().out


def test_the_install_carries_the_shipped_mods_and_no_example(tmp_path):
    """recompile.py's GNU build puts every mod's library in gen/mods, the
    examples' among them; the install copies only the folders of mods/, so
    soa.ini's `mods = mods` never loads damage-double (R0's check, which
    doubles every battle's damage) or the lab. Installs made 2026-10-04 to 14
    carry map-log this way (build/player1, build/r5c/P). The mutation, every
    folder of gen/mods installed, installs damage-double and the lab too."""
    gen = tmp_path / "gen"
    for name in ("encounter-rate", "damage-double", "lab"):
        (gen / "mods" / name).mkdir(parents=True)
        (gen / "mods" / name / "mod.dll").write_bytes(b"MZ")
        (gen / "mods" / name / "mod.ini").write_text(f"id = {name}\n", encoding="utf-8")
    (gen / "soa.exe").write_bytes(b"MZ")
    root = tmp_path / "root"
    root.mkdir()
    player_build.install(root, gen)
    assert sorted(p.name for p in (root / "mods").iterdir()) == ["encounter-rate"]
    assert (root / "mods" / "encounter-rate" / "mod.dll").is_file()
    shipped = player_build.shipped_mods()
    assert {"autotext", "coop", "encounter-rate"} <= shipped, shipped
    assert not {"battle-tally", "damage-double", "lab", "map-log"} & shipped, shipped


def test_the_baked_digest_reads_crlf_as_lf(tmp_path):
    """R5-0: a checkout's line endings are not the commit's -- GitHub's
    Windows runner checks out with core.autocrlf on -- and baked= is made of
    this record, so the same files with CRLF endings make the same record,
    while a changed line still moves it."""
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for rel in player_build.BAKED:
        name = rel if "." in Path(rel).name else rel + "/x.py"
        text = f"{rel}\none\ntwo\n".encode()
        for tree, data in ((lf, text), (crlf, text.replace(b"\n", b"\r\n"))):
            (tree / name).parent.mkdir(parents=True, exist_ok=True)
            (tree / name).write_bytes(data)
    assert player_build.inputs_record(lf) == player_build.inputs_record(crlf)
    (crlf / "runtime" / "cpu.h").write_bytes(b"runtime/cpu.h\r\none\r\nthree\r\n")
    assert player_build.inputs_record(lf) != player_build.inputs_record(crlf)


# ---- R5b: Android targets (specs/android-sysroot.md 6.1) ---------------------

# The functions stand_in replaces, as this module found them, for the tests
# that run one of them for real.
ORIGINAL = type("Original", (), {})()
for _name in ("build", "install_android", "android_preflight", "ensure_sysroot"):
    setattr(ORIGINAL, _name, getattr(player_build, _name))


class FakeRecompile:
    """subprocess.Popen as recompile.py: these lines out, and a library made
    in --out, so build() and install_android() run as they do."""

    def __init__(self, lines, code=0):
        self.lines, self.code, self.cmds = lines, code, []

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        if "--out" in cmd and self.code == 0:
            out = Path(cmd[cmd.index("--out") + 1])
            (out / "libsoa_game.so").write_bytes(b"\x7fELF the phone's")
        proc = type("P", (), {})()
        proc.stdout = iter(f"{ln}\n" for ln in self.lines)
        proc.wait = lambda: self.code
        return proc


def test_an_android_target_builds_into_its_own_folder_and_says_so(monkeypatch, tmp_path, capsys):
    """recompile.py --cc android-arm64 into <root>/gen-android-arm64, no
    --reproducible (mingw's), every [build] line passed on as [build] android,
    and libsoa_game.so at the root's top, its sha256 in the done line."""
    stand_in(monkeypatch, tmp_path / "source")
    for name in ("build", "install_android"):
        monkeypatch.setattr(player_build, name, getattr(ORIGINAL, name))
    monkeypatch.setattr(player_build, "android_preflight", lambda root, targets: None)
    monkeypatch.setattr(player_build, "ensure_sysroot", lambda: None)
    fake = FakeRecompile(["[build] translate", "[build] 1/19 dispatch.c", "checked it"])
    monkeypatch.setattr(player_build.subprocess, "Popen", fake)
    root = tmp_path / "root"
    code = player_build.main(["--disc", "x.iso", "--root", str(root), "--target", "android-arm64"])
    out = capsys.readouterr().out
    assert code == 0, out
    (cmd,) = fake.cmds
    assert cmd[cmd.index("--cc") + 1] == "android-arm64"
    assert Path(cmd[cmd.index("--out") + 1]) == root / "gen-android-arm64"
    assert "--reproducible" not in cmd and "--no-decomp" in cmd
    lib = (root / "libsoa_game.so").read_bytes()
    assert lib == b"\x7fELF the phone's"
    digest = hashlib.sha256(lib).hexdigest()
    assert out.splitlines()[-4:] == [
        "[build] android translate",
        "[build] android 1/19 dispatch.c",
        "  checked it",
        f"[build] android done libsoa_game.so sha256 {digest}",
    ]
    assert not (root / "soa.exe").exists() and not (root / "gen").exists()
    # the emulator's library goes beside the phone's, under its own name
    player_build.main(["--disc", "x.iso", "--root", str(root), "--target", "android-x86_64"])
    assert (root / "libsoa_game-x86_64.so").exists()
    assert "android done libsoa_game-x86_64.so" in capsys.readouterr().out


def test_an_android_build_that_fails_names_the_unit(monkeypatch, tmp_path, capsys):
    stand_in(monkeypatch, tmp_path / "source")
    monkeypatch.setattr(player_build, "build", ORIGINAL.build)
    monkeypatch.setattr(player_build, "android_preflight", lambda root, targets: None)
    monkeypatch.setattr(player_build, "ensure_sysroot", lambda: None)
    lines = ["[build] 3/19 chunk_002.c", "  FAIL chunk_002.c: x.c:1:1: error: boom"]
    monkeypatch.setattr(player_build.subprocess, "Popen", FakeRecompile(lines, code=1))
    argv = ["--disc", "x.iso", "--root", str(tmp_path / "r"), "--target", "android-arm64"]
    assert player_build.main(argv) == 1
    assert (
        capsys.readouterr()
        .out.rstrip()
        .endswith(
            "[build] android failed: the compile of chunk_002.c failed; the lines above say why"
        )
    )
    monkeypatch.setattr(
        player_build.subprocess, "Popen", FakeRecompile(["[build] link", "ld.lld: error: x"], 1)
    )
    assert player_build.main(argv) == 1
    assert "[build] android failed: link failed (exit status 1)" in capsys.readouterr().out


def test_the_targets_run_in_order_after_one_check_and_one_preflight(monkeypatch, tmp_path, capsys):
    asked = stand_in(monkeypatch, tmp_path / "source")
    calls = []
    monkeypatch.setattr(
        player_build, "android_preflight", lambda root, targets: calls.append(list(targets))
    )
    monkeypatch.setattr(player_build, "ensure_sysroot", lambda: calls.append("sysroot"))
    argv = ["--disc", "x.iso", "--root", str(tmp_path / "root")]
    argv += ["--target", "android-x86_64", "--target", "windows", "--target", "android-x86_64"]
    assert player_build.main(argv) == 0
    assert asked == [("android-x86_64", True), ("windows", True)]  # each once, in order
    assert calls == [["android-x86_64", "windows"], "sysroot"]
    out = [ln for ln in capsys.readouterr().out.splitlines() if not ln.startswith("  ")]
    assert out == [
        "[build] check",
        "[build] extract",
        "extracting x.iso: nothing extracted yet",
        "extracted",
        "[build] android translate: no record of the last translation",
        "[build] android done libsoa_game-x86_64.so sha256 " + "1" * 64,
        "[build] translate: no record of the last translation",
        "[build] done soa.exe sha256 " + "0" * 64,
    ]
    # windows alone, the default, asks nothing of Android
    calls.clear()
    asked.clear()
    assert player_build.main(["--disc", "x.iso", "--root", str(tmp_path / "root")]) == 0
    assert calls == [] and asked == [("windows", False)]


def test_a_new_package_compiler_flags_or_sysroot_translates_again(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source"
    (source / "runtime").mkdir(parents=True)
    (source / "runtime" / "cpu.h").write_text("cpu.h", encoding="utf-8")
    root = tmp_path / "root"
    monkeypatch.setattr(player_build, "android_preflight", lambda root, targets: None)
    monkeypatch.setattr(player_build, "ensure_sysroot", lambda: None)
    argv = ["--disc", "x.iso", "--root", str(root), "--target", "android-arm64"]

    def run(identity):
        asked = stand_in(monkeypatch, source, identity)
        assert player_build.main(argv) == 0
        return asked[0][1]

    assert run(IDENTITY) is True  # the first build
    assert run(IDENTITY) is False  # nothing moved: relink
    capsys.readouterr()
    for key in IDENTITY:
        assert run({**IDENTITY, key: "0" * 64}) is True, key
        assert f"[build] android translate: {key}" in capsys.readouterr().out
        assert run(IDENTITY) is True  # and back again


def sysroot_package(monkeypatch, tmp_path, version="v1.2.3"):
    """A source/ whose vendor/android-sysroot-src holds a test table's files,
    and, when `version`, a package's VERSION."""
    import fetch_android_sysroot as fas

    files = {"libc/include/math.h": b"/* math */\n", "libc/private/x.h": b"/* x */\n"}
    rows = {
        p: fas.Source(len(d), role, "both", fas.sha256(d), fas.blob_id(d))
        for (p, d), role in zip(files.items(), ("ship", "build"), strict=True)
    }
    monkeypatch.setattr(fas, "SOURCES", rows)
    monkeypatch.setattr(fas, "SHIP", {"libc/include/math.h": "usr/include/math.h"})
    source = tmp_path / "source"
    for path, data in files.items():
        f = source / "vendor" / fas.CACHE / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    if version:
        (source / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    monkeypatch.setattr(player_build, "SOURCE", source)
    monkeypatch.setattr(player_build.toolchain, "mingw_clang", lambda: "clang.exe")
    monkeypatch.setattr(player_build.toolchain, "mingw_identity_problem", lambda exe: None)
    return source


def test_a_damaged_source_is_refused_before_the_extraction(monkeypatch, tmp_path, capsys):
    source = sysroot_package(monkeypatch, tmp_path)
    stand_in(monkeypatch, source)
    monkeypatch.setattr(player_build, "android_preflight", ORIGINAL.android_preflight)
    monkeypatch.setattr(player_build, "ensure_sysroot", ORIGINAL.ensure_sysroot)
    (source / "vendor" / "android-sysroot-src" / "libc/include/math.h").write_bytes(b"/* m */\n")
    root = tmp_path / "root"
    argv = ["--disc", "x.iso", "--root", str(root), "--target", "windows"]
    assert player_build.main([*argv, "--target", "android-arm64"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "[build] check",
        "[build] android failed: this package's Android files are not as it shipped them "
        "(libc/include/math.h): extract the package again, into a new folder",
    ]
    assert not root.exists()  # nothing written, Windows' target not begun


def test_a_damaged_tree_is_rebuilt_from_the_sources(monkeypatch, tmp_path, capsys):
    source = sysroot_package(monkeypatch, tmp_path)
    asked = stand_in(monkeypatch, source)
    monkeypatch.setattr(player_build, "android_preflight", ORIGINAL.android_preflight)
    monkeypatch.setattr(player_build, "ensure_sysroot", ORIGINAL.ensure_sysroot)
    (source / "vendor" / "ANDROID-SYSROOT.sha256").write_text("not this script's\n")
    ran = []

    def relay(cmd, prefix=""):
        ran.append(cmd)
        return 0, ["44 of 44 bionic files the build reads ... are as pinned"]

    monkeypatch.setattr(player_build, "relay", relay)
    argv = ["--disc", "x.iso", "--root", str(tmp_path / "root"), "--target", "android-arm64"]
    assert player_build.main(argv) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:5] == [
        "[build] check",
        "[build] android sysroot",
        "[build] extract",
        "extracting x.iso: nothing extracted yet",
        "extracted",
    ]
    tool = source / "tools" / "fetch_android_sysroot.py"
    assert ran == [[sys.executable, str(tool), "--offline"]]
    assert asked == [("android-arm64", True)]  # and the build went on

    # a build of it that fails stops before the extraction, in the player's words
    def broken(cmd, prefix=""):
        return 1, ["error: crtbegin_so.o for arm64 built here has sha256 0, pinned 1"]

    monkeypatch.setattr(player_build, "relay", broken)
    assert player_build.main(argv) == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "[build] android failed: the Android files could not be built here (crtbegin_so.o for "
        "arm64 built here has sha256 0, pinned 1): extract the package again, into a new "
        "folder, and send build\\setup.log with any report"
    )


def test_too_little_space_for_the_android_build_is_refused(monkeypatch, tmp_path):
    import collections

    sysroot_package(monkeypatch, tmp_path)
    measured = []
    free = {"bytes": 0}
    Usage = collections.namedtuple("Usage", "total used free")

    def disk_usage(path):
        measured.append(Path(path))
        return Usage(1 << 40, 0, free["bytes"])

    monkeypatch.setattr(player_build.shutil, "disk_usage", disk_usage)
    MIB, NEED = player_build.MIB, player_build.ANDROID_FREE
    root = tmp_path / "not" / "yet"  # measured at its nearest folder that exists
    free["bytes"] = NEED - 1
    why = player_build.android_preflight(root, ["windows", "android-arm64"])
    assert why == (
        f"the Android build needs about {NEED // MIB} MB free in {root}, and there are "
        f"{NEED // MIB - 1} MB: free some space and build again"
    )
    assert measured == [tmp_path]
    free["bytes"] = NEED
    assert player_build.android_preflight(root, ["android-arm64"]) is None
    # two targets need it twice; a folder whose translation is there needs less
    assert player_build.android_preflight(root, ["android-arm64", "android-x86_64"])
    root.mkdir(parents=True)
    monkeypatch.setattr(
        player_build, "_size", lambda f: NEED if f.name == "gen-android-arm64" else 0
    )
    free["bytes"] = NEED + player_build.RELINK_FREE
    assert player_build.android_preflight(root, ["android-arm64", "android-x86_64"]) is None
    free["bytes"] = player_build.RELINK_FREE - 1  # a relink still needs its own room
    assert "needs about 64 MB" in player_build.android_preflight(root, ["android-arm64"])


def test_a_package_says_extract_again_and_a_checkout_names_the_tool(monkeypatch, tmp_path):
    root = tmp_path / "root"
    for version in ("v1", ""):
        source = sysroot_package(monkeypatch, tmp_path / (version or "checkout"), version)
        (source / "vendor" / "android-sysroot-src" / "libc/private/x.h").unlink()
        why = player_build.android_preflight(root, ["android-arm64"])
        if version:
            assert why == (
                "this package's Android files are not as it shipped them (libc/private/x.h): "
                "extract the package again, into a new folder"
            )
        else:
            assert why == (
                "vendor/android-sysroot-src: libc/private/x.h: missing: "
                "python tools/fetch_android_sysroot.py fetches it"
            )
            assert "extract" not in why
    sysroot_package(monkeypatch, tmp_path / "p2")
    monkeypatch.setattr(player_build.toolchain, "mingw_clang", lambda: None)
    assert "this package's compiler is missing (toolchain\\bin\\clang.exe)" in (
        player_build.android_preflight(root, ["android-arm64"])
    )
    monkeypatch.setattr(player_build.toolchain, "mingw_clang", lambda: "clang.exe")
    monkeypatch.setattr(player_build.toolchain, "mingw_identity_problem", lambda e: "not it")
    monkeypatch.setattr(player_build.toolchain, "clang_id", lambda e: "clang version 19.1.0")
    assert player_build.android_preflight(root, ["android-arm64"]) == (
        "this package's compiler is not the one it shipped with (clang version 19.1.0): "
        "extract the package again, into a new folder"
    )
    sysroot_package(monkeypatch, tmp_path / "c2", "")
    monkeypatch.setattr(player_build.toolchain, "mingw_clang", lambda: None)
    assert player_build.android_preflight(root, ["android-arm64"]) == (
        "no llvm-mingw here: python tools/fetch_mingw.py fetches it"
    )


def test_the_package_version_is_the_staged_one(tmp_path):
    import package

    assert player_build.package_version(tmp_path) == "checkout"
    package.stage_source(tmp_path / "source", "v9.9-3-gabc1234")
    assert player_build.package_version(tmp_path / "source") == "v9.9-3-gabc1234"
    assert player_build.package_version(ROOT) == "checkout"  # a clone has none


def test_a_record_names_what_made_the_translation():
    """identity() for real: the package, the compiler's line and its flags,
    and for Android the sysroot, each as a sha256 (no compiler is started
    when there is none; its line is then empty)."""
    win = player_build.identity("windows")
    assert set(win) == {"package", "compiler", "cflags"}
    arm = player_build.identity("android-arm64")
    assert set(arm) == {"package", "compiler", "cflags", "sysroot"}
    assert win["package"] == hashlib.sha256(b"checkout").hexdigest()
    assert win["cflags"] != arm["cflags"]
    assert all(len(v) == 64 for v in (*win.values(), *arm.values()))


def test_an_rvz_reads_back_as_the_disc(fixture_disc, tmp_path):
    from soa.disc import Disc
    from soa.rvz import RVZ

    discfixture.write_rvz(fixture_disc.image, tmp_path / "disc.rvz")
    assert RVZ(str(tmp_path / "disc.rvz")).read(0, len(fixture_disc.image)) == fixture_disc.image
    with Disc(player_build.open_image(tmp_path / "disc.rvz")) as disc:
        assert disc.boot.game_id == fixture_disc.game_id


RVZ_SCRIPT = """
import sys, tempfile
from pathlib import Path
sys.path.insert(0, {tools!r})
from soa import discfixture
from soa.rvz import RVZ
d = Path(tempfile.mkdtemp())
fx = discfixture.build(d / "disc.iso")
discfixture.write_rvz(fx.image, d / "disc.rvz")
assert RVZ(str(d / "disc.rvz")).read(0, len(fx.image)) == fx.image
print("rvz ok")
"""


def test_the_embedded_python_reads_an_rvz_and_needs_its_zstd(tmp_path):
    """3.5: the package's python/ carries compression.zstd, which the RVZ
    reader needs; the same run with _zstd.pyd taken out fails."""
    if not EMBED.exists():
        pytest.skip(f"no {EMBED.name} in vendor/ (python tools/package.py stage fetches it)")
    with zipfile.ZipFile(EMBED) as z:
        z.extractall(tmp_path / "python")
    exe = tmp_path / "python" / "python.exe"
    script = RVZ_SCRIPT.format(tools=str(ROOT / "tools"))
    ok = subprocess.run([str(exe), "-c", script], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and "rvz ok" in ok.stdout, ok.stderr
    (tmp_path / "python" / "_zstd.pyd").unlink()
    gone = subprocess.run([str(exe), "-c", script], capture_output=True, text=True, check=False)
    assert gone.returncode != 0 and "zstd" in gone.stderr


def test_another_disc_image_or_rebuild_extracts_again(monkeypatch, tmp_path, capsys):
    """The distribution review's defect (2026-10-26): with extracted/disc.iso
    there, a player who picked another image and pressed Rebuild kept playing
    the first. A different file, by path or size, or Rebuild, extracts again;
    the same image does not. The mutation, the old test of disc.iso alone,
    keeps a's data after b is named."""
    source = tmp_path / "source"
    (source / "runtime").mkdir(parents=True)
    (source / "runtime" / "cpu.h").write_text("cpu.h", encoding="utf-8")
    root = tmp_path / "root"
    a, b = tmp_path / "a.iso", tmp_path / "b.iso"
    a.write_bytes(b"A" * 10)
    b.write_bytes(b"B" * 12)

    def extract(image, out):
        out.mkdir(parents=True, exist_ok=True)
        (out / player_build.IMAGE_NAME).write_bytes(image.read_bytes())
        print(f"extracted {image.name}")

    stand_in(monkeypatch, source)
    monkeypatch.setattr(player_build, "extract", extract)

    def run(disc, *extra):
        assert player_build.main(["--disc", str(disc), "--root", str(root), *extra]) == 0
        return [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("extract")]

    assert run(a) == [f"extracting {a}: nothing extracted yet", "extracted a.iso"]
    assert run(a) == []  # the same image: kept
    assert run(b) == [f"extracting {b}: the image is not the one extracted", "extracted b.iso"]
    assert run(b, "--rebuild") == [f"extracting {b}: Rebuild extracts again", "extracted b.iso"]
    b.write_bytes(b"C" * 20)  # another file at the same path
    assert run(b)[1:] == ["extracted b.iso"]
    assert (root / "extracted" / player_build.IMAGE_NAME).read_bytes() == b"C" * 20
    (root / "extracted" / player_build.SOURCE_RECORD).unlink()  # an install from before the record
    assert run(b) == [f"extracting {b}: no record of the image extracted", "extracted b.iso"]


def install_of(
    parent: Path,
    version: str,
    ini: str | None = "mods = mods\n",
    card: bytes | None = b"card",
    built: bool = True,
    age: int = 0,
) -> Path:
    """An earlier version's folder beside the new one, its files `age` hours old."""
    d = parent / f"soa-{version}-windows-x64"
    d.mkdir(parents=True)
    files = []
    if built:
        (d / "soa.exe").write_bytes(b"MZ")
    if ini is not None:
        (d / "soa.ini").write_text(ini, encoding="utf-8")
        files.append(d / "soa.ini")
    if card is not None:
        (d / "build" / "cards").mkdir(parents=True)
        (d / "build" / "cards" / "slotA.raw").write_bytes(card)
        files.append(d / "build" / "cards" / "slotA.raw")
    when = 1_800_000_000 - age * 3600
    for f in files:
        os.utime(f, (when, when))
    return d


def fresh_gen(tmp_path: Path) -> Path:
    gen = tmp_path / "gen"
    gen.mkdir(exist_ok=True)
    (gen / "soa.exe").write_bytes(b"MZ")
    return gen


def test_a_new_versions_folder_takes_the_last_installs_saves_and_settings(tmp_path, capsys):
    """The distribution review's other defect: a new version unzips to a
    folder of its own, and its first install began with no saves and the
    default soa.ini. Each is now copied from the newest built install beside
    it, and named; the old folder keeps its own. The mutation, no carry-over,
    leaves the default soa.ini and no card."""
    old = install_of(
        tmp_path, "v1", ini="mods = mods\nbattle-boosts.exp = 2\n", card=b"SAVES", age=5
    )
    install_of(tmp_path, "v0", ini="mods = mods\nseed = 7\n", card=b"OLDER", age=50)
    install_of(
        tmp_path, "v9", ini="unbuilt = 1\n", card=b"NEVER", built=False
    )  # Setup never built it
    root = tmp_path / "soa-v2-windows-x64"
    root.mkdir()
    player_build.install(root, fresh_gen(tmp_path))
    assert (root / "soa.ini").read_text(encoding="utf-8") == "mods = mods\nbattle-boosts.exp = 2\n"
    assert (root / "build" / "cards" / "slotA.raw").read_bytes() == b"SAVES"
    assert (old / "build" / "cards" / "slotA.raw").read_bytes() == b"SAVES"  # copied, not moved
    assert (
        "[build] carried over soa.ini from soa-v1-windows-x64, build/cards/slotA.raw from soa-v1-windows-x64"
        in capsys.readouterr().out
    )


def test_the_carry_over_never_writes_over_what_is_there(tmp_path, capsys):
    install_of(tmp_path, "v1", ini="mods = mods\nseed = 1\n", card=b"OLD", age=1)
    root = tmp_path / "soa-v2-windows-x64"
    (root / "build" / "cards").mkdir(parents=True)
    (root / "build" / "cards" / "slotA.raw").write_bytes(b"NEW")
    player_build.install(root, fresh_gen(tmp_path))
    assert (root / "build" / "cards" / "slotA.raw").read_bytes() == b"NEW"
    assert (root / "soa.ini").read_text(
        encoding="utf-8"
    ) == "mods = mods\nseed = 1\n"  # it had none
    capsys.readouterr()
    player_build.install(root, fresh_gen(tmp_path))  # a Rebuild in the same folder: nothing moves
    assert "carried over" not in capsys.readouterr().out
    # and a folder with no earlier install beside it gets the default soa.ini
    alone = tmp_path / "elsewhere" / "soa-v3-windows-x64"
    alone.mkdir(parents=True)
    player_build.install(alone, fresh_gen(tmp_path))
    assert "mods = mods" in (alone / "soa.ini").read_text(encoding="utf-8")
    assert not (alone / "build").exists()
