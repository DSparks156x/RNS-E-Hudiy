#!/bin/bash
# Update button. Same steps as update_rnse.sh: quit Hudiy so the hotspot drops and the Pi can join a known network,
# wait for GitHub, update, reboot. The chain keeps running so this terminal still reaches the RNS-E screen.
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
A=$HOME/avsd
REBOOT_AFTER_FAIL_S=30

echo "===================================================="
echo "              Update A/V over SD"
echo "===================================================="

fail() {
    echo "Update failed: $1"
    echo "Still on the old version. Rebooting in $REBOOT_AFTER_FAIL_S seconds."
    sleep "$REBOOT_AFTER_FAIL_S"
    sudo reboot now
    exit 1
}

# Read by avsd_run.sh: a missing Hudiy is not a reason to stop the chain. A reboot clears it.
touch "$XDG_RUNTIME_DIR/avsd-updating"
sleep 1
pkill -x hudiy
sleep 3
nmcli connection down "Hudiy AccessPoint" >/dev/null 2>&1

# The full install keeps its branch and repository in config.json. A standalone one has only its own file.
CONFIG=$HOME/config.json
REPO=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('repo', ''))" 2>/dev/null)
BRANCH=$(python3 -c "import json; print(json.load(open('$CONFIG')).get('branch', ''))" 2>/dev/null)
REPO=${REPO:-DSparks156x/RNS-E-Hudiy}
REPO=${REPO#https://github.com/}
REPO=${REPO%.git}
BRANCH=${BRANCH:-$(cat "$A/branch" 2>/dev/null)}
BRANCH=${BRANCH:-main}
URL="https://github.com/$REPO.git"
echo "Repository $REPO, branch $BRANCH"

echo "Waiting for internet. Turn on your phone hotspot or get in range of home Wi-Fi."
until git ls-remote "$URL" HEAD >/dev/null 2>&1; do
    echo "Waiting for GitHub..."
    sleep 5
done
echo "GitHub connection established."

TMP=$(mktemp -d "$A/update.XXXXXX") || fail "no temporary folder"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading..."
git clone --quiet --depth 1 --filter=blob:none --sparse -b "$BRANCH" "$URL" "$TMP/repo" || fail "download"
git -C "$TMP/repo" sparse-checkout set avsd || fail "download"
bash "$TMP/repo/avsd/install.sh" --update || fail "install"

echo "Update finished. Rebooting in 10 seconds."
sleep 10
sudo reboot now
