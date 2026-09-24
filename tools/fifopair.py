#!/usr/bin/env python3
"""Pair the draws of two captured frames: how much of frame N+1 matches frame N.

    python tools/fifopair.py build/fifo-pairs/5000 build/fifo-pairs/5001
    python tools/fifopair.py build/fifo-pairs/5000 build/fifo-pairs/5001 --json

The kill experiment for 60 fps by renderer interpolation (docs/PLAN-60FPS-MODS.md
H4, docs/research/frame-pacing.md 3(c)). An in-between image would be frame
N+1's draws re-issued with each matched draw's vertices interpolated from frame
N, so the number that matters is how much of N+1 comes from draws that have a
partner in N. Under about 90% and draws must be tagged by the game first (H7).

Each capture (<base>.fifo, .regs, .ram -- what SOA_FIFO_DUMP writes) is walked
with fifo.py's parser, display lists followed into the RAM image the way the
runtime follows them, and every draw becomes a record: primitive, vertex format,
count, the display list it came through, the CP array bases its vertex layout
indexes, the texture address of each enabled TEV stage, a hash of the TEV
setup, the position matrices it used, and its vertices in model space, view
space and on the screen.

A draw in N+1 is matched to one in N with an equal key: (display list, array
bases, textures, primitive, vertex count, TEV hash). Draws sharing a key pair
off in stream order, so a repeated draw -- ten identical trees, a run of
glyphs -- is paired by position in the stream and can be paired with the
wrong instance; the key cannot tell instances apart, which is what H7's tags
are for.

Pixels are estimated, not counted. The command stream carries no per-draw
fragment count, so a draw's area is the sum of its triangles' projected areas:
clipped to the near, eye and far planes as the renderer clips them, projected
through XF 0x1020-0x1026 and the viewport, culled as GEN_MODE says, clipped to
the 640x480 screen. Overdraw counts each time, the scissor, depth and alpha
tests are ignored, and lines and points count as nothing. So it estimates the
fragments a draw rasterizes, not the pixels it leaves visible: on ten corpus
captures (0500 to 15200, 2026-09-24) the frame total agreed with a standalone
replay's rasterized count -- pixels shaded plus failed alpha plus failed
depth, from the "[gxr] ... pixels shaded" line -- to within 0.1%, and the
triangle count exactly.

Analysis only: reads the three files of each capture and writes nothing.
"""

import argparse
import bisect
import hashlib
import json
import math
import re
import struct
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import fifo

SCREEN_W, SCREEN_H = 640, 480
KILL_LINE = 0.90  # the plan's threshold on the share of N+1's area that is matched
W_MIN = 1e-5  # the renderer's eye plane (gxr.c clip_dist CLIP_W)
Z_FAR_SLACK = 1.0 / 8388608.0  # the renderer's far-plane slack (gxr.c Z_FAR_SLACK)

KEY_FIELDS = ("dl", "arrays", "textures", "prim", "count", "tev")
KEY_NAMES = {
    "dl": "display list",
    "arrays": "array bases",
    "textures": "textures",
    "prim": "primitive",
    "count": "vertex count",
    "tev": "TEV hash",
}

# Per-vertex screen displacement, pixels: exactly zero, then these upper edges.
DISP_EDGES = (0.25, 1, 2, 4, 8, 16, 32, 64, 128)
DISP_LABELS = ("0", "<0.25", "0.25-1", "1-2", "2-4", "4-8", "8-16", "16-32", "32-64", "64-128")
DISP_LABELS += (">=128",)

AREA_NOTE = (
    "area is an estimate, not a pixel count: the command stream carries no per-draw "
    "fragment counts, so each draw's area is the sum of its triangles' projected areas "
    "(near/eye/far-clipped as the renderer clips, culled as GEN_MODE says, clipped to "
    "the 640x480 screen); overdraw counts every time, scissor/depth/alpha tests are "
    "ignored, lines and points count as nothing"
)


@dataclass(slots=True, eq=False)
class Draw:
    """One draw as the hardware would have seen it."""

    seq: int  # 1-based stream order, display lists followed (so not fifo.py's DRAW #)
    prim: int  # 0x80 QUADS .. 0xB8 POINTS
    vat: int
    count: int
    dl: int | None  # address of the display list it came through; None when direct
    arrays: tuple  # (array, base) for each array the vertex layout indexes
    textures: tuple  # texture address of each enabled TEV stage, in stage order
    tev: str  # hash of the TEV setup, see tev_hash
    pmtx: tuple  # position-matrix indices, in order of first use
    matrices: tuple  # the twelve raw XF words of each of those matrices
    model: list  # per vertex: position as read, or None when it could not be
    view: list  # per vertex: after the position matrix, or None
    screen: list  # per vertex: (x, y) in pixels, or None behind the eye or unresolved
    area: float = 0.0  # estimated covered pixels
    ortho: bool = False  # drawn through an orthographic projection: the 2D layer
    offset: int = 0  # where the command sits: in the .fifo, or in its display list
    copies_before: int = 0  # EFB copies to texture earlier in the frame
    wiped: bool = False  # a later clearing copy to texture takes it off the EFB

    def key(self, drop: str | None = None) -> tuple:
        return tuple(getattr(self, f) for f in KEY_FIELDS if f != drop)


@dataclass(slots=True)
class Frame:
    draws: list = field(default_factory=list)
    list_calls: int = 0
    empty_list_calls: int = 0  # calls whose size is zero: nothing in them to draw
    texture_copies: int = 0
    unresolved: int = 0  # vertices whose position could not be read


# --------------------------------------------------------------------------
# state a draw runs under
# --------------------------------------------------------------------------


def tev_stages(bp) -> int:
    return ((bp[0x00] >> 10) & 15) + 1


def tev_hash(bp) -> str:
    """The combiner setup: GEN_MODE's counts, each active stage's order (TREF)
    and colour and alpha environments, the KSEL swap tables and konst
    selectors, and the alpha compare. The TEV colour and konst registers
    (BP E0-E7) are values rather than setup -- a fade animates them while the
    draw stays the same draw -- so they are left out."""
    words = [bp[0x00] & 0x73C7F]  # texgens, colour channels, TEV and indirect stages
    for st in range(tev_stages(bp)):
        words.append((bp[0x28 + st // 2] >> (12 * (st & 1))) & 0xFFF)
        words.append(bp[0xC0 + 2 * st] & 0xFFFFFF)
        words.append(bp[0xC1 + 2 * st] & 0xFFFFFF)
    words.extend(bp[r] & 0xFFFFFF for r in range(0xF6, 0xFE))
    words.append(bp[0xF3] & 0xFFFFFF)
    blob = struct.pack(f"<{len(words)}I", *words)
    return hashlib.blake2b(blob, digest_size=6).hexdigest()


def texture_addresses(bp) -> tuple:
    """The image address each enabled stage samples, as gxr_tev.c tev_prepare
    resolves it: TREF names the map, TX_IMAGE3 of that map holds address >> 5."""
    out = []
    for st in range(tev_stages(bp)):
        tref = bp[0x28 + st // 2] >> (12 * (st & 1))
        if (tref >> 6) & 1:
            m = tref & 7
            rb = m if m < 4 else 0x20 + (m - 4)
            out.append((bp[0x94 + rb] & 0x1FFFFF) << 5)
    return tuple(out)


def array_bases(layout, cp) -> tuple:
    return tuple(
        (at.array, cp.get(0xA0 + at.array, 0) & 0x1FFFFFFF) for at in layout if at.mode >= 2
    )


def clip_space(xf, view) -> tuple:
    """View space to clip space through the projection (gxr.c transform)."""
    p0, p1, p2, p3, p4, p5 = (fifo.xff(xf, 0x1020 + i) for i in range(6))
    x, y, z = view
    if xf[0x1026] & 1:  # orthographic
        return (p0 * x + p1, p2 * y + p3, p4 * z + p5, 1.0)
    return (p0 * x + p1 * z, p2 * y + p3 * z, p4 * z + p5, -z)


def viewport(xf, bp) -> tuple:
    """(width, height, x origin, y origin) as gxr.c raster_prepare takes them,
    the scissor offset (BP 59) already subtracted."""
    off = bp[0x59]
    return (
        fifo.xff(xf, 0x101A),
        fifo.xff(xf, 0x101B),
        fifo.xff(xf, 0x101D) - (off & 0x3FF) * 2,
        fifo.xff(xf, 0x101E) - ((off >> 10) & 0x3FF) * 2,
    )


def project(vp, c) -> tuple:
    wd, ht, xo, yo = vp
    iw = 1.0 / c[3]
    return (xo + c[0] * iw * wd, yo + c[1] * iw * ht)


# --------------------------------------------------------------------------
# area
# --------------------------------------------------------------------------


def triangles(prim: int, n: int):
    """Index triples in the order and winding the renderer rasterizes them
    (gxr.c draw_command); lines and points have none."""
    if prim == 0x80:
        for i in range(0, n - 3, 4):
            yield i, i + 1, i + 2
            yield i, i + 2, i + 3
    elif prim == 0x90:
        for i in range(0, n - 2, 3):
            yield i, i + 1, i + 2
    elif prim == 0x98:
        for i in range(2, n):
            yield (i - 1, i - 2, i) if i & 1 else (i - 2, i - 1, i)
    elif prim == 0xA0:
        for i in range(2, n):
            yield 0, i - 1, i


def _unclipped(c) -> bool:
    return c[2] + c[3] >= 0.0 and c[3] > 0.0 and c[3] * Z_FAR_SLACK - c[2] >= 0.0


_PLANES = (
    lambda c: c[2] + c[3],  # near
    lambda c: c[3] - W_MIN,  # the eye
    lambda c: c[3] * Z_FAR_SLACK - c[2],  # far
)


def _clip(poly, dist):
    """Sutherland-Hodgman against one plane, positive inside."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da, db = dist(a), dist(b)
        if da >= 0.0:
            out.append(a)
        if (da >= 0.0) != (db >= 0.0):
            t = da / (da - db)
            out.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(len(a))))
    return out


_SCREEN_EDGES = (
    lambda p: p[0],
    lambda p: SCREEN_W - p[0],
    lambda p: p[1],
    lambda p: SCREEN_H - p[1],
)


def _twice_signed_area(poly) -> float:
    s = 0.0
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s


def _on_screen(poly, twice: float) -> float:
    if all(0.0 <= x <= SCREEN_W and 0.0 <= y <= SCREEN_H for x, y in poly):
        return abs(twice) / 2.0
    for edge in _SCREEN_EDGES:
        poly = _clip(poly, edge)
        if len(poly) < 3:
            return 0.0
    return abs(_twice_signed_area(poly)) / 2.0


def draw_area(prim: int, clip: list, vp: tuple, cull: int) -> float:
    """Estimated pixels a draw covers. `clip` holds each vertex in clip space
    (None where unresolved); `cull` is GEN_MODE's mode: 1 drops triangles
    whose screen area is negative, 2 positive, 3 all (gxr.c raster_triangle)."""
    if cull == 3:
        return 0.0
    screen = [project(vp, c) if c is not None and _unclipped(c) else None for c in clip]
    total = 0.0
    for a, b, c in triangles(prim, len(clip)):
        ca, cb, cc = clip[a], clip[b], clip[c]
        if ca is None or cb is None or cc is None:
            continue
        if screen[a] is not None and screen[b] is not None and screen[c] is not None:
            poly = [screen[a], screen[b], screen[c]]
        else:
            poly = [ca, cb, cc]
            for plane in _PLANES:
                poly = _clip(poly, plane)
                if len(poly) < 3:
                    break
            if len(poly) < 3:
                continue
            poly = [project(vp, v) for v in poly]
        twice = _twice_signed_area(poly)
        if twice == 0.0 or (cull == 1 and twice < 0.0) or (cull == 2 and twice > 0.0):
            continue
        total += _on_screen(poly, twice)
    return total


# --------------------------------------------------------------------------
# a frame's draws
# --------------------------------------------------------------------------


def _draw(seq, op, n, layout, buf, off, where, rel, cp, xf, bp, ram) -> Draw:
    default = xf[0x1018] & 0x3F
    idxs: list[int] = []
    model, view, clip = [], [], []
    for _ in range(n):
        vals, off = fifo.read_vertex(layout, buf, off, cp, ram)
        idx = vals.get("pmtx", default) & 0x3F
        if idx not in idxs:
            idxs.append(idx)
        pos = vals.get("pos")
        if pos is None:
            model.append(None)
            view.append(None)
            clip.append(None)
            continue
        v = tuple(fifo.transform_position(xf, idx, pos))
        model.append(tuple(pos))
        view.append(v)
        clip.append(clip_space(xf, v))
    vp = viewport(xf, bp)
    return Draw(
        seq=seq,
        prim=op & 0xF8,
        vat=op & 7,
        count=n,
        dl=where,
        arrays=array_bases(layout, cp),
        textures=texture_addresses(bp),
        tev=tev_hash(bp),
        pmtx=tuple(idxs),
        matrices=tuple(tuple(xf[4 * i : 4 * i + 12]) for i in idxs),
        model=model,
        view=view,
        screen=[project(vp, c) if c is not None and c[3] > 0.0 else None for c in clip],
        area=draw_area(op & 0xF8, clip, vp, (bp[0x00] >> 14) & 3),
        ortho=bool(xf[0x1026] & 1),
        offset=rel,
    )


def frame_draws(stream: bytes, cp_regs, xf_regs, bp_regs, ram=None) -> Frame:
    """Every draw of one frame, in stream order. The register images are the
    state at frame start, as a .regs file holds them."""
    cp = {i: v for i, v in enumerate(cp_regs) if v}
    xf = list(xf_regs)
    bp = list(bp_regs)
    frame = Frame()
    last_wipe = 0
    for cmd in fifo.walk(stream, cp, xf, ram, bp, follow_lists=True):
        kind = cmd[0]
        if kind == "call":
            frame.list_calls += 1
            frame.empty_list_calls += cmd[4] == 0
        elif kind == "bp" and cmd[3] == 0x52 and not cmd[4] & 0x4000:
            frame.texture_copies += 1
            if cmd[4] & 0x800:  # the copy clears the EFB behind it
                last_wipe = len(frame.draws)
        elif kind == "draw":
            op, n, layout, _vs, buf, voff = cmd[3:]
            if n == 0:  # the renderer skips these too
                continue
            d = _draw(
                len(frame.draws) + 1, op, n, layout, buf, voff, cmd[2], cmd[1], cp, xf, bp, ram
            )
            d.copies_before = frame.texture_copies
            frame.unresolved += sum(p is None for p in d.model)
            frame.draws.append(d)
    for d in frame.draws[:last_wipe]:
        d.wiped = True
    return frame


def load_frame(base) -> Frame:
    base = str(base)
    cp_regs, xf_regs, bp_regs = fifo.read_regs(base + ".regs")
    ram_path = Path(base + ".ram")
    ram = ram_path.read_bytes() if ram_path.exists() else None
    if ram is None:
        print(
            f"note: {ram_path} is missing; indexed attributes and display lists cannot be read",
            file=sys.stderr,
        )
    return frame_draws(Path(base + ".fifo").read_bytes(), cp_regs, xf_regs, bp_regs, ram)


# --------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------


def match(a: list, b: list, key) -> list:
    """Pair each draw of `b` with an unpaired draw of `a` whose key is equal,
    in stream order within a key. Returns (index in a, index in b), b ascending."""
    pool: dict = defaultdict(deque)
    for i, d in enumerate(a):
        pool[key(d)].append(i)
    pairs = []
    for j, d in enumerate(b):
        q = pool.get(key(d))
        if q:
            pairs.append((q.popleft(), j))
    return pairs


def moved(order: list) -> int:
    """How many entries must move to put `order` back in ascending order:
    its length less its longest increasing subsequence."""
    tails: list = []
    for x in order:
        i = bisect.bisect_left(tails, x)
        if i == len(tails):
            tails.append(x)
        else:
            tails[i] = x
    return len(order) - len(tails)


def disp_bin(d: float) -> int:
    return 0 if d == 0.0 else 1 + bisect.bisect_right(DISP_EDGES, d)


def _share(x, total):
    return None if not total else x / total


def _area(draws) -> float:
    return sum(d.area for d in draws)


def _frame_summary(f: Frame) -> dict:
    via = [d for d in f.draws if d.dl is not None]
    direct = [d for d in f.draws if d.dl is None]
    wiped = [d for d in f.draws if d.wiped]
    return {
        "draws": len(f.draws),
        "vertices": sum(d.count for d in f.draws),
        "unresolved_vertices": f.unresolved,
        "area": _area(f.draws),
        "through_list": {"draws": len(via), "area": _area(via)},
        "direct": {"draws": len(direct), "area": _area(direct)},
        "list_calls": f.list_calls,
        "empty_list_calls": f.empty_list_calls,
        "texture_copies": f.texture_copies,
        "wiped": {"draws": len(wiped), "area": _area(wiped)},
    }


def _describe(d: Draw) -> dict:
    return {
        "seq": d.seq,
        "prim": fifo.PRIMS.get(d.prim, hex(d.prim)),
        "count": d.count,
        "area": d.area,
        "dl": None if d.dl is None else f"{d.dl:08X}",
        "arrays": [[a, f"{base:08X}"] for a, base in d.arrays],
        "textures": [f"{t:08X}" for t in d.textures],
        "tev": d.tev,
        "pmtx": list(d.pmtx),
        "ortho": d.ortho,
    }


def pair_report(fa: Frame, fb: Frame, top: int = 10) -> dict:
    """Everything the H4 question asks of one pair; see the module docstring."""
    A, B = fa.draws, fb.draws
    total = _area(B)
    pairs = match(A, B, lambda d: d.key())
    got_a = {i for i, _ in pairs}
    got_b = {j for _, j in pairs}

    # What changed in a matched draw: nothing, only its matrices, or the vertex
    # data itself -- the last is what interpolating XF matrices cannot follow.
    change = {k: {"draws": 0, "area": 0.0} for k in ("none", "matrices", "vertex_data")}
    same_mtx = 0
    hist = [0] * len(DISP_LABELS)
    no_screen = 0
    disps = []
    for i, j in pairs:
        a, b = A[i], B[j]
        mtx_equal = a.pmtx == b.pmtx and a.matrices == b.matrices
        same_mtx += mtx_equal
        kind = "vertex_data" if a.model != b.model else ("none" if mtx_equal else "matrices")
        change[kind]["draws"] += 1
        change[kind]["area"] += b.area
        for sa, sb in zip(a.screen, b.screen, strict=True):
            if sa is None or sb is None:
                no_screen += 1
                continue
            d = math.hypot(sb[0] - sa[0], sb[1] - sa[1])
            disps.append(d)
            hist[disp_bin(d)] += 1
    disps.sort()

    # The vertex count is in the key, so every matched pair has equal counts by
    # construction; pairing without it is what says how many draws that costs.
    loose = match(A, B, lambda d: d.key("count"))
    loose_equal = sum(A[i].count == B[j].count for i, j in loose)

    # Unmatched draws of N+1 that dropping one key field would pair, against
    # the unmatched draws of N: which field is costing the matches.
    rest_a = [i for i in range(len(A)) if i not in got_a]
    rest_b = [j for j in range(len(B)) if j not in got_b]
    near = {}
    fields_for = defaultdict(list)
    for f in KEY_FIELDS:
        pp = match([A[i] for i in rest_a], [B[j] for j in rest_b], lambda d, f=f: d.key(f))
        js = [rest_b[jj] for _, jj in pp]
        near[f] = {"draws": len(js), "area": sum(B[j].area for j in js)}
        for j in js:
            fields_for[j].append(f)

    def route(pick):
        mine = [j for j in range(len(B)) if pick(B[j])]
        hit = [j for j in mine if j in got_b]
        area = sum(B[j].area for j in mine)
        hit_area = sum(B[j].area for j in hit)
        return {
            "draws": len(mine),
            "area": area,
            "matched_draws": len(hit),
            "matched_area": hit_area,
            "matched_area_share": _share(hit_area, area),
        }

    unmatched = sorted(rest_b, key=lambda j: -B[j].area)[:top]
    matched_area = sum(B[j].area for j in got_b)
    return {
        "area_note": AREA_NOTE,
        "key": [KEY_NAMES[f] for f in KEY_FIELDS],
        "frames": {"n": _frame_summary(fa), "n1": _frame_summary(fb)},
        "matched": {
            "draws": len(pairs),
            "draw_share": _share(len(pairs), len(B)),
            "area": matched_area,
            "area_share": _share(matched_area, total),
            "below_kill_line": None if not total else matched_area / total < KILL_LINE,
            "equal_counts_share": _share(len(pairs), len(pairs)),
            "equal_matrices": same_mtx,
            "equal_matrices_share": _share(same_mtx, len(pairs)),
            "changed": change,
            "order_changed": moved([i for i, _ in pairs]),
        },
        "without_count": {
            "draws": len(loose),
            "equal_counts": loose_equal,
            "equal_counts_share": _share(loose_equal, len(loose)),
        },
        "displacement": {
            "labels": list(DISP_LABELS),
            "vertices": hist,
            "no_screen_position": no_screen,
            "p50": disps[len(disps) // 2] if disps else None,
            "p95": disps[min(len(disps) - 1, (95 * len(disps)) // 100)] if disps else None,
            "max": disps[-1] if disps else None,
        },
        "routes": {
            "through_list": route(lambda d: d.dl is not None),
            "direct": route(lambda d: d.dl is None),
            "perspective": route(lambda d: not d.ortho),
            "orthographic": route(lambda d: d.ortho),
            "wiped": route(lambda d: d.wiped),
        },
        "near_miss": near,
        "largest_unmatched": [
            dict(_describe(B[j]), would_match_without=fields_for.get(j, [])) for j in unmatched
        ],
    }


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def _pct(x) -> str:
    return "n/a" if x is None else f"{100.0 * x:.1f}%"


ROUTES = (
    ("through_list", "through a display list"),
    ("direct", "direct"),
    ("perspective", "perspective (3D)"),
    ("orthographic", "orthographic (2D layer)"),
    ("wiped", "wiped by a clearing copy"),
)


def format_report(rep: dict, name_a: str = "N", name_b: str = "N+1") -> str:
    fa, fb = rep["frames"]["n"], rep["frames"]["n1"]
    m, wc, dsp = rep["matched"], rep["without_count"], rep["displacement"]
    out = [f"fifopair  N = {name_a}   N+1 = {name_b}", f"note: {rep['area_note']}", ""]

    def row(label, a, b):
        out.append(f"  {label:<38}{a:>16}{b:>16}")

    def line(label, value):
        out.append(f"  {label:<38}{value}")

    def split(part):
        return f"{part['draws']} / {part['area']:.0f}"

    row("", "frame N", "frame N+1")
    row("draws", fa["draws"], fb["draws"])
    row(
        "vertices (position unresolved)",
        f"{fa['vertices']} ({fa['unresolved_vertices']})",
        f"{fb['vertices']} ({fb['unresolved_vertices']})",
    )
    row("area, pixels", f"{fa['area']:.0f}", f"{fb['area']:.0f}")
    row(
        "  through a display list: draws / area",
        split(fa["through_list"]),
        split(fb["through_list"]),
    )
    row("  direct: draws / area", split(fa["direct"]), split(fb["direct"]))
    row(
        "display-list calls (of size zero)",
        f"{fa['list_calls']} ({fa['empty_list_calls']})",
        f"{fb['list_calls']} ({fb['empty_list_calls']})",
    )
    row("copies to texture", fa["texture_copies"], fb["texture_copies"])
    row("  draws a clearing copy wipes / area", split(fa["wiped"]), split(fb["wiped"]))
    out.append("")

    out.append(f"Matched on ({', '.join(rep['key'])}), in stream order within a key:")
    verdict = ""
    if m["below_kill_line"] is not None:
        verdict = "  UNDER the ~90% kill line" if m["below_kill_line"] else "  at or over ~90%"
    line("area of N+1 from matched draws", _pct(m["area_share"]) + verdict)
    line("draws of N+1 matched", f"{m['draws']} of {fb['draws']} ({_pct(m['draw_share'])})")
    line("equal vertex counts", f"{_pct(m['equal_counts_share'])} (the count is in the key)")
    line(
        "  pairing without the count",
        f"{wc['draws']} pairs, {wc['equal_counts']} ({_pct(wc['equal_counts_share'])}) "
        "with equal counts",
    )
    line(
        "position matrices identical",
        f"{m['equal_matrices']} ({_pct(m['equal_matrices_share'])})",
    )
    line("out of stream order", f"{m['order_changed']} (draws that must move to restore N's order)")
    out.append("  what changed in a matched draw, draws / area of N+1:")
    for k, label in (
        ("none", "nothing"),
        ("matrices", "matrices only"),
        ("vertex_data", "vertex data"),
    ):
        line(f"  {label}", split(m["changed"][k]))
    out.append("  N+1 by route, draws matched / all, area matched:")
    for k, label in ROUTES:
        r = rep["routes"][k]
        line(
            f"  {label}",
            f"{r['matched_draws']} / {r['draws']}, {_pct(r['matched_area_share'])} "
            f"of {r['area']:.0f} px",
        )
    out.append("")

    out.append("Screen displacement per vertex of matched draws, pixels:")
    for label, n in zip(dsp["labels"], dsp["vertices"], strict=True):
        out.append(f"  {label:>8} {n:>10}")
    out.append(f"  and {dsp['no_screen_position']} behind the eye or unresolved in either frame")
    if dsp["max"] is not None:
        out.append(f"  p50 {dsp['p50']:.3f}   p95 {dsp['p95']:.3f}   max {dsp['max']:.3f}")
    out.append("")

    out.append("Unmatched draws of N+1 that one relaxed key field would pair, draws / area:")
    for f, v in rep["near_miss"].items():
        line(f"  without {KEY_NAMES[f]}", split(v))
    if rep["largest_unmatched"]:
        out.append("")
        out.append("Largest unmatched draws of N+1:")
        for d in rep["largest_unmatched"]:
            where = f"list {d['dl']}" if d["dl"] else "direct"
            proj = "ortho" if d["ortho"] else "persp"
            tex = ",".join(d["textures"]) or "-"
            fix = ",".join(d["would_match_without"]) or "-"
            out.append(
                f"  #{d['seq']:<6}{d['prim']:<10}x{d['count']:<6}{d['area']:>10.0f} px  "
                f"{where} {proj}  tex {tex}  tev {d['tev']}  pairs without: {fix}"
            )
    return "\n".join(out)


def _consecutive(a: str, b: str) -> str:
    na, nb = re.fullmatch(r"\d+", Path(a).name), re.fullmatch(r"\d+", Path(b).name)
    if na and nb and int(nb.group()) != int(na.group()) + 1:
        return f"note: {Path(a).name} and {Path(b).name} are not consecutive frames"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("frame_n", help="capture base of frame N (the path without .fifo)")
    ap.add_argument("frame_n1", help="capture base of frame N+1")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument(
        "--top", type=int, default=10, metavar="K", help="list the K largest unmatched draws"
    )
    args = ap.parse_args(argv)
    rep = pair_report(load_frame(args.frame_n), load_frame(args.frame_n1), top=args.top)
    rep["bases"] = [args.frame_n, args.frame_n1]
    note = _consecutive(args.frame_n, args.frame_n1)
    if note:
        print(note, file=sys.stderr)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(format_report(rep, args.frame_n, args.frame_n1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
