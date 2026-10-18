# Pi setup

How my car Pi is set up outside this repo's `install.sh`, and the boot tuning that got power-on → Hudiy from ~19.1 s to ~11.3 s.
Nothing here is applied by `install.sh`. Do it by hand, and only if your hardware matches or you know what each step does.

- [preexisting.md](preexisting.md): everything done before the tuning (EEPROM, config.txt/cmdline.txt, EDID, packages, Hudiy/NoiseTorch), with the order to rebuild from a fresh image.
- [boot-tuning.md](boot-tuning.md): every boot/shutdown change, why, what it saved, how to apply it, and what was tested and dropped.
- [files/](files/): the real tuned files, at their target paths. `files/home/pi` is the desktop user's home.
- [tools/](tools/): boot readahead (source, list builder) and the measuring scripts.
- [revert.sh](revert.sh): undo the tuning.

## My setup
- Raspberry Pi 5 (2 GB), official active cooler, 256 GB NVMe (SK Hynix BC711, DRAM-less), PCIe gen 3.
- Raspberry Pi OS trixie 64-bit desktop (image 2025-12-04), labwc session, autologin as `pi`.
- Hudiy 2.24, this repo's services.
- CarPiHat Pro 5 (CAN, power latch on GPIO 25), FiiO KA11 USB DAC.
- RNS-E 193 over HDMI → VGA, custom EDID (800x480), r21 RNS-E firmware.

Some of it is specific to that: the CarPiHat GPIO/CAN lines, the EDID, `zram-size`, the PARTUUIDs (masked as `xxxxxxxx` in files/), the NVMe device name in the tools.

## Order
1. Fresh image and the pre-existing setup: [preexisting.md](preexisting.md#order-to-reproduce-this-pi-from-a-fresh-image), including `sudo ./install.sh`.
2. Boot tuning, top to bottom in [boot-tuning.md](boot-tuning.md). Reboot and check the picture, sound and Hudiy hotspot after the firmware/config.txt part and again at the end.
3. Boot readahead last: its list has to be captured from the finished setup.
4. After Hudiy, RNS-E or big apt updates: rebuild the readahead list, and check Hudiy's `hudiy_startup.sh` against `~/.local/bin/hudiy_startup_fast.sh`.

## Results
Power-on to Hudiy binary start (firmware "Starting OS" + uptime clock), averages:

| | before | after |
|---|---|---|
| Firmware "Starting OS" | 9.78 s | 6.78 s |
| Kernel | 1.15 s | 0.88 s |
| lightdm start | ~5.2 s | 3.1 s |
| labwc (desktop) start | 6.80 s | 3.58 s |
| Hudiy binary start (uptime) | 9.35 s | 4.48 s |
| **Power-on → Hudiy launch** | **~19.1 s** | **~11.3 s** |
| Shutdown | 10.6 s | ~5 s |

Details and the in-between steps are in [boot-tuning.md](boot-tuning.md#results-uptime-clock-unless-noted).

## Not in the repo
- The readahead list (`/etc/boottuning/readahead.list`): machine-specific, build it with `boot-readahead-relist`.
- The rpi-eeprom .debs: `apt` or archive.raspberrypi.com.
- Boot traces and test lists: regenerate with `boot-readahead-relist arm`.
- Wi-Fi profiles, SSH keys, hostnames.
