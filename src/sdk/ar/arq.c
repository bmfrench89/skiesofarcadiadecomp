/* Dolphin SDK ARQ (ARAM request queue) library as the game links it:
 * __ARQServiceQueueLo (fn_80243A34), __ARQCallbackHack (fn_80243B34),
 * __ARQInterruptServiceRoutine (fn_80243B38), ARQInit (fn_80243C04),
 * ARQPostRequest (fn_80243C74), ARQSetChunkSize (fn_80243DD0) and
 * ARQGetChunkSize (fn_80243DF0). __ARQPopTaskQueueHi is inlined at both of
 * its call sites and not emitted on its own.
 *
 * This is a prebuilt SDK library, not game code: it matches with mwcc 1.2.5n
 * (or 1.1) at -O4,p, whose old-style prologue (mflr; stw r0,4(r1); stwu) and
 * blrl indirect calls the game's own 1.3.2 build does not produce. */
#include "types.h"

#define ARQ_TYPE_MRAM_TO_ARAM 0
#define ARQ_TYPE_ARAM_TO_MRAM 1
#define ARQ_PRIORITY_LOW 0
#define ARQ_PRIORITY_HIGH 1
#define ARQ_CHUNK_SIZE_DEFAULT 4096

typedef void (*ARQCallback)(u32 pointerToRequest);

typedef struct ARQRequest {
    struct ARQRequest* next;
    u32 owner;
    u32 type;
    u32 priority;
    u32 source;
    u32 dest;
    u32 length;
    ARQCallback callback;
} ARQRequest;

typedef void (*ARCallback)(void);

BOOL OSDisableInterrupts(void);
BOOL OSRestoreInterrupts(BOOL level);
void OSRegisterVersion(const char* id);
void ARStartDMA(u32 type, u32 mainmem_addr, u32 aram_addr, u32 length); /* fn_80242004 */
ARCallback ARRegisterDMACallback(ARCallback callback);                     /* fn_80241F84 */

const char* __ARQVersion = "<< Dolphin SDK - ARQ\trelease build: Sep  5 2002 05:34:29 (0x2301) >>";

static ARQRequest* __ARQRequestQueueHi;
static ARQRequest* __ARQRequestTailHi;
static ARQRequest* __ARQRequestQueueLo;
static ARQRequest* __ARQRequestTailLo;
static ARQRequest* __ARQRequestPendingHi;
static ARQRequest* __ARQRequestPendingLo;
static ARQCallback __ARQCallbackHi;
static ARQCallback __ARQCallbackLo;
static u32 __ARQChunkSize;
static volatile BOOL __ARQInitFlag = FALSE;

static inline void __ARQPopTaskQueueHi(void)
{
    if (__ARQRequestQueueHi) {
        if (__ARQRequestQueueHi->type == ARQ_TYPE_MRAM_TO_ARAM) {
            ARStartDMA(__ARQRequestQueueHi->type, __ARQRequestQueueHi->source,
                       __ARQRequestQueueHi->dest, __ARQRequestQueueHi->length);
        } else {
            ARStartDMA(__ARQRequestQueueHi->type, __ARQRequestQueueHi->dest,
                       __ARQRequestQueueHi->source, __ARQRequestQueueHi->length);
        }
        __ARQCallbackHi = __ARQRequestQueueHi->callback;
        __ARQRequestPendingHi = __ARQRequestQueueHi;
        __ARQRequestQueueHi = __ARQRequestQueueHi->next;
    }
}

/* __ARQServiceQueueLo */
static void fn_80243A34(void)
{
    if ((__ARQRequestPendingLo == NULL) && __ARQRequestQueueLo) {
        __ARQRequestPendingLo = __ARQRequestQueueLo;
        __ARQRequestQueueLo = __ARQRequestQueueLo->next;
    }

    if (__ARQRequestPendingLo) {
        if (__ARQRequestPendingLo->length <= __ARQChunkSize) {
            if (__ARQRequestPendingLo->type == ARQ_TYPE_MRAM_TO_ARAM) {
                ARStartDMA(__ARQRequestPendingLo->type, __ARQRequestPendingLo->source,
                           __ARQRequestPendingLo->dest, __ARQRequestPendingLo->length);
            } else {
                ARStartDMA(__ARQRequestPendingLo->type, __ARQRequestPendingLo->dest,
                           __ARQRequestPendingLo->source, __ARQRequestPendingLo->length);
            }
            __ARQCallbackLo = __ARQRequestPendingLo->callback;
        } else {
            if (__ARQRequestPendingLo->type == ARQ_TYPE_MRAM_TO_ARAM) {
                ARStartDMA(__ARQRequestPendingLo->type, __ARQRequestPendingLo->source,
                           __ARQRequestPendingLo->dest, __ARQChunkSize);
            } else {
                ARStartDMA(__ARQRequestPendingLo->type, __ARQRequestPendingLo->dest,
                           __ARQRequestPendingLo->source, __ARQChunkSize);
            }
        }
        __ARQRequestPendingLo->length -= __ARQChunkSize;
        __ARQRequestPendingLo->source += __ARQChunkSize;
        __ARQRequestPendingLo->dest += __ARQChunkSize;
    }
}

/* __ARQCallbackHack: the completion callback stored when none is given. */
static void fn_80243B34(u32 pointerToRequest)
{
}

/* __ARQInterruptServiceRoutine */
static void fn_80243B38(void)
{
    if (__ARQCallbackHi) {
        (*__ARQCallbackHi)((u32)__ARQRequestPendingHi);
        __ARQRequestPendingHi = NULL;
        __ARQCallbackHi = NULL;
    } else if (__ARQCallbackLo) {
        (*__ARQCallbackLo)((u32)__ARQRequestPendingLo);
        __ARQRequestPendingLo = NULL;
        __ARQCallbackLo = NULL;
    }

    __ARQPopTaskQueueHi();

    if (__ARQRequestPendingHi == NULL) {
        fn_80243A34();
    }
}

/* ARQInit */
void fn_80243C04(void)
{
    if (__ARQInitFlag == TRUE) {
        return;
    }

    OSRegisterVersion(__ARQVersion);

    __ARQRequestQueueHi = __ARQRequestQueueLo = NULL;
    __ARQChunkSize = ARQ_CHUNK_SIZE_DEFAULT;
    ARRegisterDMACallback(fn_80243B38);

    /* Written as two statements each, not chained. A chained assignment
     * evaluates right to left, so it stores Lo before Hi; the executable
     * stores them in address order. The four words differ only in the
     * small-data field the linker fills, which is why this read as a match
     * until matchcheck learned to solve those fields. */
    __ARQRequestPendingHi = NULL;
    __ARQRequestPendingLo = NULL;
    __ARQCallbackHi = NULL;
    __ARQCallbackLo = NULL;
    __ARQInitFlag = TRUE;
}

/* ARQPostRequest */
void fn_80243C74(ARQRequest* task, u32 owner, u32 type, u32 priority, u32 source, u32 dest,
                 u32 length, ARQCallback callback)
{
    BOOL enabled;

    task->next = NULL;
    task->owner = owner;
    task->type = type;
    task->source = source;
    task->dest = dest;
    task->length = length;
    if (callback) {
        task->callback = callback;
    } else {
        task->callback = fn_80243B34;
    }

    enabled = OSDisableInterrupts();

    switch (priority) {
    case ARQ_PRIORITY_LOW:
        if (__ARQRequestQueueLo) {
            __ARQRequestTailLo->next = task;
        } else {
            __ARQRequestQueueLo = task;
        }
        __ARQRequestTailLo = task;
        break;

    case ARQ_PRIORITY_HIGH:
        if (__ARQRequestQueueHi) {
            __ARQRequestTailHi->next = task;
        } else {
            __ARQRequestQueueHi = task;
        }
        __ARQRequestTailHi = task;
        break;
    }

    if ((__ARQRequestPendingHi == NULL) && (__ARQRequestPendingLo == NULL)) {
        __ARQPopTaskQueueHi();
        if (__ARQRequestPendingHi == NULL) {
            fn_80243A34();
        }
    }

    OSRestoreInterrupts(enabled);
}

/* ARQSetChunkSize */
void fn_80243DD0(u32 size)
{
    if (size % 32) {
        __ARQChunkSize = size + (32 - (size % 32));
    } else {
        __ARQChunkSize = size;
    }
}

/* ARQGetChunkSize */
u32 fn_80243DF0(void)
{
    return __ARQChunkSize;
}
