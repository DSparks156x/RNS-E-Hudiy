/* rnv2enc CLI: raw 800x480 frames in, RNV2 .rnv stream out (each frame prefixed by a 4-byte big-endian length,
 * exactly what video/dec/rnv2dec.c reads).
 *
 *   rnv2enc -i frames.raw|- -o out.rnv|- [--fmt rgb24|bgr24|bgr0|rgb0] [--stride N] [-n frames] [--threads N]
 *           [--qpmin 0] [--lamk 0.04] [--kappa 4] [--thr 3] [--rate 8e6] [--cyc 4.49e6] [--buf 4] [--maxtries 12]
 *           [--me 0|1|2|3] [--mewin N] [--mewinmax N] [--rtrc N] [--exact] [--noraw] [--no-static-skip] [--scalar] [--prune N] [--qppred 0|1]
 *           [--linkcap B/s] [--linkctl FIFO|FILE] [--linkfd N] [--fixedq] [--levels 12] [--lamlo 0.0025] [--lamx 0.01] [--kappalo 16] [--thrlo 0] [--filltarget 0.25] [--hyst 0.85] [--dwell 4]
 *           [--damage FILE] [--auto-damage] [--skip N]
 *           [--recon FILE.yuy2] [--target FILE.yuy2] [--crc FILE] [--stats FILE] [--metrics] [--bench] [-q]
 *   Defaults are the REPORT_v3 recommended settings (qp_min 0, lam_k 0.04, kappa 4, T 3, 8e6 B/s, 4.49e6 cycles)
 *   with the real-time search / rate-control preset (--me 2, --mewinmax 1024, --rtrc 1).
 *   --exact: rnv2.py-parity preset (exhaustive 7x7 window, no search shortcuts, rnv2.py rate control).
 *   --damage FILE: one line per frame: "x,y,w,h x,y,w,h ..." (empty line = nothing damaged, "*" = unknown/full).
 *   --bench: read all frames into RAM first, then time encoding only.
 */
#define _GNU_SOURCE
#include "rnv2enc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

#define W RNV2_W
#define H RNV2_H

static uint32_t crc_tab[256];
static uint32_t crc32b(const uint8_t *p, size_t n) {
    uint32_t c = 0xFFFFFFFFu; size_t i;
    if (!crc_tab[1]) { int k; for (i = 0; i < 256; i++) { uint32_t v = (uint32_t)i; for (k = 0; k < 8; k++) v = (v >> 1) ^ (0xEDB88320u & -(v & 1)); crc_tab[i] = v; } }
    for (i = 0; i < n; i++) c = crc_tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}
static double now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec * 1e3 + t.tv_nsec * 1e-6; }

static int bpp_of(enum rnv2_fmt f) { return f == RNV2_RGB24 || f == RNV2_BGR24 ? 3 : 4; }
static void to_rgb(const uint8_t *s, enum rnv2_fmt f, int stride, uint8_t *d) {
    int y, x;
    for (y = 0; y < H; y++) {
        const uint8_t *p = s + (size_t)y * stride;
        for (x = 0; x < W; x++, d += 3) {
            switch (f) {
            case RNV2_RGB24: d[0] = p[3 * x]; d[1] = p[3 * x + 1]; d[2] = p[3 * x + 2]; break;
            case RNV2_BGR24: d[0] = p[3 * x + 2]; d[1] = p[3 * x + 1]; d[2] = p[3 * x]; break;
            case RNV2_BGR0: d[0] = p[4 * x + 2]; d[1] = p[4 * x + 1]; d[2] = p[4 * x]; break;
            default: d[0] = p[4 * x]; d[1] = p[4 * x + 1]; d[2] = p[4 * x + 2]; break;
            }
        }
    }
}

/* metrics, same definitions as video/run_eval.py */
static inline int q666(int v) { int q = v >> 2; return (q << 2) | (q >> 4); }
static inline int rnd255(double x) { double f = floor(x + 0.5); return f < 0 ? 0 : f > 255 ? 255 : (int)f; }
static void glass(const uint8_t *Y, const uint8_t *U, const uint8_t *V, uint8_t *g) {
    int i;
    for (i = 0; i < W * H; i++) {
        double y = Y[i], u = U[i >> 1] - 128.0, v = V[i >> 1] - 128.0;
        int r = rnd255(y + 1.402 * v), gg = rnd255(y - 0.344136 * u - 0.714136 * v), b = rnd255(y + 1.772 * u);
        g[3 * i] = (uint8_t)r; g[3 * i + 1] = (uint8_t)gg; g[3 * i + 2] = (uint8_t)b;
    }
}
static double psnr_mse(double mse) { return mse == 0 ? 99.0 : 10 * log10(255.0 * 255.0 / mse); }
typedef struct { double py, p666, p666c, prgb; int vsrc, vcod, vfmt; } metr;
static void metrics(const uint8_t *src, const uint8_t *rY, const uint8_t *rU, const uint8_t *rV,
                    const uint8_t *tY, const uint8_t *tU, const uint8_t *tV, uint8_t *go, uint8_t *gc, metr *m) {
    double sy = 0, s6 = 0, s6c = 0, srgb = 0; int i, c; m->vsrc = m->vcod = m->vfmt = 0;
    glass(rY, rU, rV, go); glass(tY, tU, tV, gc);
    for (i = 0; i < W * H; i++) { double d = (double)rY[i] - tY[i]; sy += d * d; }
    for (i = 0; i < W * H; i++) {
        int ms = 0, mc = 0, mf = 0;
        for (c = 0; c < 3; c++) {
            int o = q666(go[3 * i + c]), s = q666(src[3 * i + c]), t = q666(gc[3 * i + c]);
            int d1 = o - s, d2 = o - t, d3 = t - s, d4 = go[3 * i + c] - src[3 * i + c];
            s6 += d1 * d1; s6c += d2 * d2; srgb += d4 * d4;
            d1 = abs(d1); d2 = abs(d2); d3 = abs(d3);
            if (d1 > ms) ms = d1; if (d2 > mc) mc = d2; if (d3 > mf) mf = d3;
        }
        m->vsrc += ms >= 8; m->vcod += mc >= 8; m->vfmt += mf >= 8;
    }
    m->py = psnr_mse(sy / (W * H)); m->p666 = psnr_mse(s6 / (3.0 * W * H)); m->p666c = psnr_mse(s6c / (3.0 * W * H)); m->prgb = psnr_mse(srgb / (3.0 * W * H));
}

/* --ghost: stale-content metric on the 100x60 8x8 block grid, luma.
 *   err block: RMS(recon - target) >= GH_RMS (6 of 255, about 1.5 LSB of the 6-bit panel), counted at any cause (blur or stale).
 *   ghost block: err block whose recon is clearly closer (< half the SSE) to one of the block's last GH_OLD distinct source contents than to the
 *     current one, i.e. it still shows old picture rather than a blurred new one.
 *   age: consecutive frames a block has been an err block; settle: frames from the last source change until err blocks < GH_SETTLE, for large events. */
#define GH_RMS 6
#define GH_OLD 4
#define GH_SETTLE 30
#define GH_Q 16
typedef struct {
    uint8_t (*old)[GH_OLD][64], *nold; uint8_t (*cur)[64]; uint16_t *age; int started; FILE *f;
    double s_err, s_ghost, a3, a6, a12, a30; int max_err, max_ghost, max_age;
    int since, peak, settled, ev, setmax; double setsum; int chg_peak; int settled3, ev3, set3max; double set3sum;
    /* glass-time view: the frame on the panel at tick i is the newest one whose last byte has crossed the link (4.4e6/60 B per tick) by then */
    uint8_t *rq[GH_Q]; int fq[GH_Q]; double q, s_gerr, s_gghost; int gmax_err, gmax_ghost, shown;
} ghost_t;
static void ghost_init(ghost_t *g, const char *path) {
    memset(g, 0, sizeof *g);
    g->old = malloc(6000 * GH_OLD * 64); g->nold = calloc(6000, 1); g->cur = malloc(6000 * 64); g->age = calloc(6000, 2);
    if (path && strcmp(path, "-")) g->f = fopen(path, "w");
    { int i; for (i = 0; i < GH_Q; i++) { g->rq[i] = malloc(800 * 480); g->fq[i] = -1; } }
    if (g->f) fprintf(g->f, "# i nchg nerr nghost age3 age12 since gerr gghost\n");
}
static inline uint32_t sse64(const uint8_t *a, const uint8_t *b) { uint32_t s = 0; int i; for (i = 0; i < 64; i++) { int d = (int)a[i] - b[i]; s += (uint32_t)(d * d); } return s; }
static void ghost_frame(ghost_t *g, int fn, const uint8_t *rY, const uint8_t *tY, size_t bytes) {
    int by, bx, r, nchg = 0, nerr = 0, ngh = 0, a3 = 0, a12 = 0, n3 = 0;
    for (by = 0; by < 60; by++) for (bx = 0; bx < 100; bx++) {
        int b = by * 100 + bx, k; uint8_t T[64], R[64]; uint32_t e;
        for (r = 0; r < 8; r++) { memcpy(T + 8 * r, tY + (by * 8 + r) * 800 + bx * 8, 8); memcpy(R + 8 * r, rY + (by * 8 + r) * 800 + bx * 8, 8); }
        if (g->started && memcmp(T, g->cur[b], 64)) {
            nchg++;
            if (sse64(T, g->cur[b]) >= 64 * 4) { /* a real content change, not a re-quantised target */
                memmove(g->old[b][1], g->old[b][0], 64 * (GH_OLD - 1)); memcpy(g->old[b][0], g->cur[b], 64); if (g->nold[b] < GH_OLD) g->nold[b]++;
            }
        }
        memcpy(g->cur[b], T, 64);
        e = sse64(R, T);
        if (e >= 3 * 3 * 64) n3++;
        if (e >= GH_RMS * GH_RMS * 64) {
            int isg = 0;
            nerr++;
            for (k = 0; k < g->nold[b] && !isg; k++) isg = 2 * sse64(R, g->old[b][k]) < e;
            ngh += isg;
            if (g->age[b] < 65535) g->age[b]++;
            if (g->age[b] > g->max_age) g->max_age = g->age[b];
            if (g->age[b] >= 3) { a3++; g->a3++; }
            if (g->age[b] >= 6) g->a6++;
            if (g->age[b] >= 12) { a12++; g->a12++; }
            if (g->age[b] >= 30) g->a30++;
        } else g->age[b] = 0;
    }
    { /* glass time */
        int slot = fn % GH_Q, k, best = -1, gerr = 0, gg = 0; const double R = 4.4e6 / 60;
        g->q += (double)bytes; memcpy(g->rq[slot], rY, 800 * 480); g->fq[slot] = fn + (int)((g->q - 1) / R); g->q -= R; if (g->q < 0) g->q = 0;
        for (k = 0; k < GH_Q; k++) { int j = fn - k; if (j < 0) break; if (g->fq[j % GH_Q] >= 0 && g->fq[j % GH_Q] <= fn) { best = j % GH_Q; break; } }
        if (best >= 0) for (by = 0; by < 60; by++) for (bx = 0; bx < 100; bx++) {
            int b = by * 100 + bx; uint8_t T[64], R8[64]; uint32_t e; const uint8_t *sh = g->rq[best];
            for (r = 0; r < 8; r++) { memcpy(T + 8 * r, tY + (by * 8 + r) * 800 + bx * 8, 8); memcpy(R8 + 8 * r, sh + (by * 8 + r) * 800 + bx * 8, 8); }
            e = sse64(R8, T);
            if (e >= GH_RMS * GH_RMS * 64) { int isg = 0; gerr++; for (k = 0; k < g->nold[b] && !isg; k++) isg = 2 * sse64(R8, g->old[b][k]) < e; gg += isg; }
        }
        g->s_gerr += gerr; g->s_gghost += gg; if (gerr > g->gmax_err) g->gmax_err = gerr; if (gg > g->gmax_ghost) g->gmax_ghost = gg;
        g->shown = gerr * 65536 + gg;
    }
    g->started = 1;
    g->s_err += nerr; g->s_ghost += ngh;
    if (nerr > g->max_err) g->max_err = nerr;
    if (ngh > g->max_ghost) g->max_ghost = ngh;
    if (nchg > 0) { if (nchg > g->chg_peak || g->since > 0) g->chg_peak = nchg; g->since = 0; g->settled = 0; } else g->since++;
    if (nchg > 0) g->settled3 = 0;
    if (nchg == 0 && !g->settled3 && g->chg_peak >= 600 && n3 < GH_SETTLE) { g->settled3 = 1; g->ev3++; g->set3sum += g->since; if (g->since > g->set3max) g->set3max = g->since; }
    if (nchg == 0 && !g->settled && g->chg_peak >= 600 && nerr < GH_SETTLE) { g->settled = 1; g->ev++; g->setsum += g->since; if (g->since > g->setmax) g->setmax = g->since; }
    if (g->f) fprintf(g->f, "%d %d %d %d %d %d %d %d %d\n", fn, nchg, nerr, ngh, a3, a12, g->since, g->shown >> 16, g->shown & 65535);
}
static void ghost_summary(ghost_t *g, int fn) {
    fprintf(stderr, "GHOST frames %d err_mean %.1f err_max %d ghost_mean %.2f ghost_max %d | blockframes age>=3 %.0f >=6 %.0f >=12 %.0f >=30 %.0f max_age %d | settle events %d mean %.1f max %d | settle3 %d mean %.1f max %d | glass err %.1f/%d ghost %.1f/%d\n",
            fn, g->s_err / fn, g->max_err, g->s_ghost / fn, g->max_ghost, g->a3, g->a6, g->a12, g->a30, g->max_age, g->ev, g->ev ? g->setsum / g->ev : 0.0, g->setmax, g->ev3, g->ev3 ? g->set3sum / g->ev3 : 0.0, g->set3max, g->s_gerr / fn, g->gmax_err, g->s_gghost / fn, g->gmax_ghost);
    if (g->f) fclose(g->f);
}

static int parse_damage(char *line, rnv2_rect *r, int max) {
    int n = 0; char *p = line;
    while (*p == ' ' || *p == '\t') p++;
    if (*p == '*') return -1;
    while (*p && n < max) {
        int x, y, w, h, k;
        if (sscanf(p, "%d,%d,%d,%d%n", &x, &y, &w, &h, &k) != 4) break;
        r[n].x = x; r[n].y = y; r[n].w = w; r[n].h = h; n++; p += k;
        while (*p == ' ' || *p == '\t') p++;
    }
    return n;
}
/* bounding box of changed pixels vs the previous frame (simulates compositor damage for tests).  First and last changed rows by whole-row
 * compares from each end; between them only the columns still outside the box are looked at, so the cost falls as the box grows. */
static int first_diff(const uint8_t *a, const uint8_t *b, int n, int bpp) { /* first differing pixel of n, or n */
    size_t i = 0, N = (size_t)n * bpp; int x;
    while (i + 8 <= N) { uint64_t p, q; memcpy(&p, a + i, 8); memcpy(&q, b + i, 8); if (p != q) break; i += 8; }
    for (x = (int)(i / bpp); x < n; x++) if (memcmp(a + x * bpp, b + x * bpp, bpp)) return x;
    return n;
}
static int auto_damage(const uint8_t *cur, const uint8_t *prev, int stride, int bpp, rnv2_rect *r) {
    int y, x0 = W, x1 = -1, y0 = 0, y1 = H - 1; size_t rb = (size_t)W * bpp;
    if (!prev) return -1;
    while (y0 < H && !memcmp(cur + (size_t)y0 * stride, prev + (size_t)y0 * stride, rb)) y0++;
    if (y0 == H) return 0;
    while (y1 > y0 && !memcmp(cur + (size_t)y1 * stride, prev + (size_t)y1 * stride, rb)) y1--;
    for (y = y0; y <= y1 && (x0 > 0 || x1 < W - 1); y++) {
        const uint8_t *a = cur + (size_t)y * stride, *b = prev + (size_t)y * stride; int x;
        if (x0 > 0 && memcmp(a, b, (size_t)x0 * bpp)) x0 = first_diff(a, b, x0, bpp);
        if (x1 < W - 1 && memcmp(a + (size_t)(x1 + 1) * bpp, b + (size_t)(x1 + 1) * bpp, (size_t)(W - 1 - x1) * bpp)) {
            for (x = W - 1; x > x1; x--) if (memcmp(a + x * bpp, b + x * bpp, bpp)) { x1 = x; break; }
        }
    }
    r->x = x0; r->y = y0; r->w = x1 - x0 + 1; r->h = y1 - y0 + 1;
    return 1;
}

/* link-capacity control channel: lines "<bytes_per_s>" or "cap <bytes_per_s>" ('#' comments), last complete line wins,
 * polled once per frame.  FIFO / pipe fd / appended-to file; a file that shrinks is re-read from the start. */
typedef struct { int fd; off_t off; char buf[256]; int n; int key; } linkctl_t;
static double linkctl_poll(linkctl_t *c) {
    double v = 0; char tmp[512]; ssize_t r; struct stat st;
    if (c->fd < 0) return 0;
    if (fstat(c->fd, &st) == 0 && S_ISREG(st.st_mode)) {
        if (st.st_size < c->off) { lseek(c->fd, 0, SEEK_SET); c->off = 0; c->n = 0; }
    }
    while ((r = read(c->fd, tmp, sizeof tmp)) > 0) {
        ssize_t i; c->off += r;
        for (i = 0; i < r; i++) {
            if (tmp[i] == '\n') {
                char *p = c->buf, *e2; double x; c->buf[c->n] = 0; c->n = 0;
                while (*p == ' ' || *p == '\t') p++;
                if (!strncmp(p, "key", 3)) { c->key = 1; continue; }   /* link lost video: next frame is a key */
                if (!strncmp(p, "cap", 3)) p += 3;
                x = strtod(p, &e2);
                if (e2 != p && x > 0) v = x;
            } else if (c->n < (int)sizeof c->buf - 1) c->buf[c->n++] = tmp[i];
        }
    }
    return v;
}

static void usage(void) {
    fprintf(stderr, "usage: rnv2enc -i in.raw|- -o out.rnv [options]  (see the top of src/main.c or README.txt)\n");
    exit(2);
}

int main(int argc, char **argv) {
    int keydefer = 180; size_t lastbytes = 0;
    int keyint = 0, iskey = 0;   /* --keyint N: key frame every N frames; top bit of the .rnv length marks it */
    rnv2enc_params p; const char *in = NULL, *outp = NULL, *recp = NULL, *tgtp = NULL, *crcp = NULL, *statp = NULL, *dmgp = NULL;
    enum rnv2_fmt fmt = RNV2_RGB24; int stride = 0, nmax = 0, i, bench = 0, quiet = 0, domet = 0, autod = 0, skipn = 0;
    FILE *fi, *fo = NULL, *fr = NULL, *ft = NULL, *fc = NULL, *fs = NULL, *fd = NULL;
    uint8_t *frame, *prevframe = NULL, *yuy, *rgb, *go, *gc, **all = NULL; size_t fsz; int nall = 0, fn;
    double ttot = 0, tmax = 0, tph[8] = {0}; long long tbytes = 0; double *bytes_hist = NULL; int nh = 0, cap_h = 0;
    double s_p666 = 0, s_p666c = 0, s_py = 0, s_vs = 0, s_vc = 0, s_vf = 0, min_p666c = 99, min_py = 99, cycmax = 0;
    rnv2enc *e; linkctl_t lc = {-1, 0, {0}, 0, 0}; const char *ghostp = NULL; ghost_t gh;
    struct timespec cpu0, cpu1; double tdmg = 0;
    int refill = 0, srcticks = 1; double simsf = 0, sim_t = 0, sim_free = 0, sim_fin[4096], sim_b[4096], tw = 0; int sim_h = 0, sim_n = 0; /* --refill */
    rnv2enc_default_params(&p);
    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
#define ARG (++i < argc ? argv[i] : (usage(), ""))
        if (!strcmp(a, "-i")) in = ARG;
        else if (!strcmp(a, "-o")) outp = ARG;
        else if (!strcmp(a, "--fmt")) { const char *f = ARG; fmt = !strcmp(f, "rgb24") ? RNV2_RGB24 : !strcmp(f, "bgr24") ? RNV2_BGR24 : (!strcmp(f, "bgr0") || !strcmp(f, "bgrx") || !strcmp(f, "xrgb8888")) ? RNV2_BGR0 : (!strcmp(f, "rgb0") || !strcmp(f, "rgbx") || !strcmp(f, "xbgr8888")) ? RNV2_RGB0 : (usage(), RNV2_RGB24); }
        else if (!strcmp(a, "--stride")) stride = atoi(ARG);
        else if (!strcmp(a, "-n")) nmax = atoi(ARG);
        else if (!strcmp(a, "--skip")) skipn = atoi(ARG);
        else if (!strcmp(a, "--threads")) p.threads = atoi(ARG);
        else if (!strcmp(a, "--keyint")) keyint = atoi(ARG);
        else if (!strcmp(a, "--keydefer")) keydefer = atoi(ARG);
        else if (!strcmp(a, "--qpmin")) p.qp_min = atoi(ARG);
        else if (!strcmp(a, "--lamk")) p.lam_k = atof(ARG);
        else if (!strcmp(a, "--kappa")) p.kappa = atof(ARG);
        else if (!strcmp(a, "--thr")) p.thr = atof(ARG);
        else if (!strcmp(a, "--rate")) p.rate = atof(ARG);
        else if (!strcmp(a, "--linkcap")) p.link_cap = atof(ARG);
        else if (!strcmp(a, "--linkctl")) { const char *f = ARG; lc.fd = open(f, O_RDONLY | O_NONBLOCK); if (lc.fd < 0) { perror(f); return 1; } }
        else if (!strcmp(a, "--linkfd")) lc.fd = atoi(ARG);
        else if (!strcmp(a, "--fixedq")) p.adapt = 0;
        else if (!strcmp(a, "--levels")) p.nlevels = atoi(ARG);
        else if (!strcmp(a, "--lamlo")) p.lam_lo = atof(ARG);
        else if (!strcmp(a, "--lamx")) p.lam_x = atof(ARG);
        else if (!strcmp(a, "--kappalo")) p.kappa_lo = atof(ARG);
        else if (!strcmp(a, "--thrlo")) p.thr_lo = atof(ARG);
        else if (!strcmp(a, "--filltarget")) p.fill_target = atof(ARG);
        else if (!strcmp(a, "--pinlevel")) p.pin_level = atoi(ARG);
        else if (!strcmp(a, "--dwell")) p.dwell = atoi(ARG);
        else if (!strcmp(a, "--hyst")) p.hyst = atof(ARG);
        else if (!strcmp(a, "--cyc")) p.cyc_budget = atof(ARG);
        else if (!strcmp(a, "--buf")) p.buf_frames = atof(ARG);
        else if (!strcmp(a, "--maxtries")) p.max_tries = atoi(ARG);
        else if (!strcmp(a, "--me")) p.me_level = atoi(ARG);
        else if (!strcmp(a, "--mewin")) p.me_win_thr = atoi(ARG);
        else if (!strcmp(a, "--mewinmax")) p.me_win_max = atoi(ARG);
        else if (!strcmp(a, "--noraw")) p.use_raw = 0;
        else if (!strcmp(a, "--prune")) p.prune = atoi(ARG);
        else if (!strcmp(a, "--qppred")) p.qp_pred = atoi(ARG);
        else if (!strcmp(a, "--rtrc")) p.rt_rc = atoi(ARG);
        else if (!strcmp(a, "--exact")) { p.rt_rc = 0; p.me_level = 3; p.me_win_max = 1 << 30; } /* rnv2.py parity preset */
        else if (!strcmp(a, "--refine")) p.refine_static = atoi(ARG);
        else if (!strcmp(a, "--mask")) { if (!atoi(ARG)) { p.refine_static = 0; p.max_frame = 0; p.stale_d = p.stale_w = 0; p.burst_probe = 0; p.mu_relax = 0; p.qp_drop = 2; p.fast_refine = 0; keydefer = 0; } } /* --mask 0: the old rate control, bit for bit */
        else if (!strcmp(a, "--lagtarget")) p.lag_target = atof(ARG);
        else if (!strcmp(a, "--maxframe")) p.max_frame = atof(ARG);
        else if (!strcmp(a, "--staled")) p.stale_d = atof(ARG);
        else if (!strcmp(a, "--stalew")) p.stale_w = atof(ARG);
        else if (!strcmp(a, "--burstprobe")) p.burst_probe = atoi(ARG);
        else if (!strcmp(a, "--murelax")) p.mu_relax = atoi(ARG);
        else if (!strcmp(a, "--qpdrop")) p.qp_drop = atoi(ARG);
        else if (!strcmp(a, "--fastrefine")) p.fast_refine = atoi(ARG);
        else if (!strcmp(a, "--sfbudget")) p.sf_budget = atof(ARG);
        else if (!strcmp(a, "--r3")) p.r3 = atoi(ARG);
        else if (!strcmp(a, "--fill")) p.fill_gap = atoi(ARG);
        else if (!strcmp(a, "--rctol")) p.rc_tol = atof(ARG);
        else if (!strcmp(a, "--btclmin")) p.btc_lmin = atof(ARG);
        else if (!strcmp(a, "--prunen")) p.prune_nact = atoi(ARG);
        else if (!strcmp(a, "--pruner")) p.prune_r = atof(ARG);
        else if (!strcmp(a, "--forcemode")) p.force_mode = atoi(ARG);
        else if (!strcmp(a, "--btcgate")) p.btc_gate = atoi(ARG);
        else if (!strcmp(a, "--pwmax")) p.pw_max = atof(ARG);
        else if (!strcmp(a, "--srcmean")) p.src_mean = atoi(ARG);
        else if (!strcmp(a, "--smooth")) p.smooth = atoi(ARG);
        else if (!strcmp(a, "--tonepal")) p.tone_pal = atoi(ARG);
        else if (!strcmp(a, "--fillpen")) p.fill_pen = atof(ARG);
        else if (!strcmp(a, "--nurelax")) p.nu_relax = atof(ARG);
        else if (!strcmp(a, "--nurelaxthr")) p.nu_relax_thr = atof(ARG);
        else if (!strcmp(a, "--nurelaxn")) p.nu_relax_n = atoi(ARG);
        else if (!strcmp(a, "--srcdead")) p.src_dead = atoi(ARG);
        else if (!strcmp(a, "--glassdead")) p.glass_dead = atoi(ARG);
        else if (!strcmp(a, "--latq")) { const char *f = ARG; sscanf(f, "%d,%d,%d,%d", &p.lat_q4, &p.lat_q2a, &p.lat_q2b, &p.lat_q4c); }
        else if (!strcmp(a, "--latsharp")) p.lat_sharp = atoi(ARG);
        else if (!strcmp(a, "--lmin")) p.rc_lmin = atof(ARG);
        else if (!strcmp(a, "--maxvid")) p.sf_budget = atof(ARG) * 512;   /* same value as avlink --maxvid */
        else if (!strcmp(a, "--trimratio")) p.trim_ratio = atof(ARG);
        else if (!strcmp(a, "--trimmax")) p.trim_max = atof(ARG);
        else if (!strcmp(a, "--spillqp")) p.spill_qp = atoi(ARG);
        else if (!strcmp(a, "--spillsf")) p.spill_sf = atoi(ARG);
        else if (!strcmp(a, "--spillgap")) p.spill_gap = atoi(ARG);
        else if (!strcmp(a, "--spillcarry")) p.spill_carry = atoi(ARG);
        else if (!strcmp(a, "--spillcyc")) p.spill_cyc = atof(ARG);
        else if (!strcmp(a, "--refill")) { const char *f = ARG; refill = !strcmp(f, "wall") ? 1 : !strcmp(f, "sim") ? 2 : !strcmp(f, "frame") ? 0 : (usage(), 0); } /* frame: one 1/fps per frame (old).  wall: the clock.  sim: the link model below, reproducible, for offline runs */
        else if (!strcmp(a, "--srcticks")) srcticks = atoi(ARG);          /* sim: the source offers a frame every N ticks */
        else if (!strcmp(a, "--simsf")) simsf = atof(ARG);                /* sim: bytes per superframe if not --sfbudget */
        else if (!strcmp(a, "--dither")) p.dither = atoi(ARG);
        else if (!strcmp(a, "--ditherrange")) p.dither_range = atoi(ARG);
        else if (!strcmp(a, "--no-static-skip")) p.static_skip = 0;
        else if (!strcmp(a, "--scalar")) p.simd = 0;
        else if (!strcmp(a, "--damage")) dmgp = ARG;
        else if (!strcmp(a, "--auto-damage")) autod = 1;
        else if (!strcmp(a, "--recon")) recp = ARG;
        else if (!strcmp(a, "--target")) tgtp = ARG;
        else if (!strcmp(a, "--crc")) crcp = ARG;
        else if (!strcmp(a, "--stats")) statp = ARG;
        else if (!strcmp(a, "--metrics")) domet = 1;
        else if (!strcmp(a, "--ghost")) { ghostp = ARG; domet = 1; }
        else if (!strcmp(a, "--bench")) bench = 1;
        else if (!strcmp(a, "-q")) quiet = 1;
        else usage();
    }
    if (!in) usage();
    if (!stride) stride = W * bpp_of(fmt);
    fsz = (size_t)stride * H;
    fi = strcmp(in, "-") ? fopen(in, "rb") : stdin;
    if (!fi) { perror(in); return 1; }
    if (outp && !(fo = strcmp(outp, "-") ? fopen(outp, "wb") : stdout)) { perror(outp); return 1; }
    if (recp) fr = fopen(recp, "wb");
    if (tgtp) ft = fopen(tgtp, "wb");
    if (crcp) fc = fopen(crcp, "w");
    if (statp) fs = fopen(statp, "w");
    if (dmgp && !(fd = fopen(dmgp, "r"))) { perror(dmgp); return 1; }
    frame = malloc(fsz); yuy = malloc(W * H * 2); rgb = malloc(W * H * 3); go = malloc(W * H * 3); gc = malloc(W * H * 3);
    if (autod) prevframe = malloc(fsz);
    for (i = 0; i < skipn; i++) if (fread(frame, 1, fsz, fi) != fsz) break;
    if (bench) {
        int capa = 64;
        all = malloc(sizeof *all * capa);
        for (;;) {
            if (nmax && nall >= nmax) break;
            if (nall == capa) { capa *= 2; all = realloc(all, sizeof *all * capa); }
            all[nall] = malloc(fsz);
            if (fread(all[nall], 1, fsz, fi) != fsz) { free(all[nall]); break; }
            nall++;
        }
        if (!quiet) fprintf(stderr, "bench: %d frames in RAM\n", nall);
    }
    if (ghostp) ghost_init(&gh, ghostp);
    e = rnv2enc_create(&p);
    if (!quiet) fprintf(stderr, "rnv2enc: kernels %s, %d thread(s)\n", rnv2enc_kernel_name(e), p.threads);
    if (fs) fprintf(fs, "# i bytes qp tries cycles mu fill searched forced  SKIP MC MCR ZRES INTRA RAW  psnr_y psnr_666 psnr_666c psnr_rgb vis_src vis_cod vis_fmt  t_csc t_gme t_me t_ana t_dec t_- t_commit t_total  ngmv  level  linkcap  spill trims\n");
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu0);
    for (fn = 0;; fn++) {
        const uint8_t *out; size_t olen; rnv2enc_info inf; rnv2_rect dr[64]; int nd = -1; double t0, t1, td0, td1; uint8_t *cur;
        if (nmax && fn >= nmax) break;
        if (bench) { if (fn >= nall) break; cur = all[fn]; }
        else { if (fread(frame, 1, fsz, fi) != fsz) break; cur = frame; }
        if (refill == 1) { double tn = now_ms(); if (fn) rnv2enc_set_elapsed(e, (tn - tw) / 1000.0); tw = tn; } /* taken after the read returned: frame arrival, not encoder speed */
        td0 = now_ms();
        if (fd) { char line[8192]; if (fgets(line, sizeof line, fd)) nd = parse_damage(line, dr, 64); }
        else if (autod) { nd = auto_damage(cur, fn ? prevframe : NULL, stride, bpp_of(fmt), dr); }
        td1 = now_ms() - td0;
        { double cv = linkctl_poll(&lc); if (cv > 0) rnv2enc_set_linkcap(e, cv); }
        { /* keyint: frames from a file; real time (keyint/60 s) from a pipe, where a still screen delivers few frames and a key must still come */
            static int since = 0; static double tk = 0; double tn = now_ms(); int live = !strcmp(in, "-"), due; static int deferred = 0;
            if (!tk) tk = tn;
            due = keyint > 0 && (live ? tn - tk >= keyint * 1000.0 / 60 : since >= keyint - 1);
            /* a periodic key is a 250 KB burst: on a still or quiet screen nobody sees it, in motion it starves the frames after it.  Wait for a quiet frame, within limits; a key the link asked for goes at once */
            if (due && !lc.key && keydefer > 0 && lastbytes > 20000 && deferred < keydefer) { due = 0; deferred++; } else if (due) deferred = 0;
            iskey = fn > 0 && (due || lc.key); lc.key = 0;
            if (iskey) { since = 0; tk = tn; } else since++;
        }
        if (iskey) rnv2enc_force_key(e);
        t0 = now_ms();
        rnv2enc_encode(e, cur, stride, fmt, dr, nd, &out, &olen, &inf);
        t1 = now_ms();
        tdmg += td1;   /* damage scan (outside t_total); stats column t_- = decide passes + 100 x analysis passes this frame */
        ttot += t1 - t0; if (t1 - t0 > tmax) tmax = t1 - t0;
        for (i = 0; i < 8; i++) tph[i] += inf.t_ms[i];
        if (refill == 2) { /* the link as avlink runs it: one fragment per tick; the encoder blocks once VSRC_HIGH + a pipe of bytes wait.  Same model as budget/link_model.py */
            double B = simsf > 0 ? simsf : p.sf_budget, t1s, q = 0; int k, fr = B > 0 ? (int)ceil((double)olen / B) : 1; if (fr < 1) fr = 1;
            if (sim_free < sim_t) sim_free = sim_t;
            sim_free += fr; sim_fin[(sim_h + sim_n) % 4096] = sim_free; sim_b[(sim_h + sim_n) % 4096] = (double)olen; if (sim_n < 4095) sim_n++; else sim_h = (sim_h + 1) % 4096;
            t1s = sim_t + srcticks;
            for (;;) {
                while (sim_n && sim_fin[sim_h] <= t1s) { sim_h = (sim_h + 1) % 4096; sim_n--; }
                for (q = 0, k = 0; k < sim_n; k++) q += sim_b[(sim_h + k) % 4096];
                if (q <= (256 << 10) + (64 << 10) || !sim_n) break;
                t1s = sim_fin[sim_h];
            }
            rnv2enc_set_elapsed(e, (t1s - sim_t) / p.fps); sim_t = t1s;
        }
        lastbytes = olen; tbytes += (long long)olen; if (inf.cycles > cycmax) cycmax = inf.cycles;
        if (nh == cap_h) { cap_h = cap_h ? cap_h * 2 : 1024; bytes_hist = realloc(bytes_hist, sizeof(double) * cap_h); }
        bytes_hist[nh++] = (double)olen;
        if (fo) { uint8_t h4[4] = {(uint8_t)((olen >> 24) | (iskey ? 0x80 : 0)), (uint8_t)(olen >> 16), (uint8_t)(olen >> 8), (uint8_t)olen}; fwrite(h4, 1, 4, fo); fwrite(out, 1, olen, fo); fflush(fo); }
        if (fr || fc) { rnv2enc_recon_yuy2(e, yuy); if (fr) fwrite(yuy, 1, W * H * 2, fr); if (fc) fprintf(fc, "%d %u\n", fn, crc32b(yuy, W * H * 2)); }
        if (ft) { rnv2enc_target_yuy2(e, yuy); fwrite(yuy, 1, W * H * 2, ft); }
        {
            metr m = {0, 0, 0, 0, 0, 0, 0};
            if (domet) {
                const uint8_t *rY, *rU, *rV, *tY, *tU, *tV;
                rnv2enc_planes(e, &rY, &rU, &rV, &tY, &tU, &tV);
                to_rgb(cur, fmt, stride, rgb);
                metrics(rgb, rY, rU, rV, tY, tU, tV, go, gc, &m);
                if (ghostp) ghost_frame(&gh, fn, rY, tY, olen);
                s_p666 += m.p666; s_p666c += m.p666c; s_py += m.py; s_vs += m.vsrc; s_vc += m.vcod; s_vf += m.vfmt;
                if (m.p666c < min_p666c) min_p666c = m.p666c; if (m.py < min_py) min_py = m.py;
            }
            if (fs) fprintf(fs, "%d %d %d %d %.0f %.4f %.0f %d %d  %d %d %d %d %d %d  %.3f %.3f %.3f %.3f %d %d %d  %.3f %.3f %.3f %.3f %.3f %.3f %.3f %.3f  %d  %d  %.0f  %d %d  %d %d %d %d %d  %.4f\n",
                            fn, inf.bytes, inf.qp, inf.tries, inf.cycles, inf.mu, inf.fill, inf.n_searched, inf.n_skip_forced,
                            inf.modes[0], inf.modes[1], inf.modes[2], inf.modes[3], inf.modes[4], inf.modes[5],
                            m.py, m.p666, m.p666c, m.prgb, m.vsrc, m.vcod, m.vfmt,
                            inf.t_ms[0], inf.t_ms[1], inf.t_ms[2], inf.t_ms[3], inf.t_ms[4], inf.t_ms[5], inf.t_ms[6], t1 - t0, inf.gmv_n, inf.level, inf.link_cap, inf.spill, inf.trims, inf.modes[6], inf.modes[7], inf.modes[8], inf.modes[9], inf.modes[10], inf.lamk);
        }
        if (autod) { /* this frame becomes the previous one without a copy */
            if (bench) prevframe = cur;
            else { uint8_t *sw = frame; frame = prevframe; prevframe = sw; }
        }
        if (!quiet && fn % 60 == 0) fprintf(stderr, "frame %d: %zu B qp %d tries %d %.2f Mcyc %.2f ms\n", fn, olen, inf.qp, inf.tries, inf.cycles / 1e6, t1 - t0);
    }
    if (fn && ghostp) ghost_summary(&gh, fn);
    if (fn) {
        double pk = 0; int k;
        if (nh >= 60) { double s = 0; for (k = 0; k < nh; k++) { s += bytes_hist[k]; if (k >= 60) s -= bytes_hist[k - 60]; if (k >= 59 && s > pk) pk = s; } }
        fprintf(stderr, "SUMMARY frames %d MBps %.3f peak1s %.3f maxcyc %.0f | enc ms mean %.3f max %.3f fps %.1f | phases ms csc %.3f gme %.3f me %.3f ana %.3f dec %.3f commit+write %.3f",
                fn, tbytes * p.fps / fn / 1e6, pk / 1e6, cycmax, ttot / fn, tmax, 1000.0 * fn / ttot,
                tph[0] / fn, tph[1] / fn, tph[2] / fn, tph[3] / fn, tph[4] / fn, tph[6] / fn);
        if (domet) fprintf(stderr, " | psnr_y %.2f (min %.2f) 666src %.2f 666ceil %.2f (min %.2f) vis src %.0f codec %.1f fmt %.0f",
                           s_py / fn, min_py, s_p666 / fn, s_p666c / fn, min_p666c, s_vs / fn, s_vc / fn, s_vf / fn);
        clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu1);
        { double c = (cpu1.tv_sec - cpu0.tv_sec) * 1e3 + (cpu1.tv_nsec - cpu0.tv_nsec) * 1e-6; fprintf(stderr, " | dmg ms %.3f | cpu ms/frame %.3f (%.1f%% of a core at 60 fps)", tdmg / fn, c / fn, c / fn * 6.0); }
        fprintf(stderr, "\n");
    }
#ifdef RNV_COUNT
    { extern long long rnv_cnt[8]; int k; fprintf(stderr, "KCOUNT per frame: csc_pairs sad pd8 fwd8 iwht addclamp halfpel_px proj_px:"); for (k = 0; k < 8; k++) fprintf(stderr, " %.0f", (double)rnv_cnt[k] / (fn ? fn : 1)); fputc(10, stderr); }
#endif
    rnv2enc_destroy(e);
    if (fo) fclose(fo); if (fr) fclose(fr); if (ft) fclose(ft); if (fc) fclose(fc); if (fs) fclose(fs);
    return 0;
}
