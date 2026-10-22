"""runtime/menu.c: the in-game menu's model and drawing (M8a, docs/specs/menu.md).

menu.c is built alone with a driver that stands in for settings.c and mod.c
(two mods, one with an option of each kind, and one mod turned off) and runs a
script of inputs: what is written to soa.ini and what the window is asked to do
are printed. A page is drawn into a buffer over a known picture, the font and
the panel checked pixel by pixel, and the drawing written as a PNG to look at.
"""

import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))

DRIVER = r"""
#include "menu.h"
#include "mod.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* settings.c, as the menu sees it */
int settings_set(const char* key, const char* value) { printf("save %s = %s\n", key, value); return 1; }
static const char* const k_keys[] = {"scaler", "turbo"};
static const char* const k_choices[] = {"integer|fit", "battle|sky|both"};
int settings_menu_count(void) { return 2; }
int settings_menu_item(int i, const char** key, const char** choices, const char** what, const char** value)
{
    if (i < 0 || i > 1) return 0;
    *key = k_keys[i]; *choices = k_choices[i]; *what = ""; *value = i == 0 ? "fit" : "";
    return 1;
}

/* mod.c: "encounter-rate" with four options, "map-log" with none, "lab" off */
static const ModMenuOption k_opts[] = {
    {"rate", 2, 0, 0, "off|half|normal|double", "normal", "normal"},
    {"hold_b", 1, 0, 0, "", "1", "1"},
    {"strength", 0, 0, 100, "", "50", "50"},
    {"tag", 3, 0, 0, "", "x", "x"},
};
int mod_menu_count(void) { return 2; }
const char* mod_menu_name(int m, const char** key)
{
    if (m == 0) { if (key) *key = "encounter-rate"; return "Encounter rate"; }
    if (m == 1) { if (key) *key = "map-log"; return "Map log"; }
    return NULL;
}
int mod_menu_option_count(int m) { return m == 0 ? 4 : 0; }
int mod_menu_option(int m, int i, ModMenuOption* out)
{
    if (m != 0 || i < 0 || i > 3) return 0;
    *out = k_opts[i];
    return 1;
}
int mod_menu_off_count(void) { return 1; }
const char* mod_menu_off_key(int i) { return i == 0 ? "lab" : NULL; }

static const char* const k_names[] = {"up", "down", "left", "right", "bl", "br", "ok", "back", "toggle"};

int main(int argc, char** argv)
{
    char cmd[32];
    while (scanf("%31s", cmd) == 1) {
        unsigned k;
        if (!strcmp(cmd, "open")) { menu_open(); printf("open %d\n", menu_is_open()); continue; }
        if (!strcmp(cmd, "state")) { int f, t; if (scanf("%d %d", &f, &t) != 2) return 1; menu_set_state(f, t); continue; }
        if (!strcmp(cmd, "draw")) {
            int w, h, x, y;
            char path[256];
            static unsigned char px[1280 * 960 * 4];
            FILE* f;
            if (scanf("%d %d %255s", &w, &h, path) != 3 || w * h > 1280 * 960) return 1;
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++) {
                    unsigned char* p = px + ((size_t)y * w + x) * 4;
                    p[0] = (unsigned char)(x & 0xFF); p[1] = (unsigned char)(y & 0xFF); p[2] = 0x80; p[3] = 0xFF;
                }
            menu_draw(px, w, h, w * 4);
            f = fopen(path, "wb");
            if (!f) return 1;
            fwrite(px, 1, (size_t)w * h * 4, f);
            fclose(f);
            printf("drawn %dx%d\n", w, h);
            continue;
        }
        for (k = 0; k < sizeof k_names / sizeof k_names[0] && strcmp(cmd, k_names[k]); k++) {}
        if (k == sizeof k_names / sizeof k_names[0]) { printf("unknown %s\n", cmd); return 1; }
        {
            int act = menu_input((int)k); /* before menu_is_open: argument order is the compiler's */
            printf("%s -> %d open %d\n", cmd, act, menu_is_open());
        }
    }
    (void)argc; (void)argv;
    return 0;
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    if toolchain.compiler_path(PROFILE) is None:
        pytest.skip(f"no {PROFILE.name}")
    out = tmp_path_factory.mktemp("menu")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / ("menu" + PROFILE.exeext)
    proc = toolchain.cc(
        [
            *PROFILE.cflags,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "menu.c"),
            str(out / "driver.c"),
            "/Fe" + str(exe),
        ],
        out,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def run(driver, script: str, cwd: Path | None = None) -> list[str]:
    proc = subprocess.run(
        [str(driver)], input=script, capture_output=True, text=True, cwd=cwd, timeout=60, check=True
    )
    return proc.stdout.splitlines()


# what menu_input answers: REDRAW 1, CLOSE 2, FULLSCREEN 4, TURBO 8, QUIT 16


def test_the_main_page_s_rows_act(driver):
    """Down to Fullscreen and Turbo, each asks the window to toggle it; Quit
    closes and quits; B on the main page closes."""
    out = run(driver, "open down down down right down left down ok")
    assert out[0] == "open 1"
    assert "right -> 5 open 1" in out and "left -> 9 open 1" in out, out  # fullscreen, turbo
    assert out[-1] == "ok -> 18 open 0", out  # quit and close
    assert run(driver, "open back")[-1] == "back -> 3 open 0"
    assert run(driver, "open toggle")[-1] == "toggle -> 3 open 0"
    assert run(driver, "up")[-1] == "up -> 0 open 0"  # closed: nothing


def test_a_mod_s_options_change_and_are_saved(driver):
    """Mods > Encounter rate: the enum moves right and left from its value,
    the bool flips, the int steps by 1 and by a tenth of its range and stops
    at its ends, the string is not edited. The mutation, left and right
    swapped on an enum, saves `double` first."""
    script = (
        "open down ok ok "  # Mods, then Encounter rate
        "right right left "  # rate: double, off, double
        "down ok "  # hold_b: 0
        "down right br br br br br br br br br br bl "  # strength: 51, 61 ... 100, 90
        "down right back back"  # tag: refused; back to Mods, then main
    )
    saves = [line for line in run(driver, script) if line.startswith("save ")]
    assert saves == [
        "save encounter-rate.rate = double",
        "save encounter-rate.rate = off",
        "save encounter-rate.rate = double",
        "save encounter-rate.hold_b = 0",
        "save encounter-rate.strength = 51",
        "save encounter-rate.strength = 61",
        "save encounter-rate.strength = 71",
        "save encounter-rate.strength = 81",
        "save encounter-rate.strength = 91",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 100",
        "save encounter-rate.strength = 90",
    ], saves


def test_mods_turn_off_and_on_through_mod_order(driver):
    """Right on a loaded mod adds `-ID` to mod_order; on the one already off,
    every entry for it goes; the other entries are kept as they were."""
    out = run_env(driver, "open down ok down right down right", SOA_MOD_ORDER="lab, map-log, -lab")
    saves = [line for line in out if line.startswith("save ")]
    assert saves == ["save mod_order = lab,-lab,-map-log", "save mod_order = -map-log"], saves


def run_env(driver, script: str, **env_set) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(driver)], input=script, capture_output=True, text=True, env=env, timeout=60, check=True
    )
    return proc.stdout.splitlines()


def test_the_settings_page_cycles_closed_keys(driver):
    """From `fit`, right wraps to `integer`; from the port's default, right
    takes the first choice and left the last; left from the first wraps."""
    saves = [
        x for x in run(driver, "open down down ok right down right left") if x.startswith("save ")
    ]
    assert saves == ["save scaler = integer", "save turbo = battle", "save turbo = both"], saves
    saves = [x for x in run(driver, "open down down ok down left") if x.startswith("save ")]
    assert saves == ["save turbo = both"], saves


# ---- the drawing -----------------------------------------------------------


def draw(driver, tmp_path, script: str, w: int, h: int) -> bytes:
    raw = tmp_path / "menu.raw"
    run(driver, f"{script} draw {w} {h} {raw}", cwd=tmp_path)
    return raw.read_bytes()


def background(x: int, y: int) -> tuple[int, int, int]:
    return (x & 0xFF, y & 0xFF, 0x80)


def px(buf: bytes, w: int, x: int, y: int) -> tuple[int, int, int]:
    i = (y * w + x) * 4
    return buf[i], buf[i + 1], buf[i + 2]


def png(path: Path, buf: bytes, w: int, h: int) -> None:
    rows = b"".join(
        b"\0"
        + bytes(
            c
            for i in range(w)
            for c in (buf[(y * w + i) * 4 + 2], buf[(y * w + i) * 4 + 1], buf[(y * w + i) * 4])
        )
        for y in range(h)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def test_a_closed_menu_draws_nothing(driver, tmp_path):
    w, h = 640, 480
    buf = draw(driver, tmp_path, "", w, h)
    assert all(px(buf, w, x, y) == background(x, y) for x, y in ((0, 0), (320, 240), (639, 479)))


def test_the_panel_and_its_text(driver, tmp_path):
    """At 640x480 the panel is drawn at scale 2 in the middle: outside it the
    picture is untouched, inside it dimmed, and the title's first glyph, S,
    is the font's S. The PNG is written for a person to look at. The
    mutation, a glyph row shifted, fails the S."""
    w, h = 640, 480
    buf = draw(driver, tmp_path, "open", w, h)
    png(ROOT / "build" / "menu-main.png", buf, w, h)
    s = 2
    pw, ph = 48 * 6 * s, (6 + 7) * 9 * s  # COLS + 2 cells wide; six rows on the main page
    x0, y0 = (w - pw) // 2, (h - ph) // 2
    for x, y in ((0, 0), (x0 - 1, y0), (x0, y0 - 1), (639, 479)):
        assert px(buf, w, x, y) == background(x, y), (x, y)
    inside = px(buf, w, x0 + 3, y0 + 3 * s)
    assert inside == tuple(c // 4 + 8 for c in background(x0 + 3, y0 + 3 * s)), inside
    glyph = [".####", "#....", "#....", ".###.", "....#", "....#", "####."]  # S
    tx, ty = x0 + 6 * s, y0 + 9 * s // 2 + s
    for r, bits in enumerate(glyph):
        for c, bit in enumerate(bits):
            got = px(buf, w, tx + c * s, ty + r * s)
            lit = got == (0x60, 0xC8, 0xF0)  # TITLE, BGR
            assert lit == (bit == "#"), (r, c, got)
