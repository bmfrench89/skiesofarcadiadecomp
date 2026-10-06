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
 *   builtin              "builtin <1|0|-1> <why>": the build's own system files (I3)
 *   system               disc_system with or without an image open: as open's three lines
 *   checkstore <path>    "checkstore <0|9>": disc_check_store, soa.exe --check-disc's (I5)
 *   report               disc_report's lines, on stdout
 *   words phone|pc       disc_set_phone_words: the refusals from here on in a phone's words, or the PC's
 *   identify <path>      "identify ok", or "refused <why>": disc_identify, on what the file holds so far
 *   truncate <n> <path>  "truncate ok": the file cut to n bytes, as storage failing under an open disc
 *   portdol              "portdol <sha1>": disc_port_dol_sha1
 *   bybuild              "bybuild <0|1>": disc_refused_by_build, of the last open
 *   table                (a split build) "table ok": soa_game_table set, as runtime/game.c sets it
 *
 * Offsets and lengths are decimal. No guest, no clock: disc.c needs only the
 * frame counter, which is 0 here, and a disc_sys.c, which disc_check.py
 * writes: the fixture's system files built in, or none (--no-embed's). Built
 * with SOA_SPLIT, disc.c reads them through soa_game_table instead, as a
 * phone's runtime does, and `table` points it at them.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "disc.h"
#include "sha1.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#include <fcntl.h>
#else
#include <unistd.h>
#endif

unsigned gx_frame_count(void) { return 0; }

#ifdef SOA_SPLIT
#include "soa_game.h"
extern const uint32_t disc_sys_dol[], disc_sys_boot[], disc_sys_fst[];
extern const size_t disc_sys_dol_size, disc_sys_boot_size, disc_sys_fst_size;
extern const char disc_sys_dol_sha1[], disc_sys_boot_sha1[], disc_sys_fst_sha1[];
const SoaGame* soa_game_table;
static SoaGame g_table;
#endif

/* The file at `path` cut to `n` bytes, while disc.c may hold it open. */
static int cut(const char* path, long long n)
{
#ifdef _WIN32
    int fd = _open(path, _O_RDWR | _O_BINARY), r;
    if (fd < 0) return -1;
    r = _chsize_s(fd, n);
    _close(fd);
    return r == 0 ? 0 : -1;
#else
    return truncate(path, (off_t)n);
#endif
}

int main(void)
{
    char line[2048], why[1024], hex[41];
    while (fgets(line, sizeof line, stdin)) {
        char cmd[16] = {0}, arg[sizeof line] = {0}; /* a path, never longer than its line */
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
        } else if (!strcmp(cmd, "builtin")) {
            int b;
            why[0] = 0;
            b = disc_builtin(why, sizeof why);
            printf("builtin %d %s\n", b, why);
        } else if (!strcmp(cmd, "system")) {
            const uint8_t *dol, *boot, *fst;
            size_t dol_n, fst_n;
            if (disc_system(&dol, &dol_n, &boot, &fst, &fst_n, why, sizeof why) != 0) {
                printf("refused %s\n", why);
            } else {
                printf("system ok\n");
                sha1_hex(dol, dol_n, hex);
                printf("dol %zu %s\n", dol_n, hex);
                sha1_hex(boot, 0x440, hex);
                printf("boot %u %s\n", 0x440u, hex);
                sha1_hex(fst, fst_n, hex);
                printf("fst %zu %s\n", fst_n, hex);
            }
        } else if (!strcmp(cmd, "checkstore")) {
            snprintf(arg, sizeof arg, "%s", line + 11);
            fflush(stdout);
            printf("checkstore %d\n", disc_check_store(arg));
        } else if (!strcmp(cmd, "report")) {
            fflush(stdout);
            disc_report();
            fflush(stderr);
            printf("report done\n");
        } else if (!strcmp(cmd, "words")) {
            int phone = strstr(line + 5, "phone") != NULL;
            disc_set_phone_words(phone);
            printf("words %s\n", phone ? "phone" : "pc");
        } else if (!strcmp(cmd, "identify")) {
            snprintf(arg, sizeof arg, "%s", line + 9);
            if (disc_identify(arg, why, sizeof why) != 0) printf("refused %s\n", why);
            else printf("identify ok\n");
        } else if (!strcmp(cmd, "truncate")) {
            int at = 0;
            if (sscanf(line, "%*s %llu %n", &len, &at) != 1 || !at) {
                printf("bad %s\n", line);
                continue;
            }
            printf("truncate %s\n", cut(line + at, (long long)len) == 0 ? "ok" : "failed");
        } else if (!strcmp(cmd, "portdol")) {
            printf("portdol %s\n", disc_port_dol_sha1());
        } else if (!strcmp(cmd, "bybuild")) {
            printf("bybuild %d\n", disc_refused_by_build());
#ifdef SOA_SPLIT
        } else if (!strcmp(cmd, "table")) {
            g_table.abi = SOA_GAME_ABI;
            g_table.size = sizeof g_table;
            g_table.dol = disc_sys_dol;
            g_table.boot = disc_sys_boot;
            g_table.fst = disc_sys_fst;
            g_table.dol_size = &disc_sys_dol_size;
            g_table.boot_size = &disc_sys_boot_size;
            g_table.fst_size = &disc_sys_fst_size;
            g_table.dol_sha1 = disc_sys_dol_sha1;
            g_table.boot_sha1 = disc_sys_boot_sha1;
            g_table.fst_sha1 = disc_sys_fst_sha1;
            soa_game_table = &g_table;
            printf("table ok\n");
#endif
        } else {
            printf("bad %s\n", line);
        }
        fflush(stdout);
    }
    disc_close();
    return 0;
}
