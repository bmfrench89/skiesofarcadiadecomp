"""The setup window (specs/distribution.md R4): tools/setup/setup.c.

Setup.exe --check runs the checks the window runs before anything is written,
for its own folder or --root's, and exits with what they found: a path the
port's ANSI calls cannot spell, one too long for the package's deepest file,
Program Files, a package not all extracted (Setup.exe opened from inside the
zip), a folder it cannot write, and a disc image in a format the build does
not read, each refused in words with the way out. The exe comes from
tools/package.py's own build, with llvm-mingw and the manifest; two builds of
one source are one file. These skip, saying why, without llvm-mingw or off
Windows. What no test here reaches -- the window, its build and Play with no
console window -- is FINDINGS "R4"'s run.

R5c (specs/android-sysroot.md 1.3) adds the Android box, and three windows
onto it: --show-build prints the command line Build would start, --bar reads
a run's [build] lines on stdin and prints where each puts the bar, then the
status the window would end on, and --assume-free sets the free space
--check sees. The recorded runs below are written from the lines
player_build.py and recompile.py print (that spec's 6.1); FINDINGS "R5c"'s
run is the window itself, building both from a real disc.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import package  # noqa: E402
import player_build  # noqa: E402
from soa import toolchain  # noqa: E402

SETUP_C = ROOT / "tools" / "setup" / "setup.c"
# setup.c's CHECK_* in order: its exit codes
CHECKS = [
    "OK",
    "PATH",
    "PROGRAM_FILES",
    "WRITE",
    "SPACE",
    "SMART_APP_CONTROL",
    "FORMAT",
    "INCOMPLETE",
    "LONG",
]
# setup.c's PACKAGE: what it looks for to know the package was all extracted
PACKAGE = [
    "python/python.exe",
    "source/tools/player_build.py",
    "toolchain/bin/x86_64-w64-mingw32-clang.exe",
    # R5b: bionic's sources, which a package's Android build is made from
    "source/vendor/android-sysroot-src/libc/arch-common/bionic/crtbegin_so.c",
]
DEEPEST = 100  # setup.c's SETUP_DEEPEST when package.py does not say


def test_the_lists_here_are_setup_cs():
    text = SETUP_C.read_text(encoding="utf-8")
    enum = re.search(r"enum \{\s*(CHECK_OK.*?)\}", text, re.S).group(1)
    assert [c.strip().removeprefix("CHECK_") for c in enum.split(",") if c.strip()] == CHECKS
    files = re.search(r"PACKAGE\[\] = \{(.*?)\};", text, re.S).group(1)
    assert [f.replace("\\\\", "/") for f in re.findall(r'L"([^"]*)"', files)] == PACKAGE
    assert f"#define SETUP_DEEPEST {DEEPEST}" in text
    # R5c: the space Setup asks for the phone's build is the build's own
    mib = re.search(r"#define ANDROID_FREE \((\d+)ull << 20\)", text).group(1)
    assert int(mib) << 20 == player_build.ANDROID_FREE


def test_package_leaves_room_for_the_deepest_file(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b.txt").write_text("x", encoding="utf-8")
    # never less than what a build writes under it: the sysroot's deepest
    # header under source/vendor (R5b)
    assert package.deepest(tmp_path) == package.BUILD_DEEPEST == 87
    deep = tmp_path / ("d" * 30) / ("e" * 30)
    deep.mkdir(parents=True)
    (deep / ("f" * 40 + ".h")).write_text("x", encoding="utf-8")
    assert package.deepest(tmp_path) == 30 + 1 + 30 + 1 + 42


def lay_out(folder: Path, exe: Path, skip: str = "") -> Path:
    """A package's folder as Setup.exe sees it: itself and PACKAGE's files."""
    folder.mkdir(parents=True, exist_ok=True)
    for rel in PACKAGE:
        if rel != skip:
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(b"")
    return Path(shutil.copy(exe, folder / "Setup.exe"))


@pytest.fixture(scope="module")
def setup_exe(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Setup.exe runs on Windows")
    if toolchain.compiler_path(toolchain.MINGW) is None:
        pytest.skip("no llvm-mingw (python tools/fetch_mingw.py)")
    built = package.build_setup(tmp_path_factory.mktemp("build") / "Setup.exe")
    return lay_out(tmp_path_factory.mktemp("package"), built)


def check(exe: Path, *args: str) -> tuple[str, str]:
    proc = subprocess.run([str(exe), "--check", *args], capture_output=True, timeout=60)
    return CHECKS[proc.returncode], proc.stdout.decode("utf-8")


def test_a_whole_package_in_a_plain_folder_passes(setup_exe):
    before = sorted(setup_exe.parent.rglob("*"))
    assert check(setup_exe) == ("OK", "ready\n")
    assert sorted(setup_exe.parent.rglob("*")) == before  # the write probe is gone


def test_setup_opened_from_inside_the_zip_says_to_extract_it(setup_exe, tmp_path):
    alone = tmp_path / "Temp1_soa-windows-x64.zip"  # where Explorer runs a file from a zip
    alone.mkdir()
    code, words = check(Path(shutil.copy(setup_exe, alone / "Setup.exe")))
    assert (
        code == "INCOMPLETE" and "python\\python.exe is missing" in words and "Extract All" in words
    )
    for n, rel in enumerate(PACKAGE):  # each one missing is seen
        exe = lay_out(tmp_path / f"without{n}", setup_exe, skip=rel)
        code, words = check(exe)
        assert code == "INCOMPLETE" and rel.replace("/", "\\") in words, rel


def test_a_path_the_ansi_calls_cannot_spell_is_refused(setup_exe, tmp_path):
    folder = tmp_path / "Skïes"
    code, words = check(lay_out(folder, setup_exe))
    assert code == "PATH" and str(folder) in words and "C:\\Games\\Skies" in words


def test_a_path_too_long_for_the_deepest_file_is_refused(setup_exe):
    room = 260 - 1 - DEEPEST  # MAX_PATH, the separator, the deepest file
    code, words = check(setup_exe, "--root", "C:\\" + "a" * (room - 3))
    assert code == "LONG" and f"{room} letters long" in words
    assert (
        check(setup_exe, "--root", "C:\\" + "a" * (room - 4))[0] == "INCOMPLETE"
    )  # one shorter fits


def test_program_files_is_refused_by_the_shells_own_answer(setup_exe):
    # Windows sets the ProgramFiles variable afresh in each process, so these
    # are the folders themselves; the check comes before the package's, and
    # the short name is read long (it must exist for that, as Setup's does)
    x64, x86 = os.environ["PROGRAMW6432"], os.environ["PROGRAMFILES(X86)"]
    for folder in (x64 + r"\Skies", x86 + r"\Skies", r"C:\PROGRA~1"):
        code, words = check(setup_exe, "--root", folder)
        assert code == "PROGRAM_FILES" and "Program Files" in words, folder
    assert check(setup_exe, "--root", x64 + "2")[0] != "PROGRAM_FILES"  # a prefix is not inside


def test_a_folder_it_cannot_write_is_refused(setup_exe, tmp_path):
    lay_out(tmp_path, setup_exe)
    user = os.environ["USERNAME"]
    subprocess.run(
        ["icacls", str(tmp_path), "/deny", f"{user}:(WD,AD)"], check=True, capture_output=True
    )
    try:
        code, words = check(setup_exe, "--root", str(tmp_path))
    finally:
        subprocess.run(
            ["icacls", str(tmp_path), "/remove:d", user], check=True, capture_output=True
        )
    assert code == "WRITE" and str(tmp_path) in words
    # the mutation: the same folder, allowed again
    assert check(setup_exe, "--root", str(tmp_path))[0] == "OK"


def test_a_format_the_build_cannot_read_names_dolphins_converter(setup_exe):
    for name in ("game.iso", "game.GCM", "game.rvz"):
        assert check(setup_exe, "--disc", name)[0] == "OK", name
    for name in ("game.wbfs", "game.ciso", "game.nkit.gcz", "game"):
        code, words = check(setup_exe, "--disc", name)
        assert code == "FORMAT" and "Convert File" in words, name


def test_one_source_builds_one_setup_exe(setup_exe, tmp_path):
    again = package.build_setup(tmp_path / "Setup.exe")
    assert again.read_bytes() == setup_exe.read_bytes()
    data = setup_exe.read_bytes()
    assert b"Microsoft.Windows.Common-Controls" in data and b'level="asInvoker"' in data


def test_the_console_flag_is_what_starts_python_and_the_game():
    # the run in FINDINGS "R4" saw a console window for each when the flag was 0
    text = SETUP_C.read_text(encoding="utf-8")
    starts = re.findall(r"CreateProcessW\((.*?)\)\)?\s*[{;]", text, re.S)
    assert len(starts) == 2 and all("NO_CONSOLE" in s for s in starts)
    assert "#define NO_CONSOLE CREATE_NO_WINDOW" in text


# ---- R5c: the Android box ----------------------------------------------------

UNITS = ["dispatch.c", *(f"chunk_{n:03}.c" for n in range(18))]  # recompile's 19
REFUSAL = 'this is not the North American GameCube release (GEAE8P); game.iso is GALE01 "SUPER SMASH BROS"'


def one_target(pre: str = "") -> list[str]:
    """One target's lines as player_build relays recompile's: its record moved,
    the translation, each unit, the link (the phone's stubs first), done."""
    lines = [
        f"[build] {pre}translate: no record of the last translation",
        f"[build] {pre}translate",
    ]
    lines += [f"[build] {pre}{n}/{len(UNITS)} {unit}" for n, unit in enumerate(UNITS, 1)]
    if pre:
        lines += [f"[build] android stub {lib}" for lib in ("libc.so", "libm.so", "libdl.so")]
        lines += ["[build] android stub libsoa_runtime.so", "[build] android link"]
        return [*lines, "[build] android done libsoa_game.so sha256 " + "cd" * 32]
    lines += [
        "[build] link",
        "[build] mod autotext",
        "[build] mod coop",
        "[build] mod encounter-rate",
    ]
    return [*lines, "[build] done soa.exe sha256 " + "ab" * 32]


def first_run(android: bool = True) -> list[str]:
    """A package's first run, as player_build prints it: the check, the
    phone's sysroot built from the package's sources, the extraction, then
    soa.exe and the phone's library."""
    lines = ["[build] check"]
    if android:
        lines += [
            "[build] android sysroot",
            "  44 of 44 bionic files the build reads, at 06356e41 (android-17.0.0_r1), are as pinned",
        ]
    lines += ["[build] extract", *one_target()]
    return [*lines, *one_target("android ")] if android else lines


def show_build(exe: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run([str(exe), "--show-build", *args], capture_output=True, timeout=60)
    return proc.returncode, proc.stdout.decode("utf-8").strip()


def bar(exe: Path, lines: list[str], *args: str) -> tuple[list[tuple[int, str]], str]:
    """--bar over a recorded run: (position, line) for each line that moved
    the bar, then the status the window would end on."""
    feed = "".join(f"{line}\n" for line in lines).encode("utf-8")
    proc = subprocess.run([str(exe), "--bar", *args], input=feed, capture_output=True, timeout=60)
    assert proc.returncode == 0
    out = proc.stdout.decode("utf-8").replace("\r\n", "\n").split("\n")
    rows = []
    while out and out[0].startswith("bar "):
        _, pos, line = out.pop(0).split(" ", 2)
        rows.append((int(pos), line))
    assert out and out[0].startswith("status "), out
    return rows, "\n".join(out).removeprefix("status ").strip()


def test_the_android_box_adds_both_targets(setup_exe):
    disc = "C:\\Games\\Skies\\game.rvz"
    code, ticked = show_build(setup_exe, "--disc", disc, "--android")
    assert code == 0 and ticked.endswith(" --target windows --target android-arm64")
    code, plain = show_build(setup_exe, "--disc", disc)
    assert code == 0 and "--target" not in plain
    assert plain == ticked.removesuffix(" --target windows --target android-arm64")
    # the package's python and build script, from the folder Setup is in
    command = re.fullmatch(
        r'"(?P<root>.+)\\python\\python\.exe" -X utf8 "(?P=root)\\source\\tools\\player_build\.py" '
        r'--disc "(?P<disc>[^"]+)" --root "(?P=root)"',
        plain,
    )
    assert command and command["disc"] == disc
    assert show_build(setup_exe)[0] == 1  # no disc, no command


def test_the_bar_never_goes_back_with_android(setup_exe):
    rows, status = bar(setup_exe, first_run(), "--android", "--exit", "0")
    positions = [pos for pos, _ in rows]
    assert positions == sorted(positions)  # the mutation: no phase map
    done = next(i for i, (_, line) in enumerate(rows) if line.startswith("[build] done soa.exe"))
    assert rows[done][0] == 60 and all(pos > 60 for pos, _ in rows[done + 1 :])
    assert rows[-1] == (100, first_run()[-1])
    units = [line for _, line in rows if re.match(r"\[build\] (android )?\d+/19 ", line)]
    assert len(units) == 2 * len(UNITS)  # every unit of both moves it
    # the folder holds no soa.exe, so not the built words; their row is below
    assert status.startswith("The build finished, but soa.exe is not in this folder")


def test_without_the_box_the_bar_is_r4s(setup_exe):
    rows, _ = bar(setup_exe, first_run(android=False), "--exit", "0")
    assert [pos for pos, _ in rows[:2]] == [2, 4]  # the check, the extraction
    assert [pos for pos, _ in rows] == sorted(pos for pos, _ in rows)
    assert rows[-1] == (100, first_run(android=False)[-1])
    # an Android line is not this run's: it moves nothing
    rows, _ = bar(setup_exe, ["[build] check", "[build] android 1/19 dispatch.c"], "--exit", "1")
    assert rows == [(2, "[build] check")]


def test_the_status_says_what_this_run_built(setup_exe, tmp_path):
    """One recorded run per row of 1.3's table, into a folder already holding
    a soa.exe, as a Rebuild's is: the status is this run's, never the
    folder's (the mutation: on_done by built())."""
    built = lay_out(tmp_path / "built", setup_exe)
    (built.parent / "soa.exe").write_bytes(b"")
    empty = lay_out(tmp_path / "empty", setup_exe)
    run, plain = first_run(), first_run(android=False)
    windows_done = run.index(next(line for line in run if line.startswith("[build] done soa.exe")))
    compile_failed = run.index("[build] 7/19 chunk_005.c")
    android_compile = run.index("[build] android 7/19 chunk_005.c")
    log = "build\\setup.log: send that file with any report."
    why = "the compile of chunk_005.c failed; the lines above say why"
    space = "the Android build needs about 384 MB free in C:\\Games\\Skies, and there are 120 MB: free some space and build again"
    rows = [
        # exit 0, both built: the built words, with what to put on the phone
        (
            built,
            "--android",
            0,
            run,
            "The game is built. Press Play to play here.\nFor your Android device: copy libsoa_game.so and "
            "extracted\\disc.iso from this folder to it, then open the SoA port app and pick each when it asks, "
            "libsoa_game.so first.",
        ),
        # without the box, R4's
        (
            built,
            "",
            0,
            plain,
            "The game is built. Press Play. From now on, soa.exe in this folder starts it too.",
        ),
        # exit 0 with no soa.exe made, or none left in the folder (Windows Security)
        (
            built,
            "--android",
            0,
            run[:windows_done],
            "The build finished, but soa.exe is not in this folder.",
        ),
        (empty, "--android", 0, run, "The build finished, but soa.exe is not in this folder."),
        # exit 2: the disc's refusal
        (
            built,
            "--android",
            2,
            ["[build] check", f"[build] refused: {REFUSAL}"],
            f"This disc image cannot be used: {REFUSAL}",
        ),
        # exit 1, the phone's build refused before the extraction: nothing built
        (
            built,
            "--android",
            1,
            ["[build] check", f"[build] android failed: {space}"],
            f"Nothing was built: {space}\nUntick the Android box to build for Windows alone.",
        ),
        # exit 1, soa.exe built and the phone's build stopped, with its reason or without one
        (
            built,
            "--android",
            1,
            [
                *run[:android_compile],
                f"  FAIL chunk_005.c: error: {why}",
                f"[build] android failed: {why}",
            ],
            f"soa.exe is built: press Play to play here. The Android build stopped: {why}",
        ),
        (
            built,
            "--android",
            1,
            [*run[: windows_done + 1], "Traceback (most recent call last):"],
            "soa.exe is built: press Play to play here. The Android build stopped: its log is below, and saved as",
        ),
        # exit 1 anywhere else: the build stopped, over the folder's old soa.exe too
        (
            built,
            "--android",
            1,
            [*run[:compile_failed], "  FAIL chunk_005.c: error: expected ';'", "[build] failed"],
            "The build stopped. Its log is below, and saved as",
        ),
        (
            built,
            "",
            1,
            [*plain[:compile_failed], "[build] failed"],
            "The build stopped. Its log is below",
        ),
    ]
    for exe, box, code, lines, words in rows:
        _, status = bar(exe, lines, *([box] if box else []), "--exit", str(code))
        assert status.startswith(words), (code, lines[-1], status)
        if status.startswith(
            (
                "The build stopped",
                "soa.exe is built: press Play to play here. The Android build stopped: its",
            )
        ):
            assert status.endswith(log), status


def test_a_built_folder_with_the_box_ticked_checks_the_android_space(setup_exe, tmp_path):
    exe = lay_out(tmp_path / "p", setup_exe)
    folder, mib = exe.parent, 1 << 20
    # not built: R4's 2 GB, and with the box the phone's 384 MB beside them
    assert check(exe, "--assume-free", str(1024 * mib))[0] == "SPACE"
    assert check(exe, "--assume-free", str(2100 * mib)) == ("OK", "ready\n")
    code, words = check(exe, "--android", "--assume-free", str(2100 * mib))
    assert code == "SPACE" and "need about 2.4 GB free here, and this drive has 2.1 GB" in words
    assert "untick the Android box" in words
    # built: the phone's alone, until its library is there too (the mutation:
    # the rule ignoring the box once soa.exe is built)
    (folder / "soa.exe").write_bytes(b"")
    assert check(exe, "--assume-free", str(120 * mib))[0] == "OK"
    code, words = check(exe, "--android", "--assume-free", str(120 * mib))
    assert code == "SPACE" and "need about 0.4 GB free here, and this drive has 0.1 GB" in words
    assert check(exe, "--android", "--assume-free", str(400 * mib))[0] == "OK"
    (folder / "libsoa_game.so").write_bytes(b"")
    assert check(exe, "--android", "--assume-free", str(120 * mib))[0] == "OK"
