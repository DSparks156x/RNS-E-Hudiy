import json, os
from .base import BaseApp
try:
    from ..icons import WHEEL_CONTROL_GLYPH
except ImportError:
    from icons import WHEEL_CONTROL_GLYPH

class PhoneApp(BaseApp):

    CALL_STATES = {'INCOMING', 'ALERTING', 'DIALING', 'ACTIVE'}

    def __init__(self, config=None):
        super().__init__(config)
        self.state = "IDLE"
        self.caller_name = ""
        self.caller_number = ""
        self.battery = 0
        self.signal = 0
        self.conn_state = "DISCONNECTED"
        self.action_idx = 0
        self.control_mode = False
        self.keyboard_device = None
        try:
            import uinput
            self.keyboard_device = uinput.Device([uinput.KEY_P, uinput.KEY_O], name="phone-virtual-keyboard")
        except Exception:
            pass

    def on_enter(self):
        super().on_enter()
        self.control_mode = False
        try:
            if os.path.exists('/tmp/current_call.json'):
                with open('/tmp/current_call.json', 'r') as f:
                    data = json.load(f)
                    self.update_hudiy(b'HUDIY_PHONE', data)
        except Exception: pass

    def on_leave(self):
        super().on_leave()
        self.control_mode = False

    def set_control_mode(self, active):
        self.control_mode = bool(active)


    def update_hudiy(self, topic, data):
        if topic == b'HUDIY_PHONE':
            new_state = self.call_state(data)
            if new_state != self.state:
                self.action_idx = 0
            self.state = new_state
            self.caller_name = (data.get('caller_name') or "No ID") if new_state != "IDLE" else ""
            self.caller_number = (data.get('caller_id') or "") if new_state != "IDLE" else ""
            self.battery = data.get('battery', 0)
            self.signal = data.get('signal', 0)
            self.conn_state = data.get('connection_state', 'DISCONNECTED')

    @classmethod
    def call_state(cls, data):
        state = str(data.get('state', 'IDLE')).upper()
        return state if state in cls.CALL_STATES and data.get('call_active') is not False else 'IDLE'

    @property
    def has_phone(self):
        """Whether the phone page has a live call to display."""
        return self.has_active_call

    @property
    def has_active_call(self):
        return self.state in self.CALL_STATES

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']: return 'BACK'
        if not self.control_mode:
            return None
        action = {'previous': 'scroll_up', 'next': 'scroll_down', 'select': 'scroll_click'}.get(action, action)
        if action == 'back':
            self.action_idx = 0
            return True
        
        if action == 'scroll_up':
            if self.state in ['INCOMING', 'ALERTING', 'DIALING']:
                self.action_idx = 0
            return True
        elif action == 'scroll_down':
            if self.state in ['INCOMING', 'ALERTING', 'DIALING']:
                self.action_idx = 1
            return True
        elif action == 'scroll_click':
            key = None
            if self.state in ['INCOMING', 'ALERTING', 'DIALING']:
                key = 'KEY_P' if self.action_idx == 0 else 'KEY_O'
            elif self.state == 'ACTIVE':
                key = 'KEY_O'
                
            if key and self.keyboard_device:
                try:
                    import uinput
                    self.keyboard_device.emit_click(getattr(uinput, key))
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).error(f"Failed to emit key {key}: {e}")
            elif key:
                import logging
                logging.getLogger(__name__).info(f"Mocking phone key press: {key}")
            return True
            
        return None

    def get_view(self):
        lines = {}
        
        centering = self.config.get('display', {}).get('text_centering', False)
        align = 'center' if centering else 'left'
        flag = self.FLAG_ITEM_CENTERED if centering else self.FLAG_ITEM
        flag_inv = flag | 0x80
        
        # Determine status text
        if self.state in self.CALL_STATES:
            status_text = self.state.capitalize()
            if status_text in ['Incoming', 'Active']:
                status_text += ' Call'
        elif self.conn_state == 'CONNECTED':
            status_text = "Connected"
        else:
            status_text = "No Phone"
            
        status_scroll = self._scroll_text(status_text, 'phone_status', align=align,
            max_width_px=108 if self.control_mode else 128, font_flags=flag)
        if self.control_mode:
            # Keep the ownership symbol visible even while status text scrolls.
            status_scroll = WHEEL_CONTROL_GLYPH + ' ' + status_scroll
        
        if status_text == "No Phone":
            # Just show status and clear the rest
            lines['line1'] = (status_scroll, flag)
            lines['line2'] = ("", flag)
            lines['line3'] = ("", flag)
            lines['line4'] = ("", flag)
            lines['line5'] = ("", flag)
        else:
            name_scroll = self._scroll_text(self.caller_name, 'phone_name', align=align, max_width_px=128, font_flags=flag)
            num_scroll = self._scroll_text(self.caller_number, 'phone_number', align=align, max_width_px=128, font_flags=flag)
            
            lines['line1'] = (status_scroll, flag)
            lines['line2'] = (name_scroll, flag)
            lines['line3'] = (num_scroll, flag)
            
            # Action interface for lines 4 and 5
            if self.state in ['INCOMING', 'ALERTING', 'DIALING']:
                l4_text = "Accept"
                l5_text = "Reject"
                prefix = '>' if self.control_mode else ''
                lines['line4'] = (prefix + l4_text if self.action_idx == 0 else l4_text, flag_inv if self.control_mode and self.action_idx == 0 else flag)
                lines['line5'] = (prefix + l5_text if self.action_idx == 1 else l5_text, flag_inv if self.control_mode and self.action_idx == 1 else flag)
            elif self.state == 'ACTIVE':
                l5_text = "End Call"
                lines['line4'] = ("", flag)
                lines['line5'] = (l5_text, flag_inv if self.control_mode else flag)
            else:
                lines['line4'] = ("", flag)
                lines['line5'] = ("", flag)
            
        return lines
