"""Generate the browser mapping from the actual Python AUDSCII encoder literals."""
import argparse
import ast
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
args = parser.parse_args()
values = {}
for statement in ast.parse((args.repo/'dis_client/icons.py').read_text(encoding='utf-8')).body:
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            if isinstance(target, ast.Name) and target.id in ('audscii_trans', 'audscii_unicode'):
                values[target.id] = ast.literal_eval(statement.value)
table = values['audscii_trans']
aliases = values['audscii_unicode']
assert len(table) == 256 and all(isinstance(c, int) and 0 <= c <= 255 for c in table)
assert all(len(char) == 1 and isinstance(code, int) and 0 <= code <= 255 for char, code in aliases.items())
payload = json.dumps({'latin1': table, 'unicodeAliases': aliases}, ensure_ascii=False, separators=(',', ':'))
asset = '''// Generated from dis_client/icons.py by tools/export_audscii.py.
(function(root) {
    const mapping = PAYLOAD;
    mapping.toCode = function(char) {
        const point = char.codePointAt(0);
        return point < 256 ? mapping.latin1[point] : (mapping.unicodeAliases[char] ?? mapping.latin1[32]);
    };
    mapping.encodeText = function(text) { return Array.from(text, char => mapping.toCode(char)); };
    root.AUDSCII_MAPPING = mapping;
    if (typeof module !== 'undefined' && module.exports) module.exports = mapping;
})(typeof globalThis !== 'undefined' ? globalThis : this);
'''.replace('PAYLOAD', payload)
target = args.repo/'dis_emulator/static/audscii_data.js'
target.write_text(asset, encoding='utf-8')
print(f'Exported256 Latin1 slots and{len(aliases)} Unicode aliases to{target}')
