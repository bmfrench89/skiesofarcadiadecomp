<!-- Written 2026-09-23 by a read-only research agent from the disassembly, the DOL and the
decompressed scripts; nothing here was run when it was written. Claims marked [V] were read
from quoted instructions; [I] is inference. Check a claim against a run before building on it,
and record what a run shows in docs/FINDINGS.md, not here. -->

**Answer: saving and loading in Skies of Arcadia Legends (GEAE8P), and how a scripted run can do both**

A save can be started by poking one flag. Script opcode 138 (a save point) and the field pause menu both work by setting the word at `0x803473B4` to 1. When it is 1, a task that lives in every loaded field opens the game's own save/load menu in save mode. That menu then needs about three A presses to write the file `SA_LEGENDS.00N` to the card. Loading goes through Continue at the title: title scene 16 opens the same menu in load mode. That also needs three A presses. It restores the data and restarts the field module on the saved map. The menu's context is on the heap and no global points to it, so its A presses cannot be replaced by pokes.

I did not run anything; everything below is from the disassembly and the disc. "Verified" means I read the instructions quoted. "Inferred" is marked where it applies.

---

### 1. What opens a save (verified)

**The request words**
- `0x803473B4` (r13-29548) is the request.
- `0x803473B0` (r13-29552) is the variant: 1 means the world-map style save.
- `0x803473C4` (r13-29532) is the menu result: 0 when the menu opens, 1 when it closes, 2 when a load is cancelled.
- The only two setters:
  ```
  fn_80123E9C: 80123E9C li r3,1 / li r0,0 / stw r3,-29548(r13) / stw r0,-29552(r13)   (request, variant 0)
  fn_80123E8C: li r0,1 / stw r0,-29548(r13) / stw r0,-29552(r13)                     (request, variant 1)
  ```
- It is read in four places:
  - the save-point task (0x80123D68);
  - the script tick, which freezes while it is 1: `8021214C lwz r0,-29548(r13); cmpi 1; beq -> exit`;
  - the pause-menu task (0x800D840C);
  - opcode 138's poll mode (0x801FED90).

**The save-point task** (`fn_80123CBC`)
- It is created by `fn_80123EE4`. That is called from `fn_80101264` at 0x80101290, which the field load `fn_801015AC` calls at 0x80101660. So the task exists in every loaded map. Its pointer is at `0x80346EC0`.
- The teardown `fn_80101158` removes it through `fn_80123EB0`.
- Its states:

| State | What it does |
|---|---|
| 1 | `80123D68 lwz r0,-29548(r13); cmpi 1` → fade out (`fn_801CBBAC`), go to state 2 |
| 2 | Waits while `0x80347508` is 1 |
| 3 | `80123DE0 bl fn_801A21F8`, with r3 = the parent task at `0x803475A0` and r4 = the location id. The id is 60 if the variant is 1, otherwise the signed byte at `0x80310A48`. If the map is not 99 it pauses the field. |
| 4 | Waits for `0x803473C4 == 1` |
| 5 | `80123E5C stw 0,-29548(r13)` clears the request, back to state 1 |

**Trigger 1: script opcode 138 (0x8A), the save point**
- The command table is at `0x802F7940`, 12-byte entries. The dispatcher does `80211350 mulli r0,r5,12` … `80211368 lwz r12,8(r5); bctrl`.
- Entry 138 is at `0x802F7FB8` and points to `fn_801FED58`. With flag bit 0 set it runs:
  ```
  801FED70 lwz r3,28(r4); addi r0,r3,4; stw r0,28(r4); bl fn_800FF780
  ```
  So it takes no operands. `fn_800FF780` just does `bl fn_80123E9C`.
- In the decompressed scripts (AKLZ, big-endian words) the word `0x0000008A` occurs 59 times in 54 scripts. Every occurrence is inside an `M04xxx` entry, with the same template around it (`… 5 1000002C … A 1D 8A 29 5000000A 1D 12 …`).
- In `me101b.sct`, the map a normal run stands in, it is entry **`M04013`**. In `me103a.sct` it is `M04100`.
- Inferred: `M04013` is event id 4013, using the same naming as the hold exit (`M06500` is event 6500). I did not establish which object fires it or where that object stands.

**Trigger 2: the field pause menu (the world-map style save)**
- The field player task's state-3 body is `fn_800D1630`. It tests the pad edge word:
  - bit 0x1000 (START) calls `fn_800D84AC(0)`;
  - bit 0x800 (Y) calls `fn_800D84AC(1)`, which goes straight to entry 0.
- `fn_800D84AC` opens the menu only when all of these hold:
  - `0x803473DC == 0`, `0x803473E4 == 0` and `0x80347444 == 0`;
  - `0x80310BC0 & 0x80000000` is clear;
  - `fn_80227E84(99998)` is non-zero;
  - `fn_800FF48C(0x800D81E8, 0)` is non-zero.
- The menu task `fn_800D8214` has three entries:
  - entry 0 creates a 3580-byte menu task (`fn_800EDF38`);
  - entry 1 is ship-related (`fn_800CE2B4`);
  - entry 2 reaches `800D8378 li r0,8; stb 25; 800D8380 bl fn_80123E8C`, which is the save request, variant 1.
- The menu's input:
  - UP (0x8) and DOWN (0x4) move the cursor;
  - confirm is the mask at `0x80311A00`, which is 0x100 (A);
  - cancel is the mask at `0x80311A04` (0x200, B) or START.
- The entry list comes from the byte at `0x80310A2D`:
  - value 0 gives all three entries;
  - value 1 gives entries 0 and 2;
  - value 2 gives entry 1 only.
- The only direct stores to that byte I found both write 0: `scptInitial` at 0x80212814 and an initializer at 0x801CB01C.
- Not established: what resource 99998 is, and therefore on which maps this menu opens at all.

### 2. The save/load menu (verified)

**Opening**
- `fn_801A21F8` opens it for saving. It sets `0x803473C4 = 0`, creates a task running `fn_8019E248`, and gives it a 624-byte context at task+36. Context +1 is 0 (save mode) and +16 is the location id.
- `fn_801A2304` opens it for loading (ctx+1 = 1). It refuses if `0x80347568` is 0.

**Dispatch**
- The state byte is task+25, and the jump table is at `0x802EBD30`.
- If `0x803475D8` is non-zero the menu is forced to state 31.
- The on-screen text comes from `fn_801A64B4(task, n)`, which indexes the string table at `0x802B6810`. Examples: 1 "Save to a Memory Card…", 5 "Please select a file to save to.", 6 "Save to this file. Is this ok?", 7 "overwrite?", 8 "Now saving…", 10 "Saving completed.", 14 "Load this file…", 16 "Loading completed."

**Input**
- The menu reads the edge word `[[0x80311A60]+8]`: A is 0x100, B 0x200, X 0x400.
- UP/DOWN come from `fn_801C09F8(0,4)` and `fn_801C09F8(0,5)`, which map through the mask table at `0x802C3A68` to 0x8 and 0x4.
- States 4, 9 and 15 ignore all input while their widgets are animating.
- States 3, 13 and 14 only use A, to skip the animation.
- X (0x400) jumps straight to exit (state 30) from states 3, 4, 9, 15 and 21. The tests are at 0x801A14E0, 0x801A142C, 0x801A0ADC, 0x8019FCBC and 0x8019EF04.

**The save path**

| Step | What happens |
|---|---|
| State 1 | Takes the snapshot: `801A18B8 bl fn_801A68C4` → `bl fn_801A456C; stw r3,40(r31)`. The save captures the state at the moment the menu opens. |
| State 2 | Probes both slots. In the port, slot B is empty (`runtime/exi.c`). |
| State 4 | A selects the card, then states 5 and 6 start the scan task `fn_801A2D60`. The scan checks up to 7 names; a file slot is only offered if there is room (min(7, free/24576)). |
| State 9 | The file list. A on an empty slot leads to message 6 and state 14. |
| State 15 | Yes/No, with Yes as the default. A calls: `8019FBF8 bl fn_801A39B4` (the name, `"SA_LEGENDS"` + `".%03d"`), `8019FC10 bl fn_801A41EC`, message 8. |
| States 17, 20 | Run the writer `fn_801A3B30`, one step per frame (step table at `0x802EBDE0`): mount, [delete], create (`801A3C54`, r5 = 24576), attributes 4, header, write (`801A3E70`), set status, unmount. |
| State 21 | "Saving completed.", then the menu goes back to the file list. It does not exit by itself. |

**The saved data**
- `fn_801A456C` builds the 12,800-byte game block:
  - +0: `"EA_LEGEND v1.01"` (copied from 0x802EBDD0);
  - +16: 5,792 bytes from `0x8030B7F4` (party);
  - +5808: the word at `0x80311AC4`; +5812: the byte at `0x80311AC8`;
  - +5864..5916: position data from `0x8030A7CC..A7FC`;
  - +9072: 3,416 bytes from `0x80310B3C`, the story-flag bitset;
  - +12488: 288 bytes from `0x80310A1C`.
- `fn_801A68C4` adds the location id (+12776) and the byte at `0x80310A4E` (+12778).
- `fn_801A41EC` adds a 10-byte time stamp (+12786) and the XOR of 3,199 words (+12796). It then copies the block to offset 5184 of a zeroed 24,576-byte image.
- The writer's step 6 puts the comment "Skies of Arcadia Legends" at +0, a second comment line at +32, the banner at +64 and the icon at +3648. They come from `/ea_mc_banner.tpl` and `/ea_mc_icon.tpl`, which are on the disc.

**The load path, from Continue**
- Title scene 13: `80228DDC` stores 16 when title object byte 24 is 1.
- Scene 16 (`fn_80228B40`) creates the task `fn_801D8B94`, whose state 3 does `801D8C6C bl fn_801A2304` with r4 = 1.
- The reader `fn_801A4070` opens the file (`CARDOpen` at `801A413C`) and reads 24,576 bytes (`CARDReadAsync` at `801A4184`).
- State 18 checks the XOR (`fn_801A4684`, against +12796) and then calls `8019F50C bl fn_801A4354`, which restores:
  - `0x8030B7F4` ← +16 (5,792 bytes);
  - `0x80311AC4` and `0x80311AC0` ← +5808, and the byte at `0x80311AC8` ← +5812;
  - the position data;
  - `0x80310B3C` ← +9072 (3,416 bytes) and `0x80310A1C` ← +12488 (288 bytes);
  - `801A4544 stw 1,-29004(r13)`, so field state 1 skips the resolver;
  - `fn_801F7B04(20000)`.
- On exit, `8019E2E4` sets `0x803473C4 = 1` and clears the top bit of `0x80310BC0`.
- Scene 17: a result of 0 means loaded, so it goes to scene 18 and calls `80228B20 bl fn_801DBE6C(6)`. That sets module 6 and zeroes the field state word at `0x80311AEC`.

**How Continue gets enabled**
- `fn_801D91F4` calls `fn_801A3510`. That is the title's per-slot card poll, which finds any of `SA_LEGENDS.000`–`.006`. If the poll returns 1, `801D9254` puts the cursor on Continue the first time.
- So with a save on the card, the preamble's A press at 2040 takes Continue.

### 3. Not established
- How many frames pass between the poke and the menu reaching state 4. I infer under 300, from fade speeds of 3.0 and 8.0.
- What the three post-load calls (`fn_801CAE98`, `fn_801EF7E0`, `fn_8021B2B4`) do.
- Whether an X press in the field has a side effect.
- How to return to the title within the same run. The game's soft-reset path writes `0x803476D8 = 0` and `0x803476DC = 1` (0x801DC1E0 and 0x801DC1DC), which makes `main` shut down and re-initialize. Poking those two words would emulate it, but that is untested and the port may not survive the re-initialization. Use a second boot instead.

---

### Recipe A: save from the field in one run

Use a copy of the card; never write to `build/cards/slotA.raw`. Run only one `soa.exe` at a time.

```powershell
New-Item -ItemType Directory -Force build\savetest | Out-Null
Copy-Item build\cards\slotA.raw build\savetest\card.raw
python tools/cardformat.py verify build/savetest/card.raw
python tools/scenario.py run battle --frames 16600 --log build/scenario-save.log `
 --env SOA_CARD=build/savetest/card.raw --env SOA_TRACE=1 --env SOA_SNAP=50 --env SOA_WATCH=0x803473C4 `
 --env "SOA_POKE=15000:0x803473B0=0,15000:0x803473B4=1" `
 --env "SOA_PAD=1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2200:start,2240:a,2400:start,2440:a,2600:start,2640:a,2800:start,2840:a,3000:start,3040:a,3200:start,3240:a,3600:a,3750:a,3900:a,4050:a,4200:a,4350:a,4500:a,4650:a,4800:a,4950:a,5100:a,5250:a,5400:a,5550:a,5700:a,5850:a,6000:a,6150:a,6300:a,6450:a,6600:a,6750:a,6900:a,7050:a,7200:a,7350:a,7500:a,7650:a,7800:a,7950:a,8100:a,8250:a,8400:a,8550:a,8700:a,8850:a,9000:a,9150:a,9300:a,9450:a,9600:a,9750:a,9900:a,10050:a,10200:a,10350:a,10500:a,10650:a,10800:a,10950:a,11100:a,11250:a,11400:a,11550:a,11700:a,11850:a,12000:a,12150:a,12300:a,12450:a,12600:a,12750:a,12900:a,13050:a,13200:a,13350:a,13500:a,13650:a,13800:a,13950:a,14100:a,14250:a,14400:a,14550:a,14700:a,14850:a,15300:a,15450:a,15600:a,15750:a,15900:a,16050:x,16200:x"
python tools/cardformat.py show build/savetest/card.raw
```

This is the battle preamble with its A-every-150 repeat stopped at 14850. After 15000 there are 5 A presses and 2 X presses. The worst case needs 4 A presses; if one is spare, it only starts an overwrite, and X then exits.

What shows it worked:
- The log has `[poke] 2 poke(s) armed` and the two poke lines at frame 15000.
- The watch prints `803473C4/4 = 0 … lr 80123DE4` when the menu opens and `= 1 … lr 8019E310` when it closes.
- The trace shows `CardMountAsync lr 801A2564` for the scan and the writer, and `CardWrite` with r4 = `0000A000`, `0000C000`, `0000E000` and r5 = `2000` for the file data.
- The exit line reads `[exi] … 65536 written` for one save, or 147,456 if the spare A caused one overwrite. This is predicted from the CARD library's write pattern: 8 sectors per new save.
- The snapshots every 50 frames show the menu text (messages 1, 5, 6, 8, 10).
- `cardformat.py show` lists one file: `GEAE 8P SA_LEGENDS.000`, 3 blocks, start block 5, chain 5 6 7, permission 0x04.

### Recipe B: load it back via Continue (second boot, same card)

```powershell
python tools/scenario.py run battle --frames 4000 --log build/scenario-load.log `
 --env SOA_CARD=build/savetest/card.raw --env SOA_TRACE=1 --env SOA_SNAP=50 --env SOA_WATCH=0x80311AEC `
 --env "SOA_PAD=1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a,2840:a,3040:a"
```

What shows it worked:
- `TitleSceneChange` prints r4 = `0000000C`, then `0000000D`, then **`00000010` and `00000011`**. Those two mean Continue; this port has never entered scene 16. If it prints `0000000E` instead, the A took New Game, meaning the poll did not see the save.
- The field state watch shows `0 … lr 80228B24`, then 1, 3, 5, 7, 8. There is no 15 and no 2; New Game shows `f`, then `0 … lr 80228BB8`.
- A `LoadStart /field/a101b.mld` (the map you saved on) appears within about 1,000 frames of boot. No New Game run loads that map before frame 14710.
- The exit line reports 0 bytes written.
- The frames show the saved room.

### Other routes to try (not tested)
- **Pause menu**: on a map where it opens, press START, DOWN, DOWN, A instead of poking. This gives the variant-1 save, whose location name is looked up in `/field/wmaparea.BIN`.
- **The save point itself**: warp to `a103a` (it renders) and trigger its save point, event `M04100`. This needs the player's position.

The analysis scripts I used are in a session scratchpad, not kept; nothing in the repository was changed.