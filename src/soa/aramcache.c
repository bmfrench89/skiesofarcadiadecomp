/* The ARAM package cache: sixteen battle packages staged into ARAM at boot,
 * described by a 32-byte slot table guarded by a byte checksum (see
 * docs/FINDINGS.md, "The ARAM package cache"). Decompiled from
 * fn_8022A7F4..fn_8022AE88. */
#include "types.h"

#include "aramcache.h"

char* strstr(const char* str, const char* pat);
void* memcpy(void* dst, const void* src, size_t n);

/* Saved at 0x80800000 across a soft reset. */
void aramCacheRestore(void)
{
    memcpy(&aramCache, (void*)0x80800000, sizeof(AramCacheTable));
}

void aramCacheSave(void)
{
    memcpy((void*)0x80800000, &aramCache, sizeof(AramCacheTable));
}

void aramCacheCallback(u32 task)
{
    aramCacheDone = 1;
}

