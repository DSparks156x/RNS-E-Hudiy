/* sf.c -- see sf.h. Header offsets = sd_wire.py HDR_FMT ">IHHIIIIIHBBIHHHHIIHHI" (60 B) + hdr_crc32. */
#include "sf.h"
#include "crc.h"
#include <string.h>

void put_be16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
void put_be32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v; }
uint32_t get_be32(const uint8_t *p) { return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3]; }
uint16_t get_be16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }

int sf_tlv(sf_hdr *h, uint8_t type, const void *data, uint8_t len)
{
    if (h->ctrl_bytes + 2u + len > SF_CTRL_MAX) return -1;
    h->ctrl[h->ctrl_bytes] = type;
    h->ctrl[h->ctrl_bytes + 1] = len;
    memcpy(h->ctrl + h->ctrl_bytes + 2, data, len);
    h->ctrl_bytes = (uint16_t)(h->ctrl_bytes + 2 + len);
    return 0;
}

int sf_build(const sf_hdr *h, const uint8_t *audio, uint32_t audio_bytes, const uint8_t *video, uint32_t video_bytes,
             uint8_t *out)
{
    uint16_t asec = (uint16_t)((audio_bytes + 511) / 512), vsec = (uint16_t)((video_bytes + 511) / 512);
    uint16_t total = (uint16_t)(1 + asec + vsec);
    uint8_t *s = out;
    memset(s, 0, 512);
    put_be32(s + 0, SF_MAGIC);
    put_be16(s + 4, 1);                      /* version */
    put_be16(s + 6, 64);                     /* hdr_len */
    put_be32(s + 8, h->seq);
    put_be32(s + 12, h->flags);
    put_be32(s + 16, h->audio_pts);
    put_be32(s + 20, h->video_pts);
    put_be32(s + 24, video_bytes);
    put_be16(s + 28, h->audio_frames);
    s[30] = h->audio_fmt;
    s[31] = h->video_fmt;
    put_be32(s + 32, audio_bytes);
    put_be16(s + 36, 1);                     /* audio_sec: always 1 (sdgen.py does the same with no audio) */
    put_be16(s + 38, (uint16_t)(1 + asec));  /* video_sec */
    put_be16(s + 40, total);
    put_be16(s + 42, h->next_total_hint);
    put_be32(s + 44, crc32z(0, video, video_bytes));
    put_be32(s + 48, crc32z(0, audio, audio_bytes));
    put_be16(s + 52, h->ctrl_bytes);
    put_be16(s + 54, h->frame_id);
    put_be32(s + 56, h->pi_time_us);
    memcpy(s + 64, h->ctrl, h->ctrl_bytes);
    put_be32(s + 60, crc32z(crc32z(0, s, 60), s + 64, 448));
    uint8_t *a = out + 512;
    if (audio_bytes) memcpy(a, audio, audio_bytes);
    memset(a + audio_bytes, 0, (size_t)asec * 512 - audio_bytes);
    uint8_t *v = a + (size_t)asec * 512;
    if (video_bytes) memcpy(v, video, video_bytes);
    memset(v + video_bytes, 0, (size_t)vsec * 512 - video_bytes);
    return total;
}
