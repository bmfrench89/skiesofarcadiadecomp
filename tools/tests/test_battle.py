"""R0's battle log checker (tools/battle.py, docs/specs/battle-harness.md),
on synthetic logs: each rule passes what it should and fails what it must."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import battle  # noqa: E402


def log(rows: list[tuple]) -> str:
    """rows of (base, original, returned[, element, mult, guard]), a damage line each."""
    out = []
    for i, row in enumerate(rows):
        b, o, r, e, m, g = (*row, 0, 10, 0)[:6] if len(row) == 3 else row
        out.append(
            f"[battle] frame {100 + i} damage {b} -> {o} -> {r} by slot 0 on slot 4 element {e} mult {m} guard {g}"
        )
    return "\n".join(out)


PLAIN = log([(100, 101, 101)] + [(50, 50, 50)] * 11)
DOUBLED = log([(100, 101, 202)] + [(50, 50, 100)] * 10 + [(6000, 6000, 9999)])


def test_the_plain_rule():
    assert battle.check(PLAIN, double=False, min_hits=10) == []
    bad = PLAIN.replace("-> 101 -> 101", "-> 101 -> 102", 1)  # the wrapper adding one
    assert any("returned 102 from 101" in f for f in battle.check(bad, double=False, min_hits=10))


def test_the_doubling_rule_and_its_clamp():
    assert battle.check(DOUBLED, double=True, min_hits=10) == []
    tripled = DOUBLED.replace("-> 101 -> 202", "-> 101 -> 303", 1)
    assert any("not 202" in f for f in battle.check(tripled, double=True, min_hits=10))
    assert battle.check(PLAIN, double=True, min_hits=10)  # undoubled values fail it


def test_too_few_hits_prove_nothing():
    few = log([(100, 101, 202)] * 3)
    assert any("fewer than 10" in f for f in battle.check(few, double=True, min_hits=10))
    assert any("fewer than 10" in f for f in battle.check("", double=True, min_hits=10))


def test_every_original_is_held_to_its_formula():
    filler = [(50, 50, 50)] * 11
    far = log([(100, 140, 140)] + filler)
    assert any("outside the formula's" in f for f in battle.check(far, double=False, min_hits=10))
    guarded = log([(100, 49, 49, 0, 10, 1)] + filler)  # halved by a Guard
    assert battle.check(guarded, double=False, min_hits=10) == []
    unguarded = log([(100, 49, 49, 0, 10, 0)] + filler)  # the same, with no Guard to halve it
    assert battle.check(unguarded, double=False, min_hits=10)
    resisted = log([(100, 50, 50, 2, 5, 0)] + filler)  # the target takes half of element 2
    assert battle.check(resisted, double=False, min_hits=10) == []
    past_five = log([(100, 101, 101, 7, 5, 0)] + filler)  # no multiplier past element 5
    assert battle.check(past_five, double=False, min_hits=10) == []
    assert battle.formula_range(battle.hits(log([(-20, 0, 0)]))[0]) == (
        0,
        1,
    )  # a negative base is 0
