/* The in-game menu (M8a, docs/specs/menu.md): its model and its drawing, the
 * same on every system. The window code (window.c, window_sdl.c) turns keys
 * and the pad into menu_input calls and draws it with menu_draw over the
 * scaled picture; it never touches the game's own picture. */
#ifndef SOA_MENU_H
#define SOA_MENU_H

#include <stdint.h>

/* What a person pressed. */
enum {
    MENU_UP,
    MENU_DOWN,
    MENU_LEFT,
    MENU_RIGHT,
    MENU_BIG_LEFT,  /* an int option by a tenth of its range: LB/RB, Page Up/Down */
    MENU_BIG_RIGHT,
    MENU_OK,        /* A, Enter */
    MENU_BACK,      /* B, Esc, Backspace */
    MENU_TOGGLE     /* View+LS, F1: closes it when open */
};

/* What the window is asked to do, as bits of menu_input's answer. */
enum {
    MENU_ACT_REDRAW = 1,      /* present again: the game is held, so no frame will */
    MENU_ACT_CLOSE = 2,       /* the menu closed: release the hold */
    MENU_ACT_FULLSCREEN = 4,  /* toggle fullscreen now */
    MENU_ACT_TURBO = 8,       /* toggle turbo now */
    MENU_ACT_QUIT = 16,       /* close the window and end the run */
    MENU_ACT_SAVE_NOW = 32    /* ask for a save now (M7a, savenow.c), the menu closed first */
};

/* Whether it is open: any thread (si.c withholds the pad while it is). */
int menu_is_open(void);

/* Open it on its first page, or close it: the UI thread. */
void menu_open(void);
void menu_close(void);

/* What the window can tell it: fullscreen and turbo now, for their rows. */
void menu_set_state(int fullscreen, int turbo);

/* savenow.c (M7a): what MENU_ACT_SAVE_NOW asks for, from the UI thread. */
void savenow_request(void);

/* One input, on the UI thread: the MENU_ACT_ bits for the window. */
int menu_input(int key);

/* Draw it over `bgra` (w x h pixels, `stride` bytes a row, B G R X), when
 * it is open: a dimmed panel in the middle, scaled to the buffer. */
void menu_draw(uint8_t* bgra, int w, int h, int stride);

/* The same drawn for the GPU to blend over the picture (M8b): `bgra` cleared
 * to nothing, the panel's ground translucent, the rest opaque. 1 when it drew
 * the menu, 0 when the menu is closed. */
int menu_draw_overlay(uint8_t* bgra, int w, int h, int stride);

/* H17d (docs/specs/interp-display.md): a line in the picture's lower-left
 * corner for `ms` milliseconds, the menu open or not, drawn by menu_draw and
 * menu_draw_overlay -- what smooth motion is doing, told to the player.
 * NULL or 0 ms takes it away. Whether one shows now. */
void menu_notice(const char* text, unsigned ms);
int menu_notice_showing(void);

#endif
