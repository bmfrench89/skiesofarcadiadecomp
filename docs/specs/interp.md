# H17a: interpolation, headless, off by default

Written 2026-10-22 for the owner's choice that day (PLAN-NEXT D-41: "60fps go"), from
[PLAN-60FPS-MODS.md](../PLAN-60FPS-MODS.md) H17a (its Done restated by PLAN-GAMEPLAY-MODS §F), PLAN-NEXT A3 and
M2 row 3, ARCHITECTURE.md section 12's retention rules, and gpu-backend.md 3.1's routing. The code was mapped
first, at 14ee174.

**Why.** The game makes 30 images a second. 60 needs an image between each pair, made from the two frames'
geometry: H10 showed offline that matching draws across a pair and lerping their positions makes a right
midpoint in all five pairs. H17a makes those images during a run, headless, as a second stream of draw
commands, so H17b can show them in a window and the GPU backend can draw the same stream later (V12).

## 1. What is there already

- **H10's pair machinery** (gxr.c, "frame pairs"): `pair_key` (the display-list address, array bases, texture
  addresses, TEV and blend state), `pair_claim` (the oldest unmatched record of the previous frame with the same
  key and count), `pair_positions` (records a frame's transformed x, y, z, w, or lerps a matched draw's), and
  `pair_rotate` at the screen copy. `soa.exe --replay A B` runs it offline in three passes: A recorded, B as it
  is, B lerped (`B.mid.png`). `test_gxr_pair.py` and `tools/midpoint.py` hold it.
- **The routing field:** `DrawCmd.efb` (0 the real frame, 1 an in-between image), stamped by `claim_slot` from
  `g_target`, which only the guest thread sets (`gxr_set_target`). No consumer reads it yet: every pixel
  function indexes the one `g_efb` / `g_efb_z`.

## 2. What H17a adds

- **A second EFB,** `g_efb_mid` / `g_efb_mid_z`, and every CPU consumer -- the depth test, the blend, the clear,
  the copies to texture and to the screen, the copy filter -- taking its EFB from the command (`D->efb`), never
  from a global. With `efb` 0 everywhere the renderer is what it was.
- **`SOA_INTERP=1`:** the pair machinery records and lerps at once (the "second span" `gxr_pair_mode` refuses
  today). In `gxr_draw_inner`, each draw is built as now -- F+1's positions, recorded for the next frame -- and
  then built again for the in-between stream: a second slot claimed with `g_target` 1, the same TEV, pixel and
  raster setup and the same texture pointers (so it samples what F+1 samples and holds nothing past the frame,
  ARCHITECTURE 12), and its own vertex block in the arena holding the lerped positions where the draw matched,
  F+1's where it did not. The real command's vertices are no longer overwritten.
- **Clears and copies in the in-between stream:** an EFB clear is published to both EFBs. A copy to texture is
  the real stream's alone (the in-between stream skips it, keeping its clear, as H10's LERP pass does). The screen
  copy is published twice: the real one as now, and the in-between one, which copies EFB 1 into a buffer of its
  own (`g_screen_mid`) and touches none of the real frame's state -- not `g_screen`, the presented count, the
  frame gate, the rotation, the hash or the PNG naming.
- **Headless output:** where `SOA_SNAP` writes frame N as `NNNN.png`, the image between N-1 and N is written as
  `NNNN.mid.png`.
- **The report,** one `[interp]` line at the end: in-between images made, draws matched and drawn from F+1, the
  producer's extra time per image, the images a second the run reached with them (real and in-between), and how
  many real frames' `g_screen` the in-between pass left as it was.
- **Refused, said:** `SOA_INTERP` with a GPU backend (its second EFB is V12), and with `SOA_GXR_DRAWS`.

## 3. Not in H17a

Showing the images (H17b: the presenter, the cut detector, repeat when over budget, the `soa.ini` key), the
artifact classes (H18), and the GPU backend's second EFB (V12).

## 4. Done

1. **Off changes nothing:** replay 23/23 at 1, 2, 3 and 8 threads, and `title --check`. *Mutation:* routing one
   consumer by `!D->efb` moves the replay's hashes.
2. **The live stream makes H10's midpoint, byte for byte.** `test_gxr_pair.py`: `--replay A B` with `SOA_INTERP=1`
   runs A recorded, then B once with both streams, and its `B.png` and `B.mid.png` are byte-identical to the
   three-pass replay's `B.png` and `B.mid.png`, for every synthetic scene the file builds, at 1 and 4 threads.
   *Mutation:* the in-between command taking F+1's positions (no lerp) differs from `B.mid.png`.
3. **The in-between pass never touches the real frame:** in one live `SOA_INTERP=1` run, each real frame's
   `g_screen` is hashed when its own copy has landed and again when the in-between copy has, and the report says
   they agree at every frame. *Mutation:* the in-between screen copy written into `g_screen` makes them differ.
4. **The images, opened:** in-between PNGs from a field, a battle, a ship battle and a cutscene (live runs with
   `SOA_SNAP`), each next to its two real frames.
5. **The measurement:** the `[interp]` line from those runs, the images a second each scene reaches, recorded in
   FINDINGS as the input to PLAN-NEXT A2 (b) and A3.
