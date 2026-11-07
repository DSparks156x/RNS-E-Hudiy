avlink -- Pi 5 side of the RNS-E A/V-over-SD link (2026-11-04)
=============================================================
Reads RNV2 video (pienc/rnv2enc output) and 48 kHz PCM, packs superframes per ../../link/SPEC.md section 3
(64-B header, down-channel TLVs incl. TLV 0x11 fragments, SPEC 3.8), builds 528-B SD wire images (SPEC 1.5) and
sends them to the Teensy over USB CDC with the SPEC 5 protocol and STATUS credits.

STATUS: host-tested only (WSL x86-64). NOT run on a Pi, NOT run against a real Teensy, no RNS-E.

LIVE LATENCY (test/test_live.py checks all of this, real tick and credits, no hardware)
  Reader working: at most 8 superframes ahead of it on the Teensy; at most 2 frames in avlink's buffer, pipe 16 KB, then the encoder blocks and wlcap drops.
  No new superframe served for 400 ms: every frame discarded on arrival, one audio-only superframe per 200 ms (per tick while the reader polls). Reader back: key
  at once. More than 7 frames waiting above USB for 300 ms: discarded too. After a discard no delta goes out until a key, so the decoder keeps its picture.
  All of this needs --keyctl. CONFIG stale_ms 400 live, 1500 batch and around a bootstrap image.
WHOLE-SUPERFRAME HOLD (off by default, for the stuck-read tests): the Teensy holds only before sector 0, until the superframe is complete: no mid-read holds.
  Switch: avlink --whole-sf 1, or live printf WSF1 > /tmp/avlink_sdctl (WSF0 off), or the Teensy console cfg wholesf 1 when avlink is not running
  (console bytes written during a stream can land inside a message). It stays set until changed or Teensy reboot; avlink without the option leaves it alone.

FILES
  avlink.c   main: options, video source + fragmenter, superframe builder, live/batch loop, USB writer
  sf.c/.h    superframe header + TLVs + payload layout, CRC-32s        wire.c/.h  wire4 / wire1 images (table CRC16)
  audio.c/.h the audio stage (only place that makes audio bytes)      link.c/.h  TLNK framing, tty setup, credits
  tlink.h    message layout (= teensy/sdemu/avstream.h)                crc.c/.h   CRC-32 / CRC16 (no zlib needed)
  test/run_tests.py   all PC checks (see below)

BUILD (Pi OS Bookworm: gcc + make preinstalled; WSL the same)
  cd pi/avlink && make            -> ./avlink

RUN
  Video in : .rnv stream = 4-byte big-endian length + RNV2 frame (exactly what rnv2enc -o writes), file or pipe.
  Audio in : 48 kHz s16 stereo, little-endian (ALSA S16_LE) on a file or FIFO; --audio-be for big-endian.
             Without --audio the audio sectors carry silence; --no-audio sends audio_fmt 0.
  Live (default): one superframe per tick (--fps 60, 800 audio frames each), REPEAT when no new video frame,
             frames larger than --maxvid sectors (248) go out as TLV 0x11 fragments over consecutive ticks.
             If USB/credits fall behind, the tick is skipped (no seq consumed) and the inputs back up.
  Batch (--k N): exactly N superframes as fast as credits allow; header values identical to sdgen.py.

  Example, full chain on the Pi (capture options: pienc/README.txt):
    wf-recorder -c rawvideo -m rawvideo -x bgr0 -r 60 -f /dev/stdout \
      | ../../pienc/rnv2enc -i - --fmt bgr0 -o - --threads 2 \
      | ./avlink --video - --audio /tmp/pcm.fifo --dev /dev/ttyACM0 --stats 1
  Test stream from a file (no encoder):
    ./avlink --video ../../video/out/v2_real/highway110_night.rnv --dev /dev/ttyACM0 --stats 1
  Options: ./avlink (no args shows them). --console copies the Teensy console text to stderr. --dump-sf FILE
  writes the superframes (= sdgen .rsav); --dump-wire FILE writes the wire images.

  Audio hook: the Teensy is to become a UAC2 sound card that inserts audio itself. Then audio.c's audio_take()
  is replaced by "reserve the audio sectors" and the Teensy fills them and patches the header (audio_bytes,
  audio_crc32, hdr_crc32). Nothing else touches audio bytes. Rate control from the RNS-E STATUS (SPEC 3.5) is not
  here (needs the uplink): every tick carries exactly 48000/fps frames.

PC TESTS (Windows Python + WSL gcc; no hardware)
  C:\Users\raccoon\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -I test\run_tests.py [--raw]
  [1] wire images == link/sd_wire.py wire4/wire1 (64 sectors, both widths)
  [2] --k --dump-sf == rnse_proto/sdgen.py for the same input: highway110_night K=48, turn_night K=48 maxvid 60
      (TLV 0x11, frames over 2 and 7 superframes), --raw: rawtest4 K=30 (771 KB frames)
  [3] avlink -> pty (fake /dev/ttyACM0) -> teensy/tools/host_link (the firmware's avstream.cpp + sdproto.cpp) ->
      simulated RNS-E mode A reader: served superframes == sdgen.py byte for byte, every served wire image
      CRC-checked, video reassembled and decoded by rnse_proto/sim/host_dec with YUY2 CRC == *_c.txt. Variants:
      4-bit bus, 1-bit bus (Teensy re-encodes), Teensy started first (IDLE/holds), slow reader (stale eviction ->
      EXPIRED -> jump, every served superframe still exact), --chunk 7.
  Result 2026-11-04: wire PASS, sdgen PASS (3 cases), e2e PASS (8 runs). Live mode smoke test: 120 superframes in
  2.0 s through host_link, 0 errors.

BENCH STEPS (when the hardware is here)
  B0  Pi + Teensy only. Flash teensy/build or `pio run -t upload` (README there). On the Pi:
        ls /dev/ttyACM*            (sudo usermod -aG dialout $USER, re-login)
        ./avlink --video ../../video/out/v2_real/highway110_night.rnv --dev /dev/ttyACM0 --stats 1 --console
      expect: "teensy status=" growing ~20/s, free=1500/1500, slots=8 at first. With NO RNS-E reading, the
      Teensy evicts unread slots after 200 ms: evicted grows, sent keeps up with built, late stays ~0.
      In the Teensy console (other terminal is not possible on the same port: use `--console` output, or stop
      avlink and `screen /dev/ttyACM0`): `link` shows slots / counters.
  B1  USB rate: ./avlink --video <rawtest .rnv from test/out/raw.rnv> --k 240 --nocredits --dev /dev/ttyACM0
      (rawtest = 6.4 MB/s of wire images); time it. Need >= 5.6 MB/s (SPEC 5.1).
  B2  RNS-E in card mode (teensy README S2/S3) with an RNS-E reader of the window (rnse_proto sdstream, live):
      avlink as in B0; expect Teensy `link`: srv_sect grows, served_seq follows, notready small, expired 0,
      avlink `served=` close to `sent=`.
  Failure meanings: "teensy status=0" -> wrong port / Teensy not running sdemu 0.3 / console only (check `ver`);
  rxerr > 0 -> framing problem (version mismatch tlink.h vs avstream.h); conv > 0 -> host bus width != --wire
  (use --wire 1 for the 1-bit bring-up patch); credit_waits huge + sent < built -> the Teensy pool is not freed
  (RNS-E reading slowly: see evicted/expired).
