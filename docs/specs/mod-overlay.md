# M20: drawing for mods

Written 2026-10-27 at main 8a1f817 for the owner's D-46 (PLAN-NEXT §0 item 1: "a way for mods to draw (R5, P7),
which no plan has yet"), from a read of the presenters, the menu, the mod API and the consumers by three readers
(the night's `research-mod-overlay` workflow), each claim below re-read at its line.

**Built 2026-10-27** (FINDINGS "M20"): Done 1, 2 and 5; 6 is the owner's look. Done 3 as built: DXGI's
`menu@10600` capture shows the example's rows under the menu; Vulkan is held in two halves, the buffer it is given
(`test_overlay.py`: the draws composited over a clear buffer; `test_menu.py`: the menu over them) and
`gpuspike.py present --overlay`, the GPU blending any such buffer over the picture, the list itself not run through
a Vulkan window; SDL built and its window test run in a Linux container; GDI read, not run. Done 4 as built: replay
23/23 with the runtime as built; a replay cannot carry a drawing mod (`scenario.py` strips every `SOA_` variable
from its runs, and `--replay` returns before the game starts, so no callback runs), so for a mod drawing, the DXGI
run's own line stands in: the game's picture and the converted frame hash the same before and after a present with
the example drawing.

**Why.** R5 (battle information: enemy HP bars, the turn order, a battle log) and P7 (the Captain's Log: a
checklist, missable warnings, an objective line) show things the game does not. Nothing in `soa_mod.h` draws, and
the game's own text queue (`TextPrint`, `0x801E2EE4`) needs a string in guest memory, which no mod owns
(PLAN-GAMEPLAY-MODS "No memory that only mods own"), and a safe point, which rules out the battle events. The
port's own overlay, M8's menu, already draws over the picture on every presenter and never into the frames the
checks hash; mods should draw the same way.

## 1. What is there [V]

- **The presenters** (all on the window's thread; mods run only on the guest thread, `soa_mod.h`:23-24):
  - DXGI: `picture_scale(g_bgra -> g_scaled)`, then `menu_draw(g_scaled, g_bw, g_bh, g_bw*4)`, then the whole buffer
    uploaded (`window.c`:328-344). B G R X, client size in physical pixels, no cap.
  - GDI: draws through a client-sized copy only while the menu is open (`window.c`:559-579); with it closed it
    stretches `g_bgra` itself, so the H17d notice never shows there.
  - SDL (Linux, the Deck, Android, whose APK builds `window_sdl.c` and stubs `gxv.c`): the same as DXGI
    (`window_sdl.c`:529-559).
  - Vulkan: one overlay callback, `gxv_present_overlay(menu_draw_overlay)` (`window.c`:1114), called once per
    swap-chain present into a host-visible B G R A buffer (straight alpha, blended `SRC_ALPHA, ONE_MINUS_SRC_ALPHA`;
    3840x2400 at most) between acquire and submit, under `g_present_lock` (`gxv.c`:4480-4492). `menu_draw_overlay`
    clears the whole client before it draws, and returns 0, so no GPU pass, when there is nothing to draw.
- **The picture's place** in the window: `picture_layout` (integer or fit, centred, bars), the same on DXGI, SDL
  and Vulkan (`picture.h`:16-20). The menu ignores it: it centres on the whole client.
- **The font:** `menu.c`'s `k_font[95][7]`, printable ASCII 32-126, 5x7 in 6x9 cells, drawn at a whole scale; any
  other byte draws `?` (`menu.c`:39-139, 554-565). `test_menu.py` renders menu.c into a buffer and checks pixels.
- **What the checks see:** `SOA_HASH`, `SOA_SNAP` and `--replay` take the game's picture (`g_screen`) on the guest
  thread before any presenter (`gx.c`:480-484); scenario runs are headless (no presenter at all). The only capture
  of a presented buffer is DXGI's `SOA_WINDOW_TEST=menu@N` (a BMP of `g_scaled`).
- **P5a's filters** (gamma, colour-blind, the flash limiter) run on the picture before anything is drawn over it.

## 2. What M20 adds

- **Two API members, appended** after `claim` (old mods keep loading, `SOA_MOD_HAS`):

  ```c
  int (*draw_rect)(int32_t x, int32_t y, int32_t w, int32_t h, uint32_t rgba);
  int (*draw_text)(int32_t x, int32_t y, uint32_t size, uint32_t rgba, const char* text);
  ```

  - In the game's 640x480 units, mapped onto the picture wherever `picture_layout` puts it, so a layout made once
    sits over the same part of the picture on the Ally X, a Deck, an ultrawide or a phone; outside 0..640 and
    0..480 is allowed and clipped to the window.
  - `rgba`: `0xRRGGBBAA`, straight alpha, blended over the picture (alpha 255 opaque). A rect with w or h at 0 or
    below draws nothing and is not refused.
  - `draw_text`: one line, in the port's font, each character `6 x size` units wide and `9 x size` high, so a mod
    measures without a call; `size` 1 to 8. Bytes outside 32-126 draw `?`. Text of 1 game unit a font pixel is a
    window pixel or two on a handheld, so the guide says size 2 or more.
  - From any callback, on the guest thread: a call only adds to the mod's list for this frame (legal inside the
    battle events and `on_frame_end`, where `call_guest` is not; never from `texture_provider` or
    `projection_filter`, which the renderer calls). Each frame end publishes every mod's list and
    replaces the last frame's: a mod that draws nothing in a frame clears what it drew; while the game is held
    (the menu, a focus pause) no frame ends and the last lists stay.
  - Each returns 1, or 0 when refused: from inside `soa_mod_init`, or past the frame's room -- 256 commands a mod,
    and 4 KB of text a mod -- said once a run per mod.
- **The port's side,** a new `runtime/overlay.c`:
  - per mod, the frame's commands built on the guest thread; at the frame end, after `mod_frame`'s callbacks, the
    lists published through a triple buffer with an atomic index, the screen ring's pattern (`gxr.c`:3214-3288);
    the window thread takes the newest at each present. No mod code runs on the window thread, and nothing it
    reads is guest memory.
  - `overlay_draw(bgra, w, h, stride, rect)` on the CPU presenters, after `picture_scale` and before `menu_draw`
    (the menu and the notice stay on top): DXGI, SDL, and GDI with its client-sized branch widened to "the menu is
    open or the overlay has something".
  - On Vulkan, one composed callback replacing `menu_draw_overlay` at `window.c`:1114: clear, the overlay, then
    the menu and notice on top; nothing drawn and nothing to draw is still no GPU pass.
  - The font moves from `menu.c` to a header both use; menu.c's pixels do not move (`test_menu.py`).
- **Never** into `g_screen` or `g_bgra`: not in a hash, a snapshot, a replay or a recording. Headless runs build
  and publish the lists (the fake guest and the checks see them) and draw nothing.
- **Cost:** with no mod drawing, a version check per present and no GPU pass. On the CPU presenters, the pixels
  drawn (the buffer is rewritten and uploaded every present anyway). On Vulkan, the menu's model -- a full-client
  clear and a full-screen blend each present -- is about 8 MB a present at 1920x1080; acceptable at first, and
  a dirty-rectangle clear is the named follow-up if a measurement says otherwise.

## 3. Not in M20

Anchoring to the 3D scene (an enemy's projected position: R5's own work, from the camera); images and textures;
clipping regions; a notice for mods; the colour filters on the overlay (P5a draws before it: a red and green HP bar
is not corrected for a colour-blind player, which the guide says); fonts beyond ASCII (R5's enemy names wait on Q5
anyway: no English name exists as text on the disc); a dirty-rectangle clear on Vulkan.

## 4. Done

1. **The fake guest** (`test_mods.py`): each call adds to the list and the frame end publishes it; a frame with no
   draws clears a mod's list and leaves another's; the room's limits refuse with one line; a call from
   `soa_mod_init` is refused; a mod built before M20 still loads. *Mutations:* lists not replaced, a limit off.
2. **The rasterizer alone** (a test as `test_menu.py`'s): a list drawn into buffers of two client sizes with
   `picture_layout`'s rect, pixels checked -- a rect's fill and its straight-alpha blend, a glyph's pixels and
   advance, clipping at the window's edge, `?` for a byte past 126; the menu drawn after it covers it. *Mutations:*
   the rect not mapped through the picture's rect, the blend opaque.
3. **On the presenters:** DXGI's `menu@N` capture with an example mod drawing shows its rect over the picture; the
   Vulkan overlay with the same list through `gpuspike.py present --overlay`; SDL built and its window test run in a
   Linux container (CLAUDE.md); GDI with the branch widened.
4. **Nothing the checks see moves:** replay 23/23, and again with the example mod loaded and drawing, since
   `--replay` loads mods and renders a capture through them deterministically: every frame its manifest's hash, in
   one run each (no two live runs compared, rule 7).
5. **An example,** `examples/mods/battle-hp`: the enemies' HP as bars and numbers in a corner from actor+20/+24,
   slots 4-11, only in a battle -- R5's first part, without the anchoring.
6. **Owner:** a look in a window at the example in the story's first battle.
