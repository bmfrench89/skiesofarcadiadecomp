/*
 * Sound off Windows (portability L10): SDL3's audio stream as audio_out.c's
 * device, which keeps the meter, the arrival rate, SOA_WAV, the mute and the
 * report. Built only when SOA_SDL is defined, as window_sdl.c is. The stream
 * takes the game's rate (32 kHz, or 48) as it comes and SDL resamples to the
 * device's; how far behind the device may fall before a block is dropped is
 * audio_out.c's rule, the same 24 blocks waveOut holds.
 */
#ifdef SOA_SDL
#include <SDL3/SDL.h>
#include <stdint.h>
#include <stdio.h>

int soa_sdl_init(unsigned flags, const char** why); /* window_sdl.c */

static SDL_AudioStream* g_stream;

int audio_sdl_open(unsigned rate)
{
    SDL_AudioSpec spec;
    const char* why = "";
    if (!soa_sdl_init(SDL_INIT_AUDIO, &why)) {
        fprintf(stderr, "[audio] SDL could not start its sound: %s; no sound\n", why);
        return 0;
    }
    spec.format = SDL_AUDIO_S16LE;
    spec.channels = 2;
    spec.freq = (int)rate;
    g_stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, NULL, NULL);
    if (!g_stream) {
        fprintf(stderr, "[audio] SDL could not open a sound device: %s; no sound\n", SDL_GetError());
        return 0;
    }
    SDL_ResumeAudioStreamDevice(g_stream);
    fprintf(stderr, "[audio] output open at %u Hz, through SDL3's %s driver\n", rate, SDL_GetCurrentAudioDriver());
    return 1;
}

/* The bytes queued that the device has not taken yet. */
unsigned audio_sdl_queued(void)
{
    int n = SDL_GetAudioStreamQueued(g_stream);
    return n > 0 ? (unsigned)n : 0u;
}

/* Little-endian left/right pairs to the device; 0 when SDL refused them. */
int audio_sdl_put(const int16_t* lr, unsigned bytes)
{
    return SDL_PutAudioStreamData(g_stream, lr, (int)bytes);
}
#endif
