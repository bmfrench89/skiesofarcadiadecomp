<!-- Written 2026-09-24 by a read-only research agent from the disassembly, the DOL, the
decompressed scripts and the extracted MLDs; nothing was run. Claims marked [V] were read from
quoted instructions, bytes or disassembled script; [I] is inference. Check a claim against a
run before building on it, and record what a run shows in docs/FINDINGS.md, not here. -->

## Content systems: maps, objects, dialogue, shops, cameras, the world map and the file table

**Short answer.**
- A field map is one geometry file, `/field/aNNNx.mld`, plus one script, `/field/meNNNx.sct`. Both names come from the same two words: the map number at `0x80311AC4` and the letter at `0x80311AC8`. Every other asset is named by the script, by an object inside the MLD, or by a fixed table.
- NPCs, doors, chests, save points and trigger volumes are not created by opcodes. Each is an **index entry in an MLD**. The entry's type string picks the object's code from a 185-entry name table. Loading an MLD, whether the map or a sub-model loaded by script op 23, turns every entry into an object.
- Interaction goes through the object's **16-bit id**:
  - Pressing A near an object with id 3000–4999 runs the script entry named `M%05d` (for example `M03003`).
  - Walking into an object with id 6000–6999 does the same.
  - The entry's leading `LABEL` operand is the condition that decides whether the object is live.
- The text hook is `fn_8010BBD8(window, text)`. Every field message and choice passes through it.
- Nothing in the executable lets one map number borrow another's geometry. The port's file table is easy to extend, though, so an alias costs one FST entry.

Each claim is tagged: [V] I read it in the disassembly, the bytes or the decoded scripts; [I] I inferred it. r13 = `0x8034E720`, r2 = `0x80350000`.

Method, so the next reader can repeat it:
- The scripts were decoded with SALSA's own decoder (`github.com/SoAModTools/SALSA`, cloned into the scratchpad). Its typed operand layouts (`bi_defaults.py`) agree with this DOL's handler table in 265 of 266 entries. Op 25 is the exception, 4 bytes off.
- The repo's `tools/sct.py` cannot decode ops 24, 25, 144 or 155, whose raw offsets desynchronise it. SALSA's layout table is the fix.

---

### 1. What a field map loads [V unless marked]

| File | Name built by | Code | Chosen by |
|---|---|---|---|
| `meNNNx.sct` | `sprintf("%sme%03d%c.sct", prefix, [0x80311AC4], [0x80311AC8])`, the format at `0x802B2364` | `fn_80101264`: `80101328` formats into `0x8030A5D4`, `80101360 bl scptLoad` (`fn_801F7158`) | map words |
| `aNNNx.mld` | `"%sa%03d%c.mld"` (`0x802B2374`) into `0x8030A4D4` | `fn_801015AC`: `801017B8` sprintf, `801017C8 bl fn_80109E7C` (async load; completion `fn_80109DCC` → `fn_8010A278` instantiates the index) | map words |
| `aNNNx.ect`, `aNNNx_ep.enp` | `0x802B1320` / `0x802B1330` | `fn_800C24CC`, called at `80101364` (see `encounters.md`) | map words |
| sub-models, e.g. `a103aa19.mld` | the script's own string | **op 23** (`fn_801FF13C` → `fn_80100424`: prefix + name, skipped if already loaded, then `fn_80109E7C`; the op waits until `fn_8010038C` reports the model done). **op 113** (`fn_801FF05C`) only waits. **op 110** (`fn_801FF0F8` → `fn_801003F4`) releases. | **script** (op 23: 1,088 uses; op 110: 1,020; op 113: 749) |
| music and effect banks, e.g. `m5030000`, `e6a019` | `"/sound/" + name + ".mlt"`; the `.mlt` comes from r2-15976 | **op 69** (`fn_801FA1D0` → `fn_80219378`). Op 51 plays from a bank (`fn_80217FF4`); ops 54, 215, 248 and 250 also take sound names. | **script**. `me103a` loads `m5030000` and `k8030000` in its `soundsakadume` entry and `e6a019` in the event entry. |
| house interiors, e.g. `a002ab.mld` | `"%sa0%02d%c%c.mld"` (`0x802B174C`): **committed** map number, letter, and `'a'+params[8]` of the house object | `fn_800DE9BC` (`800DEFB0`–`800DF028`) | map words plus an object parameter. Maps below 100 only, because of the `a0%02d` format. |
| `/player.mld` | fixed (`0x802B31A8`) | `fn_8011A2A8`, from the load at `801016A0` when not in sky mode | fixed |
| `sora0N.mld` | letter table `0x802E711C` | `fn_8016ACA0` (sky maps only; `ship-worldmap.md`) | table |
| world tiles `fielRCx.mld` | `"fiel%d%da.mld"` (`0x802B141C`); letter `'a'+B[n]` from the table `0x802E0F40` (27 tiles), otherwise `'a'` | `fn_800C7F64`, map 99 only; also `a099aa.mld` (`0x802B1410`) | a 6×7 grid, streamed by distance (`fn_800C8C54`). The grid wraps: column distance is clamped to ±6, row distance to ±5 [I]. |
| ship battles: `sbek0000.mld`, `HrsBin_sbp.mll`, `rNNNx.tec` (`0x802B4104`) | fixed / map words | `fn_8012A634` → `fn_8015C644`, only when map ≥ 500 | map words |
| per-map stage task | `"stage%04d"` (`0x802B2440`) looked up in the object table (below) | `fn_801015AC` `801016DC`–`80101758` | table: special handlers exist only for 0099, 0107, 0122, 0209 and 5555. Every other map gets `0x80100AA4`. |

**Two corrections:**
- The map loader has no alternative geometry path. `0x8030A4D4`, the path buffer, is only ever cleared (`80101348`) or sprintf'd (`801017B8`).
- The only per-map tables are the `stage%04d` handlers, the sky-map list (`fn_800C8D90`) and the map-99 letter override.

**Raw files are accepted.** The async and sync readers test the first bytes for the `AKLZ` magic plus a float, and decompress only when they match (`801C65BC`–`801C660C`, again at `801C6870`). A modder does not have to recompress.

### 2. NPCs, doors, chests, triggers: MLD index entries [V]

**The index entry is 0x68 bytes.** Offsets are SPICE's; the "Read by" column is what the engine does with each field:

| Off | SPICE name | Read by |
|---|---|---|
| +0x04 | tblId | **The object id.** `fn_8010A278` masks it to 16 bits (`rlwinm 16,31`). Ids 50900–50999 become the player pointer `0x80347450` (`80101030`–`80101048`). |
| +0x10 | functionParametersPointer | `[count, words…]`. Word 5 goes to act+374, word 7 to act+366 (`fn_80100BF8`). **Word 8** is the treasure index (op 154) and the interior letter (houses). Word 13 is the default Discovery number (op 177). |
| +0x14, +0x1C, +0x20 | object, motion and texture pointers | Hit shapes come from the model (`fn_80222C80` → `fn_801C7D0C`). The motion goes to act+232. `kmap` uses the texture. |
| +0x24 | functionName (20 bytes) | **The type string.** Looked up in `0x802E2888`. A name starting `comm` is skipped (`80100E98`). |
| +0x38..0x3F | "unknown" | Runtime scratch: the first task at +56, an instance count at +60 (`fn_80100BF8`). |
| +0x44 / +0x50 / +0x5C | position, rotation, scale | Copied to act+56..64. Rotation is multiplied by 182.0444 into angle units (r2-25840) at act+68..76. Scale goes to act+80..88. |

**The type table.** `0x802E2888` has 185 records of `{char name[16]; void (*task)()}`, looked up by `fn_80100E68`.
- The NPC and object types include `man`, `objPeopleAct`, `treasure`, `kdoor1`, `door2`, `doorwall`, `walluv` (the save point in `a103a`), `kmap`, `motscpt`, `eventhook`, `hasigo1-3`, `rope1/2`, and the world-map types `fldIsland`, `fldName`, `fldHakken`, `fldHakken2`, `fldManshipA`–`F`, `fldEfcontrol`.
- A name the table lacks falls back by id:
  - Below 10000 it gets `0x8010092C`, which treats the name `goscript` (`0x802B2434`) as an invisible trigger volume.
  - 10000 and above get `0x8010DDBC`.
- **Hit volumes exist only for types in a second table**, `0x802EE7C0` (55 records of 28 bytes: prefix, suffix, class; `fn_801C8A0C`). For example, `objPeopleAct` → `0x7800001E`, `treasure` → `0x78C0002A`, `goscript` → `0x80000008`, `man` → `0x78400016`. A type absent from it cannot be talked to or touched.

**Where the ids fall.** A census of 1,126 field MLDs [V counts]:
- `man`: 2,195 entries. 698 have ids in the 3000s, which is the talk range; 1,187 are in the 30000s, event actors.
- `goscript`: 1,609 in the 4000s and 941 in the 6000s.
- `treasure`: 139, all in the 4000s.
- `kmap`: 124, all 9000+.
- `eff_camera`: 56, mostly 29000s.

**How "talk" and "touch" pick an entry.** The player's per-frame `fn_80118204` does the following:
- It returns at once if flag 1087 is set (`0x80310BC0` bit 31, the "event running" lock every entry sets), or if `r13-29208 == 1`, or if `fn_8009763C() == 12`.
- **Touch** (mode 0, every frame, with the body volume at player+444): `fn_80117BE4(0, …)` walks the global hit-volume list (`r13-29180`, linked at +48) with the overlap test `fn_80222B30`. It accepts:
  - hit types 40, 20, 48, 34, 35, 14, 15 and 16 (table `0x802E4F30`: ladders, ropes and the like), which are handled natively;
  - or object ids **6000–6999**.
- **Check/talk** (mode 1: the A edge, 0x100 in `[[0x80311A60]+8]`, and `fn_8011768C() == 0`, with the probe volume at player+448): the same walk, accepting ids **3000–4999**.
- Of the accepted volumes the **nearest** wins (`fn_80290008`).
- Then `fn_8021067C(id)` formats `M%05d` (r2-15660), finds that entry in the script index, and evaluates the expression that follows the entry's first word, the `LABEL` operand. Only a nonzero result lets `fn_80210550(id)` start the entry.
  - It stores the entry into `0x8030CEA4` and sets `0x8030E714 = 1`.
  - It refuses while `0x8030E714` is already 1.
  - Op 12 RET (`fn_801F5BD0`) clears `0x8030E714` when the call stack is empty and at most one latent task remains.
- The world map runs the same scan with the ship (`fn_80119AF4` calls `fn_80117BE4` twice) [I that it is the ship].

**A typical NPC entry** (`me002a` `M03003`, operands abridged):
```
LABEL 1 ; IF … story gates … ; FLAGSET 1087 ; Enter sys[10] ; Enter 3003 ; DefMO … ; CTRL 3003 ; LetsTalk 3003
PRINT MES <msg> … ; FLAGSET <one-shot> ; Ret sys[10] ; Ret 3003 ; FLAGCLR 1094 ; FLAGCLR 1087 ; RET
```

**Opcodes.** The following names are [V]: each handler references a self-naming debug string.
- Actors: 26 Enter, 41 Ret, 27 Let'sTalk, 28 DefMO, 29 PlayMO, 30 Face, 31 PutA, 32 PutP.
- Movement: 35 MV, 34 MVR, 89/90 MVF/MVS, 130 MV2, 161 MV3.
- Rotation and scale: 36/37 RollA/RollP, 134 Proll, 136 Scale.
- 99/246 TaskOff, 97 ChangeParts, 117 CWait, 118 Fin.
- **None of these creates an object.** A new actor has to come from an MLD loaded by op 23, then be placed with 31/32.
- sys[10] is the player's object id [I].

**Doors.** `kdoor1` and `door2` read mailbox command 2 (`fn_800CCC48`/`fn_800CCE0C` with r3 = 2); `doorwall` is a hit class `0x7A000004` [V]. Map exits are `goscript` 6xxx volumes whose `M06xxx` entry fades out (op 60) and WARPs (op 43) [V from `me099a` `M06500` and `me103a`].

### 3. Messages and choices [V]

**Message sections.** A message is its own script index entry: the words `00000009 04000000 3F800000 0000001D` (LABEL 1.0 END), then NUL-terminated text, padded to 4 bytes. Names are cosmetic (`M00040000`, `MA0190000`, `Ms004a027`), because code refers to messages by self-relative offset. In this sample 25,347 messages used only `\h(…)`, `\n`, `\e` and `\c`.

**Display opcodes:**
- **144 PRINT MES** (`fn_8020A734`): `[off][fadeout | DEFAULT]`. It requires the LABEL at the target (`scptPRINT MES: NO LABEL!`). A non-DEFAULT fadeout rewrites the last two bytes to `\c`.
- **24 PRINT** (`scptPRINT`, `fn_8020A938`): `[off]` to raw footer text.
- **155 SELECT CHOSE** (`fn_8020A338`): `[count][off][fadeout]`.
- **25 SELECT** (`0x8020A584`): `[count][off]` raw.
- 259/261 SENNIN and 265 are special dialogs built on PRINT.

**Choices.** The text is `\h(《prompt》)opt1\nopt2…`. When the window finishes, the handler stores the answer: `8020A540 lwz r0,8(ctx) ; 8020A544 stw r0,5480(0x8030CEA0)`, which is `0x8030E408` = **sys[9]**. Scripts then `SWITCH (sys[9])`. The count is 2 in 417 uses and 3 in 248; op 25 goes up to 13, in the debug menus only.

**The path from opcode to screen:**
1. The opcode allocates a context (`{status, fadeout, (answer), text}`) and posts mailbox command 5 to the queue at `0x80305B08` (`fn_802110E8` → `fn_800CD0B8`). `0x8030E468` = 1 means a message is up. The op returns 1 until `ctx[0] == 2`.
2. The window task `fn_8010D4F4` (184-byte context) is created on every map load (`fn_8010CEF8`, `80101288`). It takes command 5 (`fn_8010D280`/`fn_8010D4F4` → `fn_800CCA6C(5,0)`) and calls `fn_8010B258(window, record)`. Sub-kind 0 is print, 1 is select.
3. **`fn_8010BBD8(window, text)`** lays the text out:
   - `fn_8010B5AC` tokenises it. `fn_801E325C` decodes characters: bytes below 0x80 are ASCII; lead bytes 0x81–0x98 take a second byte; **any other byte becomes 0x8197**.
   - Each line is `memcpy`d into its own heap node (`fn_8010B88C`, size `(len+31)&~3`, linked at window+64/68). **The source string is not referenced after this call.**
   - Escapes (jump table `0x802E4C7C`) are `\a(n) \b \c \d \e \h(name) \p(r,g,b) \r \s(n) \u \x \wc(n) \wo(n)` and `\n`.
   - `\c` resets the colour to 0xFFC0C0C0 and the speed to 1. `\h` makes a 0x400 name node.
4. `fn_8010CC74` draws it, called from `main` at `801DCCF0` and `801DCD24`: the frame is `fn_8010C978`, the lines `fn_8010C5BC` → `fn_801E2A60`/`fn_801E2DB4`, the font sprites heap-allocated each frame.
5. Engine-built messages (chests, discoveries) are formatted into `0x803146A8` (144 bytes to the next global) and `strcpy`d unbounded into `0x80314738` (264 bytes to the next global) by `fn_8021026C`, then posted the same way.

**The text hook.** Hook the entry of `fn_8010BBD8`, swapping r4 for a guest-memory copy of the replacement. That one site covers every script message, every choice and the engine-built messages. Because the text is copied into nodes during the call, a single static guest scratch buffer is enough [V for the copy; I for the sufficiency]. Battle text and menus use other renderers and are not covered.

**Text speed** (M12's open item). The per-character countdown is window+58 in `fn_8010D280`. It is reloaded from node+22, which is copied from window+60 (`\s(n)`, default 1) when the node is built. A or B sets window flag 0x20, which reveals everything.

**Limits:**
- Script text has no fixed buffer (heap nodes).
- **Observed maxima over all 25,347 messages:** 3 lines, 51 characters per line (≤49 bar 5 lines), 182 bytes. The frame is drawn from constants, so 3 lines and about 48 columns is the page [I].
- Space is 0x7F in all script text; whether 0x20 renders the same is not established.
- Engine messages are bounded by the 144- and 264-byte buffers above. A long mod item name would overrun them.

### 4. Shops, chests, inns, the Guild, chest %, Discoveries [V]

- **Shops.** Op 181 (`fn_801FDDB0` → `fn_801BEAE4` → `fn_801BEB10`) stores the shop id to `0x803473BC`. Inventories are **executable data** at `0x802EC0A0`:
  - 43 records × 104 bytes: `{u16 id, u16, char* name, s16 item[48]}`, terminated by −1 (`fn_801AB580`: `mulli r3,r0,104`).
  - Scripts pick the tier by story flag (`IF !FLAG[122] → shop 8`, …). All ids 0–42 are used. Prices come from the item records.
- **Sailors' Guild.** Op 231 (`fn_801FDCDC` → `fn_801BEA70`) opens office 0–3 from `0x802ED218` (16-byte records) in info mode. It sells from the Discovery table.
- **Inns are pure script.** Op 155 yes/no → `SWITCH sys[9]` → `IF sys[0] ≥ price` → `SETI sys[0]` → op 201/202. Op 201 (`fn_801FD9B0`) sets current HP to max for members with flag 1032+ch.
- **Chests.** A chest is a `treasure` MLD object with an id in 4000–4999 (A range). Its params word 8 is a **treasure index**.
  - Its entry (e.g. `M04900`) does FLAGSET 1087; `IF !FLAG[2048+idx]` → sound; **op 154 OpenTreasure(id)** (`fn_8020C390`).
  - Op 154 finds the object (`fn_8015F1A0`) and reads `params[8]` (`8020C438 lwz r27,36(r3)` when count > 8).
  - It indexes **`0x802D59E8`**: 119 records of `{item id, or ≥ 512 for gold; count}`.
  - It tests and sets **flag 2048+idx** (`8020C4CC addi r0,r27,2048` … `8020C790 stwx`), gives the item (`fn_801EFF0C` × count) or gold (+ `0x8030BB40`), and formats a message from the formats at `0x802D6388..6468`.
  - The object itself draws open or closed from the same flag (`8019E01C addi r4,r3,2048`).
  - Maps 28b, 122a, 125a/b/d take a different message path (`8020C590`–`8020C618`).
- **Chest %.** It is not a counter. `fn_801EF300` counts flags 2048–2166 and computes `int(n/119.0*100.0)` (constants r2-16100 = 119.0 and r2-16104 = 100.0) inside the **epithet/title** routine (`0x8030B7AE`), testing 90 and 100.
  - **Correction to `story-flags.md` §2, and to this task's brief: flags 2048–2166 are treasure chests, not Discoveries.**
- **Discoveries.** Op 177 (`fn_8020DD1C`, `scptGetHakken`) takes `(id, 12 floats)`, the floats being camera poses.
  - An id below 4500 is the Discovery number. Otherwise the object with that id (`fldHakken`, ids 4500+N) supplies it from params (word 13 by default).
  - The found flag is **2900+N** (`8020DF5C addi r4,r5,2900`). A second flag, 2990+N, is set when the number compares against the story-stage table `0x802D5940` [I its meaning].
  - After the op, flags 2900–2987 are recounted into **B[51]** (`8020E17C`–`8020E250`; 88 Discoveries).
  - The table is `0x802ED258`, 40-byte records: names, text, two prices. It has 89 records, the last a special.
  - On the world map these are the `M045NN` entries of `me099a`–`q` (91 op-177 uses per script), fired by the A-button scan on `fldHakken` objects.

### 5. Cameras [V unless marked]

- **Fixed pose.** Op 50 (`fn_80204CD0`) writes six floats to `0x8030E79C..B0` (xyz, and three angles × 182.04 per SALSA).
- **Follow camera.** Ops 72 and 74 (`fn_80206CBC`/`fn_80206904` → `fn_80097118..fn_80097318`) write a camera-control struct at `0x802E0084` (+40..+98, dirty counter at +2) [I that it is the field follow camera]. The `me103a` loop pairs **op 77** (`fn_80118578`: a pending player start record at `0x8030A380` = {1, mode, x, y, z, rotY}, consumed by `fn_80118368`) with op 74.
- **Moves and fades.** The camera moves are 159 MVCA3, 121 MVCA, 139 MVCALP and 33 MVCB2 (names [V]; that they move the camera, [I]). Op 59 is fade-in and op 60 fade-out: `fn_801CBBBC`/`fn_801CBBD8` write 0 or 1 to `0x80347518`, the fade direction FINDINGS measured.
- **Op 235 is not a camera.** It calls `fn_800E2924(id)`, which finds the object with that id (`fn_801094C8`).
  - Every such object in the census has type **`kmap`**, 9000+. Its handler (`0x800E23B0`) takes the entry's texture, masks 4-bit blocks by a flag (`fn_800E1A58`), and pushes the result into texture 1 of the current texture list (`fn_80297CC0`). That is the area map [I, strong].
  - The error print is a stub (`fn_801DBE1C` is `GameDebugPrintf`), so a missing id falls through into `lwz r31,36(r31)` on NULL: the `a116c` trap.
  - **Correction to FINDINGS census 3:** "camera object 9001" is a kmap id.
- **NCAM** appears in 72 of 1,126 field MLDs. `eff_camera` objects (56) are the cutscene camera motions [I]. Ship battles use camera paths (`sb_croot`, `"Camera Path Is Not Found %d"`) and ops 223–225/232 (→ `fn_801558B0..`, the ship-battle module).

### 6. Remixing: a new script on existing geometry

- **No redirect exists for the main geometry.** The script, geometry and encounter names all come from `0x80311AC4`/`AC8` [V §1]. The resolver `fn_800FFB24` needs both files to exist. Story warps (15 → 0 → 1 → 3) skip the resolver and load the geometry name unconditionally [V FINDINGS].
- **Op 23 can load any MLD**, another map's `aNNNx.mld` included, as an extra model whose entries become objects. 124 sub-model MLDs already carry `ground` entries (house interiors, for example) [V count], so walkable sub-model floors are normal [I]. Loading a donor map this way still needs some file under the new name for the main slot.
- **In the port, an FST alias is the clean route**: a new `/field/aNNNx.mld` entry pointing at the donor's disc extent, with no bytes copied [I design; §8]. Aliases are also needed for:
  - `.ect`/`_ep.enp`, for encounters;
  - house interiors `a0NNx<c>.mld`, whose names derive from the new number.
- **What the new script controls:**
  - Donor objects with no `M%05d` entry in the new script, or whose LABEL condition is false, cannot be talked to or touched [V `fn_8021067C`]. They stay visible.
  - Donor chests keep the donor's `params[8]`, so they share the donor's flags and show its open/closed state [V]. Leave their entries out, or hide them (op 99/246 TaskOff [I]).
  - The script supplies the player start (op 77), the camera (72/74), the kmap id (op 235), lighting (`LIG_*` entries), sound banks (op 69), fades, and every WARP.
  - New NPCs or triggers need a small new MLD, holding `man` 3xxx or `goscript` 4xxx/6xxx entries with hit models, loaded by op 23.

### 7. World map and islands

**How the world map is built:**
- Map 99 streams a 6×7 grid of tiles `fielRCx.mld` [V §1].
- **The tiles hold the islands:**
  - `fldIsland`: 628 entries.
  - `fldName`, landing points with a name banner, ids 4000+: 87 [V census; I banner].
  - `fldHakken`: Discoveries, 4500+.
  - `fldManshipE`: talkable ships, 3000+.
  - `fldManshipF`: 8500+.
  - storms and rocks.
- `a099x.mld` holds the rest: sky, clouds, `fldEfcontrol`, `goscript` 6000+, event actors.

**Landing** is the A scan on a `fldName` id: `me099a` `M04000` warps to `me002a`/`me002b`, `M04001` to `me103a` [V script]. `M085xx` entries start ship battles with op 210 [V]; how 8500+ objects trigger them is not established.

**Encounter regions** are not in WMAPAREA. `fldEfcontrol` (`fn_8009C518`, id 5300 in `a099`) indexes a byte grid in its own params: `B[43]*1008 + altitudeBand*336 + cell + groundZone`. The result `v` gives `v/10` → `0x80346CD8` (the sub-table used by `fn_800C1A50`) and `v%10` → `0x80346CD4` [V; the index terms I].

**WMAPAREA.BIN** holds 3 layers of 24×28 cells:
- The layer is **B[48]**, the world-map mode. A cell is `layer*672 + row*28 + col` (`fn_800EDAA4`).
- From story stage B[6] ≥ 14, values 7 and 11 are remapped.
- Values go through `0x802B2178` to **save-location ids 60–74** (`fn_800ED8C4`, called only by the save menu's `fn_801A686C`). That names a world-map save.
- The map screen (`fn_800EE51C`) loads it too, next to a 12×14 visited grid from flags 1312–1479 [V].
- It controls neither weather nor encounters.

**A new island takes:**
1. An island model, collision and `fldIsland` entry in the right `fielRCx.mld`, or in an op-23 sub-model loaded by every `me099a`–`q` init. Sixteen scripts: the letter is B[6]+'a' and there is no 099n.
2. A `fldName` (or `goscript`) entry with a free 4xxx id, and an `M04xxx` entry that WARPs, in each of those scripts.
3. For a save name, a WMAPAREA region value; there are only 15 region ids, mapped by a fixed table.
4. Optionally a `fldHakken` 45xx with op 177. Discoveries are capped at the 89-record table and flags 2900+.
5. Map-screen art (`hrs_wmap.mll`) will not show the island [I].

### 8. The file table, and extending it in the port

**In the game** [V]:
- `__DVDFSInit` (`0x8023A478`) reads `FstStart = *(0x80000038)` once. It takes `MaxEntryNum` from root+8 and places strings at `FstStart + 12*n`.
- `fn_8023A4B0`, `DVDConvertPathToEntrynum`, walks the tree case-insensitively (`fn_8025BD6C`).
- OSInit sets `__DVDLongFileNameFlag = 1` (`80231D2C`), so long names are fine.
- **Nothing caches entry numbers.** Every opener converts the path first: `fn_801C63EC`/`fn_801C64DC` (then DVDFastOpen), `fn_801CC62C` (exists), DVDOpen `fn_8023A818`, and ChangeDir.
- Nothing in the game reads the FST max. `0x8000003C` is only written, by the SDK re-read at `8023D980`.
- The disc: 5,560 FST entries (5,552 files), 134,426 bytes, `fst_max == fst_size`. Files end at `0x55337A16`; `disc.iso` is 1,459,978,240 bytes.

**In the port** [V file:line]:
- `runtime/main.c:1158-1161` copies `sys/fst.bin` to `(ARENA_HI - size) & ~31`. `ARENA_HI = 0x81700000`, `:923`.
- `setup_low_memory` (`:989-1004`) writes 0x80000034/38/3C.
- `runtime/dvd.c:129` serves command 0xA8 from `disc.iso` at `g_cmd[1] << 2`. `disc_read` (`:91-110`) returns zeros past the image's end.

**Plan.** In `main.c`, after `mod_load` (`:1137`) and before `:1160`:
1. Parse `fst.bin` into a tree.
2. **Replace** a file by rewriting only its offset and length; no renumbering is needed.
3. **Add** a file by inserting it into its directory's contiguous range, then re-serialising. That renumbers the entries after it and every directory's next/parent index, and rebuilds the string table.
4. Give each mod file a virtual offset above `0x57058000`, 32 KiB-aligned and below 4 GiB. FST offsets are u32 bytes.
5. Pass the new size as `fst_max`.
6. `dvd.c` needs an overlay table (`[start,end) → host file`) inside `disc_read`, including a read that straddles an extent.

**Pitfalls:**
- A bigger FST lowers the arena top one-for-one. Heap slack is unknown [I].
- Names differing only in case collide.
- `runtime/aram.c:196-245` indexes `fst.bin` and `disc.iso` directly (a diagnostic; 8,192-file cap; `(long)` fseek below `0x7FFF0000`). It would call overlay audio "unidentified".
- Record packs in the pad-config line, as M1 does for patches.
- Content packs are game-derived, so add their directory names to `tools/guard.py` `FORBIDDEN_DIRS`.

### 9. Limits a content modder hits

| Limit | Value | Where |
|---|---|---|
| Field map numbers | 0–499. ≥500 takes the ship-battle load (`fn_8012A634`) and state 8 → 14. 99 is the world map (letter from B[6]). | [V] |
| Map name | `ME` + exactly three digits + a letter at index 5 (`fn_801004C4`). Errors are silent: `fn_801DBE1C` is a stub. Letters a–z, upper case folded. | [V] |
| Special map numbers | 099, 107, 122, 209 (stage tasks); sky maps 099 / 122a / 125a,b,d / 127a,b; 131e (state 7 pre-run); 028b, 122a, 125x (chest messages); 090a (game over). House interiors only for maps < 100. | [V] |
| Free numbers | 422 of 0–499 have no `aNNN?.mld` or `meNNN?.sct` of their own [V count]. Check a number against the name table `0x802E4780` and sub-model names before using it [I]. | |
| Script tasks | 384 latent slots. The dispatcher stalls when full (`802112C4`). | [V] |
| Script call stack | Stack at `0x8030E71C` (depth `0x8030E71A`); about 31 deep if it ends at `0x8030E79C` | [I] |
| Enter table | 8-byte slots at `0x8030CEB8`; overflow at 256 is only a stubbed print (`tolObjSendEnter`) | [V] check, [I] size |
| Script size | Heap-copied (`scptLoad`), no cap. The largest on disc is 840,318 bytes / 1,811 entries (`me250a`). Entry names are 15 characters. | [V] |
| Objects per map | One heap task per entry (64 + 624 bytes, `fn_801C6180`, no NULL check). The largest map index has 338 entries (`a115b`), the largest map MLD is 5.2 MB. | [V] |
| Interaction ids | Talk/check 3000–4999, touch 6000–6999, the player 50900–50999. Ids are 16-bit. | [V] |
| Messages | About 3 lines × 48 characters per page; ASCII plus SJIS leads 0x81–0x98; engine messages 144/264-byte buffers | [V observed] / [I page] |
| Chests | 119 (table `0x802D59E8`, flags 2048–2166, % = n/119). An index ≥119 reads past the table. | [V] |
| Discoveries | 88 counted (flags 2900–2987 → B[51]); 89 table records | [V] |
| Shops / Guild | 43 × 48 items; 4 offices | [V] |
| Save locations | B[44] (`0x80310A48`) picks the name. `me103a` sets it before op 138. The name table `0x802B943C` has about 70 entries. | [V] / [I count] |
| Flags | 27,328, all saved. **Scripts touch 1,070 distinct flags, the highest 4,505.** A raw token scan finds none above 2,961; this contradicts the brief's "up to ~26,000". No fixed-address engine access was found above the chest and Discovery ranges. **Flags 4,506–27,327 look free.** | [V census] / [I free] |
| Engine flag ranges | 1026+ch / 1032+ch (party), 1039–1060 (crew), **1087 (event lock)**, 1312–1479 (map-screen grid), 1856–2047 (per-map by convention), 2048–2166 (chests), 2900–2987 and 2990–3077 (Discoveries) | [V] |
| Byte variables | 288, saved. B[128..286] are cleared by load-game (`fn_801CAE98`). Unused by scripts and by fixed engine addresses: B[86..99], B[114..127], B[160..191], B[235..249], B[276..287]. **Only 86–99, 114–127 and 287 survive a load.** | [V] |
| sys (int) and float variables | Not in the save (`0x8030E3E4`/`0x8030E514`). sys[9] = choice, sys[10] = player id [I], sys[15] = where you came from (10000 after a battle, 20000 after a load, 40000 after op 214). | [V] |

### 10. Not established

- The hit-shape kinds that `fn_801C7D0C` builds from a model (36-, 60- and 196-byte records), and which MLD chunk holds them (GOBJ?).
- The exact follow-camera parameters behind ops 72 and 74, and what op 27 LetsTalk and op 40 CTRL do beyond facing.
- The unused escapes `\a \b \d \u \x \wc \wo`, and whether 0x20 renders like 0x7F.
- The `fldName` banner text source; `eventhook`; what fires the `M085xx` ship objects on the world map.
- The meaning of flags 2990+N (the Discovery second flag) and of the `0x802D5940` stage table.
- Whether a player's escape from an op-112 battle returns through sys[15] = 10000 the same way a victory does.
- Arena slack for a larger FST.

---

### RECIPE: a new quest in an existing town (Pirate Isle, `me002a`)

This needs the §8 file overlay, so that a modified `me002a.sct` replaces the disc's. AKLZ is optional. Assemble with SALSA's layouts.

1. **Flags.** Choose three flags from 4,506 upward, for example 5000 "offered", 5001 "fight started" and 5002 "done". They are saved automatically.
2. **Messages.** Append index entries, each `00000009 04000000 3F800000 0000001D` + `\h(《Name》)…\n…\e` + NUL, padded to 4. Keep to 3 lines of about 48 characters and use 0x7F for spaces.
3. **The NPC.** Reuse existing NPC 3003. Prepend a branch to `M03003`:
   `IF (FLAG[5000]==0) { FLAGSET 1087; Enter sys[10]; Enter 3003; LetsTalk 3003; PRINT MES <offer>; SELECT CHOSE 2 <yes/no>; SWITCH sys[9] {0: FLAGSET 5000 …}; Ret …; FLAGCLR 1087; RET }`.
   A brand-new NPC instead needs a small MLD with a `man` entry (id 3xxx, hit model) loaded by op 23 in `init`.
4. **The battle.** Add a touch trigger, or give NPC 3003 a later branch:
   `IF (FLAG[5000] && !FLAG[5001]) { FLAGSET 1087; FLAGSET 5001; BATTLE 1, <event id>, <stage>, -1 }`
   - Op 112 takes: 1 = event battle; the id indexes `/battle/epevent.evp`; the stage N loads `s%03d.sml/.sst`.
   - New enemies mean overlaying `epevent.evp`.
5. **The return.** After a win the field reloads with **sys[15] = 10000** (`801015F0`). In `loop`'s `SWITCH sys[15]`, the 10000 case must:
   - do `op 235 <kmap>` and **op 59**, the fade-in, then FLAGCLR 1087 (the `a101b` black screen was a missing fade);
   - then `IF (FLAG[5001] && !FLAG[5002]) { … PRINT MES <thanks>; ITEMADD <id>; SETI sys[0] = sys[0] + <gold>; FLAGSET 5002 }`. Give items one op-20 per unit.
6. **Check.** Warp there with sys[15] set (`0x8030E420`). Talk with A near NPC 3003. Look for the watch on `0x80310B3C + 4*(5000>>5)` and `/battle/…` loads, then peek the reward.

### RECIPE: a new map from existing geometry (for example `045a` from `002a`)

1. **Number.** Pick a free number below 500 that is not special (§9), for example 045, letter a.
2. **Files, through the FST overlay:**
   - `/field/a045a.mld` as an **alias** of `a002a.mld`'s extent;
   - `/field/me045a.sct`, a new script;
   - optionally `a045a.ect` and `a045a_ep.enp` (aliases or new);
   - aliases `a045a<c>.mld` → `a002a<c>.mld` for each house interior the geometry contains (`params[8]` letters).
3. **Script `init`/`loop`:**
   - Copy the donor's lighting and `soundsakadume` (op 69 banks).
   - Set the player start with **op 77** and the camera with ops 74/72.
   - `op 235 9000`, the donor's kmap id; take it from `a002a.mld`'s `kmap` entry.
   - Fade in with **op 59**, then FLAGCLR 1087.
   - Handle `SWITCH sys[15]` for arrivals: old×10+letter, 10000, 20000.
4. **Objects:**
   - Write `M%05d` entries only for the donor ids you want live: warps on `goscript` 6xxx, `M04xxx` checks.
   - Leave donor chests' `M049xx` out, since they share the donor's chest flags.
   - New actors come from a new small MLD through op 23 and are positioned with PutA/PutP.
   - Set B[44] to an existing location id before any op 138 save point.
5. **Entry.** Add a WARP `"me045a.sct"` (op 43) to an existing map's script, or warp by name for testing. Look for `LoadStart /field/a045a.mld`, the new script's entries firing, and open the frames.

Scratch tools, kept in the session scratchpad and not in the repo (`...\scratchpad\research\content\`):
- `alldis.py`: a full disassembly with r13/r2 resolved.
- `dolh.py` and `xref.py`.
- `mldidx.py`: an MLD index lister.
- `sdec.py` and `dump_all.py`: the SALSA-based script dump, 258 scripts.
- `msgstats.py`.
- `optable.txt`.
