"""Build runtime/threads.c with plat.c on their own and run a guest thread's
park and resume.

    python tools/citest/threads_check.py [--cc PROFILE] [--out build/citest/threads]

The guest's threads park in OSSaveContext and resume in OSLoadContext, and
the resume is a longjmp to the savepoint on the thread's own stack (cpu.h).
On Windows each guest thread is a fiber; off Windows there are none yet, and
before L7 the resume -- which needs no fiber when a thread loads its own
context -- sat inside the Windows-only block, so the first OSLoadContext
ended the run (exit 6). tools/citest/threads_driver.c is that call site, run
on plat_run_on_big_stack as main.c runs the guest; on Linux it also reads the
guest thread's stack size back, which has to be main.c's GUEST_STACK_BYTES,
the Windows link's /STACK, and at least 32 MB. Exits non-zero if the build
fails, the compiler is missing, the two sizes disagree, or the driver does.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
SOURCES = [
    RUNTIME / "threads.c",
    *toolchain.runtime_support_sources(),
    HERE / "threads_driver.c",
]


def guest_stack_bytes() -> int:
    """main.c's GUEST_STACK_BYTES, which must equal recompile.py's /STACK:
    the guest's stack is the same size on every platform."""
    main = (RUNTIME / "main.c").read_text(encoding="utf-8")
    m = re.search(r"^#define GUEST_STACK_BYTES \(\(size_t\)(\d+) << (\d+)\)", main, re.M)
    if not m:
        raise SystemExit(
            "::error::runtime/main.c no longer defines GUEST_STACK_BYTES as ((size_t)N << M)"
        )
    size = int(m.group(1)) << int(m.group(2))
    link = (ROOT / "tools" / "recompile.py").read_text(encoding="utf-8")
    s = re.search(r'"/STACK:(\d+)"', link)
    if not s or int(s.group(1)) != size:
        raise SystemExit(
            f"::error::main.c's GUEST_STACK_BYTES is {size}, and recompile.py links with "
            f"{s.group(0) if s else 'no /STACK'}: the guest's stack differs by platform"
        )
    return size


def run_cc(prof, what: str, args: list[str]) -> bool:
    proc = toolchain.cc(args, ROOT, prof)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        print(out)
    if proc.returncode != 0:
        print(f"::error::{what} failed", file=sys.stderr)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cc", choices=tuple(toolchain.PROFILES), default="msvc", help="the toolchain profile"
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    prof = toolchain.profile(args.cc)
    if args.out is None:
        name = "threads" if prof.name == "msvc" else f"threads-{prof.name}"
        args.out = ROOT / "build" / "citest" / name
    args.out = args.out.resolve()

    cc = toolchain.compiler_path(prof)
    if cc is None:
        print(f"{prof.name} not found (see tools/soa/toolchain.py compiler_path)", file=sys.stderr)
        print("this check must not pass silently, so it fails instead", file=sys.stderr)
        return 1
    print(f"compiler: {cc}")
    size = guest_stack_bytes()

    args.out.mkdir(parents=True, exist_ok=True)
    if not run_cc(
        prof,
        "compiling threads.c and its driver",
        [
            *prof.cflags,
            "/c",
            f"/I{RUNTIME}",
            f"/DGUEST_STACK_BYTES={size}",
            f"/Fo{args.out}/",
            *map(str, SOURCES),
        ],
    ):
        return 1
    exe = args.out / f"threads_check{prof.exeext}"
    # Named rather than globbed, so a stale object from an earlier run in the
    # same directory cannot slip into the link.
    objs = [args.out / (s.stem + prof.objext) for s in SOURCES]
    if not run_cc(prof, "linking", [*prof.cflags, *map(str, objs), f"/Fe:{exe}", *prof.linker]):
        return 1

    proc = subprocess.run(
        [str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
    )
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="")
    if proc.returncode != 0:
        print(f"::error::the driver exited {proc.returncode}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
