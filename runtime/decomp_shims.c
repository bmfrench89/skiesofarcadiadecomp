/*
 * Native stand-ins for functions the decompiled units call but nobody has
 * decompiled yet. The native twin build (tools/recompile.py) renames every
 * function a unit declares to dc_<name>; when the callee has no decompiled
 * body, its dc_ symbol must come from here. Keep each one a faithful
 * description of what the original does; retire it when the real function
 * lands in src/.
 */
#include <stddef.h>
#include <string.h>

/* MSL __fill_mem: memset's worker (word-at-a-time fill on the console). */
void dc___fill_mem(void* dst, int val, size_t n)
{
    memset(dst, val, n);
}
