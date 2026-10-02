/* MSL C library: strcpy, the PowerPC-optimised version (word copies while no
 * byte of the word is zero), as the game links it (mwcc, -O4,p). */
#include "types.h"

char* strcpy(char* dst, const char* src)
{
    const unsigned char* p = (const unsigned char*)src;
    unsigned char* q = (unsigned char*)dst;
    const u32* lp;
    u32* lq;
    u32 w;
    u32 n;

    /* Through size_t, as strcmp.c: a pointer cast straight to a 32-bit
       word truncates it on a 64-bit host, which only the low two bits
       survive anyway, but every compiler says so. */
    if (((size_t)dst & 3) == ((size_t)src & 3)) {
        n = (u32)((size_t)src & 3);
        if (n) {
            if ((*q = *p) == 0)
                return dst;
            for (n = 3 - n; n > 0; n--)
                if ((*++q = *++p) == 0)
                    return dst;
            q++;
            p++;
        }

        lp = (const u32*)p;
        w = *lp;
        if (((w + 0xFEFEFEFF) & 0x80808080) == 0) {
            lq = (u32*)q - 1;
            do {
                *++lq = w;
                w = *++lp;
            } while (((w + 0xFEFEFEFF) & 0x80808080) == 0);
            q = (unsigned char*)(lq + 1);
            p = (const unsigned char*)lp;
        }
    }

    if ((*q = *p) != 0)
        while ((*++q = *++p) != 0)
            ;

    return dst;
}
