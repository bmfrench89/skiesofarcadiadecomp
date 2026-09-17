"""Compile every runtime/*.c on its own, no linking and no generated code.

    python tools/citest/compile_runtime.py [--out build/citest/runtime]

The runtime is the part of the port that is actually hand-written C, and
until this existed nothing built it except the owner's machine, so a syntax
error in runtime/ could reach main unnoticed. Each translation unit is
compiled with /c and the flags tools/soa/toolchain.py gives every unit, which
needs no disc, no gen/ and no link step: each runtime file declares for
itself the recompiled symbols it calls. A handful of warnings that mean a call
does not match the function it names -- the implicit declaration first among
them -- are promoted to errors here, since nothing links and they are all a
link step would have caught. Prints one line per file, with the compiler's
warnings underneath, and exits non-zero if any file fails or MSVC is missing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

RUNTIME = ROOT / "runtime"

# Runtime files this deliberately does not compile, and why. Empty today:
# decomp_swap.c, selftest.c and main.c are the only files that name recompiled
# or decompiled symbols (fn_XXXXXXXX, recomp_fn_XXXXXXXX, dc_*), and each one
# declares them itself, so none of them needs gen/functions.h to compile. A
# file that ever does belongs here with its reason, so that the log says
# plainly what is covered and what is not rather than quietly shrinking.
UNCOVERED: dict[str, str] = {}


# Warnings this check refuses. Without them a call to a function that no longer
# exists is C4013 -- "assuming extern returning int" -- and since nothing here
# links, renaming a runtime function and leaving a caller behind would pass.
# The rest are the same mistake seen through a prototype: a wrong argument
# count or type, a pointer indirection that does not match, a local read before
# it is written, a non-void function that falls off its end. They are promoted
# here rather than added to toolchain.CFLAGS, which has to stay exactly what
# the real build uses: this check may be stricter than the build, never
# different from it.
STRICT = [
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


def compile_one(path: Path, out: Path) -> tuple[Path, int, str]:
    proc = toolchain.cl(
        [*toolchain.CFLAGS, *STRICT, "/c", f"/I{RUNTIME}", str(path), f"/Fo{out}/"],
        cwd=ROOT,
    )
    return path, proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "citest" / "runtime")
    args = ap.parse_args()

    cl = toolchain.cl_path()
    if cl is None:
        print("MSVC not found: no cl.exe from vswhere or the known install paths", file=sys.stderr)
        print("this check must not pass silently, so it fails instead", file=sys.stderr)
        return 1
    print(f"compiler: {cl}")
    print(f"flags:    {' '.join([*toolchain.CFLAGS, *STRICT])} /c /I{RUNTIME}\n")

    args.out.mkdir(parents=True, exist_ok=True)
    sources = sorted(RUNTIME.glob("*.c"))
    if not sources:
        print(f"no sources under {RUNTIME}", file=sys.stderr)
        return 1
    covered = [p for p in sources if p.name not in UNCOVERED]

    failed: list[Path] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for path, rc, out in pool.map(lambda p: compile_one(p, args.out), covered):
            print(f"{'ok  ' if rc == 0 else 'FAIL'} {path.name}")
            if rc != 0:
                failed.append(path)
            # The echo of the file name is the only line MSVC prints when it is
            # happy; anything else is a diagnostic worth having in the log.
            for line in out.splitlines():
                if line.strip() and line.strip() != path.name:
                    print(f"      {line}")

    print(f"\ncompiled {len(covered) - len(failed)}/{len(covered)} runtime translation units")
    if UNCOVERED:
        print("not compiled here:")
        for name, why in sorted(UNCOVERED.items()):
            print(f"  {name}: {why}")
    else:
        print("not compiled here: nothing, every runtime/*.c is covered")
    if failed:
        print(f"::error::{len(failed)} runtime file(s) failed to compile")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
