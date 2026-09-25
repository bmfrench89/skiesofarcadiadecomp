#!/usr/bin/env python3
"""Refuse to let game data into the repository.

SPEC.md section 2 says no disc images, executables, or extracted assets are ever
committed. This enforces that mechanically, in CI and as a local pre-commit hook:

    python tools/guard.py

Exits non-zero and names every offending file.
"""

import subprocess
import sys
import threading
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
    # What the port writes from the game while it runs (2026-09-24, PLAN S2):
    # memory-card images, command-stream captures and their register and RAM
    # images, recorded audio and rendered frames. Each carries the game's own
    # data, and none is ever tracked.
    ".raw",
    ".fifo",
    ".regs",
    ".ram",
    ".wav",
    ".png",
    # What mods, packs and saves would carry (2026-09-25, PLAN-GAMEPLAY-MODS
    # T0): a memory-card save exported whole in the three formats Dolphin and
    # GCMM write, texture-pack images, the game's table and archive data, and
    # audio in the formats a music pack would use.
    ".gci",
    ".gcs",
    ".sav",
    ".dds",
    ".dat",
    ".ogg",
    ".flac",
    ".mp3",
    ".opus",
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
    # Where packs, dumps, host blobs, photos and tool output go (T0): texture
    # packs and dumps are the game's images -- Dolphin lays packs out under
    # load/ and dumps under dump/ -- a host blob is a save's mod data, and a
    # photo is a capture with a 24 MB RAM image.
    "packs",
    "load",
    "dumps",
    "dump",
    "blobs",
    "photos",
    "out",
}

# A mod in this repository is text (PLAN-GAMEPLAY-MODS.md, rule 3): its edits,
# keyed by entry, and its wholly new entries, with every binary built on the
# player's machine from their own disc. So in a folder holding a mod.ini a file
# that is not UTF-8 text is refused, whatever its name says it is. Whether a
# table is edits or a whole column of the game's is T5's to judge, once it has
# written the columns down.

# How game data begins, for a binary file anywhere in the tree -- or anywhere
# in history -- whose name does not give it away (T0): renaming defeats a
# suffix list, and does not defeat this. A file with no NUL in its first 8 KB
# is text and is not judged -- tools/soa/aklz.py and these documents name the
# signatures. A RAM image from a capture begins with low memory, which holds
# the disc ID, so GEAE8P catches a renamed .ram (build/fifo/0100.ram does,
# 2026-09-25). A capture's .fifo and .regs are raw command and register bytes
# with no header, and nothing here recognises one renamed: only its name, and
# the build/ directory it is written to, keep it out.
SIGNATURES = (
    (b"AKLZ~?Qd", "the game's compression (AKLZ)"),
    (b"GCIX", "a GVR texture"),
    (b"GBIX", "a GVR texture"),
    (b"GEAE8P", "the game's code at offset 0: a .gci or disc header"),
    (b"GCSAVE", "a GCS card save"),
    (b"DATELGC_SAVE", "a SAV card save"),
    (b"\x89PNG\r\n\x1a\n", "a PNG"),
    (b"DDS ", "a DDS texture"),
    (b"OggS", "Ogg audio"),
    (b"fLaC", "FLAC audio"),
    (b"ID3", "MP3 audio"),
)

# A memory card image begins with its scrambled serial, which no signature can
# match. Its directory is blocks 1 and 2 (a block is 0x2000 bytes), each 127
# entries of 64 bytes and then the block's counter and checksums, and an entry
# begins with the game code of the save it names: GEAE8P, for this game's.
CARD_DIRECTORIES = (0x2000, 0x4000)
CARD_ENTRIES = 127
# How much of a file the content check reads: through both directory blocks.
# No length is required of the file -- a truncated card image that still holds
# its directory is still the save.
HEAD_BYTES = 0x6000

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


def forbidden_suffix(name: str) -> str | None:
    """The first suffix of the file name ``name`` that is forbidden, in any
    case, wherever it sits in the name -- or None. Every suffix, not only the
    last: ``slotA.raw.bak``, a backup of a card image, is the card image.

    Each piece after a dot is a suffix, a leading dot included. Not
    Path.suffixes, which skips a name's leading dots (``.raw.txt`` has only
    ``.txt``) and whose answer for a name ending in a dot changed in Python
    3.14: CI's history grep sees ``.raw`` in both, and the two copies of the
    rule would disagree."""
    for piece in name.split(".")[1:]:
        if f".{piece.lower()}" in FORBIDDEN_SUFFIXES:
            return f".{piece}"
    return None


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


def mp3_frame(head: bytes) -> bool:
    """An MPEG audio layer III frame header at offset 0, which is how an MP3
    with no ID3 tag begins: eleven sync bits, a version that is not the
    reserved one, layer III, and a bitrate and sample rate that are not the
    invalid ones. Layer III and not any layer, because FF FE -- the sync bits
    and layer I -- is the byte-order mark a UTF-16 text file begins with."""
    if len(head) < 3 or head[0] != 0xFF:
        return False
    b1, b2 = head[1], head[2]
    return (
        b1 & 0xE0 == 0xE0  # the rest of the sync
        and b1 & 0x18 != 0x08  # version: 01 is reserved
        and b1 & 0x06 == 0x02  # layer: 01 is layer III
        and b2 >> 4 != 0xF  # bitrate index 1111 is invalid
        and b2 & 0x0C != 0x0C  # sample rate 11 is reserved
    )


def card_save(head: bytes) -> bool:
    """Whether ``head`` holds this game's code at the start of an entry in
    either directory block of a memory card image."""
    return any(
        head.startswith(b"GEAE8P", base + 64 * i)
        for base in CARD_DIRECTORIES
        for i in range(CARD_ENTRIES)
    )


def signature_of(head: bytes) -> str | None:
    """What game data ``head`` (a file's first HEAD_BYTES) begins as, if it is
    binary and begins as any: None for text or for anything else."""
    if b"\0" not in head[:8192]:
        return None
    for magic, what in SIGNATURES:
        if head.startswith(magic):
            return what
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "WAV audio"
    if mp3_frame(head):
        return "MP3 audio"
    if card_save(head):
        return "a memory card image holding this game's save"
    return None


NOT_TEXT = (
    "not text, in a mod folder -- a mod here is text, and its binaries are built from the "
    "player's own disc (PLAN-GAMEPLAY-MODS.md rule 3)"
)


def mod_folders(paths) -> set[Path]:
    """Every folder that holds a mod.ini among ``paths``."""
    return {Path(rel).parent for rel in paths if Path(rel).name.lower() == "mod.ini"}


def in_mod_folder(path: Path, mods: set[Path]) -> bool:
    return any(folder in path.parents for folder in mods)


def is_text(data: bytes) -> bool:
    """UTF-8 with no NUL. Bytes all below 0x80 decode whatever they are, so
    the NUL is the test that catches a dump of small numbers."""
    try:
        return "\0" not in data.decode("utf-8")
    except UnicodeDecodeError:
        return False


def content_problem(path: Path, data: bytes, mods: set[Path]) -> str | None:
    """What the content check refuses in ``data``, the bytes of the file at
    ``path``: its first HEAD_BYTES at least, and all of it in a mod folder."""
    what = signature_of(data[:HEAD_BYTES])
    if what:
        return f"begins as {what} -- game data, whatever it is named"
    if in_mod_folder(path, mods) and not is_text(data):
        return NOT_TEXT
    return None


def content_problems(root: Path, files: list[str]) -> list[str]:
    """The content check (T0). Every tracked file: binary and beginning as
    game data begins, whatever it is named. And in every folder holding a
    tracked mod.ini: any file that is not UTF-8 text."""
    mods = mod_folders(files)
    problems = []
    for rel in files:
        path = Path(rel)
        if not (root / path).is_file():
            continue
        with open(root / path, "rb") as fh:
            data = fh.read() if in_mod_folder(path, mods) else fh.read(HEAD_BYTES)
        problem = content_problem(path, data, mods)
        if problem:
            problems.append(f"{rel}: {problem}")
    return problems


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


def read_blobs(root: Path, blobs: list[str], whole: set[str]) -> dict[str, bytes]:
    """The first HEAD_BYTES of each of ``blobs`` -- all of it, for one in
    ``whole`` -- through one ``git cat-file --batch`` for the lot rather than
    a process per blob. A name git does not hold as a blob (a submodule's
    commit) is left out. The ids are fed from a thread: git answers as it
    reads, and a pipe left full on either side would hang both."""
    proc = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )

    def feed() -> None:
        proc.stdin.write("".join(f"{b}\n" for b in blobs).encode())
        proc.stdin.close()

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    got = {}
    for _ in blobs:
        header = proc.stdout.readline().split()  # <id> blob <size>, or <id> missing
        if len(header) != 3:
            continue
        sha, kind, size = header[0].decode(), header[1], int(header[2])
        data = proc.stdout.read(size)
        proc.stdout.read(1)  # the newline after the content
        if kind == b"blob":
            got[sha] = data if sha in whole else data[:HEAD_BYTES]
    writer.join()
    proc.stdout.close()
    if proc.wait():
        raise subprocess.CalledProcessError(proc.returncode, "git cat-file --batch")
    return got


def history_problems(root: Path, exempt: frozenset = HISTORY_EXEMPT) -> list[str]:
    """What guard.py would refuse in the tree, applied to every blob history
    ever held: the suffixes, the directory names, and the content -- what a
    binary begins as, and in a folder that held a mod.ini at any point, a
    file that is not text. Size is CI's own step."""
    rows = history_blobs(root)
    mods = mod_folders(rel for _, _, rel in rows)
    problems, seen, judge = [], set(), []
    for commit, blob, rel in rows:
        if (blob, rel) in exempt or (blob, rel) in seen:
            continue
        seen.add((blob, rel))
        path = Path(rel)
        where = f"{rel} (blob {blob[:12]}, commit {commit[:12]})"
        suffix = forbidden_suffix(path.name)
        if suffix:
            problems.append(f"{where}: forbidden extension '{suffix}'")
        part = forbidden_dir(path)
        if part:
            problems.append(f"{where}: under '{part}/'")
        judge.append((where, blob, path))
    blobs = list(dict.fromkeys(blob for _, blob, _ in judge))
    whole = {blob for _, blob, path in judge if in_mod_folder(path, mods)}
    held = read_blobs(root, blobs, whole)
    for where, blob, path in judge:
        problem = content_problem(path, held.get(blob, b""), mods)
        if problem:
            problems.append(f"{where}: {problem}")
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

        suffix = forbidden_suffix(path.name)
        if suffix:
            problems.append(f"{rel}: forbidden extension '{suffix}' (game data)")

        part = forbidden_dir(path)
        if part:
            problems.append(f"{rel}: lives under '{part}/', which must not be tracked")

        # Measured under ROOT, not the working directory: relative to anywhere
        # else the path does not exist, and a file never found is never measured.
        if (ROOT / path).exists():
            size = (ROOT / path).stat().st_size
            if size > MAX_TRACKED_BYTES:
                problems.append(f"{rel}: {size:,} bytes exceeds the {MAX_TRACKED_BYTES:,} limit")

    problems += content_problems(ROOT, files)

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
