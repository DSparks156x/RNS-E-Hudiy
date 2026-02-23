#!/usr/bin/env python3
import sys
import logging
from tp2_protocol import TP2Protocol

# Suppress noisy protocol logs for the scan
logging.getLogger("tp2_protocol").setLevel(logging.WARNING)

def scan_tp2():
    protocol = TP2Protocol(channel='can0')
    protocol.open()
    
    print("Starting TP2.0 Module Scan (0x01 - 0x7F)...")
    print("-----------------------------------------")
    
    found = []
    for mod_id in range(1, 0x80):
        try:
            # We don't use protocol.connect because it does timing negotiation too.
            # We just want to see if the broadcast 0x200 results in a 0x200+ID response.
            
            # 1. Broadcast Request
            tester_id = 0x300
            tester_id_low = tester_id & 0xFF
            tester_id_high = (tester_id >> 8) & 0x0F
            req = [mod_id, 0xC0, 0x00, 0x10, tester_id_low, tester_id_high, 0x01]
            
            protocol._send(0x200, req)
            
            # 2. Wait for Response (short timeout)
            resp_id = 0x200 + mod_id
            resp = protocol._recv(resp_id, 50) # 50ms is enough for a local bus
            
            if resp and resp[1] == 0xD0:
                print(f"Found Module: 0x{mod_id:02X}")
                found.append(mod_id)
                # Send disconnect to keep bus clean
                protocol._send(tester_id, [0xA8])
        except Exception:
            pass

    print("-----------------------------------------")
    print(f"Scan Complete. Found {len(found)} modules.")
    protocol.close()

if __name__ == "__main__":
    scan_tp2()
