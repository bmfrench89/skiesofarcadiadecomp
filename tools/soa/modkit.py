"""The fake guest a mod runs on without the game (T10, docs/specs/mod-kit.md).

The port's own runtime/mod.c, linked with a driver that plays the game's
side: a fake DOL with one code section, and a script of memory writes, frame
ends, safe points and controller reads on stdin. tools/mod.py's `check` and
`test` run a mod on it, and tools/tests/test_mods.py builds the same one, so
the tool and the tests cannot drift apart. What it can show is that a mod
loads, its patches' grammar, its callbacks and the API's refusals -- not
what the mod does in the game: it has no game, and `call_guest` reaches only
the stand-in function at 0x80003100.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

from soa import toolchain

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"

TEXT_START, TEXT_LEN = 0x80003100, 0x1000

DRIVER = r"""
#define _CRT_SECURE_NO_WARNINGS
#include "mod.h"
#include "soa_mod.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* runtime/savext.c's (X2), which the game's hooks call */
void savext_snapshot(CpuState* s, uint32_t block);
void savext_image(CpuState* s, uint32_t image);
void savext_load(CpuState* s, uint32_t block);
void savext_new_game(void);

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
/* si.c's pad 2 (P10a), as the stub the "pad2" command sets: connected,
 * buttons; "analog2" sets its sticks and triggers. */
static int g_pad2_there;
static unsigned g_pad2_buttons;
static uint8_t g_pad2_analog[6] = {128, 128, 128, 128, 0, 0};
static int pad_stub(unsigned port, void* out)
{
    uint8_t* p = (uint8_t*)out;
    if (port != 2 || !g_pad2_there) return 0;
    p[0] = (uint8_t)g_pad2_buttons; p[1] = (uint8_t)(g_pad2_buttons >> 8);
    memcpy(p + 2, g_pad2_analog, 6);
    return 1;
}

/* The game's side of call_guest: one function at 0x80003100 that adds r3
 * and r4 and, being careless, clobbers r14, f14 and GQR 3. After the
 * "walkfns" command, also the three the lab's walker calls: every entry is
 * live (fn_8021067C), one starts and says so (fn_80210550), and an object is
 * found (fn_8015F1A0) when a "here ID" command named it. */
static int g_irq, g_walk_fns;
static uint32_t g_here[16];
static unsigned g_nhere;
int irq_in_handler(void) { return g_irq; }
int dispatch_known(uint32_t a)
{
    return a == 0x80003100u ||
           (g_walk_fns && (a == 0x8021067Cu || a == 0x80210550u || a == 0x80210450u || a == 0x8015F1A0u));
}
void dispatch(CpuState* s, uint32_t a)
{
    unsigned i;
    if (a == 0x8021067Cu) { s->gpr[3] = 1; return; }
    if (a == 0x80210550u) { printf("fn_80210550(%u)\n", s->gpr[3]); s->gpr[3] = 1; return; }
    if (a == 0x80210450u) { printf("fn_80210450(%08X)\n", s->gpr[3]); s->gpr[3] = 1; return; }
    if (a == 0x8015F1A0u) {
        uint32_t id = s->gpr[3];
        s->gpr[3] = 0;
        for (i = 0; i < g_nhere; i++)
            if (g_here[i] == id) s->gpr[3] = 0x81000000u + id;
        return;
    }
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
 *   padall F B         the same with the sticks and triggers off centre, all eight bytes printed
 *   pad2 B             pad 2 connected, buttons B    analog2 SX SY CX CY LT RT   its sticks, triggers
 *   proj O P0..P5      a new projection (O 1 orthographic), through the filter
 *   tex HASH W H       a W x H texture decoded, its source hash HASH, through the provider
 *   game               the game's registers at a safe point: r2, r13 its, r14 a mark
 *   walkfns            answer the walker's three game functions   here ID   an object id they find */
int main(int argc, char** argv)
{
    static CpuState s;
    static uint8_t* dol;
    char cmd[64];
    unsigned frame = 0, a, v;
    FILE* f = fopen(argv[2], "rb");
    size_t n = 0;
    long size;
    (void)argc;
    /* the whole DOL, the game's 3 MB as well as the fake one: its SHA-1 is checked */
    if (!f) { printf("cannot read %s\n", argv[2]); return 2; }
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    dol = (uint8_t*)malloc(size > 0 ? (size_t)size : 1);
    if (dol && size > 0) n = fread(dol, 1, (size_t)size, f);
    fclose(f);
    s.mem = (uint8_t*)calloc(1, MEM_IMAGE_SIZE);
    mod_set_host_buttons(host_stub);
    mod_set_pad_reader(pad_stub);
    {
        /* T1's pass first, as main.c makes it (I6): the files.txt lines, which
         * no disc here places, then the mods */
        DiscFileOp* ops;
        int nops = mod_scan_files(argv[1], dol, n, &ops);
        if (nops) printf("files %d\n", nops);
    }
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
        else if (!strcmp(cmd, "walkfns")) g_walk_fns = 1;
        else if (!strcmp(cmd, "here") && scanf("%u", &a) == 1 && g_nhere < 16) g_here[g_nhere++] = a;
        else if (!strcmp(cmd, "host") && scanf("%x", &v) == 1) g_host_now = v;
        else if (!strcmp(cmd, "pad2") && scanf("%x", &v) == 1) { g_pad2_there = 1; g_pad2_buttons = v; }
        else if (!strcmp(cmd, "analog2")) {
            unsigned q[6], k;
            if (scanf("%x %x %x %x %x %x", &q[0], &q[1], &q[2], &q[3], &q[4], &q[5]) != 6) break;
            for (k = 0; k < 6; k++) g_pad2_analog[k] = (uint8_t)q[k];
        }
        else if (!strcmp(cmd, "padall") && scanf("%u %x", &a, &v) == 2) {
            /* port 1's read with the person's sticks and triggers off centre: all eight bytes */
            uint8_t pad[8] = {0, 0, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66};
            int k;
            pad[0] = (uint8_t)v; pad[1] = (uint8_t)(v >> 8);
            if (g_pad) g_pad(a, pad);
            printf("padall %u", a);
            for (k = 0; k < 8; k++) printf(" %02X", pad[k]);
            printf("\n");
        }
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
        else if (!strcmp(cmd, "damage")) {
            /* R0: the game's damage call, as runtime/battle.c makes it: value base attacker target element */
            unsigned dv, db, da, dt, de;
            if (scanf("%u %u %x %x %u", &dv, &db, &da, &dt, &de) != 5) break;
            printf("damage %u -> %u\n", dv, mod_damage(dv, db, da, dt, de));
        }
        /* R1: the other events, as runtime/battle.c's wrappers call them */
        else if (!strcmp(cmd, "heal")) {
            unsigned hv;
            int hs, ht;
            if (scanf("%u %d %d", &hv, &hs, &ht) != 3) break;
            printf("heal %u -> %u\n", hv, mod_heal(hv, hs, ht));
        }
        else if (!strcmp(cmd, "spawn")) {
            unsigned sa, sr;
            if (scanf("%x %x", &sa, &sr) != 2) break;
            mod_enemy_spawn(sa, sr);
            printf("spawned\n");
        }
        else if (!strcmp(cmd, "action")) {
            unsigned at, ac;
            int as;
            if (scanf("%u %d %x", &at, &as, &ac) != 3) break;
            printf("action %u -> %u\n", at, mod_enemy_action(at, as, ac));
        }
        else if (!strcmp(cmd, "order")) {
            int8_t ord[12];
            int oi, ov;
            for (oi = 0; oi < 12 && scanf("%d", &ov) == 1; oi++) ord[oi] = (int8_t)ov;
            if (oi < 12) break;
            mod_turn_order(ord);
            printf("order");
            for (oi = 0; oi < 12; oi++) printf(" %d", ord[oi]);
            printf("\n");
        }
        else if (!strcmp(cmd, "spirit")) {
            int sv;
            if (scanf("%d", &sv) != 1) break;
            printf("spirit %d -> %d\n", sv, (int)mod_spirit_gain(sv));
        }
        else if (!strcmp(cmd, "escape")) {
            int es, esl;
            if (scanf("%d %d", &es, &esl) != 2) break;
            printf("escape %d -> %d\n", es, mod_escape(es, esl));
        }
        else if (!strcmp(cmd, "rewards")) {
            SoaRewards rw;
            int re, rg, rm;
            if (scanf("%d %d %d", &re, &rg, &rm) != 3) break;
            rw.exp = re, rw.gold = rg, rw.magic_exp = rm;
            mod_rewards(&rw);
            printf("rewards %d %d %d -> %d %d %d\n", re, rg, rm, (int)rw.exp, (int)rw.gold, (int)rw.magic_exp);
        }
        else if (!strcmp(cmd, "effect")) {
            int ft, fe, fv, fc;
            int16_t e16;
            int32_t v32;
            if (scanf("%d %d %d", &ft, &fe, &fv) != 3) break;
            e16 = (int16_t)fe, v32 = fv;
            fc = mod_effect(ft, &e16, &v32);
            printf("effect %d %d -> %d %d%s\n", fe, fv, e16, (int)v32, fc ? " cancelled" : "");
        }
        else if (!strcmp(cmd, "roundend")) {
            unsigned rr;
            if (scanf("%u", &rr) != 1) break;
            mod_round_end(rr);
            printf("round %u ended\n", rr);
        }
        else if (!strcmp(cmd, "ship")) {
            unsigned sv2;
            if (scanf("%u", &sv2) != 1) break;
            printf("ship %u -> %u\n", sv2, mod_ship_damage(sv2));
        }
        /* X2: the save's four sites, as runtime/savext.c's hooks call them */
        else if (!strcmp(cmd, "snapshot") && scanf("%x", &a) == 1) { savext_snapshot(&s, a); printf("snapshot\n"); }
        else if (!strcmp(cmd, "image") && scanf("%x", &a) == 1) { savext_image(&s, a); printf("image\n"); }
        else if (!strcmp(cmd, "loadsave") && scanf("%x", &a) == 1) { savext_load(&s, a); printf("loaded\n"); }
        else if (!strcmp(cmd, "newgame")) { savext_new_game(); printf("new game\n"); }
        else if (!strcmp(cmd, "hex")) {
            /* n bytes at an address, as hex on one line */
            unsigned ha, hn, hi;
            if (scanf("%x %x", &ha, &hn) != 2) break;
            printf("hex %08X ", ha);
            for (hi = 0; hi < hn; hi++) printf("%02X", mem_r8(&s, ha + hi));
            printf("\n");
        }
        else if (!strcmp(cmd, "puthex")) {
            /* bytes from hex at an address: "puthex ADDR N HEX" */
            unsigned pa, pn, pi, pb;
            if (scanf("%x %x", &pa, &pn) != 2) break;
            for (pi = 0; pi < pn && scanf("%2x", &pb) == 1; pi++) mem_w8(&s, pa + pi, (uint8_t)pb);
            printf("put %u\n", pi);
        }
        else if (!strcmp(cmd, "copy")) {
            /* the card's round trip: n bytes from one address to another */
            unsigned from, to, cn;
            if (scanf("%x %x %x", &from, &to, &cn) != 3) break;
            memmove(mem_ptr(&s, to), mem_ptr(&s, from), cn);
            printf("copied\n");
        }
        else if (!strcmp(cmd, "events")) {
            int ev;
            printf("events");
            for (ev = 0; ev < MOD_BATTLE_EVENTS; ev++) printf(" %d", mod_event_count(ev));
            printf("\n");
        }
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


FAKE_SHA = __import__("hashlib").sha1(fake_dol()).hexdigest()


def lib_name(profile: toolchain.Profile) -> str:
    """A mod's library as the port loads it: mod.dll on Windows, mod.so elsewhere."""
    return "mod.dll" if os.name == "nt" or profile.name == "mingw" else "mod.so"


def shared_flags(profile: toolchain.Profile) -> list[str]:
    return ["/LD"] if profile.style == "msvc" else ["-shared", "-fPIC"]


class BuildError(RuntimeError):
    """A compile or link that failed, with what the compiler said."""


def cc(args: list[str], cwd: Path, profile: toolchain.Profile) -> None:
    """`profile`'s compiler, the arguments in cl's grammar (toolchain.cc)."""
    proc = toolchain.cc(args, cwd, profile)
    if proc.returncode != 0:
        raise BuildError((proc.stdout or "") + (proc.stderr or ""))


DRIVER_DEFINES = ["/DSOA_FAKE_GUEST"]  # savext.c without the game's sites (X2)


def driver_sources(out: Path) -> list[Path]:
    """What the fake guest is built from, DRIVER written to out/driver.c: one
    list, so a runtime file mod.c comes to need is added once for every build
    of it (test_mod_library.py builds its own)."""
    return [
        RUNTIME / "mod.c",
        RUNTIME / "sha1.c",  # disc-layer I1
        RUNTIME / "tick.c",
        RUNTIME / "savext.c",  # X2, its sites left out (SOA_FAKE_GUEST)
        *toolchain.runtime_support_sources(),  # plat.c (portability L9)
        out / "driver.c",
    ]


def build_driver(out: Path, profile: toolchain.Profile, *defines: str) -> tuple[Path, Path]:
    """The fake guest in `out`: mod.c and what it needs, with DRIVER as the
    game; returns the program and the fake DOL. Compiled, then linked, since
    cl's one-step /Fo<dir> has no gcc spelling."""
    if toolchain.compiler_path(profile) is None:
        raise BuildError(f"no {profile.name} compiler here")
    (out / "driver.c").write_text(DRIVER, encoding="utf-8")
    sources = driver_sources(out)
    flags = [*profile.cflags, *DRIVER_DEFINES, *(f"/D{d}" for d in defines), "/I", str(RUNTIME)]
    cc([*flags, "/c", *map(str, sources), "/Fo" + str(out) + os.sep], out, profile)
    exe = out / ("mods" + profile.exeext)
    objs = [str(out / (s.stem + profile.objext)) for s in sources]
    cc([*profile.cflags, *objs, "/Fe" + str(exe), *profile.linker], out, profile)
    dol = out / "fake.dol"
    dol.write_bytes(fake_dol())
    return exe, dol


def build_library(
    folder: Path,
    source: Path,
    profile: toolchain.Profile,
    *defines: str,
    include: Path = RUNTIME,
) -> Path:
    """`source` built as a mod's library in `folder`, against the soa_mod.h
    in `include`, with `defines` as /D switches."""
    lib = folder / lib_name(profile)
    cc(
        [
            *profile.cflags,
            *shared_flags(profile),
            "/I",
            str(include),
            *(f"/D{x}" for x in defines),
            str(source),
            "/Fe" + str(lib),
        ],
        folder,
        profile,
    )
    return lib


def swap_sha(ini: str, sha: str) -> str:
    """mod.ini's text with its dol_sha1 replaced by `sha`."""
    out = []
    for line in ini.splitlines(keepends=True):
        key = line.split("=", 1)[0].strip() if "=" in line.split("#", 1)[0] else ""
        if key == "dol_sha1":
            end = "\n" if line.endswith("\n") else ""
            line = f"dol_sha1 = {sha}{end}"
        out.append(line)
    return "".join(out)


# A library's machine, from its header: the PE's (Windows) or the ELF's.
PE_MACHINES = {0x8664: "x86-64", 0xAA64: "arm64", 0x014C: "x86 (32-bit)", 0x01C4: "arm (32-bit)"}
ELF_MACHINES = {0x3E: "x86-64", 0xB7: "arm64", 0x03: "x86 (32-bit)", 0x28: "arm (32-bit)"}


def library_machine(data: bytes) -> str | None:
    """What a mod library was built for, by its header; None when it is not
    a PE or an ELF file at all."""
    if data[:2] == b"MZ" and len(data) >= 0x40:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe : pe + 4] == b"PE\0\0" and len(data) >= pe + 6:
            machine = struct.unpack_from("<H", data, pe + 4)[0]
            return PE_MACHINES.get(machine, f"machine 0x{machine:04X}")
    if data[:4] == b"\x7fELF" and len(data) >= 0x14:
        order = "<" if data[5] == 1 else ">"
        machine = struct.unpack_from(order + "H", data, 0x12)[0]
        return ELF_MACHINES.get(machine, f"machine 0x{machine:04X}")
    return None


def host_machine() -> str:
    """The machine the port runs on, in library_machine's words."""
    import platform

    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        return "x86-64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return m or sys.platform
