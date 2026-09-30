"""Toolchain profiles (docs/specs/portability.md 3.9, L3a).

The msvc profile's command lines are held to a golden copy of what
recompile.py ran before profiles existed, so a changed flag fails here before
it changes gen/soa.exe. The clang-cl plan writes only under gen/clang and
builds no mod, so a clang build can never be linked into gen/soa.exe; each
rule has a mutation that fails it. No compiler is run: these are the plans.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "citest"))

import recompile  # noqa: E402
from soa import toolchain  # noqa: E402

RUNTIME = ROOT / "runtime"
MSVC_FLAGS = ["/std:c17", "/O2", "/fp:strict", "/W3", "/wd4102", "/wd4702", "/wd4101"]


def test_the_msvc_profile_is_today_s_flags():
    assert toolchain.CFLAGS == MSVC_FLAGS
    assert list(toolchain.MSVC.cflags) == MSVC_FLAGS
    assert toolchain.profile(None) is toolchain.MSVC and toolchain.profile("") is toolchain.MSVC
    with pytest.raises(ValueError, match="no toolchain profile"):
        toolchain.profile("tcc")


def test_the_msvc_command_lines_are_the_golden_copy():
    """--compile, the decompiled units, the link and a mod, as recompile.py
    built them before profiles: a flag changed anywhere fails this."""
    out = Path("gen")
    od = ["/std:c17", "/Od", "/fp:strict", "/W3", "/wd4102", "/wd4702", "/wd4101"]
    assert recompile.compile_command(toolchain.MSVC, out, out / "chunk_000.c", optimize=False) == [
        *od,
        "/c",
        f"/I{RUNTIME}",
        "/Igen",
        "chunk_000.c",
        "/Fochunk_000.obj",
    ]
    assert (
        recompile.compile_command(toolchain.MSVC, out, out / "dispatch.c", optimize=True)[1]
        == "/O2"
    )
    assert recompile.decomp_command(toolchain.MSVC, out, ["src/a.c"], ["/Dx=dc_x"]) == [
        *MSVC_FLAGS,
        "/c",
        "/Iinclude",
        "/Dx=dc_x",
        f"/Fo{Path('gen') / 'decomp'}/",
        "src/a.c",
    ]
    objs = [out / "chunk_000.obj", out / "dispatch.obj"]
    assert recompile.link_command(toolchain.MSVC, out, objs) == [
        *MSVC_FLAGS,
        "/Zi",
        "/Fdgen/runtime.pdb",
        f"/I{RUNTIME}",
        "/Igen",
        "/Fogen/",
        f"/Fe:{Path('gen') / 'soa.exe'}",
        *map(str, sorted(RUNTIME.glob("*.c"))),
        *map(str, objs),
        "/link",
        "/DEBUG",
        "/OPT:REF",
        "/OPT:ICF",
        "/STACK:33554432",
    ]
    src = ROOT / "mods" / "coop" / "mod.c"
    assert recompile.mod_dll_command(src) == [
        *MSVC_FLAGS,
        "/LD",
        f"/I{RUNTIME}",
        str(src),
        f"/Fo{src.parent}\\" if sys.platform == "win32" else f"/Fo{src.parent}/",
        f"/Fe:{src.parent / 'mod.dll'}",
    ]


def outputs(cmd: list[str]) -> list[str]:
    """The paths a command line writes: its /Fo, /Fe and /Fd."""
    got = []
    for a in cmd:
        for flag in ("/Fe:", "/Fo", "/Fe", "/Fd"):
            if a.startswith(flag):
                got.append(a[len(flag) :])
                break
    return got


def strays(plan, home: Path) -> list[str]:
    """What a plan does outside `home`: an output elsewhere, a working
    directory elsewhere, or any mention of a mod folder."""
    bad = []
    for cmd, cwd in plan:
        for o in outputs(cmd):
            p = Path(o.rstrip("/\\"))
            if not p.is_absolute():
                p = ROOT / p
            if not p.resolve().is_relative_to((ROOT / home).resolve()):
                bad.append(f"writes {o}")
        if cwd != Path("."):
            bad.append(f"runs in {cwd}")
        bad += [f"names {a}" for a in cmd if "mods" in Path(a).parts]
    return bad


def clang_plan() -> list:
    out = Path(toolchain.CLANG_CL.out)
    return recompile.link_plan(toolchain.CLANG_CL, out, ["src/a.c"], ["/Dx=dc_x"])


def test_a_clang_cl_build_writes_only_under_gen_clang_and_builds_no_mod():
    assert toolchain.CLANG_CL.out == "gen/clang"
    assert not recompile.builds_mods(toolchain.CLANG_CL)
    assert strays(clang_plan(), Path("gen/clang")) == []
    # the msvc plan, by contrast, builds every mod
    msvc = recompile.link_plan(toolchain.MSVC, Path("gen"), [], [])
    assert len(msvc) == 1 + len(recompile.mod_dll_sources())


def test_the_mutations_fail(monkeypatch):
    """Pointing clang-cl at gen, or letting it build the mods, is caught."""
    monkeypatch.setattr(recompile, "builds_mods", lambda p: True)
    assert any(
        s.startswith("names ") or s.startswith("runs in ")
        for s in strays(clang_plan(), Path("gen/clang"))
    )
    monkeypatch.undo()
    to_gen = recompile.link_plan(toolchain.CLANG_CL, Path("gen"), ["src/a.c"], [])
    assert strays(to_gen, Path("gen/clang"))


def test_the_gnu_grammar_is_translated():
    assert toolchain.gnu_args(
        ["/c", "/I", "runtime", "/Iinc", "/DX=1", "/Foa.o", "/Fe:b", "x.c"]
    ) == [
        "-c",
        "-I",
        "runtime",
        "-Iinc",
        "-DX=1",
        "-o",
        "a.o",
        "-o",
        "b",
        "x.c",
    ]


def test_compile_runtime_s_strict_set_is_the_profile_s():
    import compile_runtime

    assert list(toolchain.MSVC.strict) == compile_runtime.STRICT
    assert all(w.startswith("/clang:-Werror=") for w in toolchain.CLANG_CL.strict)


def test_the_runtime_support_sources_are_none_before_l7():
    assert toolchain.runtime_support_sources() == []
