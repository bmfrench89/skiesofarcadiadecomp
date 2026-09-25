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
#include <string.h>
#include "picture.h"
int main(void)
{
    char cmd[16], mode[16];
    int a, b, c, d;
    double hz;
    while (scanf("%15s", cmd) == 1) {
        if (!strcmp(cmd, "layout") && scanf("%d %d %d %d %15s", &a, &b, &c, &d, mode) == 5) {
            PicRect r = picture_layout(a, b, c, d, strcmp(mode, "fit") ? PICTURE_INTEGER : PICTURE_FIT);
            printf("%d %d %d %d\n", r.x, r.y, r.w, r.h);
        } else if (!strcmp(cmd, "interval") && scanf("%lf %d", &hz, &a) == 2) {
            printf("%u\n", present_interval(hz, a));
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
    if len(sys.argv) != 2:
        sys.exit("usage: python tools/tests/test_picture.py <log>")
    found = check_log(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
    for p in found:
        print(f"[picture-check] {p}")
    print(f"[picture-check] {'FAIL' if found else 'ok'}")
    sys.exit(1 if found else 0)
