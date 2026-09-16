"""Does the port play a music stream the way the disc holds it?

    python tools/audio_check.py build/opening.wav extracted/sound/m01_L.dsp [--seconds 6]

Decodes the DSP-ADPCM stream, resamples it to the WAV's rate, and slides a
few seconds of it over the recording (FFT cross-correlation) to find where
it plays and how well it matches. A clear peak with a high normalised
correlation means the ADPCM decode, the sample-rate conversion and the
stream's timing are right; the game mixes voices and effects over the music,
so the coefficient is never 1.0. Analysis only; prints numbers.
"""

from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soa import dspadpcm  # noqa: E402


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
        ch = w.getnchannels()
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if ch == 2:
        pcm = pcm.reshape(-1, 2)
    return pcm, rate


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    n = int(len(x) * dst / src)
    t = np.arange(n) * (src / dst)
    return np.interp(t, np.arange(len(x)), x)


def best_offset(hay: np.ndarray, needle: np.ndarray) -> tuple[int, float]:
    """Offset of the needle in the haystack and the normalised correlation there."""
    n = len(hay) + len(needle)
    size = 1 << (n - 1).bit_length()
    H = np.fft.rfft(hay, size)
    N = np.fft.rfft(needle[::-1], size)
    corr = np.fft.irfft(H * N, size)[: len(hay)]
    off = int(np.argmax(corr)) - len(needle) + 1
    if off < 0:
        off = 0
    seg = hay[off : off + len(needle)]
    if len(seg) < len(needle):
        return off, 0.0
    denom = np.linalg.norm(seg) * np.linalg.norm(needle)
    return off, float(np.dot(seg, needle) / denom) if denom else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav", type=Path)
    ap.add_argument("dsp", type=Path, help="one channel's .dsp (the _L or _R file)")
    ap.add_argument("--seconds", type=float, default=6.0, help="length of the excerpt to match")
    ap.add_argument("--start", type=float, default=5.0, help="where in the stream the excerpt starts")
    args = ap.parse_args()

    pcm, rate = read_wav(args.wav)
    chan = 0 if args.dsp.stem.lower().endswith("_l") else 1
    hay = pcm[:, chan] if pcm.ndim == 2 else pcm

    data = args.dsp.read_bytes()
    h = dspadpcm.parse_header(data)
    want = int((args.start + args.seconds) * h.sample_rate)
    stream = np.array(dspadpcm.decode(data, h, max_samples=want), dtype=np.float64)
    stream = resample(stream, h.sample_rate, rate)
    a = int(args.start * rate)
    needle = stream[a : a + int(args.seconds * rate)]
    needle = needle - needle.mean()
    hay0 = hay - hay.mean()

    off, coef = best_offset(hay0, needle)
    print(f"stream: {h.sample_rate} Hz, {h.num_samples / h.sample_rate:.1f} s; recording: {rate} Hz, {len(hay) / rate:.1f} s")
    print(f"best match at {off / rate:.2f} s into the recording (stream time {args.start:.1f} s): correlation {coef:.3f}")
    print("verdict:", "the stream plays as the disc holds it" if coef > 0.5 else
          "weak match -- pitch, decode or timing differ" if coef > 0.15 else "no match")
    return 0 if coef > 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
