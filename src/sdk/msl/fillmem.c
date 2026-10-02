/* MSL runtime memory fill (__mem.c) as the game links it. */
#include "types.h"

void __fill_mem(void* dst, int val, size_t n)
{
    /* The original walks one pointer, written as casts of the dst parameter
       assigned and incremented in place. Both Metrowerks and MSVC accept that
       as an extension, but it is not C and every conformance mode rejects it,
       so the unit could not be trusted as a native twin. Two locals of the two
       types dst alternates between say the same thing in standard C. They are
       declared ahead of v because mwcc ranks registers by declaration order
       and the pointer used to be a parameter: declare them after v and the
       object is the same instructions with r6 and r7 exchanged. */
    unsigned char* b = (unsigned char*)dst - 1;
    u32* w;
    u32 v = (unsigned char)val;
    u32 i;

    if (n >= 32) {
        i = (u32)(~(size_t)b & 3);

        if (i) {
            n -= i;

            do
                *++b = (unsigned char)v;
            while (--i);
        }

        if (v)
            v |= v << 24 | v << 16 | v << 8;

        w = (u32*)(b - 3);

        i = (u32)(n >> 5);

        if (i)
            do {
                *++w = v;
                *++w = v;
                *++w = v;
                *++w = v;
                *++w = v;
                *++w = v;
                *++w = v;
                *++w = v;
            } while (--i);

        i = (u32)((n & 31) >> 2);

        if (i)
            do
                *++w = v;
            while (--i);

        b = (unsigned char*)w + 3;

        /* A 64-bit mask keeps mwcc from folding this into rlwinm: the
           game's build has li r0,3 / and here. */
        n &= 3ULL;
    }

    if (n)
        do
            *++b = (unsigned char)v;
        while (--n);

    return;
}
