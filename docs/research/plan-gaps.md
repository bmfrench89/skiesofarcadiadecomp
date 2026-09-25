<!-- Written 2026-09-25 by a read-only gap sweep of docs/PLAN-GAMEPLAY-MODS.md: seven critics, one lens
each (the player, the modder, engineering risk, unmapped game systems, distribution and legal,
creative ideas, the plan's own structure), a merge, and two skeptics per candidate (is it already
planned? is it worth it and true?). 83 items were proposed, 61 remained after merging, 53 survived
both skeptics and 8 were dropped (section 4). Nothing was run: disassembly, the local disc, existing
build/ logs and captures, the repository and web sources only. The lead re-checked three claims
before it was committed: the battle-start reseeds at 0x8000A1CC-D8, the 22-of-40 live-run hash
difference in FINDINGS.md, and the ignored rumble bits at si.c:869. Line numbers cite
docs/PLAN-GAMEPLAY-MODS.md as committed in c64babb (before the revision that folded this report in)
and other files as of 0515868. -->

# Gaps in the gameplay-mods plan, and what to add

The two things I'd act on first are both fixes to the plan rather than new work. **The race seed misses the reseed at battle start**, which is an hours-long relink fix. **About a dozen "Done" checks can't fail as written.** Both are in section 2. For new work, the gameplay items with the most payoff are:

- **Arena and Boss Rush**, which re-fights the game's own boss and event battles.
- **New Game+**, which carries your party into a new game.
- **Dialogue auto-advance**, a few hours on the finished controller-filter layer (M3b).
- **Everything from the gamepad, plus a first run without a terminal**, which is what the handheld needs.

Sizes, in this repo's evenings: **S** is hours to a day, **M** is several days, **L** is one to three weeks, **XL** is months. Proposed slice IDs continue each track's numbering: P10+, K7+, T9+, R10, N10+, M15+, H19+, and G3+ in PLAN.md's Track G.

## 1. Worth adding

### A. New ways to play

**Arena, Boss Rush and Time Attack.** Pick a boss or event battle from a menu and fight it again, alone or in a chain. Scores are rounds, damage taken and game frames at 0x803475C0; game frames rather than wall time, so turbo and 60 fps can't change a score. R0 already builds the parts it needs (force a battle, script the commands), but only as a test harness.
- **The fight list:**
  - The fights are the 250 event records (evp+1600+37·id, enemy-data.md:257-283). Scripts request 235 of them through op 112.
  - About 112 are distinct fights. 228 of the 250 differ only in who fills the fourth party slot.
  - The list, with each fight's stage and chapter, comes from scanning the scripts' op-112 calls with T4's decoder.
- **What it must handle:**
  - 29 records have the rule "must not lose". The mode forces "may lose" on them or catches the game-over.
  - It must restore party, items and gold after each fight, or zero the rewards through on_rewards. Otherwise it becomes a farm.
  - "Return to where you stood" is allowed only where the random-encounter gates pass. Elsewhere it uses an arena map or the fade fix (0x80347518 = 0).
- **First step:** force one event id and watch it run. Only kind 0, a map formation, has ever run this way (FINDINGS.md:1324). The event route is unverified.
- **Ship battles:** wrap P9's 398A select screen rather than building new machinery.

*L · N10, after milestone 3 · Needs M4, M7b, M8, P9, R0 (with the seed fix), R3, X2.*

**New Game+ and challenge rules.** Start a new game that keeps your levels, magic, gear, gold and Cupil, with R3's presets making enemies harder. Challenges are text files: no items, no magic, no running, fallen stay fallen, solo, no shops, low level. Each bundles a seed and a preset.
- **The obvious hook is wrong.** X2's on_new_game fires before fn_801F01E4 (0x80228BF4) resets all six characters from their templates, so anything written there is wiped.
- **Where the carry-over goes instead:**
  - Put it in a pre-hook on fn_801F3024. Its only non-debug caller runs at New Game, and it rebuilds levels and spells through the game's own formula.
  - Write items, gold, the Cupil bytes and the rating after 0x80228BF4.
  - This adds a fifth X2 hook site, gated on "NG+ pending", because fn_801F3024 also has a debug caller at 0x800FFD80.
- **The game never saves after the credits** (FINDINGS.md:1296-1305). So either offer NG+ from any save, or keep a "cleared" record outside the save.
- **Leave out the ship.** 0x8030CD5C is an index whose meaning is unconfirmed.
- **Write the command-availability bytes every turn.** The challenge rules write them at *0x80346C14 in every phase 1 of a battle, not once at the start.

*M · N11, after milestone 3 · Needs X2 (plus one hook site in its retranslation), M4, R1, R3, M5; T6 checks that a normal New Game is unchanged with it off.*

**Couch co-op battles, and online co-op through Parsec.** A second controller commands chosen party members in battle, as in Final Fantasy VI; player 1 keeps the field and menus.
- **How it works:**
  - A mod on the controller filter (pad_filter) reads whose turn it is at 0x80347330, gated on scene 7 and phase 1. When it's a co-op member's turn, it swaps in pad 2's input.
  - Parsec shows a remote friend as a second XInput pad, so the same mod is online co-op with no netcode.
  - The plan parks co-op as XL behind the deterministic clock (PLAN-GAMEPLAY-MODS.md:210, :733).
- **Care points:**
  - Check an absent pad at most once a second, as window.c:209-216 does.
  - At a handover, send neutral input until the incoming pad's buttons are released. Otherwise a thumb resting on A confirms the next member's command.
  - Make the pad slot configurable.
  - Replays need the event track (section D).
- **One-hour spike first:** going back to the previous member with B, members who can't act (+28 & 0x6D00), and ambush rounds.

*S–M · P10 · Needs M3b (done), M5; ship battles later, after K5 and R9.*

**Dialogue auto-advance and hold-to-skip; battle turbo past 2×.** The game has no text-speed option, and P2 tops out near 2×.
- **(a) Auto-advance and hold-to-skip (field text only).** This is a controller-filter mod:
  - it finds the message window through 0x80346E60;
  - a page is complete when window+56 ≥ window+54, and then it sends an A press;
  - it must leave choice boxes alone. SELECT also sets 0x8030E468, so the spike finds the choice marker.
  - it must respect window flag 0x1000.
- **(b) Battles at about 3×.** Combine P4's run-time speed switch with the tick unlock, in battles only, with audio muted.
  - Normal battles run 104 guest fps, so draw every second or third frame.
  - Ship battles run about 80 guest fps, so draw every fourth frame.
- **Not worth doing:**
  - "Fast" text through window+60: 1 is already the minimum.
  - "Instant" text: A/B already reveals the page.
  - Cutscene fast-forward past 2×: the opening tops out at 50 fps.
  - Flag 1087 as a trigger: every NPC talk sets it.

*(a) S · P11 · Needs M3b (done). (b) S, an extension of P2 and M11 · Needs S9's speed-equivalence result and the clock fixes in section E.*

**Sailing: sky-only turbo, fast travel, and the ship's controls.** Sailing is a large share of a playthrough, and no slice touches it.
- **Cheapest:** add a "sky only" option to P2, gated on 0x80347464 == 1. It needs no research.
- **Fast travel to ports you've landed at:**
  - Copy what a real landing does: go to the destination of the port's M04xxx entry and set sys[15] = 990, which the scripts read as "arrived from the world map".
  - Allow it only in the sky, with no event running.
  - Gate each port on its own landing or story flag. Flags 1312-1479 are the map screen's fog grid, not a list of visited ports.
- **Spike:**
  - Add a watch on the ship object (fldShip, fn_800D1E58) to the world-map run PLAN.md D5 already plans, to find its speed fields.
  - First check what 0x8030CD5C holds; only an init writes it.
  - Record +64 in the ship table is not ship HP.
  - Skip a storm toggle: storms probably gate the story's order.

*S each · K9 (spike, joins D5's run) and P12 (fast travel) · Needs M7b and M8 for fast travel.*

**Photo studio: poster-size stills and a free camera from a captured frame.** A hotkey captures the next frame. An offline replay then re-renders it in three ways:
- **Tiled k×k** through the projection filter, for stills as large as 5120×3840.
- **With an orbit camera** through a new view-matrix filter.
- **With the HUD removed**, by pushing flat (orthographic) draws past the far plane.

It doesn't need K4, because the capture already holds the matrices.
- **Capture:**
  - Arm it at the next frame boundary, or a mid-frame press captures half a frame.
  - Add the photos folder to FORBIDDEN_DIRS, because each photo holds a 24 MB RAM dump.
  - Don't write over `<base>.png`.
- **Tiling maths:** scale p1 and p3 by k and add an offset. The sign of the offset differs between perspective and orthographic projections.
- **Known risks:**
  - The game's copies of the frame to textures sample the zoomed tile, not the screen.
  - Lights must rotate with an orbit.
  - Billboards keep facing the old camera.
  - Geometry the game culled is simply missing.
- **Done:** identity settings reproduce the pinned hash on all 23 captures, and the stitched k=2 still is opened and compared with a 2× upscale.

*M · P14 · Needs M3c (done), a hotkey or chord · Lower priority than the gameplay items.*

### B. Game systems the plans haven't mapped

**The Swashbuckler rating and titles (fn_801EF300).** This routine is the game's own completion checker. It picks Vyse's title from the rating and from special conditions, and in doing so it names nearly every completion counter the game keeps. That gives K2 and P7 their addresses in hours.
- **Where things live:** the title table at 0x802C8E54 (24 records of 34 bytes: name, threshold, four Vyse bonuses), the rating at 0x8030BB3C, the title byte at 0x8030B7AE.
- **How a title is chosen:**
  - Below rating 226, the title is the first entry whose threshold ≥ the rating. Only the threshold's low byte is read.
  - At 226 or more, the special titles are tested. First is title 15, "Vyse the Legend": 88 Discoveries, chests at 100%, B[108]==8 and flag 586.
- **Special titles:**
  - Title 21 also needs a count over item ids 471-478 to be zero (what those ids are is [I]).
  - Title 19's counter is a little-endian u32 at B[78..81]. That it is Fisher King is [I].
  - B[105]==1 overrides everything.
- **The game's own "everything done" award.** The routine ends by setting flags 1096, 2850 and 2852 when six conditions hold. P7 should show them.
- **New titles need code.** The loop count (24) and the title indices are hard-coded, so a moved table is not enough.

*S · K7 (static, then one SOA_PEEK on the part-L save) · Feeds K2, P7, and a "title" table in T3.*

**The Wanted List is a fixed table of 8 bounties.** N3's new bounty won't show up there on its own.
- **How the list works:**
  - Each bounty has one state byte at B[100+i] (0 unknown, 1 posted, 2 defeated, 3 claimed), and B[108] counts claims.
  - Four pointer tables hold the list's text and rewards (names at 0x802EBF7C).
  - fn_801B737C loops `i<8` and marks entries as posted itself.
- **Why a ninth bounty is hard:**
  - A ninth entry has no free state byte: B[108] is the claim counter.
  - A ninth claim breaks the B[108]==8 test in fn_801EF300.
  - The reward table only sets the gold shown. The gold actually paid is a literal in four Guild scripts.
- **Recommendation:** make N3 a script-only bounty that leaves B[100..108] alone. Extending the list comes later. It needs native replacements for fn_801B737C, fn_801B6E5C and fn_801B7274/fn_801B71E8, plus T4 edits to the Guild scripts.

*Notes in K2 and N3 (hours); extending the list is M, later.*

**Crew, the eleven posts and Crescent Isle.** There are 22 crew and two candidates per post. Flag 1039+n means recruited, and 1061+n records the post choice (fn_80194A18, fn_80194A8C). The crew table at 0x802D8E64 (36-byte records) feeds the ship's stats through fn_8021A2B0. X7's crew perks and N9's crew shuffle have nothing to stand on without this.
- **Start from what's already known.** battle-system.md:511 and :519 have part of it. Add fields +17, +18/+20 (ship stat id and bonus), +22, +23, +30, and the equipment side of fn_8021A2B0.
- **A third candidate per post is code, not data:** five functions and two 22-count loops to rewrite, through X1 thunks.
- **Research fixes:**
  - story-flags.md:82 pairs these functions with the wrong flags.
  - ship-worldmap.md:42 should read 017a-f, h, i.
  - content-systems.md:266 should add flags 1061-1082.
  - Drop "Charismatic": nothing sources it.
- **Links:** tie the ship-battle half to K5, and add the ship tables to T3.

*S–M · K8 (no rebuild) · Feeds X7, N9, T3.*

**Cupil's evolution is a 16-row data table.** Fina's weapon changes form through a table at 0x802C9628: Chams needed, the next form on a Cham, and the next form on an Abirik Cham. The counts are bytes at 0x8030BB22-24, not flags, so a Cupil rebalance is a data patch.
- **Where it plugs in:**
  - T3 gains a "cupil" table.
  - P7 shows "Chams eaten since the last reset" from 0x8030BB24. The Chom item (id 290) resets the counts and the form.
  - K2 keeps only the pickup locations.
- **A data lever:** the item code switches on each item's effect byte, so a placeholder item with effect 53 or 75 already acts as a Cham.
- **What stays code:**
  - A new form outside ids 32-47 would read past the table, so it needs a native fn_801F28CC (about 90 instructions).
  - The Final Cupil threshold is hard-coded.

*S · T3 table plus P7/K2 notes · Needs one peek on a save that has Fina.*

**The camp menu and the Captain's Journal.** Mods will want entries in the game's own menu, which a pad can reach, not only in M8's overlay.
- Map the menu's label table (0x802E8FD0) and its page-handler table (0x802E9418, 8 slots).
- Leftover rows (Socket 1/2, Dispatch, and an untranslated "Change Name") could host a mod page through an X1 thunk.
- The journal is a table of records: title, chapter, progress gate, and one picture per chapter.
- Reviving Pinta's Quest's loot is out: its handlers are stubs that return 0.

*S–M · K10 (static) · Real entries need X1 or M13, and X3 for text.*

**"Where am I, and what next?"** When you Continue, and in the overlay, show one objective line and a "last time" note. SoA has no quest log, and handheld sessions are short.
- **What to key on:**
  - Use B[2..5] (0x80310A1E-21), the (part, step) pairs that scripts write after each story flag.
  - Don't use B[6]: it goes backwards (story-flags.md:134-135).
- **Where the notes come from:**
  - The last fight comes from on_enemy_spawn's formation id; on_rewards doesn't say which fight it was.
  - "Recent Discoveries" needs the order logged into T2 flags or the sidecar.
- **Content:** write one line per story part (about 12) first. Step-level lines are real content work.

*S display plus a day of research · K11 (confirm across S7a's part cards that B[2..5] rises at every story beat) and P7b · Needs M8, P7.*

### C. Tools for making and testing gameplay mods

**Named game addresses and a generated header.** Today a modder copies hex addresses out of prose, and a typo that lands on another valid address goes unnoticed. Name the data the research found, generate a C header and a Python module from it, and let patches.txt and T3 accept names.
- **Build on what exists:**
  - Extend config/names.txt and tools/inventory.py to cover data symbols; symbols.txt already lists these objects with sizes.
  - Add one small file for struct offsets.
  - Share one schema with T3 and T5.
- **The header:**
  - Its accessors call SoaModApi's big-endian reads and writes, never host structs laid over guest memory.
  - It sits beside runtime/soa_mod.h, because gen/ is never committed.
- **The test:** re-find each confirmed address from a code reference, and prove the test fails when one address is changed.
- **K2 note:** the RetroAchievements set looks PAL-only ([I]; the page returned 403). Its conditions are leads to re-find in this US build, not addresses.

*M · T9, before T3 and R0 · Needs M6 for names relative to a pointer.*

**A mod kit and docs/MODDING.md.** `tools/mod.py` gets four commands:
- **new** scaffolds a mod.
- **build** makes an x64 DLL without a Developer Prompt and refuses anything that isn't x64. A 32-bit build fails today with a bare "error 193".
- **check** tests a mod against your DOL without launching the game.
- **test** runs the mod on the fake-guest driver test_mods.py already has. It needs no disc, so community CI works.

The guide covers your first mod in 15 minutes, finding an address, patches.txt, and the API rules.
- **The test driver:**
  - Move it into tools/, with test_mods.py importing it from there so the two can't drift.
  - It has nothing for call_guest, M13 sites or R1's events yet. Say so, and grow it with each API version.
- **The API reference:**
  - Generate it from soa_mod.h, with a test, so it can't go stale.
  - Make MODDING.md the home for the rules the plans promise but never place, such as "on_frame_end may only write memory" and "keep hooks.txt away from interrupt waits".
- **Mutation:** `check` must fail a wrong dol_sha1 and a misspelled address.

*M · T10, after M4 and M5 · Owner check: you build a small mod from the guide alone.*

**The quest author's workbench.** "Why didn't my script do what I wrote?" is the question content modders ask most, and T6 only answers pass or fail. The workbench has three parts:
- **A script tracer:** frame, script, entry, opcode name and operands, flag writes, and a stop when a named flag changes.
- **An enemy-AI path tracer.**
- **A placement mode:** nudge an object live and copy the result out as text.

Notes:
- **Two opcode dispatch sites.** fn_80211298 runs an op the first time (r3=1). fn_80212130 re-calls waiting ops every frame (r3=2). Fold the second kind into "waiting on op N for k frames", or every message floods the log.
- **The stock tracer isn't enough.** trace_hit prints registers only and stops after 1,000 hits at one pc. This needs a formatter in runtime/ and its own switch, for example `SOA_SCRIPT_TRACE=me101b`. The flag stop extends S4b's planned SOA_UNTIL.
- **The AI tracer needs only the path:** condition id, branch taken, step. R1's on_enemy_action already reports the final choice. The cheapest route is X1 log-and-forward thunks on the condition table (0x802DFB10) and selector table (0x802DFC28). That requires X1 to be able to call the handler it replaced.
- **Placement:**
  - Live writes go through M8's safe-point queue.
  - The exported result is either a T3 load-time patch or a whole override map file served through T1.
  - Rotation is in units of ×182.0444.
  - First find which actor is the player (a small K item).

*M (tracers) plus M (panel and placement) · T11, milestone 4, before N3 · Needs a retranslation (batched with R1) or X1 thunks; T4's operand table; M8; T3.*

**An interaction crawler.** On one map, walk to every NPC and trigger, interact, and record the result. Content mods break at the NPC nobody walked to.
- **Results it records:** no entry, gated off, ran and returned, stuck, left the map, or fault.
- **A trap in the game code:**
  - fn_8021067C only evaluates an entry's condition. fn_80210550 starts the entry.
  - fn_80210550 sets the lock 0x8030E714 before it looks the entry up, so a missing entry leaves the lock stuck at 1.
  - So always call the condition check first.
- **Cost:** with no save states, each id needs a Continue from a card copy (about 27 s) or a re-warp.
  - So aim it at mod maps (as part of T6) plus a sample of vanilla maps per story part.
  - Derive the vanilla "who says what" table statically with tools/sct.py.
- **Mutation:** an entry with its RET removed must report "stuck". Treat the first vanilla table as a first bless: open the frames before pinning it.

*M–L · T6b, after T6, M4, M7b · Messages can be read statically, so X8 isn't required.*

**Pad scripts that wait on a condition.** Pad scripts are keyed to frame numbers, and disc loads run on the wall clock, so scripts drift (PLAN-60FPS-MODS.md:192; HANDOFF.md:210-219).
- **(a) A `wait ADDR==V` item** in the pad grammar, in both si.c and scenario.py.
  - The run logs the frame at which the condition held, so recordings still replay.
  - A mutated address must report an unmet wait.
- **(b) One state snapshot**, published at the safe point (the moment each frame when the port may change game memory). It holds scene, map, party HP/SP, battle actors, turn order and changed flags. P7's page, R0's log and R5 all read it.
- **(c) Optional: a control channel** in an example mod DLL.
  - Off by default; loopback only; Origin check and a token.
  - Each command is stamped into the event track.
  - Stream overlays and agent control are extras.

*(a) hours to a day; (b) S; (c) several days · T12 · Needs M3/M3b (done), M7b for warps, the event track.*

**An autopilot and a balance lab.** A policy table ("heal below 40%", "attack the weakest") fills in the party's commands. A headless sweep then fights each formation and writes one row per formation and seed: won, rounds, damage taken, SP spent. An R6 rebalance or an R3 preset then gets numbers instead of one playtest.
- **Real parties.** The party states must come from real story-point saves: S7a's part cards, or your own. The developers' part select sets story flags, not levels or gear.
- **An honest budget:**
  - One battle is about 1,800 frames.
  - A whole-game sweep is several nights per seed, so start with one dungeon.
  - Chain battles inside one process, and run serially as an S6 job. Parallel runs wait for soak.md's S12 gate.
- **Exclusions:** leave out ship battles and fights the party is scripted to lose.
- **What the numbers mean:** a heuristic's win rate measures the heuristic. The value is the before/after comparison.
- **Done:** a rerun gives an identical table, and doubling enemy HP moves every row in the expected direction.

*L · R10, after R0, R8, K6, T5, S6, S9.*

**Let Dolphin Memory Engine attach to soa.exe.** Dolphin Memory Engine (DME), a memory scanner with a watch list, is every GameCube modder's first tool. The port lays out guest memory the way DME looks for it (main.c:990-994), so it should attach with `DME_DOLPHIN_PROCESS_NAME=soa.exe`.
- **Version:** DME 2026.04.16 or later. Older builds require a mapped 32 MB region, and the port's is a private allocation.
- **Writes:** document DME as read-only by convention. Its writes aren't in the pad recording and bypass SOA_WATCH.
- **Cheat Engine:** needs a byte-pattern scan, because the base address moves every run.
- **Minor fix:** main.c:1001 mislabels the ARAM-size word at 0x800000D0.

*S (hours, when the machine is free) · A doc page in docs/research/mods.md.*

**Hot reload of mods.** Change a mod and see the result without relaunching.
- **Worth doing on its own first (S):** always load mod.dll from a shadow copy in build/modcache, so the DLL can be rebuilt while the game runs.
- **Reload at the safe point.** A reload must:
  - reopen registration for that mod and drop its callbacks;
  - re-wire the dispatchers, which today are wired once and only for callback kinds present at boot;
  - flush the texture cache;
  - restore recorded original values before re-applying `*= k` patches;
  - log the new mod hash as an event.
- **Extend to T3 and T5 tables:** executable tables reload at the safe point, file tables at the next map load.
- **A Lua scripting host** is a separate, later L, after R1.

*S plus M · M15 · Needs a hotkey (M8 or a chord) and the event track.*

### D. Letting many mods live together

**Manifest v2.** mod.ini gains a stable id, a version, authors and `manifest = 2`. Unknown keys under a reserved prefix draw a warning instead of a refusal, and `api` becomes a minimum. Today mod.c refuses any `api` but "1" (HEAD :682), so the first API bump (M4) would refuse every existing mod.
- **Stable ids** are what X2's chunk key, recordings (`id@version:hash`) and bug reports need. Two mods with the same id are refused.
- **Later, a separate M** beside M13 and R1:
  - a `requires =` key for compiled-in sites and events;
  - `soa.exe --build-info`;
  - a mod-shipped build.txt, limited to modsites lines. A mod can't supply the native body an hle.txt line needs.

*S core · In T2 and M4's Done, before M4.*

**Options each mod declares.** mod.ini declares typed options: int range, bool, enum, string, seed.
- Values live in soa.ini under the mod's id.
- patches.txt substitutes `${name}`, and DLLs read options through appended API calls.
- M8 draws each mod's settings page with no per-mod UI code.

Nearly every comfort and combat slice is a slider or a preset.
- **The encounter byte:** its range is 0..127 in byte units, because the game sign-extends it and 128-254 turn encounters off. Declare byte units or allow a scale factor.
- **Widths:** M6's width syntax is required, because that byte isn't word-aligned.
- **Checks ignore soa.ini**, so add an environment override (`SOA_MOD_OPT=mod.option=value`). Refuse out-of-range values.
- **P6's seed still needs a DLL**, because it is derived per map.

*M · M16, before P1's presets, P6, R3, R4 · Needs M5, M6.*

**A mod list with order and a conflict report.** Turn mods on and off and order them in settings, instead of renaming folders.
- **Today:**
  - Folder name decides the order (mod.c:814).
  - When two patches hit the same word, the later one silently wins (:878).
  - Filters chain, and the first texture provider to answer wins.
- **The fix:**
  - Refuse two mods writing the same word unless one declares `overrides`, and only when their conditions can overlap (scene=6 and scene=7 can't).
  - List what each mod patches and registers.
  - Replays keep the recorded set.
  - The page works with a pad.
- **Defer:** dependency keys and zip install.

*A day to several days · M17 · Needs M5; M8 for the page.*

**Crash and hang reports that name the mod, and a safe mode.** Today a bad pointer in a native mod is an unexplained crash, and the console text vanishes with the process.
- **Log file first.** Write the log to a file as the base layer.
- **Guard each callback.** Wrap each callback in `__try/__except` and name the mod from g_cur_mod, which is already set around every dispatch. Also check the buffer a texture provider hands back.
- **Crash file:** port commit, build level, DOL SHA-1, mod list, the last log lines and a guest backtrace.
- **Hang reporter.** Add one for windowed play (the watchdog is off there, main.c:502) that names the running mod and writes the crash file.
- **Safe mode:** `mods = off` already exists; add a pad button held at boot.
- **Stop and name, never continue half-done,** at sites that run inside the game: X1 thunks, R1 events, X2 save hooks.

*M · M3d; a status list as an M8 bullet.*

**Content ids claimed by name, not by fixed number.** A mod names what it needs (`flag bounty.accepted`), and the loader assigns numbers into a local mods.lock. Otherwise two authors who never met both take flag 8,192 and can never be loaded together, and those numbers end up in players' saves.
- **Start small (S):** the lock, plus each mod's name-to-number table written into its X2 chunk from the first release. Remapping on load comes later.
- **Rules for numbers:**
  - Never reuse flag numbers.
  - Small pools (6 weapons, 3 items, 16 ship stages) are freed with a warning.
  - Enemy ids stay fixed claims per map, because the id picks the model.
- **Vanilla re-saves:** a vanilla or Dolphin re-save wipes the table but keeps the flags, so fall back to the local lock and warn.
- **T2's Done becomes:** two independently written mods both load, and a save moved to another install reads its flag back.

*S core, M remap · Amends T2, T4, X2.*

**Settings and hotkeys in recordings (rule 6's event track).** Rule 6 (PLAN-GAMEPLAY-MODS.md:60) says everything that changes the game is recorded, but nothing builds it. A recording made on Hard would replay on Easy without a word.
- **Record the settings:** give each game-changing entry in settings.c's k_settings table a "recorded" flag, and build the `# config` line from that table.
- **Event lines:** `@frame kind key=value` lines for hotkeys, chords, overlay actions and mid-run setting changes.
  - On replay they go to M8's safe-point queue.
  - Older readers skip them.
- **A strict switch** for soak.py, R0 and T6 that refuses a mismatch; today it only warns (si.c:563-568).
- **Done:**
  - a Hard recording is refused on Easy under the strict switch;
  - a mid-run turbo toggle replays at the same frame;
  - dropping one event line makes the replay diverge.

*Days for the event lines; hours for the rest · M8 Done plus a rule in M5 · P2 depends on it.*

**Mods in CI and in the nightly.**
- **Now:**
  - A compile-time offsetof check for every SoaModApi member. Inserting a member mid-table would silently break every DLL today.
  - A DLL built against a frozen v1 header, loaded on the current port.
  - A pytest that loads every shipped mod folder through the real loader.
- **Later, a mods-on set of S6 nightly jobs:** the comfort pack plus one content mod, and every mod's T6 check, each on its own card copy.

*S now, then S6 jobs · Extends M3/M4 tests and S6.*

**A CPU budget for mods.** Turbo needs a whole frame inside 16.7 ms, and the game already takes 11.9 ms median and 18.2 ms at worst.
- **Measure:**
  - Time every mod callback and report total, p99 and max per mod.
  - Compare CPU seconds with mods on and off at the title, which catches a mod thread undoing H11's cut from 8.8 cores to 1.2.
  - Add a budget line to the Done lists of R1, X5, X6, P7 and P8.
- **Venue:** measure in live runs; replays don't run game-thread callbacks.
- **Watch these:**
  - X5's decoding runs on the game thread (dsp.c:222).
  - P8's first-sight texture load is exactly the rare hitch p99 hides, so report the max.

*S · Extends M13; checked in S6.*

**A trust boundary for native mods and the phone page.** A mod.dll runs with the port's full rights, and you will be offered community DLLs.
- **A native-code notice.** Show a one-time notice on first load and whenever the DLL's hash changes; use SHA-256 over the bytes actually loaded. Headless runs log and refuse, and never prompt.
- **Safer DLL search flags.** Add LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | DEFAULT_DIRS. That takes minutes.
- **P7's phone page:**
  - off by default, and loopback-only unless you opt in with a token;
  - it serves a snapshot taken at the safe point, and nothing can write through it.
- **Malformed-file tests** only for hand-written decoders, such as P8's DDS/BC7. Label data-only mods "no native code", not "safe".

*S · Amends M3, M5, P7, P8, X5.*

**Mod packages that never carry the game's bytes.** Without a format, the first community mods will be ISO-style file replacements, and a shared T7 output would redistribute Sega's data.
- **`tools/mod.py pack`:**
  - zips a mod folder with a hash manifest and strips build leftovers;
  - refuses the guard's suffixes and any file matching your extracted/ files.
- **Compare after decompressing.** Most disc files are AKLZ-compressed, and a recompressed copy would otherwise slip through.
- **Deltas in T1.** T1 accepts a binary delta against the player's own file. Decide this before T1 lands.
- **T7's output is local-only.**
- **Native mods:** ship the source and build it on the player's machine with `/Brepro`, a flag that makes the build reproducible.
- **Where to share:** GameBanana's existing Skies of Arcadia Legends hub (games/18776), with a PC-port category.

*M · T13, with T1's delta option decided now · Needs T10 and the native-code notice.*

### E. The handheld as a player's device

**A first run that needs no terminal.**
- **Today,** a double-click, or a launch from Steam, Playnite or Armoury Crate:
  - starts in gen\ and can't find extracted\;
  - runs headless, with rendering off;
  - opens a new blank card under gen\build\cards (exi.c:90), so your saves look gone.
- **M5 amendment (hours):**
  - Resolve every path against soa.ini's folder.
  - Default to a rendered window when soa.ini exists.
  - Hide the console.
  - Done: a launch from a front end with no arguments boots rendered, on the same card.
- **PLAN.md G3, "A player's first run" (L):**
  - A .cmd or Python setup that offers winget for Python 3.14 and the VS Build Tools, then extracts, compiles and runs the self test.
  - extract.py names European and Japanese discs as unsupported instead of suggesting `--force`, which also waives the DOL check (extract.py:55).
  - It recognises NKit, GCZ, WIA and CISO images and points at Dolphin's Convert File.
  - A "dump your own disc" page.
- **The menu** is M8's overlay, not a separate program.
- **Signing isn't needed:** a locally built exe carries no download mark.
- **Replace "master volume"** with a setting that ignores the pad and mutes audio while the window is unfocused.

*Hours plus L · M5 amendment and PLAN.md G3 · Needs M5, M8.*

**Every port action from the gamepad.** The handheld has no keyboard, yet M8, P2 and P9 are keyboard hotkeys.
- **Chords on buttons the game never sees** (LB, View, the stick clicks):
  - Detect them in window.c and si.c. pad_filter can't see them, because it only gets the 12 GameCube buttons (si.c:715).
  - While the overlay is open, withhold d-pad, A and B from the game before they're recorded.
- **Use the first connected XInput slot**, not always slot 0.
- **Remapping and presets** go in M5, with hold-to-toggle.
- **SDL3 for other pads** is your decision; see section 3.

*S for chords and the slot; M for remapping · Amends M8, P2, M5, window.c.*

**Rumble.** The game has a Rumble option and drives the motor: rdt_vibrate calls PADControlMotor, which writes OUTBUF bits 0-1. The port stores those bits and ignores them (si.c:869). Nothing calls XInputSetState.
- **Wiring:**
  - Hook the change in si_write's OUTBUF case.
  - Map channel 0 to XInput pad 0.
  - Stop the motor on pause, focus loss and exit.
  - Keep it off headless and during replays.
- **Strength:** the game only sends on or off, so a strength setting just scales the motor speed.
- **Done:** with the in-game option off, those bits never become 1.

*S (hours) · M18 · Plus an M5 key.*

**Fullscreen, and a window that fits a 7-8 inch screen.** The window is a fixed 1280×960, can't be resized and isn't DPI-aware. At Windows' 150-200% scaling it doesn't fit, most likely squashed or cut off ([I]). There is no fullscreen at all.
- **First part, before H8, relink only:**
  - per-monitor DPI awareness and a resizable window;
  - borderless fullscreen on Alt+Enter, F11 or a chord;
  - letterboxing, and a hidden cursor.
- **Follow-ups:**
  - fullscreen and fit keys in M5;
  - a sharp-bilinear filter in P5;
  - H9 rows for 144 Hz (offer 60) and VRR panels;
  - M10's aspect as a parameter (16:9 or 16:10).
- **Done:** frame hashes and replay unchanged, and you confirm it on the device.

*S for the first part, M overall · H19 plus amendments.*

**Sleep, pause, and a game clock that never jumps.**
- **The problem:**
  - Game time follows the UTC clock (hle.c:283-297), so it keeps running through sleep and can step.
  - Changing speed mid-run (P4) makes it jump, backwards when slowing.
  - After resume, the audio catches up block by block with no cap.
- **The fix:**
  - Base the clock on QueryPerformanceCounter and re-anchor it on every speed change.
  - Count any wall-clock jump over about 250 ms as paused time. Sleep notifications are unreliable under Modern Standby.
  - Cap the audio catch-up.
  - Pause at the safe point.
- **Test:** a simulated suspend (SOA_STALL) advances game time by less than about 1 s.
- **Play time is already safe:** its timer skips missed periods, so don't test that.

*M · M19, before P4's run-time switch · Inert headless.*

**A power line in every run report.** The plans ask you to note the power mode by hand. Instead, write a `[power]` line automatically:
- AC or battery, and the battery percentage;
- the active power plan's name;
- mWh used, when on battery.

Drop the idea of an automatic battery profile: presents already top out at 30. Energy per drawn frame is also an input to your GPU-backend decision, which is the only change likely to cut drain by a lot.

*S · H20.*

**Faster loads, but measure first.** Turbo doesn't shorten loads, so this is the only lever. The win may be small:
- the modelled seek is already 6 ms, against about 128 ms on real hardware;
- a battle loads about 0.75 MB;
- expect at most about 1 s saved per battle.

- **Go/no-go:** split load time into disc-busy time and decompression, and drop the idea if disc-busy is small.
- **If it ships:**
  - scale only the transfer and seek terms (dvd.c:149), with a floor;
  - soak.py must learn to catch the game's "memFree Error" message, which it misses today;
  - prove that check with a mutated log.

*S · P13 · Needs S1, S3.*

**Rules for turbo, presenting, interpolation and injected draws.** Nothing says how these combine, so turbo with interpolation on would be held back or doubled, and X6's markers would judder.
- **While the tick is unlocked:**
  - present each frame at the next vblank;
  - interpolate nothing;
  - repeat a frame at a switch, and switch only at the safe point.
- **M11's frame skip** still runs the game's copies to texture (gxr.c:1598, not :1534). Its Done opens a battle PNG taken right after a skipped frame.
- **X6's injected draws** need a stable match key, so interpolation treats them like the game's own.

*S (lines in Done lists) · H9, H17b, P2, M11, X6.*

### F. Sharing the port, and past Windows

**Decide how the port reaches other players.** SPEC.md:26 and :44-48 already rule out a prebuilt exe, because it would carry the translated game. The missing option is a one-step build on the player's machine with a compiler the project is allowed to ship.
- **Compilers:**
  - clang-cl still needs Microsoft's non-redistributable headers and libraries.
  - Only zig cc or llvm-mingw can be shipped.
- **The runtime has MSVC-only code** (`__cpuid`, `__declspec(thread)`, `#pragma comment(lib)`). Off MSVC, aram.c:160-172 silently ignores the disc path.
- **Floating point:**
  - Pass `-ffp-contract=off` explicitly.
  - The translator emits `fma()` (emit.py:147, :156), so add an exact-rounding self-test case before trusting replay.
  - The mutation build needs `-mfma` to be able to fail.
- **Timing:** write the decision now; do the compiler spike when there is a mod worth sharing.

*M · PLAN.md G4 · The spike needs your machine.*

**Build identity, a stale-link guard, and bug reports free of game data.** After a cpu.h edit, a relink "succeeds with no diagnostic, and the binary is wrong" (CLAUDE.md).
- **Stale-link guard:**
  - recompile.py re-emits every chunk on every run, so a stamp written at translation time would be refreshed by `--link` itself.
  - Write gen/build_inputs.txt only after a successful `--compile`. It records hashes of the emitted C, cpu.h, and the optimisation level.
  - `--link` then rebuilds changed chunks, and refuses on a cpu.h or level change.
  - Mutation: edit cpu.h and `--link` refuses.
- **Version line:** print it at startup, and put it in recordings as a separate header line. The config line is string-compared on replay.
- **Issue template:** say what to attach, and never to attach cards, FIFO captures, frames or WAVs publicly.
- **Doc fixes:** README.md:100-103 and CONTRIBUTING.md:30-31 wrongly say runtime edits only need `--link`.

*M · PLAN.md G5.*

**Licences for mods, templates and borrowed knowledge.** T4 plans to adopt SALSA's operand layouts, and T3/T5 ALX's vocabulary. SALSA, ALX, SPICE and SKEWER are GPL-3.0, and SOARandomizer has no licence at all.
- **Get MIT detected:** move LICENSE:23-25 into NOTICE so GitHub detects MIT; it reports "other" today. Also fix ARCHITECTURE.md:506-510, which still says no LICENSE exists.
- **Classify folders in NOTICE:**
  - mods/ goes with config/, since it holds game addresses;
  - examples/ is MIT;
  - config/scenarios/ is original work.
- **Templates:** put soa_mod.h and the examples under 0BSD or CC0.
- **Rule:** community sources are leads. Re-derive and cite from the DOL; never copy code or table files.
  - T4 becomes "re-derived from the DOL's handler table, with SALSA as a cross-check". They agree on 265 of 266.
  - The rule covers :373, :383, :395, :428 and :597.

*S · PLAN.md G6 · Your call on the GPL route.*

**The name, the trademark, and a takedown runbook.** The public repository is named after Sega's trademark, and Sega filed new Skies of Arcadia marks in January 2025. re3 and reVC were taken down, then sued.
- **Now:**
  - Pick a name that isn't the trademark, with "for Skies of Arcadia Legends" as a descriptor.
  - Rename the repo, README.md:1 and the window title (window.c:115, relink only).
  - No Sega logos or art, and no money.
  - Keep full-history git bundles off GitHub.
  - Write counter-notice criteria and a remaster trigger.
- **Later, only if needed (L):** split into an engine repo and a game repo. That is harder than it sounds: 18 of the 25 runtime files hold game addresses.
- **A rename only lowers trademark exposure.** Copyright in src/ is the bigger exposure.

*S now, L later · PLAN.md G7, plus a SPEC §2 rule.*

**Close the guard's gaps, and keep game text out of mods.** The guard refuses binary file types but can't see game text: a disassembled script is the game's dialogue, and a whole enemy file as TSV is its data.
- **Rule 3 addition:** T4 and T5 mods in the repo hold only edits keyed by entry or id, or wholly new entries. Full dumps go to build/.
- **Content check in T0:**
  - It refuses dump headers and full-column enemy tables, with a mutation test.
- **Suffixes and directories:**
  - Add compressed audio (.ogg .flac .mp3 .opus).
  - Add `out` to the forbidden directories.
  - Update CI's regex copy (ci.yml:34) and test_guard.
- **Stale counts:** CLAUDE.md says 34 refused extensions; TESTING.md:148 and the check skill still say 28.

*S · T0 and rule 3 · Your call on name tables and art sources.*

**Keep Linux, Steam Deck and ARM possible.** SPEC.md:19 promises not to rule them out, but H8's DXGI presenter and H15d's AVX2 build flag would.
- **Now (S):**
  - H8 keeps the current GDI path as a fallback.
  - H15d's SIMD goes behind an x64 guard with a scalar path.
  - A Proton smoke test: copy soa.exe to a Steam Deck and run the self test.
  - A clang compile-only CI job on Linux.
- **Parked (XL):** an OS layer, ARM64, native Linux and macOS. Any non-MSVC build must turn off fused multiply-adds.

*S now, XL parked · Nothing here is on your Windows path.*

## 2. Corrections to the plan

**The race seed misses the reseed at battle start (P6, K6, R0).**
- **The fault:** the game reseeds its random-number generator from the CPU clock (OSGetTick) at three places:
  - every field load (0x801012AC/B0);
  - twice at battle start, in fn_8000A118 (0x8000A1CC-D8).

  P6 pins only the first, so "equal seed, equal damage" can't hold.
- **The fix is hours and relink-only, in milestone 1:**
  - OSGetTick is emitted as `guest_timebase_lo` (emit.py:528; hle.c:451).
  - Pin it there when `s->lr` is 0x8000A1D0, 0x8000A1D8 or 0x801012B0 and `s->pc == 0x8023851C`.
  - No hle.txt line and no retranslation.
- **P6's Done:**
  - one reseed per field load, including the reload after a battle, and two per battle start, each taking the pinned value;
  - equal seeds give the same first-round order and damage;
  - a different seed differs.
- **K6 becomes:** with all three reseeds pinned and commands written when phase 1 begins (0x8034733C == 1), do two runs give identical damage logs? If not, name the per-frame random consumer. The D4 fallback stays: disc completions still follow the wall clock, and there are 481 rand() call sites.
- **Also:**
  - add "and at every battle start" to PLAN-60FPS-MODS.md:721;
  - give P6 a milestone-1 check (reseeds counted and pinned), with the equal-damage check after R0.

**R1's events would fire every frame, and R4's "No KO" misses poison and Unconscious.**
- **Rewards:** phase 7 (fn_8006F4B0) runs every frame, and pays out once, in sub-state 2.
  - Fire on_rewards once, when the wrapper finds 0x80347338 == 2, before calling the original. As written, a ×2 EXP boost compounds.
  - Declare magic EXP as s8 and clamp it to 127.
- **Other events:**
  - Fire on_round_end after fn_8006FD6C, only when the sub-state went from 0 to nonzero.
  - Fire on_turn_order when the phase leaves 2.
  - Fix battle-system.md:556 to match.
- **R4's Done:**
  - ×2 gives exactly twice vanilla's ctx+48/+52. Each member's share is `(2·exp + alive − 1)/alive`, so it is not exactly 2×.
  - Keep "×1 identical to off" as a second check.
  - R2's Burn ticks exactly once per round.
- **"No KO"** keeps the damage clamp and adds two paths:
  - Poison: when 0x80347338 becomes 10, clear the party bits of 0x80346BE8 and set those members' HP to 1.
  - Unconscious (effect 5, fn_8002DA88, which zeroes HP) needs a cancel flag in on_effect.
  - Done: a forced lethal poison tick and an applied effect 5 leave everyone standing, and every other logged number is unchanged.

**"Content-mod saves load in vanilla and Dolphin" (contract :52) doesn't hold yet (X2).**
- **Why:** a Continue skips the map resolver and opens `/field/aNNNx.mld` by name (save-load.md:130). On a vanilla disc a mod map's file isn't there. A black screen or hang is inferred, not run.
- **The fix, at the snapshot hook 0x801A4670:**
  - Write the mod's declared vanilla fallback into the map word and letter (+5808/+5812) and the position (+5864..+5916).
  - Keep the real location in the mod's chunk, and restore it at fn_801A4354's entry.
  - The save name follows the existing B[44] rule. Don't patch the image at 0x801A4334, which runs after the checksum.
- **Placeholder gear still loads in vanilla** as a "ダミー" (dummy) record, so "state ignored" is simply false for gear. Either swap in a substitute, or reword the contract (section 3).
- **First priority, hours:** pass unloaded mods' chunks through unchanged. Today, turning a mod off and saving loses its state.
- **Then:**
  - record which flags each mod owns, and report on load when they're set but no container is present;
  - add the same fallback, or a refusal, for M7a's save-now on maps like a116c, which would hit the camera trap in Dolphin.
- **N5's Done has no save step.** Add a matrix: modded save, then vanilla/Dolphin load, then vanilla save, then modded load.

*S–M on top of X2.*

**About a dozen Done criteria can't fail.**
- **Two live runs are not comparable.** Two unmodded title runs differed on 22 of 40 hashes (FINDINGS.md:1984), yet these criteria assume equality across two live runs:
  - PLAN-GAMEPLAY-MODS.md: P1 :234, P6 :282, R0 :444, R1 :467, R4 :497, R6 :511, X5 :659;
  - PLAN-60FPS-MODS.md: H9 :271, H17a :380-381, M8 :575;
  - M3 :503, which is simply stale.

  Rewrite each as a replay check, a same-run check, or an invariant with a mutation, or mark it as waiting on K6/D4. For P1, use contrasts: 0% fights nothing.
- **P5 and M8:**
  - SOA_HASH is taken from g_screen before `present()`. Headless, a presenter option is never exercised; windowed, the run is live.
  - P5's before/after PNGs also read g_screen.
  - Add a capture after present, and make each filter a pure function with a unit test on a synthetic image (gamma 1.0 changes nothing, 2.2 changes pixels). Don't make P5 wait for H8.
- **R0/R1 "doubling doubles every hit":**
  - It passes with zero hits and fails on knock-outs.
  - Log (original, returned) per call, assert `returned == min(2·orig, 9999)`, and require N nonzero hits.
  - The first-hit check is a range: ±2.5% random, element, Guard, criticals, and Vyse's +26.
- **R5:** the overlay and the log both read actor+20, so pair the check with an opened frame.
- **P7's chest count:**
  - No screen shows it. Use op-154 hits in a traced run, plus pokes across the 90% and 100% thresholds.
  - Those thresholds are ANDed with 0x80310A4F==88 (for ≥90), and with 0x80310A88==8 plus a bit at 0x80310B84 (for =100). Set those too, or the mutation itself can't fail.
- **N9:** add an independent reachability checker, plus a mutation that removes a key item and must be reported unbeatable.

*Hours · One slice beside "After K6".*

**The batched retranslation never runs the code it changes (R1+X2+X8).**
- **Why:** `title --check` is 2,000 frames of boot and title, and replays run no game code. Neither reaches a battle, a save or a load. R1's pass-through twin compares a wrapper with itself.
- **Add:**
  - a call count per changed function in the run report; zero calls means "did not test what it says", as S1 does;
  - a mods-off comparison against the build from before the retranslation: R0's log identical, and the save image from a new save-then-Continue scenario on a card copy byte-identical (cardwrite.scn only formats a blank card), plus a dialogue frame for X8;
  - mutations in R1's own Done for the four events nothing later tests: on_turn_order, on_spirit_gain, on_heal, on_enemy_action.

**X4's "more than 4 enemy kinds" is a hook, not a buffer redirect; T5 needs refusals.**
- **The real mechanism:**
  - The limit is a memo local to fn_80077428: 4 × s16 at 0x80347388, plus a stack array, bounded by the immediate `cmpi r25,4` at 0x80077B34.
  - Its only defect is the garbage r4 passed at `bl fn_800770B8` (0x80077B58).
  - Fix it in R1's on_enemy_spawn wrapper (lr 0x80077B5C, r25 ≥ 4 → r4 = fn_80077B88(r24)) or with a hooks.txt entry at 0x80077B58. Report a miss rather than silently using the fallback record.
  - It needs no Track F work, unless a K spike finds a fixed 4-slot table further down.
- **X4's Done adds:**
  - battles with 4 or fewer ids identical to off;
  - 5-8 distinct models actually load;
  - battle-heap high-water marks.
- **Line fixes:** :31 and :156.
- **T5 refuses:**
  - an id missing from its own file's directory (setup would otherwise build from base + 684·u32[base+4]);
  - more than 84 directory pairs;
  - more than 7 enemies in an event, since an eighth overlaps initiative, defeat and escape;
  - a summoned id from another file;
  - .ect weights that don't sum to 100 (T5 or N2 must own .ect).
- **T5 warns** on event ids ≥ 248, which use the default voice bank.
- **Record sizes:** records are 524 or 620 bytes (335 of 736 are 620). Fix :94 and :395.

**The milestone table breaks its own dependencies.**
- **Order:**
  - R6 needs T5 but sits a milestone earlier: move T5 to milestone 3.
  - Move X3 (a day, relink) into milestone 4, so the reward weapon ships with its description.
  - Place, or mark unscheduled: K2, K3, K4, K5, P8, P9, T7, R7, R8, R9, X9.
- **Batching:** X4 and X8 are milestone 5 but "batched" into milestone 2's retranslation. Make two batches (R1+X2, then X4+X8), or drop cross-milestone batching; a retranslation is about two minutes plus the self test.
- **The first three slices:**
  - P1 can ship today as a mod.dll (`write8` from on_frame_end, gated on scene 6; hold-B through pad_filter). It can't be a patches.txt line: those write whole aligned words, and 0x8030B7AD isn't aligned.
  - P1's Done cites P6's seed, so build them together; both are hours.
  - R0 can start, but can't reach its Done before K6 and R1.
  - X1 has no user before milestone 5.
  - Suggested opening: P1 with P6 (battle seed included), then T1, then R0; X1 later.
- **Encore:** before T7's owner check promises Encore "imports and boots", diff its `.text` separately from its data (an hour).

**The encounter slider and turbo duplicate M6 and M11, and their checks measure the wrong thing.**
- **Encounter slider (P1):**
  - Make P1 the only player-facing encounter setting. It also covers the world map, whose code rejoins at 0x800C2000; M6 refuses map 99.
  - Multiply the game's own value rather than overwrite it, which would cancel equipped accessories: base = the game's last write (−1 counts as 50), clamped to 0..127.
  - The same risk sits in M6's `*= k`.
- **P1's Done:**
  - With S3's accelerator, every nonzero setting fights on the first step.
  - Instead, either compare the step count at the first battle with the same seed and pad, or poke the step counter to about 480, where the odds are about 0.9%, 1.9% and 3.75% per step.
  - Add a map-99 (sky) run.
- **Turbo (P2):**
  - Merge P2 into M11 as one tick-unlock setting, and keep "after H13".
  - Drawn, the opening and ship battles gain almost nothing (18.9 vs 19.3 fps; 25.5 vs 26.0), and battles gain about 1.6×. "About 60 a second" contradicts FINDINGS.md:1644-1646.
  - Measure drawn today with `SOA_SNAP=0`; SOA_RASTER_ALL doesn't exist yet.
- **Fast boot (P4):**
  - "53 s" is the scripts' first START at frame 1600, not a measured arrival of the title.
  - Measure when the title appears.
  - A windowed fast boot must also skip drawing.

**K1 can't prove the flag range unused, and R2's "K confirms" points at a slice that doesn't exist.**
- **Why:**
  - The watch prints only 201 hits, and the New Game clear and a save restore each use them all in one frame.
  - Native memcpy and memset never reach the watch.
  - K1's window stops at flag 19,455.
- **K1's method:**
  - Watch T2's range (`SOA_WATCH=0x80310F3C,0x958`, flags 8,192-27,327), with SOA_WATCH_FROM set past the clear and the restore.
  - A mod that diffs the flag block at each safe point is the stronger detector.
  - Positive control: poke a flag ≥ 8,192 and see it reported.
  - Scan saved blocks, including late-game saves.
- **K12 (free status bits):**
  - List every mask the battle code tests on actor+28, and name the unidentified bits (0x2, 0x20000, 0x800000, 0x01000000).
  - Point R2 at K12.
  - The save question is closed: the end-of-battle write-back never copies actor+28.

**Smaller fixes.**
- **R1:** reword "Moved to M13 sites when M13 lands" to "use M13 if it has landed, otherwise hle.txt; no migration planned". X2's and X8's sites sit inside functions, and M13 can't express them.
- **X3 says "the rest stays a tripwire":** mem_guard commits the whole tail on the first stray access (main.c:593-596). Also, the heap-4 option and the mod window can't both have the tail.
- **M12's text-speed bullet** (PLAN-60FPS-MODS.md:611) is answered by content-systems.md:130.
- **PLAN.md:644-647 and soak.md:244** name an RTC pin as the fix for run-to-run differences. The game never reads the RTC counter; its seeds and save timestamps come from the timebase.
- **T8:** note that SPICE already exports MLD models to Blender, so T8 only needs the writer.
- **M9:** note that M3c's texture-provider API has already frozen the texture hash with no version field. P8 can compute Dolphin's names inside the renderer, once per decode.
- **Section C, "Photo mode waits on K4":** only a live, in-game photo mode waits on K4.

## 3. Questions only you can answer

1. **Which handheld, exactly?** A ROG Ally (120 Hz, variable refresh) and a Legion Go (144/60 Hz, 2560×1600) need different fullscreen and refresh work.
2. **The save contract:** build the vanilla-safe fallback (mod maps save a vanilla location; placeholder gear swaps to a substitute), or reword the contract honestly?
3. **Distribution:** stay source-only, or offer a one-step build with a compiler the project can ship? And do you want a separate launcher, or is M8's overlay enough (PLAN-60FPS-MODS.md:521)?
4. **GPL knowledge:** re-derive everything from the DOL (feasible; SALSA's layouts agree on 265 of 266 handlers), or ask the ALX and SALSA authors for permission or a dual licence? Asking would also open a collaboration.
5. **Game-data boundaries:** does a text table of enemy names (R5; the game only shows names as pictures) count as game data? Do original Blender sources for new art belong in the repo, which decides whether to refuse 3D-export files?
6. **Non-XInput pads:** reopen "no third-party runtime dependency" (SPEC.md:463) for SDL3, or use Windows.Gaming.Input or Steam Input?
7. **N3's bounty:** script-only, as recommended, or extend the Wanted List later?
8. **Name and posture:** rename the project now? What should happen if Sega announces a remaster?
9. **New Game+:** offer it from any save (simpler), or only after beating the game, which needs a record kept outside the save?
10. **Companion and streaming:** do you want a phone companion or stream overlays? That decides whether the control channel is built beyond condition waits.
11. **Which "Encore"?** The evidence found Taikocuya's SOALE rebalance; is that the mod you mean?

## 4. Considered and dropped

- **Moving R1/X2/X8's wrappers to M13 first:** only R1's 11 wrappers would move, X2's and X8's sites sit inside functions M13 can't wrap, and hle.txt wrappers already keep interrupt polls. What's left is a one-line fix (section 2).
- **Settling the texture-pack key in the mod API before P8:** P8 and M9 are port features that can compute Dolphin's names inside the renderer, and the API is append-only, so nothing is blocked. What's left is a note in M9.
- **One address map for the 8 MB tail, and heap addresses moving with content mods:** heap addresses don't move when the file table grows (fixed arena start, allocation from low addresses), page guards can't flag stores into committed windows, and thunks need no memory. Two small X3 notes remain (section 2).
- **Player-data folder and card safety:** exe-relative card paths are folded into the first-run item, and "a torn write loses all seven saves" was wrong, because the card keeps two copies of its directory and allocation table. Two cheap pieces are still worth about an hour each if you want them back: a single-instance lock inside soa.exe (two live copies can overwrite each other's saves), and a quit guard during the game's delete-then-create save.
- **AI-content disclosure on mod sites:** the game has no Nexus page, the port can't be uploaded as a release, and every commit trailer already discloses. A README sentence whenever you like covers it.
- **Frame-to-glTF scene ripper:** SPICE already exports MLDs to Blender, a captured frame lacks the camera matrix until K4, and it serves milestone 6, which needs an artist.
- **Speedrun kit:** the leaderboards are GameCube runs with loads timed in, so port runs wouldn't be accepted; verifying runs needs D4; and pinning the RTC would pin nothing the game reads.
- **Lost-content museum:** all 82 placeholder item records are "ダミー" (dummy) entries, most spare boss ids are variants of bosses you fight, reaching the rest needs new records, and M7b and P9 already cover visiting. It's a curiosity, off your goals.