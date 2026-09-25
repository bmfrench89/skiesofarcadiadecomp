/*
 * The race seed (docs/PLAN-GAMEPLAY-MODS.md P6; the comfort-pack spec 3.3).
 *
 * The game seeds its random numbers from the timebase, through OSGetTick
 * (0x8023851C, `mftb r3; blr`), at three sites: every field load (the call
 * returns to 0x801012B0) and twice at every battle start (0x8000A1D0 and
 * 0x8000A1D8, in fn_8000A118). Each is followed at once by srand
 * (fn_8025ECBC), which stores its argument to the seed word 0x803469A8.
 * With SOA_SEED set, those three calls -- and only those -- return a value
 * made from the seed, the site and how many times that site has been
 * reached, so the same seed gives the same sequence of seeds; every other
 * read of the timebase is left as it was.
 *
 * guest_timebase_lo (hle.c) asks here only when the guest's pc is
 * OSGetTick's: cpu.h calls s->pc "diagnostics only", and this is the one
 * place it decides something. The gate is necessary as well as sufficient:
 * dvd.c, dsp.c, aram.c and irq.c read the timebase through the guest's
 * CpuState with whatever lr the guest last set, and pinning on lr alone
 * would pin a device's clock.
 *
 * Plain C with no Windows in it, and built alone by tools/tests/test_seed.py.
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SITES 3
static const uint32_t k_site[SITES] = {0x801012B0u, 0x8000A1D0u, 0x8000A1D8u};

int g_seed_on;
static uint32_t g_seed;
static unsigned long long g_pinned[SITES], g_other;

/* MurmurHash3's finaliser: every bit of the input moves every bit of the
 * output, so seeds one apart give unrelated sequences. */
static uint32_t fmix32(uint32_t h)
{
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
}

/* The value the n-th call at a site returns, for seed s. */
uint32_t seed_value(uint32_t s, int site, uint32_t n)
{
    return fmix32(s ^ (uint32_t)(site + 1) * 0x9E3779B9u ^ n * 0x85EBCA6Bu);
}

/* OSGetTick's answer: pinned at the three sites, the timebase elsewhere. */
uint32_t seed_pin(uint32_t lr, uint32_t tb)
{
    int i;
    for (i = 0; i < SITES; i++)
        if (lr == k_site[i]) return seed_value(g_seed, i, (uint32_t)g_pinned[i]++);
    g_other++;
    return tb;
}

/* For the self test and the tests: pin with this seed, counts from zero. */
void seed_set(int on, uint32_t seed)
{
    g_seed_on = on;
    g_seed = seed;
    memset(g_pinned, 0, sizeof g_pinned);
    g_other = 0;
}

/* SOA_SEED: a decimal number, or 0x and up to eight hex digits, 32 bits.
 * Anything else is refused out loud and the seeds stay the game's own. */
int seed_init(void)
{
    const char* v = getenv("SOA_SEED");
    unsigned long long n = 0;
    int ok;
    if (!v || !*v) return 0;
    if (v[0] == '0' && (v[1] == 'x' || v[1] == 'X')) {
        const char* h = v + 2;
        ok = *h && strlen(h) <= 8 && strspn(h, "0123456789abcdefABCDEF") == strlen(h);
        if (ok) n = strtoull(h, NULL, 16);
    } else {
        ok = strlen(v) <= 10 && strspn(v, "0123456789") == strlen(v);
        if (ok) n = strtoull(v, NULL, 10);
        ok = ok && n <= 0xFFFFFFFFull;
    }
    if (!ok) {
        fprintf(stderr, "[seed] SOA_SEED=%s is not a 32-bit number (decimal, or 0x and hex digits); the game seeds itself\n", v);
        return 0;
    }
    seed_set(1, (uint32_t)n);
    fprintf(stderr, "[seed] SOA_SEED=%s: the field-load and battle-start reseeds are pinned; a recording names the seed\n", v);
    return 1;
}

/* One line in the report: how many reseeds each site pinned, and how many
 * other OSGetTick reads went by untouched. */
void seed_report(void)
{
    if (!g_seed_on) return;
    fprintf(stderr, "[seed] SOA_SEED=%u: field load %llu, battle start %llu and %llu pinned; %llu other OSGetTick reads left alone\n",
            g_seed, g_pinned[0], g_pinned[1], g_pinned[2], g_other);
}
