# Exhaust valve controller

The SB2209 RP2040 controller shares standard CAN ID `0x67A` at 500 kbit/s
with Haldex, using the separate `C3 3C` namespace. Haldex mode headers remain
unchanged. Hudiy's bar shortcut alternates absolute Open (100%) and Closed
(0%) commands through the Haldex manager. The first press requests Open if
the Pi has no recorded intent. Three identical transaction retries are sent.

The Pi stores only its last sent intent for the next toggle and display. It
never replays the valve target on startup, sends a heartbeat, or performs
ARM/HOME choreography. The controller restores its own saved target.
There is no allocated vehicle return ID; all displayed targets and update
results are unconfirmed. CAN ACK does not establish command acceptance or
physical position. No reply-ID operation is sent.

DataView **Modules → Exhaust valve controller** provides Open/Close controls,
bundle validation, firmware transfer, progress, and cancellation. Upload a
ZIP with `can-update.json`, `sb2209_app_0.bin`, and `sb2209_app_1.bin` at its
root in **Files → Exhaust valve controller**. Both native slot `.bin` images
and the manifest can also be uploaded individually. ZIP uploads install as
versioned directories under `~/exhaustfw`; standard filenames can be reused
for later versions. Only complete bundles with matching lengths, CRC32s,
and slot-specific vectors enter the firmware selector. UF2/ELF/full-flash
images are excluded.

Before sending, DataView pauses the existing Haldex/TP2 senders and inhibits
normal CAN application traffic. It reserves a deployment generation in
`~/.hudiy/exhaust_deployment.json` before ENTER. The default installed floor
is 16, matching the supplied SB2209 protocol, so the next generation is at
least 17 even when the build manifest says 1. Identical bundle retries reuse
their generation; changed code or rollback receives a newer generation.
If another tool updates the valve, raise `exhaust_valve.installed_generation_floor`
to the highest stored generation, including rejected trials. Retain the
deployment journal across Pi updates.

The sender enters the resident loader three times, waits one second, and
sends both slots sequentially over three identical passes. Each frame is
paced at 2 ms; manifests repeat every 256 chunks. Chunk indices use big-endian
uint16, three data bytes, and final FF padding outside the CRC. Each section
commits and waits four seconds. It never replaces the resident loader or the
remembered-target journal. Normal sender state is restored after transfer,
failure, or cancellation. An interrupted transfer can be retried with the
same complete bundle. The terminal result is **sent / unconfirmed**; there
is no automatic boot/receipt verification on the vehicle route.

Offline tests exercise frame encoding, generation handling, bundle validation,
transfer pacing and manifests, cancellation, ownership cleanup, and portal
installation. Actual Pi/gateway transmission and installed valve movement
still require a hardware check.
