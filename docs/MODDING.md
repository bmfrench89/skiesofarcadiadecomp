# Making mods

A mod changes what the game does without changing the port. It is a folder holding a `mod.ini` and
either a `patches.txt` (memory writes, no code) or a `mod.c` built into `mod.dll` (`mod.so` off
Windows) on the port's mod API, or both. This page is the guide; the API reference, member by member,
is [MODDING-API.md](MODDING-API.md), generated from `runtime/soa_mod.h`. The kit is `tools/mod.py`.

**Mods must not carry the game.** A mod is your text and your code. `tools/guard.py` refuses anything in
a mod folder that is not text, and no file taken from the disc belongs in one.

## A first mod in fifteen minutes

You need the port built (README), the game extracted (`extracted/sys/main.dol` is what `check` reads), and
Python.

1. **Make it.** `python tools/mod.py new mymods/hello` writes `mymods/hello/mod.ini` and a
   `patches.txt` with one working line: the step counter at `0x80346D28` held at 0 in the field, so no
   random battle can start (the same line as `examples/mods/encounters-off`).
2. **Check it.** `python tools/mod.py check mymods/hello` loads it with the port's own loader against
   your DOL, without starting the game, and prints what the port would: `loads`, or the file, the line
   and why not. Change the address to `0x8034d28` and run it again to see a refusal.
3. **Try it on the fake guest.** `python tools/mod.py test mymods/hello set 803475cc 6 set 80346d28 63
   frame get 80346d28` runs it on a stand-in for the game: the scene word set to the field, the counter
   to 0x63, one frame end, and the counter read back -- `80346D28=00000000`. No disc is needed, so a
   mod's own CI can do this.
4. **Play it.** Point the port at the folder above your mod: `mods = C:\path\to\mymods` in `soa.ini`, or
   `$env:SOA_MODS = 'mymods'`. The log says `[mod] loaded Hello ...` and lists what it writes. Walk
   around a field: no random battle comes. Battles the story starts itself still happen.

## Finding an address

The game keeps its state in fixed words, which a mod reads and writes. About seventy have names, each
proved against the instruction in the game's code that reaches it: [MODDING-NAMES.md](MODDING-NAMES.md)
lists them, from `scene` (6 the field, 7 a battle) and `field.state` to the party's records, gold and
inventory, the battle's context and the encounter table. A `patches.txt` line may give a name wherever
it gives an address -- `once party.gold = 50000`, `once party.character[1].hp = 999`, and
`on_map_load encounter.table[z].rate *= 0.5 for z=0..7` -- with the name's own width unless the line
gives one. A DLL mod includes `soa_gamedata.h` after `soa_mod.h` and calls
`soa_party_gold_get(api, &gold)` and the like, which follow pointers themselves.

The research behind them is in `docs/research/` (`encounters.md` for the battle words) and
`docs/FINDINGS.md`. To find your own, watch a word while you play: `SOA_PEEK=0x80346D28@1000-1100`
prints it at each of those frames, and `SOA_POKE=2000:0x80346D28=0x186A0` stores a value once to see
what the game does with it (both in README's table of switches). Addresses are the console's, big-endian,
in its 24 MB of RAM (`0x80000000`-`0x817FFFFF`).

## patches.txt

One write per line, applied at the end of a frame:

```
# trigger     [width]  address                  value         [for z=A..B]  [when condition...]
every_frame            0x80346d28           =   0                           when scene=6
on_map_load   u16      [0x803474bc]+2+z*132 *=  0.5           for z=0..7
once          u8       0x80310b40           =   0x10                        when map=116a
```

- **Triggers:** `every_frame`; `once`, the first frame its conditions hold; `on_map_load`, the first
  frame the field runs after a load -- including the reload after every battle, which puts the map's
  words back as the disc has them.
- **Widths:** `u32` (the default), `u16`, `u8`, and `s32`, `s16`, `s8` for signed values. A write is
  aligned to its width.
- **Addresses:** `0x` and exactly eight lowercase hex digits; or `[0x803474bc]+2`, the word at that
  address taken as a pointer, plus an offset. `+z*N` steps through a `for z=A..B`, one write per z (up
  to 64).
- **Values:** `= value`, hex or decimal, negative for a signed width; or `*= k`, which multiplies what is
  there by k (up to four decimals), clamped to the width, on `on_map_load` only, and never twice over a
  word a reload left as the patch made it.
- **Conditions,** all of which must hold: `scene=N`, `state=N`, `map=NNNx`.
- **Refused, with the line:** a misspelled address, one in the hardware window, outside RAM, unaligned or
  inside the game's code; a value the width cannot hold; an unknown trigger or condition. A mod with any
  fault is not loaded at all: half a mod is worse than none.

## files.txt: the game's files

A mod may also change which files the game reads from its disc, without touching your disc image: a
`files.txt` beside `mod.ini`, one line a file (docs/specs/disc-layer.md §3.8, T1):

```
# verb   path on the disc       a file in this folder, or (alias) a path on the disc
replace  title/t00.dat          build/t00.dat
add      field/me099z.sct       build/me099z.sct
alias    field/a045a.mld        field/a002a.mld
```

- `replace` serves your file where the disc's was; `add` puts a new file in a directory the disc already has;
  `alias` gives a disc file a second name, which reads the same bytes. Paths match case-insensitively.
- The port rebuilds the game's file table at boot and serves your files past the disc's end; the game finds
  them through its own disc code. Every other file stays exactly where it was, which the self test checks
  with the game's own lookup.
- A mistake -- a path that is not there, an `add` of a name that is, an alias of an alias -- refuses the mod
  with its line. Two mods placing the same path stop the run (exit 9) naming both: remove one.
- A replacement `.mld` or `.sct` is a game file, built on your own machine from your own disc; mods in this
  repository carry only aliases, so they hold none of the game's bytes. `examples/mods/map-alias` gives the
  missing map 045 map 002's room and script: a warp to 045a lands in 002a's room.
- Text deltas (`delta`) and per-map swaps (`swap`) are planned (I7, I8) and refused for now.

## Options a player sets

A manifest 2 `mod.ini` may declare up to 16 options (docs/specs/mod-options.md):

```
option = factor enum 0|0.25|0.5|1|2 0.5      # NAME TYPE [DOMAIN] DEFAULT
option = strength int 0..100 50
option = scenes bool 1
```

The types are `int LO..HI`, `bool`, `enum A|B|C`, `string` and `seed`. A player sets one in `soa.ini`
as `ID.NAME = VALUE` (`encounter-scale.factor = 1`); a check sets it as
`$env:SOA_MOD_OPT = 'encounter-scale.factor=1'`. `patches.txt` reads one as `${factor}`; a DLL reads
one with `api->option("factor")` or `api->option_int("strength", &v)`. A value outside its domain
refuses the mod and names the entry. A recording names the values that are not their defaults.
`examples/mods/encounter-scale` and `examples/mods/map-log` each declare one.

## Order, and two mods on the same bytes

Mods load in folder-name order unless `mod_order` in `soa.ini` (`SOA_MOD_ORDER`) lists them:
`mod_order = map-log, encounter-scale, -lab` loads those first, in that order, and `-lab` turns `lab`
off. When your patch can write bytes another mod's patch writes, on a frame where both can apply, the
later mod is refused and both lines are named -- unless both write the same value there, or one says
`overrides = OTHER-ID` in its `mod.ini`, which also loads it after the other so its write lands last
(docs/specs/mod-order.md). A DLL's writes are made at the call and are not compared.

## A native mod

`python tools/mod.py new mymods/native --dll` writes a `mod.c` that logs each map entered;
`python tools/mod.py build mymods/native` compiles it into `mod.dll` with the compiler the port uses
(no developer prompt) and refuses a library built for another machine -- a 32-bit `mod.dll` would
otherwise fail in the port as a bare "error 193". Then `check` and `test` as above.

The port calls your `soa_mod_init(api, version)` once, before the game's first instruction. Register
your callbacks there and return 0; return anything else, after saying why with `api->log`, to refuse
yourself. The callbacks, and where each runs:

| Callback | When | What it may do |
|---|---|---|
| `on_frame_end` | inside the copy that ends each frame | read and write memory only |
| `on_safe_point` | the top of the game's main loop, nothing started | anything, `call_guest` too |
| `on_map_loaded` | at a safe point, once per map entered (reloads too) | anything |
| `on_scene_change` | at a safe point, when the scene word changes | anything |
| `pad_filter` | every controller read, before the game sees it | change the pad |
| `projection_filter` | each new projection, before a vertex uses it | change the six numbers |
| `texture_provider` | each texture decode | hand back a replacement image |
| `on_damage` | each damage the battle works out (R0) | return the damage, 0-9999 |
| `on_heal` | each Recover-HP value: a heal spell, an item, Blue Rogues' heal (R1) | return the heal, 0-9999 |
| `on_enemy_spawn` | each enemy made, before the battle starts | scale the actor (never its record: every enemy of the kind shares it) |
| `on_enemy_action` | each enemy's choice, its command record filled | return the command type; edit the record |
| `on_turn_order` | once a round, the order just set | reorder it (it must stay distinct slots 0-11, ending at -1) |
| `on_spirit_gain` | the round's spirit, before the gauge's limit | return the gain |
| `on_escape` | each Run, the party's or an enemy's | return nonzero to escape |
| `on_rewards` | once a victory, before the game pays out | change the EXP, gold and magic EXP |
| `on_effect` | each effect applied (damage, heal, status...), before it is | change the effect or value, or return nonzero to cancel it |
| `on_round_end` | each round's end, once regen, poison and spirit are applied | anything a frame end may |
| `on_ship_damage` | each ship battle damage, before the game's x10 | return the damage |
| `on_save` | when the save menu opens (X2) | write your chunk for the save file; return its length, or -1 for none |
| `on_load` | when a save is loaded, after the game has restored it | read your chunk, or learn the save holds none |
| `on_new_game` | at New Game, and once at boot | start your state afresh |

The battle's events run inside the game's own call, so they read and write memory only, as a frame
end does. `SOA_BATTLE_LOG=1` logs every one, and the run report counts each event's calls, how many a
mod changed, and each mod's time in it. **A mod that crashes inside one stops the run** (exit 10), and
the log names the mod and the event; nothing continues half-done (docs/specs/battle-events.md).

**Save now** (M7a): the menu's "Save now" opens the game's own save menu wherever the field is quiet, and a
Continue lands where the save was made. A mod that writes saved game state should do it after `on_load`,
which a Continue from such a save calls too.

**Keeping state in the save** (X2, docs/specs/save-extension.md): `on_save`, `on_load` and
`on_new_game` give your mod a chunk of its own inside the game's save file, filed under your manifest 2
`id` (a mod without one cannot keep a chunk). About 9.7 KB is shared by every mod. A save made with
mods still loads in the unmodded game and in Dolphin, which ignore the chunks; the chunks of a mod
that is not loaded are kept and written back at the next save, and loading a save says which mods it
holds data for that are missing. `python tools/savext.py show <card>` lists a card's chunks, and
`SOA_SAVE_LOG=1` logs each save and load.

**A flag of your own** (T2, docs/specs/content-ids.md): never pick a story-flag number by hand, since
another mod may pick the same one. Declare `claim = flag <name>` in your manifest 2 `mod.ini` (a name is
lowercase letters, digits, `.`, `_` and `-`), and ask for the number with `api->claim("flag", "<name>",
&number)`. The port numbers claims from 24576 (lower flags are the game's own), records them in `mods.lock` beside the mods, gives the
same number every run, and never hands a number out twice, even after its mod is removed. Saves carry
the table, so a save loaded on an install that numbered a claim differently says so.

**The rules** (each one the port enforces or depends on):

- Everything runs on the game's CPU thread. Never call the API from a thread of your own.
- Registration closes when `soa_mod_init` returns; a later one returns 0 and is never called.
- `on_frame_end` runs inside the frame's copy: memory writes only, never `call_guest`.
- `call_guest` calls one of the game's functions, from a safe-point, scene or map callback only, never
  inside an interrupt handler; every register comes back as it was.
- The table only grows at its end. Check `api->size >= SOA_MOD_HAS(member)` before using anything
  appended after `log` (pad filters, projections, textures, `call_guest`, host buttons, pad 2, options,
  the battle's events):
  an older port may not have it, and a newer one always does.
- Pointer patches belong on load triggers. In a battle `0x803474BC` still names the field's table while
  its memory holds something else, so a write through it every frame lands in the battle's data.
- Memory writes are refused, returning 0, outside RAM, unaligned, or inside the game's code -- the same
  refusals as a `patches.txt` line.

## Recordings and replays

A recording (`SOA_PAD_RECORD`) names every mod it was made with, by id, version and a hash of its files,
in load order, with any option away from its default. Replay it with the same mods and it plays the same;
the port says when the mods differ, and with `SOA_PAD_STRICT=1` refuses the replay. Pad 2 and the host
buttons (LB, View, the stick clicks) are in the recording too, as `@pad2` and `@host` lines, so a mod that
reads them replays as it played; and so are turbo, the menu's Save now and its Debug actions (`@turbo`,
`@savenow`, `@action`), which a replay applies at their frames.

## What the kit can and cannot tell you

`check` and `test` run the port's own loader, so a mod they load is one the port loads, with the same
refusals in the same words. They cannot tell you what it does in the game. The fake guest has no game:
memory is what your script stores, the one function `call_guest` reaches is a stand-in at `0x80003100`
that adds two numbers, and nothing draws. Play the game to see a mod work, with `SOA_PEEK` on the words
it writes. The fake guest grows with the API; `tools/soa/modkit.py` is the driver, shared with the
port's own tests.

## Examples

- `examples/mods/encounters-off`: one patch, no options.
- `examples/mods/encounter-scale`: a pointer, a `for` run, `*=`, and an option.
- `examples/mods/battle-tally`: the battles won since New Game, counted through `on_rewards` (R1) and
  kept in the save file through `on_save` and `on_load` (X2).
- `examples/mods/damage-double`: every blow doubled through `on_damage` (R0); `SOA_BATTLE_LOG=1` and
  `python tools/battle.py check <log> --double` prove it.
- `examples/mods/map-alias`: two aliases in a `files.txt`, map 045 given map 002's room and script.
- `examples/mods/map-log`: the native template, with an option.
- `mods/encounter-rate`, `mods/autotext`, `mods/coop`: the native mods the port ships.
