"""Locate the host C toolchain.

MSVC is installed as VS 2022 Build Tools but ``cl.exe`` is not on PATH until
``vcvars64.bat`` has run. We run it once in a child ``cmd`` and capture the
environment it produces, then launch the compiler with that environment.
"""

import functools
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_VSWHERE = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
_FALLBACKS = [
    Path(r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"),
    Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community"),
    Path(r"C:\Program Files\Microsoft Visual Studio\2022\Professional"),
]


def find_vcvars() -> Path | None:
    roots: list[Path] = []
    if _VSWHERE.exists():
        try:
            out = subprocess.run(
                [str(_VSWHERE), "-latest", "-products", "*", "-property", "installationPath"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if out:
                roots.append(Path(out))
        except OSError:
            pass
    roots.extend(_FALLBACKS)
    for root in roots:
        bat = root / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if bat.exists():
            return bat
    return None


@functools.cache
def msvc_env() -> dict[str, str] | None:
    """Environment with cl.exe on PATH and INCLUDE/LIB set, or None."""
    if os.name != "nt":
        return None
    if shutil.which("cl"):
        return dict(os.environ)
    bat = find_vcvars()
    if bat is None:
        return None
    # cmd /s strips the first and last quote of its command string, which
    # would unquote the batch file's path; wrapping the whole command in one
    # more pair of quotes is what survives that. Passed as a single string so
    # Python does not re-quote it.
    cmd = f'cmd.exe /s /c ""{bat}" >nul 2>&1 && set"'
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    env: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            env[key] = value
    return env if "INCLUDE" in env else None


def cl_path() -> str | None:
    """Full path of cl.exe in the MSVC environment, or None when there is none.

    The environment captured from vcvars spells the variable ``Path`` on some
    installs and ``PATH`` on others; look it up without regard to case.
    """
    env = msvc_env()
    if env is None:
        return None
    path = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    return shutil.which("cl", path=path)


def cl(args: list[str], cwd: Path | str) -> subprocess.CompletedProcess:
    env = msvc_env()
    if env is None:
        raise RuntimeError("MSVC not found")
    # CreateProcess searches the *parent's* PATH for the executable, not the
    # child environment we pass, so resolve cl.exe against the captured one.
    exe = cl_path()
    if exe is None:
        raise RuntimeError("cl.exe not on the MSVC PATH")
    return subprocess.run(
        [exe, "/nologo", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )


# Flags every recompiled translation unit is built with. /fp:strict keeps the
# compiler from contracting a*b+c into a fused multiply-add on its own, which
# would silently change rounding relative to the guest.
CFLAGS = ["/std:c17", "/O2", "/fp:strict", "/W3", "/wd4102", "/wd4702", "/wd4101"]


# ---- toolchain profiles (docs/specs/portability.md 3.9, L3a) ----------------


@dataclass(frozen=True)
class Profile:
    """One compiler and how the port builds with it.

    `style` is the flag grammar: "msvc" (cl and clang-cl, `/c /Fo /Fe /I /D`)
    or "gnu" (gcc and clang; cc() translates the msvc forms). `strict` is the
    warning set compile_runtime.py promotes to errors; `out` the directory a
    build with this profile writes, so a clang build can never be linked into
    gen/soa.exe. `linker` goes on a command line that links, beside cflags."""

    name: str
    style: str
    cflags: tuple[str, ...]
    strict: tuple[str, ...]
    objext: str
    exeext: str
    out: str
    linker: tuple[str, ...] = ()


# The warnings that mean a call does not match the function it names; see
# compile_runtime.py, which promotes them because nothing there links.
_CLANG_STRICT = (
    "-Werror=implicit-function-declaration",
    "-Werror=int-conversion",
    "-Werror=incompatible-pointer-types",
    "-Werror=return-type",
)

MSVC = Profile(
    "msvc",
    "msvc",
    tuple(CFLAGS),
    (
        "/we4013",
        "/we4020",
        "/we4024",
        "/we4028",
        "/we4029",
        "/we4047",
        "/we4133",
        "/we4700",
        "/we4716",
    ),
    ".obj",
    ".exe",
    "gen",
)
# clang-cl on MSVC's headers, libraries and link.exe. The three -f flags make
# clang's semantics MSVC's where they differ: no contraction into an FMA (the
# guest rounds every multiply, and /fp:strict is how MSVC says it), no
# type-based alias analysis (the runtime reads byte buffers through wider
# types), and wrapping signed arithmetic. Never -ffast-math: cr_fcmp finds a
# NaN by a != a (cpu.h).
CLANG_CL = Profile(
    "clang-cl",
    "msvc",
    (
        "/std:c17",
        "/O2",
        "/fp:precise",
        "/clang:-ffp-contract=off",
        "/clang:-fno-strict-aliasing",
        "/clang:-fwrapv",
        "/D_CRT_SECURE_NO_WARNINGS=",  # empty, as the files that define it themselves do
        "/W3",
        "/wd4102",
        "/wd4702",
        "/wd4101",
        "-Wno-comment",
    ),
    tuple(f"/clang:{w}" for w in _CLANG_STRICT),
    ".obj",
    ".exe",
    "gen/clang",
    # MSVC's link.exe, which the MSVC environment supplies: a clang-cl need not
    # default to it (the Android NDK's defaults to lld-link and ships none).
    ("-fuse-ld=link",),
)
_GNU_FLAGS = (
    "-std=c17",
    "-O2",
    "-ffp-contract=off",
    "-fno-strict-aliasing",
    "-fwrapv",
    "-D_GNU_SOURCE",
    "-Wall",
)
GCC = Profile("gcc", "gnu", _GNU_FLAGS, _CLANG_STRICT, ".o", "", "gen/linux")
CLANG = Profile("clang", "gnu", _GNU_FLAGS, _CLANG_STRICT, ".o", "", "gen/linux")
PROFILES = {p.name: p for p in (MSVC, CLANG_CL, GCC, CLANG)}


def profile(name: str | None) -> Profile:
    """The profile named, or msvc for None or ""; a name that is none of them raises."""
    if not name:
        return MSVC
    if name not in PROFILES:
        raise ValueError(f"no toolchain profile {name!r}: {', '.join(PROFILES)}")
    return PROFILES[name]


def _msvc_path() -> str:
    env = msvc_env() or {}
    return next((v for k, v in env.items() if k.upper() == "PATH"), "")


def _vs_llvm() -> list[Path]:
    """VS's own clang-cl, beside the vcvars this found."""
    bat = find_vcvars()
    if bat is None:
        return []
    return [bat.parents[3] / "VC" / "Tools" / "Llvm" / "x64" / "bin" / "clang-cl.exe"]


def compiler_path(p: Profile = MSVC) -> str | None:
    """The compiler a profile runs, or None when it is not here.

    clang-cl: SOA_CLANG_CL, then PATH (the MSVC environment's too), then
    LLVM's installer's folder, then Visual Studio's own; it still needs MSVC's
    environment for headers, libraries and link.exe, so without MSVC it is
    None. gcc and clang: PATH."""
    if p.name == "msvc":
        return cl_path()
    if p.name == "clang-cl":
        if msvc_env() is None:
            return None
        env = os.environ.get("SOA_CLANG_CL", "")
        if env and Path(env).is_file():
            return env
        found = shutil.which("clang-cl") or shutil.which("clang-cl", path=_msvc_path())
        if found:
            return found
        for c in [Path(r"C:\Program Files\LLVM\bin\clang-cl.exe"), *_vs_llvm()]:
            if c.is_file():
                return str(c)
        return None
    return shutil.which(p.name)


def gnu_args(args: list[str]) -> list[str]:
    """The msvc spellings cc() is handed, in gcc's: /D, /I, /Fo, /Fe and /c."""
    out: list[str] = []
    it = iter(args)
    for a in it:
        if a in ("/I", "/D"):
            out += [f"-{a[1]}", next(it)]
        elif a.startswith(("/I", "/D")):
            out.append(f"-{a[1]}{a[2:]}")
        elif a.startswith("/Fe:"):
            out += ["-o", a[4:]]
        elif a.startswith(("/Fe", "/Fo")):
            out += ["-o", a[3:]]
        elif a == "/c":
            out.append("-c")
        else:
            out.append(a)
    return out


def cc(args: list[str], cwd: Path | str, p: Profile = MSVC) -> subprocess.CompletedProcess:
    """Run a profile's compiler. `args` are in the msvc grammar whatever the
    profile; the profile's own flags are the caller's to include (p.cflags),
    as CFLAGS always were."""
    exe = compiler_path(p)
    if exe is None:
        raise RuntimeError(f"no {p.name} compiler here")
    if p.style == "msvc":
        env = msvc_env()
        return subprocess.run(
            [exe, "/nologo", *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    return subprocess.run(
        [exe, *gnu_args(args)], cwd=str(cwd), capture_output=True, text=True, check=False
    )


def runtime_support_sources() -> list[Path]:
    """Runtime sources every build that links a runtime file needs beside it:
    runtime/plat.c once L7 creates it, nothing before."""
    return []
