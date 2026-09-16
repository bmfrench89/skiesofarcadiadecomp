/* Dolphin SDK AR (ARAM) library as the game links it:
 * ARRegisterDMACallback (fn_80241F84), ARGetDMAStatus (fn_80241FC8),
 * ARStartDMA (fn_80242004), ARInit (fn_802420F4), ARGetBaseAddress
 * (fn_802421B8), ARGetSize (fn_802421C0) and __ARHandler (fn_802421C8).
 * __ARChecksize (fn_80242240, 6132 bytes of unrolled DMA probing) is only
 * declared here. ARAlloc, ARFree, ARCheckInit, ARReset, ARGetInternalSize and
 * __ARClearArea were dead-stripped from the game and are not present.
 *
 * Prebuilt SDK library: matches with mwcc 1.2.5n at -O4,p (old-style
 * prologue and blrl indirect calls). */
#include "types.h"

#define ARAM_BASE_ADDRESS 0x4000

#define __OS_INTERRUPT_DSP_ARAM 6
#define OS_INTERRUPTMASK_DSP_ARAM 0x02000000

typedef void (*ARCallback)(void);
typedef s16 __OSInterrupt;
typedef u32 OSInterruptMask;

typedef struct OSContext {
    u8 body[712];
} OSContext;

typedef void (*__OSInterruptHandler)(__OSInterrupt interrupt, OSContext* context);

BOOL OSDisableInterrupts(void);
BOOL OSRestoreInterrupts(BOOL level);
void OSRegisterVersion(const char* id);
void OSClearContext(OSContext* context);
void OSSetCurrentContext(OSContext* context);
__OSInterruptHandler __OSSetInterruptHandler(__OSInterrupt interrupt, __OSInterruptHandler handler);
OSInterruptMask __OSUnmaskInterrupts(OSInterruptMask global);

static volatile u16 __DSPRegs[32] : 0xCC005000;

const char* __ARVersion = "<< Dolphin SDK - AR\trelease build: Nov 10 2003 05:40:52 (0x2301) >>";

static ARCallback __AR_Callback;
static u32 __AR_Size;
static u32 __AR_InternalSize;
static u32 __AR_ExpansionSize;
static u32 __AR_StackPointer;
static u32 __AR_FreeBlocks;
static u32* __AR_BlockLength;
static volatile BOOL __AR_init_flag = FALSE;

static void fn_802421C8(__OSInterrupt interrupt, OSContext* context); /* __ARHandler */
void fn_80242240(void);                                               /* __ARChecksize */

/* ARRegisterDMACallback */
ARCallback fn_80241F84(ARCallback callback)
{
    ARCallback oldCb;
    BOOL enabled;

    oldCb = __AR_Callback;
    enabled = OSDisableInterrupts();
    __AR_Callback = callback;
    OSRestoreInterrupts(enabled);
    return oldCb;
}

/* ARGetDMAStatus */
u32 fn_80241FC8(void)
{
    BOOL enabled;
    u32 val;

    enabled = OSDisableInterrupts();
    val = __DSPRegs[5] & 0x0200;
    OSRestoreInterrupts(enabled);
    return val;
}

/* ARStartDMA */
void fn_80242004(u32 type, u32 mainmem_addr, u32 aram_addr, u32 length)
{
    BOOL enabled;

    enabled = OSDisableInterrupts();

    __DSPRegs[16] = (u16)((__DSPRegs[16] & ~0x03ff) | (mainmem_addr >> 16));
    __DSPRegs[17] = (u16)((__DSPRegs[17] & ~0xffe0) | (mainmem_addr & 0xffff));

    __DSPRegs[18] = (u16)((__DSPRegs[18] & ~0x03ff) | (aram_addr >> 16));
    __DSPRegs[19] = (u16)((__DSPRegs[19] & ~0xffe0) | (aram_addr & 0xffff));

    __DSPRegs[20] = (u16)((__DSPRegs[20] & ~0x8000) | (type << 15));
    __DSPRegs[20] = (u16)((__DSPRegs[20] & ~0x03ff) | (length >> 16));
    __DSPRegs[21] = (u16)((__DSPRegs[21] & ~0xffe0) | (length & 0xffff));

    OSRestoreInterrupts(enabled);
}

/* ARInit */
u32 fn_802420F4(u32* stack_index_addr, u32 num_entries)
{
    BOOL old;
    u16 refresh;

    if (__AR_init_flag == TRUE) {
        return ARAM_BASE_ADDRESS;
    }

    OSRegisterVersion(__ARVersion);

    old = OSDisableInterrupts();

    __AR_Callback = NULL;
    __OSSetInterruptHandler(__OS_INTERRUPT_DSP_ARAM, fn_802421C8);
    __OSUnmaskInterrupts(OS_INTERRUPTMASK_DSP_ARAM);

    __AR_StackPointer = ARAM_BASE_ADDRESS;
    __AR_FreeBlocks = num_entries;
    __AR_BlockLength = stack_index_addr;

    refresh = (u16)(__DSPRegs[13] & 0x00ff);
    __DSPRegs[13] = (u16)((__DSPRegs[13] & ~0x00ff) | (refresh & 0x00ff));

    fn_80242240();

    __AR_init_flag = TRUE;

    OSRestoreInterrupts(old);

    return __AR_StackPointer;
}

/* ARGetBaseAddress */
u32 fn_802421B8(void)
{
    return ARAM_BASE_ADDRESS;
}

/* ARGetSize */
u32 fn_802421C0(void)
{
    return __AR_Size;
}

/* __ARHandler */
static void fn_802421C8(__OSInterrupt interrupt, OSContext* context)
{
    OSContext exceptionContext;
    u16 tmp;

    tmp = __DSPRegs[5];
    tmp = (u16)((tmp & ~(0x0080 | 0x0008)) | 0x0020);
    __DSPRegs[5] = tmp;

    OSClearContext(&exceptionContext);
    OSSetCurrentContext(&exceptionContext);

    if (__AR_Callback) {
        (*__AR_Callback)();
    }

    OSClearContext(&exceptionContext);
    OSSetCurrentContext(context);
}
