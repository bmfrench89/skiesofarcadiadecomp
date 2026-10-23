# T9: named game addresses, held to the game's own code

Written 2026-10-22 for the owner's answer that day (PLAN-NEXT D-43: the gameplay core, T9 first), from
[PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) T9 (its "until M6 lands" is past: M6 landed 2026-10-14), the
research documents' address tables, and the mod API. The code was mapped first, at 7976cf6.

**Built 2026-10-22** (FINDINGS "T9"): Done lines 1 to 5. *As built:* 68 names, not about a hundred -- each went in
only with an instruction `find` turned up, and the DOL tables whose counts the research does not give wait for T3;
a line's `ref` may be `REF+OFF`, an instruction reaching the block the name sits OFF bytes into, since the code
reaches gold, the field state and the inventory lists only through their blocks' bases; and
`tools/soa/gamedata.py` reads the file rather than being generated from it.

**Why.** Every mod so far names game memory by raw hex: `0x803474BC` in `mods/encounter-rate`, `0x80346E4C` in
`mods/autotext`, a dozen in `examples/mods/lab`, and copies in `mod.c`, `tick.c`, `soak.py` and `sct.py`. The
research found about a hundred such addresses, each with the instruction that reaches it, but nothing holds a name
to its address, so a wrong digit is found only when a mod does nothing in the game. T9 gives them one home and
names, generates what mods and tools read from it, and proves each address against the code that uses it. It comes
before T3 and R0 "so nothing new is written against raw hex" (PLAN-GAMEPLAY-MODS 1235).

## 1. What is there

- **`config/names.txt`** names functions only (186, `address<TAB>name<TAB>evidence`, held by `test_card.py` to
  `functions.tsv`). **`config/symbols.txt`** lists 9,279 data objects with sizes and kinds (`data:4byte` ...), every
  game datum a `lbl_`.
- **The mod API** (`runtime/soa_mod.h`): `read8/16/32/f32/bytes` and the writes, big-endian, refusing what a
  `patches.txt` line would; and five named state reads (`scene`, `field_state`, `map`, `story_flag`, `frame`).
- **`patches.txt`** targets: `0x` and eight lowercase hex digits, `[0xADDR]+off` through a pointer, `+z*N` with
  `for z=A..B`, widths `u8`..`s32` (mod.c `parse_target`). No names.
- **No test re-finds a data address from code.** The tools to do it exist: `tools/soa/dol.py`, the decoder in
  `tools/soa/ppc/`, and `matchcheck.sda_bases`, which reads r2 and r13 out of `__init_registers` -- most game words
  are small data, reached as `d(r13)`.

## 2. What T9 adds

- **`config/gamedata.txt`, the one home.** A line a name:

  ```
  # name                 address     type          ref         evidence
  encounter.table        0x803474BC  ptr:ect_zone  0x800C25D8  encounters.md:99 (stw -29284(r13))
  encounter.steps        0x80346D28  u32           0x800C1FE8  encounters.md:64 (stw -31224(r13))
  ship_battle.pending    0x803472E4  u32           0x80147E88  ship-worldmap.md:124 (stw -29756(r13))
  ```

  and records for what sits behind an address:

  ```
  record ect_zone 132
    rate     2   u16  0x800C1FF8
  ```

  (The three are real: each `ref` is the instruction the research quotes. Every other line is found the same way
  when the file is written, and a line whose instruction cannot be found is left out.)

  Types are `u8`..`s32`, `f32`, `ptr`, `ptr:RECORD`, `RECORD[N]` and `bytes[N]`. **`ref` is required:** the address
  of an instruction in the DOL that reaches the name's address, a `d(r13)` or `d(r2)` access, or a `lis`/`addi`
  pair (the use given; its `lis` found within the block before it). A record field may give its own `ref`, an
  instruction whose displacement is the field's offset modulo the record's size: the rate is read as
  `lhz -130(table+zone*132)`, zones counting from 1, and -130 is 2 less one record.
- **The test that holds them to the code** (`test_gamedata.py`): every `ref` is decoded from your DOL and must reach
  the name's address, every field `ref` must carry its offset (modulo the record's size), and every address must lie inside a data object of
  `symbols.txt` big enough for its type. It needs the disc's DOL and skips without it; a disc-free half holds the
  file's grammar, unique names, known types and record sizes. *Mutation:* one digit of one address, or of one
  offset, changed in a copy of the file fails it, naming the line.
- **Generated from it, and held current by a test** (as `MODDING-API.md` is):
  - **`runtime/soa_gamedata.h`** beside `soa_mod.h`: an address and type per name, and accessors over the API's
    reads and writes -- `soa_scene(api)`, `soa_party_character_hp(api, ch)`, `soa_battle_context_gold(api)` --
    which follow pointers themselves, so a DLL mod needs no `patches.txt` syntax for them. Never a host struct.
  - **`tools/soa/gamedata.py`**: the same names for tools (`soak.py`, `sct.py` and the checks move to it).
  - **`docs/MODDING-NAMES.md`**, the reference a person reads: name, address, type, what it is.
- **`patches.txt` takes names** wherever it takes an address: `encounter.table`, `party.character[1].hp`,
  `battle.context.gold` (through the pointer: `[0x80347390]+52`), with the name's type as the width unless one is
  given. Names resolve at load through a table generated into the runtime from the same file; an unknown name is
  refused with the line, as a bad address is today.
- **The first names** are the ones the research marks [V] or a run confirmed, about a hundred: scene and field,
  warps and maps, encounters and the battle request, story flags and variables, party, inventory and gold, the save
  request, the battle's actors, context, commands and phase, the RNG seed, the frame counters, and the DOL's tables
  (spells, gear, items, ships, AI, chests, opcodes) as base and record size for T3. An address the research marks
  [I] goes in only once a `ref` proves it.
- **The existing copies** in `mods/`, `examples/mods/lab` and the tools are switched to names where a name exists;
  `mod.c` and `tick.c`'s own words stay as they are (the runtime is not a mod) but are checked against the file.

## 3. Not in T9

T3's table layouts (it reads `gamedata.txt`'s bases and re-derives the rest), struct fields the research has not
reached, and any name for a function (that is `names.txt`).

## 4. Done

1. **Every name re-found from the code:** `test_gamedata.py` passes with the disc's DOL, every line's `ref` reaching
   its address and every field `ref` its offset. *Mutation:* an address changed by one, and separately an offset,
   each fail it with the line named.
2. **The generated files current:** the header, the Python module and `MODDING-NAMES.md` regenerate byte for byte.
   *Mutation:* a name added to the file without regenerating fails it.
3. **Names in `patches.txt`:** on the fake guest (`tools/mod.py test`, `test_mods.py`), a patch by name and the same
   patch by address write the same bytes, a field through a pointer included; an unknown name is refused with its
   line.
4. **In the game:** `mods/encounter-rate` rewritten with names gives the same rate words at `a116a`'s load as with
   addresses (a peek, as M6's run did), and a DLL using the header reads the party's gold equal to a `SOA_PEEK`.
5. **The suite and the copies:** the full suite, and every mod and tool that named an address by hex and has a name
   now uses it, `mods/` built and loaded.
