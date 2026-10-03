"""The GPU spike: the renderer drawing through a Vulkan backend, headless.

    python tools/gpuspike.py build                      # shaders, then the binary
    python tools/gpuspike.py selftest [--mutate NAME]   # build, draw on both, compare

specs/gpu-backend.md V3a. `build` compiles tools/gpuspike/raster.vert and
raster.frag to SPIR-V with the pinned glslang (tools/fetch_gpu.py), as C
arrays, and builds gx.c, gxr.c, gxr_tev.c and png.c with the spike's driver
and gxv.c (the backend) into build/gpuspike/gpuspike.exe. No gen/, no disc:
the binary links the renderer alone, as tools/citest/render_check.py does.

`selftest` runs the binary twice, `--backend cpu` and `--backend gpu`, into
build/gpuspike/<compiler>/cpu and gpu, and compares the scenes they wrote:

- the self test's two render recipes must pass on the GPU as they are
  written for the CPU (the driver checks them in-process);
- cull0..cull3: four triangle shapes in both windings, a strip, a fan and two
  quads under each cull mode. Away from edges the GPU covers exactly what the
  CPU covers and in the same colour; mode 3 covers nothing, mode 0 something;
- clip_*: triangles crossing the near and far planes, orthographic and in
  perspective. Away from edges the coverage matches and colours are within one
  step (the CPU steps attributes along a span, the GPU interpolates them, 3.4);
  and in the driver the vertices the consumer uploaded must be clip_polygon's;
- lines: every pixel either side drew is within one pixel of one the other
  drew (the CPU steps a line in ceil(length) floor()ed samples; Vulkan
  rasterizes by diamond exit, so endpoints and half-pixel steps may differ);
- points: exactly the CPU's pixels.

An edge pixel is one whose 3x3 neighbourhood in the CPU's image is not all
covered or all uncovered: Vulkan's top-left fill rule and the CPU's inclusive
one disagree there by design. --mutate unclipped makes gxv upload every draw
as it is, and must fail. Exit 0 pass, 1 fail, 3 skipped (no Vulkan device),
with the reason printed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
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
SHADERS = ("raster.vert", "raster.frag")
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
        *(SPIKE / n for n in SHADERS),
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
    crash. Nothing is rebuilt when the binary is newer than every input."""
    if toolchain.compiler_path(prof) is None:
        return False, f"no {prof.name} compiler (tools/soa/toolchain.py compiler_path)"
    bad = fetch_gpu.verify(VENDOR)
    if bad:
        return False, f"vendor/ is not as recorded ({bad[0]}); run python tools/fetch_gpu.py"
    if up_to_date(prof):
        return True, ""
    out = build_dir(prof)
    out.mkdir(parents=True, exist_ok=True)
    exe_path(prof).unlink(missing_ok=True)
    for name in SHADERS:
        var = name.replace(".", "_")
        proc = subprocess.run(
            [
                str(glslang()),
                "-V",
                "--target-env",
                "vulkan1.1",
                "--vn",
                var,
                str(SPIKE / name),
                "-o",
                str(out / f"{var}.h"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr)
            return False, f"glslang failed on {name}"
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


def selftest(prof: toolchain.Profile, mutate: str | None) -> int:
    built, why = build(prof)
    if not built:
        print(f"skip: {why}" if "compiler" in why or "vendor" in why else f"FAIL: {why}")
        return SKIP if ("compiler" in why or "vendor" in why) else 1
    gpu = run(prof, "gpu", mutate)
    m = re.search(r"^skip: (.*)$", gpu.stdout, re.M)
    if gpu.returncode == SKIP and m:
        print(f"skip: {m.group(1)}")
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("command", choices=("build", "selftest"))
    ap.add_argument("--cc", choices=tuple(toolchain.PROFILES), default="msvc")
    ap.add_argument(
        "--mutate", default=None, help="selftest: a gxv mutation that must fail it (unclipped)"
    )
    args = ap.parse_args(argv)
    prof = toolchain.profile(args.cc)
    if args.command == "build":
        built, why = build(prof)
        print(f"built {exe_path(prof)}" if built else f"not built: {why}")
        return 0 if built else 1
    return selftest(prof, args.mutate)


if __name__ == "__main__":
    raise SystemExit(main())
