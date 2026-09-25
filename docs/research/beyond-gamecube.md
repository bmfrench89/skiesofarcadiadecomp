<!-- Written 2026-09-24 by a read-only research agent for the plan section "Beyond the GameCube".
Nothing was run: no soa.exe, no scenario, no soak, no pytest. Evidence is the disassembly
(tools/disasm.py over extracted/sys/main.dol), the runtime sources, the FST, and read-only walks
of the MEM1 images already captured in build/fifo (23) and build/perfset (12). [V] = quoted
instruction, file:line, log line or a number measured from those files; [I] = inference.
No game data is reproduced here: only addresses, sizes and counts. -->

# Beyond the GameCube: which console and disc limits a PC port can lift for mods

> **Two corrections from reports written the same day.** They supersede this report where it disagrees.
> - **Flags** (§3.5 and the summary table's row 7). The "dormant 3,072–19,455" range came from a raw token
>   scan in the brief. `content-systems.md`'s census, using SALSA's decoder, finds scripts touching flags up to
>   4,505, and engine ranges up to 3,077 (Discoveries 2990+N). Treat 4,506–27,327 as the unused range. The
>   plan reserves mods from 8,192 up, and K1 confirms it by watch.
> - **Enemies** (§2.3). `ebinit`/`ecinit` are a fallback the shipped game never reads in normal play. The live
>   records are in each map's `.enp` and in `epevent.evp` (`enemy-data.md`). Per-map re-pointing of those files
>   is therefore moot: records are per map already. The binding limits are the 8 KB `.enp` battle buffer and 4
>   distinct ids per battle.

All paths are under `C:/Users/bmfre/Documents/Github/SOA/`. r13 = 0x8034E720, r2 = 0x80350000.
Scratch scripts used (not in the repository): `xref.py`/`q.py` (call and constant cross-reference over the
DOL), `heaps.py` and `memlayer.py` (heap walks over `.ram` captures), all in
`%TEMP%/claude/.../scratchpad/research/limits/`.

---

## 0. Summary

**Five findings shape everything below.**

1. **The game sizes only one heap from the arena.** Heap 4, the game's current heap, gets whatever is left
   between the fixed allocations and arena hi. So raising arena hi grows the heap the game's own allocator
   uses, and the game uses it automatically [V].
   - **The catch:** if *both* memory-size words say more than 24 MB, the game subtracts 24 MB from arena hi.
     If the physical-size word is anything but 24 MB, it also sets a devkit flag [V].
   - **The consequence:** the port should move arena hi, not the size words.
2. **A 32 MB MEM1 needs only a relink.** `MEM_MASK` already spans 32 MB, and the 8 MB tail
   (0x81800000–0x81FFFFFF) is reserved host address space today [V]. Going past 32 MB changes `cpu.h`, which
   means a full retranslation.
3. **There is room for mod data inside the save file itself, and the save stays loadable in vanilla** [V]:
   - a zeroed 3,156-byte gap inside the checksummed 12,800-byte block;
   - an unchecksummed 6,592-byte tail after the block.
4. **Guest code can call native code today, through any function pointer, with a relink only.** Every indirect
   guest call goes through `dispatch`, and `dispatch` falls through to `guest_trap(s, addr)` (`emit.py:282`)
   [V]. A registry of reserved "thunk" addresses in `guest_trap` gives native task bodies, native callbacks
   and native script opcodes. Nine of the 266 script opcodes point at `scptSTUB` and are free to take [V].
5. **Most fixed tables are addressed through constants baked into the translated C.** The item tables alone
   have 214 such sites in 76 functions [V].
   - Extending a table *in place* is impossible: the tables are packed back to back [V].
   - Growing one past its range is therefore a rewrite of every function that uses it.
   - The zero-code route is the 82 placeholder item records.

### Summary table

| # | Limit | Where | How to lift | Size | Retranslation? | Risk | Unlocks |
|---|---|---|---|---|---|---|---|
| 1 | Guest RAM 24 MB. The game's main heap (heap 4) is 9.64 MB | `main.c:923` `ARENA_HI 0x81700000`; `cpu.h:23-36`; heaps built in `fn_801DC62C` | **T0:** `ARENA_HI` → 0x81800000 (+1.1 MB). **T1:** commit the tail and put arena hi near 0x82000000, so heap 4 reaches 18.6 MB. **T2:** `MEM_MASK` 0x03FFFFFF and arena hi near 0x84000000, so heap 4 reaches ~50 MB. In every tier the size words 0x80000028 and 0x800000F0 stay at 24 MB | T0 hours; T1 a day; T2 several days | T0/T1: no (relink). T2: **yes** (`cpu.h`) | T0 low, T1 low-med, T2 med | Bigger or more assets loaded through the game's own loaders. No behaviour change until vanilla would have run out |
| 2 | Four heaps of fixed size: 1.5 MB, 6 MB (middleware), 400 KB, 448 KB | Immediates at 0x801DC78C–0x801DC808 | Pre-hooks on the `OSCreateHeap` calls, which run once at boot and are loop-free | hours | yes (`hooks.txt`) | low | Headroom for the middleware, scripts and font |
| 3 | No memory that only mods own | `mem_ptr` masks every address into the image (`cpu.h:115`) | A mod window in the tail, committed per mod request (the rest stays a tripwire), plus host memory for DLL state | a day | no | low | Mod tables, strings, models and textures that the game reaches through planted pointers |
| 4 | Item tables of 80 records per category, id chosen by range | `fn_801F4C24`, `fn_801F4AE4`, tables from 0x802C5790 on; 214 baked sites in 76 functions | Fill the **82 placeholder records** by data patch. Going past 80 needs native category/accessor/list functions and the 76 functions rewritten | placeholders hours; >80 week-plus | placeholders no; >80 yes | low / high | New items now; large item mods later |
| 5 | Inventory of 80 slots per category, saved in the party block | 0x8030BB48…0x8030C340; `fn_801EFDC0`, `fn_801F4A60` | Extended lists in the sidecar, native list functions, menu work | week-plus | yes | high | Big inventories |
| 6 | Enemy ids are u8; 245 of 255 are in use | `fn_80077428` at 0x80077A18 and 0x80077A54 | Per-map redirection of `ebinit`/`ecinit` files (needs #10), or u16 formations (decompile battle setup) | a day after #10; week-plus | no / yes | low / high | New enemies per map, or globally |
| 7 | 27,328 story flags | 0x80310B3C, 3,416 B | Use the **16,384 dormant flags 3072–19455** (confirm with a watch). Beyond that, the sidecar | hours | no | low | Mod quest state inside vanilla saves |
| 8 | A 12,800-byte save block with no room for mod state | `fn_801A456C`, `fn_801A41EC`, `fn_801A4354` | A container in the file (gap + tail) plus immutable host blobs addressed by a GUID | several days | yes (4 hook sites, or M13) | med | Mod state that survives copies and deletes and stays loadable in vanilla |
| 9 | 7 saves on one card, and slot B empty | Clamp at 0x801A2EC0; `exi.c:543` | A slot B card (+7), or a card-page switcher. Raising the 7 needs the menu decompiled | a day each; week-plus | no; yes | low; high | More saves |
| 10 | A fixed disc and FST | FST parked at `main.c:1143-1161`; reads in `dvd.c:91-129` | Rebuild the FST at boot (append or re-point entries), serve virtual offsets from host files, swap entries per map | several days | no | med | New maps, scripts, models and music; per-map enemies |
| 11 | Font covers ASCII, 4 SJIS ranges and 15 specials; 640 glyph slots; the buffer is exactly the file's size | `fn_801E26E0`; tables at 0x802F6758/0x802F6778; 0x13020 at 0x801E372C and 0x801E36E8 | Native glyph lookup, a bigger buffer, a glyph atlas built from a TTF. Or overlay text keyed by glyph hash | a day to several days; overlay/translation week-plus | lookup yes; overlay no | med | New characters, translations, crisp text |
| 12 | Audio: 64 voices, ADPCM in 16 MB of ARAM, 32 kHz | Sega driver 0x8027C000–0x80292000; `ax.c`; `audio_out.c:95` | A host mixer in `audio_push_block`; music replaced by muting voices by ARAM source | a day; several days | no | low; med | OGG/FLAC music, unlimited sound effects |
| 13 | Rendering: 640×528 EFB, GX textures up to 1024², no way to add geometry | `gxr.h:9-10`; `gxr_tev.c:44`; `gxr.c:2001` | M9 replacement textures; draws injected before the HUD and before the XFB copy | several days, plus M12's camera spike | no | med | New props, markers, ghost ships |
| 14 | A 30 fps logic tick on one guest thread | `tick.c`; safe point at lr 0x801DCB88 | Safe-point callbacks, mod threads, and native thunks through `guest_trap` | a day | no | low-med | Native systems, native script opcodes and tasks |
| 15 | Input is the pad only; keys are polled | `window.c:191`, `:219` | Mouse and hotkey events queued on the UI thread, drained at the safe point, recorded | a day | no | low | Mod UIs, mouse camera |
| 16 | No network | none | DLL threads, exchanging data at the safe point. Lockstep needs D4 | a day (API) | no | med (security, determinism) | Asynchronous online features |
| 17 | Map numbers limited to below 600 | 35 compares against 600 in the 75 functions that read the map number | Reuse the **458 free numbers** below 600 | hours | no | low | Room for new maps |

---

## 1. RAM (24 MB)

### 1.1 How the game sets up memory [V]

**`OSInit`** (0x80231C5C) sets the arena from the low-memory words.

- **Arena lo:**
  - It is the word at 0x80000030 when that is set.
  - Otherwise it is `0x803624E0`, or `align32(0x8035D4C8)` on the debug-monitor branch (0x80231D30–0x80231D84).
  - The port writes 0 there (`main.c:996`). The captures show arena lo = **0x8035D4E0**.
- **Arena hi:**
  - It is the word at 0x80000034 when that is set, else **0x81700000** (0x80231D88–0x80231DA4).
  - The port writes the FST address there (`main.c:997`). The captures show **0x816DF2E0**.
- **`ClearArena`** zeroes the arena (0x80231F60).

**The two memory-size words.**

- 0x80000028 is read only by `OSGetPhysicalMemSize` (`fn_80235DF8`), and 0x800000F0 only by
  `OSGetConsoleSimulatedMemSize` (`fn_80235E04`).
- Their callers are `__OSInitMemoryProtection` and the game's memory init `fn_801DC62C`.
- The port writes 24 MB to both, and to 0x800000D0 (`main.c:994-1002`).

**`fn_801DC62C`**, called from `main` (0x801DCB78), does the following:

- **The devkit branch.** `if (phys > 0x01800000 && simulated > 0x01800000) arenaHi -= 0x01800000` (0x801DC69C–0x801DC6C4).
  - It then sets a devkit flag at 0x803475AC = (phys != 24 MB) (0x801DC6E4–0x801DC6FC).
  - The flag is read in 14 places. Those I read gate `OSReport` output (for example 0x801D1C54, 0x801DC3EC,
    0x801DCD88), and one sits in the reset path (0x801DC160, 0x801DC1B8) [V; the full effect I].
- **The fixed allocations, from arena lo up:**
  - two XFBs of 0xA5000 (640×528×2) at 0x8035D4E0 and 0x804024E0;
  - the GX FIFO, 0x40000, at 0x804A74E0;
  - `OSInitAlloc(lo, hi, 5)` (`fn_800059D4`), whose heap array sits at 0x804E74E0.
- **The five heaps**, created with `OSCreateHeap` (`fn_80005968`):

| Heap | Size | Handle at | Main user (by the handle's readers) |
|---|---|---|---|
| 0 | 0x180000 (1.5 MB) | 0x803476A4 | A 16 KB list plus a 0x16FE00 per-frame bump arena (`fn_801D1434`, `fn_801D0B50`) |
| 1 | 0x600000 (6 MB) | 0x803476A0 | Middleware init `fn_802970A0(…, heap1, 0x600000)` (0x801DC9BC); the fallback for the game's allocator |
| 2 | 0x64000 (400 KB) | 0x8034769C | `fn_802193BC`, `fn_80219834`, `fn_80219C84`; the script VM, by the address range [I] |
| 3 | 0x70000 (448 KB) | 0x80347698 | Font (0x13020) plus glyph cache (0x24000) (`fn_801E3718`), text code |
| 4 | **rest of arena → arena hi** (9.64 MB in the port) | 0x80347694 | `OSSetCurrentHeap(heap4)` (`fn_80005A44`, 0x801DC83C); the game's own allocator |

- **Boot allocations and middleware pools.**
  - It then allocates five boot buffers from the current heap: 4 KB, 512 KB, 24 KB, 72 KB and 448 KB.
  - Those buffers become middleware pools: `fn_80291C90(buf, 64)`, `fn_80288F90(buf, 0x8000)`,
    `fn_802A8FA0(buf)` and `fn_80299078(buf, 1024, buf, 1024)`. [Their meaning I.]

**Sega's allocator.** The game's "mem" layer sits on top of the OS heaps: `memAlloc` is `fn_801E1A2C` (271
callers), `memCalloc` is `fn_801E1A74` (142), `memFree` is `fn_801E17E0` (418), and there are Static/Field
variants and an "IDmem". The core is `fn_801E184C`.

- **Where it allocates.** It takes blocks from `__OSCurrentHeap` (heap 4).
- **Fallback.** If `OSAllocFromHeap` fails, it switches to heap 1 and retries, and marks the block (byte +31 = 1)
  (0x801E18C0–0x801E1938).
- **Running total.** It keeps a running total at 0x803476FC.
- **The one fixed-heap read is never used.** `OSCheckHeap`'s free-bytes result is stored at 0x80347684 and never
  read (1 hit, a store).
- **The answer to "fixed or sized from the arena":** four heaps are fixed immediates. Only heap 4, which the mem
  layer uses, is sized from the arena.

**The port's 24 MB in the captures:**

| Range | What |
|---|---|
| 0x80000000–0x80003100 | Low memory |
| 0x80003100–0x8034D4C4 | DOL text, data and BSS |
| … 0x8035D4E0 | Stack and so on |
| 0x8035D4E0–0x804E74E0 | 2 XFBs and the GX FIFO |
| 0x804E7520–0x80D3B520 | Heaps 0–3 |
| 0x80D3B520–0x816DF2E0 | **Heap 4** |
| 0x816DF2E0–0x81700000 | FST (134,426 B) |
| 0x81700000–0x817FFFFF | **Unused 1 MB** (the port's `ARENA_HI` choice) |
| 0x81800000–0x81FFFFFF | Reserved tail, the tripwire |

- Nothing in the DOL materializes a constant from 0x81400000 upward except `OSInit`'s default and `__OSReboot`
  [V, constant scan].
- Nothing loads from or stores to that range except `__OSReboot` and `ClearArena`'s reboot-save words at
  0x812FDFEC/F0 [V].

### 1.2 Headroom measured in the 35 captured frames [V]

I walked the OSAlloc free and allocated lists, and the mem layer's list at 0x802F6748, in every `.ram`.

| Scene (capture) | Heap 4 free (largest block) | Heap 1 free | Mem-layer total |
|---|---|---|---|
| field, Dangral base (perfset field/5000) | 7.24 MB (7.2) | 3.84 MB | 1.05 MB |
| battle a101b (perfset battle/4000) | 4.90 MB (4.2) | 3.14 MB | 2.98 MB |
| **ship battle 550a (perfset ship/6000)** | **4.29 MB (4.3)** | 3.17 MB | 3.79 MB |
| sky, world map 099l (perfset sky/4000) | 5.34 MB (5.3) | 3.11 MB | 2.92 MB |
| cutscene (perfset cutscene/4500) | 5.91 MB (5.8) | 2.82 MB | 2.36 MB |
| corpus 8000 / 11900–12100 | 4.40–4.50 MB (**3.75**–3.8) | **2.24**–2.28 MB | 3.4–3.9 MB |
| boot logos (corpus 0100) | 8.24 MB | 5.25 MB | 0.06 MB |

- **Across all 35 frames:**
  - heap 4 never had less than 4.29 MB free;
  - its largest free block was never below 3.75 MB;
  - heap 1 never had less than 2.24 MB free;
  - no block had ever fallen back to heap 1.
- **Heap 4's largest free cell always ends exactly at arena hi (0x816DF2E0).** So raising arena hi grows
  precisely the largest block.
- **The per-frame bump arena in heap 0** (0x16FE00) reached a high-water mark of only 8.5 KB, 0.6% (the word at
  0x80347210). It is not a binding budget.
- **ARAM** (16 MB, `aram.c:24`): the named uploads in `build/h1-L9000.log` and `build/cap-battle.log` span
  0x004500–0x84FE40, about 8.3 MB.
- [I] These are single-frame snapshots. The peak during a map load is not measured. `SOA_PEEK=0x803476FC@N-M`
  on the running total would measure it without a rebuild.
- [I] The retail game is **not memory-starved**. More RAM matters only for content that mods add.

### 1.3 How the port models memory [V]

- **The image and its mask.** `MEM1_SIZE` is 24 MB, `MEM_MASK` is 0x01FFFFFF, and
  `MEM_IMAGE_SIZE = MASK+1+32` (`cpu.h:23-36`). `mem_ptr` is `s->mem + (ea & MEM_MASK)` (`cpu.h:115-118`), so
  cached, uncached and physical addresses all fold onto one image.
- **The reservation.** `main.c` reserves `MASK+1+64K`, commits the first 24 MB, and arms a vectored handler
  (`main.c:558-649`). The first access past 24 MB is reported once (`[mem] … past the console's 24 MB`). The
  handler then commits the whole tail and lets the run continue.
- **The test.** `SOA_MEMPOKE` exercises this (`main.c:651-683`), and `tools/tests/test_memguard.py:149-151`
  asserts the report at 0x81800000.
- **`MEM1_SIZE` bounds every device model:**
  - DVD: `dvd.c:99`, `:125`;
  - ARAM DMA: `aram.c:428`, `:441`;
  - AI DMA: `dsp.c:221`;
  - EXI DMA: `exi.c:366`, `:509`;
  - XF indexed loads and display lists: `gx.c:333`, `:346`;
  - vertex arrays: `gxr.c:445`, counted as *bad vertex refs*, which fails a scenario check;
  - EFB copy destination: `gxr.c:1716`;
  - texture hash, TLUT and decode: `gxr_tev.c:212`, `:232`, `:326`, `:356`, `:371`;
  - the `.ram` capture and replay: `gx.c:164`, `:528`;
  - mod patches: `mod.c:273`;
  - backtrace and string reads, which use a literal 0x81800000: `threads.c:70-73`, `trace.c:20`, `:54`.

### 1.4 A bigger MEM1 that the game uses automatically

**Do not change 0x80000028 or 0x800000F0.**

- Reporting 64 MB there takes the devkit branch. Arena hi becomes top − 24 MB, and the 0x803475AC flag turns
  on devkit `OSReport` output and a different reset path [V].
- Move only arena hi (the word at 0x80000034) and the parked FST. `OSInit` takes the word as given [V].
  `fn_801DC62C` then hands everything above heap 3 to heap 4 [V].

**Tiers:**

- **T0: `ARENA_HI` from 0x81700000 to 0x81800000** (`main.c:923`).
  - Heap 4 gains 1.1 MB.
  - It is the layout a retail boot leaves, with the FST at the top of RAM [I].
  - No bound changes, because everything stays below 24 MB.
  - It is relink-only, hours of work.
  - The FST moves, so `.ram` captures made afterwards differ. The replays of existing captures do not [I].
- **T1: 32 MB, relink-only.**
  - Commit the whole tail.
  - Park the FST under 0x82000000 and set arena hi there. Heap 4 becomes 18.6 MB.
  - Replace `MEM1_SIZE` in the bounds above with a runtime `g_ram_top` held in `main.c`. That keeps `cpu.h`
    untouched: generated code never names `MEM1_SIZE` [V: no `gen/*.c` references it].
  - Write `g_ram_top` bytes into `.ram` and accept 24 MB files in `--replay`, so the 23 pinned captures stay
    valid.
  - **What breaks:**
    - the tripwire has nothing left to guard;
    - `test_memguard.py` and `test_mods.py:160` expect a refusal at 0x81800000, so the feature must be opt-in or
      the tests must change;
    - the diagnostics bounded at 0x81800000 stop walking stacks that live above it.
  - Size: a day.
- **T2: 64 MB, a full retranslation.**
  - Set `MEM_MASK` = 0x03FFFFFF in `cpu.h`. Every chunk inlines `mem_ptr`.
  - Reserve 64 MB and put arena hi near 0x84000000. Heap 4 becomes ~50 MB.
  - **The hardware address widths hold up to 64 MB.** The port masks the EFB-copy destination with 21 bits << 5
    = 26 bits (`gxr.c:2050`) [V]. [I] The SDK's DI, AR and AI DMA and copy-destination fields are 26-bit
    physical addresses.
  - **64 MB is therefore the ceiling for anything GX or DMA touches.**
  - **What breaks:** the same as T1. In addition, 0x82000000–0x83FFFFFF stops aliasing low RAM; no code relies
    on that [I].
  - Size: several days.
- **In every tier:**
  - The four fixed heaps and the XFBs do not move.
  - Growing heap 1 (the middleware) needs three values changed. `fn_801DC62C` runs once at boot, and its only
    loop is a bounded clear, so `hooks.txt` pre-hooks are safe.
    - The end passed to `OSCreateHeap`: hook at 0x801DC7B8, after the `addis` at 0x801DC7B4.
    - The cursor recomputed at 0x801DC7C4: hook at 0x801DC7C8.
    - The size 0x600000 handed to `fn_802970A0`: hook at 0x801DC9BC, after 0x801DC9B4.
  - [I] Allocation is first-fit from low addresses (the SDK's `OSAllocFromHeap`), and the extra space only
    lengthens the top free cell. So until vanilla would have failed an allocation, nothing changes.

### 1.5 A mod-only window and host memory

- **Any guest address shares storage with MEM1.** A window outside the mask is impossible without changing
  `mem_ptr`: an address outside the 32 MB range aliases MEM1 [V, `cpu.h:117`].
- **The one free window today is the tail**, 0x81800000–0x81FFFFFF (8 MB). Its aliases are 0x01800000 and
  0xC1800000.
  - Game code never forms addresses there [V].
  - Guest code handed a pointer into it reads and writes it normally.
- **Design:**
  - `api->guest_alloc(size)` commits pages in the tail and returns a guest address. Uncommitted pages stay a
    tripwire.
  - The device-model bounds follow `g_ram_top`, so textures, vertex arrays and display lists placed there
    render.
  - `.ram` captures include the pages in use.
  - Size: a day, relink-only.
  - With T2 the window can be larger. For example, give the game 48 MB and mods 16 MB.
- **Host memory.** Mod DLLs have host memory already. The design work is the API: port-side consumers (overlay,
  audio, injected draws, textures, the sidecar) take host pointers, and only data that the *game* must read goes
  into guest memory.
- **Native thunks (see §8.3)** reserve a page of the tail as function addresses that the guest can call.

---

## 2. Fixed tables and id widths

### 2.1 Items [V]

- **Id to category:** `fn_801F4C24`, 43 call sites.
  - <80 is 0 (weapons), <160 is 1 (armor), <240 is 2 (accessories), <320 is 3 (items), <400 is 4 (key items).
  - <440 is 5, <480 is 6, and anything else is 7.
  - Categories 5–7 are further named tables; which item classes they hold is [I] unestablished.
- **Record accessor:** `fn_801F4AE4`, 25 call sites. It computes `base + (id − first) × size`:

| Category | Base | Record size | Records |
|---|---|---|---|
| Weapons | 0x802C5790 | 32 | 80 |
| Armor | 0x802C6190 | 40 | 80 |
| Accessories | 0x802C6E10 | 40 | 80 |
| Items | 0x802C7C34 | 36 | 80 |
| Key items | 0x802C8774 | 22 | 80 |
| Category 5 | 0x802D7E4C | 36 | 40 |
| Category 6 | 0x802D83EC | 40 | 40 |
| Category 7 | 0x802D8A2C | 36 | 30 |

  - The tables are packed back to back: 0x802C5790 + 80×32 = 0x802C6190, and so on.
- **Inventory functions:**
  - add: `fn_801EFDC0(id, cat)`, and `fn_801EFF0C(id)` by id;
  - remove: `fn_801EFB74`, and `fn_801EFC88` by id;
  - count held: `fn_801F452C`;
  - capacity: `fn_801F4A60`, which returns 80/80/80/80/80/40/40/30;
  - a category-base function, `fn_801F49DC`, which has no callers.
  - Script ops 20 and 21 call add and remove (story-flags.md).
- **The lists are fixed offsets in the party block.** They start at 0x8030BB48 (+852) and are addressed by
  `lis`/`addi` in each function. Entries are `{s16 id, u8 count ≤ 99, u8}`. A full list drops the item silently
  (0x801EFED0–0x801EFF08).
- **Id widths are not the limit.** Ids are s16 everywhere they are stored: equipment at character +16/+18/+20,
  and inventory entries. The limits are the ranges and the tables.
- **Placeholder records:**
  - Weapons: 6 (ids 74–79).
  - Armor: 21 (139–159).
  - Accessories: **17** (223–239).
  - Items: 3 (302–304).
  - Key items: 35 (365–399).
  - That is 82 in all. Placeholder records whose name is Shift-JIS "ダミー" were found at exact record strides.
  - A 36-byte battle table at 0x802AD440 (30 code references) holds another ~135.
- **How code reaches the tables:** 214 constant sites in 76 functions materialize a table base, some with field
  offsets folded into the constant or the displacement. For example, `fn_801F464C` does
  `lbz r3,-3182(r3)` = armor base + id×40 − 80×40 + 18. By table:
  - weapons: 30 sites in 16 functions;
  - items: 71 sites in 47 functions.
  - A further 13 functions compare against the category bounds inline.
- **What this means:**
  - A hook on the accessor reaches only the 25 callers that use it.
  - Relocating a table means changing constants in every function that holds them, and constants are C
    literals in `gen/`.
  - **The data itself is ordinary writable `.data`**, so filling the placeholder records is a data patch (M1/M6).
    A description or string that is new has to live in guest memory: the tail window, or a heap block.

### 2.2 More than 80 weapons [I, built on the V above]

1. A new id range (for example 1000+) and native versions of `fn_801F4C24`, `fn_801F4AE4`, `fn_801EFDC0`,
   `fn_801EFB74`, `fn_801F452C` and `fn_801F4A60`. These are `hle.txt` lines, one retranslation, and small leaf
   bodies.
2. Every one of the 16 weapon-table functions, and the 13 inline range checks, would compute garbage for the new
   ids. Examples: `fn_80076584` with 11 sites; the battle and stat code `fn_801F3FD0` and `fn_801EE344`; the
   16.6 KB menu `fn_801A6BDC`. Each needs the F4 guest-C dialect and a rewrite, or proof that it cannot see an
   extended id.
3. The fixed 80-slot lists live in the save, so extended inventory goes into the sidecar (§3), and the menus
   that iterate 80 slots need changing.

**Size:** week-plus. **Risk:** high; a site that is missed reads unrelated data. **Recommendation:** use the
placeholders now, and treat more than 80 as a Track F project.

### 2.3 Enemies [V]

- **The loader** is `fn_80077428` (1,888 B). It reads formation bytes with `lbzx` / `extsb`, where −1 means
  empty, and zero-extends them (0x80077A18).
  - Ids of 128 and up become `sprintf("../battle/ebinit%03d.dat", id−128)`. Ids below 128 become `ecinit%03d`.
    Either falls back to `ecinit000` (0x80077A54–0x80077AE0).
  - The disc has **125 `ebinit` and 120 `ecinit`** files, so 245 of the 255 usable values are taken.
  - Inside battle the ids are kept as halfwords (`sth r24` at 0x80077A20).
- **Per-map redirection** is the cheap route. §4's virtual FST can re-point the `ebinit` and `ecinit` entries
  when the committed map changes, so the effective enemy count is unbounded per map. It needs no engine change,
  and takes a day once §4 exists [I].
- **Widening to u16** changes the `.enp` format, this loader, and the formation reader `fn_800C24CC`. That is a
  week-plus decompilation.

### 2.4 Other fixed tables worth knowing

- **Magic.** A table of 48-byte records at 0x802C4BF0, with 60 constant sites [V].
- **Matrix stack.** A static stack of **128** 64-byte entries at 0x8030EA1C. On overflow it only calls the
  stubbed debug print (`fn_801DD76C`) [V].
- **Script opcodes.** 266 twelve-byte entries at 0x802F7940, with **no bound check** in the dispatcher
  (0x80211350). Nine entries point to `scptSTUB` (0x801F60F0) [V].
- **ARAM cache.** 16 packages (`src/soa/aramcache.h`) [V].
- **Map numbers.**
  - The 75 functions that read the map word hold 35 compares against 600 and 41 against 500 [V count; I
    meaning].
  - 142 distinct numbers are used, between 2 and 583 [V, FST].
  - So **458 free numbers below 600** can hold new maps.

---

## 3. The save

### 3.1 When the game touches the card [V]

- **Boot:** `CARDInit` (`fn_80245758`, 0x801DC658).
- **Title:** `fn_801A3510` mounts, probes and looks for `SA_LEGENDS.000`–`.006`. It is called from 0x801D9050,
  0x801D9200 and 0x80228A4C.
- **The save/load menu:**
  - It probes both slots.
  - The scan task `fn_801A2D60` **reads every existing file in full**: `memAlloc(24576)` at 0x801A3084, then
    `CARDRead` at 0x801A30F4. It clamps the file count to 7 (0x801A2EC0).
- **Save:**
  - The snapshot is taken when the menu opens: `fn_801A68C4` calls `fn_801A456C`.
  - On "Yes", `fn_801A41EC` builds the image. It copies the timestamp, XORs 3,199 words, then zeroes a
    24,576-byte image and copies the block to +5184.
  - The writer `fn_801A3B30` runs one step per frame. Step 0 mounts; steps 1–2 delete if overwriting; steps
    3–4 create 24,576 B; step 5 sets attribute 4; step 6 writes the comment, banner and icon to +0…5184; step 7
    is `CARDWriteAsync`; step 8 waits, sets status, closes and unmounts. **Success is step 9** (0x801A3FC8).
- **Load:**
  - `fn_801A4070` does `CARDOpen` and reads 24,576 B into an image.
  - Menu state 18 checks the XOR of 12,796 bytes (0x8019F4C0–0x8019F508) and calls **`fn_801A4354(block)`**
    (0x8019F50C) with `block = image + 5184`.
- **The EXI model** writes each programmed page straight through to `build/cards/slotA.raw` (`exi.c`,
  `card_flush`).
- **Every one of these functions has a single call site:** `fn_801A4354`, `fn_801A456C`, `fn_801A41EC`,
  `fn_801A3B30` and `fn_801A4070`.
- **The flag clear** `fn_801CAF30` runs at boot (0x801DBF64) and at New Game (0x80228BF0).

### 3.2 Free space inside the save file [V]

| Where in the 24,576-byte file | Size | Checked by the game? | Restored by `fn_801A4354`? |
|---|---|---|---|
| Block +5916…+9071 (between position data and flags) | **3,156 B** | **yes**, inside the XOR (the block comes from `memCalloc`) | no |
| Block +5813…+5863 | 51 B | yes | no |
| Block +12784…+12785 | 2 B | yes | no |
| File +17,984…+24,575 (after the block) | **6,592 B** | no | no; but read into the image |

- **The XOR is computed in `fn_801A41EC`, after `fn_801A456C`.** Bytes written into the gap at the end of
  `fn_801A456C` are therefore covered by the game's own check.
- **A modded save stays valid in vanilla:**
  - vanilla recomputes the XOR over the same bytes and ignores the gap and the tail;
  - the CARD library checksums only its system blocks (`__CARDCheckSum` over 8188/508 B, `config/names.txt`).

### 3.3 Hook points

| Event | Site | Registers | Loops that wait on an interrupt? |
|---|---|---|---|
| save snapshot (menu opened; may be cancelled) | `fn_801A456C` before return, 0x801A4670 | r31 = block | none |
| image built for file N (player confirmed) | `fn_801A41EC` at 0x801A4334 | r31 = 0x803081A4 descriptor: +0 image, +4 name `SA_LEGENDS.00N`, +24 channel | the XOR loop only; bounded, harmless |
| save loaded (the XOR passed) | `fn_801A4354` entry | r3 = block; image = r3 − 5184 | a 6-pass name loop, harmless |
| new game / boot reset | `fn_801CAF30` entry | — | clear loops, harmless |
| save written successfully (for user feedback only) | writer step 8 → 9, 0x801A3FC8 | — | **yes** |

- **Why not `hooks.txt` inside `fn_801A3B30`.** It spins on the CARD busy state at 0x801A3CC4–0x801A3CDC,
  0x801A3CF4–0x801A3D0C and 0x801A3F10–0x801A3F28, and a `hooks.txt` entry strips `irq_poll` from those
  back-edges (`emit.py:240`, `:309`).
- **Use an M13 post-wrapper there, or do without the event.** The four other sites are safe as `hooks.txt`
  entries. That is one retranslation, or M13 sites.

### 3.4 Sidecar design

**On save:**

1. At the snapshot hook, mods serialize their state into chunks `{mod id, version, bytes}`. The runtime writes a
   header `{magic 'SOAX', version, GUID(16), total, CRC32}` plus as many chunks as fit into the block gap. The
   game's XOR then covers them.
2. At the image hook, a fresh **GUID per save event** and the overflow chunks go into the 6,592-byte tail.
   Anything larger goes to `saves/ext/<GUID>.soax`, written as temp-then-rename. **Blobs are never modified
   after they are written.**

**On load:** the load hook reads the gap and tail from `image = r3 − 5184`, checks the CRC, fetches the blob by
GUID if one is referenced, and calls `on_save_loaded(chunks)`. A vanilla save, with no magic, gives each mod
its defaults.

**Why it stays consistent:**

| Case | What happens |
|---|---|
| Copy, by any tool or by copying the card image | The GUID travels in the file, and both copies point at the same immutable snapshot, which is correct |
| Delete, or overwrite with a new save | The old blob becomes an orphan. A GC pass (for example `cardformat.py gc`) keeps only the GUIDs still present on known cards. The game's own overwrite is delete-then-create (steps 1–3), so a crash there loses the save exactly as vanilla does, and leaves only an orphan |
| A save that fails after the image hook | Harmless: the file on the card still names its old GUID. **No commit event is needed for correctness** |
| Taken to Dolphin or real hardware | Loads, with the mod state ignored |
| One menu session, several saves | The snapshot is taken once when the menu opens, as the game does, and each "Yes" mints a new GUID |

**New Game** calls `on_new_game` from the `fn_801CAF30` hook. [I] Because `fn_801CAF30` also runs at boot,
mods reset at boot too.

**Size and risk:** several days, med. The risk is ordering: the gap must be written before `fn_801A41EC`'s
XOR, which it is by construction.

### 3.5 Flags

- **The dormant range.** The flag set covers 0–27,327 [V]. The prompt reports that field scripts never touch
  3,072–19,455.
- **No fixed engine accesses either.** No absolute load or store in the DOL touches the words holding flags
  3,072–27,327, 0x80310CBC–0x80311893 [V, EA scan].
- **What cannot be excluded statically.** Computed indices through the base 0x80310B3C, which 160 functions
  materialize, cannot be ruled out.
- **Confirm it** with `SOA_WATCH=0x80310CBC,0x800` over the soak scenarios. Zero hits supports the reading.
- **A registry.** The 16,384 flags persist in vanilla saves for free. A registry that hands out named blocks to
  mods avoids collisions.
- **Beyond 27,328,** or for per-mod namespaces, use sidecar chunks.

### 3.6 More than 7 saves

- **The cap.** The 7 is an immediate (0x801A2EC0), and the menu keeps 44-byte entries per file in its 624-byte
  context. Raising it means decompiling the menu: week-plus.
- **Cheap alternatives, relink-only:**
  - **Slot B:** today only channel 0 reports `EXT` (`exi.c:543`), and the SRAM entry says there is no card in
    slot B (`exi.c:426`). The game's menu already probes both slots. Make the card state per slot. That gives
    +7, in a day.
  - **A card-page switcher:** swap the slot A backing file (`exi.c`, `card_load` and `g_card_path`) when the
    save menu is closed (0x803473C4 == 1) and no card is mounted. The writer and the title poll unmount after
    each operation (0x801A3F50, 0x801A4014) [V]. That gives unlimited pages of 7, in a day to several days.
- **Not a lever:** a bigger card (`CARD_BYTES`/`CARD_ID`, `exi.c:72`, `:80`) does not raise the 7.

---

## 4. The disc and files

**Facts [V]:**

- The FST has 5,560 entries: 5,552 files and 7 directories.
- It is 134,426 B, with 67,706 B of names.
- The data ends at 1,363 MB of the 1,460 MB image.
- The largest file is 4.28 MB.
- The formats present are 1,791 `.mld`, 620 `.dsp`, 590 `.samp`, 258 `.sct`, and more.
- Entries hold u32 byte offsets and lengths, so 4 GB is addressable.
- The DI read offset is `cmd[1] << 2` (`dvd.c:129`) and is served from one `disc.iso` (`dvd.c:91-115`).
- The FST is parked just below `ARENA_HI`, and arena hi is set to the FST's address (`main.c:1143-1161`). Each
  added entry costs about 12 B plus its name, taken from heap 4.

**Limits [I unless marked]:**

- The engine resolves files by path through the SDK's FST walk. The FST imposes no practical cap on file count.
- **In practice a file must fit the largest free heap block.** The game loads whole files; heap 4's largest free
  block is ≥3.75 MB [V], or ~18 or ~48 MB after §1.
- **Some reads have a baked size.** `FontData.US` is read as exactly 0x13020 bytes (0x801E36E8) [V].
- **The ARAM package cache** names 16 fixed paths [V].

**The virtual disc, relink-only, several days:**

1. **At boot,** rebuild the FST from a tree before parking it (`main.c:1143`):
   - replaced files get their entry re-pointed to a virtual offset;
   - new files are inserted into their directory;
   - the parent and next indices are renumbered;
   - `0x8000003C` gets the new size.
   - Virtual offsets start above the image, for example at 0x60000000.
2. **In `dvd.c`,** `disc_read` checks a sorted overlay table before `disc.iso` and serves host files. The DI
   timing model is unchanged.
3. **Per map,** at the safe point, when the committed map (0x80311AC0) or the pending one (0x80311AC4 and the
   name at 0x80305CF0) changes, entries are re-pointed in guest memory. That is how enemies are redirected per
   map (§2.3).
4. **`aram.c`'s census of sources** indexes FST offsets, so it must learn the virtual files too.

- **What it unlocks:** new maps, as `me%03d%c.sct` plus `a%03d%c.mld`, `.ect`, `.enp` and `.tec` under the 458
  free map numbers. Also new or replaced models, textures inside NMLD, scripts, music (`.dsp`) and enemy files.
  All of it goes through the game's own loaders.

**Files the game never sees:** port-side systems open host files directly from the mod's folder. For example:

- PNG through WIC (M9);
- OGG or FLAC decoded by the mod DLL or by Media Foundation — `vendor/` is forbidden, so no decoder lives in the
  repository;
- meshes supplied by the mod.

**Nothing crosses into guest memory** unless a mod puts it there.

---

## 5. Text and fonts

### 5.1 What exists [V]

**`FontData.US`** is 77,856 B, which is **0x13020, the exact size of its buffer.** The buffer is allocated from
heap 3 at 0x801E372C and read at 0x801E36E8. There is no headroom.

**The header** holds two tables of 8-byte entries `{u16 compressed, u16 size, u32 offset}`:

- **Table 0:** 48 entries at 0x20.
  - These are ASCII 0x20–0x7F, **two half-width 12×24 characters per 24×24 I4 cell**.
  - The lookup indexes `(c−32)/2`; I rendered one cell to confirm it.
- **Table 1:** 640 entries at 0x1A0. 609 are compressed and 31 raw.

**The lookup `fn_801E26E0(code u16)`:**

- Below 128, it goes to table 0.
- Otherwise it takes 4 Shift-JIS ranges from `{lo, hi, table, base}` at 0x802F6758:
  - 0x8140–0x81AB, symbols;
  - 0x824F–0x82F1, full-width alphanumerics and hiragana;
  - 0x8340–0x83AA, katakana and part of the Greek range;
  - 0x8754–0x875D, numerals.
- Then 15 `{code, index}` specials at 0x802F6778, codes 0x8443–0x8474, indices 0x243–0x274.
- The loop bounds of 4 and 15 are baked in (`cmpli r10,4`, `cmpli r6,15`).
- About 99 slots in table 1 are unreachable: 0x1EB–0x242 and 0x275–0x27F.

**Accented Latin is not in the US font** [I; SJIS has no code for it and no range maps any].

**Glyphs** are decoded into a 0x24000-byte cache: 512 slots of 288 B at the word at 0x8034773C, with the slot
index at 0x80347738. They are drawn as quads on texture map 7 (FINDINGS §9; `fn_801E203C`).

**Before `FontData` has loaded,** text goes down a second path: while the font state at 0x80347710 is below 3,
`fn_801E203C` draws through `fn_80235270` (0x801E20F0–0x801E213C) [V].
- `fn_801E3718` sizes a buffer by `fn_80234E58` and fills it through `fn_80234F3C` (0x801E375C–0x801E37B4) [V].
- I read these as the SDK's font encoding, `OSLoadFont` and texel calls, which read the console's ROM font [I].
- The port provides no IPL ROM (`exi.c:5`). [I] Early error messages would be blank.

### 5.2 New glyphs, or a whole Unicode font

- **Replacing glyphs within the budget** is a file replacement through §4. It is tight, because the compressed
  sizes must still total 0x13020 or less.
- **More room** needs two pre-hooks, both boot-time and loop-free. Heap 3 has 186–216 KB free in the
  captures [V].
  - At 0x801E3740, the `OSAllocFromHeap` call, set r4 to the new size.
  - At 0x801E36F0, the `DVDReadAsync` call, set r5. A hook at 0x801E36E8 would run before the `addi` that sets
    r5.
- **New code points:**
  - The range and special tables are writable `.data`, but their counts are baked.
  - A **native `fn_801E26E0`** (one `hle.txt` line, a leaf) removes that limit. It maps any 16-bit code onto a
    glyph table the port builds at boot, rasterized from a TTF into 24×24 I4, and parked in the tail window or
    a heap-3 block.
  - Unused SJIS codes, for example the ~4,000 kanji codes, then serve as the carrier for accented Latin,
    Cyrillic or a CJK subset.
- **A full translation also needs:**
  - the text in `.sct` files (§4);
  - DOL strings, such as item names in `.data` (patches);
  - text baked into textures (M9);
  - [I] whatever layout assumes half-width ASCII against full-width SJIS advances.
- **Size:** a day to several days for the glyph side; week-plus for a translation pipeline.

### 5.3 Letting the port draw the text

This is feasible without guest hooks [I]:

1. The port can hash every glyph bitmap in `FontData` at load, giving glyph hash → character. For ASCII, the
   quad's UVs pick the half.
2. The texture cache already hashes each texture's source bytes (`gxr_tev.c:208-227`). A draw sampling an
   address inside the glyph cache can therefore be identified: which character, where on screen, and with what
   colour and alpha (from TEV konst and the vertex colours).
3. The renderer suppresses those quads and records them.
4. The overlay (M8, `window.c` `present()`) draws the text at window resolution with DirectWrite or GDI.

**Pitfalls:**

- text rendered into an EFB-copy texture;
- fades, which must be mirrored;
- interpolation and widescreen transforms.

**Size:** week-plus. **Rebuild:** relink only.

---

## 6. Audio

**Limits [V]:**

- **Voices.** Sega's driver keeps a table of 64 records of 244 bytes: the loop bound is the byte at
  0x80347DC5, which reads 64 in the battle capture (`fn_8027C414`). [I] That is the SDK's 64-voice limit.
- **Observed load.** The census reports a longest chain of 44–46 voices (`build/h1-L9000.log`,
  `cap-battle.log`).
- **Format.** Every voice-frame was ADPCM: format 0 for 100% of 103,104. The mixer also takes PCM8 and PCM16
  (`ax.c:1-12`).
- **Rate.** Voices are mixed at 32 kHz, and the AI blocks go out at 32 kHz (`dsp.c:222`).
- **ARAM** is 16 MB (`aram.c:24`); the named uploads span about 8.3 MB (§1.2). Music streams as `_l.dsp` and
  `_r.dsp` pairs (`is_stream` 1).
- **Output** is `waveOut`, 24 blocks of 4 KB, and a block is dropped when none is free (`audio_out.c:17-18`,
  `:113`).

**Host audio the game never sees:**

- **Where.** Mix in `audio_push_block` (`audio_out.c:97-131`). It runs after the guest, so the game never reads
  it. Mixing in `ax.c` `output_samples` (`:634-645`) would write into guest memory, which is avoidable.
- **What.** Unlimited voices and streamed OGG or FLAC, decoded by the mod or by Media Foundation. The AI DMA
  period sets the pace, so it rides the guest clock; `SOA_WAV` captures it if the mixing happens before
  `wav_append`.
- **Size.** A day.
- **Later.** A WASAPI output at 48 kHz, which resamples the game's stream.

**Music replacement [I]:**

1. `aram.c`'s census already names what each voice's samples were uploaded from (`starts by source` lines,
   for example `m01_l.dsp`).
2. When a voice starts on a mapped music source, the port's mixer mutes it (in `process_voice`, never in the
   guest PB) and starts the host stream.
3. The host stream follows the voice's volume envelope, and its stop and loop.

**Size:** several days. **Risk:** med; streamed sources are refilled chunk by chunk, so the mapping must key on
the stream, not the chunk.

---

## 7. Rendering

**Limits [V]:**

- **EFB.** A static `uint8_t g_efb[528][640][4]` and a 24-bit depth buffer (`gxr.c:108-109`, `gxr.h:9-10`).
  Copy fields are 10 bits wide (`gxr.c:2004-2005`).
- **Textures.** The decoder covers every GX format, C14X2 and CMPR included (`gxr_tev.c:346-423`), with
  `MAX_MIPS` 11 (`gxr.h:78`). Sizes come from the GX registers, so up to 1024² [I, from the width of the GX
  register fields].
- **Texture cache.** 256 slots of decoded RGBA8 (`gxr_tev.c:44`); H12 plans to grow it. (1,024 since H12,
  2026-09-25.)
- **The port adds no limit tighter than GX's.** Replacement textures (M9) are host-side, of any size, and are
  sampled through `lw/w`.
- **Geometry.** There is no polygon budget: a 4,096-command ring and a 48 MB vertex arena simply flush when full
  (`gxr.c:704-706`, `:1568`).
- **The real budget is time,** 86–175 ns per fragment (PLAN H1 and H6).
- **Game-side budgets** apply to anything drawn *through the game*:
  - the 128-entry matrix stack (§2.4);
  - the middleware pools sized at boot (§1.1).

**Injected draws (relink-only, several days):**

- **The API.** Add `gxr_inject(slot, fn)`. It runs on the producer thread and builds `DrawCmd`s directly from
  host meshes: clip-space `Vertex` values, a small `TevSetup`, and the current `PixelCfg`/`RasterCfg` snapshot
  (`gxr.c:1543-1620`).
- **Two slots:**
  - **(a) Pre-HUD.** At the first orthographic draw (XF 0x1026 bit 0 set) after perspective draws in a frame
    [I, a heuristic]. This is for world props, depth-tested against the game's EFB z.
  - **(b) Pre-XFB.** In `enqueue_copy` when `v & 0x4000` (`gxr.c:2001-2006`), before the copy is queued. This is
    for markers and overlays in EFB space.
- **The camera.**
  - XF matrices hold model-view per draw, so a world-space mesh needs the view matrix alone.
  - Take it from the middleware's camera, which M12 must locate; 0x80347EB4 is a candidate [I].
  - The projection comes from XF 0x1020–0x1026 [V].
- **Pitfalls:**
  - **Depth.** Use the same projection and viewport, or z will not agree.
  - **Lighting.** Use the port's own shading, or reuse the XF light registers, which hold view-space positions
    [I].
  - **Fog.** Reuse the BP fog state.
  - **EFB copies to texture.** The game copies the EFB to textures during the frame, so a draw injected before a
    copy shows up in effects and one injected after does not.
  - **Interpolation (H17).** Injected draws need per-tick transforms if they are to be interpolated.
  - **The contract.** Off by default; the 23 hashes are unchanged.

---

## 8. Logic and CPU

### 8.1 The safe point

- **Where it runs [V].** `tick.c` runs up to 8 callbacks (`SAFE_POINT_MAX`) when `VIGetRetraceCount` is called
  from 0x801DCB88, the top of `main`'s loop.
  - It runs on the guest CPU thread.
  - It runs before the frame's start stamp (0x8034768C) is read.
  - No GX is in progress and no guest thread is mid-update.
- **Its cost.** Work there is wall time on the guest thread, and the guest clock is the wall clock × `SOA_SPEED`.
  - Callbacks plus the frame must fit in two fields.
  - Guest work is a median of 11.9 ms per frame and 18.2 ms at most (PLAN H-track), so about 15 ms is spare
    against 33.3 ms.
  - With the tick unlocked (M11) the budget is one field, and heavy scenes already miss it (H2).
- **"No guest cost" holds only for work on mod-owned host threads.** The safe point should only exchange
  snapshots and requests, in microseconds. [I] The guest thread sits in `SelectThread` 37–49% of the time, so
  the cores are there.

### 8.2 What is safe to call through M4's `call_guest` [I, from the code read]

**Safe:**

- guest memory through the big-endian accessors;
- the item functions `fn_801EFF0C` and `fn_801EFC88`;
- the save-request setters `fn_80123E9C` and `fn_80123E8C`;
- the allocator `memAlloc`/`memFree` (`fn_801E1A2C` / `fn_801E17E0`), for placing mod data in the game's heap;
- word writes that the FINDINGS recipes use: warps, forced battles, fade fixes.

**Unsafe:**

- **GX calls.** The frame has not begun; draw through §7 instead.
- **Task bodies and script handlers.** They expect a task or script context in r3.
- **Scene-specific code outside its scene**, for example battle functions in the field.
- **Anything that waits on DVD or card completion.** It is legal but stalls the frame.
- **Anything at all from the frame hook,** which runs inside a gather-pipe store (PLAN M1).

**Interactions:**

- A callee may `OSSleepThread`. Guest threads are cooperative fibers, so another guest thread runs and it
  resumes; it is not a deadlock.
- An interrupt handler that "rfi"s `longjmp`s within the call.

### 8.3 Native thunks: guest code calling native code with no retranslation [V mechanism, I use]

**The mechanism:**

- `bcctrl` and `bclrl` are emitted as `dispatch(s, target)` (`emit.py:579`, `:586`), and a resolved
  unknown-target `bl` is emitted the same way (`emit.py:298`).
- `dispatch`'s default case is `guest_trap(s, addr)` (`emit.py:282`), which is runtime code at `hle.c:244`.
- If `guest_trap` first looks up a registry of reserved addresses, for example 0x81FFF000 + 4n in the tail
  (never guest code), mods can plant those addresses into **any guest function pointer**:
  - **New script opcodes.** Re-point the 9 `scptSTUB` entries of the table at 0x802F7940 (it is `.data`). The
    handler gets the script context in r3/r4 and returns r3, like the originals.
  - **Game tasks with a native body.** They run in the game's own task order every frame. The task-create API
    still needs to be identified: the save-point task is made by `fn_80123EE4`, and the save menu task by
    `fn_801A21F8`.
  - Middleware and driver callbacks.
- **Limits:**
  - direct `bl` calls cannot be redirected this way; they need `hle.txt` or M13;
  - tail jumps to unknown targets still trap (`emit.py:313`);
  - the thunk must preserve r1, r2, r13 and the non-volatile registers.
- **Size:** a day. **Rebuild:** relink.

---

## 9. Input and network

**Today [V]:**

- `window_pad` polls keys with `GetAsyncKeyState` and pad 0 through XInput, on the guest thread, twice per
  frame (`window.c:191-240`).
- `wndproc` handles only Escape and has no mouse messages (`window.c:41-50`).
- The client area is 640×480 × `SOA_SCALE` (`window.c:104`).
- The pad script and recording live in `si.c`.

**Mouse and hotkeys (a day, relink):**

- Handle `WM_MOUSEMOVE`, the button messages, `WM_INPUT` (raw, relative motion) and `WM_KEYDOWN` on the UI thread.
- Push them onto a lock-free queue, drained at the safe point. Polling loses presses between polls.
- Map the cursor to EFB coordinates by `SOA_SCALE`.
- Uses:
  - mod UIs through the overlay (M8);
  - a mouse camera, as a `pad_filter` onto the C-stick once M12 shows whether the field reads it;
  - picking in the world, with the camera matrices from §7.
- Hotkeys should avoid the pad keys (X Z C V R Q E T F G H, WASD, IJKL, arrows, Enter, Space).
- **Recording:** input events and hotkeys that change state must go into the `SOA_PAD_RECORD` file as an event
  track. Otherwise a modded session does not replay.

**Network (the API is a day; the rest is up to each DLL):**

- DLLs already have Winsock. The rules:
  - never block the guest thread;
  - own a thread;
  - exchange at the safe point.
- **Asynchronous features work:** ghost ships drawn through §7, shared markers, leaderboards, chat, remote
  spectating from `g_screen`.
- **Lockstep co-op does not,** without D4's deterministic clock: the guest timebase is the wall clock
  (PLAN D4), and would also need deterministic input timing.
- **Risks:**
  - DLLs run with full rights and no sandbox (PLAN M3);
  - network-driven changes must be logged, or they break replay.

---

## 10. Recommended architecture

**The aim:** the smallest set of port changes that lifts the most limits. Every piece is off by default and
keeps the contract: 23/23, the self test, `title --check`, `decomp.py`, and `test_memguard`/`test_mods`
unchanged with the switches off.

### E1. An extended-content layer (`runtime/ext.c`) with a sidecar save

- **Guest memory:**
  - a runtime `g_ram_top` for the device-model bounds and captures;
  - T0 (`ARENA_HI` 0x81800000) as a free win;
  - the **8 MB tail as the mod window**, committed on request. The unrequested part stays a tripwire.
  - Optional: T1 hands the tail to heap 4 instead.
  - Relink.
- **Native thunks** in `guest_trap`, plus a registry. Relink.
- **Save extension:**
  - four hook sites: 0x801A4670, 0x801A4334, `fn_801A4354`, `fn_801CAF30`;
  - the in-file container (3,156 B gap plus 6,592 B tail), and GUID-addressed immutable blobs;
  - `on_new_game`, `on_save_snapshot` and `on_save_loaded`;
  - a registry of named flags from the dormant 3072–19455 range.
  - **This is the one retranslation.** Or reuse M13 sites.
- **An item and data catalog** over the 82 placeholder records: names and descriptions live in the mod window.
  Data patches only.

### E2. A file-table extension (the virtual disc)

- The FST is rebuilt at boot, with an overlay in `dvd.c` and per-map re-pointing at the safe point.
- Relink, several days.
- It lifts: new maps, scripts (with native opcodes from E1), models, music, and enemies per map.

### E3. Host assets and outputs

- a host audio mixer in `audio_push_block`;
- the injected-draw API (the pre-HUD and pre-XFB slots);
- the overlay (M8) and texture packs (M9);
- the input event queue.
- All relink.

### E4. The native call surface already planned

- M3 (`mod.dll` and `SoaModApi`), M4 (`call_guest`), and M13 (`modsites.txt` for pre/post wrappers).
- E1–E3 are what M3's API exposes.

### Sequence

1. **Relink-only first, about a week:** `g_ram_top` with T0 and the tail window; thunks; the virtual disc; host
   audio; the input queue; the draw-injection slots behind setters, so the renderer still links alone.
2. **One retranslation:**
   - the four save hooks;
   - the native glyph lookup and the two font-size hooks;
   - optionally the heap-size hooks in `fn_801DC62C`.
3. **Optional, with its own retranslation:** `MEM_MASK` to 64 MB (T2), once a mod actually needs more than 8 MB
   of window plus heap.

**Left for Track F or never:**

- more than 80 per item category, or globally more than 255 enemies. Each is week-plus; rewrite the functions
  that hold baked table addresses;
- more than 7 saves per card, which needs the menu decompiled; slot B and card pages are the substitute;
- a higher internal resolution, which is GPU-gated;
- logic at 60 ticks.

### Biggest risks

1. **Save compatibility.**
   - Write only the gap and the tail, never a byte the game restores.
   - Write the gap before the game computes its XOR.
   - Mint a new GUID on every save.
   - Test round-trips with `cardformat.py`, and in vanilla.
2. **The contract and the tripwire.**
   - `g_ram_top` changes a dozen bounds, one of which fails runs as "bad vertex refs" if it is wrong.
   - The capture format changes.
   - The tests expect a tripwire at 0x81800000.
   - Keep all of it opt-in, and mutate an input to prove each new check can fail.
3. **`hooks.txt` inside loops that wait on interrupts.** It strips `irq_poll`; `fn_801A3B30` is the example.
   Use loop-free sites or M13.
4. **Game-side budgets that stay fixed:** the matrix stack, the middleware pools, the 1024² GX textures, and the
   64-voice driver. They bite mods that add content *through the game*. Port-side paths (injected draws, host
   audio, replacement textures) avoid them.
5. **Determinism.** DLL, network and hotkey inputs must be recorded, or replays of modded sessions break.
   Lockstep needs D4.
6. **Game data.** Blobs, packs, fonts and captures stay out of the repository. The guard needs the new directory
   names.
