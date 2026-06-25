#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DDP CAN Active Bridge & Raw Payload Logger for Audi DIS / RNS-E
Bridges:
  RNS-E Navigation (0x6C2 TX, 0x6C3 RX) <---> Cluster (0x6C0 RX, 0x6C1 TX)

Forwards packets bidirectionally and decodes the Display Data Protocol
(DDP) stream statefully, logging raw frame bytes, reassembled block bytes,
and decoded commands.
"""

import sys
import time
import argparse
import logging
import can

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("DDPBridge")

# AUDSCII to standard printable ASCII translation table
AUDSCII_TRANS = [
    0x00,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x2F,0x20,0x20,0x20,0x20,0x20,0x20,
    0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x1C,0x20,0xD7,0x65,
    0x20,0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x29,0x2A,0x2B,0x2C,0x2D,0x2E,0x2F,
    0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x3A,0x3B,0x3C,0x3D,0x3E,0x3F,
    0x40,0x41,0x42,0x43,0x44,0x45,0x46,0x47,0x48,0x49,0x4A,0x4B,0x4C,0x4D,0x4E,0x4F,
    0x50,0x51,0x52,0x53,0x54,0x55,0x56,0x57,0x58,0x59,0x5A,0x5B,0x5C,0x5D,0x5E,0x66,
    0x20,0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0A,0x0B,0x0C,0x0D,0x0E,0x0F,
    0x10,0x71,0x72,0x73,0x74,0x75,0x76,0x77,0x78,0x79,0x7A,0x7B,0x7C,0x7D,0x7E,0x20,
    0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,
    0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,
    0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0x20,0xA2,0xA0,0x20,0x20,0x2D,0x20,0x7E,
    0x6B,0xB4,0xB2,0xB3,0x20,0xB8,0x20,0x20,0x20,0xB1,0xB0,0x20,0x20,0x20,0x20,0xB9,
    0xC1,0xC0,0xD0,0xE0,0x5F,0xE1,0xE2,0x8B,0xC3,0xC2,0xD2,0xD3,0xC5,0xC4,0xD4,0xD5,
    0xCE,0x8A,0xC7,0xC6,0xD6,0xE6,0x60,0x20,0xE7,0xC9,0xC8,0xD8,0x61,0xE5,0xE8,0x8D,
    0x81,0x80,0x90,0xF0,0x91,0xF1,0xF2,0x9B,0x83,0x82,0x92,0x93,0x85,0x84,0x94,0x95,
    0xEF,0x9A,0x87,0x86,0x96,0xF6,0x97,0xBA,0xF7,0x89,0x88,0x98,0x99,0xF5,0xF8,0x20
]

# Build reverse mapping dictionary: AUDSCII byte -> ASCII char
AUDSCII_TO_CHAR = {}
for code, val in enumerate(AUDSCII_TRANS):
    if 32 <= code <= 126:
        if val not in AUDSCII_TO_CHAR:
            AUDSCII_TO_CHAR[val] = chr(code)

for i in range(1, 17):
    AUDSCII_TO_CHAR[i] = chr(96 + i)  # 'a' to 'p'
for i in range(0x71, 0x7B):
    AUDSCII_TO_CHAR[i] = chr(113 + (i - 0x71))  # 'q' to 'z'

AUDSCII_TO_CHAR[0x65] = ' '
AUDSCII_TO_CHAR[0x20] = ' '

def audscii_decode(payload: list) -> str:
    """Decodes AUDSCII byte array to readable ASCII string."""
    chars = []
    for b in payload:
        if b in AUDSCII_TO_CHAR:
            chars.append(AUDSCII_TO_CHAR[b])
        else:
            chars.append(f"\\x{b:02X}")
    return "".join(chars)

class DDPAssembler:
    """Reassembles multi-packet blocks and decodes DDP commands."""
    def __init__(self, direction: str):
        self.direction = direction
        self.buffer = []
        self.seq_num = None

    def process_can_frame(self, frame_data: list):
        if not frame_data:
            return None

        first_byte = frame_data[0]
        pkt_type = first_byte & 0xF0
        seq = first_byte & 0x0F
        raw_frame_hex = ' '.join(f'{b:02X}' for b in frame_data)

        # Keep-Alive packets (0xA0 nibble)
        if pkt_type == 0xA0:
            desc = self._decode_keepalive(frame_data)
            return f"Raw Frame: [{raw_frame_hex}] -> {desc}"

        # ACK packets (0xB0 nibble)
        if pkt_type == 0xB0:
            return f"Raw Frame: [{raw_frame_hex}] -> ACK (seq={seq})"

        # Segmented DDP packet types
        # 0x20: Frame Body (no ACK required, middle of block)
        if pkt_type == 0x20:
            self.buffer.extend(frame_data[1:])
            self.seq_num = seq
            return f"Raw Frame: [{raw_frame_hex}] -> Segment (seq={seq}, buffered)"

        # 0x10: End of Frame (ACK expected, final segment)
        # 0x00: Single segment frame (graphics ACKs / capabilities)
        if pkt_type in [0x10, 0x00]:
            self.buffer.extend(frame_data[1:])
            assembled_payload = list(self.buffer)
            self.buffer = []  # Reset buffer for next block
            self.seq_num = seq
            
            raw_block_hex = ' '.join(f'{b:02X}' for b in assembled_payload)
            desc = self._decode_ddp_block(assembled_payload)
            
            frame_type_label = "END" if pkt_type == 0x10 else "SINGLE"
            return (
                f"Raw Frame: [{raw_frame_hex}] -> Block Completed ({frame_type_label}, seq={seq})\n"
                f"       Raw Block:   [{raw_block_hex}]\n"
                f"       Interpretation: {desc}"
            )

        return f"Raw Frame: [{raw_frame_hex}] -> Unknown (type={pkt_type:02X}, seq={seq})"

    def _decode_keepalive(self, data: list) -> str:
        if data[0] == 0xA0:
            if len(data) == 6 and data[1:6] == [0x0F, 0x8A, 0xFF, 0x4A, 0xFF]:
                return "Session Open Request (A0)"
            if len(data) == 3 and data[1:3] == [0x07, 0x00]:
                return "Red DIS Present/Broadcast (A0 07 00)"
        if data[0] == 0xA1:
            if len(data) == 6 and data[1:6] == [0x0F, 0x8A, 0xFF, 0x4A, 0xFF]:
                return "Session Accept / Pong (A1 White)"
            if len(data) == 2 and data[1] == 0x0F:
                return "Session Open Reply / Pong (A1 Red)"
        if data[0] == 0xA3:
            return "Keep-Alive Ping (A3)"
        if data[0] == 0xA8:
            return "Session Close (A8)"
        return f"Session Control Message"

    def _decode_ddp_block(self, payload: list) -> str:
        if not payload:
            return "Empty Payload"

        cmd = payload[0]
        
        # Region command 'R' (0x52)
        if cmd == 0x52:
            if len(payload) >= 7:
                length = payload[1]
                flags = payload[2]
                x = payload[3]
                y = payload[4]
                w = payload[5]
                h = payload[6]
                
                flag_desc = []
                if flags & 0x80: flag_desc.append("CLAIM")
                else: flag_desc.append("CLIP")
                if flags & 0x02: flag_desc.append("CLEAR")
                if flags & 0x01: flag_desc.append("COLOR:RED")
                else: flag_desc.append("COLOR:BLACK")
                
                rest = payload[7:]
                rest_str = f" + Extra: {' '.join(f'{b:02X}' for b in rest)}" if rest else ""
                
                return f"REGION [{', '.join(flag_desc)}] bounds: (x={x}, y={y}, w={w}, h={h}){rest_str}"
            return "Malformatted Region Command"

        # Write command 'W' (0x57)
        if cmd == 0x57:
            if len(payload) >= 5:
                length = payload[1]
                flags = payload[2]
                x = payload[3]
                y = payload[4]
                text_bytes = payload[5:5 + (length - 3)]
                text_str = audscii_decode(text_bytes)
                
                font = (flags & 0x0C) >> 2
                font_desc = ["Fixed", "Proportional", "Graphics", "Unknown"][font]
                color = flags & 0x03
                color_desc = ["Black/Trans", "XOR/Trans", "Red/Black", "Red/Trans"][color]
                alignment = "Center" if (flags & 0x20) else "Left"
                
                return f"WRITE [{font_desc}, {color_desc}, {alignment}] at (x={x}, y={y}): \"{text_str}\""
            return "Malformatted Write Command"

        # Graphics row update 'U' (0x55)
        if cmd == 0x55:
            if len(payload) >= 5:
                length = payload[1]
                flags = payload[2]
                x = payload[3] # should be 0x00
                row = payload[4]
                bitmap_bytes = payload[5:5 + (length - 3)]
                bitmap_hex = ' '.join(f'{b:02X}' for b in bitmap_bytes)
                
                mode_desc = ["Erase", "Invert", "Draw", "Set"][flags & 0x03]
                
                return f"BITMAP ROW [Mode: {mode_desc}] row={row}, x={x}, data=[{bitmap_hex}]"
            return "Malformatted Bitmap Command"

        # Line draw command (0x63)
        if cmd == 0x63:
            if len(payload) >= 6:
                orientation = "Vertical" if (payload[2] == 0x10) else "Horizontal"
                x = payload[3]
                y = payload[4]
                length = payload[5]
                return f"LINE draw [{orientation}] at (x={x}, y={y}) len={length}"
            return "Malformatted Line Command"

        # Commit frame '9' (0x39)
        if cmd == 0x39:
            return "COMMIT Frame Buffer to Display"

        # Release Screen (0x33)
        if cmd == 0x33:
            return "RELEASE Screen Control to trip computer"

        # Re-Init Request (0x2E)
        if cmd == 0x2E:
            return "RE-INIT Request (Sent by Cluster)"

        # Re-Init Confirm (0x2F)
        if cmd == 0x2F:
            return "RE-INIT Confirm (Sent by Device)"

        # Swallowed graphics ACK (benign status updates)
        if cmd == 0x0B and len(payload) >= 2:
            if payload[1] == 0x03 and len(payload) >= 3 and payload[2] == 0x57:
                return "Graphics ACK (White DIS)"
            if payload[1] == 0x01 and len(payload) >= 3 and payload[2] == 0x00:
                return "Graphics ACK (Red DIS)"

        # Standard Cluster status packets (0x53)
        if cmd == 0x53:
            if len(payload) >= 2:
                status_byte = payload[1]
                status_desc = "Unknown"
                if status_byte == 0x84: status_desc = "BUSY (Half Screen)"
                elif status_byte == 0x04: status_desc = "BUSY WARNING (Half Screen)"
                elif status_byte == 0x88: status_desc = "BUSY (Full Screen)"
                elif status_byte == 0x08: status_desc = "BUSY WARNING (Full Screen)"
                elif status_byte == 0x05: status_desc = "FREE (Half Screen)"
                elif status_byte == 0x0A: status_desc = "FREE (Full Screen)"
                
                claim_active = (status_byte & 0x80) != 0
                region_type = "Full" if (status_byte & 0x0F in [0x0A, 0x08]) else "Half"
                
                return f"STATUS Update: {status_desc} (ClaimActive={claim_active}, Region={region_type}, byte=0x{status_byte:02X})"

        # Capabilities Query (0x15)
        if cmd == 0x15:
            return "CAPABILITIES Query"

        # Default fallback
        return f"Payload Command 0x{cmd:02X}"

def main():
    parser = argparse.ArgumentParser(description="Stateful DDP CAN Active Bridge & Raw Logger")
    parser.add_argument("-i", "--interface", default="can0", help="SocketCAN interface name (default: can0)")
    parser.add_argument("-b", "--bitrate", type=int, default=100000, help="CAN Bus Bitrate (default: 100000)")
    args = parser.parse_args()

    logger.info(f"Initializing CAN Bus on interface '{args.interface}' at {args.bitrate} bps...")
    
    try:
        bus = can.Bus(
            interface='socketcan',
            channel=args.interface,
            bitrate=args.bitrate
        )
    except Exception as e:
        logger.error(f"Failed to open CAN bus '{args.interface}': {e}")
        sys.exit(1)

    logger.info("DDP CAN Active Bridge and Raw Payload Logger is RUNNING.")
    logger.info("Routing:")
    logger.info("  0x6C2 (RNS-E TX) ----> bridges to ----> 0x6C0 (Cluster RX)")
    logger.info("  0x6C1 (Cluster TX) --> bridges to ----> 0x6C3 (RNS-E RX)")
    logger.info("Press Ctrl+C to stop.")

    # Stateful DDP assemblers for logs
    ddp_6c2 = DDPAssembler("RNS-E -> Proxy (0x6C2)")
    ddp_6c1 = DDPAssembler("Cluster -> Proxy (0x6C1)")

    try:
        while True:
            msg = bus.recv(timeout=1.0)
            if not msg:
                continue

            arb_id = msg.arbitration_id
            data = list(msg.data)
            
            # --- ROUTE: RNS-E to Cluster ---
            # RNS-E sends on 0x6C2 -> forward to Cluster on 0x6C0
            if arb_id == 0x6C2:
                forward_msg = can.Message(
                    arbitration_id=0x6C0,
                    data=data,
                    is_extended_id=False
                )
                try:
                    bus.send(forward_msg)
                    desc = ddp_6c2.process_can_frame(data)
                    if desc:
                        print(f"[{time.time():.4f}] [BRIDGE 0x6C2 -> 0x6C0]\n{desc}")
                except Exception as e:
                    logger.error(f"Error forwarding 0x6C2 -> 0x6C0: {e}")

            # --- ROUTE: Cluster to RNS-E ---
            # Cluster sends on 0x6C1 -> forward to RNS-E on 0x6C3
            elif arb_id == 0x6C1:
                forward_msg = can.Message(
                    arbitration_id=0x6C3,
                    data=data,
                    is_extended_id=False
                )
                try:
                    bus.send(forward_msg)
                    desc = ddp_6c1.process_can_frame(data)
                    if desc:
                        print(f"[{time.time():.4f}] [BRIDGE 0x6C1 -> 0x6C3]\n{desc}")
                except Exception as e:
                    logger.error(f"Error forwarding 0x6C1 -> 0x6C3: {e}")

    except KeyboardInterrupt:
        logger.info("Keyboard Interrupt. Shutting down CAN bus...")
    finally:
        bus.shutdown()
        logger.info("CAN bus shutdown successfully. Exiting.")

if __name__ == "__main__":
    main()
