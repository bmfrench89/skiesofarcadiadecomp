"""Tests for tools/midpoint.py on canned output: no soa.exe, no captures.

What these cover is the part of the judge that could agree with everything:
the parsing of a replay's lines and the verdicts drawn from them. Each verdict
is shown passing on a consistent set of runs and failing when the one thing it
checks is broken, so none of them can quietly stop looking.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import midpoint  # noqa: E402

PAIR_TEXT = """\
[pair] a pair replay: no capture is written and no frame hook runs between the passes
[pair] pass 1: record C:/tmp/5000
[gxr] frame 0 640x480 hash 64ffeabcb8b5265a
[gx] replayed 301413 of 301413 bytes
[pair] pass 2: as it is C:/tmp/5001
[gxr] frame 1 640x480 hash ceb43496d205a712
[gx] replayed 301569 of 301569 bytes
[pair] pass 3: between C:/tmp/5001
[gxr] frame 2 640x480 hash 791fd538a9f6dfdb
[gx] replayed 301569 of 301569 bytes
[pair] midpoint at t=0.50: 1144 of 1147 draws matched (7338 vertices interpolated), 3 drawn from \
F+1, 0 demoted (projection type differs), 2 copies to texture skipped (0 clears kept), 0 over \
capacity; largest displacement 1324.1 px, 10 matched draws with a vertex over 32 px; peak 1147 \
draws / 7354 vertices a frame; pairs eb377060ef8ba205
"""

F, F1, MID = "64ffeabcb8b5265a", "ceb43496d205a712", "791fd538a9f6dfdb"


def test_a_pair_replay_is_parsed():
    res = midpoint.parse_pair(PAIR_TEXT)
    assert res["hashes"] == [F, F1, MID]
    assert res["report"] == {
        "t": 0.5,
        "matched": 1144,
        "draws": 1147,
        "vertices": 7338,
        "from_f1": 3,
        "demoted": 0,
        "skipped": 2,
        "kept": 0,
        "over": 0,
        "largest": 1324.1,
        "over32": 10,
        "peak_draws": 1147,
        "peak_vertices": 7354,
    }


def test_a_pair_replay_missing_a_frame_or_its_report_is_refused():
    lines = PAIR_TEXT.splitlines(keepends=True)
    with pytest.raises(ValueError):
        midpoint.parse_pair("".join(ln for ln in lines if "frame 2 " not in ln))
    with pytest.raises(ValueError):
        midpoint.parse_pair("".join(ln for ln in lines if "midpoint at" not in ln))


def test_a_single_replay_is_one_hash():
    assert midpoint.parse_one("[gxr] frame 0 640x480 hash ceb43496d205a712\n") == F1
    with pytest.raises(ValueError):
        midpoint.parse_one(PAIR_TEXT)


def test_the_pairs_list_is_read_in_order(tmp_path):
    p = tmp_path / "pairs"
    p.write_text("0 0\n1 1\n3 2\n", encoding="utf-8")
    assert midpoint.read_pairs(p) == [(0, 0), (1, 1), (3, 2)]


def consistent():
    """Runs on which every verdict holds, with field's numbers: 1144 pairs of
    1147 draws, as H4 counted. Every list is its own copy, so breaking one
    run breaks nothing else."""
    want = [(i, i) for i in range(1144)]
    want_mut = [p for p in want if p != (1, 1)]
    mid = {**midpoint.parse_pair(PAIR_TEXT), "pairs": list(want)}
    runs = {
        "mid": mid,
        "mid1": copy.deepcopy(mid),
        "one": F1,
        "t1": {"hashes": [F, F1, F1], "pairs": list(want)},
        "self": {"hashes": [F, F, F], "pairs": list(want)},
        "mut": {"hashes": [F, "a" * 16, "b" * 16], "pairs": list(want_mut)},
    }
    return runs, want, want_mut


def test_every_verdict_holds_on_consistent_runs():
    runs, want, want_mut = consistent()
    out = midpoint.verdicts("field", runs, want, want_mut)
    assert len(out) == 7
    assert all(v.ok for v in out), [v for v in out if not v.ok]


@pytest.mark.parametrize(
    "name, breakage",
    [
        ("pass 2 is F+1 as a single replay draws it", lambda r, w, m: r.update(one="0" * 16)),
        (
            "the pairs are fifopair's",  # wrong the same way at both thread counts
            lambda r, w, m: [x["pairs"].__setitem__(5, (7, 5)) for x in (r["mid"], r["mid1"])],
        ),
        ("as many as H4 counted", lambda r, w, m: r["mid"]["report"].update(draws=1148)),
        (
            "the same images at one thread",
            lambda r, w, m: r["mid1"]["hashes"].__setitem__(2, "0" * 16),
        ),
        ("F with itself is F", lambda r, w, m: r["self"]["hashes"].__setitem__(2, "0" * 16)),
        ("t=1 is F+1", lambda r, w, m: r["t1"]["hashes"].__setitem__(2, "0" * 16)),
        (
            "a changed texture address loses the same pairs in both",
            lambda r, w, m: r["mut"].update(pairs=list(w)),
        ),
    ],
)
def test_each_verdict_fails_when_its_one_thing_breaks(name, breakage):
    runs, want, want_mut = consistent()
    breakage(runs, want, want_mut)
    out = {v.name: v.ok for v in midpoint.verdicts("field", runs, want, want_mut)}
    assert out[name] is False
    assert [n for n, ok in out.items() if not ok] == [name], out


def test_a_change_that_costs_nothing_is_not_a_pass():
    """Both lists equal and nothing lost would mean the mutation missed every
    draw: that proves nothing about either implementation, so it fails."""
    runs, want, _ = consistent()
    runs["mut"]["pairs"] = list(want)
    out = {v.name: v.ok for v in midpoint.verdicts("field", runs, want, list(want))}
    assert out["a changed texture address loses the same pairs in both"] is False


def test_images_round_trip_and_differences_are_counted(tmp_path):
    w, h = 3, 2
    a = bytes([10, 20, 30, 255] * (w * h))
    b = bytearray(a)
    b[4:8] = bytes([11, 20, 30, 255])  # one pixel, one channel, one level
    p = tmp_path / "a.png"
    midpoint.write_rgba(p, w, h, a)
    assert midpoint.read_rgba(p) == (w, h, a)
    assert midpoint.differing(a, bytes(b)) == 1
    diff = midpoint.difference(bytes(b), a)
    assert diff[4:8] == b"\xff\x00\xff\xff"
    assert diff[0:4] == bytes([10 // 3, 20 // 3, 30 // 3, 255])
    with pytest.raises(ValueError):
        midpoint.differing(a, a[:-4])


def test_a_png_the_port_did_not_write_is_refused(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"not a png")
    with pytest.raises(ValueError):
        midpoint.read_rgba(p)


def test_a_mutation_moves_the_texture_address_by_32_bytes():
    stream = bytes([0x00, 0x61, 0x94, 0x00, 0x43, 0x10, 0x00])
    out = midpoint.mutate(stream, 1)
    assert out[:5] == stream[:5] and out[5] == 0x11 and len(out) == len(stream)
    with pytest.raises(ValueError):
        midpoint.mutate(stream, 0)


def test_an_unknown_pair_is_refused(capsys):
    with pytest.raises(SystemExit) as e:
        midpoint.main(["nowhere"])
    assert e.value.code == 2
    assert "no pair called nowhere" in capsys.readouterr().err


def test_a_capture_that_changed_since_the_manifest_is_refused(monkeypatch, capsys):
    """Nothing runs: a judgement of inputs that drifted judges the drift."""
    rows = {name: ("", {}) for p in midpoint.PAIRS.values() for name in (p.f, p.f1)}
    monkeypatch.setattr(midpoint.perfbench, "read_manifest", lambda: rows)
    monkeypatch.setattr(midpoint.perfbench, "verify", lambda name, pinned: [".ram"])
    monkeypatch.setattr(midpoint, "judge", lambda *a, **k: pytest.fail("judged a changed capture"))
    assert midpoint.main(["sky"]) == 1
    assert "sky/4000: .ram missing or changed" in capsys.readouterr().err
