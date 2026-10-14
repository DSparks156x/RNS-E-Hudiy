#!/bin/bash
# ==============================================================================
# CAN setup: MCP2515 as ICAN (can0, 100K) + USB SocketCAN adapter (can1)
#
#   sudo ./config_can.sh [can1_bitrate]     (default 500K)
#
# This sets an MCP2515 connected as ICAN, and a USB SocketCAN adapter
# (candleLight/gs_usb etc.) as can1. Everything matches on driver, not on
# kernel name, so the names and bitrates stay correct whichever adapter
# registers first at boot. An unplugged USB adapter is harmless: networkd only
# acts when the interface appears, and brings it up automatically on hotplug.
#
# Replaces the Name=can0 80-can.network written by install.sh.
# ==============================================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if [ "$EUID" -ne 0 ]; then
    echo "? Please run as root (use sudo)"
    exit 1
fi

CAN1_BITRATE="${1:-500K}"
NETWORK_DIR=/etc/systemd/network
# gs_usb = candleLight / CANable (candleLight fw); others are common USB-CAN drivers.
USB_CAN_DRIVERS="gs_usb peak_usb kvaser_usb usb_8dev ems_usb"

mkdir -p "$NETWORK_DIR"

# --- Stable names ---
cat <<CFG > "$NETWORK_DIR/70-can0-mcp2515.link"
[Match]
Driver=mcp251x

[Link]
Name=can0
CFG

cat <<CFG > "$NETWORK_DIR/70-can1-usb.link"
[Match]
Driver=$USB_CAN_DRIVERS

[Link]
Name=can1
CFG

# --- Bitrates ---
cat <<CFG > "$NETWORK_DIR/80-can.network"
# MCP2515 SPI HAT (ICAN)
[Match]
Driver=mcp251x

[CAN]
BitRate=100K
RestartSec=100ms
CFG

cat <<CFG > "$NETWORK_DIR/81-can1.network"
# USB SocketCAN adapter
[Match]
Driver=$USB_CAN_DRIVERS

[CAN]
BitRate=$CAN1_BITRATE
RestartSec=100ms
CFG

systemctl enable systemd-networkd >/dev/null 2>&1
systemctl restart systemd-networkd

echo "? CAN configured: can0 = MCP2515 @ 100K, can1 = USB @ $CAN1_BITRATE"
echo "  Reboot (or replug the USB adapter) for the names to apply."
echo "  Verify with: networkctl status can0 can1"
