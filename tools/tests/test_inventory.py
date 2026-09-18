"""Regenerating the inventory has to leave both symbol files saying the same
thing.

``config/symbols.txt`` is ours and has always carried the names in
``config/names.txt``. ``config/GEAE8P/symbols.txt`` belongs to the
decomp-toolkit project and is what ``build/dtk/obj/`` is generated from, which
is what objdiff matches *by name*: a name only we knew left objdiff calling the
function ``fn_XXXXXXXX`` while matchcheck called it something else.
``symbols.apply_names_to_dtk`` existed for exactly this and was called from
nowhere. These tests build a four-byte executable rather than needing a disc.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inventory as INV  # noqa: E402

TEXT = 0x80003100
BLR = 0x4E800020


def executable(tmp_path: Path, functions: int = 2) -> Path:
    header = bytearray(0x100)
    text = struct.pack(f">{functions}I", *([BLR] * functions))
    struct.pack_into(">I", header, 0x00, 0x100)
    struct.pack_into(">I", header, 0x48, TEXT)
    struct.pack_into(">I", header, 0x90, len(text))
    struct.pack_into(">I", header, 0xE0, TEXT)
    path = tmp_path / "main.dol"
    path.write_bytes(bytes(header) + text)
    return path


def project(tmp_path: Path) -> Path:
    path = tmp_path / "dtk-symbols.txt"
    path.write_text(
        f"fn_{TEXT:08X} = .text:0x{TEXT:08X}; // type:function size:0x4\n"
        f"fn_{TEXT + 4:08X} = .text:0x{TEXT + 4:08X}; // type:function size:0x4\n",
        encoding="utf-8",
    )
    return path


def names(tmp_path: Path) -> Path:
    path = tmp_path / "names.txt"
    path.write_text(f"0x{TEXT + 4:08X}\tmyThing\tself-naming string\n", encoding="utf-8")
    return path


def regenerate(tmp_path: Path, dtk_project: Path) -> int:
    out = tmp_path / "config"
    return INV.main(
        [
            "--dol",
            str(executable(tmp_path)),
            "--names",
            str(names(tmp_path)),
            "--dtk-project",
            str(dtk_project),
            "--out",
            str(out),
        ]
    )


def test_a_recovered_name_reaches_the_dtk_project(tmp_path):
    dtk = project(tmp_path)
    assert regenerate(tmp_path, dtk) == 0
    carried = dtk.read_text(encoding="utf-8")
    assert f"myThing = .text:0x{TEXT + 4:08X}" in carried
    assert f"fn_{TEXT + 4:08X}" not in carried
    # and the entry with no recovered name is left exactly as dtk had it
    assert f"fn_{TEXT:08X} = .text:0x{TEXT:08X}" in carried


def test_both_symbol_files_end_up_with_the_same_name(tmp_path):
    dtk = project(tmp_path)
    regenerate(tmp_path, dtk)
    ours = (tmp_path / "config" / "symbols.txt").read_text(encoding="utf-8")
    assert "myThing" in ours and "myThing" in dtk.read_text(encoding="utf-8")


def test_the_pass_says_how_many_names_landed(tmp_path, capsys):
    regenerate(tmp_path, project(tmp_path))
    assert "named 1 of 1 recovered functions" in capsys.readouterr().out


def test_a_missing_dtk_project_is_a_note_not_a_crash(tmp_path, capsys):
    assert regenerate(tmp_path, tmp_path / "not-here.txt") == 0
    assert "not found" in capsys.readouterr().err


def test_regenerating_twice_is_the_same_file(tmp_path):
    """The rename only fires on placeholders, so a second run has nothing left
    to do and must not invent a second symbol of the same name."""
    dtk = project(tmp_path)
    regenerate(tmp_path, dtk)
    once = dtk.read_text(encoding="utf-8")
    regenerate(tmp_path, dtk)
    assert dtk.read_text(encoding="utf-8") == once
