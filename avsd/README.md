# A/V over SD

Sends Hudiy's screen and audio to the RNS-E through a Teensy in the SD slot, instead of the analog outputs. This folder is the Pi side and its settings and update app. It works with or without the rest of this repo.

```
Hudiy -> wlcap -> rnv3enc -> avlink -> USB -> Teensy -> SD slot -> RNS-E sdstream -> display + DSP
```

## Install

Needs a Raspberry Pi 5 with Hudiy, a Teensy 4.1 with the SD emulator wiring, and an RNS-E running the sdstream firmware. Unplug any HDMI display.

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/DSparks156x/RNS-E-Hudiy.git
```

```bash
git -C RNS-E-Hudiy sparse-checkout set avsd
```

```bash
bash RNS-E-Hudiy/avsd/install.sh
```

Reboot. **A/V over SD** is in the Hudiy menu under RNS-E. If you restore Hudiy's configs, run the install again to get it back.

Already have the full RNS-E-Hudiy install? Run `bash avsd/install.sh` once from a checkout to enable it. It then updates with **Update RNS-E**.

## The app

Port 5005. Anyone on the Pi's network can watch. Only Hudiy on the Pi can change things.

- **Status:** what the chain is doing, including what it is waiting for.
- **Settings:** press to change, turn the knob, press to confirm. RETURN puts the old value back. **Apply** restarts the chain with the new values until the next reboot, so a reboot undoes a bad one. **Save** keeps them.
- **Logs:** live from the chain. Saved in `~/avsd/logs`.
- **Update:** RNS-E firmware, Teensy firmware, this app and the chain.

With the full install, the file portal has **RNS-E firmware** for uploads and **A/V over SD logs** for downloads. Without it, copy files to `~/rnsefw` yourself.

## RNS-E firmware

1. Upload the sector image, named like `sector_96.bin`.
2. Turn the ignition on. `can0` is listen-only while it is off.
3. Open **Update**, select the file, press **Flash**.

The screen goes off for about a minute, then comes back by itself. A phone on the Pi's Wi-Fi can watch at `http://<Pi address>:5005`, Update page. The report is saved in `~/avsd/logs`.

Before anything is sent, the app works out the boot ROM's checksum for each module the file touches, and refuses if it wouldn't match. The OSM runs over sectors 32 to 53 and its checksum is only in sector 32, so its sectors usually have to go together, like 44 and 53. That means reading the old sector over CAN the first time, about 6 minutes each. A file in `~/rnsefw` with the same CRC as the live sector saves that read. Sector 96 isn't in a checked module.

**Check** compares the live flash to the file. **Dry run** does everything but the flash. Both stop the chain for a few seconds.

Update order: the RNS-E first, then the Pi. To go back: the Pi first, then the RNS-E. The decoder before CRC `0696DDE4` rejects the current encoder's R3 stream, which means no video.

If the RNS-E won't boot, reinstall from the disc.

## Updating the Pi side

With the full install, **Update RNS-E** does it. On its own, **Update A/V over SD** does. Either one quits Hudiy, which drops the hotspot so the Pi can join your phone hotspot or home Wi-Fi. It waits for GitHub, installs and reboots. After the reboot the app checks that frames are flowing, and goes back to the previous version if they aren't.

## Layout on the Pi

| Path | What |
|---|---|
| `~/avsd/current`, `previous` | Links to the running and last version in `~/avsd/releases` |
| `~/avsd/avsd.env` | Saved settings, `NAME=value`. The chain reads it at start. Delete a line for the default |
| `$XDG_RUNTIME_DIR/avsd-trial.env` | Applied, not saved. Gone at reboot |
| `~/avsd/car/DISABLE` | Keeps the chain down across a reboot |
| `~/avsd/logs` | Chain logs and operation reports |
| `~/rnsefw` | RNS-E sector images |
| `$XDG_RUNTIME_DIR/avsd` | The chain's live logs, gone at power-off |

`systemctl --user status avsd-chain avsd-app`

## Not tried yet

- Flashing the RNS-E from the Pi. The protocol is ported from the PC tools and tested against a simulated unit.
- The update terminal on the RNS-E screen with Hudiy quit.
