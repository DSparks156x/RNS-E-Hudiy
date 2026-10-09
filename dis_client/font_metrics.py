"""AUDSCII layout advances in physical LCD pixels.

Generated capture/reference metrics are independent of bitmap availability.
Unknown native advances conservatively reserve the maximum12px character cell.
"""
import json
from functools import lru_cache
from pathlib import Path

try:
    from .icons import encode_audscii
    from .display_resolution import high_resolution
except ImportError:
    from icons import encode_audscii
    from display_resolution import high_resolution


@lru_cache(maxsize=1)
def _metrics():
    data=json.loads(Path(__file__).with_name('font_metrics_data.json').read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or data.get('units')!='physical_pixels':
        raise ValueError('Unsupported font metrics asset')
    return data['profiles']


def font_profile(config):
    return 'native' if high_resolution(config) else 'legacy'


def _advances(flags,profile):
    if profile not in ('native','legacy'):
        raise ValueError('Font profile must be native or legacy')
    font='graphics' if flags&0x08 else 'proportional' if flags&0x04 else 'fixed'
    return _metrics()[profile][font]['advances_px']


def measure_text(text,flags=0x06,profile='native'):
    """Measure the bytes the real text encoder sends; unsupported Unicode is space."""
    widths=_advances(flags,profile)
    return sum(widths[code] for code in encode_audscii(str(text)))


def fit_text(text,max_width_px,flags=0x06,profile='native',max_chars=None):
    """Longest whole-character prefix fitting pixels and an optional byte capacity."""
    text=str(text);widths=_advances(flags,profile);total=0;count=0
    if max_width_px<0:raise ValueError('Text width cannot be negative')
    for code in encode_audscii(text):
        width=widths[code]
        if total+width>max_width_px or (max_chars is not None and count>=max_chars):break
        total+=width;count+=1
    return text[:count]


def text_character_capacity(flags=0x06, profile='native', config=None):
    """Reserve one atomic clear plus text, independent of TP2 ACK blocks.

    The encoder sends exactly one byte per input character. Normal text costs
    5 bytes; an inverted fill/text/window-reset costs 19. Cleanup reserves 14.
    Legacy/red clusters retain the conservative 42-byte application budget.
    """
    if profile not in ('native','legacy'):
        raise ValueError('Font profile must be native or legacy')
    budget=42 if profile=='legacy' else 105
    return max(0,budget-14-(19 if flags&0x80 else 5))
