/* aramCacheFetch (fn_8022ACA8): pull a cached package back out of ARAM into
 * a freshly allocated main-memory buffer, synchronously, and return it (NULL
 * when the table's checksum no longer holds, the slot is empty, or the
 * allocation fails). The ARQ chunk size is widened to 32 for the transfer
 * and restored afterwards; the completion callback stored in the slot sets
 * aramCacheDone. The checksum/valid helpers are the same static ones that
 * -inline auto folds into aramCacheValid (src/soa/aramcache_valid.c). */
#include "types.h"

#include "aramcache.h"

/* ARQ request block that follows the table at 0x803167CC. */
typedef struct AramCacheReq {
    u32 words[16];
} AramCacheReq;

extern AramCacheReq aramCacheReq;

/* The slot as this unit sees it: the valid flag compares signed here. */
typedef struct FetchSlot {
    s32 valid;
    u32 owner;
    u32 unused;
    u32 priority;
    void* staging;
    u32 aramAddr;
    u32 length;
    void (*callback)(u32);
} FetchSlot;

void* fn_801E1C7C(u32 size);                      /* heap allocate */
u32 fn_80241FC8(void);                            /* ARGetDMAStatus */
u32 ARQGetChunkSize(void);
void ARQSetChunkSize(u32 size);
void DCInvalidateRange(void* addr, u32 nBytes);
void ARQPostRequest(void* req, u32 owner, u32 type, u32 priority, u32 source,
                    u32 dest, u32 length, void (*callback)(u32));

static u32 aramCacheSum(void)
{
    const u8* p = (const u8*)&aramCache;
    u32 sum = 0;
    int i;

    for (i = 516; i > 0; i--)
        sum += *p++;

    return sum;
}

static int aramCacheSlotValid(int index)
{
    int valid = 0;
    int intact = 0;

    if (aramCacheChecksum == aramCacheSum())
        intact = 1;
    if (intact)
        valid = aramCache.slot[index].valid;

    return valid;
}

void* aramCacheFetch(int index)
{
    void* buf = NULL;
    FetchSlot* slot;
    u32 chunk;

    if (aramCacheSlotValid(index)) {
        slot = (FetchSlot*)&aramCache.slot[index];
        if (slot->valid) {
            buf = fn_801E1C7C(slot->length);
            if (buf) {
                while (fn_80241FC8() != 0)
                    ;
                chunk = ARQGetChunkSize();
                ARQSetChunkSize(32);
                aramCacheDone = 0;
                DCInvalidateRange(buf, slot->length);
                ARQPostRequest(&aramCacheReq, slot->owner, 1, slot->priority,
                               slot->aramAddr, (u32)buf, slot->length,
                               slot->callback);
                while (*(volatile int*)&aramCacheDone == 0)
                    ;
                ARQSetChunkSize(chunk);
            }
        }
    }
    return buf;
}
