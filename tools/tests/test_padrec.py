"""Tests for recording and replaying controller input (PLAN D3).

The claim D3 makes is that what the port read in a window can be written down
and played back to the guest byte for byte. Nothing checks that by reading the
code: the recorder, the parser and the cursor all have to agree about frames,
about which read of a frame is the frame's input, and about what a line that
leaves fields off means.

So these tests build ``runtime/si.c`` with stubs -- no window, no interrupts,
no disc -- and drive it the way the guest does: enable polling, call
``si_poll`` twice a frame and read the eight-byte report out of INBUFH/INBUFL.
A first run records a fake player who moves the stick and the C stick to
values a ``SOA_PAD`` script could not express; a second run replays the file
with no player at all. The two runs' reports have to be the same bytes at the
same frames.

Everything else here is one of the ways a recording is not self-contained: a
file that ends with a button held, a replay in a different configuration, a
replay whose frames pass at a different rate, and a second session that would
otherwise overwrite the first.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

# The guest, in miniature. gx_frame_count and irq_retrace_count are what si.c
# keys a recording by, so the driver owns both and can make frames and guest
# time pass at whatever rate an argument asks for -- which is the one thing a
# real recording and a real replay never agree about.
DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void si_poll(void);
void si_report(void);
int si_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out);
int si_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v);
void si_set_config_extra(const char* extra);
void si_set_path_root(const char* root);
void si_set_chord_handler(void (*fn)(int chord, unsigned frame));
uint32_t si_host_buttons(void);

/* The window's host buttons (CH1): none here -- a script's are the test. */
int window_host(uint16_t* host) { (void)host; return 0; }
static void chord(int c, unsigned f) { printf("chord %u %d\n", f, c); }

static unsigned g_frame;
static uint64_t g_retrace;
static int g_live;

unsigned gx_frame_count(void) { return g_frame; }
uint64_t irq_retrace_count(void) { return g_retrace; }
void gx_set_frame_limit(unsigned frames)
{
    fprintf(stderr, "[driver] the run would stop at frame %u\n", frames);
}

/* A player who does things a script cannot say: the stick at values between
 * the middle and the edge, the C stick somewhere else again, and a trigger
 * coming down gradually. All a function of the frame, so both runs of the
 * driver would produce it identically if both were asked to -- only the
 * recording run is. */
int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2])
{
    unsigned f = g_frame;
    if (!g_live) return 0;
    *buttons = 0;
    stick[0] = stick[1] = 128;
    cstick[0] = cstick[1] = 128;
    trig[0] = trig[1] = 0;
    if ((f / 10) % 3 == 1) *buttons |= 0x0100;           /* A, ten frames in thirty */
    if (f == 70) *buttons |= 0x1000;                     /* START, once */
    if (f >= 20 && f < 60) { stick[0] = (uint8_t)(108 + f % 41); stick[1] = 200; }
    if (f >= 40 && f < 50) { cstick[0] = 60; cstick[1] = 190; trig[0] = (uint8_t)(3 * f); }
    return 1;
}

int main(int argc, char** argv)
{
    unsigned last = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 100u;
    unsigned per = argc > 3 ? (unsigned)strtoul(argv[3], NULL, 10) : 2u;
    unsigned reads = argc > 4 ? (unsigned)strtoul(argv[4], NULL, 10) : 2u;
    uint64_t hi = 0, lo = 0, was_hi = ~0ull, was_lo = ~0ull;
    uint32_t was_host = 0;
    unsigned f, k;
    si_set_chord_handler(chord);
    g_live = argc > 1 && strcmp(argv[1], "record") == 0;
    if (getenv("DRIVER_ROOT")) si_set_path_root(getenv("DRIVER_ROOT")); /* main.c's settings_root (M5b) */
    if (getenv("DRIVER_EXTRA")) {
        /* What main.c hands over -- recorded settings and the mod list -- as
         * this many bytes: big=aaa...END. */
        size_t n = (size_t)strtoul(getenv("DRIVER_EXTRA"), NULL, 10);
        char* b = (char*)malloc(n + 1);
        memset(b, 'a', n);
        memcpy(b, "big=", 4);
        memcpy(b + n - 3, "END", 3);
        b[n] = '\0';
        si_set_config_extra(b);
        free(b);
    }
    si_write(NULL, 0xCC006430u, 4, 0x80u); /* SIPOLL: channel 0 polled every field */
    for (f = 0; f <= last; f++) {
        g_frame = f;
        g_retrace = (uint64_t)f * per;
        /* Twice, as the guest does: the field poll and a direct transfer. */
        for (k = 0; k < reads; k++) si_poll();
        if (si_host_buttons() != was_host) {
            was_host = si_host_buttons();
            printf("host %u %X\n", f, (unsigned)was_host);
        }
        si_read(NULL, 0xCC006404u, 4, &hi);
        si_read(NULL, 0xCC006408u, 4, &lo);
        if (hi != was_hi || lo != was_lo) {
            printf("%u %08llX %08llX\n", f, (unsigned long long)hi, (unsigned long long)lo);
            was_hi = hi;
            was_lo = lo;
        }
    }
    si_report();
    return 0;
}
"""


needs_msvc = pytest.mark.skipif(
    toolchain.cl_path() is None, reason="no MSVC: runtime/si.c cannot be built here"
)


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    """One build for the whole file: si.c and the miniature guest above."""
    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("padrec")
    (out / "driver.c").write_text(DRIVER)
    exe = out / "pad.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "si.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return exe


def run(driver, tmp_path, mode, env=None, last=100, per=2, reads=2):
    """One run of the driver. Reports go to stdout, everything si.c says to
    stderr, so the two are never confused for each other."""
    e = dict(os.environ)
    for name in (
        "SOA_PAD",
        "SOA_PAD_RECORD",
        "SOA_PAD_FILE",
        "SOA_PAD_STOP",
        "SOA_FRAMES",
        "SOA_UNCAP",
    ):
        e.pop(name, None)
    # The configuration line a recording carries: pin every switch it names, so
    # a machine with any of them set in the environment does not fail the test
    # with a configuration difference that is really the shell's.
    e.update(
        {
            "SOA_RENDER": "1",
            "SOA_WINDOW": "1",
            "SOA_SPEED": "1",
            "SOA_SCALE": "2",
            "SOA_THREADS": "1",
            "SOA_CARD": str(tmp_path / "card.raw"),
        }
    )
    e.update(env or {})
    proc = subprocess.run(
        [str(driver), mode, str(last), str(per), str(reads)],
        capture_output=True,
        text=True,
        env=e,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout, proc.stderr


@needs_msvc
def test_a_recording_replays_to_the_same_reports(driver, tmp_path):
    """The whole of D3 in one assertion: the eight bytes the guest reads, at
    the frames it reads them, are the same in the replay as in the session."""
    rec = tmp_path / "play.pad"
    played, _ = run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec)})
    text = rec.read_text()
    assert text.startswith("# soa pad recording v2"), text[:200]
    assert "# config " in text
    again, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)})
    assert again == played, "the replay read different bytes:\n" + text
    assert played.count("\n") > 8, "the fake player barely moved; the test proves little"
    # And the values a SOA_PAD script cannot express really are in there.
    assert " 148,200" in text or " 120,200" in text, text
    assert "60,190" in text and "," in text
    assert "[pad] replayed" in err


@needs_msvc
def test_a_recording_that_ends_with_a_button_held_lets_go(driver, tmp_path):
    """A file cut by hand at the save point, or a session killed with Ctrl-C,
    ends on whatever was held. Replaying that would hold the button for the
    rest of the run, so the loader adds the release the writer never wrote."""
    rec = tmp_path / "trimmed.pad"
    rec.write_text("# soa pad recording v2\n10 a\n20 start+a 255,128\n")
    out, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)})
    assert "ends with input still held" in err, err
    assert "a neutral state is added at frame 21" in err, err
    # The last report of the run is a released controller, not START+A.
    last = out.strip().splitlines()[-1].split()
    assert last[0] == "21", out
    # INBUFH is buttons, buttons, stick x, stick y; INBUFL the C stick and the
    # two triggers. Nothing pressed, both sticks centred, both triggers up.
    assert last[1] == "00808080" and last[2] == "80800000", out


@needs_msvc
def test_the_run_ends_when_the_recording_does(driver, tmp_path):
    """Nothing used to end a headless replay: it ran on with the controller
    neutral until a frame count the operator had to guess. The cursor passing
    the last line is that number, known exactly."""
    rec = tmp_path / "short.pad"
    rec.write_text("# soa pad recording v2\n5 a\n6 -\n")
    _, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec), "SOA_PAD_STOP": "4"})
    assert "the recording ran out at frame 7" in err, err
    assert "[driver] the run would stop at frame 11" in err, err
    _, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec), "SOA_PAD_STOP": "0"})
    assert "SOA_PAD_STOP=0" in err, err
    assert "[driver] the run would stop" not in err, err


@needs_msvc
def test_a_replay_at_another_rate_says_how_far_it_has_drifted(driver, tmp_path):
    """Frames are the key and guest time is the clock, and the two only keep
    step while the port produces frames at the rate it did when recording.
    The recording carries the retrace count so a replay can say how far apart
    they have come instead of walking into the wrong menu quietly."""
    rec = tmp_path / "play.pad"
    run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec)}, per=2)
    _, same = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)}, per=2)
    assert "the recording read this state at retrace" not in same, same
    assert "drift against the recording" not in same, same
    # Four retraces a frame instead of two: the replay is two retraces of guest
    # time further on with every frame, which passes two seconds' worth before
    # the fake player is done, and the replay says so.
    _, drifted = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)}, per=4)
    assert "the recording read this state at retrace" in drifted, drifted
    assert "drift against the recording" in drifted, drifted


@needs_msvc
def test_a_replay_in_another_configuration_says_so(driver, tmp_path):
    """The switches that change how many frames pass per second of guest time,
    and the memory card, which changes what the game's own menus hold."""
    rec = tmp_path / "play.pad"
    run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec)}, last=20)
    _, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec), "SOA_SPEED": "3"}, last=20)
    assert "recorded with" in err and "replaying with" in err, err
    assert "speed=1" in err and "speed=3" in err, err


@needs_msvc
def test_a_second_session_does_not_overwrite_the_first(driver, tmp_path):
    """The file is an hour of somebody's play; a second run with the same
    switch set writes beside it rather than over it."""
    rec = tmp_path / "play.pad"
    run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec)}, last=30)
    first = rec.read_text()
    _, err = run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec)}, last=10)
    assert "is already there" in err, err
    assert rec.read_text() == first
    assert (tmp_path / "play.pad.1").exists()


@needs_msvc
def test_a_v1_recording_still_replays(driver, tmp_path):
    """The retrace counts and the configuration line are comments, so the
    recordings and the hand-written lines that came before them still work --
    and the run says which check it cannot make for them."""
    rec = tmp_path / "old.pad"
    rec.write_text("# soa pad recording v1\n3 a\n4 -\n8 start 128,255\n9 -\n")
    out, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)}, last=12)
    assert "records no configuration" in err, err
    assert "drift" not in err, err
    frames = [line.split()[0] for line in out.strip().splitlines()]
    assert frames == ["0", "3", "4", "8", "9"], out


# Each of these used to parse as three events, one of which pressed nothing,
# with nothing said: si.c looked a name up by exact length, so "start " and
# "START" were names it did not know, and "#" with no number held for zero
# frames. scenario.py's parse_pad has always refused them; SOA_PAD typed by
# hand -- which is how the teleport experiments are driven -- never meets it.
@needs_msvc
@pytest.mark.parametrize(
    "bad",
    [
        "20:START",  # upper case
        "20:strat",  # a typo
        "20:start ",  # the space is part of the name
        " 20:start",  # and strtoul would skip this one
        "20:start#",  # held for no frames
        "20:start@",  # repeated every no frames
        "20:",  # nothing named at all
        "20:a++b",  # an empty name between two '+'
        "20:a@5x",  # trailing junk
    ],
)
def test_a_script_item_si_cannot_read_stops_the_parse_and_is_named(driver, tmp_path, bad):
    script = f"10:a,{bad},30:b"
    _, err = run(driver, tmp_path, "script", {"SOA_PAD": script}, last=40)
    assert "[si] 1 scripted controller events" in err, err
    assert f'not understood from "{bad},30:b"' in err, err


@needs_msvc
def test_a_script_with_every_form_si_reads_parses_whole(driver, tmp_path):
    """The control for the test above: the forms that are right still are."""
    script = "10:a+sup@30#5,20:start,25:sdown+sleft+sright+b+x+y+z+l+r+up+down+left+right,"
    _, err = run(driver, tmp_path, "script", {"SOA_PAD": script}, last=40)
    assert "[si] 3 scripted controller events" in err, err
    assert "not understood" not in err, err


@needs_msvc
def test_an_uncapped_recording_says_so_and_a_capped_one_is_unchanged(driver, tmp_path):
    """SOA_UNCAP changes how many frames a second of guest time holds, which
    a recording is keyed by; it is named when on, and a recording made
    without it carries exactly the line it always did."""
    rec = tmp_path / "fast.pad"
    run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec), "SOA_UNCAP": "3300"}, last=20)
    assert " uncap=3300" in rec.read_text(), rec.read_text()[:300]
    _, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)}, last=20)
    assert "recorded with" in err and "uncap=3300" in err, err
    plain = tmp_path / "plain.pad"
    run(driver, tmp_path, "record", {"SOA_PAD_RECORD": str(plain)}, last=20)
    assert " uncap=" not in plain.read_text()  # the temp path itself contains "uncap"


@needs_msvc
def test_a_long_config_line_arrives_whole_and_a_longer_one_says_it_was_cut(driver, tmp_path):
    """Recorded settings and the mod list share the recording's config line
    (PLAN-GAMEPLAY-MODS P6). Six hundred bytes of them reach it whole and
    read back the same; eight hundred do not fit, and the cut is said out
    loud instead of dropping a setting a replay needed. The mutation is the
    320-byte buffer this replaced, which fails the first half."""
    rec = tmp_path / "long.pad"
    _, err = run(
        driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec), "DRIVER_EXTRA": "600"}, last=5
    )
    cfg = [ln for ln in rec.read_text().splitlines() if ln.startswith("# config ")]
    assert len(cfg) == 1 and cfg[0].endswith(" big=" + "a" * 593 + "END"), cfg
    assert "cut at" not in err, err
    _, err = run(
        driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec), "DRIVER_EXTRA": "600"}, last=5
    )
    assert "recorded with" not in err, err  # read back whole, so no difference is claimed
    rec2 = tmp_path / "longer.pad"
    _, err = run(
        driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec2), "DRIVER_EXTRA": "800"}, last=5
    )
    assert "[pad] the config line was cut at 639 bytes of 800" in err, err
    assert "END" not in rec2.read_text()


# --------------------------------------------------------------------------
# host buttons and chords (CH1)
# --------------------------------------------------------------------------


def reports(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln[:1].isdigit()]


@needs_msvc
def test_host_buttons_come_from_the_script_and_never_reach_the_game(driver, tmp_path):
    """view+lb held ten frames: the host bits are View and LB for exactly
    those frames, the chord fires once, and not one GameCube bit moves --
    the reports are the neutral pad's from start to end."""
    out, err = run(driver, tmp_path, "script", {"SOA_PAD": "5:view+lb"}, last=30)
    assert "host 5 3" in out and "host 15 0" in out, out
    assert [ln for ln in out.splitlines() if ln.startswith("chord")] == ["chord 5 0"], out
    neutral, _ = run(driver, tmp_path, "script", {"SOA_PAD": "40:a"}, last=30)
    assert reports(out) == reports(neutral), (out, neutral)
    assert "1 scripted controller events" in err, err


@needs_msvc
def test_a_chord_fires_once_on_the_frame_its_last_button_goes_down(driver, tmp_path):
    """Held ten frames and read three times a frame, a chord fires once. LB
    alone is not a chord; View arriving while LB is held fires it then."""
    out, _ = run(driver, tmp_path, "script", {"SOA_PAD": "10:view+rs"}, last=40, reads=3)
    assert [ln for ln in out.splitlines() if ln.startswith("chord")] == ["chord 10 1"], out
    out, _ = run(driver, tmp_path, "script", {"SOA_PAD": "20:lb#30,30:view,60:view+ls"}, last=80)
    assert [ln for ln in out.splitlines() if ln.startswith("chord")] == [
        "chord 30 0",
        "chord 60 2",
    ], out


@needs_msvc
@pytest.mark.parametrize("name", ["lb", "view", "ls", "rs"])
def test_each_host_button_parses(driver, tmp_path, name):
    out, err = run(driver, tmp_path, "script", {"SOA_PAD": f"3:{name}"}, last=10)
    assert "1 scripted controller events" in err and "not understood" not in err, err
    assert "host 3 " in out, out


@needs_msvc
def test_a_misspelt_host_button_is_refused(driver, tmp_path):
    _, err = run(driver, tmp_path, "script", {"SOA_PAD": "3:lbb"}, last=10)
    assert "parsed no events" in err, err


@needs_msvc
def test_a_chord_is_a_comment_in_the_recording_and_not_replayed(driver, tmp_path):
    """The recording says the chord happened; the replay is the whole input,
    so it carries no host buttons and fires no chord, and plays the same."""
    rec = tmp_path / "chord.pad"
    live, _ = run(
        driver, tmp_path, "record", {"SOA_PAD_RECORD": str(rec), "SOA_PAD": "12:view+lb"}, last=40
    )
    assert "# chord 12 view+lb fullscreen" in rec.read_text(), rec.read_text()
    assert "chord 12 0" in live, live
    again, err = run(driver, tmp_path, "replay", {"SOA_PAD_FILE": str(rec)}, last=40)
    assert "chord" not in again and "host" not in again, again
    assert reports(again) == reports(live), (live, again)


@needs_msvc
def test_a_card_under_the_root_is_named_relative_to_it(driver, tmp_path):
    """M5b: a recording names a card under the port root by its path from
    the root, so a double-click's recording and scenario.py's replay agree;
    a card elsewhere is named as given."""
    rec = tmp_path / "rooted.pad"
    (tmp_path / "cards").mkdir()
    card = tmp_path / "cards" / "c.raw"
    run(
        driver,
        tmp_path,
        "record",
        {"SOA_PAD_RECORD": str(rec), "SOA_CARD": str(card), "DRIVER_ROOT": str(tmp_path)},
        last=5,
    )
    assert " card=cards\\c.raw:" in rec.read_text(), rec.read_text()
    elsewhere = tmp_path / "elsewhere.pad"
    run(
        driver,
        tmp_path,
        "record",
        {
            "SOA_PAD_RECORD": str(elsewhere),
            "SOA_CARD": str(card),
            "DRIVER_ROOT": str(tmp_path / "nothere"),
        },
        last=5,
    )
    assert f" card={card}:" in elsewhere.read_text(), elsewhere.read_text()
