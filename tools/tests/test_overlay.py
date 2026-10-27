"""runtime/overlay.c: what mods draw over the picture (M20, docs/specs/mod-overlay.md).

overlay.c is built alone with a driver that plays both of its threads: the
guest's (a mod's draws, then the frame end's publish) and the window's (the
newest frame taken and drawn into a buffer over a known picture). The pixels
are then checked: where the game's 640x480 units land in a client of a given
size and picture rectangle, a rect's fill and its straight-alpha blend, each
font pixel's place against runtime/font5x7.h, clipping at the client's edge,
'?' for a byte past 126, the composite the GPU's buffer gets, and the rooms.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))

DRIVER = r"""
#include "overlay.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* overlay W H PX PY PW PH ALPHA OUT, then lines on stdin: "rect X Y W H RGBA",
 * "text X Y SIZE RGBA TEXT" (mod 0's draws), "mod M" (whose draws follow),
 * "publish", "take". The client starts as the picture, B G R X 30 20 10, or
 * cleared for the GPU's buffer (ALPHA 1); at the end the taken frame is drawn
 * into it and the buffer written to OUT. */
int main(int argc, char** argv)
{
    int w, h, px, py, pw, ph, alpha, m = 0, i, drew;
    uint8_t* buf;
    char line[1024];
    FILE* f;
    if (argc < 9) return 2;
    w = atoi(argv[1]), h = atoi(argv[2]), px = atoi(argv[3]), py = atoi(argv[4]);
    pw = atoi(argv[5]), ph = atoi(argv[6]), alpha = atoi(argv[7]);
    buf = (uint8_t*)calloc((size_t)w * (size_t)h, 4);
    if (!buf) return 3;
    for (i = 0; i < w * h && !alpha; i++) {
        buf[i * 4 + 0] = 0x30;
        buf[i * 4 + 1] = 0x20;
        buf[i * 4 + 2] = 0x10;
    }
    while (fgets(line, sizeof line, stdin)) {
        int x, y, a, b, n = 0;
        unsigned rgba;
        line[strcspn(line, "\r\n")] = 0;
        if (sscanf(line, "rect %d %d %d %d %x", &x, &y, &a, &b, &rgba) == 5)
            printf("rect %d\n", overlay_rect(m, x, y, a, b, rgba));
        else if (sscanf(line, "text %d %d %d %x %n", &x, &y, &a, &rgba, &n) == 4 && n)
            printf("text %d\n", overlay_text(m, x, y, (uint32_t)a, rgba, line + n));
        else if (sscanf(line, "mod %d", &a) == 1)
            m = a;
        else if (!strcmp(line, "publish"))
            overlay_publish();
        else if (!strcmp(line, "take"))
            printf("take %d\n", overlay_take());
    }
    drew = overlay_draw(buf, w, h, w * 4, px, py, pw, ph, alpha);
    printf("drew %d\n", drew);
    f = fopen(argv[8], "wb");
    if (!f) return 4;
    fwrite(buf, 4, (size_t)w * (size_t)h, f);
    fclose(f);
    return 0;
}
"""

PICTURE = (0x30, 0x20, 0x10)  # B, G, R


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    if toolchain.compiler_path(PROFILE) is None:
        pytest.skip(f"no {PROFILE.name}")
    out = tmp_path_factory.mktemp("overlay")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / ("overlay" + PROFILE.exeext)
    proc = toolchain.cc(
        [
            *PROFILE.cflags,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "overlay.c"),
            str(out / "driver.c"),
            "/Fe" + str(exe),
        ],
        out,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


class Shot:
    """A drawn client: its pixels as (B, G, R, A) and what the driver said."""

    def __init__(self, raw: bytes, w: int, h: int, said: list[str]):
        self.raw, self.w, self.h, self.said = raw, w, h, said

    def px(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.w + x) * 4
        return tuple(self.raw[i : i + 4])

    def rgb(self, x: int, y: int) -> tuple[int, int, int]:
        return self.px(x, y)[:3]


def draw(
    driver, tmp_path, script: str, client=(1920, 1080), picture=(240, 0, 1440, 1080), alpha=0
) -> Shot:
    """The script played -- its bytes as written, so 0x80 stays 0x80 -- with
    publish and take added when it has neither."""
    if "publish" not in script and "take" not in script:
        script += "\npublish\ntake"
    out = tmp_path / f"shot{len(list(tmp_path.glob('shot*')))}.raw"
    args = [str(driver), *map(str, (*client, *picture, alpha)), str(out)]
    proc = subprocess.run(
        args, input=(script + "\n").encode("latin-1"), capture_output=True, timeout=60, check=True
    )
    return Shot(out.read_bytes(), *client, proc.stdout.decode("latin-1").splitlines())


def font() -> dict[str, list[str]]:
    """runtime/font5x7.h's glyphs by character."""
    text = (ROOT / "runtime" / "font5x7.h").read_text(encoding="utf-8")
    rows = re.findall(r'\{((?:\s*"[.#]{5}",?){7})\s*\}', text)
    glyphs = [re.findall(r'"([.#]{5})"', r) for r in rows]
    assert len(glyphs) == 95, len(glyphs)
    return {chr(32 + i): g for i, g in enumerate(glyphs)}


def test_a_rect_lands_on_the_picture_where_the_window_put_it(driver, tmp_path):
    """1920x1080 with the picture fit at 2.25 (1440 wide, from x 240): the
    whole picture's rect covers the picture and nothing of the bars, and a
    rect's edges round to the nearest pixel: 100..110 is 465..487."""
    shot = draw(driver, tmp_path, "rect 0 0 640 480 FF0000FF\nrect 100 100 10 10 00FF00FF")
    assert shot.said[-1] == "drew 1"
    assert shot.rgb(240, 0) == (0, 0, 255) and shot.rgb(1679, 1079) == (0, 0, 255)
    assert (
        shot.rgb(239, 500) == PICTURE and shot.rgb(1680, 500) == PICTURE
    )  # the bars: the picture's colour here
    assert shot.rgb(465, 225) == (0, 255, 0) and shot.rgb(487, 247) == (0, 255, 0)
    assert shot.rgb(464, 230) == (0, 0, 255) and shot.rgb(488, 230) == (0, 0, 255)


def test_straight_alpha_blends_into_the_picture(driver, tmp_path):
    shot = draw(
        driver, tmp_path, "rect 0 0 10 10 FFFFFF80", client=(640, 480), picture=(0, 0, 640, 480)
    )
    want = tuple((255 * 128 + p * 127 + 127) // 255 for p in PICTURE)
    assert shot.rgb(5, 5) == want, shot.rgb(5, 5)
    assert shot.rgb(10, 10) == PICTURE
    clear = draw(
        driver, tmp_path, "rect 0 0 10 10 FFFFFF00", client=(640, 480), picture=(0, 0, 640, 480)
    )
    assert clear.rgb(5, 5) == PICTURE and clear.said[-1] == "drew 0"  # alpha 0: nothing


def test_each_font_pixel_where_the_header_puts_it(driver, tmp_path):
    """ "Ag" at size 2 on a picture drawn at 2x: each font pixel is a 4x4
    square, cells 12 units apart, g's tail a row lower; every lit pixel lit
    and every other pixel of the cell the picture."""
    glyphs = font()
    shot = draw(
        driver, tmp_path, "text 10 20 2 FFFFFFFF Ag", client=(1280, 960), picture=(0, 0, 1280, 960)
    )
    for i, ch in enumerate("Ag"):
        drop = 1 if ch == "g" else 0
        for r in range(9):
            for col in range(6):
                lit = 0 <= r - 1 - drop < 7 and col < 5 and glyphs[ch][r - 1 - drop][col] == "#"
                x = (10 + (i * 6 + col) * 2) * 2 + 1
                y = (20 + r * 2) * 2 + 1
                want = (255, 255, 255) if lit else PICTURE
                assert shot.rgb(x, y) == want, (ch, r, col, shot.rgb(x, y))


def test_a_byte_past_126_draws_a_question_mark(driver, tmp_path):
    a = draw(
        driver,
        tmp_path,
        "text 0 0 1 FFFFFFFF \x7f\x80",
        client=(640, 480),
        picture=(0, 0, 640, 480),
    )
    b = draw(
        driver, tmp_path, "text 0 0 1 FFFFFFFF ??", client=(640, 480), picture=(0, 0, 640, 480)
    )
    assert a.raw == b.raw


def test_draws_off_the_client_are_clipped(driver, tmp_path):
    shot = draw(
        driver,
        tmp_path,
        "rect -50 -50 100 100 FF0000FF\nrect 600 440 100 100 00FF00FF",
        client=(640, 480),
        picture=(0, 0, 640, 480),
    )
    assert (
        shot.rgb(0, 0) == (0, 0, 255)
        and shot.rgb(49, 49) == (0, 0, 255)
        and shot.rgb(50, 50) == PICTURE
    )
    assert shot.rgb(639, 479) == (0, 255, 0)


def test_a_coordinate_past_an_int_once_scaled_stays_off_the_picture(driver, tmp_path):
    """The review's case: at 1920x1080's default integer 2x, the picture at
    (320, 60, 1280, 960), x = -2147483648 -- what a float-to-int conversion
    gives a NaN -- times the scale is past an int, and wrapped onto the
    picture's left edge, a text's y onto its top; a width of 2147483647, "to
    the edge", wrapped to nothing. Held before they are narrowed, the first
    two draw nothing and the third reaches the client's right edge."""
    lost = draw(
        driver,
        tmp_path,
        "rect -2147483648 100 100 10 FF0000FF\ntext 100 -2147483648 2 FF0000FF HP",
        picture=(320, 60, 1280, 960),
    )
    assert lost.said[-1] == "drew 0" and lost.rgb(400, 265) == PICTURE, lost.said
    banner = draw(
        driver, tmp_path, "rect 0 400 2147483647 20 FF0000FF", picture=(320, 60, 1280, 960)
    )
    assert banner.said[-1] == "drew 1", banner.said
    assert banner.rgb(320, 870) == (0, 0, 255) and banner.rgb(1919, 870) == (0, 0, 255)


def test_the_gpu_buffer_gets_straight_alpha_composited_over(driver, tmp_path):
    """For Vulkan: the buffer starts clear; an opaque rect is itself at alpha
    255, a translucent one over nothing keeps its own alpha, and over the
    opaque one composites to an opaque blend, as on the picture."""
    shot = draw(
        driver,
        tmp_path,
        "rect 0 0 4 4 0000FFFF\nrect 2 0 4 4 FF000080",
        client=(640, 480),
        picture=(0, 0, 640, 480),
        alpha=1,
    )
    assert shot.px(0, 0) == (255, 0, 0, 255)  # B G R A: blue, opaque
    assert shot.px(5, 0) == (0, 0, 255, 128)  # red at its own alpha, over nothing
    b, g, r, a = shot.px(3, 0)
    assert a == 255 and (r, b) == ((255 * 128 + 127) // 255, (255 * 127 + 127) // 255), shot.px(
        3, 0
    )
    assert shot.px(10, 10) == (0, 0, 0, 0)


def test_only_a_published_and_taken_frame_is_drawn(driver, tmp_path):
    """Draws not yet published draw nothing; a frame with no draws, once
    published, clears what the last one drew."""
    unpublished = draw(
        driver, tmp_path, "rect 0 0 640 480 FF0000FF\ntake", client=(64, 48), picture=(0, 0, 64, 48)
    )
    assert unpublished.said[-1] == "drew 0" and unpublished.rgb(10, 10) == PICTURE
    cleared = draw(
        driver,
        tmp_path,
        "rect 0 0 640 480 FF0000FF\npublish\ntake\npublish\ntake",
        client=(64, 48),
        picture=(0, 0, 64, 48),
    )
    assert cleared.said[-2:] == ["take 0", "drew 0"], cleared.said
    kept = draw(
        driver,
        tmp_path,
        "rect 0 0 640 480 FF0000FF\npublish\ntake\ntake",
        client=(64, 48),
        picture=(0, 0, 64, 48),
    )
    assert kept.said[-1] == "drew 1"  # no newer frame: the window keeps drawing the last


def test_each_mod_has_its_room_a_frame(driver, tmp_path):
    """256 draws and 4096 bytes of text a mod a frame; past them refused, and
    another mod keeps its own room; the next frame starts with all of it."""
    rects = "\n".join(f"rect {i} 0 1 1 FFFFFFFF" for i in range(257))
    texts = "\n".join(["text 0 0 1 FFFFFFFF " + "x" * 255] * 17)
    script = f"{rects}\nmod 1\nrect 0 0 1 1 FFFFFFFF\nmod 2\n{texts}\npublish\ntake\nmod 0\nrect 0 0 1 1 FFFFFFFF"
    shot = draw(driver, tmp_path, script, client=(64, 48), picture=(0, 0, 64, 48))
    said = [s for s in shot.said if s.startswith(("rect", "text"))]
    assert said[:256] == ["rect 1"] * 256 and said[256] == "rect 0", said[250:260]
    assert said[257] == "rect 1"  # mod 1
    assert (
        said[258:274] == ["text 1"] * 16 and said[274] == "text 0"
    )  # 16 x 255 = 4080, the 17th past 4096
    assert said[275] == "rect 1"  # mod 0 again, the next frame
