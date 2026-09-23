#!/usr/bin/env python3
"""Generate a soak-test controller script: long, pseudo-random, repeatable play.

    python tools/soak.py --seed 7 --first 3200 --last 33000
    $env:SOA_PAD = (python tools/soak.py --seed 7)

Prints an `SOA_PAD` script: the presses that walk a Continue from the title
(so the run should load a save -- see HANDOFF, "Start a run from a save"),
then, from `--first` to `--last`, a stream of steps drawn from a fixed-seed
generator -- the stick held in one of eight directions for 40-120 frames (60%
of steps), A (25%), B (10%), or a visit to the menu and back out (5%).

What it is for: the censuses load every map, but only for ten or twenty seconds
each, and a map that loads can still fault minutes into play. Twenty minutes of
this in Esperanza on 2026-09-23 ran clean under `SOA_STRICT=1` and walked Vyse
through an exit into the next map -- the first map change in this project a
player's input made. Run it with `SOA_STRICT=1`, and the same seed replays the
same input, so a fault it finds can be repeated.
"""

import argparse

DIRECTIONS = [
    "sup",
    "sdown",
    "sleft",
    "sright",
    "sup+sleft",
    "sup+sright",
    "sdown+sleft",
    "sdown+sright",
]
CONTINUE = [
    "1600:start",
    "1640:a",
    "1800:start",
    "1840:a",
    "2000:start",
    "2040:a",
    "2240:a",
    "2440:a",
    "2640:a",
]
MAX_EVENTS = 1000  # si.c holds 1024; leave room


PAD = ["up#4", "down#4", "left#4", "right#4"]  # single steps: a plain press moves a menu two slots


def script(seed: int, first: int = 3200, last: int = 33000, battle: bool = False) -> str:
    """The pad script, as one string. Deterministic in its arguments.

    `battle` adds single-step d-pad presses to the mix, so the battle wheel
    turns to a random command before an A commits it -- Magic, Focus, S-move,
    Item, Guard and Run instead of the Attack it opens on. The default mix is
    unchanged, so a seed replays the script it always did."""
    if battle:
        return _battle(seed, first, last)
    state = seed

    def rnd(n: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF  # the C library's LCG
        return (state >> 8) % n

    ev, f = list(CONTINUE), first
    while f < last and len(ev) < MAX_EVENTS - 3:
        r = rnd(20)
        if r < 12:
            ev.append(f"{f}:{DIRECTIONS[rnd(8)]}#{40 + rnd(80)}")
            f += 130
        elif r < 17:
            ev.append(f"{f}:a")
            f += 50
        elif r < 19:
            ev.append(f"{f}:b")
            f += 50
        else:
            ev += [f"{f}:start", f"{f + 90}:b", f"{f + 160}:b"]
            f += 220
    return ",".join(ev)


def _battle(seed: int, first: int, last: int) -> str:
    """Stick 40%, A 35%, a d-pad single step 20%, B 5%. Steps are spaced 70
    frames or more: a single step that arrives while the wheel is still
    turning is dropped (FINDINGS: a third step 60 frames after the second)."""
    state = seed

    def rnd(n: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return (state >> 8) % n

    ev, f = list(CONTINUE), first
    while f < last and len(ev) < MAX_EVENTS - 1:
        r = rnd(20)
        if r < 8:
            ev.append(f"{f}:{DIRECTIONS[rnd(8)]}#{40 + rnd(80)}")
            f += 130
        elif r < 15:
            ev.append(f"{f}:a")
            f += 70
        elif r < 19:
            ev.append(f"{f}:{PAD[rnd(4)]}")
            f += 70
        else:
            ev.append(f"{f}:b")
            f += 70
    return ",".join(ev)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument(
        "--first", type=int, default=3200, help="first frame of random play (after the save loads)"
    )
    p.add_argument("--last", type=int, default=33000, help="no new step starts after this frame")
    p.add_argument(
        "--battle", action="store_true", help="add d-pad steps, to turn the battle wheel"
    )
    a = p.parse_args()
    print(script(a.seed, a.first, a.last, a.battle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
