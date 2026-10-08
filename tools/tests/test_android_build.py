"""The game library from the PC, for Android (specs/android.md L12b, L12d,
specs/android-sysroot.md R5a).

recompile.py --cc android-arm64 builds libsoa_game.so through R5's route --
llvm-mingw's clang against this repository's own sysroot, the C libraries'
stubs from config/seam.txt -- against a stand-in runtime library, and
tools/soa/elfcheck.py, the Python twin of runtime/elfcheck.c, checks it as the
phone would before saying the build is done. With llvm-mingw and the sysroot
here, a game of two functions is built by recompile.py's own link plan
(tools/soa/gamefixture.py):

- elfcheck.py passes it: AArch64, a shared object named libsoa_game.so,
  every PT_LOAD at 16 KB, needing libsoa_runtime.so and the C libraries by
  bionic's own names, exporting soa_game alone, importing only what the
  runtime and the C library have, its record the one written into it, naming
  the executable the app plays; and two builds are byte for byte the same;
- a file with one thing wrong draws its refusal, first: 4 KB pages, its
  functions not hidden, an import the runtime lacks, another release's
  record, another disc's executable or none named, one built for x86-64 or
  for 32-bit ARM checked for an ARM phone, a Linux library needing glibc's
  libc.so.6, a Windows program or DLL (made here: .exe and .dll files are
  refused in this repository), and a section-name table that does not end;
- runtime/elfcheck.c, built for this machine with the profile SOA_CC names
  (MSVC by default), gives every one of those files, four that are no library
  for this system at all, and records only a damaged note would hold, the
  same verdict in the same words as the Python: as the phone's runtime holds
  them, as a desktop split build's does (glibc's C libraries too), and as
  recompile.py's check after linking does (no executable named), but for the
  hidden-functions check, which only the PC makes (the phone needs its table,
  and nothing else of the export list);
- the set a device is given to refuse (gamefixture.android_mutants) is each
  wrong in its one way, and elfcheck.c says of each what its prediction says.

Without a compiler at all, the route's own decisions are held: where the
build looked when it finds no compiler, before it reads anything; the game
library never consulting an NDK; every link naming its C libraries after its
objects; the stubs' names and places; the post-link check being the phone's;
a failed compile's reason read from stderr; the link steps' progress lines;
and an Android command run without clang's search variables. Built, the stubs
export seam.txt's names and no others, a call outside the seam fails the
link, a Linux SONAME is refused after it, the fixture is recompile.py's own
plan, a folder with a comma and a space builds, and CPATH cannot reach the
compile.

Those that build skip, saying why, without llvm-mingw or the sysroot; the C
half without a compiler for this machine. CI's android-route job runs them
with no skips.
"""

import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import elfcheck, gamefixture, seam, toolchain  # noqa: E402
from soa.dump import DEFAULT_CONFIG, read_project  # noqa: E402

SEAM, BOUND = gamefixture.SEAM, gamefixture.BOUND
DOL = read_project(DEFAULT_CONFIG).sha1  # the executable the app plays (disc_port_dol_sha1)
RECORD = seam.record(True, "0" * 64)  # the runtime's: abi, mode and baked
GAME_RECORD = seam.record(True, "0" * 64, DOL)  # a library's: and the executable it came from
RUNTIME = ROOT / "runtime"
HOST = toolchain.profile(os.environ.get("SOA_CC"))
route = pytest.mark.skipif(
    toolchain.compiler_path(toolchain.ANDROID_ARM64) is None,
    reason="no llvm-mingw or no Android sysroot (python tools/fetch_mingw.py, then python "
    "tools/fetch_android_sysroot.py)",
)
# What the phone's runtime holds a library to; a desktop split build's
# runtime holds it to the same executable (runtime/game.c names one in every
# build) and takes glibc's C libraries too; with no executable named, the
# record's dol= is held to nothing (a NULL ElfWant.dol, elfcheck.c's "-").
PHONE = {
    "machine": elfcheck.EM_AARCH64,
    "exports": seam.runtime_exports(SEAM, BOUND),
    "libc": SEAM.libc,
    "record": RECORD,
    "dol": DOL,
    "android": True,
}
DESKTOP = {**PHONE, "android": False}
NO_DOL = {**PHONE, "dol": None}
SETTINGS = {"phone": PHONE, "desktop": DESKTOP, "no-dol": NO_DOL}


def test_a_mistyped_ndk_is_no_ndk_and_the_places_are_named(monkeypatch, tmp_path):
    """SOA_ANDROID_NDK naming no NDK is none, never the next one found (a typo
    would build with another NDK unannounced), and the places looked are
    listed for the build's message, the variable's value among them."""
    monkeypatch.setenv("SOA_ANDROID_NDK", str(tmp_path / "no-such-ndk"))
    assert toolchain.android_ndk() is None
    assert toolchain.compiler_path(toolchain.ANDROID_ARM64_NDK) is None
    places = toolchain.android_ndk_places()
    assert places[0] == f"SOA_ANDROID_NDK ({tmp_path / 'no-such-ndk'})"
    assert any(p.startswith("ANDROID_NDK_HOME (") for p in places)
    (tmp_path / "ndk" / "toolchains").mkdir(parents=True)
    monkeypatch.setenv("SOA_ANDROID_NDK", str(tmp_path / "ndk"))
    assert toolchain.android_ndk() == tmp_path / "ndk"


def cc(p, args, cwd):
    proc = toolchain.cc(args, cwd, p)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")


def build(d: Path, p=toolchain.ANDROID_ARM64, **kw) -> Path:
    """gamefixture.build, with a library's record unless another is given."""
    return gamefixture.build(d, p, **{"record": GAME_RECORD, **kw})


def unend_names(lib: Path) -> None:
    """Overwrite the closing NUL of lib's section-name table, so its last
    name runs to the table's end."""
    data = bytearray(lib.read_bytes())
    shoff = struct.unpack_from("<Q", data, 40)[0]
    shstrndx = struct.unpack_from("<H", data, 62)[0]
    off, size = struct.unpack_from("<QQ", data, shoff + shstrndx * 64 + 24)
    assert data[off + size - 1] == 0
    data[off + size - 1] = ord("x")
    lib.write_bytes(bytes(data))


def make(d: Path, *, windows=None, names_unended=False, arm32=False, **kw) -> Path:
    """A library by build()'s keywords; a Windows file for `windows`, its
    (machine, dll); a 32-bit ARM library; or a library whose section-name
    table does not end."""
    if arm32:
        return gamefixture.arm32_library(d)
    if windows is not None:
        d.mkdir(parents=True, exist_ok=True)
        lib = d / seam.GAME_SONAME
        lib.write_bytes(gamefixture.windows_file(*windows))
        return lib
    lib = build(d, **kw)
    if names_unended:
        unend_names(lib)
    return lib


def check(lib: Path, want=PHONE) -> list[str]:
    """Every refusal elfcheck.py has for lib, first first; a file that is no
    ELF at all has its one."""
    try:
        elf = elfcheck.read(lib)
    except elfcheck.NotElf as exc:
        return [str(exc)]
    return elfcheck.problems(elf, **want, path=str(lib))


SAME_RELEASE = "install the app and run Setup from the same release"
OWN_DISC = "rebuild it with Setup from your own disc"
FOR_DEVICE = "rebuild it for this device with Setup"
PICK = (
    "not a game library for this device: pick the libsoa_game.so that Setup makes for this device"
)
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
    "another release's record": (
        {"record": seam.record(True, "1" * 64, DOL)},
        "this game library and this app come from different releases (its build is 111111111111, "
        f"the app's 000000000000): {SAME_RELEASE}",
    ),
    "another disc's executable": (
        {"record": seam.record(True, "0" * 64, "1" * 40)},
        "this game library was made from another disc's executable (111111111111, this app plays "
        f"{DOL[:12]}): {OWN_DISC}",
    ),
    "no executable named": (
        {"record": RECORD},
        "this game library does not say which disc's executable it was made from (this app plays "
        f"{DOL[:12]}): {OWN_DISC}",
    ),
    "built for x86-64": (
        {"p": toolchain.ANDROID_X86_64},
        f"this library was built for x86-64, not this device (64-bit ARM (AArch64)): {FOR_DEVICE}",
    ),
    "built for 32-bit ARM": (
        {"arm32": True},
        f"this library was built for 32-bit ARM, not this device (64-bit ARM (AArch64)): {FOR_DEVICE}",
    ),
    "a Linux library": (
        {"needed": ("libc.so.6",)},
        f"this library was built for Linux (it needs libc.so.6), not Android: {FOR_DEVICE}",
    ),
    "a Windows program": (
        {"windows": (0x8664, False)},
        f"is a Windows program for x86-64, {PICK}",
    ),
    "a Windows DLL": (
        {"windows": (0xAA64, True)},
        f"is a Windows library for 64-bit ARM (AArch64), {PICK}",
    ),
    "section names that do not end": (
        {"names_unended": True},
        "is damaged: its headers are not where it says",
    ),
}


@pytest.fixture(scope="module")
def libs(tmp_path_factory):
    """The good library and every mutant, built once for the tests below."""
    base = tmp_path_factory.mktemp("libs")
    out = {"good": build(base / "good")}
    for what, (kw, _) in MUTANTS.items():
        out[what] = make(base / what.replace(" ", "_").replace("'", ""), **kw)
    return out


@route
def test_the_library_is_what_the_phone_loads(libs):
    lib = libs["good"]
    assert check(lib) == []
    elf = elfcheck.read(lib)
    assert (elf.machine, elf.type, elf.soname) == (elfcheck.EM_AARCH64, 3, seam.GAME_SONAME)
    assert elf.load_aligns and all(a == 16384 for a in elf.load_aligns), elf.load_aligns
    assert seam.RUNTIME_SONAME in elf.needed and elf.record == GAME_RECORD
    # bionic's names, which the phone's runtime takes and nothing else
    assert set(elf.needed) <= {seam.RUNTIME_SONAME, *elfcheck.C_LIBRARIES}, elf.needed
    assert set(elf.exports) - {"_init", "_fini"} == {"soa_game"}
    assert ("irq_poll", False) in elf.imports


@route
def test_two_builds_are_the_same_bytes(tmp_path):
    a = build(tmp_path / "a").read_bytes()
    b = build(tmp_path / "b").read_bytes()
    assert a == b


@route
@pytest.mark.parametrize("what", sorted(MUTANTS))
def test_a_library_with_one_thing_wrong_draws_its_refusal(libs, what):
    found = check(libs[what])
    assert found and MUTANTS[what][1] in found[0], found


DRIVER = r"""
#include "elfcheck.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* argv: library, machine, record, the executable played ("-" for none),
 * android (0 or 1), then the export list and the C library's, separated by a
 * lone "--" */
int main(int argc, char** argv)
{
    ElfWant w;
    char why[700];
    int split = 6;
    while (split < argc && strcmp(argv[split], "--")) split++;
    w.machine = (unsigned short)atoi(argv[2]);
    w.record = argv[3];
    w.dol = strcmp(argv[4], "-") ? argv[4] : NULL;
    w.android = atoi(argv[5]);
    w.exports = (const char* const*)(argv + 6);
    w.nexports = (unsigned)(split - 6);
    w.libc = (const char* const*)(argv + split + 1);
    w.nlibc = (unsigned)(argc - split - 1);
    w.runtime_soname = "libsoa_runtime.so";
    if (elf_check(argv[1], &w, why, sizeof why) == 0) { puts("ok"); return 0; }
    puts(why);
    return 1;
}
"""


@pytest.fixture(scope="module")
def driver(tmp_path_factory):
    """runtime/elfcheck.c, built for this machine, as a program taking an
    ElfWant on its command line."""
    if toolchain.compiler_path(HOST) is None:
        pytest.skip(f"no {HOST.name} to build runtime/elfcheck.c for this machine")
    drv = tmp_path_factory.mktemp("driver")
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
    return exe


def c_says(exe: Path, lib: Path, want=PHONE) -> str:
    args = [
        str(exe),
        str(lib),
        str(want["machine"]),
        want["record"],
        want["dol"] or "-",
        "1" if want["android"] else "0",
        *want["exports"],
        "--",
        *want["libc"],
    ]
    return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout.strip()


def patched(lib: Path, data: bytes, old: bytes, new: bytes) -> Path:
    """data at lib with every `old` made `new`, of the same length, so nothing
    moves: the record in the note and in the table alike."""
    assert len(old) == len(new) and old in data
    lib.write_bytes(data.replace(old, new))
    return lib


@route
def test_the_phone_s_checker_agrees_with_the_pc_s(libs, driver, tmp_path):
    files = dict(libs)
    # and three files that are no library: too short, text, and a library
    # cut short, whose headers lie past its end
    files["short"] = tmp_path / "short.so"
    files["short"].write_bytes(b"\x7fELF" + bytes(40))
    files["text"] = tmp_path / "text.so"
    files["text"].write_bytes(b"this is not a library, only words about one\n" * 4)
    good = libs["good"].read_bytes()
    files["cut short"] = tmp_path / "cut.so"
    files["cut short"].write_bytes(good[:4096])
    # and a big-endian ELF for this machine, its e_machine read in its own
    # byte order: refused for its byte order, not as another machine
    files["big-endian"] = tmp_path / "big.so"
    files["big-endian"].write_bytes(
        b"\x7fELF\x02\x02\x01" + bytes(9) + struct.pack(">HH", 3, elfcheck.EM_AARCH64) + bytes(44)
    )
    # and records Setup never writes, as a damaged note might hold them, read
    # as elfcheck.c reads one: its fields apart by spaces alone, its first 511
    # bytes, made printable, each value's first 127
    zeros = b"baked=" + b"0" * 10
    files["a tab in its record"] = patched(tmp_path / "tab.so", good, b" mode=", b"\tmode=")
    files["a line break in its record"] = patched(
        tmp_path / "break.so", good, zeros, zeros[:-1] + b"\n"
    )
    files["a record past 511 bytes"] = build(
        tmp_path / "long", record=f"{RECORD} pad={'x' * 450} dol={DOL}"
    )
    long_mode = "no-decomp" + "x" * 200
    files["a value past 127 bytes"] = build(
        tmp_path / "wide", record=GAME_RECORD.replace("mode=no-decomp", f"mode={long_mode}")
    )
    files["a field's name alone"] = build(
        tmp_path / "alone", record=GAME_RECORD.replace(" mode=", " mode mode=")
    )
    said = {}
    for what, lib in files.items():
        for setting, want in SETTINGS.items():
            pc = elfcheck.verdict(lib, **want)
            assert c_says(driver, lib, want) == pc, (what, setting, pc)
            said[what, setting] = pc
    assert said["big-endian", "phone"].endswith("is not a 64-bit library for this system")
    releases = "this game library and this app come from different releases"
    assert said["a tab in its record", "phone"] == (
        f"{releases} (its abi is 1?mode=no-decomp, the app's 1): {SAME_RELEASE}"
    )
    assert said["a line break in its record", "phone"] == (
        f"{releases} (its build is 000000000?00, the app's 000000000000): {SAME_RELEASE}"
    )
    assert said["a record past 511 bytes", "phone"] == MUTANTS["no executable named"][1]
    assert said["a value past 127 bytes", "phone"] == (
        f"{releases} (its mode is {long_mode[:127]}, the app's no-decomp): {SAME_RELEASE}"
    )
    assert said["a field's name alone", "phone"] == "ok"
    # the settings differ where they should, and nowhere else
    differ = {what for what in files if said[what, "phone"] != said[what, "desktop"]}
    assert differ == {"a Linux library"}
    assert said["a Linux library", "desktop"] == "ok"
    differ = {what for what in files if said[what, "phone"] != said[what, "no-dol"]}
    assert differ == {"another disc's executable", "no executable named", "a record past 511 bytes"}


@route
def test_the_mutants_a_device_is_given_each_draw_their_refusal(driver, tmp_path):
    """gamefixture.android_mutants for the x86_64 emulator, against an APK's
    record: each library wrong in its one way, refused in the words predicted
    for it, which are elfcheck.c's with the file shown by its name."""
    apk = seam.record(True, "2" * 64)
    found = gamefixture.android_mutants(tmp_path, toolchain.ANDROID_X86_64, apk, DOL)
    contract = {"arm64", "pe-program", "pe-dll", "linux-libc6", "arm32", "pages-4k"}
    contract |= {"other-build", "other-dol", "missing-import"}
    assert contract <= set(found), sorted(found)
    want = {**PHONE, "machine": elfcheck.EM_X86_64, "record": apk}
    for key, (lib, words) in found.items():
        assert lib.name == f"{key}.so"
        assert c_says(driver, lib, want).replace(str(lib), lib.name) == words, key
    assert elfcheck.read(found["missing-import"][0]).record == f"{apk} dol={DOL}"
    assert found["missing-import"][1].startswith("this library needs hle_report, ")
    assert found["arm64"][1].startswith(
        "this library was built for 64-bit ARM (AArch64), not this device (x86-64)"
    )
    assert found["arm32"][1].startswith(
        "this library was built for 32-bit ARM, not this device (x86-64)"
    )
    assert found["pe-program"][1].startswith("pe-program.so is a Windows program for x86-64, ")
    assert found["pe-dll"][1].startswith("pe-dll.so is a Windows library for x86-64, ")
    assert found["linux-libc6"][1].startswith(
        "this library was built for Linux (it needs libc.so.6)"
    )
    assert found["pages-4k"][1].startswith("this library was built for 4096-byte pages")
    assert found["other-build"][1].startswith(
        "this game library and this app come from different releases (its build is "
    )
    assert found["other-dol"][1].startswith(
        "this game library was made from another disc's executable"
    )
    assert found["no-dol"][1].startswith("this game library does not say which disc's executable")


# ---- R5a part 2: the route's own decisions, needing no compiler -------------


def test_without_llvm_mingw_or_the_sysroot_the_build_says_where_it_looked(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain, "android_sysroot", lambda: None)
    monkeypatch.setenv("SOA_MINGW", str(tmp_path / "no-such-mingw"))
    assert toolchain.compiler_path(toolchain.ANDROID_X86_64) is None
    places = toolchain.android_places()
    exe = ".exe" if os.name == "nt" else ""
    assert places[0] == (
        f"SOA_MINGW ({tmp_path / 'no-such-mingw'}): no llvm-mingw there (no x86_64-w64-mingw32-clang{exe})"
    )
    assert places[-1].endswith(
        "android-sysroot: none (python tools/fetch_android_sysroot.py builds it)"
    )
    monkeypatch.delenv("SOA_MINGW")
    places = toolchain.android_places()
    assert places[0] == "SOA_MINGW (unset)" and len(places) == 4, places
    assert places[1].startswith(str(ROOT.parent / "toolchain" / "bin"))
    assert places[2].startswith(str(ROOT / "vendor" / "llvm-mingw" / "bin"))


def test_an_android_build_with_no_compiler_says_so_before_it_reads_anything(
    monkeypatch, tmp_path, capsys
):
    import recompile

    out = tmp_path / "gen"
    out.mkdir()
    (out / "build_inputs.txt").write_text(
        "dol_sha1 = x\nprofile = android-x86_64\ncompiler = another\n", encoding="utf-8"
    )
    dol = tmp_path / "main.dol"  # never read: the build stops before it
    monkeypatch.setenv("SOA_MINGW", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recompile.py",
            "--cc",
            "android-x86_64",
            "--link",
            "--dol",
            str(dol),
            "--no-embed",
            "--out",
            str(out),
        ],
    )
    assert recompile.main() == 1
    err = capsys.readouterr().err
    assert "android-x86_64: no compiler or no sysroot here, so nothing was built" in err
    assert "looked in, in order:" in err and "SOA_MINGW (" in err
    assert "stale link" not in err


def test_the_game_library_never_looks_for_an_ndk(monkeypatch, tmp_path):
    def no(*a, **k):
        raise AssertionError("the game library's lookup asked for an NDK")

    monkeypatch.setattr(toolchain, "android_ndk", no)
    exe = ".exe" if os.name == "nt" else ""
    for name in ("x86_64-w64-mingw32-clang", "clang"):
        (tmp_path / f"{name}{exe}").write_bytes(b"")
    monkeypatch.setenv("SOA_MINGW", str(tmp_path))
    monkeypatch.setattr(toolchain, "android_sysroot", lambda: tmp_path / "sysroot")
    for p in toolchain.ANDROID:
        assert toolchain.compiler_path(p) == str(tmp_path / f"clang{exe}")


def test_every_android_link_names_its_c_libraries_after_its_objects(tmp_path):
    import recompile

    plan = recompile.android_link_plan(toolchain.ANDROID_ARM64, tmp_path)
    stubs, stand_in, game = plan[:3], plan[3][0], plan[4][0]
    assert len(plan) == 5
    for (cmd, _), lib in zip(stubs, seam.C_LIBRARIES, strict=True):
        assert "-nostdlib" in cmd and f"-Wl,-soname,{lib}" in cmd
        assert cmd[cmd.index("-Xlinker") + 1].endswith(lib.removesuffix(".so") + ".vers")
        assert not any(a.startswith("-Wl,--version-script") for a in cmd)
    tail = ("-nodefaultlibs", "-lm", "-ldl", "-lc")
    for cmd in (stand_in, game):
        assert tuple(cmd[-4:]) == tail, cmd[-6:]
    assert f"-Wl,-soname,{seam.RUNTIME_SONAME}" in stand_in
    assert f"-Wl,-soname,{seam.GAME_SONAME}" in game
    objs = [i for i, a in enumerate(game) if a.endswith(".o") or a.endswith(".c")]
    assert max(objs) < game.index(f"-l:{seam.RUNTIME_SONAME}") < game.index("-nodefaultlibs")
    assert len(recompile.android_link_plan(toolchain.ANDROID_ARM64, tmp_path, stubs=False)) == 2


def test_the_stubs_are_seam_txt_s_in_bionic_s_places(tmp_path):
    names = seam.c_library_names(SEAM)
    assert names["libm.so"] == tuple(n for n in SEAM.libc if n in seam.BIONIC_LIBM)
    assert names["libc.so"] == tuple(n for n in SEAM.libc if n not in seam.BIONIC_LIBM)
    assert names["libdl.so"] == () and set(names["libc.so"]) | set(names["libm.so"]) == set(
        SEAM.libc
    )
    seam.write_android_stubs(tmp_path, SEAM, BOUND)
    assert (tmp_path / "libdl.vers").read_text(encoding="utf-8") == "LIBC {\n  local: *;\n};\n"
    libm = (tmp_path / "libm.vers").read_text(encoding="utf-8")
    assert libm.startswith("LIBC {\n  global:\n") and all(
        f"    {n};\n" in libm for n in names["libm.so"]
    )
    c = (tmp_path / "libc.c").read_text(encoding="utf-8")
    assert all(f"void {n}(void) {{}}" in c for n in names["libc.so"])
    assert (tmp_path / "stub_runtime.c").read_text(encoding="utf-8") == seam.stub_runtime_c(
        SEAM, BOUND
    )


def test_the_post_link_check_is_the_phone_s(monkeypatch, tmp_path):
    import dataclasses

    import recompile

    seen = {}
    monkeypatch.setattr(elfcheck, "read", lambda lib: "an elf")
    monkeypatch.setattr(elfcheck, "problems", lambda elf, **kw: seen.update(kw) or [])
    arm = dataclasses.replace(
        toolchain.ANDROID_ARM64, cflags=(*toolchain.ANDROID_ARM64.cflags, "-g")
    )
    assert recompile.post_link_problems(arm, tmp_path / "x.so", SEAM, BOUND, "0" * 64, DOL) == []
    assert seen["machine"] == elfcheck.EM_AARCH64 and seen["android"] is True and seen["dol"] == DOL
    assert seen["exports"] == seam.runtime_exports(SEAM, BOUND) and seen["libc"] == SEAM.libc
    assert seen["record"] == seam.record(True, "0" * 64)
    recompile.post_link_problems(
        toolchain.ANDROID_X86_64, tmp_path / "x.so", SEAM, BOUND, "0" * 64, DOL
    )
    assert seen["machine"] == elfcheck.EM_X86_64


def test_a_failed_compile_says_why_from_stderr(monkeypatch, tmp_path, capsys):
    import recompile

    def failed(args, cwd, p):
        return subprocess.CompletedProcess(args, 1, "", "x.c:1:1: error: boom\n")

    monkeypatch.setattr(toolchain, "cc", failed)
    unit = tmp_path / "chunk_000.c"
    unit.write_text("", encoding="utf-8")
    fails = recompile.compile_units(
        toolchain.ANDROID_X86_64, toolchain.ANDROID_X86_64, tmp_path, [unit], True, False
    )
    assert fails["chunk_000.c"] == 1
    assert "  FAIL chunk_000.c: x.c:1:1: error: boom" in capsys.readouterr().out


def test_the_android_link_steps_say_what_they_build(monkeypatch, tmp_path, capsys):
    import recompile

    monkeypatch.setattr(
        toolchain, "cc", lambda args, cwd, p: subprocess.CompletedProcess(args, 0, "", "")
    )
    plan = recompile.android_link_plan(toolchain.ANDROID_X86_64, tmp_path)
    assert (
        recompile.run_plan(
            plan, toolchain.ANDROID_X86_64, tmp_path, tmp_path / "soa", True, name_each=True
        )
        == 0
    )
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[build]")]
    assert lines == [
        "[build] stub libc.so",
        "[build] stub libm.so",
        "[build] stub libdl.so",
        "[build] stub libsoa_runtime.so",
        "[build] link",
    ]


def test_an_android_command_runs_without_clang_s_search_variables(monkeypatch):
    # what clang reads ahead of a sysroot, spelled out here, not taken from toolchain
    searched = (
        "COMPILER_PATH",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "OBJC_INCLUDE_PATH",
        "OBJCPLUS_INCLUDE_PATH",
        "LIBRARY_PATH",
        "CCC_OVERRIDE_OPTIONS",
    )
    for v in searched:
        monkeypatch.setenv(v, "poison")
    monkeypatch.setattr(toolchain, "compiler_path", lambda p: "clang")
    monkeypatch.setattr(toolchain, "android_sysroot", lambda: Path("sysroot"))
    envs = []
    monkeypatch.setattr(
        toolchain.subprocess,
        "run",
        lambda cmd, **kw: envs.append(kw.get("env")) or subprocess.CompletedProcess(cmd, 0, "", ""),
    )
    toolchain.cc(["/c", "a.c"], ".", toolchain.ANDROID_X86_64)
    assert envs[0] is not None and not set(searched) & {k.upper() for k in envs[0]}
    toolchain.cc(["/c", "a.c"], ".", toolchain.GCC)
    assert envs[1] is None  # only Android's commands are cleaned


# ---- R5a part 2: built through the route -----------------------------------


@route
def test_the_stubs_export_seam_txt_s_names_and_no_other(tmp_path, monkeypatch):
    monkeypatch.setattr(gamefixture, "_BUILT_STUBS", {})
    build(tmp_path / "g", toolchain.ANDROID_X86_64)
    names = seam.c_library_names(SEAM)
    for lib in seam.C_LIBRARIES:
        elf = elfcheck.read(tmp_path / "g" / "stub" / lib)
        assert elf.soname == lib
        assert set(elf.exports) == set(names[lib]), (lib, elf.exports)
        for name in names[lib]:
            assert f"{name}@@LIBC" in dyn_syms(tmp_path / "g" / "stub" / lib), (lib, name)
    game = dyn_syms(tmp_path / "g" / seam.GAME_SONAME)
    assert "irq_poll" in game and not any(
        f"{n}@" in game and f"{n}@LIBC" not in game for n in SEAM.libc
    )


@route
def test_a_call_outside_the_seam_fails_the_link(tmp_path):
    extra = "#include <string.h>\nunsigned long g3(const char* s) { return strlen(s); }\n"
    with pytest.raises(RuntimeError, match="undefined symbol: strlen"):
        build(tmp_path / "g", toolchain.ANDROID_X86_64, extra=extra)


@route
def test_the_post_link_check_refuses_a_linux_library(tmp_path):
    import recompile

    lib = build(tmp_path / "g", toolchain.ANDROID_X86_64, needed=("libc.so.6",))
    found = recompile.post_link_problems(toolchain.ANDROID_X86_64, lib, SEAM, BOUND, "0" * 64, DOL)
    assert found and "built for Linux (it needs libc.so.6)" in found[0], found


@route
def test_the_fixture_is_built_by_recompile_s_own_plan(tmp_path, monkeypatch):
    import recompile

    monkeypatch.setattr(gamefixture, "_BUILT_STUBS", {})
    calls = []
    real = recompile.android_link_plan

    def spy(p, out, **kw):
        calls.append((out, kw))
        return real(p, out, **kw)

    monkeypatch.setattr(recompile, "android_link_plan", spy)
    build(tmp_path / "a", toolchain.ANDROID_X86_64)
    build(tmp_path / "b", toolchain.ANDROID_X86_64)
    assert [c[1]["units"] for c in calls] == [
        [(tmp_path / "a").resolve() / "game.c"],
        [(tmp_path / "b").resolve() / "game.c"],
    ]
    assert [c[1]["stubs"] for c in calls] == [True, False]  # the second copies the first's
    assert (tmp_path / "b" / "stub" / "libc.so").read_bytes() == (
        tmp_path / "a" / "stub" / "libc.so"
    ).read_bytes()


@route
def test_a_folder_with_a_comma_and_a_space_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(gamefixture, "_BUILT_STUBS", {})
    lib = build(tmp_path / "Skies, the game", toolchain.ANDROID_ARM64)
    assert check(lib) == []


@route
def test_the_environment_cannot_reach_the_game_s_compile(tmp_path, monkeypatch):
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "math.h").write_text("#error poisoned\n", encoding="utf-8")
    (poison / "stdint.h").write_text("#error poisoned\n", encoding="utf-8")
    monkeypatch.setenv("CPATH", str(poison))
    monkeypatch.setenv("C_INCLUDE_PATH", str(poison))
    monkeypatch.setattr(gamefixture, "_BUILT_STUBS", {})
    assert check(build(tmp_path / "g")) == []


def dyn_syms(lib: Path) -> str:
    """llvm-readelf --dyn-syms of lib, llvm-mingw's own: each symbol with its version."""
    exe = Path(toolchain.mingw_clang()).with_name(
        "llvm-readelf" + (".exe" if os.name == "nt" else "")
    )
    return subprocess.run(
        [str(exe), "--dyn-syms", "-W", str(lib)], capture_output=True, text=True, check=True
    ).stdout


def test_the_game_library_needs_the_sysroot_as_well_as_llvm_mingw(monkeypatch, tmp_path):
    exe = ".exe" if os.name == "nt" else ""
    for name in ("x86_64-w64-mingw32-clang", "clang"):
        (tmp_path / f"{name}{exe}").write_bytes(b"")
    monkeypatch.setenv("SOA_MINGW", str(tmp_path))
    monkeypatch.setattr(toolchain, "android_sysroot", lambda: None)
    for p in toolchain.ANDROID:
        assert toolchain.compiler_path(p) is None


def test_recompile_refuses_another_clang_and_a_sysroot_not_as_recorded(
    monkeypatch, tmp_path, capsys
):
    import recompile

    exe = ".exe" if os.name == "nt" else ""
    for name in ("x86_64-w64-mingw32-clang", "clang"):
        (tmp_path / f"{name}{exe}").write_bytes(b"")
    monkeypatch.setenv("SOA_MINGW", str(tmp_path))
    monkeypatch.setattr(toolchain, "android_sysroot", lambda: tmp_path / "sysroot")
    argv = [
        "recompile.py",
        "--cc",
        "android-x86_64",
        "--link",
        "--dol",
        str(tmp_path / "no.dol"),
        "--no-embed",
        "--out",
        str(tmp_path / "gen"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(toolchain, "clang_id", lambda exe: "clang version 19.0.1 (https://x 0123)")
    assert recompile.main() == 1
    err = capsys.readouterr().err
    assert "clang version 19.0.1" in err and "fetch_mingw.py" in err
    version, commit = toolchain.MINGW_CLANG
    monkeypatch.setattr(
        toolchain,
        "clang_id",
        lambda exe: f"clang version {version} (https://github.com/llvm/llvm-project.git {commit})",
    )
    monkeypatch.setattr(
        recompile,
        "android_sysroot_problem",
        lambda vendor: (
            "vendor/android-sysroot is not as recorded (x): run python tools/fetch_android_sysroot.py"
        ),
    )
    assert recompile.main() == 1  # before the absent --dol is read
    assert "vendor/android-sysroot is not as recorded (x)" in capsys.readouterr().err


@route
def test_a_good_library_passes_the_post_link_check(tmp_path):
    import recompile

    baked = "0" * 64
    lib = build(
        tmp_path / "g",
        toolchain.ANDROID_X86_64,
        record=seam.record(True, baked, DOL, "android-x86_64"),
    )
    assert (
        recompile.post_link_problems(toolchain.ANDROID_X86_64, lib, SEAM, BOUND, baked, DOL) == []
    )


def test_a_fixture_folder_built_twice_or_a_dead_cache_entry_still_builds(monkeypatch, tmp_path):
    """gamefixture's stub reuse: a folder built again in place, and a cached
    folder since removed, each link their own stubs."""
    if toolchain.compiler_path(toolchain.ANDROID_X86_64) is None:
        pytest.skip(
            "no llvm-mingw or no Android sysroot (python tools/fetch_mingw.py, then python tools/fetch_android_sysroot.py)"
        )
    import shutil

    monkeypatch.setattr(gamefixture, "_BUILT_STUBS", {})
    build(tmp_path / "a", toolchain.ANDROID_X86_64)
    build(tmp_path / "a", toolchain.ANDROID_X86_64)  # in place: no copy onto itself
    shutil.rmtree(tmp_path / "a")
    assert (
        check(
            build(tmp_path / "b", toolchain.ANDROID_X86_64),
            {**PHONE, "machine": elfcheck.EM_X86_64},
        )
        == []
    )
