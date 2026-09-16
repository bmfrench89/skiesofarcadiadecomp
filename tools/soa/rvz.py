"""RVZ container decoder (Dolphin compressed disc format).

Decodes RVZ directly so the pipeline has no dependency on a Dolphin install.
See docs/FINDINGS.md section 1 for the two format details that matter:
groups tile from the chunk-aligned base, and junk runs carry a 68-byte seed.

Junk runs are zero-filled rather than regenerated (slice 0.5). This affects
inter-file padding only -- the DOL, FST and all real file data decode exactly.
"""

import struct
from compression import zstd


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
            out = self._unpack(data) if packed else data
        out = out.ljust(self.chunk, b"\0")
        if len(self.cache) < 64:
            self.cache[idx] = out
        return out

    def _unpack(self, d):
        # RVZ run encoding: u32 size (bit31 => junk run, followed by 4-byte seed)
        out = bytearray()
        p = 0
        while p + 4 <= len(d):
            (sz,) = struct.unpack(">I", d[p : p + 4])
            p += 4
            junk = sz & 0x80000000
            sz &= 0x7FFFFFFF
            if junk:
                p += 68  # LFG seed = 17 u32
                out += b"\0" * sz  # junk = padding; irrelevant for real files
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
