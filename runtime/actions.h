/*
 * M7b, the debug actions (docs/specs/debug-actions.md): warp by name, part
 * select, the ending, the fade fix and the encounter toggle, queued to the
 * safe point from the menu (any thread) and from SOA_ACTION (tests).
 */
#ifndef SOA_ACTIONS_H
#define SOA_ACTIONS_H

#include <stdint.h>

enum { ACT_NONE, ACT_WARP, ACT_PART, ACT_ENDING, ACT_FADE, ACT_ENCOUNTERS_OFF, ACT_ENCOUNTERS_ON, ACT_KINDS };

/* Ask for one at the next safe point; `map` (number << 8 | letter) for a
 * warp. From any thread: one request waits at a time, a second is dropped
 * (0 then). */
int actions_request(int kind, uint32_t map);

/* SOA_ACTION's grammar, `NAME[:ARG]@FRAME[,...]`: how many were scheduled, or
 * -1 with the fault said. */
int actions_parse(const char* text);

/* Whether the encounter toggle is off (the menu's row). */
int actions_encounters_off(void);

/* The maps a warp reaches, for the menu: how many, and each. */
int actions_warp_count(void);
uint32_t actions_warp_map(int i);

#endif
