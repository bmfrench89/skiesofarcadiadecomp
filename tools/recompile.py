#!/usr/bin/env python3
"""Translate the whole DOL to C.

    python tools/recompile.py [--dol extracted/sys/main.dol] [--out gen] [--chunk 400]
                              [--compile] [--limit N]

Writes gen/functions.h, gen/dispatch.c and gen/chunk_NNN.c (gitignored: they
are derived from the game binary and are reproduced locally from the user's
own dump). Prints instruction coverage so what is *not* translated is always
visible. --compile runs MSVC over every chunk to prove the C is valid.
"""

import argparse
import collections
import concurrent.futures
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from soa import dol as D  # noqa: E402
from soa import symbols as S  # noqa: E402
from soa import toolchain  # noqa: E402
from soa.hle import load_hle  # noqa: E402
from soa.ppc import cfg  # noqa: E402
from soa.recomp import Emitter  # noqa: E402

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dol", type=Path, default=Path("extracted/sys/main.dol"))
    ap.add_argument("--config", type=Path, default=Path("config"))
    ap.add_argument("--out", type=Path, default=Path("gen"))
    ap.add_argument("--chunk", type=int, default=400, help="functions per C file")
    ap.add_argument("--limit", type=int, default=0, help="translate only the first N functions")
    ap.add_argument("--compile", action="store_true", help="compile every chunk with MSVC")
    ap.add_argument("--optimize", action="store_true", help="compile at /O2 instead of /Od")
    ap.add_argument(
        "--link", action="store_true", help="link the objects with runtime/ into soa.exe"
    )
    args = ap.parse_args()

    dol = D.parse(args.dol.read_bytes())
    t0 = time.time()
    functions, _ = cfg.build_iterative(dol)
    code = cfg.CodeView(dol)
    tables = cfg.find_jump_tables(dol, code)
    print(f"{len(functions):,} functions, {len(tables)} switch tables ({time.time() - t0:.1f}s)")

    names = {}
    tsv = args.config / "functions.tsv"
    if tsv.exists():
        names = {a: r["name"] for a, r in S.load_tsv(tsv).items()}

    hle = load_hle(args.config / "hle.txt")
    hooks = load_hle(args.config / "hooks.txt")
    savepoints = load_hle(args.config / "savepoints.txt")
    traces = load_hle(args.config / "trace.txt")
    if hle or hooks or savepoints:
        print(
            f"{len(hle)} functions bound to HLE, {len(hooks)} runtime hooks, "
            f"{len(savepoints)} savepoints"
        )
    em = Emitter(dol, functions, tables, code, names, hle, hooks, savepoints, traces)
    entries = sorted(functions)
    if args.limit:
        entries = entries[: args.limit]

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "functions.h").write_text(em.prototypes(), encoding="utf-8")
    (args.out / "dispatch.c").write_text(em.dispatch_c(), encoding="utf-8")

    t0 = time.time()
    chunks: list[Path] = []
    for n in range(0, len(entries), args.chunk):
        body = ['#include "functions.h"', ""]
        for entry in entries[n : n + args.chunk]:
            body.append(em.function_c(functions[entry]))
            body.append("")
        path = args.out / f"chunk_{n // args.chunk:03d}.c"
        path.write_text("\n".join(body), encoding="utf-8")
        chunks.append(path)
    st = em.stats
    total_bytes = sum(p.stat().st_size for p in chunks)
    print(
        f"emitted {len(entries):,} functions into {len(chunks)} files, "
        f"{total_bytes / 1024**2:.1f} MB of C ({time.time() - t0:.1f}s)"
    )

    print(
        f"\ninstruction coverage: {st.coverage_pct:.3f}%  "
        f"({sum(st.translated.values()):,} translated, {sum(st.unsupported.values()):,} not)"
    )
    if st.oe_ignored:
        print(f"  OE forms translated without overflow tracking: {st.oe_ignored}")
    if st.unsupported:
        print("  unsupported, by mnemonic:")
        for mn, c in st.unsupported.most_common():
            print(f"    {mn:16} {c:>7,}")

    if args.compile:
        env = toolchain.msvc_env()
        if env is None:
            print("\nMSVC not found; skipping compile", file=sys.stderr)
            return 1
        units = [args.out / "dispatch.c", *chunks]
        # Validation compiles at /Od: the point is to prove the C is
        # well-formed, and /O2 over 50 MB of it takes many minutes.
        flags = [("/O2" if args.optimize else "/Od") if f == "/O2" else f for f in toolchain.CFLAGS]
        print(f"\ncompiling {len(units)} translation units with MSVC ({flags[1]}) ...")
        t0 = time.time()

        def build(path: Path):
            return path, toolchain.cl(
                [
                    *flags,
                    "/c",
                    f"/I{RUNTIME}",
                    f"/I{args.out}",
                    path.name,
                    f"/Fo{path.with_suffix('.obj').name}",
                ],
                cwd=args.out,
            )

        failures = collections.Counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            for path, proc in pool.map(build, units):
                if proc.returncode != 0:
                    failures[path.name] += 1
                    errs = [ln for ln in proc.stdout.splitlines() if "error" in ln.lower()]
                    print(f"  FAIL {path.name}: {errs[0] if errs else proc.stdout[-300:]}")
        elapsed = time.time() - t0
        print(f"compiled {len(units) - len(failures)}/{len(units)} units in {elapsed:.1f}s")
        if failures:
            return 1

    if args.link:
        if toolchain.msvc_env() is None:
            print("\nMSVC not found; skipping link", file=sys.stderr)
            return 1
        objs = sorted(args.out.glob("chunk_*.obj")) + [args.out / "dispatch.obj"]
        exe = args.out / "soa.exe"
        t0 = time.time()
        proc = toolchain.cl(
            [
                *toolchain.CFLAGS,
                f"/I{RUNTIME}",
                f"/I{args.out}",
                f"/Fo{args.out}/",
                f"/Fe:{exe}",
                *map(str, sorted(RUNTIME.glob("*.c"))),
                *map(str, objs),
                "/link",
                "/STACK:33554432",  # guest call depth becomes host call depth
            ],
            cwd=".",
        )
        if proc.returncode != 0:
            print(proc.stdout[-2000:], file=sys.stderr)
            return 1
        print(f"linked {exe} ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
