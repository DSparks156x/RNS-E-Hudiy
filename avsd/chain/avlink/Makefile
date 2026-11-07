# avlink -- Pi 5 side of the RNS-E A/V-over-SD link. Builds on Pi OS Bookworm (aarch64) and x86-64 Linux / WSL.
#   make            -> avlink
#   make test       -> unit tests that need no Python (wire image round-trip vs. the C reference) are in test/;
#                      the full checks (sd_wire.py / sdgen.py / Teensy host build / host_dec) are test/run_tests.py
CC      ?= gcc
CFLAGS  ?= -O2 -g
CFLAGS  += -std=c11 -Wall -Wextra -Wno-unused-parameter
SRC = avlink.c sf.c wire.c crc.c audio.c link.c
HDR = sf.h wire.h crc.h audio.h link.h tlink.h

avlink: $(SRC) $(HDR)
	$(CC) $(CFLAGS) $(SRC) -o $@

clean:
	rm -f avlink

.PHONY: clean
