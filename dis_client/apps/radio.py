import sys
from .base import BaseApp

class RadioApp(BaseApp):
    def __init__(self, config=None):
        super().__init__(config)
        self.top = "Radio"
        self.bot = ""
        self.topics_top = set()
        self.topics_bot = set()
        self.topics = set()
        print("[RadioApp] Initialized")

    def set_topics(self, t_top, t_bot):
        self.topics_top = t_top
        self.topics_bot = t_bot
        self.topics = self.topics_top.union(self.topics_bot)
        print(f"[RadioApp] Topics set: {self.topics}")

    def update_can(self, topic, payload):
        """
        Receives RAW BYTES from DisplayEngine.
        """
        is_top = topic in self.topics_top
        is_bot = topic in self.topics_bot

        if not (is_top or is_bot):
            return

        try:
            if isinstance(payload, bytes):
                # 1. Decode Audi ISO-8859-1 (Latin-1)
                decoded = payload.decode('iso-8859-1', errors='replace')
                
                # 2. Handle Control Characters (0x1C)
                # The radio sends 0x1C as a spacer block. We map it to SPACE (0x20).
                # This turns "\x1c\x1cFM" into "  FM", preserving the indentation.
                clean_text = decoded.replace('\x1c', ' ')
                
                # 3. Clean Nulls
                clean_text = clean_text.replace('\x00', '')
                
                # Debug: Verify we have leading spaces
                # print(f"[RadioApp] '{topic}' -> '{clean_text}'")

                if is_top:
                    self.top = clean_text
                elif is_bot:
                    self.bot = clean_text
                    
        except Exception as e:
            print(f"[RadioApp] Error decoding {topic}: {e}")

    def handle_input(self, action):
        if action in ['hold_up', 'hold_down']: 
            return 'BACK'
        return None

    def get_view(self):
        lines = {}
        lines['line1'] = ("Radio", self.FLAG_HEADER)

        t_top = str(self.top) if self.top else ""
        t_bot = str(self.bot) if self.bot else ""

        centering = self.config.get('display', {}).get('text_centering', False)
        flag = self.FLAG_ITEM_CENTERED if centering else self.FLAG_ITEM
        wipe_flag = 0xA6 if centering else self.FLAG_WIPE # 0x86 (Invert) | 0x20 (Center) -> Wait, FLAG_WIPE is 0x02

        # --- FIX FOR ARTIFACTS AND CENTERING ---
        if not t_top.strip():
             # If completely empty, send full blank line to wipe
            lines['line3'] = (" " * 10, self.FLAG_WIPE)
        else:
            if centering:
                lines['line3'] = (t_top.strip()[:10], self.FLAG_ITEM_CENTERED)
            else:
                lines['line3'] = (t_top[:10].ljust(10), self.FLAG_WIPE)

        # Line 4 (Info): Limit 16 chars, Pad to 16
        if not t_bot.strip():
            lines['line4'] = (" " * 16, self.FLAG_ITEM)
        else:
            if centering:
                lines['line4'] = (t_bot.strip()[:16], self.FLAG_ITEM_CENTERED)
            else:
                lines['line4'] = (t_bot[:16].ljust(16), self.FLAG_ITEM)

        lines['line2'] = (" " * 16, self.FLAG_ITEM)
        lines['line5'] = (" " * 16, self.FLAG_ITEM)
        
        return lines
