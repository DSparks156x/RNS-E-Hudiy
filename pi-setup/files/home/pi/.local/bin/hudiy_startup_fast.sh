#!/bin/bash
# boot-tuning: copy of ~/.hudiy/share/hudiy_startup.sh (Hudiy 2.16), changes marked [bt].
# If Hudiy updates its own startup script, re-check this copy against it.
LOG=/run/user/$(id -u)/hudiy-startup.log; t() { echo "$(cut -d" " -f1 /proc/uptime) $1" >> "$LOG"; }  # [bt] timing
t start

EC_SINK="echo_cancel_sink"
EC_SOURCE="echo_cancel_source"
EQ_SINK="hudiy_equalizer_sink"
sink_exists() { pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fxq "$1"; }
until pactl info >/dev/null 2>&1; do sleep 0.05; done
t pactl

# [bt] was "sleep 1": echo-cancel attaches to the current default sink, so wait until a real
# ALSA sink (the USB DAC) is default instead of guessing. Max 3 s, then carry on as before.
for i in $(seq 1 60); do
  case "$(pactl get-default-sink 2>/dev/null)" in alsa_output.*) break ;; esac
  sleep 0.05
done
t "sink $(pactl get-default-sink 2>/dev/null)"

sink_exists "$EQ_SINK" || pactl load-module module-ladspa-sink sink_name="$EQ_SINK" master="$EC_SINK" plugin=hudiy_equalizer label=hudiy_equalizer control=0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
# [avsd] aec_method=null (was webrtc + noise_suppression) and no NoiseTorch: the dome chain
# (~/.config/pipewire/filter-chain.conf.d/50-dome-mic.conf: its own WebRTC AEC + DeepFilterNet -> dome_mic)
# is the one mic chain. Two full chains ran before, and this one sat in the music path for nothing.
# echo_cancel_sink stays: the music goes through it and avlink taps it. echo_cancel_source = raw default mic.
sink_exists "$EC_SINK" || pactl load-module module-echo-cancel aec_method=null source_name="$EC_SOURCE" sink_name="$EC_SINK"
t modules

pactl set-default-sink "$EQ_SINK"
# [avsd] Assistant/calls use dome_mic when the dome filter chain is up (max 2 s), else the plain mic
for i in $(seq 1 40); do pactl list short sources | awk '{print $2}' | grep -Fxq dome_mic && break; sleep 0.05; done
if pactl list short sources | awk '{print $2}' | grep -Fxq dome_mic; then pactl set-default-source dome_mic; else pactl set-default-source "$EC_SOURCE"; fi
t "source $(pactl get-default-source)"

# [bt] Hudiy never recovers if NetworkManager appears after it starts (no hotspot), and lightdm
# no longer waits for NM, so wait for NM here (max 5 s), in parallel with the audio setup above.
gdbus wait --system --timeout 5 org.freedesktop.NetworkManager
t nm

$HOME/.hudiy/share/hudiy &
# [bt] let systemd start the late RNS-E services (rnse-late.path)
touch /run/rnse_control/hudiy-started 2>/dev/null
t hudiy
