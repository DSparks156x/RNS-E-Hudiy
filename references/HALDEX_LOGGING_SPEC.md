# What to log in the car

Companion to `HALDEX_CAN_INTERFACE.md` (frame formats) and
`PREFLIGHT_VEHICLE.md` (what must be checked before flashing).

The point of the vehicle drive is not "collect data". It is to close four
specific questions the bench cannot answer. Everything below exists to serve
one of them.

---

## 0. Current firmware contract

**Tbl27's axis is `(DAT_0F13F4 − DAT_0F1D1A) · sign(DAT_0F13F4)`** — measured
yaw rate minus **model** yaw rate, 17.87 counts per deg/s.

The measured half is on ICAN `0x2A1`. The model half is computed inside the ECU
by `FUN_0464B0` and appears on current firmware's fixed `0x679` frame as a
signed value at 17.87 counts/(deg/s). The logger treats this field as
`model_yaw`, not the historical `B1A` telemetry variant.

Current vehicle candidate 7316 uses fixed `0x679` plus tagged, multiplexed
`0x6DA`. The executable format authority is
`HaldexRE/phase2_can_telemetry_mux.py`; do not decode `0x6DA` as the older four
little-endian words without first validating its `0xD0 | page` header.

Mode commands on `0x67A` use a compact two-byte namespace. Send five identical
frames 20 ms apart; bytes 2-7 are zero for Hudiy mode commands and ignored by
Haldex:

| Bytes 0-1 | Meaning |
| --- | --- |
| `5A A5` | Stock, row 0 |
| `A5 5A` | Performance, row 1 |
| `3C C3` | Competition, row 2 |
| `C3 3C` | External-device namespace; preserve current row |

An unrecognized header fails immediately to Stock. The pre-7316 packet format
also began `5A A5`, so an old sender silently selects Stock regardless of its
legacy mode byte. Log the transmitted header and confirm the applied mode from
`0x6DA`.

---

## 1. From the Haldex frames — 50 Hz, exists nowhere else

Decode per `HALDEX_CAN_INTERFACE.md` §4. Log **all sixteen bytes of both
frames, raw, with the hardware timestamp**, and decode in post.

Raw matters. If a field turns out to be misread — and one already was
(`A7E` is the hold timer mid-countdown, not the calibration constant) — raw
bytes can be re-parsed and a decoded-only CSV cannot.

| Frame | Carries | Answers |
| --- | --- | --- |
| `0x679` | `YAW_MODEL`, `C06`, `C22`, `B08` | Q1 yaw sizing, Q2 Tbl48 |
| `0x6DA` | Tagged pages 0..6; see below | Q1/Q3 context, Q4 slip loop |

Every `0x6DA` frame is eight bytes: byte 0 is `0xD0 | page`, byte 1 carries
mode `[1:0]`, B1CC `[4:2]`, A78 `[5]`, `token_ok` `[6]`, and ABS `[7]`; the
remaining bytes are three little-endian words. Reject frames whose header does
not match `(byte0 & 0xF8) == 0xD0`. **Take mode from this status byte, never
from what the button was set to.**

The eight-frame page schedule is `0, 1, 2, 3, 4, 5, 6, 1`. Page 1 arrives at
12.5 Hz; every other page arrives at 6.25 Hz.

| Page | Word 0 | Word 1 | Word 2 |
| ---: | --- | --- | --- |
| 0 | A72 ceiling | A74 final reference | A7C slip integrator |
| 1 | C9E demanded accel (s16) | C9C actual accel (s16) | measured yaw (s16, 17.87 counts/(deg/s)) |
| 2 | B26 lateral feed-forward (s16) | BC4 curvature | BB6 computed axle slip (s16) |
| 3 | wheel VL | wheel VR | wheel HL |
| 4 | wheel HR | measured lateral acceleration (s16) | throttle low byte, BLS high byte |
| 5 | A7E hold timer | C12 high-gear factor | target-gear word (gear in low byte) |
| 6 | C3A slip energy | C26 energy ceiling | AFE fault/derate ceiling |

Wheel speeds use 0.005 km/h/count. Pages 3 and 4 occur on consecutive 20 ms
ticks, so the reconstructed four-wheel sample is deliberately non-atomic.
Preserve each raw page and its hardware timestamp.

---

## 2. From ICAN and measuring groups — do not assume ACAN is available

The logger is attached to infotainment CAN only. Decode only messages present in
`PQ35_46_ICAN.dbc`: `0x359` for ABS-sourced vehicle speed, averaged front-axle
path pulses, brake/ABS/ESP/selector state; `0x351` provides another gateway
vehicle-speed channel; `0x35B` provides RPM/coolant/brake state, `0x3C3`
provides steering, `0x2A1` provides the
navigation yaw signal, and `0x527`/`0x555` for optional temperatures. The raw
ACAN frames (`0x4A0`, `0x0C2`, `0x1A0`, `0x280`, `0x288`, `0x4A8`, `0x428`)
are not available to this installation and must not be decoded here.

Signals absent from ICAN can come from the Haldex telemetry pages or, when
known safe, TP2 measuring groups. A logging profile owns its group
subscriptions for the duration of the recording, independently of whichever
DataView tab is visible, and may subscribe to several groups on several
modules concurrently.

The default Haldex profile opens no diagnostic sessions. In particular, it
does not poll ABS module `0x03`: doing so triggers an ESP fault and interferes
with Haldex operation on this vehicle. RPM comes from ICAN `0x35B`; boost and
oil temperature come from ICAN `0x555`. The logger remains configurable for
verified measuring groups on other modules, but it should not open extra
sessions merely to collect speculative or duplicated values.

Four individual wheel speeds now come passively from `0x6DA` pages 3 and 4.
Measured lateral acceleration comes from page 4; demanded and actual
longitudinal acceleration plus measured yaw come from page 1. No ABS
diagnostic session is required. ICAN `0x359` remains a useful independent
vehicle-speed and front-axle-path reference, and ICAN `0x2A1` remains an
independent yaw channel.

**Required:**

- **all four wheel speeds** — not just vehicle speed. Real slip is computed from
  these, and closing the slip loop (Q4) is impossible without them
- **measured yaw rate** — the other half of the Tbl27 axis
- **lateral acceleration**, longitudinal acceleration
- **steering wheel angle** and, if broadcast, steering rate
- **brake light switch (BLS)** and the **ABS / ESP active** flags — these drive
  the B1CC selector and the brake-policy gate
- **throttle pedal position**, engine RPM, **engine torque**, selected gear

**Wanted:**

- coolant / ambient temperature — the Haldex has a hot/cold ratio (Tbl2) and a
  cold controller behaves differently
- GPS position and heading if you have it — it makes "same corner, both modes"
  a computation instead of a memory

---

## 3. Logger-side

**Timestamps from the CAN hardware, not the host clock.** A host stamp is taken
whenever the logger happened to drain the queue; under load that turns a 50 Hz
stream into what looks like a slower one. This is not hypothetical — it made
these exact frames read as 40 Hz on the bench until they were measured against
driver timestamps. SocketCAN: `SO_TIMESTAMP`.

**One clock for everything.** Haldex frames and bus signals must share a time
base or none of the cross-signal analysis works.

**Do not decimate.** Both frames at 50 Hz is 16 bytes × 100/s — nothing. Log
every frame.

**Mark mode-change commands.** Log when the CarPi *sent* a `0x67A` burst and
what it asked for, as a separate event from the mode the ECU *reports*. The
delta between those two is the transport's real-world reliability, which has
only ever been measured on a bench with one other node on the bus.

**Give yourself a marker button.** One press writes a timestamped event. "That
felt like understeer" is the highest-value signal in the whole log and it only
exists if you can tag it in the moment. Rich beats sparse — tag freely.

---

## 4. The four questions, and what each needs

**Q1 — how big should Tbl27 be?**
Histogram `(measured_yaw − YAW_MODEL) · sign(measured_yaw)` in counts,
conditioned on speed and lateral acceleration. The table's existing axis runs
`[266, 153, 102, 76, 43, 5, 0, −5, −34, −102, −165]` counts, so the histogram
says directly which axis points real driving actually visits. Then size the
values so the product clears the ~600-count floor where it should and not
where it shouldn't.
*Needs: `YAW_MODEL`, measured yaw, speed, lateral accel.*

**Q2 — did the Tbl48 revert do anything?**
`C22` against `B08` across speed, looking for the dynamic cap nulling below
~94.3 km/h. This was unverifiable before because `C22` and `B08` were in no
measuring block; `0x679` now carries both.
*Needs: `0x679`, vehicle speed.*

**Q3 — do the modes actually feel different, and does the data agree?**
Same corner, back-to-back, alternating mode 0 and mode 1, logged mode taken
from `0x6DA`. Compare `B08` and `A7C` traces against matched speed, steering
and lateral accel. **Alternate within a single drive** — tyre temperature,
surface and weather move more between sessions than the tune does.
*Needs: both frames, full bus set, markers.*

**Q4 — close the slip loop.**
The bench slip loop is open: the simulator's slip is imposed, not produced by
the controller's own torque. Real wheel speeds against the controller's own
`A7C` response closes it, and that is what makes every future bench prediction
trustworthy instead of indicative.
*Needs: four wheel speeds, `0x6DA`, engine torque.*

---

## 5. What a useful first drive looks like

Not a track day. Mode 0 for the whole first session — **confirm nothing is
broken and collect the stock baseline**, which is the reference every A/B is
measured against and is worth more than an early impression of the tune.

Then alternate. Same roads, same corners, marker button on anything that feels
like something.

Straight-line launches are the cheapest high-slip data you will get and they
exercise `A7C` hard; a damp roundabout in both modes is worth an hour of
motorway.
