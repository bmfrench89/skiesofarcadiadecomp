"""The seam between the runtime and a split game library (specs/android.md L12a).

A split build is Android's arrangement on a desktop: libsoa_runtime.so,
libsoa_game.so and a launcher, the game library loaded by runtime/game.c after
runtime/elfcheck.c has held it to config/seam.txt. Built here with the profile
SOA_CC names (CI's Linux legs: gcc and clang), from the real game.c, elfcheck.c,
plat.c and the C tools/soa/seam.py writes, with stand-ins for the rest of the
runtime and a game of two functions:

- the game library loads through the launcher; its entry runs and calls the
  runtime, and the table's record is the one written into it;
- its dynamic symbols are the one export, soa_game, and imports the runtime has;
- a library is refused before dlopen, in the player's words, when it imports a
  symbol the runtime lacks, carries another build's record, has no table, is
  laid out for 4 KB pages, or carries no record at all.

With a real split build in gen/linux-split (recompile.py --cc gcc --split), its
libraries are held to config/seam.txt too. Everything here wants an ELF system
and skips without one, as on Windows.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import embed, seam, toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
SEAM = seam.read_seam(ROOT / "config" / "seam.txt")
RUNTIME = ROOT / "runtime"
elf = pytest.mark.skipif(
    os.name == "nt"
    or PROFILE.name not in ("gcc", "clang")
    or toolchain.compiler_path(PROFILE) is None,
    reason="needs an ELF system and gcc or clang (SOA_CC)",
)
BOUND = {0x80232E38}  # one binding the runtime answers, as hle.txt's do
RECORD = seam.record(True, "0" * 64)


def cc(args, cwd):
    proc = toolchain.cc(args, cwd, PROFILE)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def stand_ins() -> str:
    """The runtime's seam symbols as stand-ins: data for g_*, a function that
    says it was called otherwise; and the runtime's own fn_ for the binding."""
    lines = ["#include <stdio.h>", "#include <stdint.h>"]
    for name in seam.runtime_exports(SEAM, BOUND):
        if name.startswith("g_"):
            lines.append(f"uint32_t {name};")
        else:
            lines.append(f'void {name}(void) {{ printf("runtime: {name}\\n"); }}')
    return "\n".join(lines) + "\n"


MAIN = r"""
#include <stdio.h>
#include "soa_game.h"
int soa_main(int argc, char** argv)
{
    static CpuState s;
    (void)argc; (void)argv;
    printf("record: %s\n", soa_game_table->record);
    soa_game_table->entry(&s);
    printf("twin: %s\n", soa_game_table->twin(0x80232E38u) ? "found" : "none");
    fflush(stdout);
    return 0;
}
"""


def functions_h() -> str:
    """The stand-in for <out>/functions.h, which declares every translated
    function: here the entry and each twin's body."""
    names = ["fn_80003140", *(seam.body_name(a, BOUND) for a in SEAM.twins)]
    return '#include "cpu.h"\n' + "".join(f"void {n}(CpuState* s);\n" for n in names)


def game_c() -> str:
    """A game of two functions -- the entry, which calls the runtime and
    nothing of the C library's, and the binding's twin -- with dispatch, and
    every other twin the table names."""
    body = [
        '#include "functions.h"',
        "void fn_80003140(CpuState* s) { irq_poll(s); } /* the runtime's stand-in says so */",
        "void dispatch(CpuState* s, uint32_t a) { (void)s; (void)a; }",
        "int dispatch_known(uint32_t a) { return a == 0x80003140u; }",
    ]
    for a in SEAM.twins:
        body.append(f"void {seam.body_name(a, BOUND)}(CpuState* s) {{ (void)s; }}")
    return "\n".join(body) + "\n"


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    """libsoa_runtime.so, the real loader and checks with stand-ins, and the launcher."""
    d = tmp_path_factory.mktemp("runtime")
    (d / "stand_ins.c").write_text(stand_ins(), encoding="utf-8")
    (d / "main_stub.c").write_text(MAIN, encoding="utf-8")
    (d / "runtime_seam.c").write_text(seam.runtime_seam_c(SEAM, BOUND, RECORD), encoding="utf-8")
    (d / "runtime.map").write_text(seam.version_script(SEAM, BOUND), encoding="utf-8")
    (d / "launcher.c").write_text(seam.LAUNCHER_C, encoding="utf-8")
    cc(
        [
            *PROFILE.cflags,
            "-fPIC",
            "-shared",
            "/DSOA_SPLIT=1",
            f"/I{RUNTIME}",
            f"/Fe{d / seam.RUNTIME_SONAME}",
            str(RUNTIME / "game.c"),
            str(RUNTIME / "elfcheck.c"),
            str(RUNTIME / "plat.c"),
            str(d / "stand_ins.c"),
            str(d / "main_stub.c"),
            str(d / "runtime_seam.c"),
            f"-Wl,-soname,{seam.RUNTIME_SONAME}",
            f"-Wl,--version-script={d / 'runtime.map'}",
            *PROFILE.linker,
            "-ldl",
        ],
        d,
    )
    cc(
        [
            *PROFILE.cflags,
            f"/Fe{d / 'soa'}",
            str(d / "launcher.c"),
            f"-L{d}",
            f"-l:{seam.RUNTIME_SONAME}",
            "-Wl,-rpath,$ORIGIN",
            *PROFILE.linker,
        ],
        d,
    )
    return d


def game(
    rt: Path,
    d: Path,
    *,
    record=RECORD,
    extra_c="",
    page=16384,
    table=True,
    note=True,
    undefined=False,
):
    """A game library beside a copy of the launcher, made as the split build
    makes it, or with one thing wrong; the path of the launcher."""
    d.mkdir(parents=True, exist_ok=True)
    for name in ("soa", seam.RUNTIME_SONAME):
        shutil.copy2(rt / name, d / name)
    (d / "functions.h").write_text(functions_h(), encoding="utf-8")
    (d / "game.c").write_text(game_c() + extra_c, encoding="utf-8")
    (d / "disc_sys.c").write_text(embed.disc_sys_c(None), encoding="utf-8")
    table_c = seam.game_table_c(SEAM, BOUND, [0x80003140, *SEAM.twins], record)
    if not note:
        table_c = table_c.replace("#if defined(__ELF__)", "#if 0")
    (d / "game_table.c").write_text(table_c, encoding="utf-8")
    cc(
        [
            *PROFILE.cflags,
            "-fPIC",
            "-fvisibility=hidden",
            "-shared",
            *([] if table else ["/Dsoa_game=soa_game_renamed"]),
            f"/I{RUNTIME}",
            f"/I{d}",
            f"/Fe{d / seam.GAME_SONAME}",
            str(d / "game.c"),
            str(d / "disc_sys.c"),
            str(d / "game_table.c"),
            f"-Wl,-soname,{seam.GAME_SONAME}",
            f"-Wl,-z,max-page-size={page}",
            *([] if undefined else ["-Wl,--no-undefined"]),
            f"-L{d}",
            f"-l:{seam.RUNTIME_SONAME}",
            "-lm",
        ],
        d,
    )
    return d / "soa"


def run(launcher: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    return subprocess.run([str(launcher)], capture_output=True, text=True, env=env, timeout=60)


@elf
def test_the_game_library_loads_runs_and_calls_the_runtime(runtime, tmp_path):
    proc = run(game(runtime, tmp_path / "good"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"[game] {tmp_path / 'good' / seam.GAME_SONAME}: {RECORD}" in proc.stderr, proc.stderr
    assert f"record: {RECORD}" in proc.stdout
    assert "runtime: irq_poll" in proc.stdout, proc.stdout
    assert "twin: found" in proc.stdout


@elf
def test_the_game_library_exports_the_table_alone(runtime, tmp_path):
    game(runtime, tmp_path / "g")
    nm = shutil.which("nm")
    if nm is None:
        pytest.skip("no nm")
    lib = tmp_path / "g" / seam.GAME_SONAME
    out = subprocess.run(
        [nm, "-D", "--defined-only", str(lib)], capture_output=True, text=True
    ).stdout
    defined = {
        ln.split()[-1] for ln in out.splitlines() if ln.split() and ln.split()[-2] in "TtDdRrBb"
    }
    assert defined - {"_init", "_fini"} == {"soa_game"}, defined


REFUSALS = {
    "an import the runtime lacks": (
        {"extra_c": "void hle_report(void);\nvoid g2(void) { hle_report(); }\n", "undefined": True},
        "this library needs hle_report, which this app's runtime does not have",
    ),
    "another build's record": (
        {"record": seam.record(True, "1" * 64)},
        "this library was built from other sources than this app (its baked is " + "1" * 64,
    ),
    "the decompiled code's record": (
        {"record": seam.record(False, "0" * 64)},
        "(its mode is decomp, the app's no-decomp)",
    ),
    "no table": ({"table": False}, "has no soa_game table: it is not a game library"),
    "4 KB pages": ({"page": 4096}, "this library was built for 4096-byte pages"),
    "no record": ({"note": False}, "this library carries no build record"),
}


@elf
@pytest.mark.parametrize("what", sorted(REFUSALS))
def test_a_library_is_refused_before_dlopen_in_the_players_words(runtime, tmp_path, what):
    kw, words = REFUSALS[what]
    proc = run(game(runtime, tmp_path / "bad", **kw))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert words in proc.stderr, proc.stderr
    assert "runtime: irq_poll" not in proc.stdout


SPLIT = ROOT / "gen" / "linux-split"


@elf
def test_a_real_split_build_crosses_only_the_seam():
    game_lib, runtime_lib = SPLIT / seam.GAME_SONAME, SPLIT / seam.RUNTIME_SONAME
    if not game_lib.exists() or not runtime_lib.exists() or shutil.which("nm") is None:
        pytest.skip(
            "no split build in gen/linux-split (recompile.py --cc gcc --split --compile --link)"
        )

    def dyn(lib, *flags):
        out = subprocess.run(["nm", "-D", *flags, str(lib)], capture_output=True, text=True).stdout
        return {ln.split()[-1].split("@")[0] for ln in out.splitlines() if ln.strip()}

    from soa.hle import load_hle

    bound = set(load_hle(ROOT / "config" / "hle.txt"))
    sys.path.insert(0, str(ROOT / "tools"))
    import recompile

    bound -= recompile.decomp_bound()  # a split build is --no-decomp
    exports = set(seam.runtime_exports(SEAM, bound))
    weak = dyn(game_lib, "--undefined-only") - exports - set(SEAM.libc)
    assert all(n.startswith(("_ITM_", "__gmon_start__")) for n in weak), weak
    assert dyn(game_lib, "--defined-only") - {"_init", "_fini"} == {"soa_game"}
    assert dyn(runtime_lib, "--defined-only") - {"_init", "_fini"} == exports | {"soa_run"}
