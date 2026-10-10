"""Known r21 panel masks and their CAN envelope; press handling lives in MMI."""


PANEL_BUTTONS = {
    (8, 0): 'NAV', (0, 8): 'TEL', (0, 4): 'MEDIA',
    (4, 0): 'NAME', (0, 12): 'INFO', (12, 0): 'CAR',
}


def valid_panel_frame(msg, data):
    """Validate before passing these masks into the shared MMI press handler."""
    return (msg.get('arbitration_id') == 0x461 and msg.get('dlc') == 6
            and len(data) == 6 and data[:2] == b'\x37\x30' and data[5] == 0
            and not any(msg.get(flag, False) for flag in
                        ('is_extended_id', 'is_remote_frame', 'is_error_frame'))
            and data[2] in (1, 4))
