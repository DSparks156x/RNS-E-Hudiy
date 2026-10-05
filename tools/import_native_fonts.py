"""Import verified native LCD captures into the shared browser font asset.

Usage: python tools/import_native_fonts.py --source native_fonts.json
The source is the font-capture export. Uncaptured fonts remain absent so clients
can retain their explicit legacy fallback. No image resizing is performed.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def build(source):
    raw = Path(source).read_bytes()
    capture = json.loads(raw)
    if capture.get('schema_version') != 1 or capture.get('native_resolution') != [128, 96]:
        raise ValueError('Expected native128x96 font capture schema1')
    fonts = {}
    for name, font in capture['fonts'].items():
        if not any(g['status'] == 'verified' for g in font['glyphs']):
            continue
        if len(font['glyphs']) != 256 or {g['code'] for g in font['glyphs']} != set(range(256)):
            raise ValueError('Font must contain exactly256 distinct raw codes')
        glyphs = []
        for glyph in sorted(font['glyphs'], key=lambda g: g['code']):
            record = {key: glyph.get(key) for key in (
                'code', 'status', 'size', 'mask_hex', 'advance_px', 'ink_bbox',
                'left_bearing_px', 'top_bearing_px', 'right_bearing_px')}
            advance = record['advance_px']
            if advance is not None and (not isinstance(advance, (int, float)) or advance < 0):
                raise ValueError('Invalid physical-pixel advance')
            if glyph['status'] == 'verified':
                width, height = record['size']
                if width <= 0 or height <= 0 or len(bytes.fromhex(record['mask_hex'])) != ((width+7)//8)*height:
                    raise ValueError('Invalid row-padded native glyph bitmap')
            elif record['mask_hex'] is not None:
                raise ValueError('Unverified glyph bitmap must remain unknown')
            provenance = glyph.get('provenance')
            if provenance:
                evidence = capture['sources'][provenance['source_index']]
                record['capture'] = {key: evidence.get(key) for key in ('page_id', 'photo_sha256', 'polarity')}
            glyphs.append(record)
        fonts[name] = {'font_bits': font['font_bits'], 'units': 'physical_pixels',
                       'counts': font['counts'], 'glyphs': glyphs}
    return {'schema_version': 1, 'native_resolution': [128, 96],
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'advance_semantics': capture['advance_semantics'], 'fonts': fonts}


def build_metrics(source, legacy_source):
    """Export advances only, in physical pixels, for Python layout code."""
    native=build(source)
    legacy_raw=Path(legacy_source).read_bytes()
    legacy_text=legacy_raw.decode('utf-8')
    profiles={'native':{},'legacy':{}}
    for name, constant in (('fixed','FIXED'),('proportional','PROP'),('graphics','GRAPHICS')):
        font=native['fonts'].get(name)
        advances=[];statuses=[]
        for code in range(256):
            glyph=font['glyphs'][code] if font else {}
            value=glyph.get('advance_px')
            if value is not None and (isinstance(value,bool) or not 0<=value<=12 or int(value)!=value):
                raise ValueError('Native advance must be an integer in0..12')
            advances.append(int(value) if value is not None else 12)
            statuses.append('measured' if value is not None else 'fallback_max_cell')
        profiles['native'][name]={'advances_px':advances,'width_status':statuses,'fallback_px':12}
        match=re.search(r'\bconst\s+FONT_DATA_'+constant+r'\s*=\s*',legacy_text)
        if not match:raise ValueError('Missing legacy font table: '+constant)
        table,_=json.JSONDecoder().raw_decode(legacy_text[match.end():])
        if set(table)!={str(code) for code in range(256)}:
            raise ValueError('Legacy font must contain all256 codes')
        widths=[]
        for code in range(256):
            record=table[str(code)]
            if not isinstance(record,list) or len(record)!=8 or type(record[0]) is not int or not 0<=record[0]<=6:
                raise ValueError('Invalid legacy glyph width')
            widths.append(record[0]*2)
        profiles['legacy'][name]={'advances_px':widths,'width_status':['legacy_reference']*256,'fallback_px':12}
    return {'schema_version':1,'units':'physical_pixels',
            'source_sha256':native['source_sha256'],
            'legacy_source_sha256':hashlib.sha256(legacy_raw).hexdigest(),
            'unknown_width_policy':'Missing native advances reserve the maximum12px cell; measured widths are usable independently of bitmap status.',
            'profiles':profiles}


def write_atomic(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(content,encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1]/'dis_emulator/static/native_font_data.js')
    parser.add_argument('--legacy-fonts',type=Path,default=Path(__file__).resolve().parents[1]/'dis_emulator/static/font_data.js')
    parser.add_argument('--metrics-out',type=Path,default=Path(__file__).resolve().parents[1]/'dis_client/font_metrics_data.json')
    args = parser.parse_args()
    data = build(args.source)
    metrics=build_metrics(args.source,args.legacy_fonts)
    content = ('// Generated by tools/import_native_fonts.py. Native captured pixels; do not resize.\n'
               '(function(root) {\n  const data = ' + json.dumps(data, separators=(',', ':')) + ';\n'
               '  root.NATIVE_FONT_DATA = data;\n'
               "  if (typeof module !== 'undefined' && module.exports) module.exports = data;\n"
               "})(typeof globalThis !== 'undefined' ? globalThis : this);\n")
    write_atomic(args.out,content)
    write_atomic(args.metrics_out,json.dumps(metrics,separators=(',',':'))+'\n')
    print(json.dumps({'asset': str(args.out),'metrics':str(args.metrics_out), 'fonts': {name: font['counts'] for name, font in data['fonts'].items()}}))


if __name__ == '__main__':
    main()
