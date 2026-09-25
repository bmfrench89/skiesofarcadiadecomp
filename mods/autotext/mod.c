/*
 * autotext (docs/PLAN-GAMEPLAY-MODS.md P11; the comfort-pack spec 3.5):
 * dialogue that turns its own pages.
 *
 * The field's message window is a task the game stores at 0x80346E4C once
 * per map load (0 for the two frames of a warp); its context, 184 bytes,
 * hangs off task + 36, and the context's first halfword is the window's
 * flags. Its state, an s16 at 0x80346E64, is rewritten at the end of every
 * run of the task and -- unlike 0x80346E60, the draw's pointer, which the
 * draw stores 0 back into -- still holds at a controller read. State 4 is a
 * complete page waiting for A; 6 is a choice box; flag 0x10 marks a choice
 * -- on a page, one after a choice -- and 0x40 a page that scrolls itself,
 * and the game turns both kinds of page on its own countdown (FINDINGS
 * "P11's spike", "P11").
 *
 * So, in the field only: when the state is 4 and neither flag is set, wait
 * SOA_AUTOTEXT frames, then press A -- two frames down, two up -- once, and
 * arm again only after the state has left 4. Never in a choice or in any
 * other state, and never over the person's own A or B: the person wins.
 *
 *     SOA_AUTOTEXT unset or 0   off
 *     SOA_AUTOTEXT=on or 1      45 frames, a second and a half
 *     SOA_AUTOTEXT=N            N frames, for N of 2 or more
 *
 * Hold-to-skip (P11b): while the host button LB is held (CH1; the
 * keyboard's Tab), it presses A in states 3 and 4 -- text still appearing,
 * and a complete page -- two frames down and two up for as long as LB is
 * held, never in a choice box and never on a page the game turns itself.
 * A press in state 3 shows the page at once, the next turns it. Host
 * buttons are not in recordings yet, so a replay does not skip; the first
 * skip says so, once.
 *
 * SOA_AUTOTEXT_TEST=press-in-choice also presses in state 6: the mutation
 * the Done runs, never for play. soa.ini's `autotext` sets the same switch.
 * Built beside its mod.ini by `python tools/recompile.py --link`.
 */
#include "soa_mod.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#define WINDOW_TASK 0x80346E4Cu  /* u32: the message window's task, 0 when there is none */
#define WINDOW_STATE 0x80346E64u /* s16: 4 a complete page, 6 a choice */
#define TASK_CONTEXT 36u         /* u32 in the task: the window's context */
#define FLAG_AFTER_CHOICE 0x10u  /* context flags: the game advances these pages itself */
#define FLAG_AUTO_SCROLL 0x40u
#define SCENE_FIELD 6u
#define STATE_REVEAL 3
#define STATE_PAGE 4
#define STATE_CHOICE 6
#define PRESS_FRAMES 2u

enum { ARMED, WAITING, PRESSING, RELEASING, PRESSED };

static const SoaModApi* g_api;
static uint32_t g_delay;       /* frames on a complete page before pressing */
static int g_press_in_choice;  /* SOA_AUTOTEXT_TEST=press-in-choice */
static int g_phase = ARMED;
static uint32_t g_since, g_until; /* the frame the wait began; the frame this phase ends */
static int g_skipping, g_skip_told;
static uint32_t g_skip_next, g_skip_down_until; /* hold-to-skip's cadence */

/* The window's state, or -1 when there is no window to read. */
static int window_state(uint16_t* flags)
{
    uint32_t task, ctx;
    uint16_t state;
    if (!g_api->read32(WINDOW_TASK, &task) || !task) return -1;
    if (!g_api->read32(task + TASK_CONTEXT, &ctx) || !ctx) return -1;
    if (!g_api->read16(ctx, flags) || !g_api->read16(WINDOW_STATE, &state)) return -1;
    return (int16_t)state;
}

static void on_pad(void* user, uint32_t frame, SoaPad* pad)
{
    uint16_t flags = 0;
    int state = g_api->scene() == SCENE_FIELD ? window_state(&flags) : -1;
    int page = state == STATE_PAGE || (g_press_in_choice && state == STATE_CHOICE);
    int theirs = (pad->buttons & (SOA_PAD_A | SOA_PAD_B)) != 0;
    int held = g_api->size >= SOA_MOD_HAS(host_buttons) && (g_api->host_buttons() & SOA_HOST_LB);
    (void)user;
    if (held && (state == STATE_REVEAL || state == STATE_PAGE) && !(flags & (FLAG_AFTER_CHOICE | FLAG_AUTO_SCROLL)) &&
        !theirs) {
        if (!g_skipping || frame >= g_skip_next) {
            char line[96];
            if (!g_skip_told) {
                g_skip_told = 1;
                g_api->log("hold-to-skip in use: host buttons are not in recordings yet, so a replay will not skip");
            }
            snprintf(line, sizeof line, "frame %u skip press in state %d", frame, state);
            g_api->log(line);
            g_skipping = 1;
            g_skip_down_until = frame + PRESS_FRAMES;
            g_skip_next = frame + 2 * PRESS_FRAMES;
        }
        if (frame < g_skip_down_until) pad->buttons |= SOA_PAD_A;
        else pad->buttons &= (uint16_t)~SOA_PAD_A;
        g_phase = PRESSED; /* the page is being skipped: auto-advance re-arms once it leaves 4 */
        return;
    }
    g_skipping = 0;
    switch (g_phase) {
    case ARMED:
        /* On a page, the two flags mean the game turns it itself; in a choice
         * box (test mode only) 0x10 is the box's own mark, so they do not apply. */
        if (page && !(state == STATE_PAGE && (flags & (FLAG_AFTER_CHOICE | FLAG_AUTO_SCROLL))) && !theirs) {
            g_phase = WAITING;
            g_since = frame;
        }
        break;
    case WAITING:
        if (!page || theirs) g_phase = page ? PRESSED : ARMED; /* the person pressed: this page is theirs */
        else if (frame - g_since >= g_delay) {
            char line[96];
            snprintf(line, sizeof line, "frame %u page advanced after %u frames", frame, frame - g_since);
            g_api->log(line);
            g_phase = PRESSING;
            g_until = frame + PRESS_FRAMES;
        }
        break;
    case PRESSING:
        if (frame >= g_until) {
            g_phase = RELEASING;
            g_until = frame + PRESS_FRAMES;
        }
        break;
    case RELEASING:
        if (frame >= g_until) g_phase = PRESSED;
        break;
    case PRESSED:
        if (!page) g_phase = ARMED;
        break;
    }
    if (g_phase == PRESSING) pad->buttons |= SOA_PAD_A;
    else if (g_phase == RELEASING && !theirs) pad->buttons &= (uint16_t)~SOA_PAD_A;
}

static int env(const char* name, char* out, DWORD cap)
{
    DWORD n = GetEnvironmentVariableA(name, out, cap);
    if (!n) return 0;
    if (n >= cap) snprintf(out, cap, "%s", "(too long)");
    return 1;
}

__declspec(dllexport) int soa_mod_init(const SoaModApi* api, uint32_t version)
{
    char v[32], line[160], *end;
    unsigned long n;
    /* pad_filter is the last member this mod calls. */
    if (version < 1 || api->size < SOA_MOD_HAS(pad_filter)) return 1;
    g_api = api;
    if (!env("SOA_AUTOTEXT", v, sizeof v) || !v[0] || !strcmp(v, "0")) {
        api->log("off (SOA_AUTOTEXT unset or 0): pages wait for A as they always have");
        return 0;
    }
    n = strtoul(v, &end, 10);
    if (!strcmp(v, "on") || !strcmp(v, "1")) g_delay = 45;
    else if (v[0] >= '0' && v[0] <= '9' && !*end && n >= 2 && n <= 100000) g_delay = (uint32_t)n;
    else {
        snprintf(line, sizeof line, "SOA_AUTOTEXT=%s is not 0, 1, on or a number of frames; off", v);
        api->log(line);
        return 0;
    }
    if (env("SOA_AUTOTEXT_TEST", v, sizeof v) && !strcmp(v, "press-in-choice")) {
        g_press_in_choice = 1;
        api->log("SOA_AUTOTEXT_TEST=press-in-choice: pressing in choice boxes too -- a mutation for the check, not for play");
    }
    api->pad_filter(on_pad, NULL);
    snprintf(line, sizeof line, "a complete page turns itself after %u frames, in the field, never in a choice",
             g_delay);
    api->log(line);
    return 0;
}
