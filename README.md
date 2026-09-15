# Skies of Arcadia Legends — Native PC Port

A native PC port of **Skies of Arcadia Legends** (GameCube, `GEAE8P`) built by
static recompilation, with progressive decompilation layered on top.

> **No game data lives in this repository, ever.** You supply your own dump of a
> disc you own. This repo contains only original tooling, runtime code, and
> analysis metadata.

## Why this game

Disc analysis (see [docs/FINDINGS.md](docs/FINDINGS.md)) turned up an unusually
favorable target:

| Signal | Value | Why it matters |
|---|---|---|
| REL modules | **none** | All code is in one DOL. Static recompilation sees the whole program. |
| Gekko-only instructions | **0.76%** | Dreamcast-lineage code barely touches paired singles or locked cache. |
| Function count | **~5.4k–8k** | Smaller than *any* GameCube game yet fully decompiled. |
| Symbol map | absent | The one real gap — mitigated by SDK signature lifting (see spec). |

## Documents

- **[docs/SPEC.md](docs/SPEC.md)** — architecture and technical decisions
- **[docs/ROADMAP.md](docs/ROADMAP.md)** — work slices, milestones, current status
- **[docs/FINDINGS.md](docs/FINDINGS.md)** — disc analysis evidence base

## Status

Phase 0. See the roadmap.
