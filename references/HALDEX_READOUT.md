# Refactored flasher and Hudiy readout

Integrated from the 2026-09-16 `HaldexRE/flasher` refactor:

- `flasher/haldex_flash.py` contains the shared KWP helpers and application
  upload/capture implementation. Hudiy retains strict service-response checking,
  bounded response-pending handling and no ambiguous TransferData retry.
- `haldex_patcher.py` provides strict 320 KiB sizing, whole-sector selection,
  selected-sector patches and checksum repair. Unselected bytes remain unchanged.
- `tp20.py` now supports segmented upload responses, intermediate ACKs and
  sequence wrap while retaining channel/sequence/length checks.
- `haldex_flasher.py` remains the Hudiy lifecycle adapter for progress,
  cancellation, cleanup and separately verified commit/application boot.
- `readout.py` adds UI progress, automatic naming and persistent capture reports
  around the shared reader. No second dumper or standalone checksum script exists.

The reference's adapter-selection CLI and J2534/Panda implementations are not
duplicated into Hudiy. Hudiy uses its installed SocketCAN adapter. No hardware
was accessed and no reference binaries or source files were changed.

## UI

Select sectors, then **Read Controller firmware**. No input firmware file is needed.
The existing progress/ETA/cancel display is shared, with a distinct **Readout
complete** result and binary/report download links. Other connected clients
receive start/progress/terminal events. Invalid requests are rejected before
busy state or CAN acquisition.

Readout obtains the same diagnostic ownership as flashing, enables persistent
Flashing Mode, and keeps it on afterward. It requires the running application
at TP2 address `0x764`; it does not enter the programming loader, erase firmware,
send RequestDownload, or use the withdrawn empty-download verification sequence.
The flow is `10 89`, security level `27 03/04`, `10 84`, then `35/36/37` upload;
cleanup exits that session and reads identification again.

## Files

Saved under `~/haldexfw/readouts/<capture-id>/`, with automatic names such as:

`0BR907554A_6716_segments4-7_20260916T120000000000Z.bin`

The filename uses actual Controller part number, software version, selected sector
numbers and UTC capture-start date/time. Names are sanitized; server-generated
capture IDs prevent overwrite collisions. Clients cannot choose output paths.

Every image is 327680 bytes with CPU addresses as offsets. Only the selected
sectors contain captured data; **all unread addresses are FF padding**, including
bootloader and memory gap even for a full application readout. The report records
captured ranges, hashes, selected-sector checksums, raw identification, cleanup
results and times. Successful readout downloads require complete capture,
correct captured-sector checksums and successful session cleanup. The readout is
never patched or checksum-repaired: it preserves the original captured bytes.

On cancellation/failure, saved windows remain in `pass1.bin`; `report.json` records
actual coverage and the UI offers its report link. Incomplete data is not offered
as a successful firmware download. `diagnostic.jsonl` and operation logs retain
raw requests/responses. Upload TransferData is never retried after an ambiguous
timeout; a new user readout starts a fresh operation.

## Verification and remaining bench acceptance

Run `python -m unittest discover -s tests -v` and
`npm --prefix hudiy_dataview run typecheck`. Tests cover the refactored reader,
upload TP2 segmentation, naming/padding, selected patch scope, partial captures,
malformed requests, timeout/cancel cleanup, shared ownership and download-path
validation. The installer checks imports from the installed layout.

On the recoverable Linux bench, exercise the installed UI for calibration and
full application reads, inspect the generated names/reports, compare captured
sectors against the known bench image, and repeat a capture to compare hashes.
Verify background TX inhibition, readout cancellation, identification after exit,
and download behavior. These software-only checks do not establish SocketCAN
timing or hardware readiness. Do not infer that FF padding is readback evidence.

Firmware storage defaults to visible `~/haldexfw` (configurable with
`haldex.firmware_dir`). The picker searches subfolders recursively and shows
relative paths. Legacy tune folders remain searchable. Failed/incomplete capture
files are excluded; only the successful image named in a capture report is listed.

