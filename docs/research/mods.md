<!-- Written 2026-09-24 by a read-only research agent for docs/PLAN-60FPS-MODS.md; nothing was
run. [V]/V marks what was read from quoted instructions, file:line or logs; [I]/I is inference. -->

# Native PC mods and enhancements on the GEAE8P port: architecture

Everything here comes from reading the code only. I did not run anything and I changed no repository files. All paths are under `C:/Users/bmfre/Documents/Github/SOA/`. **[V]** means I checked it against the quoted code, a file:line or the disassembly. **[I]** means it is inference. r13 = 0x8034E720 and r2 = 0x80350000.

---

## 0. Summary

1. **The port has four ways for native code to take over from guest code, and none of them loads at run time.**
   - **Link-time replacement** (`config/hle.txt`), **pre-instruction hooks** (`config/hooks.txt`) and **tracepoints** (`config/trace.txt`) are all baked into the translated C. Each change costs a full retranslation, about 2 minutes.
   - **`SOA_POKE` and `SOA_WATCH`** work at run time, but a poke is a one-shot write at the end of a frame, and the watch covers one range of stores.
   - Nothing in the runtime loads a DLL, keeps a list of callbacks, or calls a guest function on a mod's behalf.
2. **I verified from the disassembly that the game runs one logic tick per presented frame, and each frame takes at least 2 VI fields.**
   - The main loop calls the scene dispatcher once per iteration. `fn_801DC420` then waits until the retrace count has moved by 1 since the loop started, and calls `VIWaitForRetrace` on top of that.
   - That is a structural 30 fps cap, which drops to 20 fps when a frame runs over. It partly answers PLAN's open question "is the logic clock the VI retrace or the presented frame": it is the presented frame, and the presented frame is paced by VI.
3. **One `hle.txt` binding gives mods both a safe per-frame point and a switch for game speed.** Binding the 8-byte leaf `VIGetRetraceCount` (`fn_8023F704`) natively does both, with one retranslation and no change to the emitter. After that, most mods need only a relink or no rebuild at all.
4. **Decompilation (Track F) is needed only for mods that change logic *inside* a function.** Pokes, pre/post hooks and renderer features need only addresses.
   - Today's native path cannot run game code at all. It has no big-endian accessors over guest memory and no way for native code to call back into guest code. Even `C_MTXFrustum`, which is already matched, is not native.
   - Those two pieces are therefore the first mod-relevant work in Track F.
5. **Easy (relink, known addresses):** encounter-rate toggle, a battle speed-up by raising the tick rate, save anywhere (with one known trap), a debug/warp menu, and texture dump and replace.
6. **Medium to high:** widescreen, camera controls, faster text.
7. **Gated behind renderer speed (C4 or a GPU backend) and more research:** higher internal resolution and true 60 fps.

---

## 1. What exists today

### 1.1 Mechanisms and what each costs to change

| Mechanism | Where | What it does | Cost to change |
|---|---|---|---|
| **HLE binding** (link-time replacement) | `config/hle.txt` (19 entries, 12 of them decompiled); parsed by `tools/soa/hle.py:22,25-58`; emitted at `tools/soa/recomp/emit.py:244-248` | The translated body is renamed `recomp_fn_X`, and the runtime's own `fn_X` wins the link. Every caller binds to the native version with no change to the call site. The original body stays in the exe, so native code can call it back. [V] | Full retranslation (CLAUDE.md). Adding a line and only relinking gives LNK2005; removing one silently leaves the native version in charge. |
| **Pre-instruction hook** | `config/hooks.txt` (1 entry: `0x80237BA8`); `emit.py:257-258` emits `hook_X(s);` before the instruction at X | Native code runs with full access to `CpuState` at any address. A hook at a function's entry catches direct calls, tail calls (`fn_T(s); return;`, `emit.py:311-312`) and `dispatch` (`emit.py:277-285`), because all three enter the C function at its top. [V] | Full retranslation. **Side effect:** any hook in a function removes `irq_poll` from every back-edge of that function (`emit.py:240`, `:309`). A mod hook placed in a loop that spins waiting for an interrupt would hang. |
| **Savepoints** | `config/savepoints.txt` | Wraps a call site in `setjmp`, for thread parking. Not usable for mods. | Full retranslation. |
| **Tracepoint** | `config/trace.txt`; `emit.py:259-260`; `runtime/trace.c:32` | `trace_hit` prints registers when `SOA_TRACE` is set. It is read-only. | Full retranslation. |
| **`SOA_POKE`** | `runtime/main.c:684-786`, installed at `:976-977` | Up to 256 one-shot 32-bit writes at "frame ≥ N". Each prints the value it replaced, so it doubles as a read. It refuses MMIO addresses. [V] | None (environment variable). |
| **Frame hook** | `runtime/gx.c:79-86`, called at `gx.c:148` inside `frame_end` | **Only one function-pointer slot**, and `SOA_POKE` already uses it. It fires inside `load_bp`, that is, inside a guest gather-pipe store made by `GXCopyDisp` (`fn_8024F194`, called at 0x801DC484). [V] | Relink. |
| **`SOA_WATCH`** | `runtime/cpu.h:146-150`, `trace.c:65-95` | One range. A compare is inlined into every `mem_w*`. Prints the first 201 hits with a backtrace. Stores only; loads are not watched. [V] | None at run time. Changing the mechanism means editing `cpu.h`, which is a full retranslation. |
| **Decompiled swap-ins** | `runtime/decomp_swap.c:36-75` | Five-line EABI adapters: r3-r5 in, r3 out, host pointers from `mem_ptr`, onto `dc_*` bodies. [V] | Full retranslation (hle.txt). |
| **`dc_` renames** | `tools/recompile.py:60-83` | `/Dname=dc_name` for every function a `native` unit defines or declares. Units are built at `/O2` at link time. [V] | Relink. |
| **Native units** | `config/GEAE8P/units.txt` (21 units, 8 marked `native`) | A unit may be native only if it is byte-order-free, touches no MMIO, reads no game globals, and calls nothing undecompiled (`recompile.py:64-67`). [V] | Relink. |
| **Native calling guest** | `runtime/irq.c:276-291` (`call_guest_handler`), and `irq.c:460` around the scheduler | Save the register file, set r3/r4, call `dispatch(s, addr)`, restore. `main.c:55` keeps the single `CpuState*` in `g_state`. [V] | This pattern is only reachable from inside `irq.c`. |

Measured build costs (`docs/TESTING.md:304`, `HANDOFF.md`): the `/O2` compile of the translated code takes 103 s on 16 cores, and a link takes about 20 s. A full retranslation is therefore about 2 minutes: acceptable for development, not for a user flipping a mod.

### 1.2 Facts about the guest ABI that the design relies on [V]

- **One struct holds all guest state.** `CpuState` (`cpu.h:65-76`) has the GPRs, FPRs (ps0/ps1), CR, LR, CTR, the eight GQRs, and a `void* user` field that is runtime-private.
- **Guest memory is one big-endian image.** Every access goes through `mem_r*`/`mem_w*`, which byte-swap (`cpu.h:120-204`). A write into `.text` has **no effect on execution**, because the code was translated from the DOL at build time.
  - **Consequence:** Gecko or Action Replay codes that patch instructions cannot work here. Only data-write codes carry over.
- **Guest calls are C calls.**
  - A resolved `bl` is a direct C call (`emit.py:294-298`); anything else goes through the generated `dispatch` switch.
  - `blr` is a C `return`, so a native caller gets control back when the guest function returns.
  - An interrupt handler that "rfi"s `longjmp`s out through any C frames between it and the handler's entry (ARCHITECTURE "One interrupt"). A mod post-hook can be skipped on that path.
- **Threads.** There is one guest CPU thread, and guest threads live on host fibers under it. The UI thread, the raster workers and the watchdog are separate host threads, and mods must never touch `CpuState` from them.
- **The renderer must link on its own.** `gx.c`, `gxr.c` and `gxr_tev.c` never call into `main.c`; they expose setters instead (`gx.c:73-78`, HANDOFF). This matters for renderer mods.

### 1.3 The frame loop, from the disassembly [V]

- **`main` (0x801DCB28) loops from 0x801DCB84 to 0x801DCD74.**
  - It starts each iteration with `801DCB84 bl fn_8023F704` (VIGetRetraceCount, `lwz r3,-27836(r13); blr`, which reads 0x80347A64) and stores the result to 0x8034768C.
  - It calls `fn_801DC288` once (0x801DCCB8).
  - It later calls `fn_801DC420`, the frame end.
- **`fn_801DC288`** (the scene dispatcher) runs the handler for the current scene, then increments the frame counter 0x803475C0 (`801DC390-98`). The scene id is at 0x803475CC: 6 is the field (`fn_80101828`), 7 is battle (`fn_8000A118`).
- **`fn_801DC420`** (the frame end), in order:
  1. `801DC484 bl fn_8024F194`: GXCopyDisp. This is where the port's `frame_end` and `SOA_POKE` fire.
  2. A spin from `801DC490` to `801DC4A8`: `bl fn_801C6248` (the async file pump, `akFioReadASync`), then `bl fn_8023F704`, then `subf r0, start, now; cmpli r0,1; blt`. It spins while fewer than one retrace has passed since the loop started.
  3. VISetNextFrameBuffer (`fn_8023F614`) and `fn_8023F4E4`.
  4. `801DC4D8 bl fn_8023E460`: VIWaitForRetrace. It disables interrupts, then `OSSleepThread` until the word at 0x80347A64 changes.
- **Result:** at least 2 fields per logic tick, which is a 30 fps cap with a 20 fps fallback. This matches the ratio of "2.00" retraces per frame that `hle.c` expects, and the 26.7 fps measured in `boot_window.log`.

---

## 2. Design: a mod system in layers

### L0. Keep what exists

Keep hle.txt, hooks.txt, trace.txt, `SOA_POKE` and `SOA_WATCH` for development and diagnosis. They are the proof tools.

### L1. A mod runtime, `runtime/mod.c` (relink only)

**A versioned C API** (`SoaModApi`, plain data only), passed to each mod:

- **Guest memory.** Wrappers over `mem_r*`/`mem_w*` (`u8/u16/u32/f32` and bulk copies), all big-endian.
  - Refuse `is_mmio` addresses, as `poke_at_frame` already does.
  - Refuse writes into the DOL's `.text` ranges with a message, because they are silently inert.
  - Bound accesses to MEM1.
- **State helpers.** Scene 0x803475CC, map 0x80311AC4 / byte 0x80311AC8, field state 0x80311AEC, story flags 0x80310B3C.
- **Callbacks.**
  - `on_frame_end`: runs inside the GXCopyDisp store. **Memory writes only**: no guest calls and no GX.
  - `on_safe_point`: the top of the main loop, on the main thread, between frames. Guest calls are allowed here (L2).
  - `on_map_loaded`, `on_scene_change`: derived at the safe point from the words above.
  - `pad_filter`: a hook in `si.c:684-697 pad_sample`, after live and scripted input are merged.
  - Renderer filters, registered through setters (`gxr_set_texture_provider`, `gxr_set_projection_filter`, and so on) so the renderer still links alone.
- **Frame-hook chaining.** `gx_set_frame_hook` has one slot. Turn it into a dispatcher in `main.c`/`mod.c` that calls `poke_at_frame`, then each mod. `gx.c` does not change.
- **Loading.** Nothing loads unless `SOA_MODS=<dir>` is set, and it is off by default. Each mod is a folder:
  - `mod.ini`: name, API version, and the required DOL SHA-1 `8c0e2781…cc13` (`config/GEAE8P/config.yml`);
  - optionally `mod.dll`, exporting `int soa_mod_init(const SoaModApi*, uint32_t ver)`, loaded with `LoadLibrary`;
  - and/or a **declarative patch list** for mods that need no code, in the form `addr = value`, with `when` (conditions on scene, map or state) and `every_frame | on_map_load | once`.
- **Hotkeys and overlay.**
  - Hotkeys go through `window.c` (keys are polled with `GetAsyncKeyState`, `window.c:191`). The UI thread only posts requests to a queue, which is drained at the safe point.
  - The overlay is drawn in `window.c present()` (`:87-99`), after the RGBA to BGRA conversion. It never goes into `g_screen`, so the frame hashes cannot move.
- **Reproducibility.** Add the active mods and their settings to the header that `pad_config` writes (`si.c:278-284`). Without this, a `SOA_PAD_RECORD` replay of a modded session cannot be reproduced.

### L2. A safe point and tick control: one retranslation, installed once

- **Bind `0x8023F704 VIGetRetraceCount` in `hle.txt`** to a native version that returns the word at 0x80347A64, as the original does.
  - **When `s->lr == 0x801DCB88`** (the call at the top of the loop), first run the `on_safe_point` callbacks.
  - **When `s->lr == 0x801DC49C`** (the call inside the spin) and the tick unlock is on, return `start + 1` (the word at 0x8034768C, plus 1). The spin then exits, and `VIWaitForRetrace` alone paces the loop: one field per tick, 60 ticks a second of guest time.
- **Why this binding rather than a `hooks.txt` entry at 0x801DCB84:**
  - It changes no emitted code in `main`. A hook would strip `irq_poll` from main's back-edges.
  - It needs no emitter change.
  - Its other callers (six SDK sites around 0x802344AC–0x80234B00, and middleware 0x80297150) get the original behaviour.
  - Add it to the self test's twin cases.
- **Calling guest code at the safe point:** `api->call_guest(addr, int args[≤8], float args[≤8])`.
  - Follow the `irq.c:276-291` pattern: `regs_save`, load r3–r10 and f1–f8, `dispatch`, read r3/f1, `regs_restore`.
  - First assert r2 = 0x80350000, r13 = 0x8034E720, and the GQRs unchanged (the game installs six constant GQRs, `cpu.h:441-443`).
  - Refuse the call if an interrupt handler is active (`g_in_handler`).
  - The callee may sleep the thread. That is legal at this point (the main thread is between frames) but must be documented.

### L3. Hook sites by address (pre, post, replace)

- **Recommended (compiled in):**
  - A new list, `config/modsites.txt`. Unlike `hooks.txt`, it does **not** set `_hooked`, so back-edges keep their interrupt polls.
  - For each listed function, `emit.py` emits `body_fn_X` plus a wrapper `fn_X`: `if (g_modsite[i]) mod_call(s, i, body_fn_X); else body_fn_X(s);`.
  - A mod attaches `pre`, `post` or `replace` handlers at run time. A replacement can still call `body` (call-original).
  - Adding a *new site* costs one retranslation. Attaching and detaching do not.
  - Post-hooks are skipped when an interrupt-return `longjmp` unwinds through them. Document this.
- **Optional, only after measuring:** a guard at the entry of every function (a one-byte table load and a not-taken branch) makes all 7,144 functions attachable with no retranslation. Measure it with `tools/profile.py` before adopting it.
  - [I] It is probably cheap. Every translated block already stores `s->pc` (`emit.py:254`), and A4 measured 47.4% of a run in the guest idle loop.
  - But it doubles the function symbols and grows 55.7 MB of C, so do not assume it.
- **Not possible at run time:** changing an instruction in the middle of a function, such as the `cmpli r0,1` in the spin. Because constants are baked into the C, that takes either a hook at that address or a decompiled replacement (L4).

### L4. Native game code: the "guest-C" dialect (Track F, see §4)

- Pointer types are `GPTR(T)`: a u32 guest address in the MSVC build, `T*` under mwcc.
- Loads and stores go through `LD32`/`ST32`/`LDF`/`STF` macros: `mem_r32`/`mem_w32` natively, plain dereferences under mwcc, so matching bytes are unchanged.
- Calls to functions nobody has decompiled go through `dispatch(g_state, addr)`, using the L2 call path.
- Without this, decompiled game functions can be matched but never run natively.

### L5. Safety rules (summary)

| Rule | Why |
|---|---|
| Every guest access goes through big-endian accessors. Mods must never lay a host struct over guest memory. | This is the `strcmp` inversion lesson. |
| Only three things are allowed at frame end: memory writes, no guest calls, no GX. | Frame end runs inside a gather-pipe store; a nested GX write would corrupt the parse. |
| Guest calls happen only at the safe point, with the register file saved and r1 left on the current guest stack. | Keeps the guest ABI intact. |
| No `CpuState` access from the UI, raster or watchdog threads. | Only the guest CPU thread may touch it. |
| All enhancements are off by default. With mods off, these must be unchanged: the 23 frame hashes (`scenario.py replay`), the 73 self-test cases, `title --check`, and `decomp.py`. | That is the regression contract. |
| A new baseline is pinned only after someone opens the frames. | CLAUDE.md's "first bless" rule. |
| Mods must not change the save format. Anything a mod writes into saved regions persists into the card. | The saved regions are party 0x8030B7F4 (5,792 B), flags 0x80310B3C (3,416 B) and 0x80310A1C (288 B), per `save-load.md`. |
| Texture dumps and packs are game-derived data and must stay out of the repository. Add their directory names to `FORBIDDEN_DIRS` in `tools/guard.py`. | Today the guard does not refuse `.png` anywhere. |
| Emulator-style save states are out of scope. The game's card save is the supported path. | Guest control state lives in host C stacks and fibers (PLAN, "Not worth doing"). |

---

## 3. Enhancements: requirements and difficulty

| Enhancement | What is already known | What it needs | Rebuild | Difficulty |
|---|---|---|---|---|
| **Encounter rate: off or ×k** | Per `encounters.md`, from quoted instructions not yet checked by a run: the check is `fn_800C1C24` (1,960 B), called every frame in field state 8 (0x80101A58). The step counter 0x80346D28 is incremented when the player moves (0x800C1FD8). `f31 = (N−30)*rate/14400`, times an accessory factor, `max(f31,0)*0.5`, and a battle happens iff X < f31 with X in [0,100). The rate is read from the loaded table: `800C1FF8 lhz r0,-130(table+zone*132)`; table pointer 0x803474BC. | **Off:** write 0x80346D28 = 0 at every frame end. N is then at most 1 at the compare, f31 clamps to 0, and no battle fires. **×k:** when 0x803474BC changes (a map load), scale the u16 at `table + 2 + z*132` for zones 0–7. This is data only. Map 99 (the world map) uses a separate sub-table (`fn_800C1A50`), which needs its own layout work. | None (L1 patch list) | **Low** |
| **Battle speed-up** | Verified loop pacing (§1.3). Scene 7 is battle. The guest clock is fixed at first read and takes only integers (`hle.c:267-283`). `waveOut` drops a block when no buffer is free (ARCHITECTURE). | **Preferred:** the L2 tick unlock, gated on 0x803475CC == 7. Logic runs 2×, while audio stays on the unscaled guest clock. Rendering must either keep 60 fps or skip every other frame: reuse the skip at `gxr.c:1534`, and also skip the XFB present on skipped frames. **Alternative:** a piecewise guest timebase (the same machinery as D4) with speed ×k. Audio then plays too fast and is dropped. | One retranslation (L2), then a relink | **Low-medium** |
| **Save anywhere** | The one-word request is verified by a run: 0x803473B0 = 0 and 0x803473B4 = 1 open the game's own save menu in any loaded field (FINDINGS §11). The result word is 0x803473C4. The save-point task exists in every map. | Allow it only when scene = 6, state = 8, and no event is running (the script tick freezes while the request is 1, 0x8021214C). **Trap:** a load sets `sys[15] = 20000` (`fn_801F7B04(20000)` in `fn_801A4354`). On maps with no save point, that "loaded from save" branch can be broken: `a116c` asked for camera 9001 and trapped (census 3). Either limit saving to the 54 scripts that contain op 138 (list them with `tools/sct.py`), or after a Continue into such a map, write 0x8030E420 = 0 before its script runs. | None / relink | **Low-medium** (the trap is the work) |
| **Debug menu (warp, part select, flags)** | All verified by runs in HANDOFF/FINDINGS. **Warp:** the name at 0x80305CF0 (three words), 0x8030E420 = 0, then 0x80311AEC = 15. **Part select:** warp to `ME355A.SCT`. **Ending:** 0x80310A68 = 0x4C000000. **Forced battle:** six words. **Fade fix:** 0x80347518 = 0. The picker's map-name table is at 0x802E4780: 158 entries of `{s16, u8, 0, char*}` in Shift-JIS. | The L1 overlay, keyboard focus (stop forwarding to the pad while the menu is open), and actions queued to the safe point. Decode Shift-JIS with `MultiByteToWideChar(932)`. Do not use the old stage-select route (state 2): it skips the teardown. | Relink (after L2) | **Medium** (mostly UI) |
| **Free camera (debug)** | [I] XF position matrices hold model-view, and the renderer applies them at `gxr.c:625` before projection (`gxr.c:635-648`). | Renderer-side: pre-multiply every position matrix of a *perspective* draw by a user delta D, and rotate the normal matrices (XF 0x400) and the light registers the same way. Expected artifacts: billboards face the old camera, and the CPU still culls against the game's own camera. Game logic is untouched. | Relink | **Medium**, acceptable for debugging only |
| **Camera controls (gameplay)** | The input side is ready: the right stick is mapped to the C-stick (`window.c`) and recorded (`si.c`). Unknown: whether the field reads the C-stick or triggers for the camera, and where the camera object and view matrix live. Script op 235 / `fn_800E2924` takes camera object ids (FINDINGS census 3). | **Research spike:** a `SOA_WATCH` on the view-matrix source. The pointer at 0x80347EB4 (−26732(r13)), used by `fn_8029C9B0`, is a candidate [I]. Then a `pad_filter` plus hooks, or targeted decompilation. | Retranslation for hooks | **Medium-high** |
| **Faster text** | Glyphs are rendered from `AFNT` into 24×24 I4 textures in main memory (FINDINGS §9). The code that advances characters is **not located**. | **Research spike:** watch the glyph texture writes to find the message task and its per-frame advance or wait. Then a data poke, or a hook. A cheap stopgap is to run the tick unlock while a message window is open. | Unknown | **Medium** |
| **Texture dump / replace** | The cache already hashes all source bytes plus the palette on every lookup (`gxr_tev.c:208-227`). Its keys are (addr, fmt, w, h, tlut). The sampler scales by `lw[l]/w` (`gxr_tev.c:741`), so a higher-resolution replacement samples correctly with no other change [V]. | **Dump:** write a PNG named from (w, h, fmt, `source_hash`) on first decode; `png.c` already writes PNGs. **Replace:** a hash-to-file index loaded at startup, used in `texture()`/`decode_texture` (`:437-527`); keep replacements in their own cache so an eviction does not reload the file; add log2(scale) to the LOD. **Needed:** a PNG *reader* (WIC, which ships with Windows, avoids vendoring; `vendor/` is both a forbidden and an ignored directory name). **Contract:** `hash_range` becomes a pack format and must be frozen and versioned. EFB-copy textures never match, which is correct. Glyph textures are hashed by content, so individual glyphs can be replaced. | Relink | **Low-medium** |
| **Widescreen 16:9** | Every perspective matrix comes from `C_MTXFrustum` = `fn_80239270` (already matched, `src/sdk/mtx/mtx.c`). It has **5 call sites, all in the middleware**: `fn_802970A0`, `fn_80299188` (37 callers), `fn_80299238` (called once, from init at 0x801DC9FC), `fn_802992F8`, `fn_802993C8` (11 callers). Their inputs live in the block at 0x80345850–0x803458A4, the matrix at 0x80346400, and a flag 0x80347F6C = 2 is set after each build. [I] GXSetProjection = `fn_80251F8C`, which emits the XF command `0x00061020` (5 callers). The renderer reads XF 0x1020–0x1026 at `gxr.c:635-648`. The EFB is 640×528 (`gxr.h:9-10`), and the window is fixed at 640×480×scale (`window.c:104`). | **Stage 1, renderer only, anamorphic:** for perspective draws (XF 0x1026 bit 0 clear), p0 × 3/4, and present the image stretched to 16:9. There is no fragment cost, and EFB copies to texture are unchanged. The work is the HUD: ortho draws that should not stretch need a pillarbox, with full-screen quads exempted. **Stage 2, game side:** a pre-hook on `fn_80239270` that multiplies l and r (f3, f4) by 4/3, only for camera callers (selected by lr). **Unknown:** CPU frustum culling. About 20 functions reference the 0x80345850 block, including `fn_80288C68` and `fn_802AB460`–`fn_802AC160`, which are the candidates [I]. | Stage 1 relink; stage 2 retranslation | **Medium** (stage 1), **high** (clean edges) |
| **Higher internal resolution** | `g_efb`/`g_efb_z` are static 640×528 arrays (`gxr.c:107-108`). The viewport and scissor are in EFB pixels (`gxr.c:780-788, 842-848`). An EFB copy must write exactly the hardware's tile size (FINDINGS §9). The game copies the whole EFB to four 640×480 R8 buffers every frame. The fragment path is the limiter at 26.7 fps windowed (PLAN C4). | A run-time scale factor k: EFB allocated at k×; `to_screen`, scissor and clears ×k; LOD − log2 k; `copy_to_texture` box-downsamples k×k back to the guest size; present at k×. k = 1 must reproduce the 23 hashes. Cost is **k² fragments**. | Relink | **High**; gated on C4, and realistically on a GPU backend |
| **60 fps** | §1.3: one tick per presented frame, at least 2 fields. Fades step per frame (fade speeds 3.0 and 8.0, `save-load.md`). The middleware (807 functions) calls up into game code only 2 times out of 3,996 outbound calls. | **A. Logic at 60 ticks:** the L2 unlock plus halving every per-tick constant. Game-wide, and infeasible without broad decompilation. **B. Renderer interpolation:** build on the FIFO capture machinery. Replay tick N+1's stream with its XF matrices interpolated against the matched matrices of tick N. Costs one frame of latency, shows artifacts wherever draws fail to match, and doubles rasterization. **C. Hybrid:** if the middleware's animation or camera update takes a delta time, run it at 60 while game logic stays at 30. Unknown. **The frame-pacing research must answer:** does the middleware take a time step; which per-tick quantities does game logic keep; and what depends on tick count as opposed to `OSGetTick` (for example the title's 92.267 s timeout, which uses wall clock). | Several | **Very high**, gated on that research and on renderer speed |

---

## 4. How Track F serves mods

- **What mods can do without decompilation.** Data patches, frame and safe-point callbacks, pre/post hooks and renderer features need only addresses. The `docs/research/*.md` method (disassembly marked [V] or [I], then a confirming run) is the right tool for those. The names that result belong in `config/names.txt` with evidence, and could be emitted as the generated bindings header PLAN already proposes (`gen/bindings.h`) for mods to include.
- **When decompilation is required.** Only when a mod changes logic *inside* a function: the spin threshold in `fn_801DC420`, a different encounter formula in `fn_800C1C24`, camera or text logic.
  - Write the function in C, match it byte for byte (`tools/decomp.py`), then apply the mod as a separate, reviewed change on top.
  - That change must not live inside the matched unit, or the unit stops matching.
- **The blocker to fix first.** The native path cannot run game code.
  - The four game units in `src/soa/` (aramcache\*) match but declare host structs with `void*` and function-pointer fields (`aramcache.h`).
  - `mtx.c` is not native either: `C_MTXFrustum` writes host-order floats through an `Mtx44*`.
  - PLAN ("Not worth doing, or not yet") names exactly the two missing mechanisms: byte-order-aware accessors, and a native-to-guest call path.
  - The first mod-relevant F item is therefore the **guest-C dialect (L4)**. Prove it by flipping `aramcache*.c` and `mtx.c` to native while `decomp.py` still matches and the self-test twin comparison still passes.
- **Targeted, not whole libraries.** The functions the enhancements above touch come to about 8 KB, roughly the size of the whole decompilation so far (8,084 B):
  - `fn_800C1C24` 1,960 B, `fn_80101828` 1,596, `fn_800FFB24` 1,484, `main` 664, `fn_80123CBC` 464, `fn_801DC420` 228, `fn_802993C8`/`fn_80299188` 232/176, `fn_80239270` (done);
  - plus the text and camera functions once they are found.
  - Finishing SDK libraries gives mods almost nothing beyond names.
- **What each oracle proves.**
  1. The mwcc match proves the baseline C *is* the shipped code, so the only behaviour change is the mod's own change.
  2. The self-test twin comparison (`selftest.c` `decomp_selftest`, 200 random rounds) proves the native build of the unmodified function matches `recomp_fn_*` in the port. It catches host errors the match cannot see, such as byte order or ABI marshalling.
  3. Scenario checks plus `SOA_WATCH` prove the mod has its intended effect.
- **Caveat.** In game code, the words carrying relocations (every `bl` and every r13 global) are the ones the oracle can decide only by linking. Those are the "35 not counted" bucket. Mod targets will land there until a link-level check exists, so budget for that verification.

---

## 5. Suggested slices, in order

| # | Slice | Rebuild | Done when |
|---|---|---|---|
| M0 | L1 skeleton: `mod.c`, chained frame hook, `SOA_MODS`, patch lists, MMIO and `.text` refusals, mods recorded in `pad_config` | Relink | An "encounters off" patch keeps 0x80346D28 ≤ 1 on `a101b` with no battle for N frames. With mods off: replay hashes, self test, `title --check` unchanged. |
| M1 | L2: native `VIGetRetraceCount` (safe point plus tick unlock), with a self-test twin | One retranslation | Safe-point callbacks == presented frames. With the unlock on, 0x803475C0 advances about 60 per guest second and the audio report is unchanged. |
| M2 | `call_guest` API with register save/restore and r2/r13/GQR asserts | Relink | A self-test case calls a known leaf (for example `fn_8023F704`'s recompiled twin) and the registers come back intact. |
| M3 | Overlay, hotkeys, debug menu (warp list from 0x802E4780, part select, save now, forced battle, fade fix, speed, encounter toggle) | Relink | Each action reproduces its FINDINGS recipe, with the frames opened. |
| M4 | Texture dump/replace (WIC reader, frozen hash, pack directories added to the guard) | Relink | Dump, then an edited PNG replaces a known texture. Pack off gives the 23 hashes. |
| M5 | Widescreen stage 1 (anamorphic plus 16:9 present); research spike on culling and HUD | Relink | Frames at `a101b` and in a battle opened and judged; hashes unchanged with it off. |
| M6 | L3 `modsites.txt` (wrapper emission without `_hooked`); overhead measured with `profile.py` | Retranslation | Pre/post/replace attach and detach at run time on a listed site; overhead reported. |
| M7 | L4 guest-C dialect; `aramcache*.c` and `mtx.c` go native | Relink | Still matches, twins pass, the port runs them. |
| M8 | Targeted decompilation: `fn_801DC420`, then `fn_800C1C24`, then the camera and text targets | Relink | Matched, twin-tested, mod change applied on top. |
| M9 | Research spikes: text advance, camera, middleware time step (60 fps route C), CPU culling | None | Findings written up with [V] and [I] marks. |
| M10 | Internal resolution k | Relink | Only after C4. |
| M11 | 60 fps | — | After M9's answer and a renderer that can hold 60. |

---

## 6. Key files (absolute)

- C:/Users/bmfre/Documents/Github/SOA/config/hle.txt, C:/Users/bmfre/Documents/Github/SOA/config/hooks.txt, C:/Users/bmfre/Documents/Github/SOA/config/trace.txt, C:/Users/bmfre/Documents/Github/SOA/config/GEAE8P/units.txt
- C:/Users/bmfre/Documents/Github/SOA/tools/soa/hle.py, C:/Users/bmfre/Documents/Github/SOA/tools/soa/recomp/emit.py, C:/Users/bmfre/Documents/Github/SOA/tools/recompile.py
- C:/Users/bmfre/Documents/Github/SOA/runtime/cpu.h, C:/Users/bmfre/Documents/Github/SOA/runtime/decomp_swap.c, C:/Users/bmfre/Documents/Github/SOA/runtime/irq.c, C:/Users/bmfre/Documents/Github/SOA/runtime/main.c, C:/Users/bmfre/Documents/Github/SOA/runtime/gx.c, C:/Users/bmfre/Documents/Github/SOA/runtime/gxr.c, C:/Users/bmfre/Documents/Github/SOA/runtime/gxr.h, C:/Users/bmfre/Documents/Github/SOA/runtime/gxr_tev.c, C:/Users/bmfre/Documents/Github/SOA/runtime/trace.c, C:/Users/bmfre/Documents/Github/SOA/runtime/hle.c, C:/Users/bmfre/Documents/Github/SOA/runtime/si.c, C:/Users/bmfre/Documents/Github/SOA/runtime/window.c
- C:/Users/bmfre/Documents/Github/SOA/src/sdk/mtx/mtx.c, C:/Users/bmfre/Documents/Github/SOA/src/soa/aramcache.h
- C:/Users/bmfre/Documents/Github/SOA/docs/research/encounters.md, C:/Users/bmfre/Documents/Github/SOA/docs/research/save-load.md, C:/Users/bmfre/Documents/Github/SOA/docs/research/ship-worldmap.md, C:/Users/bmfre/Documents/Github/SOA/docs/FINDINGS.md
