/*
 * The power line in every run report (H20, docs/specs/power-line.md): AC or
 * battery, the battery's charge, the power plan and Windows' power mode, and
 * on battery the energy the run used, in all and per 1000 frames drawn. A
 * frame rate means one machine on AC in Turbo and another on battery in a
 * quiet mode, and until now only a person's note said which.
 *
 * power_line is a pure function of two readings, so the test feeds it any
 * pair (tools/tests/test_power.py); the readings are plat.c's.
 */
#include "power.h"

#include <stdio.h>
#include <string.h>

unsigned gx_frame_count(void);

static PlatPower g_start;
static unsigned g_start_frame;

/* "plan Turbo, mode best performance", the parts that are known. */
static size_t names(const PlatPower* p, char* out, size_t cap)
{
    int n = snprintf(out, cap, ", plan %s, mode %s", p->plan[0] ? p->plan : "-", p->mode[0] ? p->mode : "-");
    return n < 0 ? 0 : (size_t)n >= cap ? cap - 1 : (size_t)n;
}

void power_line(const PlatPower* a, const PlatPower* b, unsigned frames, char* out, size_t cap)
{
    size_t used;
    int n;
    if (!b->known) {
        snprintf(out, cap, "[power] not known on this system");
        return;
    }
    if (a->known && a->ac >= 0 && b->ac >= 0 && a->ac != b->ac) {
        snprintf(out, cap, "[power] %s at the start, %s at the report: no energy figure for a run that changed source",
                 a->ac ? "AC" : "battery", b->ac ? "AC" : "battery");
        return;
    }
    if (b->battery == 0) {
        n = snprintf(out, cap, "[power] %s, no battery", b->ac == 0 ? "battery" : "AC");
    } else if (b->ac == 0 && a->known && a->percent >= 0 && b->percent >= 0) {
        n = snprintf(out, cap, "[power] battery %d%% -> %d%%", a->percent, b->percent);
    } else if (b->percent >= 0) {
        n = snprintf(out, cap, "[power] %s, battery %d%%", b->ac == 0 ? "battery" : b->ac == 1 ? "AC" : "source -",
                     b->percent);
    } else {
        n = snprintf(out, cap, "[power] %s", b->ac == 0 ? "battery" : b->ac == 1 ? "AC" : "source -");
    }
    used = n < 0 ? 0 : (size_t)n >= cap ? cap - 1 : (size_t)n;
    used += names(b, out + used, cap - used);
    if (b->ac == 0 && a->known && a->ac == 0 && a->mwh >= 0 && b->mwh >= 0) {
        if (b->mwh > a->mwh)
            snprintf(out + used, cap - used, "; the battery reads %lld mWh more than at the start, so no energy figure",
                     b->mwh - a->mwh);
        else if (frames)
            snprintf(out + used, cap - used, "; %lld mWh over %u frames, %lld mWh a 1000", a->mwh - b->mwh, frames,
                     (a->mwh - b->mwh) * 1000 / frames);
        else
            snprintf(out + used, cap - used, "; %lld mWh over no frame drawn", a->mwh - b->mwh);
    }
}

void power_start(void)
{
    plat_power_read(&g_start);
    g_start_frame = gx_frame_count();
}

void power_report(void)
{
    PlatPower now;
    char line[256];
    plat_power_read(&now);
    power_line(&g_start, &now, gx_frame_count() - g_start_frame, line, sizeof line);
    fprintf(stderr, "%s\n", line);
}
