from typing import List, Dict, Any

class ScreenBase:
    """
    Base class for any DIS Screen/App.
    Defines the layout using primitive elements to be diffed and drawn by SmartDriver.
    """
    
    def __init__(self):
        self.needs_full_screen = False # Override to True if screen claims Top + Center
        
    def handle_can_message(self, topic: str, payload_hex: bytes):
        """Called by AppManager when a raw CAN packet arrives."""
        pass
        
    def handle_hudiy_data(self, topic: str, data: dict):
        """Called by AppManager when Hudiy JSON API data arrives."""
        pass
        
    def handle_button_press(self, button_name: str, event_type: str):
        """
        Called when steering wheel/stalk buttons are manipulated.
        event_type = 'tap' or 'hold'
        button_name = 'up' / 'down' / 'mode' etc.
        """
        pass
        
    def render(self) -> List[Dict[str, Any]]:
        """
        Returns a list of elements defining the current visual state of the screen.
        Format: [{'type': 'text', 'x': 0, 'y': 11, 'text': 'Hello'}, ...]
        """
        return []

    # Utility functions for generating elements
    def create_text(self, text: str, x: int, y: int, flags: int = 0x06) -> Dict[str, Any]:
        return {'type': 'text', 'x': x, 'y': y, 'text': text, 'flags': flags}
        
    def create_bitmap(self, icon_name: str, x: int, y: int) -> Dict[str, Any]:
        return {'type': 'bitmap', 'x': x, 'y': y, 'icon_name': icon_name}
        
    def create_line(self, x: int, y: int, length: int, vertical: bool = True) -> Dict[str, Any]:
        return {'type': 'line', 'x': x, 'y': y, 'length': length, 'vertical': vertical}
