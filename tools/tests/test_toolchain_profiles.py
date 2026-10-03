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
# portability.md 3.9's table, copied rather than imported, so a flag changed in
# toolchain.py fails here on every CI leg, with or without a compiler.
MSVC_FLAGS = ["/std:c17", "/O2", "/fp:strict", "/W3", "/wd4102", "/wd4702", "/wd4101"]
CLANG_CL_FLAGS = [
    "/std:c17",
    "/O2",
    "/fp:precise",
    "/clang:-ffp-contract=off",
    "/clang:-fno-strict-aliasing",
    "/clang:-fwrapv",
    "/D_CRT_SECURE_NO_WARNINGS=",
    "/W3",
    "/wd4102",
    "/wd4702",
    "/wd4101",
    "-Wno-comment",
]
GNU_FLAGS = [
    "-std=c17",
    "-O2",
    "-ffp-contract=off",
    "-fno-strict-aliasing",
    "-fwrapv",
    "-D_GNU_SOURCE",
    "-Wall",
]
MSVC_STRICT = [
    "/we4013",
    "/we4020",
    "/we4024",
    "/we4028",
    "/we4029",
    "/we4047",
    "/we4133",
    "/we4700",
    "/we4716",
]
CLANG_STRICT = [
    "-Werror=implicit-function-declaration",
    "-Werror=int-conversion",
    "-Werror=incompatible-pointer-types",
    "-Werror=return-type",
]


def test_the_msvc_profile_is_today_s_flags():
    assert toolchain.CFLAGS == MSVC_FLAGS
    assert list(toolchain.MSVC.cflags) == MSVC_FLAGS
    assert toolchain.profile(None) is toolchain.MSVC and toolchain.profile("") is toolchain.MSVC
    with pytest.raises(ValueError, match="no toolchain profile"):
        toolchain.profile("tcc")


def test_every_profile_is_the_spec_s():
    """The flags, strict sets, linker flags and directories of 3.9's table.
    Never fast-math anywhere: cr_fcmp finds a NaN by a != a (cpu.h), and
    /fp:fast would pass the FMA probe, since -ffp-contract=off still holds."""
    assert list(toolchain.CLANG_CL.cflags) == CLANG_CL_FLAGS
    assert list(toolchain.MSVC.strict) == MSVC_STRICT
    assert list(toolchain.CLANG_CL.strict) == [f"/clang:{w}" for w in CLANG_STRICT]
    assert (toolchain.MSVC.linker, toolchain.CLANG_CL.linker) == ((), ("-fuse-ld=link",))
    for p in (toolchain.GCC, toolchain.CLANG):
        assert (list(p.cflags), list(p.strict)) == (GNU_FLAGS, CLANG_STRICT)
        assert (p.linker, p.out) == (("-pthread", "-lm"), "gen/linux")
    assert [p.out for p in (toolchain.MSVC, toolchain.CLANG_CL)] == ["gen", "gen/clang"]


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


def test_the_link_builds_the_gpu_backend_in_only_when_asked():
    """V5: with vendor/ filled, --link defines SOA_GXV and adds the SPIR-V and
    Vulkan-Headers include paths, and nothing else; without it the command is
    the golden copy above."""
    from soa import shaders

    out = Path("gen")
    plain = recompile.link_command(toolchain.MSVC, out, [])
    i = plain.index("/Igen")
    backend = ["/DSOA_GXV=1", f"/I{out / 'gxv'}", f"/I{shaders.HEADERS}"]
    assert recompile.link_command(toolchain.MSVC, out, [], gxv=True) == (
        plain[: i + 1] + backend + plain[i + 1 :]
    )


def test_the_msvc_link_plan_is_the_golden_copy(tmp_path):
    """What --link runs, in order, objects included, as before profiles: the
    decompiled units, then the link of the chunks it finds, dispatch and the
    units' objects, then each mod. Only chunk_* objects are globbed, and a
    stale object in decomp/ is not linked (it was until L3a)."""
    out = tmp_path / "gen"
    (out / "decomp").mkdir(parents=True)
    for name in ("chunk_001.obj", "chunk_000.obj", "chunk_000.c", "dispatch.obj", "stale.obj"):
        (out / name).write_bytes(b"")
    (out / "decomp" / "gone.obj").write_bytes(b"")
    dc = ["src/soa/b.c", "src/sdk/a.c"]
    objs = [out / "chunk_000.obj", out / "chunk_001.obj", out / "dispatch.obj"]
    objs += [out / "decomp" / "a.obj", out / "decomp" / "b.obj"]
    assert recompile.link_plan(toolchain.MSVC, out, dc, ["/Dx=dc_x"]) == [
        (recompile.decomp_command(toolchain.MSVC, out, dc, ["/Dx=dc_x"]), Path(".")),
        (recompile.link_command(toolchain.MSVC, out, objs), Path(".")),
        *[(recompile.mod_dll_command(src), src.parent) for src in recompile.mod_dll_sources()],
    ]


# The flags that name a file a command line writes, the compiler's and the
# linker's, compared without regard to case as cl and link.exe do.
OUTPUT_FLAGS = ("/fe:", "/fo", "/fe", "/fd", "/pdb:", "/out:", "/implib:", "/map:")


def outputs(cmd: list[str]) -> list[str]:
    """The paths a command line writes."""
    got = []
    for a in cmd:
        flag = next((f for f in OUTPUT_FLAGS if a.lower().startswith(f)), None)
        if flag:
            got.append(a[len(flag) :])
    return got


def strays(plan, home: Path, objext: str = ".obj") -> list[str]:
    """What a plan does outside `home`, each path taken from the command's
    working directory: an output or an object read elsewhere, a working
    directory elsewhere but the root, or any mention of a mod folder."""
    home = (ROOT / home).resolve()
    bad = []
    for cmd, cwd in plan:
        base = ROOT / cwd
        if cwd != Path(".") and not base.resolve().is_relative_to(home):
            bad.append(f"runs in {cwd}")
        for o in outputs(cmd):
            if not (base / o.rstrip("/\\")).resolve().is_relative_to(home):
                bad.append(f"writes {o}")
        for a in cmd:
            read = a.endswith(objext) and not any(a.lower().startswith(f) for f in OUTPUT_FLAGS)
            if read and not (base / a).resolve().is_relative_to(home):
                bad.append(f"links {a}")
        bad += [f"names {a}" for a in cmd if "mods" in Path(a).parts]
    return bad


def clang_plan(out: Path | None = None) -> list:
    """Everything a clang-cl build runs: a chunk's --compile, run in its
    directory, then --link's plan, with the directory main() would choose."""
    out = recompile.out_dir(toolchain.CLANG_CL, out)
    return [
        (recompile.compile_command(toolchain.CLANG_CL, out, out / "chunk_000.c", False), out),
        *recompile.link_plan(toolchain.CLANG_CL, out, ["src/a.c"], ["/Dx=dc_x"]),
    ]


def test_a_clang_cl_build_writes_only_under_gen_clang_and_builds_no_mod():
    assert recompile.out_dir(toolchain.CLANG_CL, None) == Path("gen/clang")
    assert recompile.out_dir(toolchain.MSVC, None) == Path("gen")
    assert not recompile.builds_mods(toolchain.CLANG_CL)
    plan = clang_plan()
    assert strays(plan, Path("gen/clang")) == []
    # every line is clang-cl's: its flags first (the compile's at /Od), and
    # the link takes MSVC's link.exe, the one linker the NDK's clang-cl can use
    at_od = ["/Od" if f == "/O2" else f for f in CLANG_CL_FLAGS]
    assert plan[0][0][: len(at_od)] == at_od
    assert all(cmd[: len(CLANG_CL_FLAGS)] == CLANG_CL_FLAGS for cmd, _ in plan[1:])
    link = next(cmd for cmd, _ in plan if "/link" in cmd)
    last_input = max(i for i, a in enumerate(link) if a.endswith((".c", ".obj")))
    assert last_input < link.index("-fuse-ld=link") < link.index("/link")  # GNU ld's order
    # the msvc plan, by contrast, builds every mod
    msvc = recompile.link_plan(toolchain.MSVC, Path("gen"), [], [])
    assert len(msvc) == 1 + len(recompile.mod_dll_sources())


def test_the_mutations_fail(monkeypatch):
    """Letting clang-cl build the mods, compiling or linking outside its
    directory, or writing a pdb elsewhere through the linker, is caught."""
    home = Path("gen/clang")
    monkeypatch.setattr(recompile, "builds_mods", lambda p: True)
    assert any(s.startswith(("names ", "runs in ")) for s in strays(clang_plan(), home))
    monkeypatch.undo()
    out = Path("gen/clang")
    compile_up = recompile.compile_command(toolchain.CLANG_CL, out, out / "chunk_000.c", False)
    compile_up[-1] = "/Fo../chunk_000.obj"
    assert strays([(compile_up, out)], home) == ["writes ../chunk_000.obj"]
    msvc_objs = [Path("gen/chunk_000.obj")]
    assert strays([(recompile.link_command(toolchain.CLANG_CL, out, msvc_objs), Path("."))], home)
    pdb = recompile.link_command(toolchain.CLANG_CL, out, []) + ["/PDB:gen/soa.pdb"]
    assert strays([(pdb, Path("."))], home) == ["writes gen/soa.pdb"]


@pytest.mark.parametrize("given", ["gen", "./gen", "gen/", "gen/clang/..", str(ROOT / "gen")])
def test_clang_cl_may_not_write_into_msvc_s_directory(given, monkeypatch):
    """--cc clang-cl --out gen would link clang objects into gen/soa.exe,
    which replay --bless trusts by its path; msvc may name it any way."""
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match="msvc build's"):
        recompile.out_dir(toolchain.CLANG_CL, Path(given))
    assert recompile.out_dir(toolchain.MSVC, Path(given)) == Path(given)
    assert recompile.out_dir(toolchain.CLANG_CL, Path("build/clang")) == Path("build/clang")


def test_main_takes_its_directory_from_out_dir(monkeypatch, capsys):
    """main() reaches out_dir before it reads anything, and a refusal is a
    usage error, not a build into gen."""
    seen = []

    def spy(p, given):
        seen.append((p.name, given))
        raise ValueError("refused")

    monkeypatch.setattr(recompile, "out_dir", spy)
    monkeypatch.setattr(sys, "argv", ["recompile.py", "--cc", "clang-cl", "--link"])
    with pytest.raises(SystemExit) as exc:
        recompile.main()
    assert (exc.value.code, seen) == (2, [("clang-cl", None)])
    assert "refused" in capsys.readouterr().err


def test_compile_levels_in_each_grammar():
    """--compile validates at /Od, or -O0 for gcc and clang; --optimize is /O2."""
    for p, low, high in ((toolchain.MSVC, "/Od", "/O2"), (toolchain.GCC, "-O0", "-O2")):
        out = Path(p.out)
        slow = recompile.compile_command(p, out, out / "chunk_000.c", optimize=False)
        fast = recompile.compile_command(p, out, out / "chunk_000.c", optimize=True)
        assert (low in slow, high in slow, high in fast, low in fast) == (True, False, True, False)
        assert (recompile.opt_level(p, False), recompile.opt_level(p, True)) == (low, high)


def test_a_soa_clang_cl_naming_no_file_finds_no_compiler(monkeypatch, tmp_path):
    """SOA_CLANG_CL is the compiler or none: a typo must not quietly test
    another clang found on PATH."""
    monkeypatch.setattr(toolchain, "msvc_env", lambda: {"PATH": ""})
    monkeypatch.setattr(toolchain.shutil, "which", lambda *a, **k: "C:/other/clang-cl.exe")
    monkeypatch.setenv("SOA_CLANG_CL", str(tmp_path / "missing.exe"))
    assert toolchain.compiler_path(toolchain.CLANG_CL) is None
    named = tmp_path / "clang-cl.exe"
    named.write_bytes(b"")
    monkeypatch.setenv("SOA_CLANG_CL", str(named))
    assert toolchain.compiler_path(toolchain.CLANG_CL) == str(named)
    monkeypatch.delenv("SOA_CLANG_CL")
    assert toolchain.compiler_path(toolchain.CLANG_CL) == "C:/other/clang-cl.exe"


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


def test_a_compile_into_a_directory_is_one_gcc_per_source():
    """cl's /Fo<dir>/ over several sources, which every citest script uses,
    has no gcc spelling: L4b, which first runs gcc, makes it one command per
    source, each object named for its source in that directory."""
    cmds = toolchain.gnu_commands(
        ["-O2", "/c", "/Iinclude", "/Dstrlen=dc_strlen", "/Foout/", "a/string.c", "b/mem.c"],
        "gcc",
        toolchain.GCC,
    )
    assert cmds == [
        [
            "gcc",
            "-O2",
            "-c",
            "-Iinclude",
            "-Dstrlen=dc_strlen",
            "-o",
            str(Path("out") / "string.o"),
            "a/string.c",
        ],
        [
            "gcc",
            "-O2",
            "-c",
            "-Iinclude",
            "-Dstrlen=dc_strlen",
            "-o",
            str(Path("out") / "mem.o"),
            "b/mem.c",
        ],
    ]
    # a link, or a compile naming its object, stays one command
    assert toolchain.gnu_commands(["x.o", "y.o", "/Fe:prog"], "gcc", toolchain.GCC) == [
        ["gcc", "x.o", "y.o", "-o", "prog"]
    ]
    assert toolchain.gnu_commands(["/c", "/Fox.o", "x.c"], "gcc", toolchain.GCC) == [
        ["gcc", "-c", "-o", "x.o", "x.c"]
    ]


def test_a_posix_path_that_begins_like_a_flag_is_a_file(monkeypatch):
    monkeypatch.setattr(toolchain.os.path, "exists", lambda a: a == "/Data/soa/gx.c")
    assert toolchain.gnu_args(["/c", "/Data/soa/gx.c", "/DX"]) == ["-c", "/Data/soa/gx.c", "-DX"]


def test_compile_runtime_s_strict_set_is_the_profile_s():
    import compile_runtime

    assert compile_runtime.STRICT == MSVC_STRICT


def test_the_runtime_support_sources_are_plat_c():
    """L7's cold half, which main.c calls and every test that links main.c
    needs beside it; the link of soa.exe globs it with the rest of runtime/."""
    assert toolchain.runtime_support_sources() == [RUNTIME / "plat.c"]
    assert (RUNTIME / "plat.c").is_file()
