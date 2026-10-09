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

    def test_manager_application_is_added_without_replacing_existing_apps(self):
        old = {'applications': [{'action': 'personal_app', 'url': 'http://localhost:7777'}]}
        new = json.loads((ROOT / 'config/hudiy/applications.json').read_text())
        result, updated = self.migrate('applications.json', old, new)
        self.assertEqual(result, 0)
        self.assertEqual(updated['applications'][0], old['applications'][0])
        self.assertEqual(updated['applications'][1]['action'], 'hudiy_manager')
        self.assertEqual(self.migrate('applications.json', updated, new)[0], 2)

    def test_manager_menu_preserves_custom_entries_and_adds_hudiy_category(self):
        old = {'categories': [{'label': 'Personal'}], 'items': [{'action': 'personal_app', 'label': 'Mine'}]}
        new = json.loads((ROOT / 'config/hudiy/applications_menu.json').read_text())
        result, updated = self.migrate('applications_menu.json', old, new)
        self.assertEqual(result, 0)
        self.assertEqual(updated['items'][0], old['items'][0])
        self.assertEqual(updated['items'][1]['action'], 'hudiy_manager')
        self.assertEqual([item['label'] for item in updated['categories']], ['Personal', 'Hudiy'])
        self.assertEqual(self.migrate('applications_menu.json', updated, new)[0], 2)

    def test_existing_manager_customization_is_preserved(self):
        old = {'applications': [{'action': 'hudiy_manager', 'url': 'http://localhost:7777', 'allowBackground': True}]}
        new = json.loads((ROOT / 'config/hudiy/applications.json').read_text())
        self.assertEqual(self.migrate('applications.json', old, new), (2, old))

    def test_brightness_defaults_do_not_replace_existing_levels(self):
        old = {'rnse': {'auto_brightness': {'enabled': True, 'night_brightness': 3}}}
        new = json.loads((ROOT / 'config.json').read_text())
        _, updated = self.migrate('config.json', old, new)
        self.assertEqual(updated['rnse']['auto_brightness'], {'enabled': True, 'day_brightness': 10, 'night_brightness': 3})


if __name__ == '__main__':
    unittest.main()
