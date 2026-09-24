<!-- Written 2026-09-24 by a read-only research agent for docs/PLAN-60FPS-MODS.md; nothing was
run. [V]/V marks what was read from quoted instructions, file:line or logs; [I]/I is inference. -->

# Automated soak and regression programme: spec

**Status:** read-only investigation. Nothing was launched. **[V]** means I verified it from a file:line, a log line, the disassembly or a command I ran. **[I]** means I inferred it.

## 0. What exists today

**Generator: `tools/soak.py`**
- It is a pad generator and nothing more. It has an LCG, the Continue preamble (frames 1600–2640) and two mixes: walk, and `--battle` (`_battle`, soak.py:84).
- It caps a script at 1000 events (soak.py:44), because `si.c` holds 1024 (si.c:78).
- It does not run anything and does not check anything. `test_soak.py` has 6 tests. [V]

**Checker: `scenario.py check_report` (scenario.py:547)**
- It asserts:
  - exit 0;
  - no `[mmio!]`, under `SOA_STRICT`;
  - 0 unknown FIFO bytes, with pipe bytes > 0;
  - 0 bad vertex refs, with triangles > 0;
  - the pad event count.
- `RE_STOP` (scenario.py:463) catches spin, trap, unimplemented and watchdog.
- It does **not** fail on `[mem]` tripwire lines or `[gxr]` WARN_ONCE lines. TESTING §4, "What the scenarios do not cover", says so. [V]

**How the 12 soaks were actually run** [V]
- Source: the scratchpad scripts `soaks.sh`, `bsoaks.sh` and `bsoaks2.sh`.
- Each copied `card-partX.raw` to `build/savetest/work.raw`, then ran `scenario.py run battle --frames 33500 --log … --env SOA_CARD=… SOA_TRACE=1 SOA_SNAP=1000 SOA_STRICT=1 SOA_PAD=$(soak.py …)`.
- **None used `--check`.** Each verdict was `grep -c 'mmio!'` plus a grep for "unknown bytes".
- Every `run_*.log` header labels the run "battle: The opening through to the first battle".

**Measured across all 12 logs** [V]
- 33,500 frames took 1121.6–1128.1 wall seconds (`[run]` line, `SOA_SPEED=1`). That is 29.7–29.9 fps.
- All 12 exited 0 with 0 `[mmio!]`, 0 unknown bytes and 0 bad vertex refs.
- Every save reached its field at frame 2650.

**Renderer coverage is thin** [V]
- Headless `SOA_SNAP=N` rasterizes only every Nth frame (gxr.c:1534).
- So "0 bad vertex refs" covers 34 of 33,500 frames. For example, bsoak101 rasterized 76,548 triangles out of 26,374,282 parsed draws.

**What the logs show that the write-up does not** [V]
- **A renderer tripwire fired unreported.** `[gxr] BP_MASK 080000 was in force for BP 00 000001…` appears in exactly the three part-G logs: soakG, bsoak101 and bsoak202. These are the only soaks that had battles.
- **The battle count in FINDINGS is wrong.** FINDINGS.md:1544 says part G "fought four random battles". soakG has 3 × `/battle/stsicon.mld` and 3 × `m0458.samp`, plus one `m0458.info`; the scratch grep counted the `.info` line as a battle.
  - bsoak101 had 1 battle and bsoak202 had 2.
  - None of the three loaded PCWIN, so it is not established how battles 1–2 in soakG ended.
- **Game over wasted a large share of the part-G soaks.** `a090a` loaded at frames 20792, 16856 and 19013. So 38–50% of each G soak ran the title and attract demo (`a299a`/`a297a`).
- **The random A presses saved to the card repeatedly.**
  - bsoak404 (part F): `card … 1933312 written`, with 118 `CardUpdateDirErase`.
  - bsoak101: 557,056 bytes written.
- Texture-cache thrash warnings ("the working set does not fit") appear in the soaks. That is a signal for the speed work.

**Scratch tools not in the repo** [V]
- `mkcensus.py`: 5 pokes per warp (the name, `sys[15]=0`, state 15); never pokes the map words; asserts ≤256 pokes.
- `mkship.py`: 7 pokes per stage (name, return name at 0x802E5E68, 0x803472E4=1).
- `mkpart.py`: the part-select pad for parts C–K.
- `padL.txt`: the pad for part L.
- `census.py` + `pngstats.py`: the census table.
- `ect.py`: encounter tables.
- `logs.py`: fps and pixel metrics.
- `parts.sh`: the loop that made the part cards.

**Runtime limits** [V]
- Snapshot PNGs always go to `build/frames` (gxr.c:2063).
- `SOA_POKE`: at most 256 items (main.c:708), each fires once, and there is no read-only form (main.c:769-785).
- `SOA_PAD`: 1024 events. `SOA_PAD_FILE` grows as needed (si.c:469).
- The headless watchdog defaults to 20 s (main.c:501).
- The frame-limit stop flushes, reports, then calls `_exit(0)` (gx.c:169-179).
- The per-frame hook is installed at main.c:977.

**Determinism** [V]
- The RNG is reseeded from OSGetTick on every map load: `801012AC bl OSGetTick`, `801012B0 bl fn_8025ECBC`.
- The guest clock follows the host clock (PLAN D4).
- So HANDOFF.md:337, "A fault it finds replays from its seed", is true of the input only. Encounters and timing will differ from run to run.

## 1. Soaks in dungeons with encounter tables

### 1a. Which save for which dungeon

**Rule:** use the save made at the start of the dungeon's own story part, so the dungeon's own flags are still clear, as on a first visit. Enter by name-warp with `sys[15]=0` (the default entrance), unless the save already lands there.

**How the table was derived** [I]: I ran `tools/sct.py` over all 35 maps (scratch `encmaps.py`) and mapped each story flag the scripts test to a part, at 50 flags per part (story-flags.md). This is a lower bound: the linear disassembly desynchronised in 1–36 entries per map.

| Save (where it lands) | Encounter maps whose scripts test that part's flags |
|---|---|
| C (`004a`) | 106a, 106c (flags ≤122) |
| D (`002e`) | 109b, 109c, 109d (≤162) |
| E (`008b`) | 111b, 111c, 111d, 112b (209–227) |
| F (`010a`) | 115b (≤276) |
| G (`116a`) | 116a, which needs no warp and already had battles [V]; 116c, 116d, 116e, 116g, 116h; 017a (tests up to 320) |
| H (`018a`) | 020b, 121b; 121c tests no story flag |
| I (`019b`) | 123b, 125a; 123d tests none |
| J (`017b`/`017c`) | 126b (455–457) |
| K (`099l`) | 126d (≤521), 103b revisit (521), 099a sky |
| L (`126a`) | 131e (≤567), 122a (563), 020b (566); 130b, 130c, 131c and 035b test no story flag |
| A (`card-saved`, `101b`) | 101b only with the alarm set (FINDINGS recipe); 103b and 103c test part-A flags 13 and 20 |

**Where a "dungeon card" is allowed.** Scripts containing op 138, a save point [V by scan]: 017a, 101b, 103c, 106a, 109d, 111d, 115b, 116a, 116e, 116g, 116h, 122a, 123b, 125a, 130b.
- Only these maps may get a card made by warp + one-word save request, for later Continues straight into the dungeon.
- Anywhere else, a Continue takes the `sys[15]=20000` branch, which retail cannot reach. That is the `a116c` trap.

### 1b. Forcing encounters fairly

**Never use the six-word request (`0x803473D4`) in a soak.** It skips every gate (encounters.md §1A), and it is what produced the black field on `a101b`.

**Accelerate the game's own random path instead.** Poke the step counter `0x80346D28 = 100000`.
- The counter is `r13-31224`, loaded at 800C1FC8, incremented at 800C1FD8 and stored at 800C1FE8. [V]
- Every gate runs before the counter is read. For example, the flag-1025 test at 800C1D48 (`lwz 128(r3)` @0x80310BBC, bit 0x2) comes before 800C1FC8. [V]
- The zone test (1..8) at 800C1FA4–800C1FB4 and the movement test at 800C1FB8–800C1FC4 also come before it. [V]
- Zone rate > 0 still applies, by the rate formula in encounters.md. [I]
- So the poke only shortens the wait. It cannot produce a battle the story forbids.
- The counter resets on map load and after each battle (encounters.md), so re-poke every K frames. At K=600 that is 50 pokes per 30k frames, which fits under 256 alongside a 5-poke warp.

**Control that must show zero battles:** the accelerator on `card-saved` (`a101b`, `0x80310BBC=0x430E`, flag 1025 set). This is the mutation that proves the oracle can fail.

**Control that must show more battles:** part G on `116a`, same seed, against the unaccelerated baseline of 1–3 battles per 30k frames.

**Post-battle check.** After every battle-to-same-map field reload, the next snapshot must be non-black. Otherwise the report raises "question: black after battle", which is the `a101b` class of problem.

### 1c. Setup assertions: a soak must prove it soaked where it says

- The first field map after the Continue must be the save's map, by frame 3000.
- The warp target's `.mld` must load.
- A battle job with 0 `stsicon.mld` loads is reported "did not test what it says", not "pass".
- Title timeout risk: the title drops into the attract demo after 92.267 s of host wall clock (HANDOFF). A slowed run that misses the Continue would otherwise "pass" while soaking the attract demo.

## 2. Scratch scripts into the repository

**`tools/census.py`**
- **`poke`:**
  - Field warps get 5 pokes each and never touch 0x80311AC0/AC4/AC8.
  - Ship stages get 7 pokes each (opcode 210) and never touch 0x80311AEC.
  - It refuses more than 256 pokes, i.e. 51 field warps or 36 ship stages per run.
  - It emits the pokes plus a schedule.
- **`table`:**
  - Attributes `LoadStart /field/…` lines to warps.
  - Reads PNG stats only from the job's own frames directory or from frames newer than the run's start (the census-3 stale-frame lesson).
  - Attributes `[mmio!]`, `[mem]`, `[game]` and `[gxr]` warnings to warp windows.
- **`maps`:**
  - Writes `config/maps.tsv` from `extracted/`: warpable, has `.ect`/`.enp`, save point present, part tested, and ids and booleans only.
  - Expected counts: 255 warpable, 66 of them 5xx, 35 with encounter tables.
- **PNG reader:** move `pngstats.py` to `tools/soa/png.py`, stdlib only.

**`tools/partsel.py`**
- `pad <B..L>` plus the `ME355A` warp pokes and the save request at frame 10000.
- `make-card` runs it from `card-saved.raw`, checks the landing map in the log, then runs `cardformat.py verify`.

**`tools/soak.py`** gains:
- `--warp NNNx` and `--encounter-every K`;
- a `--pad-file` output (the v2 recording format) for scripts longer than about 100k frames;
- `check <log> [--expect-map …]`, which uses `scenario.parse_report` plus soak extras and writes `summary.json`.

**Soak invariants**

| Check | Kind |
|---|---|
| exit 0 | fail |
| no `[mmio!]` (`SOA_STRICT`) | fail |
| 0 unknown bytes and pipe > 0 | fail |
| 0 bad vertex refs and triangles > 0 | fail |
| no `[trap]`/`[unimplemented]`/`[spin]`/`[watchdog]`, or exit 3/2/4/5/6 | fail |
| no `[mem]` tripwire (new) | fail |
| pad events == generated | fail |
| setup assertions (1c) | fail |
| `cardformat.py verify` on the job's card = READY (new; soaks write the card) | fail |
| `[gxr]` WARN_ONCE lines, `[game]` prints, texture-cache thrash, black stretches, black-after-battle | question |
| maps visited with their frames, battles (`stsicon`), PCWIN, game-over frame, BEFF packages, card bytes read/written, fps, rasterized-frame fraction | recorded |

**Committed ledger (optional): `config/soak_ledger.tsv`.** One row per run the owner chooses to keep: date, commit, exe sha, job, save, map, seed, mix, accel, frames, verdict, counters. FINDINGS then cites rows instead of prose counts, which rot.

## 3. Overnight batch runner (`tools/nightly.py`)

**Plan file:** `config/soaks/*.tsv`, one row per job: name, card, warp, mix, seed, frames, accel, speed, extra env.

**Per job, strictly one `soa.exe` at a time:**
- Take a lock file, and refuse to start if an `soa.exe` process is already live.
- Copy the card into `build/soak/<run>/<job>/card.raw`. Never use `slotA.raw`.
- Clear `build/frames`.
- Run through `scenario.stream_run` with a timeout (frames / 20 fps + 120 s).
- Move the PNGs into the job directory.
- Run `soak.py check`, which writes `summary.json`.

**Around the jobs:**
- **Resumable:** skip any job that already has a `summary.json`.
- **Stale-binary guard:** refuse if `gen/soa.exe` is older than the newest file in `runtime/`, `src/` or `include/`, or if `[poke] N poke(s) armed` differs from the generated count.
- **Recorded:** exe sha256 and HEAD plus a dirty flag.
- **Output:** `report.md` plus `summary.tsv`: verdicts, questions, fps per job, and a diff against the previous night. Exit is non-zero on any failure.

**Budget [V]:** 1,125 s per 33,500-frame job, so about 25 jobs per 8 hours.

**Proposed night (~4.5 h):**
- 12 dungeon battle soaks: 3.75 h.
- title/opening/battle `--check` plus replay: about 12.5 min.
- One-sixth of the map census, about 19 min. A full census is about 6 × 19 min, so run it weekly.
- One full-raster soak.
- Scheduled by Windows Task Scheduler, not CI.

## 4. CI

**CI can run** [V: `ci.yml` has guard, pytest + ruff on ubuntu and windows, and the MSVC compile job]:
- every new Python module, against fixture logs copied from the runtime's `fprintf` formats;
- mutation tests: inject `[mmio!]`, `5 unknown bytes`, a `[mem]` line, a missing `[gx]` line, a wrong landing map, a stale PNG;
- the runner end to end against a fake-port script (canned stderr and exit codes; tests timeout, kill, resume and the lock);
- pinned generator outputs:
  - census-4 pokes equal the scratch `c4_poke.txt` byte for byte;
  - the part pads equal the ones that made the cards, with `padL.txt` for L;
- schema checks for the plan, `maps.tsv` and the ledger;
- the guard.

**CI cannot run:**
- `soa.exe`, since there is no `gen/` without the disc;
- any soak, census or scenario;
- replay;
- card or PNG work;
- the check that `maps.tsv` agrees with the disc. That test should skip without `extracted/`, like `test_image_every_word_agrees`.

**Do not use a self-hosted runner.** The repo is public (HANDOFF: "public history"). Fork pull requests would execute on the owner's machine, and any uploaded artifacts (PNGs, card images, guest strings) would publish game-derived data.

**Guard gap [V]:** `.raw`, `.fifo`, `.regs`, `.ram`, `.wav` and `.png` are not in `FORBIDDEN_SUFFIXES`, and none is tracked today.

**Stale doc [V]:** TESTING.md:948-949 still gives CI as "409 passed, 70 skipped / 478 passed, 1 skipped", while §1 says 511/87 and 597/1.

## 5. Slices, in order

| # | Slice | Size | Acceptance |
|---|---|---|---|
| S1 | `soak.py check` + `summary.json` + the new invariants | 1 day | All 12 existing soak logs pass. soakG reports 3 battles, game over at 20792, and the BP_MASK question. Each injected mutation fails. No disc needed. |
| S2 | Guard: add the soak artefact suffixes; fix TESTING:948-949 | hours | `guard.py` and `--history` pass (exempt by blob if history hits); `test_guard` covers the new suffixes. |
| S3 | `tools/partsel.py` (pad + card maker) | half day | Pinned pads for C–L parse, stay ≤1024 events and match what made the cards. On the owner's machine, rebuilding G lands `a230a` then `a116a` and the card verifies READY. |
| S4 | `tools/census.py poke/table` + `tools/soa/png.py` | 1.5 days | Pokes match the scratch files byte for byte. Tests show the map words are never poked, ship mode never pokes the state word, and 257 pokes are refused. `table` over `census4.log` gets all 51 warp loads right from the log alone (its PNGs have since been overwritten, so pixel stats are tested on synthetic PNGs). |
| S5 | `census.py maps` → `config/maps.tsv` | 1 day | 255 warpable, 66 of them 5xx, 35 with encounter tables matching encounters.md §4; the disc test skips in CI. |
| S6 | `soak.py --warp/--encounter-every`; no `0x803473D4` anywhere (tested) | 1 day + 2 runs | `card-saved`/`a101b`: 0 battles. Part G on `116a`: more battles than the same seed unaccelerated, with every post-battle snapshot non-black or raised as a question. |
| S7 | `tools/nightly.py` + report + fake port | 2 days | CI dry run passes. A 3-job real run survives a kill and resumes, producing 3 summaries and a report. |
| S8 | Dungeon reach matrix, all 35 maps (3,000 frames each, about 70 min), then 30-minute soaks on the ones that reach | 1 day + 1 night | Every map has a row (reached / drew / encounter / fault) with the frame opened, and the save-to-dungeon table is corrected from what ran. |
| S9 | Census baseline under the fixed recipe (from `card-saved`, `sys[15]=0`, 600-frame gap). Re-run the census-1–3 maps, which used older recipes; look at every frame before blessing (CLAUDE.md, first bless). | 1 day + 2 h of runs | `config/census_baseline.tsv`, with a commit that says how each outcome was checked. |
| S10 | `SOA_SPEED=3` equivalence (same seeds: map sequence, battles, invariants) | hours + 1 h | Adopt it only if equivalent. That would give about 2.3× throughput (TESTING: 63–80 fps). |
| S11 | Runtime aids, `--link` only, frame hook in `main.c`, called main→gx only: `SOA_PEEK=addr@N` (flag word, map, scene, step counter); `SOA_UNTIL=addr=value` (clean stop, e.g. map 90 = game over); `SOA_RASTER_ALL` (rasterize every frame while snapshotting every N); `SOA_FRAMES_DIR` | hours each | Each has `test_poke`-style tests. `SOA_UNTIL` stops with the full report and exit 0. Measure the full-raster fps cost. |
| S12 | Parallel runs, gated on S11's frames directory. CLAUDE.md records three unexplained silent exit -1 deaths with two processes running. | a day | 10 isolated pairs, 0 deaths. Otherwise stay serial. |
| S13 | Nightly plan + Task Scheduler + two consecutive nights | hours + 2 nights | The second night's report shows only its diff from the first. |

**Total:** about 10 days of work plus 3–4 nights. Every slice that adds tests must update every copy of the test count: PLAN, TESTING (4 places), HANDOFF, README and `SKILL.md`.

**Toward 60 fps and mods:**
- This suite (invariants, census baseline, replay corpus, fps per job) is the before/after net for C4 and any frame-rate patch.
- Generators should hold durations in game-seconds and take `--fps`, because a 60 fps mod doubles every frame-keyed hold and gap.
- Exact regression replays need D4 (a deterministic clock) and `SOA_RTC`. Until then, compare invariants and coarse outcomes, not frame sequences.

**Files**
- Scratch scripts and read-only analysis: a session scratchpad, not kept (`mkcensus.py`, `mkship.py`, `mkpart.py`, `census.py`, `pngstats.py`, `soaks.sh`, `bsoaks.sh`, `bsoaks2.sh`, `parts.sh`, `encmaps.py`).
- Soak logs: `C:\Users\bmfre\Documents\Github\SOA\build\scenario-soak{D,E,G,H,J,L}.log` and `scenario-bsoak{101..606}.log`.
