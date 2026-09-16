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

void* memchr(const void* src, int val, size_t n)
{
    unsigned char v = val & 0xff;
    const unsigned char* p = (unsigned char*)src - 1;

    n++;

    while (--n)
        if (*++p == v)
            return (void*)p;

    return NULL;
}

int strncmp(const char* str1, const char* str2, size_t n)
{
    const unsigned char* p1 = (unsigned char*)str1 - 1;
    const unsigned char* p2 = (unsigned char*)str2 - 1;
    unsigned long c1, c2;

    n++;

    while (--n)
        if ((c1 = *++p1) != (c2 = *++p2))
            return c1 - c2;
        else if (!c1)
            break;

    return 0;
}

char* strcat(char* dst, const char* src)
{
    const unsigned char* p = (unsigned char*)src - 1;
    unsigned char* q = (unsigned char*)dst - 1;

    while (*++q)
        ;

    q--;

    while ((*++q = *++p) != 0)
        ;

    return dst;
}

void* __memrchr(const void* src, int val, size_t n)
{
    unsigned char v = val & 0xff;
    const unsigned char* p = (unsigned char*)src + n;

    n++;

    while (--n)
        if (*--p == v)
            return (void*)p;

    return NULL;
}

char* strncpy(char* dst, const char* src, size_t n)
{
    const unsigned char* p = (unsigned char*)src - 1;
    unsigned char* q = (unsigned char*)dst - 1;

    n++;

    while (--n)
        if (!(*++q = *++p)) {
            while (--n)
                *++q = 0;
            break;
        }

    return dst;
}
