# RNS-E Hudiy 

A fork of Korni92's RNS-E-Hudiy with new features and tweaks to my own preferences.

---

## Features

### RNS-E Manager

Edit integration and Hudiy configuration, control project services and read
recent logs on the head unit. The Files portal also accepts validated config
replacements with backups. See [Manager usage](hudiy_manager/README.md).

RNS-E controls include automatic screen brightness (0–10), separate automatic
LCD brightness (0–100), startup baselines when each automatic channel is off,
and an opt-in source label based on Hudiy’s reported media/navigation provider.
The provider label does not indicate an exact connection state.
The RNS-E page also has live Pi video controls for gamma, contrast, black point
and RGB gains, with optional startup profiles and original-color restoration.
The same page offers [r21 ADC tuning](hudiy_manager/ADC_TUNING.md): linked RGB
gain/offset, timing and sync controls, complete register dumps, stock Revert,
named volatile presets, and a full-size 800×480 calibration image.

### DIS (Driver Information System)
*   **Contextual Display**: Shows navigation, now playing, and phone info from Hudiy API. 
*   **Smart Auto-Switching**: Automatically switches to the Navigation tab when a maneuver is active or approaching (~200m).
*   **Automatic Return**: Returns to the previous tab 5 seconds after a maneuver is completed.
*   **Tab switching**: Cycle between screens with the Stalk Rocker
*   **Cool Icons**: Unecessarily Complete set of navigation icons for the DIS even though half of them go unused with the current hudiy api and several are used wrong anyways. 

### Hudiy DataView & Diagnostics
*   **Dashboards**: Real-time dashboards for Engine, Transmission, and AWD.
*   **Data & Logs**: Configurable named-value recordings, short graph review, CSV export,
    and eight-slot DIS page configuration. The value picker browses the complete API
    catalog by system and function.
*   **VW TP2.0 Diagnostics**: Pull and clear DTCs directly from the UI, on some modules. Engine works, others somewhat. 
*   **Measuring Groups**: View specific module measuring blocks.
*   **Diagnostic Toggle**: Safety switch to stop all diagnostic activity to allow use of VCDS/Scanners. 
*   **Offline File Portal**: Open `/files` from a phone on the Pi network to upload
    validated controller firmware or download drive logs, saved service journals, flash
    operation logs, live service errors, and controller readouts. The head-unit DataView
    remains a separate 800x480 interface.

### Inputs & Power
*   **Unified Inputs**: Handles RNS-E and Steering Wheel Control (SWC) buttons.
*   **r21 TV panel shortcuts**: NAV navigation, TEL phone, MEDIA current player, INFO DataView, CAR RNS-E Manager, and NAME app menu. SETUP stays home; RADIO returns to factory radio. All faceplate buttons share the short, long and extended press mappings. See [button mapping details](references/TV_BUTTONS_HUDIY_MAPPING.md).
*   **Power Management**: GPIO shutdown via Radio Amp Wake signal for fast boot.
*   **CAN Listen Only**: Automatically puts CAN into listen-only mode when ignition is off.

---

# Big ass disclaimer 

release should be ~stable/functional, beta may have things that dont work as intended, testing will pull latest main, which could be completely broken. Don't count on my releases or any other channel not being broken or not messing up your setup. I am not thoroughly testing every release/setup combination.. If it worked fine on my setup its good to go. Default configs reflect my setup (see more info on that below).

**Back up your current setup, scripts, config files etc, or even use a new SD card/drive and fresh install before installing this.**

Im not responsible for thermonuclear war, divorce, timing chain tensioners failing etc etc caused by these scripts. 

Feel free to open an issue or message me on forums if you have any questions/suggestions. 

* Known issues can be found in the [Fixlist.md](FixList.md) file, along with roadmap.

---

## Installation

1.  Download the script:
    ```bash
    ... acquire update_rnse.sh from hudiy_client folder.
    ```
2.  Run the installer:
    ```bash
    sudo ./update_rnse.sh
    ```
    *   **Note**: `update_rnse.sh` will download the latest install.sh and run it. it will add new options to hudiy configs, and create config.json.  It will create backups of configs it changed.
3. Configure your CAN interface
    The script will bring up CAN0, but your can interface must be configured, ie your mcp2515 in config.txt etc. 
4. Configure your Pis config.txt and cmdline.txt as needed.
---

## Configuration

To edit the configuration, use the built-in Config Editor tool:

1. Open `tools/config_editor.html` on your computer in any web browser.
2. Click **Import JSON** and select `config.json` from the device.
3. Modify settings as desired (the editor includes descriptions for each parameter).
4. Click **Export config.json** to save the updated file, and overwrite the file on the device.

Main configuration variables and descriptive guides are defined in the editor's schema.

### Data & Logs and configurable DIS readings

Open **Data & Logs**, between AWD and Diagnostics. Recording profiles select named
values from the complete vehicle-data catalog. Browse by system and functional group,
search all values, or view only the selected values. Catalog support does not guarantee
that a particular controller currently supplies a reading; source status and freshness
remain visible. Estimated and unverified providers require an explicit profile opt-in.

Names and searches open a built-in touch keyboard sized for an 800×400 screen.
New page/profile dialogs open it automatically. QWERTY, Shift/Caps, numbers and
symbols, cursor arrows, Select all, Clear and hold-to-delete support editing without
a physical keyboard. **Done** applies the text to the field; **Cancel** discards the
keyboard edit. The form's **Save** or **Apply** still saves the configuration.
The keyboard uses the current Hudiy palette and enforces page/profile name limits.
The file portal also offers touch entry for searches and upload PINs; desktop mouse
and keyboard entry there continues to use normal inputs.

**Start** records the selected profile independently of the visible DataView tab.
**Mark** adds an event. **Stop & save** keeps the screen on Record, while **Stop & review**
opens the recent section. Review offers short time windows, numeric traces grouped by
unit, markers, and nonnumeric events. Invalid or stale samples produce gaps. Export CSV
for longer analysis. The existing Haldex/raw CAN logger remains available on AWD and
uses its original profiles.

The **DIS pages** section edits eight slots per page, units, precision, icon and native
font, plus the linked recording profile. Apply saves all page edits. The existing
`car_info` entry in `display.center_display.applist` opens this configurable screen
on native displays. Its position and inclusion remain controlled by that app list.
With `display.center_display.high_resolution` disabled, the red DIS retains the
five-line layout.
On a native DIS, changing numbers and header text use cluster text
commands; static icons and tiny units use a cached graphic layer.
The DIS icon picker shows that same pixel artwork. Reading symbols remain within
the existing ten-pixel column; unit legends occupy at most 9×11 physical pixels.
After changing the DIS icon artwork or automatic rules, run
`python tools/export_dis_reading_assets.py` before building DataView to keep its
picker and automatic choices synchronized.

Each new DIS slot chooses its own units here. The config editor's **Navigation &
Legacy Units** section remains for navigation/acceleration speed and older DIS or
boost-widget views; it does not override the new page slots.

Double-click **MODE** to toggle the navigation wheel between its configured normal
actions and DIS control. A native wheel symbol appears in the readings corner and
phone status only while DIS owns the wheel. The selected header item is inverted. Scroll moves
focus, click selects, and double-click the wheel goes back. On the readings page, select
the page name, scroll through subpages, and click to confirm. The play arrow starts
logging; while recording it becomes a stop square and a flag appears for markers.
Focus cycles through page, start/stop, then flag when recording. These controls
share the same recording session as the touchscreen. The stalk still cycles DIS apps;
leaving an app returns the wheel to normal mode. Subpage changes retain DIS control.

Phone behavior keeps the existing `display.phone.claim_on_phone` setting for automatic
page showing and `display.phone.scroll_wheel_phone_menu` for automatic wheel takeover.
Phone controls also work with calls shown only on the top display; the same wheel symbol
indicates wheel ownership. Manual readings control takes priority over phone takeover.
A manual MODE toggle overrides automatic takeover for the current call. Loss of the
DIS service heartbeat returns the wheel to its configured normal mappings. Volume
controls retain their existing mappings. Set `input_mappings.mfsw.double_click_ms` to
adjust the click window (default 350 ms).

MODE single press and hold retain their configured key mappings; double-click
needs no new binding or config restore. The second press must start within the
click window and can be released after it. The old `input_mappings.mfsw.phone_alt`
overrides are ignored by the shared wheel router. The keyboard service logs MODE
double-click recognition, wheel ownership changes, and unavailable DIS contexts
to `journalctl -u can_keyboard_control.service`.

Named recordings and shared page/profile configuration live in `~/logs/data-logs` by
default (`data_logs.directory`): `workspace.json` holds configuration and `sessions/`
holds session metadata and acquisition records. Updating the application does not
replace these files. The DataView service hosts the recorder and DIS logging command
endpoint; it must run even when logging is started from the wheel. See
[vehicle data service](vehicle_data/README.md) for source policies and sample metadata.

The `file_portal.firmware_targets` list controls upload destinations. Haldex images are
validated and stored in `~/haldexfw`; PQ EPS images are independently validated and
stored in `~/epsfw`. EPS accepts either a complete 384 KiB CPU-linear image or an exact
4 KiB `0x5E000–0x5EFFF` steering dataset. Haldex and EPS readouts are kept separately in
their respective `readouts` directories. Additional controllers can define their own ID,
label, directory, allowed extensions, size limit, and validator as support is added. Set
`file_portal.upload_pin` to require a PIN for uploads; downloads remain available to
devices on the Pi network.

### Native white DIS graphics

Use **Center display → High Resolution** for a white A3/TT DIS; disable it for a red
DIS. This single setting selects the font metrics, Car Info layout, navigation
graphics and cover-art resolution. In `display.center_display`:

```json
{
  "high_resolution": true,
  "coverart": {
    "native_preset": "legacy",
    "native_args": {},
    "native_render_order": "tiles",
    "native_delta": false
  }
}
```

Older configs migrate from their existing font selection, or their former graphics
flags when no font selection exists. The new setting always takes precedence.
Navigation uses the approved Maps SVG family as monochrome 72x72 icons and keeps distance,
street, and approach-bar overlays. Curated sources and provenance are in
`dis_client/nav_icons_sources/`; the development-only
`tools/generate_native_nav_icons.py` reproduces the packed masks. The runtime
does not need an SVG renderer.
Roundabout direction follows `display.road_side` (`right` means counterclockwise).
Cover art uses a full 128x96 canvas. The `legacy` preset applies your existing
`coverart.args` at native resolution; `native_args` overrides individual controls.
Other presets are `balanced` (ordered dither), `photo` (error diffusion), and `text`
(threshold). Their overrides belong in `native_args` and do not inherit legacy args.

`tiles` finishes small regions before moving on. `planes` draws a base followed by
subpixel layers, and `bands` finishes horizontal strips. These orders produce the
same target image but can look different while it is being drawn. `native_delta`
requires `tiles`; leave it disabled to send each cover as a complete snapshot.
Detailed or dithered images can take longer to settle on the LCD. A transport ACK
does not measure when the LCD has finished updating.

The Config Editor adds missing native options to older imports without changing
existing preferences. Restart the DIS services after saving configuration changes.

### Exhaust valve control and firmware

The Hudiy bar includes an exhaust valve toggle next to Haldex and Android Auto
reconnect. DataView **Modules → Exhaust valve controller** provides Open/Close
and firmware updates. Upload a ZIP containing `can-update.json` and both native
slot `.bin` images through **Files → Exhaust valve controller**, then refresh
the firmware list. The controller restores its own target on power-up; the Pi
sends valve commands only when requested. Commands and firmware transfers are
reported as unconfirmed because the vehicle protocol has no return route.
See [the SB2209 integration notes](flasher/EXHAUST_VALVE.md) for deployment
generation tracking and transfer behavior.

### Collecting Android Auto / CarPlay API behavior

Hudiy API diagnostics are always captured automatically. No configuration or
terminal commands are needed:

1. Connect Android Auto or CarPlay and use it normally: play/pause/change media,
   start and cancel a route, pass a few maneuvers, and place or receive a call.
2. Press **Save Logs** in the Hudiy menu.
3. Download the saved log folder (`~/logs/YYYY-MM-DD/1`, then `2`, and so on).
   It contains the recent service journals
   and `hudiy-api-events_*.log` (plus `hudiy-api-events-previous_*.log` if rotated).
4. Send the downloaded file unchanged. Each line records the provider, callback,
   raw protobuf fields and presence information, a bounded wire-data preview/hash,
   and the normalized data published to the rest of this project.

The capture retains at most two bounded files (8 MiB each). It can contain
street names, media metadata, contact names, and phone numbers, so treat it as private.
There are no capture configuration options; older capture settings are ignored
and removed during an update.

The **Save Logs** action also snapshots both available raw capture files into
the same dated, numbered folder as the recent service journals. All files in a
save share its number, and each button press creates a new folder. A
`hudiy_data_api_*.log` file is the service journal; the raw snapshots are named
`hudiy-api-events_*.log` and `hudiy-api-events-previous_*.log`. These contain
JSON-lines API events, including field presence and normalized results.
The live capture files can also be downloaded from **Hudiy API captures** at
DataView's `/files` page.

---

## Updating

Use the update button in the Hudiy menu or run:
The update button will quit hudiy, wait for the Pi to have internet (Ie, connect to your phones hotspot or home wifi), and then update and reboot.
Updating will add any new options to all config files, and back up old ones. 
```bash
sudo ./hudiy_client/update_rnse.sh
```
**Update Hudiy** quits Hudiy, opens a fullscreen terminal, waits for internet
access, then runs Hudiy's installed updater at `~/.hudiy/share/updater`. This
updates Hudiy itself separately from the RNS-E package. Hudiy's updater handles
the update interaction; see [Hudiy updating](https://github.com/wiboma/hudiy#updating).

Configs can be overwritten using the restore configs button, or run the restore configs script directly.  It will **replace** all config files and create backups. 
Config restore uses the configured repo/branch, it can be your own config reference. 

## Architecture

Managed via `systemd` services:
*   `can_handler`: provides a zmq stream of raw can messages to and from infotainment bus.
*   `can_base_function`: TV tuner simulation and time sync.
*   `can_keyboard_control`: Translates CAN signals to virtual keyboard inputs.
*   `dis_service` & `dis_display`: DIS rendering and logic.
*   `hudiy_dataview/data_logger.py`: profile-driven session logging built into DataView. The
    `haldex` profile produces fused Haldex/relevant-ICAN/measuring-group CSV snapshots; `raw_can`
    records arbitrary CAN traffic one frame per row. Logs default to
    `~/logs/YYYY-MM-DD/profile_0001.csv`, with daily recording numbers reserved before
    capture starts. The Files portal groups recordings and service captures by folder,
    lists the newest dates first, and offers a ZIP download for each folder. Logging
    can be extended by registering another `LogProfile`.
*   `tp2_worker`: Diagnostics over TP2. currently not over the can handler. 
*   `hudiy_dataview`: Provides Hudiy Dataview app
*   `hudiy_status_service`: Decodes some of the status messages on the infotainment bus that contain various pieces of data (RPM/Boost/Coolant/Oil/Ambient/Bat Voltage)
---
