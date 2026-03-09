
#!/usr/bin/env python3
import re
import math
import sys
from typing import List, Dict, Any

def hex_to_bytes(hex_str: str) -> List[int]:
    return [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]

def check_correlation(x_vals: List[float], y_vals: List[float]) -> float:
    if len(x_vals) < 2 or len(x_vals) != len(y_vals): return 0
    n = len(x_vals)
    sum_x = sum(x_vals); sum_y = sum(y_vals)
    sum_x2 = sum(x*x for x in x_vals); sum_y2 = sum(y*y for y in y_vals)
    sum_xy = sum(x*y for x, y in zip(x_vals, y_vals))
    
    num = n * sum_xy - sum_x * sum_y
    den_sq = (n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2)
    if den_sq <= 0: return 0
    return num / math.sqrt(den_sq)

def analyze_log(file_path: str):
    print(f"Loading log: {file_path}")
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"Error: {e}")
        return

    entries = content.split("==================================================")
    processed_data = []
    all_fields = set()
    all_can_ids = set()

    for entry in entries:
        if "CAN Messages" not in entry or "TP2 Module 0x01 Groups" not in entry:
            continue
            
        data = {}
        # Parse CAN
        can_matches = re.findall(r'\[(\w+)\] Payload: (\w+)', entry)
        for can_id, payload_hex in can_matches:
            data[can_id] = hex_to_bytes(payload_hex)
            all_can_ids.add(can_id)
            
        # Parse TP2 Groups
        group_matches = re.finditer(r'\[Group (\d+)\](.*?)(?=\[Group|$)', entry, re.DOTALL)
        for gm in group_matches:
            grp_id = gm.group(1)
            f_matches = re.findall(r'Field (\d): ([\d\-\.]+)', gm.group(2))
            for f_idx, f_val in f_matches:
                f_key = f"G{grp_id}F{f_idx}"
                data[f_key] = float(f_val)
                all_fields.add(f_key)
        
        if data:
            processed_data.append(data)

    print(f"Analyzed {len(processed_data)} entries. Found {len(all_fields)} fields and {len(all_can_ids)} CAN IDs.\n")

    for field in sorted(list(all_fields)):
        # Get target values
        points = [d for d in processed_data if field in d]
        if len(points) < 5: continue # Need minimum sample size
        
        target_vals = [d[field] for d in points]
        
        # Correlation candidates
        results = []
        for can_id in sorted(list(all_can_ids)):
            # 8-bit
            for b in range(8):
                x = [d[can_id][b] for d in points if can_id in d and b < len(d[can_id])]
                if len(x) == len(target_vals):
                    corr = check_correlation(x, target_vals)
                    results.append({"type": "8b", "id": can_id, "idx": b, "corr": corr, "x": x})
            
            # 16-bit
            for b in range(7):
                x_le = [d[can_id][b] + d[can_id][b+1]*256 for d in points if can_id in d and b+1 < len(d[can_id])]
                if len(x_le) == len(target_vals):
                    corr = check_correlation(x_le, target_vals)
                    results.append({"type": "16le", "id": can_id, "idx": b, "corr": corr, "x": x_le})
                
                x_be = [d[can_id][b]*256 + d[can_id][b+1] for d in points if can_id in d and b+1 < len(d[can_id])]
                if len(x_be) == len(target_vals):
                    corr = check_correlation(x_be, target_vals)
                    results.append({"type": "16be", "id": can_id, "idx": b, "corr": corr, "x": x_be})

        results = [r for r in results if abs(r['corr']) > 0.85] # Threshold for significance
        results.sort(key=lambda x: abs(x['corr']), reverse=True)
        
        if not results: continue

        print(f"--- Field: {field} ---")
        seen_combos = set()
        for r in results[:5]: # Show top 5 strong correlations
            combo = (r['id'], r['type'])
            if combo in seen_combos: continue
            seen_combos.add(combo)
            
            # Linear regression
            x, y = r['x'], target_vals
            n = len(x)
            sum_x, sum_y = sum(x), sum(y)
            sum_xy, sum_x2 = sum(xi*yi for xi, yi in zip(x, y)), sum(xi*xi for xi in x)
            var_x = (n * sum_x2 - sum_x**2)
            if var_x == 0: continue
            m = (n * sum_xy - sum_x * sum_y) / var_x
            c = (sum_y - m * sum_x) / n
            
            print(f"  {r['corr']:+.4f} | {r['id']:>3}[{r['idx']}] {r['type']:<4} | y = raw * {m:.4f} + {c:.2f}")
        print()

if __name__ == "__main__":
    analyze_log(sys.argv[1] if len(sys.argv) > 1 else "references/log.txt")
