/* link.h -- SPEC 5 transport: TLNK messages over CDC (/dev/ttyACM0) or any byte stream (pty, fifo, file),
 * nonblocking, with STATUS-based credit flow control. The Teensy console text that shares the CDC stream is
 * skipped (or copied to stderr with link.console = 1).
 * The first STATUS establishes lifetime-counter origins before any SF traffic is queued. Protocol v1
 * has no epoch/challenge: it cannot authenticate an initial buffered STATUS or distinguish every reset
 * from legitimate u32 wrap. Contradictory later acknowledgements fail closed; live reboot recovery
 * requires reopening with a fresh receiver snapshot (and an epoch protocol for a complete guarantee). */
#ifndef AVL_LINK_H
#define AVL_LINK_H
#include <stdint.h>
#include <stddef.h>
#include "tlink.h"

typedef struct {
    int fd, rfd;                 /* write / read fds (same for a tty) */
    int is_tty, console, hup;
    uint8_t *out; size_t olen, ocap, opos;   /* pending output bytes [opos, olen) */
    uint8_t *in; size_t ilen, icap;
    uint32_t msg_seq;
    /* credits */
    int have_status;
    tl_status st;                /* last STATUS */
    uint32_t sent_sectors, sent_begins;      /* totals queued so far (u32 wrap, differences only) */
    uint32_t ack_sectors, ack_begins;        /* acknowledged in this connection, relative to first STATUS */
    int credit_error;            /* sticky EPROTO: close/reopen; never rebaseline a live session */
    uint64_t n_status, n_served, bytes_out, rx_junk;
    uint32_t last_served_seq, last_served_t;
} link_t;

int link_open(link_t *l, const char *path);      /* tty -> raw 8N1, nonblocking */
void link_close(link_t *l);
uint8_t *link_msg(link_t *l, uint16_t type, uint32_t len);   /* append a message header, returns payload ptr */
int link_credits(const link_t *l);               /* free pool sectors usable now (<0 = none / no STATUS yet) */
int link_slots(const link_t *l);                 /* free superframe slots usable now */
size_t link_pending(const link_t *l);            /* output bytes not written yet */
int link_write(link_t *l);                       /* write what the fd takes; -1 on error */
int link_read(link_t *l);                        /* read + parse; -1 on hangup or invalid credit state (EPROTO) */
int link_drain(link_t *l, int timeout_ms);       /* block until all output is written */

#endif
