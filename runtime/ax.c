/*
 * The stock AX microcode, in C: what the DSP does with each command list
 * the game's audio driver mails it every 5 ms. Voices are parameter blocks
 * (AXPB, 0xC0 bytes, linked through their first word) whose samples live
 * in ARAM as DSP-ADPCM, PCM16 or PCM8; each frame every running voice is
 * decoded, rate-converted to 32 kHz, shaped by its volume envelope and
 * mixed by its mixer gains into the main and two auxiliary buses. The aux
 * buses can be handed to the CPU for effects and mixed back; the main bus
 * is written as 160 stereo samples where the AI DMA reads them.
 *
 * Layouts follow the AX headers of the SDK this game links (2002); the
 * command numbers are those Dolphin's AX HLE documents for this microcode.
 */
#define _CRT_SECURE_NO_WARNINGS
#include "cpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FRAME_SAMPLES 160 /* 5 ms at 32 kHz */
#define MS_SAMPLES 32

uint8_t* aram_memory(void);

/* ---- parameter block: word offsets (AXPB, 96 words) ----------------------- */

enum {
    PB_NEXT_HI = 0, PB_NEXT_LO, PB_THIS_HI, PB_THIS_LO,
    PB_SRC_TYPE = 4, PB_COEF_SELECT, PB_MIXER_CTRL, PB_RUNNING, PB_IS_STREAM,
    PB_MIXER = 9,        /* 18: L dL R dR AL dAL AR dAR BL dBL BR dBR S dS AS dAS BS dBS */
    PB_ITD = 27,         /* 7 */
    PB_UPDATES = 34,     /* 7: num_updates[5], data hi, data lo */
    PB_DPOP = 41,        /* 9 */
    PB_VOL_ENV = 50,     /* 2: cur_volume, delta */
    PB_UNK3 = 52,        /* 3 */
    PB_AUDIO_ADDR = 55,  /* 8: looping, format, loop hi/lo, end hi/lo, cur hi/lo */
    PB_ADPCM = 63,       /* 20: coefs[16], gain, pred_scale, yn1, yn2 */
    PB_SRC = 83,         /* 7: ratio hi/lo, cur_addr_frac, last_samples[4] */
    PB_ADPCM_LOOP = 90,  /* 3: pred_scale, yn1, yn2 */
    PB_WORDS = 96
};

enum { MX_L = 0, MX_DL, MX_R, MX_DR, MX_AL, MX_DAL, MX_AR, MX_DAR, MX_BL, MX_DBL, MX_BR, MX_DBR, MX_S, MX_DS, MX_AS, MX_DAS, MX_BS, MX_DBS };

/* mixer_control bits of this microcode */
#define MIX_L 0x0001
#define MIX_R 0x0002
#define MIX_S 0x0004
#define MIX_RAMP 0x0008
#define MIX_AL 0x0010
#define MIX_AR 0x0020
#define MIX_AS 0x0040
#define MIX_A_RAMP 0x0080
#define MIX_BL 0x0100
#define MIX_BR 0x0200
#define MIX_BS 0x0400
#define MIX_B_RAMP 0x0800

typedef struct {
    uint16_t w[PB_WORDS];
} PB;

static uint32_t rd32(CpuState* s, uint32_t a) { return mem_r32(s, a | 0x80000000u); }
static uint16_t rd16(CpuState* s, uint32_t a) { return mem_r16(s, a | 0x80000000u); }
static void wr16(CpuState* s, uint32_t a, uint16_t v) { mem_w16(s, a | 0x80000000u, v); }

static void pb_read(CpuState* s, uint32_t addr, PB* pb)
{
    int i;
    for (i = 0; i < PB_WORDS; i++) pb->w[i] = rd16(s, addr + 2u * (uint32_t)i);
}

static void pb_write(CpuState* s, uint32_t addr, const PB* pb)
{
    int i;
    for (i = 0; i < PB_WORDS; i++) wr16(s, addr + 2u * (uint32_t)i, pb->w[i]);
}

/* ---- buses ------------------------------------------------------------ */

static int32_t g_main[3][FRAME_SAMPLES];  /* L R S */
static int32_t g_auxa[3][FRAME_SAMPLES];
static int32_t g_auxb[3][FRAME_SAMPLES];
static uint64_t g_frames, g_voices, g_samples_out;
static int g_verbose = -1;

/* ---- sample fetch ------------------------------------------------------- */

typedef struct {
    PB* pb;
    uint32_t cur;        /* current address in the format's units (nibbles / samples / bytes) */
    uint32_t end, loop;
    int fmt, looping;
    int16_t yn1, yn2;
    int pred_scale;
    const int16_t* coefs;
    uint8_t* aram;
    int stopped;
} Voice;

static int16_t clamp16(int32_t v) { return (int16_t)(v < -32768 ? -32768 : (v > 32767 ? 32767 : v)); }

#define ARAM_MASK ((16u << 20) - 1)

/* One sample at the voice's current address, advancing it and following the loop. */
static int16_t fetch_sample(Voice* v)
{
    int16_t out = 0;
    if (v->stopped) return 0;
    if (v->cur >= v->end) {
        if (v->looping) {
            v->cur = v->loop;
            if (v->fmt == 0) {
                v->pred_scale = v->pb->w[PB_ADPCM_LOOP];
                v->yn1 = (int16_t)v->pb->w[PB_ADPCM_LOOP + 1];
                v->yn2 = (int16_t)v->pb->w[PB_ADPCM_LOOP + 2];
            }
        } else {
            v->stopped = 1;
            return 0;
        }
    }
    switch (v->fmt) {
    case 0x00: { /* DSP-ADPCM: nibble addresses, 16 nibbles per frame, the first two the header */
        uint32_t nib = v->cur;
        if ((nib & 15) == 0) { v->pred_scale = v->aram[(nib / 2) & ARAM_MASK]; nib += 2; }
        {
            uint8_t byte = v->aram[(nib / 2) & ARAM_MASK];
            int n = (nib & 1) ? (byte & 15) : (byte >> 4);
            int scale = 1 << (v->pred_scale & 15);
            int ci = (v->pred_scale >> 4) & 7;
            int32_t c1 = v->coefs[ci * 2], c2 = v->coefs[ci * 2 + 1];
            int32_t nibble = n >= 8 ? n - 16 : n;
            int32_t val = (scale * nibble * 2048 + c1 * v->yn1 + c2 * v->yn2 + 1024) >> 11;
            out = clamp16(val);
            v->yn2 = v->yn1;
            v->yn1 = out;
        }
        v->cur = nib + 1;
        break;
    }
    case 0x0A: { /* PCM16, sample addresses */
        uint32_t b = (v->cur * 2) & ARAM_MASK;
        out = (int16_t)(((uint16_t)v->aram[b] << 8) | v->aram[b + 1]);
        v->cur++;
        break;
    }
    case 0x19: /* PCM8, byte addresses */
        out = (int16_t)((int8_t)v->aram[v->cur & ARAM_MASK] << 8);
        v->cur++;
        break;
    default:
        v->cur++;
        break;
    }
    return out;
}

/* ---- voice processing ---------------------------------------------------- */

static void mix_add(int32_t* bus, const int32_t* in, int n, uint16_t* gain, int ramp, int16_t delta)
{
    int i;
    int32_t vol = *gain;
    for (i = 0; i < n; i++) {
        bus[i] += (in[i] * vol) >> 15;
        if (ramp) vol += delta;
    }
    if (ramp) *gain = (uint16_t)vol;
}

/* The driver's per-millisecond parameter changes: (offset, value) pairs. */
static void apply_updates(CpuState* s, PB* pb, int ms)
{
    uint32_t data = ((uint32_t)pb->w[PB_UPDATES + 5] << 16) | pb->w[PB_UPDATES + 6];
    unsigned start = 0, n = pb->w[PB_UPDATES + ms], i;
    int k;
    if (!data || !n) return;
    for (k = 0; k < ms; k++) start += pb->w[PB_UPDATES + k];
    data &= 0x7FFFFFFFu;
    for (i = start; i < start + n && i < 4096; i++) {
        uint16_t off = rd16(s, data + i * 4u), val = rd16(s, data + i * 4u + 2u);
        if (off < PB_WORDS) pb->w[off] = val;
    }
}

static void process_voice(CpuState* s, uint32_t addr, uint8_t* aram)
{
    PB pb;
    Voice v;
    int32_t samples[MS_SAMPLES];
    int ms, i;
    uint32_t ratio, frac;
    int16_t last[4];

    pb_read(s, addr, &pb);
    apply_updates(s, &pb, 0);
    if (!pb.w[PB_RUNNING]) { pb_write(s, addr, &pb); return; }
    g_voices++;
    if (g_verbose && g_voices <= 6)
        fprintf(stderr, "[ax] voice pb %08X fmt %04X loop %u addr %04X%04X..%04X%04X cur %04X%04X ratio %04X%04X ctrl %04X vol %04X/%d gains L %04X R %04X AL %04X AR %04X updates %u %u %u %u %u\n",
                addr, pb.w[PB_AUDIO_ADDR + 1], pb.w[PB_AUDIO_ADDR], pb.w[PB_AUDIO_ADDR + 2], pb.w[PB_AUDIO_ADDR + 3],
                pb.w[PB_AUDIO_ADDR + 4], pb.w[PB_AUDIO_ADDR + 5], pb.w[PB_AUDIO_ADDR + 6], pb.w[PB_AUDIO_ADDR + 7],
                pb.w[PB_SRC], pb.w[PB_SRC + 1], pb.w[PB_MIXER_CTRL], pb.w[PB_VOL_ENV], (int16_t)pb.w[PB_VOL_ENV + 1],
                pb.w[PB_MIXER + MX_L], pb.w[PB_MIXER + MX_R], pb.w[PB_MIXER + MX_AL], pb.w[PB_MIXER + MX_AR],
                pb.w[PB_UPDATES], pb.w[PB_UPDATES + 1], pb.w[PB_UPDATES + 2], pb.w[PB_UPDATES + 3], pb.w[PB_UPDATES + 4]);

    v.pb = &pb;
    v.aram = aram;
    v.stopped = 0;

    for (ms = 0; ms < 5; ms++) {
        uint16_t ctrl, vol;
        int16_t dvol;
        uint16_t* mx;
        if (ms) apply_updates(s, &pb, ms);
        if (!pb.w[PB_RUNNING]) break;

        /* (re)load the voice's position and decoder state: an update may have changed them */
        v.fmt = pb.w[PB_AUDIO_ADDR + 1];
        v.looping = pb.w[PB_AUDIO_ADDR] != 0;
        v.loop = ((uint32_t)pb.w[PB_AUDIO_ADDR + 2] << 16) | pb.w[PB_AUDIO_ADDR + 3];
        v.end = ((uint32_t)pb.w[PB_AUDIO_ADDR + 4] << 16) | pb.w[PB_AUDIO_ADDR + 5];
        v.cur = ((uint32_t)pb.w[PB_AUDIO_ADDR + 6] << 16) | pb.w[PB_AUDIO_ADDR + 7];
        v.coefs = (const int16_t*)&pb.w[PB_ADPCM];
        v.pred_scale = pb.w[PB_ADPCM + 17];
        v.yn1 = (int16_t)pb.w[PB_ADPCM + 18];
        v.yn2 = (int16_t)pb.w[PB_ADPCM + 19];
        ratio = ((uint32_t)pb.w[PB_SRC] << 16) | pb.w[PB_SRC + 1];
        frac = pb.w[PB_SRC + 2];
        for (i = 0; i < 4; i++) last[i] = (int16_t)pb.w[PB_SRC + 3 + i];
        if (ratio == 0) ratio = 0x10000;

        /* 32 output samples through the rate converter */
        for (i = 0; i < MS_SAMPLES; i++) {
            uint32_t step = frac + ratio, whole = step >> 16, k;
            frac = step & 0xFFFF;
            for (k = 0; k < whole; k++) {
                last[0] = last[1]; last[1] = last[2]; last[2] = last[3];
                last[3] = fetch_sample(&v);
            }
            samples[i] = last[2] + (((last[3] - last[2]) * (int32_t)frac) >> 16);
        }

        /* volume envelope */
        vol = pb.w[PB_VOL_ENV];
        dvol = (int16_t)pb.w[PB_VOL_ENV + 1];
        for (i = 0; i < MS_SAMPLES; i++) {
            samples[i] = (samples[i] * (int32_t)vol) >> 15;
            vol = (uint16_t)(vol + dvol);
        }
        pb.w[PB_VOL_ENV] = vol;

        /* mixer: this microcode build (0x4E8A8B21) always mixes L/R; bit 0
         * adds aux A, bit 1 aux B, bit 2 surround, bit 3 the ramps */
        {
            uint16_t raw = pb.w[PB_MIXER_CTRL];
            ctrl = MIX_L | MIX_R;
            if (raw & 1) ctrl |= MIX_AL | MIX_AR;
            if (raw & 2) ctrl |= MIX_BL | MIX_BR;
            if (raw & 4) { ctrl |= MIX_S; if (raw & 1) ctrl |= MIX_AS; if (raw & 2) ctrl |= MIX_BS; }
            if (raw & 8) ctrl |= MIX_RAMP | ((raw & 1) ? MIX_A_RAMP : 0) | ((raw & 2) ? MIX_B_RAMP : 0);
        }
        mx = &pb.w[PB_MIXER];
        {
            int o = ms * MS_SAMPLES;
            int r0 = (ctrl & MIX_RAMP) != 0, ra = (ctrl & MIX_A_RAMP) != 0, rb = (ctrl & MIX_B_RAMP) != 0;
            if (ctrl & MIX_L) mix_add(g_main[0] + o, samples, MS_SAMPLES, &mx[MX_L], r0, (int16_t)mx[MX_DL]);
            if (ctrl & MIX_R) mix_add(g_main[1] + o, samples, MS_SAMPLES, &mx[MX_R], r0, (int16_t)mx[MX_DR]);
            if (ctrl & MIX_S) mix_add(g_main[2] + o, samples, MS_SAMPLES, &mx[MX_S], r0, (int16_t)mx[MX_DS]);
            if (ctrl & MIX_AL) mix_add(g_auxa[0] + o, samples, MS_SAMPLES, &mx[MX_AL], ra, (int16_t)mx[MX_DAL]);
            if (ctrl & MIX_AR) mix_add(g_auxa[1] + o, samples, MS_SAMPLES, &mx[MX_AR], ra, (int16_t)mx[MX_DAR]);
            if (ctrl & MIX_AS) mix_add(g_auxa[2] + o, samples, MS_SAMPLES, &mx[MX_AS], ra, (int16_t)mx[MX_DAS]);
            if (ctrl & MIX_BL) mix_add(g_auxb[0] + o, samples, MS_SAMPLES, &mx[MX_BL], rb, (int16_t)mx[MX_DBL]);
            if (ctrl & MIX_BR) mix_add(g_auxb[1] + o, samples, MS_SAMPLES, &mx[MX_BR], rb, (int16_t)mx[MX_DBR]);
            if (ctrl & MIX_BS) mix_add(g_auxb[2] + o, samples, MS_SAMPLES, &mx[MX_BS], rb, (int16_t)mx[MX_DBS]);
        }

        /* state back into the block */
        pb.w[PB_AUDIO_ADDR + 6] = (uint16_t)(v.cur >> 16);
        pb.w[PB_AUDIO_ADDR + 7] = (uint16_t)v.cur;
        pb.w[PB_ADPCM + 17] = (uint16_t)v.pred_scale;
        pb.w[PB_ADPCM + 18] = (uint16_t)v.yn1;
        pb.w[PB_ADPCM + 19] = (uint16_t)v.yn2;
        pb.w[PB_SRC + 2] = (uint16_t)frac;
        for (i = 0; i < 4; i++) pb.w[PB_SRC + 3 + i] = (uint16_t)last[i];
        if (v.stopped) { pb.w[PB_RUNNING] = 0; break; }
    }
    pb_write(s, addr, &pb);
}

static void process_pb_list(CpuState* s, uint32_t addr)
{
    uint8_t* aram = aram_memory();
    int guard = 0;
    while (addr && guard++ < 256) {
        uint32_t next;
        process_voice(s, addr, aram);
        next = rd32(s, addr) & 0x7FFFFFFFu;
        if (next == addr) break;
        addr = next;
    }
}

/* ---- aux buses and output ----------------------------------------------- */

static void wr32(CpuState* s, uint32_t a, uint32_t v) { mem_w32(s, a | 0x80000000u, v); }

/* Buffers exchanged with the CPU are 32-bit samples, three channels of 160. */
static void upload_bus(CpuState* s, uint32_t addr, int32_t bus[3][FRAME_SAMPLES])
{
    int c, i;
    if (!addr) return;
    for (c = 0; c < 3; c++)
        for (i = 0; i < FRAME_SAMPLES; i++)
            wr32(s, addr + (uint32_t)(c * FRAME_SAMPLES + i) * 4u, (uint32_t)bus[c][i]);
}

static void download_into_main(CpuState* s, uint32_t addr)
{
    int c, i;
    if (!addr) return;
    for (c = 0; c < 3; c++)
        for (i = 0; i < FRAME_SAMPLES; i++)
            g_main[c][i] += (int32_t)rd32(s, addr + (uint32_t)(c * FRAME_SAMPLES + i) * 4u);
}

static void output_samples(CpuState* s, uint32_t lr_addr, uint32_t s_addr)
{
    int i;
    for (i = 0; i < FRAME_SAMPLES; i++) {
        int16_t l = clamp16(g_main[0][i]), r = clamp16(g_main[1][i]);
        wr16(s, lr_addr + (uint32_t)i * 4u, (uint16_t)r);      /* right first, as the AI wants it */
        wr16(s, lr_addr + (uint32_t)i * 4u + 2u, (uint16_t)l);
    }
    if (s_addr)
        for (i = 0; i < FRAME_SAMPLES; i++) wr16(s, s_addr + (uint32_t)i * 2u, (uint16_t)clamp16(g_main[2][i]));
    g_samples_out += FRAME_SAMPLES;
}

/* ---- the command list ------------------------------------------------------- */

static int32_t bus_peak(int32_t bus[3][FRAME_SAMPLES])
{
    int32_t peak = 0;
    int c, i;
    for (c = 0; c < 3; c++)
        for (i = 0; i < FRAME_SAMPLES; i++) { int32_t v = bus[c][i] < 0 ? -bus[c][i] : bus[c][i]; if (v > peak) peak = v; }
    return peak;
}

void ax_command_list(CpuState* s, uint32_t addr)
{
    uint32_t pb_addr = 0;
    int end = 0, guard = 0;
    uint32_t p = addr & 0x7FFFFFFFu;
    uint64_t voices_before = g_voices;
    static int traced;
    if (g_verbose < 0) g_verbose = getenv("SOA_AX_VERBOSE") ? 1 : 0;
    memset(g_main, 0, sizeof g_main);
    memset(g_auxa, 0, sizeof g_auxa);
    memset(g_auxb, 0, sizeof g_auxb);
    g_frames++;

    while (!end && guard++ < 64) {
        uint16_t cmd = rd16(s, p);
        p += 2;
        if (g_verbose && (g_frames <= 4 || (g_voices > voices_before && traced < 40))) {
            fprintf(stderr, "[ax] frame %llu cmd %u main peak %d auxa %d auxb %d\n", (unsigned long long)g_frames, cmd, bus_peak(g_main), bus_peak(g_auxa), bus_peak(g_auxb));
            if (g_voices > voices_before) traced++;
        }
        switch (cmd) {
        case 0x00: /* SETUP: studio initial values and ramps (buses start silent) */
            p += 4;
            break;
        case 0x01: { /* DL_AND_VOL_MIX: samples from memory into main with volume */
            uint32_t a = (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu;
            uint16_t vol_main = rd16(s, p + 4);
            int c, i;
            p += 10;
            for (c = 0; c < 3; c++)
                for (i = 0; i < FRAME_SAMPLES; i++)
                    g_main[c][i] += (int32_t)(((int64_t)(int32_t)rd32(s, a + (uint32_t)(c * FRAME_SAMPLES + i) * 4u) * vol_main) >> 15);
            break;
        }
        case 0x02: /* PB_ADDR */
            pb_addr = ((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2);
            p += 4;
            break;
        case 0x03: /* PROCESS_PB */
            process_pb_list(s, pb_addr & 0x7FFFFFFFu);
            break;
        case 0x04: case 0x05: { /* MIX_AUXA / MIX_AUXB: upload the bus, read back the processed one */
            uint32_t up = ((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2);
            uint32_t down = ((uint32_t)rd16(s, p + 4) << 16) | rd16(s, p + 6);
            p += 8;
            upload_bus(s, up & 0x7FFFFFFFu, cmd == 0x04 ? g_auxa : g_auxb);
            download_into_main(s, down & 0x7FFFFFFFu);
            break;
        }
        case 0x06: /* UPLOAD_LRS: main bus to memory */
            upload_bus(s, (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu, g_main);
            p += 4;
            break;
        case 0x07: { /* SET_LR: main L/R from memory */
            uint32_t a = (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu;
            int c, i;
            p += 4;
            for (c = 0; c < 2; c++)
                for (i = 0; i < FRAME_SAMPLES; i++) g_main[c][i] = (int32_t)rd32(s, a + (uint32_t)(c * FRAME_SAMPLES + i) * 4u);
            break;
        }
        case 0x08: p += 20; break;
        case 0x09: /* MIX_AUXB_NOWRITE */
            download_into_main(s, (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu);
            p += 4;
            break;
        case 0x0A: p += 4; break; /* compressor table */
        case 0x0B: case 0x0C: break;
        case 0x0D: /* MORE: continue with another list */
            p = (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu;
            break;
        case 0x0E: { /* OUTPUT: surround address, then L/R address */
            uint32_t sa = ((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2);
            uint32_t lr = ((uint32_t)rd16(s, p + 4) << 16) | rd16(s, p + 6);
            p += 8;
            output_samples(s, lr & 0x7FFFFFFFu, sa & 0x7FFFFFFFu);
            break;
        }
        case 0x0F: end = 1; break;
        case 0x10: p += 8; break;  /* MIX_AUXB_LR */
        case 0x11: { /* SET_OPPOSITE_LR: main L/R from 32-bit samples, right positive, left negated */
            uint32_t a = (((uint32_t)rd16(s, p) << 16) | rd16(s, p + 2)) & 0x7FFFFFFFu;
            int i;
            p += 4;
            for (i = 0; i < FRAME_SAMPLES; i++) {
                int32_t x = (int32_t)rd32(s, a + (uint32_t)i * 4u);
                g_main[0][i] = -x;
                g_main[1][i] = x;
                g_main[2][i] = 0;
            }
            break;
        }
        case 0x12: p += 12; break;
        case 0x13: p += 16; break; /* SEND_AUX_AND_MIX */
        default:
            if (g_verbose) fprintf(stderr, "[ax] unknown command %u\n", cmd);
            end = 1;
            break;
        }
    }
}

void ax_report(void)
{
    fprintf(stderr, "[ax] %llu frames mixed, %llu voice-frames, %llu samples output\n",
            (unsigned long long)g_frames, (unsigned long long)g_voices, (unsigned long long)g_samples_out);
}
