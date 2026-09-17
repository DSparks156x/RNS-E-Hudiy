import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OpenpilotConflictTests(unittest.TestCase):
    def test_openpilot_is_disabled_in_config_and_transport(self):
        config = json.loads((ROOT / 'config.json').read_text())
        self.assertIs(config['openpilot']['enabled'], False)

        source = (ROOT / 'tp2' / 'openpilot_receiver.py').read_text()
        tree = ast.parse(source)
        constants = {
            node.targets[0].id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        }
        self.assertIs(constants['OPENPILOT_TRANSPORT_ENABLED'], False)
        self.assertIn('0x67A/0x6DA', constants['OPENPILOT_DISABLED_REASON'])
        receiver = next(node for node in tree.body
                        if isinstance(node, ast.ClassDef) and node.name == 'OpenpilotReceiver')
        class_constants = {
            node.targets[0].id: node.value.value
            for node in receiver.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        }
        self.assertIs(class_constants['TRANSPORT_ENABLED'], False)
        self.assertIn('0x67A/0x6DA', class_constants['DISABLED_REASON'])

    def test_worker_requires_both_config_and_transport_enable(self):
        source = (ROOT / 'tp2' / 'tp2_worker.py').read_text()
        self.assertIn('op_enabled = bool(op_requested and OPENPILOT_TRANSPORT_ENABLED)', source)


if __name__ == '__main__':
    unittest.main()
