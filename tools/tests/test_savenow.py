"""tools/savenow.py, M7a's list of the maps with a save point
(docs/specs/save-now.md): the header it writes, and, where the disc is, that
runtime/save_point_maps.h is what the disc's scripts say."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import savenow  # noqa: E402

DATA = ROOT / "extracted"


def test_a_map_is_its_number_and_letter_as_the_api_gives_it():
    assert savenow.word("116a") == 0x7461 and savenow.word("002a") == 0x0261


def test_the_header_lists_what_it_was_given_and_a_dropped_map_shows():
    maps = ["002a", "116a", "524a"]
    text = savenow.header(maps)
    assert savenow.listed(text) == maps
    assert "#define SAVE_POINT_MAPS 3" in text and "0x00007461u, /* a116a */" in text
    assert savenow.listed(savenow.header(maps[1:])) != maps  # what check compares


def test_the_committed_header_parses():
    maps = savenow.listed(savenow.HEADER.read_text(encoding="utf-8"))
    assert "116a" in maps and "101b" in maps and "116c" not in maps
    assert f"#define SAVE_POINT_MAPS {len(maps)}" in savenow.HEADER.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (DATA / "disc.iso").exists() and not any(DATA.glob("*.soadisc")), reason="no disc"
)
def test_the_headers_are_what_the_disc_says():
    saves, warps = savenow.scan_all(DATA)
    assert savenow.listed(savenow.HEADER.read_text(encoding="utf-8")) == saves
    assert savenow.listed(savenow.WARP_HEADER.read_text(encoding="utf-8")) == warps  # M7b


def test_the_warp_list_is_the_field_s_maps():
    """M7b: below 500 (the 5xx are ship battles), with 116c and 355a, the part
    menu, in it, and sorted by map."""
    maps = savenow.listed(savenow.WARP_HEADER.read_text(encoding="utf-8"))
    assert "116c" in maps and "355a" in maps and all(int(m[:3]) < 500 for m in maps)
    assert maps == sorted(maps)
    assert "0x00006761u, /* a103a */" in savenow.warp_header(["103a"])
