# What to log in the car

Companion to `HALDEX_CAN_INTERFACE.md` (frame formats) and
`PREFLIGHT_VEHICLE.md` (what must be checked before flashing).

The point of the vehicle drive is not "collect data". It is to close four
specific questions the bench cannot answer. Everything below exists to serve
one of them.

---

## 0. The one thing that needs deciding before you flash

**Tbl27's axis is `(DAT_0F13F4 − DAT_0F1D1A) · sign(DAT_0F13F4)`** — measured
yaw rate minus **model** yaw rate, 17.87 counts per deg/s.

The measured half is a scaled copy of a CAN signal already on the bus. **The
model half is computed inside the ECU by `FUN_0464B0` and appears nowhere
else.** Without it, no amount of driving produces the error histogram Tbl27 has
to be sized against — and Tbl27 is the whole reason for taking the
"leverage the Haldex's own smarts" route on yaw.

There is no free message object and no free byte. So there is a variant image
that spends the one field provably carrying nothing:

```
artifacts/vehicle_taskf_yawcal_320k.bin
SHA-256 3344504F7F98B400C5D55CCA9B26D7197B921D110981F4C42498CD87FC220F18
```

`0x679` bytes 0-1 carry **`YAW_MODEL`** (`0x0F1D1A`, s16) instead of `B1A`.

`B1A` is `Tbl27 × Tbl32|33 × Tbl31 >> 30`. Tbl27 is all-zero in row 0 and below
its ~600-count floor in both provisional rows, so `B1A` reads **0 in every
mode** — confirmed on hardware in all three. It becomes interesting only after
Tbl27 is sized, which is what this variant exists to enable.

**It differs from the standard vehicle image by exactly two bytes:** one operand
word in the payload (`0x9B1A` → `0x9D1A`) and one Layer-1 checksum byte. Same
base, same everything else, checksums verified, no simulator patches.

**Recommendation: drive the yaw-calibration image.** Swap back to the standard
one once Tbl27 is real. If you would rather not, say so and drive the standard
image — you get everything below except question 1.

---

## 1. From the Haldex frames — 50 Hz, exists nowhere else

Decode per `HALDEX_CAN_INTERFACE.md` §4. Log **all sixteen bytes of both
frames, raw, with the hardware timestamp**, and decode in post.

Raw matters. If a field turns out to be misread — and one already was
(`A7E` is the hold timer mid-countdown, not the calibration constant) — raw
bytes can be re-parsed and a decoded-only CSV cannot.

| Frame | Carries | Answers |
| --- | --- | --- |
| `0x679` | `YAW_MODEL` (or `B1A`), `C06`, `C22`, `B08` | Q1 yaw sizing, Q2 Tbl48 |
| `0x6DD` | `A72`, `A74`, `A7C`, status word | Q3 A/B, Q4 slip loop |

The status word gives mode, B1CC selector, A78 force-zero, `token_ok` and A7E
in one 16-bit field. **Take mode from this frame, never from what the button
was set to** — they disagree exactly when something interesting happened.

---

## 2. From the car's own bus — do not spend Haldex bytes on these

All of it already exists on PQ35 CAN. Log at whatever rate each is broadcast.

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
from `0x6DD`. Compare `B08` and `A7C` traces against matched speed, steering
and lateral accel. **Alternate within a single drive** — tyre temperature,
surface and weather move more between sessions than the tune does.
*Needs: both frames, full bus set, markers.*

**Q4 — close the slip loop.**
The bench slip loop is open: the simulator's slip is imposed, not produced by
the controller's own torque. Real wheel speeds against the controller's own
`A7C` response closes it, and that is what makes every future bench prediction
trustworthy instead of indicative.
*Needs: four wheel speeds, `0x6DD`, engine torque.*

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
