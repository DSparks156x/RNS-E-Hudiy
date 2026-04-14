# apps/car_info.py
from .base import BaseApp
import time

class CarInfoApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        # Data Store
        self.data = {
            'boost': '--',
            'oil': '--',
            'load': '--',
            'iat': '--',
            'coolant': '--',
            'maf': '--',
            'ign': '--'
        }
        self.tp2_groups = [3]
        self.tp2_low_priority_groups = [113]
        # Atmospheric pressure fallback (standard atmosphere)
        self.atmosphere = 1013.25
        
        # Rate Limiting
        self.last_update_time = 0
        self.update_interval = 0.5 # 500ms (2 FPS max)
        self.cached_view = {}

    def on_enter(self):
        super().on_enter()
        self.last_update_time = 0 # Force immediate refresh
        self.cached_view = {}

    def update_can(self, topic, payload):
        # Legacy CAN ID handling removed.
        pass

    def update_hudiy(self, topic, payload):
        if topic == b'HUDIY_DIAG':
            mod = payload.get('module')
            group = payload.get('group')
            data = payload.get('data', [])
            
            # Atmosphere is now provided via CAN Group 1 from can_service.py
                        
            # Module 01, Group 3: Realtime Engine 
            if mod == 1 and group == 3:
                if len(data) > 1:
                    try:
                        # Block 2: MAF
                        try:
                            val = float(data[1]['value'])
                            # Truncate to 3 digits max integer
                            self.data['maf'] = f"{int(val)}gs"
                        except (ValueError, TypeError):
                            self.data['maf'] = f"{data[1]['value']}gs"
                    except (KeyError, TypeError):
                        pass
                if len(data) > 3:
                    try:
                        # Block 4: Ignition Timing
                        try:
                            val = float(data[3]['value'])
                            # explicit + sign if positive, - if negative, degree symbol
                            self.data['ign'] = f"{val:+.1f}°"
                        except (ValueError, TypeError):
                            self.data['ign'] = f"{data[3]['value']}°"
                    except (KeyError, TypeError):
                        pass

            if group == 0: # Temperatures
                if len(data) > 0: self.data['oil'] = f"{data[0]['value']}{data[0]['unit']}"
                if len(data) > 2: self.data['coolant'] = f"{data[2]['value']}{data[2]['unit']}"
                if len(data) > 3: self.data['iat'] = f"{data[3]['value']}{data[3]['unit']}"
            elif group == 1: # Performance
                # atmosphere is now at index 4
                if len(data) > 4:
                    try:
                        self.atmosphere = float(data[4]['value'])
                    except (ValueError, TypeError):
                        pass

                if len(data) > 1: 
                    try:
                        raw_boost = float(data[1]['value'])
                        
                        # Configuration
                        boost_unit = self.config.get('display', {}).get('units', {}).get('boost', 'metric')
                        boost_mode = self.config.get('display', {}).get('units', {}).get('boost_mode', 'absolute')
                        
                        display_val = raw_boost
                        if boost_mode == 'relative':
                            display_val = raw_boost - self.atmosphere
                            
                        if boost_unit == 'imperial':
                            # mbar to psi
                            psi_val = display_val * 0.0145038
                            sign = "+" if boost_mode == 'relative' and psi_val >= 0 else ""
                            self.data['boost'] = f"{sign}{psi_val:.1f}psi"
                        else:
                            # metric (mbar)
                            sign = "+" if boost_mode == 'relative' and display_val >= 0 else ""
                            self.data['boost'] = f"{sign}{int(round(display_val))}mb"
                            
                    except (ValueError, TypeError):
                        self.data['boost'] = f"{data[1]['value']}mb"
                if len(data) > 3: self.data['load'] = f"{data[3]['value']}{data[3]['unit']}"

    def get_view(self):
        # Rate Limit Check
        now = time.time()
        if (now - self.last_update_time) < self.update_interval and self.cached_view:
            return self.cached_view

        centering = self.config.get('display', {}).get('text_centering', False)
        flag = self.FLAG_ITEM_CENTERED if centering else self.FLAG_ITEM

        lines = {}
        # Line 1: Boost
        lines['line1'] = (f"Boost: {self.data['boost']}", flag)
        # Line 2: MAF
        lines['line2'] = (f"Air: {self.data['maf']}", flag)
        # Line 3: Ignition Timing
        lines['line3'] = (f"Timing: {self.data['ign']}", flag)
        # Line 4: Oil
        lines['line4'] = (f"Oil: {self.data['oil']}", flag)
        # Line 5: Coolant
        lines['line5'] = (f"Coolant: {self.data['coolant']}", flag)
        
        # Update Cache
        self.cached_view = lines
        self.last_update_time = now
        
        return lines