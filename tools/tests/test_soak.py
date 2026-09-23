"""tools/soak.py: the soak-test script has to repeat exactly and has to be one
si.c reads whole -- a fault found by seed 7 is only useful if seed 7 replays
the same presses, and a script si.c stops parsing halfway through would soak
nothing and say so only in the log."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import scenario  # noqa: E402
import soak  # noqa: E402


def test_the_same_seed_gives_the_same_script():
    assert soak.script(7) == soak.script(7)
    assert soak.script(7) != soak.script(11)


def test_the_script_passes_the_strict_pad_grammar():
    """parse_pad refuses everything si.c would stop at or silently drop."""
    for seed in (1, 7, 11, 12345):
        events = scenario.parse_pad(soak.script(seed))
        assert len(events) > 100, seed


def test_it_starts_with_the_continue_presses_and_stays_in_bounds():
    events = scenario.parse_pad(soak.script(7, first=3200, last=9000))
    frames = [e.frame for e in events]
    assert frames[:9] == [1600, 1640, 1800, 1840, 2000, 2040, 2240, 2440, 2640]
    assert all(3200 <= f < 9000 + 220 for f in frames[9:])
    assert frames == sorted(frames)


def test_it_never_exceeds_what_si_c_holds():
    """si.c keeps 1024 events and drops the rest without a word."""
    assert len(scenario.parse_pad(soak.script(3, first=3200, last=10**7))) <= 1000


def test_the_step_mix_is_the_documented_one():
    """Mostly stick, some A, less B, a few menu visits -- all four present."""
    text = soak.script(7, 3200, 60000)
    assert "#" in text and ":a," in text and ":b," in text and ":start," in text
