import time
try:
    from ..font_metrics import measure_text, fit_text as fit_font_text, font_profile
except ImportError:
    from font_metrics import measure_text, fit_text as fit_font_text, font_profile

class BaseApp:
    # --- SHARED DISPLAY FLAGS ---
    FLAG_HEADER = 0x22 # Fixed Width + Protocol Center
    FLAG_WIPE   = 0x02 # Fixed Width + Manual Center (Wipes ghosts)
    FLAG_ITEM   = 0x06 # Compact Font + Left Align
    FLAG_ITEM_CENTERED = 0x26 # Compact Font + Protocol Center

    def __init__(self, config=None):
        self.active = False
        self.topics = set()
        self.config = config or {}
        
        # Scroll State: { 'key': {'offset': 0, 'last_tick': 0, 'pause': 0} }
        self._scroll_state = {}

    def get_effective_unit(self, key, default='metric'):
        """
        Gets the effective unit for a given key ('speed', 'cartemp', 'ambient_temp', 'boost').
        Resolves the configuration setting (e.g., 'imperial', 'metric', 'car').
        If 'car', checks the dynamic 'car_units' parsed from CAN message mEinheiten (0x60E).
        """
        units_cfg = self.config.get('display', {}).get('units', {})
        cfg_val = units_cfg.get(key, default)
        
        if cfg_val == 'car':
            car_units = self.config.get('car_units', {})
            if key == 'speed':
                return car_units.get('speed', 'metric')
            elif key in ('cartemp', 'ambient_temp'):
                return car_units.get('temp', 'metric')
            elif key == 'boost':
                # Map car pressure unit to 'imperial' (if psi) or 'metric' (if bar or kPa)
                car_pressure = car_units.get('pressure', 'bar')
                return 'imperial' if car_pressure == 'psi' else 'metric'
            
        return cfg_val

    def format_temp(self, celsius_val, unit_type):
        """Converts Celsius to Fahrenheit if unit_type is imperial, and formats it."""
        try:
            val = float(celsius_val)
            if unit_type == 'imperial':
                f_val = val * 1.8 + 32.0
                return f"{int(round(f_val))}°F"
            else:
                return f"{int(round(val))}°C"
        except (ValueError, TypeError):
            return f"{celsius_val}"

    def set_topics(self, *args):
        for t_set in args: self.topics.update(t_set)

    def on_enter(self):
        """Called when app becomes active"""
        self.active = True

    def on_leave(self):
        """Called when app goes to background"""
        self.active = False
        self._scroll_state = {} # Reset scroll states

    def update_can(self, topic, payload):
        """Called by DisplayEngine when a CAN message arrives."""
        pass

    def update_hudiy(self, topic, data):
        """Called by DisplayEngine when Hudiy API data arrives."""
        pass

    def handle_input(self, action):
        # Return: None, 'BACK', or 'app_name'
        return None

    def get_view(self):
        # Returns Dict (Text Lines) or List (Draw Commands)
        return {}

    def on_frame_sent(self, seq):
        """Called by DisplayEngine when a commit command with seq is sent to the renderer."""
        pass

    def on_frame_acked(self, seq):
        """Called by DisplayEngine when a DRAW_ACK with seq is received from the renderer."""
        pass

    def text_width(self, text, flags=0x06):
        """Physical-pixel advance using the configured cluster font profile."""
        return measure_text(text,flags,font_profile(self.config))

    def fit_text(self, text, width, flags=0x06):
        return fit_font_text(text,width,flags,font_profile(self.config))

    def _scroll_text(self, text, key, max_len=14, speed_ms=None, align='left', start_pause_ms=None, end_pause_ms=None, continuous=None, *, max_width_px=None, font_flags=0x06):
        """
        Returns a window of text that scrolls if longer than max_len.
        - Supports continuous looping.
        - Uses configurable defaults from config.json.
        """
        if not text:
            self._scroll_state.pop(key, None)
            return ""
        text = str(text)

        # 1. Resolve configuration (Param > Config > Default)
        scroll_cfg = self.config.get('display', {}).get('text_scrolling', {})
        if speed_ms is None: speed_ms = scroll_cfg.get('speed_ms', 300)
        if start_pause_ms is None: start_pause_ms = scroll_cfg.get('start_delay_ms', 1000)
        if end_pause_ms is None: end_pause_ms = scroll_cfg.get('end_delay_ms', 250)
        if continuous is None: continuous = scroll_cfg.get('continuous', False)

        if max_width_px is not None:
            return self._scroll_text_pixels(text,key,max_width_px,font_flags,speed_ms,
                                           align,start_pause_ms,end_pause_ms,continuous)

        if len(text) <= max_len:
            # If it fits, remove state so it resets if it grows later
            if key in self._scroll_state: del self._scroll_state[key]
            
            if align == 'center':
                return text.strip() # Return naked string; DIS protocol will center it
            return text # No padding for static left-aligned text

        # 2. Setup scroll state
        now = time.monotonic() * 1000
        
        signature = (text, max_len, bool(continuous))
        if self._scroll_state.get(key, {}).get('signature') != signature:
            self._scroll_state[key] = {
                'signature': signature,
                'offset': 0, 
                'last_tick': now, 
                'pause_until': now + start_pause_ms
            }
            
        state = self._scroll_state[key]
        
        # 3. Handle pause
        if now < state['pause_until']:
            offset = state['offset']
            # Windowing logic for continuous vs restart
            if continuous:
                # Add a separator space for smooth looping
                spacer = chr(0x1F) 
                display_text = text + spacer
                return (display_text * 2)[offset : offset + max_len]
            return text[offset : offset + max_len]

        # 4. Step animation
        if now - state['last_tick'] > speed_ms:
            state['last_tick'] = now
            state['offset'] += 1
            
            if continuous:
                spacer = chr(0x1F)
                full_len = len(text) + len(spacer)
                
                # Recover even if an old offset has passed the cycle boundary.
                if state['offset'] >= full_len:
                    state['offset'] = 0
                    state['pause_until'] = now + start_pause_ms
            else:
                # Standard restart logic
                if state['offset'] + max_len == len(text):
                    state['pause_until'] = now + speed_ms + end_pause_ms
                elif state['offset'] + max_len > len(text):
                    state['offset'] = 0
                    state['pause_until'] = now + start_pause_ms
            
        # 5. Extract current window
        offset = state['offset']
        if continuous:
            spacer = chr(0x1F)
            display_text = text + spacer
            # Wrap around using double-string technique
            return (display_text * 2)[offset : offset + max_len]
        
        return text[offset : offset + max_len]

    def _scroll_text_pixels(self,text,key,width,flags,speed_ms,align,start_pause_ms,end_pause_ms,continuous):
        """Advance by characters while fitting each window to measured pixels."""
        if width<0:raise ValueError('Text width cannot be negative')
        profile=font_profile(self.config)
        total=measure_text(text,flags,profile)
        if total<=width:
            self._scroll_state.pop(key,None)
            return text.strip() if align=='center' else text
        now=time.monotonic()*1000
        signature=(text,'pixels',width,flags&0x0C,profile,bool(continuous))
        if self._scroll_state.get(key,{}).get('signature')!=signature:
            self._scroll_state[key]={'signature':signature,'offset':0,'last_tick':now,
                                     'pause_until':now+start_pause_ms}
        state=self._scroll_state[key]
        display_text=text+chr(0x1F) if continuous else text
        if continuous:
            terminal=len(display_text)
        else:
            # End at the first suffix that fits, not at a fixed character count.
            terminal=0;remaining=total
            while remaining>width and terminal<len(text):
                remaining-=measure_text(text[terminal],flags,profile)
                terminal+=1
        if state['offset']<0 or (continuous and state['offset']>=terminal) or (not continuous and state['offset']>terminal):
            state.update(offset=0,last_tick=now,pause_until=now+start_pause_ms)
        if now>=state['pause_until'] and now-state['last_tick']>speed_ms:
            state['last_tick']=now
            if continuous:
                state['offset']+=1
                if state['offset']>=terminal:
                    state.update(offset=0,pause_until=now+start_pause_ms)
            elif state['offset']>=terminal:
                state.update(offset=0,pause_until=now+start_pause_ms)
            else:
                state['offset']+=1
                if state['offset']>=terminal:
                    state['pause_until']=now+speed_ms+end_pause_ms
        offset=state['offset']
        candidate=(display_text*2)[offset:] if continuous else text[offset:]
        return fit_font_text(candidate,width,flags,profile)
