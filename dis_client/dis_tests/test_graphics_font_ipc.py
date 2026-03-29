#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_graphics_font_ipc.py

Sweeps all 256 character codes in a chosen font to discover unknown glyphs.
Primary use: find hidden large-text or special tiles in the graphics font (0x08).

Builds a reverse AUDSCII map to convert target cluster char codes into the
input characters that dis_service's translate_to_audscii() will map correctly.

Usage:
  python test_graphics_font_ipc.py [--mock] [--font F] [--start N] [--delay S]

  --font F   Font flag bits (0x00=fixed, 0x04=proportional, 0x08=graphics,
             0x0C=unknown/4th). Default: 0x08 (graphics)
  --start N  Start from char code N (decimal or 0xHH hex). Default: 0
  --delay S  Seconds to pause per page of 4 glyphs. Default: 1.5
  --end N    End at char code N (inclusive). Default: 255
"""

import zmq
import time
import json
import os
import sys
import argparse

# --- AUDSCII Table (matches icons.py) ---
# Maps input byte (CP1252/ISO-8859-1) -> cluster char code (AUDSCII)
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
    0xEF,0x9A,0x87,0x86,0x96,0xF6,0x97,0xBA,0xF7,0x89,0x88,0x98,0x99,0xF5,0xF8,0x20,
]

# Build reverse map: cluster char code -> input char code (first-occurrence wins)
REVERSE_AUDSCII = {}
for _i, _v in enumerate(AUDSCII_TRANS):
    if _v not in REVERSE_AUDSCII:
        REVERSE_AUDSCII[_v] = _i

FONT_NAMES = {
    0x00: "Fixed",
    0x04: "Proportional",
    0x08: "Graphics",
    0x0C: "Unknown/4th",
}

COLOUR_RED_BLACK = 0x02  # Red text on black background


def get_input_char(target_code: int):
    """Return chr() that AUDSCII-translates to target_code, or None if unreachable."""
    inp = REVERSE_AUDSCII.get(target_code)
    return chr(inp) if inp is not None else None


def run():
    parser = argparse.ArgumentParser(description="Graphics font / tile sweep test")
    parser.add_argument('--mock', action='store_true', help='Connect to emulator (TCP 5557)')
    parser.add_argument('--font', default='0x08',
                        help='Font flag bits: 0x00=fixed 0x04=prop 0x08=graphics 0x0C=unknown (default: 0x08)')
    parser.add_argument('--start', default='0x00',
                        help='Start char code (decimal or 0xHH). Default: 0x00')
    parser.add_argument('--end', default='0xFF',
                        help='End char code inclusive (decimal or 0xHH). Default: 0xFF')
    parser.add_argument('--delay', type=float, default=1.5,
                        help='Seconds per page of 4 glyphs (default: 1.5)')
    args = parser.parse_args()

    font_flag  = int(args.font,  0)
    start_code = int(args.start, 0)
    end_code   = int(args.end,   0)
    delay      = args.delay
    font_name  = FONT_NAMES.get(font_flag & 0x0C, f"0x{font_flag & 0x0C:02X}")
    text_flags = (font_flag & 0x0C) | COLOUR_RED_BLACK  # font bits + red/black

    # --- ZMQ Connect ---
    config_path = '/home/pi/config.json'
    if not os.path.exists(config_path) and os.path.exists('./config.json'):
        config_path = './config.json'

    if args.mock:
        addr = "tcp://127.0.0.1:5557"
    else:
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            zmq_cfg = cfg.get('interfaces', {}).get('zmq', cfg.get('zmq', {}))
            addr = zmq_cfg.get('dis_draw', "tcp://127.0.0.1:5557")
        except Exception:
            addr = "tcp://127.0.0.1:5557"

    print(f"Connecting to {addr}...")
    ctx  = zmq.Context()
    draw = ctx.socket(zmq.PUSH)
    draw.connect(addr)
    time.sleep(0.5)

    print(f"\n{'='*55}")
    print(f"  Graphics Font Tile Sweep")
    print(f"  Font   : {font_name}  (flags=0x{text_flags:02X})")
    print(f"  Range  : 0x{start_code:02X} - 0x{end_code:02X}")
    print(f"  Delay  : {delay}s per page (4 glyphs)")
    print(f"{'='*55}")

    # Pre-scan: find unmappable codes
    skipped = [c for c in range(start_code, end_code + 1) if get_input_char(c) is None]
    if skipped:
        print(f"  NOTE: {len(skipped)} codes unreachable via AUDSCII: "
              + ", ".join(f"0x{c:02X}" for c in skipped))
    print()

    # --- Initial clear ---
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    time.sleep(0.3)

    # --- Sweep in pages of 4 ---
    PAGE = 4
    codes  = list(range(start_code, end_code + 1))
    pages  = [codes[i:i+PAGE] for i in range(0, len(codes), PAGE)]
    total  = len(pages)

    for page_idx, page in enumerate(pages):
        # Build per-column data
        col_chars  = []   # the glyph char to display
        col_labels = []   # label string for that col
        skipped_cols = []

        for code in page:
            ch = get_input_char(code)
            col_labels.append(f"{code:02X}")
            if ch is None:
                col_chars.append(None)
                skipped_cols.append(code)
            else:
                col_chars.append(ch)

        # --- Build display ---
        # Row 1 (y=1):  font name + page indicator, fixed proportional font
        header = f"{font_name[:3].upper()} {page[0]:02X}-{page[-1]:02X} ({page_idx+1}/{total})"
        
        # Row 2 (y=13): column labels "XX XX XX XX", proportional font
        label_str = " ".join(col_labels)
        
        # Row 3 (y=25): glyphs rendered wide (each at fixed x column)
        # Row 4 (y=37): repeat glyphs for size reference

        # --- Send commands ---
        draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
        draw.send_json({'command': 'draw_text',
                        'text': header, 'x': 0, 'y': 1,
                        'flags': 0x04 | COLOUR_RED_BLACK})  # proportional + red/black

        draw.send_json({'command': 'draw_text',
                        'text': label_str, 'x': 0, 'y': 13,
                        'flags': 0x00 | COLOUR_RED_BLACK})  # fixed font for even spacing

        # Place each glyph at x = 0, 16, 32, 48 (16px apart)
        for col_idx, (ch, code) in enumerate(zip(col_chars, page)):
            x = col_idx * 16
            if ch is None:
                # Draw a "?" using proportional font to indicate skip
                draw.send_json({'command': 'draw_text',
                                'text': '?', 'x': x, 'y': 25,
                                'flags': 0x04 | COLOUR_RED_BLACK})
            else:
                # Draw glyph once large on row 3
                draw.send_json({'command': 'draw_text',
                                'text': ch, 'x': x, 'y': 25,
                                'flags': text_flags})
                # Draw glyph again on row 4 (in case it's double-height)
                draw.send_json({'command': 'draw_text',
                                'text': ch, 'x': x, 'y': 37,
                                'flags': text_flags})

        draw.send_json({'command': 'commit'})

        # Console progress
        glyph_info = " | ".join(
            f"0x{code:02X}={'?' if ch is None else 'ok'}"
            for ch, code in zip(col_chars, page)
        )
        sys.stdout.write(f"\r[{page_idx+1:3d}/{total}] {glyph_info}   ")
        sys.stdout.flush()

        time.sleep(delay)

    # --- Final clear ---
    print()
    print("\nSweep complete. Clearing screen...")
    draw.send_json({'command': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48})
    draw.send_json({'command': 'commit'})
    print("Done.")


if __name__ == "__main__":
    run()
