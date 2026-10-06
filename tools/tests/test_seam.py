"""The seam between the runtime and a split game library (specs/android.md L12a, L12d).

A split build is Android's arrangement on a desktop: libsoa_runtime.so,
libsoa_game.so and a launcher, the game library loaded by runtime/game.c after
runtime/elfcheck.c has held it to config/seam.txt. Built here with the profile
SOA_CC names (CI's Linux legs: gcc and clang), from the real game.c, elfcheck.c,
plat.c and the C tools/soa/seam.py writes, with stand-ins for the rest of the
runtime (disc.c's answers among them) and a game of two functions:

- the game library loads through the launcher; its entry runs and calls the
  runtime, and the table's record is the one written into it, naming the
  executable this runtime plays; one with that executable's system files
  built in loads too;
- its dynamic symbols are the one export, soa_game, and imports the runtime has;
- a library is refused before dlopen, in the player's words, when it imports a
  symbol the runtime lacks, comes from another release or the decompiled
  code's build, was made from another disc's executable or names none, has no
  table, is laid out for 4 KB pages, carries no record at all, or is a
  Windows program; and after dlopen when the system files built into it are
  not the executable this runtime plays;
- runtime/game.h's calls, as runtime/android.c makes them: a check loads
  nothing; a library refused before dlopen leaves the process free to load
  another, and one refused after it is the process's one dlopen and leaves
  nothing to run; one library is loaded at most in a process, and soa_run
  runs the one already loaded;
- a library handed over open, as /proc/self/fd/N, is checked through its
  descriptor though its file cannot be read by name, and N's offset moves.

With a real split build in gen/linux-split (recompile.py --cc gcc --split), its
libraries are held to config/seam.txt too. Everything here wants an ELF system
and skips without one, as on Windows.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import elfcheck, embed, gamefixture, seam, toolchain  # noqa: E402

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
# The executable this test's runtime plays (its disc_port_dol_sha1), and the
# bytes it is the SHA-1 of, for a library with its system files built in.
PORT_EXE = b"the executable this test's runtime plays"
PORT_DOL = hashlib.sha1(PORT_EXE, usedforsecurity=False).hexdigest()
RUNTIME_RECORD = seam.record(True, "0" * 64)  # the runtime's: abi, mode and baked
RECORD = seam.record(True, "0" * 64, PORT_DOL)  # a library's: and the executable it came from
LOADER_CALLS = ("soa_check_game", "soa_load_game", "soa_game_dlopened")


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


# runtime/disc.c's two answers runtime/game.c asks for, as stand-ins: the
# executable this runtime plays, and whether the system files built into the
# loaded library are its copies -- none built in (a --no-embed build, 0), the
# executable this runtime plays (1), or another one (-1), which disc.c's
# disc_builtin would find by hashing them.
DISC = f"""
#include <stdio.h>
#include <string.h>
#include "soa_game.h"

const char* disc_port_dol_sha1(void)
{{
    return "{PORT_DOL}";
}}

int disc_builtin(char* why, size_t cap)
{{
    if (*soa_game_table->dol_size == 0) return 0;
    if (strcmp(soa_game_table->dol_sha1, disc_port_dol_sha1()) == 0) return 1;
    snprintf(why, cap, "the executable built into this game library is %s, not this port's", soa_game_table->dol_sha1);
    return -1;
}}
"""


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


# runtime/game.h's calls, in the order runtime/android.c makes them: one per
# pair of arguments, "check <path>" or "load <path>", each said with whether
# a library has been dlopened yet; and then the run.
LOADER = r"""
#include <stdio.h>
#include <string.h>
#include "game.h"
int soa_run(int argc, char** argv);
int main(int argc, char** argv)
{
    char why[700];
    int i, rc;
    for (i = 1; i + 1 < argc; i += 2) {
        if (!strcmp(argv[i], "check"))
            rc = soa_check_game(argv[i + 1], why, sizeof why);
        else
            rc = soa_load_game(argv[i + 1], why, sizeof why);
        printf("%s: %d, dlopened %d%s%s\n", argv[i], rc, soa_game_dlopened(), rc ? ": " : "", rc ? why : "");
    }
    fflush(stdout);
    return soa_run(1, argv);
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
    every other twin the table names; and two calls into the C library, as
    translated code makes them, so it needs glibc's libc.so.6 and libm.so.6
    as a real split build's library does (the linker drops a library nothing
    calls)."""
    body = [
        '#include "functions.h"',
        "void fn_80003140(CpuState* s) { irq_poll(s); } /* the runtime's stand-in says so */",
        "void dispatch(CpuState* s, uint32_t a) { (void)s; (void)a; }",
        "int dispatch_known(uint32_t a) { return a == 0x80003140u; }",
        "void* game_copy(void* d, const void* s, size_t n) { return memcpy(d, s, n); }",
        "double game_root(double x) { return sqrt(x); }",
    ]
    for a in SEAM.twins:
        body.append(f"void {seam.body_name(a, BOUND)}(CpuState* s) {{ (void)s; }}")
    return "\n".join(body) + "\n"


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    """libsoa_runtime.so, the real loader and checks with stand-ins, the
    launcher, and a program making runtime/game.h's calls, which this
    library exports for it beside the seam (the APK's runtime calls them
    from inside, runtime/android.c)."""
    d = tmp_path_factory.mktemp("runtime")
    (d / "stand_ins.c").write_text(stand_ins(), encoding="utf-8")
    (d / "disc_stand_ins.c").write_text(DISC, encoding="utf-8")
    (d / "main_stub.c").write_text(MAIN, encoding="utf-8")
    (d / "runtime_seam.c").write_text(
        seam.runtime_seam_c(SEAM, BOUND, RUNTIME_RECORD), encoding="utf-8"
    )
    (d / "runtime.map").write_text(
        seam.version_script(SEAM, BOUND, extra=LOADER_CALLS), encoding="utf-8"
    )
    (d / "launcher.c").write_text(seam.LAUNCHER_C, encoding="utf-8")
    (d / "loader.c").write_text(LOADER, encoding="utf-8")
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
            str(d / "disc_stand_ins.c"),
            str(d / "main_stub.c"),
            str(d / "runtime_seam.c"),
            f"-Wl,-soname,{seam.RUNTIME_SONAME}",
            f"-Wl,--version-script={d / 'runtime.map'}",
            *PROFILE.linker,
            "-ldl",
        ],
        d,
    )
    for name in ("launcher", "loader"):
        cc(
            [
                *PROFILE.cflags,
                f"/I{RUNTIME}",
                f"/Fe{d / ('soa' if name == 'launcher' else name)}",
                str(d / f"{name}.c"),
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
    system=None,
    windows=False,
):
    """A game library beside a copy of the launcher, made as the split build
    makes it, or with one thing wrong: `system` built into it as
    disc_sys.c's files (embed.disc_sys_c), or a Windows program in its
    place; the path of the launcher."""
    d.mkdir(parents=True, exist_ok=True)
    for name in ("soa", seam.RUNTIME_SONAME):
        shutil.copy2(rt / name, d / name)
    if windows:
        (d / seam.GAME_SONAME).write_bytes(gamefixture.windows_file())
        return d / "soa"
    (d / "functions.h").write_text(functions_h(), encoding="utf-8")
    (d / "game.c").write_text(game_c() + extra_c, encoding="utf-8")
    (d / "disc_sys.c").write_text(embed.disc_sys_c(system), encoding="utf-8")
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


def system_files(exe: bytes) -> dict[str, bytes]:
    """disc_sys.c's three files for a library built with `exe` as its executable."""
    return {"main.dol": exe, "boot.bin": bytes(0x440), "fst.bin": bytes(12)}


def run(launcher: Path, *args: str, env=None, **kw) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    return subprocess.run(
        [str(launcher), *args],
        capture_output=True,
        text=True,
        env={**clean, **(env or {})},
        timeout=60,
        **kw,
    )


@elf
def test_the_game_library_loads_runs_and_calls_the_runtime(runtime, tmp_path):
    proc = run(game(runtime, tmp_path / "good"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"[game] {tmp_path / 'good' / seam.GAME_SONAME}: {RECORD}" in proc.stderr, proc.stderr
    assert f"record: {RECORD}" in proc.stdout
    assert "runtime: irq_poll" in proc.stdout, proc.stdout
    assert "twin: found" in proc.stdout
    # by glibc's names for its C libraries, which a desktop runtime takes and
    # a phone's refuses as a Linux library's (ElfWant.android)
    needed = elfcheck.read(tmp_path / "good" / seam.GAME_SONAME).needed
    assert {"libc.so.6", "libm.so.6"} <= set(needed), needed


@elf
def test_a_library_with_this_executable_built_in_loads(runtime, tmp_path):
    proc = run(game(runtime, tmp_path / "embedded", system=system_files(PORT_EXE)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "runtime: irq_poll" in proc.stdout, proc.stdout


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


SAME_RELEASE = "install the app and run Setup from the same release"
OWN_DISC = "rebuild it with Setup from your own disc"
REFUSALS = {
    "an import the runtime lacks": (
        {"extra_c": "void hle_report(void);\nvoid g2(void) { hle_report(); }\n", "undefined": True},
        "this library needs hle_report, which this app's runtime does not have",
    ),
    "another release's record": (
        {"record": seam.record(True, "1" * 64, PORT_DOL)},
        "this game library and this app come from different releases (its build is 111111111111, "
        f"the app's 000000000000): {SAME_RELEASE}",
    ),
    "the decompiled code's record": (
        {"record": seam.record(False, "0" * 64, PORT_DOL)},
        "this game library and this app come from different releases (its mode is decomp, "
        f"the app's no-decomp): {SAME_RELEASE}",
    ),
    "another disc's executable": (
        {"record": seam.record(True, "0" * 64, "1" * 40)},
        "this game library was made from another disc's executable (111111111111, this app plays "
        f"{PORT_DOL[:12]}): {OWN_DISC}",
    ),
    "no executable named": (
        {"record": RUNTIME_RECORD},
        "this game library does not say which disc's executable it was made from (this app plays "
        f"{PORT_DOL[:12]}): {OWN_DISC}",
    ),
    "no table": ({"table": False}, "has no soa_game table: it is not a game library"),
    "4 KB pages": ({"page": 4096}, "this library was built for 4096-byte pages"),
    "no record": ({"note": False}, "this library carries no build record"),
    "a Windows program": (
        {"windows": True},
        "is a Windows program for x86-64, not a game library for this device",
    ),
}


@elf
@pytest.mark.parametrize("what", sorted(REFUSALS))
def test_a_library_is_refused_before_dlopen_in_the_players_words(runtime, tmp_path, what):
    kw, words = REFUSALS[what]
    proc = run(game(runtime, tmp_path / "bad", **kw))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert words in proc.stderr, proc.stderr
    assert "runtime: irq_poll" not in proc.stdout


@elf
def test_a_library_whose_system_files_are_another_executable_is_refused(runtime, tmp_path):
    """After dlopen, the system files built into it are held to the
    executable this runtime plays (disc_builtin): disc_open would pass over
    them, and the run would stop at boot with nothing on the screen."""
    d = tmp_path / "other-exe"
    proc = run(game(runtime, d, system=system_files(b"another executable")))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    damaged = "the system files built into this game library are damaged: rebuild it with Setup"
    assert f"[game] {damaged}" in proc.stderr, proc.stderr
    # and why, for the log: here the stand-in's words for disc_builtin's
    other = hashlib.sha1(b"another executable", usedforsecurity=False).hexdigest()
    detail = f"the executable built into this game library is {other}, not this port's"
    assert f"[game] {d / seam.GAME_SONAME}: {detail}" in proc.stderr, proc.stderr
    assert "runtime: irq_poll" not in proc.stdout


ONE_LOAD = (
    "only one game library can be loaded in a run, and one already was: open the app again to use"
)


@elf
def test_the_loader_s_calls_as_android_c_makes_them(runtime, tmp_path):
    """A check loads nothing; a library refused before dlopen leaves the
    process free to load another (after an app update the installed one is
    refused so, and the player's next pick must still load); a load loads; a
    second load in the process is refused, whatever it names; and soa_run
    runs the library already loaded, never SOA_GAME's (here a path to
    nothing, which would be refused)."""
    bad = game(runtime, tmp_path / "bad", page=4096).parent / seam.GAME_SONAME
    good = game(runtime, tmp_path / "good").parent / seam.GAME_SONAME
    steps = ("check", bad, "load", bad, "check", good, "load", good, "load", good)
    proc = run(runtime / "loader", *map(str, steps), env={"SOA_GAME": str(tmp_path / "nothing.so")})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    pages = (
        "this library was built for 4096-byte pages, and devices may use 16 KB ones: "
        "rebuild it with this package's Setup"
    )
    assert lines[:5] == [
        f"check: 1, dlopened 0: {pages}",
        f"load: 1, dlopened 0: {pages}",
        "check: 0, dlopened 0",
        "load: 0, dlopened 1",
        f"load: 1, dlopened 1: {ONE_LOAD} {good}",
    ], lines
    assert f"record: {RECORD}" in lines and "runtime: irq_poll" in lines, lines
    assert proc.stderr.count("[game] ") == 1, proc.stderr  # the one load's line


@elf
def test_a_library_refused_after_dlopen_leaves_nothing_to_run(runtime, tmp_path):
    """One refused after dlopen -- its system files another executable's --
    is still the process's one dlopen, so no second library meets
    disc_builtin's verdict on the first, which disc.c keeps for the process;
    and its table goes with it, so soa_run has nothing to run, and refuses
    SOA_GAME's good library as a second load."""
    other = game(runtime, tmp_path / "other", system=system_files(b"another executable"))
    good = game(runtime, tmp_path / "good").parent / seam.GAME_SONAME
    proc = run(
        runtime / "loader",
        "load",
        str(other.parent / seam.GAME_SONAME),
        env={"SOA_GAME": str(good)},
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    damaged = "the system files built into this game library are damaged: rebuild it with Setup"
    assert proc.stdout.splitlines()[:1] == [f"load: 1, dlopened 1: {damaged}"], proc.stdout
    assert "record:" not in proc.stdout and "runtime: irq_poll" not in proc.stdout, proc.stdout
    assert f"[game] {ONE_LOAD} {good}" in proc.stderr, proc.stderr


@elf
def test_a_library_handed_over_open_is_checked_through_its_descriptor(runtime, tmp_path):
    """SOA_GAME=/proc/self/fd/N, as runtime/android.c checks a picked library
    before copying it (L12d): elf_check reads it through N, so a file that
    can no longer be read by name is still checked -- here refused for its 4
    KB pages, which only a read of its program headers can say. A checker
    that opened the path again would be refused "cannot open" instead, but
    not as root, who reads the file anyway; so N's offset is asked too, which
    holds as root: reads through a duplicate of N move it, and a file opened
    again by name has an offset of its own."""
    launcher = game(runtime, tmp_path / "picked", page=4096)
    lib = launcher.parent / seam.GAME_SONAME
    fd = os.open(lib, os.O_RDONLY)
    try:
        lib.chmod(0)
        proc = run(launcher, env={"SOA_GAME": f"/proc/self/fd/{fd}"}, pass_fds=(fd,))
        moved = os.lseek(fd, 0, os.SEEK_CUR)  # 0 when it was opened
    finally:
        lib.chmod(0o644)
        os.close(fd)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "this library was built for 4096-byte pages" in proc.stderr, proc.stderr
    assert moved > 0, "N's offset never moved: the library was opened again by name"


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
