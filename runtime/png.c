/* Minimal PNG writer: RGBA8, uncompressed deflate (stored blocks). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

static uint32_t crc_table[256];

static void crc_init(void)
{
    uint32_t n, k;
    if (crc_table[1]) return;
    for (n = 0; n < 256; n++) {
        uint32_t c = n;
        for (k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        crc_table[n] = c;
    }
}

static uint32_t crc32_update(uint32_t c, const uint8_t* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) c = crc_table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c;
}

static void put32(FILE* f, uint32_t v)
{
    uint8_t b[4] = {(uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
    fwrite(b, 1, 4, f);
}

static void chunk(FILE* f, const char* type, const uint8_t* data, size_t len)
{
    uint32_t c;
    put32(f, (uint32_t)len);
    fwrite(type, 1, 4, f);
    if (len) fwrite(data, 1, len, f);
    c = crc32_update(0xFFFFFFFFu, (const uint8_t*)type, 4);
    if (len) c = crc32_update(c, data, len);
    put32(f, c ^ 0xFFFFFFFFu);
}

int png_write_rgba(const char* path, const uint8_t* rgba, int w, int h, int stride)
{
    FILE* f;
    size_t raw_len = (size_t)h * (1 + (size_t)w * 4);
    uint8_t* raw = (uint8_t*)malloc(raw_len);
    size_t nblocks = (raw_len + 65534) / 65535;
    size_t zlen = 2 + raw_len + nblocks * 5 + 4;
    uint8_t* z = (uint8_t*)malloc(zlen);
    size_t i, off, zo = 0;
    uint32_t a = 1, b = 0;
    uint8_t ihdr[13];
    static const uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};

    if (!raw || !z) return 0;
    crc_init();
    for (i = 0; i < (size_t)h; i++) {
        raw[i * (1 + (size_t)w * 4)] = 0; /* filter: none */
        memcpy(raw + i * (1 + (size_t)w * 4) + 1, rgba + i * (size_t)stride, (size_t)w * 4);
    }
    for (i = 0; i < raw_len; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }

    z[zo++] = 0x78; z[zo++] = 0x01;
    for (off = 0; off < raw_len || (off == 0 && raw_len == 0); off += 65535) {
        size_t n = raw_len - off < 65535 ? raw_len - off : 65535;
        int last = off + n >= raw_len;
        z[zo++] = (uint8_t)last;
        z[zo++] = (uint8_t)n; z[zo++] = (uint8_t)(n >> 8);
        z[zo++] = (uint8_t)~n; z[zo++] = (uint8_t)(~n >> 8);
        memcpy(z + zo, raw + off, n);
        zo += n;
        if (raw_len == 0) break;
    }
    z[zo++] = (uint8_t)(b >> 8); z[zo++] = (uint8_t)b; z[zo++] = (uint8_t)(a >> 8); z[zo++] = (uint8_t)a;

    f = fopen(path, "wb");
    if (!f) { free(raw); free(z); return 0; }
    fwrite(sig, 1, 8, f);
    ihdr[0] = (uint8_t)(w >> 24); ihdr[1] = (uint8_t)(w >> 16); ihdr[2] = (uint8_t)(w >> 8); ihdr[3] = (uint8_t)w;
    ihdr[4] = (uint8_t)(h >> 24); ihdr[5] = (uint8_t)(h >> 16); ihdr[6] = (uint8_t)(h >> 8); ihdr[7] = (uint8_t)h;
    ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
    chunk(f, "IHDR", ihdr, 13);
    chunk(f, "IDAT", z, zo);
    chunk(f, "IEND", NULL, 0);
    fclose(f);
    free(raw);
    free(z);
    return 1;
}
