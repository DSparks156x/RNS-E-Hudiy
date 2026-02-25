# apps/car_info.py
from .base import BaseApp
import time

class CarInfoApp(BaseApp):
    def __init__(self):
        super().__init__()
        # Data Store
        self.data = {
            'oil': '--',
            'bat': '--.-',
            'fuel': '--'
        }
        # Rate Limiting
        self.last_update_time = 0
        self.update_interval = 0.5 # 500ms (2 FPS max)
        self.cached_view = {}

    def update_can(self, topic, payload):
        # Example CAN IDs (Adjust to match your actual config)
        # For now, I'll assume some standard-ish logic or just store raw values
        
        # Oil Temp (Example ID 0x555, byte 7 - 60)
        if '555' in topic: 
            try:
                temp = payload[7] - 60
                self.data['oil'] = f"{temp}C"
            except: pass

        # Battery Voltage (Example ID 0x571)
        if '571' in topic: # Adjust ID!
            try:
                volts = ((payload[0]/2)+50)/10
                self.data['bat'] = f"{volts:.1f}V"
            except: pass
            
        # Fuel Level (Example ID 0x35B, byte 5)
        if '35B' in topic:
            try:
                liters = payload[5]
                self.data['fuel'] = f"{liters}L"
            except: pass

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']: return 'BACK'
        return None

    def get_view(self):
        # Rate Limit Check
        now = time.time()
        if (now - self.last_update_time) < self.update_interval and self.cached_view:
            return self.cached_view

        lines = {}
        lines['line1'] = ("Car Info", self.FLAG_HEADER)

        # Line 2: Oil Temp
        oil_txt = f"Oil: {self.data['oil']}".ljust(16)[:16]
        lines['line2'] = (oil_txt, self.FLAG_ITEM)

        # Line 3: Battery
        bat_txt = f"Batt: {self.data['bat']}".ljust(16)[:16]
        lines['line3'] = (bat_txt, self.FLAG_ITEM)

        # Line 4: Fuel
        fuel_txt = f"Fuel: {self.data['fuel']}".ljust(16)[:16]
        lines['line4'] = (fuel_txt, self.FLAG_ITEM)

        # Line 5: Back
        lines['line5'] = ("Back".ljust(16)[:16], self.FLAG_ITEM)

        # Update Cache
        self.cached_view = lines
        self.last_update_time = now
        
        return lines