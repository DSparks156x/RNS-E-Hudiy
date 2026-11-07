/* sf.h -- superframe container (link/SPEC.md section 3): 64-B header + 448-B down-channel, audio sectors, video
 * sectors; all fields big-endian. Matches link/sd_wire.py pack_header_sector() and rnse_proto/sdgen.py. */
#ifndef AVL_SF_H
#define AVL_SF_H
#include <stdint.h>
#include <stddef.h>

#define SF_MAGIC 0x52534156u   /* 'RSAV' */
#define SF_CTRL_MAX 448
#define SF_MAX_SECT 256

enum {
    SFF_KEY = 1, SFF_REPEAT = 2, SFF_IDLE = 4, SFF_DISCONT = 8, SFF_ADISCONT = 16, SFF_SYNTH = 32,
    SFF_NOTREADY = 64, SFF_EXPIRED = 128, SFF_EOS = 256
};
enum { AUDIO_FMT_NONE = 0, AUDIO_FMT_S16 = 1, AUDIO_FMT_S24_32 = 2 };
#define VIDEO_FMT_RNV2 2

/* down-channel TLVs {u8 type, u8 len, data} */
#define TLV_YUY2_CRC 0x10   /* u32 frame, u32 CRC-32 of the decoded YUY2 frame (test streams) */
#define TLV_FRAG 0x11       /* u32 frame_total_bytes, u32 offset, u32 CRC-32 of the whole frame */

typedef struct {
    uint32_t seq, flags, audio_pts, video_pts;
    uint16_t audio_frames;
    uint8_t audio_fmt, video_fmt;
    uint16_t next_total_hint, frame_id;
    uint32_t pi_time_us;
    uint8_t ctrl[SF_CTRL_MAX];
    uint16_t ctrl_bytes;
} sf_hdr;

static inline uint16_t sf_total_sec(uint32_t audio_bytes, uint32_t video_bytes)
{
    return (uint16_t)(1 + (audio_bytes + 511) / 512 + (video_bytes + 511) / 512);
}

int sf_tlv(sf_hdr *h, uint8_t type, const void *data, uint8_t len);   /* append a TLV; -1 if it doesn't fit */
/* Lay out one superframe into out (>= total*512 bytes, total = sf_total_sec()). Fills audio_bytes/sec,
 * video_bytes/sec, total_sec, both payload CRCs and hdr_crc32. Returns total_sec. */
int sf_build(const sf_hdr *h, const uint8_t *audio, uint32_t audio_bytes, const uint8_t *video, uint32_t video_bytes,
             uint8_t *out);
void put_be16(uint8_t *p, uint16_t v);
void put_be32(uint8_t *p, uint32_t v);
uint32_t get_be32(const uint8_t *p);
uint16_t get_be16(const uint8_t *p);

#endif
