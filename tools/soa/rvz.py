"""RVZ container decoder (Dolphin compressed disc format).

Decodes RVZ directly so the pipeline has no dependency on a Dolphin install.
See docs/FINDINGS.md section 1 for the two format details that matter:
groups tile from the chunk-aligned base, and junk runs carry a 68-byte seed.

Junk runs (the pseudo-random padding a GameCube disc carries between files)
are regenerated from their 68-byte seed with the same lagged Fibonacci
generator the disc mastering used, so a read past a file's end returns what
the drive would return, not zeros (slice 0.5).
"""

import struct
from compression import zstd

# ---- junk generator ---------------------------------------------------------
# A lagged Fibonacci generator over 521 words with lag 32. RVZ stores the 17
# seed words of every junk run; the stream position within the run is the run's
# disc offset modulo the 32 KiB sector. Algorithm after Dolphin's
# DiscIO/LaggedFibonacciGenerator (CC0).

LFG_K = 521
LFG_J = 32
LFG_SEED_WORDS = 17
LFG_BYTES = LFG_K * 4


def _lfg_forward(buf):
    for i in range(LFG_J):
        buf[i] ^= buf[i + LFG_K - LFG_J]
    for i in range(LFG_J, LFG_K):
        buf[i] ^= buf[i - LFG_J]


class JunkGenerator:
    """Yields the padding bytes for one junk run."""

    def __init__(self, seed):
        words = list(struct.unpack(">17I", seed[: LFG_SEED_WORDS * 4]))
        buf = words + [0] * (LFG_K - LFG_SEED_WORDS)
        for i in range(LFG_SEED_WORDS, LFG_K):
            buf[i] = ((buf[i - 17] << 23) ^ (buf[i - 16] >> 9) ^ buf[i - 1]) & 0xFFFFFFFF
        # The hardware shifts by 18 rather than 16 when emitting; fold that in once.
        self.buf = [(x & 0xFF00FFFF) | ((x >> 2) & 0x00FF0000) for x in buf]
        for _ in range(4):
            _lfg_forward(self.buf)
        self.pos = 0  # byte position within the current 2084-byte block

    def skip(self, count):
        self.pos += count
        while self.pos >= LFG_BYTES:
            _lfg_forward(self.buf)
            self.pos -= LFG_BYTES

    def get(self, count):
        out = bytearray()
        while count > 0:
            block = struct.pack(">521I", *self.buf)
            take = min(count, LFG_BYTES - self.pos)
            out += block[self.pos : self.pos + take]
            self.pos += take
            count -= take
            if self.pos == LFG_BYTES:
                _lfg_forward(self.buf)
                self.pos = 0
        return bytes(out)


def junk_bytes(seed, disc_offset, count):
    """The junk a disc holds at ``disc_offset`` for a run with this seed."""
    g = JunkGenerator(seed)
    g.skip(disc_offset % 0x8000)
    return g.get(count)


class RVZ:
    def __init__(self, path):
        # held open for the object's lifetime: reads are random-access and lazy
        self.f = open(path, "rb")  # noqa: SIM115
        h1 = self.f.read(0x48)
        assert h1[:4] == b"RVZ\x01", "not RVZ"
        h2size = struct.unpack(">I", h1[0x0C:0x10])[0]
        self.iso_size = struct.unpack(">Q", h1[0x24:0x2C])[0]
        h2 = self.f.read(h2size)
        self.disc_type, self.ctype, self.clevel, self.chunk = struct.unpack(">IIiI", h2[:16])
        self.disc_header = h2[0x10:0x90]
        (nrde,) = struct.unpack(">I", h2[0xB4:0xB8])
        (rdeo,) = struct.unpack(">Q", h2[0xB8:0xC0])
        (rdes,) = struct.unpack(">I", h2[0xC0:0xC4])
        (nge,) = struct.unpack(">I", h2[0xC4:0xC8])
        (geo,) = struct.unpack(">Q", h2[0xC8:0xD0])
        (ges,) = struct.unpack(">I", h2[0xD0:0xD4])
        self.raw = self._table(rdeo, rdes, nrde, 24, ">QQII")
        gt = self._blob(geo, ges)
        self.groups = [struct.unpack(">III", gt[i * 12 : i * 12 + 12]) for i in range(nge)]
        self.cache = {}

    def _blob(self, off, size):
        self.f.seek(off)
        return zstd.decompress(self.f.read(size))

    def _table(self, off, size, n, esz, fmt):
        b = self._blob(off, size)
        return [struct.unpack(fmt, b[i * esz : (i + 1) * esz]) for i in range(n)]

    def group(self, idx):
        if idx in self.cache:
            return self.cache[idx]
        doff, dsize, packed = self.groups[idx]
        comp = bool(dsize & 0x80000000)
        dsize &= 0x7FFFFFFF
        if dsize == 0:
            out = b"\0" * self.chunk
        else:
            self.f.seek(doff * 4)
            raw = self.f.read(dsize)
            data = zstd.decompress(raw) if comp else raw
            out = self._unpack(data, self.group_disc_offset(idx)) if packed else data
        out = out.ljust(self.chunk, b"\0")
        if len(self.cache) < 64:
            self.cache[idx] = out
        return out

    def group_disc_offset(self, idx):
        """Disc offset of the first byte a group decodes to."""
        base, size, gidx, ngroups = self.raw[0]
        return base - (base % self.chunk) + (idx - gidx) * self.chunk

    def _unpack(self, d, disc_offset):
        # RVZ run encoding: u32 size (bit 31 => junk run, followed by the 68-byte seed)
        out = bytearray()
        p = 0
        while p + 4 <= len(d):
            (sz,) = struct.unpack(">I", d[p : p + 4])
            p += 4
            junk = sz & 0x80000000
            sz &= 0x7FFFFFFF
            if junk:
                out += junk_bytes(d[p : p + 68], disc_offset + len(out), sz)
                p += 68
            else:
                out += d[p : p + sz]
                p += sz
        return bytes(out)

    def read(self, offset, length):
        # disc[0:0x80] is stored verbatim in header2; the rest is grouped
        base, size, gidx, ngroups = self.raw[0]
        out = bytearray()
        end = offset + length
        gbase = base - (base % self.chunk)  # groups tile from chunk-aligned start
        while offset < end:
            rel = offset - gbase
            g = gidx + rel // self.chunk
            o = rel % self.chunk
            take = min(self.chunk - o, end - offset)
            out += self.group(g)[o : o + take]
            offset += take
        return bytes(out)
