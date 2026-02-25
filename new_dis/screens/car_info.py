from typing import List, Dict, Any
from .base import ScreenBase

class CarInfoScreen(ScreenBase):
    def __init__(self):
        super().__init__()
        self.needs_full_screen = True
        
        # Mock Data / Real Data
        self.oil_temp = 0
        self.coolant = 0
        self.fuel_level = 0
        self.battery_v = 0.0

    def handle_can_message(self, topic: str, payload_hex: bytes):
        # Decode CAN messages here based on standard RNS-E CAN IDs.
        pass

    def render(self) -> List[Dict[str, Any]]:
        elements = []

        # Title
        elements.append(self.create_text("VEHICLE INFO", 8, 2, flags=0x86)) # Inverted red bg

        # Measuring blocks
        # row 1
        elements.append(self.create_text("Oil T:", 0, 20))
        elements.append(self.create_text(f"{self.oil_temp}°C", 32, 20))
        
        # row 2
        elements.append(self.create_text("Coolant:", 0, 35))
        elements.append(self.create_text(f"{self.coolant}°C", 40, 35))
        
        # row 3
        elements.append(self.create_text("Fuel:", 0, 50))
        elements.append(self.create_text(f"{self.fuel_level}L", 32, 50))
        
        # row 4
        elements.append(self.create_text("Voltage:", 0, 65))
        elements.append(self.create_text(f"{self.battery_v}v", 40, 65))

        return elements
