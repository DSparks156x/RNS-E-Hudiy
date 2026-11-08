#!/bin/bash
# Car start of the A/V-over-SD chain, run by avsd-chain.service (systemd --user, restarts it on any exit).
# Waits for what the chain needs, then runs hud2.sh, which reads ~/avsd/avsd.env, and watches it:
# if any part dies or stops reporting, this script exits and systemd kills what is left and starts over.
A=$HOME/avsd
HERE=$(dirname "$(readlink -f "$0")")
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)} WAYLAND_DISPLAY=wayland-0
# tmpfs: the chain's fifos and logs stay off the SD card. rnv2enc's per-frame stats go nowhere.
export CHAINDIR=$XDG_RUNTIME_DIR/avsd
STALE_S=${AVSD_STALE_S:-20}     # avlink prints a STAT line every 5 s
say() { echo "avsd: $*"; }
# update_avsd.sh quits Hudiy to get off the hotspot, then shows its terminal through this chain.
# While this file exists a missing Hudiy is not a reason to stop. tmpfs, so a reboot clears it.
UPDATING=$XDG_RUNTIME_DIR/avsd-updating
updating() { [ -e "$UPDATING" ]; }

waitfor() {   # waitfor DESCRIPTION COMMAND...: retry for ever, one line every 30 s
  local what=$1 n=0; shift
  until "$@" >/dev/null 2>&1; do
    [ $((n % 30)) = 0 ] && say "waiting for $what"
    n=$((n + 1)); sleep 1
  done
  say "$what ok after ${n} s"
}
have_noop()  { wlr-randr 2>/dev/null | grep -q '^NOOP-1'; }
have_sink()  { pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fxq hudiy_equalizer_sink; }
have_teensy() { ls /dev/serial/by-id/usb-Teensyduino_SDemu_Touch_*-if00; }
port_free()  { ! fuser -s "$(ls /dev/serial/by-id/usb-Teensyduino_SDemu_Touch_*-if00 | head -1)"; }

waitfor "wayland socket" test -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
waitfor "pulse server" pactl info
waitfor "headless output NOOP-1" have_noop
hudiy_or_update() { updating || pgrep -x hudiy; }
waitfor "hudiy" hudiy_or_update
waitfor "sink hudiy_equalizer_sink" have_sink
# The music must run on the Pi's clock. A USB mic can drive, and every echo canceller links its mic to echo_cancel_sink, so a mic that is
# plugged in became the clock of the music avlink taps. The dome mic ran it more than 0.72% slow, past what the tick can follow: 1-2.5 s of
# padded silence per minute, then short pads heard as crackles (car log 2026-11-07 16:22-17:10, clean unplugged). A silent sink on the
# system clock, with a driver priority far above any device (2000), and the echo canceller's otherwise unconnected output on it, keeps the
# graph on the Pi clock; mics then follow, rate-matched by PipeWire. Lingers in PipeWire, so a chain restart finds it.
clock_sink() {
  pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fxq avsd_clock || \
    pw-cli create-node adapter '{ factory.name=support.null-audio-sink node.name=avsd_clock node.description=avsd-clock media.class=Audio/Sink audio.position=[FL FR] audio.rate=48000 node.driver=true priority.driver=50000 priority.session=0 object.linger=true }' >/dev/null
  for i in 1 2 3 4 5; do pactl list short sinks | awk '{print $2}' | grep -Fxq avsd_clock && break; sleep 0.2; done
  local ck ec
  ck=$(pactl list short sinks | awk '$2=="avsd_clock"{print $1}')
  [ -n "$ck" ] || return 1
  # "-" = present and already on avsd_clock; otherwise the indices to move
  ec=$(pactl -f json list sink-inputs 2>/dev/null | python3 -c 'import json,sys
e=[i for i in json.load(sys.stdin) if i.get("properties",{}).get("node.name")=="echo-cancel-playback"]
m=[str(i["index"]) for i in e if i["sink"]!='"$ck"']
print(" ".join(m) if m else ("-" if e else ""))')
  [ "$ec" = - ] && return 0
  for i in $ec; do pactl move-sink-input "$i" avsd_clock && say "avsd_clock: moved echo-cancel-playback $i back onto the Pi clock"; done
  [ -n "$ec" ]
}
waitfor "Pi clock driving the audio graph (avsd_clock)" clock_sink
waitfor "Teensy on USB" have_teensy
waitfor "Teensy port free" port_free

DEV=$(ls /dev/serial/by-id/usb-Teensyduino_SDemu_Touch_*-if00 | head -1)
export LINKDEV="--dev $DEV"
# The capture takes the first wl_output: HDMI, if a display or the old converter is plugged in, may not be what Hudiy draws on.
if wlr-randr 2>/dev/null | grep -q '^HDMI-A-'; then say "WARNING: an HDMI output is active; unplug the converter (CAR_INSTALL step 3)"; fi
mkdir -p "$CHAINDIR"
ln -sf /dev/null "$CHAINDIR/st.txt"
: > "$CHAINDIR/live.log"
: > "$CHAINDIR/enc.log"
# Keep logs across reboots: tmpfs is lost at power-off. About 2 MB/h. The newest 40 runs stay (3 files each).
LOGD=$A/logs; mkdir -p "$LOGD"; ls -1t "$LOGD"/*.log 2>/dev/null | tail -n +121 | xargs -r rm -f
STAMP=$(date +%Y%m%d-%H%M%S)-$(cut -c1-8 /proc/sys/kernel/random/boot_id)
tail -n +1 -F "$CHAINDIR/live.log" >> "$LOGD/$STAMP-live.log" 2>/dev/null &
tail -n +1 -F "$CHAINDIR/enc.log" >> "$LOGD/$STAMP-enc.log" 2>/dev/null &
tail -n +1 -F "$CHAINDIR/cap.log" >> "$LOGD/$STAMP-cap.log" 2>/dev/null &
say "starting chain on $DEV, logs in $CHAINDIR"
"$HERE/hud2.sh" 315360000 &
HUD=$!
trap 'kill $HUD 2>/dev/null; exit 0' TERM INT
sleep 6

alive() { [ -s "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
n=0
while :; do
  sleep 2
  # Every 10 s: keep the music on the Pi clock if Hudiy, WirePlumber or a replugged mic re-routed it (cheap no-op when it is in place)
  n=$((n+1)); [ $((n % 5)) -eq 0 ] && clock_sink 2>/dev/null
  why=
  kill -0 $HUD 2>/dev/null || why="hud2.sh ended"
  alive "$CHAINDIR/cap.pid" || why="wlcap gone"
  alive "$CHAINDIR/enc.pid" || why="encoder gone"
  alive "$CHAINDIR/link.pid" || why="avlink gone"
  pgrep -x 'parec|pw-record' >/dev/null || why="audio capture gone (avlink would stay on silence)"
  updating || pgrep -x hudiy >/dev/null || why="hudiy gone"
  age=$(( $(date +%s) - $(stat -c %Y "$CHAINDIR/live.log" 2>/dev/null || echo 0) ))
  [ "$age" -gt "$STALE_S" ] && why="avlink silent for ${age} s"
  if [ -n "$why" ]; then
    say "restart: $why"
    tail -n 3 "$CHAINDIR/live.log" "$CHAINDIR/cap.log" "$CHAINDIR/enc.log" "$CHAINDIR/parec.log" 2>/dev/null | cut -c1-200
    exit 1
  fi
done
