# r21 ADC tuning

The Manager RNS-E page tunes the head unit ADC (AKM AK5406) through the
existing local CAN base service. The register map comes from
`RNSE hacking/analysis/ak5406_v1/PI_UI_REGISTERS.md`; the older ADI-based map
(offsets in 0B–0D, chip probe on 1A) was wrong and is gone.

Commands use standard CAN ID `0x7B0`, DLC 8. Replies default to `0x7B6`
(r44+); set `can_ids.rnse_adc_reply` to the firmware's reply ID and restart
RNS-E functions if it changes. Setting this field to `null` disables readbacks:
single commands are unconfirmed and hold the controller busy for at least 200 ms.
Multi-register writes, pairs, linked RGB, presets with multiple values, Revert
and Re-send clock require a configured reply ID; they cannot safely burst commands.

## When values are lost

All chip writes are volatile; a reboot restores the firmware values. A TV mode
re-initialisation (0x602 rate change, TV re-select) also overwrites 01–03. The
service remembers the last confirmed 01–03 writes; **Re-send clock** on the
Clock page writes them again. Nothing is reapplied automatically. Every other
register is written once at boot and is shared with the reverse camera until
the next reboot.

## Registers

- **Writable with stock firmware:** 01–13 and 19–1B, except the ones below.
- **Writable after the BC widening patch** (`BC_WIDEN_SPEC.md`): also 17/18,
  1C and 1D–28. Unpatched firmware answers `EE` (rejected); the page marks
  these controls `W`.
- **Never written:** 00 (chip ID `AE`), 0B–0D, 0F (power-down), 14–16, 29+.

The server enforces these encodings:

| Register | Rule |
|---|---|
| 01 + 02 | Line length; one batch, 01 then 02; 02 bits 3:0 clear; 224–4096 clocks |
| 03 | VCO range 0–2 (bits 7:6), charge pump 0–6 (bits 5:3), bits 2:0 clear |
| 04, 10 | Bits 2:0 clear |
| 05, 06, 07 | 1–255; clamp start + length ≤ 104 |
| 0E | `2D` (SOG) or `25` (HSYNC pin) only |
| 17+18, 19+1A, 1B+1C | Manual offset pairs; MSB 0 or 1; one batch, MSB then LSB |
| 1D+1E, 1F+20, 21+22 | Black target pairs; MSB 0 or 1; −4 to +20 codes |
| 24 | `58` or `78` only |
| 25 | 0–254 and less than the clamp length |
| 28 | `A0`, `B0`, `E0` or `F0` only (lower drive values switch the outputs off) |

The clamp checks use the last readback, or the firmware value, for registers
not in the batch. Batches are sent in register order, which keeps every pair
in latch order. When start grows and length shrinks, length goes first; when
length shrinks below the current split, the split goes first. A pending write
to either clamp register blocks another clamp change. A clamp timeout or I2C
error requires a fresh successful dump of both clamp values before further
clamp writes.

Revert is a separate fixed operation writing the firmware values for 01–13
(except reserved ones) and then 23–28. Without the widening patch it stops at
23 with `rejected`; the stock range has already been restored by then.

## Replies

A successful local queue is followed by a pending write status. Only a `W`
reply (`57 rr vv ss`) confirms readback and status: `00` means success, `EE`
rejected, `FC` readback failed, and other status bytes an I2C error. The
firmware accepts one BC/BD request at a time and silently drops overlapping
requests. A batch sends its first BC immediately; remaining writes have
`queued` status. Only the matching register's W reply releases the next frame,
through the live guarded send callback. An error, unexpected readback, send
failure or two-second reply timeout stops the batch; remaining registers become
`not_sent`. No automatic retry or later resumption is scheduled. All new BC/BD
commands are blocked while a write, batch or dump is busy. In listen-only mode,
during mode transitions, while flashing, or when the radio is inactive,
commands are rejected and are never deferred for later sending.

## Dump

Dump is explicitly requested with BD. The firmware still sends 39 bytes in
eight frames that may arrive in any order. Assembly keys frames by byte 0: `41`
with the `ADC` signature for the header and `01`–`07` for data/bitmap frames.
Dump commits atomically after eight distinct valid frames, a count of 39, valid
data padding and a valid 39-bit failed-read bitmap. Duplicate or invalid frames
discard the partial generation; an incomplete dump expires after three seconds.
After an invalid generation or timeout, late frames are ignored until a fresh
explicit Dump request.

Only 00–1D and 24 are real; the other dump entries (31, 35–37, 41, 43, 45, 46)
are aliases or test space and are hidden. 1E–23 and 25–28 are not in the dump:
the page shows the last confirmed W readback for them, which a reboot does not
clear. The first complete dump in the service session is the comparison
baseline; later complete dumps and successful write readbacks highlight changes.

## Presets

Built-in presets from the register reference: Firmware (runs Revert), Banding
fix A/B, Banding diagnostic, TV clamp, Camera-safe clamp, Low-noise drive and
Low PLL bandwidth. Saved presets are named JSON register-to-byte maps stored at
`~/.hudiy/rnse-adc-presets.json`, separately from configuration. Saving holds
every control with a known value. Saving and listing send no CAN frames; Load
explicitly applies the map. Names are limited to 64 characters, with at most 32
presets. A preset file written before the AK5406 map (with 0B–0D) no longer
validates; delete it.

## Local API

| Method and path | Body | Result |
|---|---|---|
| GET `/api/manage/rnse-adc` | — | State, register rows 00–28, write statuses, dump progress, firmware values |
| POST `/api/manage/rnse-adc/write` | `{"values":{"08":112,"09":112,"0A":112}}` | Snapshot after queuing |
| POST `/api/manage/rnse-adc/dump` | `{}` | Snapshot after dump request |
| POST `/api/manage/rnse-adc/revert` | `{}` | Snapshot after fixed firmware writes |
| POST `/api/manage/rnse-adc/resend-clock` | `{}` | Snapshot after re-sending the last confirmed 01–03 |
| GET `/api/manage/rnse-adc/presets` | — | `{"presets":{"name":{"08":112}}}` |
| POST `/api/manage/rnse-adc/presets` | `{"name":"name","values":{"08":112}}` | Saved preset map |

Mutations use the existing same-origin Manager header and configured PIN.
Request bodies are limited to 4 KiB. Registers use two hexadecimal digits and
values are JSON integers. Register rows carry `in_dump` and `access` (`now`,
`widen` or `read_only`). The wire format has no request or generation token, so
unusually late replies to an earlier explicit request cannot always be
distinguished from a newer request. Avoid immediate retries after an invalid
dump or timed-out write when checking hardware.
