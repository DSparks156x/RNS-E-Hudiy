#!/usr/bin/env python3
import time
import logging
from tp2_protocol import TP2Protocol

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

def identify_module(mod_id):
    protocol = TP2Protocol(channel='can0')
    try:
        protocol.open()
        if not protocol.connect(mod_id):
            return None
        
        # Start session
        protocol.send_kvp_request([0x10, 0x01])
        
        info = {}
        
        # Part Number (0x1A 0x80)
        resp = protocol.send_kvp_request([0x1A, 0x80])
        if resp and resp[0] == 0x5A:
            part_num = "".join([chr(b) for b in resp[2:] if 32 <= b <= 126])
            info['part_num'] = part_num.strip()
            
        # Component info (0x1A 0x91)
        resp = protocol.send_kvp_request([0x1A, 0x91])
        if resp and resp[0] == 0x5A:
            comp = "".join([chr(b) for b in resp[2:] if 32 <= b <= 126])
            info['component'] = comp.strip()
            
        return info
    except Exception as e:
        return None
    finally:
        protocol.close()

if __name__ == "__main__":
    # The modules found in your scan
    modules = [0x01, 0x02, 0x03, 0x05, 0x06, 0x07, 0x0A, 0x1F, 0x20, 0x22, 0x23, 0x29, 0x2A, 0x2C, 0x4F, 0x52, 0x5A]
    
    print(f"{'Addr':<6} | {'Part Number':<15} | {'Component'}")
    print("-" * 65)
    for m in modules:
        id_info = identify_module(m)
        if id_info:
            p = id_info.get('part_num', 'N/A')
            c = id_info.get('component', 'N/A')
            print(f"0x{m:02X}   | {p:<15} | {c}")
        else:
            print(f"0x{m:02X}   | Failed to connect/read")
        time.sleep(0.1)
