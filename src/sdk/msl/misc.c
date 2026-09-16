/* MSL C library: miscellaneous routines near the string block, as the game
 * links them (mwcc 1.3.2, -O4,p): memcmp, wctomb (UTF-8) and strtol.
 * Decompiled against the executable. */
#include "types.h"

#define LONG_MAX 0x7FFFFFFFL
#define LONG_MIN (-LONG_MAX - 1)
#define INT_MAX 0x7FFFFFFF
#define ERANGE 34

typedef unsigned short wchar_t;

/* __strtoul (strtoul.c) */
unsigned long fn_8025F3A4(int base, int max_width, int (*ReadProc)(void*, int, int), void* ReadProcArg,
                          int* chars_scanned, int* negative, int* overflow);
/* __StringRead (ansi_files.c / strtoul.c helper) */
int fn_8025ECE4(void* isc, int ch, int action);

extern int errno;

typedef struct {
    char* NextChar;
    int NullCharDetected;
} __InStrCtrl;

/* memcmp */
int fn_8025C6C4(const void* src1, const void* src2, size_t n)
{
    const unsigned char* p1;
    const unsigned char* p2;

    for (p1 = (const unsigned char*)src1 - 1, p2 = (const unsigned char*)src2 - 1, n++; --n;)
        if (*++p1 != *++p2)
            return (*p1 < *p2) ? -1 : 1;

    return 0;
}

/* wctomb (UTF-8 encoding of a 16-bit wchar_t) */
int fn_8025C620(char* s, wchar_t wchar)
{
    int number_of_bytes;
    unsigned char* target;
    unsigned char first_byte_mark[4] = {0x00, 0x00, 0xC0, 0xE0};

    if (s == NULL)
        return 0;

    if (wchar < 0x80)
        number_of_bytes = 1;
    else if (wchar < 0x800)
        number_of_bytes = 2;
    else
        number_of_bytes = 3;

    target = (unsigned char*)s + number_of_bytes;

    switch (number_of_bytes) {
    case 3:
        *--target = (wchar & 0x3F) | 0x80;
        wchar >>= 6;
    case 2:
        *--target = (wchar & 0x3F) | 0x80;
        wchar >>= 6;
    case 1:
        *--target = wchar | first_byte_mark[number_of_bytes];
    }

    return number_of_bytes;
}

/* strtol */
long fn_8025F2B4(const char* str, char** end, int base)
{
    unsigned long ul;
    __InStrCtrl isc;
    int chars_scanned;
    int negative;
    int overflow;

    isc.NextChar = (char*)str;
    isc.NullCharDetected = 0;

    ul = fn_8025F3A4(base, INT_MAX, &fn_8025ECE4, &isc, &chars_scanned, &negative, &overflow);

    if (end)
        *end = (char*)str + chars_scanned;

    if (overflow || (!negative && ul > LONG_MAX) || (negative && ul > -LONG_MIN)) {
        ul = negative ? LONG_MIN : LONG_MAX;
        errno = ERANGE;
    } else if (negative) {
        ul = -ul;
    }

    return ul;
}
