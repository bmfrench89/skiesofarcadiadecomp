/* MSL C library: numeric conversion helpers and memmove, as the game links
 * them (mwcc 1.3.2, -O4,p): __strtoul (strtoul.c), atoi and memmove (mem.c).
 * Decompiled against the executable. */
#include "types.h"

#define LONG_MAX 0x7FFFFFFFL
#define LONG_MIN (-LONG_MAX - 1)
#define INT_MAX 0x7FFFFFFF
#define ULONG_MAX 0xFFFFFFFFUL
#define ERANGE 34
#define EOF (-1)

#define __GetAChar 0
#define __UngetAChar 1

extern int errno;

extern unsigned char __ctype_map[256];
extern unsigned char __upper_map[256];

#define isspace(c) (__ctype_map[(unsigned char)(c)] & 0x06)
#define isdigit(c) (__ctype_map[(unsigned char)(c)] & 0x10)
#define isalpha(c) (__ctype_map[(unsigned char)(c)] & 0xC0)
#define toupper(c) ((c) == EOF ? EOF : (int)__upper_map[(unsigned char)(c)])

typedef struct {
    char* NextChar;
    int NullCharDetected;
} __InStrCtrl;

/* __StringRead */
int fn_8025ECE4(void* isc, int ch, int action);

/* __copy_longs_rev_unaligned / __copy_longs_unaligned / __copy_longs_rev_aligned / __copy_longs_aligned */
void fn_8025C834(void* dst, const void* src, size_t n);
void fn_8025C8E4(void* dst, const void* src, size_t n);
void fn_8025C9A8(void* dst, const void* src, size_t n);
void fn_8025CA54(void* dst, const void* src, size_t n);

#define __min_bytes_for_long_copy 32

/* memmove */
void* fn_8025C768(void* dst, const void* src, size_t n)
{
    const char* p;
    char* q;
    int rev = ((unsigned long)src < (unsigned long)dst);

    if (n >= __min_bytes_for_long_copy) {
        if (((unsigned long)src ^ (unsigned long)dst) & 3) {
            if (!rev)
                fn_8025C8E4(dst, src, n);
            else
                fn_8025C834(dst, src, n);
        } else {
            if (!rev)
                fn_8025CA54(dst, src, n);
            else
                fn_8025C9A8(dst, src, n);
        }
        return dst;
    }

    if (!rev) {
        p = (const char*)src - 1;
        q = (char*)dst - 1;
        n++;
        while (--n)
            *++q = *++p;
    } else {
        p = (const char*)src + n;
        q = (char*)dst + n;
        n++;
        while (--n)
            *--q = *--p;
    }

    return dst;
}

enum scan_states {
    start = 0x01,
    check_for_zero = 0x02,
    leading_zero = 0x04,
    need_digit = 0x08,
    digit_loop = 0x10,
    finished = 0x20,
    failure = 0x40
};

#define final_state(scan_state) (scan_state & (finished | failure))
#define success(scan_state) (scan_state & (leading_zero | digit_loop | finished))

/* __strtoul (not yet matched; declared for atoi) */
unsigned long fn_8025F3A4(int base, int max_width, int (*ReadProc)(void*, int, int), void* ReadProcArg,
                          int* chars_scanned, int* negative, int* overflow);

/* atoi (strtol(str, NULL, 10) with strtol inlined) */
int atoi(const char* str)
{
    unsigned long ul;
    __InStrCtrl isc;
    int overflow;
    int negative;
    int chars_scanned;

    isc.NextChar = (char*)str;
    isc.NullCharDetected = 0;

    ul = fn_8025F3A4(10, INT_MAX, &fn_8025ECE4, &isc, &chars_scanned, &negative, &overflow);

    if (overflow || (!negative && ul > LONG_MAX) || (negative && ul > -LONG_MIN)) {
        ul = negative ? LONG_MIN : LONG_MAX;
        errno = ERANGE;
    } else if (negative) {
        ul = -ul;
    }

    return ul;
}
