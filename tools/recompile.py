#!/usr/bin/env python3
"""Translate the whole DOL to C.

    python tools/recompile.py [--dol extracted/sys/main.dol] [--out gen] [--chunk 400]
                              [--cc msvc|clang-cl|gcc|clang|mingw] [--compile] [--link] [--limit N]

Writes gen/functions.h, gen/dispatch.c and gen/chunk_NNN.c (gitignored: they
are derived from the game binary and are reproduced locally from the user's
own dump). Prints instruction coverage so what is *not* translated is always
visible. --compile runs the compiler over every chunk to prove the C is valid;
--link links them with runtime/ into soa.exe and builds the mods.

--cc picks a toolchain profile (tools/soa/toolchain.py; portability.md 3.9):
msvc by default. Another profile writes everything -- the C, the objects, the
exe -- under its own directory, gen/clang for clang-cl, so a clang build can
never be linked into gen/soa.exe. mingw (llvm-mingw, distribution R1) links
GNU-style into gen/mingw/soa.exe with no Microsoft compiler, and builds each
mod's mod.dll under gen/mingw/mods, beside a copy of its mod.ini and
patches.txt, never over the msvc build's beside mod.c.
"""

import argparse
import collections
import concurrent.futures
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# units.txt is read by one parser, which decomp.py owns (stdlib only, so the
# no-pip CI job that imports this file still needs nothing installed).
import fetch_gpu  # noqa: E402
from decomp import read_units  # noqa: E402
from soa import dol as D  # noqa: E402
from soa import shaders, toolchain  # noqa: E402
from soa import symbols as S  # noqa: E402
from soa.hle import load_hle  # noqa: E402
from soa.ppc import cfg  # noqa: E402
from soa.recomp import Emitter  # noqa: E402

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
VENDOR = Path(__file__).resolve().parents[1] / "vendor"

# Where mods with native code live: the ones the port ships, and the examples
# a mod author copies. --link builds each folder's mod.c into its mod.dll.
MOD_FOLDERS = ("mods", "examples/mods")


def mod_dll_sources(root: Path = RUNTIME.parent) -> list[Path]:
    """Every mod.c under MOD_FOLDERS, one per mod folder, in name order."""
    return sorted(p for d in MOD_FOLDERS for p in (root / d).glob("*/mod.c"))


def mod_dll_command(src: Path) -> list[str]:
    """The cl line --link builds a mod's mod.dll with, beside its mod.c
    (test_mods.py builds the shipped mods with this same line)."""
    folder = src.parent
    return [
        *toolchain.CFLAGS,
        "/LD",
        f"/I{RUNTIME}",
        str(src),
        f"/Fo{folder}{os.sep}",
        f"/Fe:{folder / 'mod.dll'}",
    ]


# The text files a mod folder's mod.dll is loaded beside: a mingw build copies
# them into its own mods/ folder with the mod.dll it builds.
MOD_TEXT = ("mod.ini", "patches.txt")


def mod_out_dir(p: toolchain.Profile, out: Path, src: Path) -> Path:
    """Where --link puts a mod's mod.dll: beside its mod.c for msvc, under
    <out>/mods/<folder> for mingw (distribution R1), absolute."""
    if p.name == "msvc":
        return src.parent.resolve()
    return (out / "mods" / src.parent.name).resolve()


def gnu_mod_dll_command(p: toolchain.Profile, src: Path, dest: Path) -> list[str]:
    """The mingw profile's line for a mod's mod.dll, written into dest."""
    return [*p.cflags, "-shared", f"/I{RUNTIME}", str(src.resolve()), f"/Fe{dest / 'mod.dll'}"]


# ---- the command lines, one profile at a time (portability.md 3.9, L3a) ----
# Pure functions: test_toolchain_profiles.py holds the msvc profile's to a
# golden copy and checks that clang-cl's write only under gen/clang.


def out_dir(p: toolchain.Profile, given: Path | None) -> Path:
    """Where a build goes: --out, or the profile's own directory (clang-cl:
    gen/clang). A profile other than msvc may not write into msvc's: --link
    links whatever objects its directory holds, so a clang-cl runtime would
    join MSVC's chunks in gen/soa.exe, which replay --bless trusts by path."""
    out = given if given is not None else Path(p.out)
    if p is not toolchain.MSVC and out.resolve() == Path(toolchain.MSVC.out).resolve():
        raise ValueError(
            f"--cc {p.name} --out {given}: {toolchain.MSVC.out} is the msvc build's; "
            f"leave --out unset for {p.out}"
        )
    return out


# The optimisation flag in each grammar, and what --compile uses without
# --optimize.
_OPT_LEVELS = {"/O2": "/Od", "-O2": "-O0"}


def opt_level(p: toolchain.Profile, optimize: bool) -> str:
    """The level --compile builds the translated C at, in the profile's grammar."""
    flag = next(f for f in p.cflags if f in _OPT_LEVELS)
    return flag if optimize else _OPT_LEVELS[flag]


def compile_command(p: toolchain.Profile, out: Path, path: Path, optimize: bool) -> list[str]:
    """--compile's line for one translation unit, run in `out`. Validation
    compiles at /Od (-O0) unless --optimize: the point is to prove the C is
    well-formed, and /O2 over 50 MB of it takes many minutes."""
    level = opt_level(p, optimize)
    flags = [level if f in _OPT_LEVELS else f for f in p.cflags]
    return [
        *flags,
        "/c",
        f"/I{RUNTIME}",
        f"/I{out}",
        path.name,
        f"/Fo{path.with_suffix(p.objext).name}",
    ]


def decomp_command(
    p: toolchain.Profile, out: Path, dc_files: list[str], dc_defines: list[str]
) -> list[str]:
    """The native build of the hand-decompiled units, run in the repository root."""
    return [*p.cflags, "/c", "/Iinclude", *dc_defines, f"/Fo{out / 'decomp'}/", *dc_files]


def decomp_objects(p: toolchain.Profile, out: Path, dc_files: list[str]) -> list[Path]:
    """The objects decomp_command makes: one per unit, named after it."""
    return sorted(out / "decomp" / (Path(f).stem + p.objext) for f in dc_files)


def gnu_link_command(
    p: toolchain.Profile, out: Path, objs: list[Path], gxv: bool = False
) -> list[str]:
    """The mingw profile's link (distribution R1): msvc's, in clang's words.
    -gcodeview and lld's --pdb write <out>/soa.pdb, which SOA_HOSTPROF's
    report reads through dbghelp as it reads MSVC's. The libraries and the
    stack are the profile's linker flags, last, after every source and object."""
    return [
        *p.cflags,
        "-gcodeview",
        f"/I{RUNTIME}",
        f"/I{out}",
        *(["/DSOA_GXV=1", f"/I{out / 'gxv'}", f"/I{shaders.HEADERS}"] if gxv else []),
        f"/Fe{out / ('soa' + p.exeext)}",
        *map(str, sorted(RUNTIME.glob("*.c"))),
        *map(str, objs),
        f"-Wl,--pdb={out / 'soa.pdb'}",
        *p.linker,
    ]


def link_command(p: toolchain.Profile, out: Path, objs: list[Path], gxv: bool = False) -> list[str]:
    """The link of runtime/ and the objects into soa.exe, run in the root.

    gxv builds runtime/gxv.c as the GPU backend (SOA_GXV=1), against
    vendor/'s Vulkan-Headers and the SPIR-V headers shaders.build wrote into
    <out>/gxv; without it gxv.c is the stub that says the build has none.

    /Zi and /DEBUG write <out>/soa.pdb without changing the code /O2 makes
    (/OPT:REF and /OPT:ICF are what /DEBUG would otherwise turn off): the
    runtime's functions and lines get names, which SOA_HOSTPROF's report and a
    crash's stack both need. The translated chunks carry no debug information
    and add only their public names.

    Every runtime file is globbed, so runtime_support_sources() is not added
    here: it is for the tests that link a few runtime files, and plat.c would
    otherwise be on this line twice."""
    return [
        *p.cflags,
        "/Zi",
        f"/Fd{out}/runtime.pdb",
        f"/I{RUNTIME}",
        f"/I{out}",
        *(["/DSOA_GXV=1", f"/I{out / 'gxv'}", f"/I{shaders.HEADERS}"] if gxv else []),
        f"/Fo{out}/",
        f"/Fe:{out / ('soa' + p.exeext)}",
        *map(str, sorted(RUNTIME.glob("*.c"))),
        *map(str, objs),
        *p.linker,
        "/link",
        "/DEBUG",
        "/OPT:REF",
        "/OPT:ICF",
        "/STACK:33554432",  # guest call depth becomes host call depth
    ]


def builds_mods(p: toolchain.Profile) -> bool:
    """The msvc profile builds mods/*/mod.c beside each, for gen/soa.exe;
    mingw builds them under its own directory (mod_out_dir). clang-cl's build
    must touch nothing outside its own, and L9 builds mod.so on Linux."""
    return p.name in ("msvc", "mingw")


def link_plan(
    p: toolchain.Profile,
    out: Path,
    dc_files: list[str],
    dc_defines: list[str],
    gxv: bool = False,
) -> list[tuple[list[str], Path]]:
    """Every compiler command --link runs, in order, each with its working
    directory: the decompiled units, the link, then (msvc only) each mod."""
    objs = sorted(out.glob("chunk_*" + p.objext)) + [out / ("dispatch" + p.objext)]
    plan: list[tuple[list[str], Path]] = []
    if dc_files:
        plan.append((decomp_command(p, out, dc_files, dc_defines), Path(".")))
        objs += decomp_objects(p, out, dc_files)
    link = gnu_link_command if p.name == "mingw" else link_command
    plan.append((link(p, out, objs, gxv), Path(".")))
    if p.name == "msvc":
        plan += [(mod_dll_command(src), src.parent) for src in mod_dll_sources()]
    elif builds_mods(p):
        plan += [
            (gnu_mod_dll_command(p, src, mod_out_dir(p, out, src)), mod_out_dir(p, out, src))
            for src in mod_dll_sources()
        ]
    return plan


# A definition or declaration starting in column 1; the name is the last
# identifier before the parameter list. ``typedef`` is excluded because a
# function-pointer typedef ends in a parameter list of its own, and the
# identifier in front of that list is the return type -- so
# ``typedef void (*ARCallback)(void);`` reads as a function called "void".
_FUNC_DEF = re.compile(
    r"^(?!typedef\b)[A-Za-z_][^\n;{}=]*?\b(\w+)\s*\([^;{}]*\)\s*(?:\n\{|;)", re.M
)

# Every C89/C99 keyword, so that a declaration shaped like one of those
# typedefs is caught rather than turned into a /D that redefines the language.
_KEYWORD_TEXT = """
auto break case char const continue default do double else enum extern float for goto if
inline int long register restrict return short signed sizeof static struct switch typedef
union unsigned void volatile while _Bool _Complex _Imaginary
"""
_C_KEYWORDS = frozenset(_KEYWORD_TEXT.split())


class RenameError(Exception):
    """A unit's scan produced a rename that must never reach the compiler."""


def native_decomp_sources(units: Path) -> tuple[list[str], list[str]]:
    """The units marked ``native`` in config/GEAE8P/units.txt, and the /D renames
    that prefix every function they define or declare with dc_ (a declared
    callee that is not decompiled yet comes from runtime/decomp_shims.c).
    A unit earns ``native`` by compiling under MSVC, reading nothing whose
    meaning depends on byte order, touching no memory-mapped register, and
    calling nothing undecompiled; units that read the game's globals fail the
    second of those until the native build maps them onto guest memory."""
    files = [u.src for u in read_units(units) if u.native] if units.exists() else []
    names = set()
    for f in files:
        for name in _FUNC_DEF.findall(f.read_text(encoding="utf-8")):
            # A keyword here means the scan misread a declaration. Emitting the
            # /D anyway would define the keyword away over every unit in the
            # build, and the damage would surface as an unrelated syntax error
            # in whichever file used it next.
            if name in _C_KEYWORDS:
                raise RenameError(
                    f"{f}: read the C keyword '{name}' as a function name. "
                    f"A rename of '{name}' would break every unit in the native build; "
                    f"fix _FUNC_DEF in {Path(__file__).name} rather than the unit."
                )
            names.add(name)
    return [str(f) for f in files], [f"/D{n}=dc_{n}" for n in sorted(names)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument(
        "--cc",
        choices=list(toolchain.PROFILES),
        default="msvc",
        help="the toolchain profile; a non-msvc one writes to its own --out (clang-cl: gen/clang)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="where the C, objects and exe go (default the profile's: gen, gen/clang, gen/linux)",
    )
    ap.add_argument("--chunk", type=int, default=400, help="functions per C file")
    ap.add_argument("--limit", type=int, default=0, help="translate only the first N functions")
    ap.add_argument("--compile", action="store_true", help="compile every chunk with --cc")
    ap.add_argument("--optimize", action="store_true", help="compile at /O2 instead of /Od")
    ap.add_argument(
        "--link", action="store_true", help="link the objects with runtime/ into soa.exe"
    )
    args = ap.parse_args()
    prof = toolchain.profile(args.cc)
    # A clang build goes to its own directory, so it can never be linked into
    # gen/soa.exe: --link globs whatever objects --out holds.
    try:
        args.out = out_dir(prof, args.out)
    except ValueError as exc:
        ap.error(str(exc))
    # The msvc profile's lines are the ones the docs quote (TESTING.md).
    shown = "MSVC" if prof is toolchain.MSVC else prof.name
    into = "" if prof is toolchain.MSVC else f" into {args.out}"

    dol = D.parse(args.dol.read_bytes())
    t0 = time.time()
    functions, _ = cfg.build_iterative(dol)
    code = cfg.CodeView(dol)
    tables = cfg.find_jump_tables(dol, code)
    print(f"{len(functions):,} functions, {len(tables)} switch tables ({time.time() - t0:.1f}s)")

    names = {}
    tsv = args.config / "functions.tsv"
    if tsv.exists():
        names = {a: r["name"] for a, r in S.load_tsv(tsv).items()}

    hle = load_hle(args.config / "hle.txt")
    hooks = load_hle(args.config / "hooks.txt")
    savepoints = load_hle(args.config / "savepoints.txt")
    traces = load_hle(args.config / "trace.txt")
    if hle or hooks or savepoints:
        print(
            f"{len(hle)} functions bound to HLE, {len(hooks)} runtime hooks, "
            f"{len(savepoints)} savepoints"
        )
    em = Emitter(dol, functions, tables, code, names, hle, hooks, savepoints, traces)
    entries = sorted(functions)
    if args.limit:
        entries = entries[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "functions.h").write_text(em.prototypes(), encoding="utf-8")
    (args.out / "dispatch.c").write_text(em.dispatch_c(), encoding="utf-8")

    t0 = time.time()
    chunks: list[Path] = []
    for n in range(0, len(entries), args.chunk):
        body = ['#include "functions.h"', ""]
        for entry in entries[n : n + args.chunk]:
            body.append(em.function_c(functions[entry]))
            body.append("")
        path = args.out / f"chunk_{n // args.chunk:03d}.c"
        path.write_text("\n".join(body), encoding="utf-8")
        chunks.append(path)
    st = em.stats
    total_bytes = sum(p.stat().st_size for p in chunks)
    print(
        f"emitted {len(entries):,} functions into {len(chunks)} files, "
        f"{total_bytes / 1024**2:.1f} MB of C ({time.time() - t0:.1f}s)"
    )

    print(
        f"\ninstruction coverage: {st.coverage_pct:.3f}%  "
        f"({sum(st.translated.values()):,} translated, {sum(st.unsupported.values()):,} not)"
    )
    if st.oe_ignored:
        print(f"  OE forms translated without overflow tracking: {st.oe_ignored}")
    if st.unsupported:
        print("  unsupported, by mnemonic:")
        for mn, c in st.unsupported.most_common():
            print(f"    {mn:16} {c:>7,}")

    if args.compile:
        if toolchain.compiler_path(prof) is None:
            print(f"\n{shown} not found; skipping compile", file=sys.stderr)
            return 1
        units = [args.out / "dispatch.c", *chunks]
        level = opt_level(prof, args.optimize)
        print(f"\ncompiling {len(units)} translation units with {shown} ({level}){into} ...")
        t0 = time.time()

        def build(path: Path):
            return path, toolchain.cc(
                compile_command(prof, args.out, path, args.optimize), args.out, prof
            )

        failures = collections.Counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            for path, proc in pool.map(build, units):
                if proc.returncode != 0:
                    failures[path.name] += 1
                    errs = [ln for ln in proc.stdout.splitlines() if "error" in ln.lower()]
                    print(f"  FAIL {path.name}: {errs[0] if errs else proc.stdout[-300:]}")
        elapsed = time.time() - t0
        print(f"compiled {len(units) - len(failures)}/{len(units)} units in {elapsed:.1f}s")
        if failures:
            return 1

    if args.link:
        if prof.style != "msvc" and prof.name != "mingw":
            print(
                f"\n--link builds with msvc, clang-cl or mingw; {prof.name}'s link is portability L10's",
                file=sys.stderr,
            )
            return 1
        if toolchain.compiler_path(prof) is None:
            print(f"\n{shown} not found; skipping link", file=sys.stderr)
            return 1
        exe = args.out / ("soa" + prof.exeext)
        t0 = time.time()
        # The hand-decompiled units (src/) are built natively too, every function
        # renamed dc_<name> so they sit beside the C runtime's own strlen and
        # friends; the selftest runs them against their recompiled twins.
        try:
            dc_files, dc_defines = native_decomp_sources(Path("config/GEAE8P/units.txt"))
        except RenameError as exc:
            print(exc, file=sys.stderr)
            return 1
        if dc_files:
            (args.out / "decomp").mkdir(parents=True, exist_ok=True)
        # The GPU backend (specs/gpu-backend.md 3.10), when tools/fetch_gpu.py
        # has filled vendor/: the shaders to SPIR-V first, and a shader that
        # does not compile fails the build. Without vendor/ soa.exe is built
        # as before, and SOA_GPU=vulkan says how to get the backend.
        gxv = shaders.available()
        if gxv:
            bad = fetch_gpu.verify(VENDOR)
            if bad:
                print(
                    f"vendor/ is not as recorded ({bad[0]}); run python tools/fetch_gpu.py",
                    file=sys.stderr,
                )
                return 1
            built, why = shaders.build(args.out / "gxv")
            if not built:
                print(why, file=sys.stderr)
                return 1
            print("GPU backend: built in (SOA_GPU=vulkan)")
        else:
            print("GPU backend: not built in (python tools/fetch_gpu.py, then --link again)")
        failed_mods = 0
        for cmd, cwd in link_plan(prof, args.out, dc_files, dc_defines, gxv):
            if cwd != Path(".") and prof.name == "mingw":
                # the mod's own text beside the mod.dll this build makes
                src = next(s for s in mod_dll_sources() if s.parent.name == cwd.name)
                cwd.mkdir(parents=True, exist_ok=True)
                for name in MOD_TEXT:
                    if (src.parent / name).exists():
                        (cwd / name).write_bytes((src.parent / name).read_bytes())
            proc = toolchain.cc(cmd, cwd, prof)
            if cwd != Path("."):  # a mod.dll, beside its mod.c or under <out>/mods
                where = cwd.relative_to(RUNTIME.parent) / "mod.dll"
                if proc.returncode != 0:
                    out_text = proc.stdout + proc.stderr
                    errs = [ln for ln in out_text.splitlines() if "error" in ln.lower()]
                    print(
                        f"  FAIL {where}: {errs[0] if errs else out_text[-300:]}",
                        file=sys.stderr,
                    )
                    failed_mods += 1
                else:
                    print(f"built {where}")
                continue
            if proc.returncode != 0:
                print((proc.stdout + proc.stderr)[-2000:], file=sys.stderr)
                return 1
            if "/link" in cmd or any(a.startswith("-Wl,--pdb=") for a in cmd):
                print(f"linked {exe} ({time.time() - t0:.1f}s)")
        if failed_mods:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
