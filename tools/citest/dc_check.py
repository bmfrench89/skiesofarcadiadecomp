"""Build the hand-decompiled MSL units natively and check them against libc.

    python tools/citest/dc_check.py [--out build/citest/decomp]

Compiles the units config/GEAE8P/units.txt marks ``native`` with the exact
/Ddc_* renames tools/recompile.py builds for the twin build, links them with
runtime/decomp_shims.c (which supplies the dc_ symbols nobody has decompiled
yet) and tools/citest/dc_driver.c, and runs the driver, which compares every
routine with the host C library on generated inputs. Needs no disc and no
generated code, so it runs in CI where SOA_SELFTEST cannot. Prints the rename
list, then the driver's report; exits non-zero if anything fails to build or
any routine disagrees.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

# native_decomp_sources() lives in recompile.py because the twin build is what
# defines the renames; importing it here is also why the CI job that runs this
# needs no pip install, and tools/tests/test_citest.py holds that line.
from recompile import native_decomp_sources  # noqa: E402
from soa import toolchain  # noqa: E402

HERE = Path(__file__).resolve().parent
# decomp_shims.c is compiled without the renames on purpose: it is the runtime
# side of the twin build, and its dc___fill_mem is what mem.c's memset calls.
SUPPORT = [ROOT / "runtime" / "decomp_shims.c", HERE / "dc_driver.c"]


def run_cl(what: str, args: list[str]) -> bool:
    proc = toolchain.cl(args, cwd=ROOT)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        print(out)
    if proc.returncode != 0:
        print(f"::error::{what} failed", file=sys.stderr)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", type=Path, default=ROOT / "config" / "GEAE8P" / "units.txt")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "citest" / "decomp")
    args = ap.parse_args()

    cl = toolchain.cl_path()
    if cl is None:
        print("MSVC not found: no cl.exe from vswhere or the known install paths", file=sys.stderr)
        return 1
    print(f"compiler: {cl}")

    sources, defines = native_decomp_sources(args.units)
    if not sources:
        print(f"::error::no units marked native in {args.units}", file=sys.stderr)
        return 1
    print("native units: " + ", ".join(sources))
    print("renames:      " + " ".join(defines) + "\n")

    args.out.mkdir(parents=True, exist_ok=True)
    if not run_cl(
        "compiling the decompiled units",
        [*toolchain.CFLAGS, "/c", "/Iinclude", *defines, f"/Fo{args.out}/", *sources],
    ):
        return 1
    if not run_cl(
        "compiling the driver",
        [*toolchain.CFLAGS, "/c", f"/Fo{args.out}/", *map(str, SUPPORT)],
    ):
        return 1

    exe = args.out / "dc_check.exe"
    # Named rather than globbed, so a stale object from an earlier run in the
    # same directory cannot slip into the link.
    objs = [args.out / (Path(s).stem + ".obj") for s in [*sources, *SUPPORT]]
    if not run_cl("linking the driver", [*toolchain.CFLAGS, *map(str, objs), f"/Fe:{exe}"]):
        return 1

    proc = subprocess.run([str(exe)], capture_output=True, text=True, check=False)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        print(f"::error::{proc.returncode} decompiled routine(s) disagree with the host C library")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
