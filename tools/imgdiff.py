"""The frame oracle: is a candidate frame close enough to its reference?

    python tools/imgdiff.py REF.png CAND.png [--heat out.png]
    python tools/imgdiff.py refs [--set corpus|perfset|gpuset] [--exe gen/soa.exe]
    python tools/imgdiff.py mutate [--set corpus|perfset]

A GPU renderer cannot reproduce the CPU renderer's frame hashes: edges,
interpolation and blending round differently. This is the tolerance that
judges it instead (specs/gpu-backend.md 3.12, V0), frozen before any GPU
frame exists so that no GPU frame can shape it.

For two 640x480 frames, d is the largest of |R-C| over red, green and blue
at a pixel. A pixel is exact at d = 0, near at 1-16 and far above 16. Blob
pixels are far pixels whose eight neighbours are all far: a missing or wrong
object leaves blobs, an edge drawn a pixel differently does not. MAE is the
mean absolute error over every pixel and channel, and bias the mean signed
error (candidate minus reference) per channel. A frame passes when all of
THRESHOLDS hold.

`refs` replays each capture of a set with gen/soa.exe --replay, from a
scratch copy (never build/fifo, whose PNGs a replay overwrites) and in a
sanitised environment, and keeps the frame in build/gpu-oracle/ref/<set>/.
For the corpus it requires the frame's FNV-1a to be config/fifo_manifest.tsv's.
`mutate` runs MUTATIONS over those references: the noise-like ones must pass
on every frame, the defect-like ones fail on every frame but a listed blind
spot -- the proof that the thresholds can fail, made before they are used.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import perfbench  # noqa: E402
import scenario  # noqa: E402
from soa import png  # noqa: E402

EXE = ROOT / "gen" / "soa.exe"
OUT = ROOT / "build" / "gpu-oracle"
GPUSET_MANIFEST = ROOT / "config" / "gpuset_manifest.tsv"
NEAR = 16  # d above this is far

# Frozen by V0 (FINDINGS "V0"), before any GPU frame existed. Which mutation
# fixed each is in that entry; changing one is its own commit, naming the
# inspected frames that justify it, and must still fail every mutation.
THRESHOLDS = {
    "far": 0.01,  # far pixels, as a fraction of the frame
    "blob": 64,  # blob pixels
    "largest": 32,  # the largest 8-connected blob
    "mae": 1.5,
    "bias": 0.75,  # |bias| on each channel
    "shift": 0.25,  # |S| on each axis: a one-pixel shift is 1.0, a half-pixel one about 0.5
    "blur": 0.10,  # |L| on each axis: a second 1:2:1 vertical filter is about 0.25
}


@dataclass
class Metrics:
    pixels: int
    exact: int
    near: int
    far: int
    blob: int
    largest: int
    mae: float
    bias: tuple[float, float, float]
    shift: tuple[float, float] = (0.0, 0.0)  # S along x and y
    blur: tuple[float, float] = (0.0, 0.0)  # L along x and y

    def failures(self) -> list[str]:
        t = THRESHOLDS
        out = []
        if self.far > t["far"] * self.pixels:
            out.append(f"far {self.far} > {t['far']:.0%} of {self.pixels}")
        if self.blob > t["blob"]:
            out.append(f"blob {self.blob} > {t['blob']}")
        if self.largest > t["largest"]:
            out.append(f"largest blob {self.largest} > {t['largest']}")
        if self.mae > t["mae"]:
            out.append(f"MAE {self.mae:.3f} > {t['mae']}")
        for name, b in zip("RGB", self.bias, strict=True):
            if abs(b) > t["bias"]:
                out.append(f"bias {name} {b:+.3f} beyond {t['bias']}")
        for kind, pair in (("shift", self.shift), ("blur", self.blur)):
            for axis, v in zip("xy", pair, strict=True):
                if abs(v) > t[kind]:
                    out.append(f"{kind} {axis} {v:+.3f} beyond {t[kind]}")
        return out

    def line(self) -> str:
        return (
            f"exact {self.exact}, near {self.near}, far {self.far} ({self.far / self.pixels:.3%}), "
            f"blob {self.blob} (largest {self.largest}), MAE {self.mae:.3f}, "
            f"bias {self.bias[0]:+.3f} {self.bias[1]:+.3f} {self.bias[2]:+.3f}, "
            f"shift {self.shift[0]:+.3f} {self.shift[1]:+.3f}, blur {self.blur[0]:+.3f} {self.blur[1]:+.3f}"
        )


def measure(w: int, h: int, ref: bytes, cand: bytes) -> tuple[Metrics, bytearray, bytearray]:
    """The metrics, and the far and blob masks (one byte a pixel)."""
    if len(ref) != w * h * 4 or len(cand) != len(ref):
        raise ValueError("the two images are not the same size")
    n = w * h
    far = bytearray(n)
    exact = near = 0
    abs_sum = 0
    sr = sg = sb = 0
    for i in range(n):
        o = i * 4
        dr = cand[o] - ref[o]
        dg = cand[o + 1] - ref[o + 1]
        db = cand[o + 2] - ref[o + 2]
        sr += dr
        sg += dg
        sb += db
        ar, ag, ab = abs(dr), abs(dg), abs(db)
        abs_sum += ar + ag + ab
        d = max(ar, ag, ab)
        if d == 0:
            exact += 1
        elif d <= NEAR:
            near += 1
        else:
            far[i] = 1
    blob = erode(far, w, h)
    shift, blur = filter_fit(w, h, ref, cand)
    m = Metrics(
        pixels=n,
        exact=exact,
        near=near,
        far=n - exact - near,
        blob=sum(blob),
        largest=largest_component(blob, w, h),
        mae=abs_sum / (3 * n),
        bias=(sr / n, sg / n, sb / n),
        shift=shift,
        blur=blur,
    )
    return m, far, blob


def filter_fit(
    w: int, h: int, ref: bytes, cand: bytes
) -> tuple[tuple[float, float], tuple[float, float]]:
    """How much of the error a small filter over the reference explains, per
    axis: S, the least-squares coefficient of the error on the reference's
    backward difference, and L, on its second difference (R[-1] - 2R + R[+1]),
    over red, green and blue at every interior pixel.

    Noise and edge disagreements leave both near 0. A frame drawn a pixel
    over is C = R[-1], so S = -1; a second 1:2:1 filter is C = R + L/4, so
    L = 0.25. Those are the defects a GPU path is likeliest to have frame-wide
    -- a pixel-centre offset, a filter applied twice -- and the ones far
    pixels and MAE miss: their errors are small and everywhere (V0)."""
    s = w * 4
    es_x = gg_x = es_y = gg_y = el_x = ll_x = el_y = ll_y = 0
    for y in range(1, h - 1):
        row = y * s
        for x in range(1, w - 1):
            o = row + x * 4
            for k in range(3):
                p = o + k
                rv = ref[p]
                e = cand[p] - rv
                left, up = ref[p - 4], ref[p - s]
                gx, gy = rv - left, rv - up
                lx = left - 2 * rv + ref[p + 4]
                ly = up - 2 * rv + ref[p + s]
                es_x += e * gx
                gg_x += gx * gx
                es_y += e * gy
                gg_y += gy * gy
                el_x += e * lx
                ll_x += lx * lx
                el_y += e * ly
                ll_y += ly * ly

    def ratio(a: int, b: int) -> float:
        return a / b if b else 0.0

    return (ratio(es_x, gg_x), ratio(es_y, gg_y)), (ratio(el_x, ll_x), ratio(el_y, ll_y))


def erode(mask: bytearray, w: int, h: int) -> bytearray:
    """A 3x3 erosion: set where the pixel and all eight neighbours are set. The
    border is never set, having neighbours outside the frame."""
    out = bytearray(w * h)
    for y in range(1, h - 1):
        up, row, down = (y - 1) * w, y * w, (y + 1) * w
        for x in range(1, w - 1):
            if (
                mask[row + x]
                and mask[row + x - 1]
                and mask[row + x + 1]
                and mask[up + x - 1]
                and mask[up + x]
                and mask[up + x + 1]
                and mask[down + x - 1]
                and mask[down + x]
                and mask[down + x + 1]
            ):
                out[row + x] = 1
    return out


def largest_component(mask: bytearray, w: int, h: int) -> int:
    """The size of the largest 8-connected set of mask pixels."""
    seen = bytearray(len(mask))
    best = 0
    for start, v in enumerate(mask):
        if not v or seen[start]:
            continue
        seen[start] = 1
        stack, size = [start], 0
        while stack:
            p = stack.pop()
            size += 1
            py, px = divmod(p, w)
            for dy in (-1, 0, 1):
                ny = py + dy
                if ny < 0 or ny >= h:
                    continue
                for dx in (-1, 0, 1):
                    nx = px + dx
                    if 0 <= nx < w:
                        q = ny * w + nx
                        if mask[q] and not seen[q]:
                            seen[q] = 1
                            stack.append(q)
        best = max(best, size)
    return best


def heat(w: int, h: int, ref: bytes, cand: bytes, far: bytearray, blob: bytearray) -> bytes:
    """The reference at a third of its brightness, near pixels yellow, far
    pixels orange and blob pixels magenta: where to look first."""
    out = bytearray(len(ref))
    for i in range(w * h):
        o = i * 4
        if blob[i]:
            out[o : o + 4] = b"\xff\x00\xff\xff"
        elif far[i]:
            out[o : o + 4] = b"\xff\x80\x00\xff"
        elif ref[o : o + 3] != cand[o : o + 3]:
            out[o : o + 4] = b"\xff\xff\x00\xff"
        else:
            out[o], out[o + 1], out[o + 2], out[o + 3] = (
                ref[o] // 3,
                ref[o + 1] // 3,
                ref[o + 2] // 3,
                255,
            )
    return bytes(out)


def compare(ref: Path, cand: Path, heat_out: Path | None = None) -> Metrics:
    w, h, a = png.read_rgba(ref)
    w2, h2, b = png.read_rgba(cand)
    if (w, h) != (w2, h2):
        raise ValueError(f"{ref} is {w}x{h} and {cand} is {w2}x{h2}")
    m, far, blob = measure(w, h, a, b)
    if heat_out:
        png.write_rgba(heat_out, w, h, heat(w, h, a, b, far, blob))
    return m


# --------------------------------------------------------------------------
# references: replays of a set, in a scratch directory and a clean environment
# --------------------------------------------------------------------------


def child_env(parent: dict[str, str]) -> dict[str, str]:
    """The replay's environment: the parent's with every SOA_* removed, then
    the tool's own. A player's soa.ini must not move a frame (SOA_SETTINGS=0),
    and nothing set for another run -- SOA_GPU above all -- may reach the
    reference."""
    env = {k: v for k, v in parent.items() if not k.startswith("SOA_")}
    env["SOA_SETTINGS"] = "0"
    env["SOA_HASH"] = "1"
    env["SOA_THREADS"] = "4"
    return env


@dataclass
class Capture:
    name: str  # the reference's file name, without .png
    base: Path  # the capture, without its extension
    frame_hash: str | None  # the pinned FNV-1a, for the corpus only


def corpus() -> list[Capture]:
    rows = scenario.read_manifest(scenario.MANIFEST)
    out = []
    for name, (key, frame) in sorted(rows.items()):
        base = scenario.FIFO_DIR / name
        if not scenario.part(base, ".fifo").exists():
            raise SystemExit(f"imgdiff: {base} is missing; the corpus is build/fifo")
        if scenario.capture_key(base) != key:
            raise SystemExit(f"imgdiff: {name}'s files are not the ones its manifest row pins")
        out.append(Capture(name, base, frame))
    return out


def perfset() -> list[Capture]:
    out = []
    for name, (_label, pinned) in sorted(perfbench.read_manifest().items()):
        changed = perfbench.verify(name, pinned)
        if changed:
            raise SystemExit(
                f"imgdiff: {name}: {', '.join(changed)} missing or changed since its manifest"
            )
        out.append(Capture(name.replace("/", "_"), perfbench.SET / name, None))
    return out


def gpuset() -> list[Capture]:
    if not GPUSET_MANIFEST.exists():
        raise SystemExit("imgdiff: no config/gpuset_manifest.tsv yet; V1 captures the gpu set")
    out = []
    for line in GPUSET_MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, key, *_ = line.split("\t")
        base = ROOT / "build" / "gpuset" / name
        if scenario.capture_key(base) != key:
            raise SystemExit(f"imgdiff: {name}'s files are not the ones its manifest row pins")
        out.append(Capture(name.replace("/", "_"), base, None))
    return out


SETS = {"corpus": corpus, "perfset": perfset, "gpuset": gpuset}


def render(c: Capture, exe: Path, scratch: Path) -> tuple[Path, str]:
    """Replay one capture from a scratch copy; the PNG and what it printed."""
    work = scratch / c.name
    work.mkdir(parents=True, exist_ok=True)
    for ext in scenario.PARTS:
        shutil.copyfile(scenario.part(c.base, ext), work / ("frame" + ext))
    base = work / "frame"
    p = subprocess.run(
        [str(exe), "--replay", str(base)],
        cwd=ROOT,
        env=child_env(dict(os.environ)),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise SystemExit(f"imgdiff: {c.name}: --replay exited {p.returncode}\n{out[-2000:]}")
    return work / "frame.png", out


def cmd_refs(args: argparse.Namespace) -> int:
    caps = SETS[args.set]()
    dest = OUT / "ref" / args.set
    dest.mkdir(parents=True, exist_ok=True)
    (OUT / "tmp").mkdir(parents=True, exist_ok=True)
    bad = 0
    with tempfile.TemporaryDirectory(dir=OUT / "tmp") as tmp:
        for c in caps:
            frame, printed = render(c, args.exe, Path(tmp))
            w, h, rgba = png.read_rgba(frame)
            got = png.screen_hash(w, h, rgba)
            said = scenario.frame_hashes(printed)
            note = ""
            if said != [got]:
                note = f"; the replay printed {said}, the PNG hashes to {got}"
                bad += 1
            elif c.frame_hash is not None and got != c.frame_hash:
                note = f"; the manifest pins {c.frame_hash}"
                bad += 1
            shutil.copyfile(frame, dest / f"{c.name}.png")
            print(f"  {'ok  ' if not note else 'FAIL'}  {c.name}: {got}{note}")
    print(f"[imgdiff] {len(caps) - bad} of {len(caps)} references in {dest.relative_to(ROOT)}")
    return 1 if bad or not caps else 0


# --------------------------------------------------------------------------
# the mutation suite: the thresholds must fail a defect and pass noise
# --------------------------------------------------------------------------


def most_detailed(w: int, h: int, rgba: bytes, size: int = 24) -> tuple[int, int]:
    """The top-left corner of the size x size window with the most edge
    energy (summed |dx| + |dy| of luma), on a 4-pixel grid."""
    lum = [(rgba[i * 4] * 2 + rgba[i * 4 + 1] * 5 + rgba[i * 4 + 2]) // 8 for i in range(w * h)]
    grad = [0] * (w * h)
    for y in range(h - 1):
        r = y * w
        for x in range(w - 1):
            grad[r + x] = abs(lum[r + x + 1] - lum[r + x]) + abs(lum[r + w + x] - lum[r + x])
    # summed-area table
    sat = [0] * ((w + 1) * (h + 1))
    for y in range(h):
        run = 0
        for x in range(w):
            run += grad[y * w + x]
            sat[(y + 1) * (w + 1) + x + 1] = sat[y * (w + 1) + x + 1] + run
    best, at = -1, (0, 0)
    for y in range(0, h - size + 1, 4):
        for x in range(0, w - size + 1, 4):
            a, b = y * (w + 1) + x, (y + size) * (w + 1) + x
            s = sat[b + size] - sat[b] - sat[a + size] + sat[a]
            if s > best:
                best, at = s, (x, y)
    return at


def clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else v


def m_identity(w, h, img, rng):
    return bytes(img)


def m_noise(w, h, img, rng):
    out = bytearray(img)
    for i in range(w * h):
        for c in range(3):
            out[i * 4 + c] = clamp(img[i * 4 + c] + rng.choice((-1, 1)))
    return bytes(out)


def m_scatter(w, h, img, rng):
    out = bytearray(img)
    for i in rng.sample(range(w * h), int(w * h * 0.003)):
        for c in range(3):
            out[i * 4 + c] = clamp(img[i * 4 + c] + rng.randint(-64, 64))
    return bytes(out)


def m_line(w, h, img, rng):
    out = bytearray(img)
    for y in range(h):
        o = (y * w + y * w // h) * 4
        out[o : o + 3] = bytes(255 - v for v in img[o : o + 3])
    return bytes(out)


def m_block(w, h, img, rng):
    out = bytearray(img)
    x0, y0 = most_detailed(w, h, img)
    for y in range(y0, y0 + 24):
        for x in range(x0, x0 + 24):
            o = (y * w + x) * 4
            out[o : o + 3] = b"\x00\x00\x00"
    return bytes(out)


def m_bright(w, h, img, rng):
    out = bytearray(img)
    for i in range(w * h):
        for c in range(3):
            out[i * 4 + c] = clamp(img[i * 4 + c] + 4)
    return bytes(out)


def m_swap(w, h, img, rng):
    out = bytearray(img)
    out[0::4], out[2::4] = img[2::4], img[0::4]
    return bytes(out)


def m_washed(w, h, img, rng):
    out = bytearray(img)
    for i in range(w * h):
        for c in range(3):
            out[i * 4 + c] = clamp(round(16 + 0.9 * img[i * 4 + c]))
    return bytes(out)


def m_shift(w, h, img, rng):
    """Everything one pixel right; the first column repeats."""
    out = bytearray(img)
    for y in range(h):
        r = y * w * 4
        out[r + 4 : r + w * 4] = img[r : r + (w - 1) * 4]
    return bytes(out)


def m_blur(w, h, img, rng):
    """A 1:2:1 vertical blur, rounded; the edge rows repeat."""
    out = bytearray(img)
    s = w * 4
    for y in range(h):
        up, dn = max(y - 1, 0) * s, min(y + 1, h - 1) * s
        r = y * s
        for x in range(0, s, 4):
            for c in range(3):
                out[r + x + c] = (img[up + x + c] + 2 * img[r + x + c] + img[dn + x + c] + 2) >> 2
    return bytes(out)


# name, function, whether the thresholds must pass it
MUTATIONS = [
    ("identity", m_identity, True),
    ("noise +-1", m_noise, True),
    ("0.3% scattered", m_scatter, True),
    ("diagonal line", m_line, True),
    ("black 24x24 block", m_block, False),
    ("+4 brightness", m_bright, False),
    ("red-blue swap", m_swap, False),
    ("washed out", m_washed, False),
    ("one-pixel shift", m_shift, False),
    ("vertical blur", m_blur, False),
]

# Captures on which a mutation that must fail passes, each with its reason
# (FINDINGS "V0"). More than three for one mutation stops V0: the metric
# changes, not this list.
BLIND_SPOTS: dict[str, dict[str, str]] = {
    "+4 brightness": {
        "0100": "a boot frame nearly all white: +4 clamps at 255, leaving 89% of pixels exact",
        "0300": "a boot frame nearly all white: +4 clamps at 255, leaving 93% of pixels exact",
    },
    "red-blue swap": {
        "0500": "a grey frame: red equals blue at every pixel, so the swap changes nothing",
        "0700": "a grey frame: red equals blue at every pixel, so the swap changes nothing",
    },
}


def cmd_mutate(args: argparse.Namespace) -> int:
    refs = sorted((OUT / "ref" / args.set).glob("*.png"))
    if not refs:
        print(
            f"imgdiff: no references in {(OUT / 'ref' / args.set).relative_to(ROOT)}; run `refs` first"
        )
        return 1
    passed_bad: dict[str, list[str]] = {name: [] for name, _, _ in MUTATIONS}
    failed_good: dict[str, list[str]] = {name: [] for name, _, _ in MUTATIONS}
    for ref in refs:
        w, h, img = png.read_rgba(ref)
        cells = []
        for k, (name, fn, should_pass) in enumerate(MUTATIONS):
            rng = random.Random(f"{ref.stem}/{k}")
            m, _, _ = measure(w, h, img, fn(w, h, img, rng))
            ok = not m.failures()
            cells.append("pass" if ok else "FAIL")
            if should_pass and not ok:
                failed_good[name].append(f"{ref.stem}: {'; '.join(m.failures())}")
            if not should_pass and ok:
                passed_bad[name].append(f"{ref.stem}: {m.line()}")
        print(f"  {ref.stem:14} " + " ".join(cells))
    print("  columns: " + ", ".join(n for n, _, _ in MUTATIONS))
    bad = 0
    for name, _, should_pass in MUTATIONS:
        if should_pass and failed_good[name]:
            bad += 1
            print(f"[imgdiff] {name} must pass, and fails on {len(failed_good[name])}:")
            for line in failed_good[name]:
                print(f"    {line}")
        if not should_pass:
            listed = BLIND_SPOTS.get(name, {})
            unlisted = [p for p in passed_bad[name] if p.split(":")[0] not in listed]
            spots = len(passed_bad[name])
            verdict = "ok" if not unlisted and spots <= 3 else "FAIL"
            if verdict == "FAIL":
                bad += 1
            print(
                f"[imgdiff] {name}: fails on {len(refs) - spots} of {len(refs)}; blind spots {spots}: {verdict}"
            )
            for line in passed_bad[name]:
                print(f"    {line}{'' if line.split(':')[0] in listed else '  (not listed)'}")
    print(
        f"[imgdiff] {len(refs)} references, {len(MUTATIONS)} mutations: {'ok' if not bad else 'FAIL'}"
    )
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("refs", "mutate"):
        ap = argparse.ArgumentParser(prog=f"imgdiff.py {argv[0]}")
        ap.add_argument("--set", choices=tuple(SETS), default="corpus")
        ap.add_argument("--exe", type=Path, default=EXE)
        args = ap.parse_args(argv[1:])
        return cmd_refs(args) if argv[0] == "refs" else cmd_mutate(args)
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("ref", type=Path)
    ap.add_argument("cand", type=Path)
    ap.add_argument("--heat", type=Path, default=None, help="write a difference heat map")
    args = ap.parse_args(argv)
    m = compare(args.ref, args.cand, args.heat)
    fails = m.failures()
    print(f"[imgdiff] {m.line()}")
    print(f"[imgdiff] {'pass' if not fails else 'FAIL: ' + '; '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
