"""tools/encounter_check.py: P1b's rules over mods/encounter-rate's trial lines.

Logs simulated from the roll's model pass; each fault the spec names fails.
"""

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import encounter_check as ec  # noqa: E402

M = {"0.5": 0.5, "1": 1.0, "2": 2.0, "0": 0.0, "hold": 0.0}


def lines(trials: list[ec.Trial]) -> str:
    return "".join(
        f"[mod] encounter-rate: trial {t.n} {t.kind} {t.zone0} {t.rate0} {t.zone1} {t.rate1} {t.moved} {t.end}\n"
        for t in trials
    )


def model_log(per_kind: int = 60, rate: int = 20, seed: int = 7) -> list[ec.Trial]:
    """Trials of each kind in turn, from the model, at one zone and rate."""
    rng = random.Random(seed)
    out = []
    for n in range(per_kind * len(ec.KINDS)):
        kind = ec.KINDS[n % len(ec.KINDS)]
        t = ec.simulate(M[kind], rate, rng)
        out.append(ec.Trial(n, kind, 3, rate, 3, rate, t.moved, t.end))
    return out


def verdict(trials, rate=20):
    return ec.judge(trials, rate)


def test_a_model_log_passes_at_rate_20_and_45():
    for rate in (20, 45):
        ok, why = verdict(model_log(rate=rate), rate)
        assert ok, why


def test_the_command_line_reads_a_log(tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_text("noise\n" + lines(model_log()), encoding="utf-8")
    assert ec.main([str(log)]) == 0
    out = capsys.readouterr().out
    assert "300 trial(s), 300 counted at rate 20, 0 stuck" in out and out.rstrip().endswith(
        "pass"
    ), out
    assert "fails the ordering rule" in out


def test_k_shuffled_fails():
    """The same trials with the nonzero kinds' labels shuffled: the ordering
    no longer holds (a mod that changed nothing looks like this)."""
    trials = model_log()
    kinds = [t.kind for t in trials if t.kind in ("0.5", "1", "2")]
    random.Random(3).shuffle(kinds)
    seq = iter(kinds)
    mixed = [
        ec.Trial(t.n, next(seq), t.zone0, t.rate0, t.zone1, t.rate1, t.moved, t.end)
        if t.kind in ("0.5", "1", "2")
        else t
        for t in trials
    ]
    ok, why = verdict(mixed)
    assert not ok and any("r(2) > r(1) > r(0.5) does not hold" in w for w in why), why


@pytest.mark.parametrize("kind", ["0", "hold"])
def test_a_battle_with_battles_off_fails(kind):
    trials = model_log()
    i = next(i for i, t in enumerate(trials) if t.kind == kind)
    t = trials[i]
    trials[i] = ec.Trial(t.n, kind, t.zone0, t.rate0, t.zone1, t.rate1, 200, "battle")
    ok, why = verdict(trials)
    assert not ok and any(f"k={kind}: trial {t.n} ended `battle`" in w for w in why), why


def test_39_counted_at_one_k_fails():
    trials = [t for t in model_log(per_kind=40)]
    drop = next(i for i, t in enumerate(trials) if t.kind == "2")
    del trials[drop]
    ok, why = verdict(trials)
    assert not ok and "FAIL: k=2 has 39 counted trials, under 40" in why, why


def test_eleven_percent_stuck_fails():
    trials = model_log()
    n = int(len(trials) * 0.11) + 1
    for t in trials[-n:]:
        t.end, t.moved = "stuck", 100
    ok, why = verdict(trials)
    assert not ok and any("trials stuck, over 10%" in w for w in why), why


def test_a_rate_0_zone_is_not_counted_as_rate_20():
    """Thirty k=2 trials at rate 20 and twenty in a rate-0 zone: only the
    thirty count, so k=2 is short. A check counting the rate-0 ones would
    pass the count."""
    trials = [t for t in model_log(per_kind=60) if t.kind != "2" or t.n < 150]
    k2 = [t for t in trials if t.kind == "2"]
    assert len(k2) == 30
    trials += [ec.Trial(1000 + i, "2", 1, 0, 1, 0, 600, "clear") for i in range(20)]
    ok, why = verdict(trials)
    assert not ok and "FAIL: k=2 has 30 counted trials, under 40" in why, why


def test_no_trial_lines_say_so():
    ok, why = verdict([])
    assert not ok and "SOA_ENCOUNTERS_TEST=1" in why[0]


def test_the_false_failure_figure_is_small_at_the_spec_s_counts():
    """The spec puts it near 0.2% at 40 trials a k and rate 20."""
    assert ec.false_failure({"0.5": 40, "1": 40, "2": 40}, 20, runs=300) < 0.03
