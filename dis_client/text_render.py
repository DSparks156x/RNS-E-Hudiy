"""Plan measured, bounded text replacements without exposing an intermediate wipe.

Widths are physical LCD pixels; rectangles and DDP positions use logical pixels.
A native logical pixel covers two physical pixels. Legacy capture advances have
already been scaled into the same coordinate space by font_metrics.
"""
from math import ceil, floor

try:
    from .font_metrics import measure_text, text_character_capacity
except ImportError:
    from font_metrics import measure_text, text_character_capacity


def text_bounds(command, profile='native'):
    """Painted rectangle: glyph advances normally, full highlight when inverted."""
    text = str(command.get('text', ''))
    width = measure_text(text, command.get('flags', 6), profile)
    if not text or width <= 0:
        return None
    if command.get('flags', 6) & 0x80:
        return (command.get('x', 0), command.get('y', 0),
                command.get('highlight_width', 64-command.get('x', 0)),
                command.get('highlight_height', 9))
    x = command.get('x', 0) * 2
    if command.get('flags', 6) & 0x20:
        # DDP centers within the current full-width text region.
        x = (128 - width) / 2
    left, right = floor(x / 2), ceil((x + width) / 2)
    return (left, command.get('y', 0), right - left, 9)


def intersect_rect(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right = min(a[0] + a[2], b[0] + b[2])
    bottom = min(a[1] + a[3], b[1] + b[3])
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def text_update(new, previous=None, profile='native', viewport=(0, 0, 64, 48), force_clear=False, config=None):
    """Return one atomic IPC command; only clear when the old footprint remains.

    Previous is the last submitted draw_text command for this logical field.
    Callers must discard previous on view/ownership changes or a DRAW_NACK.
    The viewport protects neighboring overlays such as the approach bar.
    """
    result = dict(command='update_text', text=str(new.get('text', '')),
                  x=new.get('x', 0), y=new.get('y', 0), flags=new.get('flags', 6))
    for key in ('highlight_width', 'highlight_height'):
        if key in new:
            result[key] = new[key]
    # Fit old and new identically so footprint history describes sent bytes.
    result['text']=result['text'][:text_character_capacity(result['flags'],profile,config)]
    if previous:
        previous=dict(previous,text=str(previous.get('text',''))[:
            text_character_capacity(previous.get('flags',6),profile,config)])
    if 'field_id' in new:
        result['field_id'] = new['field_id']
    old = text_bounds(previous, profile) if previous else None
    current = text_bounds(result, profile)
    if force_clear:
        erase = viewport
    elif old and (not current or old[0] < current[0] or old[1] != current[1]
                  or old[0] + old[2] > current[0] + current[2]
                  or old[1] + old[3] > current[1] + current[3]
                  or previous.get('flags', 6) != result['flags']):
        erase = intersect_rect(old, viewport)
    else:
        erase = None
    if erase:
        result['clear_rect'] = dict(zip(('x', 'y', 'w', 'h'), erase))
    return result
