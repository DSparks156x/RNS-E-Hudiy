# r21 ADC tuning

The Manager RNS-E page tunes the head unit ADC through the existing local CAN
base service. Commands use standard CAN ID `0x7B0`, DLC 8. Replies default to
`0x462`; set `can_ids.rnse_adc_reply` to the firmware's reply ID and restart
RNS-E functions if it changes. Setting this field to `null` disables readbacks:
single commands are unconfirmed and hold the controller busy for at least 200 ms.
Multi-register writes, linked RGB, presets with multiple values, Revert and chip
identification require a configured reply ID; they cannot safely burst commands.

All chip writes are volatile. Startup, config reload, preset reads, radio wake,
and service recovery do not reapply ADC tuning. After a reboot or TV/camera mode
reinitialisation, explicitly load the active preset again when the TV path is
active. Camera and TV share RGB offsets; other registers can reset on mode
switches. The Pi page and Revert target 480p register 03=`30` (range 0, charge
pump current 6); the 15 kHz boot value is `10` (range 0, current 2).

Gain uses byte values 0–255. Offset sliders use 0–127 and send `value << 1`
(encoded bytes 0–254). Phase sends `value << 3`. VCO combines range and charge
pump current in register 03. The server validates these encodings and requires
clamp placement plus duration below 110 clocks, using the last readback or
known defaults for the unchanged clamp control. Slider batches validate before
any frame is queued. Linked RGB queues one write for each of the three channels.
When both clamp controls change, the server orders them to keep the intermediate
window within the limit. A pending write to either clamp control blocks another
clamp change. A clamp timeout or I2C error requires a fresh successful dump of
both clamp values before further clamp writes.

Ordinary writes and presets accept only registers 03–06, 08–0D, 11–13.
PLL divider registers 01/02 remain locked. Revert is a separate fixed operation
restoring the stock/r21 values for registers 01–13, including PLL `3F/50`,
clamp `16/2F`, RGB offsets `7E`, coast `06/06`, and threshold `20`. The stock
register 24 value `58` is shown in the dump but omitted from Revert because the
firmware rejects that address.

A successful local queue is followed by a pending write status. Only a `W`
reply confirms readback and status: `00` means success, `EE` rejected, and other
status bytes an I2C error. The firmware accepts one BC/BD request at a time and
silently drops overlapping requests. A batch sends its first BC immediately;
remaining writes have `queued` status. Only the matching register's W reply
releases the next frame, through the live guarded send callback. An error,
unexpected readback, send failure or two-second reply timeout stops the batch;
remaining registers become `not_sent`. No automatic retry or later resumption
is scheduled. A successful readback differing from the requested byte is still
shown as `ok`, but stops continuation because subsequent clamp writes might be
unsafe. All new BC/BD commands are blocked while a write, batch, dump or chip
probe/restore is busy, including writes to different registers.
In listen-only mode, during mode transitions, while flashing, or when the radio
is inactive, commands are rejected and are never deferred for later sending.

Dump is explicitly requested with BD. Opening CAR > Version does not trigger
a CAN dump. All eight reply frames may arrive in any order, including the
header last. Assembly keys frames by byte 0: `41` with the `ADC` signature for
the header and `01`–`07` for data/bitmap frames. Dump commits all 39 registers
atomically after eight distinct valid frames, a count of 39, valid data padding
and a valid 39-bit failed-read bitmap. Duplicate or invalid frames discard the
partial generation; an incomplete dump expires after three seconds. After an
invalid generation or timeout, late frames are ignored until a fresh explicit
Dump request. The first frame starts assembly even when it is not the header.
Failed reads show no value. The first complete dump in the service session is
the comparison baseline; later complete dumps and successful write readbacks
highlight changes. This is a session baseline, not a guarantee of power-on values.

Identify chip is a dedicated register 1A operation. It first requires a complete
dump with a successful register 1D value `00`, confirming auto offset is off.
It sends `1A=04`, then classifies a successful readback: `04` means AD9985 class,
`00` means AD9883A class, and other bytes mean unknown. Rejection, I2C error or
timeout do not identify the chip. After the probe reply or two-second timeout,
the CAN service attempts exactly one `1A=00` restore, even if the UI has closed.
Restore respects the same transmission guards and reports its own readback,
status and confirmation. The firmware supplies no transaction token: after a
probe timeout, an unusually late `1A=00` probe reply can be indistinguishable
from the restore reply, particularly on an AD9883A-class chip. The probe remains
unconfirmed in that case, and its restore confirmation has this wire limitation.
An inhibited or failed restore stays unconfirmed and
is not retried. No general writes or presets may address 19–1B. Other commands
are blocked while probing/restoring.

Presets are named JSON register-to-byte maps stored at
`~/.hudiy/rnse-adc-presets.json`, separately from configuration. Saving and
listing them send no CAN frames. Load explicitly applies the selected map.
Names are limited to 64 characters, with at most 32 presets.

## Local API

| Method and path | Body | Result |
|---|---|---|
| GET `/api/manage/rnse-adc` | — | State, 39 register rows, write statuses, dump progress, defaults |
| POST `/api/manage/rnse-adc/write` | `{"values":{"08":112,"09":112,"0A":112}}` | Snapshot after queuing |
| POST `/api/manage/rnse-adc/dump` | `{}` | Snapshot after dump request |
| POST `/api/manage/rnse-adc/revert` | `{}` | Snapshot after fixed stock writes |
| POST `/api/manage/rnse-adc/identify` | `{}` | Snapshot with separate `identification.probe` and `identification.restore` states |
| GET `/api/manage/rnse-adc/presets` | — | `{"presets":{"name":{"08":112}}}` |
| POST `/api/manage/rnse-adc/presets` | `{"name":"name","values":{"08":112}}` | Saved preset map |

Mutations use the existing same-origin Manager header and configured PIN.
Request bodies are limited to 4 KiB. Registers use two hexadecimal digits and
values are JSON integers. Snapshots expose global `busy`, and per-register
`queued`, `pending`, final acknowledgement, or unsent states. The wire format
has no request or generation token, so unusually late replies to an earlier
explicit request cannot always be distinguished from a newer request. Avoid
immediate retries after an invalid dump or timed-out write when checking hardware.
