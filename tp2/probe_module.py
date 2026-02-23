#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_module.py - Verbose TP2.0 diagnostic tool for any module.

Usage:
    python3 probe_module.py -m 0x02 11 12    # Transmission, groups 11 & 12
    python3 probe_module.py -m 0x22 1 3      # AWD, groups 1 & 3
    python3 probe_module.py -m 0x01 3        # Engine, group 3 (default)
"""
import time
import logging
import argparse
import sys
import can
from tp2_protocol import TP2Protocol, TP2Error
from tp2_coding import TP2Coding

# Full verbose logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def probe_connect(module_id: int) -> TP2Protocol | None:
    """
    Attempt TP2.0 connection with verbose output.
    Returns connected protocol or None on failure.
    """
    proto = TP2Protocol(channel='can0')
    print(f"\n{'='*60}")
    print(f"  PROBE: Module 0x{module_id:02X}")
    print(f"{'='*60}")

    try:
        proto.open()
    except TP2Error as e:
        print(f"[FAIL] CAN bus open failed: {e}")
        return None

    # --- Step 1: Broadcast ---
    print(f"\n[1] Sending broadcast request to 0x{module_id:02X} on 0x200...")
    req = [module_id, 0xC0, 0x00, 0x10, 0x00, 0x03, 0x01]
    proto._send(0x200, req)

    resp = proto._recv(0x201, timeout_ms=1500)
    if not resp:
        print("[FAIL] No response on 0x201. Module not present or not responding.")
        proto.close()
        return None

    print(f"[OK  ] Broadcast response: {[f'0x{b:02X}' for b in resp]}")

    # Check response header — byte 1 should be 0xD0 for a valid channel setup
    if resp[1] != 0xD0:
        print(f"[WARN] Unexpected opcode byte: 0x{resp[1]:02X} (expected 0xD0)")
    if resp[0] != 0x00:
        print(f"[WARN] Response byte[0]=0x{resp[0]:02X} (expected 0x00 — check if module ID matches)")

    # Parse dynamic CAN IDs
    tx_id = (resp[5] << 8) | resp[4]
    rx_id = proto.tester_id  # We listen on 0x300
    print(f"       TX to ECU: 0x{tx_id:03X}  |  RX from ECU: 0x{rx_id:03X}")

    proto.tx_id = tx_id
    proto.rx_id = rx_id

    # --- Step 2: Timing parameters ---
    print(f"\n[2] Sending timing parameters (A0)...")
    params = [0xA0, 0x0F, 0x8A, 0xFF, 0x32, 0xFF]
    proto._send(proto.tx_id, params)

    resp = proto._recv(proto.rx_id, timeout_ms=1000)
    if not resp:
        print("[FAIL] No timing response (A1). Module may not support TP2 on this ID.")
        proto.close()
        return None

    print(f"[OK  ] Timing response: {[f'0x{b:02X}' for b in resp]}")
    if resp[0] != 0xA1:
        print(f"[WARN] Expected 0xA1, got 0x{resp[0]:02X}")

    proto.connected = True
    proto.seq_tx = 0
    proto.seq_rx = 0

    # --- Step 3: Start KWP session ---
    print(f"\n[3] Starting KWP session (0x10 0x89)...")
    try:
        resp = proto.send_kvp_request([0x10, 0x89])
        if resp and resp[0] != 0x7F:
            print(f"[OK  ] Session started: {[f'0x{b:02X}' for b in resp]}")
        else:
            print(f"[FAIL] Session rejected: {resp}")
            proto.close()
            return None
    except TP2Error as e:
        print(f"[FAIL] Session error: {e}")
        proto.close()
        return None

    proto.send_keep_alive()
    print(f"\n[OK  ] Module 0x{module_id:02X} connected and ready.\n")
    return proto


def read_groups(proto: TP2Protocol, module_id: int, groups: list[int], iterations: int = 3):
    """Read each group N times and print decoded data."""
    for grp in groups:
        print(f"\n--- Group {grp} (0x{grp:02X}) ---")
        for i in range(iterations):
            try:
                resp = proto.send_kvp_request([0x21, grp])
                if resp and resp[0] == 0x61:
                    decoded = TP2Coding.decode_block(resp[2:])
                    vals = ", ".join([f"{item['value']}{item['unit']}" for item in decoded])
                    print(f"  [{i+1}] {vals}")
                elif resp and resp[0] == 0x7F:
                    print(f"  [{i+1}] REJECTED (NRC=0x{resp[2]:02X if len(resp)>2 else 0:02X})")
                    break
                else:
                    print(f"  [{i+1}] Unexpected response: {resp}")
            except TP2Error as e:
                print(f"  [{i+1}] ERROR: {e}")
            try:
                proto.send_keep_alive()
            except Exception:
                pass
            time.sleep(0.05)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Verbose TP2.0 module probe.')
    parser.add_argument(
        '-m', '--module',
        default='0x01',
        help='Module ID in hex (e.g. 0x01, 0x02, 0x22) or decimal. Default: 0x01'
    )
    parser.add_argument(
        '-n', '--iterations',
        type=int,
        default=3,
        help='How many times to read each group. Default: 3'
    )
    parser.add_argument(
        'groups',
        nargs='*',
        help='Group numbers to read. Default: 1'
    )
    args = parser.parse_args()

    # Parse module ID
    try:
        module_id = int(args.module, 0)
    except ValueError:
        print(f"Invalid module ID: {args.module}")
        sys.exit(1)

    # Parse groups
    groups = [1]
    if args.groups:
        try:
            raw = ' '.join(args.groups)
            groups = [int(x, 0) for x in raw.replace(',', ' ').split()]
        except ValueError:
            print("Invalid group numbers.")
            sys.exit(1)

    proto = probe_connect(module_id)
    if not proto:
        print(f"\n[FAIL] Could not connect to module 0x{module_id:02X}.")
        sys.exit(1)

    try:
        read_groups(proto, module_id, groups, args.iterations)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        proto.close()
        print("\nDone.")
