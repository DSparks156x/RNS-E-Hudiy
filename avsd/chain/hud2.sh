#!/bin/bash
# Hudiy screen + Hudiy audio -> RNS-E
# Env: KEYINT (periodic key safety net, frames), LINKCAP (B/s), MAXVID (video sectors per superframe: must read in under a tick, so audio
# keeps 60 superframes/s even when video lags), GAIN (dB, at most -3, above 0 wraps), ENCTHREADS.
# CAPMODE: dmabuf (default: labwc hands over its buffer, no readback on the labwc thread) or shm (labwc reads back).
# RTPRIO: SCHED_FIFO priority of the encoder, 0 = off. wlcap gets one less, avlink one more. Needs passwordless sudo; without it the chain just runs at normal priority.
# Test without the Teensy: LINKDEV="--dump-sf /dev/null" CHAINDIR=/some/dir NORANDR=1 WLCAP_BIN=... AVLINK_BIN=... hud2.sh SECS
export XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0
A=$HOME/avsd
B=$A/current/bin
# Settings file, plain NAME=value lines: see avsd.env
[ -f "$A/avsd.env" ] && . "$A/avsd.env"
# Apply in the app: temporary values on top. tmpfs, so a reboot drops them.
[ -f "$XDG_RUNTIME_DIR/avsd-trial.env" ] && . "$XDG_RUNTIME_DIR/avsd-trial.env"
cd "${CHAINDIR:-$A/clips}" || exit 1
[ -n "$NORANDR" ] || wlr-randr --output NOOP-1 --custom-mode 800x480@60Hz 2>/dev/null
rm -f pcm.fifo key.fifo cap.pid enc.pid link.pid; mkfifo pcm.fifo key.fifo
if [ "${CAPMODE:-dmabuf}" = shm ]; then CAPARG=; FMT=rgb0; else CAPARG=--dmabuf; FMT=bgr0; fi
R=${RTPRIO:-5}
if [ "$R" -gt 0 ]; then
  (   # the chain stays owned by pi; only setting its priority needs root. -a: every thread.
    sleep 1
    sudo -n chrt -a -f -p $((R - 1)) "$(cat cap.pid)"
    sudo -n chrt -a -f -p "$R" "$(cat enc.pid)"
    sudo -n chrt -a -f -p $((R + 1)) "$(cat link.pid)"
    # Audio above the chain. PipeWire gets no RT here by itself (data-loop.0 ran SCHED_OTHER under a FIFO encoder, 2026-11-05).
    pgrep -x pw-record | while read -r p; do sudo -n chrt -a -f -p $((R + 2)) "$p"; done
    # Hudiy's audio reaches PipeWire through pipewire-pulse's main thread, and Hudiy runs at normal priority under a real-time chain. AUDIOPRIO=0 turns this off.
    if [ "${AUDIOPRIO:-1}" = 1 ]; then
      for p in $(pgrep -x pipewire-pulse); do sudo -n chrt -f -p $((R + 2)) "$p"; done
      for p in $(pgrep -x hudiy); do sudo -n renice -n -10 -p $(ls /proc/$p/task) >/dev/null; done
    fi
    for p in $(pgrep -x pipewire) $(pgrep -x pipewire-pulse); do
      for t in /proc/$p/task/*; do
        [ "$(cat "$t/comm" 2>/dev/null)" = data-loop.0 ] && sudo -n chrt -f -p $((R + 15)) "${t##*/}"
      done
    done
  ) > rt.log 2>&1 &
fi
withpid() { f=$1; shift; bash -c 'echo $$ > "$0"; exec "$@"' "$f" "$@"; }
# AUDIOCAP=parec reverts. parec goes through pipewire-pulse, which loses buffers ("out of buffers" in its log): 47724-47931 frames/s against pw-record's 48004 on the same monitor, 2026-11-05.
# echo_cancel_sink is fed by the Hudiy EQ sink: capturing there follows Hudiy volume and EQ. The EQ sink's own monitor is before both (measured 2026-11-06).
CAPSINK=hudiy_equalizer_sink; pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fxq echo_cancel_sink && CAPSINK=echo_cancel_sink
if [ "${AUDIOCAP:-pw}" = parec ]; then
  timeout $1 parec -d hudiy_equalizer_sink.monitor --rate=48000 --format=s16le --channels=2 --raw --latency-msec=20 > pcm.fifo 2>parec.log &
else
  timeout $1 pw-record --target "$CAPSINK" -P '{stream.capture.sink=true}' --rate 48000 --channels 2 --format s16 --latency 20ms --raw - > pcm.fifo 2>parec.log &
fi
timeout $1 bash -c 'echo $$ > cap.pid; exec "$0" "$@"' "${WLCAP_BIN:-$B/wlcap}" $CAPARG 2>cap.log | withpid enc.pid "${ENC_BIN:-$B/rnv3enc}" -i - --fmt $FMT -o - --keyint ${KEYINT:-0} --linkcap ${LINKCAP:-4.5e6} --linkctl key.fifo --stats st.txt --threads ${ENCTHREADS:-2} --maxvid ${MAXVID:-161} ${ENCFLAGS:---cyc ${CYC:-4.05e6} --refill wall --dither ${DITHER:-0} --srcdead ${SRCDEAD:-3} --srcmean ${SRCMEAN:-48} --fillpen ${FILLPEN:-2}} $ENCEXTRA 2>enc.log | withpid link.pid "${AVLINK_BIN:-$B/avlink}" --video - --audio pcm.fifo ${LINKDEV:---dev /dev/ttyACM0} --keyctl key.fifo --linkcap ${LINKCAP:-4.5e6} --maxvid ${MAXVID:-161} --whole-sf ${WHOLESF:-1} --gain-db ${GAIN:--3} --stats ${STATS:-5} --console > live.log 2>&1
