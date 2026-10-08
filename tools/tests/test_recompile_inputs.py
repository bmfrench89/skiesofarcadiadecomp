"""What recompile.py builds into soa.exe, and the stale-link guard (disc-layer I3).

No MSVC and no DOL: the build-input record is two pure functions over a
temporary folder, never the real gen/ and never main(); the system files come
from tools/soa/discfixture.py's synthetic image; and the C embed.py writes is
read back here into the bytes it stands for.
"""

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import recompile  # noqa: E402
from soa import discfixture, embed, toolchain  # noqa: E402

A = "8c0e278126fa3b0173400fdb632038172743cc13"
B = A[:-1] + "4"  # one hex digit apart


def test_the_same_executable_passes_and_another_is_refused(tmp_path):
    recompile.write_build_inputs(tmp_path, A, "msvc")
    assert recompile.check_build_inputs(tmp_path, A) is None
    why = recompile.check_build_inputs(tmp_path, B)
    assert why and A in why and B in why and "--compile" in why
    assert recompile.build_inputs_note(tmp_path) is None
    assert recompile.read_build_inputs(tmp_path) == {"dol_sha1": A, "profile": "msvc"}


def test_a_folder_with_no_record_passes_once_with_a_note(tmp_path):
    assert recompile.check_build_inputs(tmp_path, A) is None
    note = recompile.build_inputs_note(tmp_path)
    assert note and recompile.BUILD_INPUTS in note and "next --compile" in note


def unwords(c: str, sym: str) -> bytes:
    """The bytes a disc_sys.c array stands for, cut to its size."""
    body = re.search(rf"const uint32_t disc_sys_{sym}\[\d+\] = \{{(.*?)\}};", c, re.S).group(1)
    data = b"".join(int(w, 16).to_bytes(4, "little") for w in re.findall(r"0x([0-9A-F]{8})u", body))
    size = int(re.search(rf"const size_t disc_sys_{sym}_size = (\d+)u;", c).group(1))
    return data[:size]


def test_the_embedded_words_are_the_files_bytes(tmp_path):
    fx = discfixture.build(tmp_path / "disc.iso")
    c = embed.disc_sys_c(fx.system)
    assert c.startswith("/* " + embed.MARKER)
    for sym, name in embed.PARTS:
        assert unwords(c, sym) == fx.system[name], name
        digest = hashlib.sha1(fx.system[name]).hexdigest()
        assert f'const char disc_sys_{sym}_sha1[] = "{digest}";' in c
    assert embed.words(b"\x01\x02\x03\x04\x05") == [0x04030201, 0x00000005]  # little-endian, padded


def test_no_embed_has_the_same_symbols_and_nothing_in_them():
    c = embed.disc_sys_c(None)
    assert embed.MARKER not in c
    for sym, _ in embed.PARTS:
        assert f"const uint32_t disc_sys_{sym}[1] = {{" in c
        assert f"const size_t disc_sys_{sym}_size = 0u;" in c
        assert f'const char disc_sys_{sym}_sha1[] = "";' in c


def test_the_system_files_come_from_the_disc_and_are_held_to_config_and_dol(tmp_path):
    fx = discfixture.build(tmp_path / "data" / "disc.iso")
    dol = fx.system["main.dol"]
    files, why = recompile.system_files(tmp_path / "data", dol, fx.dol_sha1, force=False)
    assert why is None
    for _, name in embed.PARTS:  # the very slices the fixture placed
        assert files[name] == fx.system[name], name
    files, why = recompile.system_files(tmp_path / "data", dol, B, force=False)
    assert files is None and "not config/'s" in why
    files, why = recompile.system_files(tmp_path / "data", dol + b"\0", fx.dol_sha1, force=False)
    assert files is None and "not --dol's" in why
    files, why = recompile.system_files(tmp_path / "data", dol + b"\0", B, force=True)
    assert why is None and files["main.dol"] == dol
    files, why = recompile.system_files(tmp_path / "nothing", dol, fx.dol_sha1, force=False)
    assert files is None and why


def test_the_link_compiles_disc_sys_beside_the_runtime():
    out = Path("gen")
    for p in (recompile.toolchain.MSVC, recompile.toolchain.MINGW):
        link = recompile.link_plan(p, Path(p.out) if p.name != "msvc" else out, [], [])[0][0]
        assert any(a.endswith("disc_sys.c") for a in link), p.name


# ---- R5a part 2: the compiler, its flags and the sysroot --------------------

CLANG = "clang version 23.1.2 (https://github.com/llvm/llvm-project.git 85ac5602)"


def test_a_link_of_objects_another_compiler_flags_or_sysroot_made_is_refused(tmp_path):
    rec = {"compiler": CLANG, "cflags": "f" * 64, "sysroot": "s" * 64}
    recompile.write_build_inputs(tmp_path, A, "android-x86_64", **rec)
    assert recompile.check_build_inputs(tmp_path, A, **rec, strict=True) is None
    other = recompile.check_build_inputs(
        tmp_path, A, **{**rec, "compiler": "clang version 19"}, strict=True
    )
    assert (
        other and "compiled by" in other and "clang version 19" in other and "stale link" in other
    )
    flags = recompile.check_build_inputs(
        tmp_path, A, **{**rec, "cflags": "0" * 64}, strict=True, profile="android-x86_64"
    )
    assert flags and "other flags than android-x86_64's" in flags
    root = recompile.check_build_inputs(tmp_path, A, **{**rec, "sysroot": "t" * 64}, strict=True)
    assert root and "ssssssssssss" in root and "tttttttttttt" in root
    # an Android record without the fields, and an Android folder with none
    recompile.write_build_inputs(tmp_path, A, "android-x86_64")
    old = recompile.check_build_inputs(tmp_path, A, **rec, strict=True)
    assert old and "before build_inputs.txt named their compiler, flags and sysroot" in old
    none = recompile.check_build_inputs(tmp_path / "nothing", A, **rec, strict=True)
    assert none and "has no build_inputs.txt" in none
    # a mingw record that names no compiler passes, with a note
    recompile.write_build_inputs(tmp_path, A, "mingw")
    assert recompile.check_build_inputs(tmp_path, A, compiler=CLANG, cflags="f" * 64) is None
    note = recompile.build_inputs_note(tmp_path, gnu=True)
    assert note and "does not name the compiler or flags" in note
    # msvc keeps its two keys
    recompile.write_build_inputs(tmp_path, A, "msvc")
    assert recompile.read_build_inputs(tmp_path) == {"dol_sha1": A, "profile": "msvc"}


def test_compiler_id_is_the_first_line_and_write_build_inputs_writes_it(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(toolchain, "compiler_path", lambda p: str(tmp_path / f"fake-{p.name}"))
    toolchain.clang_id.cache_clear()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "\nclang version 9.9.9 (x)\nTarget: y\n", "")

    monkeypatch.setattr(toolchain.subprocess, "run", run)
    assert toolchain.compiler_id(toolchain.ANDROID_X86_64) == "clang version 9.9.9 (x)"
    assert toolchain.compiler_id(toolchain.ANDROID_X86_64) == "clang version 9.9.9 (x)"
    assert len(calls) == 1  # cached per path
    assert toolchain.compiler_id(toolchain.MSVC) == ""
    toolchain.clang_id.cache_clear()
    cid = toolchain.compiler_id(toolchain.ANDROID_X86_64)
    flags = recompile.cflags_digest(toolchain.ANDROID_X86_64)
    recompile.write_build_inputs(
        tmp_path, A, "android-x86_64", compiler=cid, cflags=flags, sysroot="s" * 64
    )
    rec = recompile.read_build_inputs(tmp_path)
    assert (rec["compiler"], rec["cflags"], rec["sysroot"]) == (cid, flags, "s" * 64)
    assert (
        recompile.check_build_inputs(
            tmp_path, A, compiler=cid, cflags=flags, sysroot="s" * 64, strict=True
        )
        is None
    )
    toolchain.clang_id.cache_clear()


def test_the_sysroot_not_as_recorded_is_refused_before_the_build(monkeypatch, tmp_path):
    import fetch_android_sysroot as fas

    want = {f"{fas.DEST}/usr/include/a.h": fas.sha256(b"a\n")}
    monkeypatch.setattr(fas, "expected_record", lambda: dict(want))
    tree = tmp_path / fas.DEST / "usr" / "include"
    tree.mkdir(parents=True)
    (tree / "a.h").write_bytes(b"a, a byte on\n")
    fas.write_record(tmp_path / fas.RECORD, want)
    why = recompile.android_sysroot_problem(tmp_path)
    assert why and why.startswith(
        "vendor/android-sysroot is not as recorded (android-sysroot/usr/include/a.h: differs"
    )
    assert why.endswith("run python tools/fetch_android_sysroot.py")
    (tree / "a.h").write_bytes(b"a\n")
    assert recompile.android_sysroot_problem(tmp_path) is None
    assert "no " in recompile.android_sysroot_problem(tmp_path / "none")
