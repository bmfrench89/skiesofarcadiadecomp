"""The GPU spike: the renderer drawing through a Vulkan backend, headless.

    python tools/gpuspike.py build                        # shaders, then the binary
    python tools/gpuspike.py selftest [--mutate NAME]     # draw 17 scenes on both, compare
    python tools/gpuspike.py tevdiff [--cases 100000]     # the TEV, exact against tev_pixel
    python tools/gpuspike.py copydiff [--rects 200]       # the copies, exact against gxr.c's
    python tools/gpuspike.py loddiff [--cases 100000]     # the level of detail, against gxr's
    python tools/gpuspike.py oracle [--mutations]         # the captures, CPU against GPU, V0's verdict
    python tools/gpuspike.py time                         # GPU and consumer ms a frame
    python tools/gpuspike.py logicop [--mutate M]         # logic ops native, blend and snapshot
    python tools/gpuspike.py ramdiff                      # each copy's RAM, CPU against GPU
    python tools/gpuspike.py chain battle_4421 ...        # copies carried into the next frames

specs/gpu-backend.md V3a, V3b, V4a, V4b and V5's loddiff. `build` compiles the shaders in
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
`loddiff` (V5) runs lod.glsl, the fragment stage's level of detail, against
the sampler's own level choice (tex_level) bit for bit, and against span_lod's
formula within 1/1024, the derivatives given to both, since V0 does not
reliably see a level's blur (FINDINGS "V4").

`oracle` (V4a, V4b) replays every capture of --set (corpus,perfset; add
gpuset for V1's): on the CPU, a reference that must hash to the manifest
(corpus) or equal V0's inspected image, and on the GPU, which V0 judges. A
frame that copies to a texture is replayed from a scratch copy with 0xA5 over
every row of tiles it copies into (3.12's poison). A failure must be listed
in BY_DESIGN, bisected. --mutations then runs the GPU mutations, each of which must fail
V0 wherever it changes 0.5% of a frame, on five captures or more, but for the
exceptions GPU_BLIND_SPOTS and SHORT_OF_FIVE list. `time` gives the GPU's and
the consumer's milliseconds a frame, beside perfbench's CPU figures.

`logicop` (V4b) draws the mask effect's 14 captures with native logic ops,
the blend approximation and the EFB snapshot, which must give byte-identical
frames; `ramdiff` holds every copy's bytes, CPU against GPU, and traces each
difference to the EFB the copy read; `chain` carries each frame's copies into
the next frame's RAM, as V1's battle start needs.

--mutate names a mutation the command must fail on: unclipped (selftest),
clamp (tevdiff), rounding, intensity and unseeded (copydiff), lod and
lodmin (loddiff), and-copy,
or-copy and or-and (logicop), dest+32 (ramdiff). Exit 0 pass,
1 fail, 3 skipped (no compiler, no vendor/, no Vulkan device), the reason
printed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from itertools import compress, count, groupby
from operator import ne
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fetch_gpu  # noqa: E402
import fifo  # noqa: E402
import imgdiff  # noqa: E402
import scenario  # noqa: E402
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
    ("raster.vert", "raster_vert_noinvariant", ("GXV_MUTATE_NOINVARIANT",)),
    ("raster.frag", "raster_frag", ()),
    ("raster.frag", "raster_frag_alpha", ("GXV_MUTATE_ALPHA",)),
    ("raster.frag", "raster_frag_lod", ("GXV_MUTATE_LOD",)),
    ("raster.frag", "raster_frag_fog", ("GXV_MUTATE_FOG",)),
    ("tevdiff.comp", "tevdiff_comp", ()),
    ("tevdiff.comp", "tevdiff_comp_clamp", ("GXV_MUTATE_CLAMP",)),
    ("loddiff.comp", "loddiff_comp", ()),
    ("loddiff.comp", "loddiff_comp_lod", ("GXV_MUTATE_LOD",)),
    ("loddiff.comp", "loddiff_comp_lodmin", ("GXV_MUTATE_LODMIN",)),
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
    "invariance": ("area", 0, "colour"),
    "logic": ("area", 0, "colour"),
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


def run(
    prof: toolchain.Profile, backend: str, mutate: str | None, logicop: str | None = None
) -> subprocess.CompletedProcess:
    out = build_dir(prof) / backend
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    args = [str(exe_path(prof)), "--backend", backend, "--out", str(out)]
    if mutate:
        args += ["--mutate", mutate]
    if logicop and backend == "gpu":
        args += ["--logicop", logicop]
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


def selftest(prof: toolchain.Profile, mutate: str | None, logicop: str | None = None) -> int:
    code = ready(prof)
    if code is not None:
        return code
    gpu = run(prof, "gpu", mutate, logicop)
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
            if line.startswith(("recipes", "clip ", "invariance ")):
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


def loddiff(prof: toolchain.Profile, cases: int, seed: int, mutate: str | None) -> int:
    code = ready(prof)
    if code is not None:
        return code
    args = [str(exe_path(prof)), "--backend", "gpu", "--loddiff", str(cases), "--seed", str(seed)]
    if mutate:
        args += ["--mutate", mutate]
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if skipped(proc):
        return SKIP
    for line in proc.stdout.splitlines():
        if line.startswith("lodhits "):
            print("hits, a path a count, every one at least 100:")
            print("  " + "  ".join(line.split()[1:]))
        elif not line.startswith("device "):
            print(line)
    for line in proc.stderr.splitlines():
        if line.startswith("[gxv]") or "failed" in line:
            print(line)
    level = re.search(
        r"^loddiff level \d+ cases, seed \d+: (\d+) mismatch\w*; (\d+) path", proc.stdout, re.M
    )
    formula = re.search(r"^loddiff formula (\d+) cases, seed \d+: (\d+) over", proc.stdout, re.M)
    ok = (
        proc.returncode == 0
        and level is not None
        and level.group(1) == "0"
        and level.group(2) == "0"
        and formula is not None
        and int(formula.group(1)) > 0
        and formula.group(2) == "0"
    )
    print(f"[gpuspike] loddiff {'passes' if ok else 'FAILS'}")
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


# ---- V4a: captures -------------------------------------------------------------


def clean_env() -> dict[str, str]:
    """The parent's environment with every SOA_* taken out, and SOA_SETTINGS=0:
    nothing set for another run may reach a replay (3.12's rule, and imgdiff's
    for its references)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env["SOA_SETTINGS"] = "0"
    return env


@dataclass
class Cap:
    setname: str
    capture: imgdiff.Capture
    copies: list  # TexCopy: what the frame copies to a texture


def captures(sets: list[str]) -> list[Cap]:
    """Every capture of those sets, with the copies to a texture its stream
    makes (V4a's 21 have none)."""
    return [Cap(name, c, texture_copies(c.base)) for name in sets for c in imgdiff.SETS[name]()]


def replay_base(cap: Cap, scratch: Path) -> Path:
    """What to replay: the capture itself, or -- when its frame copies to a
    texture -- a scratch copy with every destination poisoned (3.12)."""
    if not cap.copies:
        return cap.capture.base
    return scratch_capture(cap.capture.base, scratch / cap.capture.name, cap.copies)


def replay(
    prof: toolchain.Profile,
    backend: str,
    base: Path,
    png_out: Path,
    mutate: str | None = None,
    logicop: str | None = None,
    dump_ram: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess, str | None]:
    """One capture through the spike: the run, and the frame's hash."""
    args = [str(exe_path(prof)), "--backend", backend, "--replay", str(base), "--png", str(png_out)]
    if mutate:
        args += ["--mutate", mutate]
    if logicop and backend == "gpu":
        args += ["--logicop", logicop]
    if dump_ram:
        args += ["--dump-ram", str(dump_ram)]
    proc = subprocess.run(
        args,
        cwd=ROOT,
        env={**clean_env(), **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    m = re.search(r"^frame \d+x\d+ hash ([0-9a-f]{16})$", proc.stdout, re.M)
    return proc, m.group(1) if m else None


def same_pixels(a: Path, b: Path) -> bool:
    return png.read_rgba(a) == png.read_rgba(b)


def changed_fraction(a: Path, b: Path) -> float:
    """The fraction of pixels whose RGB differs at all."""
    w, h, x = png.read_rgba(a)
    _, _, y = png.read_rgba(b)
    rows_x, rows_y = pixel_rows(w, h, x), pixel_rows(w, h, y)
    differ = sum(sum(map(ne, rx, ry, strict=True)) for rx, ry in zip(rows_x, rows_y, strict=True))
    return differ / (w * h)


# V4a's mutations of the GPU path (specs/gpu-backend.md V4a): each must change
# at least 0.5% of the pixels of at least five captures ("applies", 3.12), and
# fail V0 on every capture where it applies.
GPU_MUTATIONS = {
    "skip-largest": "the most visible of the frame's five largest draws (by samples) skipped",
    "fog": "fog off",
    "nofilter": "the copy filter off in the screen copy",
    "alpha": "the alpha test off",
    "lod": "level-of-detail bias +1",
    "logic-copy": "logic ops ignored, drawn as copies (V4b)",
    "skip-copies": "copies to a texture skipped (V4b)",
    "dest+32": "copies to a texture written 32 bytes on (V4b)",
}
APPLIES = 0.005

# Where a mutation applies and V0 still passes, each found on 2026-10-03 and
# looked at (FINDINGS "V4"), as imgdiff lists V0's own. A blind spot that is
# not listed fails the run, and so do more than three for one mutation.
GPU_BLIND_SPOTS: dict[str, dict[str, str]] = {
    "lod": {
        "sky_4000": "one level blurrier on the player's ship and the cloud band only: 12% of pixels move, "
        "most by one or two steps, 137 far; V0's whole-frame blur and MAE are diluted by the empty sky",
        "sky_4001": "the frame after sky_4000, the same",
        "15200": "the ship's hold: one level blurrier fades the floor's rivets almost away; 12% of pixels "
        "move, 1,012 far, and V0's vertical blur measure reads 0.089 against its 0.10",
        "15800": "the hold, later: the same, 0.089 again",
        "corpus_15800": "15800 as the benchmark set captured it: the same",
    },
}
# Captures of one moment, for counting blind spots over distinct frames
# (3.12): each "+1" benchmark frame and the benchmark set's copies of corpus
# frames, under the frame they repeat.
SAME_MOMENT: dict[str, str] = {
    "sky_4001": "sky_4000",
    "battle_4001": "battle_4000",
    "ship_6001": "ship_6000",
    "cutscene_4501": "cutscene_4500",
    "field_5001": "field_5000",
    "corpus_15800": "15800",
    "corpus_6000": "6000",
}
# Captures that fail V0 for a cause 3.12 calls by design, each bisected to
# its first diverging draws (FINDINGS "V4"). An unlisted failure fails the
# run, and so do more than three listed ones (3.12: the threshold question).
BY_DESIGN: dict[str, str] = {
    "field_5000": "coplanar decals' depth: the CPU steps depth along a span by float adds and drifts 27 to 57 "
    "24-bit steps over long spans (draws 346, 355 and 653), so decals 374, 393 and 653 pass LEQUAL on the CPU "
    "that exact arithmetic and the GPU (within 2 steps of it) fail; draw 656 ties exactly and the CPU's last "
    "bit fails it; draw 76 samples at LOD 3.50, on the boundary of two very different mip levels",
    "field_5001": "the frame after field_5000, the same",
}
# A mutation that applies on fewer than five captures, with why. The rule
# (3.12) wants five; the corpus and the benchmark set have no more to give,
# and with V1's captures (--set corpus,perfset,gpuset) the alpha test applies
# on five.
SHORT_OF_FIVE: dict[str, str] = {
    "alpha": "only 8000 and the ship pair have alpha-tested pixels that show once drawn (0.9%, 3.8%); "
    "sky's come to 0.49% and 12100's to 0.23%",
}


def oracle(prof: toolchain.Profile, sets: list[str], mutations: bool) -> int:
    """V4a's and V4b's Done: every capture of the sets, poisoned where its
    frame copies to a texture, replayed on the CPU (the reference, checked
    against the manifest's hash or V0's inspected image) and on the GPU, and
    V0's verdict on the pair."""
    code = ready(prof)
    if code is not None:
        return code
    out = build_dir(prof) / "oracle"
    out.mkdir(parents=True, exist_ok=True)
    caps = captures(sets)
    with_copies = sum(1 for cap in caps if cap.copies)
    print(
        f"{len(caps)} captures from {', '.join(sets)}; {with_copies} copy to a texture and are "
        f"replayed poisoned, {len(caps) - with_copies} do not"
    )
    failures = 0
    largest: dict[str, list[str]] = {}
    bases: dict[str, Path] = {}
    rows = []
    for cap in caps:
        setname, c = cap.setname, cap.capture
        base = bases[c.name] = replay_base(cap, out / "poisoned")
        ref, gpu = out / f"{c.name}_cpu.png", out / f"{c.name}_gpu.png"
        proc, h = replay(prof, "cpu", base, ref)
        if proc.returncode != 0 or h is None:
            print(f"FAIL {c.name}: the CPU replay exited {proc.returncode}")
            failures += 1
            continue
        if c.frame_hash is not None:
            ref_ok = h == c.frame_hash
            ref_note = f"reference {h} {'is' if ref_ok else 'is NOT'} the manifest's"
        else:
            v0 = imgdiff.OUT / "ref" / setname / f"{c.name}.png"
            ref_ok = v0.exists() and same_pixels(ref, v0)
            ref_note = (
                f"reference {'is' if ref_ok else 'is NOT'} V0's {v0.relative_to(ROOT).as_posix()}"
            )
        if not ref_ok:
            print(f"FAIL {c.name}: {ref_note}")
            failures += 1
            continue
        # The GPU's frame, counting each draw's samples on the way (which
        # changes no pixel) for the skip-largest mutation.
        proc, _ = replay(prof, "gpu", base, gpu, "measure")
        if skipped(proc):
            return SKIP
        m = re.search(r"largest draws \(draw:samples\)((?: \d+:\d+)+)", proc.stderr)
        if proc.returncode != 0 or not m:
            print(f"FAIL {c.name}: the GPU replay exited {proc.returncode}")
            for line in proc.stderr.splitlines():
                if "refused" in line or "failed" in line:
                    print(f"  {line}")
            failures += 1
            continue
        largest[c.name] = [d.split(":")[0] for d in m.group(1).split() if not d.endswith(":0")]
        metrics = imgdiff.compare(ref, gpu, out / f"{c.name}_heat.png")
        bad = metrics.failures()
        listed = bool(bad) and c.name in BY_DESIGN
        failures += bool(bad) and not listed
        rows.append((c.name, not bad, listed))
        verdict = "pass" if not bad else "by design" if listed else "FAIL"
        print(
            f"{verdict} {setname:7} {c.name:14} {'poisoned ' if cap.copies else ''}{metrics.line()}"
        )
        for line in bad:
            print(f"     {line}")
        if listed:
            print(f"     by design: {BY_DESIGN[c.name]}")
    passed = sum(ok for _, ok, _ in rows)
    by_design = sum(listed for _, _, listed in rows)
    if by_design > 3:
        print(
            f"FAIL {by_design} by-design failures: more than three is the threshold question (3.12)"
        )
        failures += 1
    print(f"[gpuspike] oracle: {passed} of {len(caps)} pass V0, {by_design} fail by design")
    if mutations and not failures:
        # A frame that already fails V0 cannot show a mutation failing it.
        judged = [(cap.setname, cap.capture) for cap in caps if cap.capture.name not in BY_DESIGN]
        failures += oracle_mutations(prof, judged, out, largest, bases)
    return 1 if failures else 0


def oracle_mutations(
    prof: toolchain.Profile,
    caps: list[tuple[str, imgdiff.Capture]],
    out: Path,
    largest: dict[str, list[str]],
    bases: dict[str, Path],
) -> int:
    """Each GPU mutation on every capture: where it changes 0.5% of the
    pixels or more it applies, and there V0 must fail. The draw skipped is
    the one, of the five that passed the most samples, whose absence changes
    the most pixels: the most samples alone picks a full-screen fill that
    later draws cover entirely, whose absence nobody could see."""
    bad = 0
    for name, what in GPU_MUTATIONS.items():
        applies = failed = 0
        cells = []
        for _, c in caps:
            mutated = out / f"{c.name}_{name}.png"
            if name == "skip-largest":
                best, frac = None, -1.0
                for draw in largest[c.name]:
                    trial = out / f"{c.name}_skip{draw}.png"
                    proc, _ = replay(prof, "gpu", bases[c.name], trial, f"skip-draw:{draw}")
                    f = (
                        changed_fraction(out / f"{c.name}_gpu.png", trial)
                        if proc.returncode == 0
                        else -1.0
                    )
                    if f > frac:
                        best, frac = draw, f
                        trial.replace(mutated)
                    else:
                        trial.unlink(missing_ok=True)
                if best is None:
                    cells.append(f"{c.name} no draw to skip")
                    bad += 1
                    continue
            else:
                proc, _ = replay(prof, "gpu", bases[c.name], mutated, name)
                if proc.returncode != 0:
                    cells.append(f"{c.name} exit {proc.returncode}")
                    bad += 1
                    continue
                frac = changed_fraction(out / f"{c.name}_gpu.png", mutated)
            fails = bool(imgdiff.compare(out / f"{c.name}_cpu.png", mutated).failures())
            if frac >= APPLIES:
                applies += 1
                failed += fails
                cells.append(f"{c.name} {frac:.1%} {'fails' if fails else 'PASSES'}")
            else:
                cells.append(f"{c.name} {frac:.2%} -")
        listed = GPU_BLIND_SPOTS.get(name, {})
        spots = [cell.split()[0] for cell in cells if cell.endswith("PASSES")]
        unlisted = [n for n in spots if n not in listed]
        distinct = {SAME_MOMENT.get(n, n) for n in spots}
        ok = (applies >= 5 or name in SHORT_OF_FIVE) and not unlisted and len(distinct) <= 3
        bad += not ok
        print(
            f"{'ok  ' if ok else 'FAIL'} mutation {name} ({what}): applies on {applies}, "
            f"fails V0 on {failed}, blind spots {len(spots)} ({len(distinct)} distinct)"
        )
        for i in range(0, len(cells), 4):
            print("       " + ";  ".join(cells[i : i + 4]))
        if applies < 5:
            print(f"       applies on fewer than five: {SHORT_OF_FIVE.get(name, 'NOT LISTED')}")
        for n in spots:
            print(f"       blind spot {n}: {listed.get(n, 'NOT LISTED')}")
    print(
        f"[gpuspike] mutations: {'each fails V0 wherever it applies, but for the blind spots listed' if not bad else f'{bad} problem(s)'}"
    )
    return bad


def time_frames(prof: toolchain.Profile, sets: list[str], runs: int, perf_runs: int) -> int:
    """GPU and consumer milliseconds a frame, median of `runs` replays, beside
    tools/perfbench.py's CPU figures taken before and after in the same
    session (A B A). Reported, not a gate (V4a)."""
    code = ready(prof)
    if code is not None:
        return code
    scratch = build_dir(prof) / "time"
    scratch.mkdir(parents=True, exist_ok=True)

    def perfbench() -> None:
        exe = ROOT / "gen" / "soa.exe"
        if not exe.exists():
            print("perfbench: no gen/soa.exe here, so no CPU figures")
            return
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "perfbench.py"), "run", "--runs", str(perf_runs)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        print(proc.stdout.rstrip())

    perfbench()
    print(f"{'capture':<16} {'GPU ms':>8} {'consumer ms':>12}   (median of {runs})")
    for c in (c for name in sets for c in imgdiff.SETS[name]()):
        gpu_ms, consumer_ms = [], []
        for _ in range(runs):
            proc, _ = replay(prof, "gpu", c.base, scratch / "frame.png")
            if skipped(proc):
                return SKIP
            g = re.search(r"GPU ([0-9.]+) ms", proc.stderr)
            k = re.search(r"consumer ([0-9.]+) ms", proc.stderr)
            if proc.returncode != 0 or not g or not k:
                print(f"FAIL {c.name}: exit {proc.returncode}")
                return 1
            gpu_ms.append(float(g.group(1)))
            consumer_ms.append(float(k.group(1)))
        print(
            f"{c.name:<16} {statistics.median(gpu_ms):8.2f} {statistics.median(consumer_ms):12.2f}"
        )
    perfbench()
    return 0


# ---- V4b: copies to a texture: poison, ramdiff, chain ---------------------------

MEM1_SIZE = 0x01800000
POISON = 0xA5
# Each texture format's tile: width, height, bytes (gxr.c copy_bytes).
TILE = {
    0: (8, 8, 32),
    1: (8, 4, 32),
    2: (8, 4, 32),
    3: (4, 4, 32),
    4: (4, 4, 32),
    5: (4, 4, 32),
    6: (4, 4, 64),
}


def copy_texfmt(v: int) -> int:
    """gxr.c's copy_texfmt: the texture format a copy command makes, 99 for
    one it refuses. A third copy of it (gxv.c has the second), held to the
    first by the CPU replays this file's poison step must leave unmoved."""
    tpf = (v >> 3) & 15
    fmt = tpf // 2 + (tpf & 1) * 8
    if (v >> 15) & 1:
        return fmt if fmt <= 3 else 99
    return {0: 0, 1: 1, 7: 1, 8: 1, 9: 1, 10: 1, 2: 2, 3: 3, 11: 3, 12: 3, 4: 4, 5: 5, 6: 6}.get(
        fmt, 99
    )


@dataclass
class TexCopy:
    """A copy to a texture, as the stream makes it."""

    index: int  # among the frame's copies to a texture
    offset: int  # where its BP 0x52 write starts in the stream
    dest: int
    extent: int  # bytes, from its first tile to the end of its last
    texfmt: int
    x0: int
    y0: int
    ow: int
    oh: int
    half: int
    row_bytes: int

    def runs(self) -> list[tuple[int, int]]:
        """The bytes the copy writes, a run a row of tiles: a stride wider than
        the copy leaves gaps between them that it never touches."""
        tw, th, bpt = TILE[self.texfmt]
        cols, rows = (self.ow + tw - 1) // tw, (self.oh + th - 1) // th
        return [(self.dest + r * self.row_bytes, cols * bpt) for r in range(rows)]


def texture_copies(base: Path) -> list[TexCopy]:
    """Every copy to a texture a capture's stream makes, with copy_bytes'
    arithmetic (strides included), from the registers as the stream sets
    them. Only copies in the stream itself: a copy inside a display list is
    refused, since cutting the stream there (ramdiff) would cut the list."""
    cp_regs, xf_regs, bp_regs = fifo.read_regs(str(scenario.part(base, ".regs")))
    cp = {i: v for i, v in enumerate(cp_regs) if v}
    bp = dict(enumerate(bp_regs))
    ram = scenario.part(base, ".ram").read_bytes()
    stream = scenario.part(base, ".fifo").read_bytes()
    out: list[TexCopy] = []
    for cmd in fifo.walk(stream, cp, list(xf_regs), ram, bp=bp, follow_lists=True):
        if cmd[0] != "bp" or cmd[3] != 0x52 or cmd[4] & 0x4000:
            continue
        if cmd[2] is not None:
            raise SystemExit(f"gpuspike: {base.name} copies to a texture inside a display list")
        v = cmd[4]
        texfmt = copy_texfmt(v)
        if texfmt == 99:
            continue
        tl, wh = bp.get(0x49, 0), bp.get(0x4A, 0)
        w, h = (wh & 0x3FF) + 1, ((wh >> 10) & 0x3FF) + 1
        half = (v >> 9) & 1
        ow, oh = (w // 2, h // 2) if half else (w, h)
        tw, th, bpt = TILE[texfmt]
        natural = (ow + tw - 1) // tw * bpt
        row = max((bp.get(0x4D, 0) & 0x3FF) * 32, natural)
        rows, cols = (oh + th - 1) // th, (ow + tw - 1) // tw
        extent = (rows - 1) * row + cols * bpt if rows and cols else 0
        dest = ((bp.get(0x4B, 0) & 0x1FFFFF) << 5) & fifo.MEM_MASK
        if extent and dest + extent <= MEM1_SIZE:
            out.append(
                TexCopy(
                    len(out),
                    cmd[1],
                    dest,
                    extent,
                    texfmt,
                    tl & 0x3FF,
                    (tl >> 10) & 0x3FF,
                    ow,
                    oh,
                    half,
                    row,
                )
            )
    return out


def scratch_capture(
    base: Path,
    out: Path,
    poison: list[TexCopy],
    splice: dict[int, bytes] | None = None,
    stream: bytes | None = None,
) -> Path:
    """A copy of a capture in `out`: its RAM with `splice`'s bytes laid over
    it (chain) and then 0xA5 over every range in `poison` (3.12: a sampler
    can then see only what this replay's copies wrote), and its stream
    replaced by `stream` when given (ramdiff)."""
    out.mkdir(parents=True, exist_ok=True)
    dst = out / base.name
    shutil.copyfile(scenario.part(base, ".regs"), scenario.part(dst, ".regs"))
    if stream is None:
        shutil.copyfile(scenario.part(base, ".fifo"), scenario.part(dst, ".fifo"))
    else:
        scenario.part(dst, ".fifo").write_bytes(stream)
    ram = bytearray(scenario.part(base, ".ram").read_bytes())
    for at, data in (splice or {}).items():
        ram[at : at + len(data)] = data
    for c in poison:
        for at, n in c.runs():
            ram[at : at + n] = bytes([POISON]) * n
    scenario.part(dst, ".ram").write_bytes(bytes(ram))
    return dst


def bp_write(reg: int, value: int) -> bytes:
    return bytes([0x61, reg]) + (value & 0xFFFFFF).to_bytes(3, "big")


def efb_at(base: Path, c: TexCopy) -> bytes:
    """The capture's stream cut just before copy c, then an unfiltered
    640x480 screen copy: replayed, its frame is the EFB as that copy found it."""
    stream = scenario.part(base, ".fifo").read_bytes()[: c.offset]
    tail = bp_write(0x53, 0) + bp_write(0x54, 0) + bp_write(0x49, 0) + bp_write(0x4A, 0x077E7F)
    return stream + tail + bp_write(0x52, 0x4003)


def texel_of(off: int, c: TexCopy) -> tuple[int, int] | None:
    """The texel byte `off` of a copy holds (the first, for R4's two), or
    None for a byte between rows of tiles or past the copy's edge."""
    tw, th, bpt = TILE[c.texfmt]
    ty, rem = divmod(off, c.row_bytes)
    tx, b = divmod(rem, bpt)
    if tx >= (c.ow + tw - 1) // tw:
        return None
    if c.texfmt == 0:
        iy, ix = b // 4, (b % 4) * 2
    elif c.texfmt in (1, 2):
        iy, ix = divmod(b, 8)
    elif c.texfmt == 6:
        iy, ix = divmod((b % 32) // 2, 4)
    else:
        iy, ix = divmod(b // 2, 4)
    x, y = tx * tw + ix, ty * th + iy
    return (x, y) if x < c.ow and y < c.oh else None


def logic_captures() -> list[Cap]:
    """The captures that draw under a logic op: the mask effect's 14."""
    out = []
    for cap in captures(["corpus", "perfset"]):
        summary = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "fifo.py"), str(cap.capture.base), "--summary"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        m = re.search(r"(\d+) draws under a logic op", summary)
        if m and int(m.group(1)):
            out.append(cap)
    return out


LOGIC_MODES = ("native", "blend", "snapshot")


def logicop(prof: toolchain.Profile, mutate: str | None) -> int:
    """V4b: the mask effect's captures through the three ways of drawing a
    logic op, poisoned; byte-identical images (a same-replay contrast). With
    --mutate, the mutation is applied to the native path alone: the paths must
    then differ, and the native frame must fail V0 against the CPU's."""
    code = ready(prof)
    if code is not None:
        return code
    out = build_dir(prof) / "logicop"
    out.mkdir(parents=True, exist_ok=True)
    caps = logic_captures()
    bad = 0
    for cap in caps:
        c = cap.capture
        base = replay_base(cap, out / "poisoned")
        pngs, counts = {}, {}
        for mode in LOGIC_MODES:
            pngs[mode] = out / f"{c.name}_{mode}.png"
            proc, _ = replay(
                prof, "gpu", base, pngs[mode], mutate if mode == "native" else None, mode
            )
            if skipped(proc):
                return SKIP
            m = re.search(r"logic ops: (\d+) draws", proc.stderr)
            counts[mode] = int(m.group(1)) if proc.returncode == 0 and m else -1
        images = {mode: png.read_rgba(pngs[mode]) for mode in LOGIC_MODES}
        w, h, _ = images["native"]
        rows = {mode: pixel_rows(w, h, images[mode][2]) for mode in LOGIC_MODES}
        differ = {
            mode: sum(
                sum(map(ne, a, b, strict=True))
                for a, b in zip(rows["native"], rows[mode], strict=True)
            )
            for mode in ("blend", "snapshot")
        }
        same = images["blend"] == images["snapshot"]
        drawn = min(counts.values())
        line = (
            f"{c.name:14} logic draws {drawn}; native differs from blend at {differ['blend']} px, "
            f"from snapshot at {differ['snapshot']}; blend {'=' if same else '!='} snapshot"
        )
        if mutate:
            ref = out / f"{c.name}_cpu.png"
            replay(prof, "cpu", base, ref)
            fails = bool(imgdiff.compare(ref, pngs["native"]).failures())
            ok = drawn > 0 and differ["blend"] > 0 and differ["snapshot"] > 0 and same and fails
            line += f"; the mutated native frame {'fails' if fails else 'PASSES'} V0"
        else:
            ok = drawn > 0 and not differ["blend"] and not differ["snapshot"] and same
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {line}")
    what = (
        f"--mutate {mutate}: every capture's paths differ and the native one fails V0"
        if mutate
        else ("the three paths give byte-identical images")
    )
    print(f"[gpuspike] logicop over {len(caps)} captures: {what if not bad else f'{bad} FAIL'}")
    return 1 if bad else 0


def ramdiff(prof: toolchain.Profile, sets: list[str], mutate: str | None = None) -> int:
    """V4b: after each copy to a texture, the GPU's bytes against the CPU's,
    both poisoned: bytes written, bytes differing and the largest difference.
    Each differing byte is traced to the EFB as that copy found it (efb_at,
    on both paths): a texel can differ only where one of the pixels its
    filter reads does, the encoders being byte for byte the same (V3b)."""
    code = ready(prof)
    if code is not None:
        return code
    out = build_dir(prof) / "ramdiff"
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    copies_seen = 0
    for cap in (cap for cap in captures(sets) if cap.copies):
        c = cap.capture
        base = replay_base(cap, out / "poisoned")
        rams = {}
        for b in ("cpu", "gpu"):
            rams[b] = out / f"{c.name}_{b}.ram"
            proc, _ = replay(
                prof,
                b,
                base,
                out / f"{c.name}_{b}.png",
                mutate if b == "gpu" else None,
                dump_ram=rams[b],
            )
            if b == "gpu" and skipped(proc):
                return SKIP
        cpu_ram, gpu_ram = rams["cpu"].read_bytes(), rams["gpu"].read_bytes()
        for tc in cap.copies:
            copies_seen += 1
            a = cpu_ram[tc.dest : tc.dest + tc.extent]
            g = gpu_ram[tc.dest : tc.dest + tc.extent]
            written = sum(1 for at, n in tc.runs() for x in cpu_ram[at : at + n] if x != POISON)
            differ = [i for i in range(tc.extent) if a[i] != g[i]]
            largest = max((abs(a[i] - g[i]) for i in differ), default=0)
            untraced = 0
            if differ:
                efb = {}
                for b in ("cpu", "gpu"):
                    cut = scratch_capture(
                        c.base,
                        out / f"{c.name}_at{tc.index}_{b}",
                        cap.copies,
                        stream=efb_at(c.base, tc),
                    )
                    replay(prof, b, cut, out / f"{c.name}_at{tc.index}_{b}.png")
                    efb[b] = png.read_rgba(out / f"{c.name}_at{tc.index}_{b}.png")[2]
                for i in differ:
                    t = texel_of(i, tc)
                    if t is None:
                        untraced += 1
                        continue
                    sx = tc.x0 + (2 * t[0] if tc.half else t[0])
                    sy = tc.y0 + (2 * t[1] if tc.half else t[1])
                    rows = range(max(sy - 1, 0), min(sy + 2 + tc.half, 480))
                    cols = range(sx, min(sx + 1 + tc.half, 640))
                    if not any(
                        efb["cpu"][(y * 640 + x) * 4 : (y * 640 + x) * 4 + 3]
                        != efb["gpu"][(y * 640 + x) * 4 : (y * 640 + x) * 4 + 3]
                        for y in rows
                        for x in cols
                    ):
                        untraced += 1
            ok = written > 0 and not untraced
            bad += not ok
            print(
                f"{'ok  ' if ok else 'FAIL'} {c.name:14} copy {tc.index + 1} to {tc.dest:08X} (format {tc.texfmt}, "
                f"{tc.extent} bytes): {written} written, {len(differ)} differ, largest {largest}, "
                f"{untraced} not traced to the EFB"
            )
    print(
        f"[gpuspike] ramdiff over {copies_seen} copies: {'every difference is the EFB' if not bad else f'{bad} FAIL'}"
    )
    return 1 if bad else 0


def chain(prof: toolchain.Profile, names: list[str]) -> int:
    """V4b: a sequence of V1's captures N ... N+k, each frame's copies kept
    and spliced into the next frame's RAM, except where that frame copies
    itself. On the CPU the spliced bytes must equal what the next frame's RAM
    already holds there (no CPU write came between); each chained GPU frame
    must pass V0 against the chained CPU frame."""
    code = ready(prof)
    if code is not None:
        return code
    out = build_dir(prof) / "chain"
    out.mkdir(parents=True, exist_ok=True)
    caps = {cap.capture.name: cap for cap in captures(["gpuset"])}
    kept: dict[str, dict[int, bytes]] = {"cpu": {}, "gpu": {}}
    bad = 0
    for name in names:
        cap = caps[name]
        own = [(tc.dest, tc.dest + tc.extent) for tc in cap.copies]

        def outside(at: int, n: int, own: list[tuple[int, int]] = own) -> bool:
            return all(at + n <= lo or at >= hi for lo, hi in own)

        splice = {
            b: {at: data for at, data in kept[b].items() if outside(at, len(data))} for b in kept
        }
        ram = scenario.part(cap.capture.base, ".ram").read_bytes()
        mismatched = sum(
            sum(map(ne, ram[at : at + len(data)], data, strict=True))
            for at, data in splice["cpu"].items()
        )
        pngs = {}
        for b in ("cpu", "gpu"):
            base = scratch_capture(cap.capture.base, out / f"{name}_{b}", cap.copies, splice[b])
            pngs[b] = out / f"{name}_{b}.png"
            dump = out / f"{name}_{b}.ram"
            proc, _ = replay(prof, b, base, pngs[b], dump_ram=dump)
            if b == "gpu" and skipped(proc):
                return SKIP
            after = dump.read_bytes()
            for tc in cap.copies:
                kept[b] = {
                    at: d
                    for at, d in kept[b].items()
                    if at + len(d) <= tc.dest or at >= tc.dest + tc.extent
                }
                for at, n in tc.runs():
                    kept[b][at] = after[at : at + n]
            dump.unlink()
        metrics = imgdiff.compare(pngs["cpu"], pngs["gpu"])
        fails = metrics.failures()
        ok = not mismatched and not fails
        bad += not ok
        spliced = sum(len(d) for d in splice["cpu"].values())
        print(
            f"{'ok  ' if ok else 'FAIL'} {name}: {len(splice['cpu'])} range(s), {spliced} bytes spliced, "
            f"{'equal to its RAM' if not mismatched else f'{mismatched} byte(s) NOT equal to its RAM'}; "
            f"V0 {'passes' if not fails else 'FAILS'}: {metrics.line()}"
        )
    print(
        f"[gpuspike] chain over {len(names)} frames: {'every frame chains and passes' if not bad else f'{bad} FAIL'}"
    )
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "command",
        choices=(
            "build",
            "selftest",
            "tevdiff",
            "copydiff",
            "loddiff",
            "oracle",
            "time",
            "logicop",
            "ramdiff",
            "chain",
        ),
    )
    ap.add_argument(
        "frames", nargs="*", help="chain: V1's captures in order, e.g. battle_4421 battle_4422"
    )
    ap.add_argument("--cc", choices=tuple(toolchain.PROFILES), default="msvc")
    ap.add_argument("--mutate", default=None, help="a gxv mutation the command must fail on")
    ap.add_argument("--cases", type=int, default=100000, help="tevdiff and loddiff: random cases")
    ap.add_argument("--rects", type=int, default=200, help="copydiff: rectangles a combination")
    ap.add_argument("--seed", type=int, default=1, help="tevdiff, copydiff and loddiff")
    ap.add_argument("--set", default="corpus,perfset", help="oracle and time: capture sets")
    ap.add_argument("--mutations", action="store_true", help="oracle: also the GPU mutations")
    ap.add_argument("--runs", type=int, default=5, help="time: replays a capture")
    ap.add_argument(
        "--logicop",
        default=None,
        help="selftest: how gxv draws logic ops (native, blend, snapshot)",
    )
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
    if args.command == "loddiff":
        return loddiff(prof, args.cases, args.seed, args.mutate)
    if args.command == "oracle":
        return oracle(prof, args.set.split(","), args.mutations)
    if args.command == "logicop":
        return logicop(prof, args.mutate)
    if args.command == "ramdiff":
        return ramdiff(prof, args.set.split(","), args.mutate)
    if args.command == "chain":
        return chain(prof, args.frames)
    if args.command == "time":
        return time_frames(prof, args.set.split(","), args.runs, 3)
    return selftest(prof, args.mutate, args.logicop)


if __name__ == "__main__":
    raise SystemExit(main())
