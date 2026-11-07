#!/bin/bash
# One screen of car checks. Read-only. Run on the Pi.
export XDG_RUNTIME_DIR=/run/user/$(id -u)
L=$XDG_RUNTIME_DIR/avsd
echo "== service";   systemctl --user --no-pager -n 0 status avsd-chain.service | sed -n 1,4p
echo "== chain log"; journalctl -b _SYSTEMD_USER_UNIT=avsd-chain.service -n 8 --no-pager -o cat
echo "== avlink";    tail -n 2 "$L/live.log" 2>/dev/null | cut -c1-220
echo "== capture";   tail -n 1 "$L/cap.log" 2>/dev/null | cut -c1-160
echo "== priority";  cat "$L/rt.log" 2>/dev/null | tail -n 3
echo "== governor";  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo "== power";     vcgencmd get_throttled; vcgencmd measure_temp
echo "== audio";     pactl get-default-sink; pactl list short sinks | cut -c1-90
echo "== teensy";    ls -l /dev/serial/by-id/ 2>/dev/null | grep -i teensy
echo "== wayvnc";    pgrep -a wayvnc || echo off
echo "== outputs";   WAYLAND_DISPLAY=wayland-0 wlr-randr 2>/dev/null | grep -E '^[A-Za-z]|current' | cut -c1-70
