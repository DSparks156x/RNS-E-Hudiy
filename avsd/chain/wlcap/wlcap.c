/* wlcap: direct Wayland screen capture to stdout, no scaling, no libraries beyond libc (speaks the wire protocol itself).
 *
 *   wlcap [--fps 60] [--n FRAMES] [--no-damage] | rnv2enc -i - --fmt rgb0 -o - ...
 *   wlcap --dmabuf [--fps 60] [--n FRAMES]      | rnv2enc -i - --fmt bgr0 -o - ...
 *
 * Default, zwlr_screencopy_manager_v1 + wl_shm: the compositor reads the frame back on its own thread and delivers XBGR8888 (= rgb0 bytes), stride = width * 4.
 * --dmabuf, zwlr_export_dmabuf_manager_v1: the compositor only hands over its finished output buffer (linear XRGB8888 = bgr0 bytes, stride = width * 4) and this
 * program copies it (DMA_BUF_IOCTL_SYNC waits for the GPU). The frame object keeps the buffer locked during the copy, so it can't be re-rendered under us.
 * It fires on every output frame whether or not anything changed (no damage events, and wlroots schedules a commit for it), so a frame identical to the last
 * one sent is dropped here: this also drops what compositor damage can't, a client commit with unchanged pixels. One plain screencopy comes first: a still
 * screen must still produce a picture.
 * Two threads, so a slow encoder can never hold up capture:
 *   capture: keeps one copy_with_damage request pending at all times, so every compositor commit that changed something is caught
 *            and a still screen costs no readback at all. Frames go to the newest-wins buffer, older unsent ones are overwritten.
 *   writer:  hands the newest frame to the pipe as soon as it exists, at most --fps per second. No fixed tick: two free-running 60 Hz
 *            clocks would beat, repeating one frame and overwriting the next every few seconds, which shows as judder. A still screen
 *            sends the same picture 10 times a second so the encoder keeps running. When the encoder is busy only this thread blocks.
 * Needs WAYLAND_DISPLAY and XDG_RUNTIME_DIR. Stats go to stderr. Build: cc -O2 -pthread -o wlcap wlcap.c */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/dma-buf.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

static int sock;
static uint32_t next_id = 2;
static uint32_t id_registry, id_shm, id_mgr, id_output, id_pool, id_buf[3], id_frame, id_export;
static uint32_t ver_mgr;
static int g_dmabuf;                                /* id_frame is a zwlr_export_dmabuf_frame_v1, not a screencopy frame */

/* event state */
static uint32_t ev_fmt, ev_w, ev_h, ev_stride, ev_flags;
static int ev_have_buf, ev_buf_done, ev_ready, ev_failed;
/* export_dmabuf frame state; fds arrive as ancillary data, in order */
static uint32_t dx_h, dx_bflags, dx_fmt, dx_nobj, dx_cancel;
static uint64_t dx_mod;
static uint32_t dx_size, dx_off, dx_stride;
static int dx_fd = -1, dx_nseen;
static int fdq[16], fdq_n;
static uint8_t rbuf[65536];
static size_t rlen;

static double now_s(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

static void die(const char *m) { fprintf(stderr, "wlcap: %s (%s)\n", m, strerror(errno)); exit(1); }

/* ---------------------------------------------------------------- wire output */
static uint8_t obuf[512];
static size_t olen;
static void m_begin(void) { olen = 8; }
static void m_u32(uint32_t v) { memcpy(obuf + olen, &v, 4); olen += 4; }
static void m_str(const char *s)
{
    uint32_t n = (uint32_t)strlen(s) + 1, pad = (4 - n % 4) % 4;
    m_u32(n);
    memcpy(obuf + olen, s, n);
    memset(obuf + olen + n, 0, pad);
    olen += n + pad;
}
static void m_send(uint32_t obj, uint16_t op, int fd)
{
    uint32_t hdr = ((uint32_t)olen << 16) | op;
    memcpy(obuf, &obj, 4);
    memcpy(obuf + 4, &hdr, 4);
    struct iovec io = {obuf, olen};
    struct msghdr mh;
    char cbuf[CMSG_SPACE(sizeof(int))];
    memset(&mh, 0, sizeof mh);
    mh.msg_iov = &io;
    mh.msg_iovlen = 1;
    if (fd >= 0) {
        mh.msg_control = cbuf;
        mh.msg_controllen = sizeof cbuf;
        struct cmsghdr *c = CMSG_FIRSTHDR(&mh);
        c->cmsg_level = SOL_SOCKET;
        c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(c), &fd, sizeof(int));
    }
    if (sendmsg(sock, &mh, MSG_NOSIGNAL) != (ssize_t)olen) die("send");
}

/* ---------------------------------------------------------------- wire input */
static void bind_global(uint32_t name, const char *iface, uint32_t ver, uint32_t id)
{
    m_begin(); m_u32(name); m_str(iface); m_u32(ver); m_u32(id);
    m_send(id_registry, 0, -1);
}

static void on_event(uint32_t obj, uint16_t op, const uint8_t *p, uint32_t n)
{
    uint32_t a[10] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    memcpy(a, p, n < 40 ? n : 40);
    if (obj == 1) {                                 /* wl_display */
        if (op == 0) { fprintf(stderr, "wlcap: protocol error obj %u code %u: %s\n", a[0], a[1], (const char *)p + 12); exit(1); }
    } else if (obj == id_registry && op == 0) {     /* global: name, iface, version */
        uint32_t name = a[0], len = a[1];
        const char *iface = (const char *)p + 8;
        uint32_t ver;
        memcpy(&ver, p + 8 + ((len + 3) & ~3u), 4);
        if (!strcmp(iface, "wl_shm") && !id_shm) { id_shm = next_id++; bind_global(name, iface, 1, id_shm); }
        else if (!strcmp(iface, "wl_output") && !id_output) { id_output = next_id++; bind_global(name, iface, 1, id_output); }
        else if (!strcmp(iface, "zwlr_screencopy_manager_v1") && !id_mgr) {
            ver_mgr = ver < 3 ? ver : 3;
            id_mgr = next_id++;
            bind_global(name, iface, ver_mgr, id_mgr);
        }
        else if (!strcmp(iface, "zwlr_export_dmabuf_manager_v1") && !id_export && g_dmabuf) { id_export = next_id++; bind_global(name, iface, 1, id_export); }
    } else if (obj == id_frame && id_frame && g_dmabuf) {
        switch (op) {
        case 0: dx_h = a[1]; dx_bflags = a[4]; dx_fmt = a[6]; dx_mod = ((uint64_t)a[7] << 32) | a[8]; dx_nobj = a[9]; dx_nseen = 0; break;   /* w h x y buffer_flags flags format mod_hi mod_lo num_objects */
        case 1:                                     /* index, (fd), size, offset, stride, plane */
            if (fdq_n > 0) {
                int fd = fdq[0];
                memmove(fdq, fdq + 1, sizeof(int) * (size_t)--fdq_n);
                if (dx_nseen++ == 0) { dx_fd = fd; dx_size = a[1]; dx_off = a[2]; dx_stride = a[3]; } else close(fd);
            }
            break;
        case 2: ev_ready = 1; break;
        case 3: ev_failed = 1; dx_cancel = a[0]; break;
        default: break;
        }
    } else if (obj == id_frame && id_frame) {
        switch (op) {
        case 0: ev_fmt = a[0]; ev_w = a[1]; ev_h = a[2]; ev_stride = a[3]; ev_have_buf = 1; break;
        case 1: ev_flags = a[0]; break;
        case 2: ev_ready = 1; break;
        case 3: ev_failed = 1; break;
        case 6: ev_buf_done = 1; break;
        default: break;
        }
    }
}

static void rx_some(void)                           /* one receive, keeping any file descriptors that come with it */
{
    char cb[CMSG_SPACE(sizeof(int) * 8)];
    struct iovec io = {rbuf + rlen, sizeof rbuf - rlen};
    struct msghdr mh;
    memset(&mh, 0, sizeof mh);
    mh.msg_iov = &io;
    mh.msg_iovlen = 1;
    mh.msg_control = cb;
    mh.msg_controllen = sizeof cb;
    ssize_t r = recvmsg(sock, &mh, MSG_CMSG_CLOEXEC);
    if (r <= 0) die("compositor closed the connection");
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&mh); c; c = CMSG_NXTHDR(&mh, c))
        if (c->cmsg_level == SOL_SOCKET && c->cmsg_type == SCM_RIGHTS) {
            int n = (int)((c->cmsg_len - CMSG_LEN(0)) / sizeof(int)), fd;
            for (int i = 0; i < n; i++) {
                memcpy(&fd, CMSG_DATA(c) + (size_t)i * sizeof(int), sizeof(int));
                if (fdq_n < 16) fdq[fdq_n++] = fd; else close(fd);
            }
        }
    rlen += (size_t)r;
}

static void pump(int timeout_ms)
{
    struct pollfd p = {sock, POLLIN, 0};
    if (poll(&p, 1, timeout_ms) <= 0) return;
    rx_some();
    size_t i = 0;
    while (i + 8 <= rlen) {
        uint32_t obj, h;
        memcpy(&obj, rbuf + i, 4);
        memcpy(&h, rbuf + i + 4, 4);
        uint32_t sz = h >> 16;
        if (sz < 8) die("bad message");
        if (i + sz > rlen) break;
        on_event(obj, (uint16_t)h, rbuf + i + 8, sz - 8);
        i += sz;
    }
    memmove(rbuf, rbuf + i, rlen - i);
    rlen -= i;
}

static int do_sync(void)                            /* roundtrip */
{
    uint32_t cb = next_id++;
    m_begin(); m_u32(cb);
    m_send(1, 0, -1);
    double t = now_s();
    for (;;) {
        /* wl_callback.done is simply the event for object cb: stop as soon as it is the last parsed one */
        struct pollfd p = {sock, POLLIN, 0};
        if (poll(&p, 1, 100) > 0) {
            rx_some();
            size_t i = 0;
            int done = 0;
            while (i + 8 <= rlen) {
                uint32_t obj, h;
                memcpy(&obj, rbuf + i, 4);
                memcpy(&h, rbuf + i + 4, 4);
                uint32_t sz = h >> 16;
                if (i + sz > rlen) break;
                if (obj == cb) done = 1;
                else on_event(obj, (uint16_t)h, rbuf + i + 8, sz - 8);
                i += sz;
            }
            memmove(rbuf, rbuf + i, rlen - i);
            rlen -= i;
            if (done) return 0;
        }
        if (now_s() - t > 5) die("no reply from compositor");
    }
}

static void write_all(const uint8_t *p, size_t n)
{
    while (n) {
        ssize_t w = write(1, p, n);
        if (w < 0) { if (errno == EINTR) continue; exit(errno == EPIPE ? 0 : 1); }
        p += w;
        n -= (size_t)w;
    }
}

/* ---------------------------------------------------------------- newest-wins exchange between the threads */
static pthread_mutex_t q_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t q_cv = PTHREAD_COND_INITIALIZER;
static uint8_t *q_buf[3];
static uint8_t q_inv[3];                            /* y-inverted flag of each buffer */
static int q_ready = -1, q_send = -1, q_free[3] = {1, 2, -1}, q_nfree = 2;   /* capture owns buffer 0 first */
static size_t q_size;
static uint32_t q_stride, q_h;
static double g_period;
static long g_nmax;
/* stats, under q_m */
static long c_frames, c_over, c_fails, c_same, w_frames, w_dup, w_late;
static double c_tot, c_max, c_gap_max, w_tot, w_max, c_read, c_read_max;

static void *writer(void *arg)
{
    (void)arg;
    uint8_t *flip = NULL;
    double last = 0, t_stat = 0, gap = g_period * 0.99;             /* 60.6/s at most: the compositor's frame timer can run a little over 60 */
    long l_c = 0, l_w = 0, l_d = 0;
    for (;;) {
        pthread_mutex_lock(&q_m);
        for (;;) {                                                  /* wait for a new frame, or the still-screen refresh */
            if (q_ready >= 0 || (q_send >= 0 && now_s() - last >= 0.1)) break;
            struct timespec ts;
            clock_gettime(CLOCK_REALTIME, &ts);
            ts.tv_nsec += 20000000;
            if (ts.tv_nsec >= 1000000000) { ts.tv_nsec -= 1000000000; ts.tv_sec++; }
            pthread_cond_timedwait(&q_cv, &q_m, &ts);
        }
        double w = last + gap - now_s();
        if (w > 0) {                                                /* too soon after the last one: wait, and take whatever is newest then */
            pthread_mutex_unlock(&q_m);
            struct timespec ts = {0, (long)(w * 1e9)};
            nanosleep(&ts, NULL);
            pthread_mutex_lock(&q_m);
        } else if (last && w < -g_period && q_ready >= 0 && now_s() - last < 0.05) w_late++;
        if (q_ready >= 0) {
            if (q_send >= 0) q_free[q_nfree++] = q_send;
            q_send = q_ready;
            q_ready = -1;
        } else w_dup++;
        const uint8_t *src = q_buf[q_send];
        size_t n = q_size;
        int inv = q_inv[q_send];
        uint32_t st = q_stride, h = q_h;
        pthread_mutex_unlock(&q_m);

        double t0 = now_s();
        if (!last) t_stat = t0 + 5;
        last = t0;
        if (inv) {
            if (!flip) flip = malloc(n);
            for (uint32_t y = 0; y < h; y++) memcpy(flip + (size_t)y * st, src + (size_t)(h - 1 - y) * st, st);
            src = flip;
        }
        write_all(src, n);
        double t1 = now_s(), d = t1 - t0;

        pthread_mutex_lock(&q_m);
        w_frames++; w_tot += d; if (d > w_max) w_max = d;
        if (t1 >= t_stat) {
            long nc = c_frames - l_c, nw = w_frames - l_w;
            fprintf(stderr, "wlcap: captured %ld (%.1f/s) overwritten %ld fails %ld same %ld copy mean %.2f max %.2f gap max %.1f ms | written %ld (%.1f/s) repeats %ld late %ld write mean %.2f max %.2f ms | buffer read mean %.2f max %.2f ms\n",
                    c_frames, nc / 5.0, c_over, c_fails, c_same, c_tot / (nc ? nc : 1) * 1e3, c_max * 1e3, c_gap_max * 1e3,
                    w_frames, nw / 5.0, w_dup - l_d, w_late, w_tot / (nw ? nw : 1) * 1e3, w_max * 1e3, c_read / (nc ? nc : 1) * 1e3, c_read_max * 1e3);
            l_c = c_frames; l_w = w_frames; l_d = w_dup;
            c_tot = c_max = c_gap_max = w_tot = w_max = c_read = c_read_max = 0;
            t_stat += 5;
        }
        long wf = w_frames;
        pthread_mutex_unlock(&q_m);
        if (g_nmax && wf >= g_nmax) exit(0);
    }
    return NULL;
}

/* ---------------------------------------------------------------- export_dmabuf */
#define DRM_FMT(a, b, c, d) ((uint32_t)(a) | ((uint32_t)(b) << 8) | ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))
static struct { ino_t ino; uint8_t *map; size_t len; } maps[8];     /* a compositor swapchain is a few buffers: map each once */

static const uint8_t *map_buffer(int fd, size_t len)
{
    struct stat st;
    if (fstat(fd, &st)) die("fstat dmabuf");
    for (int i = 0; i < 8; i++) if (maps[i].map && maps[i].ino == st.st_ino && maps[i].len == len) return maps[i].map;
    static int victim;
    int v = victim++ % 8;
    if (maps[v].map) munmap(maps[v].map, maps[v].len);
    uint8_t *m = mmap(NULL, len, PROT_READ, MAP_SHARED, fd, 0);
    if (m == MAP_FAILED) die("mmap dmabuf");
    maps[v].ino = st.st_ino; maps[v].map = m; maps[v].len = len;
    return m;
}

/* copy the exported frame into dst (bgr0 bytes, top row first); returns the seconds spent */
static double read_exported(uint8_t *dst, size_t stride, uint32_t h)
{
    if (dx_nobj != 1 || dx_fd < 0 || dx_mod != 0 || dx_stride != stride || dx_h != h || (dx_fmt != DRM_FMT('X', 'R', '2', '4') && dx_fmt != DRM_FMT('A', 'R', '2', '4'))) {
        fprintf(stderr, "wlcap: exported buffer is not linear XRGB8888 (fourcc %.4s, modifier %llx, %u objects, stride %u): use the default mode\n",
                (const char *)&dx_fmt, (unsigned long long)dx_mod, dx_nobj, dx_stride);
        exit(1);
    }
    const uint8_t *m = map_buffer(dx_fd, (size_t)dx_off + dx_size);
    struct dma_buf_sync sy = {DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ};
    while (ioctl(dx_fd, DMA_BUF_IOCTL_SYNC, &sy) && errno == EINTR) {}      /* waits for the GPU */
    double t = now_s();
    const uint8_t *src = m + dx_off;
    if (dx_bflags & 1) for (uint32_t y = 0; y < h; y++) memcpy(dst + (size_t)y * stride, src + (size_t)(h - 1 - y) * stride, stride);   /* y_invert */
    else memcpy(dst, src, stride * h);
    t = now_s() - t;
    sy.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ;
    ioctl(dx_fd, DMA_BUF_IOCTL_SYNC, &sy);
    return t;
}

int main(int argc, char **argv)
{
    double fps = 60;
    int cursor = 1, use_damage = 1, want_dmabuf = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--fps") && i + 1 < argc) fps = atof(argv[++i]);
        else if (!strcmp(argv[i], "--n") && i + 1 < argc) g_nmax = atol(argv[++i]);
        else if (!strcmp(argv[i], "--no-cursor")) cursor = 0;
        else if (!strcmp(argv[i], "--no-damage")) use_damage = 0;
        else if (!strcmp(argv[i], "--dmabuf")) want_dmabuf = 1;
        else { fprintf(stderr, "usage: wlcap [--fps 60] [--n FRAMES] [--no-cursor] [--no-damage] [--dmabuf]\n"); return 2; }
    }
    g_period = 1.0 / fps;
    const char *rt = getenv("XDG_RUNTIME_DIR"), *wd = getenv("WAYLAND_DISPLAY");
    if (!rt) rt = "/run/user/1000";
    if (!wd) wd = "wayland-0";
    struct sockaddr_un a;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    snprintf(a.sun_path, sizeof a.sun_path, "%s/%s", rt, wd);
    sock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (sock < 0 || connect(sock, (struct sockaddr *)&a, sizeof a)) die(a.sun_path);
    if (fcntl(1, F_SETPIPE_SZ, 1 << 20) < 0) fprintf(stderr, "wlcap: pipe size unchanged (%s)\n", strerror(errno));   /* fewer wakeups per frame */

    g_dmabuf = want_dmabuf;                                 /* so the registry binds the export manager; the first frame still uses screencopy */
    id_registry = next_id++;
    m_begin(); m_u32(id_registry);
    m_send(1, 1, -1);
    do_sync();
    do_sync();
    if (!id_shm || !id_mgr || !id_output) { fprintf(stderr, "wlcap: compositor lacks wl_shm / screencopy / output\n"); return 1; }
    if (want_dmabuf && !id_export) { fprintf(stderr, "wlcap: compositor lacks zwlr_export_dmabuf_manager_v1\n"); return 1; }
    g_dmabuf = 0;

    uint32_t bw = 0, bh = 0, bs = 0, bf = 0;
    uint8_t *map = NULL;
    int started = 0, fill = 0, last_pub = -1;              /* last_pub stays out of q_free until a newer frame is published */
    double t_last = 0;
    if (ver_mgr < 2) use_damage = 0;                        /* copy_with_damage arrived in version 2 */

    for (;;) {
        double t0 = now_s();
        if (want_dmabuf && started) {                       /* after the first plain copy */
            g_dmabuf = 1;
            id_frame = next_id++;
            ev_ready = ev_failed = 0;
            dx_fd = -1; dx_nseen = 0;
            m_begin(); m_u32(id_frame); m_u32((uint32_t)cursor); m_u32(id_output);
            m_send(id_export, 0, -1);                       /* capture_output: answered at the next output commit */
            while (!ev_ready && !ev_failed) pump(100);
            double rd = 0;
            if (ev_ready) rd = read_exported(q_buf[fill], q_stride, q_h);
            if (dx_fd >= 0) { close(dx_fd); dx_fd = -1; }
            double t1 = now_s();
            m_begin(); m_send(id_frame, 0, -1);             /* destroy: unlocks the buffer */
            id_frame = 0;
            pthread_mutex_lock(&q_m);
            if (ev_failed) c_fails++;
            else if (last_pub >= 0 && !memcmp(q_buf[fill], q_buf[last_pub], q_size)) c_same++;
            else {
                q_inv[fill] = 0;
                if (q_ready >= 0) { q_free[q_nfree++] = q_ready; c_over++; }
                q_ready = fill;
                last_pub = fill;
                fill = q_free[--q_nfree];
                c_frames++;
                c_tot += t1 - t0; if (t1 - t0 > c_max) c_max = t1 - t0;
                c_read += rd; if (rd > c_read_max) c_read_max = rd;
                if (t_last && t1 - t_last > c_gap_max) c_gap_max = t1 - t_last;
                t_last = t1;
                pthread_cond_signal(&q_cv);
            }
            pthread_mutex_unlock(&q_m);
            if (ev_failed) {
                if (dx_cancel == 1) { fprintf(stderr, "wlcap: export cancelled for good\n"); return 1; }
                struct timespec ts = {0, 5000000};          /* temporary: try again shortly */
                nanosleep(&ts, NULL);
            }
            continue;
        }
        id_frame = next_id++;
        ev_have_buf = ev_buf_done = ev_ready = ev_failed = 0;
        ev_flags = 0;
        m_begin(); m_u32(id_frame); m_u32((uint32_t)cursor); m_u32(id_output);
        m_send(id_mgr, 0, -1);
        while (!ev_failed && !(ev_have_buf && (ev_buf_done || ver_mgr < 3))) pump(100);
        if (!ev_failed && (ev_w != bw || ev_h != bh || ev_stride != bs || ev_fmt != bf)) {
            if (started) { fprintf(stderr, "wlcap: output mode changed, the encoder has a fixed size: exiting\n"); return 1; }
            bw = ev_w; bh = ev_h; bs = ev_stride; bf = ev_fmt;
            size_t one = (size_t)bs * bh;
            int fd = memfd_create("wlcap", MFD_CLOEXEC);
            if (fd < 0 || ftruncate(fd, (off_t)(one * 3))) die("memfd");
            map = mmap(NULL, one * 3, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            if (map == MAP_FAILED) die("mmap");
            id_pool = next_id++;
            m_begin(); m_u32(id_pool); m_u32((uint32_t)(one * 3));
            m_send(id_shm, 0, fd);
            close(fd);
            for (int b = 0; b < 3; b++) {
                id_buf[b] = next_id++;
                m_begin(); m_u32(id_buf[b]); m_u32((uint32_t)(one * (size_t)b)); m_u32(bw); m_u32(bh); m_u32(bs); m_u32(bf);
                m_send(id_pool, 0, -1);
                q_buf[b] = map + one * (size_t)b;
            }
            q_size = one; q_stride = bs; q_h = bh;
            pthread_t th;
            if (pthread_create(&th, NULL, writer, NULL)) die("thread");
            started = 1;
            fprintf(stderr, "wlcap: %ux%u stride %u format %u, %s\n", bw, bh, bs, bf, want_dmabuf ? "export_dmabuf, bgr0" : use_damage ? "damage-driven" : "every frame");
        }
        if (!ev_failed) {
            m_begin(); m_u32(id_buf[fill]);
            m_send(id_frame, use_damage && t_last ? 2 : 0, -1);  /* the first one is a plain copy: a still screen must still produce a picture */
            while (!ev_ready && !ev_failed) pump(100);
            if (want_dmabuf && ev_ready && bf == DRM_FMT('X', 'B', '2', '4')) {  /* --dmabuf output is bgr0 for every frame, this one too */
                uint8_t *p = q_buf[fill];
                for (size_t i = 0; i < (size_t)bs * bh; i += 4) { uint8_t t = p[i]; p[i] = p[i + 2]; p[i + 2] = t; }
            }
        }
        double t1 = now_s();
        pthread_mutex_lock(&q_m);
        if (ev_failed) c_fails++;
        else {
            q_inv[fill] = (ev_flags & 1) != 0;
            if (q_ready >= 0) { q_free[q_nfree++] = q_ready; c_over++; }
            q_ready = fill;
            last_pub = fill;
            fill = q_free[--q_nfree];
            c_frames++;
            c_tot += t1 - t0; if (t1 - t0 > c_max) c_max = t1 - t0;
            if (t_last && t1 - t_last > c_gap_max) c_gap_max = t1 - t_last;
            t_last = t1;
            pthread_cond_signal(&q_cv);
        }
        pthread_mutex_unlock(&q_m);
        m_begin(); m_send(id_frame, 1, -1);                         /* destroy */
        id_frame = 0;
        if (!use_damage) {                                          /* no damage events to wait on: don't outrun the frame rate */
            double w = g_period * 0.9 - (now_s() - t0);
            if (w > 0) { struct timespec ts = {0, (long)(w * 1e9)}; nanosleep(&ts, NULL); }
        }
    }
    return 0;
}
