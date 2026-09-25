"""runtime/tick.c: VIGetRetraceCount answered natively (PLAN-60FPS-MODS M2).

The original is `lwz r3,-27836(r13); blr`. The native one must be that
everywhere but at the main loop's two call sites, told apart by lr: at
0x801DCB88, the top of the loop, it first runs the safe-point callbacks; at
0x801DC49C, the frame end's spin, once the tick is unlocked from a frame, it
answers the frame's start plus one so the spin leaves after one field.

Built alone here with a driver playing the game's side. The self test holds
the native function to its recompiled twin on random counts in the real
binary; that the game then runs a frame a field is a run (FINDINGS "M2").
"""

import os
import subprocess
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void fn_8023F704(CpuState* s);
int tick_on_safe_point(void (*fn)(CpuState*));
void tick_unlock_from(unsigned frame);

uint32_t g_watch_addr, g_watch_len;
void watch_hit(CpuState* s, uint32_t e, unsigned n, uint64_t v) { (void)s; (void)e; (void)n; (void)v; }
void gx_pipe_write(CpuState* s, unsigned n, uint64_t v) { (void)s; (void)n; (void)v; }
uint32_t mmio_read32(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
void mmio_write32(CpuState* s, uint32_t e, uint32_t v) { (void)s; (void)e; (void)v; }

static unsigned g_frame;
static void (*g_report)(void);
unsigned gx_frame_count(void) { return g_frame; }
void hle_on_report(void (*fn)(void)) { g_report = fn; }

static void safe_a(CpuState* s) { printf("safe a %08X\n", s->lr); }
static void safe_b(CpuState* s) { (void)s; printf("safe b\n"); }

/* On stdin:  count V | start V | frame F | unlock F | cb | call LR | report */
int main(void)
{
    static CpuState s;
    char cmd[32];
    unsigned v;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    while (scanf("%31s", cmd) == 1) {
        if (!strcmp(cmd, "count") && scanf("%x", &v) == 1) mem_w32(&s, 0x80347A64u, v);
        else if (!strcmp(cmd, "start") && scanf("%x", &v) == 1) mem_w32(&s, 0x8034768Cu, v);
        else if (!strcmp(cmd, "frame") && scanf("%u", &v) == 1) g_frame = v;
        else if (!strcmp(cmd, "unlock") && scanf("%u", &v) == 1) tick_unlock_from(v);
        else if (!strcmp(cmd, "cb")) { tick_on_safe_point(safe_a); tick_on_safe_point(safe_b); }
        else if (!strcmp(cmd, "call") && scanf("%x", &v) == 1) {
            s.lr = v;
            s.gpr[3] = 0xDEADBEEFu;
            fn_8023F704(&s);
            printf("r3 %08X\n", s.gpr[3]);
        } else if (!strcmp(cmd, "report")) { fflush(stdout); if (g_report) g_report(); fflush(stderr); }
    }
    return 0;
}
"""

TOP, SPIN = "801DCB88", "801DC49C"


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("tick")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "tick.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "tick.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def play(exe, script: str) -> tuple[list[str], str]:
    proc = subprocess.run(
        [str(exe)], input=script, capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines(), proc.stderr


@needs_msvc
def test_it_is_the_original_everywhere_else(driver):
    """lwz r3,-27836(r13): the retrace count, whatever lr says, with nothing
    registered and the tick locked -- the main loop's two sites included."""
    out, _ = play(driver, f"count 1234 start 1000 call 0 call 80001000 call {TOP} call {SPIN}")
    assert out == ["r3 00001234"] * 4


@needs_msvc
def test_the_top_of_the_loop_runs_the_safe_point_callbacks_first(driver):
    """In the order registered, with lr still the call site, and then the
    count as the original returns it: the loop stores it as the frame's start."""
    out, _ = play(driver, f"cb count 77 call {TOP} call 80001000")
    assert out == [f"safe a {TOP}", "safe b", "r3 00000077", "r3 00000077"]


@needs_msvc
def test_unlocked_the_spin_leaves_after_one_field(driver):
    """From the unlock frame on, the spin's call answers start + 1, which is
    count - start = 1 at 0x801DC4A4 and not less: the spin exits. Before that
    frame, and at every other call site, the count."""
    script = (
        f"unlock 3300 count 500 start 4F0 frame 3299 call {SPIN} "
        f"frame 3300 call {SPIN} call {TOP} call 0 "
        f"start 600 frame 4000 call {SPIN} report"
    )
    out, err = play(driver, script)
    assert out == ["r3 00000500", "r3 000004F1", "r3 00000500", "r3 00000500", "r3 00000601"]
    assert "from frame 3300 the frame end's spin was let go after one field 2 times" in err, err


@needs_msvc
def test_the_report_counts_safe_points_against_frames(driver):
    """M2's check in a run: safe points equal presented frames, so every frame
    passed through the top of the loop once."""
    _, err = play(driver, f"call {TOP} call {TOP} call {TOP} call 0 frame 3 report")
    assert "[tick] 3 safe points over 3 presented frames; the tick is locked" in err, err


@needs_msvc
def test_unlocking_at_zero_locks_it_again(driver):
    out, _ = play(driver, f"unlock 1 frame 5 count 9 start 3 call {SPIN} unlock 0 call {SPIN}")
    assert out == ["r3 00000004", "r3 00000009"]


def test_the_binding_is_in_hle_txt():
    """Without the line the translated fn_8023F704 is the only one and this
    file's twin would clash at link (LNK2005); with it, every caller binds
    here. The binding lists' spelling rule applies."""
    text = (ROOT / "config" / "hle.txt").read_text(encoding="utf-8")
    assert any(line.startswith("0x8023F704 ") for line in text.splitlines())
