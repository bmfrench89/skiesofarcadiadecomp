<!-- Written 2026-09-25 by the planning session, read-only; revised the same day after two reviews at
`main` b071949, then checked again at `main` 012164a in a consistency review across the five planning
documents (its entries close the review log). Since b071949: P6 (24d9235), C5a (750cef0), P6b (79c9ad8),
manifest 2's second follow-up (b1199b3) and T0c (012164a) have landed. Line numbers are at b071949 unless
marked; P6 and P6b changed hle.c, main.c, selftest.c, settings.c and si.c and added seed.c, C5a added 125
lines to gx.c (from :53), and b1199b3 and P1a touch mod.c, so citations into those have moved. gxr.c
moves most, so it is also cited by function name. At 012164a the working tree held the implementation
session's uncommitted P1a. This session ran nothing in the game. [V] means read at file:line, in gen/*.c,
in the disassembly (`python tools/disasm.py`), or in a run recorded in FINDINGS; [V run] means a run the
implementation session reported, with its log named. [I] means inferred. One compile probe was run in a
scratch directory (section 2.9). This file supersedes docs/specs/now.md from now.md's first row that has
not landed, which is N5's P1 (now.md's own rule). The order across all plans is ../PLAN-NEXT.md. The
review log is the last section. -->

# The comfort pack (gameplay milestone 1), implementation-ready

## 1. Purpose and scope

**What you get.** The comfort pack is the set of small changes that make the port nicer to play every
day, before any gameplay mod changes the rules. Each one is off until you switch it on in `soa.ini`
(the settings file beside the game), and each can be switched on alone. Three of them are mods (P1, P11,
P10b). `python tools/recompile.py --link` builds them along with the port (P1a adds that), and they load
from the `mods` folder. Until M5b does it for you, `soa.ini` also needs a `mods = <your SOA folder>\mods`
line. Without it, `encounters = half` only prints a line saying that no such mod is loaded.

| You get | Slice | In plain words |
|---|---|---|
| Fewer, more or no random battles, and "hold B to avoid" | P1a, P1b | A mod that scales the game's own encounter multiplier. Presets: off, half, normal, double. |
| A pinned random seed | P6 and P6b (**landed**, 24d9235 and 79c9ad8) | The game re-rolls its dice at every map load and battle start from the clock. With a seed set, those re-rolls take the same values every run, which is what races and our own battle tests need. Whether whole battles then repeat is a later question (K6). |
| Dialogue that advances itself, and hold-to-skip | P11, P11b | A mod that presses A for you when a text page has finished and waited a moment, and never on a choice. Holding LB skips quickly. |
| Couch co-op in battles, and online through Parsec | P10a, P10b | A second pad commands the party members you give it; player 1 keeps everything else. |
| Rumble | M18 | The game already sends rumble on/off; the port finally passes it to the pad. |
| Fullscreen, a window that fits a 7–8 inch screen, no stray cursor | H19a | Borderless fullscreen (F11, Alt+Enter or a pad chord), a resizable, DPI-aware window, black bars instead of stretching. |
| Every port action from the pad | CH1 | Chords on the buttons the game never uses (View, LB, the stick clicks), and port 1 follows whichever pad is connected. |
| A clock that survives sleep | M19 | Closing the handheld's lid no longer makes the game think 30 seconds passed in one frame. |
| Double-click start that finds your saves | M5b | Relative paths stop depending on where the game was launched from; the console hides and the log goes to a file. |
| Saves to and from Dolphin | P3 | `cardformat.py import` / `export` of `.gci` files. |
| Picture options | P5a, P5b | Gamma, colour-blind correction, a flash limiter, a CRT look, a sharp scaler; and "deflicker off" for a crisper image. |
| Battle turbo | M11a | Battles (and, if you choose, sailing) at up to 2× by letting the game's frame cap go, not by speeding its clock. |
| Guard and manifest groundwork | T0, MV2, T0c (**landed**) | The repository refuses the new kinds of game data these features create; mods have a stable id and version. Landed at 3949028, b071949 and b1199b3 (MV2), 1c7b780 and 4041dfc (T0), and 012164a (T0c, the one gap left). |

**Not in scope.** Turbo past 2× (M11b, after M19 and S9), the M8 overlay and its input withholding,
M16's declared mod options (until then each mod reads an environment variable that `soa.ini` sets),
the event track that records chord and pad-2 input (milestone 2), H9's VI lock, H17's interpolation,
and any GPU work. The disc layer (I-track), portability (L-track) and the GPU decision (V-track) are
separate specs; section 5 lists where they touch this one.

**The contract.** With a slice's feature off: `python tools/scenario.py replay` stays 23/23, the self
test (`$env:SOA_SELFTEST='1'; gen\soa.exe extracted`) passes, `python tools/scenario.py run title
--check` passes, `python tools/decomp.py` is unchanged, and `python -m pytest
tools/tests/test_memguard.py tools/tests/test_mods.py` passes. "The contract holds" below means all
five. Two slices change every run by design and say so: M19 (the clock's source) and CH1 (which XInput
slot is port 1); both are headless-neutral and keep the five checks.

**How this relates to now.md.** Of `docs/specs/now.md`'s rows, these have landed:
- N1, the status lines (cb469d6);
- N2, manifest v2 (3949028, then b071949 for the API minimum and one API constant);
- N3, T0 (1c7b780, then 4041dfc, which brought it to this spec's design);
- N4, the acquire loads in gxr.c's render queue (c8274db).

N5's P6 landed as 24d9235 (FINDINGS "P6"), and its remainder, P6b (3.3), as 79c9ad8 (FINDINGS "P6,
followed up"). N6's spike ran and passed (b911380, FINDINGS "P11's spike"). This spec takes
over from N5's P1. One correction still matters: hold-to-skip needs CH1's host buttons, so N6 should
ship auto-advance only (P11), and P11b follows CH1. [../PLAN-NEXT.md](../PLAN-NEXT.md) sets the order
of these slices among the other plans' (its C1).

---

## 2. Current state, with file:line

### 2.1 Mods (`runtime/mod.c`, `runtime/mod.h`, `runtime/soa_mod.h`)
- **Manifest 2 landed** (3949028). `manifest = 2` requires `id` and `version` and allows `authors`. `api`
  is the least API needed (`mod.c:878-884`). An `x_` key warns and loads. A second mod with an id
  already loaded is refused (`mod.c:907-908`). The recording says `id@version:hash`. Both shipped
  `mod.ini` files are manifest 2, and `test_the_shipped_mods_are_manifest_2` (`test_mods.py:965`)
  requires that. Version 1 stays covered by the synthetic default ini in the `mod()` helper
  (`test_mods.py:192`) [V].
- **One API constant landed** (b071949): `mod.h:13-15` is `#ifndef MOD_API` / `#define MOD_API
  ((int)SOA_MOD_API_VERSION)`. `test_api_is_the_least_the_mod_needs` (`test_mods.py:988`) builds the loader
  at API 2, where `api = 1` and `2` load and `3` is refused. A v2 file with no `api` is told "no `api = `"
  (`mod.c:910`) [V].
- **The recording line's tail is keyed by id** (b1199b3): the `+N more:HASH` tail for mods that do not
  fit now hashes each by the name the line would give it (`id@version` for manifest 2), so renaming a
  manifest 2 mod's folder does not change a recording's line [V, FINDINGS "Manifest 2" amendment].
- `SoaModApi` ends at `call_guest` (`soa_mod.h:139`). Every addition since v1 was appended with the
  version left at 1 and gated by `api->size` (`SOA_MOD_HAS`, `soa_mod.h:146`) [V].
- **A DLL has no report hook.** `mod_report` (`mod.c:1083-1113`) prints a DLL mod's callback counts
  and nothing of its own. `g_cur_mod` (`mod.c:393`) names whose callback is running, and the write
  functions (`mod.c:438-450`) do not count anything [V].
- Load order is a byte-wise `strcmp` sort of folder names (`qsort`, `mod.c:1003`) [V]. `SOA_MODS=mods`
  loads every folder in `mods/`, so `mods/encounters-off` (always "encounters off",
  `mods/encounters-off/patches.txt`) loads beside anything new put there [V].
- `pad_filter` runs after the recording has its copy and before the `[si]` log (`si.c:758-763`) [V].
- Nothing builds a shipped mod's DLL. `examples/mods/map-log/mod.c:8` gives the `cl /LD` line to type,
  and `.gitignore:30-31` ignores `*.dll` [V].

### 2.2 Settings (`runtime/settings.c`)
- Nine keys (`settings.c:39-48`), each an environment variable set with `_putenv_s` only where the
  environment is silent. The file is `soa.ini` beside the exe, i.e. `gen\soa.ini` (README.md:151).
  `SOA_SETTINGS=0` turns it off, and scenario.py and perfbench.py set that (`test_settings.py:138-145`)
  [V].
- `main.c:1122-1125` loads it before any switch is read; mods load later (`main.c:1178-1185`) [V].
- **Landed with P6 (24d9235):** `Setting` gains a `recorded` flag, `seed` is the tenth key, and
  `settings_recorded()` joins `key=value` for each recorded key that is set. main.c joins that and
  `mod_describe()` into a `static char extra[320]` and hands it to `si_set_config_extra` [V]. P6b
  (79c9ad8) grew that buffer to 640 bytes (3.3).

### 2.3 Controller (`runtime/si.c`, `runtime/window.c`)
- Port 1 only: `g_present = {1,0,0,0}` (`si.c:74`) [V]. The `SOA_PAD` grammar is parsed at
  `si.c:92-157`, with `+` joining buttons (`si.c:118`, `:128`). scenario.py keeps a second copy
  (`tools/scenario.py:132-133`, `:233-244`) [V].
- The recording's `# config` line is `pad_config` (`si.c:292-304`); mods reach it through
  `si_set_config_extra` (`si.c:287-290`), whose buffer `g_cfg_extra` is 320 bytes (`si.c:282`) and is
  filled by a silent `snprintf`. The line is built into 768-byte buffers (`si.c:333`, `:502`). The card
  path in it is `SOA_CARD` as given (`si.c:294`) [V].
- `PadEvent` holds `uint16_t buttons` (`si.c:79`), and `BTN_ALL` is `0x1F7F` (`si.c:59`), so bits 7,
  13, 14 and 15 are unused. `pad_sample` (`si.c:704-717`) merges `window_pad` and the script and
  masks with `BTN_ALL`. `pad_report` (`si.c:730-770`) latches the first read of a frame only while
  recording. Otherwise every read samples afresh [V].
- `SICnOUTBUF` writes are stored in `g_outbuf` and never acted on (`si.c:869`) [V].
- `test_padrec.py` builds `si.c` alone with stubs, `window_pad` among them (`test_padrec.py:67`,
  `:128`), so any new external symbol si.c calls needs a stub there or a setter [V].
- `window_pad` reads the keyboard only while the window is in front (`window.c:404`) and XInput slot
  0 always (`window.c:432-435`), probing an absent pad once a second [V]. LB, Back/View and the stick
  clicks are never read. Enter maps to START (`window.c:410`) [V].

### 2.4 The window and presenter (`runtime/window.c`, H8)
- A fixed `640·scale × 480·scale` client, `scale` default 2, style `WS_OVERLAPPEDWINDOW` without
  thick frame or maximize (`window.c:285-297`); not DPI-aware (no awareness call anywhere) [V].
- H8's DXGI flip-model swap chain is created once at the client size (`window.c:154-196`, `:328`),
  scaled on the CPU by whole pixels into `g_scaled` (`window.c:200-216`); there is no `ResizeBuffers`
  path. `DXGI_MWA_NO_ALT_ENTER` is already set (`window.c:180`) [V].
- **The sync interval rule** (`window.c:316-326`), chosen once at startup from DWM's refresh period:
  when `hz/30` is within 0.02 of a whole number, the interval is that number; otherwise it is 1. Either
  way it is clamped to 1–4. So 60 Hz gives 2, 120 gives 4, and 85 and 144 give 1 [V].
- Escape closes the game (`window.c:227`) [V]. GDI remains the fallback (`window.c:327-329`) [V].
- `present()` converts `g_screen` to BGRA on the UI thread (`window.c:267-280`). `SOA_HASH` is taken
  from `g_screen` in `enqueue_copy` when the screen copy is queued (`gxr.c:3086-3088`), before any of
  this [V].

### 2.5 Tick and clock (`runtime/tick.c`, `runtime/hle.c`, `runtime/dsp.c`, `runtime/irq.c`)
- The safe point is `VIGetRetraceCount` from lr `0x801DCB88`; the unlock answers the spin at lr
  `0x801DC49C` (`tick.c:84-98`). The unlock's only switch is `SOA_UNCAP=N` (`main.c:876-886`) [V].
- The guest timebase is `timespec_get(TIME_UTC)` minus the first reading, times a speed read once
  (`hle.c:290-304`). TIME_UTC is not monotonic, and the subtraction (`hle.c:302`) is unsigned: a clock
  step backwards past the first reading (an NTP correction after resume, say) wraps to about 584 years
  [V arithmetic; the step itself is I].
- `guest_timebase_lo/hi` (`hle.c:482-483`) are called from translated code; `OSGetTick`
  (`fn_8023851C`) is `s->pc = 0x8023851C; s->gpr[3] = guest_timebase_lo(s);` (gen/chunk_013.c) [V].
- **Report hooks.** At b071949 the table holds 4 and silently drops a fifth (`hle.c:164-171`). The
  three registrations are `window.c:331`, `tick.c:66` and `main.c:1183`, and mod.c's only when a mod
  loads. P6 (24d9235) grew the table to 16, and it prints a line when it is full [V].
- **Stop paths.** Every orderly exit calls `hle_report()` first (`hle.c:69-70`, `:107-108`, `:250-251`,
  `:258-259`, `main.c:493-494`, `gx.c:186-188`, `window.c:348`), except threads.c's six `exit(6)`
  (`threads.c:141`, `:217`, `:266`, `:295`, `:304`, `:311`). Those use `exit`, not `_exit`, so
  `atexit` handlers run on them [V].
- A VI retrace after a long gap is delivered once, not caught up (`irq.c:380-390`, `g_vi_last = now`);
  the AI DMA is caught up one block per poll (`dsp.c:214-231`, `g_dma_due += g_dma_period`) [V].
- Headless runs have a 20 s watchdog (`main.c:504`) [V].

### 2.6 Card and paths (`runtime/exi.c`, `runtime/main.c`, `runtime/aram.c`, `tools/cardformat.py`)
- The card is a 4 Mbit, 59-block image (`exi.c:72`, `CARD_BYTES`) at CWD-relative
  `build/cards/slotA.raw` (`exi.c:90`), mirrored in `si.c:294` [V]. The disc default is CWD-relative
  `extracted` (`main.c:1087`), and `aram.c:160-172` reads the disc directory from MSVC's `__argv`,
  ignoring `soa.ini`'s `disc` [V].
- `cardformat.py` writes, shows and verifies (`cardformat.py:1045-1087`, `:1117-1160`); it parses
  directory entries (`:475-557`) but has no import or export [V]. `--size` takes 4–128 Mbit
  (`CARD_SIZES`, `:120`; `:1089-1095`). `verify()` (`:700-826`) checks each directory and FAT block's
  checksum and free count, never which slot an update wrote. `current_slot()` (`:560-570`) picks the
  slot with the lower check code as the one written next [V]. A card image's block 0 begins with the
  12-byte scrambled flash serial (`id_block`, `:300`), not the game code [V]. The game's save is one
  file per slot, `GEAE 8P SA_LEGENDS.000`, 3 blocks, permission 0x04 (save-load.md:170;
  FINDINGS.md:1236) [V].

### 2.7 Guard (`tools/guard.py`) — T0 and T0c have landed
- 43 suffixes and 18 directory names (`load`, `dump` and `dumps` among them) after 1c7b780 and 4041dfc.
  CI's history regex copies the suffixes (`.github/workflows/ci.yml:34` at b071949, :36 at 012164a).
  CLAUDE.md:10-11, TESTING.md:155 (:156 at 012164a) and SKILL.md:72 all say 43 [V: `python -c "import
  guard"` in `tools/`, 43 at 012164a too].
- **The content check** (`signature_of`, `content_problems`) refuses a binary file anywhere in the tree
  that begins with a game-data signature (`SIGNATURES`: AKLZ, GVR, `GEAE8P` at offset 0, PNG, DDS, Ogg,
  FLAC, MP3, WAV). In a folder holding a `mod.ini`, it also refuses any file that is not UTF-8 text [V].
- 1c7b780's 64-row table limit was dropped at 4041dfc; T5 writes the enemy-table check once its schema
  exists [V commit message].
- **One gap, closed by T0c (012164a):** the signature list called `GEAE8P` at offset 0 "a card file or
  a disc header", but a card image does not begin with it (2.6), so a renamed card image got through.
  T0c knows a card image by its directory, reads 0x6000 bytes, counts every suffix in a name
  (`slotA.raw.bak` is a `.raw`), and makes `--history` read content [V, 012164a's message].

### 2.8 The renderer's copy filter and frame skip (`runtime/gxr.c`, at b071949 = c8274db for this file)
- The renderer's switches are read in `gxr_enabled` (`gxr.c:213-226`) [V].
- `enqueue_copy` (`gxr.c:2921-3091`) collapses BP 0x53/0x54 with `copy_filter` (`gxr.c:2877`), called
  at `:2938`, with `filtered` computed at `:2939`. It does this for screen and texture copies alike [V].
- SOA_SNAP's frame skip is one test in `gxr_draw_inner` (`gxr.c:2378`); copies have no such test [V].

### 2.9 Checked while writing
- **`_putenv_s` reaches a mod DLL.** The port and a `cl /LD` DLL each carry their own static CRT. A
  scratch probe (host exe calls `_putenv_s`, then `LoadLibrary`s a DLL that reads the variable) read
  it back through both `GetEnvironmentVariableA` and the DLL's own `getenv` [V, probe]. Mods load
  after settings, so a `soa.ini` line does reach a DLL mod.
- **P6's three call sites** are exactly `s->lr = 0x801012B0u; fn_8023851C(s);` (gen/chunk_005.c:114683),
  `0x8000A1D0u` and `0x8000A1D8u` (gen/chunk_000.c:13077, :13081). Each is followed at once by a call to
  srand, `fn_8025ECBC` (translated, `gen/chunk_015.c:31429`; not decompiled), and these three are its
  only callers [V].
- **P11's window**: read in the disassembly (section 3.5), then confirmed in one run (b911380, FINDINGS
  "P11's spike") [V run].
- **P1's multiplier writer** `fn_801EF7E0` is called from 22 sites in the translated code: map load
  (`lr 0x800FFD98`, gen/chunk_005.c:111208), Continue (`0x801A4538`), the menus (`0x801F026C`–`0x801F4E90`)
  and five others. None of them runs every frame [V grep of gen; the purposes of `0x8006F400`,
  `0x8006FC1C`, `0x801451D4` and `0x80175xxx` are I].

---

## 3. Design

### 3.0 Rules every slice follows

- **Setters, not calls, into files that link alone.** Several files are built alone with stubs:
  - si.c, by `test_padrec.py`;
  - mod.c, by `test_mods.py`;
  - seed.c, by `test_seed.py`;
  - the renderer, by `tools/citest/render_check.py` and the nine `tools/tests/test_gxr_*.py` modules.

  New wiring goes through setters that main.c calls (the pattern of `si_set_pad_filter` and
  `gx_set_frame_hook`), or through a new stub listed in the slice's files.
- **Settings keys.** Each new feature adds one `k_settings` line, off by default, and
  its README line (README.md:159-161 and the switch table). The `recorded` flag (P6) marks keys that
  change what the game does (3.3).
- **Mod settings until M16.** A DLL mod reads its environment variable with `GetEnvironmentVariableA`
  (verified in 2.9). Its `k_settings` line names the mod's id. After mods load, main.c says when such
  a variable is set and no mod with that id is loaded: "`encounters = half` is set, and no mod with id
  `encounter-rate` is loaded; it does nothing". P1a adds that line.
- **Report hooks.** Up to three were taken at b071949, and mod.c's only when a mod loads (2.5). P6
  (24d9235) took the fourth and grew the table to 16, printing a line rather than dropping a hook.
  M18's `[rumble]` would otherwise have been the first to vanish silently. The fix landed in P6 so
  that no later slice depends on someone remembering it.
- **Logging.** Each runtime feature has one tag (`[seed]`, `[chord]`, `[clock]`, `[rumble]`,
  `[picture]`, `[turbo]`), says once per run what it is doing, and has a line in the end-of-run report
  with its counts. A **DLL mod** logs through `api->log` as `[mod] <dir>:`. It has no report hook, so its
  per-event lines are its counts. From P1a on, mod.c's existing report line for each DLL also gives
  `W write(s)`: the successful `write*` calls made while that mod's callback ran, counted through
  `g_cur_mod`. The API does not change.
- **Replayability (rule 6 of PLAN-GAMEPLAY-MODS).** Settings that change the game go into the `#
  config` line now (3.3), not in milestone 2. What still cannot replay in milestone 1 is logged once
  per run: pad 2's input (P10), hold-to-skip (P11b), and chord toggles made mid-run (CH1, M11a).
- **Portable logic, Windows edges.** Decision logic lives in plain C that an SDL or Android front end
  can reuse: chords in si.c, and `picture.c`, `clock.c` and `seed.c`. XInput, DXGI and Win32 stay in
  window.c.
- **Prerequisites, once.** P6 (landed) and P1a come before every later slice that adds a recorded key
  (P6's `recorded` column) or a DLL mod (P1a's mod-id line and its DLL build). Each slice below names
  them again.

### 3.1 MV2 — manifest v2: landed

3949028 landed manifest v2 as the plan's section F describes it, and b071949 landed what this spec
added: one API constant, overridable for a test; the API-minimum test at `/DMOD_API=2`; and the "no
`api = `" message. mod.c's manifest comment (`mod.c:45-56`) says that a save's chunk will be keyed by
the id, and only manifest 2 has one. b1199b3 then keyed the recording line's `+N more` tail by id too
(2.1). Nothing remains here.

### 3.2 T0 — the guard: landed; T0c, card images: landed

1c7b780 and 4041dfc landed the design this section proposed: the suffixes (`.gci`, `.gcs`, `.sav`,
`.dds`, `.dat`, `.ogg`, `.flac`, `.mp3`, `.opus`), the directories (`packs`, `load`, `dump`, `dumps`,
`blobs`, `photos`, `out`) and the signature check. The counts are fixed in every copy.

**T0c, one residual, landed at 012164a.** As specified here, a binary file was to be refused as "a
memory card image holding this game's save" when both of these hold:
- its length is one of `CARD_SIZES`' byte lengths (512 KiB × 2^k, k = 0–5);
- `GEAE8P` begins a 64-byte directory entry of block 1 or block 2 (offset `0x2000 + 64·i` or
  `0x4000 + 64·i`, i < 127).

The landed check is wider [V, 012164a]: the directory test applies to a binary file of any length (a
truncated card is caught too); `GCSAVE` and `DATELGC_SAVE` (GCS and SAV card saves) and an untagged
MP3's frame header join the signatures; every suffix in a name counts; and `--history` sends every blob
through the content check. The `SIGNATURES` comment for `GEAE8P` now says ".gci or disc header".

### 3.3 P6 — the race seed, and recorded settings (landed: P6 at 24d9235, P6b at 79c9ad8)

**The pin** (as landed). `runtime/seed.c` exports `seed_pin(lr, tb)`, `seed_value(seed,
site, n)`, `seed_set(on, seed)`, `seed_init(in_effect, cap)` (P6b's signature: it hands back the seed
it pinned) and `seed_report()`. `hle.c`'s `guest_timebase_lo` asks
`seed_pin` only when `s->pc == 0x8023851C` (OSGetTick):

```c
uint32_t guest_timebase_lo(CpuState* s)
{
    uint32_t v = (uint32_t)timebase();
    return g_seed_on && s->pc == 0x8023851Cu ? seed_pin(s->lr, v) : v;   /* OSGetTick only */
}
```

- `seed_pin(lr, tb)` returns `tb` unless `lr` is one of the three sites: 0 = `0x801012B0` (field
  load), 1 = `0x8000A1D0` and 2 = `0x8000A1D8` (battle start). At a site it returns `seed_value(seed,
  site, n) = fmix32(seed ^ (site + 1)·0x9E3779B9 ^ n·0x85EBCA6B)`, where `n` counts that site's calls so
  far and `fmix32` is MurmurHash3's finaliser. It counts the pinned reseeds per site and the unpinned
  `OSGetTick` reads.
- The pin cannot leak to a later read: each site is followed at once by `s->lr = …; fn_8025ECBC(s)`,
  which changes lr before any other timebase read (2.9) [V].
- `SOA_SEED=<decimal, or 0x and up to 8 hex digits>`; `seed` in `k_settings`, recorded. A malformed
  value is refused with a line, and the reseeds stay the game's own.
- Report, as `battle.scn` run to frame 13,500 gave it at 79c9ad8: `[seed] SOA_SEED=12345: field load 4,
  battle start 1 and 1 pinned; 214554 other OSGetTick reads left alone` [V run, FINDINGS "P6, followed
  up"].
- **P6b added** one line per pin, `[seed] pin: site S (lr 801012B0) n N -> 0xVVVVVVVV`. There is no
  frame number in it, so seed.c still links alone. Pins happen only at loads and battle starts, a few a
  minute at most. This line is what the live Done checks, because the report gives only counts.
- No `hle.txt` line and no `cpu.h` change: a `--link`.

**Recorded settings (pulled forward from milestone 2's event track).** Landed with P6: `k_settings`
gains a `recorded` flag, set on `seed` now and on P1's, P10's, P11's and M11a's keys as
they land. `settings_recorded(char*, size_t)` returns `key=value` for each recorded key whose variable is
set. main.c joins it with `mod_describe()` and passes the result through `si_set_config_extra` for every
run, not only runs with mods. A recording made with none of them set keeps exactly the line it has
today. The replay's existing mismatch warning (`si.c:572-577`) then names a different seed or preset.
The strict switch that refuses a mismatch stays in milestone 2.

**Room for it (P6b, landed).** Settings come first, so a long mod list cannot push them out.
- main.c's `extra` and si.c's `g_cfg_extra` grow from 320 to 640 bytes.
- The `cfg`, `was` and `now` buffers (`si.c:333`, `:502`) grow from 768 to 1024.
- `settings_recorded` and `si_set_config_extra` each print `[pad] the config line was cut at N bytes`
  when a value does not fit, instead of dropping it silently.
- `mod_describe` keeps its 300 bytes and its own `+N more` rule.

### 3.4 P1 — encounter slider and hold-B (`mods/encounter-rate`)

A DLL mod, `mods/encounter-rate/mod.c`, with a v2 `mod.ini` (id `encounter-rate`). It must be a DLL:
the byte is not word-aligned, and `patches.txt` writes whole aligned words (`mod.c:309`).

- **The game's multiplier** is the s8 at `0x8030B7AD`, read at `0x800C2000` (`lbz`, `extsb`, compared
  with −1 at `0x800C2014`, skipped at `0x800C2040`). −1 (0xFF) skips the multiplier, i.e. the normal
  rate. Otherwise the odds are multiplied by byte/50: 0–127 is 0–254%, and 128–254 are negative and turn
  encounters off [V static]. On `card-saved` at its a101b spot the byte reads `FF` [V run,
  `build/p1-addr.log`, on a byte-identical copy of `card-saved`]. The byte lies below the saved party
  block (`0x8030B7F4`), so nothing the mod writes reaches a save [V per X2's block list].
- **Working out base, as the game does.** Base is 50 for "none". Otherwise it is the effect-84 value of
  the last of characters 0–5 whose accessory has one [V per the plan; the addresses below were read in
  one run, `build/p1-addr.log`]:
  - the accessory is the u16 at `0x8030B7F4 + 92·c + 20` [V run: on `card-saved`, character 0's
    reads 204 and character 1's 201, the rest 0];
  - ids 160–239 index 40-byte records at `0x802C6E10 + (id−160)·40`;
  - each record holds four `{u8 code, u8, s16 value}` at +24 [V run: accessory 210's first is
    `54 00 0064`, code 84 and value 100; 211's is `54 00 0005`, code 84 and value 5].

  On this disc only 210 (100) and 211 (5) have code 84, so `card-saved`'s party (204, 201) gives base
  50, "none". The mod repeats the scan every frame and **never rereads the multiplier byte**, which
  holds the mod's own last write. If the computed effect-84 value is negative (none on this disc has
  one), it writes nothing.
- **Presets** from `SOA_ENCOUNTERS` (`off`, `half`, `normal`, `double`; unset is normal). Integer
  arithmetic only:
  - `half` writes `base / 2`, truncating: 50 → 25, 100 → 50, 5 → 2;
  - `double` writes `min(base · 2, 127)`: 50 → 100, 100 → 127;
  - `off` writes 0;
  - `normal` **writes nothing**, except for the restore below.

  The writes come from `on_frame_end` while `scene() == 6` (field and world map). The plan had `normal`
  write base×1; writing nothing makes "identical to off" true by construction.
- **Hold B:** a `pad_filter` notes B held in scene 6, and while it is held the frame end writes 0. The
  mod sets a `dirty` flag whenever it writes the byte. When the frame end runs with B released, the
  preset `normal` and `dirty` set, it writes the game's own value once and clears `dirty`. The game's
  value is 0xFF when no character's accessory has code 84, else that effect value. Without this, one
  tap of B at `normal` would leave encounters off until the next map load or equipment change. Hold-B
  is on by default; `SOA_ENCOUNTERS_HOLD_B=0` turns it off.
- **Logging:** once, the preset and hold-B state. Each time base changes: `[mod] encounter-rate: base B
  (character c's accessory id, or none)`. mod.c's report line gives the write count (3.0).
- **Settings:** `encounters` and `encounters_hold_b` in `k_settings`, both recorded, both naming mod
  id `encounter-rate` (3.0).
- **The DLL is built by `--link`.** `tools/recompile.py --link` also compiles each `mods/*/mod.c` (and
  `examples/mods/*/mod.c`) with `cl /LD /O2 /I runtime <src> /Fe:<folder>\mod.dll`, and names each one
  it built (with the msvc profile only: a clang-cl or gnu build does not build the mods, portability.md
  3.9 and L3a). A folder whose source fails to compile fails the link step.
- **Move `mods/encounters-off` to `examples/mods/encounters-off`** in this slice, so that `mods = …\mods`
  in `soa.ini` does not turn encounters off for good beside the slider. The copies to fix, found with
  `grep -rn "encounters-off" --include=*.py --include=*.md --include=*.c .` (at 012164a):
  - `tools/tests/test_mods.py:405`, `:412` and `:968` (the first two build the path from parts);
  - `HANDOFF.md:47` and `:395`;
  - `README.md:202`;
  - the header comment at `runtime/mod.c:7-15`.

  PLAN-60FPS-MODS.md:454 and FINDINGS "M1" and "Manifest 2" are history and keep the old path.
  `test_mods.py:219` and `:222` build a synthetic folder of that name and do not change.
- **Test mode** (`SOA_ENCOUNTERS_TEST=1`, P1b's Done only):
  - **Trials** cycle through five kinds: k = ½, 1, 2, 0, and `hold`, which is k = 1 with B ORed into the
    pad by the test mode before its own hold check.
  - **A trial starts** by writing 480 to the step counter `0x80346D28`.
  - **It ends** at a battle (scene 6 → 7), at 600 moving frames (the counter's own increments), or as
    `stuck` after 3000 frames of wall time with fewer than 600 moving frames.
  - **The counter does not count everywhere.** At `card-saved`'s a101b spot, zone 0, it stayed 0 over
    1,700 frames of scripted walking, although the frames show Vyse walking [V run, the implementation
    session's Q-I5 run]. So the trials need a card and a walk in a rate-20 zone where it counts (Q-I5).
  - **Each trial logs** `trial n kind zone0 rate0 zone1 rate1 moved battle|clear|stuck`. The zone is the
    u16 at `0x8034740E`, and its rate is the u16 at `[0x803474BC] + 2 + (zone−1)·132` (encounters.md:61-66)
    [V per research]. Both are read at the trial's start and at its end.
  - **In battle it flees.** It writes 100 to the party escape override `0x8030B7AB` every frame. In
    phase 1 it turns the wheel to Run (three `right#4`, then A) through `pad_filter`, so a trial costs
    seconds, not a minute of fighting. The wheel position and the override are [I] until Q-I5's first run.
- **`tools/encounter_check.py LOG`** reads the trial lines and applies P1b's rules. Its pytest feeds it
  synthetic logs.

### 3.5 P11 — dialogue auto-advance (`mods/autotext`), and what the plan got wrong

**The plan's address is the wrong one.** P11 says to find the message window "through
`0x80346E60`". That word is the draw's per-frame pointer: the window task stores it at the end of each
of its runs (`0x8010D434`, `0x8010D260`, `0x8010D65C`, …) and the draw `fn_8010CC74` reads it and
**stores 0 back** at `0x8010CCD4` [V static]. The safe point, the frame end and the SOA_PEEK hook all
run after the draw, and the pad filter runs at an interrupt, so a mod reading `0x80346E60` sees 0, or a
value from partway through a frame.

**What to read instead** [V static, and confirmed in one run: b911380, FINDINGS "P11's spike"]:

| Word | Holds | Evidence |
|---|---|---|
| `0x80346E4C` (u32) | The window task, stored once per field map load; 0 for two frames of a warp | `0x80101288 bl fn_8010CEF8; 0x8010128C stw r3,-30932(r13)`; the spike |
| task + 36 (u32) | The 184-byte window context | `fn_8010CEF8`: `li r3,184; bl` alloc; `0x8010CF3C stw r30,36(r31)`; the task body loads it at `0x8010D518` |
| `0x80346E64` (s16) | The window's state, rewritten at the end of every run of the task, and not cleared by the draw | `0x8010D898 lbz r0,25(r30); 0x8010D89C sth r0,-30908(r13)`; the spike |
| context + 0 (u16) | The window's flags | read throughout `fn_8010D12C`, `fn_8010D280` |

The state machine (`fn_8010D4F4`, dispatch at `0x8010D514`–`0x8010D570`) [V static]:
- **0** and **254** initialise (`fn_8010D458`, `0x8010D574`).
- **1** waits for a message command.
- **2** opens, going to 3, or to **6 instead of 3 when context flag 0x10 is set**
  (`0x8010D62C`–`0x8010D640`). Flag 0x10 is the choice marker the plan's spike was to find.
- **3** reveals text (`fn_8010D280`).
- **4**: the page is complete and waits (`fn_8010D12C`). On A, or when a countdown ends, it goes to
  **7** if flag 0x80 is set, **5** if flag 0x200 is set, else **8** (`0x8010D190`–`0x8010D1B0`,
  `0x8010D1F4`–`0x8010D214`). With flag 0x10 (after a choice) the countdown at context+26 does this by
  itself. With flag 0x40 (auto-scroll) the countdown goes to 5 (`0x8010D238`–`0x8010D25C`). Otherwise
  state 4 waits for A: the 0x100 bit at +8 of the field's pad record `*(0x80311A60 + 4·ctrl)`
  (`0x8010D1C0`–`0x8010D1DC`).
- **5** scrolls to the next page (then 3).
- **6** is a choice box (`fn_8010CF78`).
- **7** closes (then 1).
- **8** waits after the last page and stores 8 back until the script moves on (`0x8010D7EC`–`0x8010D81C`).
- Any other value tears down: the context is freed and task+36 is set to 0 (`0x8010D824`–`0x8010D888`).
  The spike saw 255 for two frames of a warp.

Other flags and fields:
- Flag **0x1000** only stops A and B from revealing the page at once (`0x8010D2F4`–`0x8010D324`); A still
  advances a complete page. The plan's "respect flag 0x1000" is satisfied by pressing only in state 4.
- Context +54 is the page's character count and +56 how many are shown (`0x8010D328`–`0x8010D334`), as
  the plan says. State 4 is the better test, because it also covers the game's own end-of-page handling.
- Not used: story flag 1086 (bit `0x40000000` of `0x80310BC0`) also makes state 4 advance with no A
  (`0x8010D1E0`–`0x8010D1F0`) and changes how the window is drawn (`0x8010CCF0`). It looks like the
  attract demo's own auto-advance [I]. It is a saved story flag, so a mod must not set it.

**What the spike showed** (b911380): after a warp to `ME355A.SCT` with no A, the state rested at 4 for
2,913 frames (3087–5999), on the officer's page 《どうせみないでしょ？》. The A at 6000 moved it through
5 and 3, and the choice that followed (「みる」「みない」) rested at 6 from 6007 to the end at 6600 [V run,
FINDINGS "P11's spike"]. HANDOFF (lines 311-321) and FINDINGS "The developers' part select" describe
the next step. Choosing みる leads to 《どうする？》, shown first as a message box waiting for A, then to
the B/C/next choice (「Bパートへ」「Cパートへ」 and "next"), where the first choice runs the part
routines and warps to part B's `/field/a002b.mld` [V, earlier runs].

**The mod.** `mods/autotext/mod.c`, v2 `mod.ini`, id `autotext`. One `pad_filter`:
- Only while `scene() == 6`. Read the state; read the context through `0x80346E4C` → +36 with the
  API's checked reads (a zero or out-of-range pointer means "no window").
- **The delay.** `SOA_AUTOTEXT` unset or `0` is off; `on` or `1` means 45 frames (1.5 s); a number of 2
  or more is that many frames. README and `k_settings`' text say the same.
- When the state is 4 and `(flags & 0x50) == 0`, start a wait. After the delay, press A: set
  `SOA_PAD_A` on every read of two frames, then clear it on every read of the next two. Press once per
  page, re-arming only after the state has left 4.
- Never in state 6, or in any state but 4. Never when the person is already pressing A or B (the
  person wins).
- Test mode `SOA_AUTOTEXT_TEST=press-in-choice` also presses in state 6: the mutation for the Done.
- Log one line per press, `[mod] autotext: frame F page advanced after W frames`; these lines are its
  counts (3.0). `autotext` in `k_settings`, recorded, mod id `autotext`.

**Hold-to-skip is P11b**, after CH1. While host button LB is held (`api->host_buttons()`), it presses A
in states 3 and 4 on the same two-on, two-off cadence, never in 6 and never when `(flags & 0x50) != 0`.
Each press is logged with its state (`[mod] autotext: frame F skip press in state 3`). The first time it
is used, it logs once that host buttons are not in the recording yet.

### 3.6 CH1 — gamepad chords and host buttons

- **Host buttons** are the pad's buttons the game never sees: LB, View (Back), LS and RS (the stick
  clicks). The keyboard's **Tab** counts as LB. They never reach the game.
- **Where the bits live.**
  - **The window.** `window.c` exports a new `int window_host(uint16_t* host)`, which returns 1 when
    read and ORs `SOA_HOST_LB 1`, `SOA_HOST_VIEW 2`, `SOA_HOST_LS 4` and `SOA_HOST_RS 8` into `*host`.
    `window_pad`'s signature and its stub (`test_padrec.py:67`) do not change; `test_padrec.py` gains a
    `window_host` stub.
  - **The script.** `PadEvent` (`si.c:79`) gains `uint8_t host`, and the parser maps `lb`, `view`, `ls`
    and `rs` into it, never into `buttons`.
  - **The merge.** si.c keeps `g_host = window_host() | the script's host bits`, updated on the first
    pad read of each frame; si.c already knows the frame from `gx_frame_count`. It does this whether or
    not a recording latches, so repeated reads in one frame cannot fire a chord twice. During a
    `SOA_PAD_FILE` replay the host bits are 0, because the replay is the whole input. `si_host_buttons()`
    exports `g_host`.
- **Port 1 follows the pad.** `window.c` uses the first connected XInput slot, found by probing all
  four once a second while none is connected, and keeps it until it disconnects (the M8 amendment).
- **Chords are detected in si.c** on `g_host`, so they work and are tested headless. A chord fires on
  the frame its last button is pressed:
  - **View+LB**: fullscreen on/off (H19a).
  - **View+RS**: turbo on/off (M11a), applied at the next safe point.
  - **View+LS**: reserved for M8's menu.
  - LB held alone is not a chord; mods read it (P11b).
- **Actions reach their owners through one setter,** `si_set_chord_handler(fn)`. main.c's handler is a
  switch with one arm per chord, so CH1 does not depend on the slices that come after it. In CH1 the
  fullscreen and turbo arms only log, `[chord] frame F: view+lb -> fullscreen (not built yet)` and
  `... view+rs -> turbo (not built yet)`. H19a replaces the fullscreen arm and M11a the turbo arm.
- **The script grammar gains `lb`, `view`, `ls`, `rs`** in si.c and in scenario.py
  (`tools/scenario.py:132`, `:233`), because the pad grammar lives in both (CLAUDE.md).
- **Recording.** Each chord writes `# chord F view+lb fullscreen` into the recording (a comment the
  replay ignores) and a `[chord]` line to the log. Replaying chord actions is the event track's
  (milestone 2).
- **API.** `uint32_t (*host_buttons)(void)`, appended to `SoaModApi`, returns the `SOA_HOST_*` bits as
  of the current controller read. mod.c gets it from a setter (`mod_set_host_buttons`), so
  `test_mods.py`'s driver can stub it.
- The chord map is a proposal (Q-O5); the keyboard keeps F11 for fullscreen (H19a).

### 3.7 M18 — rumble

- The game drives the motor with `PADControlMotor`, which writes `0x00400300 | cmd` to `SICnOUTBUF`
  (cmd 0 stop, 1 rumble, 2 stop hard) [I, the SDK's layout; the port stores the word, `si.c:869`].
- **si.c** acts on a channel-0 OUTBUF write whose bits 0–1 changed: `speed = bits == 1 ? strength :
  0`, passed to a sink set by `si_set_motor_sink(fn)`. A gate forces the speed to 0 unless all three
  hold: a window is open (`si_set_motor_window`), no `SOA_PAD` script or `SOA_PAD_FILE` replay drives
  input, and strength > 0. Channels 1–3 never call the sink.
- **window.c** implements the sink with `XInputSetState(slot, {s, s})` on port 1's slot. It calls
  `si_motor_stop()` (a zero-speed call if the motor is on) on:
  - focus loss (`WM_ACTIVATEAPP`);
  - pause (M19);
  - close, before `_exit` (`window.c:345-354`);
  - a report hook, which covers every path through `hle_report`;
  - an `atexit` handler, which covers threads.c's six `exit(6)`. They skip `hle_report` but use `exit`
    (2.5).
- `rumble = 0..100` (`SOA_RUMBLE`), default 100 (Q-O2); not recorded (it changes nothing in the game).
- A crash (`_exit` from a fault path, or a killed process) with the motor on is the one case left. The
  pad may keep buzzing until XInput's own timeout or until the pad is unplugged [I].

### 3.8 H19a — fullscreen and a window that fits (reconciled with H8)

All in window.c, on the UI thread that already owns the window and presents.
- **DPI:** `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` through `GetProcAddress` (Windows
  10 1703+; fallback `SetProcessDPIAware`), before `RegisterClassA` (`window.c:294`). Handle
  `WM_DPICHANGED` with the suggested rectangle. Border sizes from `AdjustWindowRectExForDpi`.
- **Default size:** the largest whole multiple of 640×480 whose window fits the monitor's work area;
  `SOA_SCALE`/`scale` still wins. At 150% on a 1080p handheld today's 1280×960 client is 1920×1440
  physical pixels, taller than the screen [V arithmetic].
- **Resizable:** full `WS_OVERLAPPEDWINDOW`. `WM_SIZE` sets a flag; the UI loop then calls
  `IDXGISwapChain1_ResizeBuffers` (no back-buffer reference is held between presents, `window.c:211-213`),
  reallocates `g_scaled`, and presents the last frame again. Minimised (0×0): no resize, no present.
- **Letterbox:** `picture_layout(src_w, src_h, dst_w, dst_h, mode)` in `runtime/picture.c` (pure; P5a
  shares the file) returns the image rectangle. Mode `integer` (largest whole multiple, the default)
  or `fit` (largest 4:3 that fits, nearest neighbour, uneven pixels). The bars are black. GDI uses the
  same rectangle in `StretchDIBits` and fills the bars.
- **The sync interval moves into `picture.c`** as `present_interval(double hz, int fps)`, today's rule
  unchanged: `hz/fps` within 0.02 of a whole number gives that number, else 1, clamped to 1–4 (2.4).
  window.c calls it with fps = 30 at startup and on `WM_DISPLAYCHANGE`, and logs the new interval.
- **Borderless fullscreen:** F11, Alt+Enter (`WM_SYSKEYDOWN` with `VK_RETURN`) or the View+LB chord.
  Save the placement, switch to `WS_POPUP` covering the monitor (`GetMonitorInfo`), and restore on the
  way back. H8 already stops DXGI's own Alt+Enter (`window.c:180`); keep that. The chord's arm in
  main.c (3.6) now posts to the UI thread. With no window it logs `(no window: logged only)`.
- **Alt+Enter must not press START.** Today Enter is START whenever the window is in front
  (`window.c:410`); with Alt held, `window_pad` drops Enter's START.
- **Escape in fullscreen leaves fullscreen** instead of closing the game (Q-O3); in a window it still
  closes, as README documents.
- **Cursor:** hidden in fullscreen, and after two seconds without mouse movement in a window
  (`WM_SETCURSOR`).
- **Keys:** `fullscreen = 0|1`, `scaler = integer|fit` (P5a adds `sharp`); not recorded.
- **Test knob:** `SOA_WINDOW_TEST=fs@300,win@600,size:1000x700@900`, driven from the UI loop by
  `gxr_presented()`, logging `[window] frame F: client WxH, image WxH at +X+Y, monitor WxH, mode M`.
- Not here: H9's VI lock, VRR, 144 Hz rows, M10's aspect.

### 3.9 M5b — a first run without a terminal

- **The port root.** The exe's folder, or the parent of the nearest ancestor folder named `gen` whose
  parent holds `runtime\` (so `gen\clang\` and `gen/linux/` builds, portability.md 3.9, find the same
  root). That is the repository layout every player also has, since builds are local. `SOA_ROOT`
  overrides it, for tests.
- **Which `soa.ini`.** `<root>\soa.ini` first, then `<exe folder>\soa.ini` (today's). When both
  exist, the first is used and the log says which. `SOA_SETTINGS=<path>` names a file (tests);
  `SOA_SETTINGS=0` stays "off". `/soa.ini` joins `.gitignore`: it holds personal absolute paths.
- **Relative paths in `soa.ini`** (`disc`, `mods`, `card`, `record`, and later keys that take paths)
  resolve against the root, not the current directory, and not `gen\` (Q-O1 explains the choice).
  Environment variables keep today's CWD-relative meaning, so no script or check changes.
- **Defaults, when a `soa.ini` was loaded** and does not set them:
  - the card is `<root>\build\cards\slotA.raw`;
  - the disc is `<root>\extracted`;
  - `mods` is `<root>\mods`, when any mod-backed key (`encounters`, `autotext`, `coop`) is set.

  settings.c puts the card into `SOA_CARD`, so exi.c and si.c agree without code in either, and returns
  the disc. With no `soa.ini` nothing changes: every check runs without one.
- **The recording names the card relative to the root** when it lies under it: `si_set_path_root(root)`
  is a setter, and `pad_config` strips the prefix. A recording made from a double-click and a replay run
  by scenario.py (CWD = root, the relative default) then agree, and no personal absolute path enters
  a `.pad` file.
- **aram.c** takes the disc directory from main.c (`aram_set_data_dir`) instead of `__argv`
  (`aram.c:160-172`), which also makes it honour `soa.ini`'s `disc`.
- **Rendered by default** when a `soa.ini` was loaded: `render = 1` unless the file or the environment
  says otherwise.
- **Hide the console, keep the log.** Only when both of these hold:
  - the process owns its console (`GetConsoleProcessList` returns 1: started from Explorer or a front
    end, not a terminal);
  - stderr is that console (`GetFileType(GetStdHandle(STD_ERROR_HANDLE)) == FILE_TYPE_CHAR`).

  Then it reopens stderr and stdout to `<root>\build\logs\soa-YYYYMMDD-HHMMSS.log` and makes them
  unbuffered again (`setvbuf(..., _IONBF, 0)`: every stop path leaves through `_exit`). Then it calls
  `FreeConsole()`, and the first log line names the file. The second condition matters: a tool that
  reads the port through a pipe (scenario.py's `stream_run`, `tools/scenario.py:741-747`), started from
  a parent with no console, gives the port a console of its own, where the first condition alone would
  send the report to a file. The decision is a pure function, `should_hide_console(procs, stderr_type)`,
  in settings.c.
- **When the window loses focus:** `unfocused = run|mute` (default `run`, today's behaviour,
  `window.c:389-394`). `mute` ignores the gamepad and silences audio while another window is in front:
  `audio_set_muted` zeroes the samples in `audio_push_block`. M19 adds `pause`.

### 3.10 M19 — a clock that survives sleep and speed changes

- **`runtime/clock.c`,** pure logic plus a host source: `QueryPerformanceCounter` on Windows,
  `clock_gettime(CLOCK_MONOTONIC)` elsewhere (the L-track reuses it). `hle.c`'s `timebase()` becomes
  `clock_guest_ticks()`.
- **The model:** guest time accumulates `speed × Δhost` for each read. A Δ above the gap threshold
  (`SOA_CLOCK_GAP_MS`, default 250; 0 turns the rule off) counts as 0 and bumps an **epoch** counter,
  with a log line `[clock] frame F: a gap of 30.2 s wall counted as 0 s of guest time`. Guest time is
  monotonic by construction.
- **The origin is logged:** at the first read, `[clock] origin at W.WWW s of wall time since start`, so
  a check can compare guest and wall seconds exactly.
- **Speed changes** (`clock_set_speed(n)`, for M11b and P4) re-anchor with no jump and bump the
  epoch. `SOA_SPEED` still sets the start.
- **Pause** (`clock_pause(1/0)`): tick.c's safe point (`tick.c:88-91`) blocks while paused;
  paused time is excluded; resume bumps the epoch. Callers: `WM_POWERBROADCAST` suspend and resume
  (window.c), `unfocused = pause` (M5b's key), M18 stops the motor on pause.
- **Audio after an epoch change:** dsp.c resynchronises `g_dma_due = now + period` instead of
  catching up block by block (`dsp.c:218`). Only on an epoch change, so `speed.scn` at `SOA_SPEED=10`,
  where the DMA legitimately runs behind, keeps today's block count.
- **Reports:** `[run]` says how many seconds were excluded and how many gaps there were; the report path
  reads the clock without advancing it (the report may run on the UI thread).
- **Test knob:** `SOA_STALL=<frame>:<seconds>` sleeps the guest thread once, in the frame hook.
- **Legacy switch for one release:** `SOA_CLOCK=utc` restores the `timespec_get` source, for
  bisecting a timing report.
- Why the gap rule is needed at all: handhelds use Modern Standby, where the system counts as "on"
  and even `QueryUnbiasedInterruptTime` keeps advancing [I]; and TIME_UTC also steps with NTP (2.5).

### 3.11 P3 — `.gci` import and export (`tools/cardformat.py`)

- **The format:** a 0x40-byte directory entry, as on the card, then `blocks × 8192` bytes; Dolphin
  checks the file size against the entry's block count at 0x38 [V, Dolphin `GCIFile.cpp`,
  `GCMemcard.h`; the offsets match `cardformat.py:475-557`].
- **`export CARD (--index N | --name NAME) OUT.gci`:** the entry from the current directory, then the
  blocks along its chain in the current FAT. The default file name follows Dolphin's GCI-folder
  naming [I; check against Dolphin's `DEntry::GCI_FileName` before shipping].
- **`import CARD IN.gci --out NEW.raw` (default) or `--in-place`:**
  - It refuses any of these:
    - a game or maker other than `GEAE`/`8P`;
    - a size that is not `0x40 + 8192·n`, or that disagrees with the entry;
    - 0 blocks;
    - not enough free blocks;
    - no free entry of 127;
    - a name already on the card (`--replace` deletes the old file first);
    - an image that does not verify before the import.
  - Blocks are allocated from the FAT's last-allocated + 1, as `__CARDAllocBlock` does [I]. It writes
    the chain, the free count and last-allocated.
  - It writes the new directory and FAT into **the slot `current_slot()` picks**, the one with the lower
    check code, with check code = the other slot's + 1 (s16 wrap), recomputing checksums. The other,
    newer slot is left byte for byte as it was. This is how the card library itself alternates them
    (`cardformat.py:560-570`), and it keeps the previous state as the backup copy. `verify()` cannot
    see a wrong choice (2.6), so the Done checks the slots directly.
  - It keeps the entry's own fields (time, permission, copy count), setting only the start block.
  - It re-verifies what it wrote and exits 1 unless the mount would say READY.
- `--in-place` first copies the card to `<card>.bak-YYYYMMDD-HHMMSS` and refuses while a `soa.exe`
  is running (`tasklist`): exi.c keeps the card open and writes through (`exi.c:171-195`), so a
  concurrent import could be overwritten half-way.
- **Deferred to M7a:** the plan's export warning for saves made off an op-138 map. Nothing in the port
  can make such a save until M7a's save-now exists.

### 3.12 P10 — couch co-op

**P10a, pad 2 in the runtime** (a change from the plan, which had the mod read XInput itself; section
4 says why):
- `window.c` reads port 2 from the next connected XInput slot after port 1's, with the same
  once-a-second probe; in checks, `SOA_PAD2` is a script in `SOA_PAD`'s grammar (si.c's parser,
  refactored from globals into a struct so both scripts use it).
- **The game keeps seeing one controller:** `g_present` stays `{1,0,0,0}` (`si.c:74`). Pad 2 is read
  for mods only and never answers an SI transfer.
- `int (*read_pad)(uint32_t port, SoaPad* out)`, appended to `SoaModApi`: port 2 only in milestone 1;
  1 when something is connected, 0 otherwise; meaningful inside `pad_filter`. Wired through setters
  (`si_set_pad2_source`, `mod_set_pad_reader`).
- Pad 2 is not recorded yet; recording it is the event track's (milestone 2), and it is now one si.c
  change because si.c reads it.

**P10b, the mod** (`mods/coop`, v2, id `coop`), one `pad_filter`:
- `SOA_COOP=<party slots>` (e.g. `1` or `1,3`); `coop` in `k_settings`, recorded.
- In scene 7 with the phase word `0x8034733C == 1`, if the member index `0x80347330` is in the set,
  port 1 gets pad 2's state in place of the person's (battle-system.md:186) [V per research].
- **Handover:** when the owner of the turn changes, pass neutral until the incoming pad has no
  button down, so a thumb resting on A cannot confirm the next member's command.
- Pad 2 absent: port 1 plays everyone, logged once.
- **Logging:**
  - each handover, and each forwarded pad-2 press;
  - at the phase 1 → 2 edge, each member's command type: the **s32 word** at `0x80309174 + 32·m`, +0
    (0 Attack … 3, 6 Run: battle-system.md:107). The word is stored by `stwx r31,r3,r0` at
    `0x8007C7E0`, with the member index from `0x80347330` shifted by 5 at `0x8007C7DC` [V static]. An
    `SOA_PEEK` of that address reads it whole;
  - once per run, that the session cannot be replayed yet.
- **The one-hour spike first** (before any mod code):
  - going back with B (the member index drops, a handover);
  - members who cannot act (`+28 & 0x6D00`, skipped by the game);
  - ambush rounds (no phase 1);
  - two readings the live Done rests on, peeked at a phase-1→2 edge after one known wheel input: the
    command-type word's value for Attack and after one left, and the wheel's opening slot and whether
    it wraps. Both are [I] until then.

### 3.13 P5 — picture options

**P5a, `runtime/picture.c`** (pure C, no Windows), called from window.c's `present()`:
- Native-resolution filters on the 640×480 image, before the scaler: gamma (a 256-entry table per
  channel), colour-blind correction or simulation, and a flash limiter.
  - **The flash limiter** takes the per-frame relative luminance of the frame. When a transition would
    make a fourth flash in one second, by the WCAG/Xbox-118 definition over ≥ 25% of the image, it
    blends toward the previous frame until it would not.
  - **The colour-blind model** is fixed so the tests have fixed values. Simulation uses Machado,
    Oliveira and Fernandes (2009) at severity 1.0, applied in linear RGB: decode sRGB, multiply, encode.
    Machado's page does not state the space; linear is [I] from the model's derivation. The matrices,
    rows multiplying (R, G, B), from the authors' page (Table 1, severity 1.0):
    - protan: `[0.152286, 1.052583, −0.204868; 0.114503, 0.786281, 0.099216; −0.003882, −0.048116,
      1.051998]`;
    - deutan: `[0.367322, 0.860646, −0.227968; 0.280085, 0.672501, 0.047413; −0.011820, 0.042940,
      0.968881]`;
    - tritan: `[1.255528, −0.076749, −0.178779; −0.078411, 0.930809, 0.147602; 0.004733, 0.691367,
      0.303900]`.

    Each row sums to 1, so grey maps to grey. Correction is the daltonize error redistribution
    (Fidaner, Lin and Ozguven, as in the daltonize.org code):
    - `err = rgb − simulate(rgb)`;
    - `rgb' = rgb + [0, 0, 0; 0.7, 1, 0; 0.7, 0, 1]·err`;
    - clamp to 0–1.
- Output-resolution modes in the scaler: `sharp` (whole-pixel prescale, then bilinear to the fit
  rectangle) and `crt` (scanline darkening at output resolution).
- Keys: `gamma`, `colorblind = off|protan|deutan|tritan`, `colorblind_mode = correct|simulate`,
  `flash_limit`, `crt`, and `scaler` gains `sharp`. None recorded.
- `--replay <base>` with any picture key set also writes `<base>.picture.png` (never `<base>.png`),
  sized by `SOA_PICTURE_SIZE=WxH` (default 1920×1080), so every filter can be opened without a window.
- The present path times itself; `[present]` reports p99 and max ms.

**P5b, deflicker off for the display copy** (`gxr.c`; the implementation session holds gxr.c):
- `SOA_DEFLICKER=0` (`deflicker = 0`), read with the renderer's other switches in `gxr_enabled`
  (`gxr.c:213-226`).
- In `enqueue_copy`, when `to_screen`, the kernel `copy_filter` collapsed becomes the identity
  (0/64/0) before `filtered` is computed (`gxr.c:2938-2939`, the `copy_filter` call and the line after
  it). The screen copy then takes the unfiltered path, and its fences follow from that. Texture copies
  keep the game's weights.

### 3.14 M11a — turbo up to 2×, absorbing P2

- `SOA_TURBO=battle|sky|both` (`turbo`, recorded).
  - **battle** is scene 7, and scene 6 on a map ≥ 500 (ship battles).
  - **sky** is the sky-mode word `0x80347464 == 1`: the world map and the ship-piloted maps 122a,
    125a/b/d and 127a/b (ship-worldmap.md:157) [V per research].
- tick.c evaluates it at the safe point and keeps the answer for the frame (the plan's "switch only at
  the safe point"). The spin (`tick.c:92`) is let go when either `SOA_UNCAP` or the turbo answer says
  so. `tick_turbo_now()` exports the answer. M11a replaces CH1's turbo arm (3.6) with
  `tick_turbo_toggle()`, applied at the next safe point, which logs `[turbo] frame F: on` / `off`.
- **The presenter follows it, without changing the normal case.** At 2× the game makes up to 60 images
  a second, and H8's sync interval of 2 at 60 Hz would show only 30 of them. window.c calls
  `present_interval(hz, tick_turbo_now() ? 60 : 30)` (3.8), keeping today's rule in both cases, and
  logs each change.

  | Display | normal | turbo |
  |---|---|---|
  | 60 Hz | 2 | 1 |
  | 85 Hz | 1 | 1 |
  | 120 Hz | 4 | 2 |
  | 144 Hz | 1 | 1 |

  The plain `round(hz/60)` and `round(hz/30)` rule would be wrong on the owner's 85 Hz display
  (FINDINGS.md:2126): 3 in normal play, 28.3 presents a second, where today it is 1.
- **Draw every frame, first.** M11's plan reused SOA_SNAP's skip (`gxr_draw_inner`, `gxr.c:2378`), but
  copies have no such test. A copy on a skipped frame would copy an EFB that nothing was drawn into
  (PLAN-GAMEPLAY-MODS section F). The first step measures whether battles need a skip at all at HEAD
  (below). A skip, if needed, is its own gxr.c slice (M11a-skip):
  - on a skipped frame, skip the draws, the texture copies, the screen copy and its clear;
  - keep the register and texture state;
  - log any later draw that samples an address a skipped copy would have written.
- **H13.** The guest ran a battle at 104 images a second before H13's first steps (FINDINGS "H3"), and
  the Dangral base went from 114 to 125 with them (PLAN-60FPS-MODS.md:301). The sky's guest ceiling has
  never been measured; M11a's first step measures it. H13 reopens only if either is under 60.
- **M11b** (not milestone 1): turbo past 2× in battles, audio muted, frame skip, after M19's
  `clock_set_speed` and S9.

### 3.15 Configuration keys added

| Key | Variable | Values | Recorded | Slice |
|---|---|---|---|---|
| `seed` | `SOA_SEED` | 32-bit number | yes | P6 (landed, 24d9235; recorded as in effect, 79c9ad8) |
| `encounters`, `encounters_hold_b` | `SOA_ENCOUNTERS`, `SOA_ENCOUNTERS_HOLD_B` | off/half/normal/double; 0/1 | yes | P1a |
| `autotext` | `SOA_AUTOTEXT` | unset or 0 off; `on` or 1 = 45 frames; N ≥ 2 frames | yes | P11 |
| `rumble` | `SOA_RUMBLE` | 0–100 | no | M18 |
| `fullscreen`, `scaler` | `SOA_FULLSCREEN`, `SOA_SCALER` | 0/1; integer/fit(/sharp) | no | H19a, P5a |
| `unfocused` | `SOA_UNFOCUSED` | run/mute(/pause) | no | M5b, M19 |
| `coop` | `SOA_COOP` | party slots | yes | P10b |
| `gamma`, `colorblind`, `colorblind_mode`, `flash_limit`, `crt` | `SOA_GAMMA`, … | as 3.13 | no | P5a |
| `deflicker` | `SOA_DEFLICKER` | 0/1 | no | P5b |
| `turbo` | `SOA_TURBO` | battle/sky/both | yes | M11a |

Test-only variables (not in `k_settings`): `SOA_ENCOUNTERS_TEST`, `SOA_AUTOTEXT_TEST`, `SOA_PAD2`,
`SOA_STALL`, `SOA_CLOCK_GAP_MS`, `SOA_CLOCK`, `SOA_WINDOW_TEST`, `SOA_PICTURE_SIZE`, `SOA_ROOT`,
`SOA_SETTINGS=<path>`.

---

## 4. Alternatives considered

- **P11 through `0x80346E60`** (the plan): rejected, because the draw zeroes it every frame (3.5).
- **P11 through story flag 1086,** which makes the game advance pages itself: rejected. It is saved
  with the game and also changes how windows are drawn.
- **P10's pad 2 read by the mod through XInput** (the plan): works, but every co-op mod would link
  XInput and repeat the absent-pad probe, and pad 2 could never enter the recording without a new
  API. Reading it in the runtime costs about a day more and makes rule 6 one si.c change.
- **P1 writing base×1 at "normal"** (the plan): replaced by writing nothing, so "normal" is the game.
  The price is hold-B's restore (3.4).
- **P1 rounding half up:** rejected for truncating integer division, which gives one answer on every
  compiler and a mutation trace that can be written down (P1a's Done).
- **A DLL report callback (`on_report` appended to `SoaModApi`):** rejected for now. Counting API writes
  per mod in mod.c needs no API change and covers P1's check; a mod's own log lines cover the rest.
  M16 may add a report call with the declared options.
- **Recorded settings in milestone 2** (the plan's event track): the settings half is a few lines of
  si.c's existing config line, so it lands with P6 now; the strict refusal stays in milestone 2.
- **M5b resolving against `soa.ini`'s folder** (the plan): that folder is `gen\`, build output; the
  owner's card would move to `gen\build\cards\` and look lost. Rejected for the port root.
- **M5b hiding the console on `GetConsoleProcessList` alone:** rejected, because a piped child of a
  console-less parent also owns its console (3.9).
- **M19 with `QueryUnbiasedInterruptTime`,** which leaves out sleep: rejected; it keeps counting in
  Modern Standby [I] and does not cover a debugger or a stalled thread. **Keeping TIME_UTC with jump
  detection:** rejected, because a backward step still wraps.
- **H19a's scaler on the GPU** (a D3D11 pixel shader on H8's device): cheaper per frame at 1080p and
  above, but it adds a shader compiler dependency (`D3DCompile` from `d3dcompiler_47.dll`) to the one
  path that shows the game, while the GPU decision is open. The CPU version is small, and its pure
  functions become the reference if the V-track moves presentation to shaders.
- **M11a's presenter as `round(hz/60)` / `round(hz/30)`:** rejected, because it changes normal play on
  85 Hz and 144 Hz displays (3.14).
- **M18 calling XInput from si.c:** rejected; si.c stays free of `windows.h` and links alone.
- **M18 adding `hle_report()` to threads.c's exits:** rejected for an `atexit` handler. Those paths skip
  the report deliberately; stopping the motor is all that is needed.
- **CH1 ordered after H19a and M11a:** rejected. A chord handler whose arms only log lets CH1 land first
  and be checked headless, and each later slice replaces its own arm.
- **M11's frame skip by reusing SOA_SNAP's test** (the plan): rejected, because copies are not
  skipped (3.14); measure first, then a skip with its own rules if needed.
- **Chords on GameCube buttons** (for example START+SELECT-style combinations): rejected; the game sees
  those buttons, so a chord would also press them, and withholding them before the recording is M8's
  work.
- **An enemy-table content check before T5:** 1c7b780 tried a 64-row limit on mod-folder tables, and
  4041dfc dropped it as a guess that would refuse data-driven mods. T5 writes the real check.

---

## 5. Risks and concerns, stated plainly

- **Two sessions, one tree, and a slice in flight.** P6 landed at 24d9235 without three things
  section 3.3 asks for; they landed as P6b (79c9ad8). At 012164a P1a was uncommitted in the working
  tree. Only one session edits `runtime/gxr*.c` and `gx.c` at a time: P5b and any
  M11a skip wait for the implementation session to say gxr.c is free.
- **P11's addresses were read, then run once.** The spike confirmed states 4 and 6 in one conversation
  (b911380). A second conversation with a different window (a sign, a shop, a cut-scene) may use flags
  the spike did not see. The mod presses only in state 4 without flags 0x50, and logs every press, so a
  surprise shows in the log rather than as a wrong choice.
- **More sessions cannot be replayed for a while.** Pad 2 (P10), hold-to-skip (P11b) and chord toggles
  (CH1, M11a) are not in the recording until milestone 2. If you play co-op or toggle turbo with
  `SOA_PAD_RECORD` on and something breaks, the recording will not reproduce it.
- **M19 changes the clock of every run.** A mistake there changes game timing everywhere. Mitigations:
  - every gap is logged, and ordinary runs must log none (M19's Done);
  - `SOA_CLOCK_GAP_MS=0` turns the rule off;
  - `SOA_CLOCK=utc` restores the old source for one release.

  A gap can also be legitimate host work, such as a first-sight texture pack load or a long PNG write on
  the guest thread. Those now pause game time instead of jumping it, which is what you want, but it is a
  change.
- **H19a touches the one path that shows the game, and H8 is still waiting for your check.** Resizing
  a flip-model swap chain is new code there. The GDI path stays, and `SOA_PRESENTER=gdi` remains the
  escape hatch.
- **DPI awareness changes the default window size** on a scaled display (smaller physical pixels,
  bigger default multiple). Anyone used to 1280×960 will see a different window.
- **Escape quits the game today,** and on a handheld in fullscreen that is one mis-press from losing
  unsaved play. 3.8 proposes that Escape leaves fullscreen instead (Q-O3).
- **Co-op and turbo need you.** Each of these is built and checked as far as a headless run can go, then
  listed for one owner session:
  - P10 needs two pads in your hands;
  - M11a needs your judgement at speed;
  - H19a and CH1 need the device;
  - M18 needs a pad that rumbles;
  - M19 needs a sleep and wake;
  - M5b needs a double-click;
  - P3 needs a real Dolphin save.
- **P3 writes cards.** A bad import can make a card BROKEN. The default writes a new file;
  `--in-place` keeps a backup and refuses while the game runs. `build/cards/slotA.raw` is still the one
  card that exists on one machine only (CLAUDE.md).
- **`mods/` is not an "enabled" list.** Every folder in it loads. Until M17's mod list, putting the
  comfort mods beside an "encounters off" data mod would silently combine them; P1a moves that example
  out. M5b's default `mods` folder makes this matter more, because it loads everything there.
- **The mods are code you build.** P1a makes `--link` build them, and a compile error in one mod folder
  then fails the port's link. That is on purpose, so a broken mod is never silently skipped. The
  consequence is that a half-written mod in `mods/` blocks the build until it is fixed or moved.
- **A crash can leave the pad buzzing** (M18): every orderly exit stops the motor, a fault does not.
- **The GPU decision may make some of this throwaway.** If a GPU backend lands soon, H19a's CPU scaler
  and P5a's sharp and CRT modes (perhaps a day of work) would be redone as shaders. The window
  handling, DPI, fullscreen, letterbox rectangle, `present_interval` and every pure filter's tests carry
  over.
- **Where the other three specs touch this one:**
  - **The disc layer (I-track)** changes what "the disc" is. It should reuse M5b's `aram_set_data_dir`
    and settings.c's resolved `disc` as its seams, and it must keep DI completion timing, which M19 does
    not alter. Its I5a would change that timing on purpose, so it needs its own agreement first
    (disc-layer.md, implementation question 1).
  - **Portability (L-track)** takes `clock.c`'s POSIX source. The chord, picture and seed logic are
    plain C for an SDL or Android front end; window.c stays the Windows one.
  - **The GPU spec (V-track)** decides whether H19a's scaler and P5a's output modes move to shaders.
- **60 fps moves back by this milestone's length,** about three and a half weeks of evenings at these
  sizes, or about 4 with the gap fillers ../PLAN-NEXT.md puts beside them. H17a does not depend on
  anything here; if 60 fps matters more to you, it can go first.
- **The plan's addresses in P10 and M11a are research readings, not runs.** P1's were read in one run
  (`build/p1-addr.log`, 3.4). Each Done below peeks them in the same run that checks the feature, and
  P10b's live Done waits on its spike.

---

## 6. Slices

**Landed:**
- MV2: 3949028 and b071949;
- T0: 1c7b780 and 4041dfc;
- now.md's N4: c8274db;
- P11's spike: b911380;
- P6: 24d9235, without 3.3's three additions, which are P6b;
- P6b: 79c9ad8;
- T0c: 012164a;
- manifest 2's second follow-up (the recording line's `+N more` tail keyed by id): b1199b3.

**In flight** (working tree, uncommitted at 012164a): P1a. The implementation session ran
../PLAN-NEXT.md's C5a (gpu-backend.md section 6, a `gx.c` log) first, before P6b; it landed as 750cef0,
and it is not a comfort slice.

**Order:** P1a, P11, P1b (now.md's N5 and N6, with P1 split), then M18, CH1, P11b, H19a, M5b, M19,
P3, P10a, P10b, P5a, P5b, M11a. P6b and T0c have landed. [../PLAN-NEXT.md](../PLAN-NEXT.md) C1
places the gap fillers among them.

**Can ship alone:** P3 (tooling only); M18 (P6's hook table has landed); CH1; H19a
(keyboard toggles; the chord arm is CH1's); M5b; M19; P5b.
**Need another first:**
- P1a needs P6 and P6b (both landed);
- P11 and P1b need P6 and P1a;
- P11b needs P11 and CH1;
- P10b needs P10a, P6 and P1a;
- M11a needs P6, and its chord arm needs CH1;
- P5a's `sharp` and `crt` need H19a's scaler (its native filters do not);
- M5b's `unfocused = pause` needs M19;
- M11b needs M19 and S9.

Every `--link` slice also runs `python tools/citest/compile_runtime.py` and `python tools/recompile.py
--link` before its checks. "Contract" is the five checks of section 1, with the feature off.

---

**T0c. Card images under any name** — *hours; none; prerequisites none. **Landed 012164a**, wider
than specified (3.2).*
- Files (as landed): `tools/guard.py`, `tools/tests/test_guard.py`, `.github/workflows/ci.yml`, and the
  documents that say what the guard refuses.
- What: 3.2.
- *Done, as landed* (its commit message):
  - `python -m pytest tools/tests/test_guard.py` (76 tests), all synthetic: a truncated synthetic card is
    refused at three directory entries and passes at five other offsets; `.gcs`, `.sav`, `load/`,
    `dump/`, the GCS, SAV and MP3 frame heads, backup names such as `slotA.raw.bak`, and in `--history`
    a PNG named `.txt`, a card image and a mod-folder binary deleted with its `mod.ini`. Eighteen
    mutations each turned at least one test red.
  - `python tools/guard.py` and `python tools/guard.py --history` pass on this repository; every
    savetest card image holding a save is refused by content (read-only, on this machine's `build/`).

**P6. Race seed, recorded settings, report hooks** — *hours; `--link`; prerequisites none. **Landed
24d9235**, without 3.3's three additions, which are P6b.*
- Files (as landed): `runtime/seed.c` (new), `runtime/hle.c`, `runtime/settings.c`, `runtime/main.c`,
  `runtime/selftest.c`, `tools/tests/test_seed.py` (new), `tools/tests/test_settings.py`, README.md.
- What: 3.3 but its three additions, and the report-hook table (3.0).
- *Done, as landed* (FINDINGS "P6"):
  - `python -m pytest tools/tests/test_seed.py`: seed.c built alone gives, for seeds {0, 1,
    0xFFFFFFFF} and n = 0..3 at each site, the values of an independent Python `fmix32`. A lr outside
    the three returns the timebase untouched and counts as "other". Malformed `SOA_SEED` values (`12x`,
    `0x123456789`, `4294967296`) are refused with the line.
  - Self test (`$env:SOA_SELFTEST='1'; gen\soa.exe extracted`), the case "race seed at OSGetTick":
    - with `seed_set(1, 12345)`, the translated `fn_8023851C` (OSGetTick) called with lr at each site
      returns `seed_value(12345, site, n)` for n = 0 and 1;
    - the translated `fn_8025ECBC` (srand) called just after stores that value at `0x803469A8`;
    - with lr `0x8000A1DC`, the value returned equals no site's pin for n = 0..3.

    Mutation: a `seed_pin` that ignores lr fails the last line. It is deterministic: it compares against
    pins, never two clock reads. Nothing is left to add here.
  - The battle scenario with `SOA_SEED=12345` [V run, FINDINGS "P6"]: field load 2, battle start 1 and
    1 pinned, 191,132 other reads; both field loads come before the deck fight, which starts at frame
    9810 and is still going at the scenario's 12,000; the recording's line ends `seed=12345`; a store
    watch shows srand storing `8739D20C` from lr `0x8000A1D4` and `2A787E8A` from `0x8000A1DC` at frame
    9810, which are `seed_value(12345, 1, 0)` and `seed_value(12345, 2, 0)` exactly.
  - Without `SOA_SEED` no `[seed]` line appears and the contract holds.
  - `python -m pytest tools/tests/test_settings.py`: `seed` sets `SOA_SEED`, and `settings_recorded`
    returns `seed=12345` only when it is set.
  - The pin sites exist: a pytest that, when `gen/` is present, finds each `s->lr = 0x…u;
    fn_8023851C(s);` exactly once, followed by `fn_8025ECBC`, and skips without `gen/`. A retranslation
    that moves a site fails it.
  - The contract holds.

**P6b. P6's three additions** — *hours; `--link`; prerequisites P6 (24d9235). **Landed 79c9ad8**
(FINDINGS "P6, followed up").*
- Files (as landed): `runtime/seed.c`, `runtime/main.c`, `runtime/si.c`, `runtime/settings.c`,
  `tools/tests/test_seed.py`, `tools/tests/test_padrec.py`, `tools/tests/test_settings.py`, the stubs
  in `tools/tests/test_memguard.py` and `test_profiler.py`, and the count copies.
- What: 3.3's pin line and "Room for it". It also records the seed as seed.c applied it (decimal, so
  `0x3039` and `12345` record alike, and a refused value records nothing), and `settings_recorded` no
  longer leaves half a value in the buffer.
- *Done, as landed:*
  - `python -m pytest tools/tests/test_seed.py`: each pin prints its `[seed] pin:` line, with the value
    the Python `fmix32` gives.
  - `python tools/scenario.py run battle --frames 13500 --env SOA_SEED=12345 --env
    SOA_PAD_RECORD=build/p6.pad --log build/scenario-p6.log`, then `python tools/tests/test_seed.py
    build/scenario-p6.log build/p6.pad`. The module's `__main__` checks the run with the same Python
    `fmix32`:
    - every `[seed] pin` line's value equals `seed_value(12345, site, n)`, each site counting from 0;
    - the report's per-site counts equal the numbers of pin lines;
    - a field-load pin comes after a battle start (the battle's exit path);
    - the recording's `# config` line ends `seed=12345`.

    The run gave field load 4, battle start 1 and 1 [V run, 79c9ad8]: two field loads before the deck
    fight and two after it, between frames 12,800 and 12,900 (the victory pose) and between 13,060 and
    13,100 (after the results screen; the deck field is back at 13,400). The first P6 run stopped at
    12,000, mid-battle, which is why this one runs to 13,500. The battle-start pins are `0x8739D20C`
    and `0x2A787E8A`, the values P6's watch saw srand store. Mutation: the same check with one value
    edited names that pin and fails.
  - `python -m pytest tools/tests/test_padrec.py`, a new case: a 600-byte config extra reaches the
    recording's `# config` line whole. An 800-byte one prints the "cut at" line. Mutation: the old
    320-byte buffer fails the first (tried).
  - `python -m pytest tools/tests/test_settings.py`: the recorded seed is the one seed.c applied, with
    the raw text as the mutation.
  - The contract held: replay 23/23 at 1, 2, 3 and 8 threads, the self test, `title --check`.

**P1a. Encounter slider and hold-B** — *a day; none for the DLL, `--link` for the settings lines, the
mod-id line and the DLL build; prerequisites P6 (recorded settings) and P6b, both landed. In flight in
the working tree at 012164a.*
- Files: `mods/encounter-rate/{mod.c,mod.ini}`, `examples/mods/encounters-off/` (moved), `runtime/mod.c`
  (per-mod write counts), `runtime/settings.c`, `runtime/main.c` (the "no such mod" line),
  `tools/recompile.py` (builds `mods/*/mod.c`), `tools/tests/test_mods.py` (with a `__main__` log
  checker), HANDOFF.md, README.md.
- What: 3.4, except its test mode.
- These runs peek only the multiplier byte, which the mod writes in any field zone. They do not depend
  on the zone or the step counter (Q-I5).
- *Done:*
  - `python -m pytest tools/tests/test_mods.py`. Each shipped `mods/*/mod.c` compiles with the `/LD` line
    `--link` uses. On the fake guest with scene 6:
    - with `SOA_ENCOUNTERS` unset, mod.c's report line for the mod reads `0 write(s)` over 100 frame
      ends;
    - at `half` with no accessory, the byte reads 25 and the count is nonzero;
    - with a synthetic accessory table giving character 0 effect 84 = 100, `half` reads 50 and `double`
      127;
    - at `normal`, 30 frames with B held read 0, and the first frame end after release writes 0xFF once
      and then nothing.

    Mutations: a build that multiplies the byte it read (not base) reads 50, 25, 12, 6, 3, 1, 0 at half
    with the accessory and fails the second frame; a build that skips the restore leaves 0.
  - **The byte held, one run per preset, each against fixed values.** Common to every run:
    - a copy of `build/savetest/card-saved.raw` (a101b, part A);
    - `--env SOA_CARD=<copy> --env SOA_MODS=mods --env SOA_ENCOUNTERS=<preset>`;
    - the Continue preamble,
      `SOA_PAD=1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a` (no A after the
      load);
    - `python tools/scenario.py run battle --frames 4000`.

    Case A, nothing poked, `--env SOA_PEEK=0x8030B7AC@3000-3600`:
    - the mod logs `base 50 (none)`: characters 0 and 1 wear 204 and 201, neither with code 84 [V run,
      `build/p1-addr.log`]. If it logs another base, the expected values follow from it by 3.4's
      arithmetic, and the log line is the evidence;
    - the second byte reads 25 at half and 100 at double on every frame but those where the game
      rewrote it (the next frame is back);
    - at normal it reads the game's own `FF`, and the report says `0 write(s)`.

    Case B, the accessory:
    - poke 210 into character 0's slot, `3000:0x8030B808=0x00D2LLLL`, where LLLL is the lower half as
      case A's peek of `0x8030B808@2990` read it;
    - then warp to the same map at 3010 with HANDOFF's five pokes (`0x80305CF0=0x4D453130`,
      `0x80305CF4=0x31422E53`, `0x80305CF8=0x43540000`, `0x8030E420=0`, `0x80311AEC=15`, i.e.
      `ME101B.SCT`), so the load runs `fn_801EF7E0`;
    - `--env SOA_PEEK=0x8030B7AC@3300-3900`: 50 at half, 127 at double, and the game's own `64` at normal
      with `0 write(s)`. At normal, `64` is also the proof that the load recomputed the byte. `FF` there
      means the setup, not the mod, is wrong [I: `lr 0x800FFD98` is the load path].

    Mutation: a build that overwrites instead of multiplying reads 25 and 100 in case B.
  - **Hold B at normal, restored.** Case A's command at `normal` with `,3400:b#300` added to the pad reads
    `00` from 3401 to 3700 and `FF` from 3701 to 3900, within one frame at each edge. Mutation: a build
    without the restore reads `00` to 3900.
  - **Each of these runs is checked by a command:** `python tools/tests/test_mods.py p1a <case> <preset>
    <log>`, whose `__main__` applies the rules above to the peek lines and the mod's log lines. Its
    pytest feeds it a synthetic log with one rule broken (the checker's mutation).
  - `python tools/recompile.py --link` names `mods\encounter-rate\mod.dll` among what it built.
  - With `SOA_ENCOUNTERS=half` and `SOA_MODS` unset, the log has the "no mod with id `encounter-rate`"
    line.
  - The contract holds; `SOA_MODS` unset changes nothing.

**P11. Dialogue auto-advance** — *hours; none (DLL) and `--link` for its settings line; prerequisites
P6, P1a (now.md N6, auto-advance only; its spike is done, b911380).*
- Files: `mods/autotext/{mod.c,mod.ini}`, `runtime/settings.c`, `tools/tests/test_mods.py`, README.md.
- What: 3.5.
- *Done:*
  - **One run** from a copy of `card-saved`: `python tools/scenario.py run battle --frames 8000
    --env SOA_CARD=<copy> --env SOA_MODS=mods --env SOA_AUTOTEXT=45
    --env "SOA_PAD=1600:start,1640:a,1800:start,1840:a,2000:start,2040:a,2240:a,2440:a,2640:a,6000:a,6900:a"
    --env "SOA_POKE=3000:0x80305CF0=0x4D453335,3000:0x80305CF4=0x35412E53,3000:0x80305CF8=0x43540000,3000:0x8030E420=0,3000:0x80311AEC=15"
    --env SOA_PEEK=0x80346E64@2900-7900 --log build/scenario-p11.log`. The state is the upper halfword
    of each peek. `python tools/tests/test_mods.py p11 build/scenario-p11.log` applies these rules
    (its pytest feeds it a synthetic log with one rule broken). The run passes when:
    - (a) the mod logs at least two presses (the officer's page 《どうせみないでしょ？》, and
      《どうする？》 after 6000), and for each one the peek at the end of the frame before it reads 4;
    - (b) the first frame after 3002 that reads 6 comes less than 120 frames after the first that reads
      4. The spike's page completed at 3087, and without the mod it rested at 4 for 2,913 frames;
    - (c) from that first 6 until frame 5999, every peek reads 6: the mod never presses in a choice;
    - (d) `/field/a002b.mld` (part B) loads, and the last `[peek] frame F` line before its load line has
      F ≥ 6900.
  - **Mutations, same pad script and pokes:**
    - without `SOA_MODS`, (b) fails: the first 6 comes after 6000, as in the spike. (d) fails too,
      because the A at 6000 dismisses the officer's page and the A at 6900 chooses みる, so nothing
      loads;
    - with `SOA_AUTOTEXT_TEST=press-in-choice`, (c) fails and a002b loads before 6000.

    The sequence after みる (《どうする？》 as a box, then the B/C choice) is from earlier runs, not this
    one [V FINDINGS "The developers' part select"]. If the B/C choice is not up by 6900, the log shows
    it, and the pad's second A moves later.
  - `python -m pytest tools/tests/test_mods.py`, on the fake guest:
    - with state 4 and flags 0 written to the words above, the filter presses A for two frames after
      the delay, and not again until the state leaves 4;
    - with flags 0x10 or 0x40, state 6, state 8 or a task word of 0, it never presses;
    - `SOA_AUTOTEXT=on` waits 45 frames and `0` never presses.

    Mutation: writing the guard as `flags & 0x50 == 0` fails the flags cases.
  - The contract holds.

**P1b. The encounter contrast** — *a day to several days (runs of about 130,000 frames at
`SOA_SPEED=3`); `--link`; prerequisites P1a, and a card and walk that keep the party in a rate-20 zone
where the step counter counts. `card-saved`'s a101b spot is not one: it is zone 0, and the counter
stayed 0 over 1,700 frames of walking (Q-I5). Q-I5's short run on another card, for example the
part-G card at 116a, comes first.*
- Files: `mods/encounter-rate/mod.c` (test mode), `tools/encounter_check.py`,
  `tools/tests/test_encounter_check.py`.
- What: 3.4's test mode.
- *Done:*
  - **The rules**, applied by `python tools/encounter_check.py LOG`:
    - count only trials whose logged rate is 20 at both ends, the rate of a101b's zones 2 and 3
      (encounters.md §2);
    - for each k, compute `r(k)` = battles per 1000 moving frames over the counted trials. This is the
      rate estimate for trials censored at 600, and it replaces "the mean moving frames to a battle";
    - it passes when:
      - each nonzero k has at least 40 counted trials, and `r(2) > r(1) > r(½)`;
      - there are at least 40 counted k = 0 trials, each reaching 600 moving frames with no battle;
      - there are at least 20 counted `hold` trials, each reaching 600 moving frames with no battle;
      - no more than 10% of all trials are `stuck`.
    - **False failure** is about 0.2%, from the plan's constant-odds model at N = 480 [I]. At 40 battles
      per k, each ordering comparison sits about 3.1 standard errors apart. A mod that does nothing fails
      the k = 0 and hold rules: a k = 1 trial at rate 20 reaches 600 moving frames with no battle with
      probability about e^−11.
  - `python -m pytest tools/tests/test_encounter_check.py`. Logs simulated from that model pass. Each of
    these fails:
    - the same logs with k shuffled;
    - a battle at k = 0;
    - a battle in a hold trial;
    - 39 counted trials at one k;
    - 11% stuck;
    - a rate-0 zone counted as rate 20.
  - **The field run**: `python tools/scenario.py run encounter --env SOA_CARD=<Q-I5's card copy>
    --env SOA_MODS=mods --env SOA_ENCOUNTERS_TEST=1 --env SOA_SPEED=3 --env "SOA_PAD=<Q-I5's walk>"
    --frames 150000 --log build/scenario-p1.log`, then `python tools/encounter_check.py
    build/scenario-p1.log` passes.
  - **The sky**: the same on the world map (map 99) from the part-L card, with its own log, applying
    the same rules to its zones' logged rate. If that rate is not 20, the false-failure figure is
    recomputed for it in the check's output.
  - The contract holds with `SOA_ENCOUNTERS_TEST` unset.

**M18. Rumble** — *hours; `--link`; prerequisites P6 (the report-hook table). **Owner.***
- Files: `runtime/si.c`, `runtime/window.c`, `runtime/main.c`, `runtime/settings.c`, `runtime/selftest.c`,
  `tools/tests/test_padrec.py` (stubs unchanged: the sink is a setter), README.md.
- What: 3.7.
- *Done:*
  - Self test, a new case with a counting sink:
    - channel 0 OUTBUF bits 0–1 = 1 gives one call with nonzero speed;
    - = 0 and = 2 each give a zero-speed call;
    - a repeated write of the same bits gives no call;
    - channels 1–3 give none;
    - with strength 0, with the window flag off, or with scripted input, no write gives a nonzero call;
    - `si_motor_stop()` while on gives one zero-speed call.

    Mutation: a gate that ignores strength fails the strength-0 line.
  - `python -m pytest tools/tests/test_padrec.py` unchanged.
  - **Owner:** the pad rumbles in a battle with the game's Vibration option on, and not with it off.
  - The contract holds.

**CH1. Gamepad chords and host buttons** — *a day; `--link`; prerequisites none (the API append is
after MV2, landed). **Owner.***
- Files: `runtime/si.c`, `runtime/window.c`, `runtime/main.c`, `runtime/mod.c`, `runtime/soa_mod.h`,
  `tools/scenario.py`, `tools/tests/test_padrec.py` (the `window_host` stub),
  `tools/tests/test_scenario.py`, `tools/tests/test_mods.py`, README.md.
- What: 3.6.
- *Done:*
  - `python -m pytest tools/tests/test_padrec.py tools/tests/test_scenario.py`: `lb`, `view`, `ls` and
    `rs` parse in both grammars, and a misspelling is still refused. A script with `view+lb` produces
    the host bits and no GameCube bit. A chord held for 10 frames and read 3 times a frame fires once.
  - One headless run: `python tools/scenario.py run title --check --env
    "SOA_PAD=1600:start,1640:a,1700:view+lb,1800:lb,1900:view+rs" --env SOA_PAD_RECORD=build/ch1.pad`.
    That is title.scn's own pad plus three host presses, inside its 2000 frames. It passes its checks,
    and:
    - the log has exactly `[chord] frame 1700: view+lb -> fullscreen (not built yet)` and `[chord] frame
      1900: view+rs -> turbo (not built yet)`, and no chord line at 1800;
    - the `[si]` lines from 1700 to 1910 show no button change (host buttons never reach the game);
    - the recording holds the two `# chord` lines.

    Mutation: a build that maps LB to Z shows `0010` in the `[si]` log.
  - `python -m pytest tools/tests/test_mods.py`: `host_buttons` returns what the stub source gives,
    and a DLL built against the previous header still loads (`SOA_MOD_HAS`).
  - `python tools/scenario.py run title --check` (the pad-grammar row of CLAUDE.md's table).
  - **Owner:** with the pad in slot 1 or 2 (not 0), port 1 plays.

**P11b. Hold-to-skip** — *hours; none; prerequisites P11, CH1.*
- Files: `mods/autotext/mod.c`, `tools/tests/test_mods.py`.
- *Done:*
  - `python -m pytest tools/tests/test_mods.py`: on the fake guest, with host LB set by the stub, the
    filter presses A in states 3 and 4 on the two-on, two-off cadence, and never in 6 or with flags 0x10
    or 0x40. With LB clear it only auto-advances.
  - In P11's run with `,3000:lb#2400` added to the pad script, checked by `python
    tools/tests/test_mods.py p11b <log>` (its pytest feeds it a synthetic log with one rule broken):
    - the mod logs at least one `skip press in state 3`;
    - the first 6 after 3002 comes fewer than 45 frames after the first 3 after 3002;
    - the choice still rests at 6 until 6000, and `a002b` loads only after 6900.

    Mutation: the same run with the `lb` item removed logs no state-3 press, and the first 6 comes at
    least 45 frames after the first 4.

**H19a. Fullscreen, DPI, resizing, letterbox** — *a day to several days; `--link`; prerequisites none
(its chord arm replaces CH1's). **Owner.***
- Files: `runtime/window.c`, `runtime/picture.c` (layout and interval), `runtime/main.c` (the chord
  arm), `runtime/settings.c`, `tools/tests/test_picture.py` (new), README.md.
- What: 3.8.
- *Done:*
  - `python -m pytest tools/tests/test_picture.py`:
    - `picture_layout` for 640×480 into 1920×1080 gives 1280×960 at (320,60) in `integer` and
      1440×1080 at (240,0) in `fit`;
    - into 1280×800 it gives 640×480 / 1066×800, and into 2560×1600 1920×1440 / 2133×1600;
    - into anything smaller than 640×480 it gives a rectangle that fits;
    - `present_interval(hz, 30)` is 2, 1, 4 and 1 at 60, 85, 120 and 144 Hz.

    Mutations: swapping width and height in the formula fails three cases; a plain `round(hz/30)` fails
    85 and 144.
  - One windowed run with `SOA_WINDOW_TEST=fs@300,win@600,size:1000x700@900`, then the same with
    `--env SOA_PRESENTER=gdi`. In each run on its own:
    - every `[window]` line's image rectangle equals `picture_layout(640, 480, client W, client H,
      mode)` for its own logged client size and mode. `python tools/tests/test_picture.py <log>` checks
      this and the rules below: its `__main__` is the Python twin of `picture_layout` reading the log,
      and its pytest feeds it a synthetic log with one rule broken;
    - the rectangle lies inside the client, is 4:3 within one pixel, and is centred within one pixel;
    - after fullscreen the client equals the logged monitor size;
    - `[present]` reports no failed present or resize.

    The two runs are never compared with each other.
  - The CH1 headless run now logs `[chord] frame 1700: view+lb -> fullscreen (no window: logged only)`.
  - Alt+Enter not pressing START cannot be driven from a headless check; it is part of the owner
    check below, read from that session's `[si]` log (no `1000` at the toggle's frame).
  - **Owner** on the device: fullscreen by F11, Alt+Enter and the chord; the window resizes and
    letterboxes; the cursor hides; Escape in fullscreen leaves fullscreen.
  - The contract holds (the window is not part of headless checks).

**M5b. A first run without a terminal** — *a day; `--link`; prerequisites none (`unfocused = pause`
needs M19). **Owner.***
- Files: `runtime/settings.c`, `runtime/main.c`, `runtime/aram.c`, `runtime/window.c`, `runtime/si.c`
  (`si_set_path_root`), `runtime/audio_out.c`, `runtime/selftest.c`, `.gitignore`,
  `tools/tests/test_settings.py`, `tools/tests/test_padrec.py`, README.md.
- What: 3.9.
- *Done:*
  - `python -m pytest tools/tests/test_settings.py`, with `SOA_ROOT=<tmp>` and a `soa.ini` there:
    - `card = saves\a.raw` becomes `<tmp>\saves\a.raw`; an absolute path is kept; a variable set in the
      environment is kept as given;
    - the default card is `<tmp>\build\cards\slotA.raw` only when a `soa.ini` was read, and `render`
      defaults to 1 only then;
    - `mods` defaults to `<tmp>\mods` only when a mod-backed key is set;
    - the root rule picks the parent of a folder named `gen` that sits beside `runtime\`, and the exe's
      own folder otherwise; `<tmp>\gen\clang\soa.exe` gets the same root as `<tmp>\gen\soa.exe`;
    - `should_hide_console` is true for (1, char) only, and false for (1, pipe), (1, file) and
      (2, char).

    Mutations: resolving against the current directory fails the first case; dropping the handle-type
    test fails (1, pipe); looking only at the exe's own folder's name fails the `gen\clang` case.
  - `python -m pytest tools/tests/test_padrec.py`: with the root set, a card under it is written as a
    relative path in `# config`, and a card outside it as given.
  - **Launched from another directory,** the way a front end starts it:
    `Start-Process -WorkingDirectory $env:TEMP -FilePath (Resolve-Path gen\soa.exe)` with
    `SOA_SETTINGS=<a test ini naming only nosound = 1>` and `SOA_FRAMES=600`:
    - the log file named in its first line exists under `build\logs\`;
    - its `[exi] memory card` line names `<root>\build\cards\slotA.raw`;
    - no `gen\build\` or `%TEMP%\build\` directory was created.
  - **Piped under a new console:** a Python `subprocess.Popen` of the same command with
    `creationflags=CREATE_NEW_CONSOLE` and `stderr=PIPE` receives the `[run]` report on the pipe, and no
    new file appears under `build\logs\`.
  - Self test, a new case: `audio_set_muted(1)`, then push a nonzero block, and the samples handed to
    the device (through a test hook in audio_out.c) are all zero; after `audio_set_muted(0)` they are the
    block's. Mutation: a mute that skips `audio_push_block` fails the first line.
  - The contract holds (every check runs with no `soa.ini`).
  - **Owner:**
    - double-click `gen\soa.exe` with your `soa.ini`: it opens rendered, on your card, with no console;
    - with `unfocused = mute`, alt-tab away: the game goes silent and ignores the pad.

**M19. A clock that survives sleep and speed changes** — *several days; `--link`; prerequisites none.
**Owner.***
- Files: `runtime/clock.c` (new), `runtime/hle.c`, `runtime/tick.c`, `runtime/dsp.c`, `runtime/main.c`
  (`SOA_STALL`), `runtime/window.c` (power events, `unfocused = pause`), `runtime/selftest.c`,
  `tools/tests/test_clock.py` (new), README.md.
- What: 3.10.
- *Done:*
  - `python -m pytest tools/tests/test_clock.py`, clock.c built alone and fed synthetic host times:
    - steady 1 ms steps give 1 ms of guest time each;
    - one 10 s step gives 0 and one epoch bump, and the same with the gap rule at 0 gives 10 s;
    - a backward host step gives no backward guest step;
    - a speed change from 1 to 2 is continuous (the reading just after is within 2 ms of the one just
      before) and bumps the epoch;
    - paused spans are excluded.
  - One headless run, `python tools/scenario.py run title --check --env SOA_STALL=600:10
    --log build/scenario-m19.log` (10 s, under the 20 s headless watchdog):
    - it passes the four checks;
    - the log has one `[clock]` gap line at frame 600 counting 0 s;
    - the `[run]` line's guest seconds are at least 9 s below its wall seconds minus the logged origin
      offset.

    Mutation, the same command plus `--env SOA_CLOCK_GAP_MS=0`: no gap line, and guest seconds equal
    wall seconds minus the origin offset within 0.5 s.
  - **No gaps in ordinary runs:** `python tools/scenario.py run title --check` and `python
    tools/scenario.py run battle` without `SOA_STALL` each log zero `[clock]` gap lines and `[run]`'s gap
    count 0. A nonzero count fails: a normal host stall must not trip the rule.
  - Self test, a new case: with the DMA running, an epoch bump makes the next `dsp_poll` deliver one
    block and resynchronise, not a burst.
  - The contract holds; `python tools/scenario.py run speed --check` (at `SOA_SPEED=10`) still passes.
  - **Owner:** sleep the handheld for a minute in the field; on waking, the play-time clock has not
    jumped.

**P3. `.gci` import and export** — *a day; none; prerequisites none. **Owner.***
- Files: `tools/cardformat.py`, `tools/tests/test_cardformat.py`.
- What: 3.11.
- *Done:*
  - `python -m pytest tools/tests/test_cardformat.py`, all synthetic (no game data):
    - a formatted image plus a synthetic 3-block `GEAE8P` entry imports and verifies READY;
    - it exports to a `.gci` whose data blocks equal the input's, and whose entry equals it except the
      start block at 0x36;
    - importing that export into a second image gives the same blocks;
    - importing twice gives two chains that do not overlap.
  - **The slots:** after an import, the directory and FAT slot that `current_slot()` picked before the
    import holds the new contents with check code = the other slot's + 1. The other slot is byte for
    byte what it was before the import.

    Mutations, each failing this assertion: writing into the newer slot; leaving the check code
    unchanged.
  - **Each refusal in 3.11 fires:** wrong maker, wrong size, zero blocks, a duplicate name, and an
    image that does not verify.
    - "Not enough free blocks" is tested on the default 4 Mbit geometry (59 user blocks) with 57 blocks
      used and a 3-block import.
    - "No free entry" is tested on a 16 Mbit image built with `--size 16` (251 user blocks), holding 127
      one-block entries.
  - `--in-place` writes the `.bak` first.
  - **Owner:** a save exported from Dolphin imports into a copy of your card, verifies READY, and
    Continue lands on the saved map; a port save exported with `export` loads in Dolphin.

**P10a. Pad 2 in the runtime** — *a day; `--link`; prerequisites none (the API append is after MV2,
landed).*
- Files: `runtime/si.c`, `runtime/window.c`, `runtime/mod.c`, `runtime/soa_mod.h`, `runtime/main.c`,
  `tools/tests/test_padrec.py`, `tools/tests/test_mods.py`, README.md.
- What: 3.12.
- *Done:*
  - `python -m pytest tools/tests/test_padrec.py`:
    - `SOA_PAD2` parses with `SOA_PAD`'s grammar and refusals;
    - the two scripts do not affect each other (a press in one never appears in the other);
    - with `SOA_PAD2` set, an SI transfer on channel 1 still reports no controller.

    Mutation: setting `g_present[1]` fails the last case.
  - `python -m pytest tools/tests/test_mods.py`: `read_pad(2, …)` returns the stub's state; `read_pad(1)`
    and `read_pad(3)` return 0; a DLL built before the append still loads.
  - The contract holds.

**P10b. Couch co-op** — *hours to a day; none (DLL) and `--link` for its settings line; prerequisites
P10a, P6, P1a, and its one-hour spike (3.12). **Owner.***
- Files: `mods/coop/{mod.c,mod.ini}`, `runtime/settings.c`, `tools/tests/test_mods.py`, README.md; a
  FINDINGS entry for the spike.
- What: 3.12.
- *Done:*
  - **The spike** is in FINDINGS: the command-type word read whole at a phase-1→2 edge for Attack and
    after one left, and the wheel's opening slot and wrap. The live check below waits on it, and its
    expected values come from it.
  - `python -m pytest tools/tests/test_mods.py`, on the fake guest:
    - the filter follows the member index and phase words;
    - it passes neutral at a handover while the incoming pad holds A, until a frame with every button
      released, and then forwards the next A.

    Mutation: a filter with no handover rule confirms on the held A. This is the handover's check.
  - `python tools/scenario.py run battle --env SOA_MODS=mods --env SOA_COOP=1
    --env "SOA_PAD2=3600:left#4@20,3700:a@200" --env SOA_PAD_RECORD=build/p10.pad
    --log build/scenario-p10.log`. This is the deck fight, where Vyse is slot 0 and Aika slot 1.
    `python tools/tests/test_mods.py p10b build/scenario-p10.log build/p10.pad` applies the rules
    below, with the spike's values (its pytest feeds it a synthetic log with one rule broken). It
    passes when:
    - on every one of Aika's turns the `[si]` lines show only pad-2 presses, with no `0100` from port
      1's A-every-150 script;
    - her logged command type equals the spike's value for the number of lefts forwarded before her A;
    - on at least one of her turns at least one left was forwarded;
    - on Vyse's turns only port 1's presses appear;
    - every `[mod] coop: handover` line is followed by neutral `[si]` input until a frame where pad 2 has
      no button down;
    - `build/p10.pad` still holds port 1's A presses during Aika's turns, because the record is taken
      before the filter.
  - Mutation, the same command with `--env SOA_COOP=`: no pad-2 press is forwarded, so the "at least one
    left" rule fails.
  - Frames opened on Aika's action (SOA_SNAP) show the command pad 2 chose.
  - **Owner:** two pads, one battle; then one battle through Parsec if you want online.

**P5a. Picture options** — *a day; `--link`; prerequisites H19a for `sharp` and `crt` (the native
filters need nothing).*
- Files: `runtime/picture.c`, `runtime/picture.h`, `runtime/window.c`, `runtime/main.c` (the replay
  output), `runtime/settings.c`, `tools/tests/test_picture.py`, README.md.
- What: 3.13.
- *Done:*
  - `python -m pytest tools/tests/test_picture.py` on synthetic images:
    - gamma 1.0 changes no byte, and 2.2 changes mid-greys;
    - each simulation matrix equals 3.13's coefficients to six places, and maps grey to grey within
      1/255;
    - correction of a pure red under protan equals the daltonize formula computed in Python within
      1/255;
    - the flash limiter, fed a full-screen black/white flash at 5 Hz (three frames each at 30 fps),
      leaves at most 3 flashes a second by the same detector, while a 2 Hz flash passes untouched;
    - `sharp` into an exact multiple equals nearest-neighbour.

    Mutations: a limiter that never acts fails the 5 Hz case; one that always acts fails the 2 Hz case;
    a matrix applied to sRGB values instead of linear fails the correction case.
  - **Replay, no window,** on copies of three captures kept outside `build/fifo` (a field, a battle,
    the title):
    - `gen\soa.exe --replay <copy>` with each key set writes `<copy>.picture.png`, and each is opened;
    - with every key at its identity value plus `SOA_PICTURE_SIZE=640x480` and `scaler=integer`, the
      decoded RGB pixels of `.picture.png` equal those of `.png`, compared by a pytest helper that
      decodes both;
    - mutation: `gamma = 1.01` makes them differ.
  - **Budget:** in one windowed run at the device's resolution with `sharp` and the native filters on,
    `[present]` reports p99 under 6 ms, a limit fixed here.
  - The contract holds; `SOA_HASH` is untouched by construction (it is taken before `present()`).

**P5b. Deflicker off for the display copy** — *hours; `--link`; prerequisites the implementation
session releases gxr.c.*
- Files: `runtime/gxr.c`, `tools/tests/test_gxr_copy_filter.py`, `runtime/settings.c`, README.md.
- What: 3.13.
- *Done:*
  - `python -m pytest tools/tests/test_gxr_copy_filter.py`: with `SOA_DEFLICKER=0`, a synthetic display
    copy under the game's weights (BP 0x53 `30A208`, 0x54 `00820A`) equals the same copy under the SDK's
    identity set, byte for byte, and a texture copy under the game's weights does not. Mutation:
    applying the switch to texture copies fails the second assertion.
  - `python tools/scenario.py replay` 23/23 with the switch unset (it drops `SOA_*`), at the thread
    counts `--threads 1,2,3,8`.
  - With it set, each capture replayed directly from a copy outside `build/fifo` (`gen\soa.exe --replay
    <copy>` with `SOA_HASH=1`, `SOA_DEFLICKER=0`) prints a hash different from its manifest line, for
    all 23 (every capture's display copy is filtered, PLAN.md:479); three of the PNGs are opened.

**M11a. Turbo up to 2×** — *a day; `--link`; prerequisites P6 (a recorded key); its chord arm replaces
CH1's; the presenter uses H19a's `present_interval` (or moves it into picture.c itself if H19a has not
landed). **Owner.***
- Files: `runtime/tick.c`, `runtime/window.c`, `runtime/picture.c` (`present_interval`), `runtime/main.c`
  (the chord arm), `runtime/settings.c`, `runtime/audio_out.c` (one report line),
  `tools/tests/test_picture.py`, `tools/tests/test_turbo.py` (new: the run's log checker), README.md; a
  FINDINGS entry.
- What: 3.14.
- *Done:*
  - **Measured first, into FINDINGS:** the battle and world-map ceilings at HEAD, guest alone
    (`SOA_UNCAP` in snapshot mode) and drawn every frame, as H3 measured them, with any comparison
    interleaved. If the battle drawn every frame holds 60 at p95, no skip is built; otherwise M11a-skip is
    specified from the numbers.
  - `python -m pytest tools/tests/test_picture.py`: `present_interval(hz, 60)` is 1, 1, 2 and 1 at 60,
    85, 120 and 144 Hz, and `(hz, 30)` still gives H19a's values. Mutation: `round(hz/60)` fails 144,
    and `round(hz/30)` fails 85.
  - One run, `python tools/scenario.py run battle --frames 13500 --env SOA_TURBO=battle
    --env "SOA_PEEK=0x803475C0@3600-13500,0x803475CC@3600-13500" --env SOA_WAV=build/turbo.wav
    --log build/scenario-m11a.log`, then `python tools/tests/test_turbo.py build/scenario-m11a.log`.
    Its `__main__` splits the peek lines by the scene word (`0x803475CC`), same frame. Over the
    scene-7 frames, the game frame counter (`0x803475C0`) advances 1 per retrace ±5%. Over the scene-6
    frames before the first 7, it advances 0.5 per retrace ±5%. Both use the retrace counts the peek
    lines carry. That is a same-run contrast. The battle returns to the field inside the run: a field
    load follows the last scene-7 frame. (At normal speed the deck fight starts at frame 9810 and the
    field loads come between 12,800 and 13,100, FINDINGS "P6, followed up"; the scenario's own 12,000
    frames end mid-battle, hence `--frames 13500`.) Its pytest feeds it a synthetic log with one rule
    broken (the checker's mutation).
  - **Audio rate, same run:** the new `[audio]` line (bytes over the wall time between the first and
    last block) reads 128,000 bytes a second ±3%, a tolerance fixed here. Mutation, the same command with
    `--env SOA_SPEED=2`: about 256,000, outside it.
  - The CH1 headless run now logs `[chord] frame 1900: view+rs -> turbo on`, then `[turbo] frame F: on`
    with F at the next safe point.
  - A windowed run at 60 Hz logs the presenter's interval changing 2 → 1 at the battle and 1 → 2 after.
    The other rates are the pytest's, because a check cannot change the display.
  - **Owner:** a few battles at turbo in a window feel right, and the music is at its normal pitch.
  - The contract holds with `SOA_TURBO` unset.

---

## 7. Open questions

**For the owner**
- **Q-O1. Where relative paths point (M5b).** `soa.ini` now lives in `gen\`, which is build output. I
  recommend that relative paths and the default card mean "inside the SOA folder" (the one holding
  `gen\` and `build\`), and that `soa.ini` may also sit there. Your card stays where it is today. Agree?
- **Q-O2. Rumble on by default?** The game has its own Vibration option; the port could leave its
  strength at 100 and let the game decide, or start at 0 until you turn it on.
- **Q-O3. Escape.** Today Escape quits the game immediately. In fullscreen, should Escape leave
  fullscreen instead? Should quitting ever need a confirmation?
- **Q-O4. Which handheld, and at what refresh rate?** (the plan's Q1). The research says your machine is
  a Ryzen Z1 Extreme: a ROG Ally or Ally X (7-inch, 1920×1080, 120 Hz) or a Legion Go (8.8-inch,
  2560×1600, 144 Hz) need different default sizes. At 144 Hz the game would take one refresh per image
  and pace unevenly until H9. H8's notes also say your display ran at 85 Hz; is that an external monitor?
- **Q-O5. The chord layout.** Proposed: View+LB fullscreen, View+RS turbo, View+LS reserved for the
  menu, LB held to skip text; on the keyboard F11 and Tab. Different buttons?
- **Q-O6. Auto-advance speed.** 1.5 seconds after a page finishes, as the `on` value? Should it also wait
  longer for longer pages?
- **Q-O7. Turbo.** Battles only, or battles and sailing? On from the settings file, or only by chord?
- **Q-O8. Picture options.** Which matter to you? The flash limiter and the sharp scaler are the
  handheld's; the CRT look and colour-blind modes can wait if unused.
- **Q-O9. Co-op.** Which party slot should a second player take by default, and do you want to test it
  online through Parsec?
- **Q-O10. Your own files and time for the checks.**
  - A Dolphin save to import (P3).
  - An hour with two pads (P10).
  - The device, for H19a, CH1, M18 and M11a.
  - A sleep and wake (M19).
  - A double-click start with your `soa.ini` (M5b).

**For the implementation session**
- **Q-I1. (Answered, b911380.)** P11's spike confirmed states 4 and 6 at `0x80346E64`.
- **Q-I2. (Answered, ../PLAN-NEXT.md C1: P11, then P11b after CH1.)** N6 as hold-to-skip too?
  Hold-to-skip needs host buttons (CH1); I suggest N6 ships auto-advance only (P11) and P11b follows CH1.
- **Q-I3. (Answered, b071949.)** `MOD_API` derives from `SOA_MOD_API_VERSION`, and the API-minimum test
  builds at 2.
- **Q-I4. (Answered, ../PLAN-NEXT.md C1.)** gxr.c is free now; P5b sits late in M1, and M11a-skip is
  built only if M11a's measurement asks for it.
- **Q-I5. (Partly answered, 2026-09-25.)** Before P1b, one short run with the test mode on. It answers
  four questions:
  - which card and walk keep the party in a rate-20 zone where the step counter counts, read from the
    logged zone and rate. **Partly answered** [V run, the implementation session]: `card-saved`'s spot
    in a101b reads zone 0 (the u16 at `0x8034740E`), and the step counter `0x80346D28` stayed 0 over
    1,700 frames of scripted walking, although the frames show Vyse walking. So the counter does not
    count there, and P1b needs another card and route in a rate-20 zone, for example the part-G card
    at `116a`, where M1 fought [I: its zone's rate is not read yet];
  - whether three `right#4` then A reach Run on the wheel;
  - whether escape override 100 always escapes;
  - whether holding B still lets moving frames accumulate.

  The last three are [I] until that run. P1a's live Done peeks only the multiplier byte, so it does
  not depend on this.
- **Q-I6.** P10b's spike. The command type is the s32 word at `0x80309174 + 32·m` [V static:
  `stwx` at `0x8007C7E0`]. Its values for Attack and after one left, and the wheel's opening slot and
  wrap, still need the peek at a phase-1→2 edge before P10b's live Done can be written down exactly.
- **Q-I7.** Counts: new self-test cases (P6, M5b, M18, M19) and new pytest modules change the counts
  quoted in PLAN.md, TESTING.md, HANDOFF.md, README.md, ARCHITECTURE.md and SKILL.md; fix every copy with
  the commit that moves them.
- **Q-I8. (Answered: P6 at 24d9235, P6b at 79c9ad8.)** P6 landed without the three additions 3.3 asks
  for:
  - the `[seed] pin:` line;
  - the 640- and 1024-byte buffers, with the "cut at" line;
  - `test_seed.py`'s `__main__` log check.

  They landed as P6b (79c9ad8), a follow-up before P1a. P6's self-test mutation already compares
  against pins for n = 0..3, never two clock reads, so it was not among them.

---

## Appendix: what in the plans is stale or wrong

1. **P11 (PLAN-GAMEPLAY-MODS.md:463-465):** `0x80346E60` is the draw's pointer, zeroed at `0x8010CCD4`
   each frame, not a place to find the window. Use `0x80346E4C` → +36 and the state at `0x80346E64`
   (confirmed in a run, b911380). The choice marker is context flag 0x10 / state 6; flag 0x1000 only
   blocks the instant reveal.
2. **P11's hold-to-skip** is specified as "a chord", but `pad_filter` sees only the twelve GameCube
   buttons; it needs CH1's host buttons (now.md N6 bundles it).
3. **P1's Done** expects the byte to read 50 at normal with nothing equipped; with "normal writes
   nothing" it reads the game's own `FF`. Its accessory case pokes the slot in the field, but only a load,
   Continue or an equipment change recomputes the byte (2.9), so the poke needs a warp after it. P1's
   contrast needs a zone the plan could not locate; log zone and rate in-run instead.
4. **P3's export warning** about op-138 maps cannot fire until M7a's save-now exists; move it there.
5. **T0's "full-column enemy tables" check** landed as a 64-row limit (1c7b780) and was dropped at 4041dfc
   as a guess. T5 writes the real one. The counts are fixed in every copy (43 and 18).
6. **M5 amendment** ("resolve every path against soa.ini's folder"): that folder is `gen\`; resolving
   the default card there would appear to lose the owner's saves.
7. **Rule 6 and E's milestone notes** say P1's preset and P6's seed stay out of the recording until
   milestone 2; the `# config` line can carry them now at almost no cost (P6 does, 24d9235).
8. **Section A's state line** (PLAN-GAMEPLAY-MODS.md:63-67) says H15c is under way. H13 is done enough,
   and H15d and H16 wait on the GPU decision (PLAN-60FPS-MODS.md:301, :357, :363, from cb469d6). H15c is
   done, with the sampler stage subsumed; that comes from the implementation session's reply of
   2026-09-25, not from the plan. **PLAN-60FPS-MODS.md:353 is itself stale:** it still says "The sampler
   is next".
9. **Milestone 1's table (section E)** omits M11, while section C picks turbo as a comfort item and the
   Android research's order puts M11 in step 5. This spec includes M11a (to 2×) and leaves M11b out.
10. **M11 in PLAN-60FPS-MODS.md:602** cites the skip at `gxr.c:1534`; it is in `gxr_draw_inner`
    (`gxr.c:2378` at b071949), and copies are not skipped. Its "The audio report is unchanged" (:607),
    like M2's (:479) and H9's (:270), compares two live runs.
11. **H19 (section F)** says "today the window is a fixed 1280×960": still true, but H8's swap chain
    now has to learn `ResizeBuffers`, and Alt+Enter would also press START (`window.c:410`).
12. **M19 (section F)** names the TIME_UTC clock. It misses two things:
    - the subtraction is unsigned (`hle.c:302`), so a backward step wraps rather than stalls;
    - `SOA_STALL=600:30` would trip the 20 s headless watchdog (`main.c:504`); use 10 s.
13. **`hle.c:164-171`** dropped a fifth report hook silently; P6 fixed it (24d9235).
14. **`mods/encounters-off`** sits in `mods/`, so any `soa.ini` pointing `mods` at that folder turns
    random battles off permanently, whatever else is chosen. P1a moves it.
15. **M11's presenter note** implies `round(hz/60)` under turbo. Today's rule (`window.c:316-326`) is
    "a whole multiple within 0.02, else 1", and it must stay that way for the owner's 85 Hz display.

---

## Review log

Two reviews of the first draft were checked against the repository on 2026-09-25. The tree moved
while they were checked. Beyond c8274db, which one reviewer cited, these had landed:
- 4041dfc, the T0 follow-up;
- b911380, P11's spike;
- b071949, MV2b.

P6 was uncommitted in the working tree. Where that changes a finding, the entry says so. The findings
are numbered in the order given, and both reviewers' copies of the same point share one entry.

**Applied**
1. *MV2 is not in flight; it landed* (high, both reviewers). Applied, and extended: the remainder the
   reviewer proposed as MV2b (one API constant, the "no `api = `" message, the `/DMOD_API=2` test) has
   also landed, at b071949. The MV2 slice is gone, 3.1 records what landed, the "encounters-off stays
   v1" bullet is deleted, the header is restated at b071949, and 1's now.md rows are updated (N1–N4
   landed, N5 in flight).
2. *T0 landed with a different design* (high, both reviewers). Applied in part. T0 is marked landed and
   its slice dropped, the stale-count grep is deleted, and 2.7 is rewritten. Since the review, 4041dfc
   brought the landed guard to this spec's design: 43 suffixes with `.gcs` and `.sav`; 18 directories
   with `load`, `dump` and `dumps`; the tree-wide signature check. It also dropped the 64-row rule. So
   the reviewer's "replace the enemy-table deferral with 'landed as the 64-row limit'" is rejected as
   overtaken: the limit no longer exists, and 4 and Appendix 5 say so. The suggestion to move `.gcs`,
   `.sav` and `load/` into P3 and P8 is rejected for the same reason.
3. *M11a's presenter rule changes normal play* (high, both reviewers). Applied: `present_interval(hz,
   fps)` keeps today's rule for both 30 and 60, with a pytest at 60, 85, 120 and 144 Hz (3.8, 3.14, H19a,
   M11a).
4. *Stale line numbers* (medium). Applied: re-cited at b071949. gxr.c is unchanged since c8274db, and
   its citations are `gxr_enabled` :213-226, `copy_filter` :2877, `enqueue_copy` :2921-3091, the call
   and `filtered` at :2938-2939, `gxr_draw_inner`'s skip at :2378, and the hash at :3086-3088. mod.c's
   are :309, :878-884, :910, :1003 and :1083, and the watchdog is `main.c:504`. gxr.c is cited by
   function as well.
5. *P10b's command type is a word, not a byte* (medium). Applied, re-verified with `tools/disasm.py
   0x8007C7C8 0x8007C7F0`: `stwx` at `0x8007C7E0`. It is tagged [V static], and Q-I6 is reframed.
6. *P3's slot mutation cannot fail* (medium). Applied. `verify()` checks only checksums and free counts
   (`cardformat.py:700-826`), so the Done now asserts which slot was written and that the other is
   unchanged.
7. *CH1 needs code from later slices* (medium, both reviewers). Applied as the reviewer's first option.
   main.c's chord handler has arms that log "(not built yet)" until H19a and M11a replace them, and
   each of those slices adds a Done line for its arm.
8. *The spike's pass rule is too strict* (medium). Rejected as overtaken: the spike ran at b911380 and
   passed under the original rule. The state rested at 4 for 2,913 frames, one A moved it through 5 and
   3, and the choice rested at 6. The reviewer's underlying point was that more pages follow a choice.
   That point caught a real defect in P11's Done: 《どうする？》 and the B/C choice follow みる, so one A
   at 6000 could never load `a002b`. The run now has a second A at 6900, `--frames 8000`, and a relative
   timing rule (b) instead of fixed frames.
9. *M5b hides the console on the process count alone* (medium). Applied: it also requires
   `GetFileType(stderr) == FILE_TYPE_CHAR`, as a pure function with a pytest. The Done adds a
   `CREATE_NEW_CONSOLE` launch with a piped stderr.
10. *P5a's byte-for-byte identity cannot hold* (medium, both reviewers). Applied: `SOA_PICTURE_SIZE=640x480`
    and `scaler=integer`, comparing decoded pixels, with a `gamma = 1.01` mutation.
11. *Report hooks: P6 is the fourth, not the fifth* (low). Applied, with the reason restated. P6 in
    flight already carries the 16-entry table and its line.
12. *Nine `test_gxr_*` modules; `render_check.py` is in `tools/citest`* (low). Applied (3.0).
13. *The state machine list is incomplete* (low). Applied, re-verified in the disassembly of
    `fn_8010D4F4` and `fn_8010D12C`: 0 initialises; 8 rests (`0x8010D818`–`0x8010D81C` store 8 back); 4 exits to 7, 5 or 8;
    the 0x40 countdown goes to 5.
14. *`flags & 0x50 == 0` and "default 45 … unset is off"* (low, both reviewers). Applied:
    `(flags & 0x50) == 0` everywhere, and unset/`0` is off, `on`/`1` is 45, N ≥ 2 is N frames (3.5, 3.15).
    P11's pytest has a precedence mutation.
15. *P1: 255, "the game's own byte", rounding* (low, both reviewers). Applied: 255 (−1) skips, re-verified
    at `0x800C2014`/`0x800C2040`. "If the computed effect-84 value is negative, write nothing". Truncating
    integer arithmetic, with the rereading mutation's trace written out.
16. *M18: not every stop path reaches `hle_report`* (low). Applied, re-verified (`threads.c`, six
    `exit(6)`). Those paths use `exit`, so M18 registers an `atexit` handler rather than adding a report
    to threads.c, and a crash is named as the one case left.
17. *`GEAE8P` at offset 0 misses card images* (low). Applied as T0c against the landed guard, which has
    the same gap. `.raw` is already refused by suffix, so only renames are at stake. The check looks at
    the directory entries of blocks 1 and 2 of a card-sized binary.
18. *127 entries cannot be reached on a 59-block card* (low, both reviewers). Applied: a 16 Mbit image
    (`--size 16`, 251 user blocks) for that one refusal. One reviewer suggested 32 Mbit; 16 is the
    smallest that holds 127 one-block files.
19. *The config line's buffers are sized for mods alone; M5b's absolute card path* (low, both
    reviewers). Applied. It is live in P6's in-flight edit (main.c's `extra[320]`). Buffers go to
    640/1024 with a "cut at" line and a padrec test, and the recording names the card relative to the
    root.
20. *P6's self-test mutation can flake* (low, and medium from the second reviewer). Applied, and the
    working tree's self-test case already does it: the `0x8000A1DC` value is compared against every
    site's pin for n = 0..3, never against a second clock read. "srand's twin" is replaced by the
    translated `fn_8025ECBC`.
21. *Appendix 8 cites the wrong source for "H15c done"* (low). Applied: it cites the implementation
    session's reply, and adds PLAN-60FPS-MODS.md:353's "The sampler is next" as stale.
22. *H19a compares two live runs; P1's hold-B has no trials* (low, and medium from the second reviewer).
    Applied. Each H19a run is checked against `picture_layout` for its own logged client size, and the
    runs are never compared. P1b's test mode has a fifth trial kind, `hold`.
23. *P1: hold B at `normal` never restores the byte* (high). Applied: a `dirty` flag and a one-time
    restore of the game's own value. P1a's Done has a live check and a mutation.
24. *DLL mods have no report mechanism* (high). Applied, the reviewer's option (a): mod.c counts each
    DLL's successful writes through `g_cur_mod` and adds `W write(s)` to its existing report line. There
    is no API change; 4 records option (b) as rejected for now.
25. *P1's accessory case needs a load* (medium). Applied, re-verified: `fn_801EF7E0` has 22 callers in
    gen, none per-frame. The case pokes the slot, warps to `ME101B.SCT`, and peeks after arrival, with
    the full command written out.
26. *P6's live check needs values the report does not carry* (medium). Applied: a `[seed] pin:` line
    per pin, checked by `test_seed.py`'s `__main__` against Python `fmix32`. The `SOA_WATCH` step is
    dropped.
27. *P1's statistics are under-specified* (medium). Applied:
    - battles per 1000 moving frames;
    - rate-20 trials only;
    - a `stuck` rule;
    - minimum counts for k = 0 and hold;
    - the false-failure figure (about 0.2%);
    - the flee automation tagged [I] and added to Q-I5.
28. *P1 is not "a day"* (medium). Applied: split into P1a (a day) and P1b (a day to several days).
29. *Prerequisites are incomplete* (medium). Applied per slice, and stated once in 3.0.
30. *CH1's host bits have no home* (medium). Applied: `PadEvent.host` for the script, a new
    `window_host()` with its stub, and the merge on the first read of each frame. `si_host_buttons()`
    exports the result.
31. *P11b's live Done passes with a do-nothing LB* (medium). Applied: a logged state-3 press and a
    fast-advance timing rule, with a mutation.
32. *P10b rests on unverified readings, and its handover needs a frame from a run* (medium). Applied.
    The readings join the spike and are tagged [I] until then. The handover check is the fake-guest
    pytest, with a same-run invariant in the live run.
33. *M11a's run has placeholders* (medium). Applied: one wide peek of the frame counter and the scene
    word over 3600–12000, split by scene, measured per retrace.
34. *Nothing builds the DLL mods, and they need `mods` set* (medium). Applied: `--link` builds
    `mods/*/mod.c` (P1a), M5b defaults `mods` when a mod-backed key is set, and section 1 tells the owner.
35. *M19 has no check that ordinary runs never trip the gap rule* (low). Applied: zero gap lines in
    `title` and `battle`, and a logged origin offset that makes the mutation's rule 0.5 s.
36. *`unfocused = mute` is unchecked* (low). Applied: a self-test case and an owner check.
37. *The move of `mods/encounters-off` misses copies* (low). Applied, listed at b071949's line numbers,
    with the grep that finds them.
38. *P10a could change the game's controller count* (low). Applied: `g_present` stays `{1,0,0,0}`, with
    a padrec case and a mutation.
39. *The colour-blind matrices name no source* (low). Applied: Machado, Oliveira and Fernandes 2009
    (severity 1.0) from the authors' page, the daltonize correction, and linear RGB, marked [I].
40. *P11's `--frames 6800` is too tight* (low). Applied, and extended to 8000 frames and a peek to 7900
    for the second A (entry 8). (d) names how the load's frame is found.
41. *M18, M19 and M5b lack the Owner mark* (low). Applied, and CH1 has one too. Q-O10 lists M19, M5b and
    CH1.

**Rejected**
- **Entry 2, in part:** "landed as the 64-row limit" and "move `.gcs`, `.sav` and `load/` to P3 and P8".
  Both were overtaken by 4041dfc.
- **Entry 8, the spike's pass rule itself:** overtaken by b911380, which passed under the original rule.
- **Entry 16, adding `hle_report()` to threads.c:** replaced by an `atexit` handler. Those exits skip the
  report on purpose, and only the motor needs stopping.
- **The second reviewer's `/DMOD_API=2` MV2b slice:** not rejected on the merits. It landed at b071949
  before this revision, so no slice is needed.

**Consistency review, 2026-09-25, at 012164a.** A check across the five planning documents and against
the repository, with the implementation session's facts from after the drafts and the commits that
landed while it ran (C5a 750cef0, P6b 79c9ad8, b1199b3, T0c 012164a):
- P6 landed as 24d9235 without 3.3's three additions. P6 is recorded as landed, with its run's figures
  (FINDINGS "P6"), and the additions became a slice of their own, **P6b**, which then landed as
  79c9ad8. P6's self-test mutation already compared against pins, so it was not an addition.
- **P6b's reload after the battle.** The implementation session's first report (P6's run to 12,000:
  both field loads before the deck fight, none after) led this review to drop the post-battle reload
  from P6b's live check. 79c9ad8 then ran the scenario to 13,500 and found the field loads after the
  fight, at 12,800–13,100, and its checker requires one. P6b's Done is recorded as landed, with that
  check, and M11a's run keeps its return-to-the-field line with `--frames 13500`.
- T0c landed as 012164a, wider than 3.2 specified (any length, more signatures, every suffix, history
  by content); 2.7, 3.2 and the slice say what landed. b1199b3's id-keyed recording tail is in 2.1.
- P1's addresses are tagged [V run] from `build/p1-addr.log`, whose card is byte-identical to
  `card-saved` (3.4).
- Q-I5 is partly answered: `card-saved`'s a101b spot is zone 0 and the step counter did not count
  there, so P1b's prerequisite is now a card and walk in a rate-20 zone. P1a's live Done does not
  depend on the zone.
- P11's first box is named, 《どうせみないでしょ？》, as FINDINGS "P11's spike" shows it; its Done
  already matched FINDINGS' sequence after みる.
- The live Done lines of P1a, P11, P11b, P10b, H19a and M11a now name the command that checks the log
  (`test_mods.py`, `test_picture.py`, and a new `test_turbo.py`).
- M5b's port root also covers `gen\clang\` and `gen/linux/` builds (portability.md 3.9), with a test.
- `--link` builds the mods with the msvc profile only (portability.md L3a).
- Q-I2, Q-I4 and Q-I8 are marked answered; the encounters-off copies are re-cited at 012164a
  (README.md:202).
