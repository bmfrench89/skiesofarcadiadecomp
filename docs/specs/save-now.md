# M7a: save now, anywhere on the field

Written 2026-10-24 after milestone 2's core list (D-43), from [PLAN-60FPS-MODS.md](../PLAN-60FPS-MODS.md) M7a,
[PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) §F's M7a amendment, X2's [save-extension.md](save-extension.md)
and D-44 (the honest save promise, which still asks for save-now's location fallback). Measured first: FINDINGS "M7a".

**Built 2026-10-24** (FINDINGS "M7a"): Done lines 1 to 5. *As built:* the menu closes before the safe point
decides, so a refusal is in the log, not on screen; a save-now on a save point's map also lands where it was made
(`sys15` 0), not at the save point.

**Why.** The game saves only at save points. On a handheld, a player who has to stop mid-dungeon loses the way back.
Save now opens the game's own save menu wherever the field is quiet.

## 1. What is there [V]

- **The request** (save-load.md §1): `save.request` (`0x803473B4`) = 1 with `save.variant` (`0x803473B0`) = 0 makes
  the save-point task, which every loaded field has, open the game's own save menu. Measured on `a116c`, a map
  with no save point: the menu opened and the save was written (`build/reach/m7-116c-save`, map 0x74 `c` in it).
- **The trap.** Every Continue ends with `fn_801F7B04(20000)`, `sys[15]` (`0x8030E420`) = 20000, which a map's
  script takes as "back from my save point". On a map whose script has no op 138 (SAVEPOINT) that branch was never
  reachable in retail; `a116c`'s asks for area map 9001, which the map lacks, and stops (`build/reach/m7-116c-load`:
  the strict check at `0x800E1B2C`, under op 235's `fn_800E2924`).
- **The fix, measured:** `sys[15]` = 0 after the load and before the map's script runs, and the Continue lands on
  `a116c` with the field running and the player where the save was made (`build/reach/m7-116c-fix`, frame 3700).
- **57 of the 257 field scripts have op 138** (`sct.py`'s disassembly of each, `[138]`).
- **A quiet field** (the lab's `save` item): scene 6, field state 8, flag 1087 clear, `0x8030E714` not 1.

## 2. What M7a adds

- **`savenow_request()`**, from the menu's new Main item "Save now" and from `SOA_SAVE_NOW=F` (frame F, for tests):
  at the next safe point on a quiet field the request is written; elsewhere it is refused, with the reason, in the
  log ("save now refused, in a battle", "…, during an event"). The menu closes first, so it cannot show the
  refusal; an on-screen word is M8's later work.
- **`runtime/save_point_maps.h`**, generated from the disc by `tools/savenow.py generate` and checked by
  `tools/savenow.py check` (and `test_savenow.py` where the disc is): the maps whose script has op 138.
- **The last save-point map,** remembered at each map entered (and at a Continue onto one).
- **X2's `soa.savenow` chunk,** written only for a save the port opened, with the map word, letter and position it
  was made at. Off a save point, the block's map word and letter (+5808, +5812) take the last save-point map, so
  the game alone, a P3 export or Dolphin loads the save there, at its save point, instead of trapping.
- **At the load,** before the game copies the block: a `soa.savenow` chunk puts its own map back into the block
  where the block still holds the fallback; after the copy, `sys[15]` = 0, so the player lands where the save was
  made, on a save point's map too.

## 3. Not in M7a

M7b's other actions (warp by name, part select, the forced battle, the fade fix, the encounter toggle, the ending,
the tick unlock), save-now on the world map (map 99, its own variant) and in a ship battle, and Dolphin itself (an
owner check).

## 4. Done

1. **On a save point's map** (`a116a`): a save-now from `SOA_SAVE_NOW`, through the game's menu, then a fresh
   Continue from that card lands on `a116a` where the save was made, and `cardformat.py verify` says READY.
2. **Off one** (`a116c`): the card's map word holds the last save-point map and its `soa.savenow` chunk `a116c`
   (`savext.py show`). A fresh Continue in the port lands on `a116c` and draws (frames opened). The build from before
   X2 (`build/x2/before`, standing in for the game alone) Continues onto the fallback map, at its save point.
   *Mutation:* with the load's restore off, the port lands on the fallback too.
3. **Refused when not quiet:** a request during a battle, and one during an event, are logged as refused and write
   nothing.
4. **The menu:** `test_menu.py` drives "Save now" and sees the menu close and the request asked for.
5. **The map list:** `tools/savenow.py check` agrees with the disc, and a map dropped from the header fails it.
