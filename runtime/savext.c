/*
 * X2, the save extension (docs/specs/save-extension.md): each mod's chunk of
 * its own inside the game's save file, the chunks of mods not loaded carried
 * through every save, and a word at each load about the ones missing.
 *
 * The game's save file is 24,576 bytes: its 12,800-byte block at +5184, and
 * nothing after +17,984. The block comes zeroed from memCalloc, and its bytes
 * +5916..+9071 are never written by the game nor read back, yet sit inside
 * the XOR the game checks (beyond-gamecube.md 3.2). So:
 *   - at the snapshot (hooks.txt 0x801A4670, r31 the block, before the XOR)
 *     the container goes into that gap, header and whole chunks, as many as
 *     fit, and the game's own check then covers it;
 *   - at the image (hooks.txt 0x801A4334, the image at *(r31 + 0), the block
 *     copied to +5184 after its XOR) the rest goes into the file's tail;
 *   - at the load (hle.txt fn_801A4354, r3 the block inside its image) the
 *     original restores the game, then each mod gets its chunk;
 *   - at New Game and boot (hle.txt fn_801CAF30) each mod is told.
 *
 * Big-endian throughout, as the rest of the file; tools/savext.py reads the
 * same layout.
 *   gap  +0 'SOAX', +4 u16 version, +6 u16 chunks here, +8 u16 chunks in the
 *        tail, +10 u16 0, +12 the save's id (16 bytes), +28 u32 CRC-32 of the
 *        chunks here, +32 u32 their length, +36 the chunks
 *   tail +0 'SOAT', +4 u16 version, +6 u16 chunks, +8 the save's id, +24 u32
 *        CRC-32, +28 u32 length, +32 the chunks
 *   a chunk: u8 id length (1-31), the id, u32 length, the bytes
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include "mod.h"
#include "plat.h"
#include "sha1.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BLOCK_LEN 12800u
#define BLOCK_IN_IMAGE 5184u
#define GAP_OFF 5916u /* in the block */
#define GAP_LEN 3156u
#define TAIL_OFF 17984u /* in the image */
#define TAIL_LEN 6592u
#define GAP_HEAD 36u
#define TAIL_HEAD 32u
#define VERSION 1u
#define ID_MAX 31u
#define KEPT_MAX (GAP_LEN + TAIL_LEN)
#define CLAIMS_ID "soa.claims" /* T2's table; no mod's id begins soa. */

int mod_loaded(const char* id); /* mod.c */

static int g_log;
static unsigned long long g_calls[4], g_written[4]; /* snapshot, image, load, new game */
static const char* const k_site[4] = {"snapshot", "image", "load", "new game"};

/* The save's id and what waits for the tail: set at the snapshot, written at
 * the image (a menu may be cancelled between them, and the next snapshot
 * starts again). */
static uint8_t g_id[16];
static uint8_t g_tail[TAIL_LEN];
static uint32_t g_tail_len, g_tail_chunks;
static int g_tail_armed;

/* The chunks of the last save loaded that no loaded mod saves for itself:
 * written back at every save until a New Game. */
static uint8_t g_kept[KEPT_MAX];
static uint32_t g_kept_len;

static uint32_t crc32(const uint8_t* p, uint32_t n)
{
    uint32_t c = 0xFFFFFFFFu, i;
    int k;
    for (i = 0; i < n; i++) {
        c ^= p[i];
        for (k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static void put16(uint8_t* p, uint32_t v) { p[0] = (uint8_t)(v >> 8), p[1] = (uint8_t)v; }
static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24), p[1] = (uint8_t)(v >> 16), p[2] = (uint8_t)(v >> 8), p[3] = (uint8_t)v;
}
static uint32_t get16(const uint8_t* p) { return (uint32_t)p[0] << 8 | p[1]; }
static uint32_t get32(const uint8_t* p) { return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }

/* The chunk at p within [p, end): its id, data and size; 0 if it runs off. */
static int chunk_at(const uint8_t* p, const uint8_t* end, char id[ID_MAX + 1], const uint8_t** data, uint32_t* size,
                    const uint8_t** next)
{
    uint32_t n;
    if (p >= end) return 0;
    n = p[0];
    if (n == 0 || n > ID_MAX || (size_t)(end - p) < 1u + n + 4u) return 0;
    memcpy(id, p + 1, n);
    id[n] = '\0';
    *size = get32(p + 1 + n);
    if ((size_t)(end - p) - 1u - n - 4u < *size) return 0;
    *data = p + 1 + n + 4;
    *next = *data + *size;
    return 1;
}

static uint32_t chunk_put(uint8_t* out, const char* id, const uint8_t* data, uint32_t size)
{
    uint32_t n = (uint32_t)strlen(id);
    out[0] = (uint8_t)n;
    memcpy(out + 1, id, n);
    put32(out + 1 + n, size);
    if (size) memcpy(out + 1 + n + 4, data, size);
    return 1 + n + 4 + size;
}

static int saves_for_itself(const char* id)
{
    int i;
    for (i = 0; i < mod_event_count(MOD_EV_SAVE); i++)
        if (!strcmp(mod_save_id(MOD_EV_SAVE, i), id)) return 1;
    return 0;
}

/* The kept chunk for id, if any. */
static int kept_chunk(const char* id, const uint8_t** data, uint32_t* size)
{
    const uint8_t *p = g_kept, *end = g_kept + g_kept_len, *next;
    char cid[ID_MAX + 1];
    while (chunk_at(p, end, cid, data, size, &next)) {
        if (!strcmp(cid, id)) return 1;
        p = next;
    }
    return 0;
}

static void new_id(void)
{
    static uint64_t x;
    int i;
    x ^= plat_mono_ns() * 0x9E3779B97F4A7C15ull + (uintptr_t)&x;
    for (i = 0; i < 16; i++) {
        x ^= x << 13, x ^= x >> 7, x ^= x << 17;
        g_id[i] = (uint8_t)(x >> 24);
    }
}

/* The snapshot, r31 the block: every chunk, the gap's whole ones in order and
 * the rest held for the image. */
void savext_snapshot(CpuState* s, uint32_t block)
{
    static uint8_t all[KEPT_MAX];
    uint8_t* gap = mem_ptr(s, block + GAP_OFF);
    uint32_t used = 0, gap_len = 0, gap_chunks = 0, i;
    const uint8_t *p, *end, *next, *data;
    char id[ID_MAX + 1];
    uint32_t size;
    int n = mod_event_count(MOD_EV_SAVE), k;
    g_calls[0]++;
    g_tail_armed = 0;
    g_tail_len = g_tail_chunks = 0;
    if (!n && !g_kept_len && !mod_claims_count()) return;
    for (i = 0; i < GAP_LEN; i++)
        if (gap[i]) {
            fprintf(stderr, "[save] the block's gap holds a byte the game wrote (+%u): nothing written, so this save "
                            "carries no mod's chunk\n",
                    GAP_OFF + i);
            return;
        }
    new_id();
    /* T2's table first: the numbers this install gave each claim */
    if (mod_claims_count()) {
        static char text[KEPT_MAX];
        uint32_t tn = mod_claims_text(text, KEPT_MAX - (1u + sizeof CLAIMS_ID - 1u + 4u));
        used += chunk_put(all, CLAIMS_ID, (const uint8_t*)text, tn);
    }
    /* each loaded mod's own, then the kept ones it does not replace */
    for (k = 0; k < n; k++) {
        const char* mid = mod_save_id(MOD_EV_SAVE, k);
        uint32_t head = 1u + (uint32_t)strlen(mid) + 4u, room = KEPT_MAX - used;
        static uint8_t buf[KEPT_MAX];
        int32_t got = room > head ? mod_save_call(k, buf, room - head) : -2;
        if (got == -1) continue; /* nothing to keep: its old chunk goes too */
        if (got < 0 || (uint32_t)got > room - head) {
            fprintf(stderr, "[mod] %s: its save chunk does not fit the %u bytes left; the one from the save before is "
                            "carried\n",
                    mid, room > head ? room - head : 0u);
            if (kept_chunk(mid, &data, &size) && used + head + size <= KEPT_MAX) used += chunk_put(all + used, mid, data, size);
            continue;
        }
        used += chunk_put(all + used, mid, buf, (uint32_t)got);
    }
    p = g_kept, end = g_kept + g_kept_len;
    while (chunk_at(p, end, id, &data, &size, &next)) {
        if (!saves_for_itself(id) && used + 1u + strlen(id) + 4u + size <= KEPT_MAX)
            used += chunk_put(all + used, id, data, size);
        p = next;
    }
    if (!used) return;
    /* whole chunks into the gap while they fit, the rest to the tail */
    p = all, end = all + used;
    while (chunk_at(p, end, id, &data, &size, &next) && GAP_HEAD + gap_len + (uint32_t)(next - p) <= GAP_LEN) {
        memcpy(gap + GAP_HEAD + gap_len, p, (size_t)(next - p));
        gap_len += (uint32_t)(next - p);
        gap_chunks++;
        p = next;
    }
    while (chunk_at(p, end, id, &data, &size, &next)) {
        if (TAIL_HEAD + g_tail_len + (uint32_t)(next - p) > TAIL_LEN) {
            fprintf(stderr, "[save] %s's chunk (%u bytes) fits neither the gap nor the tail: not saved\n", id, size);
        } else {
            memcpy(g_tail + TAIL_HEAD + g_tail_len, p, (size_t)(next - p));
            g_tail_len += (uint32_t)(next - p);
            g_tail_chunks++;
        }
        p = next;
    }
    memcpy(gap, "SOAX", 4);
    put16(gap + 4, VERSION);
    put16(gap + 6, gap_chunks);
    put16(gap + 8, g_tail_chunks);
    put16(gap + 10, 0);
    memcpy(gap + 12, g_id, 16);
    put32(gap + 28, crc32(gap + GAP_HEAD, gap_len));
    put32(gap + 32, gap_len);
    g_written[0] += GAP_HEAD + gap_len;
    g_tail_armed = g_tail_chunks > 0;
    if (g_log)
        fprintf(stderr, "[save] snapshot: %u chunk(s), %u bytes in the gap, %u chunk(s), %u bytes held for the tail\n",
                gap_chunks, GAP_HEAD + gap_len, g_tail_chunks, g_tail_len);
}

/* The image, built and holding the block's copy: the tail, and the hashes. */
void savext_image(CpuState* s, uint32_t image)
{
    g_calls[1]++;
    if (g_tail_armed) {
        uint8_t* tail = g_tail;
        memcpy(tail, "SOAT", 4);
        put16(tail + 4, VERSION);
        put16(tail + 6, g_tail_chunks);
        memcpy(tail + 8, g_id, 16);
        put32(tail + 24, crc32(tail + TAIL_HEAD, g_tail_len));
        put32(tail + 28, g_tail_len);
        memcpy(mem_ptr(s, image + TAIL_OFF), tail, TAIL_HEAD + g_tail_len);
        g_written[1] += TAIL_HEAD + g_tail_len;
        g_tail_armed = 0;
    }
    if (g_log) {
        char block[41], file[41];
        sha1_hex(mem_ptr(s, image + BLOCK_IN_IMAGE), BLOCK_LEN, block);
        sha1_hex(mem_ptr(s, image), TAIL_OFF + TAIL_LEN, file);
        fprintf(stderr, "[save] image at %08X: block sha1 %s, file sha1 %s\n", image, block, file);
    }
}

/* A save loaded, the game's half done: each mod's chunk, the rest kept. */
void savext_load(CpuState* s, uint32_t block)
{
    static uint8_t got[KEPT_MAX];
    const uint8_t* gap = mem_ptr(s, block + GAP_OFF);
    const uint8_t* tail = mem_ptr(s, block - BLOCK_IN_IMAGE + TAIL_OFF);
    uint32_t len = 0, gap_len, tail_len, kept = 0;
    int claims_seen = 0;
    const uint8_t *p, *end, *next, *data;
    char id[ID_MAX + 1];
    uint32_t size;
    int i, n = mod_event_count(MOD_EV_LOAD);
    g_calls[2]++;
    g_kept_len = 0;
    if (!memcmp(gap, "SOAX", 4)) {
        gap_len = get32(gap + 32);
        if (get16(gap + 4) != VERSION || gap_len > GAP_LEN - GAP_HEAD || crc32(gap + GAP_HEAD, gap_len) != get32(gap + 28)) {
            fprintf(stderr, "[save] this save's mod container is damaged (its version, length or CRC): ignored, and the "
                            "save loads as the game's alone\n");
        } else {
            memcpy(got, gap + GAP_HEAD, gap_len);
            len = gap_len;
            if (get16(gap + 8)) {
                tail_len = get32(tail + 28);
                if (memcmp(tail, "SOAT", 4) || memcmp(tail + 8, gap + 12, 16) || tail_len > TAIL_LEN - TAIL_HEAD ||
                    crc32(tail + TAIL_HEAD, tail_len) != get32(tail + 24)) {
                    fprintf(stderr, "[save] this save's mod container names %u chunk(s) in the file's tail, and the "
                                    "tail does not hold them: those are lost\n",
                            get16(gap + 8));
                } else {
                    memcpy(got + len, tail + TAIL_HEAD, tail_len);
                    len += tail_len;
                }
            }
        }
    }
    /* each loaded mod with on_load gets its chunk, or none */
    for (i = 0; i < n; i++) {
        const char* mid = mod_save_id(MOD_EV_LOAD, i);
        const uint8_t* mine = NULL;
        uint32_t mine_n = 0;
        p = got, end = got + len;
        while (chunk_at(p, end, id, &data, &size, &next)) {
            if (!strcmp(id, mid)) mine = data, mine_n = size;
            p = next;
        }
        mod_load_call(i, mine, mine_n);
    }
    /* T2's table checked, the rest kept, and the ones whose mod is not loaded said */
    p = got, end = got + len;
    while (chunk_at(p, end, id, &data, &size, &next)) {
        if (!strcmp(id, CLAIMS_ID)) {
            claims_seen = 1;
            mod_claims_check(data, size);
        } else if (!saves_for_itself(id)) {
            memcpy(g_kept + g_kept_len, p, (size_t)(next - p));
            g_kept_len += (uint32_t)(next - p);
            kept++;
            if (!mod_loaded(id))
                fprintf(stderr, "[mod] this save holds data for %s, which is not loaded: kept, and written back at the "
                                "next save\n",
                        id);
        }
        p = next;
    }
    if (!claims_seen && mod_claims_count())
        fprintf(stderr, "[mod] this save names no claims (made without mods that claim numbers, or saved again by the "
                        "game alone): this install's mods.lock stands\n");
    if (g_log)
        fprintf(stderr, "[save] load of the block at %08X: %u bytes of chunks, %u kept for the next save\n", block, len,
                kept);
}

void savext_new_game(void)
{
    g_calls[3]++;
    g_kept_len = 0;
    mod_new_game();
    if (g_log) fprintf(stderr, "[save] new game (or boot): the kept chunks dropped\n");
}

#ifndef SOA_FAKE_GUEST
void recomp_fn_801A4354(CpuState* s);
void recomp_fn_801CAF30(CpuState* s);
void hle_on_report(void (*fn)(void));

void hook_801A4670(CpuState* s) { savext_snapshot(s, s->gpr[31]); }

void hook_801A4334(CpuState* s) { savext_image(s, mem_r32(s, s->gpr[31])); }

void fn_801A4354(CpuState* s)
{
    s->pc = 0x801A4354u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    uint32_t block = s->gpr[3];
    recomp_fn_801A4354(s);
    savext_load(s, block);
}

void fn_801CAF30(CpuState* s)
{
    s->pc = 0x801CAF30u; /* first, as the translation's block head does: a sample in here names it (test_hle_pc) */
    recomp_fn_801CAF30(s);
    savext_new_game();
}

static void savext_report(void)
{
    int i;
    for (i = 0; i < 4; i++)
        fprintf(stderr, "[save] site %s: %llu call(s), %llu byte(s) written%s\n", k_site[i], g_calls[i], g_written[i],
                g_calls[i] ? "" : " -- never called: this run did not test it");
}

void savext_init(void)
{
    const char* log = getenv("SOA_SAVE_LOG");
    g_log = log && atoi(log) ? 1 : 0;
    if (g_log || mod_event_count(MOD_EV_SAVE) || mod_event_count(MOD_EV_LOAD)) hle_on_report(savext_report);
}
#endif
