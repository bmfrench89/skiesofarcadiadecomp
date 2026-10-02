"""Hold the renderer's exp2f and log2f to correct rounding over every input
it can give them, and their outputs to config/libm.tsv.

    python tools/citest/libm_check.py [--cc PROFILE] [--cflag FLAG]... [--out DIR] [--bless]

runtime/crmath.h is CORE-MATH's binary32 exp2f and log2f (portability.md
3.8, L6): fog takes exp2f on [-8, 0] and texture LOD log2f on every positive
finite float. tools/citest/libm_driver.c walks a slice of a domain and
compares each output with the host's double-precision function rounded to
float; where that reference lies within 2^-40 of a rounding boundary the
driver hands the input here, and Python's decimal at 50 digits decides. Each
domain is 64 fixed slices, run in parallel at idle priority, so the result
does not depend on the number of cores. The outputs' FNV-1a hash per
function has to match config/libm.tsv; --bless writes it, and refuses while
any output is wrong.

-DLIBM_HOST (--cflag) checks the host's exp2f and log2f instead, the
mutation: on UCRT it must report 2.5's 74,154 and 313,550 differences.
Exits non-zero if the build fails, the compiler is missing, any output is
not correctly rounded, or a hash differs from the pinned one.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
PINNED = ROOT / "config" / "libm.tsv"
SLICES = 64
# The renderer's domains (2.5): exp2f from -0 to -8, log2f over every
# positive finite float.
DOMAINS = {
    "exp2f": (0x80000000, 0xC1000000, "[-8, 0]"),
    "log2f": (0x00000001, 0x7F7FFFFF, "(0, inf)"),
}
FNV_OFFSET, FNV_PRIME = 0xCBF29CE484222325, 0x100000001B3


def fnv1a(h: int, data: bytes) -> int:
    for b in data:
        h = ((h ^ b) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def f32(bits: int) -> float:
    return struct.unpack("<f", struct.pack("<I", bits))[0]


def bits32(f: float) -> int:
    return struct.unpack("<I", struct.pack("<f", f))[0]


def exact(fn: str, x: float) -> Decimal:
    """2^x or log2(x) to 50 significant digits."""
    with localcontext() as c:
        c.prec = 70
        d, ln2 = Decimal(x), Decimal(2).ln()
        v = (d * ln2).exp() if fn == "exp2f" else d.ln() / ln2
        c.prec = 50
        return +v


def round_f32(v: Decimal) -> int:
    """The float nearest v, ties to even, as bits: decided against v exactly,
    not through a double, which could round twice."""
    near = bits32(float(v))
    best = None
    with localcontext() as c:
        c.prec = 400
        for cand in (near - 1, near, near + 1):
            if cand < 0 or cand > 0xFFFFFFFF or (cand & 0x7F800000) == 0x7F800000:
                continue
            dist = abs(Decimal(f32(cand)) - v)
            key = (dist, cand & 1)
            if best is None or key < best[0]:
                best = (key, cand)
    return best[1]


def slices(first: int, last: int) -> list[tuple[int, int]]:
    n = last - first + 1
    edges = [first + n * i // SLICES for i in range(SLICES + 1)]
    return [(edges[i], edges[i + 1] - 1) for i in range(SLICES)]


def run_slice(exe: Path, fn: str, lo: int, hi: int) -> dict:
    kw: dict = {"capture_output": True, "text": True, "check": False}
    if os.name == "nt":
        kw["creationflags"] = subprocess.IDLE_PRIORITY_CLASS
    else:
        kw["preexec_fn"] = lambda: os.nice(19)
    p = subprocess.run([str(exe), fn, f"{lo:08X}", f"{hi:08X}"], **kw)
    if p.returncode != 0:
        raise RuntimeError(f"{fn} {lo:08X}-{hi:08X} exited {p.returncode}: {p.stderr}")
    out = {"arb": [], "wrong": [], "summary": None}
    for line in p.stdout.splitlines():
        w = line.split()
        if w[0] == "arb":
            out["arb"].append((int(w[1], 16), int(w[2], 16)))
        elif w[0] == "wrong":
            out["wrong"].append(tuple(int(v, 16) for v in w[1:4]))
        elif w[0] == "slice":
            out["summary"] = {
                "inputs": int(w[4]),
                "wrong": int(w[5]),
                "arb": int(w[6]),
                "hash": int(w[7], 16),
            }
    if out["summary"] is None:
        raise RuntimeError(f"{fn} {lo:08X}-{hi:08X} printed no summary")
    return out


def read_pinned() -> dict[str, tuple[int, str]]:
    if not PINNED.exists():
        return {}
    pinned = {}
    for line in PINNED.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("function\t"):
            continue
        fn, _first, _last, inputs, h = line.split("\t")
        pinned[fn] = (int(inputs), h)
    return pinned


def write_pinned(results: dict[str, dict]) -> None:
    lines = [
        "# soa_exp2f and soa_log2f (runtime/crmath.h, CORE-MATH) over the renderer's",
        "# domains: FNV-1a 64 over each output's four bytes, low byte first, per 1/64",
        "# slice, then over the 64 slice hashes. tools/citest/libm_check.py checks it,",
        "# and --bless rewrites it only when every output is correctly rounded.",
        "function\tfirst\tlast\tinputs\thash",
    ]
    for fn, r in results.items():
        first, last, _ = DOMAINS[fn]
        lines.append(f"{fn}\t{first:08X}\t{last:08X}\t{r['inputs']}\t{r['hash']:016x}")
    PINNED.write_bytes(("\n".join(lines) + "\n").encode())


def build(prof, cflags: list[str], out: Path) -> Path | None:
    out.mkdir(parents=True, exist_ok=True)
    src = HERE / "libm_driver.c"
    exe = out / f"libm_driver{prof.exeext}"
    obj = out / f"libm_driver{prof.objext}"
    steps = [
        [*prof.cflags, *cflags, "/c", f"/I{RUNTIME}", f"/Fo{obj}", str(src)],
        [*prof.cflags, *cflags, str(obj), f"/Fe:{exe}", *prof.linker],
    ]
    for what, args in zip(("compiling", "linking"), steps, strict=True):
        p = toolchain.cc(args, ROOT, prof)
        text = ((p.stdout or "") + (p.stderr or "")).strip()
        if text:
            print(text)
        if p.returncode:
            print(f"::error::{what} the driver failed", file=sys.stderr)
            return None
    return exe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc", choices=tuple(toolchain.PROFILES), default="msvc")
    ap.add_argument("--cflag", action="append", default=[], help="added to the compile and link")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--bless", action="store_true", help="write config/libm.tsv")
    args = ap.parse_args()
    prof = toolchain.profile(args.cc)
    if args.out is None:
        name = "libm" if prof.name == "msvc" else f"libm-{prof.name}"
        args.out = ROOT / "build" / "citest" / name
    args.out = args.out.resolve()
    cc = toolchain.compiler_path(prof)
    if cc is None:
        print(f"{prof.name} not found (see tools/soa/toolchain.py compiler_path)", file=sys.stderr)
        print("this check must not pass silently, so it fails instead", file=sys.stderr)
        return 1
    print(f"compiler: {cc}")
    exe = build(prof, args.cflag, args.out)
    if exe is None:
        return 1

    t0 = time.monotonic()
    jobs = [
        (fn, lo, hi) for fn, (first, last, _) in DOMAINS.items() for lo, hi in slices(first, last)
    ]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 1) as pool:
        outs = list(pool.map(lambda j: run_slice(exe, *j), jobs))
    print(f"[libm] {len(jobs)} slices in {time.monotonic() - t0:.1f} s")

    pinned = read_pinned()
    results: dict[str, dict] = {}
    failed = False
    for fn, (_first, _last, domain) in DOMAINS.items():
        mine = [o for j, o in zip(jobs, outs, strict=True) if j[0] == fn]
        inputs = sum(o["summary"]["inputs"] for o in mine)
        wrong = sum(o["summary"]["wrong"] for o in mine)
        h = FNV_OFFSET
        for o in mine:
            h = fnv1a(h, o["summary"]["hash"].to_bytes(8, "little"))
        arb = [a for o in mine for a in o["arb"]]
        arb_wrong = [(x, r) for x, r in arb if round_f32(exact(fn, f32(x))) != r]
        examples = [w for o in mine for w in o["wrong"]][:5]
        total_wrong = wrong + len(arb_wrong)
        results[fn] = {"inputs": inputs, "hash": h, "wrong": total_wrong}
        pin = pinned.get(fn)
        verdict = (
            "not pinned" if pin is None else ("ok" if pin == (inputs, f"{h:016x}") else "DIFFERS")
        )
        print(
            f"[libm] {fn} over {domain}: {inputs} inputs; {len(arb)} near a rounding boundary, "
            f"decided by decimal at 50 digits, {len(arb) - len(arb_wrong)} of them right; "
            f"{total_wrong} not correctly rounded; hash {h:016x} (pinned "
            f"{pin[1] if pin else 'nothing'}): {verdict}"
        )
        for x, r, ref in examples:
            print(f"    {fn}({f32(x)!r}) = {f32(r)!r}, the reference rounds to {f32(ref)!r}")
        for x, r in arb_wrong[:5]:
            print(
                f"    {fn}({f32(x)!r}) = {f32(r)!r}, decimal says {f32(round_f32(exact(fn, f32(x))))!r}"
            )
        failed |= total_wrong > 0 or (not args.bless and verdict != "ok")

    if args.bless:
        if any(r["wrong"] for r in results.values()):
            print("::error::not blessing: some outputs are not correctly rounded")
            return 1
        write_pinned(results)
        print(f"[libm] wrote {PINNED.relative_to(ROOT)}")
        return 0
    if failed:
        print("::error::the libm check failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
