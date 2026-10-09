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

## RNS-E automatic brightness

In the RNS-E section, enable automatic brightness and set day/night levels from
0 to 10. Defaults are day 10, night 5, disabled. These settings control the RNS-E
screen separately from Hudiy/Android Auto theme switching.

The base CAN service reads the configured vehicle light-status frame and waits
for an active radio. It queues standard ID `0x7B0`, DLC 8,
`B7 LL 00 00 00 00 00 00` on the infotainment CAN interface. It sends when the
target changes and rearms after radio wake or observed inhibition; there is no
periodic brightness heartbeat. Listen-only and Flashing Mode inhibit sending.
Queue success is not a hardware acknowledgment. Vehicle behavior still needs
an in-car check with this build.

## Developer preview

Run `npm run build` in `hudiy_dataview` to rebuild all three apps and regenerate
the shared metadata. `management-preview.html` is an explicit sample fixture
for layout checks; the production app always uses the real API.
