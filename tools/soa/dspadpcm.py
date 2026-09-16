"""Nintendo DSP-ADPCM (``.dsp``) decoding.

The disc's music streams and sample banks are DSP-ADPCM: 8-byte frames of a
header nibble pair (predictor index, scale) and 14 four-bit samples, decoded
with the file's 8 coefficient pairs::

    s[n] = clamp((nibble << scale) * 2048 + c0 * s[n-1] + c1 * s[n-2] + 1024) >> 11

``parse_header`` reads the standard 0x60-byte header; ``decode`` returns the
samples as a list of ints. Analysis only: nothing here writes game data.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class DspHeader:
    num_samples: int
    num_nibbles: int
    sample_rate: int
    loop_flag: int
    fmt: int
    loop_start: int
    loop_end: int
    coefs: list[int]
    pred_scale: int
    yn1: int
    yn2: int

    @property
    def data_offset(self) -> int:
        return 0x60


def parse_header(data: bytes) -> DspHeader:
    if len(data) < 0x60:
        raise ValueError("not a DSP-ADPCM header")
    num_samples, num_nibbles, rate = struct.unpack(">III", data[:12])
    loop_flag, fmt = struct.unpack(">HH", data[12:16])
    loop_start, loop_end = struct.unpack(">II", data[16:24])
    coefs = list(struct.unpack(">16h", data[0x1C:0x3C]))
    pred_scale, yn1, yn2 = struct.unpack(">Hhh", data[0x3E:0x44])
    return DspHeader(
        num_samples,
        num_nibbles,
        rate,
        loop_flag,
        fmt,
        loop_start,
        loop_end,
        coefs,
        pred_scale,
        yn1,
        yn2,
    )


def decode(
    data: bytes, header: DspHeader | None = None, max_samples: int | None = None
) -> list[int]:
    """Decode a .dsp file (header + frames) to 16-bit samples."""
    h = header or parse_header(data)
    out: list[int] = []
    hist1, hist2 = h.yn1, h.yn2
    want = h.num_samples if max_samples is None else min(h.num_samples, max_samples)
    pos = h.data_offset
    coefs = h.coefs
    while len(out) < want and pos + 8 <= len(data):
        frame = data[pos : pos + 8]
        pos += 8
        scale = 1 << (frame[0] & 0xF)
        idx = (frame[0] >> 4) & 7
        c0, c1 = coefs[2 * idx], coefs[2 * idx + 1]
        for i in range(14):
            byte = frame[1 + i // 2]
            nib = (byte >> 4) if (i & 1) == 0 else (byte & 0xF)
            if nib >= 8:
                nib -= 16
            s = (((nib * scale) << 11) + 1024 + c0 * hist1 + c1 * hist2) >> 11
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            out.append(s)
            hist2, hist1 = hist1, s
            if len(out) >= want:
                break
    return out
