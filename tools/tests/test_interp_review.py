"""tools/interp_review.py: the in-between images ranked for the owner's look.

Synthetic snapshots, written as the port writes them: a square that moves from
x=10 to x=30 with its in-between image at x=20 (a good one), and another whose
in-between image is a different picture altogether (what a missed cut looks
like). The bad one must rank first and the good one score near nothing; the
page lists both with their pictures, and a cut from the log is labelled.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import interp_review  # noqa: E402
from soa import png  # noqa: E402

W, H = 64, 48


def picture(square_x: int | None, ground: tuple[int, int, int] = (20, 40, 60)) -> bytes:
    out = bytearray()
    for y in range(H):
        for x in range(W):
            inside = square_x is not None and square_x <= x < square_x + 12 and 10 <= y < 30
            out += bytes((240, 200, 40, 255)) if inside else bytes((*ground, 255))
    return bytes(out)


def snapshot(d: Path, n: int, before: bytes, mids: list[bytes], after: bytes) -> None:
    png.write_rgba(d / f"{n - 1:04d}.png", W, H, before)
    png.write_rgba(d / f"{n:04d}.png", W, H, after)
    if len(mids) == 1:
        png.write_rgba(d / f"{n:04d}.mid.png", W, H, mids[0])
    else:
        for k, m in enumerate(mids):
            png.write_rgba(d / f"{n:04d}.mid{k + 1}.png", W, H, m)


def test_a_missed_cut_ranks_first_and_a_good_image_scores_near_nothing(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    snapshot(frames, 100, picture(10), [picture(15), picture(20), picture(25)], picture(30))
    snapshot(frames, 200, picture(10), [picture(None, (200, 30, 200))], picture(30))
    log = tmp_path / "interp.log"
    log.write_text(
        "199 keyed3d 1 matched3d 1 far16 0 far32 0 far64 0 far128 0 worst 0.0 cut 0 frame_ms 33.0\n"
        "200 keyed3d 1 matched3d 0 far16 0 far32 0 far64 0 far128 0 worst 0.0 cut 1 frame_ms 33.0\n",
        encoding="utf-8",
    )
    out = tmp_path / "review"
    assert interp_review.main([str(frames), "--log", str(log), "--out", str(out)]) == 0
    found = interp_review.triplets(frames)
    assert [n for n, _ in found] == [100, 200]
    assert [p.name for p in found[0][1]] == ["0100.mid1.png", "0100.mid2.png", "0100.mid3.png"]
    page = (out / "index.html").read_text(encoding="utf-8")
    assert page.index("<b>200</b>") < page.index("<b>100</b>")  # the missed cut first
    assert "a cut the detector marked" in page
    for name in ("0099.png", "0100.mid2.png", "0100.png", "0100.neither.png", "0200.mid.png"):
        assert (out / "img" / name).exists(), name
    _, _, a = png.read_rgba(frames / "0099.png")
    _, _, b = png.read_rgba(frames / "0100.png")
    _, _, good = png.read_rgba(frames / "0100.mid2.png")
    _, _, bad = png.read_rgba(frames / "0200.mid.png")
    g_bad, g_seen, _ = interp_review.neither_mask(a, good, b, W, H, 1)
    b_bad, b_seen, _ = interp_review.neither_mask(a, bad, b, W, H, 1)
    # motion itself scores a little: the square's middle position is neither
    # frame's (8 of its columns, 5% of this small picture); a cut scores all
    assert g_bad / g_seen < 0.1 < 0.9 < b_bad / b_seen, (g_bad / g_seen, b_bad / b_seen)


def test_a_folder_without_a_frame_before_is_said(tmp_path, capsys):
    frames = tmp_path / "frames"
    frames.mkdir()
    png.write_rgba(frames / "0100.png", W, H, picture(30))
    png.write_rgba(frames / "0100.mid.png", W, H, picture(20))
    assert interp_review.main([str(frames), "--out", str(tmp_path / "review")]) == 1
    assert "no snapshot" in capsys.readouterr().out


def test_an_out_folder_holding_the_frames_is_refused_and_nothing_is_removed(tmp_path):
    """The page's folder is removed before it is written. Given the frames
    folder or a folder above it, the tool refuses even where an index.html
    makes it look like a page; given a folder of other files with no page
    in it, it refuses too; and every file stays. The mutations, either rule
    left out, remove the frames or the other files."""
    frames = tmp_path / "frames"
    frames.mkdir()
    snapshot(frames, 100, picture(10), [picture(20)], picture(30))
    for page_like in (frames, tmp_path):  # the first rule alone refuses these
        (page_like / "index.html").write_text("<p>an old page</p>", encoding="utf-8")
    other = tmp_path / "notes"
    other.mkdir()
    (other / "keep.txt").write_text("mine", encoding="utf-8")  # the second rule alone refuses this
    for out in (frames, tmp_path, other):
        assert interp_review.main([str(frames), "--out", str(out)]) == 2, out
    assert (frames / "0100.png").is_file() and (other / "keep.txt").is_file()
    page = tmp_path / "review"
    assert interp_review.main([str(frames), "--out", str(page)]) == 0
    assert interp_review.main([str(frames), "--out", str(page)]) == 0  # its own page, again
