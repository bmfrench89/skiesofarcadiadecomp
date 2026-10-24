# T2: content ids claimed by name (the core)

Written 2026-10-24 for D-43 (the gameplay core, milestone 2: T2 after batch A), from
[PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) T2 and X2's [save-extension.md](save-extension.md).

**Built 2026-10-24** (FINDINGS "T2"): Done lines 1 to 4. *As built:*
- **The pool is 24,576 to 27,327, not the plan's 8,192 up** (K1, FINDINGS "K1"): the area maps' grids own flags
  as high as 24,255.
- **A damaged lock refuses only the mods that claim,** not every mod: a mod with no claim cannot be hurt by a bad
  number, and one whose files are already on the disc cannot be refused without stopping the run (I6's rule).
- **A mod that sets a flag must wait for the load:** the first try set it on the field before the Continue's load,
  and the game's restore (`fn_801A4354`'s `memcpy` from `0x801A451C`, frame 2648) put the saved block back over it.
  The test mod sets it after `on_load`, which is the pattern for any mod that writes saved game state.

**Why.** Two mods written by different people each want a story flag of their own. If both pick the same number by hand, they
corrupt each other silently. T2 lets a mod ask for a flag by name; the loader picks the number, the same one every
run on this install, and never hands it to anyone else.

## 1. What is there

- **Story flags** 0..27,327 at `story.flags` (`0x80310B3C`, 3,416 bytes, saved whole). The plan reserved 8,192 and up
  for mods; **K1 found that wrong** (FINDINGS "K1"): flags up to 24,255 hold the area maps' exploration grids, 256
  flags each, and 24,256 to 27,327 are touched by no grid, script or save. So T2 hands out **24,576 to 27,327**,
  and `tools/flagmap.py` checks that pool against the disc's grids.
- **mod.ini** (manifest 2) has `option` lines a mod declares; X2 gives each mod a save chunk filed under its id.
- No mod claims anything today.

## 2. What T2 adds

- **`claim = flag <name>`** in a manifest 2 mod.ini, as many as it needs; a name is lowercase letters, digits, `.`,
  `_` and `-`, under 48 characters. Other kinds (`map`, `item`, ship stages, opcode stubs, thunk slots) are refused by
  name until their slices need them.
- **`mods.lock`** beside the mods (`SOA_MODS`'s folder), a text file: `flag <mod id> <name> <number>` per claim and
  `next flag <n>`. A claim found there keeps its number; a new one takes `next`, which only rises: **a flag number is
  never reused**, even after its mod is removed. Written (temp then rename) only when it changes; a line it cannot
  read refuses every mod that claims (said with the file and line), since guessing would hand out a number a save
  already uses.
- **`claim(kind, name, &number)`**, an appended `SoaModApi` member: the calling mod's own claim, in its init or any
  callback; 0 for a name it did not claim.
- **The save carries the table:** at each save X2 writes a chunk `soa.claims` (ids beginning `soa.` are refused to
  mods), the lock's lines. At a load, each claim whose number in the save differs from this install's lock is
  reported, naming the mod, the name and both numbers; nothing is moved (the remap is T2's later half). A vanilla or
  Dolphin re-save drops the chunk, and the load then says the save names no claims.
- **The log:** `[mod] <id>: flag <name> is <n>` at load, `(new)` on a first claim.

## 3. Not in T2's core

The remap on load, the other kinds' pools, freeing small pools, patches.txt naming a claim, and K1's confirmation.

## 4. Done (core)

1. **Two independent mods, each claiming a flag, both load with different numbers,** recorded in `mods.lock`, and each
   reads its own through `claim`; a second run gives the same numbers; with the first mod removed, a third mod's new
   claim takes a number neither had (fake guest, `test_mods.py`).
2. **A mismatch is reported:** a save made where the lock gave a claim one number, loaded where it gives another,
   names the mod, the claim and both numbers (fake guest). *Mutation:* the same lock on both sides reports nothing.
3. **In the game:** a test mod claims a flag, sets it, and a save then a fresh Continue reads it back set, through the
   game's own save, the flag at its claimed number (the saved flag block peeked).
4. **A damaged lock refuses the mods that claim,** with its file and line, and loads the rest.
