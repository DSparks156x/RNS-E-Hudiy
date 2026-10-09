# DataView capture fixture

This renders the production tab components and stylesheet in a capture-only tab shell. The screenshots show the software's actual controls, with synthetic telemetry and a synthetic saved recording. They are not vehicle test results.

From `help-site`, run:

```sh
npm run dev -- --config scripts/capture-vite.config.js --port 5190
```

Open `http://127.0.0.1:5190/scripts/capture-dataview.html?scene=data-record` at 800 × 480. Allow the fixture to finish its navigation before capturing. Scenes:

| Scene | Production component/state |
| --- | --- |
| `engine` | Engine gauges |
| `transmission` | Transmission gauges and selector travel |
| `data-record` | Data & Logs profile/live readings |
| `data-recording` | Data & Logs recording controls and markers |
| `data-review` | Saved recording graphs, traces and markers |
| `data-dis` | Eight-slot DIS page configuration |
| `data-slot` | DIS slot settings dialog |
| `data-picker` | Value picker using the full production catalog |
| `awd` | AWD gauges, mode status, controls and legacy drive logger |
| `diagnostics` | Production module picker |
| `diagnostics-engine` | Engine measuring groups 3, 20 and 115 with synthetic values in production catalog block order |

On Diagnostics, select AWD and then Flash Controller to inspect the production controller dialog with synthetic 320 KiB firmware metadata. Steering Assist opens the EPS dialog with a synthetic revision 3001 controller and 4 KiB dataset metadata. Controller identities and file metadata are synthetic. The exhaust valve panel also shows a synthetic *requested* target; production UI correctly labels the target unconfirmed. Engine groups 3, 20 and 115 use the block order and units documented by the production catalog; an empty fixture DTC report is not a result from a vehicle.

The capture Vite config aliases `socket.io-client` to `capture-socket.js`, which has no transport. `capture-data-logs.js` intercepts the production `/api/data-logs` fetch requests in memory and rejects all other requests. Controls update only the fixture. No vehicle connection, flash, firmware transfer or log-file write is performed. Diagnostics is disabled when the capture shell is opened without this Vite config.

`capture-value-catalog.json` is a snapshot of `vehicle_data.catalog.get_catalog()`. Refresh it from the repository root after changing the catalog:

```sh
python -c "import json,pathlib; from vehicle_data.catalog import get_catalog; pathlib.Path('help-site/scripts/capture-value-catalog.json').write_text(json.dumps(get_catalog(),ensure_ascii=False,separators=(',',':')),encoding='utf-8')"
```

DataStore receives the catalog's actual units and provider kinds (`diag` / `ican`), with fixture-prefixed source IDs. Its quality flags follow the catalog provider metadata; this describes reference mapping and synthetic fresh samples, not hardware verification.

The static site build does not include the capture fixture. The public media manifest records the components and fixture used to produce the saved images.
