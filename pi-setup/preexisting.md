# Pre-existing customisations (before the boot tuning)

Everything that was on the reference Pi before the [boot tuning](boot-tuning.md) started. Read-only survey done 2026-10-18.
boot-tuning.md covers everything after that; this file does not repeat it.

## Summary
- Base: Raspberry Pi OS trixie 64-bit desktop, image 2025-12-04 (`/etc/rpi-issue`), flashed with Raspberry Pi Imager on 2026-02-12 (hostname, user `pi`, SSH on, timezone, US keyboard, a Wi-Fi client network, Wi-Fi country US). Boots from NVMe.
- Hudiy installed 2026-02-12 23:06 (its installer pulled ~45 packages and wrote a few system files).
- RNS-E install.sh first run 2026-02-12 23:44, many runs since (latest 17d5879).
- Manual: EEPROM (boot order, PSU current), config.txt/cmdline.txt for the CarPiHat Pro 5 and the RNS-E EDID, the EDID file itself, NoiseTorch, labwc touch mapping, a few packages and dev tools.
- Origin is taken from file timestamps, /var/log/apt history, dpkg logs and ~/.bash_history. "Unknown origin" means none of these explain it.

Origins: **stock** = image or Imager customisation; **Hudiy** = Hudiy installer/updater; **install.sh** = this repo; **manual** = done by hand.

## Order to reproduce this Pi from a fresh image
1. Flash Raspberry Pi OS trixie 64-bit desktop with Raspberry Pi Imager. Customise: hostname, user `pi`, SSH on, timezone, keyboard, Wi-Fi, Wi-Fi country.
2. EEPROM: `sudo rpi-eeprom-config --edit`, set the values in [EEPROM](#eeprom). Reboot.
3. Install the EDID file to /usr/lib/firmware ([EDID](#edid-file)).
4. config.txt and cmdline.txt as in [Boot files](#boot-files). Reboot and check the picture.
5. Install Hudiy: run its installer (`run.sh` from the Hudiy download, see the Hudiy docs).
6. NoiseTorch for Hudiy's echo-cancel chain ([User files](#user-files)).
7. Clone this repo and run `sudo ./install.sh`. Answer the CAN prompts so the mcp2515 line matches the CarPiHat (8 MHz, interrupt 23), or add the line first so it skips the prompt.
8. Manual extras you want from [Packages](#packages) and [System files](#system-files).
9. Then everything in [boot-tuning.md](boot-tuning.md).

## EEPROM
Before tuning. Stock Pi 5 values: `BOOT_ORDER=0xf461`, no `PSU_MAX_CURRENT`.

| Item | What / why | Origin | Reproduce |
|---|---|---|---|
| `BOOT_ORDER=0xf416` | NVMe first, then SD, then USB, repeat | manual | `sudo rpi-eeprom-config --edit` |
| `PSU_MAX_CURRENT=5000` | Pi is powered through the CarPiHat, so it can't read the PSU; without this USB current is limited | manual | same |
| `POWER_OFF_ON_HALT=0`, `BOOT_UART=0` | stock defaults | stock | none |

Bootloader image itself was 2025-11-05 (updated in boot-tuning.md). `DISABLE_HDMI=1` is in boot-tuning.md.

## Boot files
The current files (after tuning) are in [files/boot/firmware](files/boot/firmware).

### config.txt, compared with the stock trixie file

| Line | What / why | Origin |
|---|---|---|
| `dtparam=i2c_arm=on`, `dtparam=i2s=on`, `dtparam=spi=on` (uncommented) | I2C, I2S, SPI on. SPI is needed for the mcp2515 | manual (install.sh also ensures `spi=on`) |
| `dtparam=audio=off` | no on-board audio; sound goes out the FiiO KA11 USB DAC | manual |
| `dtoverlay=dwc2,dr_mode=host` (in `[all]`) | USB-C port as host | manual |
| `usb_max_current_enable=1` | full USB current without a 5 A USB-C PSU | manual |
| `#dtoverlay=hifiberry-dacplus-std` | CarPiHat DAC, disabled | manual |
| `dtoverlay=vc4-kms-v3d,noaudio` | KMS without HDMI audio | manual |
| `gpio=25=op,dh` | CarPiHat Pro 5 power latch: GPIO 25 high at boot keeps the Pi powered | manual (CarPiHat) |
| `dtoverlay=gpio-poweroff,gpiopin=25,active_low` | drops GPIO 25 after halt so the CarPiHat cuts power | manual (CarPiHat) |
| `dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=23` | CarPiHat Pro 5 CAN controller (8 MHz crystal, IRQ on GPIO 23) | manual. install.sh would have added a different line (default 12 MHz / GPIO 25 + `spimaxfrequency`), so this one was there first |
| `dtparam=spi=on` (second copy), `dtoverlay=spi-bcm2835-overlay` | duplicate / nonexistent overlay | manual, removed in boot-tuning.md |
| `hdmi_edid_file=1`, `[HDMI:0]`, `hdmi_edid_filename=Rpi_RNSE_800x480i_EDID.bin`, `hdmi_group=1`, `hdmi_mode=7` | firmware-side EDID override and CEA mode 7 (480i). The .bin is not on the FAT partition, so the firmware can't load it; with KMS the kernel `drm.edid_firmware` is what sets the mode. Looks unused | manual |
| commented `hdmi_force_hotplug`, `hdmi_ignore_edid`, `hdmi_timings=1600 ...` | earlier experiments | manual |
| `disable_splash=1` | no rainbow screen | manual |
| `dtparam=pciex1_gen=3` | NVMe at PCIe gen 3 | manual |

Note: everything after `[HDMI:0]` up to `[cm4]` sits inside the `[HDMI:0]` section. It worked as is.

### cmdline.txt
Original:
```
console=serial0,115200 console=tty1 root=PARTUUID=xxxxxxxx-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash fastboot plymouth.ignore-serial-consoles logo.nologo vt.global_cursor_default=0 loglevel=0 cfg80211.ieee80211_regdom=US drm.edid_firmware=HDMI-A-1:Rpi_RNSE_800x480i_EDID.bin
```
Added by hand to the stock line: `fastboot logo.nologo vt.global_cursor_default=0 loglevel=0` (quiet boot, no logo or cursor) and `drm.edid_firmware=HDMI-A-1:Rpi_RNSE_800x480i_EDID.bin` (forces the RNS-E mode). `cfg80211.ieee80211_regdom=US` comes from Imager. Keep your own PARTUUID.

## EDID file
`drm.edid_firmware` loads `/usr/lib/firmware/Rpi_RNSE_800x480i_EDID.bin` (not package-owned, manual). It is not in this repo.

| File | Content | Date |
|---|---|---|
| `/usr/lib/firmware/Rpi_RNSE_800x480i_EDID.bin` (current) | 800x480 progressive, 31.96 MHz, htotal 1014, vtotal 525 (60 Hz). Copied from `~/Rpi_RNSE_800x480i_E2_htotal1014_15p97MHz.bin` | 2026-10-09 |
| `...EDID.bin.orig` | first version: 800x480 interlaced, 16.00 MHz, htotal 1016 | 2026-02-12 |
| `/boot/Rpi_RNSE_800x480i_EDID.bin` (+ `.orig`) | same two files on the root fs, not the FAT partition. Unused | same |

The name still says "i" but the file in use is progressive.

Reproduce (current file, SHA256 `afb548cd...7d19660c`):
```
echo 'AP///////wAhbQAAAQAAACUSAQOAAQF4Cg3JoFdHmCcSSEwAAAABAAEAAQABAAEAAQABAAEAfAwg1jDgLRAeSJMAkPAQAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAA/ABScGlFRElECiAgICAgAAAAEAAAAAAAAAAAAAAAAAAAAVsCAw5AIwl/B2UDDAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAhw==' | base64 -d | sudo tee /usr/lib/firmware/Rpi_RNSE_800x480i_EDID.bin >/dev/null
sha256sum /usr/lib/firmware/Rpi_RNSE_800x480i_EDID.bin   # afb548cdcca6da89203b80145c0884691df7e5a71552075a5ef2093d7d19660c
```
Original interlaced file (SHA256 `7a8cb66f...7d8c46fe`), base64:
`AP///////wAhbQAAAQAAACUSAQOAAQF4Cg3JoFdHmCcSSEwAAAABAAEAAQABAAEAAQABAAEAQAYg2DDgLRAgSJMAkPAQAACAAAAAEAAAAAAAAAAAAAAAAAAAAAAA/ABScGlFRElECiAgICAgAAAAEAAAAAAAAAAAAAAAAAAAARkCAw5AIwl/B2UDDAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAhw==`

## Packages
Image packages are stock. Everything installed after first boot, from `/var/log/apt/history.log*`:

| Date | Packages | Origin | Notes |
|---|---|---|---|
| 02-12 23:06 | `libboost-json1.83.0` | Hudiy (`run.sh`) | |
| 02-12 23:07 | Qt6/QML modules, qt6-wayland, gstreamer, ofono, bluez-obexd, gpsd, pulseaudio-utils, swh-plugins, libfftw3-*, librtlsdr0, libliquid1, libboost-* ...; removed `modemmanager` | Hudiy installer | |
| 02-12 23:44 onward | git, python3-can, can-utils, python3-zmq, protobuf, flask, PIL, numpy, opencv ... | install.sh | the install.sh apt list |
| 02-12 | pip (system): `websocket-client`, `eventlet` (+ greenlet, dnspython) in /usr/local/lib | install.sh | pip fallback when apt has no python3-websocket-client |
| 02-14 | `python3-rpi.gpio` (removed stock `python3-rpi-lgpio`) | older install.sh | RPi.GPIO 0.7.1 does not work on a Pi 5. Current install.sh no longer installs it; keep the stock rpi-lgpio on a new build |
| 02-14 | `cmake` | manual | to build cannelloni |
| 02-22 | `python3-eventlet`, `python3-gevent`, `python3-gevent-websocket` | manual | nothing in the repo imports them now (only `hudiy_dataview/app_mock.py`). Not needed |
| 03-01 | `xterm`, `foot` | manual | foot is now in install.sh (update terminal). xterm not needed |
| 03-04 | `libxcb-cursor0 libxcb-xinerama0` | manual, now install.sh | Hudiy needs them |
| 03-11 | `mosh` | manual | optional, remote shell |
| 03-11 | `qpwgraph` | manual | optional, PipeWire graph for audio debugging |
| 10-17 | rpi-eeprom 28.33 | boot-tuning.md | |

`apt install rustdesk`, `realvnc`, `nomachine` were tried and failed; nothing installed.

Built from source: `/usr/local/bin/cannelloni` (2026-02-14) from `~/Documents/cannelloni` (github.com/mguentner/cannelloni, CAN over UDP for sniffing from the PC). Manual, optional:
```
git clone https://github.com/mguentner/cannelloni.git && cd cannelloni && cmake -DCMAKE_BUILD_TYPE=Release . && make && sudo make install
```

## System files

| Item | What / why | Origin | Reproduce |
|---|---|---|---|
| hostname, `/etc/hosts`, user `pi`, groups, TZ, keyboard, Wi-Fi client profile, `cfg80211` regdom | Imager customisation via cloud-init (`/boot/firmware/user-data`, `network-config`) | stock (Imager) | Imager settings |
| `/etc/cloud/cloud-init.disabled` (02-13) | cloud-init off after first boot | stock (unverified) | none |
| `/etc/sudoers.d/010_pi-nopasswd` | passwordless sudo for pi | stock | none |
| `/etc/sudoers.d/rnse-manager` | Manager may start/stop project units | install.sh | |
| lightdm `autologin-user=pi`, `autologin-session=rpd-labwc`; getty@tty1 `autologin.conf` | desktop autologin | stock (desktop autologin; lightdm.conf touched 02-13, likely raspi-config boot behaviour) | `sudo raspi-config nonint do_boot_behaviour B4` |
| `/etc/udev/rules.d/99-hudiy.rules`: `SUBSYSTEM=="usb", ATTR{idVendor}=="*", ATTR{idProduct}=="*", MODE="0666", GROUP="plugdev"` | USB access for Android Auto | Hudiy | |
| `/etc/polkit-1/rules.d/50-ssh-allow-all.rules` | sudo group may control NetworkManager without a prompt (hotspot) | Hudiy | |
| `/etc/bluetooth/main.conf`: `ControllerMode = bredr` | classic Bluetooth only | Hudiy | |
| `/etc/plymouth/plymouthd.conf`: `Theme=spinner` | | Hudiy (timestamp) | moot: plymouth is off in boot-tuning.md |
| `ModemManager` masked, `modemmanager` removed; `ofono.service`, `ofono-fcc-unlock`, `gpsd.socket` enabled | ofono is the HFP backend | Hudiy | |
| `~/.config/wireplumber/wireplumber.conf.d/50-hudiy.conf`: `bluez5.hfphsp-backend = "ofono"`; empty `~/.config/pipewire/pipewire-pulse.conf.d/50-hudiy.conf` | | Hudiy | |
| `/etc/modules-load.d/uinput.conf`, `/etc/udev/rules.d/99-uinput.rules`, `/etc/systemd/network/80-can.network`, `systemd-networkd` (+ wait-online) enabled, fstab tmpfs lines, all project services | | install.sh | |
| `/etc/modules`: `i2c-dev` | | stock (raspi-config I2C) | |
| `bluetooth` group: `root` added (2026-10-08) | | install.sh run as root without sudo (usermod uses `$REAL_USER`) | not needed |
| `/etc/ssh/sshd_config`: `ClientAliveInterval 59`, `ClientAliveCountMax 3` (03-11) | keeps SSH over the hotspot alive | manual | add both lines, `sudo systemctl restart ssh` |
| `/etc/apt/apt.conf.d/10proxy` | created and removed again | manual | none |
| `NetworkManager-wait-online.service` disabled | `network-online.target.wants` was changed 2026-02-13 22:02 | manual (inferred) | `sudo systemctl disable NetworkManager-wait-online` |
| `cups.service`, `cups.socket`, `cups.path` disabled | printing off. boot-tuning.md only disabled cups-browsed | unknown origin | `sudo systemctl disable cups.service cups.socket cups.path` |
| `glamor-test`, `upower`, `rpi-eeprom-update`, `run-lock.mount`, `apt-listchanges.timer` disabled vs preset | | probably stock, unverified | check on a fresh image |
| `/usr/lib/netplan/00-network-manager-all.yaml` differs from package (2026-10-08; content is just `renderer: NetworkManager`) | | unknown origin | none |
| NM Wi-Fi client profiles | personal networks (nmtui) | manual | not part of the build. Hudiy makes its own "Hudiy" hotspot |
| `/etc/systemd/system/carpihat.service` (disabled) + `~/Services/pihat/carpihat.py` | CarPiHat ignition watcher (GPIO 12, shutdown after 10 s). Disabled; replaced by `features.power_management.gpio_shutdown` (pin 12) in config.json | manual (CarPiHat example) | not needed |
| no crontabs, no sysctl/modprobe changes | | | |

dpkg conffile differences in `/etc/login.defs`, `/etc/default/useradd`, `/etc/skel/.bashrc`, chromium/firefox prefs, avahi, initramfs.conf, `g_ether.conf`, labwc-greeter environment are all dated 2025-12-04 (image build): stock.

## User files

| Item | What / why | Origin | Reproduce |
|---|---|---|---|
| `~/.hudiy/` | Hudiy install (2.16 at the start, 2.24 now) and config | Hudiy; config JSONs from install.sh | |
| `~/.config/labwc/autostart` original: `$HOME/.hudiy/share/hudiy_run.sh` | starts Hudiy at login | Hudiy | |
| `~/noisetorch` (2026-03-11) + `~/.config/noisetorch/config.toml` (`Threshold = 95`) | Hudiy's `hudiy_startup.sh` runs `$HOME/noisetorch -i -s echo_cancel_source` (noise suppression after echo-cancel). Needs a capability | manual (per Hudiy) | download the NoiseTorch release binary to `~/noisetorch`, `chmod +x`, `sudo setcap 'CAP_SYS_RESOURCE=+ep' ~/noisetorch` |
| `~/.config/labwc/rc.xml`: `<touch deviceName="UsbHID SingWon-CTP-V1.18A" mapToOutput="HDMI-A-1" mouseEmulation="yes"/>` (also in `rcgreeter.xml`) | maps a USB touch panel to the HDMI output | manual (Control Centre touchscreen setting, 02-13) | only with that touch panel |
| `~/.config/labwc/environment` original: `XKB_DEFAULT_*` us/pc105 | | stock (Imager keyboard) | |
| `~/.config/kanshi/config`: HDMI-A-1 1920x1080 (+ `.bak` 720x480, `.init` 800x480) | Screen Configuration leftovers. No-op: the output has no 1920x1080 mode | manual (GUI) | not needed |
| `~/.config/pcmanfm/default/desktop-items-0.conf` original: sunrise wallpaper | | stock | |
| `~/hudiy_client`, `~/rns-e_can`, `~/dis_client`, `~/tp2`, `~/hudiy_dataview`, `~/hudiy_manager`, `~/flasher`, `~/config.json`, `~/vehicle_data`, `~/vag_protocols`, `~/tools`, `~/haldexfw`, `~/epsfw`, `~/exhaustfw` | project | install.sh | |
| `~/RNS-E-Hudiy` (git clone), `~/hudiy_installer`, `~/confbackup`, captures/logs, `~/Rpi_RNSE_800x480i_E2_htotal1014_15p97MHz.bin` | working files | manual | not needed except the EDID (above) |
| `~/.bashrc`, `~/.profile` | unchanged from skel | stock | |
| `~/.vnc` (03-11) | one-off `vncserver-virtual` session; VNC is off | manual | not needed |

## Not checked / limits
- Shell history is capped at 2000 lines and starts around 2026-02-22; earlier manual steps are inferred from timestamps.
- "Probably stock" service states were not compared against a freshly flashed image.
