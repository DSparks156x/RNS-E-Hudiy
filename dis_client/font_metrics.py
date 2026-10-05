"""AUDSCII layout advances in physical LCD pixels.

Generated capture/reference metrics are independent of bitmap availability.
Unknown native advances conservatively reserve the maximum12px character cell.
"""
import json
from functools import lru_cache
from pathlib import Path

try:
    from .icons import encode_audscii
except ImportError:
    from icons import encode_audscii


@lru_cache(maxsize=1)
def _metrics():
    data=json.loads(Path(__file__).with_name('font_metrics_data.json').read_text(encoding='utf-8'))
    if data.get('schema_version')!=1 or data.get('units')!='physical_pixels':
        raise ValueError('Unsupported font metrics asset')
    return data['profiles']


def font_profile(config):
    value=(config or {}).get('display',{}).get('font_resolution','native')
    return value if value in ('native','legacy') else 'native'


def _advances(flags,profile):
    if profile not in ('native','legacy'):
        raise ValueError('Font profile must be native or legacy')
    font='graphics' if flags&0x08 else 'proportional' if flags&0x04 else 'fixed'
    return _metrics()[profile][font]['advances_px']


def measure_text(text,flags=0x06,profile='native'):
    """Measure the bytes the real text encoder sends; unsupported Unicode is space."""
    widths=_advances(flags,profile)
    return sum(widths[code] for code in encode_audscii(str(text)))


def fit_text(text,max_width_px,flags=0x06,profile='native'):
    """Longest whole-character prefix whose accumulated advance fits the budget."""
    text=str(text);widths=_advances(flags,profile);total=0;count=0
    if max_width_px<0:raise ValueError('Text width cannot be negative')
    for code in encode_audscii(text):
        width=widths[code]
        if total+width>max_width_px:break
        total+=width;count+=1
    return text[:count]
