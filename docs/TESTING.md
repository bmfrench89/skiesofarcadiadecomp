# Testing — how to check this thing works

Nothing here needs you to read the rest of the documentation. The sections go
cheapest first, and each one ends with what it does *not* cover, so you can
stop as soon as you have the answer you came for.

Every command below was run on the machine this was written on and the output
is quoted from that run, with one exception that says so where it occurs:
section 2's build transcript, whose line shapes come from
`tools/recompile.py` itself and whose counts come from the tree. That machine:
Windows 11, 16 logical CPUs, Python 3.14.0, VS 2022 Build Tools (MSVC
14.44.35207), the Metrowerks compilers in `vendor/`, and an extracted disc in
`extracted/`. Timings will differ; orders of magnitude should not.

| Question | Section | Wall time here |
|---|---|---|
| Did I break the tooling? | [1. No disc needed](#1-the-checks-that-need-no-disc) | 1 min |
| Does it build? | [2. The build](#2-the-build) | minutes |
| Is the runtime still sane? | [3. The self test](#3-the-self-test-75-cases) | 0.1 s |
| Does the game still run? | [4. The scenarios](#4-the-scenario-library) | 71 s to 26 min |
| Does it still draw the same pixels? | [5. The frame hashes](#5-the-frame-hash-corpus) | 18 s |
| Do the decompiled units still match? | [6. The match check](#6-the-decompilation-check) | 4 s |
| What can CI do for me? | [7. What needs what](#7-what-needs-what) | — |
| I am about to push | [8. Before you push](#8-before-you-push) | ~1 min |

---

## 1. The checks that need no disc

These are the whole of what CI can run, and between them they take about a
minute. Nothing here reads `extracted/`; every fixture is synthesised in
memory.

### `python -m pytest tools/tests -q`

```
957 passed in 176.01s
```

957 tests in 52 files, none of which reads the disc. They cover the Python
that builds the port and, through the tests that compile one `runtime/*.c` on
its own and run it, some of the C as well:

| File | Tests | What a failure means |
|---|---|---|
| `test_mods.py` | 98 | `runtime/mod.c`'s data patches, built alone against a fake DOL: every refusal (address spelling, hardware window, outside RAM, alignment, the DOL's code, values, triggers, conditions, `mod.ini` keys, the API and the DOL's SHA-1) refuses the whole mod with its file and line; manifest 2's id and version name a mod in the recording -- past the line's end too, by id and not folder -- a bad or duplicate id refuses it, an `x_` key is passed over; `every_frame`, `once` and `on_map_load` apply when they say; a `mod.dll` built here loads on `SoaModApi`, whose memory calls refuse what a patch would, its callbacks fire where they say, a DLL that refuses itself takes its callbacks with it, and the example in `examples/mods` builds and loads; `call_guest` runs at a safe point with every register put back and is refused anywhere else; and the shipped `mods/encounter-rate`, built with `--link`'s line: nothing written unset, each preset's byte from the base the game works out (no accessory, 210, 211 on a later character), only in the field, hold-B's zeros and its one restore of the game's value, hold-B off leaving the controller alone, an unknown preset refused, and the spec's two mutations (halving the byte read back, no restore) failing |
| `test_scenario.py` | 91 | the scenario files, the pad grammar and the invariant checker, against report lines copied from the `fprintf`s that produce them |
| `test_cardformat.py` | 77 | the memory-card formatter: does the image it writes say what the mount reads? |
| `test_guard.py` | 76 | the game-data guard: its suffix and size limits against CI's copy, CI's grep refusing the same names as the guard, a suffix anywhere in a name (`slotA.raw.bak`), the tree check on names git would quote, and `--history` -- a file deleted later, a file renamed through a forbidden name, an exemption keyed by content, and the content check over deleted blobs; and T0: what mods, packs and saves would carry, the pack, load, dump, blob, photo and out folders, a binary file that begins as game data whatever it is named (a card image by its directory, an untagged MP3 by its first frame), and in a mod folder a file that is not text, NULs included |
| `test_cfg.py` | 40 | control-flow recovery over synthetic DOLs: function boundaries and switch tables |
| `test_soak.py` | 40 | `tools/soak.py`: the generated play repeats by seed and fits `si.c`; `check` turns a soak log into pass, FAIL or "did not test what it says" and each injected fault fails through its own check; the warp and the encounter accelerator never poke the forced-battle flag, and a field that comes back black after a battle is a question |
| `test_decode.py` | 32 | the Gekko decoder, on encodings hand-derived from the 750CL manual |
| `test_emit.py` | 22 | the emitter; the last cases compile the emitted C with MSVC and run it |
| `test_gxr_overlap.py` | 21 | the ordering around EFB copies (H14): with `SOA_GXR_STALL` holding one worker back before its draws, copies or clears, every thread count leaves the copied memory, screen, EFB, decoded textures and what the CPU reads after `GXDrawDone` that the one-worker run leaves, over frames that differ; the copies were fenced and not drained, each producer read (texture, palette, vertex array) waited for its own copy, the frame gate drained once a frame, and `SOA_GXR_DRAIN=1` and `SOA_GXR_TOKENWAIT=1` hold too. Nine deliberate breakages of the fences, waits and gate each turn it red. Copy images: a draw sampling a copy's own texture takes the image the workers decoded, held to the drains' decode from memory, through an overwritten image, an unfiltered copy, a drain then a CPU write, a hook's write and a token between copy and draw, with the producer's image counts pinned per protocol; seven more breakages each turn it red |
| `test_dump.py` | 20 | whether the tree notices a dump that is not the build `config/` describes |
| `test_crossval_capstone.py` | 19 | our decoder against capstone's PowerPC backend — **needs `capstone`, which CI does not install** |
| `test_profile.py` | 19 | `tools/profile.py` against the report the port prints, and the wording of those lines as an interface to `runtime/` |
| `test_padrec.py` | 19 | recording controller input and replaying it byte for byte, and the `SOA_PAD` items `si.c` refuses rather than pressing nothing; 600 bytes of recorded settings and mods reach the `# config` line whole, and 800 are cut with a line that says so |
| `test_midpoint.py` | 18 | `tools/midpoint.py` on canned output: the `[pair]` and hash lines parse, each of the seven verdicts fails when its one thing breaks, a mutation that costs no pair is not a pass, and a capture that drifted from the manifest is refused before anything runs |
| `test_fifopair.py` | 17 | the H4 pair analyser, on captures built byte by byte: an identical pair matches all its area, a changed texture unmatches its draw, a moved draw lands in the displacement histogram, list and direct draws are counted apart, and the area estimate clips and culls as the renderer does |
| `test_disasm.py` | 17 | `tools/disasm.py`'s address notes: an update form moves its base, `ori` reads rD and writes rA, and rA=0 is the number zero |
| `test_uncap.py` | 17 | `SOA_UNCAP=N` and `SOA_FRAMETIME_FROM=N` are read at startup and refuse a value that is not a frame; the `[frametime]` percentiles tell a hitch from a steady run, and an uncap restarts the record at its frame |
| `test_poke.py` | 16 | SOA_POKE: a malformed switch is refused out loud rather than driving a run that looks like it ignored you |
| `test_decomp.py` | 15 | the `dc_*` rename scanner, on declarations that look like functions and are not; and the one `units.txt` reader, which refuses a row it cannot read |
| `test_bindings.py` | 15 | the binding lists (`hle.txt`, `hooks.txt`, `savepoints.txt`, `trace.txt`): a line that is not an entry, or a repeated address, is an error naming its file and line |
| `test_gxr_pair.py` | 15 | H10's in-between image, on the renderer built alone: synthetic frames captured through the real capture path and replayed as pairs. A triangle moved by 2d lands at d pixel for pixel; perspective and depth motion give the view-space midpoint; t=0 and t=1 give the two frames; an unmatched draw comes from F+1; copies to texture are skipped with their clears kept; equal keys pair in stream order; the pairs written are fifopair's; and `gxr_flush` never touches the pair state |
| `test_seed.py` | 15 | `runtime/seed.c`, built alone: the race seed's values are MurmurHash3's finaliser over the seed, the site and the site's call count (against an independent Python one), exactly the three OSGetTick sites are pinned, each counts its own calls, a seed that is not 32 bits is refused and the seed in effect is handed back in decimal; each pin prints its line, and the module's own log check (`python tools/tests/test_seed.py <log>`) fails an edited value, a missing pin, a wrong count, a wrong seed and a run that never left a battle; and each site is in the translated code once, followed by srand |
| `test_aklz.py` | 14 | the AKLZ container decoder, on hand-built streams |
| `test_formats.py` | 14 | the disc's format parsers, on synthesised fixtures |
| `test_gxr_tripwires.py` | 14 | each unmodelled renderer feature warns exactly once, and what the game really programs stays silent |
| `test_matchcheck_relocs.py` | 14 | what a relocated word is allowed to hide — every case is a thing the old oracle called a MATCH |
| `test_peek.py` | 14 | `SOA_PEEK` refuses a malformed item out loud and keeps its own list; a watch aimed with `SOA_WATCH_FROM` prints only from that frame, and every watch line carries its frame (against the real `trace.c`) |
| `test_regs.py` | 12 | which GPR an instruction actually writes |
| `test_fifo_verts.py` | 11 | vertex-attribute dumping, on streams built byte by byte |
| `test_profiler.py` | 11 | the sampler in `runtime/main.c`, built and run with no game and no disc |
| `test_toolchain_inputs.py` | 11 | what a fresh checkout can check and with which compiler; every `src/**/*.c` is in `units.txt` |
| `test_settings.py` | 11 | `runtime/settings.c`, built alone: each `soa.ini` key sets its switch and `disc` names the directory, the environment wins and says so, an unknown key is named with its line, `SOA_SETTINGS=0` turns the file off, every scripted check sets it, and a setting that changes the game is recorded only when set -- as its owner says it is in effect, never half a value when the line is full; a setting a mod reads says it does nothing without that mod and is then not recorded, and one of a fixed set of values is recorded only as one of them |
| `test_gxr_copy_filter.py` | 9 | what the EFB copy's vertical filter does to a pixel, including that the SDK's filter-off weights are the exact identity |
| `test_matchcheck.py` | 9 | how an object's symbol is matched to a function in the executable |
| `test_symbols.py` | 9 | the symbol database |
| `test_decomp_native.py` | 8 | what it takes for a unit to run natively, checked by building it |
| `test_card.py` | 7 | the parts of Track B that are text: `exi.c`, `selftest.c`, `irq.c`, `names.txt` and the README agreeing |
| `test_gxr_texcache.py` | 7 | the texture cache (H12), with `gxr_tev.c` included whole to reach its statics: the index stays whole through 30,000 lookups over three times its keys, the least recently used texture goes first, a texture is hashed once an epoch and again after BP 0x66 or a copy moves it, `SOA_TEXVERIFY` catches a rewrite inside one, a dropped decode is rebuilt in place, and a palette load keeps a decode whose palette came back the same and makes it again when it did not |
| `test_ax_census.py` | 6 | the audio census lines a run prints, and the invariants between them |
| `test_gxr_queue.py` | 6 | the handshake between `gxr_flush` and the rasterizer threads |
| `test_tick.py` | 6 | `runtime/tick.c`'s native `VIGetRetraceCount`, built alone: the original everywhere but the main loop's two call sites; the top of the loop runs the safe-point callbacks in order, and the frame end's spin answers start + 1 from the unlock frame on |
| `test_gxr_lifetimes.py` | 6 | the lifetime rules the renderer's queue lives by — the texture use-after-free of 2026-09-17 — under H14's fences and again under `SOA_GXR_DRAIN=1`, where a draw's setup still drains for a queued copy |
| `test_citest.py` | 5 | the CI scripts' own claims: nothing fell out of coverage, the render driver has not drifted from `selftest.c`, the import graph is stdlib-only |
| `test_sct.py` | 5 | `tools/sct.py`, the field-script disassembler, on bytecode built word by word: a flag test, a backward jump, a warp name, a switch, and an entry that runs off its end |
| `test_inventory.py` | 5 | regenerating the inventory leaves both symbol files saying the same thing |
| `test_dspadpcm.py` | 4 | DSP-ADPCM decoding against hand-computed frames |
| `test_hle_pc.py` | 4 | every native adapter says which guest function it is, so the profile does not charge it to its caller |
| `test_memguard.py` | 4 | the bound on the guest memory image |
| `test_rvz_junk.py` | 4 | the junk generator behind RVZ junk runs |
| `test_perfbench.py` | 3 | the renderer benchmark: its figure is busy thread-time over every fragment processed, and a capture that drifted from the pinned manifest is caught |
| `test_gxr_fastpath.py` | 3 | the pixel path's specialised cases (H15c) against the general path: 4,000 random register sets through the real `tev_prepare`, near misses included, 64 random pixels each through both TEV paths, and 400,000 random blends through both blend cases -- colour and alpha test identical |
| `test_gxr_alpha.py` | 2 | the early depth test's premise (H15a): whether a draw's alpha compare passes every alpha, on sixteen combinations worked out by hand -- the XOR of two always-true compares among them -- and the answer's cache between draws |

Anything that needs a C compiler or an optional package skips itself rather
than failing, so the number you see depends on what is installed. Measured on
this machine by hiding one at a time:

| Installed | Result |
|---|---|
| everything (MSVC + capstone) | `957 passed` |
| no capstone — **what CI installs** | `938 passed, 1 skipped` |
| no MSVC | `670 passed, 287 skipped` |
| neither — **the Ubuntu CI leg** | `651 passed, 288 skipped` |

Two things follow. The 69 MSVC-gated tests are the ones that build a runtime
file and run it — the renderer's queue and lifetimes, the tripwires, the memory
guard, the pad recorder, the profiler, the native-twin build — so on Linux the
Python is checked and the C is not. And CI's install line is `pytest` and
`ruff` only, **not** `pip install -e .[dev]`, so `capstone` is absent and the 19
cross-validation tests skip in CI on both legs: our decoder is checked against
an independent disassembler only on a developer machine.

One test — `test_image_every_word_agrees` in `test_crossval_capstone.py` — also
skips without `extracted/sys/main.dol`. It is the only test in the tree that
wants the disc.

### `python -m ruff check tools` and `python -m ruff format --check tools`

```
All checks passed!
```
```
70 files already formatted
```

Two separate commands. **Run both.** The format check has broken CI twice, and
it is the one people forget, because `ruff check` passing feels like it covered
formatting. It did not. A failure looks like this — the tool prints the diff it
would apply and exits 1:

```
unformatted: File would be reformatted
   --> tools\soa\dump.py:162:8
    |
161 | def describe_disc(root: Path) -> str:
    -     """"GEAE8P rev 0" from the extracted disc header, or "" if it is not
162 +     """ "GEAE8P rev 0" from the extracted disc header, or "" if it is not
...
1 file would be reformatted, 65 files already formatted
```

`python -m ruff format tools` fixes it. CI pins `ruff==0.16.7`; a different
local version can disagree about a line nobody touched.

### `python tools/guard.py`

```
guard: 161 tracked files, no game data
```

Refuses game data in the tree: 43 forbidden extensions, wherever they sit in a
name (`.rvz`, `.iso`, `.dol`, `.tpl`, `.dsp`, `.bin`, `.map`, `.gci`, … — so
`slotA.raw.bak` too; `.bin` is deliberate, the only `.bin` files
in this project's world are `boot.bin`, `bi2.bin` and `fst.bin`), eighteen
directory names that must never be tracked (`extracted/`, `gen/`, `build/`,
`vendor/`, `scratch/`, `packs/`, `photos/`, …), any tracked file over 2 MiB, a binary
file that begins as game data (AKLZ, GVR, a `.gci` or disc header, a GCS or SAV
card save, PNG, DDS, Ogg, FLAC, MP3 with or without a tag, WAV, or a memory card
image whose directory holds this game's save) whatever it is named, and, in a
folder holding a `mod.ini`, any file that is not text (T0: a mod here is its
edits, never the game's data). A capture's `.fifo` and `.regs` have no header,
so renamed they pass: only their names keep them out. It lists `git
ls-files`, so it sees what would actually be committed rather than what is
lying around. CI runs the same script, then scans **every blob in the whole
history** for the same suffixes, because a file deleted in a later commit is
still in the pack, and `guard.py --history` applies the directory names and
the content check to every path and blob any commit added — in a folder that
held a `mod.ini` at any point, the text rule too.

### The three MSVC checks — no disc, no `gen/`

```
python tools/citest/compile_runtime.py
python tools/citest/dc_check.py
python tools/citest/render_check.py
```

**`compile_runtime.py`** — 3.2 s:

```
ok   aram.c
...
ok   window.c

compiled 26/26 runtime translation units
not compiled here: nothing, every runtime/*.c is covered
```

Each file compiled on its own with `/c` and the flags in
`tools/soa/toolchain.py`, plus nine warnings promoted to errors. Nothing links,
so C4013 — implicit declaration — is first among them: it is the only sign that
a rename left a caller behind. Three C4996 deprecation warnings (`getenv`,
`fopen`) print and are not errors. If a runtime file ever genuinely needs
generated code, it goes in the `UNCOVERED` table at the top of that script with
a reason and the job's log names it; the table is empty today, and
`test_citest.py` holds it that way.

**`dc_check.py`** — 2.8 s. Byte-matching a decompiled routine says nothing
about how it is *called*. This builds the units `units.txt` marks `native` with
the `/Ddc_*` renames `recompile.py` derives, links them to a driver, and
compares each routine with the host C library over 3,000 generated cases:

```
decompiled MSL routines vs the host C library, 3000 cases each
ok   strlen      3000 cases
ok   strchr      3000 cases
ok   memchr      3000 cases
ok   __memrchr   3000 cases
ok   strncmp     3000 cases
ok   strcat      3000 cases
ok   strncpy     3000 cases
ok   memcpy      3000 cases
ok   memset      3000 cases

all 9 routines agree with the host C library
```

One gap worth knowing: `memset` here is the wrapper only. Its fill is
`__fill_mem`, which `runtime/decomp_shims.c` answers with the host `memset`, so
the decompiled fill is checked by `tools/decomp.py` (it matches) and by the
in-port self test, not here.

**`render_check.py`** — 3.4 s. The only check in this section that looks at a
pixel; everything above it would pass for a renderer that drew nothing. It
links `gx.c`, `gxr.c`, `gxr_tev.c`, `png.c` and a driver with two stubs, and
runs the same two checks the in-port self test runs:

```
[gxr] rasterizing on 1 worker thread
[selftest] render full-screen quad      ok    got "307200 of 307200 red"
[selftest] render triangle rows         ok    got "complete, 53301 px"
[render] second frame hash 63a57c77609efd77 (not asserted)
[render] both render checks pass
```

The register recipe in the driver is a verbatim copy of `selftest.c`'s, because
that one is `static` in a file that cannot link outside the port;
`tools/tests/test_citest.py` compares the two texts so the copy cannot drift.
The frame hash is printed and *not* asserted: `ceilf`/`floorf` at a span
boundary is where two MSVC versions could legitimately differ, and nobody has
run two.

### One check on the built binary that still needs no disc

```
$env:SOA_MEMPOKE='0x81800000'
gen\soa.exe nodisc
```

```
[mem] a store from block 00000000 reached 81800000, past the console's 24 MB of RAM; the port keeps zeroed scratch up there so that it does not reach the host heap. An address up there means the port is not modelling something. Reported once.
  backtrace from r1:
[mem] SOA_MEMPOKE: 81800000 <- DEADBEEF, reads back DEADBEEF
```

That is the MEM1 out-of-range tripwire firing on purpose, before anything opens
the disc. It proves the `PAGE_NOACCESS` reservation and the vectored exception
handler are both in place in this binary. The run then exits 1 with

```
cannot open nodisc/sys/main.dol
cannot open nodisc/sys/boot.bin
cannot open nodisc/sys/fst.bin
[boot] nodisc does not look like an extracted disc (sys/main.dol, sys/boot.bin and sys/fst.bin live there); run: python tools/extract.py <your disc dump> --iso
```

which is expected: `nodisc` is not a disc.

### What section 1 does not cover

Linking `soa.exe`, anything under `gen/`, the device models, the guest half of
`runtime/selftest.c`, the mwcc byte-for-byte match, the replay corpus, and
every frame the game itself draws. A green run here means the C compiles, nine
MSL routines behave like libc, and the rasterizer still fills a triangle. It
says nothing about the game running.

---

## 2. The build

```
python tools/recompile.py --compile --link
```

Needs the extracted disc (it reads `extracted/sys/main.dol`) and MSVC. After
changing anything under `runtime/` only, `--link` on its own is enough. Add
`--optimize` for a build that runs the game at full speed; the default `/Od`
build is for checking that the translated C is well-formed.

A successful run prints seven lines, in this order — the shape is
`tools/recompile.py`'s and the counts are this project's, with only the elapsed
times left as `<t>`:

```
7,144 functions, <n> switch tables (<t>s)
20 functions bound to HLE, 1 runtime hooks, 1 savepoints
emitted 7,144 functions into 18 files, 55.7 MB of C (<t>s)

instruction coverage: 100.000%  (696,171 translated, 0 not)

compiling 19 translation units with MSVC (/Od) ...
compiled 19/19 units in <t>s
linked gen\soa.exe (<t>s)
```

Every count there is checkable without building: 7,144 functions and 696,171
instructions are [ROADMAP.md](ROADMAP.md) slice 3.6's; `config/hle.txt`,
`hooks.txt` and `savepoints.txt` hold 19, 1 and 1 entries; and a built `gen/`
in this checkout holds 18 `chunk_*.c` totalling 55.7 MB, which with
`dispatch.c` is the 19 translation units.

The three lines worth reading every time:

- **`instruction coverage: 100.000%`** with `0 not`. Anything less prints an
  `unsupported, by mnemonic:` table underneath it naming what was dropped, and
  the port will run past those instructions doing nothing.
- **`compiled 19/19 units`**. A `FAIL chunk_0NN.c: ...` line above it is emitted
  C that does not compile.
- **`linked gen\soa.exe`**. Without it there is no binary, and sections 3, 4
  and 5 all need one.

Recorded timings (ROADMAP 3.6, 16 cores): the `/Od` validation compile is 3 s;
the `--optimize` release compile of the translated code is 103 s. The link is
where `runtime/*.c` and the natively compiled `src/` twins are built, so a
runtime-only change costs the link and nothing else.

If MSVC cannot be found, every step says so on stderr — `MSVC not found;
skipping compile` — and returns 1 rather than pretending it did the work.
`tools/soa/toolchain.py` finds it through `vswhere` and runs `vcvars64.bat`, so
`cl.exe` does not need to be on `PATH`.

---

## 3. The self test (79 cases)

```
$env:SOA_SELFTEST='1'
gen\soa.exe extracted
```

**0.11 s.** This is the cheapest real check in the project and the one to run
after every `--link`. It calls the recompiled library functions, the device
models, the AX mixer and the software renderer directly, outside the game's
control flow, so a wrong answer is a bug with a two-line repro. The last line
is the verdict:

```
[selftest] 0 failure(s)
```

Every case prints `ok` or `FAIL`, what it got and — on failure — what it
wanted. A failure exits **7**. It does not need a window, a sound device or a
card, but it does need the disc: `main.c` loads the DOL before it runs
anything, because the checks `dispatch()` into recompiled code by address.
Without one you get the boot message and exit 1, not a self-test result:

```
> $env:SOA_SELFTEST='1'; gen\soa.exe nodisc
cannot open nodisc/sys/main.dol
cannot open nodisc/sys/boot.bin
cannot open nodisc/sys/fst.bin
[boot] nodisc does not look like an extracted disc (sys/main.dol, sys/boot.bin and sys/fst.bin live there); run: python tools/extract.py <your disc dump> --iso
```

That is the reason none of section 3 runs in CI.

The 79 cases, in the order they print:

| # | Group | Cases |
|---|---|---|
| 1–26 | The memory card, through the EXI registers | 26 |
| 27–35 | The MSL C library, through the recompiled code | 9 |
| 36–37 | ARAM DMA, both directions | 2 |
| 38–70 | The AX mixer | 33 |
| 71–72 | The software renderer, through the real GX pipe | 2 |
| 73 | Decompiled against recompiled | 1 |
| 74 | `VIGetRetraceCount`, native against its twin | 1 |
| 75 | The data-cache range calls, native against their twins | 1 |
| 76 | Paired-single loads and stores against the general formula | 1 |
| 77 | The race seed at OSGetTick | 1 |
| 78 | The encounter multiplier as the game works it out | 1 |
| 79 | A mod's call into the game: every register as it was | 1 |

### The memory card (26)

Every command the CARD library sends, driven the way the library drives it:

```
[selftest] card image starts absent     ok    got "gone"
[selftest] card device ID               ok    got "00000004"
[selftest] card read status             ok    got "41"
[selftest] card program and read back   ok    got "512 bytes match"
[selftest] read latency on the DMA path ok    got "four dummy bytes, then the array"
[selftest] SRAM flash ID from image     ok    got "112233445566778899AABBCC"
[selftest] SRAM flash ID checksum       ok    got "D1"
[selftest] SRAM checksum and flags      ok    got "0004 FFF8 04"
[selftest] SRAM write and read at offset ok    got "5A 11223344 in place"
[selftest] SRAM DMA both ways           ok    got "32 bytes in and back"
[selftest] program raises the interrupt ok    got "csr 1 pending 1"
[selftest] masked interrupt waits       ok    got "csr 1 pending 0"
[selftest] masked, nothing delivered    ok    got "0"
[selftest] delivered to interrupt 9     ok    got "9:1 12:0 15:0 csr 0"
[selftest] cleared, nothing delivered   ok    got "0"
[selftest] handler reads status         ok    got "41 midway 0"
[selftest] handler leaves it quiet      ok    got "csr 0 pending 0"
[selftest] programmed page reads back   ok    got "one page in an erased sector"
[selftest] erase raises the interrupt   ok    got "pending 1"
[selftest] erase handler sees a clear bit ok    got "midway 0"
[selftest] sector erase                 ok    got "sector blank, ID block intact"
[selftest] consecutive page programs    ok    got "four pages, four interrupts"
[selftest] disabled card stays quiet    ok    got "csr 0 pending 0"
[selftest] card image flushed to disk   ok    got "524288 bytes, 97BF"
[selftest] reloaded from disk           ok    got "ID block 1122..BBCC D1"
[selftest] card counters                ok    got "3100 read, 1280 written, 6 interrupts"
```

The command set is device ID (0x00), read status, set interrupt (0x81), clear
status, sector erase (0xF1), page program (0xF2), read array, and the read
latency on the DMA path — plus the interrupt each write ends with and the two
SRAM checksums the mount recomputes. It runs first and on an image of its own
(`build/cards/selftest.raw`), which it deletes and rebuilds each run: the flash
ID the runtime presents in SRAM is recovered from the card image the first time
anything reads SRAM, so the image has to be shaped before that happens.

Two things that look like flakiness and are not:

- **The two hex digits in `card image flushed to disk` change every run.** The
  format time seeds the scrambled serial, so every byte of the ID block
  downstream of it differs run to run — `001C`, `6CA8` and `97BF` on three
  consecutive runs here. The expectation is computed from the block this run
  wrote, not blessed. That is the point: a check that read back what a previous
  run left behind would pass while proving nothing.
- **`card image starts absent` failing** means the last run's image could not be
  deleted (a stale handle, a read-only file). Everything after it would pass
  against old bytes, so it fails there instead.

Reverting any one of the three EXI mount fixes fails a check that names it —
measured, one revert at a time. So does deleting `irq.c`'s EXI delivery block
or renumbering it: the interrupt checks install the guest's own
`EXIIntrruptHandler` in the slot `deliver_pending` reads and count what arrives
there, rather than reading back the predicate under test.

### The C library and ARAM (11)

`sprintf` four ways (strings, integer conversions and widths, more than four
arguments, and floats through the FPU with the CR bit-6 varargs convention),
then `strcpy`+`strcat`, `strlen`, `strcmp`, `memset` and an unaligned `memcpy`,
all executed as recompiled PowerPC. Then ARAM DMA in both directions, driven
through the AI registers the way `ARStartDMA` drives them — the direction has to
survive the read-back-and-merge the SDK does in the middle.

### The AX mixer (33)

The ADPCM arithmetic (scale, shift flooring, predictor, coefficient pairs,
clamping), one-shot and looped playback with the state a loop restores, pan and
word order, the Q15 envelope, bus width and clamping, gain ramps, rate
consumption, both auxiliary buses in both directions including the mode this
game never selects, and the command-list walker's limits (the end command, the
64-command cap, a self-linked block, the chain guard). Every expectation is
derived from the sample format's own arithmetic rather than blessed from what
the mixer produces — which matters, because this project has already pinned a
bug in place by blessing output once. The first run of these found a real
defect: the resampler formed `(next - prev) * fraction` in `int`, wrapping a
silent sample to full-scale negative.

### The renderer's pixel checks (2)

```
[selftest] render full-screen quad      ok    got "307200 of 307200 red"
[selftest] render triangle rows         ok    got "complete, 53301 px"
```

Both go through the real GX pipe — bytes written to the gather pipe, parsed by
the front end, rasterized — using the register recipe the game uses for its
full-screen fades, so they pin down the command encodings as well as the
rasterizer.

1. **The full-screen quad** must cover *every* pixel: 307,200 of 640×480, exact.
   Off by one pixel and it fails.
2. **The title screen's cloud triangle**, at the real coordinates
   (320.5, −22.1), (789.1, −22.1), (789.1, 530.2). Its top edge is off
   horizontal by a sub-pixel amount, as the perspective divide leaves it; the
   span code once divided by that crumb, overflowed the int conversion and
   dropped whole rows. The check is a count *and* six probe pixels: three that
   must be green (600,300), (630,10), (500,100) and three that must not be
   (360,60), (600,340), (100,200), so a triangle that filled its bounding box
   fails as loudly as one full of holes.

These two also run in CI through `render_check.py` (section 1), which is the
only pixel CI ever looks at.

### Decompiled against recompiled (1)

```
[selftest] decompiled vs recompiled     ok    got "12 functions agree over 200 rounds"
```

The twelve functions that `config/hle.txt` swaps in — `strlen`, `strchr`,
`memchr`, `__memrchr`, `strncmp`, `strcat`, `strncpy`, `memcpy`, `memset`,
`strcpy`, `strcmp`, `strstr` — each run against the recompiled translation of
the same address, on the same guest memory, over 200 rounds of random strings
drawn from a six-letter alphabet so repeats and near-misses actually occur.
This is what catches a match that is somehow still wrong, and a native routine
that is right on its own but wrong at the boundary:

- The writing routines (`strcat`, `strncpy`, `strcpy`, `memcpy`, `memset`) are
  compared over the whole 128-byte destination buffer, not by comparing the
  resulting string. `strcpy`'s word path reads up to three bytes past the
  terminator inside an aligned word; a twin that wrote one byte too many would
  pass a `strcmp` of the result.
- `strcmp` is compared on the *sign* only. The twin's word path is big-endian
  and the magnitudes are allowed to differ; the guest only ever tests the sign.
  This is the one twin whose C needs a host-order guard, and getting it
  backwards is exactly the defect that was found by running it.

### `VIGetRetraceCount` against its twin (1)

```
[selftest] VIGetRetraceCount native vs twin ok    got "the count at 0x80347A64 over 200 rounds and four call sites"
```

`runtime/tick.c` answers `VIGetRetraceCount` (PLAN-60FPS-MODS M2) so the main
loop has a safe point and a tick the port can let go. It must be the original
-- the retrace count at 0x80347A64 -- everywhere but the frame end's spin once
unlocked. This runs it against the recompiled translation over 200 random
counts and four call sites, the top of the loop among them, where it adds only
a pass over the callbacks. The spin, and the callbacks, are `test_tick.py`'s.
Answering the count plus one at one call site fails it at round 2.

### The data-cache calls, paired singles, the race seed (3)

```
[selftest] DC range calls native vs twin ok    got "five calls over 100 rounds, a quarter of them empty"
[selftest] psq_load/psq_store vs generic ok    got "8192 loads and stores over 8 types and 64 scales agree with the ldexp formula"
[selftest] race seed at OSGetTick       ok    got "three sites pinned twice each and srand stored each pin; 8000A1DC left to the clock"
```

The five data-cache range calls (H13) are no-ops natively; their twins must
leave memory and the syscall count as the natives do. `cpu.h`'s paired-single
fast path is held to the `ldexp` formula over every type and scale. The race
seed (P6) runs the game's own OSGetTick and srand from each reseed site twice,
and from `0x8000A1DC` must get the clock (FINDINGS "H13, first steps", "P6").

### The encounter multiplier (1)

```
[selftest] encounter multiplier as the game has it ok    got "FF with none or without effect 84, 64 for 210, 05 for 211 on a later character"
```

`mods/encounter-rate` works out the multiplier the game would hold from the
party's accessories, and writes it back after a hold of B; this runs the
game's own `fn_801EF7E0` on five parties set up in memory and needs the byte
the mod's reckoning gives (FINDINGS "P1a"). Claiming the first character's
accessory wins fails it: the game gives 05.

---

## 4. The scenario library

Thirteen scripted runs in `config/scenarios/`, each a pad script, a frame
budget, an environment, what it is supposed to show, and an `evidence:` line
naming the log in `build/` or the section of FINDINGS it was recovered from.

```
python tools/scenario.py list
```

```
audio        11500 frames   19 events  The opening, headless, with every mixed sample written to a WAV file.
battle       12000 frames   19 events  The opening through to the first battle and out the other side.
capture       4500 frames   18 events  Run the opening headless and dump three command streams for --replay.
cardwrite     6000 frames    5 events  Blank card in slot A, New Game, then Yes to "Proceed with formatting?" -- the only CARDFormatAsync in the executable.
encounter    30000 frames   23 events  Walk a101b for twenty minutes of game time until a fight starts.
hold         16500 frames   21 events  Past the battle into the ship's hold, then walk Vyse with the stick.
monkey      126000 frames   24 events  The hold and its menus mashed with five buttons on five different periods.
newgame       3400 frames   18 events  Nine START/A pairs from 1600 to 3240: the title, New Game, the first dialogue.
opening       7500 frames   19 events  The Valuan bridge and the boarding, advanced by one A press every 150 frames.
speed        10000 frames   19 events  The opening headless at ten times guest speed, rendering nothing.
title         2000 frames    2 events  Boot through the logos to the title screen, press START, then New Game.
voice        12600 frames   19 events  The opening through the end of the first battle, headless: the first recording this port has made that contains speech.
window        7500 frames   19 events  The opening in a window at 2x, so the frame rate is the one a person sees.
```

### Running one

```
python tools/scenario.py run title --check
```

The tail of that run:

```
[check] the run exits 0                     pass  exit 0, 2000 frames
[check] no MMIO outside the modelled range  pass  no [mmio!] lines
[check] no unknown FIFO bytes               pass  0 unknown bytes of 354674256
[check] no bad vertex references            pass  0 bad vertex refs over 7874314 vertices, 112314 triangles
[check] the pad script was understood       pass  2 events
title: 4 of 4 invariants hold
```

The log goes to `build/scenario-<name>.log` (gitignored), and `--quiet` stops
the run echoing to the terminal. `python tools/scenario.py show title` prints
the scenario with its evidence and the exact command line;
`show <name> --command --shell powershell|cmd|sh` prints just the command, so
you can run it by hand:

```
$env:SOA_PAD='1600:start,1640:a'
$env:SOA_FRAMES='2000'
$env:SOA_RENDER='1'
$env:SOA_SNAP='50'
gen\soa.exe extracted
```

`python tools/scenario.py check build/scenario-hold.log --name hold` applies the
same checks to a log written earlier — useful for a run you drove by hand, and
free.

**Run one at a time.** Two runs of the port at once share `build/frames/`,
`build/cards/slotA.raw` and, if you do not pass `--log`, the same log path, and
in this session three consecutive scenarios died part-way through — silently,
exit `-1`, with no report line — while a second `soa.exe` was running, and
passed when run alone. Nothing in the tool stops you; the collisions are in the
filesystem.

### What the invariants mean

| Check | Reads | Fails when |
|---|---|---|
| the run exits 0 | the process status | the run did not reach its frame budget. The runtime documents its codes: 1 the disc did not load, 2 something unimplemented, 3 a guest trap, 4 a spin on a register answered with zero, 5 the watchdog, 6 the thread model gave up, 7 the self test, 8 `SOA_STRICT` |
| no MMIO outside the modelled range | `[mmio!]` lines | the guest touched hardware the runtime does not model — almost always a garbage pointer |
| no unknown FIFO bytes | the `[gx]` report line | the graphics front end met a command byte it could not parse. **Also fails at zero with nothing behind it**: a run that pushed nothing to the GP has checked nothing |
| no bad vertex references | the `[gxr]` report line | a draw referenced a vertex outside its array. Also fails at a zero with no triangles behind it |
| the pad script was understood | `[si] N scripted controller events` | the port read a different script from the one the file says. Without it the other four can all be true of a run that drove nothing |

`--check` sets `SOA_STRICT=1`, which stops the run at the *first* unmodelled
access with a guest backtrace and exits 8, rather than logging the first twenty
and carrying on. Knowing where beats knowing how many. The exit-status check
then reports itself as skipped and points at the MMIO check, so one broken thing
is named once. `--no-strict` runs to the frame limit and counts the lines
instead, which is what you want when a bad access is already known.

A check reports **skip** when the run could not have produced the evidence. A
headless scenario prints no `[gxr]` line at all, so:

```
[check] no bad vertex references            skip  nothing was rendered (no SOA_RENDER), so gxr_report prints nothing
scenario-capture.log: 3 of 4 invariants hold (1 skipped: no bad vertex references)
```

A scenario that *does* set `SOA_RENDER` and still prints no `[gxr]` line fails
that check rather than skipping it.

### How long each one takes

Measured here, one at a time, `python tools/scenario.py run <name> --check
--quiet`, on 16 cores:

| Scenario | Frames | What sets the pace | Wall time |
|---|---|---|---|
| `title` | 2,000 | renders, a PNG every 50 frames | **71 s** |
| `newgame` | 3,400 | renders, a PNG every 100 | **118 s** |
| `capture` | 4,500 | headless; writes three 24 MB captures | **154 s** |
| `cardwrite` | 6,000 | headless, tracing on | **204 s** |
| `opening` | 7,500 | renders, a PNG every 100 | **256 s** |
| `window` | 7,500 | opens a real window at 2x | *not run here — needs a desktop* |
| `speed` | 10,000 | `SOA_SPEED=10`, nothing drawn | **130 s** |
| `audio` | 11,500 | headless, every sample to a WAV | **389 s** |
| `battle` | 12,000 | renders, a PNG every 100 | **408 s** |
| `voice` | 12,600 | headless, WAV and tracing | **425 s** |
| `hold` | 16,500 | `SOA_SPEED=3`, a PNG every 300, three captures | **262 s** |
| `encounter` | 30,000 | `SOA_SPEED=3`, a PNG every 500 | **425 s** (7 min) |
| `monkey` | 126,000 | `SOA_SPEED=3`, a PNG every 1,000 | **1,577 s** (26 min) |

All twelve headless ones back to back are about 74 minutes, and `monkey` is
more than a third of that. For a change to `runtime/si.c` or a scenario file,
`title` at 71 seconds is the one to run; for a change that could affect the
game's own logic, `opening` at four minutes reaches the boarding.

**The frame count does not predict the time**, and the reason is worth knowing.
At `SOA_SPEED=1` every scenario runs at 28–30 game frames per wall second —
`title` 28, `newgame` 29, `opening` 29, `battle` 29, `audio` 30, `voice` 30 —
whether it renders or not, which is the game's own 30 fps cap and not the host:
the port spends the difference idling, as PLAN A4 measured directly (47% of a
run is `SelectThread`). `SOA_SPEED=3` lifts that to 63–80 (`hold` 63,
`encounter` 71, `monkey` 80), short of the 90 the cap would then allow, so the
host is starting to be the limit. `speed`, at `SOA_SPEED=10`, manages 77
against a cap of 300: that scenario measures the host, the others measure the
guest.

### The invariants are not the point of every scenario

`cardwrite` is the example, and it caught this page out. It is judged by one
number in the `[exi]` line — `40960 written`, which had been 0 in every log
this repository ever kept — and `--check` does not read that number. Its own
file says **delete `build/cards/blank.raw` before every run**: a blank card is
the absence of the file, a successful format creates it, and the second run
then finds a valid card, never draws the prompt and writes nothing. Run here
without deleting it, `cardwrite` reported

```
cardwrite: 3 of 4 invariants hold (1 skipped: no bad vertex references)
```

with `[exi] ... card 81920 bytes read, 0 written, 0 interrupts` in the log. All
the checks it can make passed, and the thing the scenario exists to show did
not happen.

Pointed at a card image that really is absent, the same scenario — 3 m 24 s —
gives the same three ticks and a completely different log:

```
> python tools/scenario.py run cardwrite --check --quiet --env SOA_CARD=build/cards/fresh.raw
[exi] memory card build/cards/fresh.raw: new blank card
...
[trace] CardScreenStatus@r31   ... r3 00000002     <- status 2: the format prompt
[trace] CardPromptYes          ... pc 8022B47C     <- Yes, confirmed
[trace] CardFormatAsyncCall    ... pc 801A2758     <- the one CARDFormatAsync in the executable
[trace] CardFormatResult       ... r3 00000000
[exi] 2403 immediate, 609 DMA transfers; card 122880 bytes read, 40960 written, 325 interrupts
```

and `python tools/cardformat.py verify build/cards/fresh.raw` then ends
`verdict: CARDDoMount would return 0 (READY)` — the game formatted a card the
game's own mount accepts. None of that is in the exit status. Read the `shows:`
and `note:` lines of a scenario before trusting it — `python
tools/scenario.py show <name>` prints them.

### What the scenarios do not cover

They are the cheap invariants. None of them looks at a pixel, a sample or a
counter's value — a renderer that painted every frame black passes all four.
What a frame actually contains is section 5. `--check` also counts only
positives: a stray `[gxr]` or `[mem]` tripwire line is in the log but does not
fail the exit status, so read the log when something changed in the renderer.

---

## 5. The frame-hash corpus

```
python tools/scenario.py replay
```

**18.3 s.** This is the only check in the project that compares what the game
actually drew with what it drew before.

```
[replay] 23 captures x 4 thread counts x 2 passes = 184 replays, each loading a 24 MB memory image
[replay] pass 1, SOA_THREADS=1
[replay] pass 1, SOA_THREADS=2
[replay] pass 1, SOA_THREADS=3
[replay] pass 1, SOA_THREADS=8
[replay] pass 2, SOA_THREADS=1
[replay] pass 2, SOA_THREADS=2
[replay] pass 2, SOA_THREADS=3
[replay] pass 2, SOA_THREADS=8
  ok    0100: ced8f6518129ba7a
  ok    0300: 060aa3991d5675e2
  ok    0500: 18188c9e9ce5bbdb
  ok    0700: 43e4f07acb6eb6bc
  ok    11900: 8397a025bf14b446
  ok    12000: 2bd2ed4ef6cb6f64
  ok    12100: a299e090100d8908
  ok    1500: eb9e8561b21e23d4
  ok    15200: a0cb1546b9125d59
  ok    1550: a0943b2e3ed178f9
  ok    15800: 6994bc39a78c21fa
  ok    16300: 98abad1aafa1ac08
  ok    2000: 1b89d592cb4ff90a
  ok    2050: b0baac995859366f
  ok    2100: 57b709d297ec6a66
  ok    3600: 2918b9b8dd044aa8
  ok    3900: 1b9127a8c6a17b2d
  ok    4200: 9cb3932be64e1dcb
  ok    4500: d66bf6cc34f00b08
  ok    4800: 04e0ac5788d18865
  ok    6000: fd05131bf320ca69
  ok    6300: 713cbc1951a1b894
  ok    8000: f672349f32fb0053
[replay] 23 captures match config/fifo_manifest.tsv at SOA_THREADS 1,2,3,8
```

Each capture is three files written by `SOA_FIFO_DUMP`: the frame's command
stream, the CP/XF/BP register shadows it began with, and a 24 MB image of MEM1.
`gen/soa.exe --replay <base>` renders one with no game running at all, and
`SOA_HASH=1` makes it print `[gxr] frame N WxH hash <16 hex>` — FNV-1a over the
finished rows after a `gxr_flush()`.

### What 184 replays prove, and what they do not

- **The same bytes in give the same pixels out.** Two passes over the same
  capture with the same thread count must agree; a disagreement is
  non-determinism in the renderer itself.
- **The answer does not depend on how many threads rasterize it.** That is the
  whole reason for sweeping 1, 2, 3 and 8. A hash that moves with the thread
  count is a race in the rasterizer, not a rendering — this is what pinned the
  worker hand-off across a flush, and how the `float tex[8][4]` slots that read
  stack were found.
- **A change to the renderer is visible and attributable.** It has already
  caught two real things: the test suite quietly overwriting its own corpus,
  and the texture use-after-free of 2026-09-17, whose fix moved 8 of the 23
  frames. Those 8 old hashes were the manifest pinning broken output — washed
  green and blue, with gold, maroon and skin tones missing — so a hash moving is
  a question, not a verdict. Look at the PNG before re-blessing.
- **It does not prove the frames are right.** They are pinned to what this port
  rendered, not to a console. The corpus also contains no line and no point
  draw, so the row-ownership rule in `raster_line` and `raster_point` is
  unpinned: both draw on every worker with no `my_row` test and nothing here
  would catch it.

### The manifest, and why it can live in the repository

`config/fifo_manifest.tsv` has three columns: the capture's name, **sha256 over
its own `.fifo`, `.regs` and `.ram`**, and the frame hash. The middle column is
what makes a row mean something on a machine that cannot have the capture —
without it a row could not be told from a typo. A mismatch there is reported
differently from a pixel change:

```
input <name>: this capture hashes ..., the manifest was blessed from ... -- a different capture, so the frame hash means nothing
```

### The warning: the corpus lives in a gitignored directory

`build/fifo/` is the corpus. It is game data — 24 MB of the game's own memory
per capture — so it is gitignored, never committed, and **exists on exactly one
machine**. There is nothing to restore it from.

- **A capturing run must be pointed somewhere else.** Set
  `SOA_FIFO_DIR=build/fifo-new` (or anything but `build/fifo`) alongside
  `SOA_FIFO_DUMP`. The two scenarios that capture — `capture` and `hold` — both
  do, and `scenario.py run` creates the directory for you. A run that dumps into
  `build/fifo` overwrites a capture whose blessed hash then means nothing, with
  nothing to restore from.
- **`--replay` overwrites `<base>.png`.** The reference PNGs are the only
  rendering of those frames anyone has, so the first sweep copies them to
  `build/fifo/ref-before` before it starts and says so.
- **Re-blessing is deliberate.** `python tools/scenario.py replay --bless`
  rewrites the manifest, and refuses to do it if the sweep did not agree with
  itself. Blessing a frame you have not looked at is how the texture
  use-after-free stayed pinned for a day.

Adding a capture to the corpus is therefore a deliberate two-step: capture into
`build/fifo-new`, sweep it on its own with `python tools/scenario.py replay
--fifo build/fifo-new` to see that it renders the same way at every thread
count, then move the three files into `build/fifo` and `--bless`. A capture
that is in `build/fifo` but not in the manifest is reported as `new`, and one
in the manifest with no files behind it as `gone`; both fail the sweep rather
than being quietly ignored.

`SOA_HASH=1` is for replays and nothing else. In a live run it forces a
`gxr_flush()` on every frame the port presents, which spoils any frame-rate
measurement, and `SOA_SNAP` skips rasterizing the frames it is not writing, so
most of the hashes would be of a frame nothing drew.

### The in-between image (H10)

```
python tools/midpoint.py            # the five pairs in build/perfset, 8 threads
```

About three minutes. Each pair's captures are checked against
`config/perfset_manifest.tsv`, copied to a scratch directory and replayed one
`soa.exe` at a time with `--replay F F+1`. Every pair must pass seven checks:
pass 2 is F+1 exactly as a single replay draws it; the pairs the renderer
wrote are `fifopair.match`'s, as many as H4 counted; the images are the same
at one thread; F paired with itself is F; t=1 is F+1; and a copy of F+1 with
one texture address changed loses the same pairs in both implementations.
The last line reads `midpoint: 5 of 5 pairs pass`, and anything else exits 1.

It pins no hash. The in-between image has no reference but the eye, so the
images land in `build/midpoint/<scene>/` -- `F.png`, `mid.png`, `F1.png`,
`t0.png` and `diff.png`, magenta where the in-between image differs from F+1 --
and a change to the lerp means opening them. The synthetic side, where the
right answer is known exactly, is `tools/tests/test_gxr_pair.py` in section 1.

---

## 6. The decompilation check

```
python tools/decomp.py
```

**4.0 s.** Builds every unit in `config/GEAE8P/units.txt` with the Metrowerks
compiler it names, then compares every function and every data object in the
object file against the executable's bytes. Needs `vendor/mwcc/` (see
`python tools/fetch_toolchain.py`) and the extracted disc.

Today: **21 units, 83 functions and 17 data objects MATCH, nothing differs**,
and the run exits 0. Four more symbols are named and skipped rather than
counted — static helpers mwcc inlined, which have no counterpart in the
executable to compare with (`aramCacheIntact`, `aramCacheSum`,
`aramCacheSlotValid`, `pool_order_seed`).

```
== src\sdk\msl\string.c (mwcc 1.3.2)
strlen                   MATCH  7/7 words  (object 28 bytes, executable 28)
strchr                   MATCH  12/12 words  (object 48 bytes, executable 48)
...
== src\sdk\ar\arq.c (mwcc 1.2.5n)
fn_80243A34              MATCH  46/64 words, 18 need a link  (object 256 bytes, executable 256)
...
__ARQVersion             MATCH  0/4 bytes, 4 need a link  (data at 0x80346918 via fn_80243C04)
@1                       MATCH  69/69 bytes  (data at 0x802FB198 via __ARQVersion)
66 word(s) and 4 data byte(s) only a link can decide, across 7 otherwise-matching symbol(s)
...
7 unit(s) fully verified; 14 with words only a link can decide
```

One unit on its own:

```
python tools/matchcheck.py build/src/strcpy.o
```
```
strcpy                   MATCH  46/46 words  (object 184 bytes, executable 184)
```

### What MATCH means now

It means every word was compared and every word was decided. That is a stronger
claim than it used to be, and the difference matters.

The old oracle compared any word carrying a relocation on its **six-bit primary
opcode alone**, on the theory that the linker fills the rest in. Under that
rule a `bl` to the wrong function reported MATCH, and so did an address
materialised into the wrong register — in exactly the code where matching mwcc
is hardest. Now the linker fills in only the field the relocation names; every
other bit is the compiler's, and the field itself has a right answer whenever
the relocation's symbol has an address this project knows. So each relocated
word is one of three things:

- **verified** — the bits outside the field are identical *and* the field in the
  executable points where the relocation says it should. For a REL24 that means
  the opcode plus AA and LK plus the actual branch target; for a 16-bit
  relocation the whole first halfword; for an SDA21 the register too.
- **differs** — one of those is wrong. Reported, and the unit fails.
- **unverified** — "needs a link".

Data objects are compared as well, not just `STT_FUNC`. A unit's own globals
have no address until something places them, so their addresses are recovered
from the fields the executable already has: that is how `__ARVersion` leads to
the SDK banner it points at, and the banner gets compared like anything else.
Two references to one symbol must agree, and two symbols in one input section
must keep their distance, because the linker places an input section as one run.

`tools/tests/test_matchcheck_relocs.py` builds its own objects and its own
executable — no disc — and each of its 14 cases is a thing the old rule called a
match.

### What "needs a link" means

The bits outside the relocated field are identical, but **nothing here knows the
target's address**, so only a link could settle the field. It is never counted
as a match, and it is never counted as a failure either. The count is printed
per unit:

```
5 word(s) only a link can decide, across 3 otherwise-matching symbol(s)
```

In practice these are references to globals this project has no address for
yet. They cluster where you would expect: `src/sdk/ar/arq.c` has 66 of them
across 7 symbols because the AR queue is nothing but calls and global state,
while `src/sdk/msl/strcpy.c` and `strstr.c` have none at all — a leaf routine
that touches no global has nothing a link could decide.

A unit with any of them is reported as **unverified**, not **match**:

```
7 unit(s) fully verified; 14 with words only a link can decide
```

`--strict` makes those a failure — `python tools/decomp.py --strict` exits 1
here where the plain run exits 0 — and a checkout with a complete symbol
database should reach it. It is not the default, because today it would fail on
14 units that are almost certainly right.

### Exit codes

`tools/decomp.py`: non-zero if a unit fails to compile, any unit differs, or a
compiler named in `units.txt` is missing (**2**, and every unit that needs it is
named — the run was incomplete, not clean, which is why a checkout missing
1.2.5n does not silently report a short run). `tools/matchcheck.py` on one
object: **0** everything compared and verified, **1** something differs or a
symbol makes a claim about the executable that is wrong, **3** nothing differs
but something was left undecided. Both read the executable and never write it.

### A match is not a behaviour test

Matching bytes proves understanding of what the compiler did; it proves nothing
about whether the routine is called correctly, or whether the natively compiled
twin behaves the same on x86. Those are `tools/citest/dc_check.py` (section 1)
and the self test's case 73 (section 3). All three are needed: the string
comparison that returned positive where the answer was negative byte-matched
perfectly the whole time.

---

## 7. What needs what

| Check | Disc | MSVC | Metrowerks | Built `soa.exe` | Capture corpus | CI runs it |
|---|---|---|---|---|---|---|
| `pytest tools/tests` | no¹ | partly² | no | no | no | **yes**, Ubuntu + Windows |
| `ruff check` / `ruff format --check` | no | no | no | no | no | **yes** |
| `tools/guard.py` | no | no | no | no | no | **yes**, plus a full-history scan |
| `citest/compile_runtime.py` | no | yes | no | no | no | **yes**, Windows |
| `citest/dc_check.py` | no | yes | no | no | no | **yes**, Windows |
| `citest/render_check.py` | no | yes | no | no | no | **yes**, Windows |
| `SOA_MEMPOKE` tripwire | no | — | no | **yes** | no | no |
| `recompile.py --compile --link` | **yes** | yes | no | — | no | no |
| `SOA_SELFTEST=1` | **yes** | — | no | **yes** | no | no |
| `scenario.py run … --check` | **yes** | — | no | **yes** | no | no |
| `scenario.py replay` | **yes**³ | — | no | **yes** | **yes** | no |
| `decomp.py` / `matchcheck.py` | **yes** | no | **yes** | no | no | no |
| `audio_check.py` | **yes** | — | no | **yes** | no | no |
| `validate_assets.py` | **yes** | no | no | no | no | no |

¹ One test (`test_image_every_word_agrees`) skips without `extracted/sys/main.dol`.
² 287 of the 957 skip without a C compiler; they build one runtime file and run it.
³ `--replay` takes the capture as its argument, but `main.c` still opens the
disc directory.

### What CI can and cannot run

Four job runs on every push and pull request:

| Job | Runner | Does |
|---|---|---|
| **Game data guard** | ubuntu | `tools/guard.py`, then every blob in the whole history against the same suffix list, then `tools/guard.py --history` over every path any commit touched and the bytes it held, then a 2 MiB blob-size ceiling |
| **Tests** | ubuntu | `pytest`, `ruff check`, `ruff format --check` — 651 passed, 288 skipped |
| **Tests** | windows | the same three — 938 passed, 1 skipped |
| **Runtime compiles (MSVC)** | windows | `compile_runtime.py`, `dc_check.py`, `render_check.py` |

The Windows runner already ships VS 2022, and `tools/soa/toolchain.py` finds it
through `vswhere` and runs `vcvars64.bat` exactly as it does on a developer
machine, so CI and your build use the same compiler and the same flags. All
three scripts **fail loudly rather than skipping** when there is no `cl.exe`: a
check that quietly does nothing is worse than no check. The `native` job also
installs nothing with pip — `dc_check.py` imports `tools/recompile.py` for one
helper and that import graph is stdlib-only, which `test_citest.py` asserts
rather than leaving it to be discovered in CI.

**CI cannot run:** linking `soa.exe`, anything under `gen/`, the device models,
the guest half of `runtime/selftest.c`, the mwcc byte-for-byte match, the replay
corpus, any scenario, and anything that reads `extracted/`. All of those need
the disc, the vendored compilers, or captures that are game data. A green tick
means the C compiles, those MSL routines behave like libc, and the rasterizer
still fills a triangle — nothing about the game running. **Sections 3, 4 and 5
are yours to run; nobody else can.**

### Other tools that check something

- `python tools/profile.py build/scenario-title.log` — reads the timing a run
  printed back and asserts the four properties a truthful profile has (busy plus
  idle comes to the pool's span within 5%, the table sums to 100%, and frames,
  guest seconds and wall seconds are three separate numbers). Two logs of the
  same scenario also compares their top tens. On the title run here: `8 threads
  x 70.72s = 565.76s against busy 10.90s + idle 554.86s = 565.76s, 0.0% apart`.
- `python tools/cardformat.py verify <image>` — re-runs the mount's own checks
  over a card image without launching the port, and ends `verdict: CARDDoMount
  would return 0 (READY)`. This is how the card the game wrote was confirmed to
  be one its own mount would accept.
- `python tools/audio_check.py build/opening.wav extracted/sound/<stream>.dsp` —
  cross-correlates a `SOA_WAV` recording against the decoded stream on the disc.
  Needs numpy, which `pyproject.toml` does not list.
- `python tools/validate_assets.py` — decodes every AKLZ container on the disc
  and asserts each yields exactly its declared size and contains no PowerPC
  code.

---

## 8. Before you push

In this order, because each one is cheaper than the next and the first failure
is the one worth reading:

```
python tools/guard.py
python -m ruff check tools
python -m ruff format --check tools
python -m pytest tools/tests -q
```

About a minute all told (`ruff ...` and `python -m ruff ...` are the same
thing; the second works whether or not the shim is on `PATH`).

**Run the format check as its own command.** `ruff check` passing feels like it
covered formatting; it does not, and that is what broke CI both times.
[CONTRIBUTING.md](../CONTRIBUTING.md) asks for the guard and the tests — the two
ruff commands are what CI adds on top, and the format one is the omission that
costs a red tick. If you would rather not think about it, run `python -m ruff
format tools` before the check: it is idempotent, and its diff is the fix.

If you touched anything under `runtime/`, add:

```
python tools/citest/compile_runtime.py
python tools/recompile.py --link
$env:SOA_SELFTEST='1'; gen\soa.exe extracted
```

If you touched `runtime/gxr*.c`, `runtime/gx.c` or anything a draw passes
through, add `python tools/scenario.py replay` — 18 seconds, and it is the only
thing that will tell you a pixel moved. If it reports `DIFFS`, look at the PNG
before you re-bless.

If you touched `src/`, `include/` or `config/GEAE8P/units.txt`, add
`python tools/decomp.py`; if you touched `config/hle.txt`, rebuild with
`--compile --optimize --link` and run the self test, because case 73 is what
checks the swap.

If you touched `config/scenarios/`, `tools/scenario.py` or `runtime/si.c`, run
one scenario end to end — `python tools/scenario.py run title --check`, about
70 seconds — because the pad grammar lives in two places and the tests only
check that they agree in the abstract.

---

Every figure on this page was measured in one sitting on one machine, so treat
it as a starting point and not as a contract: the checks are the contract, and
they are all in the tree. [PLAN.md](PLAN.md) says what is being worked on next,
[ROADMAP.md](ROADMAP.md) what is done, [FINDINGS.md](FINDINGS.md) what the
evidence behind a claim is, and [CONTRIBUTING.md](../CONTRIBUTING.md) how to get
from a clean machine to a running game.
