# Boot and shutdown tuning (2026-10-18)

Everything changed on the reference Pi to cut power-on → Hudiy launch from ~19.1 s to ~11.3 s.
Done on top of the [pre-existing setup](preexisting.md) and the RNS-E `install.sh`.
The real installed files are in [files/](files/), at their target paths. `files/home/pi` is the desktop user's home.
Undo with [revert.sh](revert.sh).

Tags: **[boot]** faster boot, **[gap]** what shows on screen between boot and Hudiy, **[shutdown]** shutdown time.

## Baseline (before any change)
- Firmware "Starting OS": 9781 ms (`sudo vclog -m`)
- systemd: 1.146 s kernel + 21.881 s userspace (graphical.target held up by dis_* `sleep 10` x2)
- labwc start ~6.8 s, hudiy binary ~9.35 s (uptime clock)
- lightdm blocked behind network.target -> NetworkManager (2.9 s, ~2 s netplan stall)
- DefaultTimeoutStopSec = 90 s

## Firmware and bootloader

- **[boot] Bootloader EEPROM 2025-11-05 -> 2026-09-25** (default channel; turbo clocks before kernel load). Installed rpi-eeprom 28.33-1 + rpi-eeprom-images 28.33-1. Get them with internet up:
  ```
  sudo apt update && sudo apt install --only-upgrade rpi-eeprom rpi-eeprom-images
  sudo rpi-eeprom-update -a && sudo reboot
  ```
  The .debs are also on archive.raspberrypi.com (check the SHA256 against the archive index if you download by hand). Rollback: the 2025-11-05 image is in rpi-eeprom_28.9-1_all.deb (stable/pieeprom-2025-11-05.bin), flash with `sudo rpi-eeprom-update -d -f <file>`. Not in revert.sh: firmware rollback is a deliberate step.
- **[boot] EEPROM `DISABLE_HDMI=1`** (`sudo rpi-eeprom-config --edit`): no bootloader diagnostics screen. Bootloader stage 5.28 -> 4.74 s, firmware hand-off 7.33 -> 6.74 s.
- Nothing else to gain in the bootloader. ~4.5 s of it is BootROM + LPDDR4X training before any configurable step runs; that matches Raspberry Pi's own CM5 reference and can't be cut.
- **[boot] config.txt** (current file: [files/boot/firmware/config.txt](files/boot/firmware/config.txt)):
  - `camera_auto_detect=0`, `display_auto_detect=0`: no CSI camera / DSI panel, skips firmware I2C probing.
  - `auto_initramfs=0`: nvme/ext4/pcie are built into the kernel. Firmware ~-1.0 s, kernel ~-0.2 s.
  - removed duplicate `dtoverlay=vc4-kms-v3d` (the `,noaudio` one stays, so video/audio unchanged), nonexistent `dtoverlay=spi-bcm2835-overlay`, duplicate `dtparam=spi=on` (~0.13 s).
  - `kernel=kernel_2712_raw.img` under `[all]`: uncompressed copy of the kernel; firmware gunzip of the stock image cost ~0.4 s. Kept current by [zz-boottuning-raw-kernel](files/etc/kernel/postinst.d/zz-boottuning-raw-kernel), which drops the `kernel=` line if it ever fails. Install the hook first, then create the first copy and add the line:
    ```
    sudo install -m 755 files/etc/kernel/postinst.d/zz-boottuning-raw-kernel /etc/kernel/postinst.d/
    sudo sh -c 'gunzip -c /boot/firmware/kernel_2712.img > /boot/firmware/kernel_2712_raw.img'
    echo kernel=kernel_2712_raw.img | sudo tee -a /boot/firmware/config.txt
    ```
  - `force_eeprom_read=0` under `[all]`: CarPiHat has no HAT ID EEPROM. ~0-15 ms, within noise; kept because it is free.
- **[boot] cmdline.txt**: added `plymouth.enable=0`. The spinner segfaulted on every boot/shutdown on this setup, and without initramfs it never showed anyway. Current line: [files/boot/firmware/cmdline.txt](files/boot/firmware/cmdline.txt) (put your own PARTUUID back).

## systemd and system services

- **[boot] Masked** `systemd-binfmt.service proc-sys-fs-binfmt_misc.automount` (only registered python .pyc-as-executable; cost 1.0 s on the sysinit critical path waiting for binfmt_misc to load), `accounts-daemon.service` (lightdm waited 0.6 s for it, and it waited for polkit; lightdm falls back to /etc/passwd), `rp1-test.service` (only writes an Xorg config; the session is labwc/Wayland) and `sshswitch.service` (only enables SSH when /boot/firmware/ssh exists; ssh is already enabled).
  ```
  sudo systemctl mask systemd-binfmt.service proc-sys-fs-binfmt_misc.automount accounts-daemon.service rp1-test.service sshswitch.service
  ```
- **[boot/shutdown] Disabled** printing + NFS, unused in the car: `sudo systemctl disable cups-browsed.service rpcbind.service rpcbind.socket nfs-blkmap.service nfs-client.target` (cups itself was already off, see preexisting.md).
- **[boot] Masked generators**: `/etc/systemd/system-generators/cloud-init-generator -> /dev/null` (`/etc/cloud/cloud-init.disabled` exists, so it generated nothing). `rpi-swap-generator -> /dev/null` too, see swap below.
  ```
  sudo mkdir -p /etc/systemd/system-generators
  sudo ln -s /dev/null /etc/systemd/system-generators/cloud-init-generator
  ```
- **[shutdown] `DefaultTimeoutStopSec=10s`** (was 90 s) for system and user managers: [system.conf.d](files/etc/systemd/system.conf.d/99-boottuning-stop-timeout.conf), [user.conf.d](files/etc/systemd/user.conf.d/99-boottuning-stop-timeout.conf).
- **[boot] [systemd-user-sessions.service](files/etc/systemd/system/systemd-user-sessions.service)** override without `After=network.target` (lightdm was waiting ~1.6 s on NetworkManager). It is a copy of the packaged unit with that one word removed; if systemd changes the unit, recopy from `/usr/lib/systemd/system/` and remove it again.
- **[gap] [getty@tty1 drop-in](files/etc/systemd/system/getty@tty1.service.d/99-boottuning-delay.conf)**: tty1 autologin starts 10 s later so its prompt can't flash before the desktop VT is up.
- **[boot] `loginctl enable-linger <user>`**: user manager + PipeWire start at boot instead of inside the lightdm login (logind waited ~0.35 s for user@1000 to finish starting).

## NetworkManager / netplan

- **[boot] eth0 moved from netplan to a native NM keyfile** ([eth0-dhcp.nmconnection](files/etc/NetworkManager/system-connections/eth0-dhcp.nmconnection), mode 600). The netplan profile was `/etc/netplan/90-NM-<uuid>.yaml`; delete it. NM was re-saving it every boot -> 3x (netplan generate + daemon-reload) = ~2 s stall before NM ready, and lightdm waits on NM. Any Wi-Fi client profiles that live in netplan need the same move (keep the PSK in the keyfile, never in this repo).
- **[boot] netplan wrapper**: `/usr/sbin/netplan` diverted to `netplan.distrib`, replaced by [a wrapper](files/usr/sbin/netplan) that skips the bare `netplan generate` NM runs at every start when there is no netplan YAML / netplan NM profile (Python start-up + generate + udevadm reload + systemctl daemon-reload, ~0.8 s; the reload freezes systemd while the desktop starts). Everything else passes through.
  ```
  sudo dpkg-divert --local --rename --divert /usr/sbin/netplan.distrib --add /usr/sbin/netplan
  sudo install -m 755 files/usr/sbin/netplan /usr/sbin/netplan
  ```
  Revert: `sudo rm /usr/sbin/netplan && sudo dpkg-divert --rename --remove /usr/sbin/netplan`
- Hudiy must not start before NM is on D-Bus: it does NOT recover if NetworkManager appears after it starts (hotspot never comes up). Tested. Since lightdm no longer waits for NM, the fast startup script waits for it (below).

## Filesystems and swap

- **[reliability+boot] /etc/fstab**: `/boot/firmware` is `noauto,x-systemd.automount,x-systemd.idle-timeout=30` ([fstab](files/etc/fstab), with your own PARTUUIDs). Mounted only when something touches it and unmounted again after 30 s, so a power cut almost never hits it mounted (the FAT volume was flagged "not properly unmounted" at boot). Also off the boot critical path. A FAT dirty bit that is already set: `sudo fsck.vfat -a <boot partition>` once.
- **[boot] /etc/rpi/swap.conf**: `Mechanism=zram` (was auto = zram+file). Swap was 0 MB used of 2 GB; drops the 2 GB /var/swap writeback file, its loop device and resize service from the sysinit critical path. zram swap stays as a RAM safety net.
- **[boot] Static zram units**: `/etc/systemd/system-generators/rpi-swap-generator -> /dev/null`, replaced by static copies of its output for Mechanism=zram: [20-rpi-swap-zram0-ctrl.conf](files/etc/systemd/zram-generator.conf.d/20-rpi-swap-zram0-ctrl.conf), [dev-zram0.swap](files/etc/systemd/system/dev-zram0.swap) (+ `swap.target.wants` link), [bindings.conf](files/etc/systemd/system/systemd-zram-setup@zram0.service.d/bindings.conf). `zram-size=2006` is this Pi's RAM in MiB (capped at 2048); set yours from `free -m`, or copy what the generator wrote to /run/systemd/generator first. If swap.conf or the RAM size ever changes, revert this first: the static files don't follow swap.conf.
  ```
  sudo ln -s /dev/null /etc/systemd/system-generators/rpi-swap-generator
  sudo mkdir -p /etc/systemd/system/swap.target.wants
  sudo ln -s ../dev-zram0.swap /etc/systemd/system/swap.target.wants/dev-zram0.swap
  ```

## Desktop session

- **[boot] Lean lightdm session wrapper**: `session-wrapper=/usr/local/bin/boottuning-session-wrapper` under `[Seat:*]` in /etc/lightdm/lightdm.conf. [The wrapper](files/usr/local/bin/boottuning-session-wrapper) replaces /etc/X11/Xsession (~0.5 s of Xsession.d scripts for X11): keeps the session bus address, /etc/profile + ~/.profile, `QT_QPA_PLATFORMTHEME`.
  ```
  sudo install -m 755 files/usr/local/bin/boottuning-session-wrapper /usr/local/bin/
  sudo sed -i '/^\[Seat:\*\]/a session-wrapper=/usr/local/bin/boottuning-session-wrapper' /etc/lightdm/lightdm.conf
  ```
- **[boot] Desktop extras deferred**: [/etc/xdg/labwc/autostart](files/etc/xdg/labwc/autostart) starts pcmanfm-pi, kanshi and lxsession-xdg-autostart (polkit agent, keyring, pwrkey, xdg autostart entries) 10 s after login in a background subshell, so they don't compete with labwc/Hudiy for the disk. kanshi was a no-op anyway here. wf-panel-pi (taskbar) is off. The file is a conffile of rpd-wayland-core; dpkg keeps local edits on upgrade. Staged: most of these dropped, and lightdm replaced, [below](#no-splash-no-lightdm-staged-2026-10-29-not-yet-boot-tested).
- **[gap] Black desktop**: [desktop-items-0.conf](files/home/pi/.config/pcmanfm/default/desktop-items-0.conf): solid black, no trash/mount icons (was sunrise.jpg wallpaper).
- **[gap] Invisible cursor**: theme from [tools/make-invisible-cursor.sh](tools/make-invisible-cursor.sh) (run as the desktop user) at `~/.local/share/icons/invisible`, enabled by `XCURSOR_THEME=invisible` + `XCURSOR_SIZE=24` in [~/.config/labwc/environment](files/home/pi/.config/labwc/environment).

## Hudiy start

- **[boot] [~/.local/bin/hudiy_startup_fast.sh](files/home/pi/.local/bin/hudiy_startup_fast.sh)**: copy of Hudiy's `hudiy_startup.sh`, changes marked `[bt]`:
  - `sleep 1` replaced by waiting (max 3 s) until the USB DAC is the default sink. Echo-cancel attaches to the default sink, so this is also more robust.
  - waits (max 5 s) for `org.freedesktop.NetworkManager` on D-Bus right before the hudiy binary.
  - touches `/run/rnse_control/hudiy-started` after launching Hudiy, which starts `rnse-late.target` (install.sh sets that up).
  - per-step timing in `/run/user/<uid>/hudiy-startup.log`.

  [~/.config/labwc/autostart](files/home/pi/.config/labwc/autostart) runs splash with this script instead of `hudiy_run.sh` (staged: without splash, [below](#no-splash-no-lightdm-staged-2026-10-29-not-yet-boot-tested)). Vendor `hudiy_startup.sh` and `hudiy_run.sh` are byte-identical from 2.16 to 2.24, so no port was needed; re-check after Hudiy updates.
- RNS-E services: the late split (rnse-late.target/.path/.timer), lazy numpy/PIL/OpenCV imports and no DIS start sleeps are in the repo `install.sh` and services now, not a local change. OpenCV alone was ~150 MB of libraries paged in at 3 s (import 941 -> 192 ms).

## No splash, no lightdm (staged 2026-10-29, not yet boot-tested)

Staged on the reference Pi for the next boot; the files in files/ are already the staged versions. Expected gain ~1 s (splash) + ~0.5-1 s (lightdm).

- **[boot] No Hudiy splash**: [~/.config/labwc/autostart](files/home/pi/.config/labwc/autostart) runs `hudiy_startup_fast.sh` directly, same exports. splash only draws and waits (~1.5 s) on a boost interprocess condition in /dev/shm (`hudiy#launch#condition`, `sem.hudiy#launch#mutex`) that Hudiy signals once it's up. Hudiy opens it with `sem_open(name, 0)`; if it's missing it logs `failed to initialize interprocess routines` and carries on (checked in the 2.24 disassembly). splash also D-Bus-activated the desktop portals at 4.4 s.
- **[boot] labwc from systemd instead of lightdm**: [hudiy-session.service](files/etc/systemd/system/hudiy-session.service) with `Alias=display-manager.service`. User=pi on tty7, `PAMName=hudiy-session` ([PAM file](files/etc/pam.d/hudiy-session) = the session part of lightdm-autologin), so pam_systemd registers an active wayland session on seat0/VT 7 (wireplumber and udisks need that). `chvt 7` first, as lightdm did. Runs `boottuning-session-wrapper /usr/bin/labwc-pi`, the same command lightdm ran. lightdm stays installed.
- **[boot] Fewer desktop extras**: [/etc/xdg/labwc/autostart](files/etc/xdg/labwc/autostart) still waits 10 s, then runs only pwrkey (`systemd-inhibit --what=handle-power-key gtk-nop`), `create_xauth`, the activation-environment update, and [usb-automount](files/usr/local/bin/usb-automount). pcmanfm-pi, kanshi and lxsession-xdg-autostart are gone. usb-automount is ~20 lines of Gio VolumeMonitor: mounts USB sticks at start and on plug-in at /media/pi/<label>, like pcmanfm did. It has to run inside the session (polkit). udiskie would pull ~50 packages.
- **[boot] Portals masked**: `xdg-desktop-portal`, `-gtk`, `-wlr` user units -> /dev/null. Nothing in the car uses them; they also dragged in gvfsd.
- **[safety] Dead-man switch**: [hudiy-session-guard.service](files/etc/systemd/system/hudiy-session-guard.service) runs [hudiy-session-guard](files/usr/local/sbin/hudiy-session-guard) at every boot. At 45 s uptime, if no `~/.hudiy/share/hudiy` process is running, it goes back to lightdm, the splash autostart and unmasked portals, and starts lightdm, so the hotspot and SSH come back on their own. `--dry-run` and `--dry-run --assume-dead` test it. Log: `journalctl -t boottuning-guard`. Disable it once a few boots are fine.

```
sudo install -m 644 files/etc/systemd/system/hudiy-session.service files/etc/systemd/system/hudiy-session-guard.service /etc/systemd/system/
sudo install -m 644 files/etc/pam.d/hudiy-session /etc/pam.d/
sudo install -m 755 files/usr/local/sbin/hudiy-session-guard /usr/local/sbin/
sudo install -m 755 files/usr/local/bin/usb-automount /usr/local/bin/
cp -a ~/.config/labwc/autostart ~/boot-tuning/backup/__home__pi__.config__labwc__autostart.pre-session
cp -a /etc/xdg/labwc/autostart ~/boot-tuning/backup/__etc__xdg__labwc__autostart.pre-session
install -m 644 files/home/pi/.config/labwc/autostart ~/.config/labwc/autostart
sudo install -m 644 files/etc/xdg/labwc/autostart /etc/xdg/labwc/autostart
mkdir -p ~/.config/systemd/user
for u in xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-wlr; do ln -sfn /dev/null ~/.config/systemd/user/$u.service; done
sudo systemctl disable lightdm.service
sudo systemctl enable hudiy-session.service hudiy-session-guard.service
```
The guard restores from the two `.pre-session` backups, so make them first.

## Boot readahead

**[boot]** boot-readahead.service ([unit](files/etc/systemd/system/boot-readahead.service): `DefaultDependencies=no`, `WantedBy=sysinit.target`, nothing orders after it; starts at ~1.3 s, done by ~3.3 s) runs `/usr/local/sbin/boot-readahead` ([tools/boot-readahead.c](tools/boot-readahead.c)), which preads the ranges in `/etc/boottuning/readahead.list` with 8 threads (~484 MB, 3.4k files). The list is the boot working set up to 15 s, from a boot trace of `filemap:mm_filemap_add_to_page_cache`, page ranges merged when <64 KB apart, sorted by physical block (filefrag), so the DRAM-less NVMe sees large mostly-sequential reads instead of ~10k scattered small ones. Hudiy binary start 5.70 s -> 4.48 s on average.

The list is machine-specific and not in the repo. Install and build it:
```
sudo apt install gcc
gcc -O2 -pthread -o boot-readahead tools/boot-readahead.c
sudo install -m 755 boot-readahead tools/boot-readahead-relist /usr/local/sbin/
sudo install -D -m 755 tools/ra-mklist.py /usr/local/lib/boottuning/ra-mklist.py
sudo install -m 644 files/etc/systemd/system/boot-readahead.service /etc/systemd/system/
sudo mkdir -p /etc/boottuning && sudo systemctl enable boot-readahead.service
sudo boot-readahead-relist arm; sudo reboot
# wait ~60 s after the desktop is up
sudo boot-readahead-relist build
```
`arm` adds the trace options to cmdline.txt and creates `/etc/boottuning/capture` (readahead skipped on that boot); `build` stops the trace, restores cmdline.txt, writes the list (previous one kept as readahead.list.old). Without a list the service does nothing.

REGENERATE after Hudiy / RNS-E / big apt updates (`arm`, reboot, `build`). A stale list only wastes some reads; missing files are skipped.

| | without | readahead, 512 KB gap, 564 MB | readahead, 64 KB gap, 487 MB (kept) |
|---|---|---|---|
| sysinit.target | 2.47 s | 2.75 s | 2.66 s |
| lightdm start | 2.93 s | 3.45 s | 3.11 s |
| labwc start | 3.89 s | 3.81 s | 3.58 s |
| Hudiy binary start | 5.70 s (5.53-5.79) | 4.64 s (4.51-4.80) | 4.48 s (4.32-4.59) |
| NVMe at 60 s | 10.8k reads, 538 MB | 8.8k reads, 663 MB | 8.7k reads, 616 MB |

One sitting, 4 boots each, alternating. Capture (trace) boots without readahead: 5.73 / 5.98 s. Standalone cold-cache read of the list: first-access order 2.6-3.0 s, disk order 1.55 s (8 threads; 4 and 16 no better). Early units (sysinit/lightdm) start ~0.2 s later because of the competing reads, but everything from labwc on is earlier.

## Results (uptime clock unless noted)
A = everything above except readahead, Hudiy 2.18 (4 boots). B = A + force_eeprom_read=0 + Hudiy 2.24 (3 boots). Averages.

| | before | first pass | A | B |
|---|---|---|---|---|
| Firmware "Starting OS" | 9781 ms | 6744 ms | 6795 ms | 6781 ms |
| Kernel | 1.15 s | 0.88 s | 0.88 s | 0.88 s |
| sysinit.target | | | 2.74 s | 2.71 s |
| lightdm start | ~5.2 s | 3.5 s | 3.28 s | 3.20 s |
| user@1000 | | | 4.11 s | 4.24 s |
| labwc (desktop) start | 6.80 s | 4.54 s | 4.13 s | 4.27 s |
| labwc autostart runs | | | 5.30 s | 5.81 s |
| Hudiy binary start | 9.35 s | 7.68 s | 6.01 s (5.82-6.39) | 6.85 s (6.76-6.92) |
| rnse-late.target | | | 6.04 s | 6.89 s |
| Power-on -> Hudiy launch (firmware + uptime) | ~19.1 s | ~14.4 s | ~12.8 s | ~13.6 s |
| NVMe reads at ~70 s uptime | | ~526 MB | 10.8k reads, 540 MB, 17.7 s total read wait | 10.8k reads, 541 MB, 24.4 s total read wait |
| Hudiy hotspot active | 13.2 s | 8.3-11 s | | |
| Shutdown | 10.6 s | ~5 s | | |

A vs B: same number of reads and bytes, but average read latency went 1.6 -> 2.25 ms. The slowdown already showed before the Hudiy updates, so it's the drive (SK Hynix BC711, DRAM-less), not Hudiy 2.24. NVMe at 33 C, no throttling. Everything before the Hudiy binary slowed by the same factor. Readahead (above) is what fixed it: with it, Hudiy starts at ~4.5 s uptime, ~11.3 s from power-on.

## Tested, not applied
- `overlay_prefix=ov/` with only the 7 used overlay files in /boot/firmware/ov/ (one tryboot boot): worked, but dtb_file -> Starting OS only went 1634 -> 1615 ms. The ~50 ms per overlay is apply time, not the directory scan. Not worth a kernel postinst hook and the stale-overlay risk.
- NVMe APST off (`nvme_core.default_ps_max_latency_us=0`): no change (reads still ~3.5 ms avg at boot).
- NVMe HMB on (`nvme.max_host_mem_size_mb=64` + `cma-128`): allocated fine, no real change; tail latency is the drive itself.
- `fstrim -av`: no change.
- Masking debugfs/tracefs/fusectl/mqueue mounts: no gain.
- Holding the 13 Python services back 8 s (one boot): Hudiy 8.30 -> 6.19 s, labwc 5.00 -> 3.67 s. Led to the rnse-late split and lazy imports in the repo.
- Starting Hudiy without waiting for NM: no hotspot. The wait is required.

## Not done / ideas
- Hudiy hotspot channelBandwidth 80MHz -> 20MHz would skip the wpa_supplicant neighbour scan (up to ~3 s).

## Measuring
- [tools/measure.sh](tools/measure.sh): one line per stage after a boot (firmware Starting OS, systemd-analyze, unit start times, labwc/hudiy process start, the fast-startup log, NVMe read totals).
- [tools/ioproc.py](tools/ioproc.py): top processes by bytes read.
- [tools/randread.py](tools/randread.py): raw random-read latency of the drive (edit `dev` for yours).
- `sudo vclog -m` for the bootloader/firmware stage, `systemd-analyze critical-chain`, `systemd-analyze plot > boot.svg`.
