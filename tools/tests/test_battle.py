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


# `rewards` (docs/specs/battle-mods.md 7): R4's and R3's check on on_rewards


def rewards_log(rows: list[tuple], last_phases: tuple = ()) -> str:
    """rows of (exp, exp', gold, gold', magic, magic'): a rewards line each,
    each followed by a victory's end line; then an end line per last phase."""
    out = []
    for i, (a, b, c, d, e, f) in enumerate(rows):
        out.append(
            f"[battle] frame {200 + i} rewards exp {a} -> {b} gold {c} -> {d} magic exp {e} -> {f}"
        )
        out.append(
            f"[battle] frame {300 + i} end: 900 frames, 3 rounds, 12 damage calls (10 nonzero), last phase 7"
        )
    for i, phase in enumerate(last_phases):
        out.append(
            f"[battle] frame {400 + i} end: 50 frames, 1 rounds, 0 damage calls (0 nonzero), last phase {phase}"
        )
    return "\n".join(out)


def ks(exp: str = "1", gold: str = "1", magic: str = "1") -> dict:
    return {
        "exp": battle.multipliers(exp),
        "gold": battle.multipliers(gold),
        "magic": battle.multipliers(magic),
    }


def test_rewards_at_x1_pair_each_value_with_itself():
    assert battle.check_rewards(rewards_log([(120, 120, 300, 300, 3, 3)]), ks()) == []
    added = rewards_log([(120, 121, 300, 300, 3, 3)])  # a mod that adds one at x1
    assert any("exp 120 -> 121, not 120" in f for f in battle.check_rewards(added, ks()))


def test_rewards_doubled_exactly():
    good = rewards_log([(120, 240, 301, 602, 3, 3)])
    assert battle.check_rewards(good, ks("2", "2")) == []
    assert battle.check_rewards(good, ks())  # held to x1, the doubled values fail
    off = rewards_log([(120, 241, 301, 602, 3, 3)])
    assert any("exp 120 -> 241, not 240" in f for f in battle.check_rewards(off, ks("2", "2")))


def test_rewards_round_down_at_each_mod_in_turn_and_keep_the_caps():
    # 1.25 then 2 (difficulty's Hard first, where mod_order puts it first):
    # 103 -> 128 -> 256, where 103 x 2.5 at once is 257; magic EXP 3 -> 3 -> 6
    hard_x2 = ks("1.25,2", "1.25,2", "1.25,2")
    assert battle.check_rewards(rewards_log([(103, 256, 1, 2, 3, 6)]), hard_x2) == []
    assert battle.check_rewards(rewards_log([(103, 257, 1, 2, 3, 6)]), hard_x2)
    assert battle.check_rewards(rewards_log([(103, 256, 1, 2, 3, 7)]), hard_x2)
    capped = rewards_log([(5, 10, 60_000_000, 99_999_999, 100, 127)])
    assert battle.check_rewards(capped, ks("2", "2", "2")) == []
    # each mod holds magic EXP to 127 after its own step: 40 x4 is 160, held to
    # 127, then x0.5 is 63 -- not 40 x 4 x 0.5 = 80
    held = rewards_log([(10, 10, 10, 10, 40, 63)])
    assert battle.check_rewards(held, ks(magic="4,0.5")) == []
    assert battle.check_rewards(rewards_log([(10, 10, 10, 10, 40, 80)]), ks(magic="4,0.5"))


def test_rewards_fire_once_a_victory_and_at_least_once():
    assert any("no rewards line" in f for f in battle.check_rewards("", ks()))
    one = rewards_log([(1, 1, 1, 1, 1, 1)], last_phases=(7,))  # two victories, one payout
    assert any("1 rewards line(s) for 2 victory(ies)" in f for f in battle.check_rewards(one, ks()))
    fled = rewards_log(
        [(1, 1, 1, 1, 1, 1)], last_phases=(9, 8)
    )  # an escape and a defeat pay nothing
    assert battle.check_rewards(fled, ks()) == []


def test_rewards_from_the_command_line(tmp_path):
    path = tmp_path / "battle.log"
    path.write_text(rewards_log([(120, 240, 301, 602, 3, 3)]), encoding="utf-8")
    assert battle.main(["rewards", str(path), "--exp", "2", "--gold", "2"]) == 0
    assert battle.main(["rewards", str(path)]) == 1


# ---- info: battle-info's rows and log against R0's own lines (R5) -----------


def info_log(r0: list[tuple], shows: list[tuple], extra: list[tuple] = ()) -> str:
    """R0's actor lines (frame, slot, hp, max, status), the mod's shows lines
    (frame, slot, hp, max) and any other lines (frame, text), in frame order as
    a run would print them."""
    lines = (
        [
            (f, f"[battle] frame {f} slot {s} hp {hp}/{mx} mp 0 status {st:08X}")
            for f, s, hp, mx, st in r0
        ]
        + [(f, f"[mod] battle-info: frame {f}: slot {s} shows {hp}/{mx}") for f, s, hp, mx in shows]
        + list(extra)
    )
    return "\n".join(text for _, text in sorted(lines, key=lambda x: x[0])) + "\n"


def hit(frame: int, by: int, on: int, value: int) -> tuple:
    return (
        frame,
        f"[battle] frame {frame} damage {value} -> {value} -> {value} by slot {by} on slot {on} "
        "element 0 mult 10 guard 0",
    )


def says(frame: int, text: str) -> tuple:
    return (frame, f"[mod] battle-info: frame {frame}: {text}")


# the run's shape: a soldier at 58, struck to 28 by slot 1 (P2) and seen at
# 10500, and finished by slot 0 (P1) at 10679, knocked out in the same frame;
# R0 logs each a frame after the mod's frame end saw it
START = (9811, "[battle] frame 9811 start: battle 1 on map 000000C9")
R0 = [(9813, 4, 58, 58, 0), (10501, 4, 28, 58, 0), (10680, 4, 0, 58, 0x8100)]
SHOWN = [(9812, 4, 58, 58), (10500, 4, 28, 58)]
BLOWS = [hit(10450, 1, 4, 30), hit(10650, 0, 4, 43)]


def test_info_every_number_shown_is_r0_s_and_every_change_shown():
    assert battle.check_info(info_log(R0, SHOWN, [START])) == []
    # R0's knock-out line is no row: the filter passes over it (taken out, 0/58 is a change never shown)
    assert battle.check_info(info_log(R0, SHOWN)) == []


def test_info_a_number_shown_wrong_fails():
    off = SHOWN[:1] + [(10500, 4, 29, 58)]
    faults = battle.check_info(info_log(R0, off))
    assert any("slot 4 shown at 29/58" in f for f in faults), faults
    # the right HP over the wrong max: a record's max scaled (difficulty) and the row not told
    off = [(9812, 4, 58, 87)] + SHOWN[1:]
    faults = battle.check_info(info_log(R0, off))
    assert any("slot 4 shown at 58/87" in f for f in faults), faults


def test_info_a_change_never_shown_fails():
    """A row that froze at 58: R0's 28 is never shown."""
    faults = battle.check_info(info_log(R0, SHOWN[:1]))
    assert any("R0 has slot 4 at 28/58" in f for f in faults), faults


def test_info_another_slot_s_numbers_fail():
    r0 = R0 + [(9813, 5, 40, 40, 0)]
    faults = battle.check_info(info_log(r0, SHOWN + [(9812, 5, 58, 58)]))
    assert any("slot 5 shown at 58/58" in f for f in faults), faults


def test_info_a_row_for_a_fallen_enemy_fails():
    """The mod drawing 0/58 for a soldier R0 has knocked out in that frame."""
    faults = battle.check_info(info_log(R0, SHOWN + [(10679, 4, 0, 58)]))
    assert any("slot 4 shown at 0/58" in f for f in faults), faults


def test_info_with_no_row_shown_proves_nothing():
    faults = battle.check_info(info_log(R0, []))
    assert any("nothing is proved" in f for f in faults), faults


def test_info_a_row_may_come_a_frame_before_r0_s_line_or_with_it_never_after():
    for d, ok in ((0, True), (1, True), (2, False)):
        moved = [(f + d, s, hp, mx) for f, s, hp, mx in SHOWN]
        assert (battle.check_info(info_log(R0, moved)) == []) == ok, d


def test_info_starts_each_battle_afresh():
    """A second battle (R0's start line) whose soldier matches the first's
    last row: nothing drawn in it fails, a row drawn in it passes."""
    second = [(20000, "[battle] frame 20000 start: battle 2 on map 000000C9")]
    r0 = R0[:2] + [(20002, 5, 28, 58, 0)]
    shown = SHOWN + [(10500, 5, 28, 58)]  # slot 5 at 28 in the first battle
    r0 = r0 + [(10501, 5, 28, 58, 0)]
    faults = battle.check_info(info_log(r0, shown, [START, *second]))
    assert any("frame 20002: R0 has slot 5 at 28/58" in f for f in faults), faults
    assert battle.check_info(info_log(r0, shown + [(20001, 5, 28, 58)], [START, *second])) == []


def test_info_holds_the_log_to_r0():
    """Each blow the log tells: R0's change in that slot's HP, and its striker
    R0's last damage line on it since its HP last moved; a knock-out, R0's bit."""
    good = [says(10500, "P2 > A -30"), says(10679, "P1 > A -28"), says(10679, "A down")]
    assert battle.check_info(info_log(R0, SHOWN, [START, *BLOWS, *good])) == []
    for line, why in (
        (says(10500, "P1 > A -30"), "puts A's -30 to P1"),  # the wrong striker
        (says(10500, "P2 > A -31"), "the log says A -31"),  # the wrong amount
        (says(10500, "A -30"), "names no striker for A's -30"),  # a blow told as poison
        (says(10500, "A down"), "the log says A down"),  # not knocked out yet
    ):
        faults = battle.check_info(info_log(R0, SHOWN, [START, *BLOWS, line]))
        assert any(why in f for f in faults), (line, faults)


def test_info_holds_the_order_to_r0():
    """Each order the mod shows: a suffix of R0's latest order, the fallen
    left out -- A knocked out at 10680 leaves B alone at the end."""
    order = [(10503, "[battle] frame 10503 order 1 0 5 4")]
    r0 = R0 + [(9813, 0, 420, 420, 0), (9813, 1, 360, 360, 0), (9813, 5, 58, 58, 0)]
    shown = SHOWN + [(9812, 5, 58, 58)]
    good = [says(10502, "order P2 P1 B A"), says(10600, "order P1 B A"), says(10700, "order B")]
    assert battle.check_info(info_log(r0, shown, [START, *order, *good])) == []
    for line in (says(10600, "order P1 P2 B A"), says(10700, "order B A")):
        faults = battle.check_info(info_log(r0, shown, [START, *order, line]))
        assert any("is no suffix of R0's" in f for f in faults), (line, faults)
