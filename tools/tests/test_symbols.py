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
