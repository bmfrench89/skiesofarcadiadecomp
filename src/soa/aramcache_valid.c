/* aramCacheValid (fn_8022AE04): the slot's valid flag, or 0 when the ARAM
 * cache table's byte checksum no longer holds.
 *
 * The checksum test is a static helper that -inline auto folds into the
 * caller; the same six-fold unrolled loop (86 iterations of 6 bytes over the
 * 516-byte table) appears three times inside aramCacheStage, which is what
 * one expects from an inlined helper. Three things are load-bearing for the
 * match: the count-down loop (a count-up loop is unrolled by 16 with a
 * remainder), the helper keeping its own flag variable and returning it (the
 * compiler then shares the zero between the flag and the sum, giving the
 * "mr sum, intact" in the prologue), and the declaration order p, intact,
 * sum, which sets the register assignment (sum r4, intact r5, p r6). */
#include "types.h"

#include "aramcache.h"

/* 1 when the sum of every byte of the table equals the stored checksum. */
static int aramCacheIntact(void)
{
    const u8* p = (const u8*)&aramCache;
    int intact = 0;
    u32 sum = 0;
    int i;

    for (i = 516; i > 0; i--)
        sum += *p++;

    if (aramCacheChecksum == sum)
        intact = 1;
    return intact;
}

u32 aramCacheValid(int index)
{
    u32 valid = 0;

    if (aramCacheIntact())
        valid = aramCache.slot[index].valid;

    return valid;
}
