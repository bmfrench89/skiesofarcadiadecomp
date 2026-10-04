"""soa.exe built with no Microsoft compiler (specs/distribution.md R1).

tools/fetch_mingw.py pins llvm-mingw and records every file it keeps: a file
changed by one byte, or missing, fails --verify. The mingw profile's flags,
libraries and stack are the spec's, and its plan writes only under gen/mingw,
the mods' mod.dll under gen/mingw/mods, never beside the msvc build's. With
vendor/llvm-mingw and the disc's executable, the whole build runs with
msvc_env made to raise -- so nothing of Microsoft's is touched -- and the exe
it makes imports no fma, exp2f or log2f from a C runtime DLL: the guest's
math stays inside it (3.3). Those skip, saying why, without them.
"""

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_mingw  # noqa: E402
import recompile  # noqa: E402
from soa import toolchain  # noqa: E402

MINGW_FLAGS = ["-std=c17", "-O2", "-ffp-contract=off", "-fno-strict-aliasing", "-fwrapv", "-Wall"]
LIBS = ["user32", "gdi32", "xinput9_1_0", "d3d11", "dxgi", "dxguid", "dwmapi", "winmm", "dbghelp"]


def test_the_fetch_keeps_the_x86_64_target_alone():
    keep = fetch_mingw.kept
    assert keep(PurePosixPath("bin/x86_64-w64-mingw32-clang.exe"))
    assert keep(PurePosixPath("x86_64-w64-mingw32/lib/libucrt.a"))
    assert keep(PurePosixPath("include/stdio.h"))
    for gone in (
        "aarch64-w64-mingw32/lib/libucrt.a",
        "i686-w64-mingw32/bin/libc++.dll",
        "python/bin/python3.exe",
        "bin/lldb.exe",
        "bin/clangd.exe",
        "bin/armv7-w64-mingw32-clang.exe",
    ):
        assert not keep(PurePosixPath(gone)), gone


def test_verify_finds_a_changed_byte_and_a_missing_file(tmp_path):
    vendor = tmp_path / "vendor"
    files = {}
    for name, text in (("llvm-mingw/bin/a.exe", b"abc"), ("llvm-mingw/include/b.h", b"xyz")):
        p = vendor / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text)
        files[name] = fetch_mingw.entry_digest(p)
    fetch_mingw.write_record(vendor / fetch_mingw.RECORD, files, "# test")
    assert fetch_mingw.verify(vendor) == []
    (vendor / "llvm-mingw/bin/a.exe").write_bytes(b"abd")
    (vendor / "llvm-mingw/include/b.h").unlink()
    assert fetch_mingw.verify(vendor) == [
        "llvm-mingw/bin/a.exe: differs from the record",
        "llvm-mingw/include/b.h: recorded but missing",
    ]
    assert fetch_mingw.verify(tmp_path / "none")[0].startswith("no ")


def test_the_linux_archive_unpacks_files_and_links_and_skips_the_rest(tmp_path):
    """CI's path: the Ubuntu-hosted tar.xz, its top folder stripped, kept
    files with their modes, links as links (where this OS makes them), and
    the other targets left out."""
    import io
    import lzma
    import tarfile

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as t:
        for name, data, mode in (
            ("top/bin/clang-target-wrapper.sh", b"#!/bin/sh\n", 0o755),
            ("top/include/stdio.h", b"/* h */\n", 0o644),
            ("top/aarch64-w64-mingw32/lib/x.a", b"arm", 0o644),
        ):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("top/bin/x86_64-w64-mingw32-clang")
        link.type, link.linkname = tarfile.SYMTYPE, "clang-target-wrapper.sh"
        t.addfile(link)
    blob = lzma.compress(raw.getvalue())
    dest = tmp_path / "llvm-mingw"
    try:
        out = fetch_mingw.unpack(blob, "x.tar.xz", dest)
    except OSError as exc:  # no symbolic links without Windows' developer mode
        pytest.skip(f"this OS made no symbolic link: {exc}")
    names = sorted(p.relative_to(dest).as_posix() for p in out)
    assert names == [
        "bin/clang-target-wrapper.sh",
        "bin/x86_64-w64-mingw32-clang",
        "include/stdio.h",
    ]
    assert (
        fetch_mingw.entry_digest(dest / "bin/x86_64-w64-mingw32-clang")
        == "link:clang-target-wrapper.sh"
    )
    assert (dest / "include/stdio.h").read_bytes() == b"/* h */\n"
    if os.name != "nt":
        assert (dest / "bin/clang-target-wrapper.sh").stat().st_mode & 0o111


def test_the_mingw_profile_is_the_spec_s():
    p = toolchain.profile("mingw")
    assert (p.style, list(p.cflags), p.out, p.exeext) == ("gnu", MINGW_FLAGS, "gen/mingw", ".exe")
    assert list(p.linker) == [f"-l{lib}" for lib in LIBS] + [
        "-lsynchronization",
        "-Wl,--stack,33554432",
    ]


def test_soa_mingw_naming_no_compiler_finds_none(monkeypatch, tmp_path):
    monkeypatch.setenv("SOA_MINGW", str(tmp_path))
    assert toolchain.compiler_path(toolchain.MINGW) is None
    monkeypatch.delenv("SOA_MINGW")
    assert toolchain.mingw_bins()[-1] == ROOT / "vendor" / "llvm-mingw" / "bin"


def test_the_mingw_plan_writes_only_under_gen_mingw():
    out = Path("gen/mingw")
    plan = recompile.link_plan(toolchain.MINGW, out, [], [], gxv=True)
    link, cwd = plan[0]
    assert cwd == Path(".") and "/link" not in link
    assert link[: len(MINGW_FLAGS)] == MINGW_FLAGS
    assert f"/Fe{out / 'soa.exe'}" in link and f"-Wl,--pdb={out / 'soa.pdb'}" in link
    last_input = max(i for i, a in enumerate(link) if a.endswith((".c", ".o")))
    assert last_input < link.index("-luser32") < link.index("-Wl,--stack,33554432")
    mods = plan[1:]
    assert len(mods) == len(recompile.mod_dll_sources())
    home = (out / "mods").resolve()
    for cmd, where in mods:
        assert where.parent == home and cmd[-1] == f"/Fe{where / 'mod.dll'}"
        assert "-shared" in cmd
    # the msvc plan, by contrast, writes each mod.dll beside its mod.c
    msvc = recompile.link_plan(toolchain.MSVC, Path("gen"), [], [])
    assert all(where != Path(".") and (where / "mod.c").exists() for _, where in msvc[1:])


BOOM = """
import sys
sys.path.insert(0, {tools!r})
from soa import toolchain

def boom():
    raise RuntimeError("msvc_env was asked for in a mingw build")

toolchain.msvc_env = boom
import recompile
sys.argv = ["recompile.py", "--cc", "mingw", "--compile", "--optimize", "--link"]
raise SystemExit(recompile.main())
"""


def test_the_whole_build_needs_nothing_of_microsoft_s_and_keeps_its_math():
    if toolchain.compiler_path(toolchain.MINGW) is None:
        pytest.skip("no llvm-mingw (python tools/fetch_mingw.py)")
    if not (ROOT / "extracted" / "sys" / "main.dol").exists():
        pytest.skip("no extracted/sys/main.dol to translate")
    proc = subprocess.run(
        [sys.executable, "-c", BOOM.format(tools=str(ROOT / "tools"))],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]
    assert "linked gen" in proc.stdout and "msvc_env was asked for" not in proc.stderr
    readobj = Path(toolchain.compiler_path(toolchain.MINGW)).parent / (
        "llvm-readobj" + (".exe" if os.name == "nt" else "")
    )
    imports = subprocess.run(
        [str(readobj), "--coff-imports", str(ROOT / "gen" / "mingw" / "soa.exe")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    symbols = {
        ln.split("Symbol: ")[1].split(" ")[0] for ln in imports.splitlines() if "Symbol: " in ln
    }
    assert {"fma", "exp2f", "log2f"} & symbols == set(), sorted(symbols)
    assert "CloseHandle" in symbols  # the table was read
