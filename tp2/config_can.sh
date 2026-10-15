#!/bin/bash
# ==============================================================================
# CAN setup: MCP2515 as ICAN ("ican", 100K) + USB SocketCAN adapter ("diagcan")
#
#   sudo ./config_can.sh [diagcan_bitrate]     (default 500K)
#
# This sets an MCP2515 connected as ICAN, and a USB SocketCAN adapter
# (candleLight/gs_usb etc.) as diagcan.
#
# Naming: the kernel hands out canN names in driver registration order, and
# renaming two adapters into canN collides when both appear at once at boot.
# "ican"/"diagcan" are outside the kernel's namespace, so .link files matched
# by driver can always rename each adapter immediately, in any order.
#
# An unplugged USB adapter is harmless: networkd only acts when the interface
# appears, and brings it up automatically on hotplug.
#
# Also updates on this Pi:
#   - ~/config.json interfaces.can: can0 -> ican, can1 -> diagcan
#   - can_handler / tp2_worker units: wait for ican instead of can0
# install.sh writes those units from config.json's infotainment interface, so
# a reinstall keeps ican.
# ==============================================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if [ "$EUID" -ne 0 ]; then
    echo "? Please run as root (use sudo)"
    exit 1
fi

DIAGCAN_BITRATE="${1:-500K}"
NETWORK_DIR=/etc/systemd/network
# gs_usb = candleLight / CANable (candleLight fw); others are common USB-CAN drivers.
USB_CAN_DRIVERS="gs_usb peak_usb kvaser_usb usb_8dev ems_usb"

REAL_USER="${SUDO_USER:-$USER}"
if [ "$REAL_USER" = "root" ]; then
    REAL_HOME="/root"
else
    REAL_HOME="/home/$REAL_USER"
fi
CONFIG_JSON="$REAL_HOME/config.json"

mkdir -p "$NETWORK_DIR"

# --- Clean up earlier versions of this script / install.sh ---
rm -f "$NETWORK_DIR/70-can0-mcp2515.link" "$NETWORK_DIR/70-can1-usb.link" \
      "$NETWORK_DIR/80-can.network" "$NETWORK_DIR/81-can1.network" \
      /etc/modprobe.d/usb-can-after-mcp2515.conf
if [ -f /etc/systemd/system/usb-can-load.service ]; then
    systemctl disable usb-can-load.service >/dev/null 2>&1
    rm -f /etc/systemd/system/usb-can-load.service
fi

# --- Names ---
cat <<CFG > "$NETWORK_DIR/70-ican.link"
# MCP2515 SPI HAT -> ican
[Match]
Driver=mcp251x

[Link]
Name=ican
CFG

cat <<CFG > "$NETWORK_DIR/70-diagcan.link"
# USB SocketCAN adapter -> diagcan
[Match]
Driver=$USB_CAN_DRIVERS

[Link]
Name=diagcan
CFG

# --- Bitrates ---
cat <<CFG > "$NETWORK_DIR/70-ican.network"
# MCP2515 SPI HAT (ICAN)
[Match]
Name=ican

[CAN]
BitRate=100K
RestartSec=100ms
CFG

# No RestartSec: gs_usb rejects restart-ms ("does not support restart from
# bus off"), which makes networkd fail the whole link.
cat <<CFG > "$NETWORK_DIR/70-diagcan.network"
# USB SocketCAN adapter
[Match]
Name=diagcan

[CAN]
BitRate=$DIAGCAN_BITRATE
CFG

# --- config.json ---
if [ -f "$CONFIG_JSON" ]; then
    python3 - "$CONFIG_JSON" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
rename = {'can0': 'ican', 'can1': 'diagcan'}
can = cfg.setdefault('interfaces', {}).setdefault('can', {})
for key in ('infotainment', 'diagnostic'):
    can[key] = rename.get(can.get(key, 'can0'), can.get(key))
with open(path, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(f"   config.json: infotainment={can['infotainment']}, diagnostic={can['diagnostic']}")
PY
else
    echo "   ! $CONFIG_JSON not found, set interfaces.can by hand."
fi

# --- Service units ---
for unit in can_handler.service tp2_worker.service; do
    if [ -f "/etc/systemd/system/$unit" ]; then
        sed -i 's/sys-subsystem-net-devices-can0\.device/sys-subsystem-net-devices-ican.device/g' \
            "/etc/systemd/system/$unit"
    fi
done
systemctl daemon-reload

systemctl enable systemd-networkd >/dev/null 2>&1

echo "? CAN configured: ican = MCP2515 @ 100K, diagcan = USB @ $DIAGCAN_BITRATE"
echo "  Reboot for the new names to apply."
echo "  Verify with: networkctl status ican diagcan"
echo "  To diagnose over ICAN instead, set interfaces.can.diagnostic to \"ican\"."
