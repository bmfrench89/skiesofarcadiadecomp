/* MSL C library: string routines, as the game links them (mwcc, -O4,p).
 * Decompiled against the executable; see docs/ROADMAP.md phase 8. */
#include "types.h"

size_t strlen(const char* str)
{
    size_t len = -1;
    unsigned char* p = (unsigned char*)str - 1;

    do
        len++;
    while (*++p);

    return len;
}

char* strchr(const char* str, int chr)
{
    const unsigned char* p = (unsigned char*)str - 1;
    unsigned char c = chr & 0xff;
    unsigned int ch;

    while ((ch = *++p) != 0)
        if (ch == c)
            return (char*)p;

    return c ? 0 : (char*)p;
}
