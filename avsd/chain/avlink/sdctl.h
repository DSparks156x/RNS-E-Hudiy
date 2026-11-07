/* sdctl.h -- control FIFO of avlink (rnse_proto/SDBOOT.txt), included by avlink.c after the superframe queue.
 * While avlink owns the Teensy port, other tools reach the card through /tmp/avlink_sdctl:
 *   "IMG1" + u32 LE byte count + whole sectors: queued as one superframe with the next seq (RNS-E bootstrap image);
 *                                               when it has gone to USB, its seq is written to /tmp/avlink_sdctl.seq
 *   "STOP": TLV 0x12 in the next superframes, the running sdstream exits (err 8) on the first one it reads
 *   "WSF1" / "WSF0": Teensy whole-superframe hold on / off, at once, no restart (CONFIG whole_sf) */
#include <sys/stat.h>
#define SDCTL_PATH "/tmp/avlink_sdctl"
#define TLV_STOP 0x12
#define SDCTL_MAX (256u * 512u)
static int g_ctl = -1, g_stop_tlv, g_img_wait;
static uint32_t g_img_seq;
static uint8_t *g_ib;
static uint32_t g_ihave, g_ineed;
static uint8_t g_ihdr[8];
static uint32_t g_ihdrn;

static void sdctl_open(void)
{
    unlink(SDCTL_PATH);
    if (mkfifo(SDCTL_PATH, 0600) == 0) g_ctl = open(SDCTL_PATH, O_RDWR | O_NONBLOCK);
}

static void sdctl_close(void)
{
    if (g_ctl >= 0) { close(g_ctl); unlink(SDCTL_PATH); }
}

static void sdctl_poll(void)
{
    if (g_ctl < 0) return;
    if (g_img_wait) {                           /* image handed to USB: tell the loader which seq it got */
        int queued = 0;
        for (int i = 0; i < tq_n; i++) if (tq[(tq_head + i) % TQ_N].seq == g_img_seq) queued = 1;
        if (!queued && !link_pending(&g_link)) {
            int f = open(SDCTL_PATH ".seq", O_WRONLY | O_CREAT | O_TRUNC, 0600);
            if (f >= 0) { char b[16]; int n = snprintf(b, sizeof b, "%u\n", g_img_seq); if (write(f, b, (size_t)n) != n) {} close(f); }
            g_img_wait = 0;
        }
    }
    if (g_ineed && g_ihave == g_ineed) {        /* room in the queue: it goes out in order, seq stays monotonic */
        if (tq_n >= TQ_N) return;
        txsf *t = &tq[(tq_head + tq_n++) % TQ_N];
        t->seq = g_seq; t->total = (uint16_t)(g_ineed / 512); t->next_idx = 0; t->state = 0; t->body = g_ib;
        g_img_seq = g_seq; g_img_wait = 1;
        g_seq++;
        g_ib = NULL; g_ineed = g_ihave = 0;
    }
    for (;;) {
        ssize_t r;
        if (g_ineed) {
            if (g_ihave == g_ineed) return;
            r = read(g_ctl, g_ib + g_ihave, g_ineed - g_ihave);
            if (r <= 0) return;
            g_ihave += (uint32_t)r;
            continue;
        }
        uint32_t want = g_ihdrn >= 4 && !memcmp(g_ihdr, "IMG1", 4) ? 8 : 4;
        r = read(g_ctl, g_ihdr + g_ihdrn, want - g_ihdrn);
        if (r <= 0) return;
        g_ihdrn += (uint32_t)r;
        if (g_ihdrn == 4 && !memcmp(g_ihdr, "STOP", 4)) { g_stop_tlv = 12; g_ihdrn = 0; continue; }
        if (g_ihdrn == 4 && (!memcmp(g_ihdr, "WSF1", 4) || !memcmp(g_ihdr, "WSF0", 4))) { g_whole_sf = g_ihdr[3] == '1' ? 2 : 1; g_cfg_dirty = 1; g_ihdrn = 0; continue; }
        if (g_ihdrn == 4 && memcmp(g_ihdr, "IMG1", 4)) { memmove(g_ihdr, g_ihdr + 1, 3); g_ihdrn = 3; continue; }
        if (g_ihdrn == 8) {
            uint32_t n; memcpy(&n, g_ihdr + 4, 4);
            g_ihdrn = 0;
            if (n && !(n % 512) && n <= SDCTL_MAX && (g_ib = malloc(n))) { g_ineed = n; g_ihave = 0; }
        }
    }
}
