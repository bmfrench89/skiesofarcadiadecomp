/*
 * The native mod API (docs/PLAN-60FPS-MODS.md M3). Include this, build a shared
 * library that exports
 *
 *     SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version);
 *
 * and put it beside the mod's mod.ini as mod.dll (Windows) or mod.so
 * (elsewhere, portability L9). The port calls it once, after
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

/* What makes soa_mod_init visible to the loader: additive, with no version
 * change, since a mod built before it spelled the same thing out. */
#if defined(_WIN32)
#define SOA_MOD_EXPORT __declspec(dllexport)
#else
#define SOA_MOD_EXPORT __attribute__((visibility("default")))
#endif

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

/* Host buttons (host_buttons, CH1): the pad's buttons the game never sees. */
#define SOA_HOST_LB 0x1u   /* the left bumper, and the keyboard's Tab */
#define SOA_HOST_VIEW 0x2u /* View (Back) */
#define SOA_HOST_LS 0x4u   /* the left stick's click */
#define SOA_HOST_RS 0x8u   /* the right stick's click */

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

/* A victory's rewards, for on_rewards (R1): what the game is about to pay. */
typedef struct SoaRewards {
    int32_t exp;       /* shared over the living members */
    int32_t gold;      /* written back held to 0-99,999,999 */
    int32_t magic_exp; /* written back held to 0-127 */
} SoaRewards;

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

    /* Appended (M4). Call the game's function at `addr` -- from inside an
     * on_safe_point, on_map_loaded or on_scene_change callback and nowhere
     * else. Up to 8 ints go in r3..r10 and up to 8 floats in f1..f8; the
     * results are r3 and f1 (either pointer may be NULL). Every register
     * comes back as it was, so the frame the game is about to run never sees
     * the call. Returns 1, or 0 with a log line when refused: outside a
     * safe point, inside an interrupt handler, `addr` not the start of a
     * function in this program (the list the port was translated with), or
     * more than 8 of either. The function may sleep the game's thread
     * (OSSleepThread and the like), which is legal between frames: the call
     * returns when that thread runs again. */
    int (*call_guest)(uint32_t addr, const uint32_t* ints, uint32_t n_ints, const double* floats,
                      uint32_t n_floats, uint32_t* r3, double* f1);

    /* Appended (CH1). The host buttons held as of the current controller
     * read, SOA_HOST_* bits: the buttons a person presses for the port or a
     * mod, which never reach the game. 0 while a recording replays, which is
     * the whole input. Not in recordings yet (the event track's). */
    uint32_t (*host_buttons)(void);

    /* Appended (P10a). A second controller, read for mods and never seen by
     * the game: port 2 only for now. Fills *out and returns 1 when something
     * is connected there, 0 otherwise. Meaningful inside pad_filter, which
     * runs at each of the game's controller reads. Not in recordings yet. */
    int (*read_pad)(uint32_t port, SoaPad* out);

    /* Appended (M16). The value of an option this mod declares in its
     * mod.ini (`option = NAME TYPE [DOMAIN] DEFAULT`): what soa.ini or
     * SOA_MOD_OPT set, checked against its domain when the mod loaded, or
     * the default. `option` gives the text, kept for the run -- an int,
     * bool or seed as a decimal; `option_int` gives an int, bool or seed as
     * a number and returns 1, and returns 0 for an enum or a string. NULL
     * and 0 for a name the mod did not declare, and for a call from outside
     * its soa_mod_init and its callbacks (docs/specs/mod-options.md). */
    const char* (*option)(const char* name);
    int (*option_int)(const char* name, int64_t* out);

    /* Appended (R0, docs/specs/battle-harness.md). Every damage the battle
     * works out, at fn_800108EC (the base, the element, and the attacker and
     * target actors as the game passes them): fn gets the value the game, or
     * the mod before it, gave, and returns the one the next sees; the last,
     * held to 0-9999, is what the game gets. In load order. It runs inside
     * the battle's own call on the game's thread: memory reads and writes
     * only, as at a frame end. */
    int (*on_damage)(uint32_t (*fn)(void* user, uint32_t value, uint32_t base, uint32_t attacker, uint32_t target,
                                    uint32_t element),
                     void* user);

    /* Appended (R1, docs/specs/battle-events.md): the battle's other events,
     * each in load order inside the game's own call, as on_damage. Slots are
     * the battle's actor slots, 0-3 the party and 4-11 the enemies; a fault in
     * any of these stops the run and names the mod. This one: each Recover-HP
     * value (fn_8006AE20), returning the heal, held to 0-9999. */
    int (*on_heal)(uint32_t (*fn)(void* user, uint32_t value, int source, int target), void* user);
    /* each enemy made (fn_800770B8), after the game filled it: scale the actor,
     * never the record, which every enemy of the kind shares across battles */
    int (*on_enemy_spawn)(void (*fn)(void* user, uint32_t actor, uint32_t record), void* user);
    /* each enemy's choice (fn_8008A424), its command record at cmd (+0 type,
     * +4 target, +5 selector, +6 id): returns the type */
    int (*on_enemy_action)(uint32_t (*fn)(void* user, uint32_t type, int slot, uint32_t cmd), void* user);
    /* the round's order, once it is set: slots, first to act first, ending at
     * -1; kept only if it is still distinct slots 0-11 ending at -1 */
    int (*on_turn_order)(void (*fn)(void* user, int8_t order[12]), void* user);
    /* the round's spirit gain, before the gauge's clamp: returns the gain */
    int (*on_spirit_gain)(int32_t (*fn)(void* user, int32_t amount), void* user);
    /* each Run, the party's or an enemy's (fn_80010340): nonzero escapes */
    int (*on_escape)(int (*fn)(void* user, int success, int slot), void* user);
    /* once a victory, before the game pays out */
    int (*on_rewards)(void (*fn)(void* user, SoaRewards* rewards), void* user);
    /* each effect applied (fn_8002BD88), before it is: returns nonzero to
     * cancel it; effect and value are written back */
    int (*on_effect)(int (*fn)(void* user, int target, int16_t* effect, int32_t* value), void* user);
    /* each round's end, once its regen, poison and spirit are applied */
    int (*on_round_end)(void (*fn)(void* user, uint32_t round), void* user);
    /* each ship battle damage (fn_80146BF4), before the game's x10: returns it */
    int (*on_ship_damage)(uint32_t (*fn)(void* user, uint32_t value), void* user);

    /* Appended (X2, docs/specs/save-extension.md): a chunk of the mod's own in
     * the game's save file, filed under its manifest 2 id; one of each per mod,
     * and 0 for a mod with no id. This one: when the save menu opens, write the
     * chunk into buf (cap bytes at most, the room left) and return its length,
     * or -1 for none. Inside the game's call, as the battle's events. */
    int (*on_save)(int32_t (*fn)(void* user, uint8_t* buf, uint32_t cap), void* user);
    /* when a save is loaded: the chunk it holds for this mod, or data NULL and
     * size 0 when it holds none (a vanilla save, or one made without the mod) */
    int (*on_load)(void (*fn)(void* user, const uint8_t* data, uint32_t size), void* user);
    /* at New Game, and once at boot */
    int (*on_new_game)(void (*fn)(void* user), void* user);

    /* Appended (T2, docs/specs/content-ids.md): the number this install gave
     * one of the mod's own claims (`claim = flag <name>` in its mod.ini), in
     * its init or any callback; kind "flag" for now. 0 for a name it did not
     * claim. The number is the same every run here, and never another mod's. */
    int (*claim)(const char* kind, const char* name, uint32_t* number);
} SoaModApi;

typedef int (*SoaModInit)(const SoaModApi* api, uint32_t version);

/* The size a table must reach to hold `member`: compare api->size with it. */
#define SOA_MOD_HAS(member) (offsetof(SoaModApi, member) + sizeof(((SoaModApi*)0)->member))

#endif
