/* audio.c -- see audio.h */
#include "audio.h"
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int audio_open(audio_stage *a, const char *path, int be, int live)
{
    memset(a, 0, sizeof *a);
    a->fd = -1;
    a->be = be;
    a->cap = 65536;
    a->buf = malloc(a->cap);
    if (!a->buf) return -1;
    if (!path) return 0;
    a->fd = strcmp(path, "-") ? open(path, O_RDONLY) : 0;
    if (a->fd < 0) return -1;
    struct stat st;
    if (live && fstat(a->fd, &st) == 0 && !S_ISREG(st.st_mode)) {
        fcntl(a->fd, F_SETFL, fcntl(a->fd, F_GETFL) | O_NONBLOCK);
        a->nonblock = 1;
    }
    return 0;
}

int audio_poll_fd(const audio_stage *a) { return (a->fd >= 0 && a->nonblock && !a->eof) ? a->fd : -1; }

static int read_some(audio_stage *a, size_t want)
{
    if (a->fd < 0 || a->eof) return 0;
    if (a->have + want > a->cap) want = a->cap - a->have;
    if (!want) return 0;
    ssize_t r = read(a->fd, a->buf + a->have, want);
    if (r > 0) { a->have += (size_t)r; a->raw_bytes += (uint64_t)r; a->last_arrival = 1; return (int)r; }
    if (r == 0 || (errno != EAGAIN && errno != EINTR)) a->eof = 1;
    return 0;
}

void audio_read_avail(audio_stage *a)
{
    while (a->nonblock) {
        if (a->have == a->cap) {                 /* no superframes going out (reader away, or USB behind): keep the newest half. Leaving the FIFO unread */
            size_t drop = (a->cap / 2) & ~(size_t)3;   /* here would make poll() return at once, forever: 75% of a core, measured */
            memmove(a->buf, a->buf + drop, a->have - drop);
            a->have -= drop;
            a->frames_dropped += drop / 4;
        }
        if (read_some(a, a->cap - a->have) <= 0) break;
    }
}

int audio_take(audio_stage *a, int frames, uint8_t *out, int blocking)
{
    size_t need = (size_t)frames * 4;
    if (a->fd >= 0) {
        if (blocking || !a->nonblock) while (a->have < need && !a->eof) read_some(a, need - a->have);
        else {
            audio_read_avail(a);
            /* PipeWire hands audio over in bursts (256-1440 frames), the tick takes a fixed 800. With no margin the tick found too little, padded the rest
             * with silence, and later dropped the backlog: ~20 audible gaps per 30 s, in multiples of 16 frames (bench 2026-11-05, 1 kHz through the chain).
             * So: hold a margin (PRIME). Only a real shortage re-primes. Over HIGH the excess goes, back to the margin: ticks are skipped while the
             * reader is away, and the delay must not grow. */
            size_t prime = 48 * AUDIO_PRIME_MS * 4, high = prime + 48 * 60 * 4;
            if (!a->primed) {
                if (a->have >= need + prime) a->primed = 1;
                else {
                    memset(out, 0, need);
                    a->frames_silence += need / 4;
                    return 0;
                }
            }
            if (a->have > need + high) {
                size_t drop = (a->have - need - prime) & ~(size_t)3;
                memmove(a->buf, a->buf + drop, a->have - drop);
                a->have -= drop;
                a->frames_dropped += drop / 4;
            }
            if (a->have < need) a->primed = 0;
        }
    }
    size_t got = a->have < need ? (a->have & ~(size_t)3) : need;
    if (a->be) memcpy(out, a->buf, got);
    else for (size_t i = 0; i < got; i += 2) { out[i] = a->buf[i + 1]; out[i + 1] = a->buf[i]; }
    if (a->gain_q15 && a->gain_q15 != 32768)                 /* out is big-endian s16 here */
        for (size_t i = 0; i + 1 < got; i += 2) {
            int v = (int16_t)(((uint16_t)out[i] << 8) | out[i + 1]);
            v = (v * a->gain_q15) >> 15;
            out[i] = (uint8_t)((uint16_t)v >> 8); out[i + 1] = (uint8_t)v;
        }
    memset(out + got, 0, need - got);
    memmove(a->buf, a->buf + got, a->have - got);
    a->have -= got;
    a->frames_in += got / 4;
    a->frames_silence += (need - got) / 4;
    return (int)(got / 4);
}

void audio_close(audio_stage *a)
{
    if (a->fd > 0) close(a->fd);
    free(a->buf);
    a->buf = NULL;
}
