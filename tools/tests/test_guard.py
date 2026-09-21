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
