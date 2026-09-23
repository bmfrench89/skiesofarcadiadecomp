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


def forbidden_dir(path: Path) -> str | None:
    """The first directory component of ``path`` that is forbidden, in any
    case, at any depth -- or None. The file's own name is not a directory:
    ``src/game.c`` is fine, ``src/game/x.c`` is not."""
    for part in path.parts[:-1]:
        if part.lower() in FORBIDDEN_DIRS:
            return part
    return None


# Blobs that published history holds under a forbidden directory and that were
# read, one by one, on 2026-09-23 and allowed to stay. All 24 were committed on
# 2026-09-15/16 and deleted in 9e4a955. Twenty-two are analysis scripts that
# read the DOL at run time and embed nothing from it; gather_pipe_functions.tsv
# is function addresses and store counts, which config/ publishes anyway;
# mnemonics.txt is an opcode census; f12000.txt is one frame's GX command
# stream decoded to register writes and draw *summaries* -- no vertex, texture,
# model, audio or text bytes. Rewriting public history to remove them would
# have changed every hash since 2026-09-15, which the documents cite. Keyed by
# blob as well as path, so a new file at one of these names is still refused.
HISTORY_EXEMPT = frozenset(
    {
        ("1b4948e8464f98d3965cd6f502b3a8119bd480bf", "scratch/gx/gp.py"),
        ("201eed81bb4928fd69e21f6fc81237824edbaf3e", "scratch/gx/gather_pipe_functions.tsv"),
        ("22ff93a43db3124cb4be4ab359614bf2bad143e9", "scratch/gx/mmio.py"),
        ("3dff40aceb41c88540739a35acc128a986c0c008", "scratch/gx/flow2.py"),
        ("43ac1ed6f138e4477342d6122c46f7dbab16d02f", "scratch/gx/gp2.py"),
        ("4e0a37312b03a24ce08c8a83116df64ba91e9e5e", "scratch/gx/layers.py"),
        ("51815a3372fd1838a7c15600f7b48bb73a3fc101", "scratch/gx/dasm.py"),
        ("53bc25e4c149074a79e5a7a337ab43875ac1e3e9", "scratch/gx/regions.py"),
        ("5ded07c80c2de8c0a802de9e93dbb26c2b5e10ed", "scratch/gx/callgraph.py"),
        ("667f448e6139475a2b0b8b9bbfc35230c169dd93", "scratch/gx/globals.py"),
        ("7116f8e7632d10d5e3c448069b0c66f443694dc9", "scratch/gx/gxapi.py"),
        ("720f773008d0c922d3428770b0d86ac9561b1a54", "scratch/gx/flow3.py"),
        ("73c71987e9fb63cfe7b6cdf9e39ff275f8159dce", "scratch/gx/mnemonics.txt"),
        ("79df93c7d3a30d73654a0a84ab7aa6936ecda27b", "scratch/gx/regions3.py"),
        ("864a43fa3f964633914de281bd4251b288f339cb", "scratch/f12000.txt"),
        ("96c6e729be04fa9ae2adca4c4db5103e3d5807af", "scratch/gx/xcheck.py"),
        ("9ab5fc68cfb8729179b95d1252720fa3e48b8c5a", "scratch/gx/mmio2.py"),
        ("bc12da13e033a1445bda7d02ce91b33fbb16e28a", "scratch/gx/strings.py"),
        ("bc86e299401bea43ccc739adb12f6d46a8e678a7", "scratch/gx/gp3.py"),
        ("bfef12a38e68644bed1bbd08e3dc57644d1b4197", "scratch/gx/opcodes.py"),
        ("cd8929c505b91dd4ccc0c7cbfb4bad799071e7c8", "scratch/gx/flow.py"),
        ("eb9bb5dcc19201310d7764b8c2a2a7da60a96012", "scratch/gx/tables.py"),
        ("f341ded8131bc3cda13e92c1230bcab4434fbac4", "scratch/gx/sda.py"),
        ("f6983ef64432fdf045405243cd5c53f4f414ade8", "scratch/gx/lis.py"),
    }
)


def history_blobs(root: Path) -> list[tuple[str, str, str]]:
    """(commit, blob, path) for every file any commit on any ref added or
    changed. Every path history has ever held is in here: a path in a commit's
    tree was put there by that commit or an ancestor, so the first-parent diffs,
    with the roots shown whole, cover them all. Not ``rev-list --objects``,
    which names each blob once, under the first path it was reached by -- so a
    file renamed to ``main.dol`` and back, or bytes that also sit at an
    innocent path, were scanned under the innocent name. Deletions are left
    out: removing a file is never the leak."""
    out = subprocess.run(
        [
            "git",
            "log",
            "--all",
            "--format=@%H",
            "--raw",
            "--no-renames",
            "--no-abbrev",
            "--diff-merges=first-parent",
            "--root",
            "-z",
        ],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", "surrogateescape")
    toks = out.split("\0")
    rows, commit, i = [], "", 0
    while i < len(toks):
        tok = toks[i].lstrip("\n")
        if tok.startswith("@"):
            commit = tok[1:]
        elif tok.startswith(":") and i + 1 < len(toks):
            meta = tok[1:].split()  # old mode, new mode, old blob, new blob, status
            if not meta[4].startswith("D"):
                rows.append((commit, meta[3], toks[i + 1]))
            i += 1
        i += 1
    return rows


def history_problems(root: Path, exempt: frozenset = HISTORY_EXEMPT) -> list[str]:
    """What guard.py would refuse in the tree, applied to every blob history
    ever held: the suffixes and the directory names. Size is CI's own step."""
    problems, seen = [], set()
    for commit, blob, rel in history_blobs(root):
        if (blob, rel) in exempt or (blob, rel) in seen:
            continue
        seen.add((blob, rel))
        path = Path(rel)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(
                f"{rel} (blob {blob[:12]}, commit {commit[:12]}): forbidden extension '{path.suffix}'"
            )
        part = forbidden_dir(path)
        if part:
            problems.append(f"{rel} (blob {blob[:12]}, commit {commit[:12]}): under '{part}/'")
    return problems


def main() -> int:
    if sys.argv[1:] == ["--history"]:
        problems = history_problems(ROOT)
        if problems:
            print("GAME DATA GUARD FAILED: history holds\n", file=sys.stderr)
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            print(
                "\nA later commit cannot undo this. See HISTORY_EXEMPT in tools/guard.py.",
                file=sys.stderr,
            )
            return 1
        print(
            f"guard: {len(history_blobs(ROOT))} files added or changed in history, none forbidden "
            f"({len(HISTORY_EXEMPT)} reviewed and exempt)"
        )
        return 0

    problems: list[str] = []
    files = tracked_files(ROOT)

    for rel in files:
        path = Path(rel)

        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{rel}: forbidden extension '{path.suffix}' (game data)")

        part = forbidden_dir(path)
        if part:
            problems.append(f"{rel}: lives under '{part}/', which must not be tracked")

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
