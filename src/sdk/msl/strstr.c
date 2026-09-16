/* MSL C library: strstr, as the game links it (mwcc, -O4,p).
 * Decompiled against the executable; see docs/ROADMAP.md phase 8.
 *
 * Form notes: the pattern pointer is biased (p1 = pat - 1) and the first
 * character read with *++p1, MSL style; the inner compare restarts from
 * s1 - 1 / p1 - 1 (it re-checks the first character), which is what keeps
 * `pat - 1` from being hoisted out of the outer loop. The explicit NULL check
 * on pat is in the executable. */
#include "types.h"

char* strstr(const char* str, const char* pat)
{
    const unsigned char* s1 = (unsigned char*)str - 1;
    const unsigned char* p1 = (unsigned char*)pat - 1;
    unsigned long firstc, c1, c2;

    if (!pat || !(firstc = *++p1))
        return (char*)str;

    while ((c1 = *++s1) != 0)
        if (c1 == firstc) {
            const unsigned char* s2 = s1 - 1;
            const unsigned char* p2 = p1 - 1;

            while ((c1 = *++s2) == (c2 = *++p2) && c1)
                ;

            if (!c2)
                return (char*)s1;
        }

    return NULL;
}
