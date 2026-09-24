#!/usr/bin/env python3
"""The renderer's benchmark: nanoseconds per fragment over a fixed capture set.

    python tools/perfbench.py run                  # every capture, 5 replays each, 8 threads
    python tools/perfbench.py run --runs 9 --threads 4
    python tools/perfbench.py manifest --write     # pin the set (after opening every PNG)

The set lives in `build/perfset/<scene>/<frame>.{fifo,regs,ram}` -- captured with
`SOA_FIFO_DIR` pointed there, never at `build/fifo`, and game data, so it stays
on the machine that captured it. `config/perfset_manifest.tsv` pins each file's
SHA-256 and the scene it shows; `run` refuses a capture that no longer matches,
because a benchmark whose inputs drift measures the drift (PLAN-60FPS-MODS H6:
H13-H16 report against this set and no other).

Each replay runs on a copy in a scratch directory, since `--replay` writes
`<base>.png` beside its input. Worker busy time (thread-seconds) divided by the
fragments the renderer processed (shaded + failed alpha + failed depth) is the
figure the pixel-path work is judged by; 60 images a second of a 2.4 M-fragment
scene needs about 55 ns with eight workers (FINDINGS "H1"). The busy time is
printed to 10 ms, so a single replay of a light frame is coarse: take the median
of several.
"""

import argparse
import hashlib
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "build" / "perfset"
MANIFEST = ROOT / "config" / "perfset_manifest.tsv"
EXE = ROOT / "gen" / "soa.exe"
PARTS = (".fifo", ".regs", ".ram")

BUSY = re.compile(r"\[gxr\] workers: (\d+) threads, .*?busy ([\d.]+)s")
FRAGS = re.compile(
    r"\[gxr\] \d+ triangles.*?; (\d+) pixels shaded \((\d+) outside, (\d+) failed alpha, (\d+) failed depth\)"
)


def parse_replay(text: str) -> tuple[int, float, int]:
    """(threads, worker busy seconds, fragments) from one replay's output."""
    b, f = BUSY.search(text), FRAGS.search(text)
    if not b or not f:
        raise ValueError("replay output has no [gxr] workers/triangles lines")
    shaded, alpha, depth = int(f[1]), int(f[3]), int(f[4])
    return int(b[1]), float(b[2]), shaded + alpha + depth


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def captures(root: Path = SET) -> list[str]:
    """`scene/frame` for every complete capture under the set."""
    out = []
    for fifo in sorted(root.glob("*/*.fifo")):
        base = fifo.with_suffix("")
        if all(base.with_suffix(p).exists() for p in PARTS):
            out.append(f"{fifo.parent.name}/{base.name}")
    return out


def read_manifest(path: Path = MANIFEST) -> dict[str, tuple[str, dict[str, str]]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, label, *hashes = line.split("\t")
        rows[name] = (label, dict(zip(PARTS, hashes, strict=True)))
    return rows


def verify(name: str, pinned: dict[str, str], root: Path = SET) -> list[str]:
    """What differs between a capture on disk and its manifest row."""
    base = root / name
    return [
        p
        for p in PARTS
        if not base.with_suffix(p).exists() or sha(base.with_suffix(p)) != pinned[p]
    ]


def write_manifest(labels: dict[str, str], root: Path = SET, path: Path = MANIFEST) -> int:
    lines = ["# scene/frame\tlabel\tsha256 .fifo\tsha256 .regs\tsha256 .ram"]
    names = captures(root)
    for name in names:
        base = root / name
        lines.append(
            "\t".join([name, labels.get(name, ""), *(sha(base.with_suffix(p)) for p in PARTS)])
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(names)


def run(runs: int, threads: int, exe: Path = EXE, root: Path = SET) -> int:
    rows = read_manifest()
    bad = {n: verify(n, h, root) for n, (_, h) in rows.items()}
    bad = {n: d for n, d in bad.items() if d}
    if bad:
        for n, d in bad.items():
            print(
                f"perfbench: {n}: {', '.join(d)} missing or changed since the manifest",
                file=sys.stderr,
            )
        return 1
    print(f"{'capture':<16} {'label':<28} {'Mfrag':>6} {'ns/frag med':>11} {'min':>6} {'max':>6}")
    total_busy, total_frags = 0.0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, (label, _) in rows.items():
            src = root / name
            dst = Path(tmp) / name.replace("/", "_")
            for p in PARTS:
                shutil.copyfile(src.with_suffix(p), dst.with_suffix(p))
            per = []
            frags = 0
            for _ in range(runs):
                proc = subprocess.run(
                    [str(exe), "--replay", str(dst)],
                    capture_output=True,
                    text=True,
                    cwd=ROOT,
                    env={**os.environ, "SOA_THREADS": str(threads)},
                    timeout=300,
                    check=False,
                )
                _, busy, frags = parse_replay(proc.stdout + proc.stderr)
                per.append(busy / frags * 1e9)
                total_busy += busy
                total_frags += frags
            print(
                f"{name:<16} {label:<28} {frags / 1e6:6.2f} {statistics.median(per):11.1f} {min(per):6.1f} {max(per):6.1f}"
            )
    print(
        f"{'all':<16} {'':<28} {'':>6} {total_busy / total_frags * 1e9:11.1f}  (busy / fragments over every replay)"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="replay every pinned capture and report ns per fragment")
    r.add_argument("--runs", type=int, default=5)
    r.add_argument("--threads", type=int, default=8)
    m = sub.add_parser("manifest", help="list the set, or pin it with --write")
    m.add_argument(
        "--write",
        action="store_true",
        help="rewrite config/perfset_manifest.tsv from build/perfset",
    )
    m.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="NAME=TEXT",
        help="scene label for a capture",
    )
    a = p.parse_args()
    if a.cmd == "run":
        return run(a.runs, a.threads)
    labels = dict(x.split("=", 1) for x in a.label)
    if a.write:
        print(
            f"perfbench: pinned {write_manifest(labels)} captures in {MANIFEST.relative_to(ROOT)}"
        )
    else:
        for n in captures():
            print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
