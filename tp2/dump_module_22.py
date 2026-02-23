#!/usr/bin/env python3
import time
from tp2_protocol import TP2Protocol

def dump_awd_data(groups=[1, 2, 3, 4, 5]):
    # Note: Address 22 in VCDS is Hex 0x22, which is 34 decimal.
    # If you were passing 22 decimal, you were connecting to 0x16 (Steering Wheel)
    AWD_MODULE_ADDR = 0x22
    protocol = TP2Protocol(channel='can0')
    print(f"Connecting to AWD Module (0x{AWD_MODULE_ADDR:02X}) to dump Groups {groups}...")
    
    try:
        protocol.open()
        if not protocol.connect(AWD_MODULE_ADDR):
            print("Failed to connect to AWD module.")
            return

        # Start Session 0x89 (required for most modules to read groups)
        resp = protocol.send_kvp_request([0x10, 0x89])
        if not resp or resp[0] == 0x7F:
            print(f"Session Failed: {resp}")
            return
            
        protocol.send_keep_alive()
        print("Connected! Dumping Raw Data...")

        for group_id in groups:
            try:
                resp = protocol.send_kvp_request([0x21, group_id])
                if resp and len(resp) >= 2 and resp[0] == 0x61 and resp[1] == group_id:
                    hex_data = " ".join([f"{b:02X}" for b in resp[2:]])
                    print(f"Group {group_id} Raw Data: {hex_data}")
                else:
                    print(f"Group {group_id} Failed to read. Response: {resp}")
            except Exception as e:
                print(f"Error reading Group {group_id}: {e}")
            
            # keep-alive between requests
            try:
                protocol.send_keep_alive()
            except:
                pass
            time.sleep(0.1)

    except Exception as e:
        print(f"Fatal Error: {e}")
    finally:
        protocol.close()

if __name__ == "__main__":
    dump_awd_data()
