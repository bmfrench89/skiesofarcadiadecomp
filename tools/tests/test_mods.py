"""runtime/mod.c: mods as data patches (PLAN-60FPS-MODS M1), with no disc.

A mod is a folder under SOA_MODS with a mod.ini (manifest 2's id and version,
name, api, the DOL's SHA-1)
and a patches.txt of `trigger address = value [when condition...]` lines. A
mod with any fault is refused whole and says why, with the file and line --
the binding lists drop a misspelled address without a word, and a mod that
silently lost a line would be a mod that silently does something else.

These build mod.c on its own with a driver that plays the game's side: a
fake DOL with one code section, and a script of memory writes and frame ends
on stdin. That the patches do what they say in the game is a run: FINDINGS
"M1" records the encounters-off pair.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from test_memguard import needs_msvc

ROOT = Path(__file__).resolve().parents[2]

TEXT_START, TEXT_LEN = 0x80003100, 0x1000

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "mod.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* What cpu.h's accessors can reach: none of it is, since every address a
 * patch may name is memory. */
uint32_t g_watch_addr, g_watch_len;
void watch_hit(CpuState* s, uint32_t e, unsigned n, uint64_t v) { (void)s; (void)e; (void)n; (void)v; }
void gx_pipe_write(CpuState* s, unsigned n, uint64_t v) { (void)s; (void)n; (void)v; }
uint8_t mmio_read8(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
uint32_t mmio_read32(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
void mmio_write8(CpuState* s, uint32_t e, uint8_t v) { (void)s; (void)e; (void)v; }
void mmio_write32(CpuState* s, uint32_t e, uint32_t v) { (void)s; (void)e; (void)v; }
uint16_t mmio_read16(CpuState* s, uint32_t e) { (void)s; (void)e; return 0; }
void mmio_write16(CpuState* s, uint32_t e, uint16_t v) { (void)s; (void)e; (void)v; }

/* tick.c's other ends: the frame count and the report hook. */
static unsigned g_frames;
unsigned gx_frame_count(void) { return g_frames; }
void hle_on_report(void (*fn)(void)) { (void)fn; }
static void (*g_pad)(unsigned, void*);
void si_set_pad_filter(void (*fn)(unsigned, void*)) { g_pad = fn; }
static void (*g_proj)(float p[6], int o);
void gxr_set_projection_filter(void (*fn)(float p[6], int o)) { g_proj = fn; }
static int (*g_tex)(uint64_t, uint32_t, uint32_t, uint32_t, const uint8_t*, const uint8_t**, uint32_t*, uint32_t*);
void gxr_set_texture_provider(int (*fn)(uint64_t, uint32_t, uint32_t, uint32_t, const uint8_t*, const uint8_t**,
                                        uint32_t*, uint32_t*)) { g_tex = fn; }
void gxr_hook_hazard(uint32_t a, uint32_t b) { (void)a; (void)b; }
void fn_8023F704(CpuState* s);
/* si.c's host buttons (CH1), as the stub the "host" command sets. */
static uint32_t g_host_now;
static uint32_t host_stub(void) { return g_host_now; }

/* The game's side of call_guest: one function at 0x80003100 that adds r3
 * and r4 and, being careless, clobbers r14, f14 and GQR 3. */
static int g_irq;
int irq_in_handler(void) { return g_irq; }
int dispatch_known(uint32_t a) { return a == 0x80003100u; }
void dispatch(CpuState* s, uint32_t a)
{
    if (a != 0x80003100u) { printf("dispatch of %08X\n", a); return; }
    s->gpr[3] += s->gpr[4];
    s->gpr[14] = 0xDEADDEADu;
    s->fpr[14].ps0 = -1.0;
    s->gqr[3] = 0x12341234u;
}

/* mods.exe MODSDIR DOLFILE, then commands on stdin:
 *   set ADDR VALUE     store a word       setb ADDR VALUE   store a byte
 *   frame              one frame end      get ADDR          print a word
 *   report             mod_report()       describe          mod_describe()
 *   safe               the top of the main loop: VIGetRetraceCount from 0x801DCB88
 *   pad F B            a controller read at frame F with buttons B, through the filter
 *   proj O P0..P5      a new projection (O 1 orthographic), through the filter
 *   tex HASH W H       a W x H texture decoded, its source hash HASH, through the provider
 *   game               the game's registers at a safe point: r2, r13 its, r14 a mark */
int main(int argc, char** argv)
{
    static CpuState s;
    static uint8_t dol[0x2000];
    char cmd[64];
    unsigned frame = 0, a, v;
    FILE* f = fopen(argv[2], "rb");
    size_t n = fread(dol, 1, sizeof dol, f);
    fclose(f);
    (void)argc;
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    mod_set_host_buttons(host_stub);
    printf("loaded %d\n", mod_load(&s, argv[1], dol, n));
    while (scanf("%63s", cmd) == 1) {
        if (!strcmp(cmd, "set") && scanf("%x %x", &a, &v) == 2) mem_w32(&s, a, v);
        else if (!strcmp(cmd, "setb") && scanf("%x %x", &a, &v) == 2) mem_w8(&s, a, (uint8_t)v);
        else if (!strcmp(cmd, "frame")) { mod_frame(&s, frame++); g_frames = frame; }
        else if (!strcmp(cmd, "safe")) { s.lr = 0x801DCB88u; fn_8023F704(&s); }
        else if (!strcmp(cmd, "pad") && scanf("%u %x", &a, &v) == 2) {
            uint8_t pad[8] = {0};
            pad[0] = (uint8_t)v; pad[1] = (uint8_t)(v >> 8); /* PadState's u16, host order */
            if (g_pad) g_pad(a, pad);
            printf("pad %u %04X %s\n", a, (unsigned)(pad[0] | pad[1] << 8), g_pad ? "filtered" : "unfiltered");
        }
        else if (!strcmp(cmd, "proj")) {
            float p[6];
            int o = 0, k;
            if (scanf("%d %f %f %f %f %f %f", &o, &p[0], &p[1], &p[2], &p[3], &p[4], &p[5]) != 7) break;
            if (g_proj) g_proj(p, o);
            printf("proj");
            for (k = 0; k < 6; k++) printf(" %.4f", p[k]);
            printf(" %s" "\n", g_proj ? "filtered" : "unfiltered");
        }
        else if (!strcmp(cmd, "irq")) g_irq = 1;
        else if (!strcmp(cmd, "host") && scanf("%x", &v) == 1) g_host_now = v;
        else if (!strcmp(cmd, "game")) { s.gpr[2] = 0x80350000u; s.gpr[13] = 0x8034E720u; s.gpr[14] = 0x14141414u; }
        else if (!strcmp(cmd, "regs")) printf("r14 %08X gqr3 %08X f14 %.1f\n", s.gpr[14], s.gqr[3], s.fpr[14].ps0);
        else if (!strcmp(cmd, "tex")) {
            unsigned long long hsh;
            unsigned tw, th;
            static uint8_t img[64 * 64 * 4];
            const uint8_t* got = NULL;
            uint32_t gw = 0, gh = 0;
            if (scanf("%llx %u %u", &hsh, &tw, &th) != 3 || tw * th > 64 * 64) break;
            memset(img, 0x11, sizeof img);
            if (g_tex && g_tex(hsh, 14, tw, th, img, &got, &gw, &gh) && got)
                printf("tex replaced %ux%u first %02X%02X%02X%02X" "\n", gw, gh, got[0], got[1], got[2], got[3]);
            else
                printf("tex kept %s" "\n", g_tex ? "(asked)" : "(no provider)");
        }
        else if (!strcmp(cmd, "get") && scanf("%x", &a) == 1) printf("%08X=%08X\n", a, mem_r32(&s, a));
        else if (!strcmp(cmd, "report")) { fflush(stdout); mod_report(); fflush(stderr); }
        else if (!strcmp(cmd, "describe")) printf("describe [%s]\n", mod_describe());
    }
    return 0;
}
"""


def fake_dol() -> bytes:
    """A DOL header with one code section at 0x80003100 and one data
    section, and bytes behind them -- enough for mod.c's text check."""
    head = bytearray(0x100)
    head[0x00:0x04] = (0x100).to_bytes(4, "big")  # text 0: file offset
    head[0x48:0x4C] = TEXT_START.to_bytes(4, "big")
    head[0x90:0x94] = TEXT_LEN.to_bytes(4, "big")
    head[0x1C:0x20] = (0x1100).to_bytes(4, "big")  # data 0
    head[0x64:0x68] = (0x80346000).to_bytes(4, "big")
    head[0xAC:0xB0] = (0x100).to_bytes(4, "big")
    return bytes(head) + bytes(range(256)) * 17


def build_driver(tmp_path_factory, *defines: str):
    from soa import toolchain

    if toolchain.cl_path() is None:
        pytest.skip("no MSVC")
    out = tmp_path_factory.mktemp("mods")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = out / "mods.exe"
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            *[f"/D{d}" for d in defines],
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "runtime" / "mod.c"),
            str(ROOT / "runtime" / "tick.c"),
            str(out / "driver.c"),
            "/Fo" + str(out) + os.sep,
            "/Fe" + str(exe),
        ],
        cwd=out,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    dol = out / "fake.dol"
    dol.write_bytes(fake_dol())
    return exe, dol


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    return build_driver(tmp_path_factory)


SHA = hashlib.sha1(fake_dol()).hexdigest()
PATCH = "every_frame 0x80346d28 = 0 when scene=6\n"


def mod(root: Path, name: str, patches: str | None = PATCH, ini: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if ini is None:
        ini = f"name = {name}\napi = 1\ndol_sha1 = {SHA}\n"
    (d / "mod.ini").write_text(ini, encoding="utf-8")
    if patches is not None:
        (d / "patches.txt").write_text(patches, encoding="utf-8")
    return d


def play(driver, mods: Path, script: str = "", **env_set) -> tuple[str, str]:
    """One run of the fake guest. The environment is this process's with
    every SOA_ switch taken out, so a mod that reads one sees only what the
    test sets."""
    exe, dol = driver
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(env_set)
    proc = subprocess.run(
        [str(exe), str(mods), str(dol)],
        input=script,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, proc.stderr


@needs_msvc
def test_a_good_mod_loads_and_says_so(driver, tmp_path):
    mod(tmp_path, "encounters-off")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert "[mod] loaded encounters-off" in err and "1 patch(es)" in err, err


@needs_msvc
@pytest.mark.parametrize(
    "line, why",
    [
        ("every_frame 0X80346d28 = 0", "is not an address"),
        ("every_frame 0x80346d2 = 0", "is not an address"),
        ("every_frame 80346d28 = 0", "is not an address"),
        ("every_frame 0x080346d28 = 0", "is not an address"),
        ("every_frame 0xcc008000 = 0", "hardware window"),
        ("every_frame 0x81800000 = 0", "outside the console's 24 MB"),
        ("every_frame 0x00346d28 = 0", "outside the console's 24 MB"),
        ("every_frame 0x80346d2a = 0", "not word-aligned"),
        ("every_frame 0x80003100 = 0", "inside the game's code"),
        ("every_frame 0x800040fc = 0", "inside the game's code"),
        ("every_frame 0x80346d28 = 0x1g", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = -1", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 4294967296", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 007", "is not a 32-bit value"),
        ("every_frame 0x80346d28 = 0x123456789", "is not a 32-bit value"),
        ("sometimes 0x80346d28 = 0", "is not a trigger"),
        ("every_frame 0x80346d28 0", "a patch is"),
        ("every_frame 0x80346d28 = 0 scene=6", "after the value comes `when`"),
        ("every_frame 0x80346d28 = 0 when", "after the value comes `when`"),
        ("every_frame 0x80346d28 = 0 when zone=1", "is not a condition this port knows"),
        ("every_frame 0x80346d28 = 0 when scene", "is not a condition"),
        ("every_frame 0x80346d28 = 0 when scene=six", "is not a number for scene"),
        ("every_frame 0x80346d28 = 0 when map=11a", "is not a map"),
        ("every_frame 0x80346d28 = 0 when map=116A", "is not a map"),
    ],
)
def test_each_fault_refuses_the_whole_mod_out_loud(driver, tmp_path, line, why):
    """A good line first and the fault second: the mod is refused whole, so
    the good line never applies either, and the message names file and line."""
    mod(tmp_path, "m", patches=f"# a comment\n{PATCH}{line}\n")
    out, err = play(driver, tmp_path, "set 803475cc 6 set 80346d28 1234 frame get 80346d28")
    assert "loaded 0" in out, err
    assert why in err and "patches.txt:3:" in err and "the mod is not loaded" in err, err
    assert "80346D28=00001234" in out, out


@needs_msvc
@pytest.mark.parametrize(
    "ini, why",
    [
        (f"name = m\napi = 2\ndol_sha1 = {SHA}\n", "this port speaks api 1"),
        (f"name = m\napi = 1\ndol_sha1 = {'0' * 40}\n", f"and this is {SHA}"),
        (f"name = m\napi = 1\ndol_sha1 = {SHA}\nauthor = me\n", "is not a mod.ini key"),
        (f"api = 1\ndol_sha1 = {SHA}\n", "no `name = `"),
        (f"name = m\ndol_sha1 = {SHA}\n", "no `api = 1`"),
        ("name = m\napi = 1\n", "no `dol_sha1 = `"),
        (f"name = m\napi = 1\ndol_sha1 = {SHA}\njust words\n", "is not `key = value`"),
    ],
    ids=["api", "other-dol", "unknown-key", "no-name", "no-api", "no-sha", "not-kv"],
)
def test_a_bad_mod_ini_is_refused(driver, tmp_path, ini, why):
    """The DOL check is what the SHA-1 is for: a patch list is addresses, and
    another build of the game puts other things there."""
    mod(tmp_path, "m", ini=ini)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and why in err, err


@needs_msvc
def test_the_sha1_is_the_dol_s(driver, tmp_path):
    """What the refusal quotes is the real SHA-1 of the bytes booted, so a mod
    author can copy it; hashlib agrees with mod.c's own implementation."""
    mod(tmp_path, "m", ini="name = m\napi = 1\ndol_sha1 = 0\n")
    _, err = play(driver, tmp_path)
    assert f"and this is {SHA}" in err, err
    mod(tmp_path, "m", ini=f"name = m\napi = 1\ndol_sha1 = {SHA.upper()}\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err


@needs_msvc
def test_no_patches_and_an_empty_list_are_refused(driver, tmp_path):
    mod(tmp_path / "a", "m", patches=None)
    out, err = play(driver, tmp_path / "a")
    assert "loaded 0" in out and "no patches.txt" in err, err
    mod(tmp_path / "b", "m", patches="# nothing yet\n\n")
    out, err = play(driver, tmp_path / "b")
    assert "loaded 0" in out and "no patches in it" in err, err


@needs_msvc
def test_one_bad_mod_does_not_take_a_good_one_with_it(driver, tmp_path):
    mod(tmp_path, "b-good")
    mod(tmp_path, "a-bad", patches="every_frame 0x80346d29 = 0\n")
    mod(tmp_path, "c-good", patches="once 0x80346d2c = 5\n")
    (tmp_path / "not-a-mod").mkdir()
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 2" in out, err
    # name order, so two runs apply them the same way; the recording names
    # each by folder with a hash of what it holds
    assert "describe [mods=b-good:" in out and ",c-good:" in out, out


@needs_msvc
def test_every_frame_applies_only_while_its_conditions_hold(driver, tmp_path):
    mod(tmp_path, "m")
    script = """
        set 80346d28 1234 set 803475cc 7 frame get 80346d28
        set 803475cc 6 frame get 80346d28
        set 80346d28 99 frame get 80346d28
        set 803475cc 7 set 80346d28 99 frame get 80346d28
        report
    """
    out, err = play(driver, tmp_path, script)
    assert [line for line in out.splitlines() if line.startswith("80346D28")] == [
        "80346D28=00001234",  # battle: not applied
        "80346D28=00000000",  # field: applied
        "80346D28=00000000",  # and again next frame
        "80346D28=00000099",  # battle again: left alone
    ]
    assert "every_frame 80346D28 = 00000000 applied 2 time(s), first at frame 1" in err, err


@needs_msvc
def test_once_applies_the_first_frame_its_conditions_hold(driver, tmp_path):
    mod(tmp_path, "m", patches="once 0x80346d28 = 0x186a0 when state=8\n")
    script = """
        set 80311aec 3 frame get 80346d28
        set 80311aec 8 frame get 80346d28
        set 80346d28 7 frame get 80346d28
    """
    out, _ = play(driver, tmp_path, script)
    got = [line for line in out.splitlines() if line.startswith("80346D28")]
    assert got == ["80346D28=00000000", "80346D28=000186A0", "80346D28=00000007"]


@needs_msvc
def test_on_map_load_fires_on_every_load_of_its_map(driver, tmp_path):
    """Keyed on the committed map (0x80311AC0, letter byte at 0x80311AC8),
    once the field is running after a load: the reload after a battle puts
    the map's words back as the disc has them, so it fires again (the review
    of 2026-09-25: the old rule left the rest of the stay unpatched); a map
    whose condition fails does not fire; coming back does."""
    mod(tmp_path, "m", patches="on_map_load 0x80346d28 = 1 when map=116a\n")

    def at(number, letter, state):
        return f"set 80311ac0 {number:x} setb 80311ac8 {ord(letter):x} set 80311aec {state:x} "

    step = "set 80346d28 0 frame get 80346d28 "
    script = (
        at(116, "a", 3)
        + step  # loading: not yet
        + at(116, "a", 8)
        + step  # running in 116a: fires
        + at(116, "a", 8)
        + step  # still there: no
        + at(116, "a", 3)
        + step  # battle and reload of the same map
        + at(116, "a", 8)
        + step  # running again after the reload: fires
        + at(116, "b", 8)
        + step  # another map: condition fails
        + at(116, "a", 8)
        + step  # back in 116a: fires
    )
    out, _ = play(driver, tmp_path, script)
    got = [line[-1] for line in out.splitlines() if line.startswith("80346D28")]
    assert got == ["0", "1", "0", "0", "1", "0", "1"], out


@needs_msvc
def test_a_patch_that_never_applied_says_so(driver, tmp_path):
    mod(tmp_path, "m", patches="every_frame 0x80346d28 = 0 when scene=99\n")
    out, err = play(driver, tmp_path, "frame frame report")
    assert "never applied: its conditions never held" in err, err


@needs_msvc
def test_a_folder_that_is_not_there_says_so(driver, tmp_path):
    out, err = play(driver, tmp_path / "nope")
    assert "loaded 0" in out and "is not a folder this port can read" in err, err


def test_the_example_mod_parses_under_the_documented_grammar():
    """The example in examples/mods/ is what a mod author copies, so it has to
    be one this parser would load: its DOL SHA-1 is the one config.yml pins."""
    ini = (ROOT / "examples" / "mods" / "encounters-off" / "mod.ini").read_text(encoding="utf-8")
    pinned = next(
        line.split(":", 1)[1].strip()
        for line in (ROOT / "config" / "GEAE8P" / "config.yml").read_text().splitlines()
        if line.startswith("hash:")
    )
    assert f"dol_sha1 = {pinned}" in ini
    patches = (ROOT / "examples" / "mods" / "encounters-off" / "patches.txt").read_text(
        encoding="utf-8"
    )
    assert "every_frame 0x80346d28 = 0 when scene=6" in patches


def test_the_switch_is_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "`SOA_MODS=" in readme


# --------------------------------------------------------------------------
# M3: mod.dll on SoaModApi. Each test DLL is built here from one source with
# a few switches, against runtime/soa_mod.h, the header a mod author uses.
# --------------------------------------------------------------------------

DLL_SOURCE = r"""
#include "soa_mod.h"
#include <stdio.h>
#include <string.h>

#ifndef RC
#define RC 0
#endif
#ifndef INIT
#define INIT soa_mod_init
#endif

static const SoaModApi* A;
static char b[160];

static void fe(void* u) { uint32_t v; (void)u; if (A->read32(0x80346D28, &v)) A->write32(0x80346D28, v + 1); }
static void sp(void* u) { (void)u; snprintf(b, sizeof b, "safe point, scene %u", A->scene()); A->log(b); }
static void ml(void* u, uint32_t map) { (void)u; snprintf(b, sizeof b, "map loaded %08X", map); A->log(b); }
static void sc(void* u, uint32_t f, uint32_t t) { (void)u; snprintf(b, sizeof b, "scene %u -> %u", f, t); A->log(b); }
#ifdef PROJ
/* a wider view: perspective x scaled by 3/4, orthographic (the 2D layer) left alone */
static void wide(void* u, float p[6], int ortho) { (void)u; if (!ortho) p[0] *= 0.75f; }
#endif
#ifdef TEX
/* textures whose hash ends in TEX become a 2x2 of one colour; the rest stay */
static const uint8_t k_img[16] = {TEX, 0, 0, 255, TEX, 0, 0, 255, TEX, 0, 0, 255, TEX, 0, 0, 255};
static int tex(void* u, uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h, const uint8_t* rgba, SoaImage* out)
{
    (void)u; (void)fmt; (void)w; (void)h; (void)rgba;
    if ((hash & 0xFF) != 0x42) return 0;
#ifdef BIG
    out->w = 5000; out->h = 5000; out->rgba = k_img; /* refused before it is read */
#else
    out->w = 2; out->h = 2; out->rgba = k_img;
#endif
    return 1;
}
#endif
#ifdef LATE
/* registers a pad filter from a frame end, after soa_mod_init has returned */
static void late_pad(void* u, uint32_t f, SoaPad* p) { (void)u; (void)f; p->buttons = 0; }
static void late(void* u)
{
    static int once;
    (void)u;
    if (once++) return;
    snprintf(b, sizeof b, "late registration %d", A->pad_filter(late_pad, NULL));
    A->log(b);
}
#endif
#ifdef CALL
static void callsp(void* u)
{
    uint32_t two[2] = {40, 2}, r = 0;
    int ok;
    (void)u;
    ok = A->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL);
    snprintf(b, sizeof b, "call at safe point %d -> %u", ok, r);
    A->log(b);
    ok = A->call_guest(0x80003104u, two, 2, NULL, 0, &r, NULL);
    snprintf(b, sizeof b, "call mid-function %d", ok);
    A->log(b);
}
static void callfe(void* u)
{
    uint32_t two[2] = {1, 1}, r = 0;
    (void)u;
    snprintf(b, sizeof b, "call at frame end %d", A->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL));
    A->log(b);
}
#endif
#ifdef HOST
/* the host buttons at each frame end, when the port's table has them */
static void hostfe(void* u) { (void)u; snprintf(b, sizeof b, "host %X", A->host_buttons()); A->log(b); }
#endif
#ifdef PADF
/* from frame 10, START never reaches the game; everything else does */
static void pf(void* u, uint32_t frame, SoaPad* p) { (void)u; if (frame >= 10) p->buttons &= ~SOA_PAD_START; }
#endif

__declspec(dllexport) int INIT(const SoaModApi* api, uint32_t version)
{
    uint32_t v = 0;
    uint8_t c = 0;
    float x = 0.0f;
    A = api;
    snprintf(b, sizeof b, "init version %u size %u", version, api->size);
    api->log(b);
    /* refused: code, the hardware window, unaligned, past RAM, a bulk write over code, below RAM */
    snprintf(b, sizeof b, "refusals %d%d%d%d%d%d", api->write32(0x80003100u, 1), api->write32(0xCC008000u, 1),
             api->read32(0x80346D2Au, &v), api->read32(0x81800000u, &v),
             api->write_bytes(0x800030F0u, "abcdefghijklmnopqrst", 20), api->read8(0x7FFFFFFFu, &c));
    api->log(b);
    /* big-endian, as the console keeps it; floats as their bits */
    api->write32(0x80346D20u, 0x11223344u);
    api->read8(0x80346D20u, &c);
    api->write_f32(0x80346D24u, 1.5f);
    api->read32(0x80346D24u, &v);
    api->read_f32(0x80346D24u, &x);
    snprintf(b, sizeof b, "bytes %02X float %08X %.2f", c, v, x);
    api->log(b);
    api->write32(0x80310BBCu, 2u); /* flag 1025: bit 1 of the word at 0x80310B3C + 32 * 4 */
    snprintf(b, sizeof b, "flags %d %d", api->story_flag(1025), api->story_flag(1024));
    api->log(b);
    api->on_frame_end(fe, NULL);
    api->on_safe_point(sp, NULL);
    api->on_map_loaded(ml, NULL);
    api->on_scene_change(sc, NULL);
#ifdef PADF
    api->pad_filter(pf, NULL);
#endif
#ifdef CALL
    {
        uint32_t two[2] = {2, 3}, r = 0;
        snprintf(b, sizeof b, "call in init %d", api->call_guest(0x80003100u, two, 2, NULL, 0, &r, NULL));
        api->log(b);
    }
    api->on_safe_point(callsp, NULL);
    api->on_frame_end(callfe, NULL);
#endif
#ifdef LATE
    api->on_frame_end(late, NULL);
#endif
#ifdef HOST
    if (api->size >= SOA_MOD_HAS(host_buttons)) api->on_frame_end(hostfe, NULL);
#endif
#ifdef PROJ
    api->projection_filter(wide, NULL);
#endif
#ifdef TEX
    api->texture_provider(tex, NULL);
#endif
    return RC;
}
"""


def dll(tmp_path: Path, name: str, *defines: str, patches: str | None = None) -> Path:
    """A mod folder holding mod.ini and a mod.dll built from DLL_SOURCE."""
    from soa import toolchain

    d = mod(tmp_path, name, patches=patches)
    (d / "mod_src.c").write_text(DLL_SOURCE, encoding="utf-8")
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/LD",
            "/I",
            str(ROOT / "runtime"),
            *(f"/D{x}" for x in defines),
            str(d / "mod_src.c"),
            "/Fo" + str(d) + os.sep,
            "/Fe" + str(d / "mod.dll"),
        ],
        cwd=d,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return d


@needs_msvc
def test_a_mod_dll_loads_and_the_api_refuses_what_a_patch_would(driver, tmp_path):
    """The same refusals as a patches.txt line, made at the call: code,
    the hardware window, unaligned, outside RAM, a bulk write over code.
    Memory is big-endian as the console keeps it."""
    dll(tmp_path, "native")
    out, err = play(driver, tmp_path, "get 80346D20")
    assert "loaded 1" in out, err
    assert "loaded native (" in err and "and mod.dll" in err, err
    assert "[mod] native: init version 1 size " in err, err
    assert "[mod] native: refusals 000000" in err, err
    assert "[mod] native: bytes 11 float 3FC00000 1.50" in err, err
    assert "[mod] native: flags 1 0" in err, err
    assert "80346D20=11223344" in out, out


@needs_msvc
def test_the_callbacks_fire_where_they_say(driver, tmp_path):
    """on_frame_end from the frame hook; on_safe_point, a scene change, and a
    map load -- the field running after a load state -- from the top of the
    loop. A reload of the same map after a battle is a load too."""
    dll(tmp_path, "native")

    def at(scene, state, number=116, letter="a"):
        return (
            f"set 803475cc {scene:x} set 80311aec {state:x} "
            f"set 80311ac0 {number:x} setb 80311ac8 {ord(letter):x} safe "
        )

    script = (
        "set 80346d28 5 frame frame get 80346d28 "
        + at(6, 3)  # loading
        + at(6, 8)  # running: a map load
        + at(6, 8)  # still running: nothing
        + at(7, 9)  # battle: a scene change
        + at(6, 5)  # the field reloading
        + at(6, 8)  # running again: the same map, loaded again
        + "report"
    )
    out, err = play(driver, tmp_path, script)
    assert "80346D28=00000007" in out, out  # two frame ends, each adding one
    loads = [line for line in err.splitlines() if "map loaded" in line]
    assert loads == ["[mod] native: map loaded 00007461"] * 2, err
    assert "[mod] native: scene 6 -> 7" in err and "[mod] native: scene 7 -> 6" in err, err
    assert err.count("[mod] native: safe point") == 6, err
    assert "[mod] the safe point saw 2 map load(s)" in err, err
    assert "[mod] native mod.dll: 4 callback(s)" in err, err


@needs_msvc
def test_a_dll_that_refuses_itself_takes_its_callbacks_and_patches_with_it(driver, tmp_path):
    dll(tmp_path, "shy", "RC=3", patches=PATCH)
    out, err = play(driver, tmp_path, "set 803475cc 6 set 80346d28 1234 frame safe get 80346d28")
    assert "loaded 0" in out, err
    assert "its soa_mod_init refused, returning 3" in err, err
    assert "80346D28=00001234" in out and "safe point" not in err, err


@needs_msvc
def test_a_dll_without_the_export_is_refused(driver, tmp_path):
    dll(tmp_path, "mute", "INIT=something_else")
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "it exports no soa_mod_init" in err, err


@needs_msvc
def test_a_dll_mod_is_named_in_the_recording_with_its_bytes(driver, tmp_path):
    """The hash covers mod.dll, so a rebuilt DLL is a different mod to a
    recording made with the old one."""
    d = dll(tmp_path, "native")
    first, _ = play(driver, tmp_path, "describe")
    (d / "mod.dll").write_bytes((d / "mod.dll").read_bytes() + b"\0")
    second, _ = play(driver, tmp_path, "describe")
    h1 = first.split("describe [mods=native:")[1][:8]
    h2 = second.split("describe [mods=native:")[1][:8]
    assert h1 != h2, (first, second)


@needs_msvc
def test_the_example_dll_builds_and_loads(driver, tmp_path):
    """examples/mods/map-log is the template a mod author copies: it has to
    build against runtime/soa_mod.h and load under this port."""
    from soa import toolchain

    d = tmp_path / "map-log"
    d.mkdir()
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/LD",
            "/I",
            str(ROOT / "runtime"),
            str(ROOT / "examples" / "mods" / "map-log" / "mod.c"),
            "/Fo" + str(d) + os.sep,
            "/Fe" + str(d / "mod.dll"),
        ],
        cwd=d,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    script = (
        "set 803475cc 6 set 80311aec 3 safe set 80311aec 8 set 80311ac0 74 setb 80311ac8 61 safe"
    )
    out, err = play(driver, tmp_path, script)
    assert "loaded 1" in out, err
    assert "[mod] map-log: map-log loaded" in err and "[mod] map-log: entered a116a" in err, err


@needs_msvc
def test_a_pad_filter_changes_what_the_game_reads(driver, tmp_path):
    """The filter sees each read with its frame and may change it: this one
    drops START from frame 10 and leaves A alone. si.c calls it after the
    recording's copy, so a recording holds the input as the person gave it."""
    dll(tmp_path, "nostart", "PADF")
    out, err = play(driver, tmp_path, "pad 5 1100 pad 20 1100 pad 21 0100 report")
    pads = [line for line in out.splitlines() if line.startswith("pad ")]
    assert pads == ["pad 5 1100 filtered", "pad 20 0100 filtered", "pad 21 0100 filtered"], out
    assert "3 controller read(s)" in err, err


@needs_msvc
def test_without_a_filter_si_c_is_never_handed_one(driver, tmp_path):
    """A mod that registers none leaves the read path exactly as it was."""
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "pad 20 1100")
    assert "pad 20 1100 unfiltered" in out, out


@needs_msvc
def test_a_projection_filter_sees_each_projection_and_may_change_it(driver, tmp_path):
    """gxr.c hands over GXSetProjection's six parameters once per new
    projection; this filter widens the 3D view and leaves the 2D layer,
    which is orthographic, as it was."""
    dll(tmp_path, "wide", "PROJ")
    out, err = play(
        driver, tmp_path, "proj 0 1.5 0 2 0 -1 -0.1 proj 1 0.003 -1 -0.004 1 -1 0 report"
    )
    projs = [line for line in out.splitlines() if line.startswith("proj ")]
    assert projs == [
        "proj 1.1250 0.0000 2.0000 0.0000 -1.0000 -0.1000 filtered",
        "proj 0.0030 -1.0000 -0.0040 1.0000 -1.0000 0.0000 filtered",
    ], out
    assert "2 projection(s)" in err, err


@needs_msvc
def test_without_a_projection_filter_gxr_c_is_never_handed_one(driver, tmp_path):
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "proj 0 1.5 0 2 0 -1 -0.1")
    assert "proj 1.5000 0.0000 2.0000 0.0000 -1.0000 -0.1000 unfiltered" in out, out


@needs_msvc
def test_a_texture_provider_replaces_by_source_hash(driver, tmp_path):
    """Asked once per decode with the source hash -- the cache's key, stable
    from run to run -- it replaces the textures it knows and leaves the rest;
    the image may be any size."""
    dll(tmp_path, "pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 1234567890ABCD42 8 8 tex 1234567890ABCD43 8 8 report")
    texs = [line for line in out.splitlines() if line.startswith("tex ")]
    assert texs == ["tex replaced 2x2 first C80000FF", "tex kept (asked)"], out
    assert "2 texture(s)" in err, err


@needs_msvc
def test_among_providers_the_first_that_answers_wins(driver, tmp_path):
    """Mods load in folder order, and the first provider to answer 1 is the
    one whose image is used; a later one is not asked."""
    dll(tmp_path, "a-pack", "TEX=100")
    dll(tmp_path, "b-pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 42 4 4 report")
    assert "tex replaced 2x2 first 640000FF" in out, out
    assert (
        "[mod] b-pack mod.dll:" in err and "0 texture(s)" in err.split("[mod] b-pack mod.dll:")[1]
    ), err


@needs_msvc
def test_without_a_provider_the_renderer_is_never_handed_one(driver, tmp_path):
    dll(tmp_path, "native")
    out, _ = play(driver, tmp_path, "tex 42 4 4")
    assert "tex kept (no provider)" in out, out


# --------------------------------------------------------------------------
# The review of 2026-09-25
# --------------------------------------------------------------------------


@needs_msvc
def test_a_callback_registered_after_init_is_refused(driver, tmp_path):
    """The dispatchers are wired when loading ends, so a later registration
    would be accepted and never called; now it returns 0, and the filter it
    offered never touches a read."""
    dll(tmp_path, "latecomer", "LATE")
    out, err = play(driver, tmp_path, "frame pad 5 1100")
    assert "[mod] latecomer: late registration 0" in err, err
    assert "pad 5 1100 unfiltered" in out, out


@needs_msvc
def test_a_line_too_long_to_read_whole_is_refused(driver, tmp_path):
    """Cut at 511 characters, `state=18` would read as `state=1`."""
    long_line = "every_frame 0x80346d28 = 0 when scene=6" + " " * 480 + "state=18\n"
    mod(tmp_path, "m", patches=long_line)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "patches.txt:1: a line longer than 511 characters" in err, err


@needs_msvc
def test_a_folder_the_table_cannot_hold_is_named(driver, tmp_path):
    name = "a" * 70
    mod(tmp_path, name)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out, err
    assert f"{name}: a mod's folder name has to be under 64 characters; not read" in err, err


@needs_msvc
def test_mods_past_the_recording_line_are_counted_not_cut(driver, tmp_path):
    """The config line keeps whole entries and names the rest as a count and
    one hash, never a folder name with half a hash."""
    names = [f"mod-{i:02d}-with-a-long-folder-name" for i in range(12)]
    for n in names:
        mod(tmp_path, n)
    out, _ = play(driver, tmp_path, "describe")
    line = next(x for x in out.splitlines() if x.startswith("describe ["))[len("describe [") : -1]
    entries = line[len("mods=") :].split(",")
    *whole, rest = entries
    assert all(e.split(":")[0] in names and len(e.split(":")[1]) == 8 for e in whole), line
    count, digest = rest.split(":")
    assert count == f"+{12 - len(whole)} more" and len(digest) == 8, line


@needs_msvc
def test_an_image_too_large_is_refused_and_the_next_provider_asked(driver, tmp_path):
    dll(tmp_path, "a-huge", "TEX=100", "BIG")
    dll(tmp_path, "b-pack", "TEX=200")
    out, err = play(driver, tmp_path, "tex 42 4 4")
    assert "a 5000x5000 image is refused, 4096 on a side is the most" in err, err
    assert "tex replaced 2x2 first C80000FF" in out, out


# --------------------------------------------------------------------------
# M4: calling the game from a mod
# --------------------------------------------------------------------------


@needs_msvc
def test_call_guest_runs_at_a_safe_point_and_puts_every_register_back(driver, tmp_path):
    """From a safe-point callback the game's function runs with the
    arguments in r3 and r4 and its answer comes back; what it clobbered --
    r14, f14, a GQR -- is put back, and the GQR is reported."""
    dll(tmp_path, "caller", "CALL")
    out, err = play(driver, tmp_path, "game safe regs")
    assert "[mod] caller: call at safe point 1 -> 42" in err, err
    assert "left a GQR changed; it is put back" in err, err
    assert "r14 14141414 gqr3 00000000 f14 0.0" in out, out


@needs_msvc
def test_call_guest_is_refused_everywhere_else(driver, tmp_path):
    """In soa_mod_init, at a frame end (inside the XFB copy), and at an
    address that is not the start of a function -- which dispatched would
    trap and end the run."""
    dll(tmp_path, "caller", "CALL")
    out, err = play(driver, tmp_path, "game frame safe")
    assert "[mod] caller: call in init 0" in err, err
    assert "[mod] caller: call at frame end 0" in err, err
    assert "only a safe-point, scene or map callback may call the game" in err, err
    assert "[mod] caller: call mid-function 0" in err, err
    assert "80003104 is not the start of a function in this program" in err, err
    assert "dispatch of" not in out, out


@needs_msvc
def test_call_guest_refuses_when_r2_and_r13_are_not_the_games(driver, tmp_path):
    dll(tmp_path, "caller", "CALL")
    _, err = play(driver, tmp_path, "safe")
    assert "call at safe point 0" in err and "are not the game's 80350000 and 8034E720" in err, err


@needs_msvc
def test_call_guest_is_refused_inside_an_interrupt_handler(driver, tmp_path):
    """A safe point reached while a handler runs is not a point where the
    game's code may be called: the handler owns the registers."""
    dll(tmp_path, "caller", "CALL")
    _, err = play(driver, tmp_path, "game irq safe")
    assert "call at safe point 0" in err and "refused: inside an interrupt handler" in err, err


# --------------------------------------------------------------------------
# Manifest 2 (PLAN-GAMEPLAY-MODS.md section F): an id and a version the
# recording names a mod by, api as the least the mod needs, x_ keys kept for
# later ports, and one id to one mod.
# --------------------------------------------------------------------------

V2 = f"manifest = 2\nid = enc\nversion = 1.2\nname = Enc\nauthors = someone\napi = 1\ndol_sha1 = {SHA}\n"


@needs_msvc
def test_a_manifest_2_mod_loads_and_the_recording_names_it_by_id(driver, tmp_path):
    mod(tmp_path, "some-folder", ini=V2)
    mod(tmp_path, "v1-folder")
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 2" in out, err
    assert "some-folder, enc@1.2)" in err, err
    line = next(x for x in out.splitlines() if x.startswith("describe ["))
    # name order of the folders; a manifest 2 mod by id@version, a version 1
    # mod by its folder as before, so a recording made before is still read
    assert line.startswith("describe [mods=enc@1.2:") and ",v1-folder:" in line, line


@needs_msvc
@pytest.mark.parametrize(
    "ini, why",
    [
        (V2.replace("id = enc\n", ""), "manifest 2 and no `id = `"),
        (V2.replace("version = 1.2\n", ""), "manifest 2 and no `version = `"),
        (V2.replace("id = enc", "id = Enc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = -enc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = e,nc"), "an id is lowercase letters"),
        (V2.replace("id = enc", "id = " + "e" * 64), "an id is lowercase letters"),
        (V2.replace("version = 1.2", "version = 1,2"), "a version is letters"),
        (V2.replace("version = 1.2", "version = .1"), "a version is letters"),
        (V2.replace("manifest = 2", "manifest = 3"), "this port reads manifests 1 and 2"),
        (
            V2.replace("manifest = 2\n", ""),
            "`id` is a manifest 2 key, and this mod.ini has no `manifest = 2`",
        ),
        (
            V2.replace("manifest = 2", "manifest = 1"),
            "`id` is a manifest 2 key, and this mod.ini has manifest = 1",
        ),
        (V2.replace("api = 1", "api = 0"), "is not a version number"),
        (V2.replace("api = 1", "api = one"), "is not a version number"),
        (V2.replace("api = 1", "api = 2"), "this port speaks api 1"),
        (V2 + "homepage = x\n", "is not a mod.ini key"),
    ],
    ids=[
        "no-id",
        "no-version",
        "upper-id",
        "dash-first",
        "comma-id",
        "long-id",
        "comma-version",
        "dot-first",
        "manifest-3",
        "v2-key-no-manifest",
        "v2-key-manifest-1",
        "api-0",
        "api-word",
        "api-newer",
        "unknown-key",
    ],
)
def test_a_bad_manifest_2_is_refused(driver, tmp_path, ini, why):
    mod(tmp_path, "m", ini=ini)
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and why in err and "the mod is not loaded" in err, err


@needs_msvc
def test_an_x_key_is_noted_and_the_mod_loads(driver, tmp_path):
    """A key a later port may define: this one says it does not know it and
    loads the mod; a misspelled key without the prefix still refuses it."""
    mod(tmp_path, "m", ini=V2 + "x_homepage = https://example.invalid\n")
    out, err = play(driver, tmp_path)
    assert "loaded 1" in out, err
    assert "mod.ini:8: `x_homepage` is not a key this port knows" in err, err


@needs_msvc
def test_two_mods_with_one_id_the_second_is_refused_and_names_the_first(driver, tmp_path):
    mod(tmp_path, "a-first", ini=V2)
    mod(tmp_path, "b-second", ini=V2.replace("version = 1.2", "version = 2.0"))
    out, err = play(driver, tmp_path, "describe")
    assert "loaded 1" in out, err
    assert "b-second/mod.ini: its id, enc, is already the mod's in folder a-first" in err, err
    assert "describe [mods=enc@1.2:" in out, out


def test_the_shipped_mods_are_manifest_2():
    """The folders a mod author copies from carry the manifest a new mod
    should: an id and a version, api as a minimum."""
    for folder in (
        "mods/autotext",
        "mods/encounter-rate",
        "examples/mods/encounters-off",
        "examples/mods/map-log",
    ):
        keys = {}
        for line in (ROOT / folder / "mod.ini").read_text(encoding="utf-8").splitlines():
            key, eq, value = line.partition("=")
            if eq and not line.lstrip().startswith("#"):
                keys[key.strip()] = value.strip()
        assert keys.get("manifest") == "2" and keys.get("id") == Path(folder).name, (folder, keys)
        assert keys.get("version") and keys.get("api") == "1", (folder, keys)


@pytest.fixture(scope="module")
def driver_api2(tmp_path_factory):
    """The same loader built to speak mod API 2, which no port does yet: the
    only way to show that a manifest's `api` is a minimum, since at API 1 a
    minimum and an exact match accept the same files."""
    return build_driver(tmp_path_factory, "MOD_API=2")


@needs_msvc
@pytest.mark.parametrize("need, loads", [("1", True), ("2", True), ("3", False)])
def test_api_is_the_least_the_mod_needs(driver_api2, tmp_path, need, loads):
    mod(tmp_path, "m", ini=V2.replace("api = 1", f"api = {need}"))
    out, err = play(driver_api2, tmp_path)
    assert ("loaded 1" in out) == loads, err
    if not loads:
        assert "api = 3, and this port speaks api 2" in err, err


@needs_msvc
def test_a_manifest_2_without_api_is_told_what_is_missing(driver, tmp_path):
    mod(tmp_path, "m", ini=V2.replace("api = 1\n", ""))
    out, err = play(driver, tmp_path)
    assert "loaded 0" in out and "no `api = `" in err and "no `api = 1`" not in err, err


@needs_msvc
def test_a_manifest_2_mod_past_the_recording_line_is_keyed_by_id_not_folder(driver, tmp_path):
    """The `+N more` hash takes each mod by the name the line would have
    given it: renaming the folder of a manifest 2 mod that did not fit --
    same id, version and bytes, same place in the load order -- leaves the
    line as it was, as renaming one that fits does. Keyed by folder (the
    mutation), a recording replayed after the rename would claim another
    configuration."""
    ids = [f"a-manifest-two-mod-with-a-rather-long-id-{i:02d}" for i in range(12)]
    for i, mid in enumerate(ids):
        mod(tmp_path, f"m{i:02d}", ini=V2.replace("id = enc", f"id = {mid}"))
    out, _ = play(driver, tmp_path, "describe")
    before = next(x for x in out.splitlines() if x.startswith("describe ["))
    assert "more:" in before and ids[-1] not in before, before
    (tmp_path / "m11").rename(tmp_path / "m11-renamed")
    out, _ = play(driver, tmp_path, "describe")
    after = next(x for x in out.splitlines() if x.startswith("describe ["))
    assert after == before, (before, after)


# --------------------------------------------------------------------------
# mods/encounter-rate (PLAN-GAMEPLAY-MODS P1a) on the fake guest
# --------------------------------------------------------------------------

ENC = ROOT / "mods" / "encounter-rate"
FIELD = "set 803475cc 6 "
BYTE = "get 8030b7ac "  # the multiplier is the second byte of this word
# Character 0's accessory is the high half of 0x8030B808; accessory 210's
# record's first effect is {84, 0, 100}, 211's {84, 0, 5}.
ACC_210 = "set 8030b808 00d20000 set 802c75f8 54000064 "
ACC_211_ON_1 = "set 8030b864 00d30000 set 802c7620 54000005 "


def shipped(tmp_path: Path, source: str | None = None, folder: Path = ENC) -> Path:
    """A shipped mod (mods/encounter-rate unless `folder` says) built with the
    line --link uses, into a folder whose mod.ini pins the fake DOL -- or,
    given `source`, a mutation of it."""
    import recompile
    from soa import toolchain

    d = tmp_path / folder.name
    d.mkdir(parents=True)
    ini = (folder / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    src = d / "mod.c"
    src.write_text(source or (folder / "mod.c").read_text(encoding="utf-8"), encoding="utf-8")
    proc = toolchain.cl(recompile.mod_dll_command(src), cwd=d)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    return d


def multipliers(out: str) -> list[int]:
    """The multiplier byte at each `get` of its word, in order."""
    return [
        int(line.split("=")[1], 16) >> 16 & 0xFF
        for line in out.splitlines()
        if line.startswith("8030B7AC=")
    ]


def writes(err: str) -> int:
    line = next(ln for ln in err.splitlines() if "encounter-rate mod.dll:" in ln)
    return int(line.rsplit(";", 1)[1].split()[0])


def test_every_shipped_mod_is_built_by_link():
    """--link builds each mod.c under mods/ and examples/mods/ (recompile.py's
    list): the shipped mod is among them, beside the example."""
    import recompile

    srcs = {p.parent.relative_to(ROOT).as_posix() for p in recompile.mod_dll_sources()}
    assert {"mods/autotext", "mods/encounter-rate", "examples/mods/map-log"} <= srcs, srcs


@needs_msvc
def test_encounter_rate_unset_writes_nothing(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, FIELD + "frame " * 100 + BYTE + "report")
    assert "loaded 1" in out, err
    assert "[mod] encounter-rate: random battles normal in the field" in err, err
    assert "[mod] encounter-rate: base 50 (none)" in err, err
    assert writes(err) == 0 and multipliers(out) == [0], (out, err)


@needs_msvc
def test_encounter_rate_presets_without_an_accessory(driver, tmp_path):
    shipped(tmp_path)
    for preset, want in (("half", 25), ("double", 100), ("off", 0)):
        out, err = play(
            driver,
            tmp_path,
            FIELD + "setb 8030b7ad ff frame " + BYTE + "report",
            SOA_ENCOUNTERS=preset,
        )
        assert multipliers(out) == [want], (preset, out, err)
        assert writes(err) == 1, (preset, err)


@needs_msvc
def test_encounter_rate_works_from_the_accessory_as_the_game_does(driver, tmp_path):
    """Base is the effect-84 value of the last character whose accessory has
    one: 210 on character 0 gives 100, and 211 on character 1 after it 5."""
    shipped(tmp_path)
    out, err = play(
        driver, tmp_path, FIELD + ACC_210 + "frame frame " + BYTE, SOA_ENCOUNTERS="half"
    )
    assert multipliers(out) == [50], out
    assert "base 100 (character 0's accessory 210)" in err, err
    out, _ = play(driver, tmp_path, FIELD + ACC_210 + "frame " + BYTE, SOA_ENCOUNTERS="double")
    assert multipliers(out) == [127], out
    out, err = play(
        driver, tmp_path, FIELD + ACC_210 + ACC_211_ON_1 + "frame " + BYTE, SOA_ENCOUNTERS="half"
    )
    assert multipliers(out) == [2] and "base 5 (character 1's accessory 211)" in err, (out, err)


@needs_msvc
def test_encounter_rate_writes_only_in_the_field(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(
        driver, tmp_path, "set 803475cc 7 frame frame " + BYTE + "report", SOA_ENCOUNTERS="off"
    )
    assert multipliers(out) == [0] and writes(err) == 0, (out, err)


HOLD = (
    FIELD
    + "setb 8030b7ad ff pad 1 0200 "
    + ("frame " + BYTE) * 30
    + "pad 31 0000 "
    + ("frame " + BYTE) * 5
)


@needs_msvc
def test_hold_b_at_normal_writes_zero_then_puts_the_game_s_value_back_once(driver, tmp_path):
    """Thirty frames with B held read 0; the first frame after B is let go
    writes the game's own 0xFF, and after that nothing more is written."""
    shipped(tmp_path)
    out, err = play(driver, tmp_path, HOLD + "report")
    assert multipliers(out) == [0] * 30 + [0xFF] * 5, out
    assert writes(err) == 31, err


@needs_msvc
def test_hold_b_restores_the_accessory_s_value_not_ff(driver, tmp_path):
    shipped(tmp_path)
    out, _ = play(driver, tmp_path, ACC_210 + HOLD.replace("setb 8030b7ad ff", "setb 8030b7ad 64"))
    assert multipliers(out)[30:] == [0x64] * 5, out


@needs_msvc
def test_hold_b_off_leaves_the_controller_alone(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, HOLD + "report", SOA_ENCOUNTERS_HOLD_B="0")
    assert "pad 1 0200 unfiltered" in out and multipliers(out) == [0xFF] * 35, out
    assert "holding B keeps them away off" in err and writes(err) == 0, err


@needs_msvc
def test_a_preset_the_mod_does_not_know_is_the_game_s_rate(driver, tmp_path):
    shipped(tmp_path)
    out, err = play(driver, tmp_path, FIELD + "frame " + BYTE + "report", SOA_ENCOUNTERS="HALF")
    assert "SOA_ENCOUNTERS=HALF is not off, half, normal or double" in err, err
    assert writes(err) == 0 and multipliers(out) == [0], (out, err)


@needs_msvc
def test_the_mutations_fail_the_checks(driver, tmp_path):
    """The spec's two mutations: halving the byte read back instead of base
    compounds frame on frame (50, 25, 12, ...), and a build without the
    restore leaves battles off after one press of B."""
    src = (ENC / "mod.c").read_text(encoding="utf-8")
    compound = "    base = base_now(&game, &who, &item);\n"
    assert src.count(compound) == 1
    reread = compound + (
        "    { uint8_t now; if (g_api->read8(MULTIPLIER, &now) && now != 0xFF) base = (int8_t)now; }\n"
    )
    shipped(tmp_path / "a", src.replace(compound, reread))
    out, _ = play(
        driver,
        tmp_path / "a",
        FIELD + ACC_210 + "setb 8030b7ad 64 " + ("frame " + BYTE) * 3,
        SOA_ENCOUNTERS="half",
    )
    assert multipliers(out) == [50, 25, 12], out  # the shipped mod reads 50, 50, 50

    restore = "        if (g_dirty && g_api->write8(MULTIPLIER, (uint8_t)game)) g_dirty = 0;\n"
    assert src.count(restore) == 1
    shipped(tmp_path / "b", src.replace(restore, ""))
    out, _ = play(driver, tmp_path / "b", HOLD)
    assert multipliers(out)[30:] == [0] * 5, out  # the shipped mod reads FF


# --------------------------------------------------------------------------
# mods/autotext (PLAN-GAMEPLAY-MODS P11) on the fake guest
# --------------------------------------------------------------------------

AUTO = ROOT / "mods" / "autotext"


def window(state: int, flags: int = 0, task: int = 0x80400000) -> str:
    """The message window as the game keeps it: the task at 0x80346E4C, its
    context at task + 36, the flags the context's first halfword, and the
    state the s16 at 0x80346E64 (the high half of its word)."""
    ctx = 0x80400100
    return (
        f"set 803475cc 6 set 80346e4c {task:x} set 80400024 {ctx:x} "
        f"set {ctx:x} {flags << 16:x} set 80346e64 {(state & 0xFFFF) << 16:x} "
    )


def reads(first: int, last: int, buttons: int = 0) -> str:
    return "".join(f"pad {f} {buttons:x} " for f in range(first, last + 1))


def pressed(out: str) -> list[int]:
    """The frames whose controller read the game got with A down."""
    got = []
    for line in out.splitlines():
        parts = line.split()
        if parts[:1] == ["pad"] and int(parts[2], 16) & 0x0100:
            got.append(int(parts[1]))
    return got


@needs_msvc
def test_autotext_presses_a_once_per_complete_page_after_the_delay(driver, tmp_path):
    """State 4 and no flags: the wait starts at the first read, and 45
    frames on (SOA_AUTOTEXT=on) A goes down for two frames and up for two;
    not again while the page is still up; again on the next page."""
    shipped(tmp_path, folder=AUTO)
    script = window(4) + reads(1, 60) + window(3) + reads(61, 62) + window(4) + reads(63, 120)
    out, err = play(driver, tmp_path, script, SOA_AUTOTEXT="on")
    assert pressed(out) == [46, 47, 108, 109], pressed(out)
    assert "[mod] autotext: frame 46 page advanced after 45 frames" in err, err
    assert "[mod] autotext: frame 108 page advanced after 45 frames" in err, err


@needs_msvc
@pytest.mark.parametrize(
    "state, flags, task",
    [
        (4, 0x10, 0x80400000),
        (4, 0x40, 0x80400000),
        (6, 0x10, 0x80400000),  # a choice box carries 0x10, as the game's does
        (8, 0, 0x80400000),
        (4, 0, 0),
    ],
    ids=["after-a-choice", "auto-scroll", "choice", "state-8", "no-window"],
)
def test_autotext_never_presses_where_the_game_decides(driver, tmp_path, state, flags, task):
    shipped(tmp_path, folder=AUTO)
    out, _ = play(driver, tmp_path, window(state, flags, task) + reads(1, 120), SOA_AUTOTEXT="10")
    assert pressed(out) == [], pressed(out)


@needs_msvc
def test_autotext_leaves_a_page_the_person_pressed_on(driver, tmp_path):
    shipped(tmp_path, folder=AUTO)
    script = window(4) + reads(1, 5) + reads(6, 6, 0x0100) + reads(7, 60)
    out, _ = play(driver, tmp_path, script, SOA_AUTOTEXT="10")
    assert pressed(out) == [6], pressed(out)  # theirs, and no press of the mod's


@needs_msvc
@pytest.mark.parametrize("value", ["0", "", "soon"])
def test_autotext_off_never_presses(driver, tmp_path, value):
    shipped(tmp_path, folder=AUTO)
    out, err = play(driver, tmp_path, window(4) + reads(1, 120), SOA_AUTOTEXT=value)
    assert pressed(out) == [] and "unfiltered" in out, out
    if value == "soon":
        assert "SOA_AUTOTEXT=soon is not 0, 1, on or a number of frames" in err, err


@needs_msvc
def test_autotext_mutations_fail_the_checks(driver, tmp_path):
    """Without the flags guard it presses on a page the game turns itself;
    the test switch presses in a choice box."""
    src = (AUTO / "mod.c").read_text(encoding="utf-8")
    guard = " && !(state == STATE_PAGE && (flags & (FLAG_AFTER_CHOICE | FLAG_AUTO_SCROLL)))"
    assert src.count(guard) == 1
    shipped(tmp_path / "a", src.replace(guard, ""), folder=AUTO)
    out, _ = play(driver, tmp_path / "a", window(4, 0x10) + reads(1, 30), SOA_AUTOTEXT="10")
    assert pressed(out) == [11, 12], pressed(out)
    shipped(tmp_path / "b", folder=AUTO)
    out, _ = play(
        driver,
        tmp_path / "b",
        window(6, 0x10) + reads(1, 30),
        SOA_AUTOTEXT="10",
        SOA_AUTOTEXT_TEST="press-in-choice",
    )
    assert pressed(out) == [11, 12], pressed(out)


@needs_msvc
def test_host_buttons_reach_a_mod_as_si_gives_them(driver, tmp_path):
    """host_buttons (CH1) is si.c's g_host, through the setter main.c calls:
    here a stub the driver's `host` command sets."""
    dll(tmp_path, "hostmod", "HOST")
    _, err = play(driver, tmp_path, "host 0 frame host 9 frame host 1 frame")
    assert [ln for ln in err.splitlines() if "hostmod: host" in ln] == [
        "[mod] hostmod: host 0",
        "[mod] hostmod: host 9",
        "[mod] hostmod: host 1",
    ], err


@needs_msvc
def test_a_mod_built_against_the_header_before_host_buttons_still_loads(driver, tmp_path):
    """The table grows only at the end: map-log built against soa_mod.h as it
    was before CH1 appended host_buttons loads and runs on this port."""
    from soa import toolchain

    header = (ROOT / "runtime" / "soa_mod.h").read_text(encoding="utf-8")
    start = header.index("    /* Appended (CH1).")
    end = header.index("uint32_t (*host_buttons)(void);", start) + len(
        "uint32_t (*host_buttons)(void);\n"
    )
    old = header[:start] + header[end:]
    assert "(*host_buttons)" not in old and "(*call_guest)" in old
    inc = tmp_path / "old-include"
    inc.mkdir()
    (inc / "soa_mod.h").write_text(old, encoding="utf-8")
    d = tmp_path / "mods" / "map-log"
    d.mkdir(parents=True)
    ini = (ROOT / "examples" / "mods" / "map-log" / "mod.ini").read_text(encoding="utf-8")
    (d / "mod.ini").write_text(
        ini.replace(ini.split("dol_sha1 = ")[1].split()[0], SHA), encoding="utf-8"
    )
    proc = toolchain.cl(
        [
            *toolchain.CFLAGS,
            "/LD",
            "/I",
            str(inc),
            str(ROOT / "examples" / "mods" / "map-log" / "mod.c"),
            "/Fo" + str(d) + os.sep,
            "/Fe" + str(d / "mod.dll"),
        ],
        cwd=d,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    out, err = play(driver, tmp_path / "mods", "set 803475cc 6 set 80311aec 3 safe")
    assert "loaded 1" in out and "[mod] map-log: map-log loaded" in err, (out, err)
