"""The reviewable catalog stays complete and includes the source coverage audit."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from vehicle_data.catalog import CATALOG, get_catalog_coverage
from vehicle_data.service import VehicleDataService
from tools.export_value_catalog import markdown


ROOT = Path(__file__).resolve().parents[1]


class CatalogExportTests(unittest.TestCase):
    def test_markdown_contains_every_id_and_matches_saved_catalog(self):
        document = markdown()
        self.assertEqual(document, (ROOT / 'vehicle_data/CATALOG.md').read_text(encoding='utf-8'))
        for value_id in CATALOG:
            self.assertIn(f'| `{value_id}` |', document)

    def test_json_contains_full_provider_mappings_and_every_reference_row(self):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/export_value_catalog.py')],
                                capture_output=True, text=True, encoding='utf-8', check=True)
        document = json.loads(result.stdout)
        self.assertEqual({entry['id'] for entry in document['values']}, set(CATALOG))
        self.assertEqual(len(document['engine_fields']), 384)
        self.assertEqual(document['coverage']['engine_reference']['supported_count'], 328)
        self.assertEqual(document['coverage']['engine_reference']['unmapped_count'], 0)

    def test_wire_catalog_includes_coverage_without_hardware(self):
        service = VehicleDataService.__new__(VehicleDataService)
        response = service.command({'cmd': 'CATALOG'})
        self.assertEqual(response['coverage'], get_catalog_coverage())
        self.assertEqual(len(response['values']), response['coverage']['value_count'])
        json.dumps(response, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
