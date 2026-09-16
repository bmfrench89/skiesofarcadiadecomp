/*
 * Sound output: the AI DMA's blocks, as the console would send them to the
 * DAC, queued to the default Windows audio device through waveOut. Blocks
 * arrive as big-endian right/left 16-bit pairs at 32 kHz (or 48 kHz).
 */
#ifdef _WIN32
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma comment(lib, "winmm.lib")

#define BLOCKS 24
#define BLOCK_BYTES 4096

static HWAVEOUT g_wo;
static WAVEHDR g_hdr[BLOCKS];
static uint8_t g_buf[BLOCKS][BLOCK_BYTES];
static int g_next, g_ready = -1;
static unsigned g_rate;
static uint64_t g_pushed, g_dropped;

static int audio_open(unsigned rate)
{
    WAVEFORMATEX fmt;
    int i;
    if (getenv("SOA_NOSOUND")) return 0;
    memset(&fmt, 0, sizeof fmt);
    fmt.wFormatTag = WAVE_FORMAT_PCM;
    fmt.nChannels = 2;
    fmt.nSamplesPerSec = rate;
    fmt.wBitsPerSample = 16;
    fmt.nBlockAlign = 4;
    fmt.nAvgBytesPerSec = rate * 4;
    if (waveOutOpen(&g_wo, WAVE_MAPPER, &fmt, 0, 0, CALLBACK_NULL) != MMSYSERR_NOERROR) {
        fprintf(stderr, "[audio] waveOutOpen failed; no sound\n");
        return 0;
    }
    for (i = 0; i < BLOCKS; i++) {
        memset(&g_hdr[i], 0, sizeof g_hdr[i]);
        g_hdr[i].lpData = (LPSTR)g_buf[i];
        g_hdr[i].dwBufferLength = BLOCK_BYTES;
        g_hdr[i].dwFlags = WHDR_DONE;
    }
    g_rate = rate;
    fprintf(stderr, "[audio] output open at %u Hz\n", rate);
    return 1;
}

/* Queue one AI DMA block (big-endian R/L pairs). */
static int g_peak;
static uint64_t g_blocks_seen;

/* SOA_WAV=path: every block also goes to a WAV file (stereo 16-bit, little-endian),
 * so a headless run's sound can be listened to or compared afterwards. */
static FILE* g_wav;
static uint32_t g_wav_bytes;
static unsigned g_wav_rate;
static int g_wav_tried;

static void wav_u32(FILE* f, uint32_t v) { uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24)}; fwrite(b, 1, 4, f); }
static void wav_u16(FILE* f, uint16_t v) { uint8_t b[2] = {(uint8_t)v, (uint8_t)(v >> 8)}; fwrite(b, 1, 2, f); }

static void wav_header(FILE* f, unsigned rate, uint32_t data_bytes)
{
    fseek(f, 0, SEEK_SET);
    fwrite("RIFF", 1, 4, f); wav_u32(f, 36 + data_bytes); fwrite("WAVEfmt ", 1, 8, f);
    wav_u32(f, 16); wav_u16(f, 1); wav_u16(f, 2); wav_u32(f, rate); wav_u32(f, rate * 4); wav_u16(f, 4); wav_u16(f, 16);
    fwrite("data", 1, 4, f); wav_u32(f, data_bytes);
}

static void wav_append(const uint8_t* be_rl, unsigned bytes, unsigned rate)
{
    unsigned i;
    if (!g_wav_tried) {
        const char* path = getenv("SOA_WAV");
        g_wav_tried = 1;
        if (path) {
            g_wav = fopen(path, "wb");
            g_wav_rate = rate;
            if (g_wav) wav_header(g_wav, rate, 0);
            else fprintf(stderr, "[audio] cannot write %s\n", path);
        }
    }
    if (!g_wav) return;
    for (i = 0; i + 3 < bytes; i += 4) { /* right then left on the wire; left then right in the file */
        uint8_t s[4] = {be_rl[i + 3], be_rl[i + 2], be_rl[i + 1], be_rl[i]};
        fwrite(s, 1, 4, g_wav);
        g_wav_bytes += 4;
    }
}

void audio_push_block(const uint8_t* be_rl, unsigned bytes, unsigned rate)
{
    WAVEHDR* h;
    unsigned i, n;
    int16_t* out;
    g_blocks_seen++;
    for (i = 0; i + 1 < bytes; i += 2) { /* a meter, so silence is visible in the report */
        int v = (int16_t)(((uint16_t)be_rl[i] << 8) | be_rl[i + 1]);
        if (v < 0) v = -v;
        if (v > g_peak) g_peak = v;
    }
    wav_append(be_rl, bytes, rate);
    if (g_ready < 0) g_ready = audio_open(rate);
    if (!g_ready) return;
    if (bytes > BLOCK_BYTES) bytes = BLOCK_BYTES;
    h = &g_hdr[g_next];
    if (!(h->dwFlags & WHDR_DONE)) { g_dropped++; return; } /* the device is behind; drop */
    if (h->dwFlags & WHDR_PREPARED) waveOutUnprepareHeader(g_wo, h, sizeof *h);
    out = (int16_t*)g_buf[g_next];
    n = bytes / 4;
    for (i = 0; i < n; i++) {
        int16_t r = (int16_t)(((uint16_t)be_rl[4 * i] << 8) | be_rl[4 * i + 1]);
        int16_t l = (int16_t)(((uint16_t)be_rl[4 * i + 2] << 8) | be_rl[4 * i + 3]);
        out[2 * i] = l;
        out[2 * i + 1] = r;
    }
    h->dwBufferLength = n * 4;
    h->dwFlags = 0;
    if (waveOutPrepareHeader(g_wo, h, sizeof *h) == MMSYSERR_NOERROR && waveOutWrite(g_wo, h, sizeof *h) == MMSYSERR_NOERROR) {
        g_pushed++;
        g_next = (g_next + 1) % BLOCKS;
    } else {
        h->dwFlags = WHDR_DONE;
        g_dropped++;
    }
}

void audio_report(void)
{
    fprintf(stderr, "[audio] %llu DMA blocks, peak sample %d%s; %llu played, %llu dropped\n", (unsigned long long)g_blocks_seen, g_peak,
            g_ready > 0 ? "" : " (no output device)", (unsigned long long)g_pushed, (unsigned long long)g_dropped);
    if (g_wav) { /* finish the file: the header carries the data size */
        wav_header(g_wav, g_wav_rate, g_wav_bytes);
        fclose(g_wav);
        g_wav = NULL;
        fprintf(stderr, "[audio] wrote %u bytes of samples to the WAV file\n", g_wav_bytes);
    }
}
#else
#include <stdint.h>
void audio_push_block(const uint8_t* be_rl, unsigned bytes, unsigned rate) { (void)be_rl; (void)bytes; (void)rate; }
void audio_report(void) {}
#endif
