#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging

class TP2Coding:
    """
    Decodes KWP2000 Measuring Blocks based on VW specific formulas.
    Ported from diag.c
    """
    
    @staticmethod
    def decode_block(raw_data: list) -> list:
        """
        Decodes a KWP2000 measuring block response (usually 4 values).
        Format: [Group, Val1_Type, Val1_A, Val1_B, Val2_Type...]
        Returns a list of dicts: [{'value': 12.5, 'unit': 'V', 'raw_type': 5}, ...]
        Skip first byte (Group) before passing to this? 
        Actually, KWP response for ReadGroup (0x21) is:
        [61, Group, Type, A, B, Type, A, B, Type, A, B, Type, A, B]
        We expect just the [Type, A, B...] part here.
        """
        results = []
        # Process triplets (Type, A, B)
        for i in range(0, len(raw_data), 3):
            if i+2 >= len(raw_data): break
            
            t = raw_data[i]
            a = raw_data[i+1]
            b = raw_data[i+2]
            
            val, unit = TP2Coding.decode_value(t, a, b)
            results.append({'value': val, 'unit': unit, 'type': t})
            
        return results

    @staticmethod
    def decode_value(t, a, b):
        val = 0
        unit = ""
        
        # Formulas from diag.c
        if t == 1: # 0.2 * a * b rpm
            val = (a * b) / 5.0
            unit = "rpm"
            
        elif t in [2, 20, 23, 33]:
            # Multiple % formulas
            if t == 2: val = a * 0.002 * b
            elif t == 20: val = a * (b - 128) / 128.0
            elif t == 23: val = (b / 256.0) * a
            elif t == 33: val = 100 * b / a if a != 0 else 100 * b
            unit = "%"
            
        elif t in [3, 9, 27, 34, 67]: # Degrees or similar
            if t == 3: val = 0.002 * a * b
            elif t == 9: val = (b - 127) * 0.02 * a
            elif t == 27: val = abs(b - 128) * 0.01 * a
            elif t == 34: val = (b - 128) * 0.01 * a # kW? diag.c says kW but case is grouped? Check carefully.
            # case 34 in diag.c: kW.
            elif t == 67: val = (640 * a) + b * 2.5
            
            if t == 34: unit = "kW"
            else: unit = "deg"

        elif t == 5: # Temp
            val = a * (b - 100) * 0.1
            unit = "°C"
            
        elif t in [6, 21, 43, 66]: # Voltage
            if t in [6, 21]: val = 0.001 * a * b
            elif t == 43: val = (b * 0.1) + (25.5 * a)
            elif t == 66: val = (a * b) / 511.12
            unit = "V"
            
        elif t == 7: # Speed
            val = (a * b) / 100.0
            unit = "km/h"
            
        elif t == 15: # Time ms
            val = a * b * 0.01
            unit = "ms"
            
        elif t == 18: # Presssure mbar
            val = 0.04 * a * b
            unit = "mbar"
            
        elif t == 19: # Volume l
             val = a * b * 0.01
             unit = "l"
            
        elif t == 25: # Mass Flow g/s
             val = (a / 182.0) + (1.421 * b)
             unit = "g/s"
             
        elif t == 26: # Temp C
            val = b - a
            unit = "°C"
            
        elif t == 35: # Flow l/h
            val = 0.01 * a * b
            unit = "l/h"
            
        elif t == 36: # dist km
            val = (a * 2560 + b * 10) # Wait, standard formula?
            # diag.c says case 36: p += sprintf(p, "km"); but formula?
            # It actually falls through or is missing? 
            # Re-reading diag.c: case 36 just prints "km" without value logic?
            # It seems diag.c is incomplete for some or relies on defaults.
            val = f"{a} {b}" # Raw fallback
            unit = "km"

        elif t == 52: # Torque Nm
             val = (b * 0.02 * a) - a
             unit = "Nm"

        elif t == 56: # WSC
             val = a * 256 + b
             unit = "WSC"
             
        elif t == 83: # Pressure bar
             val = (a * 256 + b) * 0.01
             unit = "bar"

        else:
             # Fallback
             val = f"0x{a:02X}{b:02X}"
             unit = f"Type_{t}"

        # Clean float formatting
        if isinstance(val, float):
            val = round(val, 2)
            
        return val, unit
