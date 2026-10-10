# r21 TV panel shortcuts in Hudiy

## Default mappings

| Button | K1 K2 (hex) | Config pair (decimal) | Action |
|---|---|---|---|
| NAV | 08 00 | `8,0` | Navigation shortcut (`KEY_F`) |
| TEL | 00 08 | `0,8` | Phone shortcut (`KEY_G`) |
| MEDIA | 00 04 | `0,4` | Current media player (`KEY_J`) |
| NAME | 04 00 | `4,0` | App menu (`applications_menu`) |
| INFO | 00 0C | `0,12` | DataView (`hudiy_diagnostics`) |
| CAR | 0C 00 | `12,0` | RNS-E Manager (`hudiy_manager`) |
| SETUP | 00 01 | `0,1` | Existing home shortcut (`KEY_H`) |
| RADIO | none | none | Factory radio; leaves TV |

No new voice-assistant binding is added. Existing knob, arrows, RETURN, track buttons, SETUP and steering-wheel mappings retain their behavior.

All faceplate buttons use `input_mappings.mmi.short_press`, `long_press`, and `extended_press`. The six new masks are included in each table. Their short defaults appear above; long and extended defaults are `null`. Short/long values accept Linux `KEY_*` strings, Hudiy action objects such as `{"action":"hudiy_diagnostics"}`, or `null`. Extended mappings also accept shell-command strings; shell commands require `features.system_actions`. Key and Hudiy actions do not require that switch.

The config tool labels NAV, TEL, MEDIA, NAME, INFO and CAR in all three groups. The Netlify guide's clickable faceplate reads a snapshot of those same tables and displays short, long and extended actions. Refresh the snapshot with `npm run sync-tools --prefix help-site` when defaults change. Older Pi configs need these six entries merged into their existing tables.

## CAN handling

The r21 firmware emits standard ID `0x461`, DLC 6, `37 30 SS K1 K2 00`, only while TV is active. Like existing faceplate buttons, repeated `01` frames count toward the configured hold thresholds. A short press fires once on the first `04` release; repeated releases do nothing. Configured long and extended actions fire once at their thresholds. Null hold mappings leave the short action available on release, even after a prolonged hold. Frame validation matches complete byte pairs: INFO and CAR are distinct buttons, not bitwise combinations. Extended-ID, remote and error CAN frames are rejected.

MEDIA `00 04` replaces the former r20d RADIO mask. RADIO no longer emits a shortcut frame. Original capture: `C:/Users/raccoon/Documents/carstuff/RNSE hacking/analysis/TV_BUTTONS_0x461_R21.md`.

Keys use the existing uinput keyboard. App/menu actions travel over the existing input-control stream to the connected Hudiy API service; they require `hudiy_data_api.service`. Actions observed while disconnected are discarded rather than replayed after reconnecting.

## Projection behavior and deployment checks

Hudiy documents F/G/J as navigation, phone and current-player shortcuts, with equivalent API KeyEvent types. Its public docs do not guarantee which projected app opens on Android Auto versus Autobox/CarPlay, and the API does not accept a target package/app identifier for these keys. Check those three buttons with each projection provider before expecting Google Maps/Waze/Spotify selection. Resuming projection alone does not select a particular app.

ProjectionStatus reports visibility, not connection state. This implementation does not automatically select/resume a provider based on media/navigation hints.

The capture mentions firmware TV modes `0x38/0x47`. Existing playback source handling compares byte 3 of a different frame (`0x661`) with configured `0x37`; that identifier is preserved.

After installing the updated code and merging config defaults, restart `can_handler.service`, `can_keyboard_control.service`, and `hudiy_data_api.service`. On the bench, test taps and holds, all six shortcuts, SETUP home, RADIO source exit, rapid alternating buttons, and existing knob/RETURN/wheel controls. Inspect `journalctl -u can_keyboard_control.service -u hudiy_data_api.service` for shortcut dispatch logs. Offline replay tests verify event handling; physical projected screen routing remains a bench check.

## References

- [Hudiy keyboard bindings](https://github.com/wiboma/hudiy#interface)
- [Hudiy predefined actions](https://github.com/wiboma/hudiy#list-of-predefined-actions)
- [Hudiy KeyEvent and DispatchAction API](https://github.com/wiboma/hudiy/blob/main/api/Api.proto)
- Local `rns-e_can/can_keyboard_control.py`, `hudiy_client/hudiy_data.py`, and `config.json`.
