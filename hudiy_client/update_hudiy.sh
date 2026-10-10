#!/bin/bash
# Run Hudiy's installed incremental updater as the user who runs Hudiy.
# Documented at https://github.com/wiboma/hudiy#updating.
set -u

echo "===================================================="
echo "                  Update Hudiy"
echo "===================================================="

finish() {
    if [ -t 0 ]; then
        read -r -p "Press Enter to close... " reply || true
    fi
    exit "$1"
}

# Allow the quit action sent by the API handler to close Hudiy first.
sleep 3

HUDIY_SHARE="$HOME/.hudiy/share"
UPDATER="$HUDIY_SHARE/updater"
if [ ! -x "$UPDATER" ]; then
    echo "Hudiy updater is missing or not executable: $UPDATER"
    echo "Run this action from the account where Hudiy is installed."
    finish 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required to check internet connectivity."
    finish 1
fi

echo "Waiting for internet access to Hudiy..."
# Python 3 is installed by the integration. Use HTTPS because ICMP can be
# blocked even when updates work. Each attempt is bounded; retries wait for
# connectivity, just like the RNS-E updater. Hudiy handles its own downloads.
while ! python3 - <<'PY'
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen('https://hudiy.eu/', timeout=10) as response:
        response.read(1)
except (OSError, urllib.error.URLError):
    sys.exit(1)
PY
do
    echo "Waiting for internet..."
    sleep 5
done

echo "Internet connection established. Starting Hudiy's updater..."
if ! cd "$HUDIY_SHARE"; then
    echo "Could not open Hudiy's installation directory: $HUDIY_SHARE"
    finish 1
fi
# Keep stdin connected to the terminal for the native updater's prompts.
"$UPDATER"
status=$?
if [ "$status" -ne 0 ]; then
    echo "Hudiy updater failed (exit status $status)."
    finish "$status"
fi

echo "Hudiy updater finished."
finish 0
