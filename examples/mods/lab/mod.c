/*
 * The lab: a native mod for scripted runs (docs/specs/reach.md U0). It changes
 * nothing unless SOA_LAB asks, and then only what each item says. SOA_LAB is a
 * list of items separated by ';':
 *
 *   entry:F:ID     at the first safe point at or after frame F where the field
 *                  runs (scene 6, state 8), no event runs (flag 1087 clear, no
 *                  script entry starting) and a live hit volume with object id
 *                  ID exists, do what the A press does when that volume is the
 *                  nearest (fn_80117BE4, 80117E78-80117EA0): fn_8021067C(ID),
 *                  the entry's LABEL condition, and only when it answers 1,
 *                  fn_80210550(ID), then the two words the scan stores after
 *                  it. What is skipped is the walk to the object, nothing else.
 *                  Tried again at every safe point until it starts or frame
 *                  F + 3600 passes; each outcome is logged once.
 *   peek:F[-G]:C   read the chain C at the safe points of frames F to G (F
 *                  alone: once) and log it when its value changes. C is an
 *                  address followed by steps: '*' reads the word there as the
 *                  next address, '+N' or '-N' adds (decimal or 0x hex). The
 *                  final word is the one logged: 0x80347390*+56 is the first
 *                  word of the battle's inventory copy.
 *   objects        at each map load, log every hit volume in the game's list:
 *                  its object id, hit type, state and shape words, for finding
 *                  where things are.
 *   hold-hp:F-G    in battle (scene 7) at each safe point of frames F to G,
 *                  every party member still standing (actor+28 & 0x2100 clear,
 *                  the game's own test, fn_80078610) has its HP put back to its
 *                  maximum (actor+20 = actor+24; actors at 0x80309DE4[0..3],
 *                  battle-system.md 1). The fight is still the game's: who
 *                  acts, what lands and when it ends. A run with this tests the
 *                  port's battle to its end, not a player's chance of winning,
 *                  and says so; it logs how many top-ups each battle took.
 *   turn:F-G:M:SEQ at party member M's first command input of each battle in
 *                  frames F to G (scene 7, the phase word 0x8034733C at 1 and
 *                  the member word 0x80347330 at M, as mods/coop reads them),
 *                  press SEQ through the pad filter: buttons separated by '/'
 *                  (left right up down a b x y z l r start), each held 10
 *                  frames and followed by 60 with nothing pressed, the game's
 *                  pace for a menu step (FINDINGS 1454-1457). While it plays,
 *                  what SOA_PAD presses is held back. At each phase 1 -> 2 edge
 *                  the members' command types are logged (the s32 at
 *                  0x80309174 + 32 * m: 3 Attack, 4 Guard, 5 Item).
 *
 * Addresses: r13 is 0x8034E720 (runtime/selftest.c), so the list head
 * r13-29180 is 0x80347524 (fn_8022300C, 80223024), linked at +48 (802230DC),
 * a volume live while its s16 at +20 is not negative (80223034), its object id
 * the word at +8 (80117E78) and its hit type the u16 at +18 (80117C24); the
 * A press's two stores r13-29464 = 1 and r13-29396 = the volume
 * (80117E98, 80117EA0) are 0x80347408 and 0x8034744C; fn_80210550 refuses
 * while 0x8030E714 is 1 (80210574).
 */
#include "soa_mod.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LIST_HEAD 0x80347524u
#define PRESS_STARTED 0x80347408u
#define PRESS_VOLUME 0x8034744Cu
#define ENTRY_BUSY 0x8030E714u
#define FN_ENTRY_LIVE 0x8021067Cu
#define FN_ENTRY_START 0x80210550u
#define FLAG_EVENT 1087u
#define ENTRY_PATIENCE 3600u

#define SCENE_BATTLE 7u
#define ACTORS 0x80309DE4u
#define ACTOR_HP 20u
#define ACTOR_MAX_HP 24u
#define ACTOR_STATUS 28u
#define STATUS_OUT 0x2100u

#define PHASE 0x8034733Cu
#define MEMBER 0x80347330u
#define COMMANDS 0x80309174u
#define PHASE_INPUT 1u
#define PHASE_ORDER 2u
#define PRESS_HOLD 10u
#define PRESS_GAP 60u
#define MAX_PRESSES 16

#define MAX_ITEMS 64
#define MAX_STEPS 8

enum { ITEM_ENTRY, ITEM_PEEK, ITEM_HOLD_HP, ITEM_TURN };

typedef struct Item {
    int kind;
    uint32_t from, to;
    uint32_t id;     /* entry */
    int state;       /* entry: 0 waiting, 1 done or given up; peek: 0 never read, 1 read */
    uint32_t last;   /* peek: the last value logged */
    uint32_t base;   /* peek */
    int nsteps;
    int32_t add[MAX_STEPS]; /* each step: deref (flag) then add */
    int deref[MAX_STEPS];
    char text[96];
    char why[96];    /* entry: the last reason it waited, logged once per change */
    /* turn: the presses, the member, and where it is: started (frame of the
     * first press, 0 idle), done for this battle */
    uint16_t presses[MAX_PRESSES];
    int npresses;
    uint32_t member, started;
    int done;
} Item;

static const SoaModApi* g_api;
static Item g_items[MAX_ITEMS];
static int g_nitems;
static int g_objects;

static void logf_(const char* fmt, ...)
{
    char line[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    g_api->log(line);
}

static int parse_u32(const char* s, char** end, uint32_t* out)
{
    unsigned long v;
    if (!s || !*s) return 0;
    v = strtoul(s, end, 0);
    if (*end == s) return 0;
    *out = (uint32_t)v;
    return 1;
}

/* "F" or "F-G" */
static int parse_frames(const char* s, Item* it)
{
    char* end;
    if (!parse_u32(s, &end, &it->from)) return 0;
    it->to = it->from;
    if (*end == '-') {
        if (!parse_u32(end + 1, &end, &it->to) || it->to < it->from) return 0;
    }
    return *end == '\0';
}

static int parse_chain(const char* s, Item* it)
{
    char* end;
    if (!parse_u32(s, &end, &it->base)) return 0;
    it->nsteps = 0;
    s = end;
    while (*s) {
        int deref = 0;
        long add = 0;
        if (it->nsteps == MAX_STEPS) return 0;
        if (*s == '*') {
            deref = 1;
            s++;
        }
        if (*s == '+' || *s == '-') {
            int neg = *s == '-';
            uint32_t v;
            if (!parse_u32(s + 1, &end, &v)) return 0;
            add = neg ? -(long)v : (long)v;
            s = end;
        } else if (!deref) {
            return 0;
        }
        it->deref[it->nsteps] = deref;
        it->add[it->nsteps] = (int32_t)add;
        it->nsteps++;
    }
    return 1;
}

static int read_chain(const Item* it, uint32_t* addr, uint32_t* value)
{
    uint32_t a = it->base;
    int i;
    for (i = 0; i < it->nsteps; i++) {
        if (it->deref[i] && !g_api->read32(a, &a)) return 0;
        a += (uint32_t)it->add[i];
    }
    *addr = a;
    return g_api->read32(a, value);
}

/* One item, already split from the list; 0 refuses the whole setting. */
static int parse_item(char* s)
{
    Item* it;
    char *a, *b;
    if (strcmp(s, "objects") == 0) {
        g_objects = 1;
        return 1;
    }
    if (g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    a = strchr(s, ':');
    if (!a) return 0;
    *a++ = '\0';
    b = strchr(a, ':');
    if (!b) return 0;
    *b++ = '\0';
    if (strcmp(s, "entry") == 0) {
        char* end;
        it->kind = ITEM_ENTRY;
        if (!parse_frames(a, it) || it->to != it->from) return 0;
        if (!parse_u32(b, &end, &it->id) || *end) return 0;
    } else if (strcmp(s, "peek") == 0) {
        it->kind = ITEM_PEEK;
        if (!parse_frames(a, it) || !parse_chain(b, it)) return 0;
    } else {
        return 0;
    }
    g_nitems++;
    return 1;
}

static uint16_t button(const char* name)
{
    static const struct {
        const char* name;
        uint16_t bit;
    } names[] = {{"left", SOA_PAD_LEFT}, {"right", SOA_PAD_RIGHT}, {"down", SOA_PAD_DOWN}, {"up", SOA_PAD_UP},
                 {"z", SOA_PAD_Z},       {"r", SOA_PAD_R},         {"l", SOA_PAD_L},       {"a", SOA_PAD_A},
                 {"b", SOA_PAD_B},       {"x", SOA_PAD_X},         {"y", SOA_PAD_Y},       {"start", SOA_PAD_START}};
    size_t i;
    for (i = 0; i < sizeof names / sizeof names[0]; i++)
        if (strcmp(name, names[i].name) == 0) return names[i].bit;
    return 0;
}

/* "turn:F-G:M:SEQ" */
static int parse_turn(char* s)
{
    Item* it;
    char *frames, *member, *seq, *tok, *end, *save;
    if (strncmp(s, "turn:", 5) != 0 || g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    it->kind = ITEM_TURN;
    frames = s + 5;
    member = strchr(frames, ':');
    if (!member) return 0;
    *member++ = '\0';
    seq = strchr(member, ':');
    if (!seq) return 0;
    *seq++ = '\0';
    if (!parse_frames(frames, it) || !parse_u32(member, &end, &it->member) || *end || it->member > 3) return 0;
    for (tok = seq; tok && *tok; tok = save) {
        save = strchr(tok, '/');
        if (save) *save++ = '\0';
        if (it->npresses == MAX_PRESSES || !(it->presses[it->npresses] = button(tok))) return 0;
        it->npresses++;
    }
    if (!it->npresses) return 0;
    g_nitems++;
    return 1;
}

static void log_commands(uint32_t frame)
{
    char line[160];
    int m, n = snprintf(line, sizeof line, "commands at frame %u:", frame);
    for (m = 0; m < 4 && n > 0 && (size_t)n < sizeof line; m++) {
        uint32_t v = 0xFFFFFFFFu;
        g_api->read32(COMMANDS + 32u * (uint32_t)m, &v);
        n += snprintf(line + n, sizeof line - (size_t)n, " %d=%d", m, (int32_t)v);
    }
    g_api->log(line);
}

/* The pad filter: plays each turn item's presses when its member's input
 * comes, and logs the commands at each phase 1 -> 2 edge. */
static void on_pad(void* user, uint32_t frame, SoaPad* pad)
{
    static uint32_t last_phase = 0xFFFFFFFFu;
    uint32_t phase = 0xFFFFFFFFu, member = 0xFFFFFFFFu;
    int battle = g_api->scene() == SCENE_BATTLE, i;
    (void)user;
    if (battle) g_api->read32(PHASE, &phase);
    if (battle && last_phase == PHASE_INPUT && phase == PHASE_ORDER) log_commands(frame);
    last_phase = battle ? phase : 0xFFFFFFFFu;
    if (phase == PHASE_INPUT) g_api->read32(MEMBER, &member);
    for (i = 0; i < g_nitems; i++) {
        Item* it = &g_items[i];
        uint32_t step, into;
        if (it->kind != ITEM_TURN) continue;
        if (!battle) {
            it->done = 0;
            it->started = 0;
            continue;
        }
        if (!it->started) {
            if (it->done || frame < it->from || frame > it->to || member != it->member) continue;
            it->started = frame;
            logf_("turn: member %u's input at frame %u: pressing %s", it->member, frame, strrchr(it->text, ':') + 1);
        }
        /* A lead-in of nothing pressed first: the wheel turns into view as
         * the input opens, and a press then is dropped. */
        into = frame - it->started;
        step = into < PRESS_GAP ? 0 : (into - PRESS_GAP) / (PRESS_HOLD + PRESS_GAP);
        if (step >= (uint32_t)it->npresses) {
            it->started = 0;
            it->done = 1;
            continue;
        }
        if (into < PRESS_GAP)
            pad->buttons = 0;
        else
            pad->buttons = (into - PRESS_GAP) % (PRESS_HOLD + PRESS_GAP) < PRESS_HOLD ? it->presses[step] : 0;
        pad->stick[0] = pad->stick[1] = 128;
    }
}

/* "hold-hp:F-G": no third field. */
static int parse_hold(char* s)
{
    Item* it;
    if (strncmp(s, "hold-hp:", 8) != 0 || g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    it->kind = ITEM_HOLD_HP;
    if (!parse_frames(s + 8, it)) return 0;
    g_nitems++;
    return 1;
}

/* One safe point of hold-hp: tops up the standing party; it->last counts this
 * battle's top-ups, logged when the battle ends. */
static void hold_hp(Item* it)
{
    uint32_t slot, actor, status, hp, max;
    if (g_api->scene() != SCENE_BATTLE) {
        if (it->state == 1) {
            logf_("hold-hp: the battle ended by frame %u; %u top-up(s)", g_api->frame(), it->last);
            it->state = 0;
            it->last = 0;
        }
        return;
    }
    if (it->state == 0) {
        logf_("hold-hp: a battle from frame %u: the party's HP is held at its maximum", g_api->frame());
        it->state = 1;
    }
    for (slot = 0; slot < 4; slot++) {
        if (!g_api->read32(ACTORS + 4 * slot, &actor) || !actor) continue;
        if (!g_api->read32(actor + ACTOR_STATUS, &status) || (status & STATUS_OUT)) continue;
        if (!g_api->read32(actor + ACTOR_HP, &hp) || !g_api->read32(actor + ACTOR_MAX_HP, &max)) continue;
        if ((int32_t)hp < (int32_t)max && (int32_t)hp > 0) {
            g_api->write32(actor + ACTOR_HP, max);
            it->last++;
        }
    }
}

/* The live hit volume with this object id, or 0. */
static uint32_t find_volume(uint32_t id)
{
    uint32_t v, oid;
    uint16_t state;
    int guard = 0;
    if (!g_api->read32(LIST_HEAD, &v)) return 0;
    while (v && guard++ < 4096) {
        if (g_api->read16(v + 20, &state) && (int16_t)state >= 0 && g_api->read32(v + 8, &oid) && oid == id)
            return v;
        if (!g_api->read32(v + 48, &v)) return 0;
    }
    return 0;
}

/* Logs why the entry waits, once each time the reason changes; returns 0. */
static int entry_wait(Item* it, const char* why)
{
    if (strcmp(it->why, why) != 0) {
        snprintf(it->why, sizeof it->why, "%s", why);
        logf_("entry %u: waiting at frame %u: %s", it->id, g_api->frame(), why);
    }
    return 0;
}

/* The reason the entry cannot start at this safe point, or NULL. */
static const char* entry_blocked(const Item* it, uint32_t* vol)
{
    uint32_t busy = 0;
    if (g_api->scene() != 6 || g_api->field_state() != 8) return "the field is not running";
    if (g_api->story_flag(FLAG_EVENT)) return "an event runs (flag 1087)";
    if (g_api->read32(ENTRY_BUSY, &busy) && busy == 1) return "a script entry is starting";
    *vol = find_volume(it->id);
    if (!*vol) return "no live hit volume has this id";
    return NULL;
}

static void try_entry(Item* it)
{
    uint32_t vol = 0, live = 0, started = 0;
    uint32_t args[1];
    const char* why;
    if (g_api->frame() > it->from + ENTRY_PATIENCE) {
        logf_("entry %u: gave up at frame %u (last: %s)", it->id, g_api->frame(), it->why[0] ? it->why : "none");
        it->state = 1;
        return;
    }
    why = entry_blocked(it, &vol);
    if (why) {
        entry_wait(it, why);
        return;
    }
    args[0] = it->id;
    if (!g_api->call_guest(FN_ENTRY_LIVE, args, 1, NULL, 0, &live, NULL)) {
        it->state = 1;
        return;
    }
    if (live != 1) {
        entry_wait(it, "its LABEL condition is 0");
        return;
    }
    if (!g_api->call_guest(FN_ENTRY_START, args, 1, NULL, 0, &started, NULL)) {
        it->state = 1;
        return;
    }
    g_api->write32(PRESS_STARTED, 1);
    g_api->write32(PRESS_VOLUME, vol);
    logf_("entry %u: started at frame %u, volume %08X, fn_80210550 answered %u", it->id, g_api->frame(), vol,
          started);
    it->state = 1;
}

static void on_safe_point(void* user)
{
    uint32_t f = g_api->frame();
    int i;
    (void)user;
    for (i = 0; i < g_nitems; i++) {
        Item* it = &g_items[i];
        if (f < it->from) continue;
        if (it->kind == ITEM_ENTRY) {
            if (it->state == 0) try_entry(it);
        } else if (it->kind == ITEM_HOLD_HP) {
            if (f <= it->to) hold_hp(it);
        } else if (it->kind == ITEM_PEEK && f <= it->to) {
            uint32_t addr = 0, value = 0;
            if (!read_chain(it, &addr, &value)) {
                if (it->state != 2) logf_("peek %s: frame %u: the chain left RAM", it->text, f);
                it->state = 2;
            } else if (it->state != 1 || value != it->last) {
                logf_("peek %s: frame %u: %08X = %08X", it->text, f, addr, value);
                it->state = 1;
                it->last = value;
            }
        }
    }
}

static void on_map_loaded(void* user, uint32_t map)
{
    uint32_t v, id, w[4], cls;
    uint16_t type, state, nshapes;
    int guard = 0, n = 0, i;
    (void)user;
    if (!g_api->read32(LIST_HEAD, &v)) return;
    while (v && guard++ < 4096) {
        id = 0;
        type = state = nshapes = 0;
        g_api->read32(v + 8, &id);
        g_api->read16(v + 18, &type);
        g_api->read16(v + 20, &state);
        g_api->read16(v + 12, &nshapes);
        for (i = 0; i < 4; i++)
            if (!g_api->read32(v + 52 + 4 * (uint32_t)i, &w[i])) w[i] = 0;
        /* +16: the hit class (the 0x802EE7C0 table's third word: goscript
         * 0x80000008, man 0x78400016), which the overlap test copies aside
         * (fn_80222B30, 80222B58); seen in a116a's 45 volumes, 2026-10-14. */
        if (!g_api->read32(v + 16, &cls)) cls = 0;
        logf_("objects a%03u%c: %08X id %u type %u class %08X state %d shapes %d, shape 0: %08X %08X %08X %08X",
              (unsigned)(map >> 8), (char)(map & 0xFF), v, id, type, cls, (int16_t)state, (int16_t)nshapes, w[0],
              w[1], w[2], w[3]);
        n++;
        if (!g_api->read32(v + 48, &v)) break;
    }
    logf_("objects a%03u%c: %d hit volume(s) at frame %u", (unsigned)(map >> 8), (char)(map & 0xFF), n,
          g_api->frame());
}

SOA_MOD_EXPORT int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    const char* env = getenv("SOA_LAB");
    char buf[2048];
    char* item;
    char* save = NULL;
    char whole[128];
    int i;
    if (version < 1 || api->size < SOA_MOD_HAS(call_guest)) return 1;
    g_api = api;
    if (!env || !*env) {
        api->log("lab loaded, idle: SOA_LAB names nothing");
        return 0;
    }
    if (strlen(env) >= sizeof buf) {
        api->log("lab: SOA_LAB is longer than 2047 characters");
        return 1;
    }
    strcpy(buf, env);
    for (item = buf; item; item = save) {
        save = strchr(item, ';');
        if (save) *save++ = '\0';
        if (!*item) continue;
        snprintf(whole, sizeof whole, "%s", item); /* the parsers cut the item as they read it */
        if (!parse_hold(item) && !parse_turn(item) && !parse_item(item)) {
            char line[160];
            snprintf(line, sizeof line, "lab: SOA_LAB item not understood: %.120s", whole);
            api->log(line);
            return 1;
        }
    }
    if (g_nitems) api->on_safe_point(on_safe_point, NULL);
    for (i = 0; i < g_nitems; i++) {
        if (g_items[i].kind != ITEM_TURN) continue;
        if (api->size < SOA_MOD_HAS(pad_filter) || !api->pad_filter(on_pad, NULL)) {
            api->log("lab: a turn item needs the pad filter, which this port does not offer");
            return 1;
        }
        break;
    }
    if (g_objects) api->on_map_loaded(on_map_loaded, NULL);
    logf_("lab loaded: %d item(s)%s", g_nitems, g_objects ? ", and the objects at each map load" : "");
    return 0;
}
