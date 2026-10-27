"""A review page of in-between images for the owner's look (PLAN-NEXT D-45,
session D): which ones to look at first.

A headless run with SOA_INTERP (or SOA_INTERP=display and SOA_INTERP_RATE) and
SOA_SNAP=N writes, every N frames, the frame (NNNN.png), its in-between images
(NNNN.mid.png, or NNNN.midK.png a slice each) and, since H17c-b's review
change, the frame before (NNNN-1's .png). An in-between image should be made of
what those two frames hold, moved part way: a pixel that matches neither is
what a camera cut the detector missed, an effect drawn from the wrong frame or a
copy read from the next one looks like. Each snapshot's middle in-between image
is scored by the share of pixels that match neither frame (sampled on a grid),
the snapshots are ranked, and the page shows the worst first: the frame before,
the in-between images, the frame, and the middle one greyed with those pixels in
magenta. A frame the cut detector marked (SOA_INTERP_LOG's `cut 1`) is labelled:
its in-between images are not shown, so its score is expected.

The page and its pictures are game imagery: they stay under build/, never
published.

    python tools/interp_review.py <frames dir> [--log interp.log] [--out build/interp-review] [--top 40]
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from soa import png  # noqa: E402

NEITHER = 40  # a channel this far from both frames: the pixel is neither's
STRIDE = 3  # the scoring grid, every third pixel each way
RE_MID = re.compile(r"^(\d+)\.mid(\d*)\.png$")
RE_LOG = re.compile(r"^(\d+) keyed3d .* cut (\d)")


def triplets(frames: Path) -> list[tuple[int, list[Path]]]:
    """(frame N, its in-between images in weight order) wherever N-1's and N's
    pictures are there too."""
    mids: dict[int, list[tuple[int, Path]]] = {}
    for p in frames.glob("*.mid*.png"):
        m = RE_MID.match(p.name)
        if m:
            mids.setdefault(int(m.group(1)), []).append((int(m.group(2) or 0), p))
    out = []
    for n in sorted(mids):
        if (frames / f"{n:04d}.png").exists() and (frames / f"{n - 1:04d}.png").exists():
            out.append((n, [p for _, p in sorted(mids[n])]))
    return out


def neither_mask(
    a: bytes, m: bytes, b: bytes, w: int, h: int, stride: int
) -> tuple[int, int, list[bool]]:
    """Over a grid of every `stride`-th pixel: how many pixels of m match
    neither a nor b, how many were looked at, and which (row-major, the grid's)."""
    flags = []
    for y in range(0, h, stride):
        row = y * w * 4
        for x in range(0, w, stride):
            i = row + x * 4
            da = max(abs(m[i] - a[i]), abs(m[i + 1] - a[i + 1]), abs(m[i + 2] - a[i + 2]))
            db = max(abs(m[i] - b[i]), abs(m[i + 1] - b[i + 1]), abs(m[i + 2] - b[i + 2]))
            flags.append(da > NEITHER and db > NEITHER)
    return sum(flags), len(flags), flags


def heat(a: bytes, m: bytes, b: bytes, w: int, h: int) -> bytes:
    """m greyed, the pixels that match neither frame in magenta."""
    _, _, flags = neither_mask(a, m, b, w, h, 1)
    out = bytearray(len(m))
    for k, f in enumerate(flags):
        i = k * 4
        if f:
            out[i : i + 4] = b"\xff\x00\xff\xff"
        else:
            g = (m[i] + m[i + 1] + m[i + 2]) // 6 + 40
            out[i : i + 4] = bytes((g, g, g, 255))
    return bytes(out)


def read_cuts(log: Path | None) -> set[int]:
    if not log or not log.exists():
        return set()
    cuts = set()
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = RE_LOG.match(line)
        if m and m.group(2) == "1":
            cuts.add(int(m.group(1)))
    return cuts


def page(rows: list[dict], title: str) -> str:
    cells = []
    for r in rows:
        imgs = "".join(
            f'<a href="{html.escape(s)}"><img src="{html.escape(s)}" alt="{html.escape(c)}"></a>'
            for c, s in r["images"]
        )
        note = "a cut the detector marked: its in-between images are not shown" if r["cut"] else ""
        cells.append(
            f"<tr><td><b>{r['frame']}</b><br>{r['score']:.2%} neither<br>{len(r['mids'])} in-between"
            f"<br><i>{html.escape(note)}</i></td><td class=imgs>{imgs}</td></tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=utf-8><title>"
        + html.escape(title)
        + "</title><style>body{font-family:sans-serif;background:#222;color:#ddd}"
        "td{vertical-align:top;padding:6px;border-bottom:1px solid #444}"
        "img{width:240px;margin:2px;image-rendering:pixelated}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p>Each row: the frame before, the in-between images in order, the frame, "
        "and the middle in-between image greyed with the pixels that match neither frame in magenta. Worst first. "
        "Click a picture for its full size.</p><table>" + "".join(cells) + "</table></body></html>"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("frames", type=Path, help="a SOA_SNAP run's frames folder (SOA_FRAMES_DIR)")
    ap.add_argument("--log", type=Path, help="that run's SOA_INTERP_LOG, to label the cuts")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "interp-review")
    ap.add_argument("--top", type=int, default=40, help="rows on the page, worst first")
    a = ap.parse_args(argv)
    found = triplets(a.frames)
    if not found:
        print(
            f"[review] no snapshot in {a.frames} has its frame before and an in-between image beside it"
        )
        return 1
    cuts = read_cuts(a.log)
    scored = []
    for n, mids in found:
        w, h, pa = png.read_rgba(a.frames / f"{n - 1:04d}.png")
        _, _, pb = png.read_rgba(a.frames / f"{n:04d}.png")
        _, _, pm = png.read_rgba(mids[len(mids) // 2])
        bad, seen, _ = neither_mask(pa, pm, pb, w, h, STRIDE)
        scored.append((bad / seen, n, mids, (w, h, pa, pm, pb)))
    scored.sort(key=lambda s: -s[0])
    out = a.out
    # The page's folder is removed and written again, so it must be one: never
    # the frames, a folder holding them, the project or its build/, nor a
    # folder with something in it that is not an earlier page (the review of
    # 2026-10-26: the frames were read, then removed, then copied from).
    whole, frames = out.resolve(), a.frames.resolve()
    held = whole == frames or whole in frames.parents
    if held or whole in (ROOT.resolve(), (ROOT / "build").resolve()):
        print(f"[review] --out {out} holds the frames or the project; nothing was removed")
        return 2
    if out.exists() and any(out.iterdir()) and not (out / "index.html").is_file():
        print(
            f"[review] --out {out} has files and no index.html, so it is no earlier page; not removed"
        )
        return 2
    if out.exists():
        shutil.rmtree(out)
    (out / "img").mkdir(parents=True)
    rows = []
    for score, n, mids, (w, h, pa, pm, pb) in scored[: a.top]:
        names = [f"{n - 1:04d}.png", *[m.name for m in mids], f"{n:04d}.png"]
        for name in names:
            shutil.copyfile(a.frames / name, out / "img" / name)
        png.write_rgba(out / "img" / f"{n:04d}.neither.png", w, h, heat(pa, pm, pb, w, h))
        images = [(name, f"img/{name}") for name in names] + [
            ("neither", f"img/{n:04d}.neither.png")
        ]
        rows.append({"frame": n, "score": score, "mids": mids, "cut": n in cuts, "images": images})
    (out / "index.html").write_text(
        page(rows, f"In-between images from {a.frames.name}"), encoding="utf-8"
    )
    worst = ", ".join(f"{n} ({s:.1%})" for s, n, _, _ in scored[:5])
    print(f"[review] {len(found)} snapshots scored; worst: {worst}; page: {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
