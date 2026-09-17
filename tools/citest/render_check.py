"""Build the renderer on its own and run its two pixel checks.

    python tools/citest/render_check.py [--out build/citest/render]

runtime/selftest.c draws a full-screen quad and the title screen's cloud
triangle through the real GX front end and counts what comes out, but it can
only run inside the port, which needs the user's disc. The renderer itself
needs nothing: gx.c, gxr.c, gxr_tev.c and png.c reach only two symbols outside
themselves, and tools/citest/render_driver.c supplies both, so the same checks
link into a binary of their own and run anywhere. This is the one check in
tools/citest/ that looks at a pixel rather than at whether the C compiles.
Prints the compiler's output, then the driver's; exits non-zero if the build
fails, MSVC is missing, or either check disagrees.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
# The renderer and the front end that feeds it. No recompiled code, no device
# models, no window: anything else in runtime/ would drag in the whole port.
SOURCES = [RUNTIME / name for name in ("gx.c", "gxr.c", "gxr_tev.c", "png.c")]
SOURCES.append(HERE / "render_driver.c")


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
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "citest" / "render")
    args = ap.parse_args()

    cl = toolchain.cl_path()
    if cl is None:
        print("MSVC not found: no cl.exe from vswhere or the known install paths", file=sys.stderr)
        print("this check must not pass silently, so it fails instead", file=sys.stderr)
        return 1
    print(f"compiler: {cl}")

    args.out.mkdir(parents=True, exist_ok=True)
    if not run_cl(
        "compiling the renderer",
        [*toolchain.CFLAGS, "/c", f"/I{RUNTIME}", f"/Fo{args.out}/", *map(str, SOURCES)],
    ):
        return 1
    exe = args.out / "render_check.exe"
    # Named rather than globbed, so a stale object from an earlier run in the
    # same directory cannot slip into the link.
    objs = [args.out / (s.stem + ".obj") for s in SOURCES]
    if not run_cl("linking the renderer", [*toolchain.CFLAGS, *map(str, objs), f"/Fe:{exe}"]):
        return 1

    proc = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, check=False)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="")
    if proc.returncode != 0:
        print(f"::error::{proc.returncode} render check(s) failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
