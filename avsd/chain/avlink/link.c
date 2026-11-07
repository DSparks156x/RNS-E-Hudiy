/* link.c -- see link.h */
#define _DEFAULT_SOURCE
#include "link.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

static uint32_t rd32le(const uint8_t *p) { return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24); }
static uint16_t rd16le(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static void wr32le(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static void wr16le(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

int link_open(link_t *l, const char *path)
{
    memset(l, 0, sizeof *l);
    l->fd = open(path, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (l->fd < 0) return -1;
    l->rfd = l->fd;
    struct termios t;
    if (tcgetattr(l->fd, &t) == 0) {        /* CDC ACM or pty: raw bytes, no echo, no CR/LF mangling */
        l->is_tty = 1;
        cfmakeraw(&t);
        t.c_cflag |= CLOCAL | CREAD;
        t.c_cc[VMIN] = 0; t.c_cc[VTIME] = 0;
        cfsetispeed(&t, B115200); cfsetospeed(&t, B115200);   /* ignored by CDC (USB HS) */
        tcsetattr(l->fd, TCSANOW, &t);
        tcflush(l->fd, TCIFLUSH);
    }
    l->ocap = 1 << 20; l->out = malloc(l->ocap);
    l->icap = TL_HDR + TL_MAX_PAYLOAD + 4096; l->in = malloc(l->icap);
    return (l->out && l->in) ? 0 : -1;
}

void link_close(link_t *l)
{
    if (l->fd >= 0) close(l->fd);
    free(l->out); free(l->in);
    l->out = l->in = NULL;
}

uint8_t *link_msg(link_t *l, uint16_t type, uint32_t len)
{
    if (l->opos && l->opos == l->olen) l->opos = l->olen = 0;
    if (l->olen + TL_HDR + len > l->ocap) {             /* compact, then grow */
        memmove(l->out, l->out + l->opos, l->olen - l->opos);
        l->olen -= l->opos; l->opos = 0;
        while (l->olen + TL_HDR + len > l->ocap) { l->ocap *= 2; l->out = realloc(l->out, l->ocap); }
    }
    uint8_t *h = l->out + l->olen;
    wr32le(h, TL_MAGIC); wr16le(h + 4, type); wr16le(h + 6, 0); wr32le(h + 8, len); wr32le(h + 12, l->msg_seq++);
    l->olen += TL_HDR + len;
    l->bytes_out += TL_HDR + len;
    return h + TL_HDR;
}

int link_credits(const link_t *l)
{
    if (!l->have_status || l->credit_error) return -1;
    uint32_t pending = l->sent_sectors - l->ack_sectors;
    if (pending > INT_MAX) return -1;
    return (int)l->st.free_sectors - (int)pending;
}

int link_slots(const link_t *l)
{
    if (!l->have_status || l->credit_error) return -1;
    uint32_t pending = l->sent_begins - l->ack_begins;
    if (pending > INT_MAX) return -1;
    return (int)l->st.free_slots - (int)pending;
}

size_t link_pending(const link_t *l) { return l->olen - l->opos; }

int link_write(link_t *l)
{
    if (l->credit_error) { errno = EPROTO; return -1; }
    while (l->opos < l->olen) {
        ssize_t w = write(l->fd, l->out + l->opos, l->olen - l->opos);
        if (w > 0) { l->opos += (size_t)w; continue; }
        if (w < 0 && (errno == EAGAIN || errno == EINTR)) return 0;
        return -1;
    }
    l->opos = l->olen = 0;
    return 0;
}

int link_drain(link_t *l, int timeout_ms)
{
    if (l->credit_error) { errno = EPROTO; return -1; }
    while (link_pending(l) && timeout_ms > 0) {
        struct pollfd p = {l->fd, POLLOUT | POLLIN, 0};
        if (poll(&p, 1, 10) > 0) {
            if ((p.revents & POLLIN) && link_read(l) < 0) return -1;
            if (link_write(l) < 0) return -1;
        }
        timeout_ms -= 10;
    }
    if (l->is_tty) tcdrain(l->fd);
    return link_pending(l) ? -1 : 0;
}

static int credit_fault(link_t *l)
{
    l->credit_error = 1;
    l->hup = 1;                   /* existing callers terminate rather than continuing with stale credits */
    errno = EPROTO;
    return -1;
}

static int on_msg(link_t *l, uint16_t type, const uint8_t *p, uint32_t len)
{
    if (type == TL_STATUS) {
        tl_status s;
        if (len != sizeof s) return credit_fault(l);
        memcpy(&s, p, sizeof s);      /* both ends little-endian */
        if (s.ver != 1 || s.size != sizeof s || !s.pool_sectors || s.pool_sectors > 65534u ||
            s.free_sectors > s.pool_sectors || s.free_slots > 256u)
            return credit_fault(l);
        if (!l->have_status) {
            /* The receiver totals survive DTR reconnects. No credited SF traffic can have been queued yet;
             * use this snapshot as the connection origin, not as acknowledgements of this process's data.
             * A no-credit diagnostic that sent before STATUS cannot be safely reconciled here. */
            if (l->sent_sectors || l->sent_begins) return credit_fault(l);
            l->ack_sectors = l->ack_begins = 0;
        } else {
            uint32_t sectors = s.rx_sectors - l->st.rx_sectors;
            uint32_t begins = s.begun - l->st.begun;
            uint32_t pending_sectors = l->sent_sectors - l->ack_sectors;
            uint32_t pending_begins = l->sent_begins - l->ack_begins;
            /* Unsigned deltas support ordinary u32 wrap. A reset/backward acknowledgement normally
             * becomes a huge delta; never reinterpret it as a new origin while data may be in flight. */
            if (s.pool_sectors != l->st.pool_sectors || pending_sectors > INT_MAX || pending_begins > INT_MAX ||
                sectors > pending_sectors || begins > pending_begins)
                return credit_fault(l);
            l->ack_sectors += sectors;
            l->ack_begins += begins;
        }
        l->st = s;
        l->have_status = 1;
        l->n_status++;
    } else if (type == TL_SERVED && len >= 8) {
        l->n_served++;
        l->last_served_seq = rd32le(p);
        l->last_served_t = rd32le(p + 4);
    }
    /* HOST_WRITE / UPLINK / CMDLOG: out of scope here (uplink agent) -- ignored */
    return 0;
}

int link_read(link_t *l)
{
    if (l->credit_error) { errno = EPROTO; return -1; }
    int nmsg = 0, hard = 0;
    for (;;) {
        if (l->ilen == l->icap) { l->rx_junk += l->ilen; l->ilen = 0; }
        ssize_t r = read(l->rfd, l->in + l->ilen, l->icap - l->ilen);
        if (r > 0) l->ilen += (size_t)r;
        else if ((r == 0 && !l->is_tty) || (r < 0 && errno != EAGAIN && errno != EINTR)) {
            /* a raw tty with VMIN=0 returns 0 for "no data"; only EIO (USB unplugged) or EOF on a non-tty is a hangup.
             * Whatever is left in the buffer: with no credits nothing is being written, so nothing else would notice. */
            hard = 1;
        }
        /* parse: skip console text until the magic */
        size_t i = 0;
        while (i + TL_HDR <= l->ilen) {
            if (rd32le(l->in + i) != TL_MAGIC) {
                size_t j = i + 1;
                while (j + 4 <= l->ilen && rd32le(l->in + j) != TL_MAGIC) j++;
                if (j + 4 > l->ilen) j = l->ilen >= 3 ? l->ilen - 3 : 0;   /* keep a possible magic prefix */
                if (j <= i) break;
                if (l->console) fwrite(l->in + i, 1, j - i, stderr);
                l->rx_junk += j - i;
                i = j;
                continue;
            }
            uint32_t len = rd32le(l->in + i + 8);
            if (len > TL_MAX_PAYLOAD) { i++; l->rx_junk++; continue; }
            if (i + TL_HDR + len > l->ilen) break;
            if (on_msg(l, rd16le(l->in + i + 4), l->in + i + TL_HDR, len) < 0) return -1;
            nmsg++;
            i += TL_HDR + len;
        }
        if (i) { memmove(l->in, l->in + i, l->ilen - i); l->ilen -= i; }
        if (hard) { l->hup = 1; return -1; }
        if (r <= 0) break;
    }
    return nmsg;
}
