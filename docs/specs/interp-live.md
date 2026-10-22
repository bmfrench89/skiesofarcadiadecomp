# H17b: interpolation, live, in a window

Written 2026-10-22 for the owner's answer that day (PLAN-NEXT D-42: "H17b, then V12"), from
[PLAN-60FPS-MODS.md](../PLAN-60FPS-MODS.md) H17b, H17a's spec and measurement ([interp.md](interp.md), FINDINGS
"H17a"), and FINDINGS "H8" for the presenter. The code was mapped first, at 399c03f.

**Why.** H17a makes the image between two frames, headless. H17b shows it: between real frames N-1 and N the
window shows the in-between image for one refresh at 60 Hz (two at 120 Hz), so the picture changes 60 times a
second while the game's logic still runs at 30. It must never make the game itself slower, and it must never show
an image that is wrong in a way a repeat would not be.

## 1. What is there

- **H17a** (gxr.c): with `SOA_INTERP=1` every draw is built twice, the second time into EFB 1, and the in-between
  screen copy lands in `g_screen_mid` after the real one lands in `g_screen`. Nothing in the window reads it.
- **The presenter** (window.c, H8; window_sdl.c on Linux and Android): a UI thread polls `gxr_presented()` every 8 ms,
  and on a new frame converts `g_screen` to `g_bgra`, scales it to `g_scaled`, and presents with DXGI's flip model
  (two buffers, frame latency 1) or SDL's renderer, with a sync interval of `present_interval(hz, 30)`: 2 at 60 Hz,
  4 at 120 Hz, 1 at 85 Hz. The `[present]` report gives the interval's histogram in refreshes and its p50 and p99.
- **`g_screen` has one buffer** (PLAN-NEXT B1): the next frame's screen copy can overwrite it while the UI thread is
  converting it. Under H17b the presenter holds frame N for a whole refresh after its in-between image, so the race
  becomes a likely one rather than a rare one.
- **What it costs** (FINDINGS "H17a", every frame drawn, uncapped): the field fell from 32.5 real frames a second to
  20.4 with the in-between stream on, the cutscene from 20.4 to 16.1. Under the 30 fps cap, building every in-between
  image would slow the game in all four scenes measured.

## 2. What H17b adds

- **A screen ring** (closes B1). Three slots, each holding a real frame and its in-between image (or none). The worker
  that finishes a frame's last screen copy (the real one when no in-between follows, else the in-between one; the
  producer marks which) copies `g_screen` and `g_screen_mid` into the free slot and publishes it, in the manner of
  gxv.c's `SCREEN_FRESH` triple buffer. The next screen copy cannot start before that command has finished (its entry
  fence), so the copy reads a finished frame. The UI thread takes the newest slot. Headless PNGs and hashes still read
  `g_screen` as they do.
- **The presenter's two images** (DXGI and SDL): on a new slot with an in-between image, present it with the sync
  interval of one 60 Hz refresh (`present_interval(hz, 60)`), then the real frame with the same interval. A slot with
  no in-between image is presented as today. Only where the display runs at a whole multiple of 60 (60, 120, 180, 240
  Hz); elsewhere (85 Hz) the window says so once and the producer is told to stop building the in-between stream, so
  nothing is spent on images nobody sees. The GDI presenter has no refresh to pace by and does the same. Showing the
  in-between image first delays every real frame by one 60 Hz refresh, 16.7 ms.
- **The budget: the in-between stream is built only when it fits.** At each frame's start the producer decides whether
  this frame gets an in-between stream, from the frames before it: the render span of the last frame (its first
  command to the last worker finishing its last screen copy) against the frame time (33.3 ms), with the in-between
  share of that span measured on the last frame that had one. Over budget, the next frames build none, and the
  presenter repeats; the pair machinery still records every frame, so the stream resumes on the first frame in budget.
  The thresholds and hysteresis are set from the four scenes' runs and recorded in FINDINGS. The guard is the game's
  own frame rate: with interpolation on it may not fall below what it is off.
- **The cut detector.** At a camera cut, draws match across the pair (same display lists, same textures) and their
  positions jump, so the lerp makes a frame that belongs to neither (H17a's battle at frame 4000). Per frame the
  producer counts the 3D draws keyed, matched, and matched with a vertex displaced more than D pixels. A frame whose
  matched share falls below H4's 90%, or whose displaced share is over a threshold set from the same runs (the battle
  cut and its neighbours among them), is a cut: its in-between image is not shown and the real frame before is held
  instead.
- **The switch:** a `soa.ini` key `interp = 0|1` (env `SOA_INTERP`), off by default, in the menu's Settings page,
  applying at the next start like every key there. `SOA_INTERP=check` stays headless-only.
- **The report:** one `[interp]` line beside `[present]`: images shown, in-between images shown, frames repeated over
  budget, frames repeated at a cut, and the slots the presenter missed (a slot superseded before it was shown).

## 3. Not in H17b

The GPU backend's second EFB and the Vulkan presenter's two images (V12, next by D-42); the artifact classes the owner
lists (H18); turbo with interpolation (turbo already presents at 60 and has no in-between to show: the two are refused
together, said once).

## 4. Done

1. **Off changes nothing:** replay 23/23 and `title --check`; a windowed run with `interp = 0` presents as before
   (the `[present]` histogram's shape at the same display rate). *Mutation:* the ring publishing a slot one command
   early is caught by the ring's own test below.
2. **The ring:** a test on the renderer built alone (as `test_gxr_pair.py` builds it) runs frames through the ring at
   1 and 4 threads with a reader that holds each slot as long as a 60 Hz presenter would, and every slot read is a
   whole frame (its real image's hash equal to the frame's `SOA_HASH`). *Mutation:* publishing before the last worker
   finishes fails it.
3. **The cut detector:** in `test_gxr_pair.py`, a synthetic pair with the camera moved far (every draw matched,
   displaced past D) and one of two unrelated captures (nothing matched) are both cuts; the small moves H10's tests
   use are not. *Mutation:* the threshold at infinity misses the far move.
4. **The budget:** windowed, capped runs on this PC of the opening, a field walk and a battle, interpolation off and
   on: the game's real frames a second with it on not below off by more than run-to-run noise (measured from two off
   runs); the share of real frames that got an in-between image shown; the present interval's p99 within one refresh
   of 16.7 ms over the stretches where every frame got one. These are measured where the display can run at 60 or
   120 Hz; where this PC's display cannot, the sequencing is checked with the display's own rate reported and the
   pacing left to the owner's session.
5. **The owner** at session D (60 or 120 Hz, D-2): does 60 look right, and a list of anything wrong, filed as H18's
   input.
