# M8: the in-game menu

Written 2026-10-21 for the owner's choice that day (PLAN-NEXT D-40: M8 first), from
[PLAN-60FPS-MODS.md](../PLAN-60FPS-MODS.md) M8, [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) §F (M8, its
amendment, and the rule-7 rewrite of its Done) and the M16/M17 specs, which leave each their page for it. The code
it touches was mapped first (window.c's present path, si.c's pad, the chords, the safe point, settings.c, mod.c).

**Status: M8a built 2026-10-21**, Done lines 1-6 met on this PC and in a Linux container (FINDINGS "M8a"); line 7
is the owner's, at the next sitting. **M8b built 2026-10-22** (FINDINGS "M8b"): the Vulkan presenter blends the
menu over its picture, held by `gpuspike.py present --overlay`.

**Why.** Every setting the port has is a line in `soa.ini` or an environment variable. On a handheld with no
keyboard, that means leaving the game to change anything. M8 is the menu a player opens from the pad.

## 1. What it is (M8a, this slice)

- **Opened and closed** by View+LS (the chord CH1 reserved for it, which logs "(not built yet)" today) or F1;
  closed by B or Esc on its first page too.
- **The game holds while it is open.** It pauses the clock as focus loss does, under a reason of its own (the pause
  becomes a set of reasons, so a focus change cannot release the menu's hold or the reverse), and the pad the game
  reads is neutral from the moment it opens: withheld in `si.c` before a recording takes its copy, so a recording
  made around the menu replays the same.
- **Pages,** each a list moved through with up and down, changed with left and right, entered with A or Enter, left
  with B or Esc:
  - **Main:** Resume; Mods; Settings; Fullscreen (applied now); Turbo (applied now); Quit.
  - **Mods:** each loaded mod by name, on or off (written as `mod_order`'s `-ID`); entered, its declared options
    (M16) with their values: an enum, a bool or an int changed in place (an int by 1, or by a tenth of its range
    with the shoulder buttons or Page Up/Down), a string or seed shown and not edited.
  - **Settings:** every `soa.ini` key with a closed set of values (its `choices`), changed in place.
- **What a change does.** Fullscreen and turbo apply at once. Everything else is written to `soa.ini`, the file the
  port read at its start, and the page says so: "saved; the game reads it when it next starts". Options are fixed
  when a mod loads (`patches.txt`'s `${NAME}` is replaced then), and a restart is the honest way to apply them.
- **Writing `soa.ini`** keeps every other line, comment and order as it was, replaces the key's line where there is
  one and appends it where there is not, and replaces the file whole (written beside it, then moved over it).
- **Drawn** by the CPU presenters (DXGI, GDI and SDL) into the scaled, client-sized buffer after the picture is
  scaled into it, never into the game's picture (`g_screen`), which the frame hashes and snapshots are taken from:
  a dimmed panel and text from a small font of the port's own (5x7, ASCII, drawn scaled to the window). With the
  game held, no frame arrives, so the menu asks for a re-present when it changes.
- **The Vulkan presenter** draws its picture on the GPU, so the menu is drawn there as an overlay the GPU blends
  (M8b): `menu_draw_overlay` writes it, clear where the menu is not, the panel's ground 11 at 191/255 (which blends
  to about the CPU path's p/4 + 8), the rest opaque, into a buffer a second pipeline on the present pass reads.

## 2. Not in M8a

Warps and saves from the menu (M7a/b's actions, which the plan's first Done wanted), a
mod's order changed from the menu (M17's list is written by hand for now), and live re-application of options.

## 3. Done

Each check's mutation is made, the check run and seen to fail, and the change put back.

1. **The menu model.** `test_menu.py` builds `menu.c` with a driver: a script of inputs moves through the pages, and
   the soa.ini lines written and the actions asked for (fullscreen, turbo, quit, close) are what the script says.
   *Mutation:* left and right swapped on an enum.
2. **soa.ini edits keep the rest.** `test_settings.py`: a file with comments, blank lines and other keys has one key
   replaced, then one appended, and nothing else moves. *Mutation:* rewriting from the parsed keys alone (comments
   lost).
3. **The font and the panel.** `test_menu.py` renders a page into a buffer and checks a glyph's pixels and that
   nothing outside the panel changed; the render is also written as a PNG and opened. *Mutation:* a glyph's row
   shifted.
4. **The game's picture is untouched.** `SOA_WINDOW_TEST=menu@N` opens the menu in a real windowed run and logs the
   screen hash (`gxr_screen_hash`) before and after a present with the menu open; they are equal. *Mutation:* the
   overlay drawn into `g_bgra` (the converted picture) fails it. The same action writes the presented buffer as a
   BMP, which is opened.
5. **The pad is withheld before the recording.** `test_padrec.py`: with the menu open, the recorded and the
   reported pad are neutral while the person's pad presses A. *Mutation:* withholding after the recording.
6. **The pause is the menu's own.** `test_tick.py` or a clock test: the menu's hold survives a focus pause ending,
   and the focus pause survives the menu closing. *Mutation:* one flag for both.
7. **Owner, in a window** (the next sitting): open the menu with View+LS, turn an encounter preset to half and a mod
   off, quit, start again, and see both applied; turbo and fullscreen applied at once.
