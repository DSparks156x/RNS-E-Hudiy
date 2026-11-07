/* audio.h -- the audio stage: the only code that produces audio sector bytes (SPEC 3.2 audio_fmt 1 = PCM s16
 * big-endian stereo, 48 kHz). Input: 48 kHz s16 stereo PCM on a pipe or file (little-endian = ALSA S16_LE by
 * default, --audio-be for big-endian). Missing input -> silence (counted).
 *
 * HOOK: the Teensy will later be a UAC2 sound card and insert audio itself. Then this stage is replaced by
 * "reserve N audio sectors and let the Teensy fill them + patch the header" (audio_stage_take() becomes a
 * no-op and sf_build() is fed audio_bytes with a NULL buffer). Nothing else in avlink touches audio bytes. */
#ifndef AVL_AUDIO_H
#define AVL_AUDIO_H
#include <stdint.h>
#include <stddef.h>

#define AUDIO_PRIME_MS 50
typedef struct {
    int fd;              /* -1: no input (silence) */
    int be;              /* input is big-endian */
    int eof;
    int nonblock;        /* pipe in live mode */
    uint8_t *buf;        /* raw input bytes not consumed yet */
    size_t have, cap;
    uint64_t frames_in, frames_silence, frames_dropped;
    int gain_q15;   /* 0 or 32768 = unity */
    int primed;     /* live: margin reached, see audio_take */
    uint64_t raw_bytes;  /* everything read from the input */
    int last_arrival;    /* set by a read, cleared by the tick clock: audio is flowing */
} audio_stage;

int audio_open(audio_stage *a, const char *path, int be, int live);   /* path NULL = silence */
int audio_poll_fd(const audio_stage *a);        /* fd to poll for POLLIN in live mode, or -1 */
void audio_read_avail(audio_stage *a);          /* live: read what the pipe has (nonblocking) */
/* Produce exactly `frames` stereo frames as s16 BE into out (frames*4 bytes). blocking: wait for the input
 * (batch); else take what is buffered and pad with silence. Returns frames that came from the input. */
int audio_take(audio_stage *a, int frames, uint8_t *out, int blocking);
void audio_close(audio_stage *a);

#endif
