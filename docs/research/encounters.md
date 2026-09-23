<!-- Written 2026-09-23 by a read-only research agent from the disassembly, the DOL and the
decompressed scripts; nothing here was run when it was written. Claims marked [V] were read
from quoted instructions; [I] is inference. Check a claim against a run before building on it,
and record what a run shows in docs/FINDINGS.md, not here. -->

**Random encounters in Skies of Arcadia Legends (GEAE8P): how they fire, how to force one, and the seven-command wheel**

A poke of six words forces a battle on the next field frame. The game has a scripted-battle request that skips every encounter check, and the poke uses it. I read everything below from the disassembly and the extracted disc. I did not launch the game. Anything not quoted as an instruction is marked as inferred.

r13 = 0x8034E720 and r2 = 0x80350000 (`gpr[2] = 0x80350000 | 0`, gen/chunk_000.c:387). The r2 constants I read are 0.0, 30.0, 14400.0, 50.0, 0.5, 100.0, 1/32768 and 1.7.

## 1. The encounter check, fn_800C1C24 (called every frame in state 8)

The field state machine's state-8 arm calls it unconditionally:
```
80101A58 bl fn_800C1C24
80101A5C cmpi r3,0
80101A60 stw r3,-30940(r13)      ; 0x80346E44 = result (1 random-type, 2 event)
80101A64 bc 4,1 -> 80101AA4      ; <=0: no battle
80101A68 bl fn_80226D14 ; then saves player +56/+60/+64/+72 and (+440)->+42 to 0x80347488..0x80347478
80101AB0 lwz r0,24(r31); cmpi 8 ...
80101B94 li r0,9 ; 80101B98 stw r0,24(r31)   ; state 9
```

### A. The forced path runs first and has no gates

```
800C1C5C lwz r0,-29516(r13)  ; 0x803473D4
800C1C60 cmpli r0,1 ; bne -> 800C1D34 (the random path)
800C1C70 stw 0,-29516(r13)   ; one-shot
800C1CD4 li r5,-1 ; 800C1CE8 beq (if [0x803473D0]==0) ; 800C1CEC lwz r5,-29524(r13)
800C1D08 sth r5,0(0x803097F0) ; 800C1D0C sth [0x803473CC],2(..) ; 800C1D10 sth [0x803473C8],4(..)
800C1D14 bl fn_8000ABCC(stage)
800C1D18..800C1D2C  return ([0x803473D0 after]== -1) ? 1 : 2
```

The only code that arms it is `fn_800C1A34(a0,a1,a2,a3)`: `stw a0,-29520; stw 1,-29516; stw a1,-29524; stw a2,-29528; stw a3,-29512`. Its only caller is fn_801FF210 at 0x801FF350. That is script opcode 112: the table base is 0x802F7940, the dispatcher does `mulli 12; lwz r12,8(r5); bctrl` at 0x802123C8..E0, and the handler sits at 0x802F7E88. It takes four script arguments.

- **0x803473D0 (a0):** 0 means a map-party battle; nonzero means an event battle.
- **0x803473CC (a1):** the formation or event id.
- **0x803473C8 (a2):** the battle stage N. fn_8000ABCC formats `s%03d.sml`, `s%03d.sst` and `stsicon.mld` into the file list at 0x803098C8.
- **0x803473D8 (a3):** the transition pattern. -1 picks one at random (fn_80097CEC calls rand when it gets -1).

### B. The random path, at 0x800C1D34

It returns 0 (no battle) if any of these holds:
- [0x80347408] is 1.
- Bit 0x2 of the story bitset word 0x80310BBC is set (`800C1D48 lwz 128(r3); rlwinm 30,30`).
- Bit 0x80 of 0x80310BC4 is set. This one-shot skip is cleared when taken (`800C1DE0 rlwinm 25,23`).
- [0x80347450] (the player) is 0.
- [0x803473E4] is 1.
- [0x80347444] is 1, or bit 0x80000000 of 0x80310BC0 is set, or [0x80347440] is -1, or [0x80347504] is 1.
- fn_801DB6B0 returns 1.
- The table pointer [0x803474BC] is 0.
- fn_8011768C returns nonzero. Below map 500 that means the player's action state at +368 is not in 1..4 or 22..25.

Map 99 takes a separate sub-table path (fn_800C1A50).

After the gates:
```
800C1F80 lhz r28,-29458(r13)            ; zone (u16 at 0x8034740E); map 99 uses [0x80346CD4]
800C1FA4..800C1FB4 zone must be 1..8
800C1FB8..800C1FC4 fcmpu 0.0,[0x80347410]; beq -> return 0   ; no movement, no count
800C1FD8 addi r0,r3,1 ; 800C1FE8 stw r0,-31224(r13)  ; STEP COUNTER 0x80346D28 ++
800C1FDC stfs 0.0,-29456(r13)           ; movement consumed
800C1FF8 lhz r0,-130(table+zone*132)    ; rate
800C200C..800C203C f31 = (N-30)*rate/14400
800C2000 lbz 0x8030B7AD ; if != -1: f31 *= byte/50      (accessory effect code 84, set in fn_801EE5A4)
800C2064..800C2078 f31 = max(f31,0)*0.5
800C207C bl fn_8025ECC4 (rand: seed*0x41C64E6D+12345, >>16 &0x7FFF)
800C20A0..800C20BC X = 100*rand/32768 - 50, +100 if <0
800C20C4 cmpi N,480 ; >=480: X /= (N*6/480)   (0x88888889 magic, i.e. N/80)
800C2110 fcmpo X,f31 ; cror ; bc 12,2 -> return 0     ; battle iff X < f31
```

Choosing the formation:
- `800C2130 lhz stage,-132(r26)`: the stage must be nonzero.
- The loop from 800C2178 to 800C2260 does a weighted draw. It starts with f27 = 100 and, for each entry up to 32, calls rand. It picks entry i if weight_i >= remaining*u, otherwise subtracts weight_i from the remaining total.
- 800C21E4..800C2224 stores -1 to 0x803097F0, the formation id to 0x803097F2 and the stage to 0x803097F4. It calls fn_8000ABCC(stage), zeroes the counter and returns 1.

The step counter at 0x80346D28 only ever goes up. It counts frames in which the player moved. It is compared at 0x800C20C4 and folded into f31. It is reset at:
- 0x800C2220, after a battle;
- 0x800C1CE0, on the forced path;
- 0x800C1DC8, on the cancel path;
- 0x800C1F28, on the map-99 table switch;
- 0x800C2620, on map load.

The movement float at 0x80347410 and the zone come from fn_800D07F8, which raycasts down from the player. It verifies as:
- `800D0888 lhz r0,36(hit); rlwinm r0,r0,0,28,31; 800D0894 sth r0,-29458(r13)`. The zone is the low nibble of the ground polygon's attribute.
- `800D0948..0950` adds 1.7*|speed|/(player+604)->+8 to the movement float when the zone is 1..9.

The RNG is reseeded from the tick counter on every map load (`801012AC bl OSGetTick; 801012B0 bl fn_8025ECBC`). Real encounters therefore will not repeat from run to run. The forced path uses no rand except for the transition pattern.

## 2. Table loading and file formats

fn_800C24CC is called from fn_80101264 at 0x80101364, during state 3's load (fn_801015AC):
- It formats `%sa%03d%c.ect` (0x802B1320) and `%sa%03d%c_ep.enp` (0x802B1330) from 0x80311AC4 and 0x80311AC8.
- fn_801CC62C checks that both exist and fn_801CC3C4 loads them.
- `800C25D4 stw enp,-29288` puts the .enp at 0x803474B8. `800C25D8 stw ect,-29284` puts the .ect at 0x803474BC.
- If the .ect is missing it prints "Encount Table is Nothing : %s". A missing .enp prints "Paty Table is Nothing".
- It then clears the step counter, the forced flag 0x803473D4 and 0x803473DC, and sets 0x803473D8 to -1.

The .ect decompresses (AKLZ) to 1056 bytes: 8 zones of 132 bytes each.

| Offset | Field |
|---|---|
| +0 | u16 stage |
| +2 | u16 rate |
| +4 + 4i | {u16 formation id, u16 weight}, 32 entries |

The weights sum to 100. For a101b, zone 2 is stage 2, rate 20, ids 0-11; zone 3 is stage 2, rate 20. Zones 1 and 4 have rate 0; zones 5-8 are empty.

.enp formation records start at +672 and are 10 bytes each: {u8, u8, u8 enemy[8]}. This comes from `80077900 mulli r3,r0,10; addi r3,r3,672; add r3,enp,r3` in battle setup. a101b has formations 0-11; formation 0 is `0e 01 00 ff…`, a single enemy.

Teardown in state 11 goes fn_80101158 → fn_800C23CC (0x801011D0). That copies 8 KB of the .enp to 0x803036E8 and repoints 0x803474B8 at it (0x800C245C..74).

Battle setup, fn_80077428:
- It reads `lha r26,0x803097F0` and compares against -1.
- For -1 (a map-party battle) it uses the .enp record numbered by 0x803097F2.
- Otherwise it loads "/battle/epevent.evp" (0x802B07C8) and uses the record at +1600 + 37*id. Ids 29, 30, 32, 45 and 69 are remapped by byte 0x8030BB1F.
- epevent.evp decompresses to 87,576 bytes. The first 1600 bytes are 200 pairs of (enemy id, offset); the first offset is 0x2B40, which leaves exactly 256 records of 37 bytes.

## 3. The 8 → 9 → 10 → 11 transition (jump table 0x802E471C)

- **State 9 (0x80101CDC):** calls fn_80219378("/sound/b7000000.mlt") and fn_80217FF4(-2,1,14), writes 0 to 0x80347474, writes state 10, and falls through.
- **State 10 (0x80101D08):** `lwz r3,-29512; bl fn_80097CA4; cmpi 1; bne wait`. This is the transition effect, a state machine in fn_80097B0C. It then releases the handle at 0x80346E40, writes -1 to 0x803473D8 and writes state 11.
- **State 11 (0x80101DD0):** calls fn_8022697C, fn_800FF908, fn_80101158 and fn_8012A26C, then `stw 0,-29392; stw 0,-29616; stw 1,-29004; li r3,7; bl fn_801DBE6C`. Scene 7 is the battle.

The battle music is chosen by fn_801010CC from 0x80346E44:
- 58 for a random-type battle;
- 59 if [0x80347464] is 1;
- 60 for event ids 72..256 and 61 for ids 167..181;
- the table at 0x802E46E0 for event ids below 59.

boot_monkey.log shows `/sound/m0458.samp` at all five a101b battles (frames 9910, 23860, 37510, 45160 and 50860). Each is followed by `/battle/stsicon.mld`, `/BCHARA/E9900000/1.MLD` and `/BCHARA/E9901000/1.MLD`.

## 4. Maps with encounter tables (decoded with the repo's AKLZ decompressor)

35 maps have both an .ect and an .enp, and every one also has an .mld and an .sct, so all can be warped to by name:

- **0xx:** a017a (stage 30), a020b (76), a035b (67/68), a099a (map 99; the .ect is 146,888 bytes of sub-tables chosen by fn_800C1A50 per region, plus a099a_01ep..13ep)
- **101-109:** a101b (2), a103b and a103c (4/5/7/79/58), a106a and a106c (8/97/98/99), a109b, a109c, a109d
- **111-116:** a111b, a111c, a111d, a112b, a115b, a116a, a116c, a116d, a116e, a116g, a116h
- **121-126:** a121b, a121c, a122a (rate 2), a123b, a123d (zone 1 rate 90), a125a, a126b, a126d
- **130-131:** a130b, a130c, a131c, a131e

a103d, a103e and a114a have an .enp with no .ect, .mld or .sct. They are orphan data.

## 5. Starting a specific battle

There is no debug battle-select menu. The only debug-looking format string in the executable is "Stage No: %03d%c". The script battle request itself is the route.

- **Map-party battle (random-type):** set 0x803473D0 to 0, 0x803473CC to a formation id and 0x803473C8 to a stage. It needs a map with an .enp, because a missing one leaves 0x803474B8 at 0.
- **Event battle:** set 0x803473D0 to nonzero and 0x803473CC to an event id from 0 to 255. Battle setup loads epevent.evp itself, so this should work on any map.

Nothing ever stores 10 into 0x803473DC through r13 (only zeros), so the "state 10" pre-load branch in fn_800C1C24 looks dead. I did not check for indirect writes.

## 6. The seven labels: a second menu function, and three statements in FINDINGS that are wrong

**fn_8007CAB0 is the command wheel.** At 0x8007C600, fn_8007C600(i) dispatches the seven slots through the table at 0x802DF8BC:

| Slot | Label | Evidence |
|---|---|---|
| 0 | Focus | Shares slot 4's handler (0x8007C648: sets 0x80347338 = 3, no submenu). Disabled by actor+28 & 0x1000. |
| 1 | Magic | Spawns fn_8007B5B0. Available if spells 0..35 are known (table 0x802C4BF0: "Increm"…"Electrulen") and actor+28 & 0x200 is clear. |
| 2 | S-move | Spawns fn_8007BEB4. Checks ids 36..59 ("Cutlass Fury"…"Aura of Denial"). |
| 3 | Attack | The wheel opens here (`8007CD64 stb 3,5(widget)`). Always available. Spawns fn_800794D8, the enemy-target selector. |
| 4 | Guard | Same handler as slot 0. Always available. |
| 5 | Item | Spawns fn_8007A890. |
| 6 | Run | Available from the escape flag. When fn_8007C9CC returns nonzero it becomes a "Blue Rogues"/"Prophecy" menu (fn_8007C344). |

The strip does not wrap. In state 2 (0x8007CF78), UP and LEFT (0x8/0x1) are refused at slot 6 and otherwise move +1. DOWN and RIGHT (0x4/0x2) are refused at slot 0 and otherwise move -1. The widget task commits at `800261EC add cursor,start,dir`.

Slots 1, 2, 3 and 5 are fixed by what they call. Focus = 0 and Guard = 4 come from the measured frames.

**Why each scripted press moved two slots.** The pad auto-repeat is fn_801C7904. On the first frame it outputs the button edge. After 6 held frames it repeats and resets its timer. runtime/si.c:80 sets `HOLD_FRAMES 10`, so a default scripted press gives two steps. With two steps per press, all six measured transitions in FINDINGS fit the order above exactly:
- Attack → Magic → Focus, then stuck at 0;
- Attack → Item → Run, then stuck at 6;
- Run → Guard → S-move.

With one step per press none of them fit. That the port's pad frames match the game's frames is an inference.

**The three corrections:**
1. **fn_8007A890 and fn_80079F74 are the Item submenu, not the command menu.** Its codes 9 to 12 are tabs: Items (0x802C7C34, "Sacri Crystal"…), Weapons (0x802C5790, "Cutlass"…), Armor (0x802C6190, "Vyse's Uniform"…) and Accessories (0x802C6E10, "Gemstone Ring"…). "Code 10 = Attack" is wrong.
2. **fn_80079C5C is not target selection.** It is spawned from the Weapons tab (0x8007ADC4) and cycles actor+256 through six values masked by fn_801F4CA0 (ids 326..331). The Y button on the wheel changes the same byte (0x8007D1A0..0x8007D250). I infer it is the weapon's Moon Stone colour.
3. **Target selection is fn_800794D8.** It starts from a remembered byte in the command record at 0x80309174 + actor*32: +20 for Attack, Focus, Guard and Run, +24 for Magic and S-move, +28 for Item.

## 7. Recipe (one run, pokes after frame 15000)

```
python tools/scenario.py run battle --frames 20000 --log build/scenario-forcebattle.log --env SOA_TRACE=1 --env SOA_WATCH=0x80311AEC --env "SOA_POKE=15000:0x803473C8=2,15000:0x803473CC=0,15000:0x803473D0=0,15000:0x803473D8=0xFFFFFFFF,15000:0x80346D28=0,15000:0x803473D4=1"
```

The pad is the scenario's own: the preamble plus A every 150 frames to the end. That fights the battle, because the wheel opens on Attack.

Look for, in order:
1. `[poke] 6 poke(s) armed`.
2. `0x803473D4 ... (was 00000000)`. The `was` values for 0x803473CC and 0x803473C8 are left over from the opening battle. If 0x803473D0 "was" the same nonzero value as 0x803473CC, the opening battle came through this request. In that case, poking those values with 0x803473D0 = 1 is the "specific id" route.
3. `0x80346D28 was` should be about 0, since nothing has pressed the stick.
4. `[watch] 80311AEC/4 = 9`, then `= a`, then `= b`, within a few hundred frames.
5. Trace lines `/sound/m0458.samp`, `/battle/stsicon.mld` and one or more `/BCHARA/E99…MLD`.
6. A PNG snapshot after 15100 showing the swirl, then a one-enemy battle.
7. After the win, `/field/a101b.mld` again and the watch showing 0, 1, 3 … 8.

If nothing changes and 0x803473D4 stays 1, the field was not in state 8. If the state stops at `a`, fn_80097CA4 never returned 1.

**On any other map:** warp by name as before, then poke the same five words 600 or more frames later (map load clears 0x803473D4). For example, for a103b: `0x803473C8=4, 0x803473CC=0` (zone 1 contains formation 0). Stages and formation ids are in section 4.

**The real random path:** poke `0x80346D28=100000` and hold the stick. That forces the roll to succeed (f31 ≈ 69 against X < 0.08), but only on a zone-2 or zone-3 floor of a101b. Where those zones lie is not established.

**Wheel check:** in a battle parked on the wheel, `left#4` should move one slot (Attack → Guard) and a plain `left` should move two (Attack → Item). For a direct readout, `SOA_WATCH=0x80346B40,16` prints the direction word (0x80346B40) and the start slot (0x80346B4C) on every move.

## Still unknown

- Which floor polygons of a101b carry zones 2 and 3.
- The meaning of 0x80347408, 0x803473E4, 0x80347444, 0x80347440, 0x80347504 and fn_801DB6B0.
- The layout of the fields inside an epevent record, and the opening battle's id (the recipe's `was` values will show it).
- The other writers of the movement float (0x80119A08, 0x80119C08, 0x80119C24).

The decode script for section 4 is (a session scratchpad, not kept). It is in the scratchpad, not the repo.