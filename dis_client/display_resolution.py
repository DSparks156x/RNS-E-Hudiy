"""Resolve the one center-display resolution setting and older configurations."""


def high_resolution(config=None):
    display = (config or {}).get('display', {})
    center = display.get('center_display', {})
    if 'high_resolution' in center:
        enabled = center['high_resolution']
        if not isinstance(enabled, bool):
            raise ValueError('display.center_display.high_resolution must be a boolean')
        return enabled
    # Older captures/settings used separate font and graphics switches. A valid
    # font profile takes precedence so a saved red-cluster setup stays legacy.
    profile = display.get('font_resolution')
    if profile in ('native', 'legacy'):
        return profile == 'native'
    flags = []
    for section, key in (('navigation', 'high_resolution'), ('coverart', 'native_resolution'),
                         ('car_info', 'high_resolution')):
        settings = center.get(section, {})
        if isinstance(settings, dict) and isinstance(settings.get(key), bool):
            flags.append(settings[key])
    return any(flags) if flags else True
