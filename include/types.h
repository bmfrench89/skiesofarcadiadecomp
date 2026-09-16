/* Minimal types for hand-decompiled units compiled with mwcc (no MSL headers). */
#ifndef TYPES_H
#define TYPES_H

typedef unsigned long size_t;
typedef signed char s8;
typedef unsigned char u8;
typedef signed short s16;
typedef unsigned short u16;
typedef signed long s32;
typedef unsigned long u32;
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
