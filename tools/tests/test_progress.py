"""README.md's progress section, and config/decompiled.tsv behind it.

The first test is the gate: the README's numbers equal a fresh render of what is
committed, and the list covers exactly the units units.txt names. The rest prove
that each thing the gate checks can fail, by handing it the mistake it exists to
catch -- a unit added and never measured, a function renamed in its source, a
number edited by hand -- because a check that agrees with everything is worse
than none.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import progress as P  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def committed():
    return P.read_list(), P.read_text_lf(P.README)[0]


def test_readme_and_list_are_current(committed):
    rows, readme = committed
    assert P.problems(rows, readme) == []


def test_a_unit_never_measured_is_caught(committed):
    rows, readme = committed
    dropped = rows[0].unit
    found = P.problems([r for r in rows if r.unit != dropped], readme)
    assert f"{dropped} is in units.txt but not in config/decompiled.tsv" in found
    assert found[-1] == "run: python tools/progress.py --measure"


def test_a_unit_units_txt_dropped_is_caught(committed):
    rows, readme = committed
    gone = P.Row("src/soa/gone.c", P.VERIFIED, rows[0].address, rows[0].size, rows[0].name)
    found = P.problems([*rows, gone], readme)
    assert "src/soa/gone.c is in config/decompiled.tsv but no longer in units.txt" in found


def test_a_function_its_source_no_longer_mentions_is_caught(committed):
    rows, readme = committed
    r = rows[0]
    renamed = P.Row(r.unit, r.state, r.address, r.size, "noSuchFunctionAnywhere")
    found = P.problems([renamed, *rows[1:]], readme)
    assert f"noSuchFunctionAnywhere is listed for {r.unit}, which no longer mentions it" in found


def test_a_size_the_inventory_disagrees_with_is_caught(committed):
    rows, readme = committed
    r = rows[0]
    found = P.problems([P.Row(r.unit, r.state, r.address, r.size + 4, r.name), *rows[1:]], readme)
    assert any("config/functions.tsv disagrees" in m for m in found)


def test_a_hand_edited_number_is_caught(committed):
    rows, readme = committed
    total = f"| {sum(r.size for r in rows):,} bytes |"
    assert total in readme
    found = P.problems(rows, readme.replace(total, "| 9,999 bytes |"))
    assert found == ["README.md's progress section is stale; run: python tools/progress.py"]


def test_a_readme_without_the_markers_is_caught(committed):
    rows, readme = committed
    found = P.problems(rows, readme.replace(P.END, ""))
    assert len(found) == 1 and "no" in found[0] and P.END in found[0]


def test_render_counts_by_area_and_by_binding():
    inventory = {
        0x100: {"size": 40},
        0x140: {"size": 60},
        0x200: {"size": 100},
        0x900: {"size": 800},  # in no split
    }
    splits = [("lib/b.c", [(0x200, 0x300)]), ("sdk/init.c", [(0x100, 0x200)])]
    rows = [
        P.Row("src/a.c", P.VERIFIED, 0x100, 40, "a"),
        P.Row("src/b.c", P.LINK, 0x200, 100, "b"),
    ]
    text = P.render(rows, inventory, splits, {0x100: "a", 0x140: "c"}, {"src/a.c"})
    lines = text.splitlines()
    assert lines[0] == P.BEGIN and lines[-1] == P.END
    assert "| Decompiled, matching byte for byte | 2 of 4 | 140 bytes |" in text
    assert "14.00%" in text  # 140 of 1,000 bytes
    assert "1 of the 2 decompiled functions (40 bytes)" in text
    # areas by address, whatever order splits.txt lists them in
    start, other = (
        lines.index(next(x for x in lines if x.startswith(p))) for p in ("| Start", "| `lib")
    )
    assert start < other
    assert "| Start-up code (`.init`) | 1 of 2 | 40 of 100 bytes |" in text
    assert "| `lib/b.c` | 1 of 1 | 100 of 100 bytes |" in text
    assert "| Outside every split | 0 of 1 | 0 of 800 bytes |" in text
    assert "| [`src/a.c`](src/a.c) | 1 | 40 | verified | yes | 1 |" in text
    assert "| [`src/b.c`](src/b.c) | 1 | 100 | link pending | — | — |" in text


def test_bar_and_percent():
    assert P.bar(0, 10, width=4) == "`░░░░`"
    assert P.bar(10, 10, width=4) == "`████`"
    assert P.bar(1, 2, width=4) == "`██░░`"
    assert (P.percent(0, 7), P.percent(7, 7), P.percent(1, 3)) == ("0%", "100%", "33.33%")
    assert P.percent(0, 0) == "0%"


def test_splice_keeps_everything_outside_the_markers():
    readme = f"top\n{P.BEGIN}\nold\n{P.END}\nbottom\n"
    assert P.splice(readme, f"{P.BEGIN}\nnew\n{P.END}") == f"top\n{P.BEGIN}\nnew\n{P.END}\nbottom\n"


def test_list_round_trips_and_refuses_what_is_not_a_row(tmp_path):
    rows = [P.Row("src/a.c", P.LINK, 0x80005520, 80, "memcpy")]
    path = tmp_path / "decompiled.tsv"
    P.write_list(rows, path)
    assert P.read_list(path) == rows
    path.write_text("unit\tstate\taddress\tsize\tname\nsrc/a.c\tmatch\t0x80005520\t80\tm\n")
    with pytest.raises(ValueError, match=":2: not a row"):
        P.read_list(path)
    path.write_text("unit\taddress\n")
    with pytest.raises(ValueError, match=":1: the header"):
        P.read_list(path)


def test_splits_are_read_without_the_section_table():
    splits = dict(P.read_splits())
    assert "Sections" not in splits
    assert splits["sdk/init.c"] == [(0x80003100, 0x80005570)]
    assert splits["game/game.c"] == [(0x80005600, 0x802319E0)]


needs_dump = pytest.mark.skipif(
    not (ROOT / "extracted" / "sys" / "main.dol").exists()
    or not (ROOT / "vendor" / "mwcc" / "GC").exists(),
    reason="measuring needs the vendored compiler and your dump",
)


@needs_dump
def test_the_committed_list_is_a_fresh_measurement(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    rows = P.measure(Path("vendor/mwcc/GC"), Path("extracted/sys/main.dol"), tmp_path)
    assert rows == P.read_list()
