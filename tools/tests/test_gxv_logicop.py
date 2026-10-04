"""Logic ops without logicOp (specs/gpu-backend.md V10).

`python tools/gpuspike.py logictest` draws two synthetic scenes with depth
off. A quad of 0x55 ORed into 0xAA must give 0xFF from the CPU, native, a
snapshot, the interlock and SOA_GPU_FEATURES=core's route, and 198 from the
forced blend approximation: the test demands both, so it proves the modes
differ where they should. Two overlapping triangles XORed onto black must
come back black in the overlap from the CPU and native; with no logicOp
(SOA_GPU_FEATURES=nologicop) the draw is routed to the interlock and drawn as
native draws it; with neither logicOp nor interlock (core) it goes to a
snapshot, named in a line, and the overlap is wrong -- never silently to a
blend. They need MSVC, vendor/ and a Vulkan device, and skip saying which
without.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gpuspike  # noqa: E402


def test_logic_ops_are_routed_and_drawn_exactly_where_they_can_be():
    proc = subprocess.run(
        [sys.executable, "tools/gpuspike.py", "logictest"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == gpuspike.SKIP:
        reason = next(
            (ln[6:] for ln in proc.stdout.splitlines() if ln.startswith("skip: ")), "skipped"
        )
        pytest.skip(reason)
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "or, blend: ('198', '198', '198'" in out
    assert "or, snapshot: ('255', '255', '255'" in out
    assert "xor, core: ('240'" in out
    assert "[gpuspike] logictest passes" in out
