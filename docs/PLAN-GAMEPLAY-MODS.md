<!-- Written 2026-09-24 from four read-only research reports written the same day
(docs/research/battle-system.md, enemy-data.md, content-systems.md, beyond-gamecube.md), the mod
research before them (docs/research/mods.md, encounters.md, story-flags.md, save-load.md,
ship-worldmap.md), and a web survey of other native ports and of the Skies of Arcadia community. Nothing
here was run when it was written. Claims marked [V] were read in the disassembly, on the local disc or
at file:line; "checked here" marks what the lead re-read while writing. Record what a slice's run shows
in docs/FINDINGS.md, and mark a slice done here the way docs/PLAN.md does. -->

# Gameplay mods, new content, and beyond the GameCube

**For the owner.** [PLAN-60FPS-MODS.md](PLAN-60FPS-MODS.md) builds the mod *framework*: the patch loader (M1, done), the safe point and tick (M2), mod DLLs (M3), calls into game code (M4), settings (M5), the overlay (M8), texture packs (M9), widescreen, and hook sites (M13). This plan is what gets built *on* that framework. It has three goals:

1. **The comfort mods players ask for most**: fewer random battles, a speed-up, save anywhere, Dolphin saves and texture packs, a completion tracker.
2. **Gameplay mods**: combat rules, difficulty, enemies, bosses, quests, ship battles and dungeons.
3. **Content the GameCube could not hold**: more memory, more saved state, new files, native game systems, and visuals the port draws itself.

**Five findings shape it.**

- **The battle engine is small, readable and data-driven [V].** Every hit ends in one function (`fn_800108EC`), enemy AI is a 64-step script interpreted by `fn_8008A424`, and status effects, AI conditions and targeting all go through function-pointer tables in writable memory.
- **Content is files plus scripts [V].** A map is `aNNNx.mld` plus `meNNNx.sct`. NPCs, doors and chests are entries in the MLD, which scripts wake by id. Dialogue is text inside the script, and one function (`fn_8010BBD8`) lays out every field message.
- **The game leaves room [V].** 422 field-map numbers below 500 have no files, and ship-battle stages 584–599 are free. Flags 4,506–27,327 are never touched by any script but are saved with every game. The item tables have 82 placeholder records. Inside the save file itself there are 3,156 checksummed bytes and 6,592 unchecked bytes that no game code reads.
- **The port can plug native code into the game without rebuilding it [V mechanism, I use].** Every indirect call the recompiler could not resolve ends in `guest_trap` (`emit.py:282`, `hle.c:244`). A registry of reserved addresses there lets a mod's C code stand in for any entry of any function-pointer table the game keeps in `.data`: script opcodes (9 of 266 are free stubs), status effects, AI conditions, target selectors, object types, battle phases. That is a relink, not a retranslation.
- **The hard walls are few and known.** Each has a cheap way round and an expensive way through (Track F decompilation):

  | Wall | Cheap way round |
  |---|---|
  | More than 80 items per category | The 82 placeholder records |
  | Enemy rosters: 8 KB per map, 4 kinds per battle | Records are already per map; a buffer redirect lifts the rest |
  | More than 7 saves per card | Card pages, or slot B's card |
  | More than 24 MB of RAM | A relink to 32 MB |

**You are needed for:**
- two decisions: which milestone follows the comfort pack (section E), and whether new art is in scope (Track N's second half);
- short playtests where a slice says **Owner**: the turbo hotkey, the difficulty presets, the first quest, the endless dungeon;
- one real run with your own patched ISO for T7.

Sizes are evenings, as in PLAN.md: **hours**, **a day**, **several days**, **week-plus**. **[V]** means read in the code or data (quoted in the research report); **[I]** means inferred. Rebuild costs follow CLAUDE.md: **none**, **`--link`**, or **one retranslation** (`--compile --optimize --link`, about two minutes plus the self test). The tracks are **P** (player comfort), **K** (knowledge still missing), **T** (tooling for content), **R** (combat), **N** (new content) and **X** (beyond the GameCube).

---

## A. Where this starts, and the rules it keeps

**State of the framework when this was written** (commit 0ddfe05; re-read PLAN-60FPS-MODS.md for the current state, because its status lines move with every commit):
- Done: M1 (the patch loader), M2 (the safe point and tick, `runtime/tick.c`), M3a (`mod.dll` on a versioned `SoaModApi`) and M3b (`pad_filter`).
- M3c, the renderer filters, is in progress.
- The rest of Track M is planned.
- Every slice here names the M items it needs.

**The contract** (Track M's, extended).
- With mods off, nothing changes: the 23 frame hashes, the self test, `title --check`, `decomp.py`, and `test_memguard`/`test_mods`.
- A save made with no content mod loads with or without mods.
- A save made with a content mod still loads in the vanilla game and on Dolphin, with the mod's state ignored. Loaded without the mod in the port, it says what is missing rather than failing later.

**Six rules.**
1. **Reuse before new art.** Build from the game's own models, stages and rooms first. New geometry waits for T8.
2. **Gameplay changes go through named events, not scattered pokes.** A mod edits a value the event hands it (damage, rewards, the AI's choice) the way the PaperBoat port does it. The events live in one place (R1), so two mods that touch damage compose, and a conflict is reported.
3. **Mods in this repository are text.** Scripts as assembly, tables as TSV, enemies as TSV rows, and `mod.ini`. The game's binary formats are built on the player's machine from their own disc. The guard stays as strict as it is (it refuses `.sct`, `.mld`, `.std` and the rest) and gains `.gci`, `.dds` and `.dat` (T0).
4. **Every content mod ships a scenario** that proves it works headless, and that a battle, a save and a map change still work with it on (T6).
5. **Hooks never go where the game waits on an interrupt.** A `hooks.txt` entry strips `irq_poll` from every back-edge of its function. The research marks each proposed site; the card writer `fn_801A3B30` and the AI walker `fn_8008A424` are the two to keep `hooks.txt` away from.
6. **Everything that changes the game is recorded.** DLL inputs, hotkeys and network events go into the pad recording's event track, or a modded session cannot be replayed.

---

## B. What the research established

Four reports, one per question. Each is in `docs/research/` with its evidence. What follows is what the plan relies on.

### B1. The battle engine ([battle-system.md](research/battle-system.md))

- **Combatants [V].** Setup (`fn_80077428`) makes 12 actors of 276 bytes, pointed to from `0x80309DE4[12]`: slots 0–3 are the party, 4–11 the enemies.
  - HP and max HP are at +20/+24, and the status word at +28.
  - Level and stats start at +128, and attack, defense, magic defense, hit and dodge at +148.
  - MP is at +254, the weapon's Moon Stone element at +256, and the enemy's data record at +272.
- **The battle context `*0x80347390` [V].** It holds the Spirit gauge (+6 max, +8 now, +10 after reservations), the EXP and gold pools (+48/+52), drops, and the battle's own copy of the item inventory.
- **Turns [V].** The phase word `0x8034733C` steps through a function table at `0x802DAE50`:
  - 1 party input, 2 enemy AI and turn order, 3 next actor, 4 wait for the action;
  - 5 after the action, 6 end of round, 7 victory, 8 defeat, 9 escape.
  - Turn order is Quick plus a random bonus, sorted by MSL's `qsort`, which is a heapsort. The order is stored at `0x803092F4`.
- **Damage [V].**
  - Hit and critical: `fn_80010B64`. Physical damage: `2·ATK − DEF` (`fn_80010A40`). Magic: `2·(Will + power) − MagDef`.
  - Every value then goes through **`fn_800108EC`**: ±2.5% variance, +1 one time in eight, the element multiplier ÷10, halved when guarding, capped at 9,999. It runs before the KO test, so a hook on its return changes every hit consistently.
- **Enemy AI [V].** `fn_8008A424` walks 64 six-byte steps at record +138:
  - a branch step tests one of 70 conditions (table `0x802DFB10`);
  - an action step picks a command and a target through one of 25 selectors (table `0x802DFC28`).
  - Both tables match the community's ALX tool, so its enemy editor's vocabulary is the game's.
- **Status [V].** Status effects are bits in actor+28 (poison 0x80, KO 0x100, silence 0x200, sleep 0x400 and so on). They are applied through the pointer tables `0x802DBB10`/`0x802DF570` and ticked in `fn_8006FD6C`.
- **Costs [V].** Spell and S-move records are 48 bytes at `0x802C4BF0`/`0x802C52B0`, with the SP cost at +25 and the power at +28. They are read live, so **a data patch changes costs and power at once.**
- **Ship battles [V].**
  - They have their own driver (`fn_80129DD0`), damage function (`fn_80146BF4`) and enemy AI (`fn_80145844`), which reads `rNNNx.tec` tables.
  - The script only sequences the fight, through B[256..275].

### B2. Enemies and battle data ([enemy-data.md](research/enemy-data.md))

- **Where the live records are [V; one chain confirmed in a RAM capture of a real battle].** In play every enemy is a 524-byte record inside either:
  - the current map's `.enp`, for random battles: a directory of {id, offset}, the records, then the formations;
  - `battle/epevent.evp`, for scripted and boss fights: 200 directory slots, 146 used.
  - `fn_80077B88` looks the id up in that directory.
  - `battle/ebinit%03d.dat` and `ecinit%03d.dat` are read only for a battle requested with formation −1, which no shipped script does. 103 of them differ from the live copies. **Editing them changes nothing in play.**
- **The record [V layout].**
  - A Japanese name (not displayed), element, EXP (+30), gold (+32), max HP (+36).
  - Element and status resistances.
  - Level and stats (+92..+110).
  - Four drop slots (+114, tried in order, first success wins; chance 101–104 means always / 1-in-10 / 1-in-5 / never, 105 or more crashes).
  - The 64-step AI (+138): special moves 0–308, spells 500–535, Attack 550, Guard 551, Run 552.
- **Ids and models [V].**
  - Ids are one byte, 0–254 (255 is empty). The id alone picks the model:
    - below 128, `MBnnn.MLD`;
    - 128 and up, through a range table at `0x802ACBE0` to `MGnnn.MLD`.
  - A model animates only the special moves its `.STD` files list.
- **Names are pictures [V].** The name shown in battle is a texture (`ts102nnn`/`ts103nnn`) inside the model file: a portrait plus the name rendered in pixels. No English enemy name exists as text on the disc.
- **Limits [V].**
  - 8 enemies per formation, 7 per event battle, 12 fighters in all.
  - **At most 4 different enemy ids in one battle;** a fifth reads a garbage pointer.
  - **A map's `.enp` must stay under 8,192 bytes decompressed,** because it is copied into a fixed 8 KB buffer (`0x803036E8`) at battle start. That is about 11–13 records. Neither ALX nor SOARandomizer checks this.
- **Event battles [V].** They are 37-byte records: magic EXP, party and enemy placements, initiative, and the defeat and escape rules. Records 0–249 are real and 250–255 are filler, free to reuse.
- **Stages and ships [V].**
  - Battle stages (`sNNN.sml/.sst`) are independent of the enemies, so any stage can host any fight.
  - Enemy ships are a separate system: 45 × 120-byte records in the executable plus per-map `rNNNa.tec` AI tables.

### B3. Maps, objects and dialogue ([content-systems.md](research/content-systems.md))

- **What a map loads [V].** A map is `aNNNx.mld` plus `meNNNx.sct`, both named from the map words `0x80311AC4`/`AC8`. Everything else is named by the script:
  - sub-models through op 23;
  - sound banks through op 69;
  - house interiors through an object parameter.
- **The game accepts uncompressed files [V].** Mods need not recompress.
- **Objects [V].**
  - NPCs, doors, chests, save points and triggers are 0x68-byte entries in an MLD's index: a 16-bit id, a type string (one of 185 in `0x802E2888`), parameters, and position, rotation and scale.
  - Pressing A near an id in 3000–4999, or walking into one in 6000–6999, runs the script entry `M%05d` (`fn_8021067C`).
  - Flag 1087 is the lock that blocks interaction while an event runs.
- **Dialogue [V].**
  - A message is its own script entry of plain text. Op 144 prints it and op 155 offers a choice, answered in sys[9].
  - **`fn_8010BBD8(window, text)` lays out every field message and choice.** It is the text hook.
  - A page is 3 lines of about 48 characters.
- **Shops, chests and Discoveries [V].**
  - Shops: 43 records × 48 items at `0x802EC0A0`.
  - Chests: 119 records at `0x802D59E8`, each with flag 2048+index.
  - Discoveries: op 177, flag 2900+N, 88 of them.
  - The Sailors' Guild: op 231.
- **The world map [V].**
  - It is a wrapping 6×7 grid of tiles `fielRCx.mld`.
  - Islands are `fldIsland` entries in the tiles, and landing points are `fldName` entries, answered by `M04xxx` entries in all 16 `me099a`–`q` scripts.
  - `WMAPAREA.BIN` only names save locations.
- **The file table [V].**
  - The game converts a path to an entry number on every open, and caches nothing.
  - So the port can rebuild the FST at boot, adding or re-pointing entries, and serve the new offsets from host files (`main.c:1137-1160`, `dvd.c:91`).

### B4. The GameCube's limits ([beyond-gamecube.md](research/beyond-gamecube.md))

| Limit | Cheap way round | Size | Rebuild |
|---|---|---|---|
| 24 MB RAM; the game's main heap is 9.64 MB | Raise arena hi: +1.1 MB now; 32 MB with the reserved tail committed (heap 4 grows to 18.6 MB). Leave the size words at 24 MB | hours; a day | `--link` |
| No memory that only mods own | The 8 MB tail as a mod window, plus host memory for DLLs | a day | `--link` |
| No way for game code to call native code | A thunk registry in `guest_trap` | a day | `--link` |
| 80 items per category | Fill the 82 placeholder records | hours | none (data) |
| Enemy rosters: ids 0–254 pick the model; records ≤ 8 KB per map; ≤ 4 kinds per battle | Records are already per map (`.enp`) and per event (`.evp`, 54 free slots), so a new enemy is a new record on an existing model. For a bigger roster, redirect the 8 KB copy into the mod window [I] | a day (data); several days (the buffer) | none; one retranslation |
| 27,328 flags, of which scripts use up to 4,505 | A flag registry from 8,192 up; beyond that, the sidecar | hours | none |
| The save has no room for mod state | A container in the save's gap (3,156 B, checksummed by the game) and tail (6,592 B), plus immutable host blobs by GUID | several days | one retranslation (4 hook sites) |
| 7 saves per card | Slot B's card, or card pages | a day each | `--link` |
| A fixed disc | Rebuild the FST at boot; overlay host files | several days | `--link` |
| Font: ASCII plus a few SJIS ranges; buffer = file size | A native glyph lookup plus a bigger buffer; or port-drawn text | a day to several days | one retranslation / `--link` |
| 64 voices, ADPCM, 32 kHz | A host mixer after the guest (`audio_push_block`) | a day | `--link` |
| No way to add geometry | Draws injected before the HUD and before the frame copy | several days | `--link` |

**Stays expensive** (Track F, week-plus each):
- more than 80 items in a category, because 214 constant sites in 76 functions address the tables;
- globally more than 255 enemies;
- more than 7 saves in one card's menu;
- logic at 60 ticks.

### B5. Corrections to earlier documents, found by this research

- **Chests and Discoveries** (`story-flags.md` §2). Flags 2048–2166 are **treasure chests** (119, with % = n/119), not Discoveries. Discoveries are flags **2900+N**, 88 of them, counted into B[51], and set a second flag at 2990+N.
- **The camera (FINDINGS census 3).** "Camera object 9001" is a **`kmap`** id, the area map drawn from a texture. The `a116c` trap is a missing kmap followed by a NULL dereference.
- **The script disassembler.** `tools/sct.py` desynchronises on ops 24, 25, 144 and 155. SALSA's operand table decodes all 266 (content-systems.md).
- **Enemy files.** `battle/ebinit`/`ecinit` are a fallback the shipped game never uses. The live enemy records are in each map's `.enp` and in `epevent.evp` (enemy-data.md). `beyond-gamecube.md` §2.3's per-map re-pointing of those files is therefore moot. Records are per map already.
- **Flag use.** Scripts reference flags up to 4,505. A raw scan of script words finds nothing above 2,961, but it misses flags passed as opcode arguments. Engine ranges end at 3,077. The earlier "3,072–19,455 is dormant" read was wrong at its low end. This plan reserves mods from **8,192** up.

---

## C. What I recommend from the two idea lists

The first list was comfort and community features; the second was gameplay and content. The picks below are the ones with the best ratio of player value to cost, given what the research found.

| Pick | Slice | Why |
|---|---|---|
| Encounter slider and hold-B | P1 | Fans' first complaint. The game already scales its encounter odds by the byte `0x8030B7AD` (checked here at `0x800C2000`) |
| Turbo | P2 | The second complaint. It is M2's tick unlock on a hotkey |
| Dolphin and console saves (`.gci`) | P3 | People can bring their own saves |
| Fast boot and quick resume | P4 | 53 seconds of logos, every launch |
| Picture options | P5 | Cheap, and invisible to the pinned hashes |
| Race seed | P6 | Reproducible battles for races, practice and **our own combat tests** (R0) |
| Captain's Log | P7 | The completion tracker every JRPG port grows; the flag ranges are now known (B5) |
| Dolphin-named texture packs | P8 | Three community packs exist |
| Developer rooms | P9 | Proven warps, and fun |
| Difficulty presets and boosts | R3, R4 | The standard in every JRPG remaster; one hook each |
| Battle information (enemy HP, turn order, log) | R5 | Pure reads; no hook needed |
| Rebalance tables | T3, R6 | Maeson and Encore exist as ISO patches; this makes them stackable mods |
| New gear, a new enemy, a new bounty | N1–N3 | The first new content: reuses the game's own pieces end to end |
| Remixed and endless dungeons | N5, N6 | New content with no new art |
| The extended-content layer | X1–X4 | What takes content past the disc and save limits |
| Randomizer | N9 | XL, but the step that turns a single-player game into a community |

**Already planned elsewhere:**
- **Save anywhere** is PLAN-60FPS-MODS.md's M7a.
- **Autosave** is a small addition once X2's save hooks exist: every few minutes, when no event runs, to its own slot.
- **Widescreen, 60 fps and HD textures** are that plan's M10/M14, Track H and M9 (P8 amends M9's naming).

**Not picked now:**
- **Archipelago, online co-op and a GPU renderer.** Each is XL, and each waits on something here.
- **Voice acting.** It is content, not code; the voice framework can come with text packs.
- **More than 80 items per category.** The placeholders cover the first mods.
- **RetroAchievements.** Whether RetroAchievements would accept a recompiled port is open, and it is worth asking them first.
- **Photo mode.** It waits on K4's camera.
- **A cheat-code importer.** P1 and R4 cover the codes people actually use.

---

## D. Tracks

### Track P — Player comfort

**Goal.** The comfort features, each off by default and switched in the settings file (M5).

**P1. Encounter slider and hold-B** — *hours, after M6's byte-wide writes.*
- A mod writes the u8 at `0x8030B7AD` every frame in the field.
  - The game reads it at `0x800C2000` (checked here): it sign-extends it, skips it at −1, and otherwise multiplies the encounter odds by byte/50.
  - So 0 means none, 25 half, 50 normal and 100 double; the range is 0–254%.
  - The byte sits outside the saved block. `fn_801EF7E0` resets it to −1 after equipment changes (battle-system.md §1.6), which is why the write is every frame.
- "Hold B to avoid" needs a `when pad=` condition in M1's format, reading the merged pad word `si.c` already builds.
- **Presets:** off, half, normal, double.

*Done:*
- On part G at `116a`, with S3's accelerator and P6's seed: 0% fights no battles, 100% fights the same number as a run with no mod, and 200% fights more. A peek of `0x8030B7AD` shows the value held.
- A hold-B stretch in a pad script fights no battle during the hold.
- The contract holds.

**P2. Turbo hotkey** — *hours, after M2 and a hotkey (M8, or a stopgap in `window.c`).*
- Holding a key turns on M2's tick unlock.
- Option: battles and ship battles only (scene 7, or scene 6 with map ≥ 500).
- It is capped near 2× by design: one field per frame. Heavy scenes are slower until the renderer work (H13–H15).

*Done:*
- Headless, with turbo driven by an environment switch, peeks of `0x803475C0` advance about 60 per wall second while it is on and 30 while it is off. The audio report is unchanged.
- **Owner:** it feels right in a window.
- The contract holds.

**P3. `.gci` import and export** — *hours.*
- `cardformat.py export CARD SLOT out.gci` and `import CARD in.gci`: a 0x40-byte directory entry plus blocks.
- It refuses a wrong game code, a full card and a corrupt file.
- `.gci` is added to the guard (T0).

*Done:*
- Synthetic round trips are byte-identical, with mutations refused (pytest, no game data).
- **Owner:** a save exported from Dolphin imports, verifies READY, and a Continue run lands on the saved map.

**P4. Fast boot and quick resume** — *a day.*
- Run guest time fast (the `SOA_SPEED` machinery, made switchable at run time) until the title, with the sound muted.
- Optionally drive Continue into the newest save with the pad sequence the scenarios already use.
- The attract demo fires 92.267 wall-clock seconds after the title, and the title is reached long before that.

*Done:*
- The title appears within 10 wall seconds.
- Quick resume lands on the saved map (checked by the map loads in the log).
- With it off, `title --check` is unchanged.

**P5. Picture options** — *hours each.*
- Gamma, colour-blind simulation or correction, a CRT look and a flash limiter (Xbox guideline 118 thresholds), all in `window.c` `present()` after `g_screen`.
- Deflicker off: skip the copy filter in the display copy only.

*Done:*
- Before-and-after PNGs are opened.
- Every presenter option leaves `SOA_HASH` lines identical. Deflicker off changes them only while it is on.
- The contract holds.

**P6. Race seed** — *hours.*
- On each map load the field reseeds the RNG from `OSGetTick` (`0x801012AC`) into `0x803469A8` (checked here).
- An `on_map_load` patch writes a seed derived from the user seed and the map number.
- **First check the order:** the patch must land after the reseed. If it does not, bind the reseed call site by lr, the way `tick.c` does.

*Done:*
- Two runs with the same seed and pad script fight the same battles, with equal formation ids and equal damage (S1's checker plus R0's harness).
- Two different seeds differ. This is the mutation.

**P7. Captain's Log** — *several days, after M8.*
- An overlay checklist:
  - Discoveries: flags 2900–2987;
  - chests: flags 2048–2166, with % = n/119;
  - crew: flags 1039–1060;
  - Chams, Moonfish and bounties: flags from K2;
  - kills: ctx+12's source `0x8030BB44`.
- Missable warnings come from story flags.
- A small local web page shows the same list on a phone.

*Done:*
- On the part-L save, the Discovery and chest counts match the game's own screens, with the frames opened.
- Poking one Discovery flag moves the count by one.

**P8. Texture packs by Dolphin's names** — *several days; this amends M9.*
- Name textures as Dolphin does: `tex1_{w}x{h}[_m]_{xxh64}[_{tlut}]_{fmt}`, where the TLUT hash covers only the palette entries used.
- Load PNG and DDS, including BC7, lazily, from `load/textures/GEA`.
- Keep M9's frozen hash too, for dumps. Its key has to be versioned.

*Done:*
- A test pins Dolphin's name for synthetic textures, with the expected values computed by a reference XXH64.
- **Owner:** a texture from one of the community packs replaces its original in a snapshot.
- With the pack off, 23/23.

**P9. Developer rooms** — *hours, after M7b and M8.*
- English menu entries for the part select (`ME355A`), the ship-battle select (`398A`, which also reaches the four unused enemy ships) and the stage picker.

*Done:* each entry reproduces its FINDINGS recipe, with the frames opened.

### Track K — Knowledge still missing

The four reports answered most questions. These are the rest, each **hours to a day, no rebuild**, written up in FINDINGS or a research note with [V]/[I].

**K1. Confirm the dormant flags by run.**
- Run `SOA_WATCH=0x80310CBC,0x800` (flags 3,072–19,455's words) with `SOA_WATCH_FROM` over three soak scenarios.
- *Done:* zero hits above 4,505 across the soaks, or the writers are named and the registry's floor moves.

**K2. The other collectibles.** Find the flags or variables for Chams, Moonfish, bounties, Piastol and the giant monsters, starting from the RetroAchievements set's public conditions as leads. *Done:* each has an address and one confirming peek.

**K3. Enemy name pictures and model files.**
- Names are textures inside the model (enemy-data.md). Find how the name texture is chosen when it is not the model's first, and whether copied `.STD` animation files point back at their original model.
- Both decide how a new enemy gets its own name and model.
- *Done:* layout and one repainted name shown in a battle (frame opened).

**K4. The field and world-map camera** (M12's camera spike).
- Ops 72/74 write a follow-camera struct at `0x802E0084` [I].
- Confirm it, and find the view matrix X6 needs.
- *Done:* one peeked matrix matches a captured frame's XF view.

**K5. Ship-battle input.** The player-side command and SP rules, and the 88-byte timeline entries. *Done:* layout and addresses.

**K6. Deterministic battles.** Given P6's seed and a frame-keyed pad, is a battle bit-for-bit repeatable, or does something read the clock mid-battle? *Done:* R0's harness run twice gives the same damage log, or FINDINGS names the clock read.

### Track T — Tooling for content

**T0. Guard additions** — *hours.*
- Add `.gci`, `.dds` and `.dat` to `FORBIDDEN_SUFFIXES`, and the pack and blob directories to `FORBIDDEN_DIRS`.
- *Done:* `test_guard` refuses each, and CI's regex copy matches.

**T1. The virtual disc** — *several days, `--link`* (beyond-gamecube.md §4, content-systems.md §8).
- In `main.c` after `mod_load` (`:1137`), before the FST copy (`:1160`):
  - parse `sys/fst.bin`;
  - **replace** a file by re-pointing its offset and length;
  - **add** a file by inserting it and re-serialising;
  - **alias** a new name onto an existing extent, with no bytes copied.
- Virtual offsets above `0x57058000`; an overlay table in `dvd.c` `disc_read`, including a read that straddles two extents.
- Per-map re-pointing at the safe point, which X4 uses for enemy files.
- Mods list their files under `files/`. The pack is recorded in the pad-config line.

*Done:*
- With no mods, the FST bytes and the contract are unchanged.
- An override of `me101b.sct` shows a changed line, with the frame opened.
- An alias `a045a.mld` onto `a002a.mld` plus a new `me045a.sct` is warpable by name and draws.
- A path collision between two mods is refused with both names.

**T2. The content registry** — *hours.*
- `mod.ini` reserves ranges:
  - flags from 8,192;
  - map numbers from the free list (400–499 suggested first);
  - enemy file numbers;
  - placeholder item ids;
  - ship stages 584–599;
  - script opcode stubs;
  - thunk slots.
- The loader refuses overlaps.
- *Done:* two mods claiming one flag are refused, naming both.

**T3. Table patches** — *several days.*
- Row-and-column edits in ALX's vocabulary, applied at boot for executable tables and at load for files: `weapon Cutlass attack = 30`, `spell 12 sp = 6`, `shop 8 item 3 = 245`.
- Mods stack when they touch different cells; the same cell in two mods is a reported conflict.
- The tables it knows at first: weapons, armor, accessories, items, spells, S-moves, shops, chests, enemy records and the SP curve (addresses in B1, B3, battle-system.md §6 and §7).

*Done:*
- A patched spell cost reads back by peek, and the magic menu offers the spell at the new cost (frame opened).
- A conflict is refused.
- Round trips are covered by tests on synthetic tables.

**T4. A script assembler** — *week-plus.*
- A text form, the SALSA operand layouts adopted into `tools/sct.py` so that ops 24, 25, 144 and 155 decode, and an assembler back to `.sct`.
- Mods keep scripts as text; the build makes the binary on the player's machine.

*Done:*
- Every one of the 258 scripts round-trips byte for byte.
- A changed operand fails the round trip.
- An edited message shows in a run.

**T5. Enemy records as text** — *days.*
- Read and write the live containers:
  - each map's `.enp`, with its {id, offset} directory, records and formations;
  - `epevent.evp`, with 200 directory slots and 256 event records.
- Each 524-byte record becomes TSV rows (ALX's column names), with the 64 AI steps as readable lines (`if hp < half → magic 12 on weakest`).
- The writer **refuses:**
  - an `.enp` over 8,192 bytes decompressed;
  - a formation with more than 4 distinct ids;
  - a drop chance of 105 or more;
  - an AI path that can end without an action;
  - a special move the model's `.STD` does not list.
- `ebinit`/`ecinit` are not written, because the game does not use them.

*Done:*
- Every `.enp` and the `.evp` round-trip.
- Each refusal has a mutation test.
- A changed max HP shows in a battle's actor +24 by peek.

**T6. Content checks** — *days.*
- `tools/contentcheck.py`, which is `soak.py`'s runner with a script:
  - warp to the mod's map;
  - walk a path;
  - talk (A near an id) and check that the entry fired;
  - force the mod's battle;
  - save, reload, and assert the map and flags.
- *Done:* it passes on vanilla `a101b`, and a broken script (mutation) fails it.

**T7. Play existing ISO mods** — *several days.*
- Diff a patched ISO the player owns against their own clean dump:
  - changed files become T1 overrides;
  - changed executable data becomes T3/M1 patches;
  - changed executable code is refused with a reason, because the translated code cannot see it.
- *Done:*
  - Synthetic ISO fixtures pass.
  - **Owner:** a Legends Maeson or Encore ISO imports and boots, and a changed stat shows in battle.

**T8. The model and collision writer** — *week-plus to months; the gate for new art.*
- Write MLD containers: NJCM models from Blender (start from the Sonic Adventure Blender add-on's chunk-model export), NJTL/GVR textures (SPICE writes GVR), GRND/GOBJ collision (nobody writes these yet), POF0 relocation tables and index entries (content-systems.md §2).
- *Done:*
  - An existing map's MLD round-trips semantically.
  - Then a room with one wall moved draws and collides correctly, with frames opened and collision probed by walking into it headless.

### Track R — Combat

**Goal.** Combat mods through one event surface, tested by a battle harness.

**R0. The battle harness** — *several days, no rebuild after P6.*
- From a card save:
  1. force a chosen formation or event battle (the six-word request at `0x803473D4`);
  2. play a fixed command script;
  3. peek actor HP (+20), SP (ctx+8) and the turn order (`0x803092F4`) every frame;
  4. write a damage log.
- *Done:*
  - Two runs with P6's seed agree (K6).
  - A mod that doubles damage (R1) doubles every logged hit in the harness. This is the check that proves the harness can fail.

**R1. Battle events** — *several days plus one retranslation* (batched with X2's hook sites).
- Native wrappers through `hle.txt`, each calling the original (`recomp_fn_X`) and letting mods edit the result. Moved to M13 sites when M13 lands.

| Event | Site | Payload |
|---|---|---|
| `on_damage` | `fn_800108EC` return | attacker, target, `int* value` (re-capped at 9,999) |
| `on_heal` | `fn_8006AE20` | target, `int* value` (via work+60) |
| `on_enemy_spawn` | `fn_800770B8` post | actor (scale the actor, **never the shared record**) |
| `on_enemy_action` | `fn_8008A424` | slot, `cmd*`: replace or adjust the AI's choice |
| `on_turn_order` | after phase 2 (`fn_80070C18`) | order[12] (read, or reorder) |
| `on_spirit_gain` | `fn_8006EF48` | `int* amount` |
| `on_escape` | `fn_80010340` | `bool* success` |
| `on_rewards` | phase 7 entry, `fn_8006F4B0` | `int* exp`, `int* gold`, `u8* magic_exp` |
| `on_effect` | `fn_8002BD88` entry | target, effect id, `int* value` |
| `on_round_end` | `fn_8006FD6C` when `0x80347338 == 0` | — |
| `on_ship_damage` | `fn_80146BF4` return | `int* value` |

- Handlers run in registration order; a mod that *replaces* the AI for a slot is exclusive, and two such mods are refused.

*Done:*
- Each event has a self-test twin case with a pass-through handler, and R0's harness logs identical numbers with the pass-through on.
- The doubling mutation from R0 fails the identity check.
- The contract holds.

**R2. Status and AI extensions by thunk** — *several days, `--link` after X1.*
- The pointer tables `0x802DBB10` (apply), `0x802DF570` (value), `0x802DFB10` (AI conditions) and `0x802DFC28` (target selectors) are `.data`.
- X1's thunks let a mod point an entry at native code: a new status effect, a new AI condition such as "if the party's SP is full", or a new targeting rule such as "whoever has the lowest defense".
- Free status bits start at `0x04000000` [I: bits the code was not seen to touch; K confirms].

*Done:*
- A native "Burn" status (a tick in `on_round_end`, applied through a spare effect id) shows its damage in R0's log.
- An enemy whose AI uses a native condition takes the branch.
- A mutated condition id changes the branch taken.

**R3. Difficulty presets** — *days, after R1.* **Owner.**
- Presets **Easy**, **Hard** and **Nightmare**, applied in `on_enemy_spawn`: HP, attack, defense, magic defense and speed multipliers, and optionally enemy level.
- Level scaling: set the enemy level from the party's (AI conditions 44/45 read the gap).
- Rewards scale in `on_rewards`.

*Done:*
- R0's log shows enemy HP × the multiplier on the actor, not the record: the second battle on the same map is not compounded (peek the record).
- **Owner:** a playtest of Hard through one dungeon.

**R4. Boosts and assists** — *hours each, after R1.*
- EXP, gold and magic EXP at ×0–×4 (`on_rewards`).
- Always escape (ctx+2 = 100, or `on_escape`).
- No knock-outs (clamp in `on_damage` for party targets).
- Full Spirit at the start (ctx+8).
- ×0 EXP doubles as a low-level challenge.

*Done:* each shows in R0's log or the post-battle result, and ×1 is identical to off.

**R5. Battle information** — *days, after M8; reads only.*
- Enemy HP bars: actors 4–11, +20/+24.
- The turn order: `0x803092F4` from phase 3; from phase 1, an estimate from Quick.
- A scrolling battle log from `on_effect`, or by polling.
- Enemy names are pictures in the game (enemy-data.md). The overlay uses a name table by id, shipped with the mod as text.

*Done:*
- The overlay's HP matches R0's log on every frame of a harness battle.
- The order matches the actors that act.

**R6. Rebalance mods** — *several days, after T3 and T5.*
- A Maeson-style rebalance written as text: spell costs and power, weapon and armor stats, the SP curve (`0x802C9184`), enemy records and drops.
- *Done:* an example rebalance mod in `mods/` (text only) applies, and R0 shows its numbers. With it off, identical.

**R7. A new command** — *week-plus, after R1.*
- The wheel and handler dispatch are switches baked at translation (battle-system.md §8), so it needs:
  - a pre-hook on `fn_8007C600` that overloads a slot with a modifier (for example "hold L on Item = Steal");
  - a handler installed for command type 7 or ≥ 9, which gets a turn slot in phase 2 but does nothing today (`0x80087040`).
- A true eighth icon needs art in `battle/command.mld`.
- *Done:* "Steal" takes an item from an enemy's drop list in a harness battle, and every other command is unchanged.

**R8. Auto-battle and repeat-last-turn** — *days, safe point only.*
- In phase 1, write each member's command from the "last" fields and reserve SP, MP and items exactly as the menus do (battle-system.md §8: the recipe with its three reservations). Then close the menus and set phase 2.
- *Done:* 20 harness rounds of "repeat" leave SP, MP and item counts exactly as 20 rounds entered by the pad would.

**R9. Ship battles** — *several days, after R1 and K5.*
- `on_ship_damage`.
- Native ship AI: bind `fn_80145844`, falling back to the original.
- A shorter-cinematics option: the tick unlock gated on map ≥ 500 (M11). Skipping animations outright is high-risk (§8 of the battle report), so it stays out.
- *Done:* a harness ship battle logs the doubled damage, and an AI replacement picks its first action.

### Track N — New content

**Goal.** New things to do, built from the game's own pieces first. Every slice ships as text plus a T6 check.

**N1. New gear in the placeholder slots** — *hours, after T3.*
- 82 placeholder records:
  - 6 weapons (ids 74–79);
  - 21 armor (139–159);
  - 17 accessories (223–239);
  - 3 items (302–304);
  - 35 key items (365–399).
- Names, stats and prices go by T3. Descriptions and new strings live in X3's mod window.
- *Done:* a new weapon bought from a patched shop (T3 on `0x802EC0A0`) equips, and R0 shows its attack. The save round-trips in vanilla.

**N2. A new enemy from an existing model** — *days, after T1 and T5.*
- A new record: stats, AI steps, drops and element (enemy-data.md's recipe).
- **The id decides the model and the name picture.** Three ways to choose it:
  - **Reuse the model's own id** with a new record in that map's `.enp` or in the `.evp`. It keeps the original's name picture, and the two cannot share a battle.
  - **Use a spare boss id** that already maps to an existing model: 247, 249 or 253; or 203–207 and 135, whose models have no name picture.
  - **Use a free id** (5, 6, 122–127) with copied model files (T1 aliases) and a repainted name texture (K3, P8).
- Only special moves the model's `.STD` lists will animate.
- **Random battles:** add the record to the `.enp` directory, add formations, and point the map's `.ect` at them. Keep the `.enp` under 8 KB and at most 4 distinct ids per battle (T5 refuses otherwise).
- **Scripted fights:** a record in one of the `.evp`'s 54 free directory slots, an event record in slots 250–255, started by script op 112.

*Done:*
- The enemy appears in a forced battle with its new HP (actor +24 by peek) and its AI's first action.
- Its drops roll from its own table (R0's log over 20 wins).
- The registry (T2) refuses a second mod claiming the same id on the same map.

**N3. The new bounty** — *week-plus, after N1, N2, T4, T6 and X2.* **Owner.** The first vertical slice.
- A new Wanted target, built from content-systems.md's quest recipe:
  - an NPC's new branch;
  - three flags from the registry;
  - an event battle against N2's enemy;
  - the post-battle return through `sys[15] = 10000`, with the fade-in the script must do itself;
  - a reward from N1.
- *Done:*
  - The T6 check walks it end to end: offer, accept, fight, reward, save, reload, reward kept.
  - **Owner:** plays it.

**N4. New ship battles** — *several days, after T1 and T4.*
- A stage in 584–599: a script modelled on `me500a` plus an `rNNNx.tec` AI table, reusing an enemy ship from the table at `0x802D6934`, including the four unused ones.
- *Done:* entered through opcode 210 from the world map, it is fought and won, and returns (T6).

**N5. A remixed dungeon** — *week-plus, after T1, T4 and N2.*
- A new map number aliased onto existing geometry (content-systems.md's second recipe):
  - its own script, warps, encounter table and chests;
  - donor chests left out, because they share the donor's chest flags;
  - its own chests given as op-20 rewards behind registry flags.
- *Done:* T6 walks from the entrance to the boss and back out, and the donor map is unchanged.

**N6. The endless dungeon** — *week-plus, after N5 and X1.* **Owner.**
- A native "Sky Rift" mode, after Lufia II's Ancient Cave and the FF1 randomizer's 52-floor Deep Dungeon: floors chained from existing dungeon rooms by per-floor aliases (T1).
- Encounter tables and enemy levels scale by floor (R3's hooks), and rewards come from a seeded table.
- The rules are native (a thunk script opcode picks the next floor).
- *Done:* 10 floors descend headless with a fixed seed. **Owner:** it is fun.

**N7. A new room from new geometry** — *after T8.* One room with its own model and collision, built by T8, placed with N5's recipe. *Done:* it draws, collides, and can be walked from a door (T6).

**N8. A new island** — *week-plus, after N7 and K4.*
- An island model and `fldIsland` entry in a world tile, or a sub-model loaded by all 16 `me099a`–`q` scripts.
- A `fldName` landing point answered by `M04xxx` in each script, and optionally a Discovery (op 177; the table caps at 89).
- *Done:* sailing to it and pressing A lands the party on N7's room.

**N9. Randomizer** — *XL.*
- A seeded shuffle of chests (the 119-entry table), shop stock, enemy formations, Moon Stone spells and crew spots, with logic that respects story gates.
- Permalinks, a spoiler log, and P7 as the tracker.
- Start from SOARandomizer's and ALX's data knowledge.
- *Done:* 100 seeds generate, each is beatable by the logic, and a run on one seed reaches part B with the shuffled chests (T6).

### Track X — Beyond the GameCube

**Goal.** The layer that lets mods hold more than the disc, the RAM and the save allow. This is beyond-gamecube.md §10, as slices. Everything is off by default.

**X1. Native thunks** — *a day, `--link`.*
- A registry of reserved addresses (for example `0x81FFF000 + 4n`) consulted by `guest_trap` before it traps.
- Mods register a native function and get an address to plant in any guest function pointer: a script opcode (9 `scptSTUB` entries at `0x802F7940`), a status or AI table entry, an object type in `0x802E2888`, or a middleware callback.
- The thunk must preserve r1, r2, r13 and the non-volatile registers; a self test enforces it.

*Done:*
- A self-test case calls a thunk through `dispatch` and checks the registers.
- A native script opcode, called from a test script, sets a flag.
- An unregistered address still traps as today.

**X2. The save extension and the flag registry** — *several days plus one retranslation* (batched with R1).
- Four hook sites:
  - the snapshot at `0x801A4670`;
  - the image build at `0x801A4334`;
  - the load at `fn_801A4354`;
  - new game and boot at `fn_801CAF30`.
- An in-file container: header `SOAX`, GUID and CRC32, and chunks per mod, in the 3,156-byte gap (inside the game's own checksum) and the 6,592-byte tail. Overflow goes to immutable host blobs by GUID.
- `on_new_game`, `on_save_snapshot` and `on_save_loaded` for mods.
- The flag registry (T2) hands out flags from 8,192 up; sidecar chunks cover anything beyond.
- **Never** use `hooks.txt` inside the card writer `fn_801A3B30`.

*Done:*
- A mod's counter survives save → reload.
- The same card loads in the unmodded port with the counter ignored, and `cardformat.py verify` reports READY.
- **Owner:** the card loads in Dolphin.
- A mutation that writes the gap after the XOR is caught by the game's own checksum on reload.

**X3. Memory for mods** — *a day, `--link`.*
- `g_ram_top` as a runtime value replacing `MEM1_SIZE` in the device-model bounds.
- Arena hi to `0x81800000`, which gives heap 4 +1.1 MB.
- The 8 MB tail as a mod window, committed per request; the rest stays a tripwire.
- The option to hand the tail to heap 4 (32 MB total) when a content mod asks for it.
- Leave the size words at `0x80000028`/`0x800000F0` alone: changing them sets a devkit flag or subtracts 24 MB.
- `test_memguard`'s tripwire expectation moves only when the option is on.

*Done:*
- With the option off, everything is identical, including the tripwire at `0x81800000`.
- With it on, a peek of heap 4's size shows the growth.
- A mod string placed in the window is shown by the game in a message (N1's descriptions).

**X4. Bigger enemy rosters** — *several days, one retranslation (batch it with R1).*
- Records are already per map, so the limits that bind are the 8 KB `.enp` battle buffer and the 4 distinct ids per battle.
- Redirect the battle-start copy (`fn_800C23CC` → `0x803036E8`) into a larger block in X3's mod window.
- Then find the table behind the 4-id limit, where a fifth id reads a garbage pointer (enemy-data.md), and widen it the same way.
- *Done:*
  - A map with 20 records fights enemies from records past the old 8 KB.
  - A battle with 5 distinct ids draws all five.
  - With the option off, the buffer and pointers are the originals.

**X5. Host audio** — *a day for the mixer; several days for music replacement.*
- A mixer in `audio_push_block` (after the guest, so the game never reads it), with streamed OGG or FLAC and unlimited voices.
- **Music packs:** mute a voice whose ARAM source maps to a replaced track (the ARAM census already names sources) and play the host stream, following its volume, loop and stop.
  - Battle music changes with the fight's state, so the mapping keys on the stream, not the chunk.
- *Done:*
  - A pack's track plays in place of `m01` in a `SOA_WAV` recording, correlated with `audio_check.py`.
  - With the pack off, the audio report is identical.

**X6. Injected draws** — *several days, `--link`, after K4.*
- `gxr_inject(slot, fn)` builds DrawCmds from host meshes in two slots:
  - before the first HUD draw, depth-tested against the game's z;
  - before the XFB copy.
- It uses the camera K4 finds and XF's projection. This is how the port draws props, markers and ghost ships the game never loaded.
- *Done:*
  - A test cube at a fixed world position stays put as the camera moves, and is occluded by nearer geometry, with frames opened.
  - Off: 23/23.

**X7. Native systems** — *week-plus each; the pattern, not one slice.*
- A mod that owns a whole feature in C: state in X2's chunks, UI in the overlay (M8), and game effects through events (R1), thunks (X1) and `call_guest` (M4).
- The first candidate is a **bestiary**: kills per enemy from `on_effect`, stats from the enemy records, a 3D view through the FIFO replay.
- Later: crafting from drops, crew perks, a Pinta's Quest-style minigame whose loot enters the save.
- *Done (bestiary):* kill counts survive save and reload (X2) and match R0's log.

**X8. Text beyond the font** — *a day to several days, one retranslation.*
- A native glyph lookup (`fn_801E26E0`) and a bigger font buffer (pre-hooks at `0x801E3740`/`0x801E36F0`), with glyphs rasterised from a TTF at boot.
- Accented Latin and other scripts ride on unused Shift-JIS codes.
- The text hook `fn_8010BBD8` swaps whole messages, keyed by script, entry and a hash of the original.
- This carries text packs, retranslations and read-aloud.
- *Done:*
  - A message replaced through the hook shows with an accented character, with the frame opened.
  - A read-aloud mod speaks the same message.

**X9. More saves** — *a day.*
- Slot B's card: the menu already probes both slots, so it gives +7.
- Then a card-page switcher while the menu is closed.
- *Done:* the save menu lists files from slot B, and a Continue from slot B lands on its map.

---

## E. Sequence, milestones and decisions

**Ordering rules.**
- X1 (thunks) and T1 (the virtual disc) are relink-only, and nearly everything in R, N and X uses one of them, so they come first among the foundations.
- **Batch the retranslations.** R1's wrappers, X2's save hooks and X8's font hooks go in one retranslation, with the self test's twin cases.
- R0's harness comes before any combat mod is called done, because it is the check that can fail.
- M-track dependencies:
  - M2 for P2;
  - M5 before anything is called player-usable;
  - M6 for P1;
  - M8 for P7, P9 and R5;
  - M4 for X7.

**Milestones.**

| Milestone | Slices | What a player gets | Rough size |
|---|---|---|---|
| **1. Comfort pack** | P1–P6, T0 | Encounter slider, turbo, `.gci` saves, fast boot, picture options, race seed | 2 weeks of evenings, once M2/M5/M6 land |
| **2. The gameplay core** | X1, T1, R0, R1 + X2 (one retranslation), T2, K1, K6 | Nothing visible yet; every later mod stands on it | 3–4 weeks |
| **3. First gameplay mods** | R3, R4, R5, T3, R6, P7 | Difficulty presets, boosts, enemy HP and turn order, rebalance mods, the Captain's Log | 2–3 weeks |
| **4. The new bounty** | T4, T5, T6, N1, N2, N3 | The first new content: a quest, an enemy, a weapon | 4–6 weeks |
| **5. Beyond the disc** | X3, X4, X5, X8, R2, N4, N5, N6 | Bigger enemy rosters, new status effects, music packs, new text, ship battles, the endless dungeon | 2–3 months |
| **6. New worlds** | T8, X6, X7, N7, N8, N9 | New rooms and islands, native systems, the randomizer | months; needs art |

**Decision points.**
- **After milestone 1.** Go on to 2 (gameplay), or take M9/M10 (textures, widescreen) first. My recommendation is 2: it unlocks the most, and the visual items are on the other plan's schedule anyway.
- **After K6.** If battles are not repeatable with a pinned seed, R0 compares distributions over many runs instead of exact logs. D4 (the deterministic clock) then moves up.
- **After T4.** If some script cannot round-trip, content mods use SALSA's output as binary overrides for that script only, recorded as an exception.
- **Before milestone 6.** Art. T8 is only worth it if someone will model rooms and islands. Without an artist, milestone 5's remixed and procedural content is the ceiling, and it is a high one.

**The first three slices: P1, X1 and R0.**
- P1 is a few hours on M6 and ships the most-wanted mod.
- X1 is a day, relink-only, and opens every function-pointer table to native code.
- R0 is the harness every combat mod will be judged by.

---

## F. Not in this plan

- **A GPU renderer, higher internal resolution and VR.** PLAN.md parks the GPU backend until H15's numbers.
- **60 fps and widescreen.** They are PLAN-60FPS-MODS.md's Tracks H and M.
- **Archipelago and online co-op.** They wait on N9 (a randomizer's logic is Archipelago's world definition), on X2 (the received-items index lives in the save), and, for lockstep co-op, on D4.
- **More than 80 items per category, more than 255 enemies globally, and more than 7 saves in one card's menu.** Each is a Track F rewrite of the functions that hold baked constants. The placeholder records, per-map enemy files and card pages cover the need until a mod proves otherwise.
- **Voice acting.** X8's text hook gives the keying (script, entry, hash), and X5's mixer plays the files. The voices themselves are a community project, cast with consent.
