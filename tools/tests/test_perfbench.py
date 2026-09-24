"""tools/perfbench.py: the benchmark the renderer's speed work is judged by.

Two things have to hold for its numbers to mean anything: the figure it
extracts is the one the renderer means (busy thread-seconds over the
fragments it processed, alpha and depth rejects included), and the capture
set it runs is the one the manifest pinned -- a benchmark whose inputs drift
measures the drift. No disc and no binary needed.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import perfbench  # noqa: E402

REPLAY = """[gxr] rasterizing on 8 worker threads
[gx] replayed 301413 of 301413 bytes
[gxr] workers: 8 threads, pool up 0.05s each = 0.42s of thread time; busy 0.33s + idle 0.10s = 0.42s, 0.1% unaccounted
[gxr] 4536 triangles, 0 lines, 0 points; 2838412 pixels shaded (0 outside, 135277 failed alpha, 647440 failed depth); 572 clipped away
"""


def test_the_figure_is_busy_over_all_fragments_processed():
    threads, busy, frags = perfbench.parse_replay(REPLAY)
    assert (threads, busy) == (8, 0.33)
    assert frags == 2838412 + 135277 + 647440  # rejected fragments cost work too


def test_output_without_the_renderer_lines_is_refused():
    with pytest.raises(ValueError):
        perfbench.parse_replay("[gx] replayed 0 of 0 bytes\n")


def make_set(root: Path) -> None:
    for scene, frame, payload in (("field", "5000", b"a"), ("sky", "4000", b"b")):
        d = root / scene
        d.mkdir(parents=True)
        for part in perfbench.PARTS:
            (d / f"{frame}{part}").write_bytes(payload + part.encode())
    (root / "sky" / "4001.fifo").write_bytes(b"incomplete")  # no .regs/.ram: not a capture


def test_the_manifest_pins_every_complete_capture_and_a_change_is_caught(tmp_path):
    root, manifest = tmp_path / "perfset", tmp_path / "m.tsv"
    make_set(root)
    assert perfbench.captures(root) == ["field/5000", "sky/4000"]
    assert perfbench.write_manifest({"field/5000": "Dangral base"}, root, manifest) == 2
    rows = perfbench.read_manifest(manifest)
    assert rows["field/5000"][0] == "Dangral base"
    assert all(perfbench.verify(n, h, root) == [] for n, (_, h) in rows.items())
    (root / "field" / "5000.ram").write_bytes(b"changed")  # the drift the pin exists to catch
    assert perfbench.verify("field/5000", rows["field/5000"][1], root) == [".ram"]
