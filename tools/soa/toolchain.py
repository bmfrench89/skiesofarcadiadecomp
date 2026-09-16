"""Locate the host C toolchain.

MSVC is installed as VS 2022 Build Tools but ``cl.exe`` is not on PATH until
``vcvars64.bat`` has run. We run it once in a child ``cmd`` and capture the
environment it produces, then launch the compiler with that environment.
"""

import functools
import os
import shutil
import subprocess
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


def cl(args: list[str], cwd: Path | str) -> subprocess.CompletedProcess:
    env = msvc_env()
    if env is None:
        raise RuntimeError("MSVC not found")
    # CreateProcess searches the *parent's* PATH for the executable, not the
    # child environment we pass, so resolve cl.exe against the captured one.
    exe = shutil.which("cl", path=env.get("PATH", ""))
    if exe is None:
        raise RuntimeError("cl.exe not on the MSVC PATH")
    return subprocess.run(
        [exe, "/nologo", *args], cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )


# Flags every recompiled translation unit is built with. /fp:strict keeps the
# compiler from contracting a*b+c into a fused multiply-add on its own, which
# would silently change rounding relative to the guest.
CFLAGS = ["/std:c17", "/O2", "/fp:strict", "/W3", "/wd4102", "/wd4702", "/wd4101"]
