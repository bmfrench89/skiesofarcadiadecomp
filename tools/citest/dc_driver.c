/*
 * Check the hand-decompiled MSL routines against the host C library.
 *
 * tools/citest/dc_check.py compiles src/sdk/msl/string.c and mem.c with the
 * same /Ddc_* renames the native twin build uses, links them with this driver
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

/* Less of this one is decompiled than it looks. mem.c's memset is a two-line
 * wrapper around __fill_mem, which nobody has decompiled: the rename makes it
 * dc___fill_mem, and runtime/decomp_shims.c answers that with the host memset.
 * So the bytes compared below are the host's own fill on both sides, and what
 * this really pins is the wrapper -- the argument order and the returned
 * pointer, which are exactly what a twin swapped into decomp_swap.c gets
 * wrong. It becomes a check of the fill itself the day __fill_mem lands in
 * src/ (PLAN F3). */
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

static unsigned run(const char* name, unsigned (*test)(void))
{
    unsigned bad;
    g_shown = 0;
    bad = test();
    printf("%s %-10s %5d cases", bad ? "FAIL" : "ok  ", name, ITER);
    if (bad) printf(", %u disagreed", bad);
    printf("\n");
    return bad ? 1u : 0u;
}

/* One table, so the count in the report cannot disagree with the list: PLAN F3
 * takes the decompiled MSL routines past these nine in an evening. */
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
