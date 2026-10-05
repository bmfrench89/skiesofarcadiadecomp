/*
 * SHA-1 (sha1.h). Moved out of mod.c by disc-layer I1, unchanged, so the disc
 * and the mods hash an executable the same way.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "sha1.h"
#include <stdio.h>
#include <string.h>

static uint32_t rol(uint32_t x, int k) { return (x << k) | (x >> (32 - k)); }

static void sha1_block(uint32_t h[5], const uint8_t* p)
{
    uint32_t w[80], a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f, k, t;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    for (i = 0; i < 80; i++) {
        if (i < 20) { f = (b & c) | (~b & d); k = 0x5A827999u; }
        else if (i < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1u; }
        else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDCu; }
        else { f = b ^ c ^ d; k = 0xCA62C1D6u; }
        t = rol(a, 5) + f + e + k + w[i];
        e = d; d = c; c = rol(b, 30); b = a; a = t;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e;
}

void sha1(const uint8_t* data, size_t n, uint8_t digest[20])
{
    uint32_t h[5] = {0x67452301u, 0xEFCDAB89u, 0x98BADCFEu, 0x10325476u, 0xC3D2E1F0u};
    uint8_t last[128];
    size_t i, rem = n % 64, full = n - rem, pad = rem < 56 ? 64 : 128;
    uint64_t bits = (uint64_t)n * 8;
    for (i = 0; i < full; i += 64) sha1_block(h, data + i);
    memset(last, 0, sizeof last);
    if (rem) memcpy(last, data + full, rem);
    last[rem] = 0x80;
    for (i = 0; i < 8; i++) last[pad - 1 - i] = (uint8_t)(bits >> (8 * i));
    sha1_block(h, last);
    if (pad == 128) sha1_block(h, last + 64);
    for (i = 0; i < 20; i++) digest[i] = (uint8_t)(h[i / 4] >> (24 - 8 * (i % 4)));
}

void sha1_hex(const uint8_t* data, size_t n, char hex[41])
{
    uint8_t d[20];
    int i;
    sha1(data, n, d);
    for (i = 0; i < 20; i++) snprintf(hex + 2 * i, 3, "%02x", d[i]);
}
