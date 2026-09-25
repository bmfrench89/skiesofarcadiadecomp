/*
 * encounter-rate (docs/PLAN-GAMEPLAY-MODS.md P1; the comfort-pack spec 3.4):
 * how often random battles come in the field, and hold B for none.
 *
 * The game keeps an encounter multiplier, the signed byte at 0x8030B7AD:
 * -1 (0xFF) is the normal rate, and anything else multiplies the odds by
 * byte/50 (read at 0x800C2000). It sets that byte itself from the party's
 * accessories -- the effect-84 value of the last of characters 0-5 whose
 * accessory has one; on this disc accessory 210 (100: twice the battles) and
 * 211 (5: a tenth) -- when a map loads or equipment changes. This mod works
 * out the same base every frame, never reading the byte back (it holds the
 * mod's own last write), and writes from it:
 *
 *     SOA_ENCOUNTERS=half     base / 2, truncated: 50 -> 25, 100 -> 50, 5 -> 2
 *     SOA_ENCOUNTERS=double   min(base * 2, 127): 50 -> 100, 100 -> 127
 *     SOA_ENCOUNTERS=off      0
 *     SOA_ENCOUNTERS=normal   nothing -- and unset is normal
 *
 * where base is 50 when no accessory has the effect. While B is held in the
 * field it writes 0, no random battles, unless SOA_ENCOUNTERS_HOLD_B=0; at
 * normal, the first frame after B is let go puts the game's own value back,
 * once, so a tap of B does not leave battles off until the next map. Only in
 * the field (scene 6), from the frame end. The byte lies below the saved
 * party block, so nothing written here reaches a save.
 *
 * soa.ini's `encounters` and `encounters_hold_b` set the same two switches.
 * Built beside its mod.ini by `python tools/recompile.py --link`, or:
 *
 *     cl /LD /O2 /I runtime mods\encounter-rate\mod.c /Fe:mods\encounter-rate\mod.dll
 */
#include "soa_mod.h"

#include <stdio.h>
#include <string.h>
#include <windows.h>

#define MULTIPLIER 0x8030B7ADu /* s8: -1 the normal rate, else the odds x byte/50 */
#define PARTY 0x8030B7F4u      /* character c's block at PARTY + 92c */
#define ACCESSORY 20u          /* the u16 accessory id, in a block */
#define ITEMS 0x802C6E10u      /* accessory records, 40 bytes each, id 160 first */
#define EFFECTS 24u            /* four {u8 code, u8, s16 value}, in a record */
#define ENCOUNTER_EFFECT 84
#define SCENE_FIELD 6u

enum { P_NORMAL, P_HALF, P_DOUBLE, P_OFF }; /* not NORMAL/DOUBLE: windows.h has a DOUBLE */
static const char* const k_preset[] = {"normal", "half", "double", "off"};

static const SoaModApi* g_api;
static int g_preset = P_NORMAL, g_hold_b = 1;
static int g_b;     /* B held at the last controller read in the field */
static int g_dirty; /* the byte holds a value of this mod's, not the game's */
static int g_shown_base = -1000, g_shown_who = -2;

/* The game's own reckoning, from the party: the base (50 when no accessory
 * has the effect), the byte the game would hold (0xFF then), and whose
 * accessory decided it -- the last character with one, as the game has it. */
static int base_now(int* game, int* who, unsigned* item)
{
    int base = 50;
    unsigned c, e;
    *game = 0xFF;
    *who = -1;
    *item = 0;
    for (c = 0; c < 6; c++) {
        uint16_t id;
        if (!g_api->read16(PARTY + 92u * c + ACCESSORY, &id) || id < 160 || id > 239) continue;
        for (e = 0; e < 4; e++) {
            uint32_t at = ITEMS + (id - 160u) * 40u + EFFECTS + 4u * e;
            uint8_t code;
            uint16_t v;
            if (!g_api->read8(at, &code) || code != ENCOUNTER_EFFECT || !g_api->read16(at + 2, &v)) continue;
            base = (int16_t)v;
            *game = (uint8_t)v;
            *who = (int)c;
            *item = id;
        }
    }
    return base;
}

static void put(int v)
{
    if (g_api->write8(MULTIPLIER, (uint8_t)v)) g_dirty = 1;
}

static void on_frame_end(void* user)
{
    int game, who, base;
    unsigned item;
    (void)user;
    if (g_api->scene() != SCENE_FIELD) return;
    base = base_now(&game, &who, &item);
    if (base != g_shown_base || who != g_shown_who) {
        char line[96];
        if (who < 0) snprintf(line, sizeof line, "base %d (none)", base);
        else snprintf(line, sizeof line, "base %d (character %d's accessory %u)", base, who, item);
        g_api->log(line);
        g_shown_base = base;
        g_shown_who = who;
    }
    if (g_hold_b && g_b) {
        put(0);
        return;
    }
    if (g_preset == P_NORMAL) {
        /* Only ever the restore: the game's value, once, after this mod's own. */
        if (g_dirty && g_api->write8(MULTIPLIER, (uint8_t)game)) g_dirty = 0;
        return;
    }
    if (base < 0) return; /* an effect this disc does not have: leave the game be */
    put(g_preset == P_HALF ? base / 2 : g_preset == P_DOUBLE ? (base * 2 > 127 ? 127 : base * 2) : 0);
}

static void on_pad(void* user, uint32_t frame, SoaPad* pad)
{
    (void)user;
    (void)frame;
    g_b = (pad->buttons & SOA_PAD_B) && g_api->scene() == SCENE_FIELD;
}

/* An environment variable as the mod sees it: 1 with its value, 0 unset. */
static int env(const char* name, char* out, DWORD cap)
{
    DWORD n = GetEnvironmentVariableA(name, out, cap);
    if (!n) return 0;
    if (n >= cap) snprintf(out, cap, "%s", "(too long)"); /* no value this mod takes: refused with its line */
    return 1;
}

__declspec(dllexport) int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char v[32], line[160];
    int i;
    /* pad_filter is the last member this mod calls. */
    if (version < 1 || api->size < SOA_MOD_HAS(pad_filter)) return 1;
    g_api = api;
    if (env("SOA_ENCOUNTERS", v, sizeof v) && v[0]) {
        for (i = 0; i < 4 && strcmp(v, k_preset[i]); i++) {}
        if (i < 4) g_preset = i;
        else {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS=%s is not off, half, normal or double; the game's own rate", v);
            api->log(line);
        }
    }
    if (env("SOA_ENCOUNTERS_HOLD_B", v, sizeof v) && v[0]) {
        if (!strcmp(v, "0")) g_hold_b = 0;
        else if (strcmp(v, "1")) {
            snprintf(line, sizeof line, "SOA_ENCOUNTERS_HOLD_B=%s is not 0 or 1; holding B keeps battles away", v);
            api->log(line);
        }
    }
    api->on_frame_end(on_frame_end, NULL);
    if (g_hold_b) api->pad_filter(on_pad, NULL); /* without it, the read path is left as it was */
    snprintf(line, sizeof line, "random battles %s in the field; holding B keeps them away %s", k_preset[g_preset],
             g_hold_b ? "on" : "off");
    api->log(line);
    return 0;
}
