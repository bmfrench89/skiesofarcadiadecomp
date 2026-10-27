/*
 * The event track's ends (docs/specs/event-track.md, E3): what changes the
 * game at a safe point -- turbo, save now, the debug actions -- written into
 * a pad recording as `F @kind value` lines, and during a replay taken from
 * it in place of the chord, the menu and the knobs. si.c holds the recorder
 * and the replay's lists (si_event_track); main.c hands them to tick.c,
 * actions.c and savenow.c, so each still links alone in its tests and in the
 * mod driver.
 */
#ifndef SOA_EVENTTRACK_H
#define SOA_EVENTTRACK_H

#include <stddef.h>

typedef struct {
    /* An event applied at frame F, written to the recording if one is being
     * made; `value` "" for a kind with none. The guest thread. */
    void (*record)(unsigned frame, const char* kind, const char* value);
    /* The next `@kind` line due at or before `frame`, its value copied into
     * `out`: 1, and taken; 0 when a replay runs and none is due; -1 when no
     * replay runs. The guest thread, at the safe point: the first call loads
     * the replay. */
    int (*take)(const char* kind, unsigned frame, char* out, size_t cap);
    /* Whether a replay is the whole input. Any thread. */
    int (*replaying)(void);
    /* A recorded event this replay could not apply, `what` as the line names
     * it: said, and under SOA_PAD_STRICT the run stops, exit 11. */
    void (*left)(unsigned frame, const char* what, const char* why);
} EventTrack;

void tick_set_event_track(const EventTrack* t);
void actions_set_event_track(const EventTrack* t);
void savenow_set_event_track(const EventTrack* t);

#endif
