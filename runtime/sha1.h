/*
 * SHA-1, for the two places the port names an executable by its hash: a
 * mod's dol_sha1 (mod.c) and the disc image's DOL (disc.c, disc-layer I1).
 * FIPS 180-4; tools/tests/test_mods.py holds it to hashlib.
 */
#ifndef SOA_SHA1_H
#define SOA_SHA1_H

#include <stddef.h>
#include <stdint.h>

void sha1(const uint8_t* data, size_t n, uint8_t digest[20]);
/* The digest as 40 lowercase hex digits and a NUL. */
void sha1_hex(const uint8_t* data, size_t n, char hex[41]);

#endif
