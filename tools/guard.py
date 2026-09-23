#!/usr/bin/env python3
"""Refuse to let game data into the repository.

SPEC.md section 2 says no disc images, executables, or extracted assets are ever
committed. This enforces that mechanically, in CI and as a local pre-commit hook:

    python tools/guard.py

Exits non-zero and names every offending file.
"""

import subprocess
import sys
from pathlib import Path

# Extensions that can only be game data. `.bin` is deliberately included: the
# only .bin files in this project's world are boot.bin / bi2.bin / fst.bin.
FORBIDDEN_SUFFIXES = {
    ".rvz",
    ".iso",
    ".gcm",
    ".ciso",
    ".wbfs",
    ".nkit",  # disc images
    ".dol",
    ".rel",
    ".elf",  # executables
    ".gvr",
    ".tpl",
    ".mld",
    ".mlk",
    ".mll",
    ".sml",  # game assets
    ".samp",
    ".dsp",
    ".sct",
    ".std",
    ".sst",
    ".tec",
    ".enp",
    ".ect",
    ".evp",
    ".lmt",
    ".bnr",
    ".bin",
    ".map",
}

# Directories that hold extracted or vendored material.
FORBIDDEN_DIRS = {
    "extracted",
    "orig",
    "assets",
    "game",
    "disc",
    "vendor",
    "refs",
    "gen",
    "build",
    "dist",
    "scratch",
}

# A tracked text file this large is almost certainly not source.
MAX_TRACKED_BYTES = 2 * 1024 * 1024

# The repository this file is in, which is the one it guards, wherever it is
# run from.
ROOT = Path(__file__).resolve().parents[1]


def tracked_files(root: Path) -> list[str]:
    """Every path git tracks under ``root``, exactly as git stores it.

    -z, because without it git C-quotes any path with a byte over 0x7F
    (core.quotepath is true by default): café.dol came back as
    "caf\\303\\251.dol", whose suffix is `.dol"`, and the guard passed it.
    Decoded as UTF-8 rather than the locale's code page, which on Windows
    would turn the name into one that is not on disk; surrogateescape keeps
    a name that is not UTF-8 at all round-trippable instead of fatal.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def main() -> int:
    problems: list[str] = []
    files = tracked_files(ROOT)

    for rel in files:
        path = Path(rel)

        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{rel}: forbidden extension '{path.suffix}' (game data)")

        for part in path.parts[:-1]:
            if part.lower() in FORBIDDEN_DIRS:
                problems.append(f"{rel}: lives under '{part}/', which must not be tracked")
                break

        # Measured under ROOT, not the working directory: relative to anywhere
        # else the path does not exist, and a file never found is never measured.
        if (ROOT / path).exists():
            size = (ROOT / path).stat().st_size
            if size > MAX_TRACKED_BYTES:
                problems.append(f"{rel}: {size:,} bytes exceeds the {MAX_TRACKED_BYTES:,} limit")

    if problems:
        print("GAME DATA GUARD FAILED\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nThis repository contains code only. Users supply their own disc dump.\n"
            "See docs/SPEC.md section 2.",
            file=sys.stderr,
        )
        return 1

    print(f"guard: {len(files)} tracked files, no game data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
