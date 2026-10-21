# M16: options each mod declares

Written 2026-10-21 at main 15652b7, from the sketch in
[PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) §F ("M16") and
[research/plan-gaps.md](../research/plan-gaps.md) ("Options each mod declares"). PLAN-NEXT §0's mod
framework track, item 3 (D-38).

**Status: done 2026-10-21** but for M8's page (section 7), every Done line met on this PC; evidence in
FINDINGS "M16".

**Why.** Every comfort and combat slice planned after it is a slider or a preset. Today a mod's
setting is a switch the port itself must know: `settings.c`'s `k_settings` names `encounters`,
`autotext` and `coop` for the three DLL mods in `mods/`, and a patches-only mod has no setting at all
(`examples/mods/encounter-scale` hard-codes its factor, 0.5). M16 lets a mod declare its options in its
own `mod.ini`, so the port needs no line per mod, and lets the player, a check or M8's settings page set
them by one rule.

## 1. The declaration

In `mod.ini`, one line per option, manifest 2 only (a value is keyed by the mod's id):

```
option = factor enum 0|0.25|0.5|1|2 0.5
option = rate int 0..127 32
option = scenes bool 1
option = tag string field
option = seed seed 12345
```

`option = NAME TYPE [DOMAIN] DEFAULT`:

| Type | Domain | A value |
|---|---|---|
| `int` | `LO..HI`, signed 32-bit decimals, LO no more than HI | a decimal in the range, `-` for a negative, no leading zero |
| `bool` | none | `0` or `1` |
| `enum` | `A\|B\|C`, 1 to 16 choices, each 1 to 31 of `A-Z a-z 0-9 . _ + -`, no repeats, under 128 characters in all | one of the choices, spelled alike |
| `string` | none | 1 to 63 of `A-Z a-z 0-9 . _ + -` |
| `seed` | none | any 32-bit number, `0x` and hex digits or decimal (`patches.txt`'s values) |

NAME is a lowercase letter, then lowercase letters, digits and `_`, under 32 characters, once per
mod; a mod declares at most 16. Any fault refuses the whole mod with the file and line, as every
`mod.ini` fault does: an unknown type, a malformed domain, a default outside it, a repeated name, a
seventeenth option, an `option` in a manifest 1 file.

The characters are narrow on purpose: a value goes into `patches.txt` text and into the recording's
`# config` line, so it may hold no space, `#`, `$`, `=`, `,`, `[`, `]` or `;`.

## 2. Values, and where they come from

- **soa.ini:** `ID.NAME = VALUE`, as in `encounter-scale.factor = 1`. `settings.c` cannot check it
  (no mod is loaded yet), so it folds the line into `SOA_MOD_OPT` and says so; the mod checks it.
- **The environment:** `SOA_MOD_OPT`, entries separated by spaces, each `ID.NAME=VALUE`:
  `$env:SOA_MOD_OPT = 'encounter-scale.factor=0 map-log.scenes=0'`. Checks set `SOA_SETTINGS=0` and
  never read soa.ini, so this is how a check sets an option. An entry here beats soa.ini's line for
  the same key, as every environment switch beats soa.ini; the override is said.
- **When the mod loads,** each entry naming its id must name a declared option and a value in its
  domain, or the mod is refused whole, naming the entry. A mod run with defaults when a value was
  asked for is a mod doing something else, the same reason a bad patch line refuses the mod.
- An entry for an id no mod has is said once after loading ("does nothing"); one that is not
  `ID.NAME=VALUE` is said and passed over. A key given twice in `SOA_MOD_OPT` refuses that mod
  (which one was meant cannot be known).
- A value is kept in one spelling: an int, bool or seed as a decimal (`0x3039` and `12345` are one
  seed), so a recording names it one way.

## 3. In patches.txt

`${NAME}` anywhere on a line is replaced by the option's value before the line is read:

```
on_map_load  u16    [0x803474bc]+2+z*132    *= ${factor}   for z=0..7
```

A `$` that does not begin `${NAME}` of a declared option refuses the mod at that line, and so does a
line longer than 511 characters once replaced. The replaced line is then read by the same rules as
any other, so a value that makes a bad patch is refused as one.

## 4. For a mod.dll

Appended to `SoaModApi` (`runtime/soa_mod.h`; `SOA_MOD_API_VERSION` stays 1, since the table grows
only at the end and a mod checks `api->size`, as M3b, M3c, M4, CH1 and P10a did):

```c
const char* (*option)(const char* name);            /* the value as text, or NULL */
int (*option_int)(const char* name, int64_t* out);  /* int, bool or seed: 1 and *out; else 0 */
```

Each answers for the mod whose `soa_mod_init` or callback is running, and NULL or 0 for a name it did
not declare or a call from anywhere else. The text lives as long as the run.

## 5. The recording

A mod with any option away from its default is named with its values after its hash, in the order
declared: `mods=encounter-scale@1.0:<hash>[factor=0]`. A mod at its defaults reads as before, so
every existing recording still matches. The defaults themselves are `mod.ini` bytes, already in the
hash. The mods past the line's room fold the same text into their one hash.

## 6. Done

Each line names its check and the mutation that proves the check can fail. Mutations are made by hand,
the check run and seen to fail, and the change put back.

1. **Every type reads back.** `test_mods.py`: a DLL declaring one option of each type logs what
   `option` and `option_int` return, unset (the defaults) and set through `SOA_MOD_OPT` (the values,
   a seed given as `0x3039` reading 12345); an undeclared name gives NULL and 0. *Mutation:*
   `api_option` answers the default whatever was set.
2. **A bad declaration refuses the mod with its line.** `test_mods.py`, one case per fault in §1.
   *Mutation:* drop the check that the default is in the domain.
3. **A bad value refuses the mod, naming the entry.** `test_mods.py`: out of range, not a choice, an
   undeclared name, a key twice; and an entry for an id no mod has is said and loads the rest.
   *Mutation:* skip the domain check on values.
4. **`${NAME}` is the value.** `test_mods.py`: the shipped `encounter-scale` example, with `factor`
   declared, halves the fake guest's rates by default, zeroes them with `factor=0`, and leaves them
   with `factor=1`; an undeclared `${x}` and a bare `$` are refused with the line. *Mutation:* replace
   with the default instead of the value.
5. **soa.ini reaches SOA_MOD_OPT, the environment winning.** `test_settings.py`. *Mutation:* let
   soa.ini's line replace the environment's entry.
6. **The recording names what is not the default.** `test_mods.py`'s `describe`: `[factor=0]` after
   the hash with the value set, nothing with it at its default. *Mutation:* leave the values out.
7. **On this PC, in the game.** `encounter-scale` with `SOA_MOD_OPT=encounter-scale.factor=0` logs
   each zone's rate `-> 0` at a map load (and `-> half` with nothing set); `map-log`, given
   `option = scenes bool 1`, logs no scene change with `map-log.scenes=0`. Recorded in FINDINGS.

## 7. Not in M16

- **M8's settings page.** It does not exist yet; when it does it reads the declarations through
  `mod.c`, which keeps them, and draws a page per mod with no code of the mod's.
- **Moving `mods/`'s three DLL mods onto declared options** (M16b, with P1's presets). Their switches
  (`SOA_ENCOUNTERS`, `SOA_AUTOTEXT`, `SOA_COOP` and soa.ini's `encounters`, `autotext`, `coop`) are
  documented, recorded and tested as they are; moving them changes what a player's soa.ini says.
- **A Lua host, hot reload of options mid-run** (M15), and P6's per-map seed, which still needs a DLL.
