/* avlink -- Pi 5 side of the RNS-E A/V-over-SD link (link/SPEC.md sections 3 and 5).
 *
 *   rnv2enc -i - --fmt bgr0 -o - | avlink --video - [--audio pcm.fifo] --dev /dev/ttyACM0
 *
 * Pipeline (each stage is its own function so a stage can move, e.g. audio into the Teensy later):
 *   video source (.rnv: 4-byte BE length + RNV2 frame)  -> fragmenter (frames > maxvid sectors -> TLV 0x11)
 *   audio stage (48 kHz s16 PCM -> s16 BE, 800 frames per tick at 60 Hz; audio.c)
 *   superframe builder (sf.c: header + down-channel TLVs + audio + video sectors, CRC-32s)
 *   wire images (wire.c: 528 B per sector, per-line CRC16)  -> TLNK SF_BEGIN / WIRE (32-sector chunks) / SF_END
 *   USB writer with STATUS credits (link.c)
 * Modes: live (default, one superframe per tick at --fps, REPEAT when no new video) or batch (--k N: exactly N
 * superframes as fast as credits allow, header values identical to rnse_proto/sdgen.py for the same input). */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "audio.h"
#include "crc.h"
#include "link.h"
#include "sf.h"
#include "wire.h"

#define AV_DELAY 2400            /* video_pts - audio_pts (D = 50 ms), SPEC 3.6 */

/* Live latency limits. Video is delta-coded and the tick takes one fragment, so a backlog above the Teensy never drains while the source runs at the tick rate.
 * Three things bound it. Slow reader: the encoder blocks early (RD_WINDOW, VSRC_MAX_FRAMES, small pipe) and wlcap's newest-wins buffer drops before encoding.
 * Reader gone (RD_STALL_US): every frame is discarded on arrival. Backlog left standing (BACKLOG_*): discarded in one go.
 * After a discard no delta goes out until a key arrives (the decoder holds its picture), and a key is requested. Audio shares the superframes, so it stays with the picture. */
#define RD_STALL_US      400000u   /* no new superframe served for this long: no reader. Longer than a stuck read + retry (122 ms measured) */
#define RD_POLLING_US    100000u   /* the reader touched the window this recently (holds, NOTREADY...): it needs the next superframe now */
#define RD_WINDOW        8         /* superframes the sender may be ahead of the reader: 133 ms, covers a stuck read without using the slots */
#define AWAY_PERIOD_US   200000u   /* reader gone: one audio-only superframe this often, so a returning reader finds something recent */
#define BACKLOG_TICKS    7         /* frames waiting above the USB queue: 117 ms */
#define BACKLOG_HOLD_US  300000u   /* ... without a break for this long. Must outlast the frames that queue behind a multi-superframe key */
#define DISCARD_GAP_US   1000000u  /* at most this often, under sustained overload a key costs more than the wait */
#define VSRC_PIPE_BYTES  16384     /* encoder pipe, rounded up to the page size */
#define VSRC_MAX_FRAMES  2
#define STALE_LIVE_MS    400       /* unread superframe older than this is useless live, the reader is told to jump. Longer than RD_WINDOW at 30 superframes/s */
#define STALE_BATCH_MS   1500      /* batch files, and a queued RNS-E bootstrap image: wait for a slow reader instead of evicting */
#define IMG_HOLD_US      3000000u
/* Reader overload, car log 2026-11-07: under heavy decode the reader tops out near 4.3 MB/s, so a busy screen at the full cap holds it back for as long as the screen stays busy.
 * Each late tick leaves 16.7 ms of audio on the Pi while the unit's FIFO runs down by the same amount, and the tick clock alone drains only 0.72%.
 * Two answers: the encoder is told to send less as soon as the reader lags, and audio left behind goes out in early ticks once the reader has room. */
#define BACKOFF_LAG      4         /* superframes built and not yet read: 67 ms */
#define BACKOFF_CALM_LAG 2         /* at or under this the reader is keeping up */
#define BACKOFF_STEP_US  100000u   /* at most one step down this often: the encoder's next frames need time to arrive */
#define BACKOFF_FACTOR   0.85
#define BACKOFF_FLOOR    0.55      /* of the configured cap */
#define BACKOFF_CALM_US  1000000u  /* calm for this long before the cap rises */
#define BACKOFF_UP_US    500000u   /* one step up this often */
#define BACKOFF_UP       0.03      /* of the configured cap */
#define CATCHUP_MAX_LAG  3         /* an early tick only while the reader has room */
#define CATCHUP_OVER     3648      /* frames over the prime level before an early tick: over the steady level (400) + a PipeWire burst (2048) + a margin of two ticks, so a burst alone never triggers one */

/* ------------------------------------------------------------------ options */
static struct {
    const char *dev, *video, *audio, *yuvcrc, *dump_sf, *dump_wire, *keyctl;
    double gain_db;
    int audio_be, no_audio, maxvid, k, eos, wire, chunk, console, stats_s, nocredits, maxq, quiet;
    double fps, linkcap;
    uint32_t seq0;
} O = {.maxvid = 248, .wire = 4, .chunk = 32, .fps = 60.0, .maxq = 3};

static uint64_t now_us(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000u + (uint64_t)t.tv_nsec / 1000u;
}

static volatile sig_atomic_t g_stop;
static void on_sig(int s) { (void)s; g_stop = 1; }

/* ------------------------------------------------------------------ video source */
typedef struct {
    int fd, eof, nonblock;
    uint8_t *buf; size_t have, cap;
    uint32_t frames;
} vsrc;

static int vsrc_open(vsrc *v, const char *path, int live)
{
    memset(v, 0, sizeof *v);
    v->fd = -1;
    if (!path) { v->eof = 1; return 0; }
    v->fd = strcmp(path, "-") ? open(path, O_RDONLY) : 0;
    if (v->fd < 0) return -1;
    struct stat st;
    if (live && fstat(v->fd, &st) == 0 && !S_ISREG(st.st_mode)) {
        fcntl(v->fd, F_SETFL, fcntl(v->fd, F_GETFL) | O_NONBLOCK);
        v->nonblock = 1;
        if (S_ISFIFO(st.st_mode)) (void)fcntl(v->fd, F_SETPIPE_SZ, VSRC_PIPE_BYTES);   /* the default 64 KB holds 21 frames of 3 KB, and a still-screen frame is 28 B */
    }
    v->cap = 1 << 20; v->buf = malloc(v->cap);
    return v->buf ? 0 : -1;
}

static void vsrc_read(vsrc *v, size_t want)
{
    if (v->fd < 0 || v->eof) return;
    if (v->have + want > v->cap) { while (v->have + want > v->cap) v->cap *= 2; v->buf = realloc(v->buf, v->cap); }
    ssize_t r = read(v->fd, v->buf + v->have, want);
    if (r > 0) v->have += (size_t)r;
    else if (r == 0 || (errno != EAGAIN && errno != EINTR)) v->eof = 1;
}

/* complete frames buffered, counting stops at limit */
static int vsrc_count(const vsrc *v, int limit)
{
    size_t off = 0;
    int n = 0;
    while (n < limit && off + 4 <= v->have) {
        size_t L = get_be32(v->buf + off) & 0x7FFFFFFFu;
        if (off + 4 + L > v->have) break;
        off += 4 + L;
        n++;
    }
    return n;
}

/* live: how much encoded video may wait here before the pipe is left full. Superframes go out at the link's pace and video is delta-coded, so nothing can be
 * dropped after the encoder without a key: without a limit a slow reader grows this buffer without end, and every frame stays that late until a still screen drains it.
 * With it the encoder blocks on the pipe, then wlcap's newest-wins buffer does the dropping, before encoding. The byte limit alone let 3 KB frames queue for 1.8 s. */
#define VSRC_HIGH (256u << 10)
static int vsrc_wants_input(const vsrc *v)
{
    if (v->fd < 0 || v->eof) return 0;
    if (vsrc_count(v, VSRC_MAX_FRAMES) >= VSRC_MAX_FRAMES) return 0;
    if (v->have < VSRC_HIGH) return 1;
    return v->have < 4 + (size_t)(get_be32(v->buf) & 0x7FFFFFFFu);   /* a single frame larger than the limit must still complete */
}
int avlink_test_wants(int fd, int eof, uint8_t *buf, size_t have);   /* test/test_stall.c */
int avlink_test_wants(int fd, int eof, uint8_t *buf, size_t have) { vsrc v; memset(&v, 0, sizeof v); v.fd = fd; v.eof = eof; v.buf = buf; v.have = have; return vsrc_wants_input(&v); }

/* next complete frame -> malloc'd copy; 1 = got one, 0 = not yet (live) or end of stream (v->eof) */
static uint32_t g_vkey;
static int vsrc_frame(vsrc *v, int blocking, uint8_t **fr, uint32_t *len)
{
    for (;;) {
        if (v->have >= 4) {
            uint32_t L = get_be32(v->buf) & 0x7FFFFFFFu;   /* top bit: rnv2enc key frame */
            g_vkey = get_be32(v->buf) >> 31;
            if (L > 64u << 20) { fprintf(stderr, "avlink: bad .rnv frame length %u, stopping video\n", L); v->eof = 1; v->have = 0; return 0; }
            if (v->have >= 4 + (size_t)L) {
                *fr = malloc(L ? L : 1);
                memcpy(*fr, v->buf + 4, L);
                *len = L;
                memmove(v->buf, v->buf + 4 + L, v->have - 4 - L);
                v->have -= 4 + L;
                v->frames++;
                return 1;
            }
            if (v->eof) { v->have = 0; return 0; }
            vsrc_read(v, 4 + (size_t)L - v->have);
        } else {
            if (v->eof) return 0;
            vsrc_read(v, 65536);
        }
        if (!blocking && v->nonblock) {          /* one read per call in live mode */
            if (v->have >= 4 && v->have >= 4 + (size_t)(get_be32(v->buf) & 0x7FFFFFFFu)) continue;
            return 0;
        }
    }
}

/* ------------------------------------------------------------------ yuy2 CRC file (TLV 0x10, test streams) */
static FILE *g_crcf;
static int crc_for_frame(uint32_t *crc)
{
    char line[128];
    if (!g_crcf || !fgets(line, sizeof line, g_crcf)) return 0;
    unsigned long fi, c;
    if (sscanf(line, "%lu %lu", &fi, &c) != 2) return 0;
    *crc = (uint32_t)c;
    return 1;
}

/* ------------------------------------------------------------------ fragmenter: frames -> fragment FIFO */
typedef struct { uint8_t *data; uint32_t len, crc, yuy2_crc; int refs, has_yuy2, key; uint32_t index; } frame_t;
typedef struct { frame_t *f; uint32_t off, len; uint16_t nch; } frag_t;
#define FQ_N 4096
static frag_t fq[FQ_N];
static int fq_head, fq_n;
static uint32_t g_frames_in, g_frames_dropped;

static void frame_unref(frame_t *f) { if (--f->refs == 0) { free(f->data); free(f); } }

static int fragment_frame(uint8_t *data, uint32_t len)
{
    uint32_t cap = (uint32_t)O.maxvid * 512;
    uint16_t nch = (uint16_t)((len + cap - 1) / cap);
    frame_t *f = calloc(1, sizeof *f);
    f->data = data; f->len = len; f->index = g_frames_in++; f->key = (int)g_vkey;
    f->crc = crc32z(0, data, len);
    f->has_yuy2 = crc_for_frame(&f->yuy2_crc);
    if (!nch) { free(data); free(f); return 0; }          /* empty frame: no superframe (as sdgen.py) */
    if (fq_n + nch > FQ_N) { g_frames_dropped++; free(data); free(f); return -1; }
    f->refs = nch;
    for (uint16_t c = 0; c < nch; c++) {
        frag_t *q = &fq[(fq_head + fq_n++) % FQ_N];
        q->f = f; q->off = c * cap; q->len = (len - q->off) < cap ? (len - q->off) : cap; q->nch = nch;
    }
    return nch;
}

/* ------------------------------------------------------------------ superframe queue (built, not yet sent) */
typedef struct {
    uint32_t seq; uint16_t total, next_idx; int state;   /* 0 begin, 1 wire, 2 end */
    uint8_t *body;
} txsf;
#define TQ_N 8
static txsf tq[TQ_N];
static int tq_head, tq_n;

static audio_stage g_aud;
static vsrc g_vid;
static link_t g_link;
static int g_have_link;
/* reader tracking, live only. stalled starts true: there is no reader until one has been seen. */
static struct { int have, stalled, returned; uint64_t n_served; uint32_t served, activity; uint64_t t_served, t_act; } g_rd = {.stalled = 1};
static int g_can_discard;           /* live, with a link, credits, a pipe and a way to ask for a key */
static int g_wait_key;              /* a delta was discarded: nothing but a key may follow */
static uint64_t g_vavg;             /* mean encoded frame, bytes */
static uint32_t g_discards, g_vdiscarded, g_stalls, g_window_waits, g_away_ticks;
static int g_whole_sf, g_cfg_dirty;  /* CONFIG whole_sf: 0 = not set by us, every CONFIG byte as before */
static FILE *g_dump_sf, *g_dump_wire;
static uint32_t g_seq, g_built, g_planned, g_first_total, g_last_fid, g_audio_pts;
static int g_video_done;
static uint64_t g_t0;
static uint32_t g_late_ticks, g_repeat_sf, g_credit_waits, g_sent_sf;
static uint16_t audio_frames_per_sf(void) { return (uint16_t)(48000.0 / O.fps + 0.5); }

static uint16_t total_for(const frag_t *fr)
{
    uint32_t ab = O.no_audio ? 0 : (uint32_t)audio_frames_per_sf() * 4;
    return sf_total_sec(ab, fr ? fr->len : 0);
}

/* batch: read frames until two fragments are queued (sdgen.py plan: a frame is taken only if all its fragments
 * fit in the K superframes; the first one that does not fit ends the video, REPEAT pads the rest) */
static void plan_fill(int blocking)
{
    while (!g_video_done && fq_n < 2) {
        uint8_t *fr; uint32_t len;
        if (O.k && g_frames_in >= (uint32_t)O.k) { g_video_done = 1; break; }
        if (!vsrc_frame(&g_vid, blocking, &fr, &len)) { if (g_vid.eof) g_video_done = 1; break; }
        g_vavg = g_vavg ? (uint64_t)((int64_t)g_vavg + ((int64_t)len - (int64_t)g_vavg) / 8) : len;
        if (g_wait_key) {
            if (!g_vkey) { uint32_t c; crc_for_frame(&c); free(fr); g_vdiscarded++; continue; }
            g_wait_key = 0;
        }
        if (O.k) {
            uint32_t cap = (uint32_t)O.maxvid * 512, nch = (len + cap - 1) / cap;
            if (g_planned + nch > (uint32_t)O.k) { free(fr); g_video_done = 1; break; }
            g_planned += nch;
        }
        fragment_frame(fr, len);
    }
}

#include "sdctl.h"

/* build superframe g_seq from the head fragment (or REPEAT) + one tick of audio */
static void build_sf(int blocking)
{
    static uint8_t abuf[48000 * 4];
    sf_hdr h;
    memset(&h, 0, sizeof h);
    frag_t fr = {0}, *frp = NULL;
    if (fq_n) { fr = fq[fq_head]; fq_head = (fq_head + 1) % FQ_N; fq_n--; frp = &fr; }
    uint16_t af = audio_frames_per_sf();
    uint32_t ab = 0;
    if (!O.no_audio) { audio_take(&g_aud, af, abuf, blocking); ab = (uint32_t)af * 4; }
    int batch = O.k > 0;
    if (g_stop_tlv > 0) { sf_tlv(&h, TLV_STOP, "STOP", 4); g_stop_tlv--; }
    h.seq = g_seq;
    h.audio_pts = g_audio_pts;
    h.video_pts = g_audio_pts + AV_DELAY;
    h.audio_frames = O.no_audio ? 0 : af;
    h.audio_fmt = O.no_audio ? AUDIO_FMT_NONE : AUDIO_FMT_S16;
    h.video_fmt = VIDEO_FMT_RNV2;
    h.pi_time_us = batch ? g_built * 16667u : (uint32_t)(now_us() - g_t0);
    if (frp) {
        frame_t *f = fr.f;
        if (fr.nch > 1) {
            uint8_t t[12];
            put_be32(t, f->len); put_be32(t + 4, fr.off); put_be32(t + 8, f->crc);
            sf_tlv(&h, TLV_FRAG, t, 12);
        }
        if (fr.off + fr.len == f->len && f->has_yuy2) {
            uint8_t t[8];
            put_be32(t, f->index); put_be32(t + 4, f->yuy2_crc);
            sf_tlv(&h, TLV_YUY2_CRC, t, 8);
        }
        if ((f->index == 0 || f->key) && fr.off == 0) h.flags |= SFF_KEY | SFF_DISCONT;   /* stream start: decoder from black */
        h.frame_id = (uint16_t)f->index;
        g_last_fid = f->index;
    } else {
        h.flags |= SFF_REPEAT;
        h.frame_id = batch ? 0 : (uint16_t)g_last_fid;   /* sdgen.py writes 0 on REPEAT */
        g_repeat_sf++;
    }
    if (batch && O.eos && g_built + 1 == (uint32_t)O.k) h.flags |= SFF_EOS;
    /* next_total_hint: total_sec of seq+1 if it is already known */
    if (batch) {
        if (g_built == 0) g_first_total = total_for(frp);
        if (g_built + 1 == (uint32_t)O.k) h.next_total_hint = g_first_total;   /* slot window wraps (sdgen) */
        else h.next_total_hint = total_for(fq_n ? &fq[fq_head] : NULL);         /* plan_fill made it certain */
    } else {
        h.next_total_hint = fq_n ? total_for(&fq[fq_head]) : 0;
    }
    uint32_t vb = frp ? fr.len : 0;
    uint16_t total = sf_total_sec(ab, vb);
    uint8_t *body = malloc((size_t)total * 512);
    sf_build(&h, ab ? abuf : NULL, ab, frp ? fr.f->data + fr.off : NULL, vb, body);
    if (frp) frame_unref(fr.f);
    if (g_dump_sf) fwrite(body, 512, total, g_dump_sf);
    if (g_dump_wire) {
        uint32_t w[WIRE4_WORDS];
        for (int s = 0; s < total; s++) {
            if (O.wire == 4) wire4_sector(body + 512 * s, w); else wire1_sector(body + 512 * s, w);
            fwrite(w, 4, O.wire == 4 ? WIRE4_WORDS : WIRE1_WORDS, g_dump_wire);
        }
    }
    if (g_have_link) {
        txsf *t = &tq[(tq_head + tq_n++) % TQ_N];
        t->seq = g_seq; t->total = total; t->next_idx = 0; t->state = 0; t->body = body;
    } else free(body);
    g_seq++; g_built++;
    g_audio_pts += af;
}

/* Tick clock. Each tick sends a fixed 800 frames, so the tick must run at the audio source's rate: in the car a DAC clocks the PipeWire sink, not the Pi clock.
 * The period follows the fill of the input buffer (filtered: PipeWire delivers in bursts up to 30 ms), so there are no periodic drops or pads and the ticks stay even for video.
 * The slope is TICK_SPAN_US per 300 frames, the limit TICK_MAX_US. With no audio arriving for 250 ms (nothing to follow), the Pi clock rules, unchanged.
 * The limit was 30 us (0.18%, 47912 frames/s): with the chain running the source measured 47905 in the car, so the buffer ran dry and re-primed, a 35 ms gap, about once a minute (log 2026-11-06). */
#define TICK_SPAN_US 30                   /* slope */
#define TICK_MAX_US 120                   /* +-0.72% */
static int64_t g_lvl_q8; static int g_lvl_have; static uint64_t g_last_audio_us; static int32_t g_tick_adj;
static uint64_t tick_period(uint64_t period, uint64_t t)
{
    if (O.no_audio || g_aud.fd < 0) return period;
    if (g_aud.last_arrival) { g_aud.last_arrival = 0; g_last_audio_us = t; }
    if (!g_aud.primed || !g_last_audio_us || t - g_last_audio_us > 250000u) { g_lvl_have = 0; g_tick_adj = 0; return period; }
    int64_t lvl = (int64_t)(g_aud.have / 4) << 8;
    if (!g_lvl_have) { g_lvl_q8 = lvl; g_lvl_have = 1; }
    g_lvl_q8 += (lvl - g_lvl_q8) >> 5;            /* ~0.5 s */
    int64_t err = (g_lvl_q8 >> 8) - (48 * AUDIO_PRIME_MS + 400);   /* frames over the level we want after a tick, mean of the burst sawtooth */
    int64_t adj = err * TICK_SPAN_US / 300;
    if (adj > TICK_MAX_US) adj = TICK_MAX_US;
    if (adj < -TICK_MAX_US) adj = -TICK_MAX_US;
    g_tick_adj = (int32_t)adj;
    return (uint64_t)((int64_t)period - adj);
}

/* ------------------------------------------------------------------ USB writer */
static void put32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }   /* LE host */
static void put16(uint8_t *p, uint16_t v) { memcpy(p, &v, 2); }

static void tx_pump(void)
{
    /* Even the no-credit USB diagnostic needs a receiver-counter origin before SF traffic.
     * CONFIG is sent separately, so waiting here does not block the initial STATUS handshake. */
    if (!g_link.have_status || g_link.credit_error) { if (tq_n) g_credit_waits++; return; }
    int wbytes = O.wire == 4 ? WIRE4_BYTES : WIRE1_BYTES;
    while (tq_n && link_pending(&g_link) < (256u << 10)) {
        txsf *t = &tq[tq_head];
        if (t->state == 0) {
            if (!O.nocredits && link_slots(&g_link) <= 0) { g_credit_waits++; return; }
            /* Keep the queue on the Teensy short while a reader is working: what it cannot take waits above the encoder, where it can be dropped. Not while it makes no progress: it may be polling for this very superframe. */
            if (!O.k && !O.nocredits && !g_rd.stalled && g_link.n_served && (int32_t)(t->seq - g_link.last_served_seq) > RD_WINDOW) { g_window_waits++; return; }
            uint8_t *p = link_msg(&g_link, TL_SF_BEGIN, 8);
            put32(p, t->seq); put16(p + 4, t->total); put16(p + 6, 0);
            g_link.sent_begins++;
            t->state = 1;
        }
        if (t->state == 1) {
            while (t->next_idx < t->total) {
                int n = t->total - t->next_idx;
                if (n > O.chunk) n = O.chunk;
                if (!O.nocredits) {
                    int c = link_credits(&g_link);
                    if (c < n) { g_credit_waits++; return; }
                }
                uint8_t *p = link_msg(&g_link, TL_WIRE, 12 + (uint32_t)n * (uint32_t)wbytes);
                put32(p, t->seq); put16(p + 4, t->next_idx); put16(p + 6, (uint16_t)n); put32(p + 8, (uint32_t)O.wire);
                for (int s = 0; s < n; s++) {
                    const uint8_t *sec = t->body + 512 * (t->next_idx + s);
                    uint32_t w[WIRE4_WORDS];        /* the output buffer may be unaligned after a partial write */
                    if (O.wire == 4) wire4_sector(sec, w); else wire1_sector(sec, w);
                    memcpy(p + 12 + (size_t)s * wbytes, w, (size_t)wbytes);
                }
                g_link.sent_sectors += (uint32_t)n;
                t->next_idx = (uint16_t)(t->next_idx + n);
                if (link_pending(&g_link) >= (256u << 10)) return;
            }
            t->state = 2;
        }
        uint8_t *p = link_msg(&g_link, TL_SF_END, 4);
        put32(p, t->seq);
        free(t->body);
        tq_head = (tq_head + 1) % TQ_N; tq_n--;
        g_sent_sf++;
    }
}

static int g_img_stale;
static void send_config(void)
{
    tl_config c;
    memset(&c, 0, sizeof c);
    c.status_hz = 20;
    c.stale_ms = (O.k || g_img_stale) ? STALE_BATCH_MS : STALE_LIVE_MS;
    c.whole_sf = (uint8_t)g_whole_sf;
    memcpy(link_msg(&g_link, TL_CONFIG, sizeof c), &c, sizeof c);
}

/* video was lost on the way to the RNS-E (the decoder now waits for a key): ask the encoder for one at once, not at the next keyint */
static int g_keyfd = -1;
static uint32_t g_key_reqs;
static uint64_t g_key_t;
static void key_feedback(uint64_t t)
{
    static uint32_t last; static int have;
    const tl_status *s = &g_link.st;
    uint32_t lost = s->expired + s->evicted + s->notready;
    if (!have) { last = lost; have = g_link.n_status != 0; return; }
    if (g_rd.stalled) { last = lost; return; }     /* no reader right now: a key would be lost too */
    /* video lost, or the reader is back (its decoder needs a key), or frames were discarded and the key has not arrived: ask again */
    if ((lost == last && !g_rd.returned && !g_wait_key) || t - g_key_t < 500000u) return;
    last = lost; g_key_t = t; g_rd.returned = 0;
    if (g_keyfd >= 0 && write(g_keyfd, "key\n", 4) == 4) g_key_reqs++;
}

/* Superframes built and not yet read. Only meaningful once the reader has served one. */
static int reader_lag(void) { return (int)((int32_t)(g_seq - 1 - g_link.last_served_seq)); }

/* Reader falling behind: lower the encoder's rate at once (--linkcap, over the key FIFO), raise it again slowly once the reader keeps up. Finds what this screen can take. */
static double g_cap_now;
static uint32_t g_backoffs, g_catchups;
static void cap_send(double cap)
{
    char b[32];
    int n = snprintf(b, sizeof b, "cap %.0f\n", cap);
    if (write(g_keyfd, b, (size_t)n) == n) g_cap_now = cap;   /* FIFO full: the next step tries again */
}
static void backoff_update(uint64_t t)
{
    static uint64_t last_down, last_up, calm_since;
    if (O.linkcap <= 0 || g_keyfd < 0 || O.k) return;
    if (!g_cap_now) g_cap_now = O.linkcap;
    if (g_rd.stalled || !g_link.n_served) { calm_since = 0; return; }      /* no reader to measure */
    int lag = reader_lag();
    if (lag >= BACKOFF_LAG) {
        calm_since = 0;
        if (t - last_down < BACKOFF_STEP_US) return;
        last_down = t;
        double c = g_cap_now * BACKOFF_FACTOR, floor_ = O.linkcap * BACKOFF_FLOOR;
        if (c < floor_) c = floor_;
        if (c < g_cap_now) { cap_send(c); g_backoffs++; }
    } else if (lag > BACKOFF_CALM_LAG) {
        calm_since = 0;
    } else if (g_cap_now < O.linkcap) {
        if (!calm_since) calm_since = t;
        if (t - calm_since >= BACKOFF_CALM_US && t - last_up >= BACKOFF_UP_US) {
            double c = g_cap_now + O.linkcap * BACKOFF_UP;
            cap_send(c > O.linkcap ? O.linkcap : c);
            last_up = t;
        }
    }
}

/* Audio left on the Pi by late ticks, and a reader with room again: send an early tick. It is an ordinary superframe (a queued frame if there is one, else REPEAT), so seq, pts and next_total_hint
 * stay exact. Audio in flight is conserved, so draining the Pi back to its level returns the unit's FIFO to its target and no further: the unit cuts a backlog only 75 ms over that. */
static int catchup_due(uint64_t t, uint64_t period)
{
    static uint64_t last;
    if (!g_can_discard || O.no_audio || g_aud.fd < 0 || !g_aud.primed || g_rd.stalled || !g_link.n_served || g_stop_tlv) return 0;
    if (tq_n >= O.maxq - 1 || reader_lag() > CATCHUP_MAX_LAG || t - last < period / 2) return 0;
    if (g_aud.have / 4 < (size_t)(48 * AUDIO_PRIME_MS + CATCHUP_OVER)) return 0;
    last = t;
    return 1;
}

/* Drop every complete frame in the pipe and in vsrc, keep a partial one for its end. Called while nothing may wait. */
static void video_drop_input(void)
{
    if (g_vid.fd < 0 || g_vid.eof) return;
    for (int i = 0; i < 64; i++) { size_t h = g_vid.have; vsrc_read(&g_vid, 65536); if (g_vid.have == h) break; }
    size_t off = 0;
    while (off + 4 <= g_vid.have) {
        size_t L = get_be32(g_vid.buf + off) & 0x7FFFFFFFu;
        if (L > 64u << 20 || off + 4 + L > g_vid.have) break;     /* a bad length stays for vsrc_frame, which stops the video */
        off += 4 + L;
        uint32_t c; crc_for_frame(&c);
        g_vdiscarded++;
    }
    if (off) { memmove(g_vid.buf, g_vid.buf + off, g_vid.have - off); g_vid.have -= off; }
}

/* Everything not yet built into a superframe goes. Built superframes stay in order: they are older deltas, the chain up to here is intact. */
static void video_discard(void)
{
    while (fq_n) { frag_t *f = &fq[fq_head]; fq_head = (fq_head + 1) % FQ_N; fq_n--; g_vdiscarded += f->off + f->len == f->f->len; frame_unref(f->f); }
    video_drop_input();
    g_wait_key = 1;
    g_discards++;
}

/* Who is reading: SERVED (new superframe read) and every counter a read of the window moves. Lifetime counters, so the first STATUS is only a baseline. */
static void reader_update(uint64_t t)
{
    const tl_status *s = &g_link.st;
    if (!g_link.n_status) return;
    uint32_t act = s->sectors_served + s->holds + s->hold_timeouts + s->notready + s->expired + s->idle;
    if (!g_rd.have) { g_rd.have = 1; g_rd.served = s->served_seq; g_rd.activity = act; g_rd.n_served = g_link.n_served; }
    if (g_link.n_served != g_rd.n_served || s->served_seq != g_rd.served) {
        g_rd.n_served = g_link.n_served; g_rd.served = s->served_seq;
        g_rd.t_served = t; g_rd.t_act = t;
    }
    if (act != g_rd.activity) { g_rd.activity = act; g_rd.t_act = t; }
    int stalled = !g_rd.t_served || t - g_rd.t_served > RD_STALL_US;
    if (stalled && !g_rd.stalled) {
        g_stalls++;
        if (g_can_discard) video_discard();
    } else if (!stalled && g_rd.stalled) {
        g_rd.returned = 1; g_key_t = 0;            /* the key goes at once */
    }
    g_rd.stalled = stalled;
    if (stalled && g_can_discard) video_drop_input();
}

/* A backlog that outlives a return, or a stall shorter than RD_STALL_US: the tick takes one frame and the source brings one, so it would stay. Frames, not bytes. */
static int backlog_ticks(void)
{
    int n = fq_n + vsrc_count(&g_vid, 64), inpipe = 0;
    if (g_vid.fd >= 0 && g_vid.nonblock && ioctl(g_vid.fd, FIONREAD, &inpipe) == 0 && inpipe > 0)
        n += g_vavg ? (int)((uint64_t)inpipe / (g_vavg + 4)) : 1;
    return n;
}

static void backlog_check(uint64_t t)
{
    static uint64_t since, last;
    if (!g_can_discard || g_rd.stalled || g_wait_key || backlog_ticks() <= BACKLOG_TICKS) { since = 0; return; }
    if (!since) since = t;
    if (t - since >= BACKLOG_HOLD_US && t - last >= DISCARD_GAP_US) { video_discard(); last = t; since = 0; }
}

static void print_stats(const char *tag)
{
    if (O.quiet) return;
    const tl_status *s = &g_link.st;
    fprintf(stderr, "%s sf built=%u sent=%u repeat=%u late=%u frames=%u drop=%u audio_in=%llu silence=%llu adrop=%llu raw=%llu adj=%d "
            "credit_waits=%u keyreq=%u | teensy status=%llu free=%u/%u slots=%u newest=%u served=%u srv_sect=%u holds=%u "
            "timeouts=%u notready=%u expired=%u idle=%u evicted=%u conv=%u rxerr=%u bus=%u junk=%llu "
            "| rd_stalled=%d stalls=%u discards=%u vdiscarded=%u waitkey=%d window_waits=%u away_ticks=%u cap_kb=%u backoffs=%u catchups=%u\n",
            tag, g_built, g_sent_sf, g_repeat_sf, g_late_ticks, g_frames_in, g_frames_dropped,
            (unsigned long long)g_aud.frames_in, (unsigned long long)g_aud.frames_silence, (unsigned long long)g_aud.frames_dropped, (unsigned long long)g_aud.raw_bytes / 4, (int)g_tick_adj, g_credit_waits, g_key_reqs,
            (unsigned long long)g_link.n_status, s->free_sectors, s->pool_sectors, s->free_slots, s->newest_seq,
            s->served_seq, s->sectors_served, s->holds, s->hold_timeouts, s->notready, s->expired, s->idle, s->evicted,
            s->converted, s->rx_errors, s->bus_width, (unsigned long long)g_link.rx_junk,
            g_rd.stalled, g_stalls, g_discards, g_vdiscarded, g_wait_key, g_window_waits, g_away_ticks, (unsigned)(g_cap_now / 1000), g_backoffs, g_catchups);
}

/* ------------------------------------------------------------------ --wire-test: wire images of a raw file */
static int wire_test(const char *in, const char *out)
{
    FILE *fi = fopen(in, "rb"), *fo = fopen(out, "wb");
    if (!fi || !fo) { perror("wire-test"); return 1; }
    uint8_t sec[512]; uint32_t w[WIRE4_WORDS]; long n = 0;
    while (fread(sec, 1, 512, fi) == 512) {
        if (O.wire == 4) { wire4_sector(sec, w); fwrite(w, 4, WIRE4_WORDS, fo); }
        else { wire1_sector(sec, w); fwrite(w, 4, WIRE1_WORDS, fo); }
        n++;
    }
    fclose(fi); fclose(fo);
    fprintf(stderr, "wire-test: %ld sectors, %d-bit\n", n, O.wire);
    return 0;
}

static void usage(void)
{
    fprintf(stderr,
        "avlink [options]\n"
        "  --dev PATH         Teensy CDC (/dev/ttyACM0) or any byte stream; omit = build/dump only\n"
        "  --video FILE|-     .rnv stream (4-byte BE length + RNV2 frame), e.g. rnv2enc ... -o -\n"
        "  --audio FILE|-     48 kHz s16 stereo PCM, little-endian (--audio-be: big-endian); none = silence\n"
        "  --no-audio         audio_fmt 0, no audio sectors\n"
        "  --yuvcrc FILE      'frame crc' lines (rnv2enc --crc, video/out/*_c.txt) -> down-channel TLV 0x10\n"
        "  --maxvid N         video sectors per superframe (248); larger frames go out as TLV 0x11 fragments\n"
        "  --k N              batch: exactly N superframes, no pacing (sdgen.py-identical headers); --eos marks the last\n"
        "  --fps F            live tick rate (60)\n"
        "  --wire 4|1         wire image width (4)          --chunk N  sectors per WIRE message (32, max 64)\n"
        "  --nocredits        ignore STATUS credits (USB throughput tests only)\n"
        "  --dump-sf FILE     write the superframes (= sdgen.py .rsav)   --dump-wire FILE  write the wire images\n"
        "  --wire-test IN OUT wire images of every 512-B sector of IN (unit test vs sd_wire.py), then exit\n"
        "  --keyctl FIFO      rnv2enc --linkctl FIFO: write key when the Teensy reports lost superframes. Live, also enables the backlog\n"
        "                     discard: no reader, or a standing queue, drops frames until a key (without it: back-pressure only)\n"
        "  --linkcap B/s      the encoder's --linkcap: with --keyctl, lower it live while the reader lags, raise it back after. 0 (default): never touch it\n"
        "  --whole-sf 1|0    Teensy holds only before sector 0, until the superframe is complete; default: leave the Teensy's setting (off after boot).\n"
        "                     Live also: printf WSF1 > /tmp/avlink_sdctl, WSF0 to turn it off\n"
        "  --console          copy Teensy console text to stderr      --stats N  stats line every N s   -q\n");
}

int main(int argc, char **argv)
{
    crc_init();
    wire_init();
    const char *wt_in = NULL, *wt_out = NULL;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
#define ARG (i + 1 < argc ? argv[++i] : (usage(), exit(2), ""))
        if (!strcmp(a, "--dev")) O.dev = ARG;
        else if (!strcmp(a, "--video")) O.video = ARG;
        else if (!strcmp(a, "--audio")) O.audio = ARG;
        else if (!strcmp(a, "--audio-be")) O.audio_be = 1;
        else if (!strcmp(a, "--gain-db")) O.gain_db = atof(ARG);
        else if (!strcmp(a, "--no-audio")) O.no_audio = 1;
        else if (!strcmp(a, "--yuvcrc")) O.yuvcrc = ARG;
        else if (!strcmp(a, "--maxvid")) O.maxvid = atoi(ARG);
        else if (!strcmp(a, "--k")) O.k = atoi(ARG);
        else if (!strcmp(a, "--eos")) O.eos = 1;
        else if (!strcmp(a, "--fps")) O.fps = atof(ARG);
        else if (!strcmp(a, "--wire")) O.wire = atoi(ARG);
        else if (!strcmp(a, "--chunk")) O.chunk = atoi(ARG);
        else if (!strcmp(a, "--nocredits")) O.nocredits = 1;
        else if (!strcmp(a, "--dump-sf")) O.dump_sf = ARG;
        else if (!strcmp(a, "--dump-wire")) O.dump_wire = ARG;
        else if (!strcmp(a, "--wire-test")) { wt_in = ARG; wt_out = ARG; }
        else if (!strcmp(a, "--keyctl")) O.keyctl = ARG;
        else if (!strcmp(a, "--linkcap")) O.linkcap = atof(ARG);
        else if (!strcmp(a, "--whole-sf")) g_whole_sf = atoi(ARG) ? 2 : 1;
        else if (!strcmp(a, "--console")) O.console = 1;
        else if (!strcmp(a, "--stats")) O.stats_s = atoi(ARG);
        else if (!strcmp(a, "-q")) O.quiet = 1;
        else { usage(); return 2; }
    }
    if (O.wire != 4 && O.wire != 1) { usage(); return 2; }
    if (wt_in) return wire_test(wt_in, wt_out);
    if (O.chunk < 1 || O.chunk > 64 || O.maxvid < 1 || O.fps < 1) { usage(); return 2; }
    uint32_t ab = O.no_audio ? 0 : (uint32_t)audio_frames_per_sf() * 4;
    if (sf_total_sec(ab, (uint32_t)O.maxvid * 512) > SF_MAX_SECT) {
        fprintf(stderr, "avlink: --maxvid %d + audio exceeds the 256-sector slot\n", O.maxvid);
        return 2;
    }
    int live = O.k == 0;
    if (vsrc_open(&g_vid, O.video, live) || audio_open(&g_aud, O.no_audio ? NULL : O.audio, O.audio_be, live)) {
        perror("avlink: input");
        return 1;
    }
    if (O.gain_db != 0) { double g = 1; for (int n = 0; n < 200; n++) g *= 1.0 + O.gain_db / 200 * 0.11512925; g_aud.gain_q15 = (int)(g * 32768 + 0.5); }   /* 10^(dB/20), no libm */
    if (O.yuvcrc && !(g_crcf = fopen(O.yuvcrc, "r"))) { perror(O.yuvcrc); return 1; }
    if (O.dump_sf && !(g_dump_sf = fopen(O.dump_sf, "wb"))) { perror(O.dump_sf); return 1; }
    if (O.dump_wire && !(g_dump_wire = fopen(O.dump_wire, "wb"))) { perror(O.dump_wire); return 1; }
    if (O.dev) {
        if (link_open(&g_link, O.dev)) { perror(O.dev); return 1; }
        g_link.console = O.console;
        g_have_link = 1;
        send_config();
    }
    if (O.keyctl && (g_keyfd = open(O.keyctl, O_RDWR | O_NONBLOCK)) < 0) { perror(O.keyctl); return 1; }
    signal(SIGINT, on_sig); signal(SIGTERM, on_sig); signal(SIGPIPE, SIG_IGN);
    g_seq = O.seq0;
    if (g_have_link && live) sdctl_open();
    /* A discard needs a key to end it, and only a pipe can be left full or drained. Otherwise: back-pressure only, as batch and --nocredits. */
    g_can_discard = g_have_link && live && !O.nocredits && g_keyfd >= 0 && g_vid.nonblock;
    g_wait_key = g_can_discard;
    g_t0 = now_us();
    uint64_t period = (uint64_t)(1e6 / O.fps), next_tick = g_t0, next_stats = g_t0 + (uint64_t)O.stats_s * 1000000u;
    int rc = 0;
    uint64_t last_status_t = g_t0, last_cfg_t = g_t0;
    uint64_t last_nstatus = 0, away_t = 0, img_t = 0;
    while (!g_stop) {
        uint64_t t = now_us();
        /* 1. build */
        if (!live) {
            while (g_built < (uint32_t)O.k && (!g_have_link || tq_n < O.maxq)) { plan_fill(1); build_sf(1); }
            if (g_built >= (uint32_t)O.k && (!g_have_link || (!tq_n && !link_pending(&g_link)))) break;
        } else if (t >= next_tick) {
            plan_fill(0);
            backlog_check(t);
            int ended = g_video_done && !fq_n && (O.no_audio || g_aud.fd < 0 || g_aud.eof) &&
                        (g_vid.fd >= 0 || g_aud.fd >= 0);
            if (ended) {
                if (!g_have_link || (!tq_n && !link_pending(&g_link))) break;
            } else if (g_have_link && tq_n >= O.maxq) {
                g_late_ticks++;                    /* USB/credits behind: don't consume a seq, encoder backs up */
            } else if (g_can_discard && g_rd.stalled && !g_stop_tlv && t - g_rd.t_act > RD_POLLING_US && t - away_t < AWAY_PERIOD_US) {
                g_away_ticks++;                    /* nobody reading: no point filling the Teensy, audio stays current in the audio stage */
            } else { build_sf(0); away_t = t; }
            next_tick += tick_period(period, t);
            if (t > next_tick + 4 * period) next_tick = t + period;   /* fell far behind: resync the clock */
        } else if (g_have_link && catchup_due(t, period)) {
            plan_fill(0);
            build_sf(0);
            g_catchups++;
        }
        /* 2. USB */
        if (g_have_link) {
            /* The Teensy sends STATUS only after a message, and drops the link if a message beats its DTR debounce (~15 ms after
             * open). Keep asking until STATUS flows. A later counter reset fails closed; seamless reboot recovery needs an epoch handshake. */
            if (g_link.n_status != last_nstatus) { last_nstatus = g_link.n_status; last_status_t = t; }
            else if (t - last_status_t > 300000u && t - last_cfg_t > 200000u) { send_config(); last_cfg_t = t; }
            if (live) { reader_update(t); backoff_update(t); }
            key_feedback(t);
            sdctl_poll();
            if (g_img_wait) img_t = t;             /* a bootstrap image is read once, later: it must outlast the stream around it */
            if (live && !!g_img_wait != g_img_stale && (g_img_wait || t - img_t > IMG_HOLD_US)) { g_img_stale = !!g_img_wait; send_config(); }
            if (g_cfg_dirty) { g_cfg_dirty = 0; send_config(); }
            tx_pump();
            if (link_write(&g_link) < 0) { fprintf(stderr, "avlink: write error: %s\n", strerror(errno)); rc = 1; break; }
        }
        /* 3. wait for input / output / tick */
        struct pollfd p[3]; int np = 0;
        if (g_have_link) { p[np].fd = g_link.fd; p[np].events = POLLIN | (link_pending(&g_link) ? POLLOUT : 0); np++; }
        if (live && g_vid.nonblock && (vsrc_wants_input(&g_vid) || (g_vid.fd >= 0 && !g_vid.eof && g_can_discard && (g_wait_key || g_rd.stalled)))) { p[np].fd = g_vid.fd; p[np].events = POLLIN; np++; }
        if (live && audio_poll_fd(&g_aud) >= 0) { p[np].fd = g_aud.fd; p[np].events = POLLIN; np++; }
        int64_t wait_us = 5000;                 /* to the microsecond: rounding down to whole ms made poll(0) spin through the last ms of every tick */
        if (live) { wait_us = (int64_t)(next_tick - now_us()); if (wait_us < 0) wait_us = 0; if (wait_us > 5000) wait_us = 5000; }
        struct timespec wait_ts = {0, (long)wait_us * 1000};
        ppoll(p, (nfds_t)np, &wait_ts, NULL);
        for (int i = 0; i < np; i++) {
            if (g_have_link && p[i].fd == g_link.fd && (p[i].revents & (POLLIN | POLLHUP | POLLERR))) {
                if (link_read(&g_link) < 0 && g_link.hup) {
                    fprintf(stderr, "avlink: %s\n", g_link.credit_error
                            ? "credit accounting lost synchronization; restart the sender"
                            : "device hung up");
                    rc = 1; g_stop = 1;
                }
            } else if (p[i].fd == g_vid.fd && (p[i].revents & (POLLIN | POLLHUP))) {
                vsrc_read(&g_vid, 65536);
            } else if (p[i].fd == g_aud.fd && (p[i].revents & (POLLIN | POLLHUP))) {
                audio_read_avail(&g_aud);
            }
        }
        if (O.stats_s && now_us() >= next_stats) { print_stats("STAT"); next_stats += (uint64_t)O.stats_s * 1000000u; }
    }
    if (g_have_link) { link_drain(&g_link, 2000); link_read(&g_link); }
    sdctl_close();
    print_stats("END");
    if (g_dump_sf) fclose(g_dump_sf);
    if (g_dump_wire) fclose(g_dump_wire);
    if (g_have_link) link_close(&g_link);
    audio_close(&g_aud);
    return rc;
}
