# M17: the mod list's order, mods turned off, and conflicts

Written 2026-10-21 at main c01484b, from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) §F ("M17") and
[research/plan-gaps.md](../research/plan-gaps.md) ("A mod list with order and a conflict report"). PLAN-NEXT
§0's mod framework track, item 4 (D-38).

**Status: done 2026-10-21** but for M8's page (section 6), every Done line met on this PC; evidence in
FINDINGS "M17".

**Why.** Today a folder's name decides when its mod loads (`mod_load`'s `qsort` of the names), turning a mod
off means moving its folder out, and when two mods' patches write the same bytes the later one wins every
frame with no word said: `mod_frame` applies `g_patches` in load order with no overlap check. A player who
drops two mods into `mods\` cannot see that one undoes the other.

## 1. The order, and mods turned off

`SOA_MOD_ORDER` (soa.ini `mod_order`), a comma-separated list of mod ids (a manifest 1 mod, which has none,
by its folder's name):

```
mod_order = encounter-scale, encounters-off, -map-log
```

- The mods it names load first, in its order; the rest follow in folder-name order, as today.
- `-ID` turns that mod off: it is not read past its id, and the log says so once.
- A name that matches no mod in the folder is said once and passed over; a name given twice is said and its
  second place ignored.
- A mod that declares `overrides` (section 2) loads after every mod it names, whatever the list says, and the
  log says when that moved it. Two mods that override each other are both refused: which wins cannot be known.
- The ids are read before anything loads (a cheap pass over each `mod.ini` for `id` and `overrides`), so a
  mod's place never depends on what the mods before it did.

## 2. Two mods writing the same bytes

When a patch's bytes can meet a patch of a mod loaded earlier, the later mod is refused with both files and
lines, unless one of the two declares the other in `overrides`:

```
overrides = encounters-off            # manifest 2: the ids this mod's writes may land on
```

- **Bytes.** A direct patch writes `width` bytes at each target (`ea + z * stride` for each z). Two pointer
  patches through the same pointer word are compared the same way on their offsets. A direct patch and a
  pointer patch, or two through different pointer words, cannot be compared before the game runs; they are
  not refused, and the report keeps saying where each applied.
- **Conditions.** Two patches whose conditions cannot both hold are no conflict: `scene=6` against `scene=7`,
  `state=3` against `state=8`, `map=116a` against `map=117a`. A condition only one of them has can hold with
  anything. The trigger does not matter: `once` and `every_frame` can land on the same frame.
- Within one mod, overlapping patches stay the author's business, as today.
- Two patches writing the same value with the same width over the same targets are no conflict: neither
  undoes the other (two mods that both hold the step counter at 0, say).
- With `overrides` declared, the overriding mod loads after the other (section 1), so its write lands last
  each frame, and the log names the pair once at load: `[mod] encounter-scale/patches.txt:13 overrides
  encounters-off/patches.txt:21 at 80346D28`.
- `overrides` naming an id that is not loaded is fine (the mod may be absent) and says nothing.
- A DLL's writes are made at the call, not declared, so they are not compared; what a DLL registers is listed
  (section 3).

## 3. What each mod does, listed

At load, after the `loaded` line, one line per patch, `[mod] encounters-off writes, patches.txt:21:
every_frame u32 80346D28 = 00000000 when scene=6`, and for a DLL one line, `[mod] map-log registers: safe
point, map load, scene change`. The list is what a player or M8's page reads to see what a mod touches.

## 4. Replays

The recording's `mods=` entry already lists the mods in load order with their hashes (and M16's values), and
a replay whose line differs says so (`si.c`'s config comparison). Since the order is now the player's, that
line is how a replay is held to the recorded set; nothing more is added here.

## 5. Done

Each check's mutation is made, the check run and seen to fail, and the change put back.

1. **The order is the list's.** `test_mods.py`: three mods whose folders sort `a b c`, listed `c,a`, load
   `c a b` (the `describe` line's order); `-b` leaves `b` out with a line; an unknown and a repeated name are
   said. *Mutation:* ignore the list (folder order).
2. **soa.ini's `mod_order` reaches `SOA_MOD_ORDER`.** `test_settings.py`, and README lists the key.
   *Mutation:* the key's line dropped from `k_settings` (the setting test fails).
3. **A conflict refuses the later mod with both places.** `test_mods.py`: same word, same conditions;
   overlapping bytes of different widths (`u8` inside a `u32`); a `for` run hitting a direct target; two
   pointer patches through one pointer with overlapping offsets. *Mutation:* the overlap test always false.
4. **What is no conflict loads.** Conditions that cannot both hold, adjacent but not overlapping bytes, a
   direct and a pointer patch, one mod's own two patches. *Mutation:* the condition test always true.
5. **`overrides` lets it through, ordered.** The overriding mod, listed first, loads second, its value is the
   one left at the frame end, and the pair is logged; mutual overrides refuse both. *Mutation:* skip the
   reordering (the value left is the other mod's).
6. **The listing.** The writes and registers lines for a patch mod and a DLL. *Mutation:* none needed beyond
   the assertion; the lines are new text.
7. **On this PC, in the game.** `encounters-off` with a copy of it under another id is refused at load and
   names both lines; with `overrides` it loads, and `mod_order` puts `map-log` first in the describe line.

## 6. Not in M17

M8's page for the list (a pad-driven list, when M8 exists), dependency keys (`requires`), zip install, and
comparing DLL writes.
