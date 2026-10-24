# M7b: the debug actions, from the menu and headless

Written 2026-10-24 after M7a, from [PLAN-60FPS-MODS.md](../PLAN-60FPS-MODS.md) M7b, research/mods.md §3's debug-menu
row and the FINDINGS recipes each action repeats.

**Built 2026-10-24** (FINDINGS "M7b"): Done lines 1 to 5. *As built:* the fade fix's black field was made by
turning the fade out with a poke, not by the battle the old recipe used (its timing has moved since); 189 maps are
warpable, the census's field maps.

**Why.** Every one of these exists today only as a hand-written `SOA_POKE` from a recipe. A player stuck behind a
black screen, or who wants to revisit a town, should not need one; a test should not have to spell three pokes.

## 1. What is there [V, each a FINDINGS recipe]

- **Warp by name:** the script name "MEnnnX.SCT" in `warp.script` (`0x80305CF0`, three words), `sys15` = 0 (the
  map's default entrance), then `field.state` = 15, the game's own warp, last (FINDINGS 1144-1200; `soak.py`'s
  `pokes`). 255 maps have both a script and geometry (`121e` and `561a` lack the geometry); the 5xx are ship-battle
  stages, which start through op 210, not a warp. Never the old stage-select route (field state 2), which skips the
  teardown.
- **Part select:** a warp to `355a`, the developers' part menu (FINDINGS "ME355A.SCT").
- **The ending:** `story.vars` B[76] = 'L' (`0x80310A68` = `0x4C000000`) on the field; state 8 then goes to the staff
  roll, scene 9 (FINDINGS 1296-1311).
- **The fade fix:** `0x80347518` = 0, the screen fade's direction, after a map load left it black (FINDINGS
  1336-1352).
- **Encounters off:** `encounter.steps` = 0 every frame keeps the roll from succeeding (research/mods.md §3; the
  `encounters-off` example mod does it as a patch).
- **The forced battle** is R0's `SOA_BATTLE_FORCE`, kept for debugging only; the tick unlock is M11's.

## 2. What M7b adds

- **`runtime/actions.c`**, a queue drained at the safe point, each action refused with its reason when the field is
  not quiet (M7a's test) or the target is not one it can reach:
  - `warp:NNNx` (a map of `warp_maps.h`, a 5xx refused), `part`, `ending`, `fade`, `encounters:off`, `encounters:on`;
  - from `SOA_ACTION=NAME[:ARG]@F[,...]` for tests, and from the menu.
- **`runtime/warp_maps.h`**, generated with `save_point_maps.h` by `tools/savenow.py` from the disc: the maps with
  both a script and geometry, below 500.
- **The menu's Debug page** (Main > Debug): Warp, with the map chosen by left and right (a tenth of the list with the
  shoulders) and taken with A; Part select; Fade fix; Encounters on or off; The ending. Taking one closes the menu.

## 3. Not in M7b

The map names on the warp row (the picker's table at `0x802E4780` is Shift-JIS; the menu's font is ASCII), the
forced battle and the tick unlock on the menu, and the ship battles.

## 4. Done

1. **Each action repeats its recipe in a headless run, its frames opened:** a warp from part G's `116a` to `103a`
   draws Shrine Island; part select shows `355a`'s menu; the ending reaches scene 9 (its first page drawn); the fade
   fix clears a field left black; with encounters off, part G's accelerated walk fights no battle, and with them on
   (the mutation), at least one.
2. **Refused when it cannot:** a warp asked for in a battle, and one to `500a`, are logged as refused and write
   nothing.
3. **The fake guest:** `test_mods.py` drives the queue: each action's words written in order (the warp's state
   last), the refusals, `SOA_ACTION`'s grammar and its faults.
4. **The menu:** `test_menu.py` moves the warp row through the list and takes it, and the Debug page's other rows ask
   for their actions.
5. **The map list:** `tools/savenow.py check` covers `warp_maps.h` too.
