"""The game's data by name (T9, docs/specs/game-names.md).

config/gamedata.txt names each game address with `ref`, an instruction in the
DOL that reaches it. The half of this file that needs the disc decodes every
ref from your DOL, and shows the check can fail: an address moved by four, and
a field's offset moved by two, are each caught with the line named. The rest
needs nothing: the file's grammar, and the files made from it current.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gamedata as tool  # noqa: E402
from soa import gamedata as G  # noqa: E402

DOL = ROOT / "extracted" / "sys" / "main.dol"
needs_dol = pytest.mark.skipif(
    not DOL.exists(), reason="no extracted/sys/main.dol: the refs are the game's code"
)
TEXT = G.CONFIG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dol():
    return tool.open_dol(DOL)


def test_the_file_parses():
    data = G.load()
    assert len(data.entries) >= 60
    assert {"scene", "encounter.table", "party.gold", "battle.context"} <= set(data.by_name())
    for r in data.records.values():
        assert r.fields, r.name


def test_the_made_files_are_current():
    """runtime/soa_gamedata.h, runtime/gamedata_names.h and
    docs/MODDING-NAMES.md, as `generate --write` makes them now."""
    assert tool.stale(G.load()) == [], "python tools/gamedata.py generate --write"


def test_a_name_added_without_regenerating_is_stale(tmp_path):
    data = G.parse(TEXT + "\nextra.word 0x803475CC u32 0x801CBC3C a second name for the scene\n")
    assert any(p.name == "soa_gamedata.h" for p in tool.stale(data))


@pytest.mark.parametrize(
    "line, why",
    [
        ("scene 0x803475CC u32 0x801CBC3C twice", "scene twice"),
        ("odd.word 0x803475cc u32 0x801CBC3C x", "an address is"),
        ("odd.word 0x803475CE u32 0x801CBC3C x", "not aligned"),
        ("odd.word 0x803475CC u7 0x801CBC3C x", "is not a type"),
        ("Bad 0x803475CC u32 0x801CBC3C x", "is not a name"),
        ("short 0x803475CC u32", "a name is"),
        ("odd.word 0x803475CC ptr:nothing 0x801CBC3C x", "no record nothing"),
        ("record tiny 2\n  word 0 u32", "runs outside tiny"),
    ],
)
def test_the_grammar_refuses_with_the_line(line, why):
    with pytest.raises(G.GameDataError, match=re.escape(why)) as e:
        G.parse(TEXT + "\n" + line + "\n")
    assert re.match(r"gamedata\.txt:\d+:", str(e.value))


RUNTIME_COPIES = [
    ("mod.c", "SCENE_ID", "scene"),
    ("mod.c", "FIELD_STATE", "field.state"),
    ("mod.c", "MAP_NUMBER", "map.number"),
    ("mod.c", "MAP_LETTER", "map.letter"),
    ("mod.c", "STORY_FLAGS", "story.flags"),
    ("mod.c", "ENCOUNTER_TABLE", "encounter.table"),
    ("tick.c", "RETRACE_COUNT", "vi.retrace_count"),
    ("tick.c", "FRAME_START_FIELDS", "frame.start_fields"),
    ("tick.c", "SCENE_ID", "scene"),
    ("tick.c", "MAP_NUMBER", "map.number"),
    ("tick.c", "SKY_MODE", "sky.mode"),
]


@pytest.mark.parametrize("source, macro, name", RUNTIME_COPIES)
def test_the_runtime_s_own_copies_agree(source, macro, name):
    """The runtime is not a mod and keeps its own #defines, but each must be
    the address the file proves."""
    text = (ROOT / "runtime" / source).read_text(encoding="utf-8")
    m = re.search(rf"^#define {macro} 0x([0-9A-Fa-f]{{8}})u", text, re.M)
    assert m, f"{source} no longer defines {macro}"
    assert int(m.group(1), 16) == G.load().by_name()[name].address


@needs_dol
def test_every_name_is_refound_in_the_code(dol):
    d, sda = dol
    objects = G.data_objects((ROOT / "config" / "symbols.txt").read_text(encoding="utf-8"))
    assert G.verify(G.load(), d, sda, objects) == []


@needs_dol
def test_an_address_moved_is_caught_with_its_line(dol):
    d, sda = dol
    data = G.load()
    victim = data.by_name()["encounter.steps"]
    moved = TEXT.replace(f"0x{victim.address:08X}", f"0x{victim.address + 4:08X}", 1)
    faults = G.verify(G.parse(moved), d, sda)
    assert len(faults) == 1 and f"gamedata.txt:{victim.line}: encounter.steps" in faults[0], faults


@needs_dol
def test_an_offset_moved_is_caught_with_its_line(dol):
    d, sda = dol
    moved = re.sub(r"(\n  rate\s+)2(\s+u16)", r"\g<1>4\2", TEXT, count=1)
    assert moved != TEXT
    faults = G.verify(G.parse(moved), d, sda)
    assert (
        len(faults) == 1 and "ect_zone.rate" in faults[0] and "not 4 (modulo 132)" in faults[0]
    ), faults


@needs_dol
def test_find_lists_the_research_s_own_instruction(dol):
    """encounters.md quotes `800C25D8 stw -29284(r13)` for the table's
    pointer: find, which chooses refs, must see it."""
    d, sda = dol
    assert 0x800C25D8 in G.find(d, 0x803474BC, sda)
