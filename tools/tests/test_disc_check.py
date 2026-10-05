"""tools/citest/disc_check.py (disc-layer I1): its two halves, and that each can fail.

The --log half needs no compiler: on a synthetic image, a log whose reads each
name the file the table puts at their offset passes, and one line naming the
neighbouring file, a read naming no file, a wrong count past a file's end, or
no read lines at all, are each refused. The fixture half builds runtime/disc.c
for the synthetic image and passes; the mutation that moves the image's file
table by four bytes fails it. That half needs MSVC, and skips without it (CI's
Linux legs run disc_check.py under gcc and clang themselves).
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "citest"))

import disc_check  # noqa: E402

from soa import discfixture, toolchain  # noqa: E402

CHECK = ROOT / "tools" / "citest" / "disc_check.py"


def line(off: int, length: int, name: str, past: int = 0) -> str:
    tail = f", {past} past its end" if past else ""
    return f"[disc] frame 7 read 0x{off:X} +{length} {name}{tail}"


@pytest.fixture
def fixture(tmp_path):
    return discfixture.build(tmp_path / "data" / "disc.iso")


def good_log(fx) -> list[str]:
    """A read of each file as the game's reader makes it, rounded up to 32."""
    out = []
    for path, off in fx.offsets.items():
        n = len(fx.files[path])
        r = (n + 31) & ~31
        out.append(line(off, r, path, r - n))
    return out


def check(tmp_path, fx, lines) -> int:
    log = tmp_path / "run.log"
    log.write_text("[boot] something else\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return disc_check.check_log(log, fx.path.parent)


def test_a_log_naming_each_files_own_reads_passes(tmp_path, fixture):
    assert check(tmp_path, fixture, good_log(fixture)) == 0


def test_a_read_naming_the_neighbouring_file_is_refused(tmp_path, fixture, capsys):
    lines = good_log(fixture)
    by_offset = sorted(fixture.offsets.items(), key=lambda kv: kv[1])
    (path, off), (neighbour, _) = by_offset[3], by_offset[4]
    lines.append(line(off, 32, neighbour))
    assert check(tmp_path, fixture, lines) == 1
    assert f"the table says {path}" in capsys.readouterr().out


def test_a_read_naming_no_file_and_a_wrong_overrun_are_refused(tmp_path, fixture):
    assert check(tmp_path, fixture, [*good_log(fixture), line(0, 32, "(no file)")]) == 1
    path, off = next(iter(fixture.offsets.items()))
    n = len(fixture.files[path])
    assert check(tmp_path, fixture, [line(off, n + 64, path, 1)]) == 1  # 64 past it, said 1
    assert check(tmp_path, fixture, [line(off, n + 64, path, 64)]) == 0


def test_a_log_with_no_reads_is_refused(tmp_path, fixture):
    assert check(tmp_path, fixture, []) == 1


needs_msvc = pytest.mark.skipif(toolchain.cl_path() is None, reason="no MSVC to build disc.c")


@needs_msvc
def test_disc_c_passes_on_the_fixture_and_the_mutation_fails_it(tmp_path):
    good = subprocess.run(
        [sys.executable, str(CHECK), "--out", str(tmp_path / "good")],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert good.returncode == 0, good.stdout[-3000:] + good.stderr[-2000:]
    assert ", 0 failed" in good.stdout and good.stdout.count("  refused ") == 10
    bad = subprocess.run(
        [sys.executable, str(CHECK), "--out", str(tmp_path / "bad"), "--mutate", "fst-offset"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert bad.returncode == 1 and "FAIL" in bad.stdout, bad.stdout[-3000:]
