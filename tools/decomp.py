"""Build the hand-decompiled units with the vendored Metrowerks compiler and
check them against the executable.

    python tools/decomp.py [--units config/GEAE8P/units.txt] [--strict]

Each unit compiles to build/src/<name>.o; tools/matchcheck.py then compares
every function and every data object in it with the executable's bytes.

A unit lands in one of three states, because matchcheck has three answers and
flattening them would be the same unsoundness this tool exists to avoid:

    match       everything was compared and everything was decided;
    unverified  nothing differs, but some words only a link could settle --
                a reference to a global this project has no address for;
    differs     something is wrong, or a compile failed.

The exit status is non-zero if a unit fails to compile, any unit differs, or a
compiler named in units.txt is missing (2, and every unit that needs it is
named -- the run was incomplete, not clean). ``--strict`` also fails on
unverified, which is what a checkout with a complete symbol database should
reach.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

MATCH, DIFFERS, UNVERIFIED = 0, 1, 3


class Unit(NamedTuple):
    src: Path
    version: str
    flags: list[str]
    native: bool


def read_units(path: Path) -> list[Unit]:
    """Every row of a units.txt, or a ValueError naming the line that is not one.

    A row is tab-separated: the source, the compiler (a folder under
    vendor/mwcc/GC/), the flags, and optionally a fourth column that is
    ``native`` and nothing else. recompile.py reads the file through here too.
    The two used to parse it apart and disagreed about a bad row: one written
    with spaces crashed this tool with a bare ValueError out of an unpacking
    and was skipped by recompile.py without a word, and a fourth column of
    ``Native`` was ignored by both -- so the unit matched here and never
    entered the port.
    """
    units = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if not 3 <= len(cols) <= 4 or not cols[0] or not cols[1]:
            raise ValueError(
                f"{path}:{n}: not source<TAB>compiler<TAB>flags[<TAB>native] "
                f"({len(cols)} tab-separated column(s)): {line!r}"
            )
        flags = cols[2].split()
        if "native" in flags:
            # Separated by a space rather than a tab, it is a flag: mwcc is
            # handed a file called "native" and the twin build never sees it.
            raise ValueError(f"{path}:{n}: 'native' is in the flags; put a tab before it")
        if len(cols) == 4 and cols[3].strip() != "native":
            raise ValueError(
                f"{path}:{n}: the fourth column is {cols[3]!r}; it is 'native' exactly, or absent"
            )
        units.append(Unit(Path(cols[0]), cols[1], flags, len(cols) == 4))
    return units


def load_units(path: Path) -> list[tuple[Path, str, list[str]]]:
    return [(u.src, u.version, u.flags) for u in read_units(path)]


def missing_compilers(units, vendor: Path) -> dict[str, list[Path]]:
    """``version -> the units that need it``, for versions not vendored.

    All of them, not the first: a checkout missing 1.2.5n used to stop at the
    unit that wanted it, so the units after that one were never reported at
    all and the run looked shorter than it was rather than incomplete.
    """
    out: dict[str, list[Path]] = {}
    for src, version, _ in units:
        if not (vendor / version / "mwcceppc.exe").exists():
            out.setdefault(version, []).append(src)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--units", type=Path, default=Path("config/GEAE8P/units.txt"))
    ap.add_argument("--vendor", type=Path, default=Path("vendor/mwcc/GC"))
    ap.add_argument("--out", type=Path, default=Path("build/src"))
    ap.add_argument(
        "--strict",
        action="store_true",
        help="fail when a unit has words only a link could decide",
    )
    args = ap.parse_args()

    units = load_units(args.units)
    args.out.mkdir(parents=True, exist_ok=True)

    absent = missing_compilers(units, args.vendor)
    for version, sources in sorted(absent.items()):
        for src in sources:
            print(f"{src}: compiler GC/{version} missing", file=sys.stderr)
    if absent:
        print(
            f"run: python tools/fetch_toolchain.py --versions {','.join(sorted(absent))}",
            file=sys.stderr,
        )

    failures = unverified = matched = 0
    for src, version, flags in units:
        cc = args.vendor / version / "mwcceppc.exe"
        if not cc.exists():
            continue
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
        if check.returncode == MATCH:
            matched += 1
        elif check.returncode == UNVERIFIED:
            unverified += 1
        else:
            if check.stderr.strip():
                print(check.stderr.rstrip(), file=sys.stderr)
            failures += 1

    parts = [f"{matched} unit(s) fully verified"]
    if unverified:
        parts.append(f"{unverified} with words only a link can decide")
    if failures:
        parts.append(f"{failures} differ")
    if absent:
        parts.append(f"{sum(len(v) for v in absent.values())} not built (compiler missing)")
    print("; ".join(parts))

    if absent:
        return 2
    if failures or (args.strict and unverified):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
