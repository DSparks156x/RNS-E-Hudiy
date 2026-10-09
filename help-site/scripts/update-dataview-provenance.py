"""Record provenance for DataView media actually present in public/media."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
scenes = {
    'dataview-engine.jpg': ('engine', 'Engine gauges with synthetic live telemetry.'),
    'dataview-engine.gif': ('engine', 'Engine gauges animated with synthetic live telemetry.'),
    'dataview-transmission.jpg': ('transmission', 'Transmission gauges and selector travel with synthetic telemetry.'),
    'dataview-record.jpg': ('data-record', 'A logging profile with selected values and live source status; start, mark and stop controls.'),
    'dataview-review.jpg': ('data-review', 'A synthetic saved recording; unit-separated graphs, selectable traces, cursor inspection, zoom, markers and CSV export controls.'),
    'dataview-dis-editor.jpg': ('data-dis', 'Eight slots arranged as four left/right rows, a linked logging profile and Apply control.'),
    'dataview-dis-slot.jpg': ('data-slot', 'Production DIS slot dialog: value, unit, precision, native font, provider policies and native icon selection.'),
    'dataview-value-picker.jpg': ('data-picker', 'Production catalog picker with actual canonical labels, units, system/group organization and provider policies.'),
    'dataview-awd.jpg': ('awd', 'AWD gauges and production mode/logger controls with synthetic status; torque estimate remains labeled estimated.'),
    'dataview-diagnostics.jpg': ('diagnostics', 'Production Diagnostics module picker. Its addresses are internal TP2 destinations.'),
    'dataview-diagnostics-engine.jpg': ('diagnostics-engine', 'Production Engine Diagnostics view showing synthetic measuring groups 3, 20 and 115 in source-backed block order.'),
    'dataview-controller.jpg': ('diagnostics → AWD → Flash Controller', 'Production controller dialog with a synthetic controller identity and 320KiB sample firmware metadata; no flash or readout performed.'),
    'dataview-eps.jpg': ('diagnostics → Steering Assist → Flash Controller', 'Production EPS controller dialog with a synthetic revision 3001 controller and 4KiB sample dataset; no write or readout performed.'),
    'dataview-exhaust.jpg': ('diagnostics → Exhaust valve controller', 'Production exhaust controller panel with synthetic requested target, explicitly unconfirmed.'),
}
sources = [
    'hudiy_dataview/src/tabs/EngineTab.tsx', 'hudiy_dataview/src/tabs/TransmissionTab.tsx',
    'hudiy_dataview/src/tabs/AWDTab.tsx', 'hudiy_dataview/src/tabs/DataLogsTab.tsx',
    'hudiy_dataview/src/tabs/DiagnosticsTab.tsx', 'hudiy_dataview/src/components/Gauge.tsx',
    'hudiy_dataview/src/components/dataLogs/LogReview.tsx', 'hudiy_dataview/src/components/dataLogs/ValuePicker.tsx',
    'hudiy_dataview/src/components/dataLogs/model.ts', 'hudiy_dataview/src/components/dataLogs/dataLogs.css',
    'hudiy_dataview/src/components/HaldexFlashModal.tsx', 'hudiy_dataview/src/components/ExhaustValvePanel.tsx',
    'hudiy_dataview/src/hooks/useDataLogs.ts', 'hudiy_dataview/src/hooks/useHaldexAndLogger.ts',
    'hudiy_dataview/src/store/DataStore.ts', 'hudiy_dataview/static/css/style_v3.css',
    'help-site/scripts/capture-dataview.jsx', 'help-site/scripts/capture-data-logs.js',
    'help-site/scripts/capture-socket.js', 'help-site/scripts/capture-vite.config.js',
    'help-site/scripts/capture-value-catalog.json',
]
existing = {name: {'scene': scene, 'caption': caption} for name, (scene, caption) in scenes.items() if (root / 'public/media' / name).is_file()}
manifest = {
    'capture': 'Production React tab components and CSS in a capture-only tab shell; browser capture at 800x480',
    'data': 'Synthetic telemetry, saved samples, markers and controller state; no vehicle observations',
    'catalog': 'Snapshot of the actual vehicle_data.catalog.get_catalog() canonical values, units and provider metadata',
    'fixture': 'scripts/capture-dataview.jsx',
    'fixture_server': 'npm run dev -- --config scripts/capture-vite.config.js --port 5190',
    'isolation': 'Socket.IO aliased to an in-memory fixture; Data & Logs fetches intercepted in memory, all other fetches rejected. No backend/vehicle writes.',
    'theme': 'Sample Hudiy Material You palette injected as production CSS variables',
    'assets': list(existing),
    'scenes': existing,
    'limitations': [
        'These captures demonstrate production UI behavior and layout, not vehicle compatibility or successful hardware operations.',
        'Catalog verified flags describe supplied reference mappings, not independent ECU validation.',
        'Measuring-block responses and empty DTC reports are synthetic; no actual module was queried. The fixture does not implement firmware transfer, CSV download, or file portal operations.',
        'Original engine animation and engine/transmission stills were captured before the expanded scenes were added.',
    ],
    'source_sha256': {path: hashlib.sha256((root.parent / path).read_bytes()).hexdigest() for path in sources},
}
(root / 'public/media/dataview-provenance.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print(f'Recorded provenance for {len(existing)} saved assets.')
