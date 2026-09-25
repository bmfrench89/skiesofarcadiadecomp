# Now: the first slices after the pivot

*Superseded 2026-09-25 by `docs/PLAN-NEXT.md`. N1-N4 landed (cb469d6;
3949028, b071949; 1c7b780, 4041dfc; c8274db). N5's P6 landed as 24d9235 and
its remainder, comfort-pack P6b, as 79c9ad8; its P1 is comfort-pack P1a,
landed as 090eea6, and P1b. N6 is comfort-pack P11 (spike b911380), with
hold-to-skip as P11b.*

*2026-09-25, from `main` at 574c683. The implementation session's plan for the
hours before the planning session's reviewed specs land. Those specs --
`docs/specs/comfort-pack.md`, `disc-layer.md`, `portability.md`,
`gpu-backend.md` and `docs/PLAN-NEXT.md`, all the planning session's to write --
supersede this file from the first row they cover that has not landed yet.*

## Why the order changed

The owner asked for the pivot on 2026-09-25: gameplay mods first, then a path
off the ISO, with the renderer paused at a clean point. The reasoning is
`docs/research/android-and-native.md` section 7. In short:

- 30 fps drawn every frame is reached in the heaviest field scene measured
  (FINDINGS "Copy images", "Neighbour fences"), so the port plays at the
  game's own rate, and what the owner gets next is best measured in features.
- A GPU backend, which Android needs and which is also the PC's surest route
  to 60 images a second, is the owner's decision. The CPU pixel path's next
  steps (H15d's rest, H16, H18) wait on it; H17 (interpolation) does not,
  because it works on draw commands whatever draws them, and it follows
  milestone 1 of `docs/PLAN-GAMEPLAY-MODS.md`.

## The slices, in order

One commit each, pushed by this session. Every check names its command; the
standing ones are CLAUDE.md's "Before you push" list and its table.

| # | Slice | Where it is specified | Touches | Checks |
|---|---|---|---|---|
| N1 | Status lines: H13 done enough, H15d and H16 wait for the GPU decision, H17 not blocked | this file | `docs/PLAN-60FPS-MODS.md` | the doc diff read back |
| N2 | Manifest v2 | `docs/PLAN-GAMEPLAY-MODS.md` section F, "Manifest v2" | `runtime/mod.c`, the shipped `mod.ini` files, `tools/tests/test_mods.py`, the docs that show a `mod.ini` | `pytest tools/tests/test_mods.py`, each new refusal turned red by a mutation; `compile_runtime.py`, `--link`, the self test |
| N3 | T0: the guard's new suffixes and directories, and the content check | `docs/PLAN-GAMEPLAY-MODS.md` T0 | `tools/guard.py`, `.github/workflows/ci.yml`, `tools/tests/test_guard.py`, every copy of the refused-extension count | `pytest tools/tests/test_guard.py`, a dump turned red by the content check, `guard.py`, `guard.py --history` |
| N4 | Acquire loads at every cross-thread read in the render queue | the portability spec's L0 class; the sites in FINDINGS "H15d paused" and the reply of 2026-09-25 | `runtime/gxr.c` | `compile_runtime.py`, `--link`, replay 23/23 at 1, 2, 3 and 8 threads, `pytest tools/tests/test_gxr_overlap.py`, and the x64 code of the worker loop compared before and after |
| N5 | P1 (encounter slider and hold-B) with P6 (race seed) | `docs/PLAN-GAMEPLAY-MODS.md` P1, P6 | a new `mods/` folder with its `mod.dll` source, `runtime/settings.c`, `runtime/hle.c` | the Done lines of P1 and P6, which are same-run checks with mutations |
| N6 | P11 (dialogue auto-advance and hold-to-skip), after its spike | `docs/PLAN-GAMEPLAY-MODS.md` P11 | a new `mods/` folder | P11's Done: a scripted conversation advances with no A in the pad script and stops at a choice; with the mod off the same script stalls |

After N6 the comfort-pack spec takes over.

## Concerns, said before starting

- **Two sessions, one tree.** The planning session writes only its five spec
  paths and commits them without pushing; this session writes code, pushes,
  and alone edits `runtime/gxr*.c` and `runtime/gx.c`. Each tells the other
  its commits.
- **Addresses from reading are not addresses from running.** Every game
  address in P1, P6 and P11 was found statically. Each is peeked in a run
  before a mod is built on it, and the Done lines are same-run contrasts
  with a mutation, never two live runs compared (CLAUDE.md, rule 7 of the
  gameplay plan).
- **Some checks need the owner.** P10's two pads, H19 on the device, M18's
  rumble in the hand and turbo's feel cannot be closed headless; each is
  built and checked as far as a run can, then listed for one owner session.
- **60 fps moves back by about milestone 1's length** (three weeks of work at
  the plan's estimate). If 60 images a second matters more to the owner than
  the comfort pack, H17a is the row to move up, and nothing here blocks it.
- **Mods stay off by default.** None of N2-N6 may change a run with
  `SOA_MODS` unset: the replay, `title --check` and the self test are the
  contract.
