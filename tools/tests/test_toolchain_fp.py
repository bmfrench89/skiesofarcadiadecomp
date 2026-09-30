"""No fused multiply-add from a clang profile (portability.md 2.8, L3a).

The guest rounds every multiply, so a*b+c contracted into one FMA changes
results. MSVC's /fp:strict never contracts; clang contracts by default when
the target has FMA. For each clang profile found here, `a*b+c` built with
-mfma must disassemble with no vfmadd; the mutation -- the profile's flags
without -ffp-contract=off -- shows vfmadd213ss. The module skips, saying so,
where no clang or llvm-objdump is found; CI's clang-cl leg (L4a) has both.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

SOURCE = "float madd(float a, float b, float c) { return a * b + c; }\n"


def objdump_for(compiler: str) -> str | None:
    beside = Path(compiler).with_name("llvm-objdump.exe")
    return str(beside) if beside.is_file() else shutil.which("llvm-objdump")


def disassembly(tmp: Path, p: toolchain.Profile, flags: list[str]) -> str:
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "madd.c"
    src.write_text(SOURCE, encoding="utf-8")
    fma = "/clang:-mfma" if p.style == "msvc" else "-mfma"
    proc = toolchain.cc([*flags, fma, "/c", str(src), f"/Fo{tmp / ('madd' + p.objext)}"], tmp, p)
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    dump = objdump_for(toolchain.compiler_path(p))
    run = subprocess.run(
        [dump, "-d", str(tmp / ("madd" + p.objext))], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    return run.stdout


CLANG_PROFILES = [toolchain.CLANG_CL, toolchain.CLANG]


@pytest.mark.parametrize("p", CLANG_PROFILES, ids=lambda p: p.name)
def test_a_clang_profile_never_contracts_into_an_fma(tmp_path, p):
    exe = toolchain.compiler_path(p)
    if exe is None:
        pytest.skip(
            f"no {p.name} here (clang-cl: SOA_CLANG_CL, PATH, LLVM's or Visual Studio's; clang: PATH)"
        )
    if objdump_for(exe) is None:
        pytest.skip(f"no llvm-objdump beside {exe} or on PATH")
    assert "vfmadd" not in disassembly(tmp_path / "profile", p, list(p.cflags))
    contract = "/clang:-ffp-contract=off" if p.style == "msvc" else "-ffp-contract=off"
    mutant = [f for f in p.cflags if f != contract]
    assert len(mutant) == len(p.cflags) - 1
    assert "vfmadd213ss" in disassembly(tmp_path / "mutant", p, mutant)
