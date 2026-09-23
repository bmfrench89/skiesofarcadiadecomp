<!-- Written 2026-09-23 by a read-only research agent from the disassembly, the DOL and the
decompressed scripts; nothing here was run when it was written. Claims marked [V] were read
from quoted instructions; [I] is inference. Check a claim against a run before building on it,
and record what a run shows in docs/FINDINGS.md, not here. -->

## Story progress: how it is stored and tested, the Shrine Island start state, and a recipe

Short answer: story progress is not a chapter counter. It is a set of flags. Each map's script reads those flags and decides what to play. The main-story flags come in blocks of 50 per "part" (part A = flags 0–49, B = 50–99, and so on), and they are set in story order. The retail disc also has the developers' own part-select room, `ME355A.SCT`. Its script contains the exact preset (flags, byte variables, party joins, destination map) for the start of every part from B to L.

Each claim is tagged: [V] I read it in the disassembly or the decompressed scripts; [I] I inferred it. None of it has been run.

### 1. Where the state lives [V]

**The flag set.** It starts at `0x80310B3C` and is 854 words long (flags 0–27,327). Flag *n* is bit `(n & 31)` of the word at `0x80310B3C + 4*(n>>5)`, counting from the least significant bit. Flag 0 is therefore the lowest bit of `0x80310B3C`.
- `fn_801CAF30` clears it: `801CAFA0 subfic r0,r5,854` / `801CAFB8 stw r3,0(r4)`.
- The same function also clears 288 byte variables at `0x80310A1C` (B[0..287]; the loop starts at `801CAFCC`).
- It is called only from boot (`fn_801DBE88`) and from New Game (`fn_80228BE4`).

**Per-map temporaries.** Flags 1856–2047 (words `0x80310C24`–`0x80310C38`) and B[128..286] are cleared by `fn_801CAE98` (`801CAEB0 stw r5,232(r4)` … `801CAECC stw r5,252(r4)`). Its only caller is the load-game function `fn_801A4354`. The warp teardown `fn_80101158` calls `0x801CAE8C` at `8010120C`, and that address is a bare `blr`.

**Save and load layout**, from `fn_801A4354`:
| Save buffer | Destination | Size | Contents |
|---|---|---|---|
| +16 | `0x8030B7F4` | 5792 bytes | party and inventory (`801A4384`–`801A438C`) |
| +5808 | `0x80311AC0` / `0x80311AC4` | word | map number |
| +5812 | `0x80311AC8` | byte | map letter |
| +9072 | `0x80310B3C` | 3416 bytes | all flags (`801A445C`–`801A4468`) |
| +12488 | `0x80310A1C` | 288 bytes | byte variables (`801A4520`–`801A4528`) |

After that it calls `fn_801CAE98`, then `fn_801F7B04(20000)`. Those three regions plus the map words are the whole story state.

### 2. The script interpreter [V]

**File format.** `me*.sct` files are AKLZ-compressed and big-endian: `u32, u32, u32 count`, then `count` entries of `(u32 offset, char name[16])`, then code at `12 + 20*count`.

**Dispatch.** `fn_80211298` looks each opcode word up in the table at `0x802F7940` (12-byte entries, handler pointer at +8, 266 opcodes):
`80211350 mulli r0,r5,12` … `80211368 lwz r12,8(r5)` … `80211378 bctrl`

**Per-frame tick.** `fn_80212130` runs 384 task slots of 52 bytes at `*(0x8030CEB0)`. It is called only from the field's state-8 arm (`80101A34`) and from the 131e pre-run (`801019D4`). So scripts do not run during a warp.

**Flag tests are expression operands, not an opcode.** `scptAnarize` (`0x801F6120`) is an RPN evaluator; token 29 ends an expression.
- Operand kinds:
  - `0x04000000` followed by an immediate float
  - `0x08…` a fixed-point constant
  - `0x1000000|n`: B[n]
  - `0x2000000|n`: flag n (tokens `0x2…`/`0x3…`)
  - `0x4000000|n`: float variable
  - `0x5000000|n`: "sys" variable
- The flag test itself:
  `801F6D38 rlwinm r5,r6,29,11,29 ; 801F6D3C rlwinm r6,r6,0,27,31 ; 801F6D40 lwzx r4,r4(=0x80310B3C),r5 ; 801F6D44 slw r5,r7(=1),r6 ; and/neg/or/rlwinm 1,31,31`
- Operators 0–22 (jump table `0x802F74C8`): `< <= > >= == != & | && || = * / % + -`.
- Sys variables:
  - sys[0] = gold `0x8030BB40`
  - sys[1] = `0x8030BB3C`
  - sys[2..7] = HP at +24 of characters 0..5
  - sys[74] = byte `0x8030B7FF`
  - sys[15] = int `0x8030E420`
  - other n: int at `0x8030E3E4+4n`

**Core opcodes:**
| Op | Handler | What it does | Proof |
|---|---|---|---|
| 0 IF | `fn_801F6044` | evaluates the expression; if the result is 0.0 it jumps by the next word | `801F6070 lfs f0,-16020(r2)` (=0.0), `801F6078 bne`, `801F6088 rlwinm r0,r0,0,0,29 ; add` |
| 3 | | SWITCH | |
| 5 / 6 / 7 | | set B / int / float variable | |
| 6, sys[0] | | gold, clamped to 99,999,999 | `801F5E5C = 0x05F5E0FF`, `801F5E8C stw r0,844(r3)` |
| 6, sys[1] | | clamped 0–255, written to `0x8030BB3C` (Swashbuckler rating; the title table at `0x802C8E54` is "Vyse the Ninny" … "Vyse the Legend") | |
| 10 / 11 / 12 | | GOTO / CALL / RET | |
| 17 FLAGSET | `fn_801F5B14` | | `801F5B78 rlwinm r6,r0,29,3,29` … `801F5B98 or` / `801F5B9C stwx r0,r5,r6` |
| 18 FLAGCLR | `fn_801F5A74` | | `andc` |
| 19 | `fn_801F59C0` | toggle | |
| 20 ITEMADD / 21 ITEMDEL | `fn_801EFDC0` / `fn_801EFB74` | | |
| 43 WARP | `fn_802073B4` | raw offset to a name string, handed to `fn_801002D0` | same as `fn_80100178` without the r13-29004 store |
| 157 JOIN(ch) | `fn_800FF6B4` | | |
| 158 LEAVE(ch) | `fn_800FF5D0` | | |

**Engine-side flag users:**
- Party membership:
  - Flag 1026+ch means "has joined before", flag 1032+ch means "in the party now" (`fn_800FF6B4`: `addi r0,r30,1032` / `addi r0,r30,1026`).
  - So the word at `0x80310BBC` that FINDINGS §11 calls a story flag word is actually party membership. Vyse and Aika are `0x30C`.
- Discoveries: `fn_801EF300` counts flags 2048–2166 (`addi r3,r9,2048`, ctr 119).
- Crew (22 slots): 1039+n and 1061+n (`fn_801E4BBC` / `fn_801E4BF4`). [the "crew" reading is I]

### 3. Maps choose what to play from flags [V]

**`me200a` loop:**
```
0064 IF (FLAG[1930]==0)   ; init clears 1930
0080  IF (FLAG[2]==0)
009c   CALL me200aa03     ; the event; its first real op (+0x110) is FLAGSET 2
00a4   FLAGSET 1930
00c4   WARP "me101b.sct"
```
Once flag 2 is set, the loop does nothing, so no camera or player is placed. That is the black `a200a`: the map was not broken and the warp route was not at fault.

**`me103a` loop:**
```
00ec IF (FLAG[1856]==0) { FLAGSET 1856; FLAGSET 1857; CALL ship
0130  IF (FLAG[18]==0) { … CALL 039a8 = me103aa19 … }   ; me103aa19 begins 039b8 FLAGSET 18
030c  else SWITCH sys[15]: 20000 (loaded save), 1031 (from 103b), 20 (from 002a), 990 (from 099a)
```
- `sys[15]` is "the map you came from". `fn_801F7B04` does `stw r3,5504(0x8030CEA0)`, and `fn_80100178` passes it `oldmap*10 + letter`.
- The `ship` routine picks the docked ship by B[6]: 0 / {5,7} / {6,8..11}.
- The only other things `me103a` reads are B[0], B[1], B[7], B[44] and flags 55, 316 and 2086 (later-part revisits).

### 4. Story order and the "chapter" [V, except where marked]

**The developer part select, `ME355A.SCT` (map `a355a`).** Its menu text is Shift-JIS: 「各パートに飛びたい」 ("I want to jump to a part"), 「Bパートへ」 ("to part B") … up to L. Each option CALLs routines `a`, `b`, … cumulatively, then JOIN/LEAVEs party members, then WARPs:
| Part | Party | Destination |
|---|---|---|
| B | Vyse, Aika | `me002b` |
| C | + Drachma | `me004a` |
| D | Vyse, Aika, Fina, Drachma | `me002e` |
| E | same | `me008b` |
| F | same | `me010a` |
| G | Vyse, Gilder | `me230a` |
| H | Vyse, Aika, Fina, Enrique | `me018a` |
| I | same | `me019b` |
| J | same | `me099a` |
| K | Vyse, Aika, Fina | `me099a` |
| L | Vyse, Aika, Fina, Gilder | `me099a` |

Routine `a` (all of part A) sets flags in this order: 1,2,3,4,5,6,7,8,9,23,10,21,22,19,11,12,18,20,13,14,15,16,17. It also sets 1643–1655 (Shrine Island's own flags), 1280–1307, B[6]=0, B[7]=2, B[45]=1, and gives items 326–331 (all six Moon Stones).

**Where each part-A flag is set:** 0 in 299a, 1 in 201a, 2 in 200a, 3 in 101b (event a04), 4–6 in 101c, 7 in 032a, 8/12/19/21/22 in 002a, 9/10/23 in 002d, 11 in 202a, 18 in 103a, 13/20 in 103b.

**The gates in `me002a` confirm the order:**
- `IF 7 && !8`, `IF 11 && !12`, `IF !21 && 10`, `IF 21 && !22 && !19`, `IF 19 && !11`.
- `IF 13 && !14 → WARP me103a`. That warp is the later return to Shrine Island.
- The first arrival comes from `me099a` handler M04001 (`WARP "me103a.sct"`).

**Counters:**
- No single chapter counter drives the scripts.
- B[6] (`0x80310A22`) is read by engine code in 19 places. The part presets set it to 0, 5, 7, 7, 7, 2, 8, 8, 10, 11, 11, 14. [meaning I]
- B[2..5] are always set as a pair of (part, step) values right after a story flag. For example, `101b` sets FLAGSET 3 then (0,3,0,4), and `202a` sets (0,12,0,13). This is likely the save-screen synopsis pointer. [I]
- The string "Flag 43(scenario progress)" (`0x802B0DEC`, used at `8009CA2C`) refers to B[43] and belongs to a side system. [V]

### 5. State at the start of Shrine Island, as in normal play
| What | Value |
|---|---|
| Flags set | 0–12, 19, 21, 22, 23 → `0x80310B3C = 0x00E81FFF` [V] |
| Flags clear | 13–18, 20, 24–31 |
| Flag 1280 (Pirate Isle, set by `002a` init) | set [V]; purpose [I] |
| B[6] | 0 |
| B[7] | 1 (set by `202a`; `103a` later sets 2) |
| B[45] | 0 (002a sets 1 after flag 14) |
| B[2..5] | 0, 12, 0, 13 |
| Party | Vyse and Aika only (`0x80310BBC` = `0x30C`), which the run already has |
| Items | Green and Red Moon Stones, given in `201a`, already held; Purple (328) comes from an optional Pirate Isle NPC after flag 12 |
| `sys[15]` | 990 (arrived from `099a`) |

### 6. Party, items, gold [V]
**Character records** at `0x8030B7F4 + 92*ch` (0 Vyse, 1 Aika, 2 Fina, 3 Drachma, 4 Enrique, 5 Gilder; names come from templates at `0x802C4860`, stride 152):
- +0: name
- +11: level byte (written by the EXP routine `fn_801F2A34` with `stb r25,11(r20)`; whether the screen shows it as-is or +1 is unverified)
- +13 / +14: MP / max MP (max 99)
- +16 / +18 / +20: weapon / armor / accessory ids, as shorts (−1 = none)
- +24 / +26: HP / max HP (max 9999)
- +36: EXP (int, max 99,999,999)
- +58..+67: five stats
- +68..+91: six magic-EXP ints

**Other addresses:**
- Active party: 4 bytes at `0x8030BB1C` (0xFF = empty, sorted); count byte at `0x8030B7A8`.
- Gold: `0x8030BB40`.

**Inventory slots** are 4 bytes: short id, byte count (max 99), one more byte; id −1 means empty. Lists by id range (`fn_801F4C24` / `fn_801EFDC0`):
| Ids | Kind | List | Slots |
|---|---|---|---|
| 0–79 | weapons | `0x8030BB48` | 80 |
| 80–159 | armor | `0x8030BC88` | 80 |
| 160–239 | accessories | `0x8030BDC8` | 80 |
| 240–319 | items (names at `0x802C7C34`, 36-byte records) | `0x8030BF08` | 80 |
| 320–399 | key items (names at `0x802C8774`, 22-byte records) | `0x8030C048` | 80 |
| 400–439 | not identified | `0x8030C200` | 40 |
| 440–479 | not identified | `0x8030C2A0` | 40 |
| 480+ | not identified | `0x8030C188` | 30 |

FINDINGS says `0x8030BC88` and `0x8030BDC8` are the battle menu's command lists. By this reading they are the armor and accessory lists; that needs a check.

**Levels by poke:** poking EXP alone does not grant stats. `fn_801F2A34` adds stat growth only for levels crossed during a call. The game's recompute-from-EXP, `fn_801F3024`, runs only at New Game and in the stage-picker's debug half (`800FFD74`–`800FFD90`, which gives 500 EXP). To give levels by poke you have to write the stat fields too.

### 7. Not established
- **What clears flag 1856 on a warp.** `me099a` and `me101b` both leave 1856 set, and nothing on the warp path clears it. Yet the earlier name-warp run did play the Shrine Island arrival. The only non-load stores I found are `8015BE18` and `8015C10C` in `fn_8015BB58`, under unread conditions. The recipe clears it explicitly, which is what loading a save does.
- **What B[7] and B[45] mean.** No fixed-address reader.
- **B[2..5] as a synopsis pointer.**
- **Linear disassembly is incomplete.** Opcodes with raw or variable-length operands (23, 24, 25, 33, 69, 144, and those marked 65534 in the table) throw off the linear pass, so some blocks were not decoded.

### RECIPE (one run)
Use the `battle` preamble, including `3600:a@150`, which keeps pressing A through all the dialogue. Set `SOA_RENDER=1`, `SOA_SNAP=100`, `SOA_TRACE=1`, `SOA_WATCH=0x80310B3C`, run to frame 22000, and pass `--log build/scenario-shrine.log`.

```
SOA_POKE=15000:0x80310B3C=0xE81FFF,15000:0x80310C24=0,15000:0x80310C28=0,15000:0x80310C2C=0,15000:0x80310C30=0,15000:0x80310C34=0,15000:0x80310C38=0,15000:0x80310BDC=1,15000:0x80310A1C=0xC,15000:0x80310A20=0xD0001,15000:0x8030E420=990,15000:0x80305CF0=0x4D453130,15000:0x80305CF4=0x33412E53,15000:0x80305CF8=0x43540000,15000:0x80311AC0=103,15000:0x80311AC4=103,15000:0x80311AC8=0x61000000,15000:0x80311AEC=15,19000:0x80310B3C=0x3,19000:0x80305CF0=0x4D453230,19000:0x80305CF4=0x30412E53,19000:0x80305CF8=0x43540000,19000:0x80311AC0=200,19000:0x80311AC4=200,19000:0x80311AC8=0x61000000,19000:0x80311AEC=15
```

What to look for:
1. **`[poke] 26 poke(s) armed`.**
2. **`80310B3C <- 00E81FFF (was 00000007)`.** Flags 0–2 set by the opening; `0000000F` if event a04 already ran. The `was` value on `80310C24` shows whether flag 1856 (bit 0) was still set.
3. **After the warp:** `LoadStart /field/a103a.mld`, then `/field/a103aa19.mld`, then `m5030000` and `e6a019` (the same loads the earlier name-warp run showed).
4. **The key check, a watch hit:** `[watch] 80310B3C/4 = ec1fff` from `fn_801F5B14` (block and lr between `0x801F5B14` and `0x801F5BB0`, lr probably `801F5B64`). That is FLAGSET 18 at the start of `me103aa19`, meaning the arrival event ran on the poked state.
5. **Frames:** from about 15200, Aika on the ledge. By about 15400, "Vyse! Over there! Look at the size of that hole!".
6. **Control at 19000**, which proves the flag branching: the `was` on `0x80310B3C` should be `00EC1FFF`. Flag 2 is now clear, so `a200a` should *draw* its event instead of going black. The watch should show `= 7` from `fn_801F5B14` (FLAGSET 2). The trace should then show `/field/a101b.mld` loading with no poke, from the script's own `WARP "me101b.sct"`.

If step 4 appears and the frames stay black, the renderer or the route is at fault, not the story state. If step 4 never appears, check the `80310C24` `was` value and the loop's `IF FLAG[1856]`.

My scratch tools and disassembly dumps are in (a session scratchpad, not kept):
- `sctdis.py`: the `.sct` disassembler; usage `python sctdis.py <sct> [entry…]`
- `me355A.txt`, `me103a.txt`, `me002a.txt`, `me002d.txt`, `me101b.txt`, `me099a.txt`: the disassembled scripts
- `flags.pkl`: flag setters and readers for all 258 scripts