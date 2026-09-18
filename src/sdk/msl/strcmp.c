/* MSL C library: strcmp, the PowerPC word-at-a-time version, as the game
 * links it (mwcc, -O4,p). Decompiled against the executable.
 *
 * Compares the first bytes, then when both pointers share the same alignment
 * walks up to a word boundary bytewise, then by whole words until a word may
 * hold a zero byte ((w - 0x01010101) & 0x80808080), then finishes bytewise.
 * Byte mismatches return the byte difference; word mismatches return -1/1. */
#include "types.h"

/* The word comparison at the bottom of the word loop is a statement about byte
 * order: on the big-endian target the first character of a word is its most
 * significant byte, so comparing the two words as unsigned integers compares
 * the strings. The native twin (tools/recompile.py builds this unit for the
 * host as well) runs little-endian, where the same two words compare their
 * last characters first and the answer comes out inverted for most inputs.
 * Only the host spelling is redefined, so mwcc still compiles the expression
 * the executable has and the object still matches word for word. Like the rest
 * of the function this assumes a 32-bit unsigned long, which both compilers
 * that build it have. */
#if defined(_MSC_VER) || (defined(__BYTE_ORDER__) && __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__)
#define IN_STRING_ORDER(w) \
    (((w) >> 24) | (((w) >> 8) & 0xFF00) | (((w) << 8) & 0xFF0000) | ((w) << 24))
#else
#define IN_STRING_ORDER(w) (w)
#endif

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

    /* Through size_t, because on the 64-bit host a cast straight to unsigned
       long truncates the address; only its low two bits are wanted. */
    if ((a = (unsigned long)((size_t)p1 & 3)) == (unsigned long)((size_t)p2 & 3)) {
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
        return (IN_STRING_ORDER(w1) > IN_STRING_ORDER(w2)) ? 1 : -1;

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
