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
