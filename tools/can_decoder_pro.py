#!/usr/bin/env python3
import re
import math
import sys
from typing import List, Dict, Any, Tuple

# Common VAG/KWP multipliers and offsets for formula matching
KNOWN_FACTORS = [0.001, 0.002, 0.01, 0.02, 0.04, 0.08, 0.1, 0.2, 0.25, 0.5, 0.75, 1.0, 1.42, 2.5]
KNOWN_OFFSETS = [0, -128, -64, -54, -48, -40, -100, 100, 128]

import json

def hex_to_bytes(hex_str: str) -> List[int]:
    return [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]

def check_correlation(x_vals: List[float], y_vals: List[float]) -> float:
    if len(x_vals) < 3 or len(x_vals) != len(y_vals): return 0
    n = len(x_vals)
    sum_x = sum(x_vals); sum_y = sum(y_vals)
    sum_x2 = sum(x*x for x in x_vals); sum_y2 = sum(y*y for y in y_vals)
    sum_xy = sum(x*y for x, y in zip(x_vals, y_vals))
    
    num = n * sum_xy - sum_x * sum_y
    den_sq = (n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2)
    if den_sq <= 0: return 0
    return num / math.sqrt(den_sq)

def get_best_correlation_with_lag(x_full: List[float], y_full: List[float], max_lag=1) -> Tuple[float, int]:
    """Tests correlation with small offsets to account for async logging."""
    best_corr = 0
    best_lag = 0
    
    # x is CAN data, y is TP2 data (targets)
    # We test shifting x relative to y
    for lag in range(-max_lag, max_lag + 1):
        if lag == 0:
            corr = check_correlation(x_full, y_full)
        elif lag > 0:
            # Shift x forward (x[1:] matches y[:-1])
            corr = check_correlation(x_full[lag:], y_full[:-lag])
        else:
            # Shift x backward (x[:-1] matches y[1:])
            abs_lag = abs(lag)
            corr = check_correlation(x_full[:-abs_lag], y_full[abs_lag:])
        
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag
            
    return best_corr, best_lag

def find_nearest_formula(m: float, c: float) -> str:
    """Attempts to match regression results to typical KWP2000 math."""
    best_match = ""
    min_err = float('inf')
    
    for f in KNOWN_FACTORS:
        for o_val in KNOWN_OFFSETS:
            # Formula is usually (raw * factor) + offset
            # m corresponds to factor, c corresponds to offset
            err = abs(m - f) + abs(c - o_val) * 0.01 # weight multiplier more
            if err < min_err:
                min_err = err
                best_match = f"raw * {f} + {o_val}"
                
    if min_err < 0.2: # Threshold for "match"
        return f" (KWP Match: {best_match})"
    return ""

def analyze_log(file_path: str):
    print(f"Loading log: {file_path}")
    processed_data = []
    all_fields = set()
    all_can_ids = set()

    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            
        # Detect Format
        if lines and lines[0].strip().startswith('{'):
            # JSONLines with Sample-and-Hold
            latest_can = {}
            for line in lines:
                try:
                    raw = json.loads(line)
                    # Update latest known CAN payloads
                    current_line_can = raw.get('can', {})
                    for can_id, payload_hex in current_line_can.items():
                        if payload_hex:
                            latest_can[can_id.upper()] = hex_to_bytes(payload_hex)
                            all_can_ids.add(can_id.upper())
                    
                    # If this line has TP2 data, create a snapshot paired with the latest CAN state
                    current_tp2 = raw.get('tp2', {})
                    if current_tp2:
                        data = latest_can.copy()
                        for grp, entries in current_tp2.items():
                            for i, ent in enumerate(entries):
                                f_key = f"G{grp}F{i}"
                                val = ent.get('value')
                                if isinstance(val, (int, float)):
                                    data[f_key] = float(val)
                                    all_fields.add(f_key)
                        if data: processed_data.append(data)
                except: continue
        else:
            # Legacy Text Format
            content = "".join(lines)
            entries = content.split("==================================================")
            for entry in entries:
                if "CAN Messages" not in entry or "TP2 Module" not in entry:
                    continue
                data = {}
                can_matches = re.findall(r'\[(\w+)\] Payload: (\w+)', entry)
                for can_id, payload_hex in can_matches:
                    data[can_id.upper()] = hex_to_bytes(payload_hex)
                    all_can_ids.add(can_id.upper())
                group_matches = re.finditer(r'\[Group (\d+)\](.*?)(?=\[Group|$)', entry, re.DOTALL)
                for gm in group_matches:
                    grp_id = gm.group(1)
                    f_matches = re.findall(r'Field (\d): ([\d\-\.]+)', gm.group(2))
                    for f_idx, f_val in f_matches:
                        f_key = f"G{grp_id}F{f_idx}"
                        data[f_key] = float(f_val)
                        all_fields.add(f_key)
                if data: processed_data.append(data)
    except Exception as e:
        print(f"Error: {e}")
        return

    print(f"Analyzed {len(processed_data)} entries. Found {len(all_fields)} fields and {len(all_can_ids)} CAN IDs.\n")

    for field in sorted(list(all_fields)):
        points = [d for d in processed_data if field in d]
        if len(points) < 5: continue
        
        target_vals = [d[field] for d in points]
        # Ignore constant fields
        if max(target_vals) - min(target_vals) < 0.1: continue
        
        results = []
        
        for can_id in sorted(list(all_can_ids)):
            # Helper to add result
            def add_res(x_vals, r_type, idx):
                if not x_vals: return
                # Variance check
                if max(x_vals) - min(x_vals) < 2: return # Need some movement
                
                corr, lag = get_best_correlation_with_lag(x_vals, target_vals)
                if abs(corr) > 0.8:
                    results.append({"type": r_type, "id": can_id, "idx": idx, "corr": corr, "lag": lag, "x": x_vals})

            # Fetch CAN data indices for these points
            can_seqs = [d[can_id] for d in points if can_id in d]
            if not can_seqs or len(can_seqs) != len(target_vals): continue

            # 1. 8-bit (Standard and Inverted)
            for b in range(8):
                if b >= len(can_seqs[0]): continue
                x = [s[b] for s in can_seqs]
                add_res(x, "8b", b)
                # Test inversion (Common for load/pressure if byte is vacuum)
                add_res([255-v for v in x], "8b_inv", b)
            
            # 2. 16-bit
            for b in range(7):
                if b+1 >= len(can_seqs[0]): continue
                x_le = [s[b] + s[b+1]*256 for s in can_seqs]
                add_res(x_le, "16le", b)
                
                x_be = [s[b]*256 + s[b+1] for s in can_seqs]
                add_res(x_be, "16be", b)

            # 3. Product (A*B) - common in RPM formulas
            for b in range(7):
                if b+1 >= len(can_seqs[0]): continue
                x_prod = [s[b] * s[b+1] for s in can_seqs]
                add_res(x_prod, "Prod", b)

        results.sort(key=lambda x: abs(x['corr']), reverse=True)
        if not results: continue

        print(f"--- Field: {field} ---")
        seen_combos = set()
        for r in results[:5]:
            combo = (r['id'], r['type'], r['idx']) # Narrower uniqueness
            if combo in seen_combos: continue
            seen_combos.add(combo)
            
            # Linear regression (account for chosen lag)
            lag = r['lag']
            if lag == 0: x, y = r['x'], target_vals
            elif lag > 0: x, y = r['x'][lag:], target_vals[:-lag]
            else: x, y = r['x'][:lag], target_vals[abs(lag):]
            
            n = len(x)
            sum_x, sum_y = sum(x), sum(y)
            sum_xy, sum_x2 = sum(xi*yi for xi, yi in zip(x, y)), sum(xi*xi for xi in x)
            var_x = (n * sum_x2 - sum_x**2)
            if var_x == 0: continue
            m = (n * sum_xy - sum_x * sum_y) / var_x
            c = (sum_y - m * sum_x) / n
            
            lag_str = f" [lag:{lag:+}]" if lag != 0 else ""
            vag_hint = find_nearest_formula(m, c)
            print(f"  {r['corr']:+.4f}{lag_str} | {r['id']:>3}[{r['idx']}] {r['type']:<4} | y = raw * {m:.4f} + {c:.2f}{vag_hint}")
        print()

if __name__ == "__main__":
    analyze_log(sys.argv[1] if len(sys.argv) > 1 else "decoder.txt")
