/*
 * libm_check's driver (portability.md 3.8, L6): runtime/crmath.h's soa_exp2f
 * or soa_log2f over one slice of the inputs the renderer can give it.
 *
 *     libm_driver exp2f|log2f <first bits> <last bits>     (hex, inclusive)
 *
 * Each output is compared with the host's double-precision function rounded
 * to float. That reference is good to far better than 2^-40 relative, so
 * where it lies within 2^-40 of a float rounding boundary its rounding cannot
 * be trusted, and the input is printed for libm_check.py to settle with
 * Python's decimal at 50 digits; everywhere else a different output is a
 * wrong one. The slice's outputs are hashed with FNV-1a, four bytes each,
 * low byte first.
 *
 * Prints "arb <x> <r>" per arbitrated input, "wrong <x> <r> <ref>" for the
 * first 20 wrong ones, then "slice <fn> <first> <last> <inputs> <wrong>
 * <arbitrated> <hash>". -DLIBM_HOST checks the host's own exp2f and log2f
 * instead: the mutation, which on UCRT must report 2.5's 74,154 and 313,550.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "crmath.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t bits_of(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

static float float_of(uint32_t u)
{
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static float under_test(int log, float x)
{
#ifdef LIBM_HOST
    return log ? log2f(x) : exp2f(x);
#else
    return log ? soa_log2f(x) : soa_exp2f(x);
#endif
}

/* Whether ref, rounded to float, could round the other way for an error of
 * 2^-40 relative: whether it lies that near the midpoint between its float
 * and the next one on its side. */
static int near_boundary(double ref)
{
    float f = (float)ref;
    double fd = f, mid;
    if (fd == ref || !isfinite(ref)) return 0;
    mid = (fd + (double)nextafterf(f, ref > fd ? INFINITY : -INFINITY)) * 0.5;
    return fabs(ref - mid) <= ldexp(fabs(ref), -40);
}

int main(int argc, char** argv)
{
    uint64_t hash = 0xcbf29ce484222325ull, inputs = 0, wrong = 0, arb = 0;
    uint32_t first, last, u;
    int log, k;
    if (argc != 4 || (strcmp(argv[1], "exp2f") && strcmp(argv[1], "log2f"))) {
        fprintf(stderr, "usage: libm_driver exp2f|log2f <first bits> <last bits>\n");
        return 2;
    }
    log = argv[1][0] == 'l';
    first = (uint32_t)strtoul(argv[2], NULL, 16);
    last = (uint32_t)strtoul(argv[3], NULL, 16);
    for (u = first;; u++) {
        float x = float_of(u), r = under_test(log, x);
        double ref = log ? log2((double)x) : exp2((double)x);
        uint32_t rb = bits_of(r);
        inputs++;
        if (near_boundary(ref)) {
            printf("arb %08lX %08lX\n", (unsigned long)u, (unsigned long)rb);
            arb++;
        } else if (rb != bits_of((float)ref)) {
            if (wrong < 20)
                printf("wrong %08lX %08lX %08lX\n", (unsigned long)u, (unsigned long)rb,
                       (unsigned long)bits_of((float)ref));
            wrong++;
        }
        for (k = 0; k < 4; k++) hash = (hash ^ ((rb >> (8 * k)) & 0xFF)) * 0x100000001b3ull;
        if (u == last) break;
    }
    printf("slice %s %08lX %08lX %llu %llu %llu %016llx\n", argv[1], (unsigned long)first, (unsigned long)last,
           (unsigned long long)inputs, (unsigned long long)wrong, (unsigned long long)arb, (unsigned long long)hash);
    return 0;
}
