#!/usr/bin/env python3
"""The in-between image of two consecutive frames, judged (PLAN-60FPS-MODS H10).

    python tools/midpoint.py                    # the five pairs in build/perfset
    python tools/midpoint.py field battle       # some of them
    python tools/midpoint.py --threads 4

Each pair is replayed with `gen/soa.exe --replay F F+1`, which renders F, then
F+1, then F+1 again with every draw matched in F moved to the point between
(runtime/gxr.c, "frame pairs"). The replays run one at a time, on copies in a
scratch directory, after the captures are checked against
`config/perfset_manifest.tsv` the way perfbench.py checks them. Then:

  - pass 2 of the pair must be F+1 exactly as a single replay draws it;
  - the pairs the renderer wrote must be fifopair.match's on the same captures,
    as many as H4 counted;
  - the in-between image must not depend on the thread count;
  - F paired with itself must give F, and t=1 must give F+1;
  - a copy of F+1 with one texture address changed must lose the same pairs in
    both implementations, and at least one.

It also counts the pixels between the t=0 image and F, the cost of moving
positions alone (colours and texture coordinates are F+1's). The images land
in `build/midpoint/<scene>/` for a person to open -- F.png, mid.png, F1.png,
t0.png and diff.png (magenta where the in-between image differs from F+1) --
and nothing here pins a hash: an in-between image has nothing to be compared
with but the eye, and the first bless is the dangerous one (CLAUDE.md).
"""

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fifo  # noqa: E402
import fifopair  # noqa: E402
import perfbench  # noqa: E402

EXE = ROOT / "gen" / "soa.exe"
SET = ROOT / "build" / "perfset"
OUT = ROOT / "build" / "midpoint"


@dataclass(frozen=True)
class Pair:
    f: str
    f1: str
    h4: tuple  # (draws matched, draws of F+1), FINDINGS "H4"


PAIRS = {
    "field": Pair("field/5000", "field/5001", (1144, 1147)),
    "battle": Pair("battle/4000", "battle/4001", (1390, 1393)),
    "ship": Pair("ship/6000", "ship/6001", (1514, 1665)),
    "cutscene": Pair("cutscene/4500", "cutscene/4501", (4146, 4280)),
    "sky": Pair("sky/4000", "sky/4001", (765, 765)),
}

HASH = re.compile(r"\[gxr\] frame \d+ \d+x\d+ hash ([0-9a-f]{16})")
REPORT = re.compile(
    r"\[pair\] midpoint at t=([\d.]+): (\d+) of (\d+) draws matched \((\d+) vertices interpolated\), "
    r"(\d+) drawn from F\+1, (\d+) demoted \(projection type differs\), (\d+) copies to texture "
    r"skipped \((\d+) clears kept\), (\d+) over capacity; largest displacement ([\d.]+) px, "
    r"(\d+) matched draws with a vertex over 32 px; peak (\d+) draws / (\d+) vertices a frame"
)
REPORT_KEYS = (
    "t",
    "matched",
    "draws",
    "vertices",
    "from_f1",
    "demoted",
    "skipped",
    "kept",
    "over",
    "largest",
    "over32",
    "peak_draws",
    "peak_vertices",
)
TEXTURE_REGS = frozenset((*range(0x94, 0x98), *range(0xB4, 0xB8)))


def parse_one(text: str) -> str:
    hashes = HASH.findall(text)
    if len(hashes) != 1:
        raise ValueError(f"a single replay presents one frame, this one {len(hashes)}")
    return hashes[0]


def parse_pair(text: str) -> dict:
    hashes = HASH.findall(text)
    m = REPORT.search(text)
    if len(hashes) != 3 or not m:
        raise ValueError(f"a pair replay presents three frames and a [pair] report: {hashes}")
    rep = {
        k: (float(v) if k in ("t", "largest") else int(v))
        for k, v in zip(REPORT_KEYS, m.groups(), strict=True)
    }
    return {"hashes": hashes, "report": rep}


def read_pairs(path: Path) -> list:
    words = path.read_text(encoding="utf-8").split()
    return [(int(a), int(b)) for a, b in zip(words[::2], words[1::2], strict=True)]


@dataclass
class Verdict:
    name: str
    ok: bool
    detail: str


def verdicts(scene: str, runs: dict, want: list, want_mut: list) -> list:
    """Every check on one pair. `runs` holds the parsed replays: "mid" (t=0.5),
    "mid1" (the same at one thread), "one" (F+1 alone, a hash), "t1", "self"
    ((F, F)) and "mut" (F with the changed F+1), each pair run with its
    "pairs"; `want` and `want_mut` are fifopair.match on the same captures."""
    pair, mid = PAIRS[scene], runs["mid"]
    lost = sorted(set(want) - set(want_mut))
    out = [
        Verdict(
            "pass 2 is F+1 as a single replay draws it",
            mid["hashes"][1] == runs["one"],
            f"{mid['hashes'][1]} / {runs['one']}",
        ),
        Verdict(
            "the pairs are fifopair's",
            mid["pairs"] == want,
            f"{len(mid['pairs'])} written, {len(want)} from fifopair.match",
        ),
        Verdict(
            "as many as H4 counted",
            (len(mid["pairs"]), mid["report"]["draws"]) == pair.h4,
            f"{len(mid['pairs'])} of {mid['report']['draws']}; H4 {pair.h4[0]} of {pair.h4[1]}",
        ),
        Verdict(
            "the same images at one thread",
            runs["mid1"]["hashes"] == mid["hashes"] and runs["mid1"]["pairs"] == mid["pairs"],
            f"in-between {runs['mid1']['hashes'][2]} / {mid['hashes'][2]}",
        ),
        Verdict(
            "F with itself is F",
            runs["self"]["hashes"][2] == runs["self"]["hashes"][1],
            f"{runs['self']['hashes'][2]} / {runs['self']['hashes'][1]}",
        ),
        Verdict(
            "t=1 is F+1",
            runs["t1"]["hashes"][2] == runs["t1"]["hashes"][1],
            f"{runs['t1']['hashes'][2]} / {runs['t1']['hashes'][1]}",
        ),
        Verdict(
            "a changed texture address loses the same pairs in both",
            runs["mut"]["pairs"] == want_mut and bool(lost),
            f"{len(lost)} lost: {lost[:4]}{' ...' if len(lost) > 4 else ''}",
        ),
    ]
    return out


# --------------------------------------------------------------------------
# images: the port's own PNGs only (runtime/png.c: 8-bit RGBA, filter 0)
# --------------------------------------------------------------------------


def read_rgba(path: Path) -> tuple:
    d = path.read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    i, idat, w, h = 8, [], 0, 0
    while i + 8 <= len(d):
        n = int.from_bytes(d[i : i + 4], "big")
        tag, body = d[i + 4 : i + 8], d[i + 8 : i + 8 + n]
        if tag == b"IHDR":
            w, h = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big")
            if (body[8], body[9]) != (8, 6):
                raise ValueError(f"{path}: not 8-bit RGBA, so not the port's")
        elif tag == b"IDAT":
            idat.append(body)
        i += 12 + n
    if not w:
        raise ValueError(f"{path}: no IHDR")
    raw = zlib.decompress(b"".join(idat))
    stride = 1 + w * 4
    if any(raw[y * stride] for y in range(h)):
        raise ValueError(f"{path}: a filtered row, so not the port's")
    return w, h, b"".join(raw[y * stride + 1 : (y + 1) * stride] for y in range(h))


def write_rgba(path: Path, w: int, h: int, rgba: bytes) -> None:
    def chunk(tag: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(tag + body).to_bytes(4, "big")
        return len(body).to_bytes(4, "big") + tag + body + crc

    raw = b"".join(b"\x00" + rgba[y * w * 4 : (y + 1) * w * 4] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def differing(a: bytes, b: bytes) -> int:
    """Pixels whose colour differs between two images of one size."""
    if len(a) != len(b):
        raise ValueError("images of different sizes")
    return sum(
        x != y for x, y in zip(memoryview(a).cast("I"), memoryview(b).cast("I"), strict=True)
    )


def difference(a: bytes, b: bytes) -> bytes:
    """`b` at a third of its brightness, magenta wherever `a` differs from it."""
    out = bytearray(len(b))
    pa, pb = memoryview(a).cast("I"), memoryview(b).cast("I")
    for i, (x, y) in enumerate(zip(pa, pb, strict=True)):
        o = i * 4
        if x != y:
            out[o : o + 4] = b"\xff\x00\xff\xff"
        else:
            out[o] = b[o] // 3
            out[o + 1] = b[o + 1] // 3
            out[o + 2] = b[o + 2] // 3
            out[o + 3] = 255
    return bytes(out)


# --------------------------------------------------------------------------
# the mutated capture
# --------------------------------------------------------------------------


def texture_writes(stream: bytes, base: Path) -> list:
    """Stream offsets of the texture-address writes in F+1's own stream."""
    cp_regs, xf_regs, bp_regs = fifo.read_regs(str(base) + ".regs")
    cp = {i: v for i, v in enumerate(cp_regs) if v}
    return [
        c[1]
        for c in fifo.walk(stream, cp, list(xf_regs), None, list(bp_regs))
        if c[0] == "bp" and c[2] is None and c[3] in TEXTURE_REGS
    ]


def mutate(stream: bytes, offset: int) -> bytes:
    """The stream with the texture address written at `offset` moved by 32
    bytes: still in memory, and a different key."""
    if stream[offset] != 0x61:
        raise ValueError(f"no BP write at {offset:#x}")
    out = bytearray(stream)
    out[offset + 4] ^= 1
    return bytes(out)


def pick_mutation(fa, f1: Path, want: list, tries: int = 16) -> tuple:
    """The first texture-address change in F+1 that costs fifopair exactly one
    pair, else the one that costs fewest: (stream, offset, pairs left)."""
    stream = f1.with_suffix(".fifo").read_bytes()
    regs = fifo.read_regs(str(f1) + ".regs")
    ram = f1.with_suffix(".ram").read_bytes()
    best = None
    for off in texture_writes(stream, f1)[:tries]:
        s = mutate(stream, off)
        fb = fifopair.frame_draws(s, *regs, ram)
        left = fifopair.match(fa.draws, fb.draws, lambda d: d.key())
        lost = len(set(want) - set(left))
        if lost and (best is None or lost < best[0]):
            best = (lost, s, off, left)
        if lost == 1:
            break
    if best is None:
        raise ValueError(f"{f1}: no texture-address change in the first {tries} costs a pair")
    return best[1:]


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------


def replay(exe: Path, args: list, threads: int, **env) -> str:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    extra = {"SOA_HASH": "1", "SOA_SETTINGS": "0", "SOA_THREADS": str(threads)}
    extra.update({k: str(v) for k, v in env.items()})
    proc = subprocess.run(
        [str(exe), "--replay", *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**clean, **extra},
        timeout=600,
        check=False,
    )
    text = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"--replay {' '.join(map(str, args))}: exit {proc.returncode}\n{text}")
    return text


def judge(scene: str, threads: int, exe: Path = EXE, root: Path = SET, out: Path = OUT) -> bool:
    pair = PAIRS[scene]
    where = out / scene
    shutil.rmtree(where, ignore_errors=True)
    where.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        f, f1 = tmp / Path(pair.f).name, tmp / Path(pair.f1).name
        for src, dst in ((root / pair.f, f), (root / pair.f1, f1)):
            for p in perfbench.PARTS:
                shutil.copyfile(src.with_suffix(p), dst.with_suffix(p))
        fa, fb = fifopair.load_frame(f), fifopair.load_frame(f1)
        want = fifopair.match(fa.draws, fb.draws, lambda d: d.key())
        stream, off, want_mut = pick_mutation(fa, f1, want)
        mut = tmp / "mut"
        mut.with_suffix(".fifo").write_bytes(stream)
        for p in (".regs", ".ram"):
            shutil.copyfile(f1.with_suffix(p), mut.with_suffix(p))

        def pair_run(a, b, t, n, name):
            listing = tmp / f"{name}.pairs"
            res = parse_pair(replay(exe, [a, b], n, SOA_PAIR_T=t, SOA_PAIR_LIST=listing))
            res["pairs"] = read_pairs(listing)
            return res

        runs = {"mid": pair_run(f, f1, 0.5, threads, "mid")}
        shutil.copyfile(f.with_suffix(".png"), where / "F.png")
        shutil.copyfile(f1.with_suffix(".png"), where / "F1.png")
        shutil.copyfile(f1.with_suffix(".mid.png"), where / "mid.png")
        runs["one"] = parse_one(replay(exe, [f1], threads))
        runs["t1"] = pair_run(f, f1, 1, threads, "t1")
        runs["t0"] = pair_run(f, f1, 0, threads, "t0")
        shutil.copyfile(f1.with_suffix(".mid.png"), where / "t0.png")
        runs["self"] = pair_run(f, f, 0.5, threads, "self")
        runs["mid1"] = pair_run(f, f1, 0.5, 1, "mid1")
        runs["mut"] = pair_run(f, mut, 0.5, threads, "mut")

    w, h, img_f = read_rgba(where / "F.png")
    _, _, img_f1 = read_rgba(where / "F1.png")
    _, _, img_mid = read_rgba(where / "mid.png")
    _, _, img_t0 = read_rgba(where / "t0.png")
    write_rgba(where / "diff.png", w, h, difference(img_mid, img_f1))
    rep = runs["mid"]["report"]
    print(f"{scene} ({pair.f} / {pair.f1}), {threads} threads, texture write at {off:#x} changed")
    print(
        f"  {rep['matched']} of {rep['draws']} draws matched ({rep['vertices']} vertices), "
        f"{rep['from_f1']} from F+1, {rep['demoted']} demoted, {rep['skipped']} copies skipped "
        f"({rep['kept']} clears kept), {rep['over']} over capacity; largest displacement "
        f"{rep['largest']:.1f} px, {rep['over32']} draws over 32 px; peak {rep['peak_draws']} draws, "
        f"{rep['peak_vertices']} vertices"
    )
    print(
        f"  pixels: in-between vs F+1 {differing(img_mid, img_f1)}, vs F {differing(img_mid, img_f)}; "
        f"t=0 vs F {differing(img_t0, img_f)} (the cost of positions only)"
    )
    ok = True
    for v in verdicts(scene, runs, want, want_mut):
        mark = "ok  " if v.ok else "FAIL"
        print(f"  {mark:7} {v.name}: {v.detail}")
        ok &= v.ok
    print(f"  images: {where.relative_to(ROOT)}")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("scenes", nargs="*", metavar="scene", help=f"of {', '.join(PAIRS)}")
    ap.add_argument("--threads", type=int, default=8)
    args = ap.parse_args(argv)
    scenes = args.scenes or list(PAIRS)
    if unknown := [s for s in scenes if s not in PAIRS]:
        ap.error(f"no pair called {', '.join(unknown)}; the pairs are {', '.join(PAIRS)}")
    rows = perfbench.read_manifest()
    bad = []
    for scene in scenes:
        for name in (PAIRS[scene].f, PAIRS[scene].f1):
            if name not in rows:
                bad.append(f"{name}: not in {perfbench.MANIFEST.relative_to(ROOT)}")
            elif d := perfbench.verify(name, rows[name][1]):
                bad.append(f"{name}: {', '.join(d)} missing or changed since the manifest")
    if bad:
        for b in bad:
            print(f"midpoint: {b}", file=sys.stderr)
        return 1
    failed = [s for s in scenes if not judge(s, args.threads)]
    print(
        f"midpoint: {len(scenes) - len(failed)} of {len(scenes)} pairs pass"
        + (f"; failed {failed}" if failed else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
