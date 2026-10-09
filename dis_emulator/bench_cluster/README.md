# Physical DIS bench console

A local web console for the physical bench cluster. It uses the full production
DisplayEngine loop, app renderers, wheel router, DIS protocol and J2534 transport.
It lives alongside the screen emulator; the cluster itself is the display.

## Start and stop

1. Power the bench cluster and connect the J2534 adapter to the bench CAN bus.
   Close any other program that owns the adapter or sends DIS drawing commands.
2. Open PowerShell in this folder:

   ```powershell
   Set-Location 'C:\Users\raccoon\Documents\carstuff\RNS-E-Hudiy\dis_emulator\bench_cluster'
   python run.py
   ```

3. Open [http://127.0.0.1:8766/](http://127.0.0.1:8766/).
4. Wait for **Telemetry connected**, driver **READY**, and **Engine running**.
   The cluster may occupy its center display with startup warnings for roughly
   the first 30 seconds. A busy rejection during that period is possible.
5. Select a page and send some data. Check the physical display as well as the
   reported ACK.

The launcher starts one adapter service, sends wake/ignition traffic, and starts
one full display client. Wake traffic continues until the launcher stops; there
is no timed demo shutdown. Reloading or closing the browser does not stop it.

To finish, press **Ctrl+C in the launcher terminal**. It stops the display client
first and then closes the adapter cooperatively. If it reports that the adapter
is still closing, inspect the session logs before starting another owner.

### Python and dependencies

The Scanmatik DLL requires **32-bit Python for the adapter process**. The launcher
can run under a different Python interpreter and use a separate adapter Python:

```powershell
python run.py --adapter-python 'C:\Users\raccoon\AppData\Local\Programs\Python\Python311-32\python.exe' --j2534-shim 'C:\Users\raccoon\Documents\carstuff\HaldexRE\flasher\j2534.py'
```

On this workstation, you can also run the whole launcher with the known 32-bit
interpreter:

```powershell
& 'C:\Users\raccoon\AppData\Local\Programs\Python\Python311-32\python.exe' run.py
```

Install requirements into each interpreter that needs them:

```powershell
python -m pip install -r requirements.txt
& 'C:\Users\raccoon\AppData\Local\Programs\Python\Python311-32\python.exe' -m pip install -r requirements.txt
```

The launcher uses the existing sibling clusterRE/.bench_deps when the interpreter
matches its Python 3.11 / 32-bit packages. The J2534 shim also needs traffic.py
beside it in HaldexRE/flasher. Keep the repository's dis_client, rns-e_can,
vehicle_data and hudiy_dataview modules available; this folder is not a standalone
replacement for them.

### Ports and an existing service

The default HTTP port is 8766; the IPC base is 18650, with draw at 18652 and status
at 18653. Use --port to change HTTP and --base-port to move the IPC range.

To connect to a service that is already running, without opening another adapter:

```powershell
python run.py --connect-existing --draw-port 18652 --status-port 18653
```

Use the existing service's actual ports. It must supply real DIS state/feedback
and keep the cluster awake. Only one display client should paint the cluster.
The connect-existing launcher does not own or shut down that external service.

## Manual display controls

Select a page under **Pages & physical inputs**, edit the matching data form, and
press its Send button. Sending data and choosing a visible page are separate
operations; the bench deliberately disables automatic nav/phone takeover.

- **Media:** title, artist, album, playback position/duration and playing state.
- **Navigation:** maneuver, side, optional angle, road/description and distance.
  Distance accepts labels such as 150 m, 1.2 km or 500 ft. A complete Send
  navigation action also updates real route-active status. Blank angle means
  absent. Distance-only callbacks cannot revive an ended route.
- **Phone:** contact, number and state. State is sent verbatim; use the state
  names your producer supports. Bench phone actions do not send host key input.

Polling preserves unfinished form edits. **Load latest form values** replaces
those drafts with the most recently reported data.

### Wheel and wiper rocker

These buttons inject receive-side events into the actual client handlers. They
exercise the production ownership and page-readiness gates.

| Control | What to test |
| --- | --- |
| Rocker up/down | Change the display page through the real wiper-stalk handler. |
| Double MODE | Toggle NORMAL / DIS wheel ownership on a supported, ready page. |
| MODE | A single press takes its normal action after the double-press window. You can also double-click this button to test two ordinary presses. |
| Scroll up/down | Follow the current owner: normal route or DIS page selection. |
| Click | A single click resolves after the double-click window; selection depends on the current page and owner. |
| Double click / hold | Additional production gestures under the expandable controls. |

Watch **Owner**, page support and **Pending gestures**. Scroll/click never force
DIS ownership. Normal-route events are recorded in the console instead of
injecting keys into Windows. Page/context transitions can reset ownership;
reselecting the same current page does not guarantee a reset.

For a simple ownership check, select Car Info, use Double MODE, verify Owner: DIS,
scroll/click its actions, then use Double MODE again and verify Owner: NORMAL.
Gesture timing comes from the repository's configured MFSW double-click window
and MMI long-press message count.

## Navigation comparison and routines

Under **Navigation setup**, choose Native stock or Custom bitmap and press
**Apply setup**. The existing **High-resolution custom artwork** setting chooses
high/normal bitmap rendering; native icons use their extracted glyphs.

Both styles use the same street text and native approach bar above it. Native
stock mode currently omits the numeric maneuver distance. The white bar fill
advances from the top as you approach; the threshold controls its appearance.

A useful manual sequence is:

1. Select Navigation, choose a maneuver and send 301 m with a 300 m threshold.
2. Send 300 m, 150 m and 0 m, then 301 m again to inspect the threshold crossing,
   fill updates and disappearance.
3. Change the maneuver/road while staying on Navigation.
4. Switch to Media and back to inspect page opening.
5. Repeat with Custom bitmap high resolution, then normal resolution.

**Test routines** provide Mixed pages, Approach bar and Random maneuvers. Choose
an interval, optionally set the random seed, and press **Start routine**. Reusing
a seed repeats the random sequence. Routines continue until **Stop routine**;
a manual action also stops them so they cannot overwrite your manual test.

The interval is a minimum scheduling interval, not guaranteed frame time. Each
step waits for real readiness, applied-command feedback and any pending draw.
Large bitmap icons can take longer than native glyphs. Stale telemetry pauses
progress; a draw NACK stops the routine and holds the rejected scene.

## Car Info and HUDIY DataView logging

Car Info uses the production ReadingsApp in high-resolution mode, the production
WorkspaceStore schema and the real DataLogs recorder. Profiles, DIS pages, eight
slots, units, precision and fonts come from the DataView workspace.

At startup, the console reads the source workspace selected by the repository's
config.json and copies it into the new bench session. **Configured source path**
and **Saved bench path** are displayed separately. If the source is absent,
production defaults are used; malformed existing documents fail visibly.

To use another DataView layout, paste its complete workspace JSON into **Saved
workspace JSON**, then press **Validate & save local**. **Load saved** restores
the saved bench document to the editor. Saves affect this session's copy only.
A new launcher session imports the source again; Pi edits are not live-synced.
To retain bench edits for another session, keep that workspace file and paste it
into the next session's editor.

### Record and inspect a test session

1. Select Car Info and a saved recording profile under **Car Info / DataView**.
2. Press **Start** and confirm that the recorder reports recording.
3. Choose a configured catalog value under **Simulated value sample**, enter a
   value/status, and press **Inject simulated value**. Only values in the active
   recording profile are recorded. Unavailable initial samples are possible.
4. Enter a marker note and press **Mark**.
5. Press **Stop**. Confirm the session ID, sample/marker counts and dropped rows.
6. Open the displayed **Local logs** directory for production-format session
   metadata and NDJSON samples, or expand **Saved local sessions**.

You can also use Double MODE to take DIS ownership, then scroll/click the actual
Car Info Start/Mark/Stop actions. Follow their displayed order: the actions change
when recording starts. The current implementation lists Stop before Mark while
recording; do not assume the selected action stayed in the same row.

The bench records submitted fixtures; it does not start vehicle acquisition or
diagnostic workers. HUDIY_VALUES updates Car Info even when another page is open.
Fixture values can become stale and show -- according to their freshness limits.

## Advanced inputs

**Topic / JSON injector** sends object payloads through the actual supported
HUDIY callbacks, including vehicle values, diagnostics, Openpilot and cover art.
Use the production producer schemas; malformed or unsupported payloads report
errors. Format JSON only formats the editor.

**CAN receive fixture** feeds an 11-bit ID and 1-8 bytes into the client's receive
handler. It does not transmit that simulated frame to physical CAN. The 351 speed
helper zeroes the other fields; moving its slider sends nothing until **Inject
speed sample**. Use explicit bytes when investigating those other fields.

## Status, errors and session files

| Indicator | Meaning |
| --- | --- |
| Telemetry connected / ages | Fresh service and display reports, independently of frame ACKs. |
| Driver READY | Actual cluster/service readiness. |
| Queued / engine applied | Ordered action delivery. Queued alone does not prove a draw finished. |
| Pending frame | An outstanding client draw awaiting a result. |
| Last driver ACK / NACK | The last completed/rejected frame and its age; an old entry remains visible. |
| Drawing held | An active NACK hold. Correct the data or select a page once the driver is ready. |
| Recorded engine errors | Preserved history. A recorded NACK labelled no current drawing hold is not an active hold. |

ACK confirms driver/transport acceptance; inspect the physical cluster for the
resulting image. A lack of new ACKs on an unchanged page can be normal. Use the
**Live event log** and **Inspect latest backend state** for details.

Each normal launcher run creates runtime/<timestamp>/ in this folder:

- service_stdout.log and service/: adapter, handshake, wire and service events.
- console/engine.log and input_events.jsonl: display engine and virtual inputs.
- console/bench_display_config.json, workspace.json and client_sources_at_start.json: session
  settings, local DataView workspace and loaded client source identities.
- console/logs/sessions/: recorded DataView sessions.

If the cluster is busy at startup, wait for its warning screens to finish and
READY to return, then select a page or send corrected data to release the hold.
If telemetry is stale or the engine stopped, inspect the logs rather than treating
an HTTP Queued message as success. For an occupied adapter/port, stop its existing
owner cleanly before restarting. An unavailable native draw or unsupported JSON
should remain a visible failure; do not repeatedly run the same failing routine.

## Scope and checks

This is the full DIS rendering client on a bench, not the complete Pi / Android
Auto stack. Phone/keyboard external actions are inert, automatic takeover is
disabled, the Settings reboot action is omitted, and preferences stay local.
Car Info app class selection occurs at startup; changing resolution live does
not replace that app class. Restart with the desired source configuration when
comparing its class variants. Settings retains the production page's current
input limitations.

There is no arbitrary draw-packet, firmware-flash, diagnostic-session or raw CAN
transmit endpoint in the browser. The adapter service does transmit the required
wake/ignition and real DIS protocol traffic.

Offline console checks (no adapter needed):

```powershell
python -m unittest test_console -v
```

See [REVIEW.txt](REVIEW.txt) for review and physical acceptance references.
