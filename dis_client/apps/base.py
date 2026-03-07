import time

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

    def _scroll_text(self, text, key, max_len=14, speed_ms=None, align='left', start_pause_ms=None, end_pause_ms=None, continuous=None):
        """
        Returns a window of text that scrolls if longer than max_len.
        - Supports continuous looping.
        - Uses configurable defaults from config.json.
        """
        if not text: return ""
        text = str(text)

        # 1. Resolve configuration (Param > Config > Default)
        scroll_cfg = self.config.get('display', {}).get('text_scrolling', {})
        if speed_ms is None: speed_ms = scroll_cfg.get('speed_ms', 300)
        if start_pause_ms is None: start_pause_ms = scroll_cfg.get('start_delay', 1000)
        if end_pause_ms is None: end_pause_ms = scroll_cfg.get('end_delay', 250)
        if continuous is None: continuous = scroll_cfg.get('continuous', False)

        if len(text) <= max_len:
            # If it fits, remove state so it resets if it grows later
            if key in self._scroll_state: del self._scroll_state[key]
            
            if align == 'center':
                return text.strip() # Return naked string; DIS protocol will center it
            return text # No padding for static left-aligned text

        # 2. Setup scroll state
        now = time.time() * 1000
        
        if key not in self._scroll_state:
            self._scroll_state[key] = {
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
                
                # If we've scrolled exactly one full cycle (including spacer)
                if state['offset'] == full_len:
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
