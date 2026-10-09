# RNS-E Manager

Open **RNS-E Manager** in Hudiy’s applications menu. The independent
`hudiy_manager.service` serves it at `http://localhost:5004`; it remains available
when DataView is stopped. It uses Hudiy’s palette and on-screen keyboard.

## Settings

Choose RNS-E integration or one of the five Hudiy config files. Search by setting
name, JSON path or description, edit values, then save. The RNS-E descriptions
come from the same source as `tools/config_editor.html`. Unknown settings stay
in the document; structured values and Hudiy menu arrays can be edited as JSON.
Manager edits the installed files directly. File uploads live in the network
Files portal for use from your phone or computer.

Save replaces the file, after basic structural validation. It creates a backup
under `~/confbackup/YYYY-MM-DD/<number>/` and preserves file permissions. A stale
revision is rejected; refresh before retrying, keeping a copy of any draft you
need. Changes do not restart anything automatically. Restart affected services
from Services for integration changes, or restart Hudiy for its own configs.

The network file portal at `http://<Pi address>:5003/files` also has a
**Configuration** category. Select the destination and upload the complete JSON
file, then **Validate & replace config**. It uses the same backup and revision
checks. The existing standalone web config editor remains available.

## Services and logs

Services shows only the project’s installed systemd units. Start, stop and
restart are separate actions. Stopping CAN transport also stops dependent DIS
units; start those again after starting transport. Manager cannot stop itself.
Active controller operations prevent changes to their transport services.

Logs shows the selected service’s most recent 1–500 journal lines, bounded to
128 KiB. Follow refreshes the tail; Pause keeps it still for reading. Full saved
logs remain downloadable in the file portal. The Manager unit uses the
`systemd-journal` group for journal access.

Service actions use `sudo -n` with a fixed allowlist. The installer validates
the exact command policy with `visudo` before installing it as
`/etc/sudoers.d/rnse-manager` (root-owned, mode 0440). Only start/stop/restart of
the twelve controlled project units is allowed; no shell, wildcards, arbitrary
units or Manager self-control. These permissions apply to processes running as
the installation user. Before running the updated installer, systems without
equivalent existing permissions show the sudo error.

## RNS-E bridge controls

The RNS-E section controls two independent channels: brightness dial (0–10)
and LCD panel brightness (0–100). Automatic screen brightness defaults off
(day 10, night 1); its manual startup baseline is 10. Automatic LCD brightness
defaults off (day 100, night 6); its manual startup baseline is 0. Automatic
channels follow the vehicle day/night state. The manual dial/LCD sliders are
for live testing: releasing a slider sends one frame and does not disable
automatic mode. A later real day/night transition replaces test values for
channels whose automatic mode is enabled. Applying settings reloads policy and
sends a changed payload once.

The bridge uses standard CAN ID `0x7B0`, DLC 8, with payload
`BB LL MM SS 00 00 00 00`. `LL` is the brightness dial from 0 to 10. `MM` selects
Hudiy (0), CarPlay (1), or Android Auto (2). `SS` selects LCD behavior: 0 follows
the cluster; 1–100 overrides the LCD level. The LCD override uses raw levels
1–5, which the stock unit effectively renders as level 6.

Source labels are opt-in and use Hudiy’s reported media/navigation provider,
including idle or paused provider state. Hudiy’s API does not report exact
connection state, so the label is not a connected-source indicator. Hudiy
publishes two-second ZMQ snapshots; that publisher does not repeat CAN frames.
CAN frames are deduplicated by exact payload. There is no heartbeat or repeat
for unchanged values. Radio wake causes one reapply; inhibition alone does not
reapply an unchanged payload. Listen-only and Flashing Mode inhibit CAN sends.

The Manager client API is available only through the Manager on local port
5004, with bounded IPC commands to the CAN base service. The service gates sends
for radio state, listen-only and Flashing Mode. Manager does not access CAN
directly. This protocol requires new firmware; hardware behavior has not yet
been verified, and older B7 firmware is replaced by this protocol.

## Pi video colors

In Settings → RNS-E → **Pi video**, choose the output connected to the head unit.
The controls adjust the whole Pi Wayland output live; they are separate from
the RNS-E screen’s CAN brightness and from `config.json`.

| Control | Default | Range |
| --- | --- | --- |
| Gamma | 1.0 | 0.5–2.0 |
| Contrast | 1.0 | 0.5–1.5 |
| Black point | 0.0 | 0.0–0.10 |
| Red, green, blue gain | 1.0 each | 0.5–1.5 |

Dragging sliders applies the latest values after a short pause. Gamma above 1
brightens midtones. Black point moves the darkest tones to black sooner; gains
adjust the individual color channels. The gray and RGB patches help compare
the output while adjusting it.

**Neutral values** sets these six controls to their defaults. **Restore original**
releases the gamma control back to the compositor and removes any saved startup
adjustment. Those operations can produce different results if the compositor
already had its own color adjustments.

Live changes last while Manager holds the output control. **Save for startup**
writes a separate profile to `~/.hudiy/share/video-color.json`; Manager restores
that profile after restarting and waits for the desktop session if needed.
Ordinary slider changes do not update that saved profile. Refresh display checks
availability again while preserving your current slider values.

This uses the supplied `RNSE hacking/tools/pi_wayland_color.py` gamma-ramp
implementation, adapted to retain one native control while values change.
It requires Linux, the same user as the Hudiy Wayland desktop, and
`wlr-gamma-control-v1` support. An output can have only one gamma-control client;
another color/night-light tool may already own it. Missing support and ownership
errors are shown in the panel. The installer supplies the user’s runtime
directory; if multiple Wayland sessions exist, set `WAYLAND_DISPLAY` explicitly
in the Manager service environment. Actual Pi output behavior needs a hardware
check.

## Developer preview

Run `npm run build` in `hudiy_dataview` to rebuild all three apps and regenerate
the shared metadata. `management-preview.html` is an explicit sample fixture
for layout checks; the production app always uses the real API.
