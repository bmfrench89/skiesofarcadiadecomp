# R3 and R4: difficulty presets, boosts and assists

Written 2026-10-27 at main 48de35c for the owner's D-46 (PLAN-NEXT §0: "Narrow to mods"; milestone 3, "a spec for
R3 and R4, then R4, then R3"), from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) R3 and R4,
[research/battle-system.md](../research/battle-system.md), and R1's events as built
([battle-events.md](battle-events.md), `runtime/battle.c`). Each site below was read again in the translated C of
48de35c's build; the effect tables were read from the player's DOL.

**Built 2026-10-27** (FINDINGS "Battle mods"): Done 1 to 3; 4 is the owner's. *As built:*
- the no-KO assist holds eleven effects beyond the plan's three (section 2: every applier that reaches the KO
  function through effect 0's);
- the record's max HP is scaled for the battle and put back after it (section 4), a review finding: the boss
  music reads it;
- the check's switch holds the characters' HP between battles; its first form, written to the actors in the first
  round, stalled the story's first battle (section 3).

**Why.** Milestone 3 is the first thing a player gets from the mod platform, and the owner asked for its
difficulty and boosts first. R1 gave mods every event these need; M16 gave them options a player sets in `soa.ini`.
What is missing is the two mods, and the checks that they do what they say.

## 1. What is there

- **R1's events** (`soa_mod.h`), each run in load order inside the game's own call: `on_rewards` once a victory,
  before the payout; `on_escape` after each Run's roll (slots 0-3 the party, 4-11 the enemies); `on_damage` after
  `fn_800108EC`; `on_effect` before each applied effect, with a cancel and the effect and value written back (to the
  message and, where it still matches, the target's work+60, so the pop-up and the action's end agree);
  `on_enemy_spawn` after `fn_800770B8` fills an enemy actor from its record; `on_round_end` after sub-state 0 of
  the round's end moves on. `SOA_BATTLE_LOG=1` logs each, before and after the mods (`[battle] ... rewards exp A ->
  B gold C -> D magic exp E -> F`, `spawn actor X record Y hp A -> B`, `damage B -> O -> R`, `effect E value V on
  slot S -> effect E' value V'`, `escape slot S A -> B`), and at each safe point in a battle the HP, MP, status and
  SP that changed.
- **M16's options:** `option = NAME TYPE [DOMAIN] DEFAULT` in `mod.ini`; `soa.ini`'s `ID.NAME = VALUE` or
  `SOA_MOD_OPT`; `api->option` and `api->option_int` in init. A value outside its domain refuses the mod.
- **The shipped mods load by default:** Setup installs every folder of `mods/` and writes `mods = mods`
  (`player_build.py`). So a shipped mod at its defaults must change nothing, and here it registers nothing either:
  the battle sites' "changed by a mod" counts stay 0 and no handler runs.
- **The fields** [V, battle-system.md §1.2 and §1.4, re-read]: an actor is 276 bytes, slots `0x80309DE4[12]`;
  HP +20 and max HP +24 (s32); Will +130 (magic power), Quick +136 (the turn order's key); Attack +148, Defense
  +150, MagDef +152 (s16); base copies of +128..+137 at +232 and of +148..+157 at +242; status +28 (`0x100`
  unconscious, `0x10000` no Spirit). The context `*0x80347390`: max SP +6, SP +8, SP after reservations +10 (s16);
  EXP +48, gold +52 (s32); magic EXP +1 (s8). The phase `0x8034733C`: 1 the party's input, 2 the AI and the order.

## 2. What knocks a party member out [V]

- **Damage:** effect 0's applier (`fn_8002DC14`) does `HP = max(0, HP - value)` (`0x8002DD00`) and calls the KO
  function `fn_8002BC4C`, which sets `0x100` when HP is 0 or less.
- **The appliers that reach `fn_8002BC4C`,** of the 79 in `0x802DBB10` (every translated body, its direct calls
  followed to the end; the only indirect call on the way is the KO function's own drop roll, `fn_8002BA8C`, after
  the KO and for slots 4 and up):
  - directly: 0, 5 (`fn_8002DA88`, Unconscious, HP = 0), 6 (`fn_8002DA24`) and 68 (`fn_8002C4A0`), the last two
    calling effect 0's applier as well;
  - through effect 0's applier, called from inside their own: 4, 8, 17, 44 (drain), 61, 62, 65, 66, 69, 70 and 72.
    `on_effect` sees these under their own number, never as effect 0. Effect 66 (`fn_8002C61C`, Blue Rogues) heals
    a party member (`on_heal` sees that branch) [I: its damage branch is for enemies].
  - No other applier reaches it.
- **A death that lands** [V, a review finding]: calculator 5 rolls, and on a hit sets the target's hit result to
  KO (5, `0x8006AC3C`-`0x8006AC50`); calculator 6 (`fn_8006AB6C`), on a susceptible target without `0x40`, does the
  same and works out no value, so the message carries the resolver's placeholder -1 (`0x800683E0`); only its other
  branch works out damage. The game's own rewrite of 6 and 68 to effect 0 under `0x40` (`0x8002BE78`-`0x8002BEC8`)
  never meets a landed death: under `0x40` calculator 6 takes its damage branch.
- **Lethal poison** does not lower HP when it ticks. Sub-state 0 of the round's end works out `2 x Vigor`, and when
  `HP - damage <= 0` sets bit `1 << slot` of the word `0x80346BE8` (`0x8006FF04`-`0x8006FF14`) instead of sending the
  damage; then, in the same loop, `fn_80010474` brings each actor's low-HP bit (`0x8000`, HP at or below a quarter
  of the maximum) into step (`0x800700D0`). Sub-state 0 moves on to 50 and 50 to 51 (`0x80070128`, `0x80070160`):
  `on_round_end` runs at the first move, two calls before 51 reads the word. A nonzero word sends the sub-state to 10
  (`0x800701A0`), which for each slot 0-11 with its bit set sends an effect-0 message and starts motion 14
  (`fn_80081168`, `0x80070370`-`0x800703A4`); sub-state 11 clears a slot's bit once its motion has finished
  (`0x800703D8`-`0x80070418`), and goes back to 1 at the first that has not, its bits left for the next round's
  sub-state 0 to zero (`0x8006FE18`). A bit cleared before 51 reads the word is a slot sub-states 10 and 11 pass
  over.
- **Not established:** whether stone (`0x4000`, three rounds) on every member counts as a defeat; the no-KO
  assist leaves stone alone.
- **A battle the story lets you lose** [V, a review finding: `tools/sct.py` over the field scripts, `epevent.evp`'s
  records]: an event battle's defeat condition (ctx+4, from its record's +35) offers Try again at 1, sends the
  game-over script (`ME090A.sct`) at 0, and at 2 returns to the field with the story carrying on (result 3,
  `fn_8006F424`, `fn_80009FD8`). Of the 235 event battles the scripts request, 210 have 1, 24 have 0 and one has 2:
  event battle 26 at the home base (`me017h`, `me017i`), whose escape condition (1) also takes Run away. With no
  knock-outs it could end only in a victory, so the assist stands down there.

## 3. R4: `mods/battle-boosts`

`manifest = 2`, `id = battle-boosts`. Options, every default the game's own:

```
option = exp enum 0|0.5|1|1.5|2|3|4 1
option = gold enum 0|0.5|1|1.5|2|3|4 1
option = magic_exp enum 0|0.5|1|1.5|2|3|4 1
option = full_spirit bool 0
option = escape bool 0
option = no_ko bool 0
```

- **Rewards** (`exp`, `gold`, `magic_exp`; `on_rewards`): each multiplied in integer arithmetic, rounded down
  (`v * 2k / 2`, k the multiplier's halves, in 64 bits), magic EXP held to 127. The game shares EXP over the living
  members, each taking `ceil(EXP / alive)` (`0x8006F5FC`), so a member's share is not exactly k times; gold is held
  to 99,999,999 by `battle.c` and again by the game. Registered only when one of the three is not 1.
- **Full Spirit at the start** (`full_spirit`; `on_safe_point`): at the first safe point of each battle (scene 7)
  with a context and the phase at 1 or 2 -- the first round's input or, after an ambush, its AI -- SP and SP after
  reservations become max SP, once; leaving scene 7 arms it for the next battle, and so does a battle begun again
  inside it -- Try again rebuilds the battle in scene 7, the phase back to 0 and the round to 1 (a review
  finding). Not when a living party member
  has `0x10000` (equipment that holds SP at 0, which the round's end would undo anyway).
- **Always escape, the party only** (`escape`; `on_escape`): slots 0-3 escape; slots 4-11 keep their own roll, so
  enemies run away no more often than in the game. A battle that forbids running (its escape condition, ctx+5)
  never offers Run, so the mod never sees one there.
- **No knock-outs** (`no_ko`), for party members (slots 0-3) only, three handlers:
  - `on_damage`: a value at or above the target's HP becomes HP - 1 (0 when HP is 1 or less);
  - `on_effect`: a death that landed -- effect 5, and effect 6 with no value (-1) -- is cancelled and the target's
    hit result made a miss (0), a death spell that missed, a state the game knows (applied as effect 0, 6's -1
    would add 1 HP, and a KO result left on a standing member is a state no run has shown the battle survive);
    6's damage branch and 68 become effect 0 with the value held to 0..HP - 1 and a KO result made a hit, as
    `fn_8002BD88` itself turns them into 0 for status `0x40` -- cancelling 68 would drop its damage too, and the
    clamp alone makes 68 worse, since its calculator drops the death only when the damage kills (`0x80068DEC`);
    and a positive value of effect 0, or of an effect that reaches effect 0's applier (4, 8, 17, 44, 61, 62, 65,
    69, 70, 72; not 66, a heal here), is held to HP - 1 at the moment it lands, which also covers several hits
    worked out before any lands and damage that never passed `fn_800108EC`;
  - `on_round_end`: each party bit of `0x80346BE8` is cleared and that member's HP set to 1, where poison leaves
    them, with the low-HP bit set as `fn_80010474` would have set it -- between rounds, where the game sets it
    after a round's non-lethal poison; enemy bits are left for the game.
  Each override is one log line: the slot, the effect or the poison bit, the HP found and what was written.
  The assist stands down, and says so once, in a battle whose defeat condition is 2 (section 2).
- **Logged at load:** what is on (`battle-boosts: exp x2, gold x2; full spirit; escape; no knock-outs`), or that
  every option is at its default and nothing is registered.
- **The check's switch,** `SOA_BOOSTS_TEST=lowhp|poison` (7.2), read by nothing else: every party character's HP
  held at 1 between battles (`party.character[c]` +24), so the next battle's setup brings the members in at 1 as
  a battle begun hurt does; for `poison`, the living members poisoned at its first round. Written to the actors
  in the first round instead, the story's first battle stalled at its next blow, before any enemy acted, both
  members newly in status `0x8000` [I: the game's low-HP stance, entered without its animation] (FINDINGS
  "Battle mods").

## 4. R3: `mods/difficulty`

`manifest = 2`, `id = difficulty`. A preset, and each multiplier on its own to override it:

```
option = preset enum easy|normal|hard|nightmare normal
option = hp enum preset|0.25|0.5|0.75|1|1.25|1.5|2|2.5|3|4 preset
option = attack enum preset|0.25|0.5|0.75|1|1.25|1.5|2|2.5|3|4 preset
option = defense enum preset|0.25|0.5|0.75|1|1.25|1.5|2|2.5|3|4 preset
option = magdef enum preset|0.25|0.5|0.75|1|1.25|1.5|2|2.5|3|4 preset
option = speed enum preset|0.25|0.5|0.75|1|1.25|1.5|2|2.5|3|4 preset
option = rewards enum preset|0|0.5|1|1.25|1.5|2|3|4 preset
```

| Preset | hp | attack | defense | magdef | speed | rewards |
|---|---|---|---|---|---|---|
| easy | 0.5 | 0.75 | 1 | 1 | 1 | 1 |
| normal | 1 | 1 | 1 | 1 | 1 | 1 |
| hard | 1.5 | 1.25 | 1 | 1 | 1 | 1.25 |
| nightmare | 2 | 1.5 | 1.25 | 1.25 | 1.25 | 1.5 |

- **Why these numbers** [I, a first proposal; the owner's Done below is where they are judged]: HP lengthens a
  fight in proportion; physical damage is `2 x ATK - DEF`, so a Defense multiplier changes damage out of
  proportion (an enemy whose Defense nears twice the party's Attack becomes nearly immune) and stays at 1 until
  Nightmare; Quick reorders turns and raises an enemy's own escape chance, so it too waits for Nightmare. Rewards
  rise with the risk; Easy keeps the game's.
- **At each spawn** (`on_enemy_spawn`, both callers: a battle's setup and Call Allies): HP and max HP (+20, +24)
  by `hp`, at least 1; Attack (+148) and Will (+130, the enemy's magic power) by `attack`; Defense (+150) by
  `defense`; MagDef (+152) by `magdef`; Quick (+136) by `speed`; each s16 held to 1..32767, and each one's base
  copy (+242, +234, +244, +246, +240) scaled the same way, so a buff's or a round's restore starts from the scaled
  value. Integer arithmetic, rounded down (`v * percent / 100`). Each spawn logs what moved.
- **The record, for the battle only, and only its max HP** [V, a review finding]: the boss music task
  `fn_8007D42C` weighs the alive bosses' HP (actor+20) against the sum of their records' max HP (+36,
  `0x8007D680`-`0x8007D6A4`, and twice more), so an actor scaled alone puts its cues at the wrong HP -- at Easy,
  the boss's below-half music from the first frame and never its normal list again. So the first spawn of a kind
  in a battle scales its record's +36 too, and remembers what it held; the game makes a later enemy of the kind
  from the scaled record, so its HP is not scaled again. When the scene leaves the battle each record is put back,
  where it still holds the scaled value (the map may have freed and reused it). The record is shared by every
  enemy of its kind and kept across battles on a map: nothing else of it is written, and nothing of it outlives
  the battle, or the next would compound.
- **Rewards** (`on_rewards`): EXP, gold and magic EXP by `rewards`, as in R4.
- **Ship battles are left as the game has them:** the field's ship driver makes their enemies and pays their
  rewards (battle-system.md §7), past both events.
- **Level scaling** (the plan's "optionally") is left out: an enemy's level (+128) is read by AI conditions 44 and
  45 (Vyse's level against it) and by nothing in the damage, so scaling it changes behaviour, not strength. A
  stat curve from the party's level is a design the owner should choose first.
- **Logged at load:** the preset and the six numbers in force, or that it is at normal with nothing registered.

## 5. Together

Both may load. Their reward handlers multiply in load order, each rounding down: `battle-boosts` before
`difficulty` (folder-name order, M17, unless `mod_order` says otherwise), so EXP x2 with Hard pays
`floor(floor(e x 2) x 1.25)`. Each logs what it does.

## 6. Not here

R3's level scaling (above); ship battles (above; `on_ship_damage` could scale their damage later); stone; a menu
for these options (M8's settings page, PLAN-GAMEPLAY-MODS F); effects
5, 6 and 68, and a party Run, forced in a real battle (section 7 holds them in the fake guest; the first battle has
none, and forcing an enemy's spell means its animation's data, a reach slice of its own); comparing a battle with
the mod against one without (rule 7: two live runs; K6/D4).

## 7. Done

1. **The fake guest** (`test_mods.py`, each mod built with the line `--link` uses): at defaults each mod loads,
   says so and registers nothing, and every event passes through. R4: each multiplier exact on several values
   (rounding down, magic EXP held to 127); escape true for slots 0-3 given false, an enemy's roll returned as given
   either way; the damage clamp for a party target at, above and below its HP, never for an enemy; each of the
   eleven effects that land as damage held, a landed death (5, and 6 with no value) cancelled with its KO result
   made a miss, 6's damage and 68 rewritten with a KO result made a hit, a heal (31, 32, 66), a status and an
   enemy target untouched; at the round's end party poison bits cleared with HP 1 and the low-HP bit, enemy bits
   kept; full Spirit
   once a battle at phase 1 or 2, not with a living member's `0x10000` (an unconscious or escaped one's does not
   count), again after the scene leaves 7; the test switch's characters, its poison, and nothing at the defaults,
   the safe point included. R3: each preset's fields and base copies at a spawn, each override beating its preset,
   defense and magdef each by its own number, the record's max HP scaled once a battle and put back after it (not
   where it has changed since), a second enemy of the kind left as made, the next battle scaled again, the rest of
   the record unchanged, the s16 and HP limits, rewards. *Mutations:* one per rule, each caught; four kept as tests.
2. **R4 in a real battle,** `battle.scn` with `SOA_BATTLE_LOG=1` (the story's first battle):
   - `battle-boosts.exp=2 battle-boosts.gold=2`: the run's `rewards` line has EXP and gold exactly twice the
     originals, magic EXP equal, and fires once; at the defaults the mod registers nothing and the pairs are equal
     (`tools/battle.py rewards`). *Mutation:* each run's log held to the other's multipliers fails the check (a
     build that adds 1 at x1 is the fake guest's mutation: at the defaults nothing is registered).
   - `full_spirit=1`: the SP line at the first round's input reads the maximum (the battle's start line, before
     the round, still reads the game's).
   - `no_ko=1` with the mod's test switch holding every party character at 1 HP between battles, so the battle's
     own setup brings them in at 1: every enemy hit on the party is logged held (`damage ... -> O -> R` with R = 0
     on a party slot), no party slot's status gains `0x100`, and the battle is won. And with poison put on them at
     the first round (the switch's second form): the round's end clears their bits, their HP stays 1, the mod
     logs each, and no party slot faints. *Mutation:* the same switch with `no_ko` off, and a party member faints.
3. **R3 in a real battle,** the same scenario: `difficulty.preset=hard` logs the first spawn's HP at 1.5 times the
   game's and the second, made from the scaled record, already there; the battle is still won, the rewards line is
   1.25 times; the record's max HP, read during the battle by the lab (`SOA_LAB=peek`, the chain slot 4's actor,
   `+272`, `+36`, since the record's address moves from run to run), is the actor's, and the mod puts it back when
   the battle ends. *Mutation:* a build that never scales the record shows the peek at the game's value during the
   battle, with the actor's HP half again above it.
4. **Owner:** Hard through one dungeon (PLAN-GAMEPLAY-MODS R3's Done); the numbers of section 4 are theirs to
   change.
