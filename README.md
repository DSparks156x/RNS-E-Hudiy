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

Back up your current setup, scripts, config files etc, or even use a new SD card/drive and fresh install before installing this. 

Im not responsible for thermonuclear war, divorce, timing chain tensioners failing etc etc caused by these scripts. 

Feel free to open an issue or message me on forums if you have any questions/suggestions. 
---

## Installation

1.  Clone the repository:
    ```bash
    ... acquire update_rnse.sh from hudiy_client folder.
    ```
2.  Run the installer:
    ```bash
    sudo ./update_rnse.sh -i
    ```
    *   **Note**: `update_rnse.sh -i` replaces Hudiy config files. `config.json` is only replaced if it doesn't exist.

---

## Configuration

Main configuration is in `config.json`.

### General Settings
*   **Branch**: 
    *   `testing`: Latest code from `main`.
    *   `beta`: Latest beta or release tag.
    *   `release`: Latest stable release tag.
*   **Can interface**: Sets the socketcan interface (Default: `can0`).
*   **ZMQ**: Configures internal ZMQ streams. (Avoid modifying unless necessary).
*   **CAN Ids**: Configures specific CAN IDs used by scripts. 
    *   **Ignition Status**: `2C3` is standard for TTs, `271` for some other platforms.
*   **FIS_line/Media/Nav**: Currently unused.

### Features
*   **Listen only mode**: Puts `can0` into listen-only when ignition is off, otherwise the radio will not go to sleep.
*   **Road-side**: Determines roundabout icon rotation. 
    *   `right`: Counterclockwise icons.
    *   `left`: Clockwise icons.
*   **Units**: 
    *   `Speed` and `Ambient Temp`: Currently unused, but if I do anything with speed/0-60 or take over the top lines and display ambient temp I will want it imperial, as I am a pesky american. 🦅🦅🦅🦅
    *   All other data is displayed as metric, just as the Germans intended. 
*   **Navigation**: Displays units as delivered by the `hudiy_api`.

---

## Updating

Use the update button in the Hudiy menu or run:
The update button will quit hudiy, wait for the Pi to have internet (Ie, connect to your phones hotspot or home wifi), and then update and reboot.
```bash
sudo ./hudiy_client/update_rnse.sh
```

## Architecture

Managed via `systemd` services:
*   `can_handler`: Central gateway to CAN hardware.
*   `can_base_function`: TV tuner simulation and time sync.
*   `can_keyboard_control`: Translates CAN signals to virtual keyboard inputs.
*   `dis_service` & `dis_display`: DIS rendering and logic.
*   `tp2_worker`: TP2.0 diagnostic communication.
*   `hudiy_dataview`: Provides Hudiy Dataview app
*   `hudiy_status_service`: Decodes some of the status messages on the infotainment bus that contain various pieces of data (RPM/Boost/Coolant/Oil/Ambient/Bat Voltage)
---
