# R0: the battle harness, and R1's damage event pulled forward

Written 2026-10-23 for the owner's answer of 2026-10-22 (PLAN-NEXT D-43: the gameplay core, T9, T1, R0, batch A),
from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) R0 and R1, docs/research/battle-system.md and encounters.md,
FINDINGS "1324" (the forced battle) and the lab's battle items. The code was mapped first, at 1c9a3b2.

**Built 2026-10-23** (FINDINGS "R0"): Done lines 1 to 5. *As built:* the battles the evidence runs fight are
the story's first, lengthened by a scratch mod that puts each target up to 9999 HP through `on_damage` before the blow
lands (a doubled blow out-hits early soldiers' max HP); the log also carries each target's element multiplier and
Guard bit, so every hit, not only the first, is held to its formula's range.

**Why.** Every combat mod in the plan (R1-R9, N2, N10) needs a battle on demand and a record of what happened in it.
R0 is that: from a card save, start a chosen battle, play its turns, and log what the battle did -- each damage call's
value before and after mods, and the actors' HP, SP and order as they change. Its Done is a damage-doubling mod
proving itself on that log, which needs R1's first event, so the event comes here.

## 1. What is there

- **Forcing a battle** (encounters.md:25-42, FINDINGS 1323-1330): the six-word request -- mode `0x803473D0` (0 the
  map's party, else an event), id `0x803473CC`, stage `0x803473C8`, transition `0x803473D8` (-1 random) and forced
  `0x803473D4` -- read first by `fn_800C1C24`, one shot, no gates, needing the field in state 8. Only a map-party
  battle on `a101b` has run this way. Map loads clear it. T9 names all five (`battle.request.*`).
- **Commands:** nothing writes the command records (`0x80309174 + 32*slot`). The lab's `turn:F-G:M:SEQ` plays a
  member's turn by pressing buttons through the pad filter at the member's first input of each battle, and logs the
  commands at the phase 1 to 2 edge (tested, `test_mods.py`).
- **Damage:** `fn_800108EC(base r3, element r4, attacker r5, target r6)` returns the damage in r3 (battle-system.md
  259-268: x[0.975, 1.025), +1 one time in eight, element/10, half on a guard, 9999 at most), called from
  `fn_80010A40` (attacks), `fn_80069B58` and `fn_8006AFD0` (S-moves). `fn_80010A40`'s base is 2 ATK - DEF, DEF 0 on a
  critical. No code logs or changes it; no `on_*` battle callback exists.
- **Natively answered functions** (`config/hle.txt`): the runtime defines `fn_X`, the translation keeps
  `recomp_fn_X`, every caller binds at link time; adding one is a full retranslation (CLAUDE.md).
- **Reproducibility:** `SOA_SEED` pins the battle start's two clock reads (P6); whether one seed gives one battle is
  K6's, open.

## 2. What R0 adds

- **The damage event (R1's first, pulled forward):** `fn_800108EC` answered natively in `runtime/battle.c`, through
  `hle.txt`: it calls `recomp_fn_800108EC`, then each mod's `on_damage(user, value, base, attacker, target, element)`
  in load order, each returning the value the next sees; the last is what the game gets, clamped to 0-9999. A new
  `SoaModApi` member, `on_damage`, appended (old mods keep loading: `SOA_MOD_HAS`). The function has no back-edge,
  so the wrapper strips no poll.
- **`SOA_BATTLE_LOG=1`:** `[battle]` lines -- each damage call as `damage <base> -> <original> -> <returned> by
  <attacker> on <target> element <e>`; at each safe point in scene 7 any actor whose HP, MP or status changed, the
  context's SP, and the turn order when it changes; the battle's start (its formation and stage) and its end (the
  phase that ended it, rounds, the counts).
- **`SOA_BATTLE_FORCE=mode:id:stage@F`:** at the first safe point from frame F with the field in state 8, the step
  counter zeroed and the request written, transition -1, forced last; said once, and said again if the field leaves
  state 8 with the request still armed. Commands are the lab's `turn:` (documented as R0's), no new writer.
- **A recipe and a checker:** `tools/battle.py run` (a card copy, the Continue, a warp to a map with an `.enp`, the
  force, `turn:` for each member, the log) and `tools/battle.py check <log>` (every damage line parsed; the doubling
  check below; a summary of hits).
- **`examples/mods/damage-double`:** a DLL registering `on_damage` that returns `min(2 * value, 9999)`.

## 3. Not in R0

R1's other events (rewards, encounters, phases), X2's save hooks (batch A), a command writer (the recipe at
battle-system.md:562 stays unproven), event battles by force (the request supports them; none has run), and any
claim that two runs give the same battle (K6).

## 4. Done

1. **The wrapper changes nothing by itself:** replay 23/23 and `title --check` after the retranslation; and in one
   battle with no mod, every logged call's returned equals its original. *Mutation:* the wrapper adding one makes the
   check fail.
2. **The doubling mod, proved on its own log:** with `damage-double`, every logged call's `returned == min(2 *
   original, 9999)`, at least 10 nonzero hits, so it cannot pass on a battle with no hits; `tools/battle.py check`
   says so. *Mutation:* the mod tripling fails it.
3. **The formula's range:** the first logged attack's original lies in `[floor(0.975 * base), ceil(1.025 * base) + 1]`
   for a neutral element and an unguarded target, and its base is 2 ATK - DEF of the actors it names (DEF 0 on a
   critical, Vyse's title bonus added), read in the wrapper.
4. **The log's other half:** the battle's start and end, every actor's HP change accounted for by a damage line or a
   heal, and the turn order each round, in the same run.
5. **The fake guest:** `test_mods.py` drives `on_damage` through a stand-in for the wrapper -- order, chaining, the
   clamp, a mod built before the member still loading.
