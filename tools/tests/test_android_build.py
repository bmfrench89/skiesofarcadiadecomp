"""The game library from the PC, for Android (specs/android.md L12b, L12d).

recompile.py --cc android-arm64 builds libsoa_game.so with the NDK's clang
against a stand-in runtime library, and tools/soa/elfcheck.py, the Python twin
of runtime/elfcheck.c, checks it as the phone would before saying the build
is done. With an NDK here (tools/soa/toolchain.py android_ndk), a game of two
functions is built the way recompile.py builds the real one
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

Everything skips, saying why, without an NDK; the C half without a compiler
for this machine.
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
ndk = pytest.mark.skipif(
    toolchain.compiler_path(toolchain.ANDROID_ARM64) is None,
    reason="no Android NDK (SOA_ANDROID_NDK, ANDROID_NDK_HOME, or an SDK's ndk/)",
)
# What the phone's runtime holds a library to; a desktop split build's
# runtime holds it to the same executable (runtime/game.c names one in every
# build) and takes glibc's C libraries too; recompile.py's check after linking
# takes either and names no executable.
PHONE = {
    "machine": elfcheck.EM_AARCH64,
    "exports": seam.runtime_exports(SEAM, BOUND),
    "libc": SEAM.libc,
    "record": RECORD,
    "dol": DOL,
    "android": True,
}
DESKTOP = {**PHONE, "android": False}
POST_LINK = {**PHONE, "dol": None, "android": False}
SETTINGS = {"phone": PHONE, "desktop": DESKTOP, "post-link": POST_LINK}


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


def make(d: Path, *, windows=None, names_unended=False, **kw) -> Path:
    """A library by build()'s keywords; a Windows file for `windows`, its
    (machine, dll); or a library whose section-name table does not end."""
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
        {"target": gamefixture.ARM32},
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


@ndk
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


@ndk
def test_two_builds_are_the_same_bytes(tmp_path):
    a = build(tmp_path / "a").read_bytes()
    b = build(tmp_path / "b").read_bytes()
    assert a == b


@ndk
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


@ndk
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
    differ = {what for what in files if said[what, "desktop"] != said[what, "post-link"]}
    assert differ == {"another disc's executable", "no executable named", "a record past 511 bytes"}


@ndk
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
