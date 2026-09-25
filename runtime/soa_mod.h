/*
 * The native mod API (docs/PLAN-60FPS-MODS.md M3). Include this, build a DLL
 * that exports
 *
 *     __declspec(dllexport) int soa_mod_init(const SoaModApi* api, uint32_t version);
 *
 * and put it beside the mod's mod.ini as mod.dll. The port calls it once, after
 * the DOL is loaded and before the game's first instruction, with the API it
 * speaks: `version` is SOA_MOD_API_VERSION as the port was built, `api->size`
 * the size of the table it filled. Return 0 to load, anything else to refuse
 * yourself (say why with api->log first).
 *
 * The table holds plain data and function pointers only, and grows only at the
 * end: a mod built against version N runs on a port at N or later. Check that
 * the table reaches the last member you use, not that it is as large as the one
 * you built against -- an older port that has every member you call is fine:
 *
 *     if (api->size < SOA_MOD_HAS(pad_filter)) return 1;  // needs M3b's filter
 *
 * Register every callback inside soa_mod_init. Registration closes when it
 * returns, and a later registration returns 0 and is never called.
 *
 * Everything here runs on the guest CPU thread, the one thread allowed to
 * touch guest state. Never call the API from a thread of your own.
 */
#ifndef SOA_MOD_API_H
#define SOA_MOD_API_H

#include <stddef.h>
#include <stdint.h>

#define SOA_MOD_API_VERSION 1u

/* Button bits, as si.c packs them. */
#define SOA_PAD_LEFT 0x0001u
#define SOA_PAD_RIGHT 0x0002u
#define SOA_PAD_DOWN 0x0004u
#define SOA_PAD_UP 0x0008u
#define SOA_PAD_Z 0x0010u
#define SOA_PAD_R 0x0020u
#define SOA_PAD_L 0x0040u
#define SOA_PAD_A 0x0100u
#define SOA_PAD_B 0x0200u
#define SOA_PAD_X 0x0400u
#define SOA_PAD_Y 0x0800u
#define SOA_PAD_START 0x1000u

/* One controller read, laid out as si.c's PadState (for pad_filter, M3b). */
typedef struct SoaPad {
    uint16_t buttons;  /* SOA_PAD_* */
    uint8_t stick[2];  /* 128 is centre */
    uint8_t cstick[2];
    uint8_t trig[2];
} SoaPad;

/* An image a mod hands back: RGBA8, rows top to bottom, w * h * 4 bytes. */
typedef struct SoaImage {
    uint32_t w, h;
    const uint8_t* rgba;
} SoaImage;

typedef struct SoaModApi {
    uint32_t size;    /* sizeof(SoaModApi) as the port built it */
    uint32_t version; /* SOA_MOD_API_VERSION the port speaks */

    /* Guest memory, big-endian as the console keeps it. Each returns 1, or 0
     * when the address is refused: outside the 24 MB of RAM, in the hardware
     * window, not aligned to its width, or -- for writes -- inside the game's
     * code. The same refusals as a patches.txt line, made at the call. */
    int (*read8)(uint32_t addr, uint8_t* out);
    int (*read16)(uint32_t addr, uint16_t* out);
    int (*read32)(uint32_t addr, uint32_t* out);
    int (*read_f32)(uint32_t addr, float* out);
    int (*read_bytes)(uint32_t addr, void* out, uint32_t n);
    int (*write8)(uint32_t addr, uint8_t v);
    int (*write16)(uint32_t addr, uint16_t v);
    int (*write32)(uint32_t addr, uint32_t v);
    int (*write_f32)(uint32_t addr, float v);
    int (*write_bytes)(uint32_t addr, const void* in, uint32_t n);

    /* The game's state words, read now. */
    uint32_t (*scene)(void);         /* 0x803475CC: 6 is the field, 7 battle */
    uint32_t (*field_state)(void);   /* 0x80311AEC: 8 is the field running */
    uint32_t (*map)(void);           /* the committed map: number << 8 | letter, 116 'a' is 0x7461 */
    int (*story_flag)(uint32_t n);   /* flag n: bit n % 32 of the word at 0x80310B3C + n / 32 * 4 */
    uint32_t (*frame)(void);         /* frames the port has presented */

    /* Callbacks, each with a pointer handed back to it. Each returns 1, or 0
     * when its table is full or soa_mod_init has already returned. */
    int (*on_frame_end)(void (*fn)(void* user), void* user);   /* inside the XFB copy: memory writes only */
    int (*on_safe_point)(void (*fn)(void* user), void* user);  /* the top of the main loop, nothing started */
    int (*on_map_loaded)(void (*fn)(void* user, uint32_t map), void* user);  /* at a safe point, once per map entered */
    int (*on_scene_change)(void (*fn)(void* user, uint32_t from, uint32_t to), void* user);  /* at a safe point */

    /* One line to the port's log, prefixed with the mod's folder name. */
    void (*log)(const char* line);

    /* Appended (M3b): check api->size before using what follows.
     *
     * Every controller read, after the person's input and SOA_PAD's are
     * merged and after SOA_PAD_RECORD has its copy, before the game and the
     * [si] log see it. Change *pad to change what the game reads. A recording
     * holds the input as given, and a replay made with the same mod applies
     * the filter again, so it stays exact. */
    int (*pad_filter)(void (*fn)(void* user, uint32_t frame, SoaPad* pad), void* user);

    /* Appended (M3c). Each time the game sets a new projection
     * (GXSetProjection), before any vertex uses it: p[0..5] as XF 0x1020-0x1025.
     * Perspective: x' = p0 x + p1 z, y' = p2 y + p3 z, z' = p4 z + p5, w' = -z;
     * orthographic: x' = p0 x + p1, y' = p2 y + p3, z' = p4 z + p5. Change p to
     * change the picture -- a wider view scales p[0] -- but what is there to
     * draw is still the game's choice: it culls against its own frustum. */
    int (*projection_filter)(void (*fn)(void* user, float p[6], int orthographic), void* user);

    /* Appended (M3c). Once each time the game's texture is decoded: `hash` is
     * its source bytes (and palette, for the indexed formats), the key the
     * port's cache uses, the same from run to run; `rgba` is the decoded base
     * level, w x h. Return 1 with out->rgba set to replace it with an RGBA8
     * image up to 4096 on a side (the sampler scales by its size over the
     * game's), 0 to keep it. The port copies the image before the call
     * returns. Among mods, the first provider that answers 1 with an image
     * that fits wins; a larger one is refused with a line, and the next
     * provider is asked. */
    int (*texture_provider)(int (*fn)(void* user, uint64_t hash, uint32_t fmt, uint32_t w, uint32_t h,
                                      const uint8_t* rgba, SoaImage* out),
                            void* user);
} SoaModApi;

typedef int (*SoaModInit)(const SoaModApi* api, uint32_t version);

/* The size a table must reach to hold `member`: compare api->size with it. */
#define SOA_MOD_HAS(member) (offsetof(SoaModApi, member) + sizeof(((SoaModApi*)0)->member))

#endif
