"""The player's package (specs/distribution.md R3): tools/package.py.

What a package may hold is guard.py --tree's to judge (test_guard.py); these
hold package.py to the same rules where it decides them: the licence texts it
copies come from the third-party folders the guard allows, the folders it
never copies are the decompiled code and every build output, and a stage
never lands on a folder that already holds something.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import guard  # noqa: E402
import package  # noqa: E402


def test_the_licences_come_from_the_third_party_folders():
    for rel in package.LICENSE_COPIES.values():
        assert guard.third_party(rel), rel


def test_a_package_never_copies_decompiled_code_or_build_output():
    assert {"src", "include", "gen", "extracted", "build"} <= package.NEVER


def test_the_pinned_downloads_are_named_by_exact_version():
    assert f"python-{package.PYTHON_VERSION}-embed-amd64.zip" == package.PYTHON_ZIP
    assert len(package.PYTHON_SHA256) == 64
    for url, pin in package.LICENSE_URLS.values():
        assert url.startswith("https://raw.githubusercontent.com/") and len(pin) == 64


def test_a_stage_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "keep.txt").write_text("the player's", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not empty"):
        package.stage(tmp_path)
    assert (tmp_path / "keep.txt").exists()
