/* MSL C library: strcpy, the PowerPC-optimised version (word copies while no
 * byte of the word is zero), as the game links it (mwcc, -O4,p). */
#include "types.h"

char* strcpy(char* dst, const char* src)
{
    const unsigned char* p = (const unsigned char*)src;
    unsigned char* q = (unsigned char*)dst;
    const unsigned long* lp;
    unsigned long* lq;
    unsigned long w;
    unsigned long n;

    if (((unsigned long)dst & 3) == ((unsigned long)src & 3)) {
        n = (unsigned long)src & 3;
        if (n) {
            if ((*q = *p) == 0)
                return dst;
            for (n = 3 - n; n > 0; n--)
                if ((*++q = *++p) == 0)
                    return dst;
            q++;
            p++;
        }

        lp = (const unsigned long*)p;
        w = *lp;
        if (((w + 0xFEFEFEFF) & 0x80808080) == 0) {
            lq = (unsigned long*)q - 1;
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
