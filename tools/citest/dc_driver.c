/*
 * Check the hand-decompiled MSL routines against the host C library.
 *
 * tools/citest/dc_check.py compiles every unit config/GEAE8P/units.txt marks
 * native with the /Ddc_* renames the native twin build uses, links them with this driver
 * and runs it, so every dc_ routine below is the decompiled code itself
 * sitting beside the host's own strlen and friends. tools/decomp.py already
 * proves those units assemble to the original's bytes; what that cannot see
 * is a routine reached with the wrong arguments or returning the wrong thing,
 * which is exactly what a twin swapped into runtime/decomp_swap.c has to get
 * right. Comparing against the host library costs no game data, so it can run
 * in CI where the real selftest (which needs the recompiled twins) cannot.
 *
 * Exit status is the number of routines that disagreed.
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t dc_strlen(const char* str);
char* dc_strchr(const char* str, int chr);
void* dc_memchr(const void* src, int val, size_t n);
void* dc___memrchr(const void* src, int val, size_t n);
int dc_strncmp(const char* a, const char* b, size_t n);
char* dc_strcat(char* dst, const char* src);
char* dc_strncpy(char* dst, const char* src, size_t n);
void* dc_memcpy(void* dst, const void* src, size_t n);
void* dc_memset(void* dst, int val, size_t n);
char* dc_strcpy(char* dst, const char* src);
int dc_fn_8025EF88(const char* a, const char* b); /* strcmp: the game's own name for it */
char* dc_strstr(const char* str, const char* pat);

#define ITER 3000
#define CAP 192 /* bytes a routine may touch */
#define PAD 32  /* untouched either side, so an overrun shows up as a mismatch */
#define BUF (PAD + CAP + PAD)
#define FRESH 0xA5 /* the pattern both buffers start from */

static uint32_t g_state = 0x2E9AF17Bu;
static unsigned g_shown; /* mismatches printed for the routine under test */

/* xorshift32 rather than rand(): the sequence is then the same on every
 * machine and every run, so a case that fails in CI reproduces locally. */
static uint32_t rnd(void)
{
    g_state ^= g_state << 13;
    g_state ^= g_state >> 17;
    g_state ^= g_state << 5;
    return g_state;
}

static size_t rnd_upto(size_t n) { return n ? (size_t)(rnd() % (uint32_t)(n + 1)) : 0; }

static int show(void) { return g_shown++ < 3; }

static void fill_random(unsigned char* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) p[i] = (unsigned char)(rnd() & 0xff);
}

/* A random string of at most cap-1 bytes, from the full 1..255 range: the
 * routines walk bytes as unsigned char, and a sign-extension mistake only
 * shows on the high half. */
static void make_string(char* p, size_t cap)
{
    size_t n = rnd_upto(cap - 1), i;
    for (i = 0; i < n; i++) {
        unsigned char c;
        do
            c = (unsigned char)(rnd() & 0xff);
        while (c == 0);
        p[i] = (char)c;
    }
    p[n] = 0;
}

/* Where the two buffers first differ, as an offset into the window a routine
 * may write, so a negative answer means it ran past its end into the guard
 * band. Returns text rather than a number because "nowhere" has to be
 * distinguishable from an offset, and the report is the only reader; the one
 * static buffer is safe because the driver is single-threaded and each
 * printf calls this once. */
static const char* diff_at(const unsigned char* a, const unsigned char* b, size_t n)
{
    static char text[32];
    size_t i;
    for (i = 0; i < n; i++)
        if (a[i] != b[i]) {
            snprintf(text, sizeof text, "%+ld", (long)i - PAD);
            return text;
        }
    return "nowhere";
}

static unsigned test_strlen(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        char s[CAP];
        size_t got, want;
        make_string(s, sizeof s);
        got = dc_strlen(s);
        want = strlen(s);
        if (got != want) {
            bad++;
            if (show()) printf("  strlen: got %zu want %zu\n", got, want);
        }
    }
    return bad;
}

static unsigned test_strchr(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        char s[CAP];
        const char *got, *want;
        int chr;
        size_t len;
        make_string(s, sizeof s);
        len = strlen(s);
        /* Half the needles are present, and the rest cover the two edge
         * cases: a byte that is absent, and 0, which both routines must
         * answer with the terminator's address. A needle above 255 checks
         * that the conversion to char happens, since the game passes one. */
        if (len && (rnd() & 1))
            chr = (unsigned char)s[rnd_upto(len - 1)];
        else if (rnd() & 1)
            chr = (int)(rnd() & 0xff);
        else
            chr = (int)(rnd() & 0xff) | 0x100;
        got = dc_strchr(s, chr);
        want = strchr(s, chr);
        if (got != want) {
            bad++;
            if (show())
                printf("  strchr(len %zu, 0x%x): got %+ld want %+ld\n", len, chr,
                    got ? (long)(got - s) : -1L, want ? (long)(want - s) : -1L);
        }
    }
    return bad;
}

static unsigned test_memchr(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char b[CAP];
        const unsigned char *got, *want;
        size_t n = rnd_upto(sizeof b);
        int val;
        fill_random(b, sizeof b);
        val = (n && (rnd() & 1)) ? b[rnd_upto(n - 1)] : (int)(rnd() & 0xff);
        got = (const unsigned char*)dc_memchr(b, val, n);
        want = (const unsigned char*)memchr(b, val, n);
        if (got != want) {
            bad++;
            if (show())
                printf("  memchr(n %zu, 0x%02x): got %+ld want %+ld\n", n, val,
                    got ? (long)(got - b) : -1L, want ? (long)(want - b) : -1L);
        }
    }
    return bad;
}

/* The host C library has no memrchr, so the reference is written out here;
 * it is a backwards scan of n bytes and nothing more. */
static const unsigned char* ref_memrchr(const unsigned char* p, int val, size_t n)
{
    while (n--)
        if (p[n] == (unsigned char)val) return p + n;
    return NULL;
}

static unsigned test_memrchr(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char b[CAP];
        const unsigned char *got, *want;
        size_t n = rnd_upto(sizeof b);
        int val;
        fill_random(b, sizeof b);
        val = (n && (rnd() & 1)) ? b[rnd_upto(n - 1)] : (int)(rnd() & 0xff);
        got = (const unsigned char*)dc___memrchr(b, val, n);
        want = ref_memrchr(b, val, n);
        if (got != want) {
            bad++;
            if (show())
                printf("  __memrchr(n %zu, 0x%02x): got %+ld want %+ld\n", n, val,
                    got ? (long)(got - b) : -1L, want ? (long)(want - b) : -1L);
        }
    }
    return bad;
}

static unsigned test_strncmp(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        char a[CAP], b[CAP];
        size_t n;
        int got, want;
        make_string(a, sizeof a);
        if (rnd() & 1) {
            /* Strings that share a prefix are the interesting ones: they are
             * what makes the length cut off the comparison. */
            size_t len = strlen(a);
            memcpy(b, a, len + 1);
            if (len && (rnd() & 1)) b[rnd_upto(len - 1)] ^= (char)((rnd() & 0x7f) | 1);
        } else {
            make_string(b, sizeof b);
        }
        n = rnd_upto(sizeof a);
        got = dc_strncmp(a, b, n);
        want = strncmp(a, b, n);
        /* Only the sign is fixed by the standard, and the decompiled routine
         * returns the raw byte difference the original does. */
        if ((got > 0) != (want > 0) || (got < 0) != (want < 0)) {
            bad++;
            if (show()) printf("  strncmp(n %zu): got %d want %d\n", n, got, want);
        }
    }
    return bad;
}

static unsigned test_strcat(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char got[BUF], want[BUF];
        char src[CAP / 2];
        char* r;
        memset(got, FRESH, sizeof got);
        /* Both halves stay under CAP/2 so the result, terminator included,
         * still fits the window between the guard bands. */
        make_string((char*)got + PAD, CAP / 2);
        memcpy(want, got, sizeof want);
        make_string(src, sizeof src);
        r = dc_strcat((char*)got + PAD, src);
        strcat((char*)want + PAD, src);
        if (r != (char*)got + PAD || memcmp(got, want, sizeof got) != 0) {
            bad++;
            if (show())
                printf("  strcat: ret %s, differs at %s\n", r == (char*)got + PAD ? "ok" : "wrong",
                    diff_at(got, want, sizeof got));
        }
    }
    return bad;
}

static unsigned test_strncpy(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char got[BUF], want[BUF];
        char src[CAP];
        size_t n;
        char* r;
        make_string(src, sizeof src);
        memset(got, FRESH, sizeof got);
        memcpy(want, got, sizeof want);
        /* n runs past the string's length often enough to exercise the zero
         * padding, which is the half of strncpy that surprises people. */
        n = rnd_upto(CAP);
        r = dc_strncpy((char*)got + PAD, src, n);
        strncpy((char*)want + PAD, src, n);
        if (r != (char*)got + PAD || memcmp(got, want, sizeof got) != 0) {
            bad++;
            if (show())
                printf("  strncpy(len %zu, n %zu): ret %s, differs at %s\n", strlen(src), n,
                    r == (char*)got + PAD ? "ok" : "wrong", diff_at(got, want, sizeof got));
        }
    }
    return bad;
}

static unsigned test_memcpy(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char got[BUF], want[BUF];
        size_t n = rnd_upto(CAP / 2);
        size_t dst = rnd_upto(CAP - n), src = rnd_upto(CAP - n);
        void* r;
        memset(got, FRESH, sizeof got);
        fill_random(got + PAD, CAP);
        memcpy(want, got, sizeof want);
        r = dc_memcpy(got + PAD + dst, got + PAD + src, n);
        /* The reference is memmove, not memcpy: the decompiled routine picks
         * its direction from the order of the pointers, so an overlapping
         * copy is defined for it while memcpy's own answer would not be. */
        memmove(want + PAD + dst, want + PAD + src, n);
        if (r != got + PAD + dst || memcmp(got, want, sizeof got) != 0) {
            bad++;
            if (show())
                printf("  memcpy(dst %zu, src %zu, n %zu): ret %s, differs at %s\n", dst, src, n,
                    r == got + PAD + dst ? "ok" : "wrong", diff_at(got, want, sizeof got));
        }
    }
    return bad;
}

/* mem.c's memset is a two-line wrapper around __fill_mem, and the rename
 * makes that dc___fill_mem, which is src/sdk/msl/fillmem.c's decompiled body:
 * the fill itself is checked here, its word loop included (lengths reach 32,
 * where it starts writing four bytes at a time), along with the wrapper's
 * argument order and returned pointer. Until fillmem.c landed this compared
 * the host's own fill on both sides. */
static unsigned test_memset(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char got[BUF], want[BUF];
        size_t n = rnd_upto(CAP);
        size_t off = rnd_upto(CAP - n);
        /* Values outside 0..255, and negative ones, reach memset in real
         * code; both sides must truncate them the same way. */
        int val = (int)(rnd() & 0x3ff) - 256;
        void* r;
        memset(got, FRESH, sizeof got);
        fill_random(got + PAD, CAP);
        memcpy(want, got, sizeof want);
        r = dc_memset(got + PAD + off, val, n);
        memset(want + PAD + off, val, n);
        if (r != got + PAD + off || memcmp(got, want, sizeof got) != 0) {
            bad++;
            if (show())
                printf("  memset(off %zu, n %zu, val %d): ret %s, differs at %s\n", off, n, val,
                    r == got + PAD + off ? "ok" : "wrong", diff_at(got, want, sizeof got));
        }
    }
    return bad;
}

/* An offset into a buffer that puts p + offset at the same word alignment as
 * `like`, half the time, and anywhere in 0..3 otherwise. strcpy and strcmp
 * take their word-at-a-time path only when both pointers share an alignment,
 * and a random pair shares one only a quarter of the time. */
static size_t align_like(const void* p, const void* like)
{
    if (rnd() & 1) return (size_t)(((uintptr_t)like - (uintptr_t)p) & 3);
    return rnd_upto(3);
}

/* The word loop copies four bytes at a time while none of them is zero, and
 * reads the source a word at a time, so the strings are long enough to take
 * it and every result is compared with its guard bands: a word written past
 * the terminator shows as a difference there. */
static unsigned test_strcpy(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        unsigned char got[BUF], want[BUF];
        char srcbuf[CAP + 4];
        size_t doff = rnd_upto(3), soff;
        char *src, *r;
        memset(got, FRESH, sizeof got);
        memcpy(want, got, sizeof want);
        soff = align_like(srcbuf, got + PAD + doff);
        src = srcbuf + soff;
        make_string(src, CAP - 4);
        r = dc_strcpy((char*)got + PAD + doff, src);
        strcpy((char*)want + PAD + doff, src);
        if (r != (char*)got + PAD + doff || memcmp(got, want, sizeof got) != 0) {
            bad++;
            if (show())
                printf("  strcpy(len %zu, dst %zu, src mod 4 %u): ret %s, differs at %s\n", strlen(src), doff,
                    (unsigned)((uintptr_t)src & 3), r == (char*)got + PAD + doff ? "ok" : "wrong",
                    diff_at(got, want, sizeof got));
        }
    }
    return bad;
}

/* The word loop decides a mismatch by comparing whole words, which on this
 * little-endian host means byte-swapping them first (strcmp.c's
 * IN_STRING_ORDER), so most cases share a long prefix and differ late, where
 * the word compare is what answers. */
static unsigned test_strcmp(void)
{
    unsigned bad = 0, i;
    for (i = 0; i < ITER; i++) {
        char abuf[CAP + 4], bbuf[CAP + 4];
        char *a = abuf + rnd_upto(3), *b;
        int got, want;
        make_string(a, CAP - 4);
        b = bbuf + align_like(bbuf, a);
        if (rnd() & 3) {
            size_t len = strlen(a);
            memcpy(b, a, len + 1);
            if (len && (rnd() & 1)) b[rnd_upto(len - 1)] = (char)(rnd() | 1);
            else if (rnd() & 1) { /* one longer: the mismatch is a's terminator */
                b[len] = (char)(rnd() | 1);
                b[len + 1] = 0;
            }
        } else {
            make_string(b, CAP - 4);
        }
        got = dc_fn_8025EF88(a, b);
        want = strcmp(a, b);
        /* Only the sign is fixed: the routine returns a byte difference, or
         * 1 and -1 from the word compare. */
        if ((got > 0) != (want > 0) || (got < 0) != (want < 0)) {
            bad++;
            if (show()) printf("  strcmp(len %zu, %zu): got %d want %d\n", strlen(a), strlen(b), got, want);
        }
    }
    return bad;
}

/* Over a three-letter alphabet, so partial matches -- the case a naive
 * search gets wrong -- are common; the pattern is cut from the string most of
 * the time, and empty now and then (which finds the start). */
static unsigned test_strstr(void)
{
    unsigned bad = 0, i, k;
    for (i = 0; i < ITER; i++) {
        char str[CAP / 2], pat[16];
        size_t n = rnd_upto(sizeof str - 1), m;
        const char *got, *want;
        for (k = 0; k < n; k++) str[k] = (char)('a' + rnd() % 3);
        str[n] = 0;
        if (n && (rnd() & 3)) {
            size_t at = rnd_upto(n - 1);
            m = rnd_upto(n - at < sizeof pat - 1 ? n - at : sizeof pat - 1);
            memcpy(pat, str + at, m);
            if (m && !(rnd() & 3)) pat[m - 1] = (char)('a' + rnd() % 3);
        } else {
            m = rnd_upto(sizeof pat - 1);
            for (k = 0; k < m; k++) pat[k] = (char)('a' + rnd() % 3);
        }
        pat[m] = 0;
        got = dc_strstr(str, pat);
        want = strstr(str, pat);
        if (got != want) {
            bad++;
            if (show())
                printf("  strstr(\"%s\", \"%s\"): got %ld want %ld\n", str, pat, got ? (long)(got - str) : -1L,
                    want ? (long)(want - str) : -1L);
        }
    }
    return bad;
}

static unsigned run(const char* name, unsigned (*test)(void))
{
    unsigned bad;
    g_shown = 0;
    bad = test();
    printf("%s %-11s %5d cases", bad ? "FAIL" : "ok  ", name, ITER);
    if (bad) printf(", %u disagreed", bad);
    printf("\n");
    return bad ? 1u : 0u;
}

/* One table, so the count in the report cannot disagree with the list. Every
 * unit units.txt marks native is reached through at least one row: memset
 * through mem.c's wrapper into fillmem.c, and strcmp as fn_8025EF88, the
 * name its unit defines and the rename keeps. */
static const struct { const char* name; unsigned (*test)(void); } ROUTINES[] = {
    {"strlen", test_strlen},
    {"strchr", test_strchr},
    {"memchr", test_memchr},
    {"__memrchr", test_memrchr},
    {"strncmp", test_strncmp},
    {"strcat", test_strcat},
    {"strncpy", test_strncpy},
    {"memcpy", test_memcpy},
    {"memset", test_memset},
    {"strcpy", test_strcpy},
    {"fn_8025EF88", test_strcmp}, /* strcmp, under the name strcmp.c gives it */
    {"strstr", test_strstr},
};
#define NROUTINES (unsigned)(sizeof ROUTINES / sizeof ROUTINES[0])

int main(void)
{
    unsigned bad = 0, i;

    printf("decompiled MSL routines vs the host C library, %d cases each\n", ITER);
    for (i = 0; i < NROUTINES; i++) bad += run(ROUTINES[i].name, ROUTINES[i].test);

    if (bad)
        printf("\n%u of %u routines disagree with the host C library\n", bad, NROUTINES);
    else
        printf("\nall %u routines agree with the host C library\n", NROUTINES);
    return (int)bad;
}
