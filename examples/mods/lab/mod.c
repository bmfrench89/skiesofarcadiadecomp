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
 *                  Busy also means what stops the player's own A press
 *                  (fn_80118204: flag 1087, 0x80347508 at 1, the field's mode
 *                  12), a message window on screen, and the map script's main
 *                  thread anywhere but its loop (a cutscene the loop called,
 *                  named in the log). An event that holds
 *                  the field a minute with its window unmoved (a shop's menu)
 *                  gets B every 70 frames until the field is free; never a
 *                  ship battle (a 5xx stage), whose menu B would answer.
 *   story:LO-HI    the walker's sense of where the story goes (reach U4): the
 *                  file SOA_LAB_STORY names holds `sct.py --story`'s lines,
 *                  each entry's flags set and maps warped to. The story's next
 *                  flag is the lowest in LO..HI still clear that a line sets
 *                  and the lines reach from here (a story's flags are not set
 *                  in order); every map's distance in warps to one that sets
 *                  it is found, and the walker prefers, before its own order,
 *                  an entry that sets it, then one that warps nearer, each for
 *                  two starts while that flag is the aim, and two more 9,000
 *                  frames after the last (a talk may open it); an aim not
 *                  reached in 30,000 frames is passed over. Where the
 *                  map itself sets it (its loop, on conditions), the walker
 *                  stays and talks. The aim and the distance are logged. A
 *                  line "MAP hookN wX..." is a warp in MAP's script that waits
 *                  for flag N, which no script sets (the world map's: the ship
 *                  reaching a spot); ranked before every live entry, the
 *                  walker sets N in its place, twice at most per aim.
 *   assist:F-G:EVERY  A, for two frames every EVERY frames, only in a battle,
 *                  at its results screen (the field's state 4, 0x80311AEC),
 *                  in a ship battle where its menu waits for A (a 5xx stage,
 *                  the ship input word at state 6, step 0; sturn plays the
 *                  crew's wheels),
 *                  or while the field's message window holds a choice (state
 *                  6 at 0x80346E64, its task at 0x80346E4C, as mods/autotext
 *                  reads them): what the walker needs where a pad script's A
 *                  every 150 frames would talk to whatever stands nearest.
 *   flag:MAP:N     once, at the first safe point where map MAP (004a; 099f is
 *                  the world map at that story stage) runs with no event,
 *                  set flag N, its word read and written back with the bit
 *                  in: what stands in for something the game sets it for and
 *                  the walker cannot do. The world map's loop starts part C's
 *                  first cutscene when flag 1766 is set (me099f, 01E20), which
 *                  a fldHakken object in a099f.mld carries: the ship sailing
 *                  there. Logged with the word before and after.
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
 *                  In a ship battle (a 5xx stage) the player's ship is held
 *                  the same way: its record at 0x80308EF8 that the driver
 *                  reads B[261] from, and the ship object's HP.
 *   finish:F-G:FRAMES  in a battle in frames F to G that has gone FRAMES
 *                  frames, every enemy still standing (slots 4 to 11, the
 *                  same test) is held at 1 HP from then on (a heal is put
 *                  back), so the game's own next blows and its victory end
 *                  it; logged, with the put-backs counted at the end. For a
 *                  party below the story's level: the part-select cards start
 *                  Vyse at level 1, and two Royal Guards outlasted 70,000
 *                  frames, and healed back up from 1 HP once.
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
    ITEM_SAVE,
    ITEM_FLAG,
    ITEM_FINISH
};

#define STORY_FLAG_WORDS 0x80310B3Cu /* flag n: bit n & 31 of the word +4 * (n >> 5) (story-flags.md 1) */
#define FLAG_COUNT 27328u            /* 854 words */


/* The field's message window, as mods/autotext reads it: its task (0 when
 * there is none) and its state, 6 being a choice. */
#define WINDOW_TASK 0x80346E4Cu
#define WINDOW_STATE 0x80346E64u
#define WINDOW_CHOICE 6
/* The task is there from each map load; state 1 waits for a message and 255
 * is a warp's teardown, 2 to 8 a window opening, writing, waiting, scrolling,
 * choosing or closing (FINDINGS "P11's spike") */
#define WINDOW_OPENING 2
#define WINDOW_LAST_OPEN 8
#define FIELD_RESULTS 4u /* the field's state while a battle's results screen waits */
#define PLAYER_HELD 0x80347508u /* r13-29208: the player's A press does nothing while it is 1 */
/* The map script's main thread (fn_80212130): its code at *0x8030CEA0, its
 * next instruction at *0x8030CEA4, which fn_80210550 points at an entry it
 * starts and which the tick points back at "loop" (r2-15588) once it reaches
 * a RET (op 12); the entries, 20 bytes each, an offset (its low two bits not
 * part of it) and a name of 16, at *0x8030D6C0, *0x8030D6C4 of them. */
#define SCRIPT_CODE 0x8030CEA0u
#define SCRIPT_PC 0x8030CEA4u
#define SCRIPT_INDEX 0x8030D6C0u
#define SCRIPT_COUNT 0x8030D6C4u
#define OP_RET 12u
#define MODE_KIND 0x80346C3Cu   /* r13-31460: with 2 here, fn_8009763C is the s8 of ... */
#define MODE_WORD 0x80302F18u   /* ... the s16 here, and 12 stops the A press too */
#define HIT_SAVE_POINT 45u     /* a volume's hit type (u16 at +18): "walluv", a save point */
#define HIT_SAVE_POINT_MOT 44u /* "wallmot", the other save point */

static int assist_wanted(void); /* below, beside the walker; on_pad calls it first */
static int story_load(const char* path); /* below, beside the walker; parse_story calls it first */
static uint32_t story_map_word(const char* s); /* likewise, for parse_item's flag: */

/* The walker's memory: how often each map's entry has been started, and how
 * often while the story aimed at flag `aim`. */
#define MAX_SEEN 1024
typedef struct {
    uint32_t map, id, runs, aim, tries, at; /* at: the frame of the last start */
} Seen;
static Seen g_seen[MAX_SEEN];
static int g_nseen;

/* story: where the story goes, from `sct.py --story`'s lines in the file
 * SOA_LAB_STORY names ("004a M03005 w250a": a map, an entry, the flags it
 * sets and the maps it warps to, through every entry it calls). A map word
 * is the API's map(), number << 8 | letter; the world map's letter is the
 * story's (B[6]), so every 099x is one place to the distances. */
#define STORY_LINES 4096
#define STORY_WORDS 16384
#define STORY_MAPS 512
#define STORY_FAR 0xFFFFu
#define STORY_TRIES 2u /* starts of one entry per aim before it stops counting */
/* ... until this many frames after its last: a002e's M06100 sets 122 only
 * once a talk there has set 2548, and reach U4's part-C walker had spent
 * both its tries on it before that talk; it never went back */
#define STORY_RETRY_FRAMES 9000u
typedef struct {
    uint32_t map, id; /* id: n for an entry named M%05d (the walker's), else 0 */
    uint32_t hook;    /* n for a line named hookN: its warps wait for flag n, which no script sets */
    uint32_t at;      /* its sets, then its warps, in g_story_words */
    uint16_t nsets, nwarps;
} StoryLine;
static StoryLine g_story[STORY_LINES];
static uint32_t g_story_words[STORY_WORDS];
static int g_nstory, g_story_on;
static uint32_t g_story_nwords, g_story_lo, g_story_hi;
static uint32_t g_story_maps[STORY_MAPS];
static uint16_t g_story_dist[STORY_MAPS];
static int g_story_nmaps;
static uint32_t g_story_aim, g_story_aim_map; /* what the last log named */
#define STORY_FLAG_LIMIT 1024u                /* sct.py's STORY_FLAGS */
static uint8_t g_story_settable[STORY_FLAG_LIMIT];
/* An aim not reached in this many frames is passed over, for the rest of the
 * run: a flag set only in a branch the run did not take, or on a later visit
 * (part C's 123: a005a's talk 3005 sets it only once flag 409 is set, a part I
 * flag), would otherwise hold the walker for good. */
#define STORY_AIM_PATIENCE 30000u
static uint8_t g_story_passed[STORY_FLAG_LIMIT];
static uint32_t g_story_aim_now, g_story_aim_from;

/* A ship battle's command input (reach U3, found by RAM captures at two
 * crew members' inputs and confirmed by peeks through a fight): the word at
 * 0x80306738 holds the menu's state (byte 0), its step (byte 1) and the crew
 * member choosing (byte 2); state 9, step 2 is a member's wheel, ready. */
#define SHIP_INPUT 0x80306738u
#define SHIP_READY_STATE 9u
#define SHIP_READY_STEP 2u
#define SHIP_WAIT_STATE 6u /* the menu waits for A, unless a member's wheel is open */

static int g_sturn_playing; /* an sturn sequence is under way: assist keeps off */
static int g_walk_backout;  /* the walker found the field held too long: B presses */
#define WALK_STUCK 1800u    /* frames an event may hold the field before B (a minute) */

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
    uint32_t window; /* walk: the message window's task and state when last read */
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
    } else if (strcmp(s, "flag") == 0) {
        char* end;
        it->kind = ITEM_FLAG;
        if (!(it->base = story_map_word(a)) || !parse_u32(b, &end, &it->id) || *end || it->id >= FLAG_COUNT)
            return 0;
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
    if (g_walk_backout && frame % (PRESS_HOLD + PRESS_GAP) < PRESS_HOLD) {
        pad->buttons = SOA_PAD_B;
        pad->stick[0] = pad->stick[1] = 128;
        return;
    }
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

/* "story:LO-HI": the window of story flags, and the file SOA_LAB_STORY names */
static int parse_story(char* s)
{
    Item window;
    if (strncmp(s, "story:", 6) != 0) return 0;
    if (g_story_on || !parse_frames(s + 6, &window) || window.to >= STORY_FLAG_LIMIT) return 0;
    if (!story_load(getenv("SOA_LAB_STORY"))) return 0;
    g_story_lo = window.from;
    g_story_hi = window.to;
    g_story_on = 1;
    return 1;
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

static Seen* seen_of(uint32_t map, uint32_t id)
{
    int i;
    for (i = 0; i < g_nseen; i++)
        if (g_seen[i].map == map && g_seen[i].id == id) return &g_seen[i];
    if (g_nseen == MAX_SEEN) return NULL;
    memset(&g_seen[g_nseen], 0, sizeof g_seen[0]);
    g_seen[g_nseen].map = map;
    g_seen[g_nseen].id = id;
    return &g_seen[g_nseen++];
}

/* Whether an entry (or a hook) still counts toward `aim` at frame f: not yet
 * tried STORY_TRIES times at this aim, or not for STORY_RETRY_FRAMES. */
static int story_fresh(const Seen* s, uint32_t aim, uint32_t f)
{
    return !s || s->aim != aim || s->tries < STORY_TRIES || f - s->at >= STORY_RETRY_FRAMES;
}

/* Counts a start toward `aim`, the tries begun again after a long gap. */
static void story_count(Seen* s, uint32_t aim, uint32_t f)
{
    if (!s) return;
    if (s->aim != aim || f - s->at >= STORY_RETRY_FRAMES) s->tries = 0;
    s->aim = aim;
    s->tries++;
    s->at = f;
}

/* "004a" as a map word; 0 if it is not one */
static uint32_t story_map_word(const char* s)
{
    if (strlen(s) != 4 || s[0] < '0' || s[0] > '9' || s[1] < '0' || s[1] > '9' || s[2] < '0' || s[2] > '9' ||
        s[3] < 'a' || s[3] > 'z')
        return 0;
    return (uint32_t)((s[0] - '0') * 100 + (s[1] - '0') * 10 + (s[2] - '0')) << 8 | (uint32_t)s[3];
}

/* The distances' place for a map, every world map (099x) being one; -1 for
 * a map no line names, unless `add` (the file's reading) makes it a place. */
static int story_node(uint32_t map, int add)
{
    int i;
    if (map >> 8 == 99) map = 99u << 8 | 'a';
    for (i = 0; i < g_story_nmaps; i++)
        if (g_story_maps[i] == map) return i;
    if (!add || g_story_nmaps == STORY_MAPS) return -1;
    g_story_maps[g_story_nmaps] = map;
    return g_story_nmaps++;
}

/* The next word of a line, cut in place; NULL at its end. */
static char* next_word(char** p)
{
    char* w = *p + strspn(*p, " \t\r\n");
    if (!*w) return NULL;
    *p = w + strcspn(w, " \t\r\n");
    if (**p) *(*p)++ = '\0';
    return w;
}

/* One line of the file into g_story; 0 if it does not parse or there is no
 * room. A blank line or a '#' comment is 1 and adds nothing. */
static int story_line(char* p)
{
    StoryLine* l;
    char *tok = next_word(&p), *name;
    if (!tok || tok[0] == '#') return 1;
    if (g_nstory == STORY_LINES) return 0;
    l = &g_story[g_nstory];
    memset(l, 0, sizeof *l);
    name = next_word(&p);
    if (!name || !(l->map = story_map_word(tok)) || story_node(l->map, 1) < 0) return 0;
    if (name[0] == 'M' && strlen(name) == 6 && strspn(name + 1, "0123456789") == 5)
        l->id = (uint32_t)strtoul(name + 1, NULL, 10);
    if (strncmp(name, "hook", 4) == 0 && name[4] && strspn(name + 4, "0123456789") == strlen(name + 4)) {
        l->hook = (uint32_t)strtoul(name + 4, NULL, 10);
        if (!l->hook || l->hook >= FLAG_COUNT) return 0;
    }
    l->at = g_story_nwords;
    while ((tok = next_word(&p)) != NULL) {
        uint32_t v = 0;
        char* end;
        if (g_story_nwords == STORY_WORDS) return 0;
        if (tok[0] == 's' && !l->nwarps && parse_u32(tok + 1, &end, &v) && !*end && v < STORY_FLAG_LIMIT)
            l->nsets++, g_story_settable[v] = 1;
        else if (tok[0] == 'w' && (v = story_map_word(tok + 1)) != 0)
            l->nwarps++;
        else
            return 0;
        g_story_words[g_story_nwords++] = v;
    }
    g_nstory++;
    return 1;
}

/* Reads the file; 0 (said why) if it cannot be read or a line does not parse. */
static int story_load(const char* path)
{
    FILE* f = path && *path ? fopen(path, "r") : NULL;
    char line[4096];
    int n = 0, ok = 1;
    if (!f) {
        logf_("story: SOA_LAB_STORY names no file that can be read (%.150s)", path ? path : "unset");
        return 0;
    }
    while (ok && fgets(line, sizeof line, f)) {
        n++;
        ok = strchr(line, '\n') != NULL || feof(f); /* a line longer than the buffer is refused */
        if (ok) ok = story_line(line);
    }
    fclose(f);
    if (!ok) {
        logf_("story: %.150s line %d is not \"MAP ENTRY sN.. wMAP..\", or passes %d lines or %d words", path, n,
              STORY_LINES, STORY_WORDS);
        return 0;
    }
    logf_("story: %d line(s), %d place(s) from %.150s", g_nstory, g_story_nmaps, path);
    return 1;
}

static void story_dists(uint32_t aim);
static uint32_t story_dist(uint32_t map);

/* The flag the story wants next, its distances measured: in the window, the
 * lowest flag still clear that a line sets and that the lines can reach from
 * `map`; else the lowest clear one a line sets (unreachable, logged so); 0
 * when there is none. Not the lowest above the highest set: part C sets 124
 * in a209a (me209ac25) before 113, 115 and 117, which come after it. */
static uint32_t story_aim(uint32_t map)
{
    uint32_t f, first = 0;
    for (f = g_story_lo; f <= g_story_hi; f++) {
        if (!g_story_settable[f] || g_story_passed[f] || g_api->story_flag(f)) continue;
        if (!first) first = f;
        story_dists(f);
        if (story_dist(map) != STORY_FAR) return f;
    }
    if (first) story_dists(first);
    return first;
}

static int story_sets(const StoryLine* l, uint32_t flag)
{
    uint32_t k;
    for (k = 0; k < l->nsets; k++)
        if (g_story_words[l->at + k] == flag) return 1;
    return 0;
}

/* Each place's distance in warps to one where a line sets `aim`: 0 there,
 * then back along every line's warps until nothing shortens. */
static void story_dists(uint32_t aim)
{
    int i, changed = 1;
    uint32_t k;
    for (i = 0; i < g_story_nmaps; i++) g_story_dist[i] = STORY_FAR;
    for (i = 0; i < g_nstory; i++)
        if (story_sets(&g_story[i], aim)) g_story_dist[story_node(g_story[i].map, 0)] = 0;
    while (changed) {
        changed = 0;
        for (i = 0; i < g_nstory; i++) {
            const StoryLine* l = &g_story[i];
            int from = story_node(l->map, 0);
            for (k = 0; k < l->nwarps; k++) {
                int to = story_node(g_story_words[l->at + l->nsets + k], 0);
                if (to >= 0 && g_story_dist[to] != STORY_FAR && g_story_dist[to] + 1u < g_story_dist[from]) {
                    g_story_dist[from] = (uint16_t)(g_story_dist[to] + 1u);
                    changed = 1;
                }
            }
        }
    }
}

static uint32_t story_dist(uint32_t map)
{
    int n = story_node(map, 0);
    return n < 0 ? STORY_FAR : g_story_dist[n];
}

/* An entry's rank toward `aim`: 0 if its lines set it; else 1 + the distance
 * of the nearest place it warps to that is nearer than this map; STORY_FAR if
 * neither (in the place that sets it, the walker stays and talks). */
static uint32_t story_score(uint32_t map, uint32_t id, uint32_t aim)
{
    uint32_t best = STORY_FAR, here = story_dist(map), k, d;
    int i;
    for (i = 0; i < g_nstory; i++) {
        const StoryLine* l = &g_story[i];
        if (l->map != map || l->id != id) continue;
        if (story_sets(l, aim)) return 0;
        for (k = 0; k < l->nwarps; k++) {
            d = story_dist(g_story_words[l->at + l->nsets + k]);
            if (d < here && d + 1 < best) best = d + 1;
        }
    }
    return best;
}

/* This map's best hook toward `aim`: a line hookN here with flag N clear,
 * warping nearer than this map, tried fewer than STORY_TRIES times at this
 * aim; its rank (1 + where it warps) in *rank, else STORY_FAR and NULL. The
 * walker's tries of a hook are kept as entry 0x80000000 | N. */
static const StoryLine* story_hook(uint32_t map, uint32_t aim, uint32_t* rank)
{
    uint32_t here = story_dist(map), k, d;
    const StoryLine* best = NULL;
    Seen* s;
    int i;
    *rank = STORY_FAR;
    for (i = 0; i < g_nstory; i++) {
        const StoryLine* l = &g_story[i];
        if (l->map != map || !l->hook || g_api->story_flag(l->hook)) continue;
        s = seen_of(map, 0x80000000u | l->hook);
        if (!story_fresh(s, aim, g_api->frame())) continue;
        for (k = 0; k < l->nwarps; k++) {
            d = story_dist(g_story_words[l->at + l->nsets + k]);
            if (d < here && d + 1 < *rank) {
                *rank = d + 1;
                best = l;
            }
        }
    }
    return best;
}

/* Logs the aim and how far this map is from it, each time either changes. */
static void story_note(uint32_t map, uint32_t aim)
{
    int i, n = 0;
    char where[64] = "";
    if (aim == g_story_aim && map == g_story_aim_map) return;
    g_story_aim = aim;
    g_story_aim_map = map;
    if (!aim) {
        logf_("story: no flag in %u-%u is left for a line to set", g_story_lo, g_story_hi);
        return;
    }
    for (i = 0; i < g_nstory && n < 3; i++) {
        char one[8];
        snprintf(one, sizeof one, "%03u%c", g_story[i].map >> 8, (char)(g_story[i].map & 0xFF));
        /* 355a is the developers' part-select room, which sets every part's
         * flags and which no warp reaches: not a place the story goes */
        if (story_sets(&g_story[i], aim) && !strstr(where, one) && g_story[i].map != (355u << 8 | 'a')) {
            size_t len = strlen(where);
            snprintf(where + len, sizeof where - len, "%s%s", n++ ? " " : "", one);
        }
    }
    if (!where[0]) snprintf(where, sizeof where, "only the part-select room");
    if (story_dist(map) == STORY_FAR)
        logf_("story: aiming at flag %u (set in %s); no warp the lines know leads there from a%03u%c", aim, where,
              map >> 8, (char)(map & 0xFF));
    else
        logf_("story: aiming at flag %u (set in %s); a%03u%c is %u warp(s) away", aim, where, map >> 8,
              (char)(map & 0xFF), story_dist(map));
}

/* The entry of the map's script that holds offset `off`, the last found kept. */
static struct {
    uint32_t code, lo, hi;
    char name[17];
} g_where;

static int script_entry(uint32_t code, uint32_t off)
{
    uint32_t index = 0, count = 0, i, o, lo = 0, hi = 0xFFFFFFFFu, w;
    int found = -1, k;
    if (g_where.code == code && off >= g_where.lo && off < g_where.hi) return 1;
    if (!g_api->read32(SCRIPT_INDEX, &index) || !g_api->read32(SCRIPT_COUNT, &count) || !index || count > 4096)
        return 0;
    for (i = 0; i < count; i++) {
        if (!g_api->read32(index + 20u * i, &o)) return 0;
        o &= ~3u;
        if (o <= off && (found < 0 || o >= lo)) {
            lo = o;
            found = (int)i;
        } else if (o > off && o < hi) {
            hi = o;
        }
    }
    if (found < 0) return 0;
    for (k = 0; k < 4; k++) {
        if (!g_api->read32(index + 20u * (uint32_t)found + 4u + 4u * (uint32_t)k, &w)) return 0;
        g_where.name[4 * k] = (char)(w >> 24);
        g_where.name[4 * k + 1] = (char)(w >> 16);
        g_where.name[4 * k + 2] = (char)(w >> 8);
        g_where.name[4 * k + 3] = (char)w;
    }
    g_where.name[16] = '\0';
    g_where.code = code;
    g_where.lo = lo;
    g_where.hi = hi;
    return 1;
}

/* Whether the map script's main thread is busy, with the entry it runs in
 * `why`: anywhere but its "loop" or a RET. a116d's loop clears flag 1087 and
 * then calls its second cutscene, which has stretches with no window and the
 * player not held; reach U4's part-C walker started an exit in one, twice,
 * and cut off the warp the loop makes when the cutscene returns. */
static int script_busy(char* why, size_t cap)
{
    uint32_t code = 0, pc = 0, op = 0;
    if (!g_api->read32(SCRIPT_CODE, &code) || !g_api->read32(SCRIPT_PC, &pc) || !code || pc < code) return 0;
    if (g_api->read32(pc, &op) && op == OP_RET) return 0;
    if (!script_entry(code, pc - code) || strcmp(g_where.name, "loop") == 0) return 0;
    snprintf(why, cap, "the map's script runs %s", g_where.name);
    return 1;
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
    uint32_t best_runs = 0xFFFFFFFFu, live = 0, started = 0, busy = 0, asked = 0, seen = 0;
    uint32_t aim = 0, score, best_score = 0xFFFFFFFFu;
    uint16_t state, type = 0;
    int guard = 0, best_exit = 1, exit_;
    Seen* s;
    char why[96];
    if (g_api->scene() != 6 || g_api->field_state() != 8) {
        snprintf(why, sizeof why, "the field is not running (scene %u, state %u)", g_api->scene(),
                 g_api->field_state());
        walk_wait(it, why);
        it->started = f;
        it->member = 0;
        g_walk_backout = 0;
        return;
    }
    if (g_api->story_flag(FLAG_EVENT)) {
        uint32_t task = 0, window;
        uint16_t wstate = 0;
        walk_wait(it, "an event runs (flag 1087)");
        it->started = f;
        /* it->member: one more than the frame this event began (0: none), or
         * last moved. A menu nothing answers (a shop: reach U4's part-C run
         * stood in the Mystery Merchant's for 190,000 frames) holds the field
         * for good; past WALK_STUCK frames the pad filter presses B, which
         * backs out of the game's menus. A cutscene whose dialogue moves on
         * (the message window's task or state changing) is not stuck: the
         * Grand Fortress's held the field longer than that, and B at a choice
         * there would answer it. */
        g_api->read32(WINDOW_TASK, &task);
        g_api->read16(WINDOW_STATE, &wstate);
        window = task ^ (uint32_t)wstate << 24;
        /* A ship battle (a 5xx stage) holds 1087 throughout, its menu is not
         * the message window, and B there answers the crew's wheel: reach
         * U4's part-C run pressed it into a501a's from 111689. Never stuck. */
        if (!it->member || window != it->window || ((map >> 8) >= 500 && (map >> 8) <= 583)) {
            if (g_walk_backout && it->member) logf_("walk: the event moved on at frame %u: no more B", f);
            g_walk_backout = 0;
            it->member = f + 1;
            it->window = window;
        }
        if (f + 1 - it->member >= WALK_STUCK && !g_walk_backout) {
            g_walk_backout = 1;
            logf_("walk: an event has held the field, its window unmoved, since frame %u: pressing B every %u frames",
                  it->member - 1, PRESS_HOLD + PRESS_GAP);
        }
        return;
    }
    if (g_walk_backout) logf_("walk: the field is free again at frame %u", f);
    it->member = 0;
    g_walk_backout = 0;
    {
        /* The player's own A press and touch (fn_80118204, 80118228-8011824C)
         * do nothing while flag 1087 is set, while fn_8009763C() is 12 (the
         * s16 at r13-31460 = 0x80346C3C is 2 and the low byte of the s16 at
         * 0x80302F18 is 12), or while r13-29208 = 0x80347508 is 1. And a
         * message window on screen is a scene still talking: a116d's second
         * cutscene clears 1087 while its dialogue runs, and reach U4's part-C
         * walker, starting an exit then, cut off the cutscene's own warp. */
        uint32_t held = 0, task = 0;
        uint16_t kind = 0, mode = 0, wstate = 0;
        const char* busy_why = NULL;
        if (g_api->read32(PLAYER_HELD, &held) && held == 1)
            busy_why = "the player is held (0x80347508 is 1)";
        else if (g_api->read16(MODE_KIND, &kind) && (int16_t)kind == 2 && g_api->read16(MODE_WORD, &mode) &&
                 (int8_t)(mode & 0xFF) == 12)
            busy_why = "the field's mode is 12 (fn_8009763C)";
        else if (g_api->read32(WINDOW_TASK, &task) && task && g_api->read16(WINDOW_STATE, &wstate) &&
                 (int16_t)wstate >= WINDOW_OPENING && (int16_t)wstate <= WINDOW_LAST_OPEN)
            busy_why = "a message window is open";
        else if (script_busy(why, sizeof why))
            busy_why = why;
        if (busy_why) {
            walk_wait(it, busy_why);
            it->started = f;
            return;
        }
    }
    if (g_api->read32(ENTRY_BUSY, &busy) && busy == 1) {
        walk_wait(it, "a script entry is starting (0x8030E714 is 1)");
        it->started = f;
        return;
    }
    if (f - it->started < it->id) return;
    if (!g_api->read32(LIST_HEAD, &v)) return;
    if (g_story_on) {
        aim = story_aim(map);
        if (aim != g_story_aim_now) {
            g_story_aim_now = aim;
            g_story_aim_from = f;
        } else if (aim && f - g_story_aim_from >= STORY_AIM_PATIENCE) {
            logf_("story: flag %u aimed at since frame %u and not set: passed over from frame %u", aim,
                  g_story_aim_from, f);
            g_story_passed[aim] = 1;
            aim = story_aim(map);
            g_story_aim_now = aim;
            g_story_aim_from = f;
        }
        story_note(map, aim);
    }
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
        s = seen_of(map, id);
        if (!s) continue;
        /* With story: the nearer the story's next flag first, an entry counting
         * toward it for STORY_TRIES starts at most. Then the fewest starts;
         * among equals, a talk or a check before an exit; then the lower id. */
        score = aim && story_fresh(s, aim, f) ? story_score(map, id, aim) : STORY_FAR;
        if (score > best_score ||
            (score == best_score && (s->runs > best_runs || (s->runs == best_runs && (exit_ > best_exit ||
                                                                                     (exit_ == best_exit && id >= best_id))))))
            continue;
        args[0] = id;
        asked++;
        if (!g_api->call_guest(FN_ENTRY_LIVE, args, 1, NULL, 0, &live, NULL) || live != 1) continue;
        best_score = score;
        best_runs = s->runs;
        best_id = id;
        best_vol = vol;
        best_exit = exit_;
    }
    it->started = f;
    if (aim) {
        /* A hook ranked before every live entry: its flag is what the game sets
         * when the ship reaches a spot on the world map, which the walker cannot
         * sail to. Set here in its place, and the map's own loop goes on. */
        uint32_t hook_rank, addr, w = 0;
        const StoryLine* h = story_hook(map, aim, &hook_rank);
        if (h && hook_rank < best_score) {
            addr = STORY_FLAG_WORDS + 4u * (h->hook >> 5);
            if (!g_api->read32(addr, &w)) return;
            g_api->write32(addr, w | 1u << (h->hook & 31));
            s = seen_of(map, 0x80000000u | h->hook);
            if (s) s->runs++;
            story_count(s, aim, f);
            it->last++;
            it->why[0] = '\0';
            logf_("walk: a%03u%c hook: flag %u set at frame %u, in place of the arrival this map's script waits for "
                  "(the story's rank toward flag %u: %u)",
                  (unsigned)(map >> 8), (char)(map & 0xFF), h->hook, f, aim, hook_rank);
            return;
        }
    }
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
    s = seen_of(map, best_id);
    if (s) s->runs++;
    story_count(s, aim, f);
    it->last++;
    if (best_score == STORY_FAR)
        snprintf(why, sizeof why, "%s", g_story_on ? "; the story's rank: none" : "");
    else
        snprintf(why, sizeof why, "; the story's rank toward flag %u: %u", aim, best_score);
    logf_("walk: a%03u%c entry %u started at frame %u (start %u here, %u in all%s)", (unsigned)(map >> 8),
          (char)(map & 0xFF), best_id, f, s ? s->runs : 0, it->last, why);
}

/* "hold-hp:F-G": no third field; or "finish:F-G:FRAMES". */
static int parse_hold(char* s)
{
    Item* it;
    char *frames, *end;
    int finish = strncmp(s, "finish:", 7) == 0;
    if ((!finish && strncmp(s, "hold-hp:", 8) != 0) || g_nitems == MAX_ITEMS) return 0;
    it = &g_items[g_nitems];
    memset(it, 0, sizeof *it);
    snprintf(it->text, sizeof it->text, "%s", s);
    it->kind = finish ? ITEM_FINISH : ITEM_HOLD_HP;
    if (finish) {
        frames = strchr(s + 7, ':');
        if (!frames) return 0;
        *frames++ = '\0';
        if (!parse_frames(s + 7, it) || !parse_u32(frames, &end, &it->id) || *end || !it->id) return 0;
    } else if (!parse_frames(s + 8, it)) {
        return 0;
    }
    g_nitems++;
    return 1;
}

/* One safe point of finish: it->started is one more than the frame this
 * battle began (0: no battle), it->state 1 once its enemies are held at 1 HP
 * (logged then), it->last how many times one was put back to 1. A part card
 * made by the developers' part select starts Vyse at level 1 (reach U4's
 * part-C run: Vyse 420 HP, two Royal Guards still up after 70,000 frames of
 * attacks; brought to 1 HP once, they healed back up, effect D2403300 29
 * times in 84 rounds); this ends a fight that party cannot, through the
 * game's own blows and victory, and says so. */
#define ENEMY_SLOTS 12u /* 0x80309DE4[4..11] are the enemies (battle-system.md 1) */
static void finish_battle(Item* it)
{
    uint32_t f = g_api->frame(), slot, actor, status, hp, n = 0;
    if (g_api->scene() != SCENE_BATTLE) {
        if (it->state) logf_("finish: the battle ended by frame %u; %u enemy HP put back to 1", f, it->last);
        it->started = 0;
        it->state = 0;
        it->last = 0;
        return;
    }
    if (!it->started) it->started = f + 1;
    if (f + 1 - it->started < it->id) return;
    for (slot = 4; slot < ENEMY_SLOTS; slot++) {
        if (!g_api->read32(ACTORS + 4 * slot, &actor) || !actor) continue;
        if (!g_api->read32(actor + ACTOR_STATUS, &status) || (status & STATUS_OUT)) continue;
        if (!g_api->read32(actor + ACTOR_HP, &hp) || (int32_t)hp <= 1) continue;
        g_api->write32(actor + ACTOR_HP, 1);
        n++;
    }
    if (!it->state)
        logf_("finish: the battle from frame %u has gone %u frames: %u enemy(s) held at 1 HP from now, so the "
              "game's own next blows end it",
              it->started - 1, it->id, n);
    else
        it->last += n;
    it->state = 1;
}


/* A ship battle's HP, held the same way (battle-system.md 7): the driver
 * fn_80129DD0 finds the player's ship among *0x8034729C records of 20 bytes
 * at 0x80308EF8, the one whose *(*(rec)+36)+378 halfword is the id at
 * 0x803472B0 (8012A0BC-8012A0C8), and takes B[261], the HP % the script's
 * _LOSE tests, from its +8 HP and +12 maximum; the turn's applier writes
 * the ship object's +24 (HP, +20 its maximum, *(*0x8034727C + 32)). Reach
 * U4's part-C run sank the Little Jack against a Valuan Cruiser at a501a. */
#define SHIP_RECORDS 0x80308EF8u
#define SHIP_RECORD_COUNT 0x8034729Cu
#define SHIP_PLAYER_ID 0x803472B0u
#define SHIP_STATE 0x8034727Cu
static uint32_t top_up(uint32_t hp_at, uint32_t max_at)
{
    uint32_t hp = 0, max = 0;
    if (!g_api->read32(hp_at, &hp) || !g_api->read32(max_at, &max)) return 0;
    if ((int32_t)hp <= 0 || (int32_t)hp >= (int32_t)max) return 0;
    g_api->write32(hp_at, max);
    return 1;
}

static uint32_t hold_ship(void)
{
    uint32_t n = 0, count = 0, id = 0, i, rec, p, q, s = 0, ship = 0;
    uint16_t rec_id;
    if (g_api->read32(SHIP_RECORD_COUNT, &count) && count <= 8 && g_api->read32(SHIP_PLAYER_ID, &id))
        for (i = 0; i < count; i++) {
            rec = SHIP_RECORDS + 20u * i;
            if (g_api->read32(rec, &p) && p && g_api->read32(p + 36, &q) && q && g_api->read16(q + 378, &rec_id) &&
                rec_id == id)
                n += top_up(rec + 8, rec + 12);
        }
    if (g_api->read32(SHIP_STATE, &s) && s && g_api->read32(s + 32, &ship) && ship) n += top_up(ship + 24, ship + 20);
    return n;
}

/* One safe point of hold-hp: tops up the standing party, or in a ship battle
 * (a 5xx stage) the player's ship; it->last counts this battle's top-ups,
 * logged when the battle ends. */
static void hold_hp(Item* it)
{
    uint32_t slot, actor, status, hp, max, stage = g_api->map() >> 8;
    if (g_api->scene() == 6 && stage >= 500 && stage <= 583) {
        if (it->state == 0) {
            logf_("hold-hp: a ship battle from frame %u: the player's ship's HP is held at its maximum",
                  g_api->frame());
            it->state = 1;
        }
        it->last += hold_ship();
        return;
    }
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

/* One safe point of flag:MAP:N: on MAP's running field with no event, flag
 * N set (its word read, its bit or'd in, written back), once. */
static void set_flag(Item* it)
{
    uint32_t addr = STORY_FLAG_WORDS + 4u * (it->id >> 5), w = 0;
    if (g_api->map() != it->base || g_api->scene() != 6 || g_api->field_state() != 8 ||
        g_api->story_flag(FLAG_EVENT) || !g_api->read32(addr, &w))
        return;
    it->state = 1;
    if (w & (1u << (it->id & 31))) {
        logf_("flag: %u was already set on a%03u%c at frame %u", it->id, it->base >> 8, (char)(it->base & 0xFF),
              g_api->frame());
        return;
    }
    g_api->write32(addr, w | 1u << (it->id & 31));
    logf_("flag: %u set on a%03u%c at frame %u (%08X: %08X -> %08X), in place of what the game sets it for", it->id,
          it->base >> 8, (char)(it->base & 0xFF), g_api->frame(), addr, w, w | 1u << (it->id & 31));
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
        } else if (it->kind == ITEM_FINISH) {
            if (f <= it->to) finish_battle(it);
        } else if (it->kind == ITEM_DUMP) {
            if (it->state == 0) dump(it);
        } else if (it->kind == ITEM_SAVE) {
            if (f <= it->to) save_point(it);
        } else if (it->kind == ITEM_WALK) {
            if (f <= it->to) walk(it);
        } else if (it->kind == ITEM_FLAG) {
            if (it->state == 0) set_flag(it);
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
        if (!parse_hold(item) && !parse_turn(item) && !parse_walk(item) && !parse_story(item) && !parse_item(item)) {
            char line[160];
            snprintf(line, sizeof line, "lab: SOA_LAB item not understood: %.120s", whole);
            api->log(line);
            return 1;
        }
    }
    if (g_nitems) api->on_safe_point(on_safe_point, NULL);
    for (i = 0; i < g_nitems; i++) {
        if (g_items[i].kind != ITEM_TURN && g_items[i].kind != ITEM_STURN && g_items[i].kind != ITEM_ASSIST &&
            g_items[i].kind != ITEM_SAVE && g_items[i].kind != ITEM_WALK)
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
