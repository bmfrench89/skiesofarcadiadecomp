"""The game library from the PC, for Android (specs/android.md L12b).

recompile.py --cc android-arm64 builds libsoa_game.so with the NDK's clang
against a stand-in runtime library, and tools/soa/elfcheck.py, the Python twin
of runtime/elfcheck.c, checks it as the phone would before saying the build
is done. With an NDK here (tools/soa/toolchain.py android_ndk), a game of two
functions is built the way recompile.py builds the real one:

- elfcheck.py passes it: AArch64, a shared object named libsoa_game.so,
  every PT_LOAD at 16 KB, needing libsoa_runtime.so, exporting soa_game alone,
  importing only what the runtime and the C library have, its record the one
  written into it; and two builds are byte for byte the same;
- a library with one thing wrong draws its refusal: 4 KB pages, its functions
  not hidden, an import the runtime lacks, another build's record, and one
  built for x86-64 checked for an ARM phone;
- runtime/elfcheck.c, built for this machine with the profile SOA_CC names
  (MSVC by default), gives every one of those libraries the same verdict in the
  same words as the Python, but for the hidden-functions check, which only the
  PC makes (the phone needs its table, and nothing else of the export list).

Everything skips, saying why, without an NDK; the C half without a compiler
for this machine.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import elfcheck, embed, seam, toolchain  # noqa: E402

SEAM = seam.read_seam(ROOT / "config" / "seam.txt")
BOUND = {0x80232E38}
RECORD = seam.record(True, "0" * 64)
RUNTIME = ROOT / "runtime"
HOST = toolchain.profile(os.environ.get("SOA_CC"))
ndk = pytest.mark.skipif(
    toolchain.compiler_path(toolchain.ANDROID_ARM64) is None,
    reason="no Android NDK (SOA_ANDROID_NDK, ANDROID_NDK_HOME, or an SDK's ndk/)",
)


def test_a_mistyped_ndk_is_no_ndk_and_the_places_are_named(monkeypatch, tmp_path):
    """SOA_ANDROID_NDK naming no NDK is none, never the next one found (a typo
    would build with another NDK unannounced), and the places looked are
    listed for the build's message, the variable's value among them."""
    monkeypatch.setenv("SOA_ANDROID_NDK", str(tmp_path / "no-such-ndk"))
    assert toolchain.android_ndk() is None
    assert toolchain.compiler_path(toolchain.ANDROID_ARM64) is None
    places = toolchain.android_ndk_places()
    assert places[0] == f"SOA_ANDROID_NDK ({tmp_path / 'no-such-ndk'})"
    assert any(p.startswith("ANDROID_NDK_HOME (") for p in places)
    (tmp_path / "ndk" / "toolchains").mkdir(parents=True)
    monkeypatch.setenv("SOA_ANDROID_NDK", str(tmp_path / "ndk"))
    assert toolchain.android_ndk() == tmp_path / "ndk"


def cc(p, args, cwd):
    proc = toolchain.cc(args, cwd, p)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def functions_h() -> str:
    names = ["fn_80003140", *(seam.body_name(a, BOUND) for a in SEAM.twins)]
    return '#include "cpu.h"\n' + "".join(f"void {n}(CpuState* s);\n" for n in names)


def game_c(extra: str = "") -> str:
    body = [
        '#include "functions.h"',
        "void fn_80003140(CpuState* s) { irq_poll(s); }",
        "void dispatch(CpuState* s, uint32_t a) { (void)s; (void)a; }",
        "int dispatch_known(uint32_t a) { return a == 0x80003140u; }",
        *(f"void {seam.body_name(a, BOUND)}(CpuState* s) {{ (void)s; }}" for a in SEAM.twins),
    ]
    return "\n".join(body) + "\n" + extra


def build(
    d: Path,
    p=toolchain.ANDROID_ARM64,
    *,
    record=RECORD,
    extra="",
    page=16384,
    flags=(),
    undefined=False,
):
    """libsoa_game.so in d, as recompile.py's android_link_plan makes it, or
    with one thing wrong."""
    stub = d / "stub"
    stub.mkdir(parents=True, exist_ok=True)
    (stub / "stub_runtime.c").write_text(seam.stub_runtime_c(SEAM, BOUND), encoding="utf-8")
    cc(
        p,
        [
            *p.cflags,
            "-fvisibility=default",
            "-shared",
            f"/Fe{stub / seam.RUNTIME_SONAME}",
            str(stub / "stub_runtime.c"),
            f"-Wl,-soname,{seam.RUNTIME_SONAME}",
        ],
        d,
    )
    (d / "functions.h").write_text(functions_h(), encoding="utf-8")
    (d / "game.c").write_text(game_c(extra), encoding="utf-8")
    (d / "disc_sys.c").write_text(embed.disc_sys_c(None), encoding="utf-8")
    (d / "game_table.c").write_text(
        seam.game_table_c(SEAM, BOUND, [0x80003140, *SEAM.twins], record), encoding="utf-8"
    )
    cc(
        p,
        [
            *p.cflags,
            *flags,
            "-shared",
            f"/I{RUNTIME}",
            f"/I{d}",
            f"/Fe{d / seam.GAME_SONAME}",
            str(d / "game.c"),
            str(d / "disc_sys.c"),
            str(d / "game_table.c"),
            f"-Wl,-soname,{seam.GAME_SONAME}",
            f"-Wl,-z,max-page-size={page}",
            *([] if undefined else ["-Wl,--no-undefined"]),
            f"-L{stub}",
            f"-l:{seam.RUNTIME_SONAME}",
            *p.linker,
        ],
        d,
    )
    return d / seam.GAME_SONAME


def check(lib: Path) -> list[str]:
    return elfcheck.problems(
        elfcheck.read(lib),
        machine=elfcheck.EM_AARCH64,
        exports=seam.runtime_exports(SEAM, BOUND),
        libc=SEAM.libc,
        record=RECORD,
        path=str(lib),
    )


@ndk
def test_the_library_is_what_the_phone_loads(tmp_path):
    lib = build(tmp_path)
    assert check(lib) == []
    elf = elfcheck.read(lib)
    assert (elf.machine, elf.type, elf.soname) == (elfcheck.EM_AARCH64, 3, seam.GAME_SONAME)
    assert elf.load_aligns and all(a == 16384 for a in elf.load_aligns), elf.load_aligns
    assert seam.RUNTIME_SONAME in elf.needed and elf.record == RECORD
    assert set(elf.exports) - {"_init", "_fini"} == {"soa_game"}
    assert ("irq_poll", False) in elf.imports


@ndk
def test_two_builds_are_the_same_bytes(tmp_path):
    a = build(tmp_path / "a").read_bytes()
    b = build(tmp_path / "b").read_bytes()
    assert a == b


MUTANTS = {
    "4 KB pages": ({"page": 4096}, "this library was built for 4096-byte pages"),
    "its functions not hidden": (
        {"flags": ("-fvisibility=default",)},
        "beside soa_game: its functions are not hidden",
    ),
    "an import the runtime lacks": (
        {"extra": "void hle_report(void);\nvoid g2(void) { hle_report(); }\n", "undefined": True},
        "this library needs hle_report, which this app's runtime does not have",
    ),
    "another build's record": (
        {"record": seam.record(True, "1" * 64)},
        "built from other sources than this app",
    ),
    "built for x86-64": (
        {"p": toolchain.ANDROID_X86_64},
        "this library was built for x86-64, not this device",
    ),
}


@ndk
@pytest.mark.parametrize("what", sorted(MUTANTS))
def test_a_library_with_one_thing_wrong_draws_its_refusal(tmp_path, what):
    kw, words = MUTANTS[what]
    found = check(build(tmp_path, **kw))
    assert any(words in f for f in found), found


DRIVER = r"""
#include "elfcheck.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* argv: library, machine, record, then the export list and the C library's,
 * separated by a lone "--" */
int main(int argc, char** argv)
{
    ElfWant w;
    char why[700];
    int i, split = 4;
    while (split < argc && strcmp(argv[split], "--")) split++;
    w.machine = (unsigned short)atoi(argv[2]);
    w.record = argv[3];
    w.exports = (const char* const*)(argv + 4);
    w.nexports = (unsigned)(split - 4);
    w.libc = (const char* const*)(argv + split + 1);
    w.nlibc = (unsigned)(argc - split - 1);
    w.runtime_soname = "libsoa_runtime.so";
    (void)i;
    if (elf_check(argv[1], &w, why, sizeof why) == 0) { puts("ok"); return 0; }
    puts(why);
    return 1;
}
"""


@ndk
def test_the_phone_s_checker_agrees_with_the_pc_s(tmp_path):
    if toolchain.compiler_path(HOST) is None:
        pytest.skip(f"no {HOST.name} to build runtime/elfcheck.c for this machine")
    drv = tmp_path / "driver"
    drv.mkdir()
    (drv / "driver.c").write_text(DRIVER, encoding="utf-8")
    exe = drv / ("elfcheck" + HOST.exeext)
    sources = [RUNTIME / "elfcheck.c", drv / "driver.c"]
    cc(
        HOST,
        [*HOST.cflags, "/c", "/I", str(RUNTIME), *map(str, sources), "/Fo" + str(drv) + os.sep],
        drv,
    )
    objs = [str(drv / (s.stem + HOST.objext)) for s in sources]
    cc(HOST, [*HOST.cflags, *objs, "/Fe" + str(exe), *HOST.linker], drv)
    libs = {"good": build(tmp_path / "good")}
    for what, (kw, _) in MUTANTS.items():
        libs[what] = build(tmp_path / what.replace(" ", "_"), **kw)
    for what, lib in libs.items():
        args = [
            str(exe),
            str(lib),
            str(elfcheck.EM_AARCH64),
            RECORD,
            *seam.runtime_exports(SEAM, BOUND),
            "--",
            *SEAM.libc,
        ]
        c_says = subprocess.run(args, capture_output=True, text=True, timeout=60).stdout.strip()
        phone = [f for f in check(lib) if "its functions are not hidden" not in f]
        assert c_says == (phone[0] if phone else "ok"), (what, c_says, phone)
