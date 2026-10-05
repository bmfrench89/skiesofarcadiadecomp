"""SOA_WAV on every system (portability L9).

runtime/audio_out.c's meter, arrival rate, WAV writer and report are every
platform's; only the device (waveOut) is Windows'. Built alone with the
toolchain profile SOA_CC names -- MSVC when unset, gcc on CI's Linux legs --
a driver pushes N blocks of known samples with SOA_WAV set and no device: the
file's header carries N x the block's bytes, the samples are the blocks'
left-then-right, and the report says how much it wrote. Before L9 the
writer sat inside `#ifdef _WIN32`, and off Windows there was no file at all.
"""

import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from soa import toolchain  # noqa: E402

PROFILE = toolchain.profile(os.environ.get("SOA_CC"))
needs_cc = pytest.mark.skipif(toolchain.compiler_path(PROFILE) is None, reason=f"no {PROFILE.name}")
BLOCKS, BLOCK = 7, 640  # 160 stereo frames a block

DRIVER = r"""
#include <stdint.h>
#include <stdio.h>
void audio_push_block(const uint8_t* be_rl, unsigned bytes, unsigned rate);
void audio_report(void);
int main(void)
{
    uint8_t b[TEST_BLOCK];
    unsigned i, k;
    for (k = 0; k < TEST_BLOCKS; k++) {
        for (i = 0; i < TEST_BLOCK; i += 4) { /* right then left, big-endian, as the AI DMA sends them */
            b[i] = (uint8_t)k; b[i + 1] = (uint8_t)(i >> 2); /* right */
            b[i + 2] = 0x40; b[i + 3] = (uint8_t)k;          /* left */
        }
        audio_push_block(b, TEST_BLOCK, 32000);
    }
    audio_report();
    return 0;
}
"""


@needs_cc
def test_soa_wav_writes_every_block_with_its_size_in_the_header(tmp_path):
    (tmp_path / "driver.c").write_text(DRIVER, encoding="utf-8")
    sources = [ROOT / "runtime" / "audio_out.c", tmp_path / "driver.c"]
    defines = [f"/DTEST_BLOCKS={BLOCKS}", f"/DTEST_BLOCK={BLOCK}"]
    proc = toolchain.cc(
        [
            *PROFILE.cflags,
            *defines,
            "/c",
            "/I",
            str(ROOT / "runtime"),
            *map(str, sources),
            "/Fo" + str(tmp_path) + os.sep,
        ],
        tmp_path,
        PROFILE,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    exe = tmp_path / ("wav" + PROFILE.exeext)
    objs = [str(tmp_path / (s.stem + PROFILE.objext)) for s in sources]
    proc = toolchain.cc(
        [*PROFILE.cflags, *objs, "/Fe" + str(exe), *PROFILE.linker], tmp_path, PROFILE
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    wav = tmp_path / "out.wav"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SOA_")}
    env.update(SOA_WAV=str(wav), SOA_NOSOUND="1")
    run = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=60)
    assert run.returncode == 0, run.stderr
    data = wav.read_bytes()
    assert data[:4] == b"RIFF" and data[8:16] == b"WAVEfmt " and data[36:40] == b"data"
    size = struct.unpack_from("<I", data, 40)[0]
    assert size == BLOCKS * BLOCK == len(data) - 44, (size, len(data))
    assert struct.unpack_from("<I", data, 24)[0] == 32000
    left, right = struct.unpack_from("<hh", data, 44 + 4 * 5)  # block 0, frame 5
    assert (left, right) == (0x4000, 5), (hex(left), right)
    assert f"wrote {BLOCKS * BLOCK} bytes of samples to the WAV file" in run.stderr, run.stderr
