#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import json
import logging
from tp2_protocol import TP2Protocol

logging.getLogger("tp2_protocol").setLevel(logging.WARNING)

def get_can_channel():
    can_channel = 'can0'
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
        with open(config_path) as f:
            config = json.load(f)
            can_channel = config.get('interfaces', {}).get('can', {}).get('diagnostic', 'can0')
    except Exception as e:
        pass
    return can_channel

def fetch_installed_modules(gateway_id, can_channel):
    print(f"Attempting to query Gateway at 0x{gateway_id:02X} over {can_channel}...")
    proto = TP2Protocol(channel=can_channel, tester_id=0x300)
    try:
        proto.open()
        if not proto.connect(gateway_id):
            print(f"[-] Could not connect to Gateway at 0x{gateway_id:02X}")
            return False
            
        print(f"[+] Connected to Gateway 0x{gateway_id:02X}. Starting Diagnostic Session (10 89)...")
        resp = proto.send_kvp_request([0x10, 0x89])
        if not resp or resp[0] == 0x7F:
            print(f"[-] Failed to start diagnostic session. Response: {resp}")
            return False
            
        print("[+] Session active. Requesting Installation List (SID 1A, Param 9F)...")
        resp = proto.send_kvp_request([0x1A, 0x9F])
        
        if not resp:
            print("[-] No response to 1A 9F request.")
            return False
        elif resp[0] == 0x7F:
            print(f"[-] Request rejected by gateway: {[hex(x) for x in resp]}")
            return False
        elif resp[0] == 0x5A and resp[1] == 0x9F:
            data = resp[2:]
            print(f"[+] Success! Received {len(data)} bytes of installation data.")
            print(f"Raw Hex: {' '.join([f'{x:02X}' for x in data])}")
            
            # Simple heuristic parsing of modules:
            # We'll print out the unique addresses found in the payload that fall in the valid ECU range.
            modules = set()
            for b in data:
                # Valid modules are usually 0x01 up to 0x7F
                if 0x00 < b < 0x80:
                    modules.add(b)
            
            print("\nPossible Module Addresses Extracted from Payload:")
            for m in sorted(list(modules)):
                print(f" - 0x{m:02X}")
            return True
        else:
            print(f"[-] Unexpected response formatting: {[hex(x) for x in resp]}")
            return False
            
    except Exception as e:
        print(f"[-] Error: {e}")
        return False
    finally:
        try:
            proto.disconnect()
            proto.close()
        except:
            pass

if __name__ == "__main__":
    can_chan = get_can_channel()
    
    # As noted, while the Gateway is logical address 0x19, 
    # it responds to TP2.0 Channel Setup on ID 0x1F.
    print("Initiating TP2.0 session with Gateway ID 0x1F...")
    fetch_installed_modules(0x1F, can_chan)

