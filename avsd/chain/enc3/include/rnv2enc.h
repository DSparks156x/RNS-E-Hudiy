/* rnv2enc - real-time RNV2 encoder (C11).  Bitstream = video/rnv2.py format, decodable by video/dec/rnv2dec.c.
 * One frame in (800x480 RGB), one RNV2 frame out (without the 4-byte big-endian length prefix of the .rnv
 * container; the CLI adds it).  The encoder's reconstruction equals the decoder output bit for bit. */
#ifndef RNV2ENC_H
#define RNV2ENC_H
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

#define RNV2_W 800
#define RNV2_H 480

enum rnv2_fmt {          /* memory byte order per pixel (ffmpeg pix_fmt names) */
    RNV2_RGB24 = 0,      /* R G B        */
    RNV2_BGR24,          /* B G R        */
    RNV2_BGR0,           /* B G R X  = DRM/wlroots XRGB8888 on little-endian */
    RNV2_RGB0            /* R G B X  = DRM XBGR8888 */
};

typedef struct { int x, y, w, h; } rnv2_rect;

typedef struct {
    int qp_min, qp_max;        /* 0, 51 */
    double rate;               /* leaky bucket channel rate, bytes/s (8e6) */
    double buf_frames;         /* bucket size in frames of channel rate (4) */
    double fps;                /* 60 */
    double cyc_budget;         /* SH-4A decode cycle cap per frame (4.49e6 = 7.5 ms) */
    double lam_k;              /* 0.04 */
    double kappa, thr;         /* perceptual penalty 4, 3 (thr is rounded to an integer) */
    double dz_inter, dz_intra; /* 0.22, 0.33 */
    double mu_min, mu_max;     /* 0.002, 2.0 */
    int use_raw;               /* 1 */
    int max_tries;             /* rate/cycle control re-decisions per frame (12 = rnv2.py) */
    int threads;               /* worker threads incl. the caller (1..16) */
    int static_skip;           /* 1: unchanged source + previous SKIP -> SKIP without evaluation */
    int simd;                  /* 1: NEON kernels when compiled in, 0: scalar reference */
    int me_level;              /* 0 one Jacobi pass, 1 two passes, 2 (default) + sparse 2/3-px rings, 3 + full 7x7 window */
    int me_win_thr;            /* level 2: window only when the best SAD cost so far exceeds this (default 0 = always) */
    int prune;                 /* analysis: skip a residual candidate whose prediction distortion is > prune x another's (0 = analyse all), on frames with >= 2500 active blocks; default 3 */
    int qp_pred;               /* start from a qp predicted from the last frame / key at the classic point (0 = rnv2.py's start); default 1 */
    int rt_rc;                 /* real-time rate control: 0 = exactly rnv2.py; N (default 1) = at most N qp analysis passes per
                                  frame (then accept within the hard bucket cap, raise qp for the next frame) and hold qp after a raise */
    /* headroom-driven quality (adapt = 1, default): the operating point (lam_k, kappa, thr) walks a ladder of nlevels steps from
       (lam_x, kappa_lo, thr_lo) = near-exact up to the classic (lam_k, kappa, thr).  Level 0 whenever the link has headroom;
       each frame takes the finest level whose size fits the bucket allowance (only the cheap mode decision is redone per
       candidate), at most one level finer per frame, coarser at once; qp / mu as before when even the classic point does not fit.  adapt = 0: fixed (lam_k, kappa, thr). */
    double link_cap;           /* link capacity, bytes/s; > 0 replaces rate (also settable live: rnv2enc_set_linkcap) */
    int adapt, nlevels;        /* 1, 12 */
    double lam_lo;             /* 0.0025: finest lambda of the smooth part of the ladder (levels 1..nlevels-2, thr / kappa as classic) */
    double lam_x, kappa_lo, thr_lo; /* level 0 = near-exact point: 0.01, 16, 0 */
    double fill_target;        /* level choice keeps the bucket near this fill fraction (0.25), the rest is burst reserve */
    int dwell;                 /* frames a level must have been held before the next finer step (coarser steps are immediate) (4) */
    double hyst;               /* a level finer than the previous frame's must fit within this fraction of the allowance (0.85) */
    int pin_level;             /* >= 0: hold this ladder level, no level control (evaluation); -1 = controlled (default) */
    int me_win_max;            /* ... and is below this (no match nearby: cut / new content; window would not help; default 1024) */
    /* anti-ghost rate control (0 = off, each usable alone; none changes the format).  See README.txt "MASKING". */
    int refine_static;         /* 1: blocks outside the damage are still refined until they reach the current quality point.  0 (old): a coarse block whose source stopped changing stays as it is until the next key */
    double lag_target;         /* with max_frame: bucket fill the qp control steers to under sustained load (fraction of the bucket): lower = less picture lag on the link (0.35) */
    double max_frame;          /* non-key frame size limit, in frames of link rate: a burst leaves as a coarser frame the link can show now, refined by the next frames, not as one huge late frame */
    double stale_d, stale_w;   /* mode decision: J[m] += stale_w * max(0, D[m] - stale_d): picture that is visibly wrong is replaced (coarsely if need be) rather than left stale */
    int burst_probe;           /* 1: on a sudden burst of active blocks estimate the frame size from a row sample first, to pick the first qp */
    int mu_relax;              /* 1: if the frame ended well under the cycle budget at a high mu, retry lower mu values (mu only rose within a frame) */
    int qp_drop;               /* qp fall per frame while frames are well under budget (rnv2.py: 2); after a burst this is how quickly the picture sharpens */
    int fast_refine;           /* 1: level steps finer without dwell while the frame is far below the allowance */
    int dither;                /* 1: static 2x2 ordered dither of the source in smooth gradient blocks, for the 6-bit panel.  Prototype: default off */
    int dither_range;          /* gradient test: max-min per channel within a block and its 4 neighbours at most this (default 24) */
    /* superframe budget (0 = off, the old rate control bit for bit).  See README.txt "SUPERFRAME BUDGET". */
    double rc_tol, btc_lmin; int fill_gap; int prune_nact; double prune_r; int force_mode, smooth, src_mean; double pw_max; int btc_gate; double fill_pen; int r3, src_dead, glass_dead, lat_q4, lat_q2a, lat_q2b, lat_q4c, lat_sharp; double rc_gamma, rc_lmin; /* RNV3 */
    double sf_budget;          /* bytes of video one superframe carries (avlink --maxvid x 512).  Non-key frames are held to this ceiling, or to a whole number of superframes when they spill deliberately */
    double trim_ratio;         /* a frame up to this x the ceiling is cut by re-running the mode decision at a higher lambda, no qp analysis pass (1.35) */
    double trim_max;           /* largest lambda factor of that cut (3): beyond it the picture suffers more than a lost frame */
    int spill_qp;              /* fitting one superframe would need qp >= this: spill instead (default 18; 99 = never) */
    int spill_sf;              /* superframes a deliberate spill takes (2) */
    int spill_gap;             /* frames between deliberate spills (30): each one costs a displayed frame */
    double spill_cyc;          /* x cyc_budget a deliberate spill may use (1: the cap holds on every frame, since one long decode starves the audio) */
    int spill_carry;           /* 1: the excess of a spill stays in the bucket as debt; 0: forgiven (the tick it took is paid in lost frames) */
} rnv2enc_params;

typedef struct {
    int bytes, qp, tries, n_skip_forced, n_searched, level;
    double cycles, mu, fill, link_cap, lamk; /* level: ladder step used (0 = near-exact); link_cap: bucket rate in force */
    int modes[11];
    int sizes[4];
    int gmv_n, gmv[8][2];      /* global motion candidates found (half-pel units) */
    double t_ms[8];            /* phase timings: csc, gme, me, analyse, decide, commit, write, total */
    int spill, trims;          /* sf_budget: 0 fits, 1 deliberate spill or key, 2 missed the ceiling; lambda trim passes */
} rnv2enc_info;

typedef struct rnv2enc rnv2enc;

void rnv2enc_default_params(rnv2enc_params *p);
rnv2enc *rnv2enc_create(const rnv2enc_params *p);
void rnv2enc_destroy(rnv2enc *e);
/* Set the link capacity (bytes/s) from any thread; it takes effect at the start of the next rnv2enc_encode call. */
void rnv2enc_set_linkcap(rnv2enc *e, double bytes_per_s);
/* Time since the previous frame, seconds, for the next encode call.  Without it the bucket drains one 1/fps per frame (old).  Unused time is not banked past an empty bucket; a short interval raises the fill, up to the bucket size. */
void rnv2enc_set_elapsed(rnv2enc *e, double seconds);
/* Encode one frame.  pix: 800x480 in fmt with stride bytes per row.  dmg/ndmg: damage rectangles (speed hint
 * only); ndmg < 0 means "no damage information" (everything is checked).  On return *out points to the frame
 * (valid until the next call).  Returns 0 on success. */
void rnv2enc_force_key(rnv2enc *e);   /* next frame is coded from black */
int rnv2enc_encode(rnv2enc *e, const uint8_t *pix, int stride, enum rnv2_fmt fmt, const rnv2_rect *dmg, int ndmg,
                   const uint8_t **out, size_t *outlen, rnv2enc_info *info);
/* reconstruction (= decoder output) and the encoder's YUY2 target, packed YUY2 (Y0 Cb Y1 Cr), 800*480*2 bytes */
void rnv2enc_recon_yuy2(const rnv2enc *e, uint8_t *dst);
void rnv2enc_target_yuy2(const rnv2enc *e, uint8_t *dst);
/* planar access for metrics: Y 800x480, U/V 400x480 */
void rnv2enc_planes(const rnv2enc *e, const uint8_t **rY, const uint8_t **rU, const uint8_t **rV,
                    const uint8_t **tY, const uint8_t **tU, const uint8_t **tV);
const char *rnv2enc_kernel_name(const rnv2enc *e);

#ifdef __cplusplus
}
#endif
#endif
