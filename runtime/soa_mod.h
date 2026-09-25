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
 * end: a mod built against version N runs on a port at N or later, and checks
 * `api->size` before touching a member added after the version it knows.
 *
 * Everything here runs on the guest CPU thread, the one thread allowed to
 * touch guest state. Never call the API from a thread of your own.
 */
#ifndef SOA_MOD_API_H
#define SOA_MOD_API_H

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

/* One controller read, as si.c holds it (for pad_filter, M3b). */
typedef struct SoaPad {
    uint16_t buttons;  /* SOA_PAD_* */
    uint8_t stick[2];  /* 128 is centre */
    uint8_t cstick[2];
    uint8_t trig[2];
} SoaPad;

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
     * when its table is full. */
    int (*on_frame_end)(void (*fn)(void* user), void* user);   /* inside the XFB copy: memory writes only */
    int (*on_safe_point)(void (*fn)(void* user), void* user);  /* the top of the main loop, nothing started */
    int (*on_map_loaded)(void (*fn)(void* user, uint32_t map), void* user);  /* at a safe point, once per map entered */
    int (*on_scene_change)(void (*fn)(void* user, uint32_t from, uint32_t to), void* user);  /* at a safe point */

    /* One line to the port's log, prefixed with the mod's folder name. */
    void (*log)(const char* line);
} SoaModApi;

typedef int (*SoaModInit)(const SoaModApi* api, uint32_t version);

#endif
