# apps/car_info.py
from .base import BaseApp
import time

class CarInfoApp(BaseApp):
    def __init__(self):
        super().__init__()
        # Data Store
        self.data = {
            'boost': '--',
            'oil': '--',
            'load': '--',
            'iat': '--'
        }
        # Rate Limiting
        self.last_update_time = 0
        self.update_interval = 0.5 # 500ms (2 FPS max)
        self.cached_view = {}

    def update_can(self, topic, payload):
        # Legacy CAN ID handling removed.
        pass

    def update_hudiy(self, topic, payload):
        if topic == b'HUDIY_DIAG':
            group = payload.get('group')
            data = payload.get('data', [])
            if group == 0: # Temperatures
                if len(data) > 0: self.data['oil'] = f"{data[0]['value']}{data[0]['unit']}"
                if len(data) > 3: self.data['iat'] = f"{data[3]['value']}{data[3]['unit']}"
            elif group == 1: # Performance
                if len(data) > 1: self.data['boost'] = f"{data[1]['value']}{data[1]['unit']}"
                if len(data) > 3: self.data['load'] = f"{data[3]['value']}{data[3]['unit']}"

    def get_view(self):
        # Rate Limit Check
        now = time.time()
        if (now - self.last_update_time) < self.update_interval and self.cached_view:
            return self.cached_view

        lines = {}
        # Line 1: Boost
        lines['line1'] = (f"Boost: {self.data['boost']}".ljust(16)[:16], self.FLAG_ITEM)
        # Line 2: Oil Temp
        lines['line2'] = (f"Oil:   {self.data['oil']}".ljust(16)[:16], self.FLAG_ITEM)
        # Line 3: Load Actual
        lines['line3'] = (f"Load:  {self.data['load']}".ljust(16)[:16], self.FLAG_ITEM)
        # Line 4: IAT
        lines['line4'] = (f"IAT:   {self.data['iat']}".ljust(16)[:16], self.FLAG_ITEM)
        # Line 5: Status/Free
        lines['line5'] = ("".ljust(16)[:16], self.FLAG_ITEM)

        # Update Cache
        self.cached_view = lines
        self.last_update_time = now
        
        return lines