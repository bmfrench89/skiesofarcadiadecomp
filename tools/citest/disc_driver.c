/*
 * runtime/disc.c on its own, driven line by line from stdin by
 * tools/citest/disc_check.py, which builds it for a synthetic image (the game
 * id and the DOL's SHA-1 are the fixture's, defined before disc.c is
 * included by the wrapper it writes):
 *
 *   open <path>          "open ok", then "dol|boot|fst <bytes> <sha1>"; or "refused <why>"
 *   serve <off> <len>    "serve <sha1 of the bytes>"   (the drive's read: counted)
 *   peek <off> <len>     "peek <bytes from the image> <sha1>"
 *   name <off>           "name <path> <start> <size>", or "name -"
 *   report               disc_report's lines, on stdout
 *
 * Offsets and lengths are decimal. No guest, no clock: disc.c needs only the
 * frame counter, which is 0 here.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "disc.h"
#include "sha1.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

unsigned gx_frame_count(void) { return 0; }

int main(void)
{
    char line[2048], why[1024], hex[41];
    while (fgets(line, sizeof line, stdin)) {
        char cmd[16] = {0}, arg[1800] = {0};
        unsigned long long off = 0, len = 0;
        line[strcspn(line, "\r\n")] = 0;
        if (sscanf(line, "%15s", cmd) != 1) continue;
        if (!strcmp(cmd, "open")) {
            const uint8_t *dol, *boot, *fst;
            size_t dol_n, fst_n;
            snprintf(arg, sizeof arg, "%s", line + 5);
            if (disc_open(arg, why, sizeof why) != 0) {
                printf("refused %s\n", why);
            } else if (disc_system(&dol, &dol_n, &boot, &fst, &fst_n, why, sizeof why) != 0) {
                printf("refused %s\n", why);
            } else {
                printf("open ok\n");
                sha1_hex(dol, dol_n, hex);
                printf("dol %zu %s\n", dol_n, hex);
                sha1_hex(boot, 0x440, hex);
                printf("boot %u %s\n", 0x440u, hex);
                sha1_hex(fst, fst_n, hex);
                printf("fst %zu %s\n", fst_n, hex);
            }
        } else if (!strcmp(cmd, "serve") || !strcmp(cmd, "peek")) {
            uint8_t* buf;
            uint32_t got = 0;
            if (sscanf(line, "%*s %llu %llu", &off, &len) != 2 || len > (64u << 20)) {
                printf("bad %s\n", line);
                continue;
            }
            buf = (uint8_t*)malloc(len ? (size_t)len : 1);
            if (!buf) return 2;
            memset(buf, 0xA5, (size_t)len); /* so a byte never written shows */
            if (cmd[0] == 's') disc_serve(off, buf, (uint32_t)len);
            else got = disc_peek(off, buf, (uint32_t)len);
            sha1_hex(buf, (size_t)len, hex);
            if (cmd[0] == 's') printf("serve %s\n", hex);
            else printf("peek %u %s\n", got, hex);
            free(buf);
        } else if (!strcmp(cmd, "name")) {
            uint64_t start = 0;
            uint32_t size = 0;
            const char* name;
            if (sscanf(line, "%*s %llu", &off) != 1) {
                printf("bad %s\n", line);
                continue;
            }
            name = disc_name_at(off, &start, &size);
            if (name) printf("name %s %llu %u\n", name, (unsigned long long)start, size);
            else printf("name -\n");
        } else if (!strcmp(cmd, "report")) {
            fflush(stdout);
            disc_report();
            fflush(stderr);
            printf("report done\n");
        } else {
            printf("bad %s\n", line);
        }
        fflush(stdout);
    }
    disc_close();
    return 0;
}
