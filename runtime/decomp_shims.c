/*
 * Native stand-ins for functions the decompiled units call but nobody has
 * decompiled yet. The native twin build (tools/recompile.py) renames every
 * function a unit declares to dc_<name>; when the callee has no decompiled
 * body, its dc_ symbol must come from here. Keep each one a faithful
 * description of what the original does; retire it when the real function
 * lands in src/.
 *
 * Empty at the moment. dc___fill_mem lived here because src/sdk/msl/fillmem.c
 * assigned to a cast and so could not be compiled for the host; it now can, is
 * marked native in config/GEAE8P/units.txt, and memset reaches the decompiled
 * worker rather than the host's memset. A stub added here has to be removed
 * again the day its unit goes native, or the two definitions collide at link
 * time -- which is the reason to keep the list short.
 */
#include <stddef.h>
#include <string.h>
