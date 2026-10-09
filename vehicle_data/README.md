# Vehicle values service

Consumers select named values. The service selects healthy ICAN providers and
shared diagnostic measuring groups across consumers. Engine mappings come from
the owner's supplied measuring-group reference; no ECU part number is required.

The browsable [value catalog](CATALOG.md) lists every current ID, type, unit and
source family. The engine coverage ledger maps all 328 labeled first-four field
occurrences across 96 groups in the supplied PDF; 56 blank placeholders are
excluded. Repeated occurrences are alternate providers for the same quantity.
The catalog also covers the existing transmission/AWD DataView fields and useful
passive ICAN engine, chassis, battery, body, climate, trip and custom Haldex values.
Documented mappings do not imply that every ECU supplies them.

Regenerate the list or export every provider and the full engine coverage ledger:

```sh
python3 tools/export_value_catalog.py --format markdown --output vehicle_data/CATALOG.md
python3 tools/export_value_catalog.py --format json --output catalog.json
```

The default diagnostic rate is **2 Hz per requested value**, and ICAN publication
is capped at **10 Hz per requested value**. These are requests, not claims about
ECU capacity. Actual group rates, request durations and overruns are observable.

## Running and installation

The existing `hudiy_status_service.service` runs `hudiy_dataview/can_service.py`,
which now starts `vehicle_data.service`. The installer includes `vehicle_data/`.
No additional runtime dependency is needed beyond the existing Python/ZeroMQ
stack. The service consumes `can_raw_stream` and `tp2_stream`; TP2 still owns
diagnostic hardware, sessions, DTC operations and diagnostic inhibition.

Default ZMQ endpoints, configurable in `interfaces.zmq`:

| Setting | Default |
| --- | --- |
| `vehicle_data_command` | `ipc:///run/rnse_control/vehicle_data_cmd.ipc` |
| `vehicle_data_stream` | `ipc:///run/rnse_control/vehicle_data_stream.ipc` |

The existing `status_stream` endpoint continues publishing compatible module-0
groups with nulls for unavailable fields. It no longer fabricates fuel or engine
load from unrelated CAN bytes. DIS Car Info and the DataView engine, transmission
and AWD pages consume named values; raw Diagnostics and logger group subscriptions
remain supported. Haldex tuning commands and logger control remain independent.

Settings under `diagnostics.values`:

```json
{"diagnostic_hz": 2, "ican_hz": 10, "lease_seconds": 15}
```

## Commands

Use a ZMQ REQ socket on `vehicle_data_command` and send JSON. A `SYNC_VALUES`
replaces one client's complete interest set. Renew within the configured lease;
the supplied consumers renew every five seconds. An empty set removes polling
interest. `UNSUBSCRIBE` releases the client immediately.

```json
{
  "cmd": "SYNC_VALUES",
  "client_id": "my_display",
  "values": [
    "engine.maf",
    {"id": "engine.ignition_timing", "rate_hz": 2},
    {"id": "engine.oil_temperature", "period_ms": 2000}
  ]
}
```

Each value can set `source` to `auto` (default), `diag`, `ican`, or a provider ID
from `CATALOG`. Specify either `rate_hz` or `period_ms`; omitting both uses the
source's configured default. Estimated and unverified providers require explicit
`allow_estimated: true` or `allow_unverified: true`, respectively.

Other commands:

- `CATALOG`: discover value IDs, types, units, provider mappings and notes, with a
  `coverage` summary of engine reference coverage and catalog counts.
- `SNAPSHOT` with `client_id`: cached samples using that client's source policy.
  Optional `values` is a list of IDs. Without a client, this is a default-policy
  diagnostic snapshot; it does not subscribe or schedule reads.
- `PLAN`: selected providers, shared groups/periods, uncovered values and reasons.
- `STATUS`: client leases, broker plan, TP2 requested/achieved rates, request
  durations, inhibition and recently observed raw group metadata.
- `UNSUBSCRIBE` with `client_id`: release that client's interests.

DataView also exposes `/api/values/catalog` and `/api/values/status` for inspection.

## Samples and freshness

Subscribe to topic `HUDIY_VALUES` on `vehicle_data_stream`. Each multipart message
contains a topic and JSON envelope `{version, client_id, values}`. Each sample
contains `id`, `value`, `unit`, `status`, `quality`, `source`, `timestamp`, `age_ms`,
`max_age_ms`, and `sample_sequence`. Filter by `client_id`: different clients may
pin different sources for the same value.

Values can be numbers, strings, statuses (decoded text or numeric codes) or
bitfields (including masked `X` bits). When the reference does not specify units,
the definition uses `unit: null` and `unit_policy: "reported"`; a successful sample
retains the ECU-decoded unit. Counters are not converted into rates. Unknown
formulas are invalid, including for status values. Identification entries expose
individual decoded fields; the generic triple decoder does not assemble a full VIN.

Passive enum labels come from documented encodings. Separate sign bits,
two's-complement values, validity bits, multiplexed custom telemetry pages and
unit selectors are checked before a reading becomes usable. Range and consumption
variants have explicit unit-specific IDs; only the variant matching the frame's
unit flags is valid.

Only `status: "ok"` is currently usable. Other states are `stale`, `invalid`,
`unavailable`, or `paused`. Timestamp is the original host acquisition/receipt
time, not an ECU clock. Re-emitting cached data never updates it. Consumers expire
samples locally as well, so a stopped broker cannot leave a reading looking live.

The planner uses deterministic weighted greedy group cover and removes redundant
groups. It considers measured request costs, shared values, existing external
group demand and per-client rates/source restrictions; it does not claim an exact
global mathematical optimum. A failed passive provider falls back to diagnostics
where semantics match. Recovery requires consecutive healthy passive samples and
a settling interval to prevent repeated switching. TP2 continues enforcing
ignition, user disable, flashing mode and exclusive diagnostic ownership.

## Extra measuring fields

There is no four-field limit in decoding, publication or raw diagnostic consumers.
Every complete three-byte field is retained. Group results carry `block_count`,
`raw_data_hex`, `trailing_bytes`, `complete`, `acquisition_timestamp`, and
`request_duration_ms`. Incomplete responses stay available for raw inspection,
but do not become canonical value samples.

Diagnostic provider `block` numbers are **one-based**, including blocks 5..8.
Group 11's extra ambient/MAF/speed annotations remain unverified candidates.
They are excluded from default planning. Formula/units alone do not establish
a field's meaning. Confirm a mapping with captures before marking it verified in
`catalog.py`; the catalog supports arbitrary block indices.

Run the inspector from the checkout, choosing the groups explicitly:

```sh
python3 tools/inspect_measuring_groups.py --target 01:11,118 --output capture.ndjson
python3 tools/inspect_measuring_groups.py --target 01:3,11 --target 02:11,12 --as-fast --duration 30 --output capacity.ndjson
```

The first command uses 2 Hz. `--as-fast` explicitly benchmarks maximum worker
polling. The tool preserves raw fields and reports observed update rates and
mean/p95 request duration; it respects diagnostic inhibition and clears only its
own subscriptions. No capacity or extra-field semantics have been confirmed on
vehicle hardware by this implementation.

## Semantic boundaries

ICAN `MO7_DFM` is generator duty, not engine load. ICAN `MO7_Ladedruckneu` has
vehicle-specific display semantics and remains unverified. Altitude-derived
atmospheric pressure is estimated. The ICAN altitude factor ratio remains separate
from diagnostic group 6's correction representation until their equivalence is
confirmed. Filtered/unfiltered ambient, diagnostic
ambient, G62 coolant, engine outlet temperature, battery voltage and engine
terminal-30 voltage remain separate values. Relative boost requires valid actual
absolute pressure and atmospheric pressure; its DIS consumer does not silently
substitute standard atmosphere.

AWD retains the existing TP2 destination `0x0A`; the reference filename ends in
`22`, and the address relationship is not established here. The custom Haldex
passive providers require the documented firmware telemetry contract; an absent
frame or an unsupported telemetry page stays unavailable/invalid. Raw quantities
with unconfirmed scaling keep count units. Calculated/projected quantities and
cluster estimates retain the explicit `allow_estimated` subscription policy.
