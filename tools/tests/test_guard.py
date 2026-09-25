"""The guard's lists, and the copy of them that lives in CI (PLAN G2).

`tools/guard.py` refuses a set of file extensions, directories and content,
and a size, in the *working tree*; `--history` applies the names and the
content to every blob history ever held. `.github/workflows/ci.yml` also
rescans every blob that has ever existed in bash, with the same suffixes
written out again as a regex and the same size written out again as a
number.

Two copies of a rule with nothing tying them together drift, and this pair
drifts silently in the direction that matters: a suffix added to `guard.py`
alone keeps new commits clean while history goes unscanned for it, and nothing
fails. They are identical today, and these tests are what will still be true
tomorrow.

Stdlib only, and no YAML parser: the workflow is read as text, which is what
the no-pip job can do and is also what keeps this test honest about the thing
CI actually runs rather than about a parsed abstraction of it.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import guard  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow():
    return WORKFLOW.read_text(encoding="utf-8")


def history_grep(workflow: str) -> re.Match:
    """CI's `grep -Ei '\\.(rvz|iso|...)(\\.[^/]*)?$'`: group 1 the whole
    pattern, group 2 the suffix list. Whatever follows the list is taken as
    it stands, and the next test judges it by what it matches."""
    m = re.search(r"grep -Ei '(\\\.\(([^)]*)\)[^']*)'", workflow)
    assert m, "no history-scan grep in ci.yml; has the step been rewritten?"
    return m


def test_the_history_scan_covers_exactly_the_suffixes_the_guard_refuses(workflow):
    """The grep's suffix list against guard.py's FORBIDDEN_SUFFIXES.

    A suffix in one and not the other is the whole failure this catches: in
    guard.py only, history is never scanned for it; in CI only, a file the
    guard happily tracks fails the build after it is pushed.
    """
    in_ci = set(history_grep(workflow).group(2).split("|"))
    in_guard = {s.lstrip(".") for s in guard.FORBIDDEN_SUFFIXES}
    assert in_ci == in_guard, (
        f"only in ci.yml: {sorted(in_ci - in_guard)}; only in guard.py: {sorted(in_guard - in_ci)}"
    )


@pytest.mark.parametrize(
    "path",
    [
        "cards/slotA.raw.bak",  # a backup of a card image is the card image
        "saves/slot.GCS.bak",
        "x.map.md",
        "a.b.dol",
        ".raw.txt",  # Path.suffixes would skip the leading dot; grep does not
        "a.raw.",
        "main.dol",
        "notes.txt",
        "x.mapper.c",  # a suffix is a whole piece, not a prefix of one
        "x.bin2",
        "dir.bin/x.c",  # a directory's name is not the file's
        "a.raw.d/b.txt",
        "src/game.c",
        "docs/refs.md",
    ],
)
def test_the_history_scan_applies_the_guard_suffix_rule(workflow, path):
    """The same list is not enough: the grep has to refuse the same *names*.
    It sees `blob <id> <size> <path>`, as cat-file prints it, and must agree
    with forbidden_suffix -- a suffix anywhere in the file's own name -- on
    each of these, the backup names that motivated it and the near misses."""
    grep = re.compile(history_grep(workflow).group(1), re.IGNORECASE)
    in_ci = grep.search(f"blob {'0' * 40} 1 {path}") is not None
    in_guard = guard.forbidden_suffix(Path(path).name) is not None
    assert in_ci == in_guard, (path, in_ci, in_guard)


def test_ci_scans_history_with_the_guard_itself(workflow):
    """The directory names and the suffixes, over every path any commit
    touched, are checked by guard.py --history rather than by a second copy
    of the rules in bash -- so there is no copy to drift."""
    assert "python tools/guard.py --history" in workflow


@pytest.mark.parametrize(
    "path,forbidden",
    [
        ("game/x.c", True),
        ("src/game/x.c", True),  # the case that bit: any depth
        ("src/Game/x.c", True),  # any case
        ("a/b/BUILD/c/d.txt", True),
        ("src/game.c", False),  # a file of that name is not a directory of it
        ("src/games/x.c", False),
        ("src/mygame/x.c", False),
        ("src/soa/gen.c", False),
        ("docs/refs.md", False),
        ("my game/x.c", False),  # a component with a space in it is not "game"
    ],
)
def test_a_forbidden_directory_is_any_directory_component(path, forbidden):
    assert (guard.forbidden_dir(Path(path)) is not None) == forbidden, path


def test_the_oversize_threshold_is_the_same_number_in_both(workflow):
    """guard.py caps a tracked file; CI caps a blob in history. Different
    limits would mean a file the guard accepts cannot be pushed."""
    m = re.search(r'\$1=="blob" && \$3 > (\d+)', workflow)
    assert m, "no oversized-blob awk in ci.yml; has the step been rewritten?"
    assert int(m.group(1)) == guard.MAX_TRACKED_BYTES


def test_the_guard_still_refuses_the_extensions_that_caused_it(workflow):
    """A handful that are not negotiable, named so that a rewrite of either
    list that quietly drops one fails here rather than in a leak. `.bin` is
    deliberate: the only .bin files in this project's world are boot.bin,
    bi2.bin and fst.bin."""
    for suffix in (".rvz", ".iso", ".gcm", ".dol", ".rel", ".elf", ".bin", ".dsp", ".gvr"):
        assert suffix in guard.FORBIDDEN_SUFFIXES, suffix


def test_every_forbidden_dir_is_matched_at_any_depth():
    """`src/game/...` is the case that bit: .gitignore has a bare `game/` rule
    matching at any depth, so a unit written there is untracked and `git add`
    says nothing. The guard has to treat a path *segment* as forbidden, not
    just a leading one."""
    assert "game" in guard.FORBIDDEN_DIRS
    for name in ("extracted", "build", "gen", "scratch", "vendor"):
        assert name in guard.FORBIDDEN_DIRS, name


# --------------------------------------------------------------------------
# the guard run against a repository of its own
# --------------------------------------------------------------------------


def scratch_repo(root: Path, files: dict[str, bytes]) -> Path:
    """A throwaway repository with ``files`` staged. ls-files reads the index,
    so nothing needs committing, and no identity needs configuring."""
    root.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q")
    # git's own default, written down: a machine that sets core.quotepath=false
    # globally would otherwise hide the failure the next test exists for.
    git("config", "core.quotepath", "true")
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git("add", "-A")
    return root


def test_a_name_git_would_quote_is_still_seen_for_what_it_is(tmp_path, monkeypatch, capsys):
    """`git ls-files` without -z C-quotes any path with a byte over 0x7F, so
    café.dol came back as "caf\\303\\251.dol" -- whose suffix is `.dol"`, which
    is on no list, and the guard passed a disc executable."""
    repo = scratch_repo(tmp_path / "repo", {"café.dol": b"x", "src/ok.c": b"int x;\n"})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "café.dol: forbidden extension" in err
    assert "ok.c" not in err


def test_the_guard_reads_its_own_repository_from_anywhere(tmp_path, monkeypatch, capsys):
    """git ran in the caller's working directory, and the size check stat()ed
    each path relative to it as well: run from anywhere but the root, the
    guard listed some other repository, or failed, and a path that did not
    resolve was never measured at all."""
    repo = scratch_repo(
        tmp_path / "repo",
        {"game/notes.txt": b"x", "big.txt": b"0" * (guard.MAX_TRACKED_BYTES + 1)},
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "game/notes.txt: lives under 'game/'" in err
    assert "big.txt:" in err and "exceeds" in err


# --------------------------------------------------------------------------
# guard.py --history, against a history of its own
# --------------------------------------------------------------------------


def history_repo(root: Path, steps: list[dict[str, bytes | None]]) -> Path:
    """A repository with one commit per step; None deletes a path."""
    root.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    for n, step in enumerate(steps):
        for rel, data in step.items():
            path = root / rel
            if data is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        git("add", "-A")
        git("commit", "-q", "--allow-empty", "-m", f"step {n}")
    return root


def blob_of(repo: Path, data: bytes) -> str:
    return (
        subprocess.run(
            ["git", "hash-object", "--stdin"], cwd=repo, input=data, capture_output=True, check=True
        )
        .stdout.decode()
        .strip()
    )


def test_a_file_deleted_later_is_still_found(tmp_path):
    """The reason history is scanned at all: a later commit cannot undo a
    leak, and the tree check sees only the last commit."""
    repo = history_repo(
        tmp_path / "r", [{"game/notes.txt": b"x", "ok.c": b"1"}, {"game/notes.txt": None}]
    )
    problems = guard.history_problems(repo, frozenset())
    assert len(problems) == 1 and "game/notes.txt" in problems[0] and "under 'game/'" in problems[0]


def test_a_file_renamed_through_a_forbidden_name_is_found(tmp_path):
    """The case rev-list --objects misses: the same bytes under an innocent
    name and a forbidden one are one object, reported once, under whichever
    path was reached first."""
    repo = history_repo(
        tmp_path / "r",
        [
            {"notes.txt": b"same bytes"},
            {"notes.txt": None, "main.dol": b"same bytes"},
            {"main.dol": None, "notes.txt": b"same bytes"},
        ],
    )
    problems = guard.history_problems(repo, frozenset())
    assert any("main.dol" in p and "forbidden extension" in p for p in problems), problems


def test_an_exempt_blob_passes_and_new_bytes_at_its_path_do_not(tmp_path):
    """HISTORY_EXEMPT is keyed by content as well as name, so the reviewed
    file stays allowed and anything else written to that name is refused."""
    repo = history_repo(
        tmp_path / "r", [{"scratch/a.py": b"reviewed"}, {"scratch/a.py": b"something new"}]
    )
    exempt = frozenset({(blob_of(repo, b"reviewed"), "scratch/a.py")})
    problems = guard.history_problems(repo, exempt)
    assert len(problems) == 1 and blob_of(repo, b"something new")[:12] in problems[0], problems


def test_a_clean_history_is_clean(tmp_path):
    repo = history_repo(tmp_path / "r", [{"src/a.c": b"1"}, {"src/a.c": b"2", "docs/b.md": b"3"}])
    assert guard.history_problems(repo, frozenset()) == []


def test_this_repository_history_passes_and_every_exemption_is_used():
    """Every entry in HISTORY_EXEMPT names a blob history really holds at that
    path -- an exemption nothing needs is a hole waiting for a file. Skipped in
    a shallow clone, which does not have the commits to check."""
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if shallow != "false":
        pytest.skip("a shallow clone does not hold the history")
    assert guard.history_problems(ROOT) == []
    held = {(blob, rel) for _, blob, rel in guard.history_blobs(ROOT)}
    assert held >= guard.HISTORY_EXEMPT, sorted(guard.HISTORY_EXEMPT - held)


def test_the_files_the_port_writes_while_it_runs_are_refused(tmp_path, monkeypatch, capsys):
    """Card images, command-stream captures with their register and RAM images,
    recorded audio and rendered frames all carry the game's own data; the soak
    and benchmark work of 2026-09-24 made hundreds of them (PLAN S2)."""
    names = [
        "cards/slot.raw",
        "cap/5000.fifo",
        "cap/5000.regs",
        "cap/5000.ram",
        "out.wav",
        "frames/0100.png",
    ]
    repo = scratch_repo(tmp_path / "repo", {n: b"x" for n in names})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    for n in names:
        assert f"{n}: forbidden extension" in err, n


# --------------------------------------------------------------------------
# T0 (PLAN-GAMEPLAY-MODS.md): what mods, packs and saves would carry, and the
# content check on mod folders
# --------------------------------------------------------------------------


def test_what_mods_packs_and_saves_would_carry_is_refused(tmp_path, monkeypatch, capsys):
    names = [
        "saves/slot.gci",
        "saves/slot.gcs",
        "saves/slot.sav",
        "texpack/a.dds",
        "tables/enemies.dat",
        "music/a.ogg",
        "music/b.flac",
        "music/c.mp3",
        "music/d.opus",
    ]
    repo = scratch_repo(tmp_path / "repo", {n: b"x" for n in names})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    for n in names:
        assert f"{n}: forbidden extension" in err, n


@pytest.mark.parametrize("name", ["packs", "load", "dumps", "dump", "blobs", "photos", "out"])
def test_the_pack_load_dump_blob_photo_and_out_folders_are_refused(name):
    assert guard.forbidden_dir(Path(f"a/{name}/b/c.txt")) is not None
    assert guard.forbidden_dir(Path(f"{name.upper()}/c.txt")) is not None
    assert guard.forbidden_dir(Path(f"docs/{name}.md")) is None


MOD_INI = b"manifest = 2\nid = m\nversion = 1\nname = m\napi = 1\ndol_sha1 = 0\n"


def test_a_dump_in_a_mod_folder_is_refused_whatever_it_is_named(tmp_path, monkeypatch, capsys):
    """Binary bytes with no signature the tree check knows -- a raw table
    dump, say -- renamed to .txt: the suffix list cannot see it, and a mod
    folder, which holds only text, refuses it. The same bytes outside a mod
    folder are not this rule's to judge."""
    dump = b"\x00\x02\x01\xf4\x00\x64\x00\x00" + bytes(range(256))
    repo = scratch_repo(
        tmp_path / "repo",
        {
            "mods/m/mod.ini": MOD_INI,
            "mods/m/patches.txt": b"once 0x80346d28 = 0\n",
            "mods/m/notes.txt": dump,
            "docs/sample.txt": dump,
        },
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "mods/m/notes.txt: not text, in a mod folder" in err, err
    assert "patches.txt" not in err and "docs/sample.txt" not in err, err


def test_a_dump_of_small_numbers_in_a_mod_folder_is_refused(tmp_path, monkeypatch, capsys):
    """Every byte below 0x80 is valid UTF-8, so a dump of small numbers
    decodes; the NULs in it are what make it not text. The fixture above
    fails to decode at all, so it cannot tell whether the NUL test is there."""
    dump = b"\x00\x02\x01\x44\x00\x64" * 8
    dump.decode("utf-8")  # the point of the fixture
    repo = scratch_repo(tmp_path / "repo", {"mods/m/mod.ini": MOD_INI, "mods/m/stats.txt": dump})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    assert "mods/m/stats.txt: not text, in a mod folder" in capsys.readouterr().err


def test_a_backup_of_a_card_image_is_refused_by_name(tmp_path, monkeypatch, capsys):
    """Every suffix in a name counts, not only the last."""
    names = ["cards/slotA.raw.bak", "saves/slot.gcs.bak", "cap/5000.fifo.old"]
    repo = scratch_repo(tmp_path / "repo", {n: b"x" for n in names})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "cards/slotA.raw.bak: forbidden extension '.raw'" in err, err
    assert "saves/slot.gcs.bak: forbidden extension '.gcs'" in err, err
    assert "cap/5000.fifo.old: forbidden extension '.fifo'" in err, err


@pytest.mark.parametrize(
    "head, what",
    [
        (b"AKLZ~?Qd\x00\x01", "the game's compression (AKLZ)"),
        (b"GCIX\x00\x00\x00\x08", "a GVR texture"),
        (b"GEAE8P\x00\xff", "the game's code at offset 0"),
        (b"GCSAVE\x00\x00" + bytes(0x108) + b"GEAE8P", "a GCS card save"),
        (b"DATELGC_SAVE\x00\x00\x00\x00" + bytes(0x70) + b"GEAE8P", "a SAV card save"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "a PNG"),
        (b"DDS \x7c\x00\x00\x00", "a DDS texture"),
        (b"OggS\x00\x02", "Ogg audio"),
        (b"fLaC\x00\x00", "FLAC audio"),
        (b"ID3\x04\x00\x00", "MP3 audio"),
        (b"\xff\xfb\x90\x64", "MP3 audio"),  # MPEG-1 layer III, 128 kbit/s, 44.1 kHz
        (b"\xff\xf3\x64\xc4", "MP3 audio"),  # MPEG-2 layer III
        (b"RIFF\x24\x00\x00\x00WAVEfmt ", "WAV audio"),
    ],
    ids=[
        "aklz",
        "gvr",
        "gci",
        "gcs",
        "sav",
        "png",
        "dds",
        "ogg",
        "flac",
        "mp3-id3",
        "mp3-frame",
        "mp3-frame-mpeg2",
        "wav",
    ],
)
def test_binary_game_data_is_refused_whatever_it_is_named(
    tmp_path, monkeypatch, capsys, head, what
):
    repo = scratch_repo(
        tmp_path / "repo", {"notes/readme.txt": head + bytes(64), "src/ok.c": b"int x;\n"}
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert f"notes/readme.txt: begins as {what}" in err, err
    assert "ok.c" not in err, err


def test_text_that_names_a_signature_is_not_refused():
    """tools/soa/aklz.py names AKLZ~?Qd; a file with no NUL in its first 8 KB
    is text, whatever it begins with."""
    assert guard.signature_of(b"AKLZ~?Qd is the magic this module reads\n") is None
    assert guard.signature_of((ROOT / "tools" / "soa" / "aklz.py").read_bytes()) is None


def test_a_utf16_file_is_not_taken_for_an_mp3():
    """FF FE, a UTF-16 byte-order mark, is eleven sync bits and layer I; with
    a NUL after every ASCII character the file is binary, and only the layer
    tells it from an MP3's first frame."""
    assert guard.signature_of("guard notes\r\n".encode("utf-16")) is None
    assert guard.signature_of(b"\xff\xfe" + "notes".encode("utf-16-le")) is None


def card_image(entry: int, size: int = 0x10000) -> bytes:
    """A memory card image, cut short at ``size``: a scrambled serial, the
    header's zeroed fields, erased (0xFF) blocks, and a directory entry for
    this game's save written at ``entry``."""
    image = bytearray(b"\xff" * size)
    image[0:12] = bytes((i * 151 + 7) & 0xFF for i in range(12))  # the serial
    image[12:0x26] = bytes(0x26 - 12)
    image[entry : entry + 64] = b"GEAE8P\xff\x02" + b"skies_save".ljust(32, b"\0") + bytes(24)
    return bytes(image)


@pytest.mark.parametrize(
    "entry",
    [0x2000 + 64 * 3, 0x2000, 0x4000 + 64 * 126],
    ids=["dir1-entry3", "dir1-entry0", "dir2-last-entry"],
)
def test_a_card_image_holding_this_games_save_is_refused_whatever_it_is_named(
    tmp_path, monkeypatch, capsys, entry
):
    """A card image begins with its scrambled serial, which no signature can
    match; its directory is what gives it away. Cut to 64 KB, which is no
    card's size: a truncated image still holds the save."""
    repo = scratch_repo(tmp_path / "repo", {"notes/card.txt": card_image(entry)})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 1
    err = capsys.readouterr().err
    assert "notes/card.txt: begins as a memory card image holding this game's save" in err, err


@pytest.mark.parametrize(
    "entry",
    [0x2000 + 64 * 3 + 8, 0x2000 + 64 * 127, 0x4000 + 64 * 127, 0x6000, 0x1000],
    ids=["mid-entry", "dir1-tail", "dir2-tail", "block3", "block0"],
)
def test_the_game_code_off_a_directory_entry_is_not_a_card_save(
    tmp_path, monkeypatch, capsys, entry
):
    """The same bytes with GEAE8P anywhere but the start of an entry: inside
    one, in either block's last 64 bytes (its counter and checksums, not an
    entry), in block 3 (the allocation table) or in the header block."""
    repo = scratch_repo(tmp_path / "repo", {"notes/card.txt": card_image(entry)})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(guard, "ROOT", repo, raising=False)
    assert guard.main() == 0, capsys.readouterr().err


def test_a_renamed_binary_added_and_deleted_is_found_in_history(tmp_path):
    """The content check over history, not only the tree: a PNG named .txt,
    added in one commit and deleted in the next, is published all the same."""
    png = b"\x89PNG\r\n\x1a\n" + bytes(64)
    repo = history_repo(
        tmp_path / "r",
        [{"notes/shot.txt": png, "ok.c": b"int x;\n"}, {"notes/shot.txt": None}],
    )
    problems = guard.history_problems(repo, frozenset())
    assert len(problems) == 1, problems
    assert problems[0].startswith(f"notes/shot.txt (blob {blob_of(repo, png)[:12]}, commit ")
    assert problems[0].endswith("begins as a PNG -- game data, whatever it is named"), problems


def test_a_card_image_and_a_backup_name_are_found_in_history(tmp_path):
    repo = history_repo(
        tmp_path / "r",
        [{"notes/card.txt": card_image(0x2000 + 64 * 3), "b/slotA.raw.bak": b"x"}, {}],
    )
    problems = guard.history_problems(repo, frozenset())
    assert any(
        p.startswith("notes/card.txt") and "a memory card image holding this game's save" in p
        for p in problems
    ), problems
    assert any(
        p.startswith("b/slotA.raw.bak") and "forbidden extension '.raw'" in p for p in problems
    ), problems


def test_a_binary_in_a_mod_folder_is_found_in_history(tmp_path):
    """A folder that held a mod.ini at any point is a mod folder for every
    blob history put in it -- here one added before the mod.ini and deleted
    with it. The same bytes outside it are not this rule's to judge."""
    dump = b"\x00\x02\x01\x44\x00\x64" * 8
    repo = history_repo(
        tmp_path / "r",
        [
            {"mods/m/stats.txt": dump, "docs/sample.txt": dump},
            {"mods/m/mod.ini": MOD_INI, "mods/m/patches.txt": b"once 0x80346d28 = 0\n"},
            {"mods/m/stats.txt": None, "mods/m/mod.ini": None},
        ],
    )
    problems = guard.history_problems(repo, frozenset())
    assert len(problems) == 1, problems
    assert problems[0].startswith("mods/m/stats.txt (blob "), problems
    assert "not text, in a mod folder" in problems[0], problems


def test_an_exempt_blob_is_not_judged_by_content(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + bytes(64)
    repo = history_repo(tmp_path / "r", [{"scratch/x.txt": png}, {"scratch/x.txt": None}])
    assert guard.history_problems(repo, frozenset({(blob_of(repo, png), "scratch/x.txt")})) == []


def test_this_repository_mod_folders_pass_the_content_check():
    assert guard.content_problems(ROOT, guard.tracked_files(ROOT)) == []
