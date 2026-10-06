"""Small game libraries, built as tools/recompile.py builds the real one for an
Android profile (specs/android.md L12b, L12d): a game of two functions with
its table and record, linked against a stand-in runtime library, 16 KB pages,
every function hidden but the table; or the same with one thing wrong; and
the Windows files a player might copy over by mistake, made here from nothing,
since .exe and .dll files are refused in this repository (tools/guard.py).

    from soa import gamefixture
    gamefixture.build(d, toolchain.ANDROID_ARM64, record=...)
    gamefixture.android_mutants(out, "android-x86_64", apk_record, dol)

tools/tests/test_android_build.py holds runtime/elfcheck.c and its Python
twin, tools/soa/elfcheck.py, to them; android_mutants() is the set a device
is given to refuse (tools/android.py), each with the words the phone must
give. Nothing in them is game data: the game is two functions, and the
system files are not built in.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
from pathlib import Path

from soa import elfcheck, embed, seam, toolchain

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
SEAM = seam.read_seam(ROOT / "config" / "seam.txt")
BOUND = {0x80232E38}  # one binding the runtime answers, as hle.txt's do
# The NDK's clang builds for every Android target: this one makes a 32-bit
# ARM library, as an old armeabi-v7a build would be.
ARM32 = "--target=armv7a-linux-androideabi33"
MACHINES = {
    toolchain.ANDROID_ARM64.name: elfcheck.EM_AARCH64,
    toolchain.ANDROID_X86_64.name: elfcheck.EM_X86_64,
}


def _cc(p: toolchain.Profile, args: list[str], cwd: Path) -> None:
    proc = toolchain.cc(args, cwd, p)
    if proc.returncode != 0:
        raise RuntimeError((proc.stdout or "") + (proc.stderr or ""))


def functions_h() -> str:
    """The stand-in for <out>/functions.h, which declares every translated
    function: here the entry and each twin's body."""
    names = ["fn_80003140", *(seam.body_name(a, BOUND) for a in SEAM.twins)]
    return '#include "cpu.h"\n' + "".join(f"void {n}(CpuState* s);\n" for n in names)


def game_c(extra: str = "") -> str:
    """A game of two functions -- the entry, which calls the runtime and
    nothing of the C library's, and the binding's twin -- with dispatch, and
    every other twin the table names; `extra` C after them."""
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
    p: toolchain.Profile = toolchain.ANDROID_ARM64,
    *,
    record: str,
    extra: str = "",
    page: int = 16384,
    flags: tuple[str, ...] = (),
    undefined: bool = False,
    target: str = "",
    needed: tuple[str, ...] = (),
) -> Path:
    """libsoa_game.so in d, as recompile.py's android_link_plan makes it, with
    `record` in its table and note; or with one thing wrong: `extra` C beside
    the game, `page` as its max-page-size, `flags` on its compile and link,
    an import left `undefined`, another `target` for it and its stand-in
    runtime, or each name in `needed` added to its DT_NEEDED (an empty
    library with that soname, linked first, and kept though nothing in it is
    called)."""
    d = Path(d).resolve()  # the compiler runs in d, so every path it is given is whole
    stub = d / "stub"
    stub.mkdir(parents=True, exist_ok=True)
    over = [target] if target else []
    (stub / "stub_runtime.c").write_text(seam.stub_runtime_c(SEAM, BOUND), encoding="utf-8")
    _cc(
        p,
        [
            *p.cflags,
            *over,
            "-fvisibility=default",
            "-shared",
            f"/Fe{stub / seam.RUNTIME_SONAME}",
            str(stub / "stub_runtime.c"),
            f"-Wl,-soname,{seam.RUNTIME_SONAME}",
        ],
        d,
    )
    named = []
    for name in needed:
        (stub / "empty.c").write_text("/* a library by its name alone */\n", encoding="utf-8")
        _cc(
            p,
            [
                *p.cflags,
                *over,
                "-shared",
                f"/Fe{stub / name}",
                str(stub / "empty.c"),
                f"-Wl,-soname,{name}",
            ],
            d,
        )
        named.append(str(stub / name))
    (d / "functions.h").write_text(functions_h(), encoding="utf-8")
    (d / "game.c").write_text(game_c(extra), encoding="utf-8")
    (d / "disc_sys.c").write_text(embed.disc_sys_c(None), encoding="utf-8")
    (d / "game_table.c").write_text(
        seam.game_table_c(SEAM, BOUND, [0x80003140, *SEAM.twins], record), encoding="utf-8"
    )
    _cc(
        p,
        [
            *p.cflags,
            *over,
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
            *(["-Wl,--no-as-needed", *named] if named else []),
            f"-L{stub}",
            f"-l:{seam.RUNTIME_SONAME}",
            *p.linker,
        ],
        d,
    )
    return d / seam.GAME_SONAME


def windows_file(machine: int = 0x8664, dll: bool = False) -> bytes:
    """A Windows file's headers, as a PE begins: "MZ" with e_lfanew, then
    "PE\\0\\0", the COFF header (its machine, and whether it is a DLL) and a
    PE32+ optional header; no sections, padded to 512 bytes. Enough for
    elfcheck to know it, and made here, never committed."""
    lfanew = 0x80
    dos = bytearray(lfanew)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, lfanew)
    # an executable image, large-address-aware, and a DLL when it is one
    chars = 0x0002 | 0x0020 | (elfcheck.PE_DLL if dll else 0)
    coff = struct.pack("<4sHHIIIHH", b"PE\0\0", machine, 0, 0, 0, 0, 240, chars)
    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)  # PE32+
    data = bytes(dos) + coff + bytes(optional)
    return data + bytes(-len(data) % 512)


def _with(record: str, key: str, value: str) -> str:
    """`record` with `key`'s value replaced."""
    parts = record.split()
    for i, part in enumerate(parts):
        if part.partition("=")[0] == key:
            parts[i] = f"{key}={value}"
            return " ".join(parts)
    raise ValueError(f"no {key}= in the record {record!r}")


def _another_build() -> str:
    """The baked digest of this tree with another runtime/cpu.h: a library
    from another release (player_build.BAKED)."""
    import player_build  # tools/, beside recompile.py

    inputs = player_build.inputs_record(ROOT)
    inputs["runtime/cpu.h"] = hashlib.sha256(b"another runtime/cpu.h").hexdigest()
    return seam.baked_digest(inputs)


def android_mutants(
    out: Path, profile: toolchain.Profile | str, record: str, dol: str
) -> dict[str, tuple[Path, str]]:
    """Small game libraries built as recompile.py builds the real one for
    `profile` (android-x86_64 or android-arm64), each wrong in one way, and
    the first refusal tools/soa/elfcheck.problems predicts for each against
    `record` and `dol` (the APK's: its runtime record, which has no dol=, and
    the executable its runtime plays). Keys:

    - 'arm64', another machine: built for 64-bit ARM ('x86_64', built for
      x86-64, when the profile is android-arm64);
    - 'pe-program' and 'pe-dll', Windows files for x86-64;
    - 'linux-libc6', needing glibc's libc.so.6 as a Linux library does;
    - 'arm32', a 32-bit ARM library;
    - 'pages-4k', laid out for 4 KB pages;
    - 'other-build', from another release (another baked: this tree's with
      another runtime/cpu.h);
    - 'other-dol', made from another disc's executable;
    - 'no-dol', saying nothing of its executable;
    - 'missing-import', the APK's exact record and dol, one unlisted import.

    Every ELF one but 'other-build', 'other-dol' and 'no-dol' carries the
    APK's record plus dol=, so it is wrong in its one way alone. Each is
    out/<key>.so, and its words name it so, as the phone shows a picked file
    by its display name. A mutant the phone would accept is an error here.

    The words are for a file the phone reads whole, as the test provider's
    file/ hands one over. A stream (its pipe/) is checked while it is copied,
    from its first bytes, and its refusal is the same words after "the copy
    was stopped after <n> of <size> bytes: ": runtime/android.c lets a Windows
    file's copy run on to the header that names it, which sits past the first
    64 bytes, before it asks."""
    p = toolchain.profile(profile) if isinstance(profile, str) else profile
    if p not in toolchain.ANDROID:
        raise ValueError(f"{p.name} is not an Android profile")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    made = out / "made"
    mine = f"{record} dol={dol}"
    if p is toolchain.ANDROID_ARM64:
        other_machine = ("x86_64", {"p": toolchain.ANDROID_X86_64})
    else:
        other_machine = ("arm64", {"p": toolchain.ANDROID_ARM64})
    recipes: dict[str, dict] = {
        other_machine[0]: {"record": mine, **other_machine[1]},
        "linux-libc6": {"record": mine, "needed": ("libc.so.6",)},
        "arm32": {"record": mine, "target": ARM32},
        "pages-4k": {"record": mine, "page": 4096},
        "other-build": {"record": f"{_with(record, 'baked', _another_build())} dol={dol}"},
        "other-dol": {
            "record": f"{record} dol={hashlib.sha1(b'another disc', usedforsecurity=False).hexdigest()}"
        },
        "no-dol": {"record": record},
        "missing-import": {
            "record": mine,
            "extra": "void hle_report(void);\nvoid g2(void) { hle_report(); }\n",
            "undefined": True,
        },
    }
    found: dict[str, tuple[Path, str]] = {}
    for key, kw in recipes.items():
        kw = {"p": p, **kw}
        lib = out / f"{key}.so"
        shutil.copyfile(build(made / key, **kw), lib)
        found[key] = (lib, "")
    for key, dll in (("pe-program", False), ("pe-dll", True)):
        lib = out / f"{key}.so"
        lib.write_bytes(windows_file(0x8664, dll))
        found[key] = (lib, "")
    for key, (lib, _) in found.items():
        # The stand-in runtime's exports, not the APK's: these libraries import
        # only seam.txt's runtime names, which every runtime exports, and the C
        # library's, so the words are the same either way.
        said = elfcheck.verdict(
            lib,
            machine=MACHINES[p.name],
            exports=seam.runtime_exports(SEAM, BOUND),
            libc=SEAM.libc,
            record=record,
            dol=dol,
            android=True,
            name=lib.name,
        )
        if said == "ok":
            raise RuntimeError(f"{lib}: the phone's checks would accept it, so it tests nothing")
        found[key] = (lib, said)
    return dict(sorted(found.items()))
