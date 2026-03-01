# RNS-E Hudiy Integration

A feature-rich fork of Korni92's RNS-E-Hudiy integration for Audi RNS-E head units and Raspberry Pi.

---

## Features

### DIS (Driver Information System)
*   **Contextual Display**: Shows navigation, now playing, and phone info from Hudiy API.
*   **Smart Auto-Switching**: Automatically switches to the Navigation tab when a maneuver is active or approaching (~200m).
*   **Automatic Return**: Returns to the previous tab 5 seconds after a maneuver is completed.
*   **White DIS Support**: Optimized for 2010+ White DIS clusters with specific handshake fixes.

### Hudiy DataView & Diagnostics
*   **Dashboards**: Real-time dashboards for Engine, Transmission, and AWD.
*   **VW TP2.0 Diagnostics**: Pull and clear DTCs directly from the UI.
*   **Measuring Groups**: View specific module measuring blocks.
*   **Diagnostic Toggle**: Safety switch to stop all diagnostic activity for VCDS/ODIS usage.

### Inputs & Power
*   **Unified Inputs**: Handles RNS-E and Steering Wheel Control (SWC) buttons.
*   **Power Management**: GPIO shutdown via Radio Amp Wake signal for fast boot.
*   **CAN Listen Only**: Automatically puts CAN into listen-only mode when ignition is off.

### Icons
*   Complete set of 44 maneuvers resized for the 2-color DIS display (31x37).

---

## Architecture

Managed via `systemd` services:
*   `can_handler`: Central gateway to CAN hardware.
*   `can_base_function`: TV tuner simulation and time sync.
*   `can_keyboard_control`: Translates CAN signals to virtual keyboard inputs.
*   `dis_service` & `dis_display`: DIS rendering and logic.
*   `tp2_worker`: TP2.0 diagnostic communication.

---

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/DSparks156x/RNS-E-Hudiy.git
    cd RNS-E-Hudiy
    ```
2.  Run the installer:
    ```bash
    sudo ./install.sh
    ```
    *   **Note**: `install.sh -u` skips replacing Hudiy config files. `config.json` is only replaced if it doesn't exist.
3.  Configure CAN HAT oscillator frequency (usually 12MHz) and interrupt pin when prompted.

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
*   **Listen only mode**: Puts `can0` into listen-only when ignition is off to keep the radio sleep cycle healthy.
*   **Road-side**: Determines roundabout icon rotation. 
    *   `right`: Counterclockwise icons.
    *   `left`: Clockwise icons.
*   **Units**: 
    *   `Speed` and `Ambient Temp`: Currently for display calculation (Imperial vs Metric).
    *   Note: Most data is processed as metric; these units adjust the HUD/DIS presentation.
*   **Navigation**: Displays units as delivered by the `hudiy_api`.

---

## Updating

Use the update button in the Hudiy menu or run:
```bash
./hudiy_client/update_rnse.sh
```


