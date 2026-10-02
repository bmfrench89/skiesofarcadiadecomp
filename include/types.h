/* Minimal types for hand-decompiled units compiled with mwcc (no MSL headers). */
#ifndef TYPES_H
#define TYPES_H

#if defined(__MWERKS__)
/* mwcc, the game's own build (tools/decomp.py): the types every unit was
 * matched with. A change here is safe only when decomp.py still matches. */
typedef unsigned long size_t;
typedef signed long s32;
typedef unsigned long u32;
#else
/* A host: the native twins tools/recompile.py builds, the CI checks, and
 * every platform the port targets. long is 32 bits on Windows and 64 on
 * Linux and Android, and the game's code assumes 32-bit words (portability.md
 * 3.7, L4b), so they are spelled out here rather than inherited from long. */
#include <stddef.h>
#include <stdint.h>
typedef signed long s32; /* MUTATION: the host branch reverted to long */
typedef unsigned long u32;
#endif
typedef signed char s8;
typedef unsigned char u8;
typedef signed short s16;
typedef unsigned short u16;
typedef signed long long s64;
typedef unsigned long long u64;
typedef float f32;
typedef double f64;
typedef int BOOL;

#ifndef NULL
#define NULL 0
#endif
#define TRUE 1
#define FALSE 0

#endif
