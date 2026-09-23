<!-- Written 2026-09-23 by a read-only research agent from the disassembly, the DOL and the
decompressed scripts; nothing here was run when it was written. Claims marked [V] were read
from quoted instructions; [I] is inference. Check a claim against a run before building on it,
and record what a run shows in docs/FINDINGS.md, not here. -->

**Findings: what the 5xx maps are, how the game gets to them, and the world map**

Everything below comes from static reads: the disassembly, the DOL, the scripts decompressed into my scratchpad with `tools/soa/aklz.py`, and the saved logs `build/scenario-sky500.log` and `build/scenario-census.log`. I did not run the game. **[V]** means I checked it against the quoted instructions or data. **[I]** means it is inference.

## 1. Scene numbers
**[V]** `fn_801DBE6C(n)` stores the scene id to `-29012(r13)` = 0x803475CC and zeroes that scene's state word at `0x80311AD4 + 4n`:
```
801DBE7C stw r3,-29012(r13) ; 801DBE80 stwx r5(=0),r4(=0x80311AD4),r0(=n*4)
```
The dispatcher is `fn_801DC288`: `cmpli r0,9 ; bgt` then a jump table at 0x802F6660.

| scene | handler | what it is |
|---|---|---|
| 0 | `fn_801DBE88`, then the scene is set to 2 | init. `fn_801DC62C` sets 0 on a reset (0x801DCAA8) |
| 1, 4, 5, 8 | 0x801DC37C | nothing; the table points at the common tail |
| 2 | loads `/sound/s1000000` and `/sound/b7000000.mlt`; if 0x803475D4==0 sets map 002/'a'; then scene 3 | boot to title |
| 3 | `fn_801D77B8` + `fn_80228A20` (state 0x80311AE0, table 0x802F91AC, 19 states) | title and menus. State 15 is `fn_80228B74` = "ME201A.sct" + scene 6 (New Game); states 7 and 8 are ME299A/ME297A |
| 6 | `fn_80101828` (state 0x80311AEC) | **field. Towns, dungeons, the world map and ship battles all run here** |
| 7 | `fn_8000A118` (state `-29604(r13)` = 0x8034737C); the arm also sets 0x803475B0=1 | character battle. Its exit `fn_80009FD8` goes to scene 6, or on a loss to "ME090A.sct" + 6 |
| 9 | `fn_801C8DF0` (state 0x80311AF8): `/ending/sr.mll`, `srok.mll`, `staff.mld` | ending and staff roll. Entered from `fn_80101494` when byte 0x80310A68 == 'L' (0x80101558-70) |

**There is no separate world-map or ship scene.**

## 2. What the 5xx maps are, and the name table
**[V]** The stage picker's label table is at 0x802E4780, with 8-byte entries `{s16 number, u8 letter, 0, char* name}`. `fn_8010A270` returns 158 as its length, and the picker loop at 0x80100070 matches `lha 0(r5)` against 0x80311AC4 and `lbz 2(r5)` against the letter. The names are Shift-JIS. My decode is in `...\scratchpad\maptable.txt`, where "Ж" stands for one undecoded character, probably 晶.

Maps below 500:

| numbers | name |
|---|---|
| 002a-d | Pirate Isle (b: right after the Valuan raid, c: after it, d: underground port) |
| 004a | Sailors' Island |
| 005a/b | Valua lower city (town side / warehouse district) |
| 008a/b | Maramba (town / port) |
| 010a/b | Horteka (town / Centime's ship) |
| 013a-d | Nasr (d: after the collapse) |
| 017a-e | home base: port, then levels 1-2 |
| 018a/b | Esperanza |
| 019a-d | Yafutoma (port, town 1-2, palace) |
| 020a | Tenkou island |
| 028a-c | Great Silver Temple 1-3 |
| 032a | Albatross |
| 033a | Little Jack |
| 034a-j | Delphinus (normal, emergency, in-ship dungeon, sky dungeon) |
| **099a** | **空マップ, "Sky Map"** |
| 101a-c | Valuan battleship (event / interior / boss) |
| 103a-e | Shrine Island (landing; temple interior at high, mid and low water; exterior) |
| 106a-c | Catacombs and execution ground |
| 107a-c | railway: upper-city station square, platform, moving train |
| 109a-g | Temple of Pyrynn |
| 111a-d | moon-crystal mine |
| 112a-c | ancient city "Dorado" |
| 114a | uninhabited island |
| 115a-c | treasure island |
| 116a-e | "Gargantua" fortress: prison, cannon, gate tunnel, dock |
| 121a/b | Fugaku |
| 122a/b | Sargasso (b: Robinson's wreck) |
| 123a-d | ice dungeon and ice town |
| 125a/b | Yellow Temple |
| 126a-c | "Dangral" base |
| 127a/b | Great Sea of Clouds dungeon |
| 130a-d | Galcian's ship |
| 131a-f | last dungeon, including the Shrine Island exterior (131e is "interior 3") |

**5xx = ship-battle stages, one per fight, named by the enemy:**

| map | enemy |
|---|---|
| 500a | バルボア船 (Baltor's ship; me500a's text has "Baltor", "Blackbeard" and Drachma's tutorial) |
| 501a, 504a, 510a, 518a, 520a, 521a, 542a-544a | Valuan fleets 1, 2, 4, 8, 9, 10, 13-15 |
| 503a | black pirate ship 1 |
| 506a, 515a, 531a, 535a, 547a | red, green, blue, yellow and silver moon-crystal weapons (script text: Bluheim, Yeligar, Zelos) |
| 507a | Belleza's ship |
| 509a, 514a, 540a, 541a | De Loco's ship A, B, C, D |
| 513a | Roc |
| 519a | fortress gate |
| 522a | Gregorio's flagship |
| 523a | giant squid |
| 524a | giant moray |
| 525a | Yafutoman pirate ship 1 |
| 527a | "big Elmo" |
| 530a | Vigoro's ship |
| 532a | horned enemy |
| 537a/538a | Sea of Clouds enemies |
| 545a | Galcian's flagship |

The table has 33 named 5xx entries (500a-547a) and 20 entries from 550a to 583a with an empty name. **[I, from script text]** 550-579 are random sky encounters (black pirate rogues, Valuan spellships, a phantom cruiser, gunboats, mage ships; 573a is Baltor's revenge). 580-583 mention Soltis and a descent.

Two extra finds:
- **The 398a script is a developer ship-battle select.** Its menu strings are "LJ0 LJ1 DER0-DER3" (a player-ship choice), then "500-509 … 580-583". It holds a warp to every number from 500 to 583, including ones not on the disc.
- **Correction to FINDINGS [V]: 255 maps are warpable, not 252.** `fn_8023A4B0` (DVDConvertPathToEntrynum) compares names through `fn_8025BD6C`, which is a lower-case table at 0x802FC1A8. So `ME199F.sct`, `ME355A.sct` and `ME398A.sct` count.

## 3. What makes entering a 5xx map a ship battle
**[V]** It is the map number, not a story flag. State 3's load, `fn_801015AC`, always calls `fn_8012A634`:
```
801015AC..  80101664 bl fn_8012A634
8012A648 li r0,500 ; 8012A64C lwz r5,0x80311AC4 ; subfc/adde. (raw 7C041915, Rc=1 -- disasm.py drops the '.') ; 8012A660 beq -> return
8012A6B8 bl fn_80148E08 ; bl fn_8015C644 ; ... 8012A8B0 bl fn_8015C6C8 ; bl fn_801560FC
8012A8C0 addi r3,..=0x802B3428 "/field/sbek0000.mld" ; bl fn_80109F90
```
The only flag this function reads is a count: bits 1032-1037 of the bitset at 0x80310B3C (0x80310BBC & 0x3F00, party membership) go into 0x803472D0.

The fight itself is the map's script. me500a.sct holds the labels `_WIN _LOSE _TURN_CHK _EV_TURN0.. toujyou` and the assets `bt500a cam500a fe500a co500a`.

## 4. How the game moves between field, world map and ship battles
**[V]** The script opcode table is at 0x802F7940, 12 bytes per entry, handler at +8. I checked opcode 43 against real bytecode: me098a.sct is 243 bytes, ending in `0000002B 00000008 0000000C "me099a.sct"`.

| opcode | handler | what it does |
|---|---|---|
| 43 | `fn_802073B4` → `fn_801002D0` | ordinary warp. Copies the name to 0x80305CF0, calls `fn_800FF908` (position save) and `fn_801F7B04`, sets state 15 |
| 210 | `fn_80214994` → `fn_80147E2C` | **enter a ship battle** (below) |
| 257 | `fn_80214908` → `fn_80147DCC` → `fn_80100270` | leave a ship battle to a named map (story battles, e.g. 500a→205a) |
| 211 | `fn_80214954` → `fn_80147DF8` | leave back to where you came from (random encounters 503/504/513/523/527/532/537/538/550-579) |

`fn_80100270` does only two things: the name goes to 0x80305CF0 and the state becomes 15. Every 5xx script except 510a also uses opcode 43 to go to ME090A on a loss.

`fn_80147E2C` (opcode 210) in detail:
```
80147E58.. sprintf(0x802E5E68,"me%03d%c.sct",0x80311AC4,0x80311AC8)   return point = CURRENT map
80147E74 bl fn_801002D0(name) ; 80147E88 stw 1,-29756(r13)=0x803472E4 ; 80147E8C stw 12 -> 0x80311AEC
```
In state 8's arm, `80101BA0 lwz -29756 ; ==1 ->` clears the flag, calls `fn_80128F80` (loads `/sound/f7000000.mlt` and opens `/sound/m04NN.samp`; NN comes from the table at 0x802E5900, default 30), then:
```
80101BC8 cmpi 0x80311AC4,500 ; bge 80101C74 (state 14) ; else state 12
```
So a normal map fades through 12 → 13 → 14. A 5xx map calling 210 goes straight to 14; the story battles do this on themselves, e.g. 500a → me500a, which I infer is the "try again" path. State 14 waits for the music in `fn_80128F2C`, then state 15 runs the teardown `fn_80101494`.

Callers of 210:
- 099a-q: 503a, 513a, 523a, 550-577a (plus 525a, 527a, 532a, 578a, 579a and 583a at later stages)
- 205a → 500a and 573a (205a is an event map)
- 033a → 506a and 507a
- 034a → 520a, 522a, 544a
- 116f→519a, 122a→524a, 127b→537a/540a/541a, 215a→514a, 240a→518a, 241a→509a/515a, 242a→521a, 243a→501a, 244a→535a, 247a→530a/531a, 249a→543a/545a, 250a→547a
- 004a names 55 of them; why is not established.

Results after a ship battle **[V]**. The teardown calls `fn_8012A26C` at 0x801014EC, *before* `fn_801004C4` parses the new name at 0x80101554, so it sees the map being left:
```
8012A2A4 bne(map>=500) -> ship teardown ... 8012A36C lha 46(ship rec) ; cmpi 2 ; beq ; 8012A37C stw 1,-29856(r13)=0x80347280
```
The next load then takes state 4:
```
801015F8..80101644: if 0x803475B0==1 || 0x80347280==1 (and flag/byte checks) -> fn_80090D9C, return 4
```
State 4 is the results screen: `fn_800E3594` loads `/field/HRS_BEND.BIN`, next to the strings "Total Exp." and " was learned!".

## 5. The Exp/Gold screen in the census and sky500 runs came from the pokes
**[V]** sky500 poked 0x80311AC0 and 0x80311AC4 to 500 *before* state 15. The teardown therefore ran the ship-battle teardown on a battle that never existed and set 0x80347280=1. The log agrees: `= 4 at block 801E1A14 lr 801018F0`, and state 5 only after the A at 15400.

**Poking 0x80311AC0/AC4/AC8 is not "belt and braces".** For 5xx maps it causes this screen, and it skips the audio preload that opcode 210 does. The name alone is enough; `fn_801004C4` fills in the map words.

## 6. The world map: map 099 inside the field scene
**[V]** The sky-mode flag is `-29372(r13)` = 0x80347464, set in state 0 (`801013B0 stw r3`) from `fn_800C8D90`. That function returns 1 for 099 with any letter, 122a, 125a, 125b, 125d, 127a and 127b; these are the maps where you pilot the ship. With the flag set, the load calls `fn_8016ACA0`, which loads `/field/sora0N.mld` (table at 0x802E711C: letters a-f, h, m use sora00; the other letters use sora02) and skips the on-foot player.

**The letter in the name is ignored** for 099. For map 99, 0x80311AC8 is overwritten with byte 0x80310A22 + 'a':
```
801012F0 cmpi AC4,99 ; 80101300 lbz 0x80310A22 ; addi 97 ; stb AC8
```
The same happens again at 0x80101764, so the story-stage byte picks 099a through 099q. Every script that warps there names ME099A: 033a (Little Jack), 035a, 035g, 098a, 355a, 525a and 580-583a.

The census shows this path: `LoadAsset lr 8016AE44 "/field/sora00.mld"` → `/field/a099a.mld`, so 0x80310A22 was 0. 099a's opcode-43 exits are 002a, 002b, 033a, 103a, 205a, 250a and 260a.

## 7. Not established
- **The world map's controls.** I could not find the code that steers the ship.
- **Whether 099a hands control over at once** or plays an event first.
- **What writes the stage byte 0x80310A22.**
- **Why ship record +46 != 2** when no battle had run.
- **Why 004a names 55 battles.**
- **Where the ship-variant setting lives** (the LJ0/DER* choice in 398a).

## RECIPE
Use the `battle` preamble and the `SOA_PAD` below, which is `battle.scn` plus probes. `SOA_RENDER=1`, `SOA_SNAP=100`, `SOA_TRACE=1`, `SOA_WATCH=0x80311AEC`, `SOA_FRAMES=22000`.
```
SOA_PAD='1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2200:start,2240:a,2400:start,2440:a,2600:start,2640:a,2800:start,2840:a,3000:start,3040:a,3200:start,3240:a,3600:a@150,15600:sup#400,16200:sleft#300,16700:sright#300,17200:r#300,17700:l#300'
SOA_POKE='15000:0x80305CF0=0x4D453039,15000:0x80305CF4=0x39412E53,15000:0x80305CF8=0x43540000,15000:0x80311AEC=15,18500:0x80305CF0=0x4D453530,18500:0x80305CF4=0x30412E53,18500:0x80305CF8=0x43540000,18500:0x802E5E68=0x6D653039,18500:0x802E5E6C=0x39612E73,18500:0x802E5E70=0x63740000,18500:0x803472E4=1'
```
The frame-15000 pokes are ME099A.SCT plus state 15. The frame-18500 pokes are the game's own opcode-210 entry to ME500A: the destination name, the return name "me099a.sct", and the flag. **They deliberately leave the state word alone.**

What to look for:
1. `[poke] 11 poke(s) armed`.
2. After 15000:
   - The watch shows 15, then 0 (lr 8010158C), 1, 3, 5, 7, 8, with **no 4**.
   - The trace shows `LoadAsset … lr 8016AE44 "/field/sora00.mld"` followed by `LoadStart "/field/a099?.mld"`; that letter is the stage byte.
   - Frames 15600-18000: the scene changes during the stick and R/L holds and stays still between them. That means the ship can be sailed.
   - A watch 9/10/11 followed by `/BCHARA/` loads is a sky random encounter. If one is still running at 18500, the second warp is lost, because state 0 clears 0x803472E4; move it later.
3. After 18500:
   - `803472E4 <- 1 (was 0)`.
   - The watch shows 12, 13, 14, 15, 0, 1, 3, 5, 7, 8, again with **no 4**.
   - `LoadStart lr 801CC68C "/sound/m0430.samp"` (lower-case m, from `fn_80128F80`); only the faithful path produces this.
   - `LoadAsset lr 8010A004 "/field/sbek0000.mld"`, then `/field/a500a.mld`.
   - Frames 18600-18800 are **not** the 39,475-colour Exp/Gold screen; they show the Little Jack and Baltor straight away.
4. A state 4 at step 3 would falsify §5.

A cheaper check of §5 alone: from a101b, the four pokes for ME500A.SCT + state 15, with no AC pokes. The prediction is the same: no 4 and no Exp/Gold.

Helpers are in a session scratchpad, not kept: `da.py` lists callers, `dolh.py` searches the DOL, `maptable.txt` is the decoded table, and `sct\` holds the decompressed scripts.