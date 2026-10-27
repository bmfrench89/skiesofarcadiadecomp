# R5: battle information

Written 2026-10-27 for PLAN-GAMEPLAY-MODS R5 (milestone 3, the owner's D-46), the night M20 gave mods a way to
draw (`docs/specs/mod-overlay.md`), and built the same night: `mods/battle-info`.

**Built 2026-10-27** (FINDINGS "Battle information"): Done 1 to 3; 4 is the owner's. The layout in section 1 is the
second one: the first run's pictures showed the first under the game's own Spirit gauge.

**Why.** A battle in this game hides three things a player decides by: how hurt each enemy is, who acts next, and
what just happened when two blows land at once. R5 shows them, each part a choice, none of them changing the game.

## 1. What a player gets

Three parts, each off until set (`soa.ini`: `battle-info.hp = 1`; the menu's Mods page; `SOA_MOD_OPT`), and the
text's size, 1 to 3 (2 reads on a handheld). With all three off the mod registers nothing, so Setup can install it
with the others.

| Part | Where | What |
|---|---|---|
| `hp` | bottom left | each living enemy's letter, a bar and `HP/max`, a row each |
| `order` | top right | the round's turn order from the slot acting on, that slot in yellow, once the game has set it |
| `log` | bottom right | the last five things the round did to anyone's HP: `P1 > A -30`, `A +25`, `B down`, `C fled`, `round 2` |

Where: while the party chooses, the top of the picture is the game's -- the Spirit gauge and its bar across
it, the target's name at its right (FINDINGS "Battle information", the first run's pictures) -- so the HP and
the log, shown in every phase until the battle is decided, take the bottom corners, and the order, shown only
once the game has set it, when the gauge
has gone, the top right. The HP's bar grows less than the text (48 units and 16 a size), so at size 3 the
rows still leave the log its corner.

The party is `P1` to `P4` and the enemies `A` to `H`, by their slots in the battle (0-3 and 4-11), the same in all
three parts. No names: an enemy's name is the game's text, which gameplay Q5 asks the owner about, and no English
name exists as text on the disc anyway; the party's would be the same question.

## 2. Where it reads

At each frame end in scene 7, from the battle's memory as R0's log reads it (`runtime/battle.c`): each slot's actor
in `battle.actors`, its HP at +20 of +24 and its status at +28 (0x100 knocked out, 0x2000 escaped: no row); the
order at `battle.turn_order` from `battle.order_cursor`, and the slot acting at `battle.acting` (`0x80347335` and
`0x80347334`, named in `config/gamedata.txt` for this, from phase 3's `fn_800708C0`, which takes the slot at the
cursor and stores it; phase 5 moves the cursor on -- battle-system.md 2.1). The order leaves out what phase 3
would pass over, by the game's own test (status `0x6500` -- knocked out, escaped, asleep, stone -- or
`0x02000000`), and the slot at the cursor, fallen during its own turn, takes the yellow with it. Once the battle
is decided (phase 7 won, 8 lost, 9 fled) nothing is drawn: the screen is the game's results or its Try again,
whose two options sit low and left (`fn_80009874` prints them at 160,360 and 160,384), where the rows are -- from
this battle's own phases on, since the last battle's 7 lasts until the game's setup writes 0. The order is
shown in phases 3 to 5 only: before the party has chosen, the game has not set it (an estimate from Quick, as R5's plan put it, would
be wrong whenever the game's random term moves it, and a wrong order is worse than none).

The log is HP seen to change between two frame ends, so it holds what landed, after every mod's say (a blow
`battle-boosts` holds at 1 HP logs what was taken, not what was rolled), and a drop while a slot acts is put to
that slot; a drop with no slot acting (poison at the round's end) has no name before it. Being HP lost, a
finishing blow reads what was left, not the blow's own number, which the game shows over the target: in the
story's first battle Vyse's 43 on a soldier with 28 left is `P1 > A -28` (the blow's number would come from
`on_effect`'s value, effect by effect, which no one has mapped beyond the damage effects R4 holds). A battle begun
again (Try again: the phase back to 0) starts the log afresh.

## 3. Done

1. **The fake guest** (`test_mods.py`): nothing registered at the defaults; each part's draws for a known battle,
   to the unit; the order from the cursor, the slot acting first and in yellow, the fallen left out, nothing before
   phase 3; the log's lines for a blow with its striker, a heal, a knock-out, an escape and a new round, five at
   most, the oldest dropped; Try again clearing it; the size option. *Mutations:* the striker taken from the wrong
   word, the order not from the cursor, the fallen kept.
2. **The oracle** (`tools/battle.py info`, `test_battle.py`), battle by battle, R0's line at the mod's frame or the
   one after, never before: every number the mod logged as shown is R0's for that slot, an enemy still in the fight,
   and every change R0 logs for one is shown; each blow, heal, knock-out and escape the log tells is R0's change, a
   named striker R0's last damage line on the target; each order shown is a suffix of R0's latest with the fallen
   left out. *Mutations:* a shown number off by one, a change never shown, no shows line at all.
3. **The story's first battle** (`battle.scn`, `SOA_SPEED=3`, `SOA_SEED=4242`, `SOA_BATTLE_LOG=1`, the three parts
   on), in a DXGI window with the menu opened over a frame mid-battle: `battle.py info` passes on the run's log, and
   the frame, opened, shows the numbers the log has at that frame (R5's own Done: "the overlay's numbers match R0's
   log, paired with an opened frame").
4. **Owner:** a battle played with the three parts on, and a word on what to show by default.

## 4. Not in this slice

The bars over each enemy (its place on the screen, from the camera: a projection of the actor's position, which no
one has found yet); names (Q5); the party's HP (the game shows it); an estimated order in phase 1; the log's lines
for status ailments other than a knock-out; ship battles (another scene, other memory).
