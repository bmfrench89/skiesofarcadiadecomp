"""Symbol database tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import symbols as S  # noqa: E402

LINE = "OSInit = .text:0x80232000; // type:function size:0x1A0 scope:global"


def test_parse_dtk_line():
    (sym,) = S.parse_dtk(LINE)
    assert sym.name == "OSInit"
    assert sym.section == ".text"
    assert sym.address == 0x80232000
    assert sym.kind == "function"
    assert sym.size == 0x1A0
    assert sym.scope == "global"


def test_roundtrip_preserves_unknown_attributes():
    text = "tbl = .rodata:0x802AC900; // type:object size:0x40 align:4 data:4byte hidden"
    (sym,) = S.parse_dtk(text)
    assert sym.attrs == {"align": "4", "data": "4byte", "hidden": True}
    assert S.parse_dtk(sym.to_dtk())[0] == sym


def test_placeholder_names():
    assert S.Symbol("fn_80005600", 0x80005600, ".text").is_placeholder
    assert S.Symbol("lbl_80004000", 0x80004000, ".init", kind="label").is_placeholder
    assert not S.Symbol("OSInit", 0x80232000, ".text").is_placeholder


def test_name_for_prefers_real_dtk_names():
    by_addr = {
        0x1000: S.Symbol("OSInit", 0x1000, ".text"),
        0x2000: S.Symbol("fn_00002000", 0x2000, ".text"),
    }
    assert S.name_for(0x1000, by_addr) == ("OSInit", "dtk")
    assert S.name_for(0x2000, by_addr) == ("fn_00002000", "auto")
    assert S.name_for(0x3000, by_addr) == ("fn_00003000", "auto")


def test_tsv_roundtrip(tmp_path):
    rows = [
        {
            "address": 0x80005600,
            "size": 852,
            "name": "fn_80005600",
            "source": "auto",
            "frame": 1,
            "leaf": 0,
            "calls": 3,
            "tail_calls": 0,
            "jump_tables": 1,
            "unresolved": 0,
        }
    ]
    path = tmp_path / "functions.tsv"
    S.write_tsv(rows, path)
    back = S.load_tsv(path)
    assert back[0x80005600]["size"] == 852
    assert back[0x80005600]["name"] == "fn_80005600"
    assert back[0x80005600]["jump_tables"] == 1


DTK_FILE = (
    "CARDInit = .text:0x80245758; // type:function size:0xAC scope:global\n"
    "fn_80248884 = .text:0x80248884; // type:function size:0x410\n"
    "fn_80248DCC = .text:0x80248DCC; // type:function size:0x1A0\n"
    "lbl_80318360 = .data:0x80318360; // type:object size:0x220\n"
)
NAMES = {
    0x80245758: ("CARDInit", "already here"),
    0x80248884: ("CARDDoMount", "the mount state machine"),
    0x80248DCC: ("CARDMountAsync", "the public entry"),
}


def test_apply_names_to_dtk_renames_placeholders_only(tmp_path):
    path = tmp_path / "symbols.txt"
    path.write_text(DTK_FILE, encoding="utf-8")
    assert S.apply_names_to_dtk(path, NAMES) == 2
    text = path.read_text(encoding="utf-8")
    assert "CARDDoMount = .text:0x80248884; // type:function size:0x410" in text
    assert "CARDMountAsync = .text:0x80248DCC; // type:function size:0x1A0" in text
    # dtk's own name stands, and a non-function entry is not our business.
    assert "CARDInit = .text:0x80245758; // type:function size:0xAC scope:global" in text
    assert "lbl_80318360 = .data:0x80318360" in text
    # Running it again has nothing left to do.
    assert S.apply_names_to_dtk(path, NAMES) == 0


def test_apply_names_to_dtk_will_not_duplicate_a_name(tmp_path):
    # The file already calls something CARDDoMount: renaming here would leave
    # two symbols of one name, and objdiff matches by name.
    path = tmp_path / "symbols.txt"
    path.write_text(
        "CARDDoMount = .text:0x80248000; // type:function size:0x10\n"
        "fn_80248884 = .text:0x80248884; // type:function size:0x410\n",
        encoding="utf-8",
    )
    assert S.apply_names_to_dtk(path, NAMES) == 0
    assert "fn_80248884 = .text:0x80248884" in path.read_text(encoding="utf-8")


def test_apply_names_to_dtk_dry_run_counts_without_writing(tmp_path):
    path = tmp_path / "symbols.txt"
    path.write_text(DTK_FILE, encoding="utf-8")
    assert S.apply_names_to_dtk(path, NAMES, write=False) == 2
    assert path.read_text(encoding="utf-8") == DTK_FILE


def test_apply_names_to_dtk_ignores_an_entry_that_moved(tmp_path):
    # A placeholder whose name and address disagree is a file to fix, not to
    # rewrite from a name table.
    path = tmp_path / "symbols.txt"
    path.write_text(
        "fn_80248884 = .text:0x80249000; // type:function size:0x410\n", encoding="utf-8"
    )
    assert S.apply_names_to_dtk(path, NAMES) == 0
