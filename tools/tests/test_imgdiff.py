"""The frame oracle (tools/imgdiff.py, specs/gpu-backend.md V0) on synthetic
frames: no soa.exe, no captures, so CI runs it.

The thresholds have to fail what a broken renderer does -- a missing object,
a colour shift, swapped channels -- and pass what two correct renderers
legitimately disagree on: last-bit noise everywhere, and scattered pixels.
The reference check has to be the manifest's hash exactly, and the replays
that make references must not see the caller's SOA_* variables.
"""

import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import imgdiff  # noqa: E402
from soa import png  # noqa: E402

W, H = 640, 480


@pytest.fixture(scope="module")
def frame() -> bytes:
    """A frame with structure in every channel and red unlike blue, so that a
    channel swap is visible and an edge-energy search has somewhere to go."""
    out = bytearray(W * H * 4)
    for y in range(H):
        for x in range(W):
            o = (y * W + x) * 4
            out[o] = (x * 3 + y) & 255
            out[o + 1] = (x ^ y) & 255
            out[o + 2] = (y * 2 + (x >> 3)) & 255
            out[o + 3] = 255
    return bytes(out)


def verdict(ref: bytes, cand: bytes) -> list[str]:
    m, _, _ = imgdiff.measure(W, H, ref, cand)
    return m.failures()


def mutated(name: str, ref: bytes) -> bytes:
    fn = next(f for n, f, _ in imgdiff.MUTATIONS if n == name)
    return fn(W, H, ref, random.Random(name))


def test_identity_passes(frame):
    m, _, _ = imgdiff.measure(W, H, frame, frame)
    assert m.exact == W * H and not m.failures()


@pytest.mark.parametrize("name", ["noise +-1", "0.3% scattered"])
def test_legitimate_noise_passes(frame, name):
    assert verdict(frame, mutated(name, frame)) == []


@pytest.mark.parametrize("name", ["black 24x24 block", "+4 brightness", "red-blue swap"])
def test_a_defect_fails(frame, name):
    assert verdict(frame, mutated(name, frame)), f"{name} passed"


def test_a_frame_drawn_a_pixel_over_is_a_shift():
    """Small errors everywhere, which far pixels and MAE pass: the filter
    test is what fails it (V0's metric change)."""
    out = bytearray(W * H * 4)
    for y in range(H):
        for x in range(W):
            o = (y * W + x) * 4
            out[o : o + 4] = bytes(((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256, 255))
    ref = bytes(out)
    m, _, _ = imgdiff.measure(W, H, ref, mutated("one-pixel shift", ref))
    assert m.shift[0] < -0.9, m.line()
    assert any(f.startswith("shift x") for f in m.failures())


def test_a_second_vertical_filter_is_a_blur(frame):
    m, _, _ = imgdiff.measure(W, H, frame, mutated("vertical blur", frame))
    assert m.blur[1] > 0.2, m.line()
    assert any(f.startswith("blur y") for f in m.failures())


def test_noise_explains_nothing(frame):
    m, _, _ = imgdiff.measure(W, H, frame, mutated("noise +-1", frame))
    assert max(map(abs, m.shift + m.blur)) < 0.05, m.line()


def test_a_block_is_a_blob_and_an_edge_is_not():
    """The blob rule is what tells a missing object from an edge drawn a pixel
    over: a filled square leaves its interior, a one-pixel line leaves nothing."""
    mask = bytearray(W * H)
    for y in range(100, 124):
        for x in range(200, 224):
            mask[y * W + x] = 1
    for x in range(W):
        mask[300 * W + x] = 1
    blob = imgdiff.erode(mask, W, H)
    assert sum(blob) == 22 * 22
    assert imgdiff.largest_component(blob, W, H) == 22 * 22


def test_the_screen_hash_is_gxr_screen_hashs():
    """FNV-1a 64 over the dimensions as big-endian 16-bit numbers, then the
    rows: worked by hand for a 2x1 image of the bytes 1..8."""
    assert png.screen_hash(2, 1, bytes(range(1, 9))) == "175196677ff53a34"


def test_one_pixel_changes_the_hash(frame, tmp_path):
    p = tmp_path / "f.png"
    png.write_rgba(p, W, H, frame)
    w, h, back = png.read_rgba(p)
    assert (w, h, back) == (W, H, frame)
    pinned = png.screen_hash(W, H, frame)
    one = bytearray(frame)
    one[4 * (W * 240 + 320)] ^= 1
    assert png.screen_hash(W, H, bytes(one)) != pinned


def test_the_replay_sees_no_soa_variable_but_the_tools(tmp_path, monkeypatch):
    """A reference made with the caller's SOA_GPU=vulkan, or a player's
    settings, would not be the CPU renderer's frame."""
    parent = {"PATH": "keep", "SOA_GPU": "vulkan", "SOA_SETTINGS": "1", "SOA_SNAP": "5"}
    env = imgdiff.child_env(parent)
    assert env["PATH"] == "keep"
    soa = {k: v for k, v in env.items() if k.startswith("SOA_")}
    assert soa == {"SOA_SETTINGS": "0", "SOA_HASH": "1", "SOA_THREADS": "4"}

    base = tmp_path / "cap" / "0100"
    base.parent.mkdir()
    for ext in (".fifo", ".regs", ".ram"):
        (tmp_path / "cap" / f"0100{ext}").write_bytes(b"x")
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"], seen["cmd"] = kw["env"], cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(imgdiff.subprocess, "run", fake_run)
    monkeypatch.setenv("SOA_GPU", "vulkan")
    imgdiff.render(imgdiff.Capture("0100", base, None), Path("soa.exe"), tmp_path / "scratch")
    assert "SOA_GPU" not in seen["env"]
    assert seen["env"]["SOA_SETTINGS"] == "0"
    # the replay runs on a scratch copy, never on the capture itself
    assert Path(seen["cmd"][2]).parent.parent == tmp_path / "scratch"


# ---- V9a: a frame drawn at scale, taken back down -------------------------


def scaled(w: int, h: int, k: int) -> bytes:
    """A w x h frame drawn at k times its size, every sample its own colour:
    sample (X, Y) holds X, Y and X + Y."""
    out = bytearray(w * k * h * k * 4)
    for y in range(h * k):
        for x in range(w * k):
            o = (y * w * k + x) * 4
            out[o : o + 4] = bytes((x & 255, y & 255, (x + y) & 255, 255))
    return bytes(out)


def test_the_centre_sample_is_each_blocks_middle():
    w, h, px = imgdiff.downsample(4 * 3, 2 * 3, scaled(4, 2, 3), 3, "centre")
    assert (w, h) == (4, 2)
    for y in range(2):
        for x in range(4):
            assert px[(y * 4 + x) * 4 : (y * 4 + x) * 4 + 3] == bytes(
                (3 * x + 1, 3 * y + 1, 3 * x + 3 * y + 2)
            )


def test_the_box_is_the_blocks_mean_rounded_as_the_copy_shader_rounds_it():
    """(sum + 2) / 4 at scale 2: samples 2x and 2x + 1 average to 2x + 0.5,
    which rounds up."""
    w, h, px = imgdiff.downsample(3 * 2, 2 * 2, scaled(3, 2, 2), 2, "box")
    assert (w, h) == (3, 2)
    for y in range(2):
        for x in range(3):
            o = (y * 3 + x) * 4
            assert px[o : o + 4] == bytes((2 * x + 1, 2 * y + 1, 2 * x + 2 * y + 1, 255))


def test_an_even_scale_has_no_centre_sample():
    with pytest.raises(ValueError):
        imgdiff.downsample(4, 4, scaled(2, 2, 2), 2, "centre")


def test_the_largest_step_ignores_alpha():
    a = bytes((10, 20, 30, 255, 0, 0, 0, 255))
    assert imgdiff.largest_step(a, bytes((10, 20, 30, 0, 0, 0, 0, 255))) == 0
    assert imgdiff.largest_step(a, bytes((10, 23, 30, 255, 0, 0, 1, 255))) == 3
