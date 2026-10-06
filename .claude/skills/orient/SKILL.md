---
name: orient
description: Get grounded before choosing or starting work on this port. Covers the owner's goal and target devices, where the order of work is decided, how to read the current state (git, CI, other sessions), what to verify before trusting a document, and when to ask the owner. Use at the start of a session, after a reboot or handoff, and before starting any slice.
---

# Before you pick anything up

Sessions have picked up work in the wrong order without noticing. On
2026-09-30 HANDOFF named L2 as next while PLAN-NEXT advised against it, and
the session that wrote it had not checked. This page is the ten minutes that
prevents that.

## 1. The goal, and where the order lives

The owner's goal (2026-09-30): **"I want to be able to play it on any Windows
or Android device."**

| In scope | Out of scope |
|---|---|
| Intel and AMD x86-64 PCs and handhelds; the dev machine is the owner's **ROG Ally X** (Z1 Extreme, 1920x1080 120 Hz), docked to a 3440x1440 85 Hz ultrawide | Windows on ARM |
| The Steam Deck, through Proton | Mid-range phones (Snapdragon 7-series, Dimensity 7000) |
| Android flagships and handhelds, Snapdragon 8 Gen 2 or newer | 2-core or pre-2015 PCs |

Vulkan, SDL3 and a build-time shader compiler are allowed; nothing is
committed that a build can fetch.

**The order is `docs/PLAN-NEXT.md` §0, which overrides everything below it in
that file.** The other plans keep the details of each slice. When two
documents disagree about what is next, §0 wins, and the disagreement is a bug
to fix in the same commit.

## 2. Read the state, not a description of it

```
git fetch -q; git status -sb; git log --oneline -8
gh run list --workflow ci.yml --limit 3
```

- **Other sessions:** call ListAgents. An implementation session and a
  planning session have shared this one checkout and this one branch. Commit
  by path (`git commit -- <paths>`), never `--amend`, and never switch
  branches here; build a branch in a scratch `git worktree` instead.
- **One `soa.exe` at a time** (CLAUDE.md): two share `build/frames/` and the
  card.
- **Then read**, in this order: HANDOFF.md's "Where the last session
  stopped"; PLAN-NEXT §0; the row for your slice in PLAN-NEXT's tables; the
  slice's own section in its spec.

## 3. Before you build a slice

- **Re-read its spec against HEAD.** Specs are written ahead of the code they
  describe, and their file:line references drift. Check each one you rely
  on.
- **Verify every claim you act on in the code itself.** This includes claims
  from a subagent's report and from FINDINGS. Measure a performance number
  again before you quote it: the machine drifts about 15% a day, so compare
  only interleaved A/B runs.
- **Read its Done.** Each Done line names a command. Plan the mutation that
  proves each new check can fail before you write the check.

## 4. The platform lens: ask it of every change

Windows runs, and since L10 Linux (no owner session there yet); Android runs on the x86-64 emulator
since L12c, on no phone yet. Don't make that harder:

- **Does it compile under clang?** Run check step 5d. Android's compiler is
  clang, and code that only MSVC accepts counts as a regression.
- **Is it a new Win32 call outside the platform layer?** 15 runtime files
  already call Windows directly (16 before L7 moved `irq.c` off it). New platform needs go through
  `runtime/plat.h` (portability.md 3.2).
- **Does it assume x86-64?**
  - SIMD goes behind `PLAT_X86_64` with a scalar path.
  - Memory ordering: x86 is forgiving and ARM is not. Shared state between
    threads uses the atomics L2 defines, never `volatile`.
  - Page size: Android may use 16 KB pages, so never hard-code 4096.
  - `long` is 64-bit on Linux and Android. L4b exists because the native
    string routines get this wrong.
- **Does it make the frame cost more on four slow cores?** The Steam Deck and
  phones are the targets now, not only the Ally X.

## 5. When to ask the owner

Ask, using the questions tool, with options and the consequence of each, before:

- changing the order, or the scope of a target;
- adding a dependency;
- the first bless of any baseline (CLAUDE.md);
- deleting anything of theirs;
- anything that needs them at the machine, such as an owner session or a look.

Act without asking on anything that follows from a recorded answer. Answers
go into PLAN-NEXT §0 or its decision register (D-1 to D-33) in the same
session, and into SPEC.md if they change the goal.

## 6. Before you stop

- Update HANDOFF's "Where the last session stopped", including the state, what
  is next and why.
- Mark the slice done in PLAN-NEXT's table and in its spec.
- Add a FINDINGS entry, with each claim's evidence.
- Measure every count you change, and fix every copy of it
  (`grep -rn "<old number>" --include="*.md" .`).
- Read CI after each push.
