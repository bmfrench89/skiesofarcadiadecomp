"""The guard's lists, and the copy of them that lives in CI (PLAN G2).

`tools/guard.py` refuses a set of file extensions and a size, and checks only
the *working tree*. A file removed in a later commit still sits in history, so
`.github/workflows/ci.yml` rescans every blob that has ever existed -- and it
does that in bash, with the same suffixes written out again as a regex and the
same size written out again as a number.

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


def test_the_history_scan_covers_exactly_the_suffixes_the_guard_refuses(workflow):
    """`grep -Ei '\\.(rvz|iso|...)$'` against guard.py's FORBIDDEN_SUFFIXES.

    A suffix in one and not the other is the whole failure this catches: in
    guard.py only, history is never scanned for it; in CI only, a file the
    guard happily tracks fails the build after it is pushed.
    """
    m = re.search(r"grep -Ei '\\\.\(([^)]*)\)\$'", workflow)
    assert m, "no history-scan grep in ci.yml; has the step been rewritten?"
    in_ci = set(m.group(1).split("|"))
    in_guard = {s.lstrip(".") for s in guard.FORBIDDEN_SUFFIXES}
    assert in_ci == in_guard, (
        f"only in ci.yml: {sorted(in_ci - in_guard)}; only in guard.py: {sorted(in_guard - in_ci)}"
    )


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
