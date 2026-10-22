# H20: a power line in every run report

Written 2026-10-21, from [PLAN-GAMEPLAY-MODS.md](../PLAN-GAMEPLAY-MODS.md) ("H20. A power line in every run
report") and PLAN-NEXT's M1 gap fillers, which ask for its Done first.

**Status: done 2026-10-21** but for Done line 3's battery run, the owner's; evidence in FINDINGS "H20".

**Why.** Every measured run is meant to carry a note of the power mode it ran in, and none does unless a person
writes it: a frame rate on battery in a quiet mode and one on AC in Turbo are different machines. The GPU decision
also wants energy per drawn frame on the handheld (specs/gpu-backend.md, "nothing records energy until H20").

## What

At the start of a run and at its report, the port reads the power state; the report gets one line:

```
[power] AC, battery 79%, plan Turbo, mode best performance
[power] battery 64% -> 58%, plan Balanced, mode best power efficiency; 4210 mWh over 36000 frames, 116 mWh a 1000
[power] AC at the start, battery at the report: no energy figure for a run that changed source
[power] AC, no battery, plan High performance, mode -
[power] not known on this system
```

- **Where it is read:** `plat_power_read` in `runtime/plat.c`, so no Win32 call lands outside the platform layer.
  Windows: `GetSystemPowerStatus` (AC, percentage), and from `powrprof.dll` loaded at run time
  `CallNtPowerInformation(SystemBatteryState)` (remaining mWh), `PowerGetActiveScheme` and
  `PowerReadFriendlyName` (the plan's name), `PowerGetEffectiveOverlayScheme` (Windows' power mode: best power
  efficiency, balanced, best performance). Loading at run time keeps every link line as it is; a part that cannot
  be read is `-`. Linux: `/sys/class/power_supply/*` (`online` of a `Mains` supply; `capacity` and `energy_now` of
  a `Battery`, µWh). Elsewhere, and on Android until it is asked for: not known.
- **The line** is written by `power_line` in `runtime/power.c`, a pure function of the two readings and the frames
  drawn between them, so a test can feed it any pair.
- **Energy** is given only when both readings are on battery and both have a remaining capacity: the difference,
  and per 1000 frames drawn. A run that changed source says so instead of a number.

## Done

1. **The line, from any pair of readings:** `tools/tests/test_power.py` builds `power.c` with a driver and checks
   each case above, and a battery that rose (charging on battery is impossible, so the figure is withheld).
   *Mutation:* the energy taken end minus start fails the battery case.
2. **Every report has it:** a short run's log holds one `[power]` line (the self test returns before any report),
   and `test_power.py` holds main.c to registering it. *Mutation:* the hook not registered.
3. **On this PC:** the line names the plan `powercfg /getactivescheme` names and the mode set in Windows' settings,
   on AC. A battery run is the owner's, unplugged at the next sitting, and its mWh is then compared with the
   battery's own report (`powercfg /batteryreport`).
4. **It builds everywhere:** `compile_runtime.py` with MSVC and llvm-mingw here; gcc, clang and the Android route in
   CI.
