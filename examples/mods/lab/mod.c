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
 *                  its object id, hit type, class, state and shape words, and
 *                  where its object's actor stands (op 154's lookup by id,
 *                  act+56..64), then the player's position.
 *   walk:F-G:IDLE  the entry walker (reach U4): at a safe point in frames F to
 *                  G where the field runs and nothing has been busy (an event,
 *                  a starting entry, another scene) for IDLE frames, start one
 *                  live entry of this map the way entry: does -- the one
 *                  started fewest times here, a talk or check (3000-4999)
 *                  before an exit (6000-6999), then the lower id. The game's
 *                  own LABEL conditions and gates keep the story in order;
 *                  what the walker skips is the walk. Each start is logged.
 *   assist:F-G:EVERY  A, for two frames every EVERY frames, only in a battle,
 *                  at its results screen (the field's state 4, 0x80311AEC),
 *                  in a ship battle where its menu waits for A (a 5xx stage,
 *                  the ship input word at state 6, step 0; sturn plays the
 *                  crew's wheels),
 *                  or while the field's message window holds a choice (state
 *                  6 at 0x80346E64, its task at 0x80346E4C, as mods/autotext
 *                  reads them): what the walker needs where a pad script's A
 *                  every 150 frames would talk to whatever stands nearest.
 *   dump:F:C:N     once, at the first safe point at or after frame F, N bytes
 *                  (a multiple of 4, at most 8192) from the address the chain
 *                  C ends on (C's steps as peek's; *0x8034727C is the ship
 *                  battle's state), eight words a line.
 *   hold-hp:F-G    in battle (scene 7) at each safe point of frames F to G,
 *                  every party member still standing (actor+28 & 0x2100 clear,
 *                  the game's own test, fn_80078610) has its HP put back to its
 *                  maximum (actor+20 = actor+24; actors at 0x80309DE4[0..3],
 *                  battle-system.md 1). The fight is still the game's: who
 *                  acts, what lands and when it ends. A run with this tests the
 *                  port's battle to its end, not a player's chance of winning,
 *                  and says so; it logs how many top-ups each battle took.
 *   save:F-G:SEQ   once, on a quiet field in frames F to G with a live save
 *                  point (hit type 44 or 45) in the map, start its entry as
 *                  the A press would, then 120 frames later press SEQ into
 *                  the save menu (buttons as turn's, 10 frames each, 60
 *                  between): a card a later run can Continue from.
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
 *   sturn:F-G:M:SEQ the same for a ship battle's crew member M, each time
 *                  that member's wheel comes ready (the word at 0x80306738:
 *                  state byte 9, step byte 2, member byte M), every turn; a
 *                  wheel still ready afterwards gets the presses again, three
 *                  times at most. In either, SEQ may hold alternatives split
 *                  by '|', used in turn by successive inputs (Focus twice,
 *                  then the special: b/right/a/a|b/right/a/a|b/right/right#4/a/a),
 *                  and a press "name#N" is held N frames (left#4: one slot).
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
#define FN_FIND_OBJECT 0x8015F1A0u /* the object with id r3: its actor, or 0 (op 154's lookup) */
#define PLAYER 0x80347450u         /* the player's actor (content-systems.md 2, 80101030) */
#define ACTOR_POS 56u              /* x, y, z floats */
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
#define MAX_PRESSES 32
#define MAX_ALTS 4
#define STURN_RETRIES 3u /* plays of a ship member's input that changed nothing, before giving up */

#define MAX_ITEMS 64
#define MAX_STEPS 8

enum {
    ITEM_ENTRY,
    ITEM_PEEK,
    ITEM_HOLD_HP,
    ITEM_TURN,
    ITEM_DUMP,
    ITEM_STURN,
    ITEM_WALK,
    ITEM_ASSIST,
    ITEM_SAVE
};


/* The field's message window, as mods/autotext reads it: its task (0 when
 * there is none) and its state, 6 being a choice. */
#define WINDOW_TASK 0x80346E4Cu
#define WINDOW_STATE 0x80346E64u
#define WINDOW_CHOICE 6
#define FIELD_RESULTS 4u /* the field's state while a battle's results screen waits */
#define HIT_SAVE_POINT 45u     /* a volume's hit type (u16 at +18): "walluv", a save point */
#define HIT_SAVE_POINT_MOT 44u /* "wallmot", the other save point */

static int assist_wanted(void); /* below, beside the walker; on_pad calls it first */

/* The walker's memory: how often each map's entry has been started. */
#define MAX_SEEN 1024
static struct {
    uint32_t map, id, runs;
} g_seen[MAX_SEEN];
static int g_nseen;

/* A ship battle's command input (reach U3, found by RAM captures at two
 * crew members' inputs and confirmed by peeks through a fight): the word at
 * 0x80306738 holds the menu's state (byte 0), its step (byte 1) and the crew
 * member choosing (byte 2); state 9, step 2 is a member's wheel, ready. */
#define SHIP_INPUT 0x80306738u
#define SHIP_READY_STATE 9u
#define SHIP_READY_STEP 2u
#define SHIP_WAIT_STATE 6u /* the menu waits for A, unless a member's wheel is open */

static int g_sturn_playing; /* an sturn sequence is under way: assist keeps off */

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
    uint8_t holds[MAX_PRESSES]; /* frames each press is held: 10, or N from "name#N" */
    int npresses;
    /* "SEQ|SEQ|...": alternatives, used in turn by a turn or sturn item's
     * successive inputs (a retry keeps the one it has) */
    uint8_t alt_from[MAX_ALTS], alt_len[MAX_ALTS];
    int nalt, alt;
    uint32_t turns;
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
    } else if (strcmp(s, "dump") == 0) {
        /* dump:F:CHAIN:BYTES -- the chain's address, then BYTES from there */
        char* n = strrchr(b, ':');
        char* end;
        it->kind = ITEM_DUMP;
        if (!n) return 0;
        *n++ = '\0';
        if (!parse_frames(a, it) || it->to != it->from || !parse_chain(b, it)) return 0;
        if (!parse_u32(n, &end, &it->id) || *end || !it->id || it->id > 8192 || it->id % 4) return 0;
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

/* "turn:F-G:M:SEQ", "sturn:F-G:M:SEQ" for a ship battle's crew, or
 * "save:F-G:SEQ" (no member) */
static int parse_turn(char* s)
{
    Item* it;
    char *frames, *member, *seq, *tok, *end, *save;
    int ship = strncmp(s, "sturn:", 6) == 0, saving = strncmp(s, "save:", 5) == 0;
    if ((!ship && !saving && strncmp(s, "turn:", 5) != 0) || g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    it->kind = ship ? ITEM_STURN : saving ? ITEM_SAVE : ITEM_TURN;
    frames = s + (ship ? 6 : 5);
    if (saving) {
        seq = strchr(frames, ':');
        if (!seq) return 0;
        *seq++ = '\0';
        if (!parse_frames(frames, it)) return 0;
    } else {
        member = strchr(frames, ':');
        if (!member) return 0;
        *member++ = '\0';
        seq = strchr(member, ':');
        if (!seq) return 0;
        *seq++ = '\0';
        if (!parse_frames(frames, it) || !parse_u32(member, &end, &it->member) || *end || it->member > 3) return 0;
    }
    {
        char *alt, *next_alt;
        for (alt = seq; alt; alt = next_alt) {
            next_alt = strchr(alt, '|');
            if (next_alt) *next_alt++ = '\0';
            if (it->nalt == MAX_ALTS || (saving && it->nalt == 1)) return 0;
            it->alt_from[it->nalt] = (uint8_t)it->npresses;
            for (tok = alt; tok && *tok; tok = save) {
                save = strchr(tok, '/');
                if (save) *save++ = '\0';
                {
                    /* "left#4": held 4 frames, under the game's 6-frame repeat,
                     * so a wheel moves one slot where a plain press moves two */
                    char* hash = strchr(tok, '#');
                    uint32_t hold = PRESS_HOLD;
                    if (hash) {
                        *hash++ = '\0';
                        if (!parse_u32(hash, &end, &hold) || *end || hold < 1 || hold > PRESS_HOLD + PRESS_GAP - 1)
                            return 0;
                    }
                    if (it->npresses == MAX_PRESSES || !(it->presses[it->npresses] = button(tok))) return 0;
                    it->holds[it->npresses] = (uint8_t)hold;
                }
                it->npresses++;
            }
            it->alt_len[it->nalt] = (uint8_t)(it->npresses - it->alt_from[it->nalt]);
            if (!it->alt_len[it->nalt]) return 0;
            it->nalt++;
        }
    }
    if (!it->npresses) return 0;
    g_nitems++;
    return 1;
}

/* A new input (not a retry) takes the next alternative. */
static void next_alt(Item* it)
{
    if (it->last == 0) it->alt = (int)(it->turns++ % (uint32_t)it->nalt);
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
    uint32_t phase = 0xFFFFFFFFu, member = 0xFFFFFFFFu, ship = 0, crew = 0xFFFFFFFFu;
    int battle = g_api->scene() == SCENE_BATTLE, i;
    (void)user;
    if (battle) g_api->read32(PHASE, &phase);
    if (battle && last_phase == PHASE_INPUT && phase == PHASE_ORDER) log_commands(frame);
    last_phase = battle ? phase : 0xFFFFFFFFu;
    if (phase == PHASE_INPUT) g_api->read32(MEMBER, &member);
    if (g_api->read32(SHIP_INPUT, &ship) && (ship >> 24) == SHIP_READY_STATE &&
        ((ship >> 16) & 0xFFu) == SHIP_READY_STEP)
        crew = (ship >> 8) & 0xFFu;
    g_sturn_playing = 0;
    for (i = 0; i < g_nitems; i++)
        if (g_items[i].kind == ITEM_STURN && g_items[i].started) g_sturn_playing = 1;
    for (i = 0; i < g_nitems; i++) {
        Item* it = &g_items[i];
        uint32_t step, into;
        if (it->kind == ITEM_SAVE) {
            /* state 1: the save point's entry has started; play from it->started */
            if (it->state != 1 || frame < it->started) continue;
            into = frame - it->started;
            step = into / (PRESS_HOLD + PRESS_GAP);
            if (step >= (uint32_t)it->npresses) {
                it->state = 2;
                logf_("save: %s played by frame %u", strrchr(it->text, ':') + 1, frame);
                continue;
            }
            pad->buttons = into % (PRESS_HOLD + PRESS_GAP) < it->holds[step] ? it->presses[step] : 0;
            pad->stick[0] = pad->stick[1] = 128;
            continue;
        }
        if (it->kind == ITEM_ASSIST) {
            if (frame >= it->from && frame <= it->to && frame % it->id < 2 && assist_wanted())
                pad->buttons |= SOA_PAD_A;
            continue;
        }
        if (it->kind == ITEM_STURN) {
            /* Every time the member's wheel comes ready, not once a battle:
             * a ship battle asks each crew member every turn. */
            if (!it->started) {
                if (crew != it->member) {
                    it->done = 0;
                    it->last = 0;
                    continue;
                }
                if (it->done || frame < it->from || frame > it->to) continue;
                it->started = frame;
                next_alt(it);
                logf_("sturn: crew %u's input at frame %u: pressing %s (alternative %d of %d)", it->member, frame,
                      strrchr(it->text, ':') + 1, it->alt + 1, it->nalt);
            }
        } else if (it->kind != ITEM_TURN) {
            continue;
        } else if (!battle) {
            it->done = 0;
            it->started = 0;
            continue;
        } else if (!it->started) {
            if (it->done || frame < it->from || frame > it->to || member != it->member) continue;
            it->started = frame;
            next_alt(it);
            logf_("turn: member %u's input at frame %u: pressing %s", it->member, frame, strrchr(it->text, ':') + 1);
        }
        /* A lead-in of nothing pressed first: the wheel turns into view as
         * the input opens, and a press then is dropped. */
        into = frame - it->started;
        step = into < PRESS_GAP ? 0 : (into - PRESS_GAP) / (PRESS_HOLD + PRESS_GAP);
        if (step >= (uint32_t)it->alt_len[it->alt]) {
            it->started = 0;
            if (it->kind == ITEM_TURN) {
                it->done = 1;
            } else if (crew == it->member && it->last < STURN_RETRIES) {
                /* Still ready: a press did not land (an A between turns can
                 * open the cannon list first: reach U3's sink run stood there
                 * 16,000 frames). Played again, a few times at most. */
                it->last++;
                it->done = 0;
                logf_("sturn: crew %u's wheel is still ready at frame %u: again (%u of %u)", it->member, frame,
                      it->last, STURN_RETRIES);
            } else if (crew == it->member) {
                it->done = 1; /* given up: the person's now */
            } else {
                /* Not ready any more: it may come ready again next turn, with
                 * the next alternative. */
                it->done = 0;
                it->last = 0;
            }
            continue;
        }
        step += it->alt_from[it->alt];
        if (into < PRESS_GAP)
            pad->buttons = 0;
        else
            pad->buttons = (into - PRESS_GAP) % (PRESS_HOLD + PRESS_GAP) < it->holds[step] ? it->presses[step] : 0;
        pad->stick[0] = pad->stick[1] = 128;
    }
}

/* "walk:F-G:IDLE", or "assist:F-G:EVERY" */
static int parse_walk(char* s)
{
    Item* it;
    char* idle;
    char* end;
    int assist = strncmp(s, "assist:", 7) == 0;
    size_t skip = assist ? 7 : 5;
    if ((!assist && strncmp(s, "walk:", 5) != 0) || g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    it->kind = assist ? ITEM_ASSIST : ITEM_WALK;
    idle = strchr(s + skip, ':');
    if (!idle) return 0;
    *idle++ = '\0';
    if (!parse_frames(s + skip, it) || !parse_u32(idle, &end, &it->id) || *end || !it->id) return 0;
    if (assist && it->id < 4) return 0; /* a press is two frames down and two up */
    g_nitems++;
    return 1;
}

/* assist: is A wanted now? In a battle, at the results screen after one (the
 * field's state 4, which waits for A: reach U4's third run stood there), or
 * at a choice box in the field. */
static int assist_wanted(void)
{
    uint32_t task = 0, ship = 0, stage = g_api->map() >> 8;
    uint16_t state = 0;
    if (g_api->scene() == SCENE_BATTLE) return 1;
    if (g_api->scene() == 6 && g_api->field_state() == FIELD_RESULTS) return 1;
    /* A ship battle (a 5xx stage) waits for A in its menu's state 6 (the
     * word 0x80306738 = 06 .. .. ..): at the opening and between one crew
     * member and the next, whatever step the last member left (reach U3's
     * sink runs stood at 060F0103 and at 06020203). State 6 is also a member's
     * wheel after B, inside an sturn sequence, where an A would choose for it
     * (the second sink run, where Aika stood for 16,000 frames): so never
     * while one plays. Reach U4's seventh run stood at the Fortress Gate for
     * 70,000 frames with no A at all. */
    if (g_api->scene() == 6 && stage >= 500 && stage <= 583 && !g_sturn_playing &&
        g_api->read32(SHIP_INPUT, &ship) && (ship >> 24) == SHIP_WAIT_STATE)
        return 1;
    return g_api->scene() == 6 && g_api->read32(WINDOW_TASK, &task) && task &&
           g_api->read16(WINDOW_STATE, &state) && (int16_t)state == WINDOW_CHOICE;
}

static uint32_t* seen_runs(uint32_t map, uint32_t id)
{
    int i;
    for (i = 0; i < g_nseen; i++)
        if (g_seen[i].map == map && g_seen[i].id == id) return &g_seen[i].runs;
    if (g_nseen == MAX_SEEN) return NULL;
    g_seen[g_nseen].map = map;
    g_seen[g_nseen].id = id;
    g_seen[g_nseen].runs = 0;
    return &g_seen[g_nseen++].runs;
}

/* One safe point of the walker: it->started is the last frame the field was
 * busy (or an entry was started), it->last the number of entries started. */
/* Logs why the walker waits, once each time the reason changes. */
static void walk_wait(Item* it, const char* why)
{
    if (strcmp(it->why, why) != 0) {
        snprintf(it->why, sizeof it->why, "%s", why);
        logf_("walk: waiting at frame %u: %s", g_api->frame(), why);
    }
}

/* One safe point of save: on a quiet field with a live save point (hit type
 * 44 or 45) in this map, start its entry as the A press would, once; the pad
 * filter then plays the item's presses into the save menu, from SAVE_SETTLE
 * frames later. */
#define SAVE_SETTLE 120u
static void save_point(Item* it)
{
    uint32_t f = g_api->frame(), v = 0, vol, id, busy = 0, live = 0, started = 0, args[1];
    uint16_t state, type;
    int guard = 0;
    if (it->state != 0) return;
    if (g_api->scene() != 6 || g_api->field_state() != 8 || g_api->story_flag(FLAG_EVENT) ||
        (g_api->read32(ENTRY_BUSY, &busy) && busy == 1) || !g_api->read32(LIST_HEAD, &v))
        return;
    while (v && guard++ < 4096) {
        vol = v;
        if (!g_api->read32(v + 48, &v)) v = 0;
        if (!g_api->read16(vol + 20, &state) || (int16_t)state < 0 || !g_api->read16(vol + 18, &type) ||
            (type != HIT_SAVE_POINT && type != HIT_SAVE_POINT_MOT) || !g_api->read32(vol + 8, &id))
            continue;
        args[0] = id;
        if (!g_api->call_guest(FN_ENTRY_LIVE, args, 1, NULL, 0, &live, NULL) || live != 1) continue;
        if (!g_api->call_guest(FN_ENTRY_START, args, 1, NULL, 0, &started, NULL)) return;
        g_api->write32(PRESS_STARTED, 1);
        g_api->write32(PRESS_VOLUME, vol);
        it->state = 1;
        it->started = f + SAVE_SETTLE;
        logf_("save: a%03u%c's save point %u started at frame %u; pressing %s from frame %u",
              (unsigned)(g_api->map() >> 8), (char)(g_api->map() & 0xFF), id, f, strrchr(it->text, ':') + 1,
              it->started);
        return;
    }
}

static void walk(Item* it)
{
    uint32_t f = g_api->frame(), map = g_api->map(), v = 0, vol, id, best_id = 0, best_vol = 0, args[1];
    uint32_t best_runs = 0xFFFFFFFFu, live = 0, started = 0, busy = 0, *runs, asked = 0, seen = 0;
    uint16_t state, type = 0;
    int guard = 0, best_exit = 1, exit_;
    char why[96];
    if (g_api->scene() != 6 || g_api->field_state() != 8) {
        snprintf(why, sizeof why, "the field is not running (scene %u, state %u)", g_api->scene(),
                 g_api->field_state());
        walk_wait(it, why);
        it->started = f;
        return;
    }
    if (g_api->story_flag(FLAG_EVENT)) {
        walk_wait(it, "an event runs (flag 1087)");
        it->started = f;
        return;
    }
    if (g_api->read32(ENTRY_BUSY, &busy) && busy == 1) {
        walk_wait(it, "a script entry is starting (0x8030E714 is 1)");
        it->started = f;
        return;
    }
    if (f - it->started < it->id) return;
    if (!g_api->read32(LIST_HEAD, &v)) return;
    while (v && guard++ < 4096) {
        vol = v;
        if (!g_api->read32(v + 48, &v)) v = 0;
        if (!g_api->read16(vol + 20, &state) || (int16_t)state < 0 || !g_api->read32(vol + 8, &id)) continue;
        exit_ = id >= 6000 && id <= 6999;
        if (!exit_ && (id < 3000 || id > 4999)) continue;
        /* A save point opens the save menu, which is never the story's way on
         * and which nothing here answers: reach U4's fourth and fifth runs
         * stood in it for 30,000 frames and more. The hit-class table at
         * 0x802EE7C0 names both kinds: "walluv" (type 45, a116a's 4100,
         * a126a's 4411) and "wallmot" (type 44, a116g's 4100). */
        if (g_api->read16(vol + 18, &type) && (type == HIT_SAVE_POINT || type == HIT_SAVE_POINT_MOT)) continue;
        seen++;
        runs = seen_runs(map, id);
        if (!runs) continue;
        /* the fewest starts first; among equals, a talk or a check before an exit */
        if (*runs > best_runs || (*runs == best_runs && (exit_ > best_exit || (exit_ == best_exit && id >= best_id))))
            continue;
        args[0] = id;
        asked++;
        if (!g_api->call_guest(FN_ENTRY_LIVE, args, 1, NULL, 0, &live, NULL) || live != 1) continue;
        best_runs = *runs;
        best_id = id;
        best_vol = vol;
        best_exit = exit_;
    }
    it->started = f;
    if (!best_vol) {
        snprintf(why, sizeof why, "no live entry: %u volume(s) in the talk, check and exit ranges, %u asked", seen,
                 asked);
        walk_wait(it, why);
        return;
    }
    it->why[0] = '\0';
    args[0] = best_id;
    if (!g_api->call_guest(FN_ENTRY_START, args, 1, NULL, 0, &started, NULL)) return;
    g_api->write32(PRESS_STARTED, 1);
    g_api->write32(PRESS_VOLUME, best_vol);
    runs = seen_runs(map, best_id);
    if (runs) (*runs)++;
    it->last++;
    logf_("walk: a%03u%c entry %u started at frame %u (start %u here, %u in all)", (unsigned)(map >> 8),
          (char)(map & 0xFF), best_id, f, runs ? *runs : 0, it->last);
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

/* dump: once, at the first safe point at or after its frame, eight words a
 * line from the chain's address (the chain's last step is an address here,
 * not a word to read). */
static void dump(Item* it)
{
    uint32_t a = it->base, off, w[8];
    int i, k;
    it->state = 1;
    for (i = 0; i < it->nsteps; i++) {
        if (it->deref[i] && !g_api->read32(a, &a)) {
            logf_("dump %s: frame %u: the chain left RAM", it->text, g_api->frame());
            return;
        }
        a += (uint32_t)it->add[i];
    }
    logf_("dump %s: frame %u: %u bytes from %08X", it->text, g_api->frame(), it->id, a);
    for (off = 0; off < it->id; off += 32) {
        for (k = 0; k < 8; k++)
            if (off + 4u * (uint32_t)k >= it->id || !g_api->read32(a + off + 4u * (uint32_t)k, &w[k])) w[k] = 0;
        logf_("dump +%04X: %08X %08X %08X %08X %08X %08X %08X %08X", off, w[0], w[1], w[2], w[3], w[4], w[5], w[6],
              w[7]);
    }
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
        } else if (it->kind == ITEM_DUMP) {
            if (it->state == 0) dump(it);
        } else if (it->kind == ITEM_SAVE) {
            if (f <= it->to) save_point(it);
        } else if (it->kind == ITEM_WALK) {
            if (f <= it->to) walk(it);
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

/* An actor's position, act+56..64 (content-systems.md 2: the MLD entry's
 * +0x44 copied there), as "(x y z)"; 0 when it cannot be read. */
static int position(uint32_t act, char* out, size_t cap)
{
    float p[3];
    if (!g_api->read_f32(act + ACTOR_POS, &p[0]) || !g_api->read_f32(act + ACTOR_POS + 4, &p[1]) ||
        !g_api->read_f32(act + ACTOR_POS + 8, &p[2]))
        return 0;
    snprintf(out, cap, "(%.2f %.2f %.2f)", p[0], p[1], p[2]);
    return 1;
}

/* The object with this id, as op 154 finds it (fn_8015F1A0: its MLD entry's
 * actor, +36, or 0), and where it stands. Called at a map load, where
 * call_guest is allowed. */
static void actor_at(uint32_t id, char* out, size_t cap)
{
    uint32_t args[1], act = 0;
    char pos[64];
    snprintf(out, cap, "no actor");
    if (id == 0 || id >= 65535) return;
    args[0] = id;
    if (!g_api->call_guest(FN_FIND_OBJECT, args, 1, NULL, 0, &act, NULL) || !act) return;
    if (position(act, pos, sizeof pos))
        snprintf(out, cap, "actor %08X at %s", act, pos);
    else
        snprintf(out, cap, "actor %08X", act);
}

static void on_map_loaded(void* user, uint32_t map)
{
    uint32_t v, id, w[4], cls, player = 0;
    uint16_t type, state, nshapes;
    char where[96];
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
        actor_at(id, where, sizeof where);
        logf_("objects a%03u%c: %08X id %u type %u class %08X state %d shapes %d, shape 0: %08X %08X %08X %08X, %s",
              (unsigned)(map >> 8), (char)(map & 0xFF), v, id, type, cls, (int16_t)state, (int16_t)nshapes, w[0],
              w[1], w[2], w[3], where);
        n++;
        if (!g_api->read32(v + 48, &v)) break;
    }
    if (g_api->read32(PLAYER, &player) && player && position(player, where, sizeof where))
        logf_("objects a%03u%c: the player %08X at %s", (unsigned)(map >> 8), (char)(map & 0xFF), player, where);
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
        if (!parse_hold(item) && !parse_turn(item) && !parse_walk(item) && !parse_item(item)) {
            char line[160];
            snprintf(line, sizeof line, "lab: SOA_LAB item not understood: %.120s", whole);
            api->log(line);
            return 1;
        }
    }
    if (g_nitems) api->on_safe_point(on_safe_point, NULL);
    for (i = 0; i < g_nitems; i++) {
        if (g_items[i].kind != ITEM_TURN && g_items[i].kind != ITEM_STURN && g_items[i].kind != ITEM_ASSIST &&
            g_items[i].kind != ITEM_SAVE)
            continue;
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
