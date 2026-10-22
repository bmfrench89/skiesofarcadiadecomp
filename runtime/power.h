/* The power line in every run report (H20, docs/specs/power-line.md). */
#ifndef SOA_POWER_H
#define SOA_POWER_H

#include <stddef.h>

/* One reading of the machine's power: plat_power_read's (plat.c). A part
 * that could not be read is -1, or "" for the names. */
typedef struct PlatPower {
    int known;          /* 0: this system says nothing */
    int ac;             /* 1 on mains, 0 on battery, -1 not known */
    int battery;        /* 1 a battery is there, 0 none, -1 not known */
    int percent;        /* the battery's charge, 0-100, or -1 */
    long long mwh;      /* the battery's remaining energy in mWh, or -1 */
    char plan[64];      /* the power plan's name (Windows), or "" */
    char mode[32];      /* Windows' power mode: best power efficiency, balanced, best performance; or "" */
} PlatPower;

/* Fill *p now; 0 when nothing is known here. */
int plat_power_read(PlatPower* p);

/* The report's line, without its newline, from a reading at the start and one
 * at the report, `frames` drawn between them (power.c). */
void power_line(const PlatPower* start, const PlatPower* end, unsigned frames, char* out, size_t cap);

/* The run's reading at its start, and its line at the report (main.c). */
void power_start(void);
void power_report(void);

#endif
