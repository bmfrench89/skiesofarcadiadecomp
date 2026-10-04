"""The GPU backend's shaders, runtime/gxv/, to SPIR-V as C arrays (specs/gpu-backend.md 3.10).

glslang, fetched into vendor/ by tools/fetch_gpu.py, compiles each shader, and
each variant of one that a test selects as a mutation, to a header of its own:
<name>.h, holding ``const uint32_t <name>[]``, which runtime/gxv.c includes.
tools/gpuspike.py and recompile.py --link both build them here, so the spike
and soa.exe embed the same SPIR-V. ``stub`` writes headers of the same names
holding one word each, for compile_runtime.py's check of gxv.c on a machine
where glslang cannot run: the C is compiled whole, and nothing that runs is
built from a stub.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHADER_DIR = ROOT / "runtime" / "gxv"
VENDOR = ROOT / "vendor"
HEADERS = VENDOR / "vulkan-headers" / "include"

# Each shader and the variants built from it: (source, header and array name,
# defines). A variant is a mutation gxv_set_mutation selects; the tests run
# each and it must fail.
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
    ("present.vert", "present_vert", ()),
    ("present.frag", "present_frag", ()),
    ("present.frag", "present_frag_offset", ("GXV_MUTATE_PRESENT",)),
]


def glslang() -> Path:
    name = "glslang.exe" if sys.platform == "win32" else "glslang"
    return VENDOR / "glslang" / "bin" / name


def available() -> bool:
    """Whether vendor/ holds what a backend build needs: glslang and the headers."""
    return glslang().exists() and (HEADERS / "vulkan" / "vulkan_core.h").exists()


def sources() -> list[Path]:
    """Every file the headers are made from, the includes among them."""
    return sorted(p for p in SHADER_DIR.iterdir() if p.is_file())


def build(out: Path) -> tuple[bool, str]:
    """Every header into out. (built, why not); glslang's own message is printed."""
    out.mkdir(parents=True, exist_ok=True)
    for src, var, defines in SHADERS:
        proc = subprocess.run(
            [
                str(glslang()),
                "-V",
                "--target-env",
                "vulkan1.1",
                f"-I{SHADER_DIR}",
                *(f"-D{d}" for d in defines),
                "--vn",
                var,
                str(SHADER_DIR / src),
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
    return True, ""


def stub(out: Path) -> None:
    """Headers of the same names, one word each: for compiling gxv.c, never for running it."""
    out.mkdir(parents=True, exist_ok=True)
    for _, var, _ in SHADERS:
        (out / f"{var}.h").write_text(
            f"/* a stub (tools/soa/shaders.py): not SPIR-V */\nconst uint32_t {var}[] = {{0}};\n",
            encoding="utf-8",
        )
