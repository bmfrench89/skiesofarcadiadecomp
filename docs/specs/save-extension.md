# X2: the save extension

Written 2026-10-23 for the owner's answers D-43 (the gameplay core, batch A) and D-44 (gameplay Q2: the honest save
promise), from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) X2 and docs/research/beyond-gamecube.md §3. The sites
were read in the disassembly at 2ac1b7c (`tools/disasm.py`).

**Built 2026-10-23** (FINDINGS "X2"): Done lines 1 to 7. *As built:*
- **The save's id is minted at the snapshot,** not at the image as research §3.4 had it: the gap holding it is
  covered by the XOR before the image exists, so the tail repeats the gap's id rather than taking a new one.
  Nothing reads the id yet (no host blobs); it ties a tail to its gap.
- **`examples/mods/battle-tally`** ships with it: R1's `on_rewards` and X2's chunk in one small mod.
- **The room was checked, not taken on trust:** the gap, the tail and research's other free spans are zero in
  all 46 saves on this PC's cards, parts A to L.

**Why.** A mod has nowhere to keep state across a save: a counter, a quest's progress, a setting chosen in play.
Worse, turning a mod off and saving would lose whatever it had. X2 gives each mod a chunk inside the game's own save
file, carries the chunks of mods that are not loaded through every save, and says, when a save is loaded, which mods
it holds data for that are missing.

**What D-44 decides.** The honest promise: vanilla saves always load anywhere; a mod's save loads in the port with its
mods, and says which are missing without them. So X2 builds no mod-map location fallback and no placeholder-gear swap
(those wait for N7 and N1), and the save-now location half waits for M7a, which is not built.

## 1. What is there [V, disassembly at 2ac1b7c]

- **The file:** 24,576 bytes: comment, banner and icon at +0..+5183, the 12,800-byte block at +5184, and +17,984 to
  the end zero.
- **The block** comes from `memCalloc` (`fn_801E1A74(1, 12800)` at `0x801A4584`), so whatever the game does not fill
  is zero. Its bytes +5916..+9071 (3,156) are never written by the game nor read back by `fn_801A4354`, and they are
  inside the XOR the game checks (12,796 bytes, stored at +12796 by `fn_801A41EC` at `0x801A42EC`).
- **The snapshot:** `fn_801A456C` fills the block when the save menu opens (it may still be cancelled); its last
  instructions are at `0x801A4670` with r31 = the block, after the flags are copied in.
- **The image:** on "Yes", `fn_801A41EC` stamps the time, XORs the block, allocates 24,576 bytes into `*(r31 + 0)`
  (r31 = the descriptor at `0x803081A4`: +4 the name `SA_LEGENDS.00N`), zeroes it, copies the block to +5184
  (`0x801A4330`) and reaches `0x801A4334`. The writer `fn_801A3B30` then puts it on the card over several frames.
- **The load:** the menu checks the XOR, then calls `fn_801A4354(block)`, the block in a 24,576-byte image read from
  the card (image = block - 5184), which copies the party, map, position, flags and play time back.
- **New game and boot:** `fn_801CAF30` clears the flags; called at boot (`0x801DBF64`) and at New Game (`0x80228BF0`).
- **`hooks.txt`** calls `hook_<addr>(s)` before an instruction; an entry strips `irq_poll` from its function's
  back-edges, and the four functions above have only bounded loops that wait on no interrupt (research §3.3).

## 2. What X2 adds

- **Four sites, one retranslation:**
  - `hooks.txt` `0x801A4670`, the snapshot: each mod's chunk is asked for, and the container written into the block's
    gap, before the game's XOR covers it;
  - `hooks.txt` `0x801A4334`, the image: what did not fit the gap goes into the file's tail (image +17,984..+24,575),
    with a fresh GUID for this save;
  - `hle.txt` `fn_801A4354`, the load: the original, then the container read from the block and its image, each
    loaded mod handed its chunk (or none), and the chunks of mods not loaded kept for the next save;
  - `hle.txt` `fn_801CAF30`, new game and boot: the original, then each mod told, and the kept chunks dropped.
- **The container,** `SOAX`: in the gap a header (magic, version, a CRC32 of everything after it, the GUID, the
  total of chunks and how many follow in the tail) and as many whole chunks as fit; the rest in the tail, after its
  own magic and the same GUID. A chunk is a mod's id (manifest 2's, up to 31 characters), its length and its bytes.
  At most 3,156 + 6,592 bytes less the headers; a mod whose chunk does not fit is told so in the log, and its chunk
  from the save before is carried instead.
- **Three `SoaModApi` members, appended:**
  - `on_save(int32_t fn(user, uint8_t* buf, uint32_t cap))`: at the snapshot, bytes written, or -1 for no chunk;
  - `on_load(void fn(user, const uint8_t* data, uint32_t size))`: at a load, the chunk this save holds for the mod,
    or `data` NULL and `size` 0 when it holds none (a vanilla save, or one made without the mod);
  - `on_new_game(void fn(user))`: at New Game and at boot.
  Each runs inside the game's call with R1's fault stop (exit 10, the mod and the event named). A mod needs a
  manifest 2 id to register `on_save` or `on_load`.
- **Pass-through:** the chunks of mods not loaded, from the last save loaded, are written back unchanged at every
  save until a New Game. With no mod registering `on_save` and none kept, the sites write nothing.
- **The load report:** `[mod] this save holds data for <id>, which is not loaded: kept, and written back at the next
  save`; a container whose CRC fails is reported and ignored (the save still loads as vanilla).
- **`SOA_SAVE_LOG=1`:** `[save]` lines at each site: the block's and the image's SHA-1 at the image hook, what was
  written where, and what was read; the report gives each site's calls and the bytes written.
- **`tools/savext.py show <card> [--file N]`:** a save file read off a card image (cardformat.py): its XOR checked
  as the game checks it, the block's SHA-1, and the container's header and chunks.

## 3. Not in X2

The location fallback for save-now (with M7a), the mod-map and placeholder-gear fallback (D-44: with N7 and N1),
host blobs for chunks over the file's room (none needs them yet), N11's NG+ sites (a retranslation of its own when
N11 starts), owned-flag records (with N3's claims), and any comparison of two saves across builds (the time, play
time and XOR follow the wall clock).

## 4. Done

1. **Mods off, inside one run of the new build:** the self test, replay 23/23, `title --check`; a Continue from a card
   copy, then a save, with `SOA_SAVE_LOG=1`, gives every site a nonzero call count (boot for the new-game site) and 0
   bytes written; the block's SHA-1 at the image hook equals `savext.py show`'s for the file on the card afterwards.
2. **That save loads in the build from before X2** (`build/x2/before/soa.exe`, 2ac1b7c): the XOR passes and the
   Continue lands on the saved map (the map word peeked).
3. **A counter survives a save:** a test mod's counter, nonzero at the save and raised afterwards, reads back the saved
   value at a Continue from that card in a fresh process. *Mutation:* with the chunk write disabled it reads back none.
4. **Pass-through:** that card, saved again with the counter mod unloaded and another loaded, still holds the counter
   mod's chunk byte for byte (`savext.py show`). *Mutation:* with pass-through disabled, it does not.
5. **The game's own checksum guards the gap:** a mutation that writes the gap after the XOR makes the Continue refuse
   the file, as the game refuses a damaged save.
6. **A fault in `on_save` stops the run and names its mod,** and the card copy is byte-identical to itself before the
   run: the snapshot comes before the writer.
7. **The fake guest:** `test_mods.py` drives the container through stand-ins for the four sites: chunks in the gap,
   overflow to the tail, a chunk too large, pass-through, a CRC that fails, a mod built before the members.
