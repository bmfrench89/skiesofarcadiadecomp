/* MSL runtime memory fill (__mem.c) as the game links it. */
#include "types.h"

void __fill_mem(void* dst, int val, size_t n)
{
    unsigned long v = (unsigned char)val;
    unsigned long i;

    ((unsigned char*)dst) = ((unsigned char*)dst) - 1;

    if (n >= 32) {
        i = (~(unsigned long)dst) & 3;

        if (i) {
            n -= i;

            do
                *++((unsigned char*)dst) = v;
            while (--i);
        }

        if (v)
            v |= v << 24 | v << 16 | v << 8;

        ((unsigned long*)dst) = (unsigned long*)(((unsigned char*)dst) - 3);

        i = n >> 5;

        if (i)
            do {
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
                *++((unsigned long*)dst) = v;
            } while (--i);

        i = (n & 31) >> 2;

        if (i)
            do
                *++((unsigned long*)dst) = v;
            while (--i);

        ((unsigned char*)dst) = ((unsigned char*)dst) + 3;

        /* A 64-bit mask keeps mwcc from folding this into rlwinm: the
           game's build has li r0,3 / and here. */
        n &= 3ULL;
    }

    if (n)
        do
            *++((unsigned char*)dst) = v;
        while (--n);

    return;
}
