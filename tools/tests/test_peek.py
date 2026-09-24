"""SOA_PEEK and SOA_WATCH_FROM: reading guest memory at a chosen frame (PLAN S4a).

A read tied to a frame is what "how many fields does this fade take" needs,
and SOA_WATCH could not give it: it stops after 201 hits and said which store,
not when -- a word stored every frame from boot spent all 201 on the logos.
SOA_PEEK prints a word at a frame or across a range of frames, with the game's
retrace count; SOA_WATCH_FROM starts a watch at a frame; every watch line now
carries the game's frame counter.

As with SOA_POKE, what a test without a disc can hold is the switch itself:
a malformed item is refused out loud, a well-formed list is counted, and the
parse happens at startup. That a peek reads what the game wrote at that frame
is checked by a run, and FINDINGS records the run.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_memguard import build, needs_msvc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def run(exe, tmp_path, **env_set):
    """One boot with no disc: main() parses the switches, finds no
    sys/main.dol and stops, which is as far as this needs to go."""
    env = dict(os.environ)
    for name in ("SOA_POKE", "SOA_PEEK", "SOA_WATCH", "SOA_WATCH_FROM", "SOA_MEMPOKE"):
        env.pop(name, None)
    env.update(env_set)
    proc = subprocess.run(
        [str(exe), str(tmp_path / "no-disc-here")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    return proc.stdout + proc.stderr


@needs_msvc
def test_well_formed_peeks_are_armed_and_counted(tmp_path):
    """A single frame, a range, and a decimal address, in one switch."""
    out = run(
        build(tmp_path), tmp_path, SOA_PEEK="0x80347510@3300,0x803475C0@3300-3400,2150987012@10"
    )
    assert "[peek] 3 peek(s) armed" in out, out
    assert "stopped at" not in out, out


@needs_msvc
@pytest.mark.parametrize(
    "bad,why",
    [
        ("0x80347510", "no frame at all"),
        ("0x80347510@", "an @ with no frame"),
        ("0x80347510@3400-3300", "a range that ends before it starts"),
        ("0x80347510@3300-", "a range with no end"),
        ("@3300", "no address"),
        ("0x80347510@3300x", "junk after the frame"),
        ("0x80347510:3300", "a poke's colon where the @ goes"),
        ("0x180347510@1", "an address past 32 bits"),
    ],
    ids=[
        "no-frame",
        "empty-frame",
        "backwards",
        "open-range",
        "no-address",
        "junk",
        "colon",
        "wide",
    ],
)
def test_a_malformed_peek_is_refused_out_loud(tmp_path, bad, why):
    out = run(build(tmp_path), tmp_path, SOA_PEEK=bad)
    assert "[peek] SOA_PEEK: stopped at" in out, f"{why}: {out}"


@needs_msvc
def test_peeks_and_pokes_are_separate_lists(tmp_path):
    """Its own list: arming peeks does not spend SOA_POKE's 256."""
    out = run(
        build(tmp_path),
        tmp_path,
        SOA_PEEK="0x80347510@1,0x80347518@1",
        SOA_POKE="1:0x80347518=0",
    )
    assert "[peek] 2 peek(s) armed" in out, out
    assert "[poke] 1 poke(s) armed" in out, out


# The watch lives in trace.c, which the boot build above stubs out, so it gets
# a build of its own: trace.c, a driver that stores the game's frame counter
# and reports a store, and stubs for what cpu.h's accessors can reach.
WATCH_DRIVER = r"""
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void watch_init(void);
void watch_hit(CpuState* s, uint32_t ea, unsigned size, uint64_t v);
extern uint32_t g_watch_addr, g_watch_len;
void guest_backtrace(CpuState* s, uint32_t sp) { (void)s; (void)sp; fprintf(stderr, "\n"); }
uint8_t mmio_read8(CpuState* s, uint32_t ea) { (void)s; (void)ea; return 0; }
uint16_t mmio_read16(CpuState* s, uint32_t ea) { (void)s; (void)ea; return 0; }
uint32_t mmio_read32(CpuState* s, uint32_t ea) { (void)s; (void)ea; return 0; }
uint64_t mmio_read64(CpuState* s, uint32_t ea) { (void)s; (void)ea; return 0; }
void mmio_write8(CpuState* s, uint32_t ea, uint8_t v) { (void)s; (void)ea; (void)v; }
void mmio_write16(CpuState* s, uint32_t ea, uint16_t v) { (void)s; (void)ea; (void)v; }
void mmio_write32(CpuState* s, uint32_t ea, uint32_t v) { (void)s; (void)ea; (void)v; }
void mmio_write64(CpuState* s, uint32_t ea, uint64_t v) { (void)s; (void)ea; (void)v; }
void gx_pipe_write(CpuState* s, unsigned size, uint64_t v) { (void)s; (void)size; (void)v; }
int main(void)
{
    static CpuState s;
    unsigned frames[] = {10, 3299, 3300, 3301};
    unsigned i;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    watch_init();
    for (i = 0; i < 4; i++) {
        /* the game's frame counter, 0x803475C0, big-endian as in the guest */
        uint32_t be = ((frames[i] & 0xFF) << 24) | ((frames[i] & 0xFF00) << 8) | ((frames[i] >> 8) & 0xFF00) | (frames[i] >> 24);
        memcpy(s.mem + (0x803475C0u & MEM_MASK), &be, 4);
        watch_hit(&s, 0x8034768Cu, 4, frames[i]);
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def watch_driver(tmp_path_factory):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("watch")
    (out / "driver.c").write_text(WATCH_DRIVER)
    exe = out / "watch.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "trace.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def watch(exe, **env_set):
    env = dict(os.environ)
    for name in ("SOA_WATCH", "SOA_WATCH_FROM"):
        env.pop(name, None)
    env.update(env_set)
    proc = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    return proc.stderr


@needs_msvc
def test_a_watch_aimed_at_a_frame_prints_only_from_that_frame(watch_driver):
    """Stores at frames 10 and 3299 are skipped; 3300 and 3301 print, each
    with the frame it happened in -- and the skipped ones do not count
    against the 201 lines, which is the point of aiming it."""
    err = watch(watch_driver, SOA_WATCH="0x8034768C", SOA_WATCH_FROM="3300")
    assert "[watch] 8034768C..80347690 from frame 3300" in err, err
    hits = [line for line in err.splitlines() if line.startswith("[watch] 8034768C/4")]
    assert [h.split(" frame ")[1].rstrip(";") for h in hits] == ["3300", "3301"], err


@needs_msvc
def test_every_watch_line_carries_its_frame(watch_driver):
    err = watch(watch_driver, SOA_WATCH="0x8034768C")
    hits = [line for line in err.splitlines() if line.startswith("[watch] 8034768C/4")]
    assert [h.split(" frame ")[1].rstrip(";") for h in hits] == ["10", "3299", "3300", "3301"], err


@needs_msvc
def test_no_switch_says_nothing(tmp_path):
    assert "[peek]" not in run(build(tmp_path), tmp_path)


def test_the_switches_are_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for switch in ("`SOA_PEEK=", "SOA_WATCH_FROM"):
        assert switch in readme, f"{switch} is not in the README's switch table"
