#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Common VAG Fault Codes (Small subset for testing)
DTC_DB = {
    17965: "Charge Pressure Control: Positive Deviation (Overboost)",
    17964: "Charge Pressure Control: Negative Deviation (Underboost)",
    17552: "Mass Air Flow Sensor (G70): Open or Short to Ground",
    16485: "Mass Air Flow Sensor (G70): Implausible Signal",
    18010: "Power Supply Terminal 30: Voltage too Low",
    16955: "Brake Switch (F): Implausible Signal",
    19586: "EGR System: Regulation Range Exceeded",
    17055: "Cylinder 1 Glow Plug Circuit (Q10): Electrical Fault",
    17056: "Cylinder 2 Glow Plug Circuit (Q11): Electrical Fault",
    17057: "Cylinder 3 Glow Plug Circuit (Q12): Electrical Fault",
    17058: "Cylinder 4 Glow Plug Circuit (Q13): Electrical Fault",
    65535: "Internal Control Module Memory Error"
}

def lookup_dtc(code):
    return DTC_DB.get(code, "Unknown DTC")
