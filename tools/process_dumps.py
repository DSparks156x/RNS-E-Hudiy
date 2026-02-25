#!/usr/bin/env python3
import sys
import glob
import os

# Knwon IDs to ignore (Hex strings)
KNOWN_IDS = {
    # Known from config.json
    "635", "623", "2C3", "602", "365", "367", "6C1", "6C0", "461", "5C3", "661",
    # Typical TP2.0 IDs (Diagnostic/Transport protocol stuff you might want to ignore)
    "200", "288", "300", "301", "302", "303", "304", "305", "306", "307", "308", "309",
    "714", "740"
}

def analyze_dump(file_path):
    print(f"\n{'='*60}")
    print(f"Analyzing {file_path}")
    print(f"{'='*60}\n")
    
    # Store history of each ID
    id_history = {} # ID -> list of (line_num_idx, data_bytes_tuple)
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                # Expecting: can0 3C3 [8] AA 00 00 00 80 E0 26 75
                # Sometimes it has a timestamp like: (16123456.123) can0 3C3 [8] AA 00 ...
                # Let's find "can0" index to be safe
                try:
                    can_idx = parts.index('can0')
                except ValueError:
                    continue
                
                if len(parts) > can_idx + 2 and parts[can_idx + 2].startswith('['):
                    can_id = parts[can_idx + 1].upper().zfill(3) # Ensure at least 3 chars, e.g. ' 5A' -> '05A'
                    
                    # Also strip leading zeros for comparison just in case
                    clean_id = can_id.lstrip('0')
                    if not clean_id: clean_id = '0'
                    
                    if can_id in KNOWN_IDS or clean_id in KNOWN_IDS:
                        continue
                    
                    data_bytes = parts[can_idx + 3:]
                    
                    if can_id not in id_history:
                        id_history[can_id] = []
                    
                    id_history[can_id].append((idx + 1, tuple(data_bytes)))
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return
                
    if not id_history:
        print("No unknown IDs found in this file.")
        return

    # Print analysis per ID
    for can_id, history in sorted(id_history.items()):
        unique_payloads = []
        last_payload = None
        for idx, payload in history:
            if payload != last_payload:
                unique_payloads.append((idx, payload))
                last_payload = payload
                
        print(f"ID: 0x{can_id} (Total messages: {len(history)}, Unique payloads: {len(unique_payloads)})")
        
        if len(unique_payloads) == 0:
            pass
        elif len(unique_payloads) == 1:
            # Steady value
            print(f"  Steady Data: {' '.join(unique_payloads[0][1])}")
        elif len(unique_payloads) < 30:
            # Print all changes
            print("  Changes:")
            for idx, p in unique_payloads:
                print(f"    Line {idx:<6}: {' '.join(p)}")
        else:
            # Too many changes, it's noisy (like RPM, Speed, etc)
            print(f"  Very noisy! Showing first and last few changes...")
            for idx, p in unique_payloads[:3]:
                print(f"    Line {idx:<6}: {' '.join(p)}")
            print("    ...")
            for idx, p in unique_payloads[-3:]:
                print(f"    Line {idx:<6}: {' '.join(p)}")
            
            # Analyze which bytes are actually changing
            first_p = unique_payloads[0][1]
            changing_bytes = set()
            for _, p in unique_payloads:
                for i in range(min(len(first_p), len(p))):
                    if first_p[i] != p[i]:
                        changing_bytes.add(i)
            print(f"  Changing byte indices (0-indexed): {sorted(list(changing_bytes))}")
            
            # Show min/max for changing bytes (hex)
            print("  Min/Max values for changing bytes:")
            for b_idx in sorted(list(changing_bytes)):
                try:
                    vals = [int(p[1][b_idx], 16) for p in unique_payloads if len(p[1]) > b_idx]
                    if vals:
                        min_v = min(vals)
                        max_v = max(vals)
                        print(f"    Byte {b_idx}: Min 0x{min_v:02X}, Max 0x{max_v:02X}")
                except ValueError:
                    pass
        print() # blank line

if __name__ == '__main__':
    files = sys.argv[1:]
    
    # If no files specified, prompt instructions or look for all txt files in current dir
    if not files:
        txt_files = glob.glob('*.txt')
        # Filter out READMEs or standard files
        txt_files = [f for f in txt_files if not f.endswith('example_cmdline.txt') and not f.endswith('example_config.txt')]
        
        if txt_files:
            print(f"Found {len(txt_files)} .txt files in current directory.")
            files = txt_files
        else:
            print("Usage: python process_dumps.py <dumpfile1.txt> [dumpfile2.txt ...]")
            print("You can pass specific files, or just run it with no arguments if the dump files are in the same folder.")
            sys.exit(0)
            
    for f in files:
        analyze_dump(f)
