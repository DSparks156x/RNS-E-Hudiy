# RNS-E Hudiy 

A fork of Korni92's RNS-E-Hudiy with new features and tweaks to my own preferences.

---

## Features

### DIS (Driver Information System)
*   **Contextual Display**: Shows navigation, now playing, and phone info from Hudiy API. 
*   **Smart Auto-Switching**: Automatically switches to the Navigation tab when a maneuver is active or approaching (~200m).
*   **Automatic Return**: Returns to the previous tab 5 seconds after a maneuver is completed.
*   **Tab switching**: Cycle between screens with the Stalk Rocker
*   **Cool Icons**: Unecessarily Complete set of navigation icons for the DIS even though half of them go unused with the current hudiy api and several are used wrong anyways. 

### Hudiy DataView & Diagnostics
*   **Dashboards**: Real-time dashboards for Engine, Transmission, and AWD.
*   **VW TP2.0 Diagnostics**: Pull and clear DTCs directly from the UI, on some modules. Engine works, others somewhat. 
*   **Measuring Groups**: View specific module measuring blocks.
*   **Diagnostic Toggle**: Safety switch to stop all diagnostic activity to allow use of VCDS/Scanners. 

### Inputs & Power
*   **Unified Inputs**: Handles RNS-E and Steering Wheel Control (SWC) buttons.
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

---

## Updating

Use the update button in the Hudiy menu or run:
The update button will quit hudiy, wait for the Pi to have internet (Ie, connect to your phones hotspot or home wifi), and then update and reboot.
Updating will add any new options to all config files, and back up old ones. 
```bash
sudo ./hudiy_client/update_rnse.sh
```
Configs can be overwritten using the restore configs button, or run the restore configs script directly.  It will **replace** all config files and create backups. 
Config restore uses the configured repo/branch, it can be your own config reference. 

## Architecture

Managed via `systemd` services:
*   `can_handler`: provides a zmq stream of raw can messages to and from infotainment bus.
*   `can_base_function`: TV tuner simulation and time sync.
*   `can_keyboard_control`: Translates CAN signals to virtual keyboard inputs.
*   `dis_service` & `dis_display`: DIS rendering and logic.
*   `tp2_worker`: Diagnostics over TP2. currently not over the can handler. 
*   `hudiy_dataview`: Provides Hudiy Dataview app
*   `hudiy_status_service`: Decodes some of the status messages on the infotainment bus that contain various pieces of data (RPM/Boost/Coolant/Oil/Ambient/Bat Voltage)
---
