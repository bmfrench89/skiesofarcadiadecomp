# H17c: in-between images at the display's own rate

Written 2026-10-25 against bf81812 plus the two defect fixes of FINDINGS "Two defects in H17b and V12", from the owner's
D-45 ("I want the 60fps finished next"; "60fps should be the games new default right?") and the research it asked for,
[research/60fps-across-ports.md](../research/60fps-across-ports.md). It is the first of that research's four items
before 60 becomes the default: a display-rate mode, so that every target screen gets smooth motion, not only one at
60 or 120 Hz.

**H17c-a built 2026-10-25** (FINDINGS "H17c-a"): Done lines 1 to 3. *As built:* the slices are stacked, not in a grid
(at 3x a 4096-row device holds one); each slice's screen copy is its own submission, not batched; the GPU-against-GPU
rule of Done 1 is "no pixel more than 16 levels apart beyond 0.005%", since a slice lower in the image rasterizes a
little differently (up to 9 levels at the third slice) and V12's one-level rule holds for the first alone; Done 2's
producer check is the GPU harness's (F+1's positions in place of F's fails it as `noweight` does), with the CPU's
refusal of more than one weight in `test_gxr_pair.py`. `display` itself is H17c-b's.

**H17c-b built 2026-10-25** (FINDINGS "H17c-b"): Done lines 4 and 5; 6 and 7 wait for the owner's displays at
session D. *As built:* `VK_KHR_present_wait2` (with `present_id2`), the extension this PC's driver has, not the
first `present_wait`; the window woken when the GPU publishes a frame, which took one-refresh intervals from 72% to
91% and frames cut short from 285 to 15; a cut shows its real image for the frame's refreshes; the budget still
turns the stream off and on; Done 5's 95% is 91.2% over the title's run with its loads (94.6% leaving out
presents whose predecessor was already on screen when they waited).

**Why.** Today one in-between image is built per real frame, at the midpoint, and shown only where the display runs
within 2% of 60, 120, 180 or 240 Hz (`present_interp`, `runtime/picture.c:52`). The owner's 85 Hz monitor, a Steam Deck
OLED at 90 Hz and a 144 Hz monitor get none; at 120 Hz the Ally X shows 60 distinct images a second, each held two
refreshes. The mature answer, shipped as the default by the N64 recompilations, is RT64's "Display" mode: as many
images per game frame as the display refreshes, each blended at its own point in time, evenly spaced
(`rt64_workload_queue.cpp`; research §"Serving every screen").

## 1. What is there [V, at HEAD]

- **One in-between command per draw.** `gxr_draw_inner` (`runtime/gxr.c:2610`) publishes the real command, then a copy
  with `efb` 1 whose vertex block is the real one with x, y, z, w lerped at `g_pair_t` (0.5, set once,
  `gxr.c:2187`) from the previous frame's positions (`pair_positions`, `:2430`). Colours, texture coordinates and TEV
  state are F+1's. Unmatched and demoted draws keep F+1's positions.
- **The GPU backend** draws `efb` 1 into the lower half of colour and depth images twice as tall (`g_halves`,
  `runtime/gxv.c:3075`), through a dynamic viewport and scissor moved down by EFB_SH; its screen copy reads that half
  into a partner slot (`gxv.c:1910-1969`). Vertices reach `raster.vert` through a storage buffer, 39 floats a vertex
  (`runtime/gxv/raster.vert:39`); the push constants are 32 bytes (`PushDraw`, `gxv.c:331`). Clipping is done on the
  CPU in the consumer, for draws with a vertex outside the volume (`gxv.c:1389-1443`, `1519-1526`).
- **The presenter** (`gxv_present`, `gxv.c:3994`) shows a taken slot's in-between image for `g_mid_ivl` refreshes,
  then the real frame for `interval`, all FIFO presents (`gxv.c:3736`). Since the fix of 2026-10-25 the window presents
  when a slot is published (`gxv_screen_fresh`), polling every 8 ms.
- **The refresh rate** comes from `DwmGetCompositionTimingInfo(NULL)` (`runtime/window.c:176-184`), DWM's global
  timing, re-read on `WM_DISPLAYCHANGE` but not when the window moves to another monitor.
- **The budget** (`interp_frame_begin`, `gxr.c:2508`) turns the stream off after three frames over 35 ms and backs off
  before trying again; the cut detector (`frame_is_cut`) marks a frame whose in-between image must not be shown.
- **The cost** (FINDINGS "V12"): about 1.35 ms of GPU time and 0.45 ms of consumer CPU per in-between image at 1x;
  0.8-1.1 ms of the producer's per in-between stream.

## 2. What H17c adds

**The images of a frame: an accumulator, RT64's.** With the display at R Hz and the game's 30 frames a second, each
game frame gets the refreshes that fall in its interval, each blended at the time it falls: refresh i shows the game
at s = i * 30 / R frames, so frame F+1's images are the refreshes with s in (F, F+1], at weights w = s - F in (0, 1].
A weight of 1 is F+1's real image; every other weight is an in-between image. Integer ticks, as RT64 keeps them
(`ticks += 30` a refresh, a frame's images the ticks it crosses), so 85 Hz gives 17 refreshes every 6 frames, one
frame of 2 images and five of 3, at weights such as 0.35, 0.71 and then 0.06, 0.41, 0.76; 90 Hz gives 1/3, 2/3 and 1
every frame; 144 Hz 5, 5, 5, 5, 4. The display's rate is
rounded as RT64 rounds it (59 and 59.94 count as 60, 119.88 as 120, 143 as 144). The weights of a frame are fixed when
it begins, at the screen copy before it (`interp_frame_begin`), and travel with its in-between commands.

**Slices: one in-between command, drawn once per weight, on the GPU.** H17a's single in-between command stays, and the
producer's cost does not grow with the image count:
- The in-between command carries F+1's vertices and a block of F's positions (16 bytes a vertex, in the arena; none
  for an unmatched or demoted draw), in place of the CPU-lerped copy, and the frame's weights.
- The backend uploads it once and draws it once per slice: the slice's viewport and scissor, and push constants
  naming the weight and where F's positions start. `raster.vert` lerps x, y, z and w under `precise`, as
  `pair_positions` does, so a slice at weight t is the CPU-lerped image at t.
- A draw with any vertex of F or F+1 outside the clip volume is lerped and clipped on the CPU per slice, as V12 does
  for every draw today: clipping is what the GPU cannot repeat per weight.
- The slices sit in a grid inside the colour and depth images, within the device's `maxImageDimension2D` (16384 on
  desktop drivers, 4096 guaranteed), so 5 slices fit at 3x on any device; the count is capped there and by memory (at
  3x a slice is about 12 MB of colour and depth, and one partner image a ring slot). The interlock and snapshot routes
  index by the fragment's own coordinate (`raster.frag:266-277`) and need no change.
- Each slice's screen copy fills its partner image; the last publishes the slot, as V12b's in-between copy does. The
  copies are batched in one submission, not one GPU round trip each.

**The presenter: one image a refresh.** A taken slot's images are presented in weight order, one refresh each (FIFO,
interval 1), the real image only where a weight is 1. A frame whose images have all been shown before the next slot
is published leaves its last image on screen (a repeat, counted). A slot published while the frame before still has
images to show supersedes them (RT64's frame reduction, counted). Where the device has `VK_KHR_present_wait`, each
present waits for the one before to reach the screen, so no more than one image is queued and nothing is shown late;
without it, FIFO's own blocking with the swap chain's minimum images. At a cut, the refreshes before the real image
hold the frame before, as H17b does.

**The display's rate, per monitor.** The window reads the refresh of the monitor it is on (`MonitorFromWindow`, then
that monitor's display mode), and again when it moves (`WM_MOVE` crossing monitors, `WM_DPICHANGED`) or the mode
changes. The producer is told through `gxr_interp_show`, which takes the rate instead of on or off.

**The switch.** `interp = display` (env `SOA_INTERP=display`), alongside `0` and `1`, in soa.ini and the menu.
`display` needs the GPU backend; with the CPU renderer it says so once and runs as `1`. `1` keeps today's meaning:
one in-between image, shown at 60, 120, 180 or 240 Hz. The default stays `0`: D-45 makes `display` the default only
after the other three items and session D.

**The budget, by slice.** Three frames over 35 ms take one slice away rather than the whole stream; back on time, one
is given back after the existing back-off. At no slices the stream is off, as today, and the frame is drawn as it is.
*Built as H17k* (FINDINGS "H17k", 2026-10-26), after H17e changed the rule to the median of the last 31 frames over
35.5 ms: each step down takes one image a frame away -- the weights then at the rate the rest serve, 60 at 85 Hz,
as a device holding fewer slices has them -- and at none the stream is off; each step back up waits V12's count.

**The report.** `[interp]` adds the display's rate, images per frame (the mean and the range), slices drawn, repeats
and frames superseded; `[gxv]` the GPU time of the slices.

## 3. Not in H17c

- The visible fallback (D-45's second item: the player told when the device cannot keep up), Android's 60 Hz request
  (the fourth), and session D's classes (the third, H18): their own slices.
- VRR: on a variable-refresh screen `display` reads the panel's top rate; tearing-allowed presents within the VRR
  range are a later option.
- The CPU renderer at more than one in-between image: it cannot hold one (FINDINGS "H17a").
- Lerping colours, texture coordinates or lighting: they stay F+1's in every slice, as today, so fades and scrolling
  textures step at 30 (research: the "paper effect" and texture-scroll work other ports did).

## 4. The slices

- **H17c-a, the slices headless** (several days): the in-between command with F's positions and the frame's weights;
  the backend's fan-out, grid and batched copies; `raster.vert`'s lerp; the CPU fallback for clipped draws;
  `SOA_INTERP_WEIGHTS=t1,t2,...` (a check's knob) fixing a frame's weights headless, and `SOA_SNAP` writing
  `NNNN.mid1.png` onward.
- **H17c-b, at the display's rate** (several days): the accumulator, the per-monitor rate, the presenter's one image a
  refresh with present-wait and frame reduction, `interp = display`, the budget by slice, the report.

## 5. Done

Each line names its command and the mutation that proves the check can fail.

**H17c-a**
1. `gpuspike.py pairs --weights 0.25,0.5,0.75`: on H10's five pairs, each slice's image against the CPU three-pass
   replay at `SOA_PAIR_T` of its weight passes V0, as V12's single image does, and against the GPU's own CPU-lerped
   image at that weight differs at no more than 0.05% of pixels by one level. *Mutation:* `raster.vert` ignoring the
   weight (every slice the midpoint) fails the 0.25 and 0.75 slices.
2. `test_gxr_pair.py`: the producer's in-between command carries F's positions for matched draws and none for
   unmatched and demoted ones, and the frame's weights; `SOA_INTERP=display` with the CPU renderer runs as `1` and
   says so. *Mutation:* positions recorded after the lerp (F+1's instead of F's).
3. Off and `1` change nothing: replay 23/23 at 1, 2, 3 and 8 threads, `contrast --set corpus,perfset,gpuset`,
   `gpuspike.py pairs` (V12's line, weight 0.5 alone), `title --check`.

**H17c-b**
4. `test_picture.py`: the accumulator's images per frame and weights for 60, 85, 90, 120, 144 and 165 Hz, held to the
   arithmetic (85: 2, 3, 3, 3, 3, 3 over six frames, the sixth ending on weight 1; 90: 1/3, 2/3, 1; 60: 0.5, 1;
   144: 5, 5, 5, 5, 4), and the rate rounding. *Mutation:* weights spaced evenly
   inside each frame (j/n) instead of by refresh time, which fails 85 and 144.
5. On this PC, the `title` scenario in a window with `SOA_GPU=vulkan SOA_INTERP=display` at 85 Hz: the `[present]`
   histogram puts at least 95% of intervals at one refresh, and images shown a second come within 3% of 85 (the
   report's own count), with the real frames a second what they are with `interp = 0` (an interleaved pair of runs).
   *Mutation:* the presenter showing each slot's images and then waiting for the next slot with no frame reduction:
   the histogram's share at one refresh falls.
6. The same at 60 Hz, which the owner sets for the run or which waits for session D: `display` and `1` show the same
   images at the same refreshes (one in-between at 0.5, then the real frame).
7. Moving the window to a monitor at another rate retargets it: the `[interp]` line names the new rate (a check on a
   second display, or the owner's at session D).

## 6. H17d: the player told

Written and built 2026-10-25, D-45's second item, a fallback the player sees (research: BlueWake's counter that
read 60 while smooth motion was paused, ogdanimal's settings opened once on a slow device). Until now a machine that
could not keep up, or a display interp = 1 cannot pace, said so in the log alone.

- **What it is:** a notice in the picture's lower-left corner for four seconds, on a dimmed band in the menu's font,
  drawn over either presenter whether or not the menu is open (`menu_notice`; `menu_draw_overlay` now draws for a
  notice too). The window watches what the in-between images are doing and posts one when it changes: shown ("Smooth
  motion: 85 images a second, the display's rate", or 60), refused with its reason ("Smooth motion off: the display
  is at 85 Hz; interp = display serves any rate", the presenter, turbo), paused over budget ("Smooth motion paused:
  the game is running behind") and back ("Smooth motion on again"); each is logged as `[notice]`. Nothing with
  `interp = 0`.
- **Not here:** the SDL window (Linux) draws a notice but posts none yet; touching `window_sdl.c` asks for the Linux
  check in a container, left for the slice that next changes it.
- **Done:**
  1. `test_menu.py`: with the menu closed a notice draws its band and its text, the overlay says it drew, and taken
     away neither does. *Mutation:* the notice drawn only with the menu open.
  2. On this PC in a window: each notice in its run's log -- `interp = 1` at 85 Hz on the GPU and on the CPU, refused
     with the display's rate; `display` at 85 Hz, shown; the CPU renderer with in-between images forced at 85 Hz
     (`SOA_INTERP_ANYRATE`), paused over budget and back.
