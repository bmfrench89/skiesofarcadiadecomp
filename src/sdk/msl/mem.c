/* MSL runtime memory routines (__mem.c) as the game links them. */
#include "types.h"

void __fill_mem(void* dst, int val, size_t n);

void* memcpy(void* dst, const void* src, size_t n)
{
    const char* p;
    char* q;

    if (src >= dst) {
        for (p = (const char*)src - 1, q = (char*)dst - 1, n++; --n;)
            *++q = *++p;
    } else {
        for (p = (const char*)src + n, q = (char*)dst + n, n++; --n;)
            *--q = *--p;
    }

    return dst;
}

void* memset(void* dst, int val, size_t n)
{
    __fill_mem(dst, val, n);
    return dst;
}
