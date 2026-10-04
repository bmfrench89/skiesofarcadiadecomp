<!-- Written 2026-10-03 from one read-only web research report, after the owner answered gate G3
("who will get builds?") with "What's the easiest for users. Do more research on this is needed and go
with the best path forward for all users." The SNK notice and Android's verification FAQ were re-read by
the session that recorded the decision. Nothing in the repository was built and the game was not run.
[V] = checked at the cited page on 2026-10-03; [I] = inference. The decision itself is PLAN-NEXT §0. -->

# Distribution: how players get the port

*Read-only research, 2026-10-03, HEAD `aff3aa6`. **[V]** means checked at a dated page. **[I]** means
inferred. It extends [android-and-native.md](android-and-native.md) §4's table of 2026-09-25.*

## 1. The short answer

**Players download a prebuilt runtime that builds the game on their own machine from their own disc**
(route B below). They download it, run it, pick their disc image and wait a few minutes once. That is
one wait more than the projects this port is compared with, and in exchange no translated or decompiled
game code is ever handed out. **Android gets a runtime-only APK** that loads the game library built the
same way on a PC (route C2); building on the phone itself (C1) is later, and only if it matters.

The easiest route, a prebuilt binary that already holds the translated game (route D), is what most
similar projects ship. It is refused here, because one of them was taken down this September for doing
exactly that (section 3).

## 2. What similar projects ship [V, each project's GitHub releases and README]

| Project (latest release) | Ships | Game code inside? | How the player supplies the game |
|---|---|---|---|
| Zelda64Recomp 1.2.2, 2025-08-27 | Windows, Linux x64/ARM64, macOS zips; a Flatpak bundle | Yes, recompiled | Picks the ROM in the main menu |
| Zelda64Recomp-Android 0.6.10, 2026-07-29 | APK, 36.7 MB | Yes | Supplies the ROM when asked |
| UnleashedRecomp 1.0.3, 2025-04-03 (a Sega game) | Windows zip; Flatpak zip | Yes, recompiled | An installer: ISO or folder, then updates and DLC, with integrity checks |
| UnleashedRecomp-Android 0.6.0, 2026-09-30 | APK, 62.7 MB | Yes | An installer using Android's file picker |
| Dusklight 2.0.3, 2026-09-30 | APK, IPA, AppImage, Windows x64/ARM64, macOS | Yes, decompiled | Picks the disc image (ISO or RVZ) on first launch |
| re:Blue 1.2.1, 2026-09-19 | Windows zip; AppImage x64/aarch64 | Yes, recompiled | A wizard checks each of the 3 discs, then installs itself |
| Ship of Harkinian 9.2.3, 2Ship 5.0.1 | Windows, Linux, macOS | Yes, decompiled | Builds an asset archive from the ROM on first launch |

- **The usual player path is four to six steps:** download, extract or install, run, pick the disc,
  play.
- **Building on the player's machine has precedents, but none ships its own compiler:** the Arch Linux
  `banjorecomp` package recompiles with the player's ROM beside the build script; the Mario 64 GUI
  builders need MSYS2 installed first; the OpenGOAL launcher takes the player's ISO and compiles on
  their machine. No static recompilation was found that bundles a C compiler [negative search].

## 3. Takedowns: what has happened, not legal advice

- **SNK, 2026-09-11: the first notice found against a static recompilation's release** [V, re-read].
  GitHub's DMCA record names three release archives of `FluffyQuack/rexglue-MetalSlugXX` as "emulated
  versions of the Xbox 360 version of the video game 'Metal Slug XX'" that were "modified and
  distributed without authorization", citing the author's own description of the code as "a static
  recompilation". The repository is still up, with no releases or tags
  ([notice](https://github.com/github/dmca/blob/master/2026/09/2026-09-11-snk.md)).
- **Nintendo, 2020:** notices against hosted Super Mario 64 PC port executables; the source
  repositories were not targeted. **2026-08-17:** 401 Switch emulator repositories, on
  anti-circumvention grounds; no decompilation or recompilation was named.
- **Sega:** GitHub's record holds one Sega notice, from 2019, for leaked mobile-game source. Nothing
  was found against UnleashedRecomp (recompiled Sega code since 2025) or the Sonic RSDK
  decompilations, whose releases ship compiled code, Android included. Sega did pull Streets of Rage
  Remake in 2011. **Not finding an action is not permission.**
- **The pattern [I]:** takedowns hit distributed binaries and assets far more than source, and SNK
  shows a recompilation *release* is a real target.

## 4. Android in 2026 [V, re-read: developer.android.com/developer-verification]

- **Developer verification** is enforced from 2026-09-30 for installs from participating stores in
  Brazil, Indonesia, Singapore and Thailand, and globally in 2027.
- **What stays open:** "Apps installed using ADB won't require verification." And an "advanced flow"
  for anyone: developer mode, a check that nobody is coaching you, a restart, **a one-time 24-hour
  wait**, then fingerprint or PIN, after which unverified apps install for 7 days or indefinitely.
- **Full registration** costs $25 and a government ID, and registers the package name and signing
  key: it would tie the owner's legal identity to the APK [I]. A free "limited distribution" tier
  reaches only 20 devices.
- **Channels:** GitHub releases, which Obtainium can track. F-Droid builds everything itself from
  free-software sources, so it cannot carry an APK that needs the player's game library [I].
- **Getting the game on:** ports use the system file picker.

## 5. The Steam Deck, and Windows warnings

- **Deck:** the precedents ship native Linux builds, as Flatpak zips or AppImages, none on Flathub. A
  Windows exe runs as a non-Steam game with Proton forced in its Compatibility settings. Set-up is
  advised in Desktop Mode, where the file picker works.
- **Windows SmartScreen** warns on an unsigned download ("Windows protected your PC", then "Run
  anyway"); signed files still warn until reputation builds. **Smart App Control**, where it is on,
  blocks unsigned files outright.
- **Signing for an individual:** Microsoft Artifact Signing is $9.99 a month and open to individuals in
  the US or Canada only. **SignPath Foundation** signs open-source projects free, if the binary is
  built automatically from the repository's own OSI-licensed source with no proprietary part. A
  runtime built without `src/` could qualify; a binary holding the translated game never could [I].

## 6. Building on the player's machine

- **A compiler to ship:** llvm-mingw (190.7 MB Windows zip, ISC and Apache-2.0 licences, no Windows SDK
  or MSVC needed) or Zig (100.3 MB) [V, their download pages]. clang-cl alone still needs Microsoft's
  headers (PLAN-GAMEPLAY-MODS G4).
- **Time:** the full build is 103 s wall on 16 Zen 4 threads with MSVC `/O2`, about 1,100-1,650
  CPU-seconds (port-android.md). On the Steam Deck's 4 cores that is roughly **5-15 minutes** [I]; clang's
  speed on this code is unmeasured.
- **The Python recompiler** would have to be frozen or embedded [I].
- **On a phone:** Termux's clang is about 69 MB to download and 430 MiB installed. Apps cannot run
  programs from their own storage, but can `dlopen` a library, which is what route C needs.

## 7. The routes

| Route | What the player does | What is handed out | Legal exposure | Work |
|---|---|---|---|---|
| A. Build from source (today) | 10 or more steps: Python, Git, the VS Build Tools (gigabytes), clone, extract, build; Android adds the NDK and adb | Source only | Lowest | Done for Windows; PLAN-GAMEPLAY-MODS G3's setup script, week-plus |
| **B. Prebuilt runtime that builds the game on first run** | 5: download, extract, run, pick the disc, wait minutes once | The runtime, the recompiler, a bundled clang (~250 MB) [I]; no game code | Low: the download holds only this repository's MIT sources and third-party toolchains [I] | Weeks [I]: the clang build, a frozen recompiler, the disc check, reproducible output |
| **C. Runtime-only APK + a player-built library** | C2: route B on a PC, copy one file to the phone, pick it. C1: install, pick the ISO, wait 10-30 minutes | An APK with no game code | Low [I] | C2: week-plus beyond B and L12. C1: months (a compiler on the phone, the recompiler off Python) |
| D. Prebuilt full binaries (the precedents) | 4-5 | Translated Sega code in every exe and APK | Highest: SNK 2026 | Least; but CI has no disc, so releases would be built on the owner's machine and could not be signed free |

## 8. What it changes

*Specified as R1-R5 in [specs/distribution.md](../specs/distribution.md), 2026-10-04.*

- **SPEC §2 rule 2 stands as written:** the translated code is still made on the player's machine from
  their own dump. SPEC §2 gains a rule that a release holds only what this repository's original
  sources and third-party toolchains build, and that `gen/` and `src/` (decompiled game code, which the
  MIT licence cannot cover) are compiled on the player's machine.
- **A release is built and tested with no game data present** [I].
- **The prebuilt runtime holds no DOL.** After disc-layer I3 a locally built `soa.exe` holds the
  player's executable verbatim, which is why it is never shared, and why route B builds it there.
- **For the owner, before the first public release:** whether to register the Android APK under their
  ID ($25) or have players use the 24-hour advanced flow; and whether to sign the runtime through
  SignPath.

**Could not verify:** whether MSVC may be redistributed; clang's compile time on this code; what Deck
players prefer; whether anything beyond the release archives was removed in the Metal Slug case.
