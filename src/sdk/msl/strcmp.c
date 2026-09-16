/* MSL C library: strcmp, the PowerPC word-at-a-time version, as the game
 * links it (mwcc, -O4,p). Decompiled against the executable.
 *
 * Compares the first bytes, then when both pointers share the same alignment
 * walks up to a word boundary bytewise, then by whole words until a word may
 * hold a zero byte ((w - 0x01010101) & 0x80808080), then finishes bytewise.
 * Byte mismatches return the byte difference; word mismatches return -1/1. */
#include "types.h"

/* strcmp */
int fn_8025EF88(const char* str1, const char* str2)
{
    const unsigned char* p1 = (unsigned char*)str1;
    const unsigned char* p2 = (unsigned char*)str2;
    const unsigned long* wp1;
    const unsigned long* wp2;
    unsigned long a;
    unsigned long c1, c2, w1, w2;
    unsigned long n;
    int d;

    c1 = *p1;
    c2 = *p2;
    if ((d = c1 - c2) != 0)
        return d;

    if ((a = (unsigned long)p1 & 3) == ((unsigned long)p2 & 3)) {
        if (a) {
            /* same misalignment: step bytewise up to the next word boundary */
            if (!c1)
                return 0;
            for (n = 3 - a; n; n--) {
                ++p1;
                ++p2;
                c1 = *p1;
                c2 = *p2;
                if ((d = c1 - c2) != 0)
                    return d;
                if (!c1)
                    return 0;
            }
            p1++;
            p2++;
        }

        /* word compare until a word may contain a zero byte */
        wp1 = (const unsigned long*)p1;
        wp2 = (const unsigned long*)p2;
        w1 = *wp1;
        w2 = *wp2;
        if ((w1 - 0x01010101) & 0x80808080)
            goto tail;
        while (w1 == w2) {
            w1 = *++wp1;
            w2 = *++wp2;
            if ((w1 - 0x01010101) & 0x80808080)
                goto tail;
        }
        return (w1 > w2) ? 1 : -1;

    tail:
        p1 = (const unsigned char*)wp1;
        p2 = (const unsigned char*)wp2;
        c1 = *p1;
        c2 = *p2;
        if ((d = c1 - c2) != 0)
            return d;
    }

    /* plain bytewise compare */
    if (!c1)
        return 0;
    do {
        ++p1;
        ++p2;
        c1 = *p1;
        c2 = *p2;
        if ((d = c1 - c2) != 0)
            return d;
    } while (c1);

    return 0;
}
