"""The player's package (specs/distribution.md R3): tools/package.py.

What a package may hold is guard.py --tree's to judge (test_guard.py); these
hold package.py to the same rules where it decides them: the licence texts it
copies come from the third-party folders the guard allows, the folders it
never copies are the decompiled code and every build output, and a stage
never lands on a folder that already holds something. Since R5-0 they also
hold what a package's build runs to what it carries, and a package's baked
inputs to the commit it was made from.
"""

import io
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import guard  # noqa: E402
import package  # noqa: E402
import player_build  # noqa: E402


def test_the_licences_come_from_the_third_party_folders():
    for rel in package.LICENSE_COPIES.values():
        assert guard.third_party(rel), rel


def test_a_package_never_copies_decompiled_code_or_build_output():
    assert {"src", "include", "gen", "extracted", "build"} <= package.NEVER


def test_the_pinned_downloads_are_named_by_exact_version():
    assert f"python-{package.PYTHON_VERSION}-embed-amd64.zip" == package.PYTHON_ZIP
    assert len(package.PYTHON_SHA256) == 64
    for url, pin in package.LICENSE_URLS.values():
        assert url.startswith("https://raw.githubusercontent.com/") and len(pin) == 64


def test_a_stage_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "keep.txt").write_text("the player's", encoding="utf-8")
    with pytest.raises(SystemExit, match="is not empty"):
        package.stage(tmp_path)
    assert (tmp_path / "keep.txt").exists()


# What a package's build runs: Setup.exe starts player_build.py, which starts
# recompile.py and imports extract to extract the disc; decomp, fetch_gpu,
# fetch_sdl and soa/ come in through those. The test imports these and every
# module TOOLS stages, so one imported only lazily is held too.
BUILD = ("player_build", "recompile", "extract")
EMBED = ROOT / "vendor" / package.PYTHON_ZIP

# Imports the build from the staged tools/, then names any module that came
# from anywhere but there and the interpreter's own library.
PROBE = """
import importlib, sys
from pathlib import Path
tools = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(tools))
for name in sys.argv[2:]:
    importlib.import_module(name)
home = Path(sys.base_prefix).resolve()
for name, mod in sorted(sys.modules.items()):
    f = getattr(mod, "__file__", None)
    if f is None:
        continue
    p = Path(f).resolve()
    if p.is_relative_to(tools) or (p.is_relative_to(home) and "site-packages" not in p.parts):
        continue
    sys.exit(f"{name} came from {p}, not the package")
print("imported from the stage:", *sys.argv[2:])
"""


def test_the_staged_tools_import_what_the_build_imports(tmp_path):
    """R5-0: what a package's source/tools/ holds is enough for its build.
    recompile.py has imported fetch_sdl at its top since L10, and TOOLS left
    it out until R5-0, so every package's build stopped there; with
    fetch_sdl.py taken out of TOOLS this fails, No module named 'fetch_sdl'.
    Run by the package's own python where vendor/ has it, else by this one
    without site-packages, which a package's python does not have."""
    source = tmp_path / "source"
    package.stage_source(source)
    python = sys.executable
    if sys.platform == "win32" and EMBED.exists():
        with zipfile.ZipFile(EMBED) as z:
            z.extractall(tmp_path / "python")
        python = str(tmp_path / "python" / "python.exe")
    names = [*BUILD, *(n[: -len(".py")] for n in package.TOOLS if n[: -len(".py")] not in BUILD)]
    run = subprocess.run(
        [python, "-I", "-S", "-c", PROBE, str(source / "tools"), *names],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"imported from the stage: {' '.join(names)}" in run.stdout


def test_a_package_s_baked_inputs_are_held_to_the_commit_s(tmp_path, capsys):
    """R5-0: package.py check holds a package's source/ to the baked inputs of
    the commit it was made from, which baked= in every soa.exe and
    libsoa_game.so it builds is made of. The commit's own files pass, and so
    do they with every line ending CRLF, as a checkout with core.autocrlf on
    writes them; a doubled CR, a changed byte, a file missing and one the
    commit lacks are each refused, by name."""
    head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True)
    if shutil.which("git") is None or head.returncode != 0:
        pytest.skip("no git checkout to read the commit from")
    pkg = tmp_path / "pkg"
    source = pkg / "source"
    tar = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", "HEAD", "--"]
        + list(player_build.BAKED),
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(source, filter="data")

    def check():
        code = package.check(pkg, "HEAD")
        return code, capsys.readouterr().out

    code, out = check()
    assert code == 0 and "the same" in out, out
    for f in source.rglob("*"):
        if f.is_file():
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    code, out = check()
    assert code == 0 and "the same" in out, out

    hle = source / "config" / "hle.txt"
    crlf = hle.read_bytes()
    hle.write_bytes(crlf.replace(b"\r\n", b"\r\r\n"))
    code, out = check()
    assert code == 1, out
    assert "config/hle.txt is not the commit's (the checkout converted its line endings?)" in out
    hle.write_bytes(crlf + b"#")
    code, out = check()
    assert code == 1 and out.rstrip().endswith("config/hle.txt is not the commit's"), out
    hle.write_bytes(crlf)

    dol = source / "tools" / "soa" / "dol.py"
    dol.rename(tmp_path / "dol.py")
    code, out = check()
    assert code == 1 and "tools/soa/dol.py is missing; the commit has it" in out, out
    (tmp_path / "dol.py").rename(dol)
    (source / "tools" / "soa" / "ppc" / "extra.py").write_text("", encoding="utf-8")
    code, out = check()
    assert code == 1 and "tools/soa/ppc/extra.py is not in the commit" in out, out

    assert package.check(tmp_path / "nothing") == 1
    assert "not a package" in capsys.readouterr().out


# ---- R5b: the phone's sysroot, built on the player's PC from what the package carries ----


def sysroot_cache(monkeypatch, root: Path) -> Path:
    """A vendor/ whose source cache holds a test table's build and ship files,
    the check files and a stray beside them, as a checkout's cache does."""
    import fetch_android_sysroot as fas

    files = {
        "libc/include/math.h": ("ship", b"/* math */\n"),
        "libc/arch-common/bionic/crtbegin_so.c": ("build", b"/* crt */\n"),
        "libc/libc.map.txt": ("check", b"LIBC { };\n"),
        "libc/kernel/uapi/linux/version.h": ("check", b"#define LINUX_VERSION_CODE 398080\n"),
    }
    rows = {
        p: fas.Source(
            len(d), role, None if role == "check" else "both", fas.sha256(d), fas.blob_id(d)
        )
        for p, (role, d) in files.items()
    }
    monkeypatch.setattr(fas, "SOURCES", rows)
    vendor = root / "vendor"
    for path, (_, data) in [*files.items(), (".build/x", (None, b"a stray"))]:
        f = vendor / fas.CACHE / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    for name in ("vulkan-headers", "glslang"):
        (vendor / name).mkdir()
        (vendor / name / "LICENSE.txt").write_text(name, encoding="utf-8")
    (vendor / package.fetch_gpu.RECORD).write_text("# gpu\n", encoding="utf-8")
    return vendor


def test_the_sources_are_staged_whole_and_alone(monkeypatch, tmp_path):
    """Exactly the build and ship files go under source/vendor/android-sysroot-src,
    libc/include/ kept (copy_tree drops it), never the check files or a stray:
    guard.py --tree passes them there, and refuses their include/ anywhere
    outside source/vendor."""
    vendor = sysroot_cache(monkeypatch, tmp_path)
    pkg = tmp_path / "pkg"
    package.stage_vendor(vendor, pkg / "source" / "vendor")
    staged = pkg / package.SYSROOT_SOURCES
    assert sorted(f.relative_to(staged).as_posix() for f in staged.rglob("*") if f.is_file()) == [
        "libc/arch-common/bionic/crtbegin_so.c",
        "libc/include/math.h",
    ]
    assert (pkg / "source" / "vendor" / "glslang" / "LICENSE.txt").is_file()
    assert guard.tree_problems(pkg) == []
    outside = tmp_path / "outside"
    shutil.copytree(staged, outside / "source" / "android-sysroot-src")
    assert any("include/" in p for p in guard.tree_problems(outside))


def test_a_stage_refuses_sources_off_their_pins_before_writing(monkeypatch, tmp_path):
    vendor = sysroot_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(package, "VENDOR", vendor)
    monkeypatch.setattr(package.fetch_mingw, "verify", lambda v: [])
    monkeypatch.setattr(package.fetch_gpu, "verify", lambda v: [])
    (vendor / "android-sysroot-src" / "libc/include/math.h").write_bytes(b"/* m */\n")
    dest = tmp_path / "pkg"
    with pytest.raises(SystemExit, match=r"android-sysroot-src/libc/include/math\.h: sha256 "):
        package.stage(dest, "v1")
    assert not dest.exists()


def test_the_package_says_its_version(tmp_path):
    package.stage_source(tmp_path / "source", "v1.0-4-gabc1234")
    assert (tmp_path / "source" / "VERSION").read_bytes() == b"v1.0-4-gabc1234\n"
    assert player_build.package_version(tmp_path / "source") == "v1.0-4-gabc1234"
    package.stage_source(tmp_path / "two")  # version() when none is given
    assert (tmp_path / "two" / "VERSION").read_text(encoding="utf-8") == package.version() + "\n"


def test_check_holds_the_version_to_the_package_s_name(tmp_path, capsys):
    """A package named soa-<ver>-windows-x64 must say <ver> in VERSION, which
    every Android library it builds carries as package=; one named otherwise
    is not held to it."""
    pkg = tmp_path / "soa-v2-windows-x64"
    (pkg / "source").mkdir(parents=True)
    (pkg / "source" / "VERSION").write_text("v1\n", encoding="utf-8")
    assert package.check(pkg) == 1
    assert "VERSION says 'v1', and the package is named for 'v2'" in capsys.readouterr().out


def test_the_kernel_s_licence_texts_are_at_the_headers_version():
    """The Linux headers in the sysroot were generated from the kernel bionic's
    pinned linux/version.h names; the GPL-2.0 and syscall note shipped beside
    them are that kernel's. A new bionic commit with newer headers fails here."""
    import re

    import fetch_android_sysroot as fas

    version_h = ROOT / "vendor" / fas.CACHE / "libc/kernel/uapi/linux/version.h"
    if not version_h.is_file():
        pytest.skip("no source cache (python tools/fetch_android_sysroot.py --lists fetches it)")
    assert fas.held("libc/kernel/uapi/linux/version.h", version_h.read_bytes()) is None
    code = int(re.search(r"LINUX_VERSION_CODE (\d+)", version_h.read_text()).group(1))
    major, minor = code >> 16, (code >> 8) & 0xFF
    assert f"v{major}.{minor}" == package.LINUX_TAG
    for name in ("linux-gpl-2.0.txt", "linux-syscall-note.txt"):
        url, pin = package.LICENSE_URLS[name]
        assert f"/torvalds/linux/v{major}.{minor}/LICENSES/" in url and len(pin) == 64


def test_the_apache_text_the_notice_names_is_in_llvm_txt():
    """NOTICE.txt sends the reader to licenses/llvm.txt for the Apache License
    2.0: its first part must be that text, before LLVM's exceptions."""
    import fetch_android_sysroot as fas

    lic = ROOT / "vendor" / "llvm-mingw" / "LICENSE.TXT"
    if not lic.is_file():
        pytest.skip("no vendor/llvm-mingw (python tools/fetch_mingw.py)")
    assert package.LICENSE_COPIES["llvm.txt"] == "toolchain/LICENSE.TXT"
    assert "licenses/llvm.txt" in fas.NOTICE_PREFACE
    text = lic.read_text(encoding="utf-8")
    start = text.index("Apache License")
    assert text.index("Version 2.0, January 2004") > start
    end = text.index("END OF TERMS AND CONDITIONS")
    assert start < end < text.index("LLVM Exceptions to the Apache 2.0 License")


def test_the_deepest_floor_covers_the_build_s_own_outputs(tmp_path):
    import fetch_android_sysroot as fas

    assert package.BUILD_DEEPEST >= 52
    assert len("source/vendor/") + fas.longest_written() <= package.BUILD_DEEPEST
    assert package.BUILD_DEEPEST == 87
    assert package.deepest(tmp_path) == package.BUILD_DEEPEST  # an empty folder
