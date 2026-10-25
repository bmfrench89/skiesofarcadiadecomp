# The event track: a modded session that replays as it was played

Written 2026-10-24 against a6ed71b, from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) "The event track (rule 6)"
and rule 6 itself: *everything that changes the game is recorded*. It is the last item of milestone 2 (that plan's
milestone table, row 2). M8 has landed, so the hotkey and overlay lines the plan held back for it are in scope here.

**Why.** A pad recording is how a session is kept: a bug report, a soak's input, a race. Today four things change the
game mid-run and never reach the file: pad 2, the host buttons a mod reads, turbo, and the menu's save-now and debug
actions. A replay of such a session silently plays a different game. And when the `# config` line differs, the replay
only warns, so a soak or a battle check can measure a game it did not mean to.

## 1. What is there [V, each checked at a6ed71b]

- **The settings half is built.** `settings.c`'s `Setting.recorded` (`runtime/settings.c:50`) marks the keys that change
  the game: `seed`, `encounters`, `encounters_hold_b`, `turbo`, `autotext`, `coop`. `settings_recorded` (`:344`)
  writes each one set, as its owner applied it, and `main.c:1411-1420` hands the result and `mod_describe()` to
  `si_set_config_extra`. A DLL mod's setting with its mod not loaded is dropped (`settings_check_mods`, `:327`).
- **Mod options are in the line** since M16: a mod with an option away from its default carries the values after its
  hash (`runtime/mod.c:2788-2823`). The plan's note that options are invisible (`mod.c:865`, `:935`) predates M16.
- **A mismatch only warns.** `pad_replay_load` (`runtime/si.c:574`) compares the recording's `# config` with this run's
  (`pad_config`, `:367`) and prints both whole lines (`:649-653`), naming neither the entry that differs nor stopping.
- **`SOA_STRICT` is taken.** It stops a run on an MMIO access outside the modelled range (`runtime/hle.c:97`, exit 8),
  and `scenario.py --check` and `reach.py` set it. The replay switch needs its own name.
- **Pad 2 is never recorded.** `si_read_pad(2)` (`si.c:832`) reads the window's second pad or `SOA_PAD2` whenever a
  mod asks, with no per-frame latch, during a replay too. The coop mod says so once per run (`mods/coop/mod.c:124`).
- **Host buttons are 0 during a replay** (`host_update`, `si.c:892`): a recording never holds them, so autotext's
  hold-to-skip on LB (`mods/autotext/mod.c:89`) does nothing when a session is replayed.
- **A chord is a comment.** `host_update` writes `# chord F view+rs turbo` (`si.c:904`), which the replay passes over.
- **Turbo flips at the safe point.** `tick_turbo_toggle` sets a request; `turbo_evaluate` (`runtime/tick.c:97`) takes it
  at the top of the frame, *before* the registered safe-point callbacks (`tick.c:171-174`). The menu's Turbo row and
  the View+RS chord both come here.
- **The menu's save-now and debug actions** are requests taken at the safe point: `savenow_request` then
  `savenow_safe_point` (`runtime/savenow.c:59`, `:86`), `actions_request` then `actions_safe_point`
  (`runtime/actions.c:58`, `:181`). `SOA_SAVE_NOW` and `SOA_ACTION` schedule the same paths by frame. A refused one
  changes nothing and says why.
- **The menu's withholding needs nothing.** The live pad is made neutral before the recording takes its copy
  (`si.c:804`), so a session around the menu already replays.
- **Settings the menu changes** are written to soa.ini and read at the next start (`runtime/menu.c:11-13`), so the next
  run's `# config` line covers them. Fullscreen changes no game state.
- **Who replays.** No tool sets `SOA_PAD_FILE` but the person; `soak.py` reads a replay's log (`RE_PAD_FILE`,
  `tools/soak.py:313`) and its pad check (`:612`) passes on `[pad] replaying N state changes`. No tool sets
  `SOA_ACTION`, `SOA_SAVE_NOW` or `SOA_BATTLE_FORCE`; `reach.py` alone sets `SOA_POKE`, and it does not record.

## 2. The file, version 3

The header becomes `# soa pad recording v3`. Pad 1's lines and the `# config` line are unchanged; v1 and v2 files still
replay. Everything new is a line whose second field starts with `@`:

```
# soa pad recording v3 -- frame buttons stick cstick triggers, one line per change; @frame lines are the event track
# config render=- window=- speed=1 scale=2 threads=- card=build/cards/slotA.raw:524288 seed=7 mods=coop@1.0:1a2b3c4d
412 a #r930
412 @pad2 b
413 @host lb
600 @turbo on
3300 @action warp:116c
3420 @savenow
```

The frame comes first, as on pad 1's lines, so a person trimming at a frame cuts both together. The plan sketched
`@frame kind key=value`; each kind here has one value, so `F @kind value` reads like the log line it repeats.

| Line | Written when | Replayed |
|---|---|---|
| `F @pad2 STATE` | the first `si_read_pad(2)` of frame F gives a state other than the last written; STATE is pad 1's grammar (`- 255,128`) | `si_read_pad(2)` gives it from frame F, the live pad and `SOA_PAD2` ignored |
| `F @pad2 off` | pad 2 stops being there | `si_read_pad(2)` returns 0 from frame F |
| `F @host NAMES` | the host buttons change (`lb`, `view+rs`, `-`), the script's included | `si_host_buttons()` gives them from frame F; no chord fires from them |
| `F @turbo on` / `off` | `turbo_evaluate` flips it at frame F, from the chord or the menu | `turbo_evaluate` sets it at frame F, before the safe-point callbacks, as it ran |
| `F @action NAME[:ARG]` | `actions.c`'s `run` writes one at frame F, from the menu or `SOA_ACTION`; `SOA_ACTION`'s own names | `actions_safe_point` runs it at frame F |
| `F @savenow` | `savenow_safe_point` opens the save menu at frame F, from the menu or `SOA_SAVE_NOW` | `savenow_safe_point` asks at frame F |

- **Only what happened is written.** A refused action or save-now changed nothing, so it is not in the file.
- **Each kind keeps its own frame order**, as pad 1's lines must (`si.c:601-607`), and is parsed into its own list, so
  a mod reading pad 2 after pad 1's line for the same frame, or a safe point's event, never trips the order check.
- **Each module takes its own events at its own point**, never through a new safe-point callback: turbo inside
  `turbo_evaluate`, so a replayed flip lands where the live one did, ahead of the callbacks (§1). The recorder and the
  replay's lists live in `si.c`; `tick.c`, `actions.c` and `savenow.c` reach them through setters `main.c` makes, as
  `si_set_pad2_source` does, so each still links alone in `test_tick.py`, `test_padrec.py` and the mod driver.
- **A replay is the whole input**, as it is for pad 1 today (`si.c:775-779`). While one runs, `SOA_ACTION` and
  `SOA_SAVE_NOW` are ignored with a line, as `SOA_PAD` is (`:659-660`); the menu's Turbo, Save now and Debug rows say
  "a replay is running" and take nothing; and pad 2 and the host buttons are the recording's, none when it has none.
- **A recorded event the replay cannot apply** (an action or a save-now refused at its frame, because the field is not
  quiet there) is the replay leaving the recording. It is logged: `[event] frame F: the recording's action warp:116c
  was refused here, during an event: the replay has left the recording`.
- **An `@` line this build does not know** is passed over with one line naming its kind.

## 3. The strict switch, and the knobs that write memory

- **`SOA_PAD_STRICT=1`.** A replay whose `# config` differs from this run's, or that has none (v1 or hand-written),
  stops before its first frame of input with **exit 11**, naming the entries that differ. A recorded event the replay
  cannot apply (§2) stops it the same way at that frame. `scenario.py`'s `EXIT_MEANINGS` gains 11.
- **Without it, the warning names the entries that differ** (`encounters=double` recorded, `encounters=half` now)
  before the two whole lines it prints today, so the log says what to fix.
- **The test knobs that write guest memory join the line**, named only when set, so every recording made without them
  keeps the line it has: `battle_force=M:I:S@F` verbatim (one word); `poke=` and `mempoke=` as the FNV-1a of their text
  in eight hex digits, since a list of pokes can outrun the 640 bytes the line has (`si.c:329`). With those, the strict
  switch covers everything a tool sets that changes the game.
- **`soak.py check --strict`:** a log whose replay names a mismatch, a recording left, or exit 11 fails the pad check.
  Without `--strict` each is a question, as a black field after a battle is. R0 and T6 run from pad scripts, not
  recordings; they take the switch when they replay one.

## 4. The slices, in order

- **E1, the strict switch** (hours): §3, and the warning's named entries. The settings lines come first, as the plan
  asks.
- **E2, pad 2 and the host buttons** (about a day): §2's `@pad2` and `@host` lines, recorded and replayed, with the
  per-frame latch pad 1 has (`si.c:934-941`). The coop mod's once-per-run line goes, and it gains none.
- **E3, the events** (about a day): §2's `@turbo`, `@action` and `@savenow` lines, the menu's rows refusing during a
  replay, `SOA_ACTION` and `SOA_SAVE_NOW` ignored during one.

## 5. Not here

- **`SOA_PACE` and `SOA_CLOCK`**, host timing that moves where input lands in guest time, as `threads` and `speed` do.
  They are diagnostics, no tool records with them, and they write no guest memory. Named in the line if a tool ever
  replays with them.
- **`SOA_STALL`**: since M19 a stall is not counted as guest time (`docs/ARCHITECTURE.md`'s `clock.c` row).
- **A frame-for-frame comparison of two replays.** A pad replay is a live run (`si.c:264-279`, PLAN D4); every Done
  below is a same-run check.
- **Mid-run option changes and hot reload** (M15): options are fixed when a mod loads.
- **The loopback control channel** (T12c), which stamps its commands into this track when Q10 builds it.

## 6. Done

Each line names its command and the mutation that proves the check can fail.

**E1**
1. `test_padrec.py`: with `SOA_PAD_STRICT=1`, a recording whose config extra says `encounters=double` replayed with
   `encounters=half` exits 11 before its first report and the log names both entries; the same pair without the
   switch runs to its end and names both; strict with an equal line runs; strict on a v1 file exits 11. *Mutation:*
   the switch read but never acted on, and the first case runs to its end.
2. `test_padrec.py`: with `SOA_BATTLE_FORCE` set, the line holds `battle_force=` verbatim; with `SOA_POKE`, `poke=`
   and eight hex digits that change when one poke's value does; with neither, the line is byte-for-byte today's (the
   existing capped-line test).
3. On this PC: a 600-frame headless run with the encounter-rate mod, `SOA_ENCOUNTERS=double` and `SOA_PAD_RECORD`,
   then its replay with `SOA_ENCOUNTERS=half` and `SOA_PAD_STRICT=1`, exits 11 naming both; with `double` it runs to
   its end. `test_scenario.py` holds `EXIT_MEANINGS[11]`; `test_soak.py` holds `check --strict` failing a log with
   the mismatch line and asking without the flag.

**E2**
4. `test_padrec.py`: a recording made with `SOA_PAD2` driving pad 2 (read twice a frame, as a filter would) holds
   `@pad2` lines at the frames it changed; its replay with no `SOA_PAD2` gives `si_read_pad(2)` the same states at
   the same frames, and 0 before the first and after an `@pad2 off`. *Mutation:* one `@pad2` line deleted, and the
   comparison fails at that frame.
5. `test_padrec.py`: a recording with `lb` and `view+rs` held from the script holds `@host` lines; on replay
   `si_host_buttons()` gives them at those frames and the chord handler is called 0 times.
6. On this PC: the coop mod with `SOA_COOP=1` and a `SOA_PAD2` script through the `battle` scenario's first battle
   (`SOA_SPEED=3`, from about frame 9811), recorded; the replay, with no pad 2, shows in its `[si]` log (written after
   the filter, `si.c:944-948`) each recorded pad-2 press on port 1 at its frame, on a co-op member's turn. *Mutation:*
   one `@pad2` press deleted from the file, and the `[si]` log no longer shows it at that frame.

**E3**
7. `test_tick.py`: a turbo flip recorded at frame F replays at frame F, before the callbacks; the menu's toggle during
   a replay takes nothing.
8. On this PC: a short run with `view+rs` in `SOA_PAD` at a frame, recorded; its replay, with no script, logs
   `[turbo] frame F: on` at the recorded frame. *Mutation:* the `@turbo` line deleted, and no `[turbo] frame` line
   follows.
9. On this PC: part G's card to the field (HANDOFF's recipe, on a scratch copy of `card-partG.raw` restored between
   the two runs), `SOA_SAVE_NOW=3300` and the save presses, recorded; the replay, with neither knob, logs
   `[savenow] frame F: the save menu asked for` at the recorded frame and its card verifies READY. Then
   `SOA_ACTION=warp:103a@3300`, recorded, and its replay warps at the recorded frame. *Mutation:* the `@savenow` line
   deleted, and no `[savenow]` line follows.
10. On this PC: a recording whose `@action` line is moved by hand to frame 100 (the title screen) is refused there and
    logged as leaving the recording; with `SOA_PAD_STRICT=1` the run exits 11 at frame 100.
