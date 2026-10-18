#!/bin/sh
# Undo the boot tuning in boot-tuning.md. Run as the desktop user (uses sudo), then reboot.
# Created files are removed; edited files are put back to the stock lines.
# Not undone: the EEPROM update and DISABLE_HDMI (firmware rollback is a deliberate step),
# the duplicate/nonexistent config.txt lines that were removed, the eth0 netplan -> keyfile move (NM makes its own wired profile), the RNS-E rnse-late split (install.sh).
set -x
U=$(id -un)
C=/boot/firmware/config.txt
sudo sed -i 's/^camera_auto_detect=0/camera_auto_detect=1/; s/^display_auto_detect=0/display_auto_detect=1/; s/^auto_initramfs=0/auto_initramfs=1/; /^kernel=kernel_2712_raw.img$/d; /^force_eeprom_read=0$/d' $C
sudo sed -i 's/ plymouth.enable=0//' /boot/firmware/cmdline.txt
sudo rm -f /etc/kernel/postinst.d/zz-boottuning-raw-kernel /boot/firmware/kernel_2712_raw.img

sudo systemctl unmask systemd-binfmt.service proc-sys-fs-binfmt_misc.automount accounts-daemon.service rp1-test.service sshswitch.service
sudo systemctl enable cups-browsed.service rpcbind.service rpcbind.socket nfs-blkmap.service nfs-client.target
sudo rm -f /etc/systemd/system.conf.d/99-boottuning-stop-timeout.conf /etc/systemd/user.conf.d/99-boottuning-stop-timeout.conf
sudo rm -f /etc/systemd/system/systemd-user-sessions.service
sudo rm -f /etc/systemd/system/getty@tty1.service.d/99-boottuning-delay.conf
sudo loginctl disable-linger "$U"

sudo rm -f /usr/sbin/netplan; sudo dpkg-divert --rename --remove /usr/sbin/netplan

sudo sed -i 's/,noauto,x-systemd.automount,x-systemd.idle-timeout=30//' /etc/fstab
sudo sed -i 's/^Mechanism=zram$/#Mechanism=auto/' /etc/rpi/swap.conf
sudo rm -f /etc/systemd/system-generators/cloud-init-generator /etc/systemd/system-generators/rpi-swap-generator
sudo rm -rf /etc/systemd/zram-generator.conf.d/20-rpi-swap-zram0-ctrl.conf /etc/systemd/system/dev-zram0.swap /etc/systemd/system/swap.target.wants/dev-zram0.swap /etc/systemd/system/systemd-zram-setup@zram0.service.d

sudo sed -i '/^session-wrapper=\/usr\/local\/bin\/boottuning-session-wrapper$/d' /etc/lightdm/lightdm.conf
sudo rm -f /usr/local/bin/boottuning-session-wrapper
printf '%s\n' '/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &' '/usr/bin/lwrespawn /usr/bin/wf-panel-pi &' '/usr/bin/kanshi &' '/usr/bin/lxsession-xdg-autostart' | sudo tee /etc/xdg/labwc/autostart >/dev/null
P=$HOME/.config/pcmanfm/default/desktop-items-0.conf
sed -i 's/^wallpaper_mode=.*/wallpaper_mode=crop/; s/^desktop_bg=.*/desktop_bg=#d6d3de/; s/^desktop_shadow=.*/desktop_shadow=#d6d3de/; s/^show_trash=.*/show_trash=1/; s/^show_mounts=.*/show_mounts=1/' "$P"
rm -rf "$HOME/.local/share/icons/invisible"
sed -i '/^XCURSOR_THEME=invisible$/d; /^XCURSOR_SIZE=24$/d' "$HOME/.config/labwc/environment"
echo '$HOME/.hudiy/share/hudiy_run.sh' > "$HOME/.config/labwc/autostart"
rm -f "$HOME/.local/bin/hudiy_startup_fast.sh"

sudo systemctl disable boot-readahead.service 2>/dev/null
sudo rm -f /etc/systemd/system/boot-readahead.service /usr/local/sbin/boot-readahead /usr/local/sbin/boot-readahead-relist
sudo rm -rf /etc/boottuning /usr/local/lib/boottuning
sudo sed -i 's/ trace_event=filemap:mm_filemap_add_to_page_cache trace_buf_size=32M//' /boot/firmware/cmdline.txt

sudo systemctl daemon-reload; echo "Reverted. Reboot to apply."
