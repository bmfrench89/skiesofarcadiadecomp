"""The GPU spike: the renderer drawing through a Vulkan backend, headless.

    python tools/gpuspike.py build                        # shaders, then the binary
    python tools/gpuspike.py selftest [--mutate NAME]     # draw 15 scenes on both, compare
    python tools/gpuspike.py tevdiff [--cases 100000]     # the TEV, exact against tev_pixel
    python tools/gpuspike.py copydiff [--rects 200]       # the copies, exact against gxr.c's

specs/gpu-backend.md V3a and V3b. `build` compiles the shaders in
tools/gpuspike/ to SPIR-V with the pinned glslang (tools/fetch_gpu.py), as C
arrays -- each mutation a variant of its own -- and builds gx.c, gxr.c,
gxr_tev.c and png.c with the spike's driver and gxv.c (the backend) into
build/gpuspike/<compiler>/gpuspike.exe, when an input is newer than it. No
gen/, no disc: the binary links the renderer alone, as
tools/citest/render_check.py does.

`selftest` (V3a) runs the binary twice, `--backend cpu` and `--backend gpu`,
into build/gpuspike/<compiler>/cpu and gpu, and judges the scenes they wrote:

- the self test's two render recipes must pass on the GPU as they are
  written for the CPU (the driver checks them in-process);
- cull0..cull3: four triangle shapes in both windings, a strip, a fan and two
  quads under each cull mode. Away from edges the GPU covers exactly what the
  CPU covers and in the same colour; mode 3 covers nothing, mode 0 something;
- clip_*: triangles crossing the near and far planes, orthographic and in
  perspective. Away from edges the coverage matches and colours are within one
  step (the CPU steps attributes along a span, the GPU interpolates them, 3.4);
  and in the driver the vertices the consumer uploaded must be clip_polygon's;
- depth, depth_persp, scissor, quad_gradient and clear: an EQUAL redraw and
  LESS against the clear, two planes crossing in perspective, per-draw
  scissors, a quad's split, and a copy's clear;
- lines: every pixel either side drew is within one pixel of one the other
  drew (the CPU steps a line in ceil(length) floor()ed samples; Vulkan
  rasterizes by diamond exit, so endpoints and half-pixel steps may differ);
- points: exactly the CPU's pixels.

An edge pixel is one whose 3x3 neighbourhood in the CPU's image is not one
colour (for the gradients, not all covered or all uncovered): Vulkan's
top-left fill rule and the CPU's inclusive one disagree there by design.

`tevdiff` (V3b) runs tev.glsl, the TEV transcribed, against tev_pixel over
setups tev_prepare built from random registers: zero mismatches, and every
path it counts taken at least 100 times. `copydiff` (V3b) runs the same random
copies through the CPU renderer and through gxv's compute copy, in two
processes at once, and compares what each left in RAM, the decoded image and a
screen copy: byte for byte, with every refused copy leaving RAM as it was.

--mutate names a mutation the command must fail on: unclipped (selftest),
clamp (tevdiff), rounding, intensity and unseeded (copydiff). Exit 0 pass,
1 fail, 3 skipped (no compiler, no vendor/, no Vulkan device), the reason
printed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from itertools import compress, count, groupby
from operator import ne
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_gpu  # noqa: E402
from soa import png, toolchain  # noqa: E402

SPIKE = ROOT / "tools" / "gpuspike"
RUNTIME = ROOT / "runtime"
OUT = ROOT / "build" / "gpuspike"
VENDOR = ROOT / "vendor"
# Each shader and the variants built from it: (source, header and array name,
# defines). A variant is a mutation gxv_set_mutation selects; the self test
# runs each and must fail.
SHADERS = [
    ("raster.vert", "raster_vert", ()),
    ("raster.frag", "raster_frag", ()),
    ("tevdiff.comp", "tevdiff_comp", ()),
    ("tevdiff.comp", "tevdiff_comp_clamp", ("GXV_MUTATE_CLAMP",)),
    ("copy.comp", "copy_comp", ()),
    ("copy.comp", "copy_comp_rounding", ("GXV_MUTATE_ROUNDING",)),
    ("copy.comp", "copy_comp_intensity", ("GXV_MUTATE_INTENSITY",)),
]
SOURCES = [RUNTIME / n for n in ("gx.c", "gxr.c", "gxr_tev.c", "png.c")]
SOURCES += [SPIKE / "driver.c", SPIKE / "gxv.c"]
SKIP = 3

# Scene name -> how it is judged: ("area", colour tolerance, edges by), ("lines",)
# or ("points",). Edges are where the CPU's image changes colour, for the
# flat-coloured scenes, or coverage, for the ones with gradients (every pixel
# of a gradient differs from its neighbours).
SCENES: dict[str, tuple] = {
    "cull0": ("area", 0, "colour"),
    "cull1": ("area", 0, "colour"),
    "cull2": ("area", 0, "colour"),
    "cull3": ("area", 0, "colour"),
    "clip_near_ortho": ("area", 1, "coverage"),
    "clip_far_ortho": ("area", 1, "coverage"),
    "clip_near_persp": ("area", 1, "coverage"),
    "clip_far_persp": ("area", 1, "coverage"),
    "depth": ("area", 0, "colour"),
    "depth_persp": ("area", 0, "colour"),
    "scissor": ("area", 0, "colour"),
    "quad_gradient": ("area", 1, "coverage"),
    "clear": ("area", 0, "colour"),
    "lines": ("lines",),
    "points": ("points",),
}


def build_dir(prof: toolchain.Profile) -> Path:
    """Each compiler's objects and binary apart: msvc and clang-cl both write
    .obj and .exe, and one must never be taken for the other's."""
    return OUT / prof.name


def exe_path(prof: toolchain.Profile) -> Path:
    return build_dir(prof) / f"gpuspike{prof.exeext}"


def glslang() -> Path:
    name = "glslang.exe" if sys.platform == "win32" else "glslang"
    return VENDOR / "glslang" / "bin" / name


def inputs() -> list[Path]:
    """Everything the binary is made from: its sources and shaders, every
    header either directory holds (any of them may be included), the record
    of the fetched files, and the scripts that hold the flags."""
    return [
        *SOURCES,
        *(SPIKE / n for n in {src for src, _, _ in SHADERS}),
        SPIKE / "tev.glsl",
        *RUNTIME.glob("*.h"),
        *SPIKE.glob("*.h"),
        VENDOR / fetch_gpu.RECORD,
        Path(__file__),
        ROOT / "tools" / "soa" / "toolchain.py",
    ]


def up_to_date(prof: toolchain.Profile) -> bool:
    exe = exe_path(prof)
    return exe.exists() and exe.stat().st_mtime > max(p.stat().st_mtime for p in inputs())


def build(prof: toolchain.Profile) -> tuple[bool, str]:
    """(built, why not). A missing compiler or vendor/ is a reason, not a
    crash. Nothing is rebuilt when the binary is newer than every input, and
    then no compiler is looked for: finding MSVC's environment takes 2 s."""
    bad = fetch_gpu.verify(VENDOR)
    if bad:
        return False, f"vendor/ is not as recorded ({bad[0]}); run python tools/fetch_gpu.py"
    if up_to_date(prof):
        return True, ""
    if toolchain.compiler_path(prof) is None:
        return False, f"no {prof.name} compiler (tools/soa/toolchain.py compiler_path)"
    out = build_dir(prof)
    out.mkdir(parents=True, exist_ok=True)
    exe_path(prof).unlink(missing_ok=True)
    for src, var, defines in SHADERS:
        proc = subprocess.run(
            [
                str(glslang()),
                "-V",
                "--target-env",
                "vulkan1.1",
                f"-I{SPIKE}",
                *(f"-D{d}" for d in defines),
                "--vn",
                var,
                str(SPIKE / src),
                "-o",
                str(out / f"{var}.h"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            return False, f"glslang failed on {src} ({var})"
    inc = [
        f"/I{RUNTIME}",
        f"/I{SPIKE}",
        f"/I{out}",
        f"/I{VENDOR / 'vulkan-headers' / 'include'}",
    ]
    proc = toolchain.cc([*prof.cflags, "/c", *inc, f"/Fo{out}/", *map(str, SOURCES)], ROOT, prof)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        print(text)
        return False, "compiling the spike failed"
    for line in text.splitlines():
        if "warning" in line:
            print(line)
    # Named rather than globbed, so a stale object cannot slip into the link.
    objs = [str(out / (s.stem + prof.objext)) for s in SOURCES]
    libs = ["-ldl"] if prof.style == "gnu" else []
    proc = toolchain.cc(
        [*prof.cflags, *objs, f"/Fe:{exe_path(prof)}", *prof.linker, *libs], ROOT, prof
    )
    if proc.returncode != 0:
        print((proc.stdout or "") + (proc.stderr or ""))
        return False, "linking the spike failed"
    return True, ""


def run(prof: toolchain.Profile, backend: str, mutate: str | None) -> subprocess.CompletedProcess:
    out = build_dir(prof) / backend
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    args = [str(exe_path(prof)), "--backend", backend, "--out", str(out)]
    if mutate:
        args += ["--mutate", mutate]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)


# ---- the comparison ----------------------------------------------------------

# A pixel as one int, its alpha masked off; and where its three colour bytes
# are within it. Pixels are read as native words, so both depend on the order.
RGB = 0xFFFFFF if sys.byteorder == "little" else 0xFFFFFF00
SHIFTS = (0, 8, 16) if sys.byteorder == "little" else (8, 16, 24)


def pixel_rows(w: int, h: int, rgba: bytes) -> list[list[int]]:
    """Each row as a list of pixels, RGB only, as ints."""
    px = memoryview(rgba).cast("I").tolist()
    return [list(map(RGB.__and__, px[y * w : (y + 1) * w])) for y in range(h)]


def row_bits(values) -> dict:
    """One row's values -> {value: bit x set where pixel x has it}, a run of
    equal values at a time rather than a pixel."""
    out: dict = {}
    x = 0
    for v, run in groupby(values):
        n = len(list(run))
        out[v] = out.get(v, 0) | (((1 << n) - 1) << x)
        x += n
    return out


def regions(rows: list[list[int]]) -> dict[int, list[int]]:
    """Each colour in the image -> one int per row, bit x set where pixel x of
    that row is that colour."""
    out: dict[int, list[int]] = {}
    for y, row in enumerate(rows):
        for v, bits in row_bits(row).items():
            out.setdefault(v, [0] * len(rows))[y] = bits
    return out


def coverage(rows: list[list[int]]) -> list[int]:
    """One int per row, bit x set where the pixel is not black (the clear)."""
    return [row_bits(map(bool, row)).get(True, 0) for row in rows]


def neighbourhood(rows: list[int], w: int) -> tuple[list[int], list[int]]:
    """(all, any) over each pixel's 3x3 neighbourhood, the image's edges
    standing in for what lies beyond them."""
    full = (1 << w) - 1
    hi = 1 << (w - 1)

    def h_all(r: int) -> int:
        return r & (((r << 1) | (r & 1)) & full) & ((r >> 1) | (r & hi))

    def h_any(r: int) -> int:
        return (r | (r << 1) | (r >> 1)) & full

    a = [h_all(r) for r in rows]
    o = [h_any(r) for r in rows]
    n = len(rows)
    all3 = [a[max(y - 1, 0)] & a[y] & a[min(y + 1, n - 1)] for y in range(n)]
    any3 = [o[max(y - 1, 0)] | o[y] | o[min(y + 1, n - 1)] for y in range(n)]
    return all3, any3


def dilate(rows: list[int], w: int) -> list[int]:
    return neighbourhood(rows, w)[1]


def popcount(rows: list[int]) -> int:
    return sum(bin(r).count("1") for r in rows)


def colour_off(cr: list[list[int]], gr: list[list[int]], where: list[int]) -> tuple[int, int]:
    """(pixels whose colour differs, the largest step in any channel), over
    the pixels set in where."""
    off = worst = 0
    for y, bits in enumerate(where):
        if not bits or cr[y] == gr[y]:
            continue
        for x in compress(count(), map(ne, cr[y], gr[y], strict=True)):
            if (bits >> x) & 1:
                a, b = cr[y][x], gr[y][x]
                off += 1
                worst = max(worst, *(abs(((a >> k) & 255) - ((b >> k) & 255)) for k in SHIFTS))
    return off, worst


def judge(name: str, how: tuple, cpu: Path, gpu: Path) -> tuple[bool, str]:
    cw, ch, c = png.read_rgba(cpu)
    gw, gh, g = png.read_rgba(gpu)
    if (cw, ch) != (gw, gh):
        return False, f"sizes differ: cpu {cw}x{ch}, gpu {gw}x{gh}"
    w, h = cw, ch
    cr, gr = pixel_rows(w, h, c), pixel_rows(w, h, g)
    cc, gc = coverage(cr), coverage(gr)
    ncpu, ngpu = popcount(cc), popcount(gc)
    full = (1 << w) - 1
    if how[0] == "points":
        diff = popcount([a ^ b for a, b in zip(cc, gc, strict=True)])
        colours = colour_off(cr, gr, cc)[0]
        ok = diff == 0 and colours == 0 and ncpu > 0
        return (
            ok,
            f"cpu {ncpu} px, gpu {ngpu} px, {diff} placed differently, {colours} coloured differently",
        )
    if how[0] == "lines":
        dc, dg = dilate(cc, w), dilate(gc, w)
        cpu_only = popcount([a & ~b for a, b in zip(cc, gc, strict=True)])
        gpu_only = popcount([b & ~a for a, b in zip(cc, gc, strict=True)])
        far_c = popcount([a & ~b & full for a, b in zip(cc, dg, strict=True)])
        far_g = popcount([b & ~a & full for a, b in zip(dc, gc, strict=True)])
        ok = far_c == 0 and far_g == 0 and ncpu > 0
        return ok, (
            f"cpu {ncpu} px, gpu {ngpu} px; {cpu_only} cpu-only and {gpu_only} gpu-only, "
            f"of which {far_c} and {far_g} are more than one pixel from the other's"
        )
    tol, edges_by = how[1], how[2]
    all3, any3 = neighbourhood(cc, w)
    edge = [o & ~a & full for a, o in zip(all3, any3, strict=True)]
    if edges_by == "colour":
        for rows in regions(cr).values():
            ra, ro = neighbourhood(rows, w)
            edge = [e | (o & ~a & full) for e, a, o in zip(edge, ra, ro, strict=True)]
        all3 = [a & ~e for a, e in zip(all3, edge, strict=True)]
    wrong = popcount([(a ^ b) & ~e & full for a, b, e in zip(cc, gc, edge, strict=True)])
    at_edges = popcount([(a ^ b) & e for a, b, e in zip(cc, gc, edge, strict=True)])
    interior = popcount(all3)
    off, worst = colour_off(cr, gr, all3)
    ok = wrong == 0 and worst <= tol
    if name == "cull3":
        ok = ok and ncpu == 0 and ngpu == 0
    elif ncpu == 0:
        ok = False
    return ok, (
        f"cpu {ncpu} px, gpu {ngpu} px; {interior} interior, {wrong} covered differently away from edges, "
        f"{at_edges} at edges; colour off at {off} interior px, by at most {worst} (allowed {tol})"
    )


def ready(prof: toolchain.Profile) -> int | None:
    """None when the binary is built; otherwise the exit code, the reason printed."""
    built, why = build(prof)
    if built:
        return None
    skip = "compiler" in why or "vendor" in why
    print(f"skip: {why}" if skip else f"FAIL: {why}")
    return SKIP if skip else 1


def skipped(proc: subprocess.CompletedProcess) -> bool:
    """The driver's own skip (no Vulkan device), said aloud."""
    m = re.search(r"^skip: (.*)$", proc.stdout, re.M)
    if proc.returncode == SKIP and m:
        print(f"skip: {m.group(1)}")
        return True
    return False


def selftest(prof: toolchain.Profile, mutate: str | None) -> int:
    code = ready(prof)
    if code is not None:
        return code
    gpu = run(prof, "gpu", mutate)
    if skipped(gpu):
        return SKIP
    cpu = run(prof, "cpu", None)
    failures = 0
    for label, proc in (("cpu", cpu), ("gpu", gpu)):
        dev = re.search(r"^device (.*)$", proc.stdout, re.M)
        print(f"[{label}] exit {proc.returncode}" + (f", device {dev.group(1)}" if dev else ""))
        for line in proc.stderr.splitlines():
            if (
                line.startswith(("[selftest]", "[gpuspike]", "[gxv]"))
                or "refused" in line
                or "failed" in line
            ):
                print(f"  {line}")
        for line in proc.stdout.splitlines():
            if line.startswith(("recipes", "clip ")):
                print(f"  {line}")
        if proc.returncode != 0:
            failures += 1
    for name, how in SCENES.items():
        c, g = build_dir(prof) / "cpu" / f"{name}.png", build_dir(prof) / "gpu" / f"{name}.png"
        if not c.exists() or not g.exists():
            print(f"FAIL {name}: no image from {'cpu' if not c.exists() else 'gpu'}")
            failures += 1
            continue
        ok, detail = judge(name, how, c, g)
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")
        failures += not ok
    print(f"[gpuspike] {'every check passes' if not failures else f'{failures} check(s) failed'}")
    return 1 if failures else 0


# ---- V3b: the exact differentials ----------------------------------------------


def tevdiff(prof: toolchain.Profile, cases: int, seed: int, mutate: str | None) -> int:
    code = ready(prof)
    if code is not None:
        return code
    args = [str(exe_path(prof)), "--backend", "gpu", "--tevdiff", str(cases), "--seed", str(seed)]
    if mutate:
        args += ["--mutate", mutate]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if skipped(proc):
        return SKIP
    for line in proc.stdout.splitlines():
        if line.startswith("hits "):
            words = line.split()[1:]
            print("hits, a path a count, every one at least 100:")
            for i in range(0, len(words), 8):
                print("  " + "  ".join(words[i : i + 8]))
        elif not line.startswith("device "):
            print(line)
    for line in proc.stderr.splitlines():
        if line.startswith("[gxv]") or "failed" in line:
            print(line)
    m = re.search(r"^tevdiff \d+ cases, seed \d+: (\d+) mismatch", proc.stdout, re.M)
    ok = proc.returncode == 0 and m is not None and m.group(1) == "0"
    print(f"[gpuspike] tevdiff {'passes' if ok else 'FAILS'}")
    return 0 if ok else 1


# A copydiff line: the case, then four hashes. Rows match when every field
# does; a refused copy (texfmt 99) must leave its RAM hash equal to the seed's.
COPY_FIELDS = [
    "combo",
    "rect",
    "tpf",
    "intensity",
    "half",
    "filtered",
    "x0",
    "y0",
    "w",
    "h",
    "stride",
    "dest",
    "texfmt",
    "extent",
    "seeded",
    "ram",
    "image",
    "screen",
]
HASHED = {"ram": 15, "image": 16, "screen": 17}


def compare_copies(cpu: list[str], gpu: list[str]) -> tuple[list[str], Counter]:
    """(problems, mismatches by (what, tpf, intensity, half, filtered))."""
    problems: list[str] = []
    mismatches: Counter = Counter()
    if len(cpu) != len(gpu) or not cpu:
        problems.append(f"the CPU wrote {len(cpu)} copies and the GPU {len(gpu)}")
    for a, b in zip(cpu, gpu, strict=False):
        fa, fb = a.split(), b.split()
        if len(fa) != len(COPY_FIELDS) or fa[:15] != fb[:15]:
            problems.append(f"the two runs made different copies: {a!r} against {b!r}")
            continue
        for side, f in (("cpu", fa), ("gpu", fb)):
            if f[12] == "99" and f[15] != f[14]:
                problems.append(f"{side} wrote RAM for a refused copy: {' '.join(f[:14])}")
        for what, k in HASHED.items():
            if fa[k] != fb[k]:
                mismatches[(what, int(fa[2]), int(fa[3]), int(fa[4]), int(fa[5]))] += 1
    return problems, mismatches


def copydiff(prof: toolchain.Profile, rects: int, seed: int, mutate: str | None) -> int:
    code = ready(prof)
    if code is not None:
        return code
    base = build_dir(prof) / "copydiff"
    procs = {}
    for backend in ("cpu", "gpu"):
        out = base / backend
        out.mkdir(parents=True, exist_ok=True)
        (out / "copydiff.txt").unlink(missing_ok=True)
        args = [
            str(exe_path(prof)),
            "--backend",
            backend,
            "--copydiff",
            str(rects),
            "--seed",
            str(seed),
        ]
        args += ["--out", str(out)]
        if mutate and backend == "gpu":
            args += ["--mutate", mutate]
        # The two sides are independent processes with their own output, so
        # they run at once: each takes about 18 s at 200 rectangles.
        procs[backend] = subprocess.Popen(
            args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    done = {}
    for backend, proc in procs.items():
        out, err = proc.communicate()
        done[backend] = subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
    if skipped(done["gpu"]):
        return SKIP
    for backend, proc in done.items():
        for line in (proc.stdout + proc.stderr).splitlines():
            if line.startswith(("[gxv]", "copydiff")) or "failed" in line or "refused" in line:
                print(f"[{backend}] {line}")
        if proc.returncode != 0:
            print(f"FAIL: the {backend} side exited {proc.returncode}")
            return 1
    cpu = (base / "cpu" / "copydiff.txt").read_text(encoding="utf-8").splitlines()
    gpu = (base / "gpu" / "copydiff.txt").read_text(encoding="utf-8").splitlines()
    problems, mismatches = compare_copies(cpu, gpu)
    refused = sum(1 for line in cpu if line.split()[12] == "99")
    print(
        f"{len(cpu)} copies, {refused} of them refused; each also copied to the screen. "
        f"Differences: "
        + ", ".join(
            f"{what} {sum(n for k, n in mismatches.items() if k[0] == what)}" for what in HASHED
        )
    )
    for line in problems[:5]:
        print(f"FAIL {line}")
    for (what, tpf, intensity, half, filtered), n in sorted(mismatches.items())[:12]:
        print(
            f"FAIL {what}: format {tpf}, intensity {intensity}, half {half}, filter {filtered}: "
            f"{n} of {rects}"
        )
    ok = not problems and not mismatches
    print(f"[gpuspike] copydiff {'passes' if ok else 'FAILS'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("build", "selftest", "tevdiff", "copydiff"))
    ap.add_argument("--cc", choices=tuple(toolchain.PROFILES), default="msvc")
    ap.add_argument("--mutate", default=None, help="a gxv mutation the command must fail on")
    ap.add_argument("--cases", type=int, default=100000, help="tevdiff: random setups")
    ap.add_argument("--rects", type=int, default=200, help="copydiff: rectangles a combination")
    ap.add_argument("--seed", type=int, default=1, help="tevdiff and copydiff")
    args = ap.parse_args(argv)
    prof = toolchain.profile(args.cc)
    if args.command == "build":
        built, why = build(prof)
        print(f"built {exe_path(prof)}" if built else f"not built: {why}")
        return 0 if built else 1
    if args.command == "tevdiff":
        return tevdiff(prof, args.cases, args.seed, args.mutate)
    if args.command == "copydiff":
        return copydiff(prof, args.rects, args.seed, args.mutate)
    return selftest(prof, args.mutate)


if __name__ == "__main__":
    raise SystemExit(main())
