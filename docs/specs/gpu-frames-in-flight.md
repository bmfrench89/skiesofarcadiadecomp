# H17h: the GPU backend with a frame in flight

Written 2026-10-26 against 47f70bb, from FINDINGS "H17e", "H17f" and "H17g" and PLAN-60FPS-MODS H17h. The owner's
D-45 ("I want the 60fps finished next"): smooth motion pauses in the battle scenario's cutscene aboard Alfonso's
ship because, in display mode, the GPU backend's consumer thread cannot keep up there.

**Built 2026-10-26** (FINDINGS "H17h"): Done 1 to 4. *As built:* a copy's image sampled from the slot in flight is carried into the recording slot's pool by a GPU buffer copy rather than waited for -- without that, two slots only traded the gate's wait for one on copies landing -- and a copy to texture goes in flight at once while the other slot is free (`SOA_GPU_LAND_EARLY=0` keeps it); `gxr_flush` ends with the backend's `settle`, finishing every slot, so the picture is the frame's after it as `gxr.h` promises; the GPU harness reads its picture after `gxr_flush`, so its every check runs frames in flight, and `repeat` holds them to one slot's (`SOA_GPU_FRAMES=1`); `copyimage` runs three routes, the carry forced by `SOA_GPU_POLL=0`. Done 3: p50 33.4 ms against one slot's 36.5. Done 4: no stop before frame 4760; one image a refresh on 87.8% of intervals, 93.7% leaving out the frames without an in-between image.

## 1. Why [V]

- In display mode the cutscene's frame is the consumer's serial path: it records the frame (p95 6.7 ms), then waits
  on its one command buffer for the GPU (p95 12.8 ms), and the producer waits for both at the next frame's first
  draw (the frame gate, p50 3.86 ms a frame). Making the producer cheaper (H17g) only made it wait longer.
- Leaving the frame's last submission in flight with one command buffer (H17f) moved the wait to the next frame's
  first command and changed nothing (p50 36.2 ms against 36.3; 64.9 against 63.2 at 3x).
- So the consumer must record frame N+1 while the GPU draws frame N: a second command buffer.

## 2. What

- **Two slots, one in flight.** Each slot has its command buffer and fence, and its half of the vertex ring, the
  draw records, the texel pool, the texture records and the copy regions (`destbuf`, `imagebuf`): draws name them
  by absolute offsets already, so a half is a base and an end. At most one slot is in flight, the one not being
  recorded; switching slots waits for it, normally long finished.
- **Two ways to submit.** `submit_next` submits the slot being recorded and switches: what a full buffer and the
  frame's end use. `submit_wait` also finishes the other: what needs results now (a copy to land for the producer,
  a depth readback, the GPU harness's tests, a frame whose picture the producer reads).
- **Finishing a slot** waits for its fence, then lands its copies (bytes into guest RAM, images into the producer's
  copy images), adds its GPU time, hands over its frame's real picture (`gxr_backend_screen_late`) and publishes its
  screen slot. The consumer polls the in-flight fence (`vkGetFenceStatus`) at every command and finishes the slot
  the moment it is done, so a frame is published as soon as the GPU has drawn it, and waits for it on its idle.
- **The frame's end.** A screen copy carries `CP_SYNC` when the producer reads the frame's picture once the copy has
  run (a PNG, a hash, `SOA_INTERP=check`); those frames are finished before the copy counts, as today, a slice at a
  time. Any other frame is recorded whole -- real image and slices, the slices without their native-size passes,
  which only a PNG reads -- and goes in flight with `submit_next`.
- **What a slot in flight must not break.**
  - A copy's image is served from the pool only to draws in its own slot. A draw sampling the image of a copy in
    the slot in flight finishes that slot first, so the producer's image has landed when it is uploaded.
  - A copy whose destination overlaps a copy still to land in the slot in flight finishes that slot first: its
    seed must hold what that copy wrote.
  - `gxr_backend_landed` reports the oldest command whose bytes are not in guest RAM: the first copy still to land
    in either slot, or, when none is, the command after the last run. It never moves back.
- **Knobs.** `SOA_GPU_FRAMES=1` keeps one slot, waiting at every submission as before H17h: the A/B. `--mutate
  deliver-early` hands a frame's picture to gxr when it is submitted rather than finished.
- **The replay's repeats** (`SOA_REPLAY_REPEAT=N`): only the last pass writes the PNG, so the earlier passes' screen
  copies go in flight; each later pass's start prints the pass before's picture's hash, so the in-flight route's
  pictures are checked against the synchronous one's. *Corrected 2026-10-26 (the review of the 60 fps work):* each
  pass's own `gxr_flush` finishes its slot (`settle`), so no frame is in flight while the next pass is recorded;
  what `repeat` checks is the hand-over of a picture from a slot finished late, and its guard now asks for two slots,
  where it once passed a run with one.

## 3. Done

1. `gpuspike.py repeat --set corpus,perfset,gpuset`: every capture replayed three times gives, at each pass, the
   single replay's hash, with at least two passes left in flight. *Mutation:* `deliver-early` fails it.
2. Off, the pictures are the same: replay 23/23 at 1, 2, 3 and 8 threads; `gpuspike.py selftest`; `oracle` (33 of
   35, the Dangral pair by design); `contrast --set corpus,perfset,gpuset`; `pairs` and `pairs --weights`.
3. Frames 4100-4599 of the battle scenario uncapped in display mode at 85 Hz, A/B in one build against
   `SOA_GPU_FRAMES=1`: p50 nearer interpolation off's 33.4 ms, and the frame gate's waits down. If frames whose last
   submission holds a copy to land still keep the gate waiting, a copy to texture submits its slot (`submit_next`)
   so that it lands before the frame ends.
4. The battle scenario in a window in display mode at 85 Hz: no budget stop before frame 4000, and the presenter's
   one-image-a-refresh share no lower than H17c-b's 91%.
