<!-- Written 2026-09-24 by a read-only research agent from the disassembly, the DOL, the
decompressed scripts and a few enemy files read in place; nothing was run and no repository
file was changed. Claims marked [V] were read from quoted instructions (address given); [I]
is inference. Community sources (ALX by Taikocuya) were used as leads and every field this
report relies on was re-checked against the code. Check a claim against a run before building
on it, and record what a run shows in docs/FINDINGS.md, not here. -->

> **Where the enemy records come from.** `enemy-data.md`, written the same day, supersedes this report's
> reading on that point. Actor +272 points at the record copy inside the current map's `.enp` (random battles)
> or `epevent.evp` (scripted battles). The `ebinit`/`ecinit` files have the same 524-byte layout, but the
> shipped game reads them only for formation −1.

**The character battle and the ship battle in Skies of Arcadia Legends (GEAE8P): actors, turn flow, damage, AI, statuses, costs, and where a combat mod hooks**

Everything below comes from reading the code and the data. I did not launch the game. r13 = 0x8034E720 and r2 = 0x80350000. "slot" is a battle slot: 0–3 party, 4–11 enemies. "rec120" is the per-character battle record at `0x8030B4D4 + 120*ch`; "char" is the character record at `0x8030B7F4 + 92*ch`; "ctx" is the battle context `*0x80347390`. Already-known facts from earlier research (scene 7, the wheel, the reward routine, the EXP routine) are cited, not redone.

## 0. Summary

- **Actors [V].** Battle setup `fn_80077428` allocates 12 actors of **276 bytes** each (`fn_801E1A74(1,276)`, 0x80077544 and 0x80077B44). Their pointers go in the table **`0x80309DE4[12]`**: party in slots 0–3, enemies in 4–11, and 0 for an empty slot. The data ids go in **`0x80309DCC[12]`** (s16). HP is at +20 (s32), max HP at +24, the status word at +28, stats at +128…+157, MP at +254 (party only), and the source record pointer at +272.
- **Spirit is shared, and lives in ctx [V].** Max SP is ctx+6, current SP is ctx+8, and "SP left after this round's reservations" is ctx+10.
  - The per-round gain is **`fn_8006EF48`**: for each able party member, `rec120+6 + actor+268`.
  - Focus adds `char+28` through effect 101.
  - SP is spent through effect 100 in `fn_8002BD88`.
- **Turn flow [V].** Scene-7 state 5 runs a 10-phase machine from the table at `0x802DAE50`, indexed by `0x8034733C`:
  - 1: party input.
  - 2: enemy AI and turn order. The key is `Quick + rand()%(avgQuick/2)`, sorted by MSL `qsort` (`fn_8025EB4C`, a **heapsort**) and stored reversed in `0x803092F4`.
  - 3: dispatch.
  - 4: wait.
  - 5: post-action checks.
  - 6: end of round (poison, regen, status timers, SP gain, victory or defeat).
  - 7: win. 8: lose. 9: escaped.
- **Damage [V].** The physical base is `2·ATK − DEF` (`fn_80010A40`); a critical sets DEF to 0. Magic is `2·(Will + power) − MagDef` and a physical S-move is `(2·ATK − DEF)·power/10` (`fn_8006AFD0`). All of them finish in **`fn_800108EC`**: ×U[0.975,1.025), +1 with probability 1/8, × the target's element value/10, ×0.5 when guarding, capped at 9999. Hit, miss and critical are decided in `fn_80010B64`.
- **Enemy AI is data-driven [V].** **`fn_8008A424(slot)`** interprets up to 64 six-byte tasks at `record+138` (`{type, id, param}`). Branch conditions come from the function table **`0x802DFB10`** (70 entries) and target selectors from **`0x802DFC28`** (25 entries).
- **The effect pipeline has one choke point [V].** Every applied result goes through `fn_8002DD8C` → **`fn_8002BD88`**, which filters immunities and dispatches through the **79-entry applier table `0x802DBB10`**. The HP subtraction itself is at `0x8002DD00`. Per-effect values come from the **79-entry calculator table `0x802DF570`**.
- **Costs [V].** A spell or S-move costs `record+25` SP (tables at `0x802C4BF0` and `0x802C52B0`). A spell also costs exactly **1 MP**. The menus reserve both, and phase 2 hands the MP back before execution charges it.
- **Ship battles [V].**
  - The per-frame driver is `fn_80129DD0`, called from field state 8 at 0x80101A28.
  - The enemy AI is `fn_80145844`, which reads `field/rNNNa.tec`.
  - The damage core is `fn_80146BF4` (the same formula shape, ×10).
  - Results are applied by `fn_8014419C`.
  - The script sees the fight only through `B[256..275]`.
- **Hooks.** No candidate combat hook contains a loop that waits on an interrupt. The AI interpreter's task walk and error loop are the only unbounded loops. The pointer tables above are called through `dispatch`, so they can be repointed at run time to any existing function. Jump tables (`bctr`) cannot, because they are compiled to `switch` statements.

---

## 1. Battle actors

### 1.1 Where they live [V]

- **The actor table.** `fn_80077428` fills `0x80309DE4[0..3]` from the active party bytes `0x8030BB1C` (0x8007752C–0x80077590), and `0x80309DE4[4..11]` from the formation (0x800779F0–0x80077B70). The alive/present test is **`fn_80078610(slot)`**: the slot is 0..11, the pointer is non-null and `actor+28 & 0x2100` is clear.
- **Ids.** `0x80309DCC[slot]` holds the character id for the party and the enemy data id for enemies; −1 means empty (0x80077454). A poison-killed enemy is set to −2 (0x80070468).
- **Initialisers.**
  - Party: `fn_80077228(ch, actor)` reads char, rec120 and the template `0x802C4860 + 152*ch`.
  - Enemies: **`fn_800770B8(actor, record)`**. Its callers are setup (0x80077B58) and the "Call EC" value calculator `fn_800692D8` (0x800693A8), so every enemy spawn goes through it.
- **Enemy records are not copied.**
  - `fn_80077B88(id)` returns a pointer into a loaded buffer:
    - an event battle searches the 200 `(id, offset)` pairs at the start of `epevent.evp` (buffer `*0x8034735C`);
    - a map-party battle searches the 84 pairs at the start of the map's `.enp` (buffer `*0x80347360`);
    - otherwise it loads `../battle/ebinit%03d.dat` (ids ≥ 128, as id−128) or `ecinit%03d.dat`, falling back to `ecinit000.dat` (0x80077BD4–0x80077C60).
  - `actor+272` keeps that pointer, and code reads the record through it for the whole battle.
  - At most four distinct enemy types are loaded per battle; their ids are kept at `0x80347388[4]` (0x80077A24–0x80077B38).

### 1.2 Actor layout (276 bytes)

Sources are [V] from the two initialisers. Meanings are [V] where a user is named, and [I] otherwise.

| Off | Type | Party ← | Enemy ← | Meaning |
|---|---|---|---|---|
| +0 | s16 | rec120+0 | 0 | Regeneration amount while status `0x40000` is set: phase 6 adds it to HP (0x8006FE60) [V] |
| +2 | s16 | 0 | 0 | Copy of the regen amount (effect 78, `fn_8002C010`) [V] |
| +4 | s8 | 0 | 0 | **Stone countdown**: set to 3 by effect 7 (0x8002D664) and decremented at round end (0x8006FF7C) [V] |
| +5, +185 | u8 | rec120+2 | 1 | ? |
| +8 / +186 | s16 | rec120+14 | rec+28 | **Counter-attack % gained per hit taken** (`fn_80010538`). A base value (+186) of 0 means the actor never counters (0x80081A74) [V] |
| +12 | s16 | 0 | 0 | Set to 1 on KO (0x8002BCD0) |
| +14 | s16 | 0 | 0 | **Buff flags**: 0x4 Quickened, 0x8 Strengthened, 0x100 Weak, 0x200 Regenerate [V, effects 20/21/26/78] |
| +16 | u32 | – | 0 | **Event flags for the AI.** 0x1 = hit this round, 0x2 = hit by a spell. Pairs 0x4/0x8, 0x10/0x20 and 0x40/0x80 mean "used ≥1/≥2 heal / attack / status spells" (`fn_80085064`). Phase 2 clears the mask 0x0002E103 each round and keeps the counters (0x80070D28) [V] |
| +20 / +24 | s32 | char+24 / char+26 | rec+36 | **HP / max HP** |
| +28 | u32 | rec120+20 | 0 | **Status word** (§5) |
| +32 | u32 | rec120+20 | 0 | Status bits from equipment, re-applied every round in phase 2 (0x80070DB4–0x80070EC0) [V] |
| +36 / +38 | s16 | – | – | Reset to 0 in phase 2, with the old value kept at +38 [V]; purpose unknown |
| +40..+51 | 6×s16 | rec120+28.. | rec+44.. | **Element multipliers ×10**, in the order Green, Red, Purple, Blue, Yellow, Silver. 10 is ×1.0 (`fn_800108EC`) |
| +64..+93 | 15×s16 | rec120+40.. | rec+56.. | **Status susceptibility** per state id (0 Poison … 8 Weak …). Zeroed while status 0x40 is set |
| +94 | s16 | | rec+86 | "Danger" (AI condition 69 sums it) |
| +128..+137 | 5×s16 | rec120+72.. (Power, Will, Vigor, Agile, Quick) | rec+92.. (**Level**, Will, Vigor, Agile, Quick) | +130 Will feeds magic, +134 Agile the critical chance, +136 Quick the turn order. For an enemy, +128 is the level: AI condition 44 compares it with Vyse's level (0x8008AEDC) [V] |
| +138.. / +160.. | s16 | 0 | 0 | **Buff deltas**: Quika writes +146; Increm writes +160/+162; Weak subtracts [V] |
| +148..+157 | 5×s16 | rec120+82.. | rec+102.. | **Attack, Defense, MagDef, Hit%, Dodge%** |
| +172 / +173 | u8 | template+13/+14 | rec+21/+22 | Width, depth |
| +174 | s16 | template+24 | rec+26 | **Movement flags**: 0x800 = can dodge (0x80010C8C); 0x20, 0x40 and 0x80 choose the melee or ranged attack (0x8008A5FC) [V] |
| +176 | f32 | template+48 | rec+40 | ? |
| +180 | s16 | char+32 | 0 | **Current counter-attack %**. A counter fires when `rand()%100 < +180` (0x80081A88) [V] |
| +182 | s16 | char+16 | – | Weapon id; its effect record is `0x802C5790 + 32*id`, +21 |
| +188.. +200.. +232.. +242.. | | | | Base copies of +40, +64, +128 and +148 |
| +254 / +255 | u8 | char+13 / +14 | – | **MP / max MP** |
| +256 | u8 | char+15 | – | **Weapon Moon Stone colour**, the element of normal attacks (0x80010B08) |
| +258 / +260 | s16 | char+18 / +20 | – | Armor, accessory |
| +262 / +264 | u8 / s16 | char+12 / char+34 | – | +1 when this actor is KO'd, and +1 on a kill it makes (0x8002BD50, 0x8002BD68); names [I] |
| +266 | s16 | rec120+10 | 0 | HP regained each round end (0x8006FE88) |
| +268 | s16 | rec120+12 | 0 | Extra SP added each round (0x8006EF9C) |
| +272 | ptr | template | enemy record | |

### 1.3 Other per-slot arrays [V]

- **Command records**, `0x80309174 + 32*slot`:

  | Off | Type | Meaning |
  |---|---|---|
  | +0 | s32 | Command type. Party (= wheel slot, 0x8007C7E0): 0 Focus, 1 Magic, 2 S-move, 3 Attack, 4 Guard, 5 Item, 6 Run, 8 Blue Rogues/Prophecy. Enemy: 1 magic, 3 attack, 4 guard, 6 run, 11 skip turn, 12 enemy S-move |
  | +4 | s8 | Target slot |
  | +5 | u8 | Enemy target-selector id |
  | +6 | s16 | Skill or item id; for an enemy attack, 0 = close and 1 = ranged |
  | +8 | s8 | Hit result: 0 miss, 1 hit, 2 critical, 3 guarded, 4 blocked, 5 KO |
  | +9 | s8 | Status effect to inflict |
  | +10..+12 | | Counter-attack bookkeeping |
  | +13 | s8 | **SP reserved at selection** |
  | +16 | s32 | Last round's command type |
  | +20 | s8 | Last target (types 1/2/3/8) |
  | +22 | s16 | Last skill id |
  | +26 | s16 | Last item id |
  | +28 | s8 | Last item target |

  The "last" fields are filled by phase 2's jump table at `0x802DF754` (0x80070EE8–0x80070F28).
- **Result records**, `0x80309730 + 16*slot`: +0 motion state, +4 target, +6 skill id, +8 hit result, +9 "motion finished" flag.
- **Battle tasks**, `0x80309700[12]`: each task has +0 a state function, +25 a sub-state and +36 a work struct. The work struct holds:
  - +0 the slot;
  - +4 flags: 0x1 acting, 0x2 cannot act, 0x10 escaped;
  - +16 the action handler;
  - **+60 the value of the effect being applied (damage, heal or SP)**.
- **Turn order.** `0x803092F4[12]` holds slots, ending at −1. The sort keys are at `0x80302B48`: 12-byte entries `{s8 slot, …, s32 key @+4}`.

### 1.4 Battle context `*0x80347390` (376 bytes, allocated by setup at 0x8007746C) [V]

| Off | Meaning |
|---|---|
| +0 | Initiative value: formation byte 0, or the override `0x8030B7AA` |
| +1 | Magic EXP reward (formation byte 1) |
| +2 / +3 | Party / enemy escape-% overrides (`0x8030B7AB` / `0x8030B7AC`; −1 = use the formula) |
| +4 / +5 | Event defeat condition / escape condition (event record +35/+36); the wheel reads +5 to decide Run (0x8007CB90) |
| **+6 / +8 / +10** | **max SP / SP / SP after reservations** (s16) |
| +12 | Enemies defeated; starts from `0x8030BB44` and is incremented in `fn_8002BCE0` |
| +14..+45 | Drops per enemy slot: 8 × {s16 amount, s16 item id} (`fn_8002BA8C`) |
| +48 / +52 | **EXP / gold pools**, added at each enemy KO from record +30/+32 (0x8002BCFC–0x8002BD1C) |
| +56..+375 | The battle's own copy of the item inventory: 80 × {s16 id, u8 count, u8} (`fn_801E0E4C(ctx+56)` at 0x800774F0) |

The formation descriptor `*0x80347384` (38 bytes) holds: +0 initiative, +1 magic EXP, `+2+3i` party ids and `+14+3j` enemy ids. The event record in `epevent.evp` (`+1600 + 37*id`) is laid out to match. Its bytes +34/+35/+36 are read as initiative, defeat condition and escape condition, and the code then writes 255/−1/−1 back into the buffer (0x80077850–0x80077868). **So an event battle can field at most 7 enemies: the 8th enemy's id byte is the initiative** [V; the capacity reading is I].

### 1.5 The enemy data record (524 bytes) [V layout; field names from ALX]

This is `name[21]`, then +21 width, +22 depth, **+23 element**, +26 movement flags, +28 counter increment, **+30 EXP (u16), +32 gold (u16), +36 max HP (s32)**, +40 f32, +44 elements[6], +56 states[15], +86 danger, **+88 effect, +89 state, +90 state-miss** (the status that normal attacks inflict), **+92 level, +94 Will, +96 Vigor, +98 Agile, +100 Quick, +102 Attack, +104 Defense, +106 MagDef, +108 Hit, +110 Dodge**, and **+114 four drops {prob, amount, id}**. Then come **+138 the AI script, 64 × {s16 type, s16 id, s16 param}**, and at +522 an end mark of −1.

The arithmetic checks: 138 + 384 + 2 = 524. I also checked it against three ebinit files, whose element values were 7–13 and whose end mark was −1.

Battle code reads these fields:
- +21 to +40 and the arrays: the initialiser;
- +23: the element of normal attacks (0x80010B18) and of enemy skills when the skill has none (0x8006B2D4);
- +30/+32: at KO;
- +86: AI condition 69;
- +88..+90: `fn_80010584`;
- +96: poison damage (0x8006FED8);
- +114: drops;
- +138: the AI.

### 1.6 Party inputs [V]

- **rec120** is built by `fn_801EE5A4`, which `fn_801EF7E0` calls for each character after an equipment, level or party change. It holds:
  - +6: SP per round;
  - +8: max-SP share;
  - +10: HP regen per round;
  - +12: SP bonus;
  - +14: counter increment;
  - +20: equipment status bits;
  - +28, +40, +72 and +82: the element, state, stat and combat-stat arrays.
- `fn_801EF7E0` (0x801EF97C) also sets:
  - **max SP `0x8030B7A4 = min(Σ rec120+8, 99)`**;
  - **starting SP `0x8030B7A6 = min(Σ rec120+6, 99)`**, forced to 0 when any member has the rec120+20 flag 0x10000.
- It resets the accessory overrides `0x8030B7A9..AD` to −1. They are, in order: party first strike, enemy first strike or initiative, party run %, enemy run %, and encounter rate.

---

## 2. Turn flow

### 2.1 The phase machine (scene 7, state 5 → `lwz -29668(r13)`; `bctrl` through `0x802DAE50`) [V]

| Phase `0x8034733C` | Function | What it does |
|---|---|---|
| 0 | `fn_80071990` | Resets the command records; round `0x80347340` = 1. Goes to phase 1, or straight to 2 when initiative `0x80347344` = 0 (enemy ambush) |
| 1 | `fn_800715F0` | Party input. For each member at index `0x80347330`, skips anyone with `+28 & 0x6D00` and runs the wheel `fn_8007CAB0` |
| 2 | `fn_80070C18` | **Enemy AI and turn order** (§2.2) |
| 3 | `fn_800708C0` | Takes the next slot from `0x803092F4[cursor 0x80347335]` and stores it in `0x80347334`. Skips it if dead, if `+28 & 0x6500`, if the command is 11, or if `0x02000000` is set (which it clears). Installs the **party handler `fn_80086C68`** or the **enemy handler `fn_8008B9E0`** into the work struct at 0x80070A54/0x80070A74 |
| 4 | `fn_80070848` | Waits for the action task |
| 5 | `fn_8007050C` | Clamps MP to max. Victory: phase 7 when only the party is alive. Defeat: phase 8. A party escape (task flag 0x10) goes to 9; an enemy that escapes is removed. Then cursor++ → phase 3, or phase 6 at −1 or 12 |
| 6 | `fn_8006FD6C` | **End of round** (§2.4) |
| 7 | `fn_8006F4B0` | Victory and rewards. EXP per member = `ceil(ctx+48 / alive)` (0x8006F5FC); gold is added at 0x8006F624 and capped at 99,999,999; magic EXP = ctx+1 |
| 8 | `fn_8006F424` | Defeat. ctx+4 = 1 means "try again" (scene state 9); otherwise the result goes to `0x8034736A` |
| 9 | `fn_8006F020` | Escaped; fills the result buffer `0x803082F8` |

Every phase function runs once per frame from the scene dispatcher. None of them waits on an interrupt [V: no blocking callees].

### 2.2 Phase 2: AI and turn order (`fn_80070C18`) [V]

1. If cmd[0] is 8 (Blue Rogues or Prophecy), initiative is set to 2: the party alone acts this round (0x80070C48).
2. Unless initiative is 2, each live enemy that is not disabled (`0x6500`) gets `cmd[slot].+0 = fn_8008A424(slot)` (0x80070CAC). When initiative is 2, every enemy gets 3.
3. Each actor's `+16 &= 0xFFFD1EFC` and `+38 = +36; +36 = 0`. Status `0x800` (confusion) forces command 3. The party's round-only status bits are rebuilt from +32.
4. **Guard is applied at once**: command 4 sets `+28 |= 1`, and the guarding actor does not enter the order (0x80071068).
5. **Key:** `avg = Σ Quick / n; half = avg/2`, and `key = actor+136 + (half ? rand() % half : 0)` (0x800711E0–0x8007121C). Two special cases:
   - `fn_8006EE54` actors (crew or special) get fixed keys from 0x10000 to 0x60000.
   - A command whose `+6 == 83` makes its target act with key 0x80000 as skill 119 (0x80071230–0x8007136C). I did not identify the meaning.
6. The actor range is set by initiative: 0 = enemies only, 2 = party only, otherwise everyone (0x80070F40–0x80070F84).
7. **Sort:** `fn_8025EB4C(0x80302B48, n, 12, fn_80010CE4)`. The comparator returns `a.key − b.key`, so the sort is ascending. The slots are then copied **reversed** into `0x803092F4`, so the highest key acts first (0x80071408–0x80071548).
   - `fn_8025EB4C` is MSL's `qsort`, but the body is a **heapsort**: it builds a heap from n/2, swaps the root with the end, and sifts down comparing children at 2i (0x8025EB70–0x8025ECA4). **It is not stable**, so actors with equal keys come out in a heap-determined order. Anyone reproducing the order (SOA_qSort) must copy this sort, not a textbook quicksort. [V for the code; I have not seen SOA_qSort itself.]
8. Resource hand-back for the party: **Magic** does `actor+254 += 1`, returning the MP the menu took (0x800715BC). **Item** calls `fn_80077DA0(id)`, returning the reserved count to ctx+56 (0x800715B4). Then phase 3 starts with cursor 0.

The RNG is `rand = seed*0x41C64E6D+12345; return (seed>>16)&0x7FFF`, with the seed at **`0x803469A8`** (`fn_8025ECC4`). It is reseeded from `OSGetTick` twice at battle start (0x8000A1CC–0x8000A1D8) [V].

### 2.3 Initiative (`fn_80010CF4`, from `fn_800849A8` at battle start) [V]

- An event battle always gets 1.
- Otherwise, with `r = rand()%101` (a separate draw for each check):
  - **party first strike (2)** if `r < 0x8030B7A9`, or when that is −1, if `r < clamp(4·level(first member) + 30 − ctx+0, 0, 30)`;
  - else **ambush (0)** if `r < 0x8030B7AA`, or when that is −1, if `r < clamp(ctx+0 − 4·level, 0, 70)`;
  - else **1**.
- Phase 6 resets initiative to 1 every round.

### 2.4 End of round (`fn_8006FD6C`, sub-state `0x80347338`) [V]

- **Sub-state 0**, for each actor:
  1. Regen (`0x40000`): HP += actor+0.
  2. HP += actor+266 (both capped at max).
  3. **Poison** (`0x80`, unless `0x6100`): damage = 2 × Vigor. Party members use the record at `0x8030B7F4 + 92*slot` +62 (indexed by slot, not by character id). Enemies use record+96. Lethal poison sets a bit in `0x80346BE8` for sub-states 10 and 11.
  4. **Confusion** (`0x800`) ends when `rand()%100 < 25`.
  5. **Stone** (`0x4000`): actor+4 decrements, and the status clears at 0.
  6. Guard (`0x1`) clears.
  7. Round-only bits clear: `0x2`, `0x800000`, `0x02000000`, `0x4`, `0x8`, `0x10`, `0x40`.
  8. Susceptibilities are restored from +200.
  9. **Then SP**: `fn_80077CCC()` checks whether any live member has `0x10000`. If so, SP = 0. Otherwise **`fn_8006EF48()`** adds `Σ(rec120[ch]+6 + actor+268)` over live members without `0x3100` to ctx+8, clamps it to ctx+6, and copies it to ctx+10.
- **Sub-state 1**: the victory and defeat test. When both sides are alive:
  - round `0x80347340` += 1;
  - the command records are reset;
  - the phase goes to 1 for the first member able to act, or to 2.

---

## 3. Damage, healing, hits and criticals

### 3.1 Hit, miss and critical (`fn_80010B64(att, tgt)`; returns 0 miss, 1 hit, 2 critical) [V]

- **Miss** when `rand()%101 < (100 − Hit(att+154) + Dodge(tgt+156)) / 2`, but only if the target has movement flag `0x800` and no status in `0x4C00`. Otherwise the attack hits. Vyse's dodge gets the bonus at `0x802C8E54 + 34·title` +30.
- **Critical**: on a plain attack (`cmd+6 == 0`), when `rand()%101 <= Agile(att+134)`.
- The caller `fn_80081B94` turns a hit into **3** when the target is guarding (`0x1`) and **4** when it has `0x4` ("Block Attack"). Result 5 (KO) is set when HP ≤ damage.

### 3.2 Physical damage (`fn_80010A40(att, tgt, result)`) [V]

- Results 0 and 4 do no damage.
- `atk = Attack(att+148)`, plus the Swashbuckler bonus +26 for Vyse (party character 0).
- `def = Defense(tgt+150)`, or **0 on a critical**.
- `base = 2·atk − def`.
- The element is `att+256` (weapon Moon Stone) for the party, or enemy record +23.
- The result is **`fn_800108EC(base, elem, att, tgt)`**, forced to at least 1 on a critical.

### 3.3 The shared finish (`fn_800108EC`; r2 constants 0.975, 0.05, 1/32768, 10.0, 0.5) [V]

```
x = max(base, 0)
x = x*0.975 + x*0.05*rand()/32768             ; 97.5%..102.5%
if (rand() & 7) == 0: x += 1
if elem <= 5: x = x * tgt.elem[elem] / 10.0   ; tgt+40+2*elem, 10 = neutral
d = (int)x ; if tgt+28 & 1 (Guard): d = (int)(x*0.5)
if d >= 10000: d = 9999
```

It has three callers: `fn_80010A40` (normal attacks), `fn_8006AFD0` (skills, items, Prophecy and Blue Rogues) and `fn_80069B58` (an enemy skill with base `2·Vigor` that damages both user and target).

### 3.4 Skills (`fn_8006AFD0(att, tgt, kind, …)`, entry 0 of the value table) [V]

| kind | Base |
|---|---|
| 1, party | Record `0x802C4BF0 + 48·id`; element +17, or the weapon element when outside 0–5. **Magic (+24 == 0), and Aika's and Fina's S-moves: `2·(Will + power(+28)) − MagDef`. Other S-moves: `(2·ATK − DEF) · power / 10`**, plus Vyse's Swashbuckler +28 on ATK |
| 1, enemy magic / 6, enemy S-move | Record `0x802AD440 + 36·id` (S-moves use `id+36`, i.e. `0x802AD950`); element +28, type +29: magical `2·(Will + base(+26)) − MagDef`, physical `(2·ATK − DEF)·base/10` |
| 2 | Prophecy: `maxSP · 100` |
| 3 | Blue Rogues: `maxSP · fn_801F52AC() · 10` |
| 4 | Item `0x802C7C34 + 36·(id−240)`: `2·power(+28) − (+31 ? MagDef : Defense)`, element +30 |

The result is stored to `work(tgt)+60`, and cmd+8 is set to 1, or 5 when it will KO.

### 3.5 Healing [V]

- **Recover HP** (`fn_8006AE20`, calculator entry 31) is **flat**: spell +28, enemy magic +24, item +28, or for Blue Rogues `maxSP · ((fn_801F52AC()>>8)&0xFF) · 10`. The damage side uses the low byte of that function's result instead. There is no Will term and no variance.
- The applier `fn_8002DBA8` (effect 31/32) does `HP = min(HP + value, maxHP)`.
- Per-round heals are actor+266 and regen actor+0 (phase 6).

### 3.6 Status infliction by normal attacks (`fn_80010584(att, tgt)`) [V]

- The effect, state and threshold come from the weapon effect record `0x802C7A90 + 20·eff` (+17 effect, +18 state, +19 threshold), where `eff` = weapon +21. For an enemy they come from record +88/+89/+90.
- `r = rand()%100`, forced to 0 below 10 and to 100 at 90 or above.
- **Inflict when `susc[state]/10 · ATK · r / DEF > threshold`.** The effect is written to `cmd[tgt]+9`.
- Target flag `0x40` blocks the negative ones.

### 3.7 Counter-attacks (`fn_800819D0`, then `fn_80082134`) [V]

- Only between the party and enemies, never on a critical, and not when the target has `0x6D00`.
- A counter is guaranteed with `+28 & 0x2` or `0x800000`. Otherwise it needs a base counter value (+186) and succeeds when `rand()%100 < +180`.
- Each hit taken adds +8 to +180 (`fn_80010538`). After a counter, +180 resets to 0, or to 100 under the guaranteed statuses.

### 3.8 The effect pipeline [V]

1. **Value.** `fn_800683D8` (the per-target resolver, called from the attack handlers and `fn_80082134`) calls the calculator **`0x802DF570[effect]`** (0x800683D8+0x228). The calculator writes `work(tgt)+60`.
2. **Commit.** **`fn_8002DD8C(slot, a, effect)`** builds a 16-byte message `{s16 slot, s16 a, s16 15, s16 effect, s32 value = work+60, s32 work+64}`. It has 11 callers: every action handler plus poison.
3. **Apply.** **`fn_8002BD88(msg)`**:
   - Effect **100** subtracts msg+8 from SP (floor 0) and **101** adds it (cap at max).
   - Otherwise, only in phase 4, it applies the immunities:
     - target `0x40` blocks negative states (some become plain damage, some are zeroed);
     - target `0x10` zeroes everything;
     - `0x8` zeroes magic (command 1, or command 12 when the skill category is magic);
     - hit result 4 zeroes attack damage.
   - Then `bctrl 0x802DBB10[effect]` for effects 0–78.
4. **Effect 0 (`fn_8002DC14`)**:
   - hitting a confused (`0x800`) target sets `0x02000000` (skip a turn);
   - it clears sleep and confusion (`0x800|0x400`);
   - **`HP = max(0, HP − value)` at 0x8002DD00–0x8002DD0C**;
   - `fn_8002BC4C` (KO);
   - `+16 |= 1`, and `|= 2` when the attacker used Magic.
5. **KO (`fn_8002BC4C`)**: when HP ≤ 0 it keeps only `0x8`, sets `0x100` and, for an enemy, adds EXP and gold and rolls drops (`fn_8002BA8C`). The first drop to succeed is taken; a probability above 100 uses a special-case function table.

### 3.9 Escape (`fn_80010340(slot)`, `r = rand()%101`, success when `r <= chance`) [V]

- **Party:** always succeeds with initiative 2. Otherwise the chance is ctx+2, or when that is −1, `80 − ctx+0 + 4·level(runner)`, plus Swashbuckler +32 for Vyse.
- **Enemy:** ctx+3, or `200 − 100·Quick(slot 0)/Quick(self)`.
- On success the Run handler `fn_800858B8` sets **`+28 |= 0x2000`** and task flag `0x10`. On failure every party member Guards.
- The community cheat address `0x80010454` is the final `adde`. In this port a code patch is inert (mods.md), so the equivalent is a hook or ctx+2 = 100.

---

## 4. Enemy AI (`fn_8008A424(slot)`, one caller at 0x80070CAC) [V]

- **Confused (`0x800`):** the action is 550 (Attack) with selector 12 (nearest) (0x8008A450–0x8008A4C0).
- **Otherwise it walks the script at `record + 138`** (record = actor+272), starting at `i = 0`:
  - **type 0 (branch):** `if (0x802DFB10[id](slot, actor)) i = param − 1; else i++` (param is 1-based);
  - **type 1 (action):**
    - `cmd+0 = id` and `cmd+5 = param`;
    - `cmd+4` is set to `slot` when param is 255, otherwise to `0x802DFC28[param](slot)`, falling back to `slot` on −1;
    - the loop then stops;
  - **anything else** prints "ENEMY DATA ERROR" through `fn_801DBE1C` and **loops forever** (0x8008A5A8–0x8008A5BC). `fn_801DBE1C` is `GameDebugPrintf`, bound natively.
- **Action ids:**

  | Id | Command |
  |---|---|
  | 550 | Attack (3); `+6` = 0 close / 1 ranged, chosen from movement flags 0x20/0x40/0x80 with a `rand()%10 > 3` roll |
  | 551 | Guard (4) |
  | 552 | Run (6) |
  | 500–549 | Magic (1), `+6 = id − 500` |
  | < 500 | Enemy S-move (12), `+6 = id` |

- **The 70 conditions** match ALX's branch list exactly. I checked several:
  - 0: HP = max;
  - 1: HP < max/2;
  - 4: `+16 & 1`;
  - 11 and 15: round `0x80347340` == 1 / 8;
  - 16: `+28 & 0x200`;
  - 18 and 19: SP compares on ctx+8/ctx+6;
  - 21: `rand()%100 <= 10`, so **"Rating N%" is really (N+1)%**;
  - 30: always;
  - 37: round ≥ 5;
  - 44: Vyse's level − actor+128 ≥ 4;
  - 69: danger sum ≤ 3000 with an empty slot.
- **The 25 target selectors** at `0x802DFC28` match ALX's parameter list (furthest, nearest, random, highest HP, …).
- **Overrides at execution** (`fn_8008B9E0`):
  - confusion again forces Attack;
  - hard-coded skill ids 54, 59, 280 and 283 are remapped depending on which enemy slots are alive (a "call allies" guard);
  - `fn_8008A280` resolves indirect targets for magic and S-moves;
  - the handlers are: magic/S-move `fn_80087074`, melee `fn_80087F6C`, ranged `fn_80087844`, guard `fn_80088ABC`, run `fn_80088B14` (jump table `0x802DFD10`).

---

## 5. Status effects [V unless marked]

**Status word `actor+28`:**

| Bit | Status | How it behaves |
|---|---|---|
| 0x1 | Guard | Set when phase 2 builds the order; halves damage; cleared at round end |
| 0x2, 0x800000 | "Counter 100%" states | Counter guaranteed; cleared at round end |
| 0x4 | Block Attack | Hit result 4. Round-only: re-applied from +32 each round |
| 0x8 | Block Magic | Round-only |
| 0x10 | Invulnerable | Every value is zeroed. Round-only |
| 0x40 | Block negative states | Susceptibilities are zeroed. Round-only |
| **0x80** | **Poison** | |
| **0x100** | **Unconscious** | |
| **0x200** | **Silence** | Magic slot disabled; AI condition 16 |
| **0x400** | **Sleep** | Being hit wakes |
| **0x800** | **Confusion** | 25% recovery each round; forces an attack on the nearest actor |
| **0x1000** | **Fatigue** | Focus disabled per encounters.md; excluded from SP gain |
| **0x2000** | **Escaped / removed** | |
| **0x4000** | **Stone** | 3-round timer at +4 |
| 0x10000 | "No Spirit" | From equipment; SP held at 0 |
| 0x20000 | ? | From equipment |
| **0x40000** | **Regenerate** | Amount at +0 |
| **0x80000** | **Weak** | −25% |
| **0x100000** | **Strengthened** | Increm: +25% Attack and Defense via deltas at +160/+162 |
| **0x200000** | **Quickened** | Quika: +50% Quick via +146 |
| 0x01000000 | ? | Cleared, together with regen, by confusion, silence and fatigue |
| 0x02000000 | Lose next turn | |

`0x6500` (can't act), `0x6100` (no poison tick), `0x3100` (no SP) and `0x2100` (not present) are the masks the code tests.

- **Apply.** The applier table `0x802DBB10` follows ALX's effect ids:
  - 3 Poison: `fn_8002DB54`;
  - 5 Unconscious: `fn_8002DA88`;
  - 7 Stone: `fn_8002D60C`;
  - 9/10 Sleep: `fn_8002D518`;
  - 11 Confusion: `fn_8002D4A4`;
  - 12/13 Silence: `fn_8002D43C`;
  - 14 Fatigue: `fn_8002D3D4`;
  - 16/17 remove positive states: `fn_8002D27C`/`fn_8002D104`;
  - 20/21 Quika/Increm;
  - 26 Weak: `fn_8002CC74`;
  - 29/30 remove negative states: `fn_8002CAD8`;
  - 31/32 heal;
  - 78 regen + buffs: `fn_8002C010`.
  - The ids 1, 2, 43, 45, 52–60, 64, 71, 73, 75 and 76 all point to a bare `blr`, `0x8002DD88`.
- **Inflict chance:** §3.6. Susceptibility is `actor+64[state]`, restored every round from +200.
- **Tick:** phase 6 (§2.4).
- **Cure:** effects 16/17 and 29/30, being hit (sleep and confusion), timers (stone), the round-end confusion roll, and KO, which clears everything except `0x8`.
- **Buff expiry:** I found no timer, so buffs appear to last until removed or until the battle ends [I].

---

## 6. Costs [V]

- **Tables.** Spells are records 0–35 at `0x802C4BF0`; S-moves 36–59 plus Blue Rogues (60) and Prophecy (61) are at `0x802C52B0`. Records are 48 bytes:
  - `name[17]`;
  - +17 element; +18 order;
  - +20 occasion flags: 1 menu, 2 battle, 4 ship;
  - +21 effect; +22 scope; +23 owner (a character id, or 6 for magic); +24 speed;
  - **+25 SP**; +28 power; +30 type; +31 state; +32 state threshold;
  - +36..+44 the ship-battle fields: occasion, effect, SP, turns, base (+42).

  The layout is from ALX and checked against code: the magic menu reads +17 and +25 (0x8007B160–0x8007B18C), the S-move menu reads +25 (0x8007BCEC), and damage reads +24 and +28.

  Enemy magic (36 records) and enemy S-moves (309 records) are 36-byte records at `0x802AD440` and `0x802AD950`:
  - `name[17]`, +21 category, +22 effect, +23 scope;
  - +24 param (the heal amount);
  - +26 base, +28 element, +29 type;
  - +30..+33 status fields.
- **Selection.**
  - The magic menu lists a spell only when **ctx+10 ≥ +25** and **MP > 0**.
  - Choosing it does `ctx+10 −= cost`, `cmd+13 = cost` and `MP −= 1`.
  - Cancelling (`fn_8007B328`) refunds both.
  - Items take their count from ctx+56 at selection.
- **Execution** (`fn_80085064`, sub-state 1):
  - `work+60 = cmd+13`, then `fn_8002DD8C(slot, 0, 100)`, so **SP −= cost** (0x8008515C–0x800851A8);
  - **MP −= 1** only for real spells, where record+24 == 0 (0x800852B0).
  - Phase 2 has already returned the menu's MP, so the net charge is 1 MP.
- Blue Rogues and Prophecy have +25 = −1 (0xFF) [V bytes], so they are gated some other way (`fn_8007C194`). Items cost no SP.
- These tables sit in the DOL's `.rodata`, but guest memory is one writable image and they are read at run time. **A data patch to +25 or +28 changes costs and powers live** [V: reads through normal loads; mod.c refuses only code ranges].

---

## 7. Ship battles [V unless marked]

- **Gating.** Setup and teardown run on any map ≥ 500 (`fn_8012A634` from load state 3, `fn_8012A26C` from the teardown).
  - Setup loads **`%sr%03d%c.tec`** (`fn_8015C644`, pointer at **`0x80347048`**).
  - It counts the party members (flags 1032–1037, "in the party now") into `0x803472D0`.
  - It clears `B[256], B[257], B[263..265], B[267], B[269]`.
  - It starts the camera task `fn_8012910C` and loads `sbek0000.mld`.
- **The per-frame driver is `fn_80129DD0`**, called unconditionally in field state 8 at 0x80101A28, just before the script tick.
  - It locates the phase from the timeline at `*0x803472A8` (88-byte entries) and the float timer at `0x803472E0`.
  - It finds the player and enemy ship among the 8×20-byte records at **`0x80308EF8`** (+8 HP, +12 max HP), using the ids at `0x803472B0`/`0x803472AC`.
  - It publishes:

    | Variable | Value |
    |---|---|
    | `B[256]`, `B[257]` | Battle state |
    | `B[258]` | Turn ready (`0x80347294 == 1`) |
    | **`B[261]`** | **Player ship HP %** |
    | **`B[262]`** | **Enemy ship HP %** (1 while above 0) |
    | `B[263]` | `min(0x803472D8, 100)` |
    | `B[264]` | Round mod party count |
- **The ship-battle state is `S = *0x8034727C`.**
  - +32 and +36 point to the player and enemy ship objects: +20 max HP, +24 HP, +28 defense, +32 magdef, +40.. elements, and weapon slots of 34 bytes from +96.
  - There are 62-byte per-phase records at `S + 62·p`: +44 who acts first, +46 outcome, +58/+20 task types, +85 enemy id.
  - There are 144-byte result blocks at `S + 292 + 144·p` (player side) and `S + 1444 + 144·p` (enemy side): +2 the SP change, +8 heal, +12 damage, and 16-byte attack records from +16.
- **Turn resolution.**
  - `fn_80144CE4(phase, side)`: `fn_80147CC8` picks who acts first, then the player action `fn_80143928` and the enemy action `fn_8014337C`, then the display `fn_801457C4` and the applier `fn_8014419C`.
  - The applier:
    - applies heals and damage to +24;
    - sets **`S + 62·p + 46` = 2 (player sunk) or 1 (enemy sunk)**;
    - sets `0x80347278` = 3 or 1;
    - on a win, sets EXP and gold from **enemy-ship record +100/+104** and rolls drops through the chance table `0x802E5D50`.
  - The teardown's "record +46" (ship-worldmap.md) is this outcome field. Any value other than 2, including 0 when no fight happened, sends the next load to the results screen.
- **Enemy ship AI** (`fn_80145844(turn, phase)`, reached through `fn_8015C5F4` → `fn_80144680` → `fn_80143734`).
  - The record is `tec + 80·turn + 20·phase`: four phases per turn; a turn index past the −2 end mark falls back to the table's first turn.
  - The condition `{s16 id, s16 param}` dispatches through `0x802E5E18`, for ids −1..8: none, player HP ≤, enemy HP ≤, SP ≤, Rating, the enemy's previous task, the player's current task, and others.
  - It returns action A (+4) when the condition is true and action B (+12) otherwise, each `{type, arm, param, duration}`.
  - This matches ALX's `.tec` layout: 20-byte records and a double −2 end mark.
- **Hit, critical and damage.**
  - Hit: `fn_80145E0C`. The weapon Hit% and the target Dodge% set the chance, which the phase modifier (+50/+52) scales, rolled against d100.
  - Critical: `fn_80145F50`, with the chance taken from the gunner's Agile (char+64) or enemy-ship record +32.
  - The attack records are built by `fn_8014359C` and `fn_80143FA4`; the latter also charges the weapon's SP (slot +31).
  - Effects go through the table **`0x802E5DB0`** (ids 100–117, as in ALX's ship effects). **107 Damage** is `fn_80146828`, which computes into **`fn_80146BF4(atk, def, elem, phase, rec)`**:

    ```
    x = max(2*atk - def, 0) * phaseMod/10
    x = x*0.975 + x*0.05*u       ; plus +1 at 1/8
    x = x * tgt.elem[e]/10
    x *= 0.5 when the defender's phase code is 3 (Guard)
    rec+12 += x*10
    ```

  - Attack sources, per weapon kind:
    - main or secondary cannon: slot attack (+118) + rec120[gunner]+72;
    - magic cannon: spell +42 + rec120+74 against magdef;
    - ship item or crew special: record +28, with +31 choosing defense or magdef;
    - enemy arm: record +50 + 10·arm.
- **Tables** (addresses from ALX's GC-US offsets, each confirmed by a code reference):
  - playable ships `0x802D6740`;
  - enemy ships `0x802D6934` (120 B × 45; read in `fn_80134A3C`);
  - cannons `0x802D7E4C` (36 B, ids from 400; `fn_80134D1C`);
  - ship accessories `0x802D83EC`;
  - ship items `0x802D8A2C`;
  - crew `0x802D8E64`;
  - the spirit curve `0x802C9184` (per character: 99 × {sp, maxsp}; `fn_801EF9A8` seeds char+28/+30 from it).
- **Script.** `me500a.sct`'s loop does the following:
  1. When `B[257] == 0` and `B[129] == 0`, it CALLs `_TURN_CHK` (story beats on `B[128]`), then runs opcode 167 (`fn_802150BC`, start a turn).
  2. `_WAIT_LOOP` spins while `B[258] == 0` (1-frame WAITs), then runs opcode 170 (`fn_8021507C`).
  3. It tests `B[261] <= 0` → `_LOSE` and `B[262] <= 0` → `_WIN`.
  4. `_SP_ATTACK` switches on `B[266]`, set by `fn_8015B358`.
  5. `_GET_PLY`/`_GET_ENE` use opcode 191 (`fn_80214DFC`) to copy ship stats into `sys[37..51]` → `B[200..234]`.
  6. `_LOSE` retries with opcode 210, or warps to ME090A.

  The fight's rules live in the engine; **the script only sequences it**.

---

## 8. Hook-point catalogue

**Mechanisms (mods.md, PLAN-60FPS-MODS.md):**

| Name | What it is | Status |
|---|---|---|
| **D** | Data patch, `SOA_MODS` | Exists today |
| **S** | Safe-point callback, `tick_on_safe_point` | Exists today |
| **H** | `hle.txt` native replacement. The original survives as `recomp_fn_X`, so a wrapper can call it and adjust the result | Full retranslation |
| **K** | `hooks.txt` pre-instruction hook. **Strips `irq_poll` from every back-edge of its function** | Full retranslation |
| **W** | M13 wrapper site (pre, post or replace) that keeps interrupt polls | Planned |

**Interrupt column:**
- "none" means the function has no back-edges, so K costs nothing.
- The battle and ship functions below all run on the game thread, once per frame, from the scene or field dispatcher.
- None of them waits on an interrupt.
- The only blocking call on this path is battle setup's disc read, and it sits inside `akFioRead`, a callee whose loops keep their polls.

| Mod | Hook site | Mechanism | What the hook does | Interrupts |
|---|---|---|---|---|
| **Damage multiplier** | **`fn_800108EC`**: return r3; r5/r6 = attacker/target actor pointers (compare them with `0x80309DE4[]` to pick a side) | H wrapper, or W post | Scale, then re-cap at 9999. This covers every normal attack, skill, item, Prophecy and Blue Rogues, and runs *before* the KO test (`fn_80081B94` and `fn_8006AFD0` compare HP with the returned value), so death animations stay consistent. Poison is not covered: it is phase 6, 0x8006FEF0 | none (0 back-edges) |
| Damage (ship) | `fn_80146BF4` return | H or W | Same; the caller multiplies by 10 | none |
| **Heal multiplier** | `fn_8006AE20` (writes `work+60` at 0x8006AFA8); regen at phase 6 | H wrapper: call the original, then scale `work(tgt)+60` | Scaling before `fn_8002DD8C` keeps the applied value consistent with the message it builds from `work+60` | none |
| **New or modified status effects** | Pointer tables **`0x802DBB10`** (apply) and **`0x802DF570`** (value), both `bctrl`; skill records +21 | **D** repoints an id to any *existing* function (`dispatch` switches over all known entries; an unknown address traps). **H** adds new native behaviour by binding an address the tables can then point at | Free status bits: I have not verified which are unused; bits ≥ `0x04000000` are not touched by the code I read. Round-end ticks: a W pre-hook on `fn_8006FD6C` when `0x80347338 == 0` | `fn_8006FD6C` has 10 bounded loops: K strips their polls; harmless, but prefer W |
| **Turn-order preview** | Read `0x803092F4[12]`, cursor `0x80347335` and keys `0x80302B48` during phases 3–5 | S or the frame callback (reads only) | Show the actual order. During phase 1 the order does not exist yet: estimate it from Quick (+136) ± avg/2. An exact prediction would need phase 2's RNG draws (AI and keys) replayed from seed `0x803469A8`, **with the heapsort's tie order** | none |
| **Enemy HP display** | Actors 4–11 (`0x80309DE4`): +20/+24, present if `+28 & 0x2100 == 0`; id `0x80309DCC` | S or frame callback (reads only), M8 overlay | The record name (`*(actor+272)`) is Shift-JIS; the source of the English name is **not found** | none |
| **Battle log** | Action start: phase 3 after 0x8007093C. Every result: **`fn_8002BD88` entry** (msg +0 target, +6 effect, +8 value) plus `0x80347334`. KO: `fn_8002BC4C`. Caption: `fn_800786C0` (*0x80347320) | W pre, or K (none of these has back-edges) | Log "actor, command (cmd+0/+6) → target: effect, value, hit result (cmd+8)". A cheaper log polls phase, cursor and HP differences at S | none |
| **Native enemy AI** | **`fn_8008A424(slot)`**, one caller | **H** (fall back to `recomp_fn_8008A424`). **D alternative:** rewrite `record+138` tasks, or repoint entries in `0x802DFB10`/`0x802DFC28` | Contract: write `cmd+0` (1/3/4/6/12), `+4` target, `+5` selector (255 = self), `+6` id (magic 0–35, S-move id, attack variant); return the type. `fn_8008B9E0` may still override (confusion, ids 54/59/280/283) and re-target magic | **K would strip the task walk's and the error loop's polls**: a cyclic or bad script then hangs with interrupts stopped. H avoids it |
| **Add a wheel command** | UI `fn_8007CAB0`; availability bytes `*0x80346C14[7]`; commit `fn_8007C600` (0x8007C7E0 writes the type) | W or K pre on `fn_8007C600` (overload a slot with a modifier), plus H on `fn_80086C68` or a hook at 0x80086E5C for a new type | The wheel (`0x802DF8BC`) and the handler dispatch (`0x802DFAE8`) are **`bctr` switches baked at translation**, so data cannot add targets. Types 7 and ≥ 9 get a turn slot in phase 2, but `fn_80086C68` does nothing for them (0x80087040): install a handler into task+0 for the custom type. A real 8th icon needs art (`battle/command.mld`) [I] | none |
| **Auto-battle / repeat last turn** | Phase 1 (`0x8034733C == 1`) | **S** (memory writes only) | Per member: set `cmd+0/+4/+6` from the "last" fields (+16/+20/+22/+26/+28) and `cmd+13 = cost`. **Reserve as the menus do**: `ctx+10 −= cost`; **MP −1 for Magic**, because phase 2 adds 1 back at 0x800715C4; **one item from ctx+56**, because phase 2 releases one at 0x800715B4. Close the menus by writing 7 to +25 of each task at `*0x803472FC..*0x80347318` (what `fn_8007D32C` does), then set phase 2 / sub-state 0 (as Run does at 0x8007C6AC). Check life (0x2100), silence (0x200), SP and stock first | none |
| **Skip attack / spell animations** | Waits: `fn_8007FFE8` (motion done; 124 callers; its own 240-frame watchdog at `0x80302BF0`), `fn_8006D1C4` (effects idle; 25 callers) | H, forcing "done" | High risk [I]. The logic would advance (the attack handler applies its value at a fixed sub-state, 0x8008690C), but models would be left mid-motion and off position. **Prefer M11's tick unlock gated on scene 7** | none (0 and 3 bounded) |
| **Spirit rules** | Per round: **`fn_8006EF48`** (one caller, 0x80070124). Focus: `fn_80010CBC` (char+28). Spend/gain: effects 100/101 in `fn_8002BD88`. Max: ctx+6. Start: ctx+8/+10 | D/S for data (actor+268 per round, ctx+6, spell +25); H/W for rules | E.g. "SP per damage taken": a W post-hook on effect 0's handler, then add to ctx+8/+10 (keep ≤ ctx+6; the gauge assumes ≤ 99 [I]) | none, except `fn_8006EF48`, which has one bounded loop |
| **Difficulty (enemy stats at spawn)** | **`fn_800770B8(actor, record)`**: two callers, setup and Call Allies | H wrapper or W post (S alternative: scale slots 4–11 once when phase 1 or 2 is first seen) | Scale actor +20/+24, +128..+137 and +148..+157, and their base copies +232 and +242. **Do not scale the record**: it is shared by every enemy of the type, and the `.enp` buffer persists across battles on a map, so the change compounds. EXP and gold come from the record at KO: scale ctx+48/+52 at phase 7 entry | 4 bounded copy loops (harmless under K) |
| **Level scaling** | Same site; party level `char[ch]+11`; enemy level `actor+128` (record +92) | Same | Setting actor+128 also changes AI conditions 44 and 45 (Vyse level − enemy level). Formation choice: encounters.md (`0x803097F2`, `.ect` tables) | same |
| Escape rate | ctx+2 / ctx+3, per battle; or H on `fn_80010340` | D, S or H | ctx+2 = 100 means always escape; ctx+5 controls Run availability | none |
| Ship AI | `fn_80145844` (returns a pointer to a 4×s16 action) | H | Native ship tactics | 5 bounded loops |

---

## 9. Not established

- **The source of the English enemy names** shown in battle. Records hold Shift-JIS names, and there is no `.sot` on the disc.
- **Unidentified status bits and fields:** `0x2`, `0x10000`'s equipment origin, `0x20000`, `0x800000`, `0x01000000`; actor +5, +10, +36, +176; command-record +14; the `+6 == 83 / 84 / 119` special case in phase 2.
- **How rec120 is built** (`fn_801EE5A4`): which equipment traits feed +6, +8, +10, +12, +14 and +20. So "Focus = char+28" versus "per-round = rec120+6" is only [I] related to the spirit curve.
- **Whether stat buffs ever expire before the battle ends.**
- **Where the damage pop-up reads its number** (assumed `work+60` [I]). If a mod scales only msg+8 inside `fn_8002BD88`, the display may disagree.
- **Enemy target re-resolution** (`fn_8008A280`) and the item handler `fn_80084A08`.
- **Ship battles:**
  - the phase timeline's 88-byte entry layout;
  - which phase modifier (S+50/+52/+54/+56) is which;
  - the player-side command input and SP rules;
  - opcodes 167, 170, 191 and 206–209 in detail;
  - the ship results flow after `0x80347278`.
- **Whether Blue Rogues and Prophecy spend the whole gauge** (their +25 is −1).
- **SOA_qSort.** I could not find the project online, so the claim that the game's sort is a heapsort is from the code alone.
- **Nothing here was checked by a run.** In particular, the initiative, escape and critical inequalities are read from compare idioms, and one run with `SOA_WATCH` on ctx+8 and `0x803092F4` would confirm the SP and order claims.

Scratch material (a session scratchpad, not kept): `bx.py` (cross-reference index over the DOL), `dis/*.txt` (disassembly dumps), `me500a.txt` (the ship script), and `alx/*.rb` (the ALX sources used as leads).
