"""Execute the installer's JSON migration without running system installation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALL = (ROOT / 'install.sh').read_text(encoding='utf-8')
MERGE_SCRIPT = INSTALL.split('        python3 -c "\n', 1)[1].split('\n" "$DEST" "$SRC" "$TEMP_FINAL"', 1)[0]


class InstallerConfigMigrationTests(unittest.TestCase):
    def migrate(self, name, old, new):
        with tempfile.TemporaryDirectory(dir=ROOT / 'scratch') as directory:
            root = Path(directory)
            destination, source, output = root / name, root / 'source.json', root / 'output.json'
            destination.write_text(json.dumps(old), encoding='utf-8')
            source.write_text(json.dumps(new), encoding='utf-8')
            result = subprocess.run([sys.executable, '-c', MERGE_SCRIPT,
                                     str(destination), str(source), str(output)],
                                    capture_output=True, text=True)
            self.assertIn(result.returncode, (0, 2), result.stderr)
            return result.returncode, json.loads(output.read_text()) if output.exists() else old

    def test_update_removes_obsolete_capture_options_and_preserves_other_diagnostics(self):
        old = {'diagnostics': {'enabled': False, 'values': {'diagnostic_hz': 7},
                               'hudiy_api_capture': {'enabled': False, 'path': '/old/log'}}}
        result, updated = self.migrate('config.json', old, {'diagnostics': {'enabled': True}})
        self.assertEqual(result, 0)
        self.assertEqual(updated, {'diagnostics': {'enabled': False, 'values': {'diagnostic_hz': 7}}})
        self.assertEqual(self.migrate('config.json', updated, {'diagnostics': {'enabled': True}})[0], 2)

    def test_update_inserts_valve_shortcut_next_to_haldex_without_replacing_customizations(self):
        old = {'shortcuts': [{'action': 'hudiy_diagnostics', 'iconName': 'custom-diag'},
                             {'action': 'toggle_haldex_mode', 'iconName': 'custom-awd'},
                             {'action': 'resume_android_auto_projection'}, {'action': 'personal_action'}]}
        new = json.loads((ROOT / 'config/hudiy/shortcuts.json').read_text())
        result, updated = self.migrate('shortcuts.json', old, new)
        self.assertEqual(result, 0)
        self.assertEqual([item['action'] for item in updated['shortcuts']],
                         ['hudiy_diagnostics', 'toggle_haldex_mode', 'toggle_exhaust_valve',
                          'resume_android_auto_projection', 'personal_action'])
        self.assertEqual(updated['shortcuts'][0]['iconName'], 'custom-diag')
        self.assertEqual(updated['shortcuts'][1]['iconName'], 'custom-awd')
        self.assertEqual(self.migrate('shortcuts.json', updated, new)[0], 2)

    def test_existing_valve_shortcut_keeps_custom_position_and_icon(self):
        old = {'shortcuts': [{'action': 'toggle_exhaust_valve', 'iconName': 'custom-valve'}]}
        new = json.loads((ROOT / 'config/hudiy/shortcuts.json').read_text())
        result, updated = self.migrate('shortcuts.json', old, new)
        self.assertEqual(result, 2)
        self.assertEqual(updated, old)


if __name__ == '__main__':
    unittest.main()
