"""DSP-ADPCM decoding against hand-computed frames (no disc needed)."""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from soa import dspadpcm  # noqa: E402


def make_header(num_samples, coefs, rate=32000):
    h = bytearray(0x60)
    struct.pack_into(">III", h, 0, num_samples, num_samples * 8 // 7, rate)
    struct.pack_into(">16h", h, 0x1C, *coefs)
    return bytes(h)


def test_header_fields():
    h = dspadpcm.parse_header(make_header(140, [1] * 16, rate=22050))
    assert h.num_samples == 140 and h.sample_rate == 22050 and h.coefs[0] == 1


def test_frame_without_prediction_scales_nibbles():
    """Coefficients zero: each sample is nibble << scale (scale 4 here)."""
    coefs = [0] * 16
    frame = bytes([0x04, 0x17, 0xF8, 0x00, 0x00, 0x00, 0x00, 0x00])  # nibbles 1,7,-1,-8,0...
    data = make_header(14, coefs) + frame
    s = dspadpcm.decode(data)
    assert s[:4] == [1 << 4, 7 << 4, -1 << 4, -8 << 4]
    assert s[4:] == [0] * 10


def test_prediction_uses_history():
    """c0 = 2048 (1.0 in 4.11 fixed point): s[n] = nibble<<scale + s[n-1]."""
    coefs = [2048, 0] + [0] * 14
    frame = bytes([0x00, 0x11, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00])  # nibbles 1,1,1,1,0...
    data = make_header(14, coefs) + frame
    s = dspadpcm.decode(data)
    assert s[:6] == [1, 2, 3, 4, 4, 4]


def test_clamps_to_16_bit():
    coefs = [0] * 16
    frame = bytes([0x0F, 0x77, 0x88, 0x00, 0x00, 0x00, 0x00, 0x00])  # 7<<15 and -8<<15
    s = dspadpcm.decode(make_header(14, coefs) + frame)
    assert s[0] == 32767 and s[2] == -32768
