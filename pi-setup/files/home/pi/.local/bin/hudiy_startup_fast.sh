#!/bin/bash
# boot-tuning: copy of ~/.hudiy/share/hudiy_startup.sh (Hudiy 2.16), changes marked [bt].
# If Hudiy updates its own startup script, re-check this copy against it.
LOG=/run/user/$(id -u)/hudiy-startup.log; t() { echo "$(cut -d" " -f1 /proc/uptime) $1" >> "$LOG"; }  # [bt] timing
t start

EC_SINK="echo_cancel_sink"
EC_SOURCE="echo_cancel_source"
EQ_SINK="hudiy_equalizer_sink"
NOISETORCH_SOURCE="NoiseTorch Microphone for Echo-Cancel Source"
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
sink_exists "$EC_SINK" || pactl load-module module-echo-cancel aec_method=webrtc aec_args=\"voice_detection=false high_pass_filter=1 noise_suppression=1 extended_filter=1 analog_gain_control=0\" source_name="$EC_SOURCE" sink_name="$EC_SINK"
t modules

$HOME/noisetorch -i -s "$EC_SOURCE"
t noisetorch

pactl set-default-sink "$EQ_SINK"
pactl set-default-source "$NOISETORCH_SOURCE"

# [bt] Hudiy never recovers if NetworkManager appears after it starts (no hotspot), and lightdm
# no longer waits for NM, so wait for NM here (max 5 s), in parallel with the audio setup above.
gdbus wait --system --timeout 5 org.freedesktop.NetworkManager
t nm

$HOME/.hudiy/share/hudiy &
# [bt] let systemd start the late RNS-E services (rnse-late.path)
touch /run/rnse_control/hudiy-started 2>/dev/null
t hudiy
