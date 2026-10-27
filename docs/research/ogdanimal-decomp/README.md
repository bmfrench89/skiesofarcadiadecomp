# ogdanimal's decompilation notes (CC0)

These are the research notes of another project, copied here whole on 2026-10-27 at the owner's word (PLAN-NEXT
D-47): the `docs/` folder of **github.com/ogdanimal/SkiesOfArcadiaLegends-Decomp** at commit `1d2f66e`, a
matching decompilation of this same game (`GEAE8P`) by ogdanimal, dedicated to the public domain under **CC0 1.0
Universal**. CC0 asks nothing, so nothing here is a licence condition; the credit is ours to give. The images the
notes link to (`images/`) were not copied, and links into that repository's other files (its `src/`, `config/`,
`tools/`, README) lead nowhere from here.

The same developer's playable recompilation, **github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp**, is GPL-3.0:
the notes below describe some of its patches, and describing them is fine, but none of that project's code may be
copied into this MIT one.

**Not re-checked here.** Every claim below is that project's, made against its own build. Before acting on one,
check it in this repository the way FINDINGS asks of any claim (CLAUDE.md, "What you must not conclude").

| Note | What it covers, and where it helps here |
|---|---|
| [qol_cheats.md](qol_cheats.md) | encounters, EXP, battle speed and invincibility: the published cheat codes decrypted and traced to their routines -- milestone 3's boosts and assists (R4) |
| [ui.md](ui.md) | menus, the HUD and the 2D layer: the draw state stack, the text queue, layouts, the UiObj animation every menu element uses -- what a mod drawing on screen (R5, P7) stands on |
| [camera.md](camera.md) | the camera and its controls |
| [frame_loop.md](frame_loop.md) | the main loop and the frame's order of work |
| [sound.md](sound.md) | MusyX and the game's sound and music |
| [ninja.md](ninja.md) | Sega's Ninja graphics library, named by behaviour |
| [widescreen.md](widescreen.md) | the aspect word at `0x80345894` (1.1 is 704/640) and the 2D's exceptions; widescreen is dropped here (D-46), kept as a record |
| [compiler.md](compiler.md), [matching.md](matching.md) | which Metrowerks compiler and flags the game code was built with, and how functions are matched |
| [sdk_import.md](sdk_import.md) | the SDK, MSL, MetroTRK and MusyX code imported from other projects, under their own licences, and why |
| [splits.md](splits.md), [symbols.md](symbols.md), [comment_section.md](comment_section.md), [common_bss.md](common_bss.md) | how that project's build splits the DOL and names its symbols |
| [getting_started.md](getting_started.md), [dependencies.md](dependencies.md), [github_actions.md](github_actions.md) | that project's own setup |

Its function names came in through `config/names.txt` the same day: 839 of them, where this repository had only a
placeholder (FINDINGS "D-47").
