from .base import BaseApp
import time

class AccelerationTestApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        
        acc_cfg = self.config.get('display', {}).get('center_display', {}).get('acceleration_test', {})
        self.speed_unit = self.config.get('display', {}).get('units', {}).get('speed', 'imperial')
        self.dist_unit_str = "mi" if self.speed_unit == 'imperial' else "km"
        self.speed_unit_str = "mph" if self.speed_unit == 'imperial' else "kmh"
        
        # Parse after units are defined so we can append the label
        self.thresholds = []
        for i in range(1, 5):
            val = acc_cfg.get(f'line_{i}', '')
            t = self.parse_threshold(val)
            self.thresholds.append(t)
        
        # State tracking
        self.total_distance = 0.0
        self.last_speed = 0.0
        self.last_time = 0.0
        
        self.cached_view = {}
        self.last_update_time = 0
        self.update_interval = 0.2  # UI refresh rate limit when ticking
        
    def on_enter(self):
        super().on_enter()
        self.last_update_time = 0 # Force refresh immediately on view
        self.cached_view = {}

    def reset_timers(self):
        for t in self.thresholds:
            if t and t.get('type') != 'current_speed':
                t['status'] = 'waiting'
                t['time_str'] = '-.---'
                t['max_speed_seen'] = 0
                t['start_time'] = 0
                t['end_time'] = 0
                t['start_dist'] = 0
        self.total_distance = 0.0

    def parse_threshold(self, val):
        if not val: return None
        val = str(val).strip()
        
        if val.lower() == 'speed':
            return {
                'raw': val,
                'label': 'Speed',
                'type': 'current_speed',
                'status': 'n/a',
                'time_str': f"0 {self.speed_unit_str}"
            }
        
        # Speed range (e.g. 0-60)
        if '-' in val:
            parts = val.split('-')
            try:
                start = float(parts[0])
                end = float(parts[1])
                return {
                    'raw': val,
                    'label': val,
                    'type': 'speed',
                    'start_speed': start,
                    'end_speed': end,
                    'status': 'waiting',
                    'time_str': '-.---',
                    'start_time': 0,
                    'end_time': 0,
                    'max_speed_seen': 0
                }
            except: pass
            
        # Distance fraction (e.g. 1/4)
        if '/' in val:
            parts = val.split('/')
            try:
                dist = float(parts[0]) / float(parts[1])
                return {
                    'raw': val,
                    'label': f"{val}{self.dist_unit_str}",
                    'type': 'distance',
                    'distance': dist, # Expected in miles or km depending on unit config
                    'status': 'waiting',
                    'time_str': '-.---',
                    'start_time': 0,
                    'start_dist': 0,
                    'end_time': 0,
                    'max_speed_seen': 0
                }
            except: pass
            
        # Distance whole number (e.g. 1)
        try:
            dist = float(val)
            return {
                'raw': val,
                'label': f"{val}{self.dist_unit_str}",
                'type': 'distance',
                'distance': dist,
                'status': 'waiting',
                'time_str': '-.---',
                'start_time': 0,
                'start_dist': 0,
                'end_time': 0,
                'max_speed_seen': 0
            }
        except: pass
        
        return None

    def update_can(self, topic, payload):
        # We listen directly to CAN_351 for high-res speed updates.
        if '351' in topic and len(payload) >= 3:
            speed_kmh = (payload[2] * 256 + payload[1]) / 480.0
            if self.speed_unit == 'imperial':
                speed = speed_kmh * 0.621371
            else:
                speed = speed_kmh
            self.process_speed(speed)

    def process_speed(self, new_speed):
        now = time.time()
        if self.last_time == 0:
            self.last_time = now
            self.last_speed = new_speed
            return
            
        dt = now - self.last_time
        if dt <= 0: return
        
        # Accumulate distance in base unit
        # speed is units/h -> convert to units/s
        speed_per_s = new_speed / 3600.0
        self.total_distance += speed_per_s * dt
        
        if new_speed < 1.0: # Basically stopped
            self.reset_timers()
        
        else:
            for t in self.thresholds:
                if not t: continue
                
                if t['type'] == 'speed':
                    if t['status'] == 'waiting':
                        if self.last_speed <= t['start_speed'] and new_speed > t['start_speed']:
                            # Started - interpolate exact crossing time
                            fraction = 0
                            if new_speed != self.last_speed:
                                fraction = (t['start_speed'] - self.last_speed) / (new_speed - self.last_speed)
                            t['start_time'] = self.last_time + dt * fraction
                            t['status'] = 'running'
                            t['max_speed_seen'] = new_speed
                            
                    elif t['status'] == 'running':
                        if new_speed > t['max_speed_seen']:
                            t['max_speed_seen'] = new_speed
                            
                        if new_speed >= t['end_speed']:
                            # Finished!
                            fraction = 0
                            if new_speed != self.last_speed:
                                fraction = (t['end_speed'] - self.last_speed) / (new_speed - self.last_speed)
                            t['end_time'] = self.last_time + dt * fraction
                            t['status'] = 'done'
                            elapsed = t['end_time'] - t['start_time']
                            t['time_str'] = f"{elapsed:.3f}s"
                        elif new_speed < t['max_speed_seen'] - 5:
                            # Aborted
                            t['status'] = 'waiting'
                            
                    elif t['status'] == 'done':
                        if new_speed < t['start_speed']:
                            t['status'] = 'waiting'
                            t['time_str'] = '-.---'
                            
                elif t['type'] == 'distance':
                    if t['status'] == 'waiting':
                        # A distance threshold starts off exactly when starting from 0.
                        # Using 1.0 margin as launched threshold.
                        if self.last_speed < 1.0 and new_speed >= 1.0:
                            # Interpolate exactly crossing 1.0 margin
                            fraction = (1.0 - self.last_speed) / (new_speed - self.last_speed) if new_speed != self.last_speed else 0
                            
                            t['start_time'] = self.last_time + dt * fraction
                            t['start_dist'] = self.total_distance
                            t['status'] = 'running'
                            t['max_speed_seen'] = new_speed
                            
                    elif t['status'] == 'running':
                        if new_speed > t['max_speed_seen']:
                            t['max_speed_seen'] = new_speed
                            
                        dist_covered = self.total_distance - t['start_dist']
                        if dist_covered >= t['distance']:
                            t['end_time'] = now
                            t['status'] = 'done'
                            elapsed = t['end_time'] - t['start_time']
                            t['time_str'] = f"{elapsed:.3f}s"
                        elif new_speed < t['max_speed_seen'] - 5:
                            t['status'] = 'waiting'

        self.last_speed = new_speed
        self.last_time = now

    def get_view(self):
        now = time.time()
        
        is_running = False
        is_done = False
        
        for t in self.thresholds:
            if not t: continue
            
            if t.get('type') == 'current_speed':
                t['time_str'] = f"{int(round(self.last_speed))} {self.speed_unit_str}"
            elif t['status'] == 'running':
                is_running = True
                elapsed = now - t['start_time']
                t['time_str'] = f"{elapsed:.1f}s" 
            elif t['status'] == 'done':
                is_done = True
                
        if self.last_speed < 1.0:
            header = "Ready"
        elif is_running:
            header = "Timing"
        elif is_done:
            header = "Done"
        else:
            header = "Rolling"

        if (now - self.last_update_time) < self.update_interval and self.cached_view:
            return self.cached_view

        centering = self.config.get('display', {}).get('text_centering', False)
        flag = self.FLAG_ITEM_CENTERED if centering else self.FLAG_ITEM
        
        lines = {}
        lines['line1'] = (header, flag)
        
        for i, t in enumerate(self.thresholds):
            line_idx = f"line{i+2}"
            if t:
                lines[line_idx] = (f"{t['label']}: {t['time_str']}", flag)
            else:
                lines[line_idx] = ("", flag)
                
        self.cached_view = lines
        self.last_update_time = now
        
        return lines
