#!/bin/bash
# Installs A/V over SD for the current user, without the rest of this repo. Run from a checkout: bash avsd/install.sh
# --update: called by update_avsd.sh, or by the main install.sh when the full install is here too.
# Keeps your settings, and the app checks the new chain after the reboot.
# Every version goes in its own folder. A failed build leaves the running version alone.
set -eu
UPDATE=false
[ "${1:-}" = "--update" ] && UPDATE=true
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
A=$HOME/avsd
C=$A/car
say() { echo "== $*"; }
die() { echo "ERROR: $*"; exit 1; }

[ "$(id -u)" != 0 ] || die "run as the user that runs Hudiy, not root"
[ "$(uname -m)" = aarch64 ] || die "needs 64-bit Raspberry Pi OS"
grep -q "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null || die "the encoder is built for the Raspberry Pi 5"

say "Packages"
NEED=
for p in build-essential python3-flask python3-serial psmisc wlr-randr foot git pulseaudio-utils pipewire-bin; do
  dpkg -s "$p" >/dev/null 2>&1 || NEED="$NEED $p"
done
if [ -n "$NEED" ]; then
  sudo apt-get update
  # shellcheck disable=SC2086
  sudo apt-get install -y $NEED
fi

VERSION=$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo local)
BRANCH=$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)
# The main installer's staging checkout is detached, so it has no branch to read.
[ "$BRANCH" != HEAD ] || BRANCH=$(cat "$A/branch" 2>/dev/null || echo main)
NAME=$(date +%Y%m%d-%H%M%S)-$VERSION
REL=$A/releases/$NAME
mkdir -p "$REL/bin" "$A/logs" "$C" "$HOME/rnsefw"
trap 'rm -rf "$REL"' ERR

say "Copying version $VERSION"
cp -r "$SRC/app" "$SRC/chain" "$SRC/teensy" "$SRC/update_avsd.sh" "$REL/"
[ -f "$REL/app/static/avsd.js" ] || die "the UI bundle is missing. CI builds it; pull again"
chmod +x "$REL/chain/"*.sh "$REL/update_avsd.sh"

say "Building, about a minute"
( cd "$REL/chain/enc3" && gcc -O3 -mcpu=cortex-a76 -std=c11 -ffp-contract=off -D_POSIX_C_SOURCE=200809L -Iinclude -Isrc -w \
    src/main.c src/enc.c src/kern_scalar.c src/kern_neon.c -o "$REL/bin/rnv3enc" -lpthread -lm )
( cd "$REL/chain/avlink" && make -s && mv avlink "$REL/bin/avlink" )
( cd "$REL/chain/wlcap" && cc -O2 -pthread -o "$REL/bin/wlcap" wlcap.c )

printf '{"version": "%s", "branch": "%s", "built": "%s"}\n' "$VERSION" "$BRANCH" "$(date -Iseconds)" > "$REL/version.json"
echo "$BRANCH" > "$A/branch"
trap - ERR

[ -e "$A/avsd.env" ] || cp "$REL/chain/avsd.env" "$A/avsd.env"

say "Switching to it"
if [ -L "$A/current" ]; then
  ln -sfn "$(readlink "$A/current")" "$A/previous.new"
  mv -T "$A/previous.new" "$A/previous"
fi
ln -sfn "releases/$NAME" "$A/current.new"
mv -T "$A/current.new" "$A/current"
for d in "$A"/releases/*; do
  case "releases/${d##*/}" in
    "$(readlink "$A/current")"|"$(readlink "$A/previous" 2>/dev/null)") ;;
    *) rm -rf "$d" ;;
  esac
done

if [ "$UPDATE" = false ]; then
  say "System settings (saved once in $C/backup)"
  B=$C/backup; mkdir -p "$B"
  E=$HOME/.config/labwc/environment
  if [ -f "$E" ]; then
    [ -e "$B/labwc-environment" ] || cp -p "$E" "$B/labwc-environment"
    sed -i 's/^XCURSOR_THEME=.*/XCURSOR_THEME=invisible/' "$E"
    grep -q '^XCURSOR_THEME=invisible$' "$E" || echo 'XCURSOR_THEME=invisible' >> "$E"
  fi
  [ -e "$B/wayvnc-enabled" ] || systemctl is-enabled wayvnc > "$B/wayvnc-enabled" 2>/dev/null || true
  sudo systemctl disable wayvnc 2>/dev/null || true
fi

say "Services"
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$A/current/chain/avsd-chain.service" "$A/current/chain/avsd-app.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable avsd-chain.service avsd-app.service
sudo install -m 644 "$A/current/chain/avsd-governor.service" /etc/systemd/system/avsd-governor.service
sudo systemctl daemon-reload
sudo systemctl enable avsd-governor.service
loginctl show-user "$(id -un)" -p Linger | grep -q yes || sudo loginctl enable-linger "$(id -un)"

say "Hudiy menu"
# With the full install, Update RNS-E updates this too, so there's no second button.
python3 - "$HOME/.hudiy/share/config" "$([ -e "$HOME/hudiy_client/update_rnse.sh" ] && echo full || echo standalone)" <<'PY'
import json, os, sys
config = sys.argv[1]
standalone = sys.argv[2] == 'standalone'
URL = 'http://localhost:5005'
APPS = [{'action': 'avsd_settings', 'url': URL}]
ITEMS = [('avsd_settings', 'A/V over SD', 'cast')]
if standalone:
    APPS.append({'action': 'avsd_update', 'url': URL + '/?update=1'})
    ITEMS.append(('avsd_update', 'Update A/V over SD', 'system_update'))
CATEGORY = {'iconFontFamily': 'Material Symbols Rounded', 'iconName': 'directions_car', 'label': 'RNS-E'}

def edit(name, change):
    path = os.path.join(config, name)
    if not os.path.exists(path):
        print('No %s: add the menu entries by hand once Hudiy is installed.' % path)
        return
    with open(path) as f:
        data = json.load(f)
    change(data)
    with open(path + '.tmp', 'w') as f:
        json.dump(data, f, indent=4)
    os.replace(path + '.tmp', path)

def apps(data):
    have = {a.get('action') for a in data['applications']}
    for app in APPS:
        if app['action'] not in have:
            data['applications'].append({**app, 'allowBackground': False, 'controlAudioFocus': False, 'audioStreamCategory': 'NONE'})

def menu(data):
    have = {i.get('action') for i in data['items']}
    # Next to Manager when it's there. An entry you already moved stays put.
    at = next((n + 1 for n, i in enumerate(data['items']) if i.get('action') == 'hudiy_manager'), len(data['items']))
    for action, label, icon in ITEMS:
        if action not in have:
            data['items'].insert(at, {'categories': ['RNS-E'], 'iconFontFamily': 'Material Symbols Rounded', 'iconName': icon, 'action': action, 'label': label})
            at += 1
    if not any(c.get('label') == 'RNS-E' for c in data['categories']):
        data['categories'].append(CATEGORY)

edit('applications.json', apps)
edit('applications_menu.json', menu)
PY

if [ "$UPDATE" = true ]; then
  printf '{"state": "pending", "version": "%s"}\n' "$VERSION" > "$A/update_check.json"
  say "Done. Version $VERSION runs after the reboot."
else
  systemctl --user restart avsd-app.service
  say "Done. Reboot to start the chain. Settings: http://localhost:5005, or A/V over SD in the Hudiy menu."
  say "Unplug any HDMI display: the chain captures Hudiy's headless output."
fi
