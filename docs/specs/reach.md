# Reach: scripted runs into what no run has reached

PLAN-NEXT §0, the PC session's step 2 (D-37): "Scripted runs into what no run has reached, fixing what breaks,
each with a FINDINGS entry. Its first slice writes down the runs and the invariants each must hold before any is
run." This is that slice. Written 2026-10-14 from four read-only investigations of the tree, with each fact this
plan acts on checked again in the code or a log, marked [V], or left as a doc's claim, [D], or an inference, [I].

The owner's words for the goal: the PC port "working 100%". Every run below goes where no run has gone, so each
can find a defect the corpus, the replay and the soaks cannot. A run that finds nothing is a result too, but only
when its invariants could have failed: each section names the run that proves its check can fail.

## 0. What every run is held to

**The base invariants** are `soak.py check`'s (tools/soak.py:564 `judge`, over `scenario.py` `check_report` at :620)
[V]: the run exits 0 at its frame limit; no `[mmio!]`; no unknown FIFO bytes; no bad vertex references; no
`[trap]`, `[spin]`, `[unimplemented]` or `[watchdog]`; no `[mem]` line; the pad and poke lists understood; the
card one the game accepts; the landing map the card names. Every run is traced (`SOA_TRACE=1`), strict
(`SOA_STRICT=1`), has its own card copy and its own `SOA_FRAMES_DIR`, and runs with `SOA_SETTINGS=0`.

**The renderer's questions.** `soak.py check` reports every `[gxr]` warning as a question, never a failure
(soak.py:296-303) [V]. Eleven of the thirteen warn-once tripwires in `runtime/gxr.c` (:285-380, :2637, :2749,
:3093, :3149) have never fired in any log here; BP_MASK and LINEPTWIDTH have, both in part G [V]. Here a tripwire
that fires for the first time is not a question: it is a finding, and the frame it fired in is captured
(`SOA_FIFO_DUMP` into `build/fifo-new`, never `build/fifo`) and looked at before the run is called a pass. Draw
tripwires fire only on rasterized frames (gxr.c:274-279), so a run that is to watch them draws every frame
(`SOA_RENDER=1` with no `SOA_SNAP` skipping) or says it did not.

**One `soa.exe` at a time** (CLAUDE.md). A 33,500-frame job takes about 19 minutes here (`build/m6`, 2026-10-14).

## 1. U0: what the runs need first

The checks below need four things the tree lacks [V: no such code today]:

1. **`soak.py check --expect-flag N[=0|1]`**, read from `[peek]` lines of the flag's word at the run's end, so a
   story claim is a flag, not a map name. Flag *n* is bit `n & 31`, from the least significant, of
   `0x80310B3C + 4*(n>>5)` (`801F6D38`-`801F6D44`, story-flags.md:14, 50) [V].
2. **Effect packages counted:** `check` lists every `/BEFF/` name a run loaded (`LoadStart ... "/BEFF/X.MLK"` and
   `LoadCrew ... "/BEFF/" "X.MLD"`) [V: the two forms in `build/scenario-fairbattle.log`], and a `--beff-seen FILE`
   ledger accumulates them across runs. Today's logs hold 19 distinct names of the disc's 576 [V: 546 `.mlk` and
   30 `.mld` in `extracted/beff`].
3. **Ship battles counted:** a 5xx stage's load starts one; it ends at `/field/HRS_BEND.BIN` (the results
   screen, ship-worldmap.md:141-149 [D]; the teardown's `cmpi 2` and store to 0x80347280 [V gen]), at the
   caller's map, or at `a090a`. `soak.py` counts `/battle/stsicon.mld` only, so a ship battle reads as 0 battles
   today (:290) [V], and its map regex misses `sora02` and `sbek` (:289) [V].
4. **The lab mod** (`examples/mods/lab`), a native mod on the existing API (`runtime/soa_mod.h`: `read32`,
   `on_safe_point`, `on_map_loaded`, `call_guest`) [V], driven by `SOA_LAB`:
   - `SOA_LAB=peek:<frame>:<base>[+off...]`: a pointer chain, logged, which `SOA_PEEK` cannot follow
     (main.c:815-822 reads fixed words) [V]: the battle actor's HP (`0x80309DE4[slot]` +20, battle-system.md:19,
     93 [D]) and the battle inventory (`*0x80347390 + 56`, [V disasm 0x800774D0-F0]);
   - `SOA_LAB=entry:<frame>:<id>`: at the first safe point at or after the frame with no event running (flag 1087
     clear), call the game's own `fn_8021067C(id)`, the function the A press calls after its proximity scan
     (content-systems.md:75-83 [D]; to verify before use). The entry's own `LABEL` condition and gates still
     decide whether it starts. This is the player pressing A at the object without walking to it, and every
     run that uses it says so.

*Done:* `test_soak.py` holds each new verdict to a synthetic log that passes and one that fails; the lab mod's
chain read is held by a test on the fake guest (`test_mods.py`'s driver); the mutation of each (the flag bit off by
one, a ship stage with no end counted as fought, the chain read skipping a dereference) turns its test red.

**Built 2026-10-14.** `soak.py check --expect-flag N[=0|1]`, `--expect-ship-end` and `--beff-ledger PATH`, and the
`[seen]` lines for effect packages and ship battles; `examples/mods/lab` with `entry`, `peek` and `objects`, built
by `--link`, and two items the first runs showed were needed: `hold-hp:F-G`, the standing party's HP put back to
its maximum in battle (U1: A presses alone lose to the boss), and `turn:F-G:M:SEQ`, a member's first command input
of each battle played through the pad filter, with the command types logged at each phase 1 -> 2 edge (U2). Twelve
tests in `test_soak.py` and five in `test_mods.py` (passing under MSVC and llvm-mingw); six mutations, each red: the
flag's bit counted from the top, a ship stage that met the frame limit counted as ended, an effect package listed
each time it loads, the chain read skipping its dereference, `hold-hp` topping up a member who is out, and a turn
played again within its battle. The `entry` item's own
reading of the code: `fn_8021067C(id)` only evaluates the entry's `LABEL` condition (it formats `M%05d`, finds the
entry and runs `scptAnarize` on the next word); `fn_80210550(id)` starts it, refusing while `0x8030E714` is 1; the
player's scan calls the first, then the second, then stores 1 at `r13-29464` and the volume at `r13-29396`
(80117E78-80117EA0), which is what the lab does. The list it walks: head `r13-29180` (80223024), next at +48, live
while the s16 at +20 is not negative, the object id at +8.

## 2. U1: a boss battle, from the story

**The target** [V, `python tools/sct.py 116a`]: part G's card lands on `a116a` (FINDINGS:1517-1526; the card's
save block names it) with flag 303 clear [D: the boss investigation decoded the card]. Its entry `M04005` begins
`IF FLAG[303]==0` (0b7d4) and runs `BATTLE (1) (19) (33) (1)` (0b9fc): event 19, an event battle, whose record
gives enemy 141, a boss (ids of 128 and up), and the defeat rule 1, "may try again" (enemy-data.md:257-285 [D]).
The map's loop runs `IF FLAG[1858] && !FLAG[304]` (00490) into the after-scene. No boss or event battle has run in
this port (README.md:54) [V], and only kind-0 battles ever have (FINDINGS:1324) [V].

**The run:** the G card, S3's preamble (the Continue), then `SOA_LAB=entry:<after the landing>:4005`, then A every
150 frames with the `--battle` mix's wheel steps so the fight is played, not idled. Then the same with the
object reached by walking, once U4's object positions are known, which is the run that counts as played.

**Invariants**, beyond §0's:
- flag 303 goes 0 → 1 (`0x80310B60` bit `0x8000`) after the entry starts, and flag 1858 is set;
- `/battle/stsicon.mld` loads once (one battle), and the enemy is the boss's (the battle's loads named in the
  FINDINGS entry);
- a win: `PCWIN.MLK` loads, `/field/a116a.mld` loads again, flag 304 is set (`me116ag05` begins `FLAGSET 304`)
  [V sct], and no `a090a`;
- or a loss under rule 1: the "try again" state (scene state 9, battle-system.md:193 [D]) and the battle again,
  never `a090a`;
- every frame from the battle's start to the after-scene's end drawn and opened at its first frame, a frame
  mid-fight and the after-scene's first lit frame.

*Can it fail:* the same job with `entry` naming 4004 (gated by temp flag 1794) must leave flag 303 clear and
`check --expect-flag 303=1` must FAIL.

**Run 2026-10-14** (FINDINGS "Reach U1"): started by `entry` from where Vyse stood; lost three times on A presses
alone, each loss the game's "try again" (and `--expect-flag 304` FAILs on that log, the control used in place of
the 4004 job); won with `hold-hp`, flag 304 set by the after-scene, every invariant held, the frames opened. Left:
the fight entered by walking (U4's positions) and won without `hold-hp` (scripted tactics).

## 3. U2: an item used in battle

**What is known:** the wheel opens on Attack, slot 3, and slot 5 is Item; a plain press moves two slots, so a
plain `left` from Attack lands on Item (FINDINGS:732, 1209-1216, 3738) [D]; the Items tab shows only when the party
holds an item marked for battle (byte +17 bit 0x02; FINDINGS:843-846) [D]; each member takes two A presses,
command then target (FINDINGS:3733-3737) [D]. Every save card holds one Sacri Crystal (id 240, heal 500) and no
other battle item [D: decoded from four cards]. The field inventory is `0x8030BF08`, 80 words of
`{s16 id, u8 count, u8}` (story-flags.md:167-173) [D]; the battle copies it to `*0x80347390 + 56`, takes one
through `fn_80077D40`, and copies it back at the win (0x8006FC34) [V disasm, the items investigation].

**The run:** part G with the accelerator, as `build/m6/G-x1` (five battles), with Vyse's first turn scripted:
`left`, A (Item), A (the Sacri Crystal), A (target: Vyse). `SOA_COOP=1` with no second pad logs each member's
command at phase 1 → 2 (`mods/coop/mod.c:63-92`) [V].

**Invariants:** the coop line shows Vyse's command type 5 (Item) in the first battle; the lab mod's chain read of
Vyse's battle HP rises by min(500, max - HP) the turn the item resolves; `0x8030BF08` reads `0x00F001xx` before
the battle and `0xFFFF....` after the win; an effect package loads at the item's turn and is named.
*Risk on record:* a spike found "Item's and Magic's menus take A without moving on in this battle"
(FINDINGS:3740-3741), unexplained. If that recurs, it is the first defect to chase, with the menu's state words
peeked.

*Can it fail:* the same job without the scripted turn must show no type 5 and an unchanged `0x8030BF08`.

**Run 2026-10-14** (FINDINGS "Reach U2"): five presses, not four (the Items tab is its own step); member 1, Gilder
in this party, since Vyse can fall before his first input. Command type 5 logged, the crystal taken at its turn,
Gilder's HP raised to its maximum, `0x8030BF08` written back `FFFF00FF` after the win. The control: the run with
four presses, whose crystal was handed back and whose command was not 5.

## 4. U3: a ship battle fought to its end

**What is known:** the one ship battle with a part-L party (`build/scenario-sky550.log`) entered `550a` by the
opcode-210 recipe (seven pokes at frame 3300, `run_sky550.log:2`) [V] and ran under A every 150 frames until the
frame limit ended it: no fault, no hang [V log]. (Its "round 3 of 41" was the SP gauge, 3 of 41; it had stalled at
its first turn, as U3's first run shows.) No log here holds `HRS_BEND` [V grep]: no ship
battle has reached its results. The script ends one by `B[261] <= 0` (lose) or `B[262] <= 0` (win)
(battle-system.md:521-529) [D].

**The run:** the L card, the same entry, 60,000 frames, A every 150 frames; if it does not end, the ship command
grid is learned from frames and the commands scripted (battle-system.md:583 lists the player's ship input as
unknown [D]).

**Invariants:** U0's ship-battle verdict ends in a win or a loss, not the frame limit; on a win, `HRS_BEND.BIN`
loads (state 4) and the caller's map `a126a` loads after; on a loss, `a090a` or the retry by opcode 210;
`SOA_PEEK` of 0x80347280 (1 on a win, set by `fn_8012A26C`) [V gen]; the results screen's frame opened.

*Can it fail:* the 12,000-frame `sky550` log must judge "did not reach its end".

**Run 2026-10-14** (FINDINGS "Reach U3"): won, with the lab's `sturn` playing a cannon for Vyse and Focus for the
other three each turn; the results screen paid 300 Gold and four levels. The controls: the A-only run (stalled,
"unfinished") and the random-mix run (fled, "ran"), both "did not test". The results file is not in the trace; the
end is read from `0x80347280`'s peek.

## 5. U4: the story between the jump points

No run has played from one part's landing map to the next part's (FINDINGS §11) [V]. What stops a blind script:
nothing tells it where it is, presses are dropped while the game is busy, and choices need a d-pad
(FINDINGS:708-712, 1260, 1267-1271, 1454-1457) [V]; `mods/autotext` presses only on a full page, never in a choice
(mods/autotext/mod.c:17-23) [V].

**The approach**, in three steps, each its own FINDINGS entry:
1. **Where things are.** The lab mod logs, at each map load, every object with a hit volume: its id, type and
   position, from the global hit-volume list (`r13-29180`, linked at +48, content-systems.md:77 [D]). That gives
   `4005`'s place in `a116a` (U1's played run) and every map's exits (6xxx) and talks (3xxx).
2. **The entry walker.** From a part's landing, the lab mod starts, one at a time, entries whose `LABEL`
   condition is live, preferring 6xxx exits the story has opened and 3xxx/4xxx entries not yet run, with
   autotext on and a scripted first option at each choice. The game's own gates keep the story in order; the
   walker only stands in for walking. A part is reached when the next part's landing map loads and its first
   story flag is set.
3. **Played legs.** Where step 1 gives positions, a leg is walked with the stick instead, and the two runs'
   flags compared.

**Invariants:** §0's; the flags of the part's range (50 a part, story-flags.md:8 [D]) only ever set in a
legal order, read from `[watch]` on the flag words; no `a090a` the walker did not cause by a battle; each new map
loaded drawn (a black field after a load is a finding, as at FINDINGS:1351-1361); the next part's landing map.
*Can it fail:* a walker job with its entry list emptied must judge "did not reach".

**Order:** G → H first (the prison, then out; U1's boss is on it), then C → D, the shortest by flags (64 → 124)
[D card decode].

## 6. U5: effect packages, and the renderer's unfired tripwires

**The runs:** one accelerated battle soak per part card, C to L (S3's recipe with `--battle`, 33,500 frames, every
frame drawn), and U1's and U3's runs. U0's ledger counts the `/BEFF/` names; each part adds its enemies' and its
party's magic and moves.

**Invariants:** §0's; every tripwire that fires is a finding with its frame captured and modelled or answered;
the ledger grows.

**The recipe, as run on 2026-10-14:** for part P, a copy of `build/savetest/card-partP.raw`; `SOA_PAD` from
`soak.py --seed <40 + P's distance from C> --battle`; `SOA_POKE` and `SOA_PEEK` from `soak.py --pokes|--peeks
--encounter-every 600`; `SOA_MODS` naming a folder holding only `examples/mods/lab`, with `SOA_LAB=objects`;
`SOA_STRICT=1`, `SOA_TRACE=1`, `SOA_SETTINGS=0`, `SOA_RENDER=1` and no `SOA_SNAP` (every frame drawn);
`SOA_FRAMES=33500`; then `soak.py check <log> --beff-ledger build/reach/beff.json`. About 30 minutes a part here. **Not here:** forcing events by the six-word request (0x803473CC-D8). It skips every gate and
soaks must never use it (soak.md:102 [D]; soak.py:205-208 asserts it is never poked [V]); a later slice may use it
to reach packages no story run can, saying so.

## 7. Order, and what is reported to the owner

U0, then U1 and U2 (one part-G family of runs), U5's part soaks in the background between them, then U3, then U4.
Each run's FINDINGS entry names its log, its invariants with what each read, the frames opened, and what broke;
each defect is fixed in its own commit with the contract CLAUDE.md names for the files it touches.
