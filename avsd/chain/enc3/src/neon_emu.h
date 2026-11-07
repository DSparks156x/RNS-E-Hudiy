/* Minimal portable emulation of the ARM NEON intrinsics used by kern_neon.c, so that the NEON kernel logic can be
 * compiled and checked against the scalar reference on x86 (make emutest).  Semantics follow the ARM ACLE
 * definitions (lane order, saturation, rounding).  Not used on ARM, where <arm_neon.h> is the real thing. */
#ifndef RNV2_NEON_EMU_H
#define RNV2_NEON_EMU_H
#include <stdint.h>
#include <string.h>

#define V(T, N, NAME) typedef struct { T v[N]; } NAME;
V(uint8_t, 8, uint8x8_t) V(uint8_t, 16, uint8x16_t) V(int16_t, 4, int16x4_t) V(int16_t, 8, int16x8_t)
V(uint16_t, 4, uint16x4_t) V(uint16_t, 8, uint16x8_t) V(int32_t, 2, int32x2_t) V(int32_t, 4, int32x4_t)
V(uint32_t, 4, uint32x4_t)
#undef V
typedef struct { int16x8_t val[2]; } int16x8x2_t;
typedef struct { int32x4_t val[2]; } int32x4x2_t;
typedef struct { uint8x16_t val[2]; } uint8x16x2_t;
typedef struct { uint8x16_t val[3]; } uint8x16x3_t;
typedef struct { uint8x8_t val[2]; } uint8x8x2_t;
typedef struct { uint32x4_t val[2]; } uint32x4x2_t;

#define E static inline
#define LOOP(N) for (int i = 0; i < (N); i++)
E uint8x8_t vld1_u8(const uint8_t *p) { uint8x8_t r; memcpy(r.v, p, 8); return r; }
E uint8x16_t vld1q_u8(const uint8_t *p) { uint8x16_t r; memcpy(r.v, p, 16); return r; }
E int32x4_t vld1q_s32(const int32_t *p) { int32x4_t r; memcpy(r.v, p, 16); return r; }
E uint32x4_t vld1q_u32(const uint32_t *p) { uint32x4_t r; memcpy(r.v, p, 16); return r; }
E void vst1q_u8(uint8_t *p, uint8x16_t a) { memcpy(p, a.v, 16); }
E void vst1_u8(uint8_t *p, uint8x8_t a) { memcpy(p, a.v, 8); }
E void vst1_s16(int16_t *p, int16x4_t a) { memcpy(p, a.v, 8); }
E void vst1q_s32(int32_t *p, int32x4_t a) { memcpy(p, a.v, 16); }
E void vst1q_u32(uint32_t *p, uint32x4_t a) { memcpy(p, a.v, 16); }
E void vst2_u8(uint8_t *p, uint8x8x2_t a) { LOOP(8) { p[2 * i] = a.val[0].v[i]; p[2 * i + 1] = a.val[1].v[i]; } }
E uint8x16x3_t vld3q_u8(const uint8_t *p) { uint8x16x3_t r; LOOP(16) { r.val[0].v[i] = p[3 * i]; r.val[1].v[i] = p[3 * i + 1]; r.val[2].v[i] = p[3 * i + 2]; } return r; }

E uint16x8_t vabdl_u8(uint8x8_t a, uint8x8_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] > b.v[i] ? a.v[i] - b.v[i] : b.v[i] - a.v[i]); return r; }
E uint16x8_t vabal_u8(uint16x8_t c, uint8x8_t a, uint8x8_t b) { uint16x8_t d = vabdl_u8(a, b); LOOP(8) c.v[i] = (uint16_t)(c.v[i] + d.v[i]); return c; }
E uint32_t vaddlvq_u16(uint16x8_t a) { uint32_t s = 0; LOOP(8) s += a.v[i]; return s; }
E uint32_t vaddvq_u32(uint32x4_t a) { uint32_t s = 0; LOOP(4) s += a.v[i]; return s; }
E uint8x16_t vabdq_u8(uint8x16_t a, uint8x16_t b) { uint8x16_t r; LOOP(16) r.v[i] = (uint8_t)(a.v[i] > b.v[i] ? a.v[i] - b.v[i] : b.v[i] - a.v[i]); return r; }
E uint8x8_t vabd_u8(uint8x8_t a, uint8x8_t b) { uint8x8_t r; LOOP(8) r.v[i] = (uint8_t)(a.v[i] > b.v[i] ? a.v[i] - b.v[i] : b.v[i] - a.v[i]); return r; }
E uint16x8_t vmovl_u8(uint8x8_t a) { uint16x8_t r; LOOP(8) r.v[i] = a.v[i]; return r; }
E uint32x4_t vmovl_u16(uint16x4_t a) { uint32x4_t r; LOOP(4) r.v[i] = a.v[i]; return r; }
E int32x4_t vmovl_s16(int16x4_t a) { int32x4_t r; LOOP(4) r.v[i] = a.v[i]; return r; }
#define GETLH(NAME, RT, AT, N) \
    E RT NAME##_low(AT a) { RT r; LOOP(N) r.v[i] = a.v[i]; return r; } \
    E RT NAME##_high(AT a) { RT r; LOOP(N) r.v[i] = a.v[i + N]; return r; }
#define vget_low_u8 vget_u8_low
#define vget_high_u8 vget_u8_high
#define vget_low_u16 vget_u16_low
#define vget_high_u16 vget_u16_high
#define vget_low_s16 vget_s16_low
#define vget_high_s16 vget_s16_high
#define vget_low_s32 vget_s32_low
#define vget_high_s32 vget_s32_high
GETLH(vget_u8, uint8x8_t, uint8x16_t, 8) GETLH(vget_u16, uint16x4_t, uint16x8_t, 4) GETLH(vget_s16, int16x4_t, int16x8_t, 4)
GETLH(vget_s32, int32x2_t, int32x4_t, 2)
#define COMB(NAME, RT, AT, N) E RT NAME(AT a, AT b) { RT r; LOOP(N) { r.v[i] = a.v[i]; r.v[i + N] = b.v[i]; } return r; }
COMB(vcombine_s16, int16x8_t, int16x4_t, 4) COMB(vcombine_s32, int32x4_t, int32x2_t, 2) COMB(vcombine_u8, uint8x16_t, uint8x8_t, 8)
COMB(vcombine_u16, uint16x8_t, uint16x4_t, 4)
E uint16x8_t vdupq_n_u16(uint16_t x) { uint16x8_t r; LOOP(8) r.v[i] = x; return r; }
E int16x8_t vdupq_n_s16(int16_t x) { int16x8_t r; LOOP(8) r.v[i] = x; return r; }
E uint32x4_t vdupq_n_u32(uint32_t x) { uint32x4_t r; LOOP(4) r.v[i] = x; return r; }
E int32x4_t vdupq_n_s32(int32_t x) { int32x4_t r; LOOP(4) r.v[i] = x; return r; }
E uint8x8_t vdup_n_u8(uint8_t x) { uint8x8_t r; LOOP(8) r.v[i] = x; return r; }
E uint16x8_t vqsubq_u16(uint16x8_t a, uint16x8_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] > b.v[i] ? a.v[i] - b.v[i] : 0); return r; }
E uint16x8_t vshlq_n_u16(uint16x8_t a, int n) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] << n); return r; }
E uint16x8_t vmulq_n_u16(uint16x8_t a, uint16_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] * b); return r; }
E uint32x4_t vmull_u16(uint16x4_t a, uint16x4_t b) { uint32x4_t r; LOOP(4) r.v[i] = (uint32_t)a.v[i] * b.v[i]; return r; }
E uint32x4_t vmlal_u16(uint32x4_t c, uint16x4_t a, uint16x4_t b) { LOOP(4) c.v[i] += (uint32_t)a.v[i] * b.v[i]; return c; }
E uint16x8_t vmull_u8(uint8x8_t a, uint8x8_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] * b.v[i]); return r; }
E int16x8x2_t vtrnq_s16(int16x8_t a, int16x8_t b) { int16x8x2_t r; for (int i = 0; i < 8; i += 2) { r.val[0].v[i] = a.v[i]; r.val[0].v[i + 1] = b.v[i]; r.val[1].v[i] = a.v[i + 1]; r.val[1].v[i + 1] = b.v[i + 1]; } return r; }
E int32x4x2_t vtrnq_s32(int32x4_t a, int32x4_t b) { int32x4x2_t r; for (int i = 0; i < 4; i += 2) { r.val[0].v[i] = a.v[i]; r.val[0].v[i + 1] = b.v[i]; r.val[1].v[i] = a.v[i + 1]; r.val[1].v[i + 1] = b.v[i + 1]; } return r; }
E uint8x16x2_t vuzpq_u8(uint8x16_t a, uint8x16_t b) { uint8x16x2_t r; LOOP(8) { r.val[0].v[i] = a.v[2 * i]; r.val[0].v[i + 8] = b.v[2 * i]; r.val[1].v[i] = a.v[2 * i + 1]; r.val[1].v[i + 8] = b.v[2 * i + 1]; } return r; }
#define RI(NAME, RT, AT) E RT NAME(AT a) { RT r; memcpy(&r, &a, sizeof r); return r; }
RI(vreinterpretq_s32_s16, int32x4_t, int16x8_t) RI(vreinterpretq_s16_s32, int16x8_t, int32x4_t) RI(vreinterpretq_s16_u16, int16x8_t, uint16x8_t)
RI(vreinterpretq_u16_s16, uint16x8_t, int16x8_t) RI(vreinterpretq_s32_u32, int32x4_t, uint32x4_t)
E int16x8_t vaddq_s16(int16x8_t a, int16x8_t b) { LOOP(8) a.v[i] = (int16_t)(a.v[i] + b.v[i]); return a; }
E int16x8_t vsubq_s16(int16x8_t a, int16x8_t b) { LOOP(8) a.v[i] = (int16_t)(a.v[i] - b.v[i]); return a; }
E int32x4_t vaddq_s32(int32x4_t a, int32x4_t b) { LOOP(4) a.v[i] = (int32_t)((uint32_t)a.v[i] + (uint32_t)b.v[i]); return a; }
E int32x4_t vsubq_s32(int32x4_t a, int32x4_t b) { LOOP(4) a.v[i] = (int32_t)((uint32_t)a.v[i] - (uint32_t)b.v[i]); return a; }
E uint32x4_t vaddq_u32(uint32x4_t a, uint32x4_t b) { LOOP(4) a.v[i] += b.v[i]; return a; }
E uint16x8_t vsubl_u8(uint8x8_t a, uint8x8_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i] - b.v[i]); return r; }
E int32x4_t vrshrq_n_s32(int32x4_t a, int n) { LOOP(4) a.v[i] = (int32_t)(((int64_t)a.v[i] + (1LL << (n - 1))) >> n); return a; }
E int32x4_t vshrq_n_s32(int32x4_t a, int n) { LOOP(4) a.v[i] = a.v[i] >> n; return a; }
E int32x4_t vshlq_n_s32(int32x4_t a, int n) { LOOP(4) a.v[i] = (int32_t)((uint32_t)a.v[i] << n); return a; }
E int16x4_t vqmovn_s32(int32x4_t a) { int16x4_t r; LOOP(4) r.v[i] = (int16_t)(a.v[i] > 32767 ? 32767 : a.v[i] < -32768 ? -32768 : a.v[i]); return r; }
E int16x8_t vqaddq_s16(int16x8_t a, int16x8_t b) { LOOP(8) { int s = a.v[i] + b.v[i]; a.v[i] = (int16_t)(s > 32767 ? 32767 : s < -32768 ? -32768 : s); } return a; }
E uint8x8_t vqmovun_s16(int16x8_t a) { uint8x8_t r; LOOP(8) r.v[i] = (uint8_t)(a.v[i] < 0 ? 0 : a.v[i] > 255 ? 255 : a.v[i]); return r; }
E uint8x16_t vrhaddq_u8(uint8x16_t a, uint8x16_t b) { LOOP(16) a.v[i] = (uint8_t)((a.v[i] + b.v[i] + 1) >> 1); return a; }
E uint16x8_t vpadalq_u8(uint16x8_t c, uint8x16_t a) { LOOP(8) c.v[i] = (uint16_t)(c.v[i] + a.v[2 * i] + a.v[2 * i + 1]); return c; }
E uint32x4_t vaddw_u16(uint32x4_t a, uint16x4_t b) { LOOP(4) a.v[i] += b.v[i]; return a; }
E uint32x4_t vaddl_u16(uint16x4_t a, uint16x4_t b) { uint32x4_t r; LOOP(4) r.v[i] = (uint32_t)a.v[i] + b.v[i]; return r; }
E int32x4_t vminq_s32(int32x4_t a, int32x4_t b) { LOOP(4) a.v[i] = a.v[i] < b.v[i] ? a.v[i] : b.v[i]; return a; }
E int32x4_t vmaxq_s32(int32x4_t a, int32x4_t b) { LOOP(4) a.v[i] = a.v[i] > b.v[i] ? a.v[i] : b.v[i]; return a; }
E int16x4_t vmovn_s32(int32x4_t a) { int16x4_t r; LOOP(4) r.v[i] = (int16_t)a.v[i]; return r; }
E uint16x4_t vmovn_u32(uint32x4_t a) { uint16x4_t r; LOOP(4) r.v[i] = (uint16_t)a.v[i]; return r; }
E uint8x8_t vmovn_u16(uint16x8_t a) { uint8x8_t r; LOOP(8) r.v[i] = (uint8_t)a.v[i]; return r; }
E uint8x8_t vorr_u8(uint8x8_t a, uint8x8_t b) { LOOP(8) a.v[i] |= b.v[i]; return a; }
E uint8x8_t vand_u8(uint8x8_t a, uint8x8_t b) { LOOP(8) a.v[i] &= b.v[i]; return a; }
E uint8x8_t vshr_n_u8(uint8x8_t a, int n) { LOOP(8) a.v[i] = (uint8_t)(a.v[i] >> n); return a; }
E uint16x8_t vbslq_u16(uint16x8_t m, uint16x8_t a, uint16x8_t b) { LOOP(8) a.v[i] = (uint16_t)((m.v[i] & a.v[i]) | (~m.v[i] & b.v[i])); return a; }
E uint32x4_t vbslq_u32(uint32x4_t m, uint32x4_t a, uint32x4_t b) { LOOP(4) a.v[i] = (m.v[i] & a.v[i]) | (~m.v[i] & b.v[i]); return a; }
E uint32x4_t vcltq_u32(uint32x4_t a, uint32x4_t b) { uint32x4_t r; LOOP(4) r.v[i] = a.v[i] < b.v[i] ? 0xFFFFFFFFu : 0; return r; }
E int32x4_t vmulq_n_s32(int32x4_t a, int32_t b) { LOOP(4) a.v[i] = (int32_t)((uint32_t)a.v[i] * (uint32_t)b); return a; }
E int32x4_t vmlaq_n_s32(int32x4_t c, int32x4_t a, int32_t b) { LOOP(4) c.v[i] = (int32_t)((uint32_t)c.v[i] + (uint32_t)a.v[i] * (uint32_t)b); return c; }
E int16x8_t vld1q_s16(const int16_t *p) { int16x8_t r; memcpy(r.v, p, 16); return r; }
E void vst1q_s16(int16_t *p, int16x8_t a) { memcpy(p, a.v, 16); }
E int16x8_t vabsq_s16(int16x8_t a) { LOOP(8) a.v[i] = (int16_t)(a.v[i] < 0 ? -a.v[i] : a.v[i]); return a; }
E uint32x4_t vmlal_n_u16(uint32x4_t c, uint16x4_t a, uint16_t b) { LOOP(4) c.v[i] += (uint32_t)a.v[i] * b; return c; }
E uint32x4_t vshlq_u32(uint32x4_t a, int32x4_t s) { LOOP(4) a.v[i] = s.v[i] >= 0 ? (s.v[i] > 31 ? 0 : a.v[i] << s.v[i]) : (s.v[i] < -31 ? 0 : a.v[i] >> -s.v[i]); return a; }
E uint16x8_t vminq_u16(uint16x8_t a, uint16x8_t b) { LOOP(8) a.v[i] = a.v[i] < b.v[i] ? a.v[i] : b.v[i]; return a; }
E uint16x8_t vcltq_s16(int16x8_t a, int16x8_t b) { uint16x8_t r; LOOP(8) r.v[i] = a.v[i] < b.v[i] ? 0xFFFF : 0; return r; }
E int16x8_t vnegq_s16(int16x8_t a) { LOOP(8) a.v[i] = (int16_t)-a.v[i]; return a; }
E int16x8_t vbslq_s16(uint16x8_t m, int16x8_t a, int16x8_t b) { LOOP(8) a.v[i] = (int16_t)((m.v[i] & (uint16_t)a.v[i]) | (~m.v[i] & (uint16_t)b.v[i])); return a; }
E uint16_t vmaxvq_u16(uint16x8_t a) { uint16_t m = 0; LOOP(8) if (a.v[i] > m) m = a.v[i]; return m; }
E uint16x8_t vorrq_u16(uint16x8_t a, uint16x8_t b) { LOOP(8) a.v[i] |= b.v[i]; return a; }
E uint16x8_t vaddq_u16(uint16x8_t a, uint16x8_t b) { LOOP(8) a.v[i] = (uint16_t)(a.v[i] + b.v[i]); return a; }
E uint16x8_t vshlq_u16(uint16x8_t a, int16x8_t s) { LOOP(8) a.v[i] = (uint16_t)(s.v[i] >= 0 ? (s.v[i] > 15 ? 0 : a.v[i] << s.v[i]) : (s.v[i] < -15 ? 0 : a.v[i] >> -s.v[i])); return a; }
E int16x8_t vdupq_n_s16_(int16_t x) { int16x8_t r; LOOP(8) r.v[i] = x; return r; }
E uint8x16_t vdupq_n_u8(uint8_t x) { uint8x16_t r; LOOP(16) r.v[i] = x; return r; }
E uint8x16_t vqsubq_u8(uint8x16_t a, uint8x16_t b) { LOOP(16) a.v[i] = (uint8_t)(a.v[i] > b.v[i] ? a.v[i] - b.v[i] : 0); return a; }
E uint16x8_t vmull_high_u8(uint8x16_t a, uint8x16_t b) { uint16x8_t r; LOOP(8) r.v[i] = (uint16_t)(a.v[i + 8] * b.v[i + 8]); return r; }
E uint32x4_t vpaddlq_u16(uint16x8_t a) { uint32x4_t r; LOOP(4) r.v[i] = (uint32_t)a.v[2 * i] + a.v[2 * i + 1]; return r; }
E uint32x4_t vmulq_n_u32(uint32x4_t a, uint32_t b) { LOOP(4) a.v[i] *= b; return a; }
E uint32x4_t vshlq_n_u32(uint32x4_t a, int n) { LOOP(4) a.v[i] <<= n; return a; }
#undef E
#undef LOOP
#endif
