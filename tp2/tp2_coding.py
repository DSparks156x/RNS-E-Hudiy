#contains tp2 workers decoding information
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging

class TP2Coding:
    """
    Decodes KWP2000 Measuring Blocks based on VW/VAG specific formulas,
    with unit scaling and display normalization aligned with OpenHaldex.
    """

    UNIT_MAP = {
        "unit_amper": "A",
        "unit_bar": "bar",
        "unit_barpersecon": "bar/s",
        "unit_centinewtometer": "cNm",
        "unit_degrecelsi": "°C",
        "unit_degreofarc": "deg",
        "unit_degreofarcpersecon": "deg/s",
        "unit_forceofgravi": "g",
        "unit_gramperliter": "g/L",
        "unit_hertz": "Hz",
        "unit_hours": "h",
        "unit_kilogram": "kg",
        "unit_kilogrammetersquar": "kg m2",
        "unit_kilometer": "km",
        "unit_kilometerperhour": "km/h",
        "unit_kilonewto": "kN",
        "unit_kilowatt": "kW",
        "unit_liter": "L",
        "unit_meter": "m",
        "unit_meterpercubicsecon": "m3/s",
        "unit_meterperseconsquar": "m/s2",
        "unit_microliter": "uL",
        "unit_millibar": "mbar",
        "unit_milliliter": "mL",
        "unit_millimeter": "mm",
        "unit_millisecon": "ms",
        "unit_minut": "min",
        "unit_minutinver": "rpm",
        "unit_newtometer": "Nm",
        "unit_newtometerpersecon": "Nm/s",
        "unit_ohm": "ohm",
        "unit_percent": "%",
        "unit_percentofforceofgravi": "% g",
        "unit_percentpersecon": "%/s",
        "unit_secon": "s",
        "unit_volt": "V",
        "unit_watt": "W",
        "unit_year": "yr",
    }

    @staticmethod
    def normalize_unit(unit: str) -> str:
        """Standardizes unit strings based on OpenHaldex unit mapping."""
        if not unit:
            return ""
        key = unit.strip().lower()
        return TP2Coding.UNIT_MAP.get(key, unit.strip())

    @staticmethod
    def normalize_display_value(value, unit: str = "", signal_name: str = ""):
        """
        Normalizes numeric display values (e.g., OpenHaldex RPM scaling rule).
        Some decoded RPM signals are published at 1/100 scale (8.25 -> 825).
        """
        if not isinstance(value, (int, float)):
            return value

        norm_unit = str(unit or "").strip().lower()
        norm_name = str(signal_name or "").strip().lower()

        if norm_unit == "rpm" or "rpm" in norm_name:
            abs_v = abs(value)
            if 0 < abs_v < 20:
                scaled = value * 100
                if 100 <= abs(scaled) <= 12000:
                    return round(scaled, 2)
        return value

    @staticmethod
    def decode_block(raw_data: list) -> list:
        """
        Decodes a KWP2000 measuring block response (usually 4 values).
        Format: [Group, Val1_Type, Val1_A, Val1_B, Val2_Type...]
        Returns a list of dicts: [{'value': 12.5, 'unit': 'V', 'type': 5}, ...]
        """
        results = []
        for i in range(0, len(raw_data), 3):
            if i + 2 >= len(raw_data):
                break

            t = raw_data[i]
            a = raw_data[i + 1]
            b = raw_data[i + 2]

            val, unit = TP2Coding.decode_value(t, a, b)
            results.append({'value': val, 'unit': unit, 'type': t})

        return results

    @staticmethod
    def decode_value(t, a, b):
        val = 0
        unit = ""

        # Formula & Scale mappings from KWP2000 VAG specs & OpenHaldex
        if t == 1:  # 0.2 * a * b rpm
            val = (a * b) / 5.0
            unit = "rpm"

        elif t == 2:  # a * 0.002 * b %
            val = a * 0.002 * b
            unit = "%"

        elif t == 3:  # 0.002 * a * b deg
            val = 0.002 * a * b
            unit = "deg"

        elif t == 4:  # abs(b - 127) * 0.01 * a deg OR 0.75*b - 48.0 °C if a == 1
            if a == 1:
                val = 0.75 * b - 48.0
                unit = "°C"
            else:
                val = abs(b - 127) * 0.01 * a
                unit = "deg"

        elif t == 5:  # Temp: a * (b - 100) * 0.1 °C
            val = a * (b - 100) * 0.1
            unit = "°C"

        elif t == 6:  # 0.001 * a * b V
            val = 0.001 * a * b
            unit = "V"

        elif t == 7:  # Speed: (a * b) / 100.0 km/h
            val = (a * b) / 100.0
            unit = "km/h"

        elif t == 8:  # 0.1 * a * b (no unit)
            val = 0.1 * a * b
            unit = ""

        elif t == 9:  # (b - 127) * 0.02 * a deg
            val = (b - 127) * 0.02 * a
            unit = "deg"

        elif t == 10:  # Status COLD / WARM
            val = "COLD" if b == 0 else "WARM"
            unit = ""

        elif t == 11:  # 0.0001 * a * (b - 128) + 1
            val = 0.0001 * a * (b - 128.0) + 1.0
            unit = ""

        elif t == 12:  # 0.001 * a * b ohm
            val = 0.001 * a * b
            unit = "ohm"

        elif t == 13:  # (b - 127) * 0.001 * a mm
            val = (b - 127) * 0.001 * a
            unit = "mm"

        elif t == 14:  # 0.005 * a * b bar
            val = 0.005 * a * b
            unit = "bar"

        elif t == 15:  # Time: 0.01 * a * b ms
            val = 0.01 * a * b
            unit = "ms"

        elif t == 16:  # Bitvalue 8-bit binary string
            bits = []
            for j in [128, 64, 32, 16, 8, 4, 2, 1]:
                if a & j:
                    bits.append('1' if (b & j) else '0')
                else:
                    bits.append('X')
            val = "".join(bits)
            unit = "bitval"

        elif t == 17:  # ASCII chr(a) + chr(b)
            try:
                val = f"{chr(a)}{chr(b)}"
            except Exception:
                val = f"{a:02X}{b:02X}"
            unit = ""

        elif t == 18:  # Pressure: 0.04 * a * b mbar
            val = 0.04 * a * b
            unit = "mbar"

        elif t == 19:  # Volume: a * b * 0.01 L
            val = a * b * 0.01
            unit = "L"

        elif t == 20:  # a * (b - 128) / 128.0 %
            val = a * (b - 128) / 128.0
            unit = "%"

        elif t == 21:  # 0.001 * a * b V
            val = 0.001 * a * b
            unit = "V"

        elif t == 22:  # Time: 0.001 * a * b ms
            val = a * b * 0.001
            unit = "ms"

        elif t == 23:  # (b / 256.0) * a %
            val = (b / 256.0) * a
            unit = "%"

        elif t == 24:  # Current: 0.001 * a * b A
            val = 0.001 * a * b
            unit = "A"

        elif t == 25:  # Mass Flow: (a / 182.0) + (1.421 * b) g/s
            val = (a / 182.0) + (1.421 * b)
            unit = "g/s"

        elif t == 26:  # Temp: b - a °C
            val = b - a
            unit = "°C"

        elif t == 27:  # abs(b - 128) * 0.01 * a deg
            val = abs(b - 128) * 0.01 * a
            unit = "deg"

        elif t == 28:  # Temp: b - a °C
            val = b - a
            unit = "°C"

        elif t == 30:  # Angle: (b / 12.0) * a deg
            val = (b / 12.0) * a
            unit = "deg"

        elif t == 31:  # Temp: (b / 2560.0) * a °C
            val = (b / 2560.0) * a
            unit = "°C"

        elif t == 33:  # 100 * b / a %
            val = (100.0 * b / a) if a != 0 else (100.0 * b)
            unit = "%"

        elif t == 34:  # Power: (b - 128) * 0.01 * a kW
            val = (b - 128) * 0.01 * a
            unit = "kW"

        elif t == 35:  # Flow: 0.01 * a * b L/h
            val = 0.01 * a * b
            unit = "L/h"

        elif t == 36:  # Distance: (a * 256 + b) * 10 km
            val = (a * 256 + b) * 10
            unit = "km"

        elif t == 37:  # Status string
            status_map = {
                0x00: "-",
                0x02: "ADP OK",
                0x05: "Idle",
                0x06: "Partial thr",
                0x07: "WOT",
                0x08: "Enrichment",
                0x09: "Deceleration",
                0x0E: "A/C low",
                0x10: "Compr. OFF",
                0xEB: "Test OFF",
            }
            val = status_map.get(b, f"0x{b:02X}")
            unit = ""

        elif t == 38:  # (b - 128) * 0.001 * a deg
            val = (b - 128.0) * a * 0.001
            unit = "deg"

        elif t == 39:  # b / 256 * a mg/h
            val = (b / 256.0) * a
            unit = "mg/h"

        elif t == 40:  # 0.001 * a * b A
            val = 0.001 * a * b
            unit = "A"

        elif t == 41:  # 0.1 * a * b Ah
            val = 0.1 * a * b
            unit = "Ah"

        elif t == 42:  # Power: (b - 128) * 0.01 * a kW
            val = (b - 128) * 0.01 * a
            unit = "kW"

        elif t == 43:  # Voltage: (b * 0.1) + (25.5 * a) V
            val = (b * 0.1) + (25.5 * a)
            unit = "V"

        elif t == 44:  # Time: a:b h:m
            val = f"{a}:{b:02d}"
            unit = "h:m"

        elif t == 45:  # (a * b) / 1000.0
            val = (a * b) / 1000.0
            unit = ""

        elif t == 46:  # (a * b - 3200) * 0.0027 deg
            val = (a * b - 3200.0) * 0.0027
            unit = "deg"

        elif t == 47:  # (b - 128) * a ms
            val = (b - 128) * a
            unit = "ms"

        elif t == 48:  # a * 256 + b
            val = a * 256 + b
            unit = ""

        elif t == 49:  # (b / 4) * a * 0.1 mg/h
            val = (b / 4.0) * a * 0.1
            unit = "mg/h"

        elif t == 50:  # Pressure: (b - 128) / (0.01 * a) mbar
            val = (b - 128.0) / 0.01
            if a != 0:
                val /= a
            unit = "mbar"

        elif t == 51:  # ((b - 128) / 255) * a mg/h
            val = ((b - 128.0) / 255.0) * a
            unit = "mg/h"

        elif t == 52:  # Torque: (b * 0.02 * a) - a Nm
            val = (b * 0.02 * a) - a
            unit = "Nm"

        elif t == 53:  # Mass Flow: (b - 128) * 1.4222 + 0.006 * a g/s
            val = (b - 128.0) * 1.4222 + 0.006 * a
            unit = "g/s"

        elif t == 54:  # Count: a * 256 + b
            val = a * 256 + b
            unit = "count"

        elif t == 55:  # Time: a * b / 200.0 s
            val = (a * b) / 200.0
            unit = "s"

        elif t in [56, 57]:  # WSC: a * 256 + b
            val = a * 256 + b
            unit = "WSC"

        elif t == 59:  # (a * 256 + b) / 32768.0
            val = (a * 256 + b) / 32768.0
            unit = ""

        elif t == 60:  # Time: (a * 256 + b) * 0.01 s
            val = (a * 256 + b) * 0.01
            unit = "s"

        elif t == 61:  # (b - 128) / a
            val = (b - 128.0) / a if a != 0 else (b - 128.0)
            unit = ""

        elif t == 62:  # Conductance: 0.256 * a * b S
            val = 0.256 * a * b
            unit = "S"

        elif t == 63:  # ASCII character pair
            try:
                val = f"{chr(a)}{chr(b)}?"
            except Exception:
                val = f"{a:02X}{b:02X}?"
            unit = ""

        elif t == 64:  # Resistance: a + b ohm
            val = a + b
            unit = "ohm"

        elif t == 65:  # 0.01 * a * (b - 127) mm
            val = 0.01 * a * (b - 127.0)
            unit = "mm"

        elif t == 66:  # Voltage: (a * b) / 511.12 V
            val = (a * b) / 511.12
            unit = "V"

        elif t == 67:  # (640 * a) + b * 2.5 deg
            val = (640.0 * a) + b * 2.5
            unit = "deg"

        elif t == 68:  # Angular speed: (256 * a + b) / 7.365 deg/s
            val = (256.0 * a + b) / 7.365
            unit = "deg/s"

        elif t == 69:  # Pressure: (256 * a + b) * 0.3254 bar
            val = (256.0 * a + b) * 0.3254
            unit = "bar"

        elif t == 70:  # Acceleration: (256 * a + b) * 0.192 m/s2
            val = (256.0 * a + b) * 0.192
            unit = "m/s2"

        elif t == 83:  # Pressure: (a * 256 + b) * 0.01 bar
            val = (a * 256 + b) * 0.01
            unit = "bar"

        elif t == 94:  # Torque: a * b * 0.1 Nm
            val = a * b * 0.1
            unit = "Nm"

        else:
            # Fallback for unrecognized type
            val = f"0x{a:02X}{b:02X}"
            unit = f"Type_{t}"

        # Clean float formatting & normalize display values / units
        if isinstance(val, float):
            val = round(val, 2)

        val = TP2Coding.normalize_display_value(val, unit)
        unit = TP2Coding.normalize_unit(unit)

        return val, unit

    @staticmethod
    def decode_freeze_frame(raw_data: list) -> list:
        """
        Decodes VAG Environment Data (Freeze Frame) blocks.
        Format: [SID=52, DTC_H, DTC_L, PID, Val, PID, Val...]
        Returns a list of dicts: [{'label': 'Mileage', 'value': 1234, 'unit': 'km'}, ...]
        """
        if not raw_data or len(raw_data) < 4:
            return []

        # Skip SID (52) and DTC (2 bytes)
        # Payload starts at index 3
        data = raw_data[3:]
        results = []
        i = 0

        while i < len(data):
            pid = data[i]
            if i + 1 >= len(data):
                break

            # Common VAG Environment Data PIDs
            if pid == 0x6C:  # Priority
                results.append({'label': 'Priority', 'value': data[i + 1], 'known': True})
                i += 2
            elif pid == 0x2B:  # Frequency
                results.append({'label': 'Frequency', 'value': data[i + 1], 'known': True})
                i += 2
            elif pid == 0x02:  # Reset Counter
                results.append({'label': 'Reset Counter', 'value': data[i + 1], 'known': True})
                i += 2
            elif pid == 0x03:  # Mileage (Fixed 3 bytes in most blocks)
                if i + 3 < len(data):
                    val = (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3]
                    results.append({'label': 'Mileage', 'value': val, 'unit': 'km', 'known': True})
                    i += 4
                else:
                    i += 2  # Fallback
            elif pid == 0x58:  # Speed
                results.append({'label': 'Speed', 'value': data[i + 1], 'unit': 'km/h', 'known': True})
                i += 2
            elif pid == 0x2E:  # Voltage
                results.append({'label': 'Voltage', 'value': round(data[i + 1] * 0.1, 1), 'unit': 'V', 'known': True})
                i += 2
            elif pid == 0x24:  # Distance (3 bytes)
                if i + 3 < len(data):
                    val = (data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3]
                    results.append({'label': 'Distance', 'value': val, 'unit': 'km', 'known': True})
                    i += 4
                else:
                    i += 2
            elif pid == 0x5B:  # Engine Load
                results.append({'label': 'Engine Load', 'value': data[i + 1], 'unit': '%', 'known': True})
                i += 2
            elif pid == 0x4E:  # Engine Speed
                if i + 2 < len(data):
                    val = (data[i + 1] << 8) | data[i + 2]
                    val = TP2Coding.normalize_display_value(val, "rpm", "Engine Speed")
                    results.append({'label': 'Engine Speed', 'value': val, 'unit': 'rpm', 'known': True})
                    i += 3
                else:
                    i += 2
            else:
                # Unknown/Generic 1-byte value
                results.append({'label': f'PID_0x{pid:02X}', 'value': data[i + 1], 'known': False})
                i += 2

        return results

    @staticmethod
    def decode_dtc_status(status_byte: int) -> list:
        """
        Decodes a DTC status byte based on ISO 14229-1 (UDS).
        Returns a list of active status strings.
        """
        meanings = [
            (0x01, "Test Failed"),
            (0x02, "Failed This Cycle"),
            (0x04, "Pending"),
            (0x08, "Confirmed"),
            (0x10, "Not Completed Since Clear"),
            (0x20, "Failed Since Clear"),
            (0x40, "Not Completed This Cycle"),
            (0x80, "Warning Requested")
        ]

        active = []
        for bit, text in meanings:
            if status_byte & bit:
                active.append(text)

        return active if active else ["No Status"]
