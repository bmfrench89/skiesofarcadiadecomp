# R1: the battle events, with M3d's in-game fault stop

Written 2026-10-23 for the owner's answer of 2026-10-22 (PLAN-NEXT D-43: the gameplay core, T9, T1, R0, batch A),
from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) R1 and M3d, docs/research/battle-system.md and R0's
[battle-harness.md](battle-harness.md). The sites were read in the disassembly at 282c2cd (`tools/disasm.py`).

**Built 2026-10-23** (FINDINGS "R1, the battle events"): Done lines 1 to 6. *As built:*
- **`on_effect` writes the value in two places.** A value changed in the message alone left a lethal blow's action
  waiting forever, its pop-up still showing the old number: `fn_8002DD8C` copies the value from the target's work
  (+60), and the action's end reads it there. So the wrapper writes the work too, where it still holds the message's
  value (the follow-up messages carry values of their own).
- **The mutations are what showed in a battle,** not the list in item 2: an enemy's HP up by half (halved, the
  story's first battle ended in one round, before any round end or spirit gain); slot 5 Guarding, the game honouring
  it; every escape refused, since the ones run succeeded anyway.
- **Item 4's fault is in `on_heal` in the fake guest and `on_damage` in a real battle.** A fault outside an event
  is not tested: it would end the test process through the OS. The hook returns at once when no event is running.
- **Reading is free.** A wrapper with no mod on its event still reads what it logs; it writes nothing.

**Why.** R0 gave mods one battle event, `on_damage`. Every combat mod after it (R2-R9, N2, N10, X4's kinds) needs
the rest: heals, spawns, the enemies' choices, the turn order, spirit, escapes, rewards, every applied effect, the
round's end and the ship's damage. Batch A is R1 with X2's save hooks; they share nothing but the retranslation
rule, and a retranslation now takes under three minutes (FINDINGS "R0": 147 s), so R1 lands alone and X2 follows
with its own spec (Q2 answered 2026-10-23, PLAN-NEXT D-44: the honest wording).

## 1. What is there

- **R0's pattern** (`runtime/battle.c`): `config/hle.txt` answers `fn_800108EC`; the runtime's `fn_X` stores its pc
  first (`test_hle_pc`), calls `recomp_fn_X`, then `mod_damage`, which runs each mod's callback in load order with
  `g_cur_mod` set. `SOA_BATTLE_LOG=1` logs each call.
- **The sites** [V, disassembly at 282c2cd]:

| Event | Function | Arguments, and what it leaves |
|---|---|---|
| heal | `fn_8006AE20(source r3, target r4, kind r5, r6)` | stores the heal into `work+60` (`0x8006AFA8`), work = `*(*(0x80309700 + 4*target) + 36)`; r6's low byte to `work+68`; the caller builds the message from `work+60` |
| enemy spawn | `fn_800770B8(actor r3, record r4)` | a leaf: fills the actor from the record, ends `actor+272 = record`; two callers, setup `0x80077B58` and Call Allies `0x800693A8` |
| enemy action | `fn_8008A424(slot r3)` | writes `cmd = 0x80309174 + 32*slot` (+0 type, +4 target, +5 selector, +6 id) and returns the type; one caller, `0x80070CAC`, which stores it into cmd+0 |
| turn order | `fn_80070C18()`, phase 2 | runs each frame of phase 2; leaves the order in `0x803092F4` (s8, ending at -1) and the phase `0x8034733C` at 3 |
| spirit | `fn_8006EF48()` | `ctx+8 += sum; ctx+10 += sum; ctx+8 = min(ctx+8, ctx+6); ctx+10 = ctx+8`, sum over live members without `0x3100` of `rec120[ch]+6 + actor+268`; one caller, `0x80070124` |
| escape | `fn_80010340(slot r3)` | returns 1 to escape, from `rand() % 101` against the chance; called for the party's Run (`fn_800858B8`) and an enemy's (`fn_80088B14`) |
| rewards | `fn_8006F4B0()`, phase 7 | sub-state `0x80347338` (r13-29672) 2 is the frame that pays out (`0x8006F598`): EXP `ctx+48` shared over the living, gold `ctx+52` added at `0x8006F624` (capped 99,999,999), magic EXP `ctx+1` (s8) |
| effect | `fn_8002BD88(msg r3)` | msg+0 target, +6 effect (s16), +8 value (s32); filters, then calls the applier `0x802DBB10[effect]`; every caller is in `fn_8002DD8C` and drops r3 |
| round end | `fn_8006FD6C()`, phase 6 | sub-state 0 applies regen, poison and the round's SP, then moves on |
| ship damage | `fn_80146BF4(atk r3, def, elem, phase, rec)` | the ship battle's damage core, the value in r3; the caller multiplies by 10 |

- **Faults:** none is caught. A mod's callback that faults ends the process through the OS with no mod named;
  `g_cur_mod` names it at every dispatch, and nothing reads it then. `plat.c` has a guard for guest memory only
  (a vectored handler on Windows, `SIGSEGV` elsewhere) that passes every other fault on.

## 2. What R1 adds

- **Ten more natively answered functions** in `hle.txt`, in `runtime/battle.c`, each storing its pc first and
  calling its `recomp_fn_X`; one retranslation.
- **Ten `SoaModApi` members, appended** (old mods keep loading, `SOA_MOD_HAS`), each run in load order inside the
  game's own call, memory reads and writes only, as `on_damage`:

| Member | fn gets, and returns | When |
|---|---|---|
| `on_heal` | `uint32_t fn(user, value, source, target)`: the heal, returned held to 0-9999, written back to `work+60` | after each `fn_8006AE20` |
| `on_enemy_spawn` | `void fn(user, actor, record)`: scale the actor, never the record (shared by every enemy of the kind, and kept across battles on a map) | after each `fn_800770B8` |
| `on_enemy_action` | `uint32_t fn(user, type, slot, cmd)`: the type returned; cmd's other fields written in guest memory | after each `fn_8008A424` |
| `on_turn_order` | `void fn(user, int8_t order[12])`: a copy, written back only if it is still a list of distinct slots 0-11 ending at -1 (else logged, and the game's kept) | once, the call of `fn_80070C18` that leaves phase 2 for 3 |
| `on_spirit_gain` | `int32_t fn(user, amount)`: the round's gain before the clamp; what comes back is added and clamped to 0..ctx+6 | at each `fn_8006EF48` |
| `on_escape` | `int fn(user, success, slot)`: nonzero to escape | after each `fn_80010340` |
| `on_rewards` | `void fn(user, SoaRewards* r)`: `{int32_t exp, gold; int32_t magic_exp}`, written back with gold 0-99,999,999 and magic EXP 0-127 | once, before the `fn_8006F4B0` call that finds sub-state 2 |
| `on_effect` | `int fn(user, target, int16_t* effect, int32_t* value)`: nonzero cancels; the two written back to msg | before each `fn_8002BD88` |
| `on_round_end` | `void fn(user, round)` | after the `fn_8006FD6C` call that moves sub-state 0 on |
| `on_ship_damage` | `uint32_t fn(user, value)`: returned held to 0 or more | after each `fn_80146BF4` |

- **The spirit gain before its clamp:** the wrapper saves SP and its maximum, sets SP to 0 and the maximum to
  32767, calls the original (which adds the sum and copies it to ctx+10), reads the sum, restores both, and writes
  `min(max(SP + amount, 0), maximum)` into ctx+8 and ctx+10. The original's own rules (who is alive, `0x3100`) still
  decide the sum.
- **With no callback for an event, its wrapper is the original and a count:** nothing is written.
- **`SOA_BATTLE_LOG=1`** gains a line per event, as `damage`'s, and the report a line per site: calls, values
  substituted (a returned value, or bytes, that differ from what the game had) and, per mod, handler time (total,
  max, and p99 from a fixed histogram).
- **The in-game fault stop (M3d's part):** a handler, through `plat.h` (`plat_fault_hook`), that while an in-game
  event is dispatching (a flag set around each callback, with `g_cur_mod`) turns an access violation, an illegal
  instruction or a division by zero into `[mod] <dir> faulted in <event>: <what> at <address>; the run stops` and
  exit 10. Outside a dispatch it passes the fault on as today. The R0 `on_damage` dispatch gains it too.

## 3. Not in R1

X2's save hooks and N11's NG+ sites (their own spec, after Q2), an exclusive AI replacement per slot (R2), X4's
kinds fix (a `--link` in the spawn wrapper, X4), the rest of M3d (the log file, the crash file, the hang reporter,
safe mode), K6's question whether two runs fight the same battle, and any comparison of two live runs (rule 7).

## 4. Done

1. **Mods off, inside one run of the retranslated build:** replay 23/23, `title --check` and the self test; R0's
   story battle and reach U3's ship battle, each with `SOA_BATTLE_LOG=1`, give every site a nonzero call count
   (heal needs a cast or a Blue Rogues heal, escape a Run: the lab's `turn:` plays them), and every count of values
   substituted 0. *Mutation:* a test mod returning value + 1 from `on_heal` makes that count nonzero.
2. **One mutation per event, on a real run:** a test mod for each event changes what it can (heal x2, spawn HP
   halved, every enemy action Guard, the order reversed, spirit +5, escape always, rewards x10, effect value 0,
   round end logging, ship damage x2), and the run shows it in memory or the log: the heal or HP line, the order
   line, SP, the result, gold peeked.
3. **`on_rewards` fires exactly once per victory,** counted against R0's battle end lines in the same run.
4. **A fault stops the run and names its mod:** a test mod that writes through a null pointer in `on_damage`
   gives exit 10 and the line naming it; the same mod faulting outside an event (its `soa_mod_init`) is not caught
   by R1's handler, as today.
5. **Budget:** the handler times of item 2's run in its report, against 50 us p99 per event, fixed now.
6. **The fake guest:** `test_mods.py` drives each new dispatcher through a stand-in: order, chaining, the clamps,
   the order's validation, a mod built before the members still loading.
