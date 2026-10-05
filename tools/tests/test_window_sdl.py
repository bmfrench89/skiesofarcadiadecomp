"""The SDL3 window and sound, run for real (portability L10).

runtime/window_sdl.c and audio_sdl.c are the window, the pads and the sound
off Windows. Built with the profile SOA_CC names against the SDL3 that
tools/fetch_sdl.py built into vendor/sdl3, beside audio_out.c, picture.c and
plat.c, with a driver standing in for the renderer and the rest of the port,
and run on an X display (CI's gcc leg: Xvfb): the window opens through SDL's
X11 driver, and

- the picture on the X screen, read back with xwd, is the driver's frame at
  whole pixels: its red, blue and green where they were drawn, in that order
  of bytes (gxr_screen's RGBA is BGRA by the time SDL has it);
- a key typed with xdotool reaches port 1 through window_pad: the key that
  types an x is A, and let go it is nothing;
- SOA_WINDOW_TEST's size: puts the client at 1000x700 with the frame at 1x,
  centred, and says so in window.c's words;
- the [present] report counts the presents, none failed;
- 200 blocks of sound at once, faster than SDL's dummy device takes them,
  keep waveOut's 24 queued and drop the rest, which the report counts.

It needs an X display, xwd and xdotool, and skips without any of them --
which CI's noskip plugin turns into a failure.
"""

import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_sdl  # noqa: E402
from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
VENDOR = ROOT / "vendor"
needs = pytest.mark.skipif(
    PROFILE.name not in ("gcc", "clang")
    or toolchain.compiler_path(PROFILE) is None
    or not fetch_sdl.available(VENDOR)
    or not os.environ.get("DISPLAY")
    or not shutil.which("xwd")
    or not shutil.which("xdotool"),
    reason="needs gcc or clang (SOA_CC), SDL3 in vendor/sdl3 (tools/fetch_sdl.py), an X display, xwd and xdotool",
)

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gxr.h"
#include "plat.h"

void window_start(void);
int window_open(void);
int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]);
void audio_push_block(const uint8_t* be_rl, unsigned bytes, unsigned rate);
void audio_report(void);

/* what the window asks of the rest of the port */
static uint8_t g_screen[EFB_H * EFB_W * 4];
static plat_a32 g_frames;
long gxr_presented(void) { return plat_load32(&g_frames); }
const uint8_t* gxr_screen(int* w, int* h) { *w = 640; *h = 480; return g_screen; }
static void (*g_report)(void);
void hle_on_report(void (*fn)(void)) { g_report = fn; }
void hle_report(void) { if (g_report) g_report(); audio_report(); }
uint64_t irq_retrace_count(void) { return 2u * (uint64_t)plat_load32(&g_frames); }
void watchdog_fallback(void) { printf("watchdog_fallback\n"); }
void si_set_motor_sink(void (*fn)(unsigned speed)) { (void)fn; }
void si_set_motor_window(int open) { (void)open; }
void si_motor_stop(void) {}
int tick_turbo_now(void) { return 0; }
void clock_pause(int on) { (void)on; }

static void frames(int n)
{
    while (n-- > 0) { plat_inc32(&g_frames); plat_sleep_ms(33); }
}

static void pad(const char* when)
{
    uint16_t b = 0;
    uint8_t s[2], c[2], t[2];
    window_pad(&b, s, c, t);
    printf("pad %s: %04x stick %u,%u\n", when, b, s[0], s[1]);
}

int main(void)
{
    static uint8_t blk[640];
    int i, x, y;
    /* RGBA, as gxr_screen gives it: the left half red, the right half blue,
     * and a green square at the top left */
    for (y = 0; y < 480; y++)
        for (x = 0; x < 640; x++) {
            uint8_t* p = g_screen + ((size_t)y * EFB_W + x) * 4;
            int green = x < 32 && y < 32;
            p[0] = green ? 0 : x < 320 ? 255 : 0;
            p[1] = green ? 255 : 0;
            p[2] = green ? 0 : x < 320 ? 0 : 255;
            p[3] = 255;
        }
    window_start();
    for (i = 0; i < 1000 && !window_open(); i++) plat_sleep_ms(10);
    if (!window_open()) { printf("no window\n"); return 2; }
    frames(30);
    if (system("xwd -root -silent -out shot.xwd") != 0) printf("xwd failed\n");
    if (system("xdotool search --name 'Skies of Arcadia' windowfocus --sync") != 0) printf("no focus\n");
    plat_sleep_ms(200);
    if (system("xdotool keydown x") != 0) printf("xdotool failed\n");
    plat_sleep_ms(300);
    pad("with x held");
    if (system("xdotool keyup x") != 0) printf("xdotool failed\n");
    plat_sleep_ms(300);
    pad("with x let go");
    frames(80); /* SOA_WINDOW_TEST's size at frame 40, and two seconds more for the X server to do it
                 * and the window to say so: a loaded machine took over 330 ms */
    for (i = 0; i < 200; i++) audio_push_block(blk, sizeof blk, 32000);
    fflush(stdout);
    hle_report();
    return 0;
}
"""


class Xwd:
    """A ZPixmap xwd of a 24-bit display, its pixels B, G, R (LSB first), in
    3 or 4 bytes each: Xvfb writes either, by how it was started."""

    def __init__(self, path: Path):
        data = path.read_bytes()
        h = struct.unpack_from(">25I", data, 0)
        header, self.width, self.height = h[0], h[4], h[5]
        byte_order, bpp, self.line, ncolors = h[7], h[11], h[12], h[19]
        assert bpp in (24, 32) and byte_order == 0, (bpp, byte_order)
        self.step = bpp // 8
        self.px = data[header + 12 * ncolors :]

    def first(self, rgb):
        """(x, y) of the first pixel of this colour in reading order, found
        on a whole pixel."""
        want = bytes(reversed(rgb))
        at = self.px.find(want)
        while at >= 0 and (at % self.line) % self.step:
            at = self.px.find(want, at + 1)
        return None if at < 0 else ((at % self.line) // self.step, at // self.line)

    def pixel(self, x, y):
        o = y * self.line + self.step * x
        return (self.px[o + 2], self.px[o + 1], self.px[o])


@needs
def test_the_sdl_window_shows_the_frame_reads_a_key_and_drops_sound_it_cannot_queue(tmp_path):
    (tmp_path / "driver.c").write_text(DRIVER, encoding="utf-8")
    flags, libs = fetch_sdl.link_args(VENDOR)
    runtime = ROOT / "runtime"
    sources = [
        runtime / "window_sdl.c",
        runtime / "audio_sdl.c",
        runtime / "audio_out.c",
        runtime / "picture.c",
        *toolchain.runtime_support_sources(),
        tmp_path / "driver.c",
    ]
    exe = tmp_path / "window_sdl"
    proc = toolchain.cc(
        [
            *PROFILE.cflags,
            *flags,
            f"/I{runtime}",
            *map(str, sources),
            f"/Fe{exe}",
            *libs,
            *PROFILE.linker,
        ],
        tmp_path,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    env = {k: v for k, v in os.environ.items() if not k.startswith(("SOA_", "SDL_"))}
    env.update(SOA_SCALE="1", SOA_WINDOW_TEST="size:1000x700@40", SDL_AUDIO_DRIVER="dummy")
    run = subprocess.run(
        [str(exe)], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=120
    )
    out, err = run.stdout, run.stderr
    assert run.returncode == 0, out + err
    assert "[window] open at 1x, presenting with SDL3's" in err and "(video x11)" in err, err

    # the picture, as X has it
    shot = Xwd(tmp_path / "shot.xwd")
    corner = shot.first((0, 255, 0))  # the frame's top-left corner, on a black screen
    assert corner, "no green on the X screen: the frame was not shown"
    left, top = corner
    assert left + 640 < shot.width and top + 480 < shot.height, (corner, shot.width)
    samples = {
        (10, 10): (0, 255, 0),
        (31, 31): (0, 255, 0),
        (40, 10): (255, 0, 0),
        (100, 240): (255, 0, 0),
        (319, 479): (255, 0, 0),
        (320, 0): (0, 0, 255),
        (639, 479): (0, 0, 255),
        (640, 240): (0, 0, 0),  # 640 wide at 1x, black past it
        (320, 480): (0, 0, 0),  # and 480 high
    }
    seen = {xy: shot.pixel(left + xy[0], top + xy[1]) for xy in samples}
    assert seen == samples, (corner, seen)

    # the keyboard, through window_pad
    assert "pad with x held: 0100 stick 128,128" in out, out + err
    assert "pad with x let go: 0000 stick 128,128" in out, out + err

    # SOA_WINDOW_TEST, in window.c's words
    assert re.search(
        r"\[window\] frame 4\d: client 1000x700, image 640x480 at \+180\+110, from 640x480, "
        r"monitor \d+x\d+, mode integer window",
        err,
    ), err

    # the presents: of 50 frames, a loaded machine shows fewer, since the
    # window shows the newest frame and skips any it missed (41 of 50 with
    # every core of a 16-core container busy); none shown says "fewer than two"
    m = re.search(r"\[present\] sdl3 \S+ renderer: (\d+) intervals between presents", err)
    assert m and int(m.group(1)) >= 20, err
    assert "[present] 0 failed present(s), 0 failed resize(s)" in err, err

    # the sound: 24 blocks queued, give or take what the device took meanwhile
    assert "[audio] output open at 32000 Hz, through SDL3's dummy driver" in err, err
    m = re.search(r"\[audio\] 200 DMA blocks, peak sample 0; (\d+) played, (\d+) dropped", err)
    assert m, err
    played, dropped = int(m.group(1)), int(m.group(2))
    assert 24 <= played <= 40 and played + dropped == 200, (played, dropped)
