/* The ARAM package cache table (see aramcache.c). */
#ifndef ARAMCACHE_H
#define ARAMCACHE_H
#include "types.h"

typedef struct AramSlot {
    u32 valid;               /* 1 once the package sits in ARAM */
    u32 owner;               /* ARQ owner id */
    u32 unused;
    u32 priority;            /* ARQ priority */
    void* staging;           /* main-memory buffer while the package loads */
    u32 aramAddr;
    u32 length;
    void (*callback)(u32);   /* ARQ completion */
} AramSlot;

typedef struct AramCacheTable {
    AramSlot slot[16];
    u32 tail;                /* the checksum covers this word too */
} AramCacheTable;

extern AramCacheTable aramCache;      /* 0x803165C8 */
extern const char* aramCacheNames[16]; /* 0x802F91F8 */
extern u32 aramCacheChecksum;         /* small data */
extern int aramCacheDone;             /* small data */

#endif
