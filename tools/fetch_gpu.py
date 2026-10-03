"""Fetch what the GPU spike builds with into vendor/, which is gitignored.

    python tools/fetch_gpu.py            # fetch what is missing, then record
    python tools/fetch_gpu.py --verify   # check what is on disk against the record

specs/gpu-backend.md V3a, D-18: the build may fetch Vulkan-Headers and glslang,
pinned, and never commits them. Two things come down:

- Vulkan-Headers at the tag vulkan-sdk-1.4.357.0: include/vulkan and
  include/vk_video, into vendor/vulkan-headers. GitHub builds a tag's archive on
  demand and does not promise the same bytes twice, so the archive's hash is
  recorded rather than enforced; every header kept is recorded.
- glslang 16.6.0, the release build for this host (Windows or Linux x86-64),
  into vendor/glslang. A release asset does not change, so its archive's
  sha256 is pinned here and a different one is refused.

vendor/GPU.sha256 records the sha256 of every file kept, in sha256sum's format
with the sources as comments, as vendor/TOOLCHAIN.sha256 does for the
Metrowerks compilers; --verify reports any file missing or changed. Nothing
here touches game data. No Vulkan runtime is fetched: the spike loads the
host's own (vulkan-1.dll), which the GPU driver installs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = "GPU.sha256"
HEADERS_TAG = "vulkan-sdk-1.4.357.0"
HEADERS_URL = f"https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/{HEADERS_TAG}.zip"
GLSLANG_VERSION = "16.6.0"
GLSLANG = {
    "Windows": (
        f"https://github.com/KhronosGroup/glslang/releases/download/{GLSLANG_VERSION}/"
        f"glslang-{GLSLANG_VERSION}-windows-x86_64-release.zip",
        "82bf434e69b9bb4829de7e2b4bc2c5e7a7861e53d66cf75e5cc70f5f694a8d9b",
    ),
    "Linux": (
        f"https://github.com/KhronosGroup/glslang/releases/download/{GLSLANG_VERSION}/"
        f"glslang-{GLSLANG_VERSION}-linux-x86_64-release.zip",
        "a3fc4f083b1793eb53e55fa3577ac9649ffbe0340715e30d116290fb5382393f",
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 - fixed https URLs
        return r.read()


def read_record(path: Path) -> tuple[dict[str, str], list[str]]:
    """(relative path -> sha256, the comment lines)."""
    files: dict[str, str] = {}
    comments: list[str] = []
    if not path.exists():
        return files, comments
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            comments.append(line)
        elif line.strip():
            digest, _, name = line.partition("  ")
            files[name.strip()] = digest.strip()
    return files, comments


def write_record(path: Path, files: dict[str, str], sources: list[str]) -> None:
    lines = [
        "# What the GPU spike builds with (tools/fetch_gpu.py, specs/gpu-backend.md V3a).",
        *sources,
    ]
    lines += [f"{d}  {n}" for n, d in sorted(files.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(vendor: Path) -> list[str]:
    files, _ = read_record(vendor / RECORD)
    if not files:
        return [f"no {vendor / RECORD}: run tools/fetch_gpu.py first"]
    bad = []
    for name, digest in sorted(files.items()):
        p = vendor / name
        if not p.exists():
            bad.append(f"{name}: recorded but missing")
        elif sha256(p.read_bytes()) != digest:
            bad.append(f"{name}: sha256 differs from the record")
    return bad


def unpack_headers(blob: bytes, dest: Path) -> list[Path]:
    """include/vulkan and include/vk_video out of the tag's archive."""
    kept = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            parts = name.split("/", 1)
            if len(parts) < 2 or name.endswith("/"):
                continue
            rel = parts[1]
            if rel.startswith(("include/vulkan/", "include/vk_video/")) or rel == "LICENSE.md":
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(name))
                kept.append(out)
    return kept


def unpack_glslang(blob: bytes, dest: Path) -> list[Path]:
    """The compiler and its licence out of the release archive."""
    kept = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if name.endswith("/") or not base:
                continue
            if "/bin/" in f"/{name}" and base.split(".")[0] in ("glslang", "glslangValidator"):
                out = dest / "bin" / base
            elif base.upper().startswith("LICENSE"):
                out = dest / base
            else:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(name))
            if not base.endswith(".exe"):
                out.chmod(0o755)
            kept.append(out)
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--vendor", type=Path, default=ROOT / "vendor")
    ap.add_argument(
        "--verify", action="store_true", help="only check what is on disk against the record"
    )
    args = ap.parse_args(argv)
    vendor = args.vendor

    if args.verify:
        bad = verify(vendor)
        for line in bad:
            print(line, file=sys.stderr)
        files, _ = read_record(vendor / RECORD)
        print(f"{len(files) - len(bad)} of {len(files)} recorded GPU build file(s) unchanged")
        return 1 if bad else 0

    host = platform.system()
    if host not in GLSLANG:
        print(f"error: no glslang release for {host}", file=sys.stderr)
        return 1
    files, comments = read_record(vendor / RECORD)
    sources = [c for c in comments if "://" in c]
    kept: list[Path] = []

    headers = vendor / "vulkan-headers"
    if not (headers / "include" / "vulkan" / "vulkan_core.h").exists():
        blob = fetch(HEADERS_URL)
        kept += unpack_headers(blob, headers)
        sources = [s for s in sources if "Vulkan-Headers" not in s]
        sources.append(
            f"# vulkan-headers: {HEADERS_URL} (archive sha256 {sha256(blob)}, not enforced)"
        )
    else:
        kept += [p for p in headers.rglob("*") if p.is_file()]

    glslang = vendor / "glslang"
    url, pin = GLSLANG[host]
    exe = glslang / "bin" / ("glslang.exe" if host == "Windows" else "glslang")
    if not exe.exists():
        blob = fetch(url)
        digest = sha256(blob)
        if digest != pin:
            print(f"error: {url} has sha256 {digest}, not the pinned {pin}", file=sys.stderr)
            return 1
        kept += unpack_glslang(blob, glslang)
        sources = [s for s in sources if "glslang:" not in s]
        sources.append(f"# glslang: {url} (sha256 {digest}, pinned)")
    else:
        kept += [p for p in glslang.rglob("*") if p.is_file()]

    for p in kept:
        files[p.relative_to(vendor).as_posix()] = sha256(p.read_bytes())
    write_record(vendor / RECORD, files, sources)
    print(f"recorded {len(files)} file(s) in {vendor / RECORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
