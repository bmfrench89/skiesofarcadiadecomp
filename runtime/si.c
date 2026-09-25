/*
 * Serial interface: the four controller ports, as the SDK's SI and PAD
 * drivers see them. One standard controller in port 1; nothing elsewhere.
 *
 * Two paths reach the controller. Direct transfers (SITransfer): the CPU
 * puts a command in the I/O buffer at 0xCC006480, writes SICOMCSR with
 * TSTART, and gets the response back in the same buffer with TCINT and an
 * SI interrupt. Polling (SIEnablePolling): once SIPOLL enables a channel
 * the hardware sends that channel's OUTBUF command every field and lands
 * the 8-byte reply in INBUFH/INBUFL with RDST set in SISR, optionally
 * interrupting. PADRead reads INBUF; reading INBUFL clears RDST.
 *
 * Input comes from the window when there is one, else from a script
 * (SOA_PAD="frame:buttons,..." -- e.g. "1700:start,1800:a+sup" holds
 * START from the game's frame 1700, and A with the stick up from 1800,
 * each for 10 frames; sup/sdown/sleft/sright move the stick; "3600:a@150"
 * presses A at frame 3600 and again every 150 frames after that).
 *
 * SOA_PAD_RECORD=<path> writes down what the port actually read, keyed by
 * the frame gx.c counts, and SOA_PAD_FILE=<path> plays that back in place
 * of any live or scripted input. A script can only say "these twelve
 * buttons, that stick, all the way"; a recording carries both sticks and
 * both triggers at the values the player gave them, which is the only way a
 * run long enough to reach a save point can be repeated. A replay ends the
 * run a little after the recording's last line (SOA_PAD_STOP), so a headless
 * replay needs no SOA_FRAMES guessed in advance.
 *
 *   0xCC006400 + 12*ch  SICnOUTBUF   0xCC006404 + 12*ch  SICnINBUFH   +8 INBUFL
 *   0xCC006430  SIPOLL      0xCC006434  SICOMCSR    0xCC006438  SISR
 *   0xCC00643C  SIEXILK     0xCC006480..0xCC0064FF  I/O buffer
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SI_BASE 0xCC006400u
#define COMCSR_TSTART 0x00000001u
#define COMCSR_RDSTINTMSK 0x08000000u
#define COMCSR_RDSTINT 0x10000000u
#define COMCSR_TCINTMSK 0x40000000u
#define COMCSR_TCINT 0x80000000u
#define SISR_WR 0x80000000u

#define BTN_LEFT 0x0001
#define BTN_RIGHT 0x0002
#define BTN_DOWN 0x0004
#define BTN_UP 0x0008
#define BTN_Z 0x0010
#define BTN_R 0x0020
#define BTN_L 0x0040
#define BTN_A 0x0100
#define BTN_B 0x0200
#define BTN_X 0x0400
#define BTN_Y 0x0800
#define BTN_START 0x1000
#define BTN_ALL 0x1F7Fu /* the twelve; exactly the bits pad_report() packs */

/* Named so a script can be written and a recording can be read back. The
 * order is the order a recording lists them in, so two recordings of the
 * same play diff cleanly. */
static const struct { const char* n; uint16_t b; } g_button_names[] = {
    {"a", BTN_A}, {"b", BTN_B}, {"x", BTN_X}, {"y", BTN_Y}, {"z", BTN_Z}, {"l", BTN_L}, {"r", BTN_R},
    {"start", BTN_START}, {"up", BTN_UP}, {"down", BTN_DOWN}, {"left", BTN_LEFT}, {"right", BTN_RIGHT},
};
#define BUTTON_NAMES (sizeof g_button_names / sizeof g_button_names[0])

static uint32_t g_outbuf[4], g_inbuf_hi[4], g_inbuf_lo[4];
static uint32_t g_poll, g_comcsr, g_sr, g_exilk;
static uint8_t g_iobuf[128];
static uint64_t g_transfers, g_polls, g_reads;
static int g_present[4] = {1, 0, 0, 0};

/* ---- scripted controller ------------------------------------------------ */

typedef struct { unsigned frame, every, hold; uint16_t buttons; uint8_t stick[2]; } PadEvent;
static PadEvent g_script[1024]; /* "F:buttons" once at frame F; "@N" again every N frames; "#H" held H frames */
static int g_script_n = -1;
#define HOLD_FRAMES 10

static uint16_t button_named(const char* name, size_t len)
{
    size_t i;
    for (i = 0; i < BUTTON_NAMES; i++)
        if (strlen(g_button_names[i].n) == len && strncmp(g_button_names[i].n, name, len) == 0)
            return g_button_names[i].b;
    return 0;
}

static void script_init(void)
{
    const char* env = getenv("SOA_PAD");
    const char* p = env;
    g_script_n = 0;
    while (p && *p && g_script_n < (int)(sizeof g_script / sizeof g_script[0])) {
        /* An item this cannot read ends the parse *at the item*, so the line
         * below names it. Each of these used to be accepted as an event that
         * pressed nothing, counted and silent: "START" or "strat" (unknown
         * name), "start ," (the space is part of the name), "1700:#" (held for
         * zero frames). tools/scenario.py rejects all of them, but SOA_PAD
         * typed by hand never passes through it. */
        const char* item = p;
        int named = 0, bad = 0;
        char* end;
        unsigned frame, every = 0, hold = HOLD_FRAMES;
        uint16_t buttons = 0;
        if (*p < '0' || *p > '9') break; /* strtoul would skip a space or take a sign */
        frame = (unsigned)strtoul(p, &end, 10);
        if (*end != ':') break;
        p = end + 1;
        uint8_t stick[2] = {128, 128};
        while (*p && *p != ',' && *p != '@' && *p != '#') {
            const char* q = p;
            size_t len;
            uint16_t b;
            while (*q && *q != ',' && *q != '+' && *q != '@' && *q != '#') q++;
            len = (size_t)(q - p);
            /* sup/sdown/sleft/sright move the main stick; everything else is a button */
            if (len == 3 && strncmp(p, "sup", 3) == 0) stick[1] = 255;
            else if (len == 5 && strncmp(p, "sdown", 5) == 0) stick[1] = 0;
            else if (len == 5 && strncmp(p, "sleft", 5) == 0) stick[0] = 0;
            else if (len == 6 && strncmp(p, "sright", 6) == 0) stick[0] = 255;
            else if ((b = button_named(p, len)) != 0) buttons |= b;
            else { bad = 1; break; }
            named = 1;
            p = *q == '+' ? q + 1 : q;
        }
        while (!bad && (*p == '@' || *p == '#')) {
            unsigned n;
            if (p[1] < '0' || p[1] > '9') { bad = 1; break; }
            n = (unsigned)strtoul(p + 1, &end, 10);
            if (*p == '@') every = n; else hold = n;
            p = end;
        }
        if (bad || !named || (*p && *p != ',')) { p = item; break; }
        g_script[g_script_n].frame = frame;
        g_script[g_script_n].every = every;
        g_script[g_script_n].hold = hold;
        g_script[g_script_n].buttons = buttons;
        g_script[g_script_n].stick[0] = stick[0];
        g_script[g_script_n].stick[1] = stick[1];
        g_script_n++;
        if (*p == ',') p++;
    }
    /* A script that parsed as nothing used to print nothing, which looks
     * exactly like the game ignoring the input. Say what was understood, and
     * where the parse gave up if it did not reach the end. */
    if (g_script_n) {
        fprintf(stderr, "[si] %d scripted controller events\n", g_script_n);
        if (p && *p) fprintf(stderr, "[si] SOA_PAD not understood from \"%s\" on; that part is ignored\n", p);
    } else if (env && *env) {
        fprintf(stderr, "[si] SOA_PAD=\"%s\" parsed no events, so nothing will be pressed "
                        "(expected frame:buttons,... e.g. 1700:start)\n", env);
    }
}

uint64_t irq_retrace_count(void);

unsigned gx_frame_count(void);

static uint16_t buttons_now(uint8_t stick[2])
{
    uint64_t frame = gx_frame_count(); /* the game's frames, not fields: deterministic against its logic */
    uint16_t b = 0;
    int i;
    stick[0] = stick[1] = 128;
    if (g_script_n < 0) script_init();
    for (i = 0; i < g_script_n; i++) {
        uint64_t rel;
        if (frame < g_script[i].frame) continue;
        rel = frame - g_script[i].frame;
        if (g_script[i].every) rel %= g_script[i].every;
        if (rel < g_script[i].hold) {
            b |= g_script[i].buttons;
            if (g_script[i].stick[0] != 128) stick[0] = g_script[i].stick[0];
            if (g_script[i].stick[1] != 128) stick[1] = g_script[i].stick[1];
        }
    }
    return b;
}

int window_pad(uint16_t* buttons, uint8_t stick[2], uint8_t cstick[2], uint8_t trig[2]);

/* ---- recording and replay ---------------------------------------------- */

/* What the port read, keyed by the frame gx.c counts, one line per change:
 *
 *   # soa pad recording v2 -- frame buttons stick cstick triggers, one line per change
 *   # config render=1 window=1 speed=1 scale=2 threads=- card=build/cards/slotA.raw:524288
 *   412 - 255,128 #r930
 *   470 a 255,128 #r1046
 *   471 a #r1048
 *   600 start #r1336
 *   1180 - 128,201 128,128 0,140 #r2632
 *   1181 - #r2634
 *   # 5 state changes over 1181 frames, 2634 retraces
 *
 * The fields are frame, buttons, main stick, C stick, triggers; "-" is no
 * buttons, "+" joins them, and trailing fields that are centred or zero are
 * left off. A frame with no line of its own holds the state the line before
 * it set, so only changes need writing: a minute of play is a few hundred
 * lines rather than three and a half thousand frames, and the result stays
 * small enough to read, annotate with # comments and cut by hand at the line
 * where the save point was reached -- which is how a usable recording will
 * actually be made, by playing loosely and then trimming. Text, one line per
 * event, is also the only format a diff can say anything useful about.
 *
 * The last line a run writes is the neutral state one frame past the last
 * read, so that a recording which ended with a button held does not hold it
 * forever on replay, and a # line after it gives the totals. Both are for
 * the person trimming; the replay adds its own neutral state when the file
 * does not end in one, which is what makes a Ctrl-C'd or hand-cut recording
 * safe to replay.
 *
 * What v2 adds, and why. A frame is the right key for the game's logic --
 * the guest consumes exactly one pad state per frame it presents -- but it is
 * not a clock: frames are produced as fast as the host manages while
 * everything the game waits on (retraces, DVD, the decrementer) runs on guest
 * time, and saved runs differ by 30% in retraces per frame between windowed
 * rendering and headless. So the same input arrives at a different point in
 * the game's own time, with no resynchronisation, and a long recording walks
 * off. Nothing here fixes that -- PLAN D4, a deterministic guest clock, is
 * the fix -- but v2 makes it visible and refuses to be quiet about it:
 *
 *   #r<n> on each line is irq.c's retrace count when that state was read, so
 *   a replay can say how far it has drifted from the run that recorded it,
 *   in guest time, rather than walking into the wrong menu silently;
 *   # config records the switches that change the frame rate and the memory
 *   card the run started from, and a replay says so when they differ.
 *
 * Both are comments: a v1 recording still replays, a hand-written line still
 * works, and a hand-edited one only loses the drift check for that line. */
typedef struct { uint16_t buttons; uint8_t stick[2], cstick[2], trig[2]; } PadState;
static const PadState PAD_NEUTRAL = {0, {128, 128}, {128, 128}, {0, 0}};

static unsigned g_pad_frame; /* the frame of the most recent controller read */
static int g_pad_seen;

static int pad_same(const PadState* a, const PadState* b)
{
    return a->buttons == b->buttons && a->stick[0] == b->stick[0] && a->stick[1] == b->stick[1] &&
           a->cstick[0] == b->cstick[0] && a->cstick[1] == b->cstick[1] &&
           a->trig[0] == b->trig[0] && a->trig[1] == b->trig[1];
}

static FILE* g_rec;
static char g_rec_path[512];
static int g_rec_tried, g_rec_done;
static PadState g_rec_last;
static uint64_t g_rec_changes;

static const char* env_or(const char* name, const char* dflt)
{
    const char* v = getenv(name);
    return v && *v ? v : dflt;
}

static long long file_size(const char* path)
{
    FILE* f = fopen(path, "rb");
    long long n = -1;
    if (!f) return -1;
    if (fseek(f, 0, SEEK_END) == 0) n = ftell(f);
    fclose(f);
    return n;
}

/* The state of the run that is not input but decides what the input means.
 * The switches ahead of the card change how many frames the port gets
 * through per second of guest time, which is what a recording is keyed by
 * and the one thing it cannot carry with it; the card is
 * the one piece of the game's own state a recording does not carry, and it
 * is the one that will bite -- replay a recording that reached a save point
 * and the second run starts at a title screen with a Continue entry the
 * first run did not have, so frame one of the menu picks the wrong thing.
 * The default path mirrors exi.c's; keep the two in step. */
static char g_cfg_extra[320];

/* What else a recording depends on, from outside this file: the mods main.c
 * loaded (mod_describe). Only a run with mods has any, so a recording made
 * without them reads exactly as it always did. */
void si_set_config_extra(const char* extra)
{
    snprintf(g_cfg_extra, sizeof g_cfg_extra, "%s", extra ? extra : "");
}

static void pad_config(char* out, size_t cap)
{
    const char* card = env_or("SOA_CARD", "build/cards/slotA.raw");
    snprintf(out, cap, "render=%s window=%s speed=%s scale=%s threads=%s card=%s:%lld%s%s",
             env_or("SOA_RENDER", "-"), env_or("SOA_WINDOW", "-"), env_or("SOA_SPEED", "1"),
             env_or("SOA_SCALE", "2"), env_or("SOA_THREADS", "-"), card, file_size(card),
             g_cfg_extra[0] ? " " : "", g_cfg_extra);
}

/* An hour of play is not worth an overwrite: a second run with the same
 * SOA_PAD_RECORD writes alongside the first rather than over it. */
static FILE* pad_record_create(const char* path)
{
    FILE* f = fopen(path, "r");
    int n;
    if (!f) {
        snprintf(g_rec_path, sizeof g_rec_path, "%s", path);
        return fopen(path, "w");
    }
    fclose(f);
    for (n = 1; n < 100; n++) {
        snprintf(g_rec_path, sizeof g_rec_path, "%s.%d", path, n);
        f = fopen(g_rec_path, "r");
        if (!f) {
            fprintf(stderr, "[pad] %s is already there, so this run records to %s instead\n", path,
                    g_rec_path);
            return fopen(g_rec_path, "w");
        }
        fclose(f);
    }
    return NULL;
}

static void pad_record_open(void)
{
    const char* path = getenv("SOA_PAD_RECORD");
    char cfg[768];
    g_rec_tried = 1;
    g_rec_last = PAD_NEUTRAL;
    if (!path || !*path) return;
    g_rec = pad_record_create(path);
    if (!g_rec) {
        fprintf(stderr, "[pad] cannot write %s; this run records nothing\n", path);
        return;
    }
    pad_config(cfg, sizeof cfg);
    fprintf(g_rec, "# soa pad recording v2 -- frame buttons stick cstick triggers, one line per change\n");
    fprintf(g_rec, "# config %s\n", cfg);
    fflush(g_rec);
    fprintf(stderr, "[pad] recording controller input to %s (%s)\n", g_rec_path, cfg);
}

static int pad_buttons_str(char* out, size_t cap, uint16_t b)
{
    const char* sep = "";
    int n = 0;
    size_t i;
    if (!b) return snprintf(out, cap, "-");
    for (i = 0; i < BUTTON_NAMES; i++)
        if (b & g_button_names[i].b) {
            n += snprintf(out + n, cap - (size_t)n, "%s%s", sep, g_button_names[i].n);
            sep = "+";
        }
    return n;
}

static void pad_record(const PadState* st, unsigned frame)
{
    char btn[64], opt[64], line[256];
    int n = 0;
    int trig = st->trig[0] || st->trig[1];
    int cstick = trig || st->cstick[0] != 128 || st->cstick[1] != 128;
    int stick = cstick || st->stick[0] != 128 || st->stick[1] != 128;
    /* si_report writes the totals from whichever thread is stopping the run
     * while this one may still be playing, so nothing may follow them. */
    if (g_rec_done || pad_same(st, &g_rec_last)) return;
    pad_buttons_str(btn, sizeof btn, st->buttons);
    opt[0] = '\0';
    if (stick) n += snprintf(opt + n, sizeof opt - (size_t)n, " %u,%u", (unsigned)st->stick[0], (unsigned)st->stick[1]);
    if (cstick) n += snprintf(opt + n, sizeof opt - (size_t)n, " %u,%u", (unsigned)st->cstick[0], (unsigned)st->cstick[1]);
    if (trig) n += snprintf(opt + n, sizeof opt - (size_t)n, " %u,%u", (unsigned)st->trig[0], (unsigned)st->trig[1]);
    snprintf(line, sizeof line, "%u %s%s #r%llu\n", frame, btn, opt,
             (unsigned long long)irq_retrace_count());
    /* One fputs, not five fprintfs: the CRT locks a FILE for the length of a
     * call, so a line built in a buffer and written whole cannot be spliced
     * into the middle of another thread's line. It could before, and the two
     * halves the loader then rejected were the last two states of the run --
     * exactly the ones a recording is made for. */
    fputs(line, g_rec);
    /* Flushed per line because the way a recording ends is the player closing
     * the window, and every stop path in this port leaves through _exit(),
     * which does not flush stdio. A line still in a buffer is a line the
     * player has to play again; at a few changes a second the cost is none. */
    fflush(g_rec);
    g_rec_last = *st;
    g_rec_changes++;
}

typedef struct { unsigned frame; uint64_t retrace; PadState st; } PadFrame;
static PadFrame* g_play;
static int g_play_n, g_play_cap, g_play_i = -1;
static int g_play_tried, g_play_done;
static const char* g_play_path;
static uint64_t g_play_late;                      /* states delivered a read later than the recording had them */
static long long g_play_drift, g_play_drift_max;  /* retraces ahead of (+) or behind (-) the recording */

/* Whitespace-separated fields, with a # anywhere ending the line. */
static char* pad_token(char** p)
{
    char* s = *p;
    char* t;
    while (*s == ' ' || *s == '\t') s++;
    if (!*s || *s == '\n' || *s == '\r' || *s == '#') { *p = s; return NULL; }
    for (t = s; *t && *t != ' ' && *t != '\t' && *t != '\n' && *t != '\r'; t++) {}
    if (*t) *t++ = '\0';
    *p = t;
    return s;
}

static int pad_parse_buttons(const char* s, uint16_t* out)
{
    uint16_t b = 0;
    if (strcmp(s, "-") == 0) { *out = 0; return 1; }
    while (*s) {
        const char* q = s;
        uint16_t one;
        while (*q && *q != '+') q++;
        one = button_named(s, (size_t)(q - s));
        if (!one) return 0;
        b |= one;
        s = *q == '+' ? q + 1 : q;
    }
    *out = b;
    return 1;
}

static int pad_parse_pair(const char* s, uint8_t v[2])
{
    char* end;
    unsigned long x = strtoul(s, &end, 10), y;
    if (end == s || *end != ',') return 0;
    s = end + 1;
    y = strtoul(s, &end, 10);
    if (end == s || *end || x > 255 || y > 255) return 0;
    v[0] = (uint8_t)x;
    v[1] = (uint8_t)y;
    return 1;
}

/* 1 parsed, 0 malformed, -1 nothing on the line. */
static int pad_parse_line(char* line, PadFrame* e)
{
    uint8_t* pairs[3];
    char* p = line;
    char* tok = pad_token(&p);
    char* end;
    int i;
    if (!tok) return -1;
    e->st = PAD_NEUTRAL;
    e->retrace = 0;
    e->frame = (unsigned)strtoul(tok, &end, 10);
    if (end == tok || *end) return 0;
    tok = pad_token(&p); /* a bare frame number is the neutral state */
    if (tok) {
        if (!pad_parse_buttons(tok, &e->st.buttons)) return 0;
        pairs[0] = e->st.stick;
        pairs[1] = e->st.cstick;
        pairs[2] = e->st.trig;
        for (i = 0; i < 3; i++) {
            tok = pad_token(&p);
            if (!tok) break;
            if (!pad_parse_pair(tok, pairs[i])) return 0;
        }
        if (tok && pad_token(&p)) return 0; /* a sixth field is a typo, not input */
    }
    /* The retrace count rides in the line's comment, "#r930", so that it is
     * optional in both directions: v1 recordings and hand-written lines have
     * none and replay exactly as they did, and a line someone edited by hand
     * loses only its own drift check. */
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '#') {
        const char* q = p + 1;
        while (*q == ' ') q++;
        if (*q == 'r' && q[1] >= '0' && q[1] <= '9') e->retrace = strtoull(q + 1, NULL, 10);
    }
    return 1;
}

static int pad_play_push(const PadFrame* e)
{
    if (g_play_n == g_play_cap) {
        int cap = g_play_cap ? g_play_cap * 2 : 256;
        PadFrame* grown = (PadFrame*)realloc(g_play, (size_t)cap * sizeof *grown);
        if (!grown) return 0;
        g_play = grown;
        g_play_cap = cap;
    }
    g_play[g_play_n++] = *e;
    return 1;
}

static void pad_replay_load(void)
{
    const char* path = getenv("SOA_PAD_FILE");
    const char* script;
    char line[1024], was[768], now[768];
    unsigned lineno = 0, bad = 0;
    FILE* f;
    g_play_tried = 1;
    was[0] = '\0';
    if (!path || !*path) return;
    f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "[pad] cannot read %s; SOA_PAD_FILE is ignored and nothing replays\n", path);
        return;
    }
    while (fgets(line, sizeof line, f)) {
        PadFrame e;
        int ok;
        lineno++;
        if (strncmp(line, "# config ", 9) == 0) {
            size_t n = strlen(line);
            while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = '\0';
            snprintf(was, sizeof was, "%s", line + 9);
            continue;
        }
        ok = pad_parse_line(line, &e);
        if (ok < 0) continue;
        if (ok && g_play_n && e.frame < g_play[g_play_n - 1].frame) {
            /* Frames only go forward, so an earlier one is a hand edit that
             * went wrong. Replaying it in file order would hide every line
             * between, silently, which is the one failure a person trimming a
             * recording cannot see. */
            ok = 0;
        }
        if (!ok) {
            if (bad < 5)
                fprintf(stderr, "[pad] %s:%u is not \"frame buttons [stick] [cstick] [triggers]\" "
                                "in frame order; that line is ignored\n", path, lineno);
            bad++;
            continue;
        }
        if (!pad_play_push(&e)) {
            fprintf(stderr, "[pad] out of memory at %s:%u; the rest of it is ignored\n", path, lineno);
            break;
        }
    }
    fclose(f);
    g_play_path = path;
    if (bad > 5) fprintf(stderr, "[pad] and %u more lines of %s ignored\n", bad - 5, path);
    if (!g_play_n) {
        fprintf(stderr, "[pad] %s holds no usable lines, so nothing will be pressed\n", path);
        return;
    }
    /* A run that ended in Ctrl-C, a kill or a crash never wrote its release
     * line, and a file cut by hand at the save point almost never ends on
     * one: the last state would then be held for the rest of the replay, with
     * a button down. Letting go here rather than at the writer covers all
     * four cases at once and costs the writer nothing. */
    if (!pad_same(&g_play[g_play_n - 1].st, &PAD_NEUTRAL)) {
        PadFrame e;
        e.frame = g_play[g_play_n - 1].frame + 1;
        e.retrace = 0;
        e.st = PAD_NEUTRAL;
        if (pad_play_push(&e))
            fprintf(stderr, "[pad] %s ends with input still held, so a neutral state is added at "
                            "frame %u; the replay lets go of it there\n", path, e.frame);
    }
    fprintf(stderr, "[pad] replaying %d state changes from %s, last at frame %u; it is the whole "
                    "input for this run, a window's keyboard and gamepad included\n",
            g_play_n, path, g_play[g_play_n - 1].frame);
    /* The recording is not self-contained and this is where that is cheapest
     * to notice: the switches below decide how many frames the port gets
     * through per second of guest time, and the card decides what the game's
     * own menus contain. Replay in the configuration you recorded in. */
    pad_config(now, sizeof now);
    if (was[0] && strcmp(was, now) != 0)
        fprintf(stderr, "[pad] recorded with %s\n[pad] replaying with %s -- a difference in speed, "
                        "rendering or thread count changes how many frames pass per second of guest "
                        "time, and a different memory card changes what the game's menus hold, so "
                        "the input can arrive in the wrong place\n", was, now);
    else if (!was[0])
        fprintf(stderr, "[pad] %s records no configuration (it predates v2), so nothing can say "
                        "whether this run is set up like the one that made it\n", path);
    /* Setting both and having one silently do nothing is the trap a scenario
     * author falls into, so name it rather than leaving it to be inferred. */
    script = getenv("SOA_PAD");
    if (script && *script) fprintf(stderr, "[pad] SOA_PAD is set as well, and is ignored\n");
}

void gx_set_frame_limit(unsigned frames);

/* Two seconds of guest time. Less than that is the ordinary jitter of a
 * frame landing either side of a retrace; more is the replay and the
 * recording being in different places in the game. */
#define DRIFT_WARN 120

static void pad_replay_drift(const PadFrame* e)
{
    long long drift, mag;
    if (!e->retrace) return; /* v1, or a hand-written line */
    drift = (long long)irq_retrace_count() - (long long)e->retrace;
    g_play_drift = drift;
    mag = drift < 0 ? -drift : drift;
    if (mag > g_play_drift_max) g_play_drift_max = mag;
    if (mag > DRIFT_WARN) {
        static int said;
        if (!said) {
            said = 1;
            fprintf(stderr, "[pad] frame %u: the recording read this state at retrace %llu and this "
                            "run is at %llu -- %lld retraces, %.1f seconds of guest time, %s. Frames "
                            "are not a clock: the game waits on guest time and the port produces "
                            "frames as fast as it can, so from here on the input arrives at a "
                            "different point in the game than it did when it was played (PLAN D4 "
                            "is the fix; replaying in the configuration it was recorded in is the "
                            "workaround)\n",
                    e->frame, (unsigned long long)e->retrace,
                    (unsigned long long)irq_retrace_count(), drift, (double)mag / 60.0,
                    drift > 0 ? "further on" : "further back");
        }
    }
}

/* The recording has run out. Everything after it would be a neutral
 * controller in front of a game nobody is driving, so end the run -- through
 * gx.c's frame limit, which flushes the renderer and prints the report the
 * same way SOA_FRAMES does. The grace is for what the last input started: a
 * save takes a second of frames to write itself. */
static void pad_replay_end(unsigned frame)
{
    const char* env = getenv("SOA_PAD_STOP");
    const char* frames = getenv("SOA_FRAMES");
    unsigned grace = env ? (unsigned)atoi(env) : 120u;
    unsigned limit = frames ? (unsigned)atoi(frames) : 0u;
    unsigned target = frame + grace;
    g_play_done = 1;
    if (!grace) {
        fprintf(stderr, "[pad] the recording ran out at frame %u; SOA_PAD_STOP=0, so the run carries "
                        "on with the controller neutral\n", frame);
        return;
    }
    if (limit && limit <= target) {
        fprintf(stderr, "[pad] the recording ran out at frame %u; SOA_FRAMES=%u ends the run first\n",
                frame, limit);
        return;
    }
    fprintf(stderr, "[pad] the recording ran out at frame %u; the run stops at frame %u, which is "
                    "%u frames of grace for whatever the last input started (SOA_PAD_STOP=n changes "
                    "it, 0 keeps the run going). The \"[boot] frames done (SOA_FRAMES)\" line that "
                    "ends the run is this stop, not a limit you set.\n", frame, target, grace);
    gx_set_frame_limit(target);
}

/* The state the recording puts at this frame, or 0 when there is no
 * recording. The frame counter only goes forward, so the lookup is a cursor
 * rather than a search, and a frame the recording says nothing about keeps
 * what the last line set -- that is what makes writing only changes safe. */
static int pad_replay(PadState* st, unsigned frame)
{
    if (!g_play_tried) pad_replay_load();
    if (!g_play_n) return 0;
    /* One entry per read, not every entry that is due. A frame the guest
     * never polled would let a while-loop step over that frame's entry
     * without anyone reading it; stepping once hands it over a read late
     * instead -- a shift rather than a loss -- and counts it. The guest polls
     * at least twice per frame it presents in every saved run, so the cursor
     * catches up inside the same frame. */
    if (g_play_i + 1 < g_play_n && g_play[g_play_i + 1].frame <= frame) {
        g_play_i++;
        pad_replay_drift(&g_play[g_play_i]);
        if (g_play_i + 1 < g_play_n && g_play[g_play_i + 1].frame <= frame) g_play_late++;
    } else if (!g_play_done && g_play_i + 1 >= g_play_n && frame > g_play[g_play_n - 1].frame) {
        pad_replay_end(frame);
    }
    *st = g_play_i < 0 ? PAD_NEUTRAL : g_play[g_play_i].st;
    return 1;
}

/* The change line the saved runs are read by. It used to live in
 * buttons_now() and print the buttons alone, which is why the stick in those
 * runs is invisible in their own logs even where the script moved it. It now
 * covers everything the port read, from whatever source, and still prints
 * exactly the old line when only buttons happened, so old logs still compare
 * against new ones. */
static void pad_log(const PadState* st, unsigned frame)
{
    static PadState last;
    static int have;
    if (!have) { last = PAD_NEUTRAL; have = 1; }
    if (pad_same(st, &last)) return;
    last = *st;
    fprintf(stderr, "[si] frame %u (retrace %llu): buttons %04X", frame,
            (unsigned long long)irq_retrace_count(), st->buttons);
    if (st->stick[0] != 128 || st->stick[1] != 128)
        fprintf(stderr, " stick %u,%u", (unsigned)st->stick[0], (unsigned)st->stick[1]);
    if (st->cstick[0] != 128 || st->cstick[1] != 128)
        fprintf(stderr, " cstick %u,%u", (unsigned)st->cstick[0], (unsigned)st->cstick[1]);
    if (st->trig[0] || st->trig[1])
        fprintf(stderr, " triggers %u,%u", (unsigned)st->trig[0], (unsigned)st->trig[1]);
    fputc('\n', stderr);
}

/* A recording being replayed is the whole input. Otherwise live input from
 * the window when there is one, and the script either way -- SOA_PAD
 * normally means no window at all (main.c decides that), but an explicit
 * SOA_WINDOW=1 alongside it should watch the script run, not silently drop
 * it. */
static void pad_sample(PadState* st, unsigned frame)
{
    *st = PAD_NEUTRAL;
    if (pad_replay(st, frame)) return;
    if (window_pad(&st->buttons, st->stick, st->cstick, st->trig)) {
        uint8_t sstick[2] = {128, 128};
        st->buttons |= buttons_now(sstick); /* the person's input and the script's, together */
        if (sstick[0] != 128) st->stick[0] = sstick[0];
        if (sstick[1] != 128) st->stick[1] = sstick[1];
    } else {
        st->buttons = buttons_now(st->stick);
    }
    st->buttons &= BTN_ALL; /* the report carries twelve buttons and nothing else */
}

/* The 8-byte controller report: buttons, main stick, C stick, triggers. */
static void pad_report(uint8_t out[8])
{
    static PadState latched;
    static unsigned latch_frame;
    static int latch_valid;
    unsigned frame = gx_frame_count();
    PadState st;
    if (!g_rec_tried) pad_record_open();
    /* The port reads the pad several times a frame -- the field poll, and any
     * direct transfer -- and the keyboard and the gamepad each answer with
     * whatever is true at that instant. A recording keyed by the frame can
     * only keep one of those answers, so while recording, the first read of a
     * frame is that frame's input and the rest are given the same thing. That
     * is the difference between a replay that is exact and one that is close.
     * It is not done otherwise: a frame can last seconds across a load, and
     * freezing live input for that long is a worse bargain than it sounds.
     * The cost while recording is real and worth knowing before a session: a
     * press made and released inside a frame that lasts seconds reaches
     * neither the guest nor the file. One state per frame cannot express
     * that, so the fix is shorter frames (PLAN D4), not a different latch. */
    if (g_rec && latch_valid && latch_frame == frame) {
        st = latched;
    } else {
        pad_sample(&st, frame);
        latched = st;
        latch_frame = frame;
        latch_valid = 1;
    }
    if (g_rec) pad_record(&st, frame);
    pad_log(&st, frame);
    g_pad_frame = frame;
    g_pad_seen = 1;
    out[0] = (uint8_t)((st.buttons >> 8) & 0x1F);   /* 0 0 1? S Y X B A -- bit 5 (use origin) clear */
    out[1] = (uint8_t)(0x80 | (st.buttons & 0x7F)); /* 1 L R Z U D R L */
    out[2] = st.stick[0]; out[3] = st.stick[1];     /* main stick */
    out[4] = st.cstick[0]; out[5] = st.cstick[1];   /* C stick */
    out[6] = st.trig[0]; out[7] = st.trig[1];       /* triggers */
}

/* ---- transfers -------------------------------------------------------- */

static void run_command(unsigned chan)
{
    uint8_t cmd = g_iobuf[0];
    uint8_t rep[10];
    unsigned n = 0;
    if (!g_present[chan]) { /* no device: the transfer errors out */
        g_sr |= 0x08000000u >> (8 * chan); /* NOREP */
        g_comcsr |= 0x20000000u;           /* COMERR */
        return;
    }
    switch (cmd) {
    case 0x00: case 0xFF: /* ID */
        rep[0] = 0x09; rep[1] = 0x00; rep[2] = 0x00; n = 3;
        break;
    case 0x41: case 0x42: /* origin / calibrate: 10 bytes, sticks centred */
        pad_report(rep);
        rep[8] = 0; rep[9] = 0;
        n = 10;
        break;
    case 0x40: /* direct poll */
        pad_report(rep);
        n = 8;
        break;
    default:
        pad_report(rep);
        n = 8;
        break;
    }
    memcpy(g_iobuf, rep, n);
    g_transfers++;
}

/* Called once per field by the interrupt code: hardware polling. */
void si_poll(void)
{
    unsigned chan;
    for (chan = 0; chan < 4; chan++) {
        uint8_t rep[8];
        if (!((g_poll >> (7 - chan)) & 1)) continue;
        if (!g_present[chan]) { g_sr |= 0x08000000u >> (8 * chan); continue; } /* NOREP */
        pad_report(rep);
        g_inbuf_hi[chan] = ((uint32_t)rep[0] << 24) | ((uint32_t)rep[1] << 16) | ((uint32_t)rep[2] << 8) | rep[3];
        g_inbuf_lo[chan] = ((uint32_t)rep[4] << 24) | ((uint32_t)rep[5] << 16) | ((uint32_t)rep[6] << 8) | rep[7];
        g_sr |= 0x20000000u >> (8 * chan); /* RDST */
        g_polls++;
    }
    if (g_sr & 0x20202020u) g_comcsr |= COMCSR_RDSTINT;
}

int si_irq_pending(void)
{
    return ((g_comcsr & COMCSR_TCINT) && (g_comcsr & COMCSR_TCINTMSK)) ||
           ((g_comcsr & COMCSR_RDSTINT) && (g_comcsr & COMCSR_RDSTINTMSK));
}

int si_read(CpuState* s, uint32_t ea, unsigned size, uint64_t* out)
{
    (void)s;
    if (ea < SI_BASE || ea >= SI_BASE + 0x100 || size != 4) return 0;
    if (ea >= SI_BASE + 0x80) {
        unsigned off = ea - SI_BASE - 0x80;
        *out = ((uint32_t)g_iobuf[off] << 24) | ((uint32_t)g_iobuf[off + 1] << 16) | ((uint32_t)g_iobuf[off + 2] << 8) | g_iobuf[off + 3];
        return 1;
    }
    switch (ea - SI_BASE) {
    case 0x00: case 0x0C: case 0x18: case 0x24: *out = g_outbuf[(ea - SI_BASE) / 12]; return 1;
    case 0x04: case 0x10: case 0x1C: case 0x28: *out = g_inbuf_hi[(ea - SI_BASE) / 12]; g_reads++; return 1;
    case 0x08: case 0x14: case 0x20: case 0x2C: {
        unsigned chan = (ea - SI_BASE) / 12;
        *out = g_inbuf_lo[chan];
        g_sr &= ~(0x20000000u >> (8 * chan)); /* reading INBUFL clears RDST */
        if (!(g_sr & 0x20202020u)) g_comcsr &= ~COMCSR_RDSTINT;
        return 1;
    }
    case 0x30: *out = g_poll; return 1;
    case 0x34: *out = g_comcsr; return 1;
    case 0x38: *out = g_sr; return 1;
    case 0x3C: *out = g_exilk; return 1;
    default: *out = 0; return 1;
    }
}

int si_write(CpuState* s, uint32_t ea, unsigned size, uint64_t v)
{
    uint32_t w = (uint32_t)v;
    (void)s;
    if (ea < SI_BASE || ea >= SI_BASE + 0x100 || size != 4) return 0;
    if (ea >= SI_BASE + 0x80) {
        unsigned off = ea - SI_BASE - 0x80;
        g_iobuf[off] = (uint8_t)(w >> 24); g_iobuf[off + 1] = (uint8_t)(w >> 16);
        g_iobuf[off + 2] = (uint8_t)(w >> 8); g_iobuf[off + 3] = (uint8_t)w;
        return 1;
    }
    switch (ea - SI_BASE) {
    case 0x00: case 0x0C: case 0x18: case 0x24: g_outbuf[(ea - SI_BASE) / 12] = w; return 1;
    case 0x30: g_poll = w; return 1;
    case 0x34: {
        /* TCINT and RDSTINT are write-one-to-clear; the masks and the
         * transfer parameters are stored; TSTART runs the transfer now. */
        uint32_t keep = g_comcsr & (COMCSR_TCINT | COMCSR_RDSTINT | 0x20000000u);
        if (w & COMCSR_TCINT) keep &= ~COMCSR_TCINT;
        if (w & COMCSR_RDSTINT) keep &= ~COMCSR_RDSTINT;
        g_comcsr = (w & ~(COMCSR_TCINT | COMCSR_RDSTINT | COMCSR_TSTART | 0x20000000u)) | keep;
        if (w & COMCSR_TSTART) {
            unsigned chan = (w >> 1) & 3;
            g_comcsr &= ~0x20000000u;
            run_command(chan);
            g_comcsr |= COMCSR_TCINT; /* complete: TSTART reads back clear */
        }
        return 1;
    }
    case 0x38:
        /* WR latches the OUTBUF commands (nothing to do); error bits are w1c */
        g_sr &= ~(w & 0x0F0F0F0Fu);
        return 1;
    case 0x3C: g_exilk = w; return 1;
    default: return 1;
    }
}

void si_report(void)
{
    unsigned frames = g_pad_seen ? g_pad_frame + 1 : 0;
    fprintf(stderr, "[si] %llu direct transfers, %llu polls, %llu input reads; poll reg %08X\n",
            (unsigned long long)g_transfers, (unsigned long long)g_polls, (unsigned long long)g_reads, g_poll);
    if (g_rec) {
        char totals[128];
        if (g_pad_seen && !pad_same(&g_rec_last, &PAD_NEUTRAL)) {
            PadState idle = PAD_NEUTRAL;
            pad_record(&idle, g_pad_frame + 1); /* let go of whatever was held */
        }
        /* This runs on whichever thread is stopping the run -- the window's,
         * when the player closes it -- while the CPU thread may still be
         * reading the pad and writing lines. Each writes its line with one
         * locked call, so they cannot interleave inside a line, and the flag
         * below keeps the other thread from starting one after the totals --
         * all but the instant it may already be inside pad_record, where the
         * worst that lands is a well-formed line after the summary. Closing
         * the file would not be safe here, and _exit() is two calls away in
         * every path that gets here. */
        g_rec_done = 1;
        snprintf(totals, sizeof totals, "# %llu state changes over %u frames, %llu retraces\n",
                 (unsigned long long)g_rec_changes, frames,
                 (unsigned long long)irq_retrace_count());
        fputs(totals, g_rec);
        fflush(g_rec);
        fprintf(stderr, "[pad] recorded %llu state changes over %u frames to %s\n",
                (unsigned long long)g_rec_changes, frames, g_rec_path);
    }
    if (g_play_n) {
        fprintf(stderr, "[pad] replayed %d of %d state changes over %u frames from %s\n",
                g_play_i + 1, g_play_n, frames, g_play_path);
        if (g_play_i + 1 < g_play_n) {
            int left = g_play_n - (g_play_i + 1);
            fprintf(stderr, "[pad] the run stopped at frame %u, so %d line%s from frame %u on never played\n",
                    g_pad_frame, left, left == 1 ? "" : "s", g_play[g_play_i + 1].frame);
        }
        /* The two numbers that say whether this replay was the same run as
         * the recording. Drift is the honest one: it is guest time, which is
         * what the game itself measures, and a replay that ends with it near
         * zero really did keep step. */
        if (g_play_drift_max)
            fprintf(stderr, "[pad] drift against the recording: %lld retraces at the end (%.1f s of "
                            "guest time), %lld at the worst\n",
                    g_play_drift, (double)g_play_drift / 60.0, g_play_drift_max);
        if (g_play_late)
            fprintf(stderr, "[pad] %llu state%s arrived a read later than the recording had %s, "
                            "because more than one was due at the same read\n",
                    (unsigned long long)g_play_late, g_play_late == 1 ? "" : "s",
                    g_play_late == 1 ? "it" : "them");
    }
}
