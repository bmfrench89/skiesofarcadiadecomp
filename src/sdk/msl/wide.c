/* MSL C library: routines around wctomb, as the game links them (mwcc 1.3.2,
 * -O4,p): _ftell (file_pos.c), wcstombs (wchar.c) and __StringRead (the
 * string-reading ReadProc used by sscanf/strtol, ansi_files.c).
 * Decompiled against the executable. wctomb and memcmp live in misc.c.
 *
 * Build note: wcstombs saves r27-r31 with stmw/lmw in the executable, which
 * mwcc 1.3.2 only emits with -use_lmw_stmw on (the default -O4,p flags give
 * a _savegpr_27 call); the two leaf routines match either way.
 * Form notes: wcstombs keeps `result` as size_t (an int makes mwcc copy it
 * before the `chars_written + result > n` add) and walks a local copy of pwcs
 * assigned after the NULL checks (that is what leaves pwcs in r4 for the test
 * and homes it in r29 after n). __StringRead returns the character through
 * an unsigned char cast, so the loaded byte is returned unextended while the
 * '\0' test uses the sign-extended char. */
#include "types.h"

typedef unsigned short wchar_t;
typedef long fpos_t;

/* errno value stored by the executable on a bad ftell (MSL file-position
 * error). */
#define EFPOS 40

/* MSL FILE, only the parts _ftell touches (offsets match the executable). */
enum __file_kinds { __closed_file, __disk_file, __console_file, __unavailable_file };
enum __io_states { __neutral, __writing, __reading, __rereading };

typedef struct {
    unsigned int open_mode : 2;
    unsigned int io_mode : 3;
    unsigned int buffer_mode : 2;
    unsigned int file_kind : 3;
    unsigned int file_orientation : 2;
    unsigned int binary_io : 1;
} __file_modes;

typedef struct {
    unsigned int io_state : 3;
    unsigned int free_buffer : 1;
    unsigned char eof;
    unsigned char error;
} __file_state;

typedef struct _FILE {
    unsigned long handle;
    __file_modes mode;
    __file_state state;
    unsigned char is_dynamically_allocated;
    unsigned char char_buffer;
    unsigned char char_buffer_overflow;
    unsigned char ungetc_buffer[2];
    wchar_t ungetwc_buffer[2];
    unsigned long position;
    unsigned char* buffer;
    unsigned long buffer_size;
    unsigned char* buffer_ptr;
    unsigned long buffer_length;
    unsigned long buffer_alignment;
    unsigned long saved_buffer_length;
    unsigned long buffer_position;
} FILE;

typedef struct {
    char* NextChar;
    int NullCharDetected;
} __InStrCtrl;

enum __ReadProcActions { __GetAChar, __UngetAChar, __TestForError };

#define EOF (-1)
#define MB_LEN_MAX 6

extern int errno;

int fn_8025C620(char* s, wchar_t wchar); /* wctomb */
char* strncpy(char* dst, const char* src, size_t n);

/* _ftell (file_pos.c) */
fpos_t fn_8025C510(FILE* file)
{
    fpos_t position;

    if ((file->mode.file_kind != __disk_file && file->mode.file_kind != __console_file) || file->state.error) {
        errno = EFPOS;
        return -1L;
    }

    if (file->state.io_state == __neutral)
        return file->position;

    position = file->buffer_position + (file->buffer_ptr - file->buffer);

    if (file->state.io_state >= __rereading)
        position -= file->state.io_state - __rereading + 1;

    return position;
}

/* wcstombs (wchar.c) */
size_t wcstombs(char* s, const wchar_t* pwcs, size_t n)
{
    size_t result;
    size_t chars_written = 0;
    char temp[MB_LEN_MAX];
    const wchar_t* p;

    if (!s || !pwcs)
        return 0;

    p = pwcs;
    while (chars_written <= n) {
        if (*p == L'\0') {
            s[chars_written] = '\0';
            break;
        }
        result = fn_8025C620(temp, *p++);
        if (chars_written + result > n)
            break;
        strncpy(s + chars_written, temp, result);
        chars_written += result;
    }

    return chars_written;
}

/* __StringRead (ansi_files.c): the ReadProc that vsscanf/strtol pull
 * characters through when the source is a C string. */
int fn_8025ECE4(void* cookie, int ch, int action)
{
    char RetChar;
    __InStrCtrl* Isc = (__InStrCtrl*)cookie;

    switch (action) {
    case __GetAChar:
        RetChar = *Isc->NextChar;
        if (RetChar == '\0') {
            Isc->NullCharDetected = 1;
            return EOF;
        } else {
            Isc->NextChar++;
            return (unsigned char)RetChar;
        }
    case __UngetAChar:
        if (!Isc->NullCharDetected)
            Isc->NextChar--;
        else
            Isc->NullCharDetected = 0;
        return ch;
    case __TestForError:
        return Isc->NullCharDetected;
    default:
        return 0;
    }
}
