<!-- Written 2026-09-24 from four read-only research reports written the same day
(docs/research/battle-system.md, enemy-data.md, content-systems.md, beyond-gamecube.md), the mod
research before them (docs/research/mods.md, encounters.md, story-flags.md, save-load.md,
ship-worldmap.md), and a web survey of other native ports and of the Skies of Arcadia community.
Revised 2026-09-25 from docs/research/plan-gaps.md, a read-only gap sweep of this plan. Its
corrections are folded in and its additions are placed below. Nothing here was run when it was
written. Claims marked [V] were read in the disassembly, on the local disc or at file:line; "checked
here" marks what the lead re-read while writing. Record what a slice's run shows in docs/FINDINGS.md,
and mark a slice done here the way docs/PLAN.md does. -->

# Gameplay mods, new content, and beyond the GameCube

> **Order and implementation specs, from 2026-09-25:** [PLAN-NEXT.md](PLAN-NEXT.md) says what comes next, and in what order. Milestone 1 (the comfort pack) is specified to implementation level in [specs/comfort-pack.md](specs/comfort-pack.md), and T1 in [specs/disc-layer.md](specs/disc-layer.md) (I6-I8). Where a slice here and a spec disagree on design, the reviewed spec wins. This plan keeps the tracks, the rules and the later milestones.

**For the owner.** [PLAN-60FPS-MODS.md](PLAN-60FPS-MODS.md) builds the mod *framework*: the patch loader (M1), the safe point and tick (M2), mod DLLs (M3), calls into game code (M4), settings (M5), the overlay (M8), texture packs (M9), widescreen, and hook sites (M13). This plan is what gets built *on* that framework. It has three goals:

1. **The comfort mods players ask for most**: fewer random battles, a speed-up, Dolphin saves, dialogue that advances itself, co-op battles, and a completion tracker.
2. **Gameplay mods**: combat rules, difficulty, enemies, bosses, quests, an arena, New Game+, ship battles and dungeons.
3. **Content the GameCube could not hold**: more memory, more saved state, new files, native game systems, and visuals the port draws itself.

**Five findings shape it.**

- **The battle engine is small, readable and data-driven [V].** Every hit ends in one function (`fn_800108EC`), enemy AI is a 64-step script interpreted by `fn_8008A424`, and status effects, AI conditions and targeting all go through function-pointer tables in writable memory.
- **Content is files plus scripts [V].** A map is `aNNNx.mld` plus `meNNNx.sct`. NPCs, doors and chests are entries in the MLD, which scripts wake by id. Dialogue is text inside the script, and one function (`fn_8010BBD8`) lays out every field message.
- **The game leaves room [V].**
  - 422 field-map numbers below 500 have no files, and ship-battle stages 584–599 are free.
  - Flags 4,506–27,327 are never touched by any script but are saved with every game.
  - The item tables have 82 placeholder records.
  - Inside the save file there are 3,156 checksummed bytes and 6,592 unchecked bytes that no game code reads.
- **The port can plug native code into the game without rebuilding it [V mechanism, I use].** Every indirect call the recompiler could not resolve ends in `guest_trap` (`emit.py:282`, `hle.c:244`). A registry of reserved addresses there lets a mod's C code stand in for any entry of any function-pointer table the game keeps in `.data`: script opcodes (9 of 266 are free stubs), status effects, AI conditions, target selectors, object types, battle phases. That is a relink, not a retranslation.
- **The hard walls are few and known.** Each has a cheap way round and an expensive way through (Track F decompilation):

  | Wall | Cheap way round |
  |---|---|
  | More than 80 items per category | The 82 placeholder records |
  | 4 enemy kinds per battle | A fix in R1's `on_enemy_spawn` wrapper, or a hook at `0x80077B58` (X4) |
  | 8 KB of enemy records per map | Records are already per map; a buffer redirect (X4) [I] |
  | More than 7 saves per card | Card pages, or slot B's card |
  | More than 24 MB of RAM | A relink to 32 MB |

**What the 2026-09-25 revision changed.** A gap sweep ([plan-gaps.md](research/plan-gaps.md): seven critics, then two skeptics per candidate; 53 of 61 candidates kept) found real errors, and they are fixed here:

- **The race seed.** The game also reseeds at every battle start, so P6 pins three sites, not one.
- **Completion checks that compared two live runs.** Live runs are never identical: two unmodded title runs differ on 22 of 40 hashes (FINDINGS.md, checked here). This plan's are rewritten, PLAN-60FPS-MODS.md's (H9, H17a, M3, M8, M11) are proposed in section F, and rule 7 forbids them.
- **Battle events.** They would have fired every frame. They now fire once.
- **The 4-enemy-kinds limit** is one fix in R1's spawn wrapper (a `--link` once batch A has landed), not a buffer redirect.
- **The "mod saves load in vanilla" promise** was false for mod maps. It now has a fallback, and a decision for you (Q2).
- **The milestones** broke their own dependencies.

It also adds new gameplay (an arena and boss rush, New Game+ and challenge rules, couch co-op, dialogue auto-advance, sailing fast travel), five game systems nobody had mapped, the tools a mod author needs, and a handheld-first set of fixes. Items that belong in the other two plans are listed in section F for their owners, not edited into those files.

**You are needed for:**
- the questions in section G (Q1–Q11). Most decide whether or how a slice is built; start with the three the most sections wait on: the save promise (Q2), distribution (Q3), and the licence route for the community tools (Q4);
- which milestone follows the comfort pack, and whether new art is in scope;
- short playtests where a slice says **Owner**: turbo (section F's M11 item), co-op (P10), the difficulty presets (R3), the arena (N10), the first quest (N3), the endless dungeon (N6), and a small mod built from the guide alone (T10);
- checks with your own files: a Dolphin save imported through `.gci` (P3), the Captain's Log's Discovery count on a save from real play (P7), a save-now Continued in Dolphin (section F's M7a amendment), the Dolphin leg of X2's save matrix, a community texture pack (P8), and one run with your own patched ISO (T7);
- confirming the handheld fixes on the device (H19).

Sizes are evenings, as in PLAN.md: **hours**, **a day**, **several days**, **week-plus**. **[V]** means read in the code or data (quoted in the research report); **[I]** means inferred. Rebuild costs follow CLAUDE.md: **none**, **`--link`**, or **one retranslation** (`--compile --optimize --link`, about two minutes plus the self test). The tracks are **P** (player comfort), **K** (knowledge still missing), **T** (tooling for content), **R** (combat), **N** (new content) and **X** (beyond the GameCube).

---

## A. Where this starts, and the rules it keeps

**State of the framework when this was revised** (0515868; re-read PLAN-60FPS-MODS.md for the current state, because its status lines move with every commit):
- **Done:** M1 (the patch loader), M2 (the safe point and tick), M3 (`mod.dll` on `SoaModApi` v1, `pad_filter`, renderer filters including a texture provider and a projection filter) and M4 (`call_guest`).
- **M5 (settings, `runtime/settings.c`)** is done but for your check.
- **Track H:** H1–H6, H10, H11's workers, H12, H14 and H15a-c are done, H7 is not needed, and the renderer paused at 574c683; see [PLAN-NEXT.md](PLAN-NEXT.md) A.
  - **H8's presenter is built** (DXGI flip model). `SOA_PRESENTER=gdi`, or a DXGI start that fails, keeps the GDI path (`runtime/window.c:327-329`). It waits on you: the display at 60 or 120 Hz, then one windowed session.
- Every slice here names the M and H items it needs.

**The contract** (Track M's, extended).
- **With mods off, nothing changes:** the 23 frame hashes, the self test, `title --check`, `decomp.py`, and `test_memguard`/`test_mods`.
- **A save made with no content mod** loads with or without mods.
- **A save made with a content mod.** The target is that it still loads in the vanilla game and in Dolphin, with the mod's state ignored. **This does not hold yet** (Q2):
  - a Continue opens the saved map's geometry by name, so a mod map's save would fail on a vanilla disc;
  - placeholder gear shows as ダミー ("dummy") there.
  If Q2 chooses the fallback, X2 builds it for both, the map and the gear. Until then, or for good if Q2 keeps this wording, the honest promise is: vanilla saves always load; mod saves load in the port with their mods.
- **Loaded without its mod in the port,** a mod save says what is missing rather than failing later.

**Eight rules.**
1. **Reuse before new art.** Build from the game's own models, stages and rooms first. New geometry waits for T8.
2. **Gameplay changes go through named events, not scattered pokes.** A mod edits a value the event hands it (damage, rewards, the AI's choice), the way the PaperBoat port does. The events live in one place (R1), so two mods that touch damage compose and a conflict is reported. **An event fires once per occurrence, never once per frame:** the battle's phase functions run every frame.
3. **Mods in this repository are text, and never the game's text.**
   - Scripts as assembly, tables as TSV, enemies as TSV rows, and `mod.ini`. The game's binary formats are built on the player's machine from their own disc.
   - A mod holds only its **edits**, keyed by entry or id, and its wholly new entries. A disassembled script is the game's dialogue, and a full enemy table is its data; full dumps belong in `build/`.
   - The guard gains the new suffixes and a content check (T0).
4. **Every content mod ships a scenario** that proves it works headless, and that a battle, a save and a map change still work with it on (T6). N10 and N11 come in milestone 4, before T6 (milestone 5). Until then they check through R0 and their own one-run logs, and they gain T6's walk when it lands.
5. **Hooks never go where the game waits on an interrupt.** A `hooks.txt` entry strips `irq_poll` from every back-edge of its function. The research marks each proposed site; the card writer `fn_801A3B30` and the AI walker `fn_8008A424` are the two to keep `hooks.txt` away from.
6. **Everything that changes the game is recorded.** Settings that change the game, DLL inputs, hotkeys and network events go into the pad recording's event track, or a modded session cannot be replayed (section F's event track).
   - Its settings lines come first, in milestone 2; the hotkey and overlay lines wait on M8.
   - **Settings are already recorded (P6, 24d9235 and 79c9ad8).** The recording's `# config` line names each setting that changes the game, as it is in effect: the seed now, and P1's, P10's, P11's and M11a's keys as they land. A replay made with a different value warns. Refusing a mismatch outright waits for the event track (specs/comfort-pack.md 3.3).
   - P10's pad 2, hold-to-skip and the chord toggles are not in the recording until the event track lands, so those sessions cannot be replayed yet. Each logs that once per run.
7. **No completion check compares two live runs.** Loads run on the wall clock, so two live runs differ even with no mod (checked here: 22 of 40 title hashes).
   - **A check is one of:**
     - a **replay** of a capture;
     - a **same-run contrast**: on and off inside one run, or a before/after in one log;
     - a **timing budget** measured in one live run and reported against a fixed limit, never against another run. Replays run no game-thread callbacks (`--replay` renders and returns before the game starts, `runtime/main.c:1196-1203`), so a budget cannot be measured there;
     - an **invariant with a mutation** that proves it can fail;
     - or it is marked as waiting on K6/D4.
   - **"Identical to off"** in a Done means the contract's checks pass with the mod absent, or a same-run contrast; never an off run compared with an on run.
   - **A retranslation batch** (section E's batches A and B) is checked inside one run of the new build: every new site's call count is nonzero, a pass-through writes nothing, save blocks are checked within that run, and a save from the new build loads in the old build. Never two live runs compared.
8. **Community tools are leads, not sources.** SALSA, ALX, SPICE and SKEWER are GPL-3.0, and SOARandomizer has no licence. Re-derive every layout from the DOL and cite the address; use their names as vocabulary only. Never copy their code or table files (Q4; section F's G6 carries the licence work).

---

## B. What the research established

Five reports, one per question, each in `docs/research/` with its evidence. What follows is what the plan relies on.

### B1. The battle engine ([battle-system.md](research/battle-system.md))

- **Combatants [V].** Setup (`fn_80077428`) makes 12 actors of 276 bytes, pointed to from `0x80309DE4[12]`: slots 0–3 are the party, 4–11 the enemies.
  - HP and max HP are at +20/+24, and the status word at +28.
  - Level and stats start at +128, and attack, defense, magic defense, hit and dodge at +148.
  - MP is at +254, the weapon's Moon Stone element at +256, and the enemy's data record at +272.
- **The battle context `*0x80347390` [V].** It holds the Spirit gauge (+6 max, +8 now, +10 after reservations), the EXP and gold pools (+48/+52), drops, and the battle's own copy of the item inventory.
- **Turns [V].** The phase word `0x8034733C` steps through a function table at `0x802DAE50`:
  - 1 party input, 2 enemy AI and turn order, 3 next actor, 4 wait for the action;
  - 5 after the action, 6 end of round, 7 victory, 8 defeat, 9 escape.
  - **Each phase function runs every frame** until it moves on. Sub-states live at `0x80347338`.
  - Turn order is Quick plus a random bonus, sorted by MSL's `qsort` (a heapsort), and stored at `0x803092F4`.
- **Damage [V].**
  - Hit and critical: `fn_80010B64`. Physical damage: `2·ATK − DEF` (`fn_80010A40`). Magic: `2·(Will + power) − MagDef`.
  - Every value then goes through **`fn_800108EC`**: ±2.5% variance, +1 one time in eight, the element multiplier ÷10, halved when guarding, capped at 9,999. It runs before the KO test, so a hook on its return changes every hit consistently.
- **Enemy AI [V].** `fn_8008A424` walks 64 six-byte steps at record +138:
  - a branch step tests one of 70 conditions (table `0x802DFB10`);
  - an action step picks a command and a target through one of 25 selectors (table `0x802DFC28`).
  - The vocabulary matches the community's ALX tool.
- **Status [V].** Status effects are bits in actor+28 (poison 0x80, KO 0x100, silence 0x200, sleep 0x400 and so on). They are applied through the pointer tables `0x802DBB10`/`0x802DF570` and ticked in `fn_8006FD6C`.
- **Costs [V].** Spell and S-move records are 48 bytes at `0x802C4BF0`/`0x802C52B0`, with the SP cost at +25 and the power at +28. They are read live, so **a data patch changes costs and power at once.**
- **Ship battles [V].** They have their own driver (`fn_80129DD0`), damage function (`fn_80146BF4`) and enemy AI (`fn_80145844`), which reads `rNNNx.tec` tables. The script only sequences the fight, through B[256..275].
- **The RNG is reseeded three times [V, checked here].**
  - Once on every field load (`0x801012AC`/`B0`).
  - **Twice at every battle start**, in `fn_8000A118`: `0x8000A1CC bl OSGetTick; bl fn_8025ECBC; 0x8000A1D4 bl OSGetTick; bl fn_8025ECBC`.
  - The seed word is `0x803469A8`. `OSGetTick` compiles to `guest_timebase_lo(s)` (`emit.py:535`), so the port can pin any of these calls by return address with a relink.

### B2. Enemies and battle data ([enemy-data.md](research/enemy-data.md))

- **Where the live records are [V; one chain confirmed in a RAM capture of a real battle].** In play every enemy is a record inside either:
  - the current map's `.enp`, for random battles: a directory of {id, offset}, the records, then the formations;
  - `battle/epevent.evp`, for scripted and boss fights: 200 directory slots, 146 used.
  - `fn_80077B88` looks the id up.
  - `battle/ebinit%03d.dat` and `ecinit%03d.dat` are read only for formation −1, which no shipped script uses. **Editing them changes nothing in play.**
- **The record [V layout].** It is 524 bytes, or 620 with padding (335 of the 736 copies):
  - a Japanese name (not displayed), element, EXP (+30), gold (+32), max HP (+36);
  - element and status resistances;
  - level and stats (+92..+110);
  - four drop slots (+114): tried in order, first success wins; chance 101–104 means always / 1-in-10 / 1-in-5 / never, and 105 or more crashes;
  - the 64-step AI (+138): special moves 0–308, spells 500–535, Attack 550, Guard 551, Run 552.
- **Ids and models [V].** Ids are one byte, 0–254 (255 is empty), and the id alone picks the model:
  - below 128, `MBnnn.MLD`;
  - 128 and up, through a range table at `0x802ACBE0` to `MGnnn.MLD`.
  - A model animates only the special moves its `.STD` files list.
- **Names are pictures [V].** The name shown in battle is a texture (`ts102nnn`/`ts103nnn`) inside the model file. No English enemy name exists as text on the disc.
- **Limits [V].**
  - 8 enemies per formation, 7 per event battle, 12 fighters in all.
  - **At most 4 different enemy ids in one battle.** The cap is a memo local to setup (4 × s16 at `0x80347388`, the immediate `cmpi r25,4` at `0x80077B34`). A fifth id passes a garbage r4 to `bl fn_800770B8` at `0x80077B58` (plan-gaps.md).
  - **A map's `.enp` must stay under 8,192 bytes decompressed,** because it is copied into a fixed 8 KB buffer (`0x803036E8`) at battle start. That is about 11–13 records.
- **Event battles [V].** They are 37-byte records: magic EXP, party and enemy placements, initiative, and the defeat and escape rules.
  - Records 0–249 are real and 250–255 are filler.
  - Scripts request 235 of them through op 112. About 112 are distinct fights; the rest differ only in the fourth party slot. 29 have the rule "must not lose" (plan-gaps.md).
- **Stages and ships [V].**
  - Battle stages (`sNNN.sml/.sst`) are independent of the enemies, so any stage can host any fight.
  - Enemy ships are 45 × 120-byte records in the executable, plus per-map `rNNNa.tec` AI tables.

### B3. Maps, objects and dialogue ([content-systems.md](research/content-systems.md))

- **What a map loads [V].** A map is `aNNNx.mld` plus `meNNNx.sct`, both named from the map words `0x80311AC4`/`AC8`. Everything else is named by the script: sub-models through op 23, sound banks through op 69, house interiors through an object parameter. The game accepts uncompressed files.
- **Objects [V].**
  - NPCs, doors, chests, save points and triggers are 0x68-byte entries in an MLD's index: a 16-bit id, a type string (one of 185 in `0x802E2888`), parameters, and position, rotation and scale.
  - Pressing A near an id in 3000–4999, or walking into one in 6000–6999, runs the script entry `M%05d`: `fn_8021067C` checks its condition, and `fn_80210550` starts it.
  - Flag 1087 blocks interaction while an event runs.
- **Dialogue [V].**
  - A message is its own script entry of plain text. Op 144 prints it; op 155 offers a choice, answered in sys[9].
  - **`fn_8010BBD8(window, text)` lays out every field message and choice.** It is the text hook.
  - A page is 3 lines of about 48 characters. The game has no text-speed option: `\s(1)` is already the fastest, and A/B reveals a page at once.
- **Shops, chests and Discoveries [V].**
  - Shops: 43 records × 48 items at `0x802EC0A0`.
  - Chests: 119 records at `0x802D59E8`, flag 2048+index.
  - Discoveries: op 177, flag 2900+N, 88 of them.
  - The Sailors' Guild: op 231.
- **The world map [V].**
  - It is a wrapping 6×7 grid of tiles `fielRCx.mld`.
  - Islands are `fldIsland` entries in the tiles, and landing points `fldName` entries, answered by `M04xxx` entries in all 16 `me099a`–`q` scripts.
- **The file table [V].** The game converts a path to an entry number on every open and caches nothing. The port can therefore rebuild the FST at boot, adding or re-pointing entries, and serve the new offsets from host files (`main.c:1143-1171`, `dvd.c:91`).

### B4. The GameCube's limits ([beyond-gamecube.md](research/beyond-gamecube.md))

| Limit | Cheap way round | Size | Rebuild |
|---|---|---|---|
| 24 MB RAM; the game's main heap is 9.64 MB | Raise arena hi: +1.1 MB now; 32 MB with the reserved tail committed (heap 4 grows to 18.6 MB). Leave the size words at 24 MB | hours; a day | `--link` |
| No memory that only mods own | The 8 MB tail as a mod window, plus host memory for DLLs. The heap option and the window cannot both have the tail | a day | `--link` |
| No way for game code to call native code | A thunk registry in `guest_trap` | a day | `--link` |
| 80 items per category | Fill the 82 placeholder records | hours | none (data) |
| 4 enemy kinds per battle; 8 KB of records per map | For the kinds, one fix in R1's `on_enemy_spawn` wrapper (X4); for the 8 KB, a buffer redirect [I] | hours; several days | `--link` for the kinds (R1's wrapper, after batch A); one retranslation for the redirect (batch B) |
| 27,328 flags, scripts use up to 4,505 | Flags claimed by name from 8,192 up (T2); beyond that, the sidecar | hours | none |
| The save has no room for mod state | A container in the save's gap (3,156 B, checksummed by the game) and tail (6,592 B), plus immutable host blobs by GUID | several days | one retranslation |
| 7 saves per card | Slot B's card, or card pages | a day each | `--link` |
| A fixed disc | Rebuild the FST at boot; overlay host files | several days | `--link` |
| Font: ASCII plus a few SJIS ranges | A native glyph lookup plus a bigger buffer; or port-drawn text | a day to several days | one retranslation / `--link` |
| 64 voices, ADPCM, 32 kHz | A host mixer after the guest (`audio_push_block`) | a day | `--link` |
| No way to add geometry | Draws injected before the HUD and before the frame copy | several days | `--link` |

**Stays expensive** (Track F, week-plus each):
- more than 80 items in a category, because 214 constant sites in 76 functions address the tables;
- globally more than 255 enemies;
- more than 7 saves in one card's menu;
- logic at 60 ticks.

**Code, but not Track F** ([plan-gaps.md](research/plan-gaps.md) §1B):
- **A ninth Wanted-list entry** (B5) — *several days, after T4*; Q7 asks whether to build it. It needs:
  - native `fn_801B737C`, `fn_801B6E5C` and `fn_801B7274`/`fn_801B71E8`;
  - T4 edits to the four Guild scripts that pay the gold as a literal;
  - a home for the ninth state byte outside B[100..108], since B[108] is the claim counter: an X2 chunk or a claimed flag;
  - a change to the title routine's B[108] == 8 test (`fn_801EF300`), which a ninth claim breaks.
- **A third crew candidate per post** (B5) — *unsized until K8.* Five functions and two 22-count loops rewritten through X1 thunks, plus new crew records and recruit and post flags claimed by name (T2).

### B5. Five game systems the first research missed ([plan-gaps.md](research/plan-gaps.md))

- **The title routine `fn_801EF300` is the game's own completion checker [V per the report].**
  - It chooses Vyse's title from the Swashbuckler rating (`0x8030BB3C`) and the title table (`0x802C8E54`: 24 records of 34 bytes), and writes the title byte `0x8030B7AE`.
  - For the special titles it tests nearly every completion counter the game keeps: 88 Discoveries, chests at 100%, B[108] == 8 bounties claimed, flag 586, and others.
  - It ends by setting flags 1096, 2850 and 2852 when six conditions hold: the game's own "everything done" award.
  - The loop count of 24 is hard-coded, so new titles need code.
- **The Wanted List is a fixed table of 8 [V per the report].**
  - Each bounty has a state byte at B[100+i] (unknown, posted, defeated, claimed), and B[108] counts claims.
  - Four pointer tables hold the list's text and rewards (names at `0x802EBF7C`).
  - `fn_801B737C` loops `i<8`, and the gold actually paid is a literal in four Guild scripts.
  - A ninth bounty has no free state byte, and a ninth claim would break the title routine's B[108] == 8 test (B4 lists the work).
- **Crew and Crescent Isle [V per the report].**
  - 22 crew, two candidates per each of eleven posts.
  - Flag 1039+n means recruited, and 1061+n records the post choice (`fn_80194A18`, `fn_80194A8C`).
  - The crew table at `0x802D8E64` (36-byte records) feeds the ship's stats through `fn_8021A2B0`.
  - A third candidate per post is code, not data: five functions and two 22-count loops to rewrite, through X1 thunks (B4).
- **Cupil's evolution is a 16-row table [V, checked here].**
  - It is at `0x802C9628`, one row per form: Chams needed, the next form on a Cham, and the next form on an Abirik Cham.
  - Cupil's form is the byte `0x8030BB22` (weapon ids 32–47, also written to Fina's weapon at `0x8030B8BC`).
  - The counts are `0x8030BB24` (Chams, item 259) and `0x8030BB23` (Abirik Chams, item 289). The Chom (item 290) resets both counts to 0 and the form to 32.
  - The thresholds and next forms are table data, so rebalancing the existing forms is a data patch.
  - Two things stay code: the Final Cupil test (`BB23 ≥ 3 && BB24 ≥ 30` → form 47, immediates at `0x801F28FC`–`0x801F2918`), and any form outside ids 32–47, which reads past the table and needs a native `fn_801F28CC`.
- **Story progress for "what next" [V per the report].** B[2..5] (`0x80310A1E`–`21`) hold (part, step) pairs written after each story flag. B[6] goes backwards and cannot be used.

### B6. Corrections to earlier documents

- **Chests and Discoveries** (`story-flags.md` §2). Flags 2048–2166 are **treasure chests** (119, % = n/119). Discoveries are flags **2900+N**, 88 of them, counted into B[51], with a second flag at 2990+N.
- **Crew flags** (`story-flags.md:82`). They are paired with the wrong functions there; 1061–1082 are the post choices (B5).
- **The camera** (FINDINGS census 3). "Camera object 9001" is a **`kmap`** id, the area map. The `a116c` trap is a missing kmap followed by a NULL dereference.
- **The script disassembler.** `tools/sct.py` desynchronises on ops 24, 25, 144 and 155. The DOL's handler table, cross-checked with SALSA's layouts (they agree on 265 of 266), decodes all of them.
- **Enemy files.** `battle/ebinit`/`ecinit` are a fallback the game never uses in play. The live records are in each map's `.enp` and in `epevent.evp`.
- **Round-end and reward hooks** (`battle-system.md:556`, `:565`).
  - `:556` ticks round-end effects from a pre-hook on `fn_8006FD6C` when `0x80347338 == 0`. That can fire on several frames: the function returns before its sub-state switch while effects are busy (`0x8006FD84`, `0x8006FD90`), and the sub-state stays 0.
  - Sub-state 0 does every actor in one call, then sets 50 (`0x8007012C`). Tick after the original, only when the sub-state went 0 → nonzero, as R1's `on_round_end` does.
  - `:565` scales ctx+48/+52 "at phase 7 entry". Point it at R1's `on_rewards` trigger instead: once, when `0x80347338 == 2`, before the original. Phase 7 is entered once, but a hook on `fn_8006F4B0`'s entry runs every frame and compounds.
- **Flag use.** Scripts reference flags up to 4,505, and engine ranges end at 3,077. The earlier "3,072–19,455 is dormant" read was wrong at its low end. Mods claim flags from **8,192** up.
- **The RTC** (PLAN.md:644-647, `soak.md:244`). An RTC pin is named there as the fix for run-to-run differences, but the game never reads the RTC counter. Its seeds and save timestamps come from the timebase.
- **The level recompute** (`story-flags.md:181`, `plan-gaps.md:44`). `fn_801F3024` does not run only at New Game and in the debug picker. It also runs six times at every boot and soft reset, once per character (N11), which is why N11's pre-hook is gated on "NG+ pending".
- **The script-count figure.** Twelve scripts write B[2..5], not thirteen (K11).

---

## C. What I recommend

The first idea list was comfort and community features, the second gameplay and content, and the gap sweep added a third. The picks below have the best ratio of player value to cost.

| Pick | Slice | Why |
|---|---|---|
| Encounter slider and hold-B | P1 | The fans' first complaint. It can ship **today** as a small `mod.dll` on the game's own multiplier byte, chosen by an `encounters` line in `soa.ini` until M16's options |
| Race seed (all three reseeds) | P6 | Pinned reseeds now; reproducible battles, for races and for our own combat tests, once K6 confirms them |
| Dialogue auto-advance and hold-to-skip | P11 | The game has no text-speed option; a few hours on `pad_filter` |
| Couch co-op battles, online through Parsec | P10 | FF6-style co-op for the price of a pad filter; Parsec makes it online with no netcode |
| `.gci` saves | P3 | Bring saves from Dolphin and the console |
| Turbo | M11 (was P2) | The second complaint. It is M11's tick unlock with a player switch; battles gain about 1.6× when drawn |
| The handheld set | F: M18, H19, M19, chords, first run | Rumble, fullscreen, a sleep-proof clock, every action from the pad, no terminal |
| Difficulty presets and boosts | R3, R4 | Standard in JRPG remasters; one event each |
| Battle information | R5 | Enemy HP, turn order, a log; reads only |
| Arena, Boss Rush, Time Attack | N10 | The game's own ~112 distinct boss and event fights, on demand |
| New Game+ and challenge rules | N11 | Keep your party; play "no items" or "fallen stay fallen" |
| Captain's Log | P7 + K7 | The game's own completion checker names the counters |
| Sailing fast travel | P12 | Sailing is a large share of a playthrough |
| Rebalance tables | T3, T5, R6 | Maeson-style rebalances as stackable text mods |
| New gear, a new enemy, a new bounty | N1–N3 | The first new content, from the game's own pieces |
| Remixed and endless dungeons | N5, N6 | New content with no new art |
| The extended-content layer | X1–X4 | Past the disc and save limits |
| Randomizer | N9 | XL, but the step that makes a community |

**Already planned elsewhere:** save anywhere (M7a, with section F's amendment); autosave, once X2's hooks exist; widescreen (M10/M14); 60 fps (Track H); HD textures (M9, with P8's Dolphin names).

**Not picked now:**
- **Archipelago and a GPU renderer.** Each is XL.
  - Archipelago waits on N9 and X2 here (section H).
  - The GPU renderer waits on nothing in this plan. It has a spike and a decision gate (`docs/specs/gpu-backend.md`; PLAN-NEXT M5, G1).
- **Voice acting.** It is content, not code; the voice framework comes with X8's text hook and X5's mixer.
- **More than 80 items per category.** The placeholders cover the first mods.
- **RetroAchievements.** Whether RA would accept a recompiled port is open, and the set looks PAL-only [I: the page returned 403]. Its conditions are leads, not addresses, for this US build.
- **A speedrun kit.** The leaderboards are GameCube runs with loads timed in, so port runs would not count, and verifying runs needs D4.
- **A cheat-code importer.** P1 and R4 cover the codes people use.

---

## D. Tracks

### Track P — Player comfort

**Goal.** The comfort features, each off by default and switched in `soa.ini` (M5). P2, turbo, moved into section F's M11 entry.

**P1. Encounter slider and hold-B** — *hours; ships now as a `mod.dll`, plus one `settings.c` line (a relink)* (M3 done). *Specified as P1a (the mod) and P1b (the encounter contrast) in [specs/comfort-pack.md](specs/comfort-pack.md) 3.4, which supersedes the design below where they differ: `normal` writes nothing, hold-B restores the game's value on release, and the addresses were read in a run (2026-09-25). P1a done (090eea6), its accessory case a self-test case; P1b waits on a card and route in a rate-20 zone where the step counter counts.*
- **How the game already does it [checked here].** The game reads the u8 at `0x8030B7AD` at `0x800C2000`. It sign-extends it, skips it at −1, and otherwise multiplies the encounter odds by byte/50:
  - the usable range is 0–127, which is 0–254%;
  - 128–254 are negative and turn encounters off;
  - the code path is shared by the world map (map 99).
- **What the mod does.** From `on_frame_end` in the field it writes `base × k`, clamped to 0..127, where base is the value the game itself would hold there (−1 counts as 50).
  - **Multiply, never overwrite.** Overwriting would cancel an equipped accessory's effect.
  - **The mod works out base itself and never rereads the byte.** After the first frame the byte holds the mod's own write, so rereading and multiplying compounds: half falls to 0 in about six frames, and double reaches 127 on the second.
  - **Working out base [V].** Only two places write the byte. `fn_801EF7E0` stores −1 (`0x801EF82C`), then calls `fn_801EE5A4` for characters 0–5 in order, party or not (loop at `0x801EF8A0`, no early return). `fn_801EE5A4` stores the value of effect code 84 (`0x801EEC44`) when the character's accessory has one, so the last character that has one wins.
    - The accessory is the u16 at `0x8030B7F4 + 92·c + 20`, and its four {u8 code, u8, s16 value} records are at `0x802C6E10 + (id − 160)·40 + 24`.
    - The mod repeats this scan every frame. On this disc only accessories 210 (value 100) and 211 (value 5) have code 84.
  - **Remembering the last write is not enough.** At double with nothing equipped the mod writes 100. Equipping accessory 210 then makes the game write 100 too, so a mod that treats any other value as the game's keeps base at 50, and the byte holds 100 instead of 127.
  - It must be a DLL: `patches.txt` writes whole aligned words, and this byte is not aligned.
  - `fn_801EF7E0` resets the byte after equipment changes, so the write is every frame.
- **Hold B to avoid:** the same mod reads the pad through `pad_filter` (M3b).
- **P1 is the only player-facing encounter setting.** M6's `*= k` scales the zone rates and keeps accessories, but it refuses map 99, so it stays a modder's tool.
- **Presets:** off (no random battles), half, normal, double.
  - **Until M16,** the DLL reads the preset from `SOA_ENCOUNTERS` (unset is normal) with `GetEnvironmentVariableA`, because the mod API has no option call yet (`runtime/soa_mod.h`).
  - `settings.c`'s `k_settings` gains an `encounters` line, so `soa.ini` can set it; today `soa.ini` reports and ignores a key it does not know. The setting changes the game, so it joins the event track's settings lines (rule 6) when they land in milestone 2. Until then the `# config` line does not carry it (`si.c:300`), so the DLL logs its preset once per run, and a recording replays as made only with the same `SOA_ENCOUNTERS`.
  - The variable is also how the checks pick a preset, because checks run with `soa.ini` off.
  - M16 (milestone 2) replaces both with a declared option.

*Done:*
- **The value held (an invariant with a mutation).** In one run per preset, each against its own fixed values, a range `SOA_PEEK` of the word `0x8030B7AC` over 600 field frames reads in its second byte (`0x8030B7AD`):
  - with nothing equipped, 25, 50 and 100 at half, normal and double;
  - with accessory 210 poked into character 0's slot, 50, 100 and 127. The slot is the u16 at `0x8030B808`; `SOA_POKE` writes whole words, so keep the other half as peeked.
  - A peek fires before the mods in the same frame (`poke_at_frame`), so a frame in which the game rewrites the byte shows the game's value, and the next frame is back at the mod's.
  - The mutations: a mod that overwrites instead of multiplying reads 25, 50 and 100 with the accessory, and one that rereads the byte sinks to 0 at half and climbs to 127 at double. The contrast below would pass the second.
- **Same-run contrast.** One run on a rate-20 zone of `a101b`: zones 2 and 3 (encounters.md §2; zones 1 and 4 are rate 0 and never fight). Which floor carries them is still open (encounters.md, "Still unknown").
  - A test switch in the DLL cycles k through ½, 1, 2 and 0. It moves to the next value after each battle, or after 600 moving frames with no battle.
  - At the start of each trial it writes 480 to the step counter `0x80346D28`, which counts frames in which the player moved. There the odds are about 0.9%, 1.9% and 3.75% a moving frame at half, normal and double; in general they are 0.09375% × rate × k at N = 480.
  - Over at least 40 trials per nonzero setting, the mean number of moving frames to a battle orders 2 < 1 < ½, and every k = 0 trial reaches 600 moving frames with no battle. A mod that does nothing fails the second.
  - A simulation of the roll at `0x800C2000`–`0x800C2110` gives the chance of a false failure: 0.1% at 40 trials, 4% at 20, 64% at one. Normal survives 600 moving frames with odds of about 2×10⁻¹⁴.
- **Hold-B, in the same run:** normal trials with B held reach 600 moving frames with no battle.
- **A sky run** (map 99, which reaches `0x800C2000` through `fn_800C1A50`) repeats the peek and the contrast in one run, with the simulation rerun for the sky's rates.
- **Comparing settings across separate runs,** even with P6's seed and one pad script, waits on K6 (rule 7). All three equal would not be a pass there: a mod that does nothing gives it.
- The contract holds.

**P3. `.gci` import and export** — *hours. Specified in [specs/comfort-pack.md](specs/comfort-pack.md) 3.11 as P3.*
- `cardformat.py export CARD SLOT out.gci` and `import CARD in.gci`: a 0x40-byte directory entry plus blocks.
- It refuses a wrong game code, a full card and a corrupt file.
- Export warns when the save's map has no op 138 and the save carries no X2 fallback. Such a save may trap in Dolphin (section F's M7a amendment).
- `.gci` is added to the guard (T0).

*Done:*
- Synthetic round trips are byte-identical, with mutations refused (pytest, no game data).
- **Owner:** a save exported from Dolphin imports, verifies READY, and Continue lands on the saved map.

**P4. Fast boot and quick resume** — *a day, after M19 (a clock that re-anchors on speed changes).*
- Run guest time fast (`SOA_SPEED`, made switchable at run time) until the title, sound muted and, when windowed, drawing skipped.
- Optionally drive Continue into the newest save.
- **Measure when the title appears first.** "53 s" is the scripts' first START at frame 1600, not a measured arrival.

*Done:*
- **An invariant with a mutation.** With fast boot on, the run's own log shows the title's first frame within N wall seconds of launch.
  - N is fixed once and written into the check with the machine it was measured on: at most half the arrival time of one measured run with fast boot off, on the same machine and pad script.
  - The mutation: a run with fast boot off misses N. A boot cannot be contrasted inside one run.
- Quick resume lands on the saved map (map loads in the log).
- Off, `title --check` passes (the contract).

**P5. Picture options** — *hours each. Specified in [specs/comfort-pack.md](specs/comfort-pack.md) 3.13 as P5a and P5b.*
- Gamma, colour-blind simulation or correction, a CRT look, a flash limiter (Xbox guideline 118 thresholds) and a sharp-bilinear scaler, applied in `present()` after `g_screen`.
- Deflicker off skips the copy filter in the display copy only.

*Done:*
- Each filter is a pure function with a unit test on a synthetic image: gamma 1.0 changes nothing, 2.2 changes pixels, and the limiter damps a synthetic 5 Hz full-screen flash.
- A capture taken *after* `present()` is opened for each. `SOA_HASH` reads `g_screen` before `present()`, so it cannot see these.
- **Deflicker off is checked on replay,** because the live title is not a hash oracle (FINDINGS.md:1983).
  - `scenario.py replay` drops every `SOA_*` variable (`replay_once`), so run each capture directly: `gen\soa.exe --replay <base>` with `SOA_HASH=1` and the switch set. Use copies of the captures kept outside `build/fifo`, because `--replay` overwrites `<base>.png`.
  - With the switch unset, `scenario.py replay` stays 23/23. With it set, all 23 hashes move: every capture's display copy is filtered (BP 0x53 = `30A208` and 0x54 = `00820A`, 16/32/16 over three rows, in all 23; PLAN.md:479).
  - "The display copy only" cannot be seen in a hash of `g_screen`, so it is a synthetic-stream test beside `test_gxr_copy_filter.py`, with the switch on: a display copy under the game's weights comes out byte for byte the same as under the SDK's identity set (0,0,21,22,21,0,0), and a texture copy under the game's weights does not.
- It does not wait for H8.

**P6. Race seed** — *hours, `--link`. Done 2026-09-25: 24d9235, and the follow-up 79c9ad8 (each pin in the log with a checker, the reload after a battle, the recording naming the seed in effect). FINDINGS "P6: the race seed pinned, and settings that change the game recorded", "P6, followed up". Specified in [specs/comfort-pack.md](specs/comfort-pack.md) 3.3.*
- In `guest_timebase_lo`, return a pinned value when `s->pc == 0x8023851C` (`OSGetTick`) and `s->lr` is `0x801012B0` (field load), `0x8000A1D0` or `0x8000A1D8` (battle start).
- The value is derived from the user's seed and a per-site counter.
- No `hle.txt` line and no retranslation.

*Done:*
- **In milestone 1, in `battle.scn` (the deck fight, then the load into `a201a`):** one reseed per field load, including the reload after the battle, and two per battle start, each counted in the report and each taking the pinned value, with each site's count nonzero (lr `0x801012B0`, `0x8000A1D0` and `0x8000A1D8`).
  - srand (`fn_8025ECBC`) is a single store of its argument to the seed word `0x803469A8`, so a `SOA_WATCH` on that word shows each reseed storing the value the report says that site's pin returned. `rand()` stores there too, so aim the watch with `SOA_WATCH_FROM`.
  - The mutation: with the second battle-start lr set to `0x8000A1DC` instead of `0x8000A1D8`, the report counts 0 pinned reseeds at that site, and the check fails.
  - Until K6, this bullet is P6's whole Done.
- **After K6** (it is K6's own two-run question, so it waits on K6 under rule 7; R0's log alone is not enough): if K6 finds battles repeatable, two runs with equal seeds give the same first-round order and damage in R0's log. A run with a different seed must give a different log, which catches a pin that ignores the seed. If K6 finds they are not repeatable, this bullet is dropped and P6 keeps only the pinned reseeds (section E, "After K6").
- Add "and at every battle start" to PLAN-60FPS-MODS.md's note on what replays from a seed (section F). *Adopted: PLAN-60FPS-MODS.md:723 says it.*

**P7. Captain's Log** — *several days, after M8 and K7; the owner check after P3.*
- **The checklist:**
  - Discoveries: flags 2900–2987;
  - chests: flags 2048–2166, % = n/119;
  - crew: 1039–1060;
  - the bounties: B[100..108];
  - Cupil: `0x8030BB22`–`24`;
  - the rating and title: K7;
  - Chams, Moonfish, Piastol and the giant monsters: K2;
  - kills: `0x8030BB44`;
  - the game's own "everything done" flags 1096, 2850 and 2852.
- **Missable warnings** from story flags.
- **P7b, "Where am I and what next?":** shown at Continue and in the overlay. One objective line keyed on the story key K11 chooses (the highest main-story flag, with B[2..5] for step lines where scripts write it), plus a "last time" note naming the last fight and the most recent Discoveries. Write about 12 part-level lines first; step-level lines are content work.
  - **The last fight:** record it once at battle start, from the request block `0x803097F0`: +0 is the event id, or −1 for a map battle, and then +2 is the formation. `on_rewards` does not say which fight it was, and `on_enemy_spawn` also fires for "Call EC" spawns in the middle of a battle (`fn_800692D8`).
  - **Recent Discoveries:** the game keeps flags 2900+N with no order, so the note cannot be rebuilt at Continue. Log each new one as it is set (diff flags 2900–2987, or hook op 177), and store the log in T2 flags or the sidecar.
- A phone page, off by default, serves a snapshot the mod takes at the safe point. It uses the same fields T12(b) would publish, but it does not wait on T12, which is unscheduled. The page is read-only: nothing can write through it. It is loopback-only unless you opt in with a token (section F, trust boundary).

*Done:*
- **Owner:** on a save made in real play whose B[51] (`0x80310A4F`) peeks nonzero, the Discovery count matches the game's own menu (frame opened).
  - The save comes from Dolphin through P3, or from the port after sailing to a Discovery.
  - The part-L save cannot serve: the part select (`ME355A`) sets no flag above 1862, never runs op 177 and never writes B[51], so both sides read 0 and the check could not fail.
- Poking one Discovery flag moves the count by one.
- **Chests have no screen of their own.**
  - **Count the chests a run opens** with `SOA_WATCH=0x80310C3C,0x10` (the four words holding flags 2048–2166) and `SOA_WATCH_FROM` past the save restore. Each watch line from op 154's store (the `stwx` at `0x8020C790`, in `fn_8020C390`) is one chest opened.
  - This needs no rebuild. A `config/trace.txt` tracepoint would cost a full `--compile`, outside batches A and B; once T11 lands, its script tracer counts op-154 hits directly.
  - **Test the thresholds against the game's own title routine.** Its answer is the title byte `0x8030B7AE`, read with `SOA_PEEK` at the end of a frame in which `fn_801EF300` ran (a load runs it through `fn_801EF7E0`). It stores 23 there first, so a watch's first store is not the answer.
    - Set the rating `0x8030BB3C` (s16) to at least 226, or the routine never tests chests, and keep B[105] (`0x80310A85`) ≠ 1, or title 23 overrides everything.
    - **100%:** B[51] (`0x80310A4F`) = 88, B[108] (`0x80310A88`) = 8, and flag 586 (bit 0x400 of `0x80310B84`). Then 119 chests gives title 15, and 118 gives title 16.
    - **90%:** B[51] = 88, and B[108] ≠ 8, since 8 selects title 16 before the 90% test is reached. Then 108 chests gives title 17, and 107 gives anything but 17.
    - Pokes write whole words, so keep the other bytes of each word.
  - **P7's % agrees with the routine:** int(100·n/119), truncated as the routine does (`fctiwz` in `fn_8025A1A4`), so 107 chests reads 89 and 108 reads 90.
  - Without the conditions above, the mutation itself cannot fail.
- **Budget (rule 7):** the time to build the checklist at the safe point (p99 and max), from one live run, against a limit fixed before the run. The phone page serves that snapshot and adds nothing to the game thread.

**P8. Texture packs by Dolphin's names** — *several days; amends M9.*
- Name textures as Dolphin does: `tex1_{w}x{h}[_m]_{xxh64}[_{tlut}]_{fmt}`, where the TLUT hash covers only the palette entries used.
- Load PNG and DDS, including BC7, lazily, from `load/textures/GEA`.
- **M3c's texture provider already froze a hash with no version field** (section F). P8 computes Dolphin's names inside the renderer, once per decode.

*Done:*
- A test pins Dolphin's name for synthetic textures, with expected values from a reference XXH64.
- Malformed-DDS tests.
- **Owner:** a texture from a community pack replaces its original in a snapshot.
- Pack off: 23/23.
- **Budget (rule 7):** the worst first-sight texture load (the max, not p99, which hides it), from one live run through a pack-heavy area, against a limit fixed before the run.

**P9. Developer rooms** — *hours, after M7b and M8.*
- English menu entries for the part select (`ME355A`), the ship-battle select (`398A`, which reaches the four unused enemy ships) and the stage picker.

*Done:* each reproduces its FINDINGS recipe, with the frames opened.

**P10. Couch co-op battles, and online through Parsec** — *hours to several days, after M5; M3b is done. Specified in [specs/comfort-pack.md](specs/comfort-pack.md) 3.12 as P10a and P10b.* **Owner.**
- **How it works.**
  - A `pad_filter` mod reads whose turn it is (`0x80347330`), gated on scene 7 and phase 1. When a co-op member's command wheel is open, it passes pad 2's input to port 1.
  - The mod reads pad 2 itself, through XInput on its configured slot, because the runtime reads slot 0 only (`window.c:433`). In checks, pad 2 is a test script the mod reads from an environment variable instead.
  - Player 1 keeps the field and the menus.
  - Parsec presents a remote friend as a second XInput pad, so the same mod is online co-op with no netcode.
- **Care points.**
  - Check an absent pad at most once a second, as `window.c` does.
  - At a handover, pass neutral input until the incoming pad's buttons are released. Otherwise a thumb resting on A confirms the next member's command.
  - Make the pad slot configurable.
  - **Replays.** The mod reads pad 2 after the recording has its copy of pad 1 (`si.c:758-760`), so a co-op session does not replay (rule 6) until pad 2's state goes into the event track (section F, milestone 2). Until then the mod logs, once per run, that the session cannot be replayed.
- **A one-hour spike first:** going back to the previous member with B, members who cannot act (`+28 & 0x6D00`), and ambush rounds.
- Ship battles come later, after K5 and R9.

*Done:*
- **In milestone 1, with no R0:** `battle.scn`'s deck fight (Vyse and Aika), run with the mod through `scenario.py run battle --env`. Pad 2 is a test script of `frame:button` pairs that the mod reads from an environment variable.
  - Pad 2's presses command Aika: a frame opened on her action shows the command pad 2 chose.
  - On her turn the `[si]` log, written after the filter (`si.c:763`), shows pad 2's presses and none of pad 1's, while the `SOA_PAD_RECORD` file, written before it (`si.c:758`), still holds pad 1's A presses. That is a same-run contrast.
- **Once R0 lands (milestone 2):** the same check on R0's forced formation.
- The handover test: A held across the handover does not confirm.
- **Owner:** two pads, one battle.

**P11. Dialogue auto-advance and hold-to-skip** — *hours; M3b is done. The spike is done (b911380, FINDINGS "P11's spike"): the window's state word is `0x80346E64`, the task is at `0x80346E4C`, and `0x80346E60` below is the wrong word (the draw stores 0 back to it every frame). Re-specified in [specs/comfort-pack.md](specs/comfort-pack.md) 3.5 as P11 (auto-advance) and P11b (hold-to-skip, after CH1). P11 done (664f005).*
- A `pad_filter` mod finds the message window through `0x80346E60`. A page is complete when window+56 ≥ window+54; then it sends one A.
- It leaves choice boxes alone (a spike finds SELECT's marker; `0x8030E468` is also set for plain messages) and respects window flag 0x1000.
- Hold-to-skip sends A on every complete page while a chord is held.
- **Not worth doing:**
  - "fast" text, because `\s(1)` is already the minimum;
  - "instant" text, because A already reveals a page;
  - flag 1087 as a trigger, because every NPC talk sets it.

*Done:*
- Inside one run: a scripted conversation advances with no A presses in the pad script, and stops at a choice until the script answers it.
- The mutation: with the mod off, the same pad script stalls at the first page.

**P12. Sailing fast travel** — *hours, after M7b, M8 and K9.*
- The sky-only turbo (`0x80347464 == 1`) is M11's sky-only option (section F), after H13; P12 does not build it.
- **Fast travel to ports already landed at:** do what a real landing does. Go to the destination of the port's `M04xxx` entry and set sys[15] = 990, "arrived from the world map".
  - Allowed only on the world map: map word `0x80311AC4 == 99` and `0x80347464 == 1`, with no event running. The sky-mode flag alone also covers the ship-piloted dungeons 122a, 125a/b/d and 127a/b (`fn_800C8D90`), and a fast travel from one of those skips story.
  - Each port is gated on its own landing or story flag. Flags 1312–1479 are the map screen's fog grid, not a list of visited ports.
  - Storm toggles stay out: storms probably gate the story's order.

*Done:* in one run from a world-map save made before the port is first visited, a fast travel to it is refused; a real landing there logs its map load and `sys[15]` = 990; back on the world map, a fast travel to the same port logs the same map load and the same `sys[15]` (a before/after in one log, rule 7). It is also refused during an event, on foot, and in the sky-mode dungeons (checked in 122a and 125a, which both have a save point).

**P13. Faster loads, measured first** — *hours to decide.*
- Turbo does not shorten loads.
- Split load time into disc-busy time and decompression. The modelled seek is already 6 ms against about 128 ms on hardware, and a battle loads about 0.75 MB, so expect at most about 1 s a battle.
- Drop the idea if disc-busy time is small.
- If it ships:
  - scale only the transfer and seek terms (`dvd.c:149`), with a floor;
  - teach `soak.py` to catch "memFree Error", with a mutated log.

*Done:*
- Disc-busy and decompression time for one battle load and one map load, from one run, are in FINDINGS with the decision.
- If it ships:
  - for each load, the log gives the model's disc time and the scaled time used, and the scaled time is the model's times the scale, never below the floor (a same-run contrast);
  - `soak.py` fails a log with "memFree Error" mutated in;
  - off, the contract holds.

**P14. Photo studio** — *several days, after M3c (done) and a chord.*
- A hotkey arms a FIFO capture at the next frame boundary.
  - It writes to the photos folder, never `build/fifo`. That is `SOA_FIFO_DIR`'s default and holds the 23 pinned captures, named by frame number (`config/fifo_manifest.tsv`), so a photo taken at a pinned frame would silently replace a capture that cannot be regenerated.
  - Each photo is named so that two sessions reaching the same frame do not collide (a timestamp prefix, for example).
- An offline `--replay` then renders it three ways:
  - **tiled k×k** through the projection filter, up to 5120×3840;
  - with an **orbit camera** through a new view-matrix filter;
  - with the **HUD removed**, by pushing orthographic draws past the far plane.
- **Each render writes its own file** (`<base>.tile-<i>-<j>.png`, `<base>.orbit.png`, `<base>.nohud.png`), never `<base>.png`. Plain `--replay` always writes `<base>.png` (`main.c:1200`), so otherwise the k² tiles and the three renders would overwrite one another. The pair replay's `.mid.png` already works this way.
- **Tiling maths:** multiply p0–p3 by k, then shift p1 and p3 by the tile's NDC offset o = 2t+1−k. The shift is +o in perspective (w = −z) and −o in orthographic (w = 1), so the sign differs between the two (`transform` in `gxr.c`).
- It needs no K4, because the capture holds the matrices.
- The photos folder goes in `FORBIDDEN_DIRS`, because a capture holds a 24 MB RAM image.
- **Known limits:** copies to texture sample the zoomed tile, lights must rotate with an orbit, billboards keep facing the old camera, and culled geometry is missing.

*Done:* identity settings reproduce the pinned hash on all 23 captures, and a stitched k=2 still is opened and compared with a 2× upscale.

### Track K — Knowledge still missing

Each is **hours to a day, no rebuild**, written up in FINDINGS or a research note with [V]/[I].

**K1. Confirm the free flags.**
- Watch the range T2 hands out: `SOA_WATCH=0x80310F3C,0x958`, flags 8,192–27,327, with `SOA_WATCH_FROM` past the New Game clear and a save restore. Each of those spends the watch's 201 lines in one frame.
- A mod that diffs the flag block at each safe point is the stronger detector, because native `memcpy`/`memset` never reach the watch.
- Scan saved blocks too, including late-game saves.

*Done:*
- The detector of record is the mod that diffs the flag block at each safe point (`on_safe_point` plus `read_bytes`, `soa_mod.h:91`/`:74`). The watch only names writers.
- **A positive control in every run:** `SOA_POKE` a flag ≥ 8,192 late in the run, after any game over, Continue or New Game. A poke goes through `mem_w32`, so the watch sees it too (`cpu.h:190`).
  - Both the diff mod and the watch must report it.
  - A run where either misses it, or where the watch prints 201 `[watch] …/N = …` hit lines (the header line is not counted), is inconclusive, not a pass. The watch goes blind after 201 hits (`trace.c:108`), and any clear or restore after `SOA_WATCH_FROM` uses all 201.
- Zero other writers reported by the diff mod across three soaks and the part cards, each run with a passing control.

**K2. The other collectibles.**
- Find Chams, Moonfish, Piastol and the giant monsters.
- The Wanted List (B[100..108]) and Cupil (`0x8030BB22`–`24`) are known statically (B5). Cupil still needs one peek on a save that has Fina, as plan-gaps.md asks.
- The RetroAchievements set's public conditions are leads only: the set looks PAL-only [I].

*Done:* each has an address and one confirming peek, and Cupil's bytes are peeked on a save that has Fina.

**K3. Enemy name pictures and model files.**
- Find how the name texture is chosen when it is not the model's first.
- Find whether copied `.STD` files point back at their original model.

*Done:* layout, and one repainted name shown in a battle (frame opened).

**K4. The field and world-map camera** (M12's camera spike).
- Ops 72/74 write a follow-camera struct at `0x802E0084` [I]. Confirm it, and find the view matrix X6 and a live photo mode need.
- Comes before X6 and N8.

*Done:* one peeked matrix matches a captured frame's XF view.

**K5. Ship-battle input.** The player-side command and SP rules, and the 88-byte timeline entries.

*Done:* layout and addresses, each [V] from the disassembly or confirmed by one peek in a ship battle (the part-L sky-encounter recipe in FINDINGS).

**K6. Deterministic battles.**
- With P6 pinning all three reseeds, and commands written when phase 1 begins (`0x8034733C == 1`), do two runs give identical damage logs?
- If not, name the per-frame random consumer: there are 481 `rand()` call sites.
- The D4 fallback stays, because disc completions still follow the wall clock.

*Done:* two runs of the harness give the same log, or FINDINGS names what differs.

**K7. The title routine as completion checker** (`fn_801EF300`) — *static, then one run from the part-L save.*
- Name every counter it tests: title 21's count over item ids 471–478, title 19's u32 at B[78..81], and the B[105] override.
- It feeds K2, P7 and a "title" table in T3.

*Done:*
- Every test in `fn_801EF300` is listed with its address and the counter it reads, [V] or [I]: the split at rating 226 (`0x801EF32C`), the special titles (`0x801EF474`–`0x801EF648`), the award (`0x801EF650`–`0x801EF7A8`) and the B[105] override (`0x801EF7B4`).
- **One run from the part-L save.** The title byte `0x8030B7AE` is not saved (the saved party block starts at `0x8030B7F4`, save-load.md), so read it after an equipment change, which calls the routine (the `bl` at `0x801EF990` in `fn_801EF7E0`).
  - Peek the rating `0x8030BB3C` and the title byte. The byte is the title the static reading predicts: below 226, the first row whose threshold at `0x802C8E6D` + 34·i is ≥ the rating. The status screen shows that title (frame opened).
  - Then poke, reading the byte the same way after each. Each gives the title the static reading predicts from the peeked counters: the rating to 226 gives 14 while no special condition holds and not all 22 crew are recruited; kills `0x8030BB44` to 2,500 then gives 20; B[105] (`0x80310A85`) to 1 gives 23 over everything.
  - `SOA_POKE` writes whole words, so each poke keeps the neighbouring bytes as peeked.

**K8. Crew posts and Crescent Isle.**
- Fields of the crew table `0x802D8E64`: +17, the ship stat id and bonus at +18/+20, +22, +23 and +30.
- The equipment side of `fn_8021A2B0`.
- Fix `story-flags.md:82`, `ship-worldmap.md:42` (017a–f, h, i) and `content-systems.md:266` (add flags 1061–1082).
- A third candidate per post is code, not data: five functions and two 22-count loops to rewrite, through X1 thunks ([plan-gaps.md](research/plan-gaps.md)).
- Comes before T3's crew table, X7's crew perks and N9's crew shuffle.

*Done:*
- Each listed field of `0x802D8E64`, and the equipment side of `fn_8021A2B0`, is [V] with the address that reads it, or [I]. The three research lines are corrected in the same change.
- In one run, one crew member not already in the list, whose record names a stat and carries a bonus (+18 not 0xFF and +20 nonzero: records 0-6, 10 and 19; for example +18 = 4, +20 = 30), added by poke, moves the ship stat that +18 names by exactly the bonus at +20. The other 13 records have +18 = 0xFF and +20 = 0, so for them the stat does not move whether or not the poke reached the list. `fn_8021A2B0` sums the bonuses of the crew ids in a 22-byte list it is passed, and reads no flags (`0x8021A538`–`0x8021A5E0` [V]), so the poke goes wherever K8 finds that list is filled from.
- The third-candidate rewrite (B4) is scoped: the five functions and the two 22-count loops are named by address [V], and the work gets a size in this plan's units. B4's "unsized until K8" is replaced with that size in the same change.

**K9. The ship's controls.**
- Add a watch on the ship object (`fldShip`, `fn_800D1E58`) to the world-map run PLAN.md D5 already plans, to find its speed fields.
- Check first what `0x8030CD5C` holds; only an init writes it.
- Record +64 in the ship table is not ship HP (plan-gaps.md:93); ship HP is +24 of the ship object (battle-system.md:478).

*Done:*
- The speed fields are named from the watch in D5's run, and what `0x8030CD5C` holds is stated [V] or [I].
- A poke to one speed field changes the ship's speed within the same run, before against after (frames opened).

**K10. The camp menu and the Captain's Journal.**
- The menu's label table (`0x802E8FD0`) and page-handler table (`0x802E9418`, 8 slots).
- The leftover rows (Socket 1/2, Dispatch, an untranslated "Change Name") could host a mod page through an X1 thunk.
- The journal is a table: title, chapter, progress gate, one picture per chapter.
- Pinta's Quest's handlers are stubs that return 0, so its loot cannot be revived there.

*Done:*
- Both tables are decoded: the labels, and the 8 handler slots, each resolved to a function start in the disassembly and named or marked a stub.
- The journal's record layout is written up with its table address.
- One page opened by pad in a run matches its label (frame opened).

**K11. Story progress keys** — *static, hours.*
- The part cards cannot answer this. `ME355A.SCT` never writes B[2..5], so every card holds `card-saved`'s values or whatever its landing event wrote.
- List every write of B[2..5] across the 258 scripts, each with the story flag set just before it. Use `tools/sct.py`, plus a raw scan for the tokens 0x10000002–5, which the desync on ops 24/25/144/155 cannot hide.
- Look in the DOL for native writers of `0x80310A1E`–`21`.
- A first scan finds 12 scripts (`sct.py` alone shows 9). Every write is a SETB right after a FLAGSET, with B[2] = flag / 50 rounded down: 0 at flag 3, up to 6 at flag 321 in `me018a`. There are none after flag 321, and the world map writes only B[4..5] (099a/e/f, flags 1087/1105).
- If nothing native carries the bytes further, P7b keys its part line on the highest main-story flag set (blocks of 50, set in story order, story-flags.md:8). It uses B[2..5] only for step lines inside parts A–G.

*Done:*
- the table;
- the answer on native writers;
- P7b's key chosen;
- one peek of `0x80310A1C`/`0x80310A20` on `card-saved` that matches the table's row for its highest flag.

**K12. Free status bits.**
- List every mask the battle code tests on actor+28, and name the unidentified bits 0x2, 0x20000, 0x800000 and 0x01000000.
- The end-of-battle write-back never copies actor+28, so the save question is closed.
- R2 points here.

*Done:*
- Every mask the battle code tests on actor+28 is listed with its test site.
- Each of 0x2, 0x20000, 0x800000 and 0x01000000 is named, or shown free in the disassembly: no setter and no test, with whole-word writes such as native `memcpy`/`memset` checked too. Never by a watch, which sees only one run.

### Track T — Tooling for content

**T0. The guard and the content check** — *hours. Done 2026-09-25 (1c7b780, 4041dfc): 43 suffixes, 18 directories, the signature check; T0c (012164a) added card images and saves under any name and read history for content. The enemy-table check is T5's, in its Done list since 012164a.*
- **Suffixes:** `.gci`, `.dds`, `.dat`, `.ogg`, `.flac`, `.mp3` and `.opus`.
- **Directories:** the pack, blob, photo and `out` directories.
- **A content check** that refuses dump headers in a mod folder. The full-column enemy-table refusal moved to T5 (4041dfc): a row count was only a guess at "a whole column", and would refuse data-driven mods.
- **Also** update CI's regex copy (`ci.yml:34`) and `test_guard`. CLAUDE.md says 34 refused extensions while TESTING.md:155 and the check skill (`.claude/skills/check/SKILL.md:72`) say 28; fix every copy in the same change.

*Done:* `test_guard` refuses each suffix and directory, and a mutation test proves the content check fails on a dump.

**T1. The virtual disc** — *several days, `--link`* (beyond-gamecube.md §4, content-systems.md §8). *Specified in [specs/disc-layer.md](specs/disc-layer.md) 3.8 as I6 (replace, add, alias), I7 (deltas) and I8 (per-map swaps), on I1's seam.*
- **Where:** in `main.c`, as a pass of its own after `sys/fst.bin` is read (`:1143-1149`) and before its size bound (`:1163`). Read the enabled mods' file lists from `SOA_MODS` without running any mod's init, parse `sys/fst.bin`, and rebuild it.
  - The rebuilt size goes through the existing bound: the FST copy is the one boot write into the image that carries its own bound (`:1153-1158`).
  - `fst_addr` (`:1169`), and with it arena hi and `0x80000038`, then follow the new size. Set `fst_max` to the new size rather than `boot+0x42C` (`:1168`; content-systems.md §8 step 5), so `0x8000003C` agrees. Nothing in the game reads it.
  - `mod_load` stays after `setup_low_memory` (`:1171`, `:1181`). 2754cba moved it there so the low-memory block cannot overwrite what a mod's init writes (the comment at `:1173-1177`), so the rebuild cannot wait for it.
- **The rebuild can:**
  - **replace** a file by re-pointing its offset and length;
  - **add** a file by inserting it and re-serialising;
  - **alias** a new name onto an existing extent.
- **Serving:** virtual offsets above `0x57058000`, and an overlay table in `dvd.c` `disc_read`, including reads that straddle two extents.
- **Deltas:** a file may also be a binary delta against the player's own file. Decide it now, because T13 and the after-T4 fallback for scripts that cannot round-trip (section E) depend on it.
- The pack is recorded in the pad-config line.

*Done:*
- No mods: the FST bytes and the contract are unchanged.
- An override of `me101b.sct` shows a changed line (frame opened).
- An alias `a045a.mld` onto `a002a.mld` plus a new `me045a.sct` is warpable by name and draws.
- A path collision between two mods is refused, naming both.

**T2. Content ids claimed by name** — *hours for the core; several days for the remap.*
- A mod names what it needs (`flag bounty.accepted`, `map sky_rift_1`), and the loader assigns numbers into a local `mods.lock`: flags from 8,192, map numbers from the free list (400–499 first), placeholder item ids, ship stages 584–599, script opcode stubs and thunk slots.
- Each mod's name → number table goes into its X2 chunk from the first release; remapping on load comes later.
- Until the remap lands, the loader compares a save's table with the local lock and reports each name whose number differs, naming the mod and both numbers. It does not guess.
- **Rules:**
  - flag numbers are never reused;
  - the small pools (6 weapons, 3 items, 16 ship stages) are freed with a warning;
  - enemy ids stay fixed claims per map, because the id picks the model.
- A vanilla or Dolphin re-save keeps the flags but wipes the table, so the loader falls back to the local lock and warns.

*Done (core):*
- Two independently written mods, each asking for a flag, both load and receive different numbers, recorded in `mods.lock`.
- A save moved to an install whose `mods.lock` gave that name a different number (the mods installed in the other order, or a third mod claimed 8,192 first) is reported on load as a mismatch, naming the mod.

*Done (remap):* the same save, on that install, reads its flag back at the local number, and re-saving writes the local table.

**T3. Table patches** — *several days, after T9; the crew table after K8.*
- Row-and-column edits applied at boot for executable tables and at load for files, for example `weapon Cutlass attack = 30`, `spell 12 sp = 6`, `cupil 3 chams = 5`.
- **Tables:** weapons, armor, accessories, items, spells, S-moves, shops, chests, the SP curve, Cupil (`0x802C9628`), titles (`0x802C8E54`), crew (`0x802D8E64`) and ship tables.
- **Layouts are re-derived from the DOL (rule 8).**
- Mods stack when they touch different cells; the same cell in two mods is a reported conflict.
- **Refuses what would read past a table or be silently truncated** (layouts from `fn_801F28CC` and `fn_801EF300`):
  - a Cupil next-form cell other than −1 (none) or 0–15. It is stored as form − 32, and a form outside 32–47 reads past the 16-row, 64-byte table at `0x802C9628`; a new form needs a native `fn_801F28CC` (90 instructions);
  - a Cupil Chams-needed value over 127, because the byte is compared signed against `0x8030BB24`;
  - a title threshold over 255, because only the low byte at row +25 is read; and any row past the 24th, because the loop count of 24 is hard-coded at `0x801EF338`.
- **Code, not cells:** the Final Cupil rule (`0x8030BB23` ≥ 3 and `0x8030BB24` ≥ 30 gives form 47, at `0x801F28FC`–`0x801F2918`) and the special titles' indices.

*Done:*
- A patched spell cost reads back by peek, and the magic menu offers the spell at that cost (frame opened).
- A conflict is refused.
- Each refusal above fires on a synthetic table: a next form of 16, 128 Chams, a threshold of 256 and a 25th title row.
- Round trips are covered by tests on synthetic tables.

**T4. A script assembler** — *week-plus.*
- A text form, with operand layouts re-derived from the DOL's handler table and SALSA as a cross-check (they agree on 265 of 266), so ops 24, 25, 144 and 155 decode.
- An assembler back to `.sct`.
- Mods keep only their edited and new entries (rule 3).

*Done:*
- All 258 scripts decode with no unknown opcode and no raw-byte fallback, and round-trip byte for byte.
- **The decode agrees with the file's own structure:**
  - every index entry decodes to exactly the next entry's offset, and no instruction crosses a boundary;
  - every GOTO, CALL, IF and SWITCH target lands on a decoded instruction;
  - every op-144 and op-155 offset lands on a LABEL (op 9) that starts a message entry, which both handlers require (`fn_8020A734`; `fn_8020A338` at `8020A3F0`–`8020A404`);
  - every op-24 and op-25 offset lands inside the file on a NUL-terminated string.
- Widening or narrowing one op's operands in the layout table (op 25 by 4 bytes, SALSA's error) makes that check fail. Editing an operand in the text is not the mutation: it changes the output whatever the layouts are.
- An edited message shows in a run.

**T5. Enemy records as text** — *days.*
- Read and write the live containers: each map's `.enp` (directory, records of 524 or 620 bytes, formations) and `epevent.evp` (200 directory slots, 256 event records).
- Records become TSV rows, with AI steps as readable lines.
- **The writer refuses:**
  - an `.enp` over 8,192 bytes decompressed;
  - an id missing from its own file's directory (setup would build from a wrong base);
  - more than 84 directory pairs;
  - more than 4 distinct ids in a formation (until X4);
  - more than 7 enemies in an event, because an eighth overlaps the rules;
  - a summoned id from another file;
  - a drop chance of 105 or more;
  - an AI path that can end without an action;
  - a special move the model's `.STD` lacks;
  - `.ect` weights that do not sum to 100.
- It **warns** on event ids ≥ 248, which use the default voice bank.

*Done:*
- every `.enp` and the `.evp` round-trip; each refusal has a mutation test; a changed max HP shows at actor +24 by peek;
- `tools/guard.py` refuses a full-column enemy table in a mod folder, judged by this schema's columns (moved from T0), and a mutation test proves the check fails on one.

**T6. Content checks** — *days.*
- `tools/contentcheck.py`, which is `soak.py`'s runner with a script:
  1. warp to the mod's map;
  2. walk a path;
  3. talk and confirm the entry fired;
  4. force the mod's battle;
  5. save, reload, and assert the map and flags.

*Done:* it passes on vanilla `a101b`, and a broken script (mutation) fails.

**T6b. An interaction crawler** — *several days, after T6, M4 and M7b.*
- On one map, walk to every NPC and trigger and record the outcome: no entry, gated off, ran and returned, stuck, left the map, or fault.
- **Always call the condition check first.** `fn_80210550` sets the lock `0x8030E714` before it looks the entry up, so starting a missing entry leaves the lock stuck.
- Each id costs a Continue from a card copy (about 27 s), so aim it at mod maps plus a sample of vanilla maps. Derive the vanilla "who says what" table statically.

*Done:*
- An entry with its RET removed reports "stuck".
- Each crawl is checked within its own run against the "who says what" table derived statically from the same map's scripts (the mod's scripts, for a mod map): an id the table gives no entry reports "no entry", an id it gives an entry never reports "no entry", and every "stuck" or "fault" has its frames opened. The static table is the baseline; a crawl is never compared with a pinned earlier crawl (rule 7). The first static vanilla table is a first bless: before trusting it, open the first vanilla crawl's frames for a sample of its entries and confirm the speaker and message match.

**T7. Play existing ISO mods** — *several days.*
- Diff a patched ISO the player owns against their own clean dump:
  - changed files become T1 overrides;
  - changed executable data becomes T3/M1 patches;
  - changed executable code is refused with a reason.
- **Before promising Encore** (Q11), diff its `.text` separately from its data (an hour).
- Output is local-only.

*Done:* synthetic fixtures pass; **Owner:** a Maeson ISO imports and boots, and a changed stat shows in battle.

**T8. The model and collision writer** — *week-plus to months; the gate for new art.*
- SPICE already exports MLD models to Blender; T8 is the writer:
  - NJCM models (start from the Sonic Adventure Blender add-on's chunk-model export);
  - NJTL/GVR textures;
  - GRND/GOBJ collision (nobody writes these yet);
  - POF0 tables and index entries.

*Done:* an existing map's MLD round-trips semantically, then a room with one wall moved draws and collides.

**T9. Named game addresses and a generated header** — *several days, before T3 and R0.*
- Name the data the research found, extending `config/names.txt` and `tools/inventory.py` to data symbols (`symbols.txt` already lists them with sizes), plus one file of struct offsets shared with T3 and T5.
- Generate a C header beside `runtime/soa_mod.h` whose accessors call `SoaModApi`'s big-endian reads and writes, never host structs, plus a Python module.
- `patches.txt` and T3 accept names.
  - Until M6 lands, `patches.txt` names only absolute, word-aligned words, because M1 writes one aligned 32-bit word (`mod.c:290`).
  - A name for a field behind a pointer (the battle context `*0x80347390`, actors) or one narrower than a word needs M6's pointer-relative and width syntax.
  - The C header and the Python module do not need M6: their accessors follow the pointer themselves.

*Done:* a test re-finds each confirmed address from a code reference, and fails when one address is changed.

**T10. A mod kit and `docs/MODDING.md`** — *several days, after M4 (done) and M5.*
- **`tools/mod.py`:**
  - `new` scaffolds a mod;
  - `build` makes an x64 DLL without a developer prompt, and refuses 32-bit, which fails today with a bare "error 193";
  - `check` tests a mod against your DOL without launching the game;
  - `test` runs it on the fake-guest driver `test_mods.py` already has, moved into `tools/` with `test_mods.py` importing it from there so the two cannot drift; community CI needs no disc.
- **What `test` can and cannot check.** The driver's guest is a stand-in: a fake DOL, and one function at `0x80003100` that is the only address its `call_guest` accepts (`test_mods.py:61-73`).
  - So `test` must accept the mod's real `dol_sha1` in place of the fake DOL's, or `mod.c:824` refuses every real mod.
  - It checks that a mod loads, its patch grammar, its callbacks and the API's refusals, not what the mod does in the game. It has no real game functions for `call_guest`, and no M13 sites or R1 events yet.
  - MODDING.md says so, and the driver grows with each API version.
- **The guide:** a first mod in 15 minutes, finding an address, `patches.txt`, and the API rules the plans promise but never place. Examples: "`on_frame_end` may only write memory", and "keep `hooks.txt` away from interrupt waits".
- **The API reference** is generated from `soa_mod.h`, with a test.

*Done:*
- `check` fails a wrong `dol_sha1` and a misspelled address.
- **Owner:** builds a small mod from the guide alone.

**T11. The quest author's workbench** — *several days each, `--link` through X1 thunks; milestone 5, after X1 and T4's operand table; the placement mode after M8 and T3; before N3.*
- **A script tracer** (`SOA_SCRIPT_TRACE=me101b`): frame, script, entry, opcode and operands, flag writes, and a stop when a named flag changes.
  - There are two dispatch sites: `fn_80211298` runs an op the first time (r3=1), and `fn_80212130` re-calls waiting ops every frame (r3=2). Fold the second into "waiting on op N for k frames".
  - **Both call through one opcode table [V]:** `0x802F7940` (`.data`, 266 twelve-byte entries, handler at +8), with `bctrl` at `0x80211378` and `0x802123E0`. X1 log-and-forward thunks on the table's entries see every op, split by r3, with no retranslation. Flag writes are found by comparing the flags before and after the forwarded call.
  - Both dispatchers are reached only by direct calls, so wrapping them instead would cost a retranslation (an `hle.txt` or `hooks.txt` entry), and neither retranslation batch holds either site.
- **An enemy-AI path tracer:** condition id, branch, step, through X1 log-and-forward thunks on `0x802DFB10`/`0x802DFC28`. X1 must be able to call the handler it replaced.
- **A placement mode:** nudge an object live through M8's queue, and export the result as text: a T3 load-time patch or a T1 override of the map file. Rotation is in units of ×182.0444.

*Done:* a traced conversation shows each op once, with its waits folded; the AI tracer shows the branch a poked HP forces.

**T12. Pad scripts that wait, and one state snapshot** — *(a) and (b) hours to a day each; (c) several days, after the event track.*
- **(a) A `wait ADDR==V` item** in the pad grammar, in both `si.c` and `scenario.py`. The run logs the frame at which the condition held, so recordings still replay.
- **(b) One state snapshot** published at the safe point: scene, map, party HP/SP, battle actors, turn order and changed flags. R0 logs the same fields itself; P7 and R5 can read the snapshot once it exists.
- **(c) Optionally, a loopback control channel** in an example mod: off by default, with an Origin check and a token, and each command stamped into the event track. Q10 decides whether it is built.

*Done:* a wait on a condition the run reaches (for example `0x8034733C == 1` in `battle.scn`) holds and the run logs its frame; the same item with a mutated address reports an unmet wait; the snapshot matches peeks on the same frame.

**T13. Mod packages that never carry the game's bytes** — *several days, after T10 and T1's delta decision.*
- `tools/mod.py pack` zips a mod folder with a hash manifest. It refuses the guard's suffixes and any file matching the player's `extracted/` files, compared **after decompressing**, since most disc files are AKLZ.
- Native mods ship source, built on the player's machine with `/Brepro`.
- Share on GameBanana's existing Skies of Arcadia Legends hub (games/18776).

*Done:* a pack containing a recompressed copy of a disc file is refused.

### Track R — Combat

**Goal.** Combat mods through one event surface, tested by a battle harness.

**R0. The battle harness** — *several days, after P6 and T9.*
- From a card save:
  1. force a chosen formation or event battle (`0x803473D4`);
  2. write commands when phase 1 begins;
  3. log `(original, returned)` for every call through `fn_800108EC`, plus actor HP, SP and the turn order each frame.
- It starts once P6 and T9 have landed, and it cannot reach its Done before R1.

*Done:*
- A doubling mod gives `returned == min(2·original, 9999)` on every logged call, with at least 10 nonzero hits, so it cannot pass on a battle with no hits.
- The first hit falls in the formula's range [V]:
  - the base is `2·ATK − DEF` (`fn_80010A40`), with DEF counted as 0 on a critical;
  - when Vyse attacks, ATK also gets his title's bonus: the s16 at `0x802C8E54 + 34·title`, +26 for an attack (`fn_80010A40`) and +28 for an S-move (`fn_8006AFD0`), with the title that `fn_801EF300` returns. It runs from −2 to +4 across the titles, so `2·ATK` moves by −4 to +8; it is not a constant 26;
  - then ±2.5%, +1 one time in eight, element and Guard;
  - a critical that comes back 0 from `fn_800108EC` is raised to 1 by `fn_80010A40`.

**R1. Battle events** — *several days plus one retranslation* (batch A, with X2).
- Native wrappers through `hle.txt`, each calling the original (`recomp_fn_X`). Use M13 if it has landed; no migration is planned.
- **Each event fires once per occurrence:**

| Event | Site | Fires when | Payload |
|---|---|---|---|
| `on_damage` | `fn_800108EC` return | every call | attacker, target, `int* value` (re-capped at 9,999) |
| `on_heal` | `fn_8006AE20` | every Recover-HP value: calculator 31, and Blue Rogues on a party member | target, `int* value` (work+60) |
| `on_enemy_spawn` | `fn_800770B8` post | every spawn | actor (scale the actor, **never the shared record**) |
| `on_enemy_action` | `fn_8008A424` | every AI decision | slot, `cmd*` |
| `on_turn_order` | phase 2 → 3 | the phase leaves 2 | order[12] |
| `on_spirit_gain` | `fn_8006EF48` | once a round | `int* amount` |
| `on_escape` | `fn_80010340` return | every call: party Run (`fn_800858B8`, slots 0–3) and enemy Run (`fn_80088B14`, slots 4+) | slot, `bool* success` |
| `on_rewards` | `fn_8006F4B0` | **once**, when `0x80347338 == 2`, before the original | `int* exp`, `int* gold`, `s8* magic_exp` (clamped to 127) |
| `on_effect` | `fn_8002BD88` entry | every effect | target, `s16* effect` (msg+6), `int* value` (msg+8), and a cancel flag |
| `on_round_end` | after `fn_8006FD6C` | the sub-state goes 0 → nonzero | — |
| `on_ship_damage` | `fn_80146BF4` return | every call | `int* value` |

- Handlers run in registration order. An AI replacement for a slot is exclusive, and two are refused.
- A handler that faults stops the run and names its mod (M3d), never continues half-done.
- **`on_heal` does not see every heal [V].** `fn_8006AE20` computes only calculator 31 (spells 6–8, and enemy magic and items with effect 31) and Blue Rogues' heal branch (`fn_800695A0`, `0x800695EC`). It misses:
  - **full heals:** effect 32, `fn_8006ADAC`, value = max HP − HP (spell 9);
  - **drain:** effect 44 sends the attacker a second effect-31 message at `0x8002DEEC`, and no calculator runs;
  - **per-round heals:** regen actor+0 (under `+28 & 0x40000`) and actor+266, which `fn_8006FD6C` adds straight to HP at `0x8006FE60`–`0x8006FEA4`, with no message.
  - `on_effect` on effects 31 and 32 sees every heal but the per-round ones. No event sees those, because `on_round_end` fires after they are applied; a mod that changes them edits actor+0 and actor+266 before phase 6.
- The `on_enemy_spawn` wrapper also carries X4's kinds fix, a `--link` once batch A has landed.

*Done:*
- The run report counts calls for each changed function; zero calls means "did not test what it says".
- **Mods off, inside one run of the retranslated build** (rule 7: none of these compares two live runs):
  - Every new hook site's call count is nonzero, and its count of substituted values or bytes written stays 0. A test handler that adds 1 makes that count nonzero.
  - **X2's save**, from a new save-then-Continue scenario on a card copy (`cardwrite.scn` only formats a blank card):
    - the 12,800-byte block `fn_801A41EC` finishes equals the file's bytes at +5184 on the card copy;
    - the game's own XOR check (`fn_801A4684`) accepts it on Continue;
    - when `fn_801A4354` returns, memory equals the block's fields: party `0x8030B7F4` ×5,792; map word and letter `0x80311AC4`/`0x80311AC8`; position `0x8030A7CC..A7FC`; flags `0x80310B3C` ×3,416 and `0x80310A1C` ×288; play time `0x803474A0`, from +12780;
    - mutations: a flag byte poked after the save is overwritten by the Continue, and one byte flipped in the card copy's block makes the XOR check refuse it.
  - The new build's save loads in the build from before the retranslation: the XOR check passes, and Continue lands on the saved map.
  - Saves are never compared across builds: the time stamp (+12786..+12795), the play time (+12780, a once-a-second alarm) and the XOR (+12796) follow the wall clock.
  - Comparing R0's log with the old build's is not a batch check; it waits on K6 (rule 7).
- A mutation per event, including the four nothing later tests: `on_turn_order`, `on_spirit_gain`, `on_heal` and `on_enemy_action`.
- `on_rewards` fires exactly once per victory.
- A test handler that faults in `on_damage` stops the run, and the report names its mod.
- **Budget (rule 7):** handler time per event and per mod (total, p99, max) from one live battle run, in the run report, against a limit fixed before the run.

**R2. Status and AI extensions by thunk** — *several days, `--link`, after X1 and K12.*
- The pointer tables `0x802DBB10`, `0x802DF570`, `0x802DFB10` and `0x802DFC28` are `.data`. X1's thunks let a mod point an entry at native code: a new status effect, a new AI condition, or a new targeting rule.
- Free status bits come from K12.

*Done:*
- A native "Burn" status ticks **exactly once a round** in R0's log.
- An enemy whose AI uses a native condition takes the branch, and a mutated condition id changes it.

**R3. Difficulty presets** — *days, after R1 and M16.* **Owner.**
- **Easy**, **Hard** and **Nightmare**, applied in `on_enemy_spawn`: HP, attack, defense, magic defense and speed multipliers, and optionally level scaling from the party's level (AI conditions 44/45 read the gap).
- Rewards scale in `on_rewards`.

*Done:*
- R0 shows the actor scaled and the shared record untouched (peek the record after two battles).
- **Owner:** Hard through one dungeon.

**R4. Boosts and assists** — *hours each, after R1 and M16.*
- EXP, gold and magic EXP ×0–×4 (`on_rewards`); full Spirit at the start.
- **Always escape, for the party only.** `fn_80010340` also rolls enemy runs, so the mod acts on `on_escape` for slots 0–3 only, or sets ctx+2 = 100, which the enemy branch never reads. A fleeing enemy keeps its own roll; otherwise every enemy that runs gets away, taking its EXP and drops with it.
- **No knock-outs:**
  - the damage clamp in `on_damage` for party targets;
  - **poison:** when the sub-state becomes 10, clear the party's bits of `0x80346BE8` and set those members' HP to 1;
  - **instant-KO effects [V]:** 5 (`fn_8002DA88`), 6 (`fn_8002DA24`) and 68 (`fn_8002C4A0`) write HP = 0 and call `fn_8002BC4C` inside the applier, where `on_damage`'s clamp cannot reach them.
    - Their sources are enemy magic 17–19 (Eterni, Eternes, Eternum) and enemy S-moves 12, 32, 33 and 297 (Death Strike, Crypt Laser, Death Laser, Moonstone Blast).
    - The clamp makes 68 worse: its calculator `fn_80068D7C` drops the death status only when the damage kills (`0x80068DEC`).
    - For a party target, `on_effect` cancels effect 5, and rewrites effects 6 and 68 to effect 0 with the value clamped to HP − 1. The rewrite to 0 is what `fn_8002BD88` itself does for status 0x40 (`0x8002BE6C`, `0x8002BEBC`); cancelling 68 instead would drop its damage.

*Done:*
- R0 logs each `on_rewards` call's `exp`, `gold` and `magic_exp` before and after the handlers, in the same call.
- At ×2, the returned EXP and gold (ctx+48/+52) are exactly twice the originals in that log. Each member's share is `(2·exp + alive − 1)/alive`, so it is not exactly 2×.
- At ×1, each pair is equal, and a mutation that adds 1 at ×1 is caught (a before/after in one log, rule 7).
- A forced lethal poison tick, and an applied effect 5, 6 and 68 each on a party member, leave everyone standing. The mod logs each override in R0's log: at sub-state 10, the party bits of `0x80346BE8`, the HP it found and the HP it wrote; for effects 5, 6 and 68, the target and what `on_effect` did.
- With always-escape on, in one harness run:
  - (a) R0 sets the party's escape override `0x8030B7AB` (copied to ctx+2) to 0 before a battle whose initiative `0x80347344` is not 2 (at 2, `fn_80010340` lets the party escape without rolling), so the party's own roll fails 100 times in 101. The first party Run's `on_escape` call (slots 0–3) returns true in R0's log, and the battle reaches phase 9. A mod that acts on no slot (the mutation) fails this, whichever route it takes.
  - (b) R0 pokes ctx+3 = 0 after setup, so every enemy roll is handed false. Every enemy `on_escape` call (slots 4+) returns the `success` it was handed, and at least one enemy Run is logged before the party escapes. A mutation that forces any enemy slot's `success` to true is caught.
- Whether every other logged number matches an off run of the same battle compares two runs, so it waits on K6/D4 (rule 7).

**R5. Battle information** — *days, after M8.*
- Enemy HP bars; the turn order from phase 3 (estimated from Quick in phase 1); a battle log from `on_effect`.
- Enemy names come from a name table by id, shipped as text (Q5 asks whether that counts as game data).

*Done:* the overlay's numbers match R0's log, **paired with an opened frame**, since both read actor+20.

**R6. Rebalance mods** — *several days, after T3 and T5.*
- A Maeson-style rebalance as text edits.

*Done:*
- The example mod in `mods/` (edits only) changes every cell it names, in executable tables and `.enp` records. A peek of each reads the mod's value (DOL tables after boot, an enemy record once its map has loaded), and R0's log shows the edited numbers in a battle in the same run.
- A mutated value in the mod's text fails its peek.
- The mod never reaches the disc: the DOL and every `extracted/` file it edits hash the same after the run as before it, and a mutation that writes one edit back is caught.
- With the mod off, the loader reports zero writes, the same peeks read the disc's own bytes, and the contract's checks pass (section A). This is an invariant against the disc, not a comparison with another run (rule 7).

**R7. A new command** — *week-plus, plus one retranslation or a place in batch B, after R1.*
- The wheel and handler dispatch are switches baked at translation, so this needs:
  - a pre-hook on `fn_8007C600` that overloads a slot (for example "hold L on Item = Steal");
  - a handler for command type 7, 9, 10, or 13 and up [V]. 11 and 12 are taken:
    - phase 3 skips any actor whose command is 11 (`0x800709A4`);
    - 12 is the enemy S-move. It has its own case in six 13-way switches on the type (`0x802DF720`, `0x802DF7E0`, `0x802DF914`, `0x802DF964`, `0x802DF9F4`, `0x802DFA28`, where 7, 9, 10 and 11 fall to the default) and in `fn_8002BD88`'s Block-Magic test (`0x8002BF34`);
  - the new type's handler hook, on `fn_80086C68` or at `0x80086E5C`, where a type above 8 falls to the default [V].
- **Rebuild:** both hooks are `hle.txt`/`hooks.txt` sites. They join batch B if R7 is picked up before milestone 6; otherwise they are one retranslation of their own, with the same checks.

*Done:* in one harness battle, driven through the wheel by pad input (R0's command writes bypass `fn_8007C600`, so the hook would never run):
- with L held on Item, the stolen item enters the battle's inventory copy in that round, before phase 7;
- with L not held, each available slot is chosen once, and the type `fn_8007C600` stores at `0x8007C7E0` (`0x80309174 + 32·actor`, +0) equals the slot chosen, with the call count above zero;
- a mutation that overloads Item without L fails the check.

**R8. Auto-battle and repeat-last-turn** — *days, safe point only.*
- In phase 1, write commands from the "last" fields and reserve SP, MP and items exactly as the menus do (battle-system.md §8), then close the menus and set phase 2.

*Done:* in one harness battle, alternate pad-entered rounds with repeat rounds. Snapshot at the first safe point of phase 1, and at the first safe point where `0x8034733C` reads 2, before phase 2 hands MP and items back (battle-system.md §2.2 step 8).
- For every repeat round, each member's `cmd+0/+4/+6/+13` and the amounts reserved during phase 1 equal those of the pad round it repeats: the drop in ctx+10, each member's MP drop at +254, and each count's drop in ctx+56.
- Compare the drops, not the absolute values: each round starts from what the previous one spent.
- A mutation that skips the MP reservation fails.

**R9. Ship battles** — *several days, plus one retranslation or a place in batch B, after R1 and K5.*
- `on_ship_damage` (already in batch A) and native ship AI (bind `fn_80145844`). The ship-battle tick unlock (scene 6, map ≥ 500) is section F's M11, not part of R9.
- **Rebuild:** the `fn_80145844` binding is an `hle.txt` line. It joins batch B if R9 is picked up before milestone 6; otherwise it is one retranslation of its own, with the same checks.

*Done:* start from the part-L save, where the party has the Delphinus; a part-A save's empty ship reads Hp 0 and stalls on round 2 (FINDINGS.md:1426-1440). Enter a ship battle the way opcode 210 does (`fn_80147E2C`): the stage name (e.g. `ME550A.SCT`) at `0x80305CF0`, the return name at `0x802E5E68`, and `0x803472E4 = 1`. Do not use R0's `0x803473D4`, which starts a scene-7 battle, and do not poke the map words (FINDINGS.md:1183-1191). The run then:
- logs `(original, returned)` for every `fn_80146BF4` call, with at least 10 nonzero hits and `returned == 2·original` on each, so it cannot pass on a battle with no hits;
- binds a native `fn_80145844` that returns an action the stage's `.tec` would not choose on turn 1, and the log shows the enemy ship taking that action first.

**R10. An autopilot and a balance lab** — *week-plus, after R0, R8, K6, T5, S6 and S9.*
- A policy table fills in commands ("heal below 40%", "attack the weakest").
- A headless sweep fights each formation and writes one row per formation and seed: won, rounds, damage taken, SP spent.
- Party states come from real story-point saves (S7a's part cards).
- Budget honestly: one battle is about 1,800 frames, so start with one dungeon and chain battles inside one process, as an S6 job.
- A heuristic's win rate measures the heuristic; the value is the before/after comparison.

*Done:*
- **If K6 found battles repeatable:** a rerun gives an identical table, and doubling enemy HP, in the same process, raises the table's total rounds and total damage taken and turns no loss into a win. A mutation that skips the doubling leaves both totals equal to the first table's, so it must fail. Per-row rounds and damage are not required to rise: AI conditions such as "HP < 50%" and the percent rolls fire at different times once HP is doubled.
- **If not:** rows are per formation, as distributions over N seeds. Doubling enemy HP, in the same process, lets no formation's median rounds or median damage taken fall by more than that formation's spread between two halves of the same run, and raises the sum over formations of median rounds by more than the sum of those spreads. A mutation that skips the doubling leaves that sum unchanged, so it must fail. The identical-rerun check waits on D4.

### Track N — New content

**Goal.** New things to do, from the game's own pieces first. Every slice ships as text edits plus a T6 check. N10 and N11 land before T6 (milestone 4 against 5): their checks run on R0 and one-run logs, and they gain T6's walk when it lands.

**N1. New gear in the placeholder slots** — *hours, after T3.*
- 82 placeholders: weapons 74–79, armor 139–159, accessories 223–239, items 302–304, key items 365–399.
- Descriptions and new strings live in X3's mod window.
- In a vanilla load the gear shows as ダミー ("dummy"): see the contract and Q2.

*Done:* a new weapon bought from a patched shop equips and shows its attack in R0.

**N2. A new enemy from an existing model** — *days, after T1 and T5.*
- **The id decides the model and the name picture.** Choose one of:
  - **reuse the model's own id** with a new record in that map's `.enp` or the `.evp` (it keeps the original's name, and the two cannot share a battle);
  - **a spare boss id** that already maps to a model: 247, 249 or 253; or 203–207 and 135, which have no name picture;
  - **a free id** (5, 6, 122–127) with copied model files (T1 aliases) and a repainted name (K3, P8).
- **Random battles:** the `.enp` directory, formations and `.ect`.
- **Scripted fights:** one of the `.evp`'s 54 free slots, event records 250–255, op 112.

*Done:*
- The enemy fights with its new HP and first AI action.
- **Its drops roll from its own table.** The test record's drop slot 1 holds an item the donor never drops, at chance 100 (`rand()%100 < 100`, always). After each of 20 harness wins that item is in the results buffer `0x803082F8`, peeked at the results screen (`fn_8006F4B0`), because R0's log does not record drops.
- Slot 1 at chance 104 (never) removes it, so the check can fail.

**N3. The new bounty** — *week-plus, after N1, N2, T4, T6, T11 and X2.* **Owner.** The first vertical slice.
- A **script-only** Wanted target that leaves B[100..108] alone. Extending the Wanted List itself is later work, listed in B4 (Q7 asks whether to build it):
  - it needs native `fn_801B737C`, `fn_801B6E5C` and `fn_801B7274`/`fn_801B71E8`, plus T4 edits to the four Guild scripts whose literals set the gold paid;
  - a ninth claim would break the title routine's B[108] == 8 test.
- **The quest:** an NPC's new branch, flags claimed by name, an event battle against N2's enemy, the return through `sys[15] = 10000` with the script's own fade-in, and N1's reward.

*Done:* T6 walks offer, accept, fight, reward, save, reload, reward kept. **Owner:** plays it.

**N4. New ship battles** — *several days, after T1 and T4.*
- A stage in 584–599: a script modelled on `me500a`, an `rNNNx.tec` AI table, and an existing enemy ship.

*Done:* entered through op 210 from the world map, fought, won, returned (T6).

**N5. A remixed dungeon** — *week-plus, after T1, T4 and N2.*
- A new map number aliased onto existing geometry, with its own script, warps, encounters and chests. Donor chests are left out, because they share the donor's chest flags.

*Done:*
- T6 walks entrance to boss and back.
- **The save matrix, if Q2 chooses X2's fallback:** save in the modded game, load in vanilla or Dolphin, save there, and load back in the modded game. If Q2 keeps section A's honest wording, the Done instead checks that the port says which mod the save needs when it is loaded without it.

**N6. The endless dungeon** — *week-plus, after N5 and X1.* **Owner.**
- A native "Sky Rift" mode: floors chained from existing rooms by per-floor aliases, encounters and levels scaled by floor, a seeded reward table, and rules in a thunk opcode.

*Done:* 10 floors descend headless with a fixed seed. **Owner:** it is fun.

**N7. A new room from new geometry** — *after T8.*

*Done:* it draws, collides and is walkable from a door (T6).

**N8. A new island** — *week-plus, after N7 and K4.*
- A `fldIsland` entry in a world tile or a shared sub-model, plus a `fldName` landing answered by `M04xxx` in all 16 `me099a`–`q` scripts.

*Done:* sailing to it and pressing A lands on N7's room.

**N9. Randomizer** — *XL.*
- Chests, shop stock, formations, Moon Stone spells and crew posts (K8), with story-gate logic, permalinks, a spoiler log, and P7 as the tracker.

*Done:*
- 100 seeds generate.
- **An independent reachability checker** agrees each is beatable, and a mutation that removes a key item is reported unbeatable.
- A seed's run reaches part B (T6).

**N10. Arena, Boss Rush and Time Attack** — *week-plus to several weeks, after milestone 3, M8 and T4's decoder; its ship battles after P9.* **Owner.**
- **The fight list.** Pick any of the game's boss and event battles from a menu, alone or in a chain.
  - The list comes from scanning the scripts' op-112 calls with T4's decoder: each fight's event id, stage and chapter.
  - `tools/sct.py` cannot build it: its linear pass loses sync on ops 24, 25, 144 and 155, and left 453 BATTLE opcodes unparsed (enemy-data.md:430).
  - About 112 are distinct.
- **Scores** are rounds, damage taken and game frames at `0x803475C0`, counted from the first phase 1 to the victory phase (`0x8034733C == 7`).
  - **Game frames do not depend only on the fight.** The counter ticks once per dispatcher pass (`801DC390`), including while the player chooses a command in phase 1. It also ticks through the disc loads inside a fight: the effect packages a fight loads, and `PCWIN.MLK` at the win (FINDINGS.md:1451).
  - Loads run on the wall clock (rule 7). With M11's tick unlock, each wall second of them counts about 60 frames instead of 30 (PLAN-60FPS-MODS.md:607); a host drawing below 30 fps counts fewer, and heavy drawn scenes still do today (PLAN-60FPS-MODS.md, H15c). How much a score moves is not measured [I].
  - So a scored fight runs with the tick locked (turbo off), the run records the setting (rule 6), and a frame score is compared only with scores made at the same setting.
- **What it must handle:**
  - 29 records are "must not lose": force "may lose", or catch the game-over;
  - restore party, items and gold after each fight, or zero the rewards through `on_rewards`, or it becomes a farm;
  - "return to where you stood" is allowed only where the random-encounter gates pass; elsewhere use an arena map or the fade fix (`0x80347518 = 0`).
- **Ship battles** wrap P9's `398A` select once P9 has landed. They are not in the Done below.
- **The first step:** force one event id and watch it run. Only kind 0, a map formation, has ever run this way (FINDINGS.md:1324).

*Done:*
- A chain of three bosses runs headless and restores the party exactly: R0's log and peeks of the party block before and after, in the same run.
- **Owner:** a three-boss chain played in a window.
- A must-not-lose fight lost in the arena returns to the menu.
- **In one run,** the same fight is fought at 1× and then with the tick unlock: the first is scored, the second is refused a score, and the frame difference between them goes into FINDINGS.

**N11. New Game+ and challenge rules** — *several days, after milestone 3.*
- **New Game+** keeps levels, magic, gear, gold and Cupil, with R3's presets to make enemies harder.
  - **The obvious hook is wrong.** X2's `on_new_game` fires before `fn_801F01E4` (`0x80228BF4`) resets all six characters from their templates.
  - **Carry-over instead, at two sites:**
    - **Levels and spells:** a pre-hook on `fn_801F3024` rebuilds them through the game's own formula. `fn_801EF9A8` calls it once per character (index in r3) at `0x801EFB54`, after copying that character's template.
    - **Items, gold, Cupil and the rating** cannot be written from that pre-hook: `fn_801F0020(0x8030BB1C)` at `0x801F0250`, still inside `fn_801F01E4` and after all six calls, resets all four (items to −1 from `0x8030BB48`, Cupil `0x8030BB22`–`24`, the rating `0x8030BB3C` to 100, gold `0x8030BB40` to 0).
    - They are written by a `hooks.txt` entry at `0x80228BF8`, the instruction after `fn_801F01E4` returns. Nothing later in `fn_80228BE4` touches that block (`fn_801E0FD4` zeroes `0x8030A794`–`0x8030B454`), and the function has no loop, so the entry strips no `irq_poll` (rule 5).
    - These are X2's fifth and sixth sites, both in batch A.
  - **Both are gated on "NG+ pending",** which is also what keeps a normal New Game untouched. The pre-hook needs the gate for more than that:
    - `fn_801F01E4` also runs at every boot and soft reset (scene 0: `fn_801DBE88` → `0x801DBF68` → `fn_80230F48` → `0x80230F54`), so the pre-hook sees six calls there too;
    - the stage picker's debug half calls `fn_801F3024` at `0x800FFD80`.
    - The gate is armed only by choosing NG+ at the title, never by a persistent setting, and it is cleared at `0x80228BF8` once the carry-over is written, not inside the pre-hook.
  - Leave the ship out: `0x8030CD5C` is unconfirmed.
- **Challenges** are text files, each bundling a seed and a preset: no items, no magic, no running, fallen stay fallen, solo, no shops, low level.
  - Command availability is written at `*0x80346C14` in **every** phase 1, not once.
- The game never saves after the credits, so either offer NG+ from any save or keep a "cleared" record outside the save (Q9).

*Done:*
- **With the mod off, or NG+ not pending, a New Game passes through untouched** (a one-run invariant, not a comparison with a vanilla run: rule 7). In `newgame.scn`, which exists today:
  - the run report (R1) counts the pre-hook's calls (six at boot, six more at New Game) and the `0x80228BF8` entry's one, and neither dispatches;
  - a `SOA_PEEK` after New Game shows each character's EXP (`0x8030B7F4 + 92·ch` +36) and six magic-EXP words (+68..+88) equal to the DOL template's (`0x802C4860 + 152·ch` +40 and +128..+148). Level is not a template field: `fn_801F3024` derives it from EXP.
  - A mutation that arms the gate with a carried EXP fails both: the sites dispatch, and the EXP differs from the template.
  - T6's walk is added when T6 lands in milestone 5.
- An NG+ start shows the carried levels in the status screen (frame opened), and a peek shows the carried gold at `0x8030BB40`.
- A "no items" run cannot select Item in a harness battle.

### Track X — Beyond the GameCube

**Goal.** Mods hold more than the disc, the RAM and the save allow. Everything is off by default.

**X1. Native thunks** — *a day, `--link`, milestone 5, before T11, R2 and N6.*
- A registry of reserved addresses consulted by `guest_trap` before it traps.
- A mod plants a thunk address in any guest function pointer: a script-opcode table entry (one of the 9 free stubs, or a used op's entry for tracing), a status or AI table entry, an object type, a middleware callback.
- **The thunk:**
  - must preserve r1, r2, r13 and the non-volatile registers;
  - may call the handler it replaced (log-and-forward). T11's tracers are its first user;
  - on a fault, stops and names the mod, never continues half-done.

*Done:*
- A self-test case calls a thunk through `dispatch` and checks the registers.
- A native opcode sets a flag.
- A log-and-forward thunk on a used op's entry logs each call, and the op still takes effect in the same run (its write is peeked). A thunk that skips the forward (the mutation) leaves the write undone.
- An unregistered address still traps.

**X2. The save extension** — *several days plus one retranslation* (batch A).
- **Hook sites:**
  - the snapshot at `0x801A4670`;
  - the image build at `0x801A4334`;
  - the load at `fn_801A4354`;
  - new game and boot at `fn_801CAF30`;
  - NG+'s pre-hook on `fn_801F3024` and its `hooks.txt` entry at `0x80228BF8` (N11).
- **An in-file container:** `SOAX`, a GUID, a CRC32 and chunks per mod, in the 3,156-byte gap (inside the game's checksum) and the 6,592-byte tail. Overflow goes to immutable host blobs by GUID.
- **Pass unloaded mods' chunks through unchanged.** This is first, hours of work: today turning a mod off and saving would lose its state.
- **Which hook writes what [V]:**
  - the gap chunks, and the fallback below, go in at the snapshot hook `0x801A4670`, before the XOR;
  - the image build `0x801A4334` writes **only** the tail (image +17,984..+24,575, with the image at `*(r31+0)`): the save's fresh GUID and the overflow chunks. By then the XOR is stored (`0x801A42EC`) and the block copied into image +5,184..+17,983 (`0x801A4330`), so any write to that copy fails vanilla's checksum;
  - **never** use `hooks.txt` in the card writer `fn_801A3B30`.
- **The vanilla fallback.** At the snapshot hook, edit the snapshot block, never live state. M7a's save-now needs the location half whatever Q2 decides (section F's M7a amendment). Mod maps and placeholder gear need their halves only if Q2 chooses the fallback:
  - **location:** write a vanilla location into the map word, letter and position (+5808/+5812, +5864..+5916). On a mod map, write the mod's declared one. For a save-now on a map whose script has no op 138, write the last op-138 map the party was on;
  - **placeholder gear:** swap each placeholder id the mod fills (N1) for its declared vanilla substitute, in the equipped slots (character +16/+18/+20, at block +16 + 92·ch) and in the inventory lists copied from `0x8030BB48..0x8030C340`;
  - keep the real location and ids, with their positions, in the chunk, and restore both at `fn_801A4354`'s entry. Restore only where the block still holds the fallback or the substitute, and report the rest: pass-through can carry a chunk across saves made without its mod.
  - If Q2 keeps section A's wording, build only the save-now location write and its restore; skip the mod-map location and the placeholder gear.
- A fault in a save hook stops the run and names the mod (M3d); nothing continues half-done.
- Record which flags each mod owns, and report on load when they are set but no container is present.

*Done:*
- A test mod's counter is nonzero at a save and raised afterwards. A soft reset to the title and a Continue from that save in the same run read back the saved value, not the raised one, and a fresh process that Continues from the card copy reads the same. With the chunk write disabled (the mutation), the same-run Continue does not read the saved value back.
- **Pass-through:** a save holding mod A's chunk, re-saved in the port with A unloaded and mod B loaded, still holds A's chunk byte for byte. With pass-through disabled (the mutation), the same check fails.
- **Mods off, in the batch-A build, each check inside one run** (rule 7):
  - every X2 site's call count is nonzero in a run that reaches it (a New Game for N11's two sites; a Continue, then a save, for the rest), and its count of bytes written stays 0. A handler that writes one byte (the mutation) makes it nonzero;
  - the block read back from the card copy after the save hashes the same as it did at the image hook;
  - that save loads in the build from before batch A: the XOR check (`fn_801A4684`) passes and Continue lands on the saved map.
- A test mod that faults in the snapshot hook stops the run and names the mod, and the card copy is byte-identical to itself before the run. The hook runs before the writer `fn_801A3B30`, so nothing half-built reaches the card.
- A mutation that writes the gap after the XOR is caught by the game's own checksum.
- **The save matrix, if Q2 chooses the fallback.** It starts from a save made on T1's alias map `a045a` with a mod on that keeps a counter, sets a flag it owns, and has filled a placeholder weapon that is equipped:
  - the port with mods off loads it at the fallback: peek `0x80311AC4`/`0x80311AC8` and get the fallback's map word and letter, not `a045a`'s, and the weapon shows as its substitute, never ダミー. **Owner:** Dolphin loads it there too;
  - the same card, loaded with the mod on, puts the player back on `a045a` with the counter and the weapon intact;
  - re-saved where X2 is absent (the build from before batch A, or **Owner:** Dolphin) and loaded with the mod on, it lands at the fallback, the counter takes its default, and the owned-flag report names the mod. The block comes from `memCalloc` (`fn_801E1A74(1, 12800)` at `0x801A4584`), so such a save carries no container.
- **Without the fallback:** a mod save loaded in the port without its mod reports what is missing.

**X3. Memory for mods** — *a day, `--link`, milestone 5.*
- `g_ram_top` replaces `MEM1_SIZE` in the device-model bounds.
- Arena hi to `0x81800000` (+1.1 MB).
- The 8 MB tail either as a mod window **or** handed to heap 4 (32 MB total), not both.
- **Correction:** `mem_guard` commits the whole tail on the first stray access (`main.c:593-596`), so "the rest stays a tripwire" needs a guard change.
- Leave the size words alone.

*Done:*
- Off, the contract's checks pass, including `test_memguard`'s report of an access at `0x81800000`, the tripwire.
- On, a peek in the same run of heap 4's size is checked against its own boot layout: the size word at +0 of its 12-byte descriptor in the OS heap array at `0x804E74E0` (handle at `0x80347694`) must equal the arena-hi word at `0x80000034` minus heap 4's start `0x80D3B520`, and that arena hi must be the mode's top (`0x81800000` for the mod window, `0x82000000` with the tail handed to heap 4) minus the FST's size rounded up to 32 bytes. With the disc's own FST that is `0xAA3DC0` (10.64 MiB) or `0x12A3DC0` (18.64 MiB); vanilla's arena hi, `0x816DF2E0`, fails it.
- A mod string in the window shows in a message.

**X4. More enemy kinds per battle, then more records** — *hours for the kinds (`--link`, in R1's wrapper, once batch A has landed); several days for the records (batch B).*
- **The kinds [V].** The 4-kind cap is a memo in `fn_80077428` (`cmpi r25,4` at `0x80077B34`), and its only defect is the garbage r4 at `bl fn_800770B8` (`0x80077B58`).
  - Fix it in R1's `on_enemy_spawn` wrapper (lr `0x80077B5C`, r25 ≥ 4 → r4 = `fn_80077B88(r24)`). The wrapper is native, so this is a `--link`.
  - The alternative is a `hooks.txt` entry at `0x80077B58`; it joins batch B only if chosen.
  - Log (r25, r4 in, r4 out) at every spawn, by either route, and report a miss rather than silently using the fallback record.
- **The records.** Redirect the 8 KB battle-start copy into X3's window [I]. `fn_800C23CC` copies into an immediate address (`0x803036E8`) and stores that address to `0x803474B8` [V], so the redirect changes code: batch B.

*Done:*
- In a battle with 2 to 4 distinct ids, the wrapper runs (nonzero calls in the run report) and its r25 ≥ 4 fix-up runs 0 times, so every spawn logs r4 out == r4 in. r25 reaches 4 only on a fifth distinct id: the memo is reset at `0x800779B8`–`0x800779E8`, and the loop `0x80077A28`–`0x80077B38` falls through only when all four slots hold other ids.
- A mutation that lowers the test to r25 ≥ 1 makes the fix-up count nonzero in that battle: r25 at `0x80077B58` is the id's memo slot, so the second kind arrives with r25 = 1.
- In a battle with 5–8 kinds, 5–8 distinct models load, the fix-up count equals the spawns whose id overflowed the memo, and no miss is reported.
- In that 5–8-kind battle, no block falls back to heap 1. The game has no battle heap: the mem layer takes battle allocations from heap 4 and, when heap 4 is full, silently retries in heap 1 and sets the block's byte +31 to 1 (`0x801E18C0`–`0x801E1938`), so the models would still load. The run report counts the blocks on the mem layer's list (`0x802F6748`) with byte +31 = 1, and the count stays 0. It also reports heap 4's lowest free total and largest free block in the battle. A mutation that fails one heap-4 allocation during the battle makes the count 1.
- **The records, mods off, in one run of the batch-B build that reaches a battle:** the redirect site's call count is nonzero, and it redirects 0 copies.
- **The records, with the redirect on:** a map whose `.enp` holds 20 records fights an enemy whose record lies past the old 8 KB. Its actor +272 points into X3's window, by peek, in the same run.

**X5. Host audio** — *a day for the mixer; several days for music.*
- A mixer in `audio_push_block`, after the guest and into a host buffer the game never reads, with OGG/FLAC and unlimited voices.
- **Music packs:** mute a voice whose ARAM source maps to a replaced track and play the host stream. Battle music changes with the fight, so the mapping keys on the stream.
- **Budget:** decoding runs on the game thread (`dsp.c:222`), so it counts against the frame; the Done reports it.

*Done (each in one run, rule 7):*
- One `SOA_WAV` recording with a pack that replaces `m01`:
  - the pack's track correlates. `audio_check.py` gains a PCM needle decoded from the pack's OGG/FLAC; today it accepts only a `.dsp`;
  - `extracted/sound/m01_L.dsp` no longer does (under 0.15, the script's "no match"), so the replaced voice is muted, not mixed underneath.
- The WAV is written after the mixer. Today `wav_append` records the guest's block before any mixing (`audio_out.c:108`).
- With no pack stream or host voice active, the mixer is an identity in the same run: a count of blocks whose output differs from the guest's block stays 0, over a nonzero number compared. A mutation that changes one sample of one block moves it to 1.
- **Budget (rule 7):** host decoding time on the game thread per frame (p99 and max), from one live run, against a limit fixed before the run.

**X6. Injected draws** — *several days, `--link`, after K4.*
- `gxr_inject` draws host meshes before the HUD, depth-tested, and before the XFB copy.
- Each gets a stable match key, so Track H's interpolation treats it like the game's own draws.

*Done:*
- A test cube stays put and is occluded, with frames opened.
- Off: 23/23.
- **Budget (rule 7):** injected-draw time per frame (p99, max), from one live run, against a limit fixed before the run.

**X7. Native systems** — *week-plus each.*
- State in X2's chunks, UI in M8, effects through R1, X1 and `call_guest`.
- The first is a **bestiary**. Then crafting, crew perks (after K8), and a Pinta's Quest-style minigame whose loot enters the save.

*Done (bestiary, each in one run, rule 7):* with at least one kill counted, save; make more kills, then soft-reset to the title and Continue from that save in the same run. The counts read back at their values at the save, not the raised ones, and those match R0's log up to the save. A fresh process that Continues from the same card reads the same values. With the bestiary's chunk write disabled (the mutation), the same-run Continue does not read back the saved values.

**X8. Text beyond the font** — *a day to several days* (batch B).
- A native glyph lookup (`fn_801E26E0`) and a bigger font buffer, with glyphs from a TTF.
- The text hook `fn_8010BBD8` swaps messages keyed by script, entry and a hash of the original.

*Done:*
- A replaced message shows an accented character (frame opened), and read-aloud speaks it.
- **Mods off, in one run of the batch-B build** (rule 7):
  - each call through the native `fn_801E26E0` is also answered by `recomp_fn_801E26E0` (a leaf whose only side effect is the 0/1 flag it stores through r4, at `0x801E27F4`; the twin runs on a copy of the CPU state with r4 pointed at a scratch guest word, so the game only ever reads the native call's flag), and the two agree on both r3 and the flag: 0 mismatches over a nonzero count, in a scenario that reaches dialogue. A mutation that remaps one code makes the count nonzero;
  - in the same scenario, the `fn_8010BBD8` hook's call count is nonzero (it lays out every field message) and it substitutes 0 messages. A mutation whose handler replaces one message makes the substitution count nonzero;
  - a FIFO replay cannot stand in for this: replays run no game code.

**X9. More saves** — *a day.*
- Slot B's card (+7), then card pages.

*Done:* the save menu lists slot B's files, and Continue from slot B lands on its map.

---

## E. Sequence, milestones and decisions

**Ordering rules.**
- **Two retranslation batches, not one:**
  - **batch A** (milestone 2): R1's wrappers and X2's save hooks, including N11's NG+ sites;
  - **batch B** (milestone 6): X4's records redirect (`fn_800C23CC`'s copy into `0x803036E8`, whose address is built into the code) and X8's font hooks.
  - **X4's kinds fix is in neither.** It lives in R1's `on_enemy_spawn` wrapper, a `--link` once batch A has landed, and ships with X4 in milestone 6. The `hooks.txt` entry at `0x80077B58` is the alternative, and joins batch B only if it is chosen.
  - **R7 and R9** are unscheduled, and each adds `hle.txt`/`hooks.txt` sites: into batch B if picked up before milestone 6, otherwise a retranslation of their own with the same checks.
  - **Each batch is checked inside one run** (rule 7), never by comparing two live runs:
    - the self test;
    - every new site's call count is nonzero;
    - with mods off, each pass-through writes nothing;
    - batch A: the save block checked within one run, and a new-build save loading in the old build (R1's mods-off checks);
    - batch B: X8's pass-through (X8's Done).
- R0 reaches its Done only after R1 (its doubling check needs `on_damage`).
- **Milestone 1 does not wait on milestone 2:**
  - P1 reads its preset (off, half, normal, double) from `SOA_ENCOUNTERS`, which a new `encounters` line in `settings.c`'s `k_settings` sets from `soa.ini` (a relink). M16 later makes it a declared option.
  - P6's and P10's checks close without R0, both in `battle.scn`'s deck fight; P10's pad 2 is scripted through an environment variable the mod reads. Both repeat on R0 once it lands.
  - P10 sessions cannot be replayed until pad 2 goes into the event track (rule 6); the mod logs that once per run.
  - P1's preset and P6's seed are in the recording's `# config` line since P6 (24d9235, 79c9ad8), and a replay with a different value warns (rule 6). The event track's strict refusal comes in milestone 2.
- **Slices that must land first:**
  - T9 (names) before T3 and R0, so nothing new is written against raw hex;
  - T4 before N10 (its fight list);
  - X1 before T11, R2 and N6;
  - K4 before X6 and N8;
  - K8 before T3's crew table, X7 and N9.
- **Dependencies on the framework** (sections A and F):
  - **M8** before:
    - the gamepad chords' overlay withholding (the chords ship in milestone 1 without it);
    - the event track's hotkey and overlay lines (it records settings lines first);
    - P7, P9, P12, R5, T11's placement mode and N10.
    - PLAN-60FPS-MODS.md puts M8 in its step 4, after the renderer and pacing work, so section F proposes moving it ahead.
  - **M7b** before P9, P12 and T6b;
  - **M16** before R3, R4 and P1's declared option;
  - **M3d** (its fault stop at in-game sites) before R1 and X2 (milestone 2) and X1;
  - **M6** before `patches.txt` accepts T9's names for fields behind a pointer or narrower than a word (T9's C header and Python module do not wait on it);
  - **M19** (the clock) lands in milestone 1, ahead of P4 and turbo past 2×.

**Milestones.**

| Milestone | Slices | What a player gets | Rough size |
|---|---|---|---|
| **1. Comfort pack** | P1, P6, P11, P10, P3, P5, T0; from section F: M18 rumble, H19 fullscreen, M19 the clock, gamepad chords (without the overlay withholding until M8), the first-run amendment (specified in `docs/specs/comfort-pack.md`, which adds P6b, CH1, M5b, P10a, P11b, T0c and M11a) | Encounter slider (a `soa.ini` line until M16), dialogue auto-advance, couch co-op, rumble, fullscreen, a clock that survives sleep, `.gci` saves, picture options, a pinned seed (reproducible battles wait on K6) | about 3 weeks |
| **2. The gameplay core** | M8 and M7a/b first (PLAN-NEXT C6), then T9, T1, R0, batch A (R1 + X2 incl. N11's NG+ sites), T2, K1, K6, K12; from F: M16 options (manifest v2 is done), M3d's in-game fault stop, the event track (settings lines first; hotkey and overlay lines once M8 lands) | Nothing visible yet; every later mod stands on it | 4–5 weeks |
| **3. First gameplay mods** | R3, R4, R5, T3 + K8, T5, R6, P7 + K7, K2, K11 | Difficulty presets, boosts, battle information, rebalances, the Captain's Log | 3 weeks |
| **4. New ways to play** | T4, P9, N10, N11, R8, P12 + K9, P4 | Arena and boss rush, New Game+ and challenges, auto-battle, fast travel, fast boot, the developer rooms | 4–5 weeks |
| **5. The new bounty** | X1, T6, T11, T10, X3, N1, N2, N3 | The first new content: a quest, an enemy, a weapon with its description | 4–6 weeks |
| **6. Beyond the disc** | batch B (X4's records + X8), X5, R2, N4, N5, N6, T6b, T13 | More enemy kinds, new status effects, music packs, new text, ship battles, the endless dungeon, shareable packages | 2–3 months |
| **7. New worlds** | T8, K4, X6, X7, N7, N8, N9, R10 | New rooms and islands, native systems, the randomizer, the balance lab | months; needs art |

**Unscheduled, any time an evening is short:** K3, K5, K10, P8, P13 (its measurement), P14, T7, T12, R7, R9, X9.

**Decision points.**
- **After milestone 1.** PLAN-NEXT's order follows milestone 1 with C5, H17, the disc layer, portability and the GPU spike; milestone 2 follows the gate.
- **After K6.** If battles are not repeatable with all three reseeds pinned, R10 compares distributions over many runs, P6 keeps only its milestone-1 check (every reseed counted and pinned), the two-run comparisons of R0's log (R1's against the old build, R4's against an off run) wait on D4, and D4 moves up.
- **After T4.** If a script cannot round-trip, that script alone is edited as a binary delta against the player's own file (T1's deltas), recorded as an exception. It is never a whole-file override: that would ship the game's dialogue (rule 3), and the guard and T13 refuse its `.sct` suffix. If T1 decided against deltas, that script stays closed to mods until the assembler round-trips it.
- **Before milestone 7.** Art. Without an artist, milestone 6's remixed and procedural content is the ceiling, and it is a high one.

**The first three slices:** *P6 and T0 are done. P1 is comfort-pack P1a, done (090eea6), and P1b; P11 is comfort-pack P11.*
1. **P1 with P6** (hours each). P1 ships as a `mod.dll` reading `SOA_ENCOUNTERS`; its `soa.ini` line and P6's pin are relinks.
2. **P11** (hours; M3b is done), dialogue auto-advance.
3. **T0** (hours), the guard's new suffixes and the content check.

Milestone 2 follows the GPU gate ([PLAN-NEXT.md](PLAN-NEXT.md) C6). It opens with **M8** and **M7a/b**, which many later slices need (the dependencies above), then **T9**, **T1** (disc-layer I6/I7) and **R0**.

X1 (a day, `--link`) comes first in milestone 5, because T11 is its first user: the AI tracer runs on its log-and-forward thunks. R2 and N6 follow in milestone 6, and X7 in milestone 7.

---

## F. Proposed for the other plans

These belong in PLAN-60FPS-MODS.md (worked by another session) or PLAN.md. They are listed here for the owner and that session to adopt, not edited into those files. The ids are proposals.

**For Track M (mods):**
- **Manifest v2** — *hours; now, before any API bump. Done 2026-09-25: 3949028, b071949, b1199b3 (FINDINGS "Manifest 2"). `requires =` and `--build-info` remain a later slice.*
  - `mod.ini` gains a stable id, a version, authors and `manifest = 2`. Unknown keys under a reserved prefix warn instead of refusing, and `api` becomes a minimum.
  - Today `mod.c` refuses any `api` but the literal "1" (`mod.c:818`, checked here), so the first API bump would refuse every existing mod.
  - Recordings name mods as `id@version:hash`. Two mods with the same id are refused, because X2's chunk key and T2's lock depend on unique ids.
  - Later, a separate slice beside M13 and R1: a `requires =` key for compiled-in sites and events, `soa.exe --build-info`, and a mod-shipped build.txt limited to modsites lines (a mod cannot supply the native body an `hle.txt` line needs).
- **M16. Options each mod declares** — *several days.*
  - Typed options (int range, bool, enum, string, seed) in `mod.ini`, with values in `soa.ini` under the mod's id.
  - `${name}` substitution in `patches.txt`, and an API call for DLLs.
  - M8 draws each mod's page with no per-mod UI code.
  - An environment override (`SOA_MOD_OPT=mod.option=value`), because checks ignore `soa.ini`.
  - Out-of-range values are refused.
- **M17. A mod list with order and a conflict report** — *a day to several days.*
  - Today folder name decides order: a byte-wise `strcmp` qsort (`mod.c:924`), then loaded in that order (`:928`). A second patch to the same word silently wins: the per-frame apply loop (`:977`) writes every patch in load order, with no overlap check.
  - Refuse overlapping writes unless one mod declares `overrides`, and only when their conditions can overlap.
  - List what each mod patches and registers.
- **M3d. Crash and hang reports that name the mod, and a safe mode** — *several days.*
  - A log file first.
  - Each callback wrapped in `__try/__except`, naming the mod from `g_cur_mod` (checked here: it is set around every dispatch).
  - At sites that run inside the game (X1 thunks, R1 events, X2 save hooks), a fault stops the run and names the mod. Nothing continues half-done.
  - Check the buffer a texture provider hands back while `g_cur_mod` is still set: copy its w×h×4 bytes inside the guarded dispatch in `mod_texture`. Today `mod_texture` clears `g_cur_mod` before it returns (`mod.c:530`), and the first read is the `memcpy` in `gxr_tev.c`'s `maybe_replace`, so a short buffer faults in the renderer with no mod named.
  - A crash file: commit, build level, DOL SHA-1, mods, the last log lines, a guest backtrace.
  - A hang reporter for windowed play (the watchdog is off there).
  - Safe mode: a pad button held at boot.
- **M15. Hot reload** — *hours for the shadow copy, then several days.*
  - Load `mod.dll` from a shadow copy in `build/modcache`, so it can be rebuilt while the game runs.
  - A reload at the safe point must drop the mod's callbacks, re-wire the dispatchers, flush the texture cache, restore original values before re-applying `*= k`, and log the new hash as an event.
  - A Lua host is a separate, later slice.
- **The event track (rule 6)** — *days for the event lines; hours for the rest.* The settings lines come first (milestone 2); the hotkey and overlay lines once M8 lands.
  - A "recorded" flag on game-changing entries of `settings.c`'s `k_settings` (checked here; P1's planned `encounters` line is one), plus each loaded mod's declared option values (M16), building the `# config` line. Today a mod enters that line only as `dir:hash` over `mod.ini`, `patches.txt` and `mod.dll` (`mod.c:865`, `:935`), so an option set in `soa.ini`, such as R3's difficulty, is invisible to it.
  - `@frame kind key=value` lines for hotkeys, chords, overlay actions and mid-run changes, fed to M8's queue on replay.
  - Pad 2's input, for P10, with the settings lines. The recording holds port 1 only, so until pad 2 is in it a co-op session cannot be replayed; P10's mod logs that once per run.
  - A strict switch for `soak.py`, R0 and T6 that refuses a mismatch; today it only warns (`si.c:573-577`).
  - *Done, the settings lines:* under the strict switch, a recording made with P1 on double is refused on half, and without the switch the log names the mismatch.
  - *Done, pad 2:* a co-op recording holding at least one pad-2 press on a co-op member's turn replays with no second pad connected. In that run the `[si]` log, written after the filter (`si.c:763`), shows each recorded pad-2 press on port 1 at its frame. Deleting one pad-2 line from the recording is the mutation: the `[si]` log then no longer shows that press at its frame.
  - *Done, the event lines (after M8):*
    - A setting changed mid-run from a hotkey (turbo, once M11 exists) is applied at its recorded frame: the replay's log has an applied-event line carrying that frame (a same-run check, rule 7).
    - Deleting that event line is the mutation: the applied line is then absent, and the log shows the setting unchanged after that frame.
    - No check compares two replays frame for frame, because a pad replay is a live run.
- **M18. Rumble** — *hours. Specified as comfort-pack M18 ([specs/comfort-pack.md](specs/comfort-pack.md) 3.7).*
  - The game drives the motor through `PADControlMotor`, writing SI OUTBUF bits 0–1. The port stores them in `g_outbuf` and never acts on them (`si.c:869`, checked here).
  - Map channel 0's change to `XInputSetState` on the XInput slot that port 1's input is read from: slot 0 today (`window.c:433`), the first connected slot after the M8 amendment. Stop the motor on pause, focus loss and exit. Keep it off headless and in replays.
  - A strength setting (an M5 key, 0 = off) scales the speed; the game only sends on or off.
  - *Done:* a self-test case in `runtime/selftest.c` writes channel 0's OUTBUF through `si_write` and counts the calls the port makes to the motor:
    - bits 0–1 = 1 gives one call with nonzero speed;
    - bits 0–1 = 0, and bits 0–1 = 2 (hard stop), each give a zero-speed call;
    - the same writes to channels 1–3 give no call;
    - with the strength at 0, headless (no window), and while `SOA_PAD` or `SOA_PAD_FILE` drives input, no write gives a nonzero call;
    - pause, focus loss and exit each give a zero-speed call while the motor is on.
  - That the game keeps those bits off while its own Rumble option is off is the game's behaviour, and already true today. It is why the port needs no gate for that option; it is not this Done.
- **M19. A clock that survives sleep and speed changes** — *several days. Specified as comfort-pack M19 (3.10).*
  - Game time follows `timespec_get(TIME_UTC)` (`hle.c`, checked here): not monotonic, and it keeps running through sleep.
  - Changing speed mid-run would jump it.
  - Base it on `QueryPerformanceCounter`, re-anchor on every speed change, treat any wall jump over about 250 ms as paused time, cap the audio catch-up, and pause at the safe point.
  - A test knob, `SOA_STALL=<frame>:<seconds>`, new with M19: at that frame the game thread sleeps once for that many seconds, which is how a suspend looks to it. It is not `SOA_GXR_STALL` (`gxr.c:168`), which only holds a rasterizer worker back by microseconds.
  - *Done:* with `SOA_STALL=600:30`, game time advances by under about 1 s across the stall. The mutation keeps the knob and drops the jump rule: the same stall then advances game time by about 30 s [I].
- **M5 amendment: a first run without a terminal** — *hours. Specified as comfort-pack M5b (3.9).*
  - Resolve every path against `soa.ini`'s folder: the card path is relative (`exi.c:90`, checked here), so a launch from `gen\` makes a fresh blank card.
  - Default to a rendered window when `soa.ini` exists, and hide the console.
  - A setting, off by default, that ignores the gamepad and mutes audio while the window is unfocused, so a launcher or Armoury Crate in front no longer drives the game. Today only the keyboard waits for focus (`window.c:404`); the pad is read whatever has it (`:433`), on purpose (`:389-392`), so the default stays as it is.
  - *Done:* a launch from a front end with no arguments boots rendered, on the same card: the log's `[exi] memory card` line names the card beside `soa.ini`, not a new blank one.
- **M8, earlier in PLAN-60FPS-MODS.md's sequence.**
  - Today it sits in step 4 of "After the first two weeks" (§C), behind step 3's pacing work (H9, H17a, H17b, H18a–e).
  - Here it gates the chords' overlay withholding, the event track's hotkey and overlay lines, P7, P9, P12, R5, T11's placement mode and N10. The proposal is to take it right after M5.
  - Its Done warps and saves from the menu, which are M7b's and M7a's actions: either they move with it, or that part of its Done waits for them.
- **M8 amendment: every action from the gamepad** — *hours to a day. Specified as comfort-pack CH1 (3.6).*
  - Chords on buttons the game never sees (LB, View, the stick clicks), detected in `window.c`/`si.c`, because `pad_filter` gets only the 12 GameCube buttons. The chords land in milestone 1, ahead of M8.
  - Once M8's overlay exists: while it is open, withhold the d-pad, A and B from the game before they are recorded.
  - Use the first connected XInput slot, not always slot 0. Remapping and presets go in M5.
- **M7a amendment: a save-now that leaves the port** — *hours for the refusal; the fallback comes with X2.*
  - A Continue always ends by setting `sys[15]` (0x8030E420) to 20000: `fn_801F7B04(20000)` at the end of `fn_801A4354` (checked here). On a map whose script has no op 138 (no save point), that branch was never reachable in retail. At `a116c` it asks for kmap 9001, which the map lacks, and traps (FINDINGS census 3; B6).
  - M7a's fix, writing 0x8030E420 = 0 before the map's script runs, lives in the runtime, not in the save. A save-now on such a map would still take that branch after a P3 export, in Dolphin or on a console [I, not run].
  - Until X2 exists: allow a save-now only on maps whose script contains op 138, and refuse elsewhere with a message.
  - With X2, at its snapshot hook `0x801A4670`: write a vanilla fallback into the map word and letter (+5808/+5812) and the position (+5864..+5916). The fallback is the last op-138 map the party was on. Keep the real location in an X2 chunk and restore it at `fn_801A4354`'s entry. X2 builds this whatever Q2 decides.
  - *Done:*
    - Before X2: in one run, a save-now on `a101b` (its script has op 138) is written and verifies READY, and one on `a116c` is refused with its message.
    - With X2: the card image of a save-now on `a116c` holds the fallback map in its map word and `a116c` in the chunk. A Continue in the port lands on `a116c` and draws (frames opened). **Owner:** the same save, exported with P3, Continues in Dolphin onto the fallback map.
- **M11 absorbs P2 (turbo).**
  - One tick-unlock setting with battle-only and sky-only options, still after H13.
  - Drawn, the opening and ship battles gain almost nothing (18.9 against 19.3 fps; 25.5 against 26.0), and battles about 1.6×.
  - M11's frame skip (SOA_SNAP's `g_snap_every … return` test in `gxr_draw_inner`; `gxr.c:2279` at cb904fa) drops draws only. The EFB-copy path (`reg == 0x52` → `enqueue_copy`) has no such test, so the game's copies to texture still run on skipped frames and copy an EFB that frame's draws never reached. M11's Done must open a battle PNG taken right after a skipped frame.
  - *Adopted (PLAN-60FPS-MODS.md:609 now gives the one-run rate check).* M11's line "The audio report is unchanged" compared the unlocked run with a locked one (rule 7): a frame-bounded run's DMA block count follows its wall time (`dsp_poll`, `dsp.c:215-222`). Replace it with a one-run check: in the unlocked run the AI DMA delivers about 32,000 samples a wall second, counted from the `SOA_WAV` file's byte count over the run's wall seconds, within a tolerance fixed before the run; a `SOA_SPEED=2` run (the mutation) falls outside it. Dropped blocks are checked, against a fixed limit, only when the `[audio]` line has an output device, because with none `audio_push_block` returns before it counts a drop (`audio_out.c:110`). M2's :479 carries the same sentence, but M2 is done and FINDINGS "M2" checked the rate.
  - *Adopted (PLAN-60FPS-MODS.md:604 names `gxr_draw_inner`).* M11 cited the skip as `gxr.c:1534`, stale the same way; it now names the function, since each H commit rewrites `gxr.c`.
  - **Turbo past 2×** in battles, with audio muted: `SOA_SPEED` speeds up the game's audio DMA with everything else, and `audio_out.c` drops what the device cannot play. It covers character battles (scene 7) and ship battles (scene 6 on a map ≥ 500).
    - Character battles run up to 104 guest fps (about 3.5×), so draw every second or third frame.
    - Ship battles run about 80 (about 2.7×), so draw every fourth: drawn every frame they are render-bound at 25.5 fps (FINDINGS "H3").
    - It combines P4's speed switch with the unlock, after S9 and M19.
  - **Owner:** turbo feels right in a window (P2's check, carried over).
- **Rules for turbo, presenting and interpolation:**
  - while the tick is unlocked, present each frame at the next vblank and interpolate nothing;
  - switch only at the safe point;
  - X6's draws carry match keys.
- **Mods in CI** — *hours.* A compile-time `offsetof` check for every `SoaModApi` member, a DLL built against a frozen v1 header loaded on the current port, and a pytest that loads every shipped mod folder through the real loader. Later, a mods-on set of S6 nightly jobs.
- **A CPU budget for mods** — *hours.* Turbo needs a whole frame inside 16.7 ms, and guest work already takes 11.9 ms median and 18.2 ms at worst (performance.md:59).
  - Time each callback (total, p99, max per mod).
  - Report the cores used at the title with mods on, against a fixed limit set from H11's measured 1.2 (FINDINGS "H11"), to catch a mod thread undoing H11's cut from 8.8. Never against a second run.
  - Report the maximum for P8's first-sight loads, which p99 hides.
  - Measure in live runs: replays run no game-thread callbacks. R1, X5, X6, P7 and P8 each carry a budget line in their Done.
- **M3 amendment: a trust boundary** — *hours.*
  - A one-time notice on first load of a native DLL and whenever its SHA-256 changes; headless runs log and refuse.
  - `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | DEFAULT_DIRS`.
  - P7's phone page is read-only, and it needs a token whenever it is not loopback-only.
  - T12(c)'s control channel is always loopback-only, with an Origin check and a token.
- **M9 note.** M3c's texture provider froze a hash with no version field; P8 computes Dolphin's names inside the renderer.
- **M12 note.** The text-speed question is answered (B3).
- **PLAN-60FPS-MODS.md:723.** Add "and at every battle start" (B1). *Adopted.*
- **Done lines in Track M that cannot fail, or are stale (rule 7).**
  - **M8 (:577).** `SOA_HASH` is taken from `g_screen` when the game's copy to the screen is queued (`enqueue_copy` in `gxr.c`). M8 draws its overlay later, in `present()`, and never into `g_screen` (:570). So "`SOA_HASH` lines are identical with the overlay open" cannot fail. Replace it with:
    - a capture taken after `present()` with the overlay open, opened;
    - a same-run check that `g_screen`'s hash is equal before and after `present()` with the overlay open, with a mutation that draws the overlay into `g_screen` and must fail it.
  - **M3 (:503, :505)** is stale against its own status line (:485): M3 is done, and its filters were checked under `--replay`, not on a title run.
    - :503 should say "a `pad_filter` that drops every button", since dropping START alone does not keep a run on the title.
    - :505 should say what FINDINGS "M3c" records: an identity projection filter matches 23 of 23 captures under `--replay`, and a wider view matches only the four orthographic boot frames.

**For Track H (frame pacing and speed):**
- **H19. Fullscreen and a window that fits a 7–8 inch screen** — *hours first, then several days. Specified as comfort-pack H19a (3.8).*
  - Today the window is a fixed 1280×960, not resizable and not DPI-aware.
  - First: per-monitor DPI awareness, a resizable window, borderless fullscreen (Alt+Enter, F11 or a chord), letterboxing, a hidden cursor.
  - Then: fullscreen keys in M5, P5's sharp-bilinear filter, H9 rows for 144 Hz and VRR panels, and M10's aspect as a parameter (16:9 or 16:10).
  - *Done:* replay 23/23 and `title --check`, with no `SOA_HASH` comparison between live runs (rule 7); **Owner** confirms on the device.
- **H20. A power line in every run report** — *hours. A gap filler in PLAN-NEXT M1; its Done is written first.* AC or battery, the battery percentage, the power plan's name, and mWh used on battery. Energy per drawn frame feeds the GPU-backend decision.
- **H8** already falls back to GDI: `SOA_PRESENTER=gdi` selects it, and it takes over when DXGI cannot start (`window.c:327-329`, FINDINGS "H8"). The proposal is only that the path stays when H8 closes, and that **H15d** puts SIMD behind an x64 guard with a scalar path, so Linux and ARM stay possible.
- **Done lines in Track H that compare two live runs (rule 7).** Two unmodded title runs differ on 22 of 40 hashes (FINDINGS "M3c"), so each of these fails with no defect:
  - **H9 (:272-273).** Drop "and `SOA_HASH` lines are unchanged" (:273). Headless runs keep today's path by construction (:265), and replay 23/23 plus `title --check` already cover it. Replace :272's "The audio report is unchanged" with the one-run audio-rate check in section F's M11 entry.
  - **H17a (:382-383).** *Adopted: PLAN-60FPS-MODS.md's H17a Done now reads as below.*
    - **Off:** replay 23/23 and `title --check`, with no `SOA_HASH` comparison.
    - **On:** a same-run contrast. In one `SOA_INTERP=1` run, hash each real frame's `g_screen` before and after its in-between pass; the two must be equal. A mutation that lets the in-between pass write `g_screen` must make them differ. The in-between PNGs are still opened.

**For PLAN.md Track G (second-person readiness):**
- **G3. A player's first run** — *week-plus.*
  - A setup script that offers winget for Python and the VS Build Tools, then extracts, compiles and runs the self test.
  - `extract.py` names European and Japanese discs as unsupported, instead of suggesting `--force`, which also waives the DOL check.
  - It recognises NKit, GCZ, WIA and CISO images and points at Dolphin's Convert File.
  - A "dump your own disc" page. The menu is M8's overlay, not a separate launcher.
- **G4. Decide how the port reaches other players** — *several days.* The owner's side of it is Q3.
  - SPEC.md already rules out a prebuilt exe, because it would carry the translated game.
  - The open option is a one-step build on the player's machine with a compiler the project may ship: zig cc or llvm-mingw, since clang-cl still needs Microsoft's headers.
  - It also needs:
    - the runtime's MSVC-only code handled: `__declspec(thread)` (`gxr.c:123`, unguarded), and `__cpuid`, `__rdtsc` and `#pragma comment(lib)`, which sit behind `_WIN32` and so reach every Windows compiler. `__forceinline` and the byte swaps (`cpu.h:46-55`) already have fallbacks;
    - the one piece that compiles cleanly anyway and behaves differently: `aram.c:160-172` reads the disc directory from MSVC's `__argv`, and on any other compiler falls back to `extracted`. The voice-source index (PLAN.md E1) then names uploads from the wrong disc, or leaves them unnamed [I]. Have `main.c` pass its resolved directory to `aram.c`. That also fixes the `soa.ini` `disc` key, which `aram.c` ignores even on MSVC today (`main.c:1123-1124` honours it);
    - `-ffp-contract=off`;
    - an exact-rounding self-test case for the emitted `fma()`, with a `-mfma` mutation build.
- **G5. Build identity and a stale-link guard** — *several days.*
  - `gen/build_inputs.txt`, written only after a successful `--compile`: hashes of the emitted C and `cpu.h`, and the optimisation level.
  - `--link` rebuilds changed chunks and refuses on a `cpu.h` or level change. Mutation: edit `cpu.h` and `--link` refuses.
  - A version line at startup, and in recordings as its own header line. Never inside `# config`: replay string-compares that line (`si.c:573`), and the event track's strict switch would refuse every recording made on another build.
  - An issue template that says never to attach cards, captures, frames or WAVs publicly.
  - Fix `README.md:100-103` and `CONTRIBUTING.md:30-31`: runtime edits do not always need only `--link`.
- **G6. Licences** — *hours.*
  - Move `LICENSE:23-25` into NOTICE so GitHub detects MIT, and replace the "Placeholder: licensing" section (`ARCHITECTURE.md:617-621`), which still says there is no LICENSE or NOTICE, with a link to both.
  - Classify folders in NOTICE: `mods/` with `config/`, since it holds game addresses; `examples/` MIT; `config/scenarios/` original.
  - Templates (`soa_mod.h`, examples) under 0BSD or CC0.
  - Rule 8, and the owner's answer to Q4 on the GPL route.
- **G7. The name, the trademark and a takedown runbook** — *hours now; week-plus later, only if needed.* Q8 asks whether to rename now.
  - Pick a name that is not Sega's trademark, with "for Skies of Arcadia Legends" as a descriptor. Sega filed new Skies of Arcadia marks in January 2025.
  - Rename the repo, `README.md:1` and the window title.
  - No Sega art and no money.
  - Counter-notice criteria, and what to do if a remaster is announced.
  - Keep full-history git bundles off GitHub.
  - Record the posture as a rule in SPEC.md §2 (Legal posture).
  - Later, only if needed (week-plus): split into an engine repo and a game repo. That is harder than it sounds: 11 of the 25 `.c` files in `runtime/` use a literal game address in code, 14 counting comments (counted here at cb904fa).
  - A rename lowers trademark exposure only; copyright in `src/` is the larger one.
- **Keep Linux and the Steam Deck possible** — *hours now.* A Proton smoke test (copy `soa.exe` and run the self test) and a clang compile-only CI job. An OS layer, ARM64, native Linux and macOS stay parked (XL).
- **Doc fixes found along the way:** `main.c:1005` (`setup_low_memory`) labels the word at `0x800000D0` "simulated memory size (mirror)" and stores 24 MB (`MEM1_SIZE`) there; that word is the ARAM size, 16 MB on retail hardware. Also the RTC note in B6.
- **Tooling: try Dolphin Memory Engine on the port** — *hours, when the machine is free.*
  - DME 2026.04.16 or later should attach to `soa.exe` with `DME_DOLPHIN_PROCESS_NAME=soa.exe` [I, untried].
  - Low memory is laid out as a GameCube's (`setup_low_memory`, `main.c:993-1009`), and guest memory is big-endian as in Dolphin. But it is a private allocation: 24 MB committed (`main.c:633-635`) inside a 32 MB + 64 KB reservation (`main.c:566`). Whether DME's region scan finds it is what the try settles.
  - Record the result in `docs/research/mods.md`.
  - Document DME as read-only by convention: its writes are not in the pad recording, and they bypass `SOA_WATCH`.
  - Cheat Engine needs a byte-pattern scan, because the base address moves every run.

---

## G. Questions only the owner can answer

Other sections cite these as Q1–Q11. A G with a number (G3–G7) is always a proposed PLAN.md Track G slice from section F.

- **Q1. Which handheld, exactly?** A ROG Ally (120 Hz, variable refresh) and a Legion Go (144/60 Hz, 2560×1600) need different fullscreen and refresh work (H19).
- **Q2. The save promise.** Build X2's vanilla-safe fallback (mod maps save a vanilla location; placeholder gear swaps to a substitute), or keep the honest wording in section A?
- **Q3. Distribution.** Stay source-only, or build section F's G4 one-step build with a compiler the project can ship? And is M8's overlay enough, or do you want a separate launcher?
- **Q4. The community tools' licences.** Re-derive everything from the DOL (feasible; the handler layouts agree on 265 of 266), or ask the ALX and SALSA authors for permission or a dual licence? Asking could also open a collaboration.
- **Q5. Game-data boundaries.** Does a text table of enemy names (R5) count as game data? Do original Blender sources for new art belong in the repository?
- **Q6. Non-XInput pads.** Reopen "no third-party runtime dependency" (SPEC.md:463) for SDL3, or use Windows.Gaming.Input or Steam Input?
- **Q7. N3's bounty.** Script-only, as recommended, or extend the Wanted List later?
- **Q8. The name.** Rename the project now (section F's G7)? And what should happen if Sega announces a remaster?
- **Q9. New Game+.** Offer it from any save (simpler), or only after the ending, which needs a record kept outside the save?
- **Q10. Companion and streaming.** Do you want a phone companion or stream overlays? That decides whether T12's control channel is built beyond condition waits.
- **Q11. Which "Encore"?** The research found Taikocuya's SOALE rebalance. Is that the mod you mean?

---

## H. Not in this plan

- **A GPU renderer, higher internal resolution and VR.** The GPU backend is a spike and gate in `docs/specs/gpu-backend.md` (PLAN-NEXT M5), and then it is the owner's decision.
- **60 fps and widescreen.** They are PLAN-60FPS-MODS.md's Tracks H and M.
- **Archipelago and lockstep online co-op.**
  - Archipelago waits on N9 (a randomizer's logic is Archipelago's world definition) and X2 (the received-items index lives in the save).
  - Lockstep co-op waits on D4.
  - P10's couch co-op over Parsec needs neither.
- **More than 80 items per category, more than 255 enemies globally, more than 7 saves in one card's menu.** Each is Track F work, and the cheap ways round cover the first mods.
- **A ninth Wanted-list entry and a third crew candidate.** These are native code but not Track F (B4, "Code, but not Track F"). Q7 decides whether the Wanted List is extended, and K8 sizes the crew work.
- **Voice acting.** X8's hook and X5's mixer carry it; the voices are a community project, cast with consent.
- **Considered and dropped by the gap sweep** (plan-gaps.md §4):
  - a speedrun kit;
  - a frame-to-glTF scene ripper;
  - a lost-content museum;
  - AI-content disclosure on mod sites (a README sentence covers it);
  - card-safety work (the card keeps two copies of its directory). Two cheap pieces remain worth an hour each: a single-instance lock inside `soa.exe`, and a quit guard during the game's delete-then-create save.
