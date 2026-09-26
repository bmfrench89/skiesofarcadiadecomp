"""runtime/picture.c: where the picture goes in a window, and how long each
frame is held (PLAN-GAMEPLAY-MODS H19a).

picture.c is built alone and held to the spec's cases and to a Python twin of
`picture_layout`; the twin is also what checks a windowed run. Run as a
script, this module reads a run's `[window]` lines --
`python tools/tests/test_picture.py <log>` -- and checks each against the
twin for its own client size and mode, and the rules around it: the image
inside the client, of the frame's shape within a pixel, centred within a
pixel, the client the monitor's size in fullscreen, and no failed present or
resize. It exits 1 and names each problem.
"""

import os
import re
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def layout(sw: int, sh: int, dw: int, dh: int, mode: str) -> tuple[int, int, int, int]:
    """picture_layout's twin: (x, y, w, h)."""
    if min(sw, sh, dw, dh) < 1:
        return (max(dw, 0) // 2, max(dh, 0) // 2, 0, 0)
    if mode == "integer":
        k = min(dw // sw, dh // sh)
        if k >= 1:
            w, h = sw * k, sh * k
            return ((dw - w) // 2, (dh - h) // 2, w, h)
    if dw * sh - dh * sw > 0:
        w, h = dh * sw // sh, dh
    else:
        w, h = dw, dw * sh // sw
    return ((dw - w) // 2, (dh - h) // 2, w, h)


RE_WINDOW = re.compile(
    r"^\[window\] frame (\d+): client (\d+)x(\d+), image (\d+)x(\d+) at \+(\d+)\+(\d+), from (\d+)x(\d+), "
    r"monitor (\d+)x(\d+), mode (integer|fit) (fullscreen|window)$"
)
RE_FAILED = re.compile(r"^\[present\] (\d+) failed present\(s\), (\d+) failed resize\(s\)$")


def check_log(log: str) -> list[str]:
    """What is wrong with a windowed run's [window] and [present] lines."""
    problems, lines, modes = [], 0, set()
    for ln in log.splitlines():
        m = RE_WINDOW.match(ln)
        if not m:
            continue
        lines += 1
        f, cw, ch, w, h, x, y, sw, sh, mw, mh = (int(g) for g in m.groups()[:11])
        mode, fs = m.group(12), m.group(13)
        modes.add(fs)
        want = layout(sw, sh, cw, ch, mode)
        if (x, y, w, h) != want:
            problems.append(f"frame {f}: image {w}x{h} at +{x}+{y}, but the layout gives {want}")
        if x < 0 or y < 0 or x + w > cw or y + h > ch:
            problems.append(f"frame {f}: the image is not inside the {cw}x{ch} client")
        if abs(w * sh - h * sw) > max(sw, sh):
            problems.append(f"frame {f}: {w}x{h} is not the frame's shape {sw}x{sh} within a pixel")
        if abs((cw - w) - 2 * x) > 1 or abs((ch - h) - 2 * y) > 1:
            problems.append(f"frame {f}: the image is not centred within a pixel")
        if fs == "fullscreen" and (cw, ch) != (mw, mh):
            problems.append(
                f"frame {f}: fullscreen, but the client {cw}x{ch} is not the monitor {mw}x{mh}"
            )
    if not lines:
        problems.append("no [window] lines: the run did not use SOA_WINDOW_TEST, or had no window")
    elif modes != {"fullscreen", "window"}:
        problems.append(f"only {sorted(modes)} lines: the run should go to fullscreen and back")
    failed = [m for ln in log.splitlines() if (m := RE_FAILED.match(ln))]
    if not failed:
        problems.append("no [present] failure line: the run did not end through the report")
    for m in failed:
        if m.group(1) != "0" or m.group(2) != "0":
            problems.append(f"{m.group(1)} failed present(s) and {m.group(2)} failed resize(s)")
    return problems


DRIVER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "picture.h"
static const char* unset(const char* v) { return strcmp(v, "-") ? v : NULL; }
int main(void)
{
    char cmd[16], mode[16], g[32], cb[16], md[16], fl[16], why[160];
    int a, b, c, d, i, n;
    double hz;
    while (scanf("%15s", cmd) == 1) {
        if (!strcmp(cmd, "layout") && scanf("%d %d %d %d %15s", &a, &b, &c, &d, mode) == 5) {
            PicRect r = picture_layout(a, b, c, d, strcmp(mode, "fit") ? PICTURE_INTEGER : PICTURE_FIT);
            printf("%d %d %d %d\n", r.x, r.y, r.w, r.h);
        } else if (!strcmp(cmd, "interval") && scanf("%lf %d", &hz, &a) == 2) {
            printf("%u\n", present_interval(hz, a));
        } else if (!strcmp(cmd, "filter") && scanf("%31s %15s %15s %15s %d", g, cb, md, fl, &n) == 5) {
            /* n pixels, r g b each, through the filters on a 1 x n frame:
             * the refusal ("-" for none), then the pixels */
            PicFilters f;
            PicFilterState* st;
            unsigned char* px = (unsigned char*)malloc((size_t)n * 4 + 4);
            for (i = 0; i < n; i++) {
                if (scanf("%d %d %d", &a, &b, &c) != 3) return 2;
                px[4 * i] = (unsigned char)c; px[4 * i + 1] = (unsigned char)b; px[4 * i + 2] = (unsigned char)a; px[4 * i + 3] = 255;
            }
            if (picture_filters_parse(&f, unset(g), unset(cb), unset(md), unset(fl), why, sizeof why)) printf("-|");
            else printf("%s|", why);
            st = picture_filters_new(&f);
            picture_filter(st, px, n, 1, 0.0);
            for (i = 0; i < n; i++) printf("%d %d %d ", px[4 * i + 2], px[4 * i + 1], px[4 * i]);
            printf("\n");
            picture_filters_free(st);
            free(px);
        } else if (!strcmp(cmd, "frames") && scanf("%lf %d", &hz, &n) == 2) {
            /* n frames of 20 x 20 greys at hz a second through the flash
             * limiter: every pixel as shown, then the frames held and the
             * most of the picture the limiter counted over the limit */
            PicFilters f;
            PicFilterState* st;
            unsigned char px[20 * 20 * 4];
            unsigned long long frames, held;
            double most;
            int v;
            picture_filters_parse(&f, NULL, NULL, NULL, "1", why, sizeof why);
            st = picture_filters_new(&f);
            for (i = 0; i < n; i++) {
                for (d = 0; d < 20 * 20; d++) {
                    if (scanf("%d", &v) != 1) return 2;
                    px[4 * d] = px[4 * d + 1] = px[4 * d + 2] = (unsigned char)v;
                    px[4 * d + 3] = 255;
                }
                picture_filter(st, px, 20, 20, i / hz);
                for (d = 0; d < 20 * 20; d++) printf("%d ", px[4 * d + 2]);
            }
            picture_filter_counts(st, &frames, &held, &most);
            printf("; %llu %.6f\n", held, most);
            picture_filters_free(st);
        } else if (!strcmp(cmd, "scale") && scanf("%d %d %d %d %15s", &a, &b, &c, &d, mode) == 5) {
            /* an a x b frame whose pixel i holds i + 1, into c x d */
            unsigned int* src = (unsigned int*)malloc((size_t)a * b * 4);
            unsigned int* dst = (unsigned int*)malloc((size_t)c * d * 4);
            for (i = 0; i < a * b; i++) src[i] = (unsigned int)i + 1;
            picture_scale((const unsigned char*)src, a, b, (unsigned char*)dst, c, d, strcmp(mode, "fit") ? PICTURE_INTEGER : PICTURE_FIT);
            for (i = 0; i < c * d; i++) printf("%u ", dst[i]);
            printf("\n");
            free(src);
            free(dst);
        }
    }
    return 0;
}
"""


def build(tmp: Path, source: str | None = None) -> Path:
    from soa import toolchain

    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "driver.c").write_text(DRIVER, encoding="utf-8")
    src = tmp / "picture.c"
    src.write_text(
        source or (ROOT / "runtime" / "picture.c").read_text(encoding="utf-8"), encoding="utf-8"
    )
    exe = tmp / "picture.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(ROOT / "runtime"),
            str(src),
            str(tmp / "driver.c"),
            "/Fo" + str(tmp) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=tmp,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def ask(exe: Path, lines: list[str]) -> list[str]:
    proc = subprocess.run(
        [str(exe)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.split("\n")[: len(lines)]


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    return build(tmp_path_factory.mktemp("picture"))


SPEC = [
    # (src, client, mode) -> (x, y, w, h), from the H19a Done
    ((640, 480, 1920, 1080, "integer"), (320, 60, 1280, 960)),
    ((640, 480, 1920, 1080, "fit"), (240, 0, 1440, 1080)),
    ((640, 480, 1280, 800, "integer"), (320, 160, 640, 480)),
    ((640, 480, 1280, 800, "fit"), (107, 0, 1066, 800)),
    ((640, 480, 2560, 1600, "integer"), (320, 80, 1920, 1440)),
    ((640, 480, 2560, 1600, "fit"), (213, 0, 2133, 1600)),
]
INTERVALS = [((60.0, 30), 2), ((85.0, 30), 1), ((120.0, 30), 4), ((144.0, 30), 1), ((59.94, 30), 2)]
# at turbo the game makes up to 60 images a second (M11a): the same rule at 60 fps
INTERVALS_60 = [((60.0, 60), 1), ((85.0, 60), 1), ((120.0, 60), 2), ((144.0, 60), 1)]


def layouts(exe, cases):
    return [
        tuple(int(v) for v in out.split())
        for out in ask(exe, [f"layout {a} {b} {c} {d} {m}" for (a, b, c, d, m) in cases])
    ]


@needs_msvc
def test_the_spec_s_layouts_and_intervals(driver):
    assert layouts(driver, [c for c, _ in SPEC]) == [want for _, want in SPEC]
    got = [int(v) for v in ask(driver, [f"interval {hz} {fps}" for (hz, fps), _ in INTERVALS])]
    assert got == [want for _, want in INTERVALS], got
    got = [int(v) for v in ask(driver, [f"interval {hz} {fps}" for (hz, fps), _ in INTERVALS_60])]
    assert got == [want for _, want in INTERVALS_60], got


@needs_msvc
def test_the_c_and_the_python_twin_agree_everywhere(driver):
    """Every client from 100x100 to 3000x2000 on a coarse grid, both modes,
    and a smaller-than-the-frame client always fits."""
    cases = [
        (640, 480, w, h, m)
        for w in range(100, 3001, 97)
        for h in range(100, 2001, 89)
        for m in ("integer", "fit")
    ]
    got = layouts(driver, cases)
    for case, rect in zip(cases, got, strict=True):
        assert rect == layout(*case), (case, rect, layout(*case))
        x, y, w, h = rect
        assert x >= 0 and y >= 0 and x + w <= case[2] and y + h <= case[3], (case, rect)


@needs_msvc
def test_the_mutations_fail(tmp_path):
    """Swapping width and height in the fit fails three of the spec's cases;
    a plain round(hz/30) fails 85 and 144."""
    src = (ROOT / "runtime" / "picture.c").read_text(encoding="utf-8")
    fit = "    if (wide > 0) return centred((int)((long long)dst_h * src_w / src_h), dst_h, dst_w, dst_h);"
    assert src.count(fit) == 1
    swapped = build(
        tmp_path / "a",
        src.replace(
            fit,
            "    if (wide > 0) return centred((int)((long long)dst_h * src_h / src_w), dst_h, dst_w, dst_h);",
        ),
    )
    wrong = [
        c
        for (c, want), got in zip(SPEC, layouts(swapped, [c for c, _ in SPEC]), strict=True)
        if got != want
    ]
    assert len(wrong) == 3, wrong
    snap = "    if (r - (double)n >= 0.02 || (double)n - r >= 0.02) n = 1;\n"
    assert src.count(snap) == 1
    rounded = build(tmp_path / "b", src.replace(snap, ""))
    got = [int(v) for v in ask(rounded, [f"interval {hz} {fps}" for (hz, fps), _ in INTERVALS])]
    assert [hz for ((hz, _), want), g in zip(INTERVALS, got, strict=True) if g != want] == [
        85.0,
        144.0,
    ], got
    # at 60 fps a plain round(hz/60) goes wrong at 144 alone (M11a)
    got = [int(v) for v in ask(rounded, [f"interval {hz} {fps}" for (hz, fps), _ in INTERVALS_60])]
    wrong = [hz for ((hz, _), want), g in zip(INTERVALS_60, got, strict=True) if g != want]
    assert wrong == [144.0], got


# ---- P5a: the filters' twins, from the spec's formulas (comfort-pack 3.13) ----

SIM = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritan": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}
CORRECT = ((0, 0, 0), (0.7, 1, 0), (0.7, 0, 1))


def to_linear(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def to_byte(lin: float) -> int:
    if not lin > 0:
        return 0
    if lin >= 1:
        return 255
    v = 12.92 * lin if lin <= 0.0031308 else 1.055 * lin ** (1 / 2.4) - 0.055
    return int(255 * v + 0.5)


def colour_twin(rgb: tuple[int, int, int], kind: str, mode: str) -> list[int]:
    """Machado at severity 1 in linear light; correction adds C (rgb - sim)."""
    lin = [to_linear(c) for c in rgb]
    s = SIM[kind]
    sim = [sum(s[r][k] * lin[k] for k in range(3)) for r in range(3)]
    if mode == "simulate":
        out = sim
    else:
        err = [lin[k] - sim[k] for k in range(3)]
        out = [lin[r] + sum(CORRECT[r][k] * err[k] for k in range(3)) for r in range(3)]
    return [to_byte(v) for v in out]


def gamma_twin(c: int, g: float) -> int:
    return int(255 * (c / 255.0) ** (1 / g) + 0.5)


COLOURS = [(r, g, b) for r in (0, 128, 255) for g in (0, 128, 255) for b in (0, 128, 255)] + [
    ((37 * i) % 256, (91 * i + 17) % 256, (53 * i + 101) % 256) for i in range(64)
]


def filtered(exe, gamma="-", cb="-", mode="-", flash="-", colours=COLOURS) -> tuple[str, list]:
    """What the filters make of `colours`, and the refusal, "-" for none."""
    line = " ".join(f"{r} {g} {b}" for r, g, b in colours)
    why, out = ask(exe, [f"filter {gamma} {cb} {mode} {flash} {len(colours)} {line}"])[0].split("|")
    v = [int(x) for x in out.split()]
    return why.strip(), [tuple(v[k : k + 3]) for k in range(0, len(v), 3)]


def off_by_more_than(got, want, step: int = 1) -> list:
    return [
        (c, g, w)
        for c, g, w in zip(COLOURS, got, want, strict=True)
        if max(abs(a - b) for a, b in zip(g, w, strict=True)) > step
    ]


def spec_matrices() -> dict[str, list[float]]:
    """3.13's three matrices, read from the spec itself."""
    text = (ROOT / "docs" / "specs" / "comfort-pack.md").read_text(encoding="utf-8")
    text = text[text.index("### 3.13") : text.index("### 3.14")].replace("−", "-")
    out = {}
    for kind in SIM:
        m = re.search(kind + r": `\[([^\]]*)\]`", text, re.S)
        assert m, kind
        out[kind] = [float(x) for x in re.findall(r"-?\d+\.\d+", m.group(1))]
    return out


def c_matrices() -> list[list[float]]:
    """picture.c's k_sim, in the order protan, deutan, tritan."""
    src = (ROOT / "runtime" / "picture.c").read_text(encoding="utf-8")
    body = src[src.index("k_sim[3][9] = {") : src.index("};", src.index("k_sim[3][9] = {"))]
    rows = re.findall(r"\{([^{}]*)\}", body)
    return [[float(x) for x in r.split(",")] for r in rows]


# ---- the flash limiter: whole frames in, each pixel counted as WCAG counts it

SIDE = 20  # the driver's frames are 20 x 20 greys


def flash_ends(values: list[int], fps: float) -> list[float]:
    """When a pixel's flashes end, as WCAG counts them: a move of relative
    luminance of 0.1 or more from where it last turned (before its first turn,
    from the highest or lowest yet), the darker below 0.8, then the opposite
    move inside a second."""
    lum = [to_linear(v) for v in values]
    low = high = lum[0]
    going, half, ends = 0, None, []
    for i in range(1, len(lum)):
        now, when = lum[i], i / fps
        top = high if going >= 0 else None
        d = 0
        if going >= 0 and top - now >= 0.1 and now < 0.8:
            d = -1
        elif going <= 0 and now - low >= 0.1 and low < 0.8:
            d = 1
        if d:
            if half and half[0] == -d and when - half[1] < 1.0:
                ends.append(when)
                half = None
            else:
                half = (d, when)
            going, low, high = d, now, now
        elif going > 0:
            high = max(high, now)
        elif going < 0:
            low = min(low, now)
        else:
            low, high = min(low, now), max(high, now)
    return ends


def most_flashes(values: list[int], fps: float) -> int:
    """The most flashes one pixel shows in any second."""
    ends = flash_ends(values, fps)
    return max((sum(1 for e in ends if s - 1.0 < e <= s) for s in ends), default=0)


def over_area(frames: list[list[int]], fps: float) -> float:
    """The largest share of the picture that flashes more than three times
    in one second: WCAG's area, counted independently of the C."""
    n = len(frames[0])
    ends = [flash_ends([f[i] for f in frames], fps) for i in range(n)]
    worst = 0
    for k in range(len(frames)):
        s = k / fps
        worst = max(worst, sum(1 for e in ends if sum(1 for x in e if s - 1.0 < x <= s) > 3))
    return worst / n


def frames_run(exe, fps: float, frames: list[list[int]]) -> tuple[list[list[int]], int, float]:
    """Frames of SIDE x SIDE greys through the flash limiter: the frames as
    shown, how many were held back, and the most of the picture it reports
    over three flashes a second."""
    vals = " ".join(str(v) for f in frames for v in f)
    shown, counts = ask(exe, [f"frames {fps} {len(frames)} {vals}"])[0].split(";")
    held, most = counts.split()
    v = [int(x) for x in shown.split()]
    n = SIDE * SIDE
    return [v[k : k + n] for k in range(0, len(v), n)], int(held), float(most)


def flat(values: list[int]) -> list[list[int]]:
    return [[v] * (SIDE * SIDE) for v in values]


def rows_of(values: list[int], rows: int, rest: int | None = None) -> list[list[int]]:
    """The top `rows` rows take each value; the rest keep `rest`, or the
    inverse of the value when `rest` is None."""
    return [
        [v if i // SIDE < rows else (255 - v if rest is None else rest) for i in range(SIDE * SIDE)]
        for v in values
    ]


FIVE_HZ = ([0] * 3 + [255] * 3) * 15  # the spec's 5 Hz: three frames each at 30 a second
TWO_HZ = ([255] * 8 + [0] * 7) * 6  # two flashes a second
ALTERNATE = [0, 255] * 45  # black and white in turn
RAMP = [to_byte(v) for v in (0, 0.075, 0.15, 0.225, 0.3, 0.225, 0.15, 0.075)] * 12
SMALL = [120] + [
    to_byte(to_linear(120) + d) for d in (0.06, -0.06)
] * 45  # 0.12 about where it began


def gradient_five_hz() -> list[list[int]]:
    """The spec's 5 Hz over a frame that is not flat: dark frames a gradient of 0 to 200."""
    dark = [i * 200 // (SIDE * SIDE - 1) for i in range(SIDE * SIDE)]
    return [dark if (k // 3) % 2 == 0 else [255] * (SIDE * SIDE) for k in range(90)]


def overlay_pulse() -> list[list[int]]:
    """A white overlay pulsing over a busy picture, 7.5 times a second at 60."""
    base = [(i * 73 + 29) % 201 for i in range(SIDE * SIDE)]
    alphas = (0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25)
    return [[int(b + alphas[k % 8] * (255 - b) + 0.5) for b in base] for k in range(120)]


def band_sweep() -> list[list[int]]:
    """Five bands of four rows, each black and white by turns every three frames
    at 60 a second, each a frame behind the one above: no one frame ends a
    fourth flash over a quarter of the picture."""
    return [
        [255 if ((k - (i // SIDE) // 4) // 3) % 2 else 0 for i in range(SIDE * SIDE)]
        for k in range(120)
    ]


def scale_twin(w: int, h: int, dw: int, dh: int, mode: str) -> list[int]:
    x0, y0, rw, rh = layout(w, h, dw, dh, mode)
    out = [0] * (dw * dh)
    for y in range(rh):
        for x in range(rw):
            out[(y0 + y) * dw + x0 + x] = (y * h // rh) * w + x * w // rw + 1
    return out


# ---- the replay's identity check: two PNGs, the same pixels


def decode_png(path: Path) -> tuple[int, int, bytes]:
    """(width, height, RGB bytes) of an 8-bit RGB or RGBA PNG, all five filters."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, idat, w, h, ch = 8, b"", 0, 0, 0
    while pos < len(data):
        n = int.from_bytes(data[pos : pos + 4], "big")
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + n]
        if kind == b"IHDR":
            w, h = int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big")
            assert body[8] == 8 and body[9] in (2, 6), "8-bit RGB or RGBA only"
            ch = 3 if body[9] == 2 else 4
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw, stride = zlib.decompress(idat), w * ch
    prev, rgb = bytearray(stride), bytearray()
    for y in range(h):
        f, line = (
            raw[y * (stride + 1)],
            bytearray(raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]),
        )
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0
            b, c = prev[x], (prev[x - ch] if x >= ch else 0)
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        for x in range(w):
            rgb += line[x * ch : x * ch + 3]
        prev = line
    return w, h, bytes(rgb)


def encode_png(path: Path, w: int, h: int, rgb: bytes, filt: int) -> None:
    """A PNG of `rgb` with every row under filter `filt`, for the decoder's own test."""
    rows, prev = [], bytes(w * 3)
    for y in range(h):
        line = rgb[y * w * 3 : (y + 1) * w * 3]
        out = bytearray()
        for x in range(w * 3):
            a = line[x - 3] if x >= 3 else 0
            b, c = prev[x], (prev[x - 3] if x >= 3 else 0)
            if filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            else:
                pred = (0, a, b, (a + b) // 2)[filt]
            out.append((line[x] - pred) & 255)
        rows.append(bytes([filt]) + bytes(out))
        prev = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")
        )

    ihdr = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def same_picture(a: Path, b: Path) -> bool:
    return decode_png(a) == decode_png(b)


@needs_msvc
def test_the_filters_are_the_spec_s_formulas(driver):
    """The matrices are 3.13's to six places, in picture.c and in the twin;
    each colour-blind model, corrected and simulated, is the twin within one
    step a channel, grey stays grey; gamma 1.0 changes no byte and 2.2
    changes mid-greys; and a bad key is refused by name while the others
    still apply."""
    spec = spec_matrices()
    for kind, c in zip(SIM, c_matrices(), strict=True):
        twin = [v for row in SIM[kind] for v in row]
        assert all(abs(a - b) < 1e-6 for a, b in zip(spec[kind], c, strict=True)), (kind, c)
        assert all(abs(a - b) < 1e-6 for a, b in zip(spec[kind], twin, strict=True)), (kind, twin)
    assert filtered(driver) == ("-", [tuple(c) for c in COLOURS])
    for kind in SIM:
        for mode in ("correct", "simulate"):
            _, got = filtered(driver, cb=kind, mode=mode)
            want = [colour_twin(c, kind, mode) for c in COLOURS]
            assert not off_by_more_than(got, want), (kind, mode, off_by_more_than(got, want)[:4])
        greys = [(v, v, v) for v in range(0, 256, 5)]
        for r, g, b in filtered(driver, cb=kind, mode="simulate", colours=greys)[1]:
            assert max(r, g, b) - min(r, g, b) <= 1, (kind, r, g, b)
    assert filtered(driver, gamma="1.0") == ("-", [tuple(c) for c in COLOURS])
    _, mid = filtered(driver, gamma="2.2", colours=[(128, 128, 128), (64, 64, 64)])
    assert mid == [(gamma_twin(128, 2.2),) * 3, (gamma_twin(64, 2.2),) * 3] and mid[0] != (
        128,
        128,
        128,
    )
    for gm in (0.5, 1.8, 2.5):
        assert filtered(driver, gamma=str(gm))[1] == [
            tuple(gamma_twin(v, gm) for v in c) for c in COLOURS
        ]
    both = filtered(driver, gamma="1.8", cb="deutan")[1]
    want = [tuple(gamma_twin(v, 1.8) for v in colour_twin(c, "deutan", "correct")) for c in COLOURS]
    assert not off_by_more_than(both, want, 2)
    for args, word in (
        ({"gamma": "3"}, "gamma"),
        ({"gamma": "x"}, "gamma"),
        ({"cb": "red"}, "colorblind"),
        ({"mode": "fix"}, "colorblind_mode"),
        ({"flash": "2"}, "flash_limit"),
    ):
        why, _ = filtered(driver, **args)
        assert why.startswith(f"{word} = ") and "left at its default" in why, (args, why)
    # a typo in one key leaves the others on
    why, got = filtered(driver, gamma="3", cb="deutan")
    assert why.startswith("gamma = ")
    assert not off_by_more_than(got, [colour_twin(c, "deutan", "correct") for c in COLOURS])


@needs_msvc
def test_the_flash_limiter_keeps_flashing_under_a_quarter_of_the_picture(driver):
    """The spec's 5 Hz and faster, over a flat frame and over busy ones, a
    flash built of small steps, halves that swap, a band sweeping down, and
    a small flash about a pixel's first light: every one flashes over more
    than a quarter of the picture as given and under a quarter as shown, by
    an independent count. Two flashes a second, a fifth of the frame, a step
    under 0.1 and a change among bright values are shown untouched."""
    cases = [
        ("5 Hz", 30.0, flat(FIVE_HZ)),
        ("15 Hz", 30.0, flat(ALTERNATE)),
        ("30 Hz at 60", 60.0, flat(ALTERNATE)),
        ("steps", 60.0, flat(RAMP)),
        ("halves", 30.0, rows_of(ALTERNATE, 10)),
        ("gradient", 30.0, gradient_five_hz()),
        ("overlay", 60.0, overlay_pulse()),
        ("sweep", 60.0, band_sweep()),
        ("small", 30.0, flat(SMALL)),
    ]
    for name, fps, frames in cases:
        assert over_area(frames, fps) > 0.25, name
        shown, held, most = frames_run(driver, fps, frames)
        area = over_area(shown, fps)
        assert held > 0 and area < 0.25 and most < 0.25, (name, held, area, most)
    for name, fps, frames in (
        ("2 Hz", 30.0, flat(TWO_HZ)),
        ("a fifth", 30.0, rows_of(ALTERNATE, 4, 0)),
        ("a small step", 30.0, flat([100, 120] * 45)),
        ("bright", 30.0, flat([235, 255] * 45)),
    ):
        shown, held, _ = frames_run(driver, fps, frames)
        assert held == 0 and shown == frames, name
    shown, _, _ = frames_run(driver, 30.0, flat(ALTERNATE))
    assert [f[0] for f in shown[:7]] == ALTERNATE[:7]  # the first three flashes go through


@needs_msvc
def test_the_scaler_is_the_layout(driver):
    """picture_scale puts each pixel where picture_layout and a nearest
    neighbour say, with black round it."""
    for w, h, dw, dh, mode in (
        (4, 3, 13, 7, "integer"),
        (4, 3, 13, 7, "fit"),
        (4, 3, 8, 6, "integer"),
        (5, 4, 3, 2, "integer"),
        (6, 4, 17, 11, "fit"),
    ):
        got = [int(v) for v in ask(driver, [f"scale {w} {h} {dw} {dh} {mode}"])[0].split()]
        assert got == scale_twin(w, h, dw, dh, mode), (w, h, dw, dh, mode)


def test_the_png_decoder_reads_every_filter(tmp_path):
    """The identity check's decoder, on pictures made here under each of
    PNG's five row filters; a changed byte is a different picture."""
    w, h = 7, 5
    rgb = bytes(
        (x * 37 + y * 11 + c * 90) % 256 for y in range(h) for x in range(w) for c in range(3)
    )
    for filt in range(5):
        encode_png(tmp_path / f"f{filt}.png", w, h, rgb, filt)
        assert decode_png(tmp_path / f"f{filt}.png") == (w, h, rgb), filt
    changed = bytearray(rgb)
    changed[40] ^= 1
    encode_png(tmp_path / "x.png", w, h, bytes(changed), 4)
    assert same_picture(tmp_path / "f0.png", tmp_path / "f4.png")
    assert not same_picture(tmp_path / "f0.png", tmp_path / "x.png")


@needs_msvc
def test_the_filter_mutations_fail(tmp_path):
    """Each rule, broken on its own, fails the check that should catch it:
    the colour model in sRGB, gamma inverted, a limiter that never acts
    (5 Hz gets through) and one that always acts (2 Hz is touched), a fourth
    flash let through, a fifth of the frame counted as enough, flashes
    measured frame to frame, the area counted a frame at a time, and a pixel
    that forgets its first extremes."""
    src = (ROOT / "runtime" / "picture.c").read_text(encoding="utf-8")

    def mutant(name: str, old: str, new: str) -> Path:
        assert src.count(old) == 1, old
        return build(tmp_path / name, src.replace(old, new))

    srgb = mutant(
        "srgb",
        "float b = s->lin[p[0]], g = s->lin[p[1]], r = s->lin[p[2]];",
        "float b = p[0] / 255.0f, g = p[1] / 255.0f, r = p[2] / 255.0f;",
    )
    got = filtered(srgb, cb="protan")[1]
    assert off_by_more_than(got, [colour_twin(c, "protan", "correct") for c in COLOURS])
    inverted = mutant("gamma", "pow(i / 255.0, 1.0 / f->gamma)", "pow(i / 255.0, f->gamma)")
    assert filtered(inverted, gamma="2.2")[1] != [
        tuple(gamma_twin(v, 2.2) for v in c) for c in COLOURS
    ]

    rule = "    return now && (now + lately) * 4 >= n;"
    never = mutant("never", rule, "    return 0;")
    shown, _, _ = frames_run(never, 30.0, flat(FIVE_HZ))
    assert most_flashes([f[0] for f in shown], 30.0) > 3
    always = mutant("always", rule, "    return 1;")
    shown, _, _ = frames_run(always, 30.0, flat(TWO_HZ))
    assert shown != flat(TWO_HZ)
    fourth = mutant("fourth", "    return n >= 3;\n}", "    return n >= 4;\n}")
    shown, _, _ = frames_run(fourth, 30.0, flat(ALTERNATE))
    assert most_flashes([f[0] for f in shown], 30.0) > 3
    fifth = mutant("fifth", rule, "    return now && (now + lately) * 5 >= n;")
    _, held, _ = frames_run(fifth, 30.0, rows_of(ALTERNATE, 4, 0))
    assert held > 0
    steps = mutant(
        "steps",
        "        } else if (q->trend > 0) {\n            if (l[i] > q->ext) q->ext = l[i]; /* still rising: it turns later */\n"
        "        } else if (q->trend < 0) {\n            if (l[i] < q->ext) q->ext = l[i];\n        } else {",
        "        } else if (q->trend) {\n            q->ext = l[i];\n        } else {",
    )
    shown, _, _ = frames_run(steps, 60.0, flat(RAMP))
    assert most_flashes([f[0] for f in shown], 60.0) > 3
    frame_area = mutant("frame-area", rule, "    return now && now * 4 >= n;")
    for fps, frames in ((30.0, gradient_five_hz()), (60.0, band_sweep())):
        shown, _, _ = frames_run(frame_area, fps, frames)
        assert over_area(shown, fps) > 0.25
    forget = mutant(
        "forget",
        "            if (l[i] < q->ext) q->ext = l[i];\n            if (l[i] > q->hi) q->hi = l[i];\n",
        "",
    )
    shown, _, _ = frames_run(forget, 30.0, flat(SMALL))
    assert most_flashes([f[0] for f in shown], 30.0) > 3


def good_log() -> str:
    lines = []
    for f, (cw, ch, fs) in zip(
        (300, 600, 900),
        ((2560, 1600, "fullscreen"), (1280, 960, "window"), (1000, 700, "window")),
        strict=True,
    ):
        x, y, w, h = layout(640, 480, cw, ch, "integer")
        lines.append(
            f"[window] frame {f}: client {cw}x{ch}, image {w}x{h} at +{x}+{y}, from 640x480, "
            f"monitor 2560x1600, mode integer {fs}"
        )
    lines.append("[present] 0 failed present(s), 0 failed resize(s)")
    return "\n".join(lines)


def test_the_log_check_passes_a_good_run_and_fails_each_rule():
    good = good_log()
    assert check_log(good) == []
    moved = good.replace("image 1280x960 at +0+0", "image 1280x960 at +1+0")
    assert any("the layout gives" in p for p in check_log(moved)), check_log(moved)
    small = good.replace(
        "client 2560x1600, image 1920x1440 at +320+80",
        "client 2500x1600, image 1920x1440 at +290+80",
    )
    assert any("not the monitor" in p for p in check_log(small)), check_log(small)
    failed = good.replace("0 failed present(s)", "2 failed present(s)")
    assert any("2 failed present" in p for p in check_log(failed)), check_log(failed)
    windowed = "\n".join(ln for ln in good.splitlines() if "fullscreen" not in ln)
    assert any("should go to fullscreen" in p for p in check_log(windowed)), check_log(windowed)
    assert check_log("")[0].startswith("no [window] lines")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--same":
        # P5a's replay identity check: <base>.png and <base>.picture.png
        a, b = decode_png(Path(sys.argv[2])), decode_png(Path(sys.argv[3]))
        same = a == b
        print(f"[picture-check] {a[0]}x{a[1]} and {b[0]}x{b[1]}: {'the same pixels' if same else 'different'}")
        sys.exit(0 if same else 1)
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/tests/test_picture.py <log> | --same <a.png> <b.png>")
    found = check_log(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
    for p in found:
        print(f"[picture-check] {p}")
    print(f"[picture-check] {'FAIL' if found else 'ok'}")
    sys.exit(1 if found else 0)
