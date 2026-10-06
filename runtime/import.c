/*
 * The import's portable half (import.h; specs/android.md L12d). The body is
 * for Linux's kernel -- Android's, and CI's Linux legs, which test it
 * (tools/tests/test_import.py) -- and elsewhere, Windows above all, the calls
 * that touch files refuse. It is chosen by __linux__, not by _WIN32: it needs
 * Linux itself (fallocate, statfs, /proc/self/fd, /mnt/appfuse), and runtime/
 * names _WIN32 only where tools/tests/test_portability.py's list allows.
 *
 * The copy is where a player loses something if a rule is missing, and each
 * rule here stands for one such loss: a provider that dies mid-stream looks
 * like a clean end of file once its descriptor is detached, so the count is
 * held to the size it gave; a 1.4 GB copy must not fill the device the memory
 * card is written to, so it needs its size and a margin free and takes the
 * space before it starts; a wrong pick must not cost a whole copy, so its
 * first bytes are checked before the rest is read; Back never reaches an app
 * that targets Android 16, so the copy can be cancelled, even while a stream
 * is silent; and whatever stops a copy, its .tmp goes and the file it would
 * have replaced stays.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE /* fallocate and FALLOC_FL_KEEP_SIZE, on glibc */
#endif
#define _CRT_SECURE_NO_WARNINGS
#include "import.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef __linux__
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/vfs.h>
#include <time.h>
#include <unistd.h>
#endif

/* ---- the bytes alone, the same everywhere ------------------------------- */

int import_sniff(const uint8_t* b, size_t n)
{
    if (n >= 4 && !memcmp(b, "\177ELF", 4)) return IMPORT_ELF;
    if (n >= 8 && !memcmp(b, "SOADISC1", 8)) return IMPORT_STORE;
    if (n >= 4 && (!memcmp(b, "RVZ\001", 4) || !memcmp(b, "WIA\001", 4))) return IMPORT_RVZ;
    if (n >= 0x20 && b[0x1C] == 0xC2 && b[0x1D] == 0x33 && b[0x1E] == 0x9F && b[0x1F] == 0x3D) return IMPORT_ISO;
    if (n >= 2 && b[0] == 'M' && b[1] == 'Z') return IMPORT_PE;
    return IMPORT_UNKNOWN;
}

const char* import_copy_name(int kind)
{
    if (kind == IMPORT_STORE) return "disc.soadisc";
    if (kind == IMPORT_ELF) return "libsoa_game.so";
    return "disc.iso";
}

/* A byte a name may go on with, so that /proc/self/fd/7 is not found inside
 * /proc/self/fd/71, nor .../disc.iso inside .../disc.iso.tmp. A full stop
 * goes on with a name only when one of these follows it, since a sentence
 * may end on a path; UTF-8's bytes are a name's too. */
static int name_byte(unsigned char c)
{
    return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == '-' ||
           c == '/' || c >= 0x80;
}
static int goes_on(const char* p)
{
    return name_byte((unsigned char)p[0]) || (p[0] == '.' && name_byte((unsigned char)p[1]));
}

/* n, less a UTF-8 character a cut left without its end: a message goes to
 * Java, whose NewStringUTF aborts a debuggable app on half a character. */
static size_t whole(const char* s, size_t n)
{
    size_t i = n;
    unsigned char lead;
    while (i > 0 && n - i < 3 && ((unsigned char)s[i - 1] & 0xC0) == 0x80) i--;
    if (i == 0) return n;
    lead = (unsigned char)s[i - 1];
    if (lead >= 0xC0 && n - (i - 1) < (size_t)(lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : 2)) return i - 1;
    return n;
}

void import_name_in(char* why, size_t cap, const char* internal, const char* display)
{
    size_t k, d, o = 0;
    const char* p;
    char* out;
    int cut = 0;
    if (!why || !cap || !internal || !*internal || !display) return;
    k = strlen(internal);
    d = strlen(display);
    out = (char*)malloc(cap);
    if (!out) return;
    for (p = why; *p && !cut;) {
        const char* s = p;
        size_t n = 1;
        if (!strncmp(p, internal, k) && (p == why || !(name_byte((unsigned char)p[-1]) || p[-1] == '.')) &&
            !goes_on(p + k)) {
            s = display;
            n = d;
            p += k;
        } else {
            p++;
        }
        if (n > cap - 1 - o) {
            n = cap - 1 - o;
            cut = 1;
        }
        memcpy(out + o, s, n);
        o += n;
    }
    if (cut) o = whole(out, o);
    out[o] = '\0';
    memcpy(why, out, o + 1);
    free(out);
}

#ifdef __linux__
_Static_assert(sizeof(off_t) == 8, "a 1.4 GB disc needs 64-bit file offsets");

#define STEP ((uint64_t)1 << 20) /* the most read at once; how often progress, and with no size the room, is asked */
#define TICK_MS 250              /* progress is asked at least this often, however slowly bytes come, or none */
/* Where Android serves a provider's descriptors on demand
 * (StorageManager.openProxyFileDescriptor, through AppFuse): a cloud's file,
 * fetched as it is read. */
#define PROXY_DIR "/mnt/appfuse"

static int refuse(char* why, size_t cap, const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, cap, fmt, ap);
    va_end(ap);
    return IMPORT_REFUSED;
}

/* A size as a player reads one: whole MB, or GB to a tenth; rounded up for
 * what is needed and down for what there is, so the two never seem to meet
 * when they do not. */
static const char* size_words(uint64_t n, int up, char* buf, size_t cap)
{
    const uint64_t mb = (uint64_t)1 << 20, gb = (uint64_t)1 << 30;
    if (n < gb) {
        snprintf(buf, cap, "%llu MB", (unsigned long long)((n + (up ? mb - 1 : 0)) / mb));
    } else {
        uint64_t tenths = (n * 10 + (up ? gb - 1 : 0)) / gb;
        snprintf(buf, cap, "%llu.%llu GB", (unsigned long long)(tenths / 10), (unsigned long long)(tenths % 10));
    }
    return buf;
}

int import_classify(int fd, int64_t* size)
{
    struct stat st;
    if (size) *size = -1;
    if (fstat(fd, &st) != 0) return IMPORT_OTHER;
    if (S_ISREG(st.st_mode) && lseek(fd, 0, SEEK_CUR) >= 0) {
        if (size) *size = (int64_t)st.st_size;
        return IMPORT_FILE;
    }
    return S_ISREG(st.st_mode) || S_ISFIFO(st.st_mode) || S_ISSOCK(st.st_mode) ? IMPORT_STREAM : IMPORT_OTHER;
}

int import_in_place(const char* authority, int fd, int kept, const char** reason)
{
    static const char* const local[] = {
        "com.android.externalstorage.documents",
        "com.android.providers.downloads.documents",
        "com.android.providers.media.documents",
    };
    char self[32], link[1024];
    size_t i, k = strlen(PROXY_DIR);
    ssize_t n;
    int ours = 0;
    const char* why = NULL;
    for (i = 0; authority && i < sizeof local / sizeof *local; i++) ours |= !strcmp(authority, local[i]);
    snprintf(self, sizeof self, "/proc/self/fd/%d", fd);
    n = readlink(self, link, sizeof link - 1);
    link[n > 0 ? n : 0] = '\0';
    if (import_classify(fd, NULL) != IMPORT_FILE) why = "a stream (a pipe or a socket)";
    else if (!ours) why = "not this phone's storage";
    else if (!strncmp(link, PROXY_DIR, k) && (link[k] == '/' || link[k] == '\0')) why = "a proxy (/mnt/appfuse)";
    else if (!kept) why = "the permission could not be kept";
    if (reason) *reason = why;
    return why == NULL;
}

int64_t import_free(const char* dir)
{
    struct statvfs st;
    if (statvfs(dir, &st) != 0) return -1;
    return (int64_t)((uint64_t)st.f_bavail * (uint64_t)st.f_frsize);
}

/* The size a copy is held to: the one given, but 0 is taken for none. Some
 * providers say 0 for a size they do not know, and a stream held to it would
 * be refused at its first byte however often it was picked again; nothing
 * worth copying is empty, and an empty file is copied empty either way. */
static int64_t held_to(const ImportCopy* c)
{
    return c->expect == 0 ? -1 : c->expect;
}

/* When a copy asks its progress callback whether to go on. */
typedef struct {
    const ImportCopy* c;
    int64_t expect; /* held_to's, which progress is told */
    uint64_t next;  /* the count at which to ask next */
    uint64_t when;  /* the time, in ms, at which to ask next however far it got */
} Pace;

static uint64_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

/* Nonzero when the copy is to stop: progress is asked, at `done` bytes, when
 * a further MiB is in since it was last asked, a quarter second has passed,
 * or `now`. */
static int stop(Pace* p, uint64_t done, int now)
{
    uint64_t t = now_ms();
    if (!p->c->progress) return 0;
    if (!now && done < p->next && t < p->when) return 0;
    p->next = (done / STEP + 1) * STEP;
    p->when = t + TICK_MS;
    return p->c->progress(done, p->expect, p->c->user) != 0;
}

/* Up to n bytes of the descriptor into b: a file's at offset `done`, by
 * pread, so a check that read it through a dup cannot have moved where this
 * starts; a stream's next, waiting a quarter second at a time while it is
 * silent and asking progress each time. How many; 0 at the end; -1 with
 * errno; -2 when cancelled while waiting. */
static ssize_t take(Pace* p, int file, uint8_t* b, size_t n, uint64_t done)
{
    for (;;) {
        ssize_t r;
        if (!file) {
            struct pollfd pf;
            int k;
            pf.fd = p->c->fd;
            pf.events = POLLIN;
            pf.revents = 0;
            k = poll(&pf, 1, TICK_MS);
            if (k < 0 && errno == EINTR) continue;
            if (k == 0) {
                if (stop(p, done, 1)) return -2;
                continue;
            }
            /* ready, or an error the read below names */
        }
        r = file ? pread(p->c->fd, b, n, (off_t)done) : read(p->c->fd, b, n);
        if (r < 0 && errno == EINTR) continue;
        return r;
    }
}

/* All of b to fd, through short writes; 0 with errno when it cannot. */
static int put(int fd, const uint8_t* b, size_t n)
{
    while (n) {
        ssize_t w = write(fd, b, n);
        if (w < 0 && errno == EINTR) continue;
        if (w <= 0) {
            if (w == 0) errno = EIO;
            return 0;
        }
        b += w;
        n -= (size_t)w;
    }
    return 1;
}

/* path made anew to write, with whatever had that name removed first: a
 * killed copy's .tmp may already be 0444. -1 with errno when it cannot. */
static int create(const char* path)
{
    if (unlink(path) != 0 && errno != ENOENT) return -1;
    return open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
}

/* The folder holding path synced, so a rename in it survives a power cut.
 * Where the filesystem cannot, the rename stands all the same. */
static void sync_folder(const char* path)
{
    char dir[1100];
    const char* slash = strrchr(path, '/');
    int fd;
    if (!slash) snprintf(dir, sizeof dir, ".");
    else if (slash == path) snprintf(dir, sizeof dir, "/");
    else if (snprintf(dir, sizeof dir, "%.*s", (int)(slash - path), path) >= (int)sizeof dir) return;
    fd = open(dir, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (fd < 0) return;
    fsync(fd);
    close(fd);
}

int import_head(const ImportCopy* c, uint8_t* b, size_t n, size_t* got, char* why, size_t cap)
{
    Pace pace;
    int kind = import_classify(c->fd, NULL);
    size_t have = 0;
    *got = 0;
    if (kind == IMPORT_OTHER) return refuse(why, cap, "/proc/self/fd/%d is neither a file nor a stream", c->fd);
    pace.c = c;
    pace.expect = held_to(c);
    pace.next = pace.when = UINT64_MAX; /* asked only while a stream is silent */
    while (have < n) {
        ssize_t r = take(&pace, kind == IMPORT_FILE, b + have, n - have, have);
        if (r == -2) {
            *got = have;
            snprintf(why, cap, "cancelled while waiting for /proc/self/fd/%d", c->fd);
            return IMPORT_CANCELLED;
        }
        if (r < 0) return refuse(why, cap, "cannot read /proc/self/fd/%d: %s", c->fd, strerror(errno));
        if (r == 0) break;
        have += (size_t)r;
    }
    *got = have;
    return IMPORT_OK;
}

int import_copy(const ImportCopy* c, uint64_t* copied, char* why, size_t cap)
{
    char tmp[1100], src[32], a[32], b[32], d[32], said[1024];
    int kind = import_classify(c->fd, NULL), out = -1, rc = IMPORT_REFUSED, made = 0, peeked = !c->peek, e;
    int64_t expect = held_to(c), room;
    uint64_t done = 0, room_at = 0;
    const uint8_t* bytes = c->head;
    size_t nbytes = c->head ? c->nhead : 0;
    uint8_t* buf = NULL;
    Pace pace;
    if (copied) *copied = 0;
    snprintf(src, sizeof src, "/proc/self/fd/%d", c->fd);
    if (snprintf(tmp, sizeof tmp, "%s/%s.tmp", c->dir, c->name) >= (int)sizeof tmp)
        return refuse(why, cap, "%s/%s.tmp is too long a path", c->dir, c->name);
    if (kind == IMPORT_OTHER) return refuse(why, cap, "%s is neither a file nor a stream", src);
    if (expect >= 0 && (uint64_t)expect > c->limit)
        return refuse(why, cap, "%s is %s, and the file asked for is never more than %s: pick the right one", src,
                      size_words((uint64_t)expect, 0, a, sizeof a), size_words(c->limit, 0, b, sizeof b));
    room = import_free(c->dir);
    if (room < 0) return refuse(why, cap, "cannot tell how much room %s has: %s", c->dir, strerror(errno));
    if (expect >= 0 && (uint64_t)room < (uint64_t)expect + IMPORT_MARGIN)
        return refuse(why, cap,
                      "copying %s needs %s, and %s more must stay free, but %s is free: make room on this device and "
                      "pick it again",
                      src, size_words((uint64_t)expect, 1, a, sizeof a), size_words(IMPORT_MARGIN, 1, b, sizeof b),
                      size_words((uint64_t)room, 0, d, sizeof d));
    buf = (uint8_t*)malloc(STEP);
    if (!buf) return refuse(why, cap, "no memory for the copy");
    out = create(tmp);
    if (out < 0) {
        rc = refuse(why, cap, "cannot create %s: %s", tmp, strerror(errno));
        goto fail;
    }
    made = 1;
#ifdef FALLOC_FL_KEEP_SIZE
    /* All of it taken now, so a device too full refuses here rather than at
     * 90%; the file keeps its length, so the peek reads only what came. A
     * filesystem without fallocate is copied to all the same. */
    if (expect > 0 && fallocate(out, FALLOC_FL_KEEP_SIZE, 0, (off_t)expect) != 0 && errno != EOPNOTSUPP &&
        errno != ENOSYS && errno != EINVAL) {
        rc = refuse(why, cap, "cannot make room for %s: %s", tmp, strerror(errno));
        goto fail;
    }
#endif
    pace.c = c;
    pace.expect = expect;
    pace.next = 0;
    pace.when = 0;
    if (stop(&pace, done, 1)) goto cancelled;
    for (;;) {
        if (!nbytes) { /* the head is written first, as if just read */
            size_t want = STEP;
            ssize_t r;
            if (!peeked && c->peek_at > done && c->peek_at - done < want) want = (size_t)(c->peek_at - done);
            /* with no size, never past the next look at the free space: each
             * look finds room for one MiB above the margin, and no more than
             * that MiB is written before the next */
            if (expect < 0 && room_at > done && room_at - done < want) want = (size_t)(room_at - done);
            r = take(&pace, kind == IMPORT_FILE, buf, want, done);
            if (r == -2) goto cancelled;
            if (r < 0) {
                rc = refuse(why, cap, "cannot read %s: %s", src, strerror(errno));
                goto fail;
            }
            if (r == 0) break;
            bytes = buf;
            nbytes = (size_t)r;
        }
        if (done + nbytes > c->limit) {
            rc = refuse(why, cap,
                        "%s sent more than %s, and the file asked for is never more than that: pick the right one", src,
                        size_words(c->limit, 0, a, sizeof a));
            goto fail;
        }
        if (expect >= 0 && done + nbytes > (uint64_t)expect) {
            rc = refuse(why, cap, "%s sent more than the %llu bytes it was said to hold: pick it again", src,
                        (unsigned long long)expect);
            goto fail;
        }
        if (expect < 0 && done >= room_at) { /* no size to take room for, so before each MiB */
            room = import_free(c->dir);
            if (room >= 0 && (uint64_t)room < IMPORT_MARGIN + STEP) {
                rc = refuse(why, cap,
                            "this device has %s free and %s of it must stay free, so the copy of %s stopped at %llu "
                            "bytes: make room and pick it again",
                            size_words((uint64_t)room, 0, a, sizeof a), size_words(IMPORT_MARGIN, 1, b, sizeof b), src,
                            (unsigned long long)done);
                goto fail;
            }
            room_at = done + STEP;
        }
        if (!put(out, bytes, nbytes)) {
            rc = refuse(why, cap, "cannot write %s: %s", tmp, strerror(errno));
            goto fail;
        }
        done += nbytes;
        nbytes = 0;
        if (!peeked && done >= c->peek_at) {
            peeked = 1;
            said[0] = '\0';
            if (c->peek(tmp, done, c->user, said, sizeof said)) goto peek_refused;
        }
        if (stop(&pace, done, 0)) goto cancelled;
    }
    /* The size first: a stream cut short must say so, not what its first
     * bytes lacked. */
    if (expect >= 0 && done < (uint64_t)expect) {
        rc = refuse(why, cap, "the copy stopped at %llu of %llu bytes: %s ended early; pick it again",
                    (unsigned long long)done, (unsigned long long)expect, src);
        goto fail;
    }
    if (!peeked) {
        said[0] = '\0';
        if (c->peek(tmp, done, c->user, said, sizeof said)) goto peek_refused;
    }
    if (fsync(out) != 0) {
        rc = refuse(why, cap, "cannot write %s: %s", tmp, strerror(errno));
        goto fail;
    }
    if (fchmod(out, 0444) != 0) {
        rc = refuse(why, cap, "cannot make %s read-only: %s", tmp, strerror(errno));
        goto fail;
    }
    e = close(out);
    out = -1;
    if (e != 0) {
        rc = refuse(why, cap, "cannot write %s: %s", tmp, strerror(errno));
        goto fail;
    }
    free(buf);
    if (copied) *copied = done;
    return IMPORT_OK;
peek_refused:
    if (!said[0]) snprintf(said, sizeof said, "its first bytes are not what was asked for");
    if (expect >= 0)
        rc = refuse(why, cap, "the copy was stopped after %llu of %llu bytes: %s", (unsigned long long)done,
                    (unsigned long long)expect, said);
    else
        rc = refuse(why, cap, "the copy was stopped after %llu bytes: %s", (unsigned long long)done, said);
    goto fail;
cancelled:
    if (expect >= 0)
        snprintf(why, cap, "the copy was cancelled at %llu of %llu bytes", (unsigned long long)done,
                 (unsigned long long)expect);
    else
        snprintf(why, cap, "the copy was cancelled at %llu bytes", (unsigned long long)done);
    rc = IMPORT_CANCELLED;
fail:
    if (out >= 0) close(out);
    if (made) unlink(tmp);
    free(buf);
    return rc;
}

int import_place(const char* tmp, const char* final, int keep_old, char* why, size_t cap)
{
    char old[1100];
    struct stat st;
    int moved = 0, e;
    if (snprintf(old, sizeof old, "%s.old", final) >= (int)sizeof old)
        return refuse(why, cap, "%s.old is too long a path", final);
    /* Asked first, so a missing tmp costs nothing, not even an older .old. */
    if (lstat(tmp, &st) != 0)
        return refuse(why, cap, "cannot put %s in place of %s: %s", tmp, final, strerror(errno));
    if (keep_old) {
        if (rename(final, old) == 0) moved = 1;
        else if (errno != ENOENT) return refuse(why, cap, "cannot keep %s as %s: %s", final, old, strerror(errno));
    }
    if (rename(tmp, final) != 0) {
        e = errno;
        if (moved) rename(old, final); /* the old one back where it was */
        return refuse(why, cap, "cannot put %s in place of %s: %s", tmp, final, strerror(e));
    }
    sync_folder(final);
    return 0;
}

int import_sweep(const char* dir)
{
    DIR* d = opendir(dir);
    struct dirent* e;
    int n = 0;
    if (!d) return errno == ENOENT ? 0 : -1;
    while ((e = readdir(d)) != NULL) {
        size_t k = strlen(e->d_name);
        struct stat st;
        if (k <= 4 || strcmp(e->d_name + k - 4, ".tmp") != 0) continue;
        if (fstatat(dirfd(d), e->d_name, &st, AT_SYMLINK_NOFOLLOW) != 0 || !S_ISREG(st.st_mode)) continue;
        if (unlinkat(dirfd(d), e->d_name, 0) == 0) n++;
    }
    closedir(d);
    return n;
}

int import_write_text(const char* path, const char* text, char* why, size_t cap)
{
    char tmp[1100];
    int fd, e;
    if (snprintf(tmp, sizeof tmp, "%s.tmp", path) >= (int)sizeof tmp)
        return refuse(why, cap, "%s.tmp is too long a path", path);
    fd = create(tmp);
    if (fd < 0) return refuse(why, cap, "cannot create %s: %s", tmp, strerror(errno));
    if (!put(fd, (const uint8_t*)text, strlen(text)) || fsync(fd) != 0) {
        e = errno;
        close(fd);
        unlink(tmp);
        return refuse(why, cap, "cannot write %s: %s", tmp, strerror(e));
    }
    if (close(fd) != 0) {
        e = errno;
        unlink(tmp);
        return refuse(why, cap, "cannot write %s: %s", tmp, strerror(e));
    }
    if (import_place(tmp, path, 0, why, cap) != 0) {
        unlink(tmp);
        return IMPORT_REFUSED;
    }
    return 0;
}

void import_probe(int fd, char* out, size_t cap)
{
    char self[32], link[1024], opened[128];
    struct statfs fs;
    ssize_t n;
    int g;
    snprintf(self, sizeof self, "/proc/self/fd/%d", fd);
    n = readlink(self, link, sizeof link - 1);
    if (n < 0) snprintf(link, sizeof link, "%s (%s)", self, strerror(errno));
    else link[n] = '\0';
    /* Not blocking: opening a named pipe's path to read would wait for a
     * writer (an anonymous pipe's never does). */
    g = open(self, O_RDONLY | O_NONBLOCK | O_NOCTTY | O_CLOEXEC);
    if (g >= 0) {
        close(g);
        snprintf(opened, sizeof opened, "ok");
    } else {
        snprintf(opened, sizeof opened, "%s", strerror(errno));
    }
    if (fstatfs(fd, &fs) == 0)
        snprintf(out, cap, "%s, f_type 0x%llx, open by name: %s", link, (unsigned long long)fs.f_type, opened);
    else
        snprintf(out, cap, "%s, f_type unknown (%s), open by name: %s", link, strerror(errno), opened);
}

#else
/* Off Linux -- Windows, where the PC opens a disc or a library by its path,
 * as it always has -- no picker hands over a descriptor, and nothing here is
 * reached. */
static const char g_none[] = "importing a picked file is for Android, whose kernel is Linux";

int import_classify(int fd, int64_t* size)
{
    (void)fd;
    if (size) *size = -1;
    return IMPORT_OTHER;
}
int import_in_place(const char* authority, int fd, int kept, const char** reason)
{
    (void)authority;
    (void)fd;
    (void)kept;
    if (reason) *reason = g_none;
    return 0;
}
int64_t import_free(const char* dir)
{
    (void)dir;
    return -1;
}
int import_head(const ImportCopy* c, uint8_t* b, size_t n, size_t* got, char* why, size_t cap)
{
    (void)c;
    (void)b;
    (void)n;
    *got = 0;
    snprintf(why, cap, "%s", g_none);
    return IMPORT_REFUSED;
}
int import_copy(const ImportCopy* c, uint64_t* copied, char* why, size_t cap)
{
    (void)c;
    if (copied) *copied = 0;
    snprintf(why, cap, "%s", g_none);
    return IMPORT_REFUSED;
}
int import_place(const char* tmp, const char* final, int keep_old, char* why, size_t cap)
{
    (void)tmp;
    (void)final;
    (void)keep_old;
    snprintf(why, cap, "%s", g_none);
    return IMPORT_REFUSED;
}
int import_sweep(const char* dir)
{
    (void)dir;
    return -1;
}
int import_write_text(const char* path, const char* text, char* why, size_t cap)
{
    (void)path;
    (void)text;
    snprintf(why, cap, "%s", g_none);
    return IMPORT_REFUSED;
}
void import_probe(int fd, char* out, size_t cap)
{
    (void)fd;
    snprintf(out, cap, "%s", g_none);
}
#endif
