# V12: the in-between images on the GPU

Written 2026-10-22 for the owner's answer that day (PLAN-NEXT D-42: "H17b, then V12"), from
[gpu-backend.md](gpu-backend.md) V12 and 3.1, [interp.md](interp.md) (H17a), [interp-live.md](interp-live.md) (H17b)
and FINDINGS "H17a" and "H17b". The code was mapped first, at 7c4d896.

**Why.** The CPU renderer reaches 32 to 43 images a second with interpolation on the Ally X, so H17b's budget keeps
the in-between images off in the opening and the field. The Vulkan backend draws a frame for 1.1 cores against the CPU
renderer's 4.8 (FINDINGS "V6a"); drawing the in-between stream there is what can make 60 real. Today `SOA_INTERP` is
refused with any backend.

## 1. What is there

- **The stream** (H17a, gxr.c): each draw is published twice, the second with `DrawCmd.efb` 1; EFB clears go to both
  EFBs; a copy to texture is the real stream's alone; the screen copy is published twice, the in-between one marked
  `CP_LAST | CP_MID` (H17b) and the real one, when an in-between copy follows, not `CP_LAST`.
- **One EFB on the GPU** (gxv.c): `g_color` (RGBA8) and `g_depth` (D32F), EFB_SW x EFB_SH (640x528 times
  `SOA_GPU_SCALE`), one render pass and framebuffer (`g_pass`, `g_fb`), an attachment-less interlock pass that reads
  the colour image as storage image binding 5, and `efb_to_buffer`, which copies the colour image into `g_readback` for
  copies to texture, the screen copy and the snapshot logic route. The viewport is static pipeline state covering the
  EFB. Nothing reads `D->efb`.
- **Every screen copy is read back** into `g_screen` (`gxr_backend_screen`), then published to the Vulkan presenter's
  triple buffer, which presents what it holds; `frame_mark` counts every screen copy as a frame.
- **A gap in H17a** (found mapping this): with a backend, whose copy never clears, the real copy's clear is published as
  its own command, but the in-between copy's is published only when the copy is foreign, so an unfiltered in-between
  screen copy would never clear EFB 1.

## 2. What V12 adds

**V12a: the second EFB, headless.**
- **One image, two halves.** Real and in-between draws arrive interleaved, one after the other, so two framebuffers
  would end and begin a render pass at every draw. Instead the colour and depth images are twice as tall, the real EFB
  the upper half and the in-between one the lower. A command with `efb` 1 draws with the viewport and scissor moved
  down by EFB_SH (the viewport becomes dynamic state; the real half's viewport is exactly today's, so real frames
  rasterize as before), clears its own half, and copies from its own half; the interlock route reads the storage image
  at the fragment's own coordinate, which already lies in its half, and the snapshot route copies its own half into
  `g_readback`.
- **Its screen copy** reads back into `g_screen_mid` (`gxr_backend_screen_mid`), never `g_screen`, and is not a frame
  for `frame_mark` or the presented count.
- **The clear gap closed** in gxr.c: the in-between screen copy's clear published as its own command with a backend, as
  the real copy's is.
- **`SOA_INTERP` allowed with the Vulkan backend**; still refused with the passthrough test backend and `SOA_GXR_DRAWS`.
- **The `[gxv]` report** says how many in-between draws, clears and screen copies it ran, and the GPU time per frame
  with both images.

**V12b: shown in the window.** The Vulkan presenter's slots hold a real image and the in-between image before it, at
the GPU's resolution. A real screen copy that is not `CP_LAST` fills its slot's real image and waits; the in-between
copy fills the other image and publishes the slot. `gxv_present` shows the in-between image for one 60 Hz refresh and
then the frame, under H17b's rules: the display at a whole multiple of 60 Hz, the cut flag holding the frame before,
and the budget, which reads the game's frame time whichever presenter there is. `[interp] shown` counts as H17b's do.

## 3. Not in V12

The artifact classes (H18); interpolation at 2x or 3x on the CPU presenter; any change to the CPU renderer's own
output.

## 4. Done

1. **Off changes nothing:** `gpuspike.py selftest`; `contrast --set corpus,perfset,gpuset`, all 67 the same pixels,
   spike and `soa.exe`; replay 23/23 and `title --check` (the CPU's). *Mutation:* the real half drawn with the moved
   viewport fails `contrast`.
2. **The live stream is the GPU's own midpoint, byte for byte:** `gpuspike.py pairs` runs H10's five pairs
   (`build/perfset`) on the GPU twice, `--replay A B` with `SOA_INTERP=1` (two passes, both streams) and without
   (three passes), and both `B.png` and `B.mid.png` are byte-identical between them. *Mutation:* the in-between
   command drawn in the real half differs.
3. **The GPU's in-between images pass V0 against the CPU's:** the same five, `B.mid.png` on the GPU against the CPU's,
   under `imgdiff`'s V0 thresholds, as `oracle` holds single frames.
4. **The real frame untouched:** `SOA_INTERP=check SOA_GPU=vulkan`, one live run, every frame's real picture the same
   before and after its in-between copy.
5. **The cost:** `partl`, 3000 frames, every frame drawn, `SOA_GPU=vulkan`, with and without `SOA_INTERP=1`: the
   `[gxv]` GPU time per frame (p50, p99) and the consumer's, both runs; the in-between image's GPU cost, the difference
   of the p50s, under 4 ms at 1x (gpu-backend.md's limit).
6. **V12b, in a window** on this PC (85 Hz, `SOA_INTERP_ANYRATE=1`): the game's real frames a second with
   interpolation on not below off, and the share of frames that got an in-between image shown, in the opening and
   `126a`; the pacing and the look at session D with H17b's.
