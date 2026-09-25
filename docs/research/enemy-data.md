<!-- Written 2026-09-24 by a read-only research agent from the disassembly, the DOL, the
decompressed disc files, the trace logs already in build/, and RAM images already captured in
build/fifo/ and build/perfset/ (read, never written). The game was not run: no soa.exe, no
scenario, no soak, no pytest. Only read-only analysis ran (tools/disasm.py, tools/sct.py,
tools/fifo.py and scratch scripts), and no file in the repository was changed. Claims marked [V] were read from
quoted instructions, bytes or log lines; [I] is inference. Check a claim against a run before
building on it, and record what a run shows in docs/FINDINGS.md, not here. -->

**Enemies in Skies of Arcadia Legends (GEAE8P): where they are defined, how an id becomes a fighting, named, animated enemy, and what bounds a mod**

The short version: `ebinit`/`ecinit` are not what the game fights with. In normal play every enemy comes from a copy of its 524-byte record embedded in the current map's `.enp` (random battles) or in `battle/epevent.evp` (scripted and boss battles). The id alone picks the model file, and the model file carries the enemy's **name as a bitmap**. So a "new enemy" is a new record placed in the right container. Its name, portrait and animations come with the model the id selects.

r13 = 0x8034E720, r2 = 0x80350000. All addresses are guest addresses. `fn_8025CB24` is sprintf, `fn_801CC62C` is "file exists" and `fn_801CC3C4` loads a whole file (AKLZ is detected by magic, `fn_801C64DC` at 0x801C65A8..D4) into a heap buffer. These roles are [I] from their call sites.

---

## 0. Answers in one place

| Question | Answer |
|---|---|
| ebinit/ecinit | One enemy record per file, 524 bytes. `ecinitNNN` is enemy id NNN and `ebinitNNN` is id 128+NNN, the same u8 id space as formations. They are opened only when a battle is requested with formation −1, which no shipped script does. 103 of the 245 files differ from the copy the game actually uses. [V] |
| Stats, names, models | Stats live in the record. The name and the model come from the id (§6). The displayed English name is a texture inside the model `.MLD`; no English enemy name exists as text anywhere on the disc. [V] |
| AI | Up to 64 six-byte tasks at record +138, run by `fn_8008A424` through a 70-entry condition table and a 25-entry target table. [V] |
| Drops | 4 slots at record +114, rolled at the enemy's death by `fn_8002BA8C`, first success wins. "1%" means probability byte 1, `rand()%100 < 1`. There is no steal mechanic in the data paths read here. [V]/[I] |
| Events and bosses | Each event record is 37 bytes: magic EXP, 4 party placements, 7 enemy placements, initiative, defeat and escape rules. 250 records are real and 6 are 0xCD filler. Boss stats live in `epevent.evp` (117 of its 146 records are ids ≥ 128). [V] |
| Stages | `sNNN.sml` holds the embedded MLD scenery and `sNNN.sst` the per-object commands plus a 9×9 terrain block (SPICE). Any existing stage can host any enemies. [V]/[I] |
| Enemy ships | A DOL table of 45 × 120 bytes at 0x802D6934, plus per-ship-map AI in `field/rNNNa.tec`. [V] |
| Hard limits | 8 enemies per formation, 7 per event, **4 distinct ids per battle**, 84 records per `.enp`, **8192 bytes per `.enp`**, 200 records in the evp, ids 0–254. [V] |

---

## 1. The three containers and the lookup

Battle setup is `fn_80077428` (called at 0x8000A28C). The request block `lbl_803097F0` (0xD8 bytes) holds the event id at +0, the formation at +2 and the stage at +4. For each enemy slot it calls `fn_80077B88(id)` [V]:

```
80077BAC lhau r3,-26640(r4)        ; 0x803097F0 event id
80077BB4 beq (== -1) -> map battle
80077BB8 lwz r0,-29636(r13)        ; else base = [0x8034735C], the loaded epevent.evp
80077C78 li  r0,84                 ; map battle: base = [0x80347360], the .enp, 84 pairs
80077C80 li  r0,200                ; event battle: 200 pairs
80077C90 lwz r0,0(r4); cmp r0,id  ; {u32 id, u32 offset} directory scan
80077C9C lwz r0,4(r4); add r3,r0,base  ; return base + offset
80077CB0 li r3,0                   ; not found
```

**The direct-file path.** When both +0 and +2 are −1, `fn_80077428` formats `../battle/ebinit%03d.dat` (0x802B07DC) for id ≥ 128 (with id−128), or `../battle/ecinit%03d.dat` (0x802B0810) for id < 128. If `fn_801CC62C` says the file is missing it falls back to `ecinit000.dat` (0x802B07F8), and then loads with `fn_801CC3C4` (0x80077A54..AE0) [V]. Three things make this path dead in retail:

- +2 is written only by the encounter code at 0x800C1D0C and 0x800C2208 [V xref].
- All 1,264 BATTLE calls with literal operands in the 258 disassembled scripts pass a0 = 1, an event battle [V: `tools/sct.py` over every `.sct`].
- The formation pointer that path would use, [0x80347358], is never written anywhere [V xref: one read at 0x800778F8].

When an id is missing from the directory, `fn_80077B88` returns 0. `fn_80077428` then uses `base + 684·u32[base+4]` (0x80077B14..B24) [V], which is not a record in any shipped layout [I]. **A formation must only name ids its own container holds.**

**Map battles.** At map load `fn_800C24CC` loads `aNNNx_ep.enp`. At the battle transition, `fn_800C23CC` copies it into a static buffer:

```
800C245C..68  memcpy(0x803036E8, [0x803474B8], 8192)
800C2474      [0x803474B8] = 0x803036E8
```

`lbl_803036E8` is a 0x2000-byte .bss object (`config/symbols.txt`) [V]. **Any `.enp` larger than 8192 decoded bytes is cut at the battle transition.** Neither ALX nor SOARandomizer checks this [V grep]. The largest shipped file is 7,192 bytes, with 10 records [V].

**Event battles.** `battle/epevent.evp` is reloaded for every event battle (0x800777F0) [V]. The alternative source is the `.enp`, taken when [0x80347370] is nonzero, but that word is only ever written with 0 (0x80101E40) [V], so the branch is dead.

**File formats (decoded)** [V: parsed every file]:

| File | Layout |
|---|---|
| `.enp` | 84 × {u32 id, u32 offset} (FFFFFFFF = empty), formations of 10 bytes from +672 up to the first record, then records. `a099a_ep.enp` is a container instead: `00 00 FF FF`, u16 count, `FFFF`, then count × {char[20] name, u32 offset, u32 size, u32 −1}, holding 13 segments of the same layout. |
| `epevent.evp` | 200 × {i32 id, i32 offset}, event records from +1600, and enemy records from 0x2B40 (146 of them, 524 bytes each). |
| `ebinit`/`ecinit` | One bare 524-byte record. |

**Record size.** 335 records are 620 bytes (16 extra empty task slots, all `.enp` except a109b/c) and 401 are 524 bytes. No record uses more than 61 tasks, and every record ends in `FFFF` [V: 736 records surveyed]. The game never needs the size, because the directory gives the start and the AI walks by index [V].

**The copies agree.** 236 of the 237 ids present in some `.enp` or the evp have one byte-identical variant everywhere. The exception is id 0: its a101b copy gives EXP 1 and its evp copy gives EXP 3 [V]. Of the `.dat` files, 134 match an in-game copy, 103 differ and 8 have no in-game copy [V].

## 2. The enemy record (524 bytes)

Field names follow ALX (`lib/alx/enemy.rb`). "Read by" is the code I read touching the field.

| Off | Type | Field | Read by / evidence |
|---|---|---|---|
| +0 | char[21] | Japanese name, Shift-JIS, 0xFF-padded (id 0 decodes as 軍艦兵) | Not shown in the US build (§6) [V bytes, I display] |
| +21 | i8 | width, in grid cells | → actor+172 (`fn_800770B8`) [V] |
| +22 | i8 | depth | → actor+173 [V] |
| +23 | i8 | element (ALX: Green…Silver = 0…5) | `fn_8006AFD0` 0x8006B2D4 [V] |
| +24 | 2 | 0xFF padding | [V] |
| +26 | i16 | behaviour flags, bit `0x800>>n` (ALX: may dodge … may move) | → actor+174. The AI's Attack choice tests 0x20/0x40/0x80 (0x8008A5FC..48) [V] |
| +28 | i16 | counter % (ALX) | → actor+8 and +186 [V copy] |
| +30 | u16 | EXP | `fn_8002BC4C` `lhz 30` → info+48 [V] |
| +32 | u16 | gold | `lhz 32` → info+52 [V] |
| +36 | i32 | max HP | → actor+20 (HP) and +24 (max) [V] |
| +40 | f32 | unknown, 18.0 in the samples | → actor+176 [V copy] |
| +44 | i16×6 | element resistances | → actor+40/+188 [V] |
| +56 | i16×15 | status resistances (ALX order) | → actor+64/+200 (16 halfwords copied, including +86) [V] |
| +86 | i16 | "danger", a summon budget | Summed over enemies against 3000 by AI condition 69 (`fn_8008A738`) [V] |
| +88 | i8 | on-hit effect id (−1 none) | `fn_800783A8` → `fn_80081FEC` [V] |
| +89/+90 | i8 | status inflicted and its miss % (ALX) | [I] |
| +92 | i16×5 | level, will, vigor, agile, quick | → actor+128/+232 [V] |
| +102 | i16×5 | attack, defense, mag-def, hit %, dodge % | → actor+148/+242. The copy loop also takes +112 [V] |
| +114 | 4×{i16 prob, i16 amount, i16 item} | drops | §4 [V] |
| +138 | 64×{i16 type, i16 id, i16 param} | AI | §3 [V] |
| +522 | i16 | `FFFF` end mark (ALX) | Present in all 736 [V] |

Item ids are the game-wide item numbers (ALX: weapons 0x000–04F, armor 050–09F, accessories 0A0–0EF, usable 0F0–13F, special 140–18F, ship items 190–1FD).

**The battle actor.** `fn_801E1A74(1,276)` allocates it; there are 12 slots, 0–3 party and 4–11 enemies:

- `0x80309DE4` holds the actor pointers, `0x80309DCC` the i16 ids and `0x80309700` the display objects [V symbols.txt sizes].
- actor+272 keeps a pointer to the record (0x80077220) [V]. The AI, drops, EXP and gold read the record through that pointer **at run time**, while HP and stats are copied once at setup.

## 3. AI: 64 tasks and the interpreter

`fn_8008A424(slot)` runs once per enemy turn and always starts at task 1 [V]:

```
8008A4C4 lwz r28,272(r30)       ; record
8008A4D4 addi r3,r28,138        ; task 1
8008A4D8 lha type / lha id / lha param
 type 0 (branch): r3 = table 0x802DFB10[id](slot, actor); true -> task index param-1, false -> next
 type 1 (action): command[slot].code = id; target mode = (u8)param;
                   255 -> self, else r3 = table 0x802DFC28[param](slot) (-1 -> self)
 other:  8008A5A8 prints "ENEMY DATA ERROR" (0x802B0CDC) in an endless loop
```

The action id then becomes a command in the 32-byte record at `0x80309174 + slot*32` (0x8008A5C0..710) [V]:

| Action id | Command | Other fields |
|---|---|---|
| 550 | 3, Attack | a ranged/melee sub-choice from the flags and `rand()%10` |
| 551 | 4, Guard | |
| 552 | 6, Run | |
| 500–549 | 1, Magic | spell id −500 |
| < 500 | 12, enemy S-move | +6 = id, the entry `36+id` of the 36-byte skill table at 0x802AD440 |

Magic occupies entries 0–35 of that table and S-moves entries 36–344, all with 17-byte English names [V].

**Table sizes.** The condition table holds 70 function pointers and the target table 25; the words that follow are other tables [V]. ALX's vocabulary has 70 conditions ("HP < 50%", "Turn 3", "ECs Alive ≤ 3" …) and 25 targets ("Nearest PC", "Self" …), which fits. The shipped data uses conditions 0–69 and targets −1 and 0–24 [V survey].

**Traps** [I, from the code shape]:
- A branch cycle with no action hangs the battle.
- Running off the end of the list reaches a type −1 task, which hangs with the error string.
- A condition id above 69 or a target above 24 calls whatever word follows the table.
- There is no "next task" state between turns; turn-based variety comes from conditions 11–15/37 (turn counters) and 21–29 (percent rolls, ALX).

**Summons.** Skill effect 43 (21 skills, most named "Call Allies") carries an enemy id at skill +24. `fn_800692D8` places that id in a free enemy slot through `fn_80077B88` [V]. The summoned id must therefore be in the same `.enp` or evp.

## 4. Drops, EXP and gold

These run at an enemy's death in `fn_8002BC4C`: the kill counter (info+12) goes up, then EXP += u16 [+30] and gold += u16 [+32], then `fn_8002BA8C(slot)` [V]:

```
8002BAC0 lha r0,114+6k(rec); p = r0 & 0xFF
  p == 255 -> next slot
  p <= 100 -> if rand()%100 < p: drop (0x51EB851F = /100)
  p  > 100 -> call 0x802DBC4C[p-101]: 101 always, 102 rand()%10==0, 103 rand()%5==0, 104 never
drop: info[4*slot-2] = amount (+116), info[4*slot] = item (+118); return   ; first success wins
```

**What that means for the data** [V]:
- One item at most per enemy.
- Value 105 and up is invalid: table entry 105 is 0, and 106+ belong to another table.
- The shipped data never uses 101–104.
- 536 drop slots, in 390 records, have probability 1: these are the "1% drops".

The roll uses the shared LCG `fn_8025ECC4`, which is reseeded from the tick on map load (encounters.md §1). Manipulating a drop therefore means controlling how many `rand()` calls happen before the killing blow [I].

**At the results screen** (`fn_8006F4B0`) [V]:
- EXP per living member = (total + n − 1) / n.
- Magic EXP is info+1.
- Gold goes into 0x8030BB40, capped at 99,999,999 (0x05F5E0FF).
- The 8 per-slot drops are merged into 0x803082F8.

## 5. Formations and the battle layout buffers

**Formation (10 bytes):** {u8 initiative, u8 magic EXP, u8 enemy[8]}, with 0xFF meaning empty. It sits at `enp + 672 + 10·formation` with no bounds check (0x80077900) [V].

**Initiative.** It goes to info+0 unless [0x8030B7AA] ≠ −1; that byte is written by the accessory routine `fn_801EE5A4` [V]. `fn_80010CF4` rolls `rand()%101` against initiative ± 4 × a stat of the lead character (party record +11) to pick the opening state [V]. Which outcome is which is [I].

**info** (`[0x80347390]`, 376 bytes) [V]:

| Offset | Contents |
|---|---|
| +0 | initiative |
| +1 | magic EXP |
| +2/+3 | accessory bytes (0x8030B7AB/AC) |
| +4 | defeat rule |
| +5 | escape rule |
| +12 | kill count |
| +14..+45 | 8 × {i16 amount, i16 item}, one drop per enemy slot |
| +48 | EXP |
| +52 | gold |
| +56 | 80 × 4-byte in-battle item list |

**layout** (`[0x80347384]`, 38 bytes): {init/0xFF, magic EXP, 4 × {party id, x, z}, 8 × {enemy id, x, z}} [V]. Map formations copy ids only, so x = 0xFF. `fn_80084570` then places every unit at random, retrying from scratch on a clash (0x800845D0..80084804) [V]. Event records give explicit x/z.

**The 4-type cap.** Each distinct id is resolved once, into a 4-entry cache at 0x80347388 whose record pointers sit in a 4-word array at r1+8 [V]:

```
80077A28 lha r0,0(cache[r25]); cmp id; beq use ptrs[r25]
80077B34 cmpi r25,4; blt loop          ; 5th distinct id falls out with r25 = 4
80077B54 lwzx r4,r1+8,r25*4            ; ptrs[4] = r1+24, the filename buffer
```

A fifth distinct id therefore builds its actor from a garbage pointer [V code]. The shipped maximum is 3 distinct ids per formation or event [V data].

## 6. From id to model, animations and the name on screen

`fn_8002F80C` (and three siblings) walks the display objects and formats the model from {kind, id} at obj+36 [V]:

```
8002F8AC kind < 4        -> "MA%03d.MLD" (party)
8002F8E0 id < 128        -> "MB%03d.MLD", id
8002F904 else fn_80008274(id); "MG%03d.MLD", result-128
```

`fn_80008274` returns ids 128–157 unchanged. For id ≥ 158 it scans the {lo, hi} pairs at 0x802ACBE0 and returns lo, so ranges of 5 (later 4 and 2) ids share one boss model [V].

**Coverage** [V: file set comparison]:

| Id range | Models |
|---|---|
| < 128 | `mbNNN.mld` exists for exactly 0–121 minus 5 and 6, the same gaps as ecinit. Every shipped common enemy has its own model. |
| 158–254 | The 22 ranges map onto the 22 MG models 030…125. |

No shipped battle uses two ids from one model range together, so a range is one boss's variants across fights, not parts [V data, I meaning].

**Animations and effects.** Each model also needs `/BCHARA/%s.STD` (0x802AD3E0) and `/BCHARA/%s0.STD` (0x802AD3F0), loaded by `fn_800594CC`/`fn_80059788` [V]. In an a101b battle the trace shows [V `build/boot_monkey.log:688,711,713`]:

```
"/BCHARA/MB0000.STD" ... "/BCHARA/MB000.MLD" ... "/BCHARA/MB000.STD"
```

Per SPICE's `StdFileLayout.md`, the 3-digit `.STD` is an action-row table: a 16-byte header, then 24-byte rows {state, …, motion, flags, **param**, …}. The 4-digit file is the effect-script entry table (PUTMODEL, HIT WEAPON, SE REQUEST …). The row params line up with each enemy's S-moves:

| Enemy | S-move its AI uses | Model `.STD` rows include |
|---|---|---|
| Guard | 79 | 79–81 |
| Seeker | 4 | 4 |
| Kantor | 5 | 5 |

So a model can only perform the S-moves its `.STD` has rows for [V correlation, I rule]. `damage.std`, `common.std` and `jouchu.mlk` are loaded for every battle. `E99%02d%02d%d` builds the party weapon models (`E9900000/1` load with MA000) [V trace].

**The name is a picture.** No English enemy name exists as a string in the DOL or in any file on the disc. I searched ASCII and UTF-16, in both cases, in every AKLZ file decompressed, and ran additive and XOR encodings plus strided u8/u16/u32 delta searches over the DOL and the battle RAM [V]. Yet the frame `build/fifo/12000.png` shows "Soldier" above the enemy's HP bar. The FIFO (`tools/fifo.py build/fifo/12000 --verts 1733-1760`) resolves it:

- Draws #1742/#1743 are two textured strips at screen (353–449, 290–306).
- They sample rows 32–47 (64 px) and 48–63 (32 px) of a 64×64 RGB5A3 texture at 0x80B13FA0.
- That texture is **byte-identical** to the first GVR in `MB000.MLD`, texture `ts102000`.
- Decoded, it is a 32×32 portrait at the top left with "Soldier" rendered below it.
- `mg000.mld`'s `ts103000` reads "Antonio" the same way [V decoded].

All 120 MB models open with a `ts102NNN` 64×64 texture. 38 MG models open with `ts103NNN` and 9 more carry one at another index. mg119 and mg121 have only a `tse03NNN` texture, and MG007 and MG075 have none at all; those last two belong to unused boss ids [V]. The record's +0 field is Japanese and plays no part [V]. Whether the game picks the name texture by index or by name is not established (§14). ALX's English names are a hand-kept list (`config/voc.rb.sample` "Enemy Names"), which fits them being absent from the data.

## 7. Event battles and bosses

**Event record (37 bytes)** at `evp + 1600 + 37·event` (0x800777F8; the id is `lha`, so there is no bound) [V]:

| Off | Field | Goes to |
|---|---|---|
| +0 | u8 magic EXP | layout+1, info+1 |
| +1 | 4 × {i8 char, i8 x, i8 z} | party placement; copied over layout+2..13 |
| +13 | 7 × {u8 enemy, i8 x, i8 z} | enemies, 0xFF empty |
| +34 | u8 initiative | info+0 |
| +35 | i8 defeat rule (ALX: 0 must not lose, 1 may try again, 2 may lose) | info+4 |
| +36 | i8 escape rule (ALX: 0 may escape, 1 must not) | info+5 |

**How the record is consumed** (0x80077810..87C) [V]:
- The code copies +34..36 out first.
- It then overwrites them in the **loaded buffer** with FF.
- It then copies +1..+37 onto the layout. The 8th enemy slot is therefore always empty: **7 enemies maximum**.

**Records in use** [V]:
- Records 0–249 hold data; 250–255 are 0xCD filler whose enemy ids are not in the directory.
- Scripts request 235 distinct ids, 0–246, through opcode 112 with a0 = 1.
- 15 valid ids are never a literal operand, among them 2, Antonio's fight: event 2 names id 0x80, and `ebinit000`/`mg000` is Antonio.
- The opening fight is event 0. The RAM of `build/fifo/11900` shows event 0, stage 1, info `0e 02 ff ff 00 01`, and actor+272 pointing at evp+0x2B40.

**Special cases in code** [V]:
- Ids 29, 30, 32, 45 and 69 are remapped when the fourth party slot (0x8030BB1F) holds Enrique (4) or Gilder (5); the party table at 0x802C4860 names 4 and 5.
- Event 9 gets a 90-frame hold at 0x80030810, and event 50 is special-cased at 0x8006FC9C.
- The music comes from `fn_801010CC` (encounters.md §3).
- The STV voice bank comes from a 248-word per-event table at 0x802B0830, read by `fn_80077E34`/`fn_8003E4CC`. The table ends where the "Do nothing" string begins, so ids ≥ 248 read string bytes and fall to the default branch [V bounds, I harmless].

**Bosses.** "Boss" means id ≥ 128:
- the MG model family (§6);
- `fn_8002969C` tags each unit at +504: 1 for party, 2 for id < 128, 3 for id ≥ 128 (0x800297F8..34) [V];
- `fn_8007D42C` sums max HP only over ids ≥ 128 (0x8007D674) [V]. It is a battle task spawned by `fn_80078658(1)`, which happens in event battles when [0x803474A8] == 1; every other battle gets `fn_8007DE54` [V].

Boss stats live only in `epevent.evp`: 117 of its 146 records, next to 29 common enemies reused in scripted fights [V].

**Unused boss ids** [V]:
- 135 and 143 have no record anywhere.
- 203–207, 247, 249 and 253 exist only as `.dat`.
- 5, 6 and 122–127 are unused common ids.

## 8. Battle stages

`fn_8000ABCC(stage)` queues `s%03d.sml`, `s%03d.sst` and `stsicon.mld` (encounters.md §1). The stage comes from `.ect` zone +0 or BATTLE argument a2, and nothing ties it to the enemies [V: no other input].

136 pairs exist, ids 1–150, with 14 gaps: 12, 27, 49, 78, 81, 88, 91, 92, 100–105 [V].

Per SPICE (`SstSmlFileLayout.md`, not re-derived here):
- `.sml` holds the stage id, a count and 16-byte records, each embedding an MLD resource (arena, floor, props).
- `.sst` holds the matching command blocks (types 0–11: setup, lighting, UV and transform animation) and, in the first block tail, an 81-byte 9×9 terrain grid.

**Reuse** [I]:
- A map formation can use any existing stage, since placement is automatic.
- An event needs its x/z bytes to fall on that stage's grid. Shipped values run 2–8, and the 9×9 grid is SPICE's reading.

## 9. Enemy ships (a separate system)

**Ship stats.** 45 records of 120 bytes at 0x802D6934, indexed `mulli 120` (0x80134A6C) [V], ALX layout checked against record 0 [V]:

| Off | Contents |
|---|---|
| +0 | char[20] name, English, e.g. "Valuan Warship" |
| +20 | i32 HP |
| +24 | 6 × i16 will, defense, mag-def, quick, agile, dodge |
| +36 | 6 × i16 elements |
| +48 | 4 arms × {type, attack, range, hit, element} |
| +100 | i32 EXP |
| +104 | i32 gold |
| +108 | 3 × {i16 drop code, i16 item} |

**Ship AI.** One `.tec` per ship-battle map, `%sr%03d%c.tec` (0x802B4104), named from the current map. It is loaded by `fn_8015C644` into [0x80347048] [V]. ALX's layout is 20-byte {cond, cond param, 2 × {type, arm, param, duration}} rows ending in `FFFE FFFE`.

The player's cannons are at 0x802D7E4C (ALX: 40 × 36 bytes; "Main Cannon" first, [V]). Script opcode 210 takes no operands and enters the ship battle [V]. None of this touches `.enp`, `.evp` or `.dat`.

## 10. Limits

| Bound | Value | Source |
|---|---|---|
| Enemy id | u8 0–254; 255 = empty slot (`extsb; cmpi -1`, 0x800779FC) | [V] |
| Common vs boss | < 128 → MB model, `ecinit`; ≥ 128 → MG via 0x802ACBE0, `ebinit` | [V] |
| `ebinit127` | would be id 255, the empty marker: can never be named | [V] |
| `ecinit127` / id 127 | no `mb127.mld`: the model load fails | [V files, I failure mode] |
| Party / enemy slots | 4 / 8, 12 actors in total | [V] |
| Enemies per event | 7 | [V] |
| Distinct enemy ids per battle | 4 | [V] |
| Records per `.enp` | 84 (directory scan) | [V] |
| Bytes per `.enp` | 8192 decoded, static copy | [V] |
| Formations per `.enp` | no code bound: the space between +672 and the first record. ALX says 32 | [V] |
| Records in the evp | 200 (146 used) | [V] |
| Event slots before the evp's enemy block | 256 (250 real) | [V] |
| AI tasks | the interpreter has no bound; 64 in the 524 layout; conditions 0–69, targets 0–24/255, actions 0–308, 500–535, 550–552 | [V] |
| Drop probability | 0–100, 101–104 special, −1 none | [V] |
| EXP, gold | u16 per enemy | [V] |
| Summon | a free enemy slot, and the danger sum at most 3000 | [V] |

## 11. The a101b chain, verified end to end

1. **Formation.** `a101b_ep.enp` decodes to 2,652 bytes. Its directory reads `00000063 00000318 | 00000000 00000584 | 00000001 000007F0`, then FFs. Formation 0 at +672 is `0e 01 00 ff ff ff ff ff ff ff`: initiative 14, magic EXP 1, one enemy, id 0 [V].
2. **Record.** Id 0 is at +0x584; the next record starts at +0x7F0, so it is 620 bytes. Its name is `8c 52 8a cd 95 ba 00` (軍艦兵), max HP 58, and its AI uses actions 550/551 only [V].
3. **In battle.** In `build/perfset/battle/4000.ram`, an a101b map battle [V]:
   - the request block reads −1 / formation 0 / stage 2;
   - [0x803474B8] = 0x803036E8, and the 2,652 bytes there equal the decoded file;
   - info = `0e 01 ff ff 00 00`;
   - layout = `0e 01 | 00 05 08 | 01 07 06 | … | 00 06 04 | ff…`, so the Soldier is auto-placed at (6,4);
   - the cache holds [0, −1, −1, −1];
   - slot 4's actor has HP 58/58 and actor+272 = **0x80303C6C = 0x803036E8 + 0x584**.
4. **Model.** Id 0 < 128 gives `MB000.MLD`, `MB000.STD` and `MB0000.STD`, as the trace shows [V].
5. **Name.** `MB000.MLD` texture 0, `ts102000`, draws "Soldier" [V decoded, and matched to the drawn texture in 12000.ram].

## 12. What the community tools do

**ALX** (`lib/alx`) [V read]:
- `cfg.rb` calls ebinit "boss data" and ecinit "enemy data", and reads `battle/ebinit*.dat`, `ecinit*.dat`, `field/*_ep.enp`, `battle/epevent.evp`, `bchara/m[abg]*.std` and `field/r*.tec`.
- `dscrptr.rb` gives GC-US DOL file offsets (+0x80003000 = address) for enemy magic 0x2AA440, S-moves 0x2AA950, enemy ships 0x2D3934, event BGM 0x2E16E0, items, shops and chests.
- Its limits are 84 enemies and 32 encounters per ENP, 200 enemies and 250 events in the EVP, and 64 tasks.
- It reads and writes the `.dat` files as if live and knows nothing of the 8 KB copy or the 4-id cache.

**SPICE** (`Docs/`): STD (action rows and effect-entry tables), SST/SML (stage pairs with a 9×9 terrain grid), ECT (including `a099a.ect`'s indexed container), SCT, MLK and MLL. It has no ENP, EVP or DAT docs.

**SOARandomizer** is a Rust port of ALX that exports and imports CSV plus ENP/EVP JSON. `enp_builder.rs` rebuilds `.enp` files by copying raw records from other files and patching element@23, counter@28, exp@30, gold@32, hp@36, level…dodge@92–111 and drops@114–137 — the same offsets as §2. It has **no randomization logic yet**: the Tauri backend only loads an ISO [V].

## 13. Recipe: a new enemy from an existing model

**Step 1. Choose the id.** The id selects the model, animations, portrait and on-screen name.

- **(a) Reuse the model's own id.** This needs no new files. The record is per container, so the new enemy can differ completely from the original: new stats, AI and drops in that map's `.enp`, or in the evp for a scripted fight. The cost: it shows the original's name and portrait, and it cannot share a battle with the original (one record per id per container). The game already does this once: the Soldier's EXP is 1 on a101b and 3 in the evp.
- **(b) A spare boss id whose range already maps to a model.** Use 247 (MG119, shared with 248), 249 (MG121/250) or 253 (MG125/254), or 203–207 (MG075) or 135 (MG007); the last two have no name texture. No new files. The enemy appears under the partner's name.
- **(c) A new id with a copied model**, to get a new name. Use 5, 6 or 122–127 as `mbNNN` (or copy MG files for 135/143). Copy `mbXXX.mld`, `mbXXX.std` and `mbXXX0.std` to the new number and repaint the `ts102NNN` texture: a 64×64 RGB5A3 image with a 32×32 portrait at the top left, the name's first 64 px in rows 32–47 and the remaining 32 px in rows 48–63.
  - The game finds files through the FST (`fn_8023A4B0` returns −1 → load fails), and the port reads the FST and data from `extracted/disc.iso` (`runtime/main.c:1124`, `runtime/dvd.c`). New files therefore need a rebuilt image or a new file-override layer; `runtime/mod.c` only pokes RAM words.
  - Files may be stored raw: the loader checks the AKLZ magic (0x801C65A8) [I, strong]. The repository's `tools/soa/aklz.py` only decompresses.
  - Whether a copied `.STD`'s decimal-packed model keys still point at the old number is not established.

**Step 2. Write the 524-byte record** (the §2 layout, in any container):
- Name bytes are cosmetic.
- Set width and depth to the model's size, because placement uses them.
- EXP and gold are u16.
- AI: ≤ 64 tasks. Branch = {0, condition 0–69, 1-based target task}; action = {1, 0–308 / 500–535 / 550–552, target 0–24 or −1}. End every path in an action. **Use only S-moves the model's `.STD` has rows for.**
- Drops: 4 × {prob 0–100 (or 101–104), amount, item id}; −1 for none.
- End with `FFFF`. Keep the danger value sensible if others will "Call Allies".

**Step 3. Place it.**

*Random encounter:*
- Add {id, offset} to a free pair of the map's `.enp` directory (≤ 84) and append the record.
- Add 10-byte formation records in the formation area. Shift the records, and every directory offset, if the area must grow.
- Point `.ect` zone entries at the new formation ids: {u16 id, u16 weight}, weights summing to 100.
- **Keep the decoded `.enp` ≤ 8192 bytes**, about 11 records of 620 bytes or 13 of 524 with 32 formations. Keep ≤ 8 enemies and ≤ 4 distinct ids per formation, and every id present in the same file.

*Scripted fight or boss:*
- Add the record to `epevent.evp`: 54 directory pairs are free, and offsets are absolute.
- Write a 37-byte event record. Slots 250–255 are filler and can be reused in place; more slots need the enemy block moved and all 200 offsets fixed. ≤ 7 enemies, with x/z on the stage grid.
- Start it with BATTLE (opcode 112: 1, event, stage, transition) in a `.sct`, or with the port's forced-battle poke (encounters.md §7). The poke is also an M1 `patches.txt` candidate, a RAM-only mod.
- Event ids ≥ 248 get the default voice bank. The music follows `fn_801010CC`'s id ranges.

*Summoner:* the summoned id must be in the same container.

**Step 4. RAM-only variant (no file changes).**
- An `.enp` record in the static copy can be patched after the transition at `0x803036E8 + offset`: stats before the actors are built, AI and drops any time.
- An evp record is reloaded each event battle into a heap buffer ([0x8034735C]). HP and stats are copied at setup, so only AI, drops, EXP and gold patches written after the load take effect [I from §2].
- M1's planned pointer-relative addresses fit the evp case (`docs/PLAN-60FPS-MODS.md`).

**Step 5. Check.** Force the battle (encounters.md §7) and confirm:
- actor+272 at `0x80309DF4+4·(slot−4)` points at your record;
- the trace shows the expected `/BCHARA/M?NNN` loads;
- the target label shows the model's name.

## 14. Not established

- How the name texture is chosen in models where `ts103NNN` is not texture 0 (mg050 has it at index 4), and what MG007/MG075 (no `ts` texture) or mg119/mg121 (`tse03…` only) would display.
- Whether a summoned enemy's model is loaded at battle start or on demand.
- The meaning of record +28 and +40, of +89/+90 beyond ALX's names, and of the 6th stat copied from +112.
- What `base + 684·u32[base+4]` was meant to be (the not-found fallback).
- Whether `.STD` action-row params also gate magic (actions 500–535), and whether a copied `.STD` references its original model number.
- Which initiative outcome each branch of `fn_80010CF4` is.
- How event 2 (Antonio) and the other 14 valid-but-unrequested events are started; the linear script pass shows 453 BATTLE opcodes it could not parse.
- Why Kantor's record sits in most `.enp` files while only the a116 formations use it.
- Whether a runtime file override in `runtime/dvd.c` can serve files the FST does not list.

Method (scratchpad only, outside the repo): `xref.py` (an index of constant and r13/r2 references over every function via `tools/disasm.py`'s annotator), `all.dis` (a whole-program disassembly), `records.py` (all 736 records from every container), `tools/sct.py` over all 258 scripts, `tools/fifo.py` on `build/fifo/12000`, and `tools/tex.py`'s decoder on model textures.
