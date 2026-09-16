"""Build the hand-decompiled units with the vendored Metrowerks compiler and
check them against the executable.

    python tools/decomp.py [--units config/GEAE8P/units.txt]

Each unit compiles to build/src/<name>.o; tools/matchcheck.py then compares
every function in it with the executable's bytes. The exit status is
non-zero if a unit fails to compile or any function differs, so this doubles
as the decompilation's test.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def load_units(path: Path) -> list[tuple[Path, str, list[str]]]:
    units = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        src, version, flags = line.split("\t")[:3]
        units.append((Path(src), version, flags.split()))
    return units


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--units", type=Path, default=Path("config/GEAE8P/units.txt"))
    ap.add_argument("--vendor", type=Path, default=Path("vendor/mwcc/GC"))
    ap.add_argument("--out", type=Path, default=Path("build/src"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for src, version, flags in load_units(args.units):
        cc = args.vendor / version / "mwcceppc.exe"
        if not cc.exists():
            print(
                f"{src}: compiler GC/{version} missing; run tools/fetch_toolchain.py --versions {version}",
                file=sys.stderr,
            )
            return 2
        obj = args.out / (src.stem + ".o")
        # -nosyspath stops the compiler looking beside the source for "quoted" headers
        proc = subprocess.run(
            [str(cc), "-c", *flags, "-i", str(src.parent), str(src), "-o", str(obj)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"{src}: compile failed\n{proc.stdout}{proc.stderr}")
            failures += 1
            continue
        print(f"== {src} (mwcc {version})")
        check = subprocess.run(
            [sys.executable, "tools/matchcheck.py", str(obj)], capture_output=True, text=True
        )
        print(check.stdout.rstrip())
        failures += check.returncode != 0
    print("all units match" if not failures else f"{failures} unit(s) differ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
