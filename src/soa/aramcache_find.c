/* aramCacheFind (fn_8022ABEC): slot index of the package whose path
 * contains the name (case-insensitive), or -1.
 *
 * The lowercasing is a small static helper that mwcc inlines: the
 * original's register allocation (copy pointer in r4 tested with addic.,
 * the loaded character in r5 sign-extended at each use) only comes out
 * when the copy pointer is the helper's parameter rather than a local of
 * aramCacheFind itself. The helper's loop is a for (;;) with a break so
 * the compiler does not rotate it. */
#include "types.h"
#include "aramcache.h"

char* strstr(const char* str, const char* pat);

static inline void strlower(char* dst, const char* src)
{
    char* p;

    if ((p = dst) != NULL && src != NULL) {
        for (;;) {
            if (*src == 0)
                break;
            if (*src >= 'A' && *src <= 'Z')
                *p = *src + 32;
            else
                *p = *src;
            src++;
            p++;
        }
        *p = 0;
    }
}

int aramCacheFind(const char* name)
{
    char lower[64];
    unsigned int i;

    strlower(lower, name);

    for (i = 0; i < 16; i++)
        if (strstr(aramCacheNames[i], lower) != NULL)
            return i;

    return -1;
}
