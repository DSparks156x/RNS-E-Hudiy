import json, os
from .base import BaseApp

class PhoneApp(BaseApp):

    def __init__(self, config=None):
        super().__init__(config)
        self.state = "IDLE"
        self.caller_name = ""
        self.caller_number = ""
        self.battery = 0
        self.signal = 0
        self.conn_state = "DISCONNECTED"
        self.action_idx = 0
        self.keyboard_device = None
        try:
            import uinput
            self.keyboard_device = uinput.Device([uinput.KEY_P, uinput.KEY_O], name="phone-virtual-keyboard")
        except Exception:
            pass

    def on_enter(self):
        super().on_enter()
        try:
            if os.path.exists('/tmp/current_call.json'):
                with open('/tmp/current_call.json', 'r') as f:
                    data = json.load(f)
                    self.update_hudiy(b'HUDIY_PHONE', data)
        except Exception: pass

    def update_hudiy(self, topic, data):
        if topic == b'HUDIY_PHONE':
            new_state = data.get('state', 'IDLE')
            if new_state != self.state:
                self.action_idx = 0
            self.state = new_state
            self.caller_name = data.get('caller_name') or "No ID"
            self.caller_number = data.get('caller_id') or ""
            self.battery = data.get('battery', 0)
            self.signal = data.get('signal', 0)
            self.conn_state = data.get('connection_state', 'DISCONNECTED')

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']: return 'BACK'
        
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
        if self.state in ['INCOMING', 'ACTIVE', 'ALERTING', 'DIALING']:
            status_text = self.state.capitalize()
            if status_text in ['Incoming', 'Active']:
                status_text += ' Call'
        elif self.conn_state == 'CONNECTED':
            status_text = "Connected"
        else:
            status_text = "No Phone"
            
        status_scroll = self._scroll_text(status_text, 'phone_status', 16, align=align)
        
        if status_text == "No Phone":
            # Just show status and clear the rest
            lines['line1'] = (status_scroll, flag)
            lines['line2'] = (" " * 16, flag)
            lines['line3'] = (" " * 16, flag)
            lines['line4'] = (" " * 16, flag)
            lines['line5'] = (" " * 16, flag)
        else:
            name_scroll = self._scroll_text(self.caller_name, 'phone_name', 16, align=align)
            num_scroll = self._scroll_text(self.caller_number, 'phone_number', 16, align=align)
            
            lines['line1'] = (status_scroll, flag)
            lines['line2'] = (name_scroll, flag)
            lines['line3'] = (num_scroll, flag)
            
            # Action interface for lines 4 and 5
            if self.state in ['INCOMING', 'ALERTING', 'DIALING']:
                l4_text = "Accept"
                l5_text = "Reject"
                if align == 'center':
                    l4_text = l4_text.center(16)
                    l5_text = l5_text.center(16)
                else:
                    l4_text = l4_text.ljust(16)
                    l5_text = l5_text.ljust(16)
                    
                lines['line4'] = (l4_text, flag_inv if self.action_idx == 0 else flag)
                lines['line5'] = (l5_text, flag_inv if self.action_idx == 1 else flag)
            elif self.state == 'ACTIVE':
                l5_text = "End Call"
                if align == 'center':
                    l5_text = l5_text.center(16)
                else:
                    l5_text = l5_text.ljust(16)
                    
                lines['line4'] = (" " * 16, flag)
                lines['line5'] = (l5_text, flag_inv)
            else:
                lines['line4'] = (" " * 16, flag)
                lines['line5'] = (" " * 16, flag)
            
        return lines
