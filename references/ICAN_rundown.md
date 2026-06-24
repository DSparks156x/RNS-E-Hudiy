# Rundown of Active CAN Messages & Signals.

This document evaluates `canlog.txt` against `PQ35_46_ICAN.dbc`. All 41 unique CAN IDs in the log were matched to DBC definitions. All signal names, comments, notes, and enum states have been fully translated to English using Google Translate API. Ai took some liberties to try to get abreviations translated.... so not everything correct.

only contains messages from the DBC that were present on my Mk2 TTs infotainment bus. 

## Message: `mAirbag_1` (0x151 / 337 Dec)
- **English Translation**: **m airbag 1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 4
- **Description**: CAN comfort CAN infotainment

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `AB1_FrontCrash` | **AB1_front_crash** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: Front crash<br>`0`: no front crash |
| `AB1_HeckCrash` | **AB1_rear_crash** | Bit 1, 1b, Intel | Scale: 1.0 | `0`: no rear crash<br>`1`: Heck_Crash |
| `AB1_Crash_FT` | **AB1_Crash_FT** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: Pages Crash Driver<br>`0`: no side crash driver |
| `AB1_Crash_BT` | **AB1_Crash_BT** | Bit 3, 1b, Intel | Scale: 1.0 | `0`: no side crash passenger<br>`1`: Side crash passenger |
| `AB1_Rollover` | **AB1_rollovers** | Bit 4, 1b, Intel | Scale: 1.0 | `1`: Rollovers<br>`0`: no rollover |
| `AB1_CrashStaerke` | **AB1_crash_strength**<br>*Note: Die folgende Auswertung ist bei VW geplant: ; >= 001: ZV auf, Innenlicht u. Warnblinker ein ; >= 010: Notruf ausgelst ; >= 100: Kraftstoffabschaltung (mit RDW-Schwelle aktiviert, d.h.Bit 7 = 1); ; Information bleibt bei jeder Schwellwert-berschreitung f* | Bit 5, 3b, Intel | Scale: 1.0 | `1`: Belt tensioner threshold exceeded<br>`3`: US threshold exceeded<br>`6`: RDW threshold exceeded<br>`2`: US threshold exceeded<br>`5`: RDW threshold exceeded<br>`4`: RDW threshold exceeded<br>`0`: no crash<br>`7`: RDW threshold exceeded |
| `AB1_AirbagLampe_ein` | **AB1_airbag_lamp_on** | Bit 8, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `AB1_Airbag_deaktiviert` | **AB1_airbag_deactivated** | Bit 9, 1b, Intel | Scale: 1.0 | `0`: active<br>`1`: disabled |
| `AB1_Beif_Airbag_deaktiviert` | **AB1_Beif_Airbag_deaktiviert** | Bit 10, 1b, Intel | Scale: 1.0 | `1`: disabled<br>`0`: active |
| `AB1_Systemfehler` | **AB1_System_error** | Bit 11, 1b, Intel | Scale: 1.0 | `1`: System error<br>`0`: no error |
| `AB1_Fa_Gurt` | **AB1_driver_belt** | Bit 12, 2b, Intel | Scale: 1.0 | `2`: Belt not inserted<br>`3`: Belt inserted<br>`0`: not available<br>`1`: Mistake |
| `AB1_Bf_Gurt` | **AB1_passenger_belt** | Bit 14, 2b, Intel | Scale: 1.0 | `2`: Belt not inserted<br>`3`: Belt inserted<br>`0`: not available<br>`1`: Mistake |
| `AB1_Diagnose` | **AB1_Diagnose** | Bit 16, 1b, Intel | Scale: 1.0 | `0`: nicht_in_Diagnose<br>`1`: in diagnosis |
| `AB1_Stellglied` | **AB1_actuator** | Bit 17, 1b, Intel | Scale: 1.0 | `1`: in the actuator test<br>`0`: not in the actuator test |
| `AB1_BF_Anschnall` | **AB1_Passenger_buckle_up** | Bit 18, 1b, Intel | Scale: 1.0 | `0`: no warning<br>`1`: Trigger seat belt warning |
| `AB1_KD_Fehler` | **AB1_KD_Fehler**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 19, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `AB1_MessageZaehler` | **AB1_message_counter**<br>*Note: Overflowing message counter for liveness detection* | Bit 20, 4b, Intel | Scale: 1.0 | - |
| `AB1_Pruefsumme` | **AB1_Pruefsumme**<br>*Note: Checksum, definition in the CAN specifications* | Bit 24, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mLSM_1` (0x2C1 / 705 Dec)
- **English Translation**: **mLSM_1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 6

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `LS1_Blk_links` | **LS1_turn_signal_left**<br>*Note: Left direction flashing activated (see Gateway Comfort)* | Bit 0, 1b, Intel | Scale: 1.0 | `0`: out of<br>`1`: aktiviert |
| `LS1_Blk_rechts` | **LS1_turn_signal_right**<br>*Note: Right direction flashing activated (see Gateway Comfort)* | Bit 1, 1b, Intel | Scale: 1.0 | `0`: out of<br>`1`: aktiviert |
| `LS1_Lichthupe` | **LS1_headlight_flasher**<br>*Note: Headlight flasher on* | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `LS1_Fernlicht` | **LS1_high_beam**<br>*Note: High beam switch* | Bit 3, 1b, Intel | Scale: 1.0 | `0`: High beam switch off<br>`1`: High beam switch on |
| `LS1_Parklicht_links` | **LS1_parking_light_on_the_left**<br>*Note: Parking light on left* | Bit 5, 1b, Intel | Scale: 1.0 | - |
| `LS1_Parklicht_rechts` | **LS1_parking_light_on_the_right**<br>*Note: Parking light on the right* | Bit 6, 1b, Intel | Scale: 1.0 | - |
| `LS1_Signalhorn` | **LS1_horn**<br>*Note: Horn on* | Bit 7, 1b, Intel | Scale: 1.0 | - |
| `LS1_Tipwischen` | **LS1_Tipwipe**<br>*Note: Tip swipe* | Bit 8, 1b, Intel | Scale: 1.0 | - |
| `LS1_Intervall` | **LS1_interval**<br>*Note: Interval or rain sensor automatic front wiper on* | Bit 9, 1b, Intel | Scale: 1.0 | - |
| `LS1_WischenStufe_1` | **LS1_wiping_level_1**<br>*Note: Wiper speed level 1* | Bit 10, 1b, Intel | Scale: 1.0 | - |
| `LS1_WischenStufe_2` | **LS1_wiping_level_2**<br>*Note: Wiper speed level 2* | Bit 11, 1b, Intel | Scale: 1.0 | - |
| `LS1_Frontwaschen` | **LS1_front_washing** | Bit 12, 1b, Intel | Scale: 1.0 | - |
| `LS1_Bew_Frontwaschen` | **LS1_Bew_front_washing** | Bit 13, 1b, Intel | Scale: 1.0 | - |
| `LS1_Heckintervall` | **LS1_rear_interval**<br>*Note: Lenkstockschalter (LSS) befindet sich in der Position Heckwischen im Intervallbetrieb. Signal wird auch ca 8 Sek. nach Heckwaschbetrieb gesetzt (Traenenwischen) oder bei Einlegen des Rckwaertsganges bei Frontwischerbetrieb und nasser Heckscheibe, obwohl * | Bit 14, 1b, Intel | Scale: 1.0 | `1`: Rear interval on<br>`0`: no rear interval wiping |
| `LS1_Heckwaschen` | **LS1_rear_wash** | Bit 15, 1b, Intel | Scale: 1.0 | - |
| `LS1_Intervallstufen` | **LS1_interval_levels**<br>*Note: Interval speed / rain sensor sensitivity (1: long pauses, 15: short P.)* | Bit 16, 4b, Intel | Scale: 1.0 | - |
| `LS1_BC_Down_Cursor` | **LS1_BC_Down_Cursor**<br>*Note: On-board computer cursor down* | Bit 20, 1b, Intel | Scale: 1.0 | - |
| `LS1_BC_Up_Cursor` | **LS1_BC_Up_Cursor**<br>*Note: On-board computer cursor UP* | Bit 21, 1b, Intel | Scale: 1.0 | - |
| `LS1_BC_Reset` | **LS1_BC_Reset**<br>*Note: On-board computer reset* | Bit 22, 1b, Intel | Scale: 1.0 | - |
| `LS1_KD_Fehler` | **LS1_KD_error**<br>*Note: 1 = at least one customer service error is entered in the error memory* | Bit 23, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `LS1_LSY_oben` | **LS1_LSY_above**<br>*Note: Steering column adjustment Y+* | Bit 24, 1b, Intel | Scale: 1.0 | - |
| `LS1_LSY_unten` | **LS1_LSY_below**<br>*Note: Lenksaeulenverstellung Y-* | Bit 25, 1b, Intel | Scale: 1.0 | - |
| `LS1_LSZ_vor` | **LS1_LSZ_vor**<br>*Note: Steering column adjustment Z+* | Bit 26, 1b, Intel | Scale: 1.0 | - |
| `LS1_LSZ_zurueck` | **LS1_LSZ_back**<br>*Note: Steering column adjustment Z-* | Bit 27, 1b, Intel | Scale: 1.0 | - |
| `LS1_ELV_enable` | **LS1_ELV_enable**<br>*Note: Befehl zum Verriegeln bzw. Entriegeln der elektrischen Lenksulenverriegelung* | Bit 28, 1b, Intel | Scale: 1.0 | `0`: Unlock ELV<br>`1`: Lock ELV |
| `LS1_def_ELV_Enable` | **LS1_def_ELV_Enable** | Bit 29, 1b, Intel | Scale: 1.0 | `0`: ELV_Enable_OK<br>`1`: ELV Enable defective |
| `LS1_Easy_Entry_LS` | **LS1_Easy_Entry_LS** | Bit 30, 1b, Intel | Scale: 1.0 | - |
| `LS1_LHeizung_aktiv` | **LS1_LHeating_active** | Bit 31, 1b, Intel | Scale: 1.0 | - |
| `LS1_Winterstellung` | **LS1_winter_position**<br>*Note: 1 = Positioning the wiper blades in winter position (reversing wiper system)* | Bit 32, 1b, Intel | Scale: 1.0 | - |
| `LS1_MFL_vorhanden` | **LS1_MFL_vorhanden**<br>*Note: 1 = Multifunction steering wheel available* | Bit 33, 1b, Intel | Scale: 1.0 | - |
| `LS1_MFA_vorhanden` | **LS1_MFA_available** | Bit 34, 1b, Intel | Scale: 1.0 | - |
| `LS1_MFA_Tasten` | **LS1_MFA_buttons** | Bit 35, 1b, Intel | Scale: 1.0 | - |
| `LS1_def_P_Verriegelt` | **LS1_def_P_Locked** | Bit 36, 1b, Intel | Scale: 1.0 | `1`: defect<br>`0`: OK |
| `LS1_MFL_Typ` | **LS1_MFL_type** | Bit 37, 1b, Intel | Scale: 1.0 | `0`: MFL Low operating concept Outdated<br>`1`: MFL High operating concept New |
| `LS1_Servicestellung` | **LS1_service_position**<br>*Note: 1 = Positioning the wiper blades in service position (enables changing the wiper blades)* | Bit 38, 1b, Intel | Scale: 1.0 | - |
| `LS1_P_verriegelt` | **LS1_P_locked** | Bit 39, 1b, Intel | Scale: 1.0 | `0`: P position<br>`1`: Selector lever out of park position |
| `LS1_FAS_Taster` | **LS1_FAS_button**<br>*Note: 1 = Control button for driver assistance systems activated* | Bit 40, 1b, Intel | Scale: 1.0 | `1`: Actuated<br>`0`: Unused |
| `LS1_Fehler_FAS_Taster` | **LS1_FAS_button_error**<br>*Note: Error in control buttons for driver assistance systems* | Bit 41, 1b, Intel | Scale: 1.0 | `0`: no error<br>`1`: Mistake |
| `LS1_Fehler_Vibration` | **LS1_Fehler_Vibration**<br>*Note: Vibration steering wheel error* | Bit 42, 1b, Intel | Scale: 1.0 | `0`: no error<br>`1`: Mistake |

---

## Message: `mZAS_Status` (0x2C3 / 707 Dec)
- **English Translation**: **m ZAS status**
- **Log Frequency**: 106 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 1

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `ZS1_ZAS_Kl_S` | **ZS1_ZAS_Kl_S** | Bit 0, 1b, Intel | Scale: 1.0 | - |
| `ZS1_ZAS_Kl_15` | **ZS1_ignition_starter_switch_terminal_15** | Bit 1, 1b, Intel | Scale: 1.0 | - |
| `ZS1_ZAS_Kl_X` | **ZS1_Ignition_starter_switch_terminal_X** | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `ZS1_ZAS_Kl_50` | **ZS1_ignition_starter_switch_terminal_50** | Bit 3, 1b, Intel | Scale: 1.0 | - |
| `ZS1_ZAS_KL_P` | **ZS1_Ignition_starter_switch_terminal_P**<br>*Note: 1 = Terminal P on (parking light position)* | Bit 4, 1b, Intel | Scale: 1.0 | - |

---

## Message: `mGateway_1` (0x351 / 849 Dec)
- **English Translation**: **m Gateway 1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GW1_FhzgGeschw_alt` | **GW1_Vehicle_Speed_​​Obsolete** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GW1_Rueckfahrlicht` | **GW1_reversing_light**<br>*Note: 1 = reversing light on* | Bit 1, 1b, Intel | Scale: 1.0 | `1`: Reversing light on |
| `GW1_FzgGeschw` | **GW1_vehicle_speed** | Bit 9, 15b, Intel | Scale: 0.01, Unit: 'Unit_KiloMeterPerHour' | `32725`: Undervoltage<br>`32708`: Init_PQ25_35_46<br>`32742`: Sensor error |
| `KKO_alt_mBSG_Kombi` | **KKO Obsolete m BSG station wagon** | Bit 63, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |

---

## Message: `mGW_Bremse_Getriebe` (0x359 / 857 Dec)
- **English Translation**: **m GW brake transmission**
- **Log Frequency**: 106 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GWB_Alt_FzgGeschw` | **GWB Obsolete vehicle speed** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_2_Bremse` | **GWB_Alt_2_Bremse** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_1_Bremse` | **GWB_Alt_1_Bremse** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_1_Getriebe` | **GWB_Alt_1_Getriebe** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_2_Getriebe` | **GWB Obsolete 2 gearboxes** | Bit 4, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_1_EPB` | **GWB Obsolete 1 EPB** | Bit 5, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_5_Bremse` | **GWB Obsolete 5 brake** | Bit 6, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_Alt_AWV_X` | **GWB Obsolete AWV X** | Bit 7, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWB_FzgGeschw_Quelle` | **GWB vehicle speed source** | Bit 8, 1b, Intel | Scale: 1.0 | `1`: ABS<br>`0`: kein_ABS |
| `GWB_FzgGeschw` | **GWB vehicle speed** | Bit 9, 15b, Intel | Scale: 0.01, Unit: 'Unit_KiloMeterPerHour' | `32725`: Undervoltage<br>`32708`: Init_PQ25_35_46<br>`32742`: Sensor error |
| `GWB_Wegimpulse` | **GWB path impulses** | Bit 24, 11b, Intel | Scale: 1.0 | - |
| `GWB_Wegimpuls_Status` | **GWB_Wegimpuls_Status** | Bit 35, 1b, Intel | Scale: 1.0 | `0`: Reset and no overflow<br>`1`: at least 1 overflow |
| `GWB_Wegimpulse_Fehler` | **GWB path pulses error** | Bit 39, 1b, Intel | Scale: 1.0 | `0`: Distance pulses OK<br>`1`: Mistake |
| `GWB_Impulszahl` | **GWB_Impulszahl** | Bit 40, 6b, Intel | Scale: 1.0 | - |
| `GWB_Alt_PLA_Status` | **GWB Obsolete PLA status** | Bit 46, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `PLS_Bremsleuchte` | **PLS brake light**<br>*Note: When braking the vehicle initiated by PLA, the brake light must be activated. This signal is the command to turn on the brake light to the control unit that switches it on.* | Bit 47, 1b, Intel | Scale: 1.0 | `1`: Brake light on<br>`0`: Brake light off |
| `GWB_TSP_aktiv` | **GWB TSP active** | Bit 48, 1b, Intel | Scale: 1.0 | `1`: Brake light on<br>`0`: no brake light requirement |
| `GWB_Notbremsung` | **GWB_Notbremsung** | Bit 49, 1b, Intel | Scale: 1.0 | `0`: keine_Notbremsung<br>`1`: Emergency braking detected |
| `GWB_ABS_Bremsung` | **GWB ABS braking**<br>*Note: Anti-lock braking system, bit also indicates pressure reduction (e.g. ESP has built up too much pressure or unbraked control on a railway hill)* | Bit 50, 1b, Intel | Scale: 1.0 | `0`: no ABS regulation<br>`1`: ABS regulation |
| `GWB_EPB_Status` | **GWB EPB status**<br>*Note: Gibt den Zustand der EPB-Aktuatoren an. Verknpfung mit Fehlerstatus; wenn z.B. 'Linke Seite Fehlerhaft' und 'Bremse geschlossen', dann ist nur die rechte Seite geschlossen. Das Bit gesetzt, wenn auf einer Seite Spannkraft aufgebaut wird. Wenn auf beiden * | Bit 51, 1b, Intel | Scale: 1.0 | `1`: Brake closed<br>`0`: Brake opened |
| `GWB_EPB_Bremslicht` | **GWB EPB brake light**<br>*Note: Brake light control during dynamic braking (only in the PQ46)* | Bit 52, 1b, Intel | Scale: 1.0 | `1`: A<br>`0`: out of |
| `GWB_Schlechtweg` | **GWB bad road** | Bit 53, 1b, Intel | Scale: 1.0 | `1`: Fading out<br>`0`: no blanking out |
| `GWB_Schlechtweg_Fehler` | **GWB bad road error** | Bit 54, 1b, Intel | Scale: 1.0 | `1`: invalid<br>`0`: valid |
| `GWB_Geschw_Ersatz` | **GWB speed replacement** | Bit 55, 1b, Intel | Scale: 1.0 | `1`: Replacement value<br>`0`: OK |
| `GWB_Schaltvorgang` | **GWB switching process**<br>*Note: Gearshift active (gearbox 1)* | Bit 56, 1b, Intel | Scale: 1.0 | `1`: Circuit is running<br>`0`: no circuit |
| `ANB_Teilbremsung_Freigabe` | **ANB partial braking release**<br>*Note: Release bit for partial braking to the ESP* | Bit 57, 1b, Intel | Scale: 1.0 | `1`: Partial braking released<br>`0`: Partial braking not released |
| `GWB_ESP_Eingriff` | **GWB ESP intervention** | Bit 58, 1b, Intel | Scale: 1.0 | `0`: kein_ESP_Eingriff<br>`1`: ESP intervention |
| `GWB_Shift_Lock` | **GWB Shift Lock** | Bit 59, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `GWB_Info_Waehlhebel` | **GWB info selector lever** | Bit 60, 4b, Intel | Scale: 1.0 | `12`: Pos S Automatic Sport<br>`6`: Item N<br>`7`: Pos R<br>`3`: Pos 3<br>`4`: Item 4<br>`1`: Item 1<br>`2`: Pos 2<br>`5`: Pos D Automatic<br>`13`: Pos L<br>`10`: Pos_Z1<br>`9`: Pos RSP Manual Sport<br>`0`: Zwischenstellung<br>`8`: Pos P Key Lock Release<br>`14`: Tipp_Gasse_Manual<br>`11`: Pos Z2<br>`15`: Mistake |

---

## Message: `mGW_Motor` (0x35B / 859 Dec)
- **English Translation**: **m GW engine**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GWM_Alt_1_Motor` | **GWM_Alt_1_Motor** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWM_Alt_2_Motor` | **GWM Obsolete 2 engine** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWM_Alt_5_Motor` | **GWM Obsolete 5 engine**<br>*Note: outdated signals from message motor 5* | Bit 2, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWM_Alt_Motor_Bremse` | **GWM Outdated Motor Brake** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWM_RME_Gehalt` | **GWM RME salary** | Bit 5, 3b, Intel | Scale: 12.5, Unit: 'Unit_PerCent' | `7`: Mistake |
| `GWM_Motordrehzahl` | **GWM engine speed**<br>*Note: Low Byte 3, High Byte 4; es wird der letzte aktuelle Mewert gesendet, d.h. die Zeit fr das letzte Arbeitsspiel (180 Grad KW beim 4 Zylinder) wird herangezogen; der Fehlerwert wird gesendet, wenn das Motor-steuergert keine plausible Drehzahlinformation * | Bit 8, 16b, Intel | Scale: 0.25, Unit: 'Unit_MinutInver' | `65280`: Mistake |
| `GWM_KuehlmittelTemp` | **GWM coolant temp** | Bit 24, 8b, Intel | Scale: 0.75, Offset: -48.0, Unit: 'Unit_DegreCelsi' | `0`: Init<br>`255`: Mistake |
| `GWM_Bremslicht_Schalter` | **GWM brake light switch**<br>*Note: Unfiltered raw signal (vehicle without BLS (e.g. Touareg GP): see 'Specification interface and behavior during driver braking for engine control unit and brake control unit in the Touareg GP', author M. Williges)* | Bit 32, 1b, Intel | Scale: 1.0 | `1`: Brake applied<br>`0`: kein_Bremsen |
| `GWM_Bremstest_Schalter` | **GWM brake test switch** | Bit 33, 1b, Intel | Scale: 1.0 | `0`: kein_Bremsen<br>`1`: Brake applied |
| `GWM_Fehl_KmittelTemp` | **GWM Missing Coolant Temp** | Bit 34, 1b, Intel | Scale: 1.0 | `0`: Temperature OK<br>`1`: Temperature not OK |
| `GWM_Kuppl_Schalter` | **GWM clutch switch** | Bit 35, 1b, Intel | Scale: 1.0 | `1`: Switch says engaged<br>`0`: Switch says disengaged |
| `GWM_Heissl_Vorwarn` | **GWM Heissl advance warning** | Bit 36, 1b, Intel | Scale: 1.0 | `0`: no warning<br>`1`: Advance warning |
| `GWM_Klimaabschaltung` | **GWM climate switch off**<br>*Note: Engine control unit switches off air conditioning compressor* | Bit 37, 1b, Intel | Scale: 1.0 | `1`: Climate compr<br>`0`: no requirement |
| `GWM_Kennfeldkuehlung` | **GWM map cooling**<br>*Note: The map cooling is installed in this vehicle and has no system errors* | Bit 38, 1b, Intel | Scale: 1.0 | `1`: ja<br>`0`: nein |
| `GWM_Komp_Leist_red` | **GWM Comp Power red**<br>*Note: Air conditioning compressor power reduction (currently not used in the PQ35/46)* | Bit 39, 1b, Intel | Scale: 1.0 | `1`: ja<br>`0`: nein |
| `GWM_KLuefter` | **GWM KLuefter** | Bit 40, 8b, Intel | Scale: 0.4, Unit: 'Unit_PerCent' | `0`: no requirement<br>`255`: Mistake |
| `GWM_Anl_Freigabe` | **GWM Anl release** | Bit 48, 1b, Intel | Scale: 1.0 | `1`: Launch release<br>`0`: Start not permitted |
| `GWM_Anl_Ausspuren` | **GWM Anl tracking** | Bit 49, 1b, Intel | Scale: 1.0 | `0`: Engine does not run stably<br>`1`: Disengage starter |
| `GWM_Interlock` | **GWM interlock** | Bit 50, 1b, Intel | Scale: 1.0 | `1`: Interlock activated<br>`0`: Interlock not activated |
| `GWM_TypStartSteu` | **GWM type start control** | Bit 51, 1b, Intel | Scale: 1.0 | `1`: Automatic start<br>`0`: Start BSG Kessy or driver |
| `GWM_Freig_Bremsanforderung` | **GWM release brake request** | Bit 52, 1b, Intel | Scale: 1.0 | `1`: Braking start released<br>`0`: Brake start not released |
| `GWM_Vorgluehen` | **GWM pre-heating**<br>*Note: Diesel pilot light and diesel system light* | Bit 53, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `GWM_GRA_Status` | **GWM GRA status** | Bit 54, 2b, Intel | Scale: 1.0 | `2`: overloads lamp on<br>`0`: ADR GRA<br>`3`: ADR not released<br>`1`: activates lamp on |
| `GWM_KVerbrauch` | **GWM K consumption** | Bit 56, 7b, Intel | Scale: 256.0, Unit: 'Unit_MicroLiter' | - |
| `GWM_Ueberl_KV` | **GWM Ueberl KV**<br>*Note: The engine control unit's internal consumption meter overflowed at least once. This bit is used to detect that the engine control unit is starting up from the reset state* | Bit 63, 1b, Intel | Scale: 1.0 | `1`: defected at least once<br>`0`: no overflow |

---

## Message: `mRadio_1_neu` (0x363 / 867 Dec)
- **English Translation**: **mRadio_1_neu**
- **Log Frequency**: 171 occurrences
- **Sender**: `Vector__XXX` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `RA1_DSP_Zeichen_1` | **RA1_DSP_character_1** | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_2` | **RA1_DSP_sign_2** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_3` | **RA1_DSP_sign_3**<br>*Note: Display data 3rd character line 1* | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_4` | **RA1_DSP_sign_4**<br>*Note: Display data 4. Character line 1* | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_5` | **RA1_DSP_sign_5** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_6` | **RA1_DSP_sign_6** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_7` | **RA1_DSP_sign_7**<br>*Note: Display data 7. Character line 1* | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `RA1_DSP_Zeichen_8` | **RA1_DSP_Zeichen_8**<br>*Note: Display data 8. Character line 1* | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mRadio_2_neu` (0x365 / 869 Dec)
- **English Translation**: **m Radio 2 new**
- **Log Frequency**: 158 occurrences
- **Sender**: `Vector__XXX` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `RA2_DSP_Zeichen_9` | **RA2_DSP_Zeichen_9** | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_10` | **RA2_DSP_sign_10** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_11` | **RA2_DSP_Zeichen_11** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_12` | **RA2_DSP_sign_12** | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_13` | **RA2_DSP_sign_13** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_14` | **RA2_DSP_character_14** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_15` | **RA2_DSP_character_15**<br>*Note: Display data 7th character line 2* | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `RA2_DSP_Zeichen_16` | **RA2_DSP_character_16**<br>*Note: Display data 8th character line 2* | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mLenkwinkel_1` (0x3C3 / 963 Dec)
- **English Translation**: **m steering angle 1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `LW1_Lenkradwinkel` | **LW1_Lenkradwinkel** | Bit 0, 15b, Intel | Scale: 0.04375, Unit: 'Unit_DegreOfArc' | - |
| `LW1_Vorzeichen` | **LW1_sign** | Bit 15, 1b, Intel | Scale: 1.0 | `1`: negative sign<br>`0`: positive sign |
| `LW1_Geschwindigkeit` | **LW1_speed** | Bit 16, 15b, Intel | Scale: 0.04375, Unit: 'Unit_DegreOfArcPerSecond' | - |
| `LW1_Geschw_Vorzeichen` | **LW1_speed_sign**<br>*Note: Steering wheel angle speed sign* | Bit 31, 1b, Intel | Scale: 1.0 | `1`: negative sign<br>`0`: positive sign |
| `LW1_ID` | **LW1_ID** | Bit 32, 8b, Intel | Scale: 1.0 | `128`: calibrated<br>`0`: not yet calibrated |
| `LW1_Quelle_Init` | **LW1_Source_Init** | Bit 40, 1b, Intel | Scale: 1.0 | `0`: Brake 3<br>`1`: EPS Bit |
| `LW1_Int_Status` | **LW1_Int_Status** | Bit 41, 2b, Intel | Scale: 1.0 | `2`: sporadischer_Fehler<br>`3`: permanent error<br>`1`: no init<br>`0`: OK |
| `LW1_KL30_Ausfall` | **LW1_KL30_failure** | Bit 43, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: no init s |
| `LW1_Zaehler` | **LW1_counter**<br>*Note: freilaufender Botschaftszhler* | Bit 44, 4b, Intel | Scale: 1.0 | - |
| `LW1_CRC8CHK` | **LW1_CRC8_CHK** | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `LW1_Pruefsumme` | **LW1_checksum** | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mClima_1` (0x3E1 / 993 Dec)
- **English Translation**: **m Climate 1**
- **Log Frequency**: 108 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN comfort

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `CL1_Drehzahlanhebung` | **CL1_speed_increase** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: elevation<br>`0`: keine_Anhebung |
| `CL1_Zuheizer` | **CL1_Zuheizer** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: A<br>`0`: out of |
| `CL1_HzgHeckscheibe` | **CL1_Hzg_rear_window** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: A<br>`0`: out of |
| `CL1_HzgFrontscheibe` | **CL1_Hzg_windscreen** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: A<br>`0`: out of |
| `CL1_Kompressor` | **CL1_compressor**<br>*Note: 1 = Kompressor ein, Zustand incl. 140ms Vorsteuerung, Info an das MSG: Kompressor EIN, PQ34_lang: Anforderung an das MSG: Kompressor einschalten* | Bit 4, 1b, Intel | Scale: 1.0 | `1`: A<br>`0`: out of |
| `CL1_Heizung_aus` | **CL1_heating_off** | Bit 5, 1b, Intel | Scale: 1.0 | `0`: Heating output<br>`1`: no heating output |
| `CL1_Kompressormoment_alt` | **CL1_Compressor_torque_Obsolete** | Bit 6, 1b, Intel | Scale: 1.0 | `0`: aktuell<br>`1`: veraltet |
| `CL1_Kaeltemitteldruck_alt` | **CL1_Refrigerant_Pressure_Obsolete** | Bit 7, 1b, Intel | Scale: 1.0 | `0`: aktuell<br>`1`: veraltet |
| `CL1_AussenTemp` | **CL1_outside_temp** | Bit 8, 8b, Intel | Scale: 0.5, Offset: -50.0, Unit: 'Unit_DegreCelsi' | `255`: Mistake |
| `CL1_KaeltemittelDruck` | **CL1_refrigerant_pressure** | Bit 16, 8b, Intel | Scale: 0.2, Unit: 'Unit_Bar' | `255`: Mistake |
| `CL1_Last_Kompressor` | **CL1_Last_Kompressor** | Bit 24, 8b, Intel | Scale: 0.25, Unit: 'Unit_NewtoMeter' | `255`: Mistake |
| `CL1_Geblaeselast` | **CL1_fan_load**<br>*Note: Lastinfo: Geblaeseansteuerung* | Bit 32, 8b, Intel | Scale: 0.4, Unit: 'Unit_PerCent' | `255`: Mistake |
| `CL1_Strg_Kluefter` | **CL1_control_Kluefter**<br>*Note: Control of the cooler fan in percent* | Bit 40, 8b, Intel | Scale: 0.4, Unit: 'Unit_PerCent' | `255`: Mistake |
| `CL1_Temp_in_F` | **CL1_temperature_in_F**<br>*Note: 1 = Air conditioning displays temperature in Fahrenheit, temperature on the bus in C!!* | Bit 48, 1b, Intel | Scale: 1.0 | `1`: Fahrenheit<br>`0`: Grade C |
| `CL1_AC_Schalter` | **CL1_AC_switch** | Bit 49, 1b, Intel | Scale: 1.0 | `1`: on pressed or on<br>`0`: out of |
| `CL1_WAPU_Zuschaltung` | **CL1_WAPU_connection** | Bit 50, 1b, Intel | Scale: 1.0 | `1`: WAPU OFF<br>`0`: WAPU ON |
| `CL1_Restwaerme` | **CL1_residual_heat**<br>*Note: 1 = residual heat function is activated, status information, i.e. fan load is present* | Bit 51, 1b, Intel | Scale: 1.0 | `0`: not activated<br>`1`: aktiviert |
| `CL1_PTC_Clima` | **CL1_PTC_Climate** | Bit 52, 3b, Intel | Scale: 25.0, Unit: 'Unit_PerCent' | - |
| `CL1_KD_Fehler` | **CL1_KD_error**<br>*Note: 1 = at least 1 customer service error is entered in the error memory* | Bit 55, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `KL_Thermomanagement` | **Terminal thermal management**<br>*Note: Stufen des Thermomanagements* | Bit 56, 2b, Intel | Scale: 1.0 | `3`: full release TMM<br>`0`: no release TMM<br>`2`: mittlere_Freigabe_TMM<br>`1`: small release TMM |

---

## Message: `mClima_2` (0x3E3 / 995 Dec)
- **English Translation**: **m Climate 2**
- **Log Frequency**: 14 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `CL2_Sonne_links` | **CL2_Sun_left** | Bit 0, 8b, Intel | Scale: 4.0, Unit: 'Unit_WattPerMeterSquar' | `255`: Mistake |
| `CL2_Sonne_rechts` | **CL2_sun_right** | Bit 8, 8b, Intel | Scale: 4.0, Unit: 'Unit_WattPerMeterSquar' | `255`: Mistake |
| `CL2_InnenTemp` | **CL2_Indoor_Temp** | Bit 16, 8b, Intel | Scale: 0.5, Offset: -50.0, Unit: 'Unit_DegreCelsi' | `255`: Mistake |
| `CL2_SitzH_links` | **CL2_SitzH_links** | Bit 24, 3b, Intel | Scale: 1.0 | - |
| `CL2_SitzH_rechts` | **CL2_seat_H_right** | Bit 27, 3b, Intel | Scale: 1.0 | - |
| `CL2_StSt_Info` | **CL2_StSt_Info**<br>*Note: Stop enable/start request for the start-stop coordinator* | Bit 30, 2b, Intel | Scale: 1.0 | `3`: System error<br>`0`: engine running n<br>`1`: Stop prohibition motor start nn<br>`2`: Motor start necessary |
| `CL2_SH` | **CL2_SH**<br>*Note: 1 = Standheizung ein, 0 = Standheizung aus* | Bit 32, 1b, Intel | Scale: 1.0 | - |
| `CL2_SL_LED` | **CL2_SL_LED** | Bit 33, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `CL2_Geblaese_plus` | **CL2_blower_plus** | Bit 34, 1b, Intel | Scale: 1.0 | - |
| `CL2_Umluft_Taste` | **CL2_recirculation_button** | Bit 39, 1b, Intel | Scale: 1.0 | - |
| `CL2_Solltemperatur` | **CL2_target_temperature** | Bit 40, 8b, Intel | Scale: 1.0 | `255`: Mistake |
| `CL2_Vorgabe_KWTemp` | **CL2_specification_KWTemp** | Bit 56, 8b, Intel | Scale: 0.75, Offset: -48.0, Unit: 'Unit_DegreCelsi' | `255`: Mistake |

---

## Message: `mNM_Gateway_I` (0x42B / 1067 Dec)
- **English Translation**: **m NM Gateway I**
- **Log Frequency**: 115 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 6

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `NMGW_I_Receiver` | **NMGW I receiver**<br>*Note: SG address* | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `NMGW_I_CmdRing` | **NMGW I Cmd Ring**<br>*Note: Ring message* | Bit 8, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_CmdAlive` | **NMGW I Cmd Alive**<br>*Note: Alive message* | Bit 9, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_CmdLimpHome` | **NMGW I Cmd Limp Home**<br>*Note: Limp Home Message* | Bit 10, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_SleepInd` | **NMGW I Sleep Ind**<br>*Note: Bus Sleep Indication* | Bit 12, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_SleepAck` | **NMGW_I_SleepAck**<br>*Note: Bus Sleep Acknowledge* | Bit 13, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Kl_30_Reset` | **NMGW I terminal 30 reset**<br>*Note: Cause of alarm: Terminal 30 reset* | Bit 20, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Fkt_Nachlauf` | **NMGW I Overrun function**<br>*Note: Cause of alarm: Expiration of timer function overrun* | Bit 21, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_NWake` | **NMGW I NWake**<br>*Note: Wake up cause: NWake input* | Bit 22, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_CAN` | **NMGW_I_CAN**<br>*Note: Wake-up cause: CAN* | Bit 23, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Wake_Up_Ltg` | **NMGW I Wake Up line**<br>*Note: Wake-up cause: Combi wake-up line* | Bit 24, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Komfort_CAN` | **NMGW I Comfort CAN**<br>*Note: Wake up by comfort CAN* | Bit 25, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Info_CAN` | **NMGW_I_Info_CAN**<br>*Note: Wecken durch Infotainment CAN* | Bit 26, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Kl_15` | **NMGW I terminal 15**<br>*Note: Wake up via terminal 15* | Bit 30, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_Diag_CAN` | **NMGW I Diag CAN**<br>*Note: Wake up via diagnostic CAN* | Bit 31, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_LIN1` | **NMGW I LIN1**<br>*Note: Wake up by LIN#1* | Bit 32, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_LIN2` | **NMGW I LIN2**<br>*Note: Wake up by LIN#2* | Bit 33, 1b, Intel | Scale: 1.0 | - |
| `NMGW_I_WakeUp2` | **NMGW I Wake Up2**<br>*Note: n.n.* | Bit 34, 6b, Intel | Scale: 1.0 | - |
| `NMGW_I_WakeUp3` | **NMGW I Wake Up3**<br>*Note: n.n.* | Bit 40, 8b, Intel | Scale: 1.0 | - |

---

## Message: `NWM_RNS` (0x436 / 1078 Dec)
- **English Translation**: **NWM RNA**
- **Log Frequency**: 114 occurrences
- **Sender**: `RNS_300_NF` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `NWM_RNS_Receiver` | **NWM RNS Receiver**<br>*Note: SG address* | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `NWM_RNS_CmdRing` | **NWM_RNS_CmdRing**<br>*Note: Ring message* | Bit 8, 1b, Intel | Scale: 1.0 | `1`: Cmd Ring |
| `NWM_RNS_CmdAlive` | **NWM RNS Cmd Alive**<br>*Note: Alive message* | Bit 9, 1b, Intel | Scale: 1.0 | `1`: Cmd Alive |
| `NWM_RNS_CmdLimpHome` | **NWM RNS Cmd Limp Home**<br>*Note: Limp Home Message* | Bit 10, 1b, Intel | Scale: 1.0 | `1`: Cmd Limp Home |
| `NWM_RNS_SleepInd` | **NWM RNS Sleep Ind**<br>*Note: Bus sleep indication* | Bit 12, 1b, Intel | Scale: 1.0 | `1`: Sleep Ind |
| `NWM_RNS_SleepAck` | **NWM RNS Sleep Ack**<br>*Note: Bus sleep acknowledge* | Bit 13, 1b, Intel | Scale: 1.0 | `1`: Sleep Ack |
| `NWM_RNS_Per_WakeUp` | **NWM RNS Per Wake Up** | Bit 16, 5b, Intel | Scale: 1.0 | `3`: KL15_HW<br>`4`: KL30_Reset<br>`8`: Eject<br>`7`: RTC<br>`5`: ON Tipper<br>`1`: CAN<br>`9`: CD insert<br>`0`: Functional wakeup<br>`2`: P Wake Up<br>`6`: Telephone mute |
| `NWM_RNS_Fkt_WakeUp` | **NWM RNS wake-up function** | Bit 21, 3b, Intel | Scale: 1.0 | `3`: Telephone mute<br>`1`: Dimmung<br>`2`: Comm Req<br>`0`: P Wake Up |
| `NWM_RNS_Klemme_15` | **NWM RNS terminal 15** | Bit 24, 1b, Intel | Scale: 1.0 | `1`: KL15 |
| `NWM_RNS_Diagnose` | **NWM RNA diagnosis** | Bit 25, 1b, Intel | Scale: 1.0 | `1`: diagnosis |
| `NWM_RNS_MindestAktivZeit` | **NWM RNS Minimum Active Time** | Bit 26, 1b, Intel | Scale: 1.0 | `1`: Minimum active time |
| `NWM_RNS_Ursache_4` | **NWM RNA cause 4** | Bit 27, 1b, Intel | Scale: 1.0 | `1`: Radio BAP Comm |
| `NWM_RNS_Ursache_5` | **NWM_RNS_Ursache_5** | Bit 28, 1b, Intel | Scale: 1.0 | `1`: TP20_RNA |
| `NWM_RNS_Ursache_6` | **NWM RNA cause 6** | Bit 29, 1b, Intel | Scale: 1.0 | `1`: TP20_RADIO |
| `NWM_RNS_Ursache_7` | **NWM RNA cause 7** | Bit 30, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Ursache_8` | **NWM RNA cause 8** | Bit 31, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_1` | **NWM RNS wake 1**<br>*Note: 1 = internal overrun before wakeup 1* | Bit 32, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_2` | **NWM RNS wake 2** | Bit 33, 1b, Intel | Scale: 1.0 | `1`: Dimmung |
| `NWM_RNS_Nachlauf_3` | **NWM RNS wake 3** | Bit 34, 1b, Intel | Scale: 1.0 | `1`: Telephone mute |
| `NWM_RNS_Nachlauf_4` | **NWM RNS wake 4**<br>*Note: 1 = interner Nachlauf vor Wakeup 4* | Bit 35, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_5` | **NWM RNS wake 5**<br>*Note: 1 = internal overrun before wakeup 5* | Bit 36, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_6` | **NWM RNS wake 6**<br>*Note: 1 = internal overrun before wakeup 6* | Bit 37, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_7` | **NWM RNS wake 7**<br>*Note: 1 = internal overrun before wakeup 7* | Bit 38, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Nachlauf_8` | **NWM_RNS_Nachlauf_8**<br>*Note: 1 = internal overrun before wakeup 8* | Bit 39, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_TimeOut_Fehler` | **NWM RNS Time Out Error**<br>*Note: 1 = Active timeout error memory entry* | Bit 41, 1b, Intel | Scale: 1.0 | `1`: Time Out FSP |
| `NWM_RNS_CAN_Diag_deaktiv` | **NWM RNS CAN Diag deactivated**<br>*Note: 1 = No CAN bus related self-diagnosis* | Bit 42, 1b, Intel | Scale: 1.0 | `1`: Diag inactive |
| `NWM_RNS_KompSchutz` | **NWM RNS comp protection**<br>*Note: 1 = Function restriction due to component protection active* | Bit 43, 1b, Intel | Scale: 1.0 | `1`: Component protection |
| `NWM_RNS_Mute_Mode` | **NWM RNS Mute Mode**<br>*Note: 1 = Function restriction due to mute mode active, only VW* | Bit 44, 1b, Intel | Scale: 1.0 | `1`: Mute fashion |
| `NWM_RNS_Transport_Mode` | **NWM RNS transport mode**<br>*Note: 1 = Function restriction due to transport mode active* | Bit 45, 1b, Intel | Scale: 1.0 | `1`: Transport fashion |
| `NWM_RNS_Abschaltst_aktiv` | **NWM RNS shutdown active**<br>*Note: 1 = Function shutdown due to shutdown switching stage* | Bit 46, 1b, Intel | Scale: 1.0 | `1`: Shutdown level |
| `NWM_RNS_Eindraht_Fehler` | **NWM RNS single wire error**<br>*Note: 1 = Single-wire operation detected* | Bit 47, 1b, Intel | Scale: 1.0 | `1`: Single wire |
| `NWM_RNS_Anf_1` | **NWM_RNS_Anf_1**<br>*Note: for future requirements* | Bit 48, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_2` | **NWM RNS Beginn 2** | Bit 49, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_3` | **NWM RNS Beginn 3** | Bit 50, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_4` | **NWM_RNS_Anf_4** | Bit 51, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_5` | **NWM RNS Beginn 5** | Bit 52, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_6` | **NWM RNS beginning 6** | Bit 53, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_7` | **NWM_RNS_Anf_7** | Bit 54, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_8` | **NWM RNS beginning 8** | Bit 55, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_9` | **NWM RNS beginning 9**<br>*Note: for future requirements 2* | Bit 56, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_10` | **NWM RNS beginning 10** | Bit 57, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_11` | **NWM RNS beginning 11** | Bit 58, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_12` | **NWM RNS beginning 12th** | Bit 59, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_13` | **NWM RNS beginning 13th** | Bit 60, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_14` | **NWM RNS beginning 14** | Bit 61, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_15` | **NWM RNS beginning 15** | Bit 62, 1b, Intel | Scale: 1.0 | - |
| `NWM_RNS_Anf_16` | **NWM RNS beginning 16** | Bit 63, 1b, Intel | Scale: 1.0 | - |

---

## Message: `mBSG_Kombi` (0x470 / 1136 Dec)
- **English Translation**: **m BSG station wagon**
- **Log Frequency**: 214 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `BSK_Blk_links` | **BSK turn signal left** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: Indicator light indicator L on |
| `BSK_Blk_rechts` | **BSK_Blk_rechts** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: Indicator light indicator R on |
| `BSK_Anhaenger` | **BSK trailer** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: Trailer flashing |
| `BSK_Warnblinker` | **BSK hazard warning lights** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Hazard warning status on |
| `BSK_DWA_Akku` | **BSK_DWA_Akku**<br>*Note: DWA battery empty indicator light* | Bit 4, 1b, Intel | Scale: 1.0 | `0`: Battery OK<br>`1`: DWA battery empty |
| `BSK_Rueckfahrlicht` | **BSK_Rueckfahrlicht**<br>*Note: 1 = reversing light on* | Bit 5, 1b, Intel | Scale: 1.0 | `1`: Reversing light on |
| `BSK_Sammelfehler_AKI` | **BSK collective error AKI** | Bit 6, 1b, Intel | Scale: 1.0 | `0`: no collection error<br>`1`: Collection error |
| `BSK_Ladekontrollampe` | **BSK charging indicator light** | Bit 7, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Terminal L active |
| `BSK_FT_geoeffnet` | **BSK_FT_geoeffnet**<br>*Note: Status of the driver's door rotary latch* | Bit 8, 1b, Intel | Scale: 1.0 | `0`: Door closed<br>`1`: Door open |
| `BSK_BT_geoeffnet` | **BSK BT open**<br>*Note: Status of the passenger door rotary latch* | Bit 9, 1b, Intel | Scale: 1.0 | `0`: Door closed<br>`1`: Door open |
| `BSK_HL_geoeffnet` | **BSK HL opened**<br>*Note: Status of the rear left door rotary latch* | Bit 10, 1b, Intel | Scale: 1.0 | `0`: Door closed<br>`1`: Door open |
| `BSK_HR_geoeffnet` | **BSK HR opened**<br>*Note: Status of the rear right door rotary latch* | Bit 11, 1b, Intel | Scale: 1.0 | `0`: Door closed<br>`1`: Door open |
| `BSK_MH_geoeffnet` | **BSK MH open** | Bit 12, 1b, Intel | Scale: 1.0 | `0`: Haube_geschlossen<br>`1`: Haube_offen |
| `BSK_HD_Hauptraste` | **BSK_HD_Hauptraste**<br>*Note: Trunk lid main catch status* | Bit 13, 1b, Intel | Scale: 1.0 | `0`: closed<br>`1`: main rest |
| `BSK_HD_Vorraste` | **BSK HD pre-detent**<br>*Note: Boot lid pre-latch status* | Bit 14, 1b, Intel | Scale: 1.0 | `0`: closed<br>`1`: Vorraste |
| `BSK_Unterspannung` | **BSK_Unterspannung**<br>*Note: Undervoltage, signals no longer all ok.* | Bit 15, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: Undervoltage |
| `BSK_Display` | **BSK display** | Bit 16, 7b, Intel | Scale: 1.0, Unit: 'Unit_PerCent' | `127`: Mistake |
| `BSK_Display_def` | **BSK display def** | Bit 23, 1b, Intel | Scale: 1.0 | `0`: Terminal 58d OK<br>`1`: Kl_58d_n_i_O |
| `BSK_Klemme_58t` | **BSK clamp 58t** | Bit 24, 7b, Intel | Scale: 1.0, Unit: 'Unit_PerCent' | `127`: Mistake |
| `BSK_Klemme_58t_def` | **BSK terminal 58t def** | Bit 31, 1b, Intel | Scale: 1.0 | `1`: Terminal 58t not OK<br>`0`: Terminal 58t OK |
| `BSK_Interlock` | **BSK interlock** | Bit 32, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `BSK_Buzzer` | **BSK Buzzer**<br>*Note: In Fahrzeugen mit separaten Tagfahrleuchten kann durch eine Bedienfolge von Blinker links (deaktivieren) / Blinker rechts (aktivieren), Lichthupe ein und Kl.15 ein das Tagfahrlicht aktiviert oder deaktiviert werden. Als Quittierung fr diese Aktivierung/D* | Bit 33, 1b, Intel | Scale: 1.0 | `0`: no gong<br>`1`: Control the gong |
| `BSK_Ruecks_HL_verriegelt` | **BSK Ruecks HL locked** | Bit 34, 1b, Intel | Scale: 1.0 | `1`: not locked<br>`0`: locked |
| `BSK_Ruecks_HR_verriegelt` | **BSK Ruecks HR locked** | Bit 35, 1b, Intel | Scale: 1.0 | `0`: locked<br>`1`: not locked |
| `BSK_Def_Lampe` | **BSK_Def_Lampe** | Bit 36, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: defect |
| `BSK_NSL_LED_Pfad` | **BSK NSL LED path** | Bit 37, 1b, Intel | Scale: 1.0 | `1`: CAN<br>`0`: wire |
| `BSK_AFL_defekt` | **BSK AFL defective** | Bit 38, 1b, Intel | Scale: 1.0 | `1`: defect<br>`0`: OK |
| `BSK_BSG_defekt` | **BSK BSG defective** | Bit 39, 1b, Intel | Scale: 1.0 | `1`: defect<br>`0`: OK |
| `BSK_Standlicht` | **BSK parking light** | Bit 40, 1b, Intel | Scale: 1.0 | `1`: Kl58 |
| `BSK_Parklicht_links` | **BSK parking light on the left** | Bit 41, 1b, Intel | Scale: 1.0 | `1`: Parking light L on |
| `BSK_Parklicht_rechts` | **BSK_Parklicht_rechts** | Bit 42, 1b, Intel | Scale: 1.0 | `1`: Parking light R on |
| `BSK_Abblendlicht` | **BSK low beam** | Bit 43, 1b, Intel | Scale: 1.0 | `1`: Kl56b_ein<br>`0`: out of |
| `BSK_Nebellicht` | **BSK fog light** | Bit 44, 1b, Intel | Scale: 1.0 | `1`: Kl83a<br>`0`: out of |
| `BSK_Heckscheibenhzg` | **BSK rear window heating**<br>*Note: The status of the rear window heating control is reported for display in the station wagon.* | Bit 45, 1b, Intel | Scale: 1.0 | - |
| `BSK_Tankklappe` | **BSK_Tankklappe**<br>*Note: A text 'tank flap open' or the CAR outline symbol is displayed in the station wagon. The right sliding door goes into local 'E-Ki Si mode' as long as the fuel filler flap is open.* | Bit 46, 1b, Intel | Scale: 1.0 | `0`: Fuel filler flap closed<br>`1`: Fuel filler flap open |
| `BSK_FFB_Bat` | **BSK FFB Bat**<br>*Note: Text display battery status FFB* | Bit 47, 1b, Intel | Scale: 1.0 | `0`: no text<br>`1`: text |
| `BSK_FLA_Soft_LED` | **BSK FLA Soft LED**<br>*Note: 1 = FLA active, display in the combination (soft LED)* | Bit 48, 1b, Intel | Scale: 1.0 | `0`: inactive<br>`1`: active |
| `BSK_FLA_Sensor_blockiert` | **BSK_FLA_Sensor_blockiert** | Bit 49, 1b, Intel | Scale: 1.0 | `1`: Sensor blocked<br>`0`: Sensor OK |
| `BSK_FLA_Defekt` | **BSK FLA defect**<br>*Note: 1 = FLA defective* | Bit 50, 1b, Intel | Scale: 1.0 | `1`: System defective<br>`0`: System_iO |
| `BCM_Remotestart_Betrieb` | **BCM_Remotestart_Betrieb** | Bit 55, 1b, Intel | Scale: 1.0 | `1`: RS_Betrieb<br>`0`: no RS operation |
| `BSK_Ruhespannung` | **BSK rest voltage**<br>*Note: In transport mode, the resting battery voltage in the station wagon is displayed at the position of the total distance traveled.* | Bit 56, 5b, Intel | Scale: 0.1, Offset: 10.5, Unit: 'Unit_Volt' | `0`: Init<br>`31`: Mistake |
| `BSK_Nebelschlusslicht` | **BSK rear fog light** | Bit 61, 1b, Intel | Scale: 1.0 | `1`: Kl83b<br>`0`: out of |
| `BSK_Fernlicht` | **BSK high beam** | Bit 62, 1b, Intel | Scale: 1.0 | `1`: Kl56a<br>`0`: out of |
| `BSK_Tagfahrlicht` | **BSK daytime running lights**<br>*Note: 1 = daytime running lights are switched on* | Bit 63, 1b, Intel | Scale: 1.0 | `1`: Daytime running lights on |

---

## Message: `mGW_KOM_INF` (0x523 / 1315 Dec)
- **English Translation**: **m GW COM INF**
- **Log Frequency**: 53 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GWI_alt_ZKE_4` | **GWI Obsolete ZKE 4**<br>*Note: 1 = Message m ZKE 4 not received (>400 ms)* | Bit 0, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_alt_ZKE_3` | **GWI_alt_ZKE_3** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_alt_Kombi_1` | **GWI Obsolete Combi 1** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_res3` | **GWI res3** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_res4` | **GWI res4** | Bit 4, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_res5` | **GWI res5** | Bit 5, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_res6` | **GWI res6** | Bit 6, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_res7` | **GWI_res7** | Bit 7, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWI_Status_Verdeck` | **GWI status top**<br>*Note: Signal indicates the status of the manual canopy.* | Bit 8, 1b, Intel | Scale: 1.0 | `0`: closed<br>`1`: open |
| `GWI_ZKE4_Zusatzfkt` | **GWI_ZKE4_Zusatzfkt**<br>*Note: Zusatzfunktionen des Komfortsteuergerts sind verfuegbar, wenn DLC von mZKE_4 >6* | Bit 15, 1b, Intel | Scale: 1.0 | - |
| `GWI_Blk_ZV_auf` | **GWI indicator ZV on** | Bit 16, 1b, Intel | Scale: 1.0 | - |
| `GWI_Blk_ZV_zu` | **GWI indicator ZV closed** | Bit 17, 1b, Intel | Scale: 1.0 | - |
| `GWI_Blk_DW_ein` | **GWI indicator DW on** | Bit 18, 1b, Intel | Scale: 1.0 | - |
| `GWI_DWA_Alarm` | **GWI DWA alarm** | Bit 19, 1b, Intel | Scale: 1.0 | - |
| `GWI_verriegelt_int` | **GWI locks internally** | Bit 20, 1b, Intel | Scale: 1.0 | - |
| `GWI_verriegelt_ext` | **GWI locks ext** | Bit 21, 1b, Intel | Scale: 1.0 | - |
| `GWI_gesaeft_ext` | **GWI juiced ext** | Bit 22, 1b, Intel | Scale: 1.0 | - |
| `KB1_angez_kmh` | **KB1_number_of_kmh** | Bit 32, 10b, Intel | Scale: 0.32, Unit: 'Unit_KiloMeterPerHour' | `1020`: Mistake |

---

## Message: `mGW_Kombi` (0x527 / 1319 Dec)
- **English Translation**: **m GW station wagon**
- **Log Frequency**: 53 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GWK_Alt_3_Kombi` | **GWK Obsolete 3 station wagon** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWK_Alt_2_Kombi` | **GWK Obsolete 2 station wagon**<br>*Note: outdated signals from embassy station wagon 2* | Bit 1, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWK_Alt_1_Kombi` | **GWK Obsolete 1 station wagon** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GWK_Reifenumfang_empf` | **GWK tire circumference recommended** | Bit 4, 1b, Intel | Scale: 1.0 | `0`: Content not received<br>`1`: Currently received |
| `GWK_FzgGeschw_Quelle` | **GWK vehicle speed source** | Bit 8, 1b, Intel | Scale: 1.0 | `0`: Speedometer sensor<br>`1`: ABS signals |
| `GWK_FzgGeschw` | **GWK vehicle speed** | Bit 9, 15b, Intel | Scale: 0.01, Unit: 'Unit_KiloMeterPerHour' | - |
| `GWK_Umfang_Reifen` | **GWK circumference tires** | Bit 28, 12b, Intel | Scale: 1.0 | - |
| `GWK_AussenTemp_gefiltert` | **GWK outside temp filtered** | Bit 40, 8b, Intel | Scale: 0.5, Offset: -50.0, Unit: 'Unit_DegreCelsi' | `255`: Mistake |
| `GWK_AussenTemp_ungefiltert` | **GWK outside temp unfiltered** | Bit 48, 8b, Intel | Scale: 0.5, Offset: -50.0, Unit: 'Unit_DegreCelsi' | `255`: Mistake |
| `GWK_AussenTemp_Fehler` | **GWK outside temp error** | Bit 56, 1b, Intel | Scale: 1.0 | `1`: OK<br>`0`: OK |
| `GWK_Warn_Heiss` | **GWK_Warn_Heiss** | Bit 57, 1b, Intel | Scale: 1.0 | `1`: warning<br>`0`: no warning |
| `GWK_Passiv_Autolock` | **GWK passive autolock**<br>*Note: 1 = Umschaltanforderung vom Kombi: 'Passiv Autolock / Autounlock'* | Bit 58, 1b, Intel | Scale: 1.0 | `0`: inactive<br>`1`: active |
| `GWK_WFS_Schl_Ort` | **GWK WFS Schl Ort**<br>*Note: Key recognition via reading coil or keyless* | Bit 59, 1b, Intel | Scale: 1.0 | `0`: keyless<br>`1`: Lesespule |
| `KB1_Lenkh_Lampe` | **KB1_steering_lamp**<br>*Note: Power steering safety lamp has been turned on* | Bit 60, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |

---

## Message: `mLicht_1_alt` (0x531 / 1329 Dec)
- **English Translation**: **m Light 1 Obsolete**
- **Log Frequency**: 214 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 4

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `LIA_Standlicht` | **LIA parking light** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: Kl58 |
| `LIA_Abblendlicht` | **LIA_Abblendlicht** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: Kl56b_ein<br>`0`: out of |
| `LIA_Fernlicht` | **LIA high beam** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: Kl56a<br>`0`: out of |
| `LIA_Nebellicht` | **LIA fog light** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Kl83a<br>`0`: out of |
| `LIA_Nebelschluss` | **LIA rear fog** | Bit 4, 1b, Intel | Scale: 1.0 | `1`: Kl83b<br>`0`: out of |
| `LIA_Rueckfahrlicht` | **LIA reversing light**<br>*Note: 1 = reversing light on* | Bit 5, 1b, Intel | Scale: 1.0 | `1`: Reversing light on |
| `LIA_Parklicht_links` | **LIA parking light on the left** | Bit 6, 1b, Intel | Scale: 1.0 | `1`: Parking light L on |
| `LIA_Parklicht_rechts` | **LIA parking light on the right** | Bit 7, 1b, Intel | Scale: 1.0 | `1`: Parking light R on |
| `LIA_Blk_links` | **LIA indicator left** | Bit 8, 1b, Intel | Scale: 1.0 | `1`: Flashing lamp L on |
| `LIA_Blk_rechts` | **LIA indicator right** | Bit 9, 1b, Intel | Scale: 1.0 | `1`: Flashing lamp R on |
| `LIA_Anhaenger` | **LIA trailer** | Bit 10, 1b, Intel | Scale: 1.0 | `1`: Trailer flashing |
| `LIA_Warnblink` | **LIA hazard warning light** | Bit 11, 1b, Intel | Scale: 1.0 | `1`: Warning lights on |
| `LIA_BLK_Frequenz` | **LIA indicator frequency**<br>*Note: 1 = Blinkfrequenz der Blinker* | Bit 12, 1b, Intel | Scale: 1.0 | `1`: Blink freq on |
| `LIA_AFL_Schalter` | **LIA AFL switch**<br>*Note: 1 = Switch in assistant driving light position* | Bit 13, 1b, Intel | Scale: 1.0 | `1`: AFL switch on<br>`0`: out of |
| `LIA_Bremslicht` | **LIA brake light**<br>*Note: 1 = Brake light switched on* | Bit 14, 1b, Intel | Scale: 1.0 | `1`: Brake light on<br>`0`: out of |
| `LIA_Tagesfahrlicht` | **LIA daytime running lights**<br>*Note: 1 = daytime running lights are switched on* | Bit 15, 1b, Intel | Scale: 1.0 | `1`: Daytime running lights on |
| `LIA_Blk_L_Kontrolle` | **LIA indicator L control** | Bit 16, 1b, Intel | Scale: 1.0 | `1`: Indicator light indicator L on |
| `LIA_Blk_R_Kontrolle` | **LIA indicator R control** | Bit 17, 1b, Intel | Scale: 1.0 | `1`: Indicator light indicator R on |
| `LIA_Kurv_Licht` | **LIA_Kurv_Licht**<br>*Note: Cornering lights are switched on* | Bit 18, 1b, Intel | Scale: 1.0 | `1`: Cornering lights on |
| `LIA_Warnblk_Status` | **LIA warning light status** | Bit 19, 1b, Intel | Scale: 1.0 | `1`: Hazard warning status on |
| `LIA_Zaehler` | **LIA Counter** | Bit 20, 4b, Intel | Scale: 1.0 | - |
| `LIA_Pruefsumme` | **LIA checksum**<br>*Note: Definition gemaess Lastenheft* | Bit 24, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mMotor7` (0x555 / 1365 Dec)
- **English Translation**: **m engine7**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN comfort 100ms

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `MO7_LL_Status` | **MO7_LL_Status** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: LLDZ_hat_Wert_1_Stufe_erreicht<br>`0`: no need for increased LL DZ |
| `MO7_V_Begrenz` | **MO7_V_limit** | Bit 1, 1b, Intel | Scale: 1.0 | `0`: V_Begrenzung_nicht_moeglich<br>`1`: V Limitation possible |
| `MO7_V_Begr_akt` | **MO7_V_Limit_act** | Bit 2, 1b, Intel | Scale: 1.0 | `0`: inactive<br>`1`: active |
| `MO7_FehlerSp` | **MO7_Error_Sp**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `MO7_Fehler_Oel_Temp` | **MO7_Oil_temperature_error** | Bit 4, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: OK |
| `MO7_PTC` | **MO7_PTC** | Bit 5, 3b, Intel | Scale: 1.0 | - |
| `MO7_DFM` | **MO7_DFM** | Bit 8, 8b, Intel | Scale: 0.4, Unit: 'Unit_PerCent' | `255`: Mistake |
| `MO7_Hoeheninfo` | **MO7_altitude_info**<br>*Note: Korrekturfaktor Hhe (1 entspricht 1013 mbar; 0,9 entspricht 1000m; 0,8 entspricht 2000m; 1,1 entspricht -1000m)* | Bit 16, 8b, Intel | Scale: 0.0078125 | `255`: Mistake |
| `MO7_Gradient_Drehz` | **MO7_gradient_speed** | Bit 24, 7b, Intel | Scale: 1.0, Unit: 'Unit_MinutInver' | `127`: ist_groessergleich_127_min |
| `MO7_Gradient_Vorz` | **MO7_Gradient_Prec** | Bit 31, 1b, Intel | Scale: 1.0 | `1`: negative sign<br>`0`: positive sign |
| `MO7_Ladedruckneu` | **MO7_boost_pressure_new** | Bit 32, 8b, Intel | Scale: 0.02, Unit: 'Unit_Bar' | `255`: Mistake |
| `MO7_GenLoadResp` | **MO7_Gen_Load_Resp** | Bit 40, 2b, Intel | Scale: 3.0, Unit: 'Unit_Secon' | - |
| `MO7_PTC_bereit` | **MO7_PTC_ready** | Bit 42, 2b, Intel | Scale: 1.0 | `0`: no 3-stage PTC installed |
| `MO7_Mot_weckfaehig` | **MO7_Mot_weckfaehig** | Bit 44, 1b, Intel | Scale: 1.0 | `1`: Awaken ACAN found<br>`0`: no waking ACAN |
| `MO7_Zus_Kuehl` | **MO7_To_Cool** | Bit 45, 1b, Intel | Scale: 1.0 | `1`: ja<br>`0`: nein |
| `MO7_Sleep_Ind` | **MO7_Sleep_Ind** | Bit 46, 1b, Intel | Scale: 1.0 | `0`: CAN is required<br>`1`: Sleep ready |
| `MO7_Rueck_LLDz` | **MO7_Rueck_LLDz** | Bit 47, 1b, Intel | Scale: 1.0 | `0`: no need for increased LL DZ<br>`1`: LLDZ_hat_Wert_2_Stufe_erreicht |
| `MO7_Last_abwurf` | **MO7_load_shedding** | Bit 48, 2b, Intel | Scale: 1.0 | `3`: Stage 3<br>`2`: Stage 2<br>`0`: Level 0<br>`1`: Stage 1 |
| `MO7_Ein_Generator` | **MO7_A_generator** | Bit 50, 1b, Intel | Scale: 1.0 | `1`: Generator_ein<br>`0`: Generator off |
| `MO7_Lastabwurf_Heiz` | **MO7_load_shedding_heating** | Bit 51, 1b, Intel | Scale: 1.0 | `0`: High performance heating system deactivated<br>`1`: High-performance heating system can be activated |
| `MO7_Stat_Gluehk` | **MO7_Stat_Gluehk** | Bit 52, 4b, Intel | Scale: 8.0, Unit: 'Unit_PerCent' | `15`: Mistake |
| `MO7_Oeltemperatur` | **MO7_Oeltemperatur** | Bit 56, 8b, Intel | Scale: 1.0, Offset: -60.0, Unit: 'Unit_DegreCelsi' | `1`: Init<br>`0`: not installed<br>`255`: Mistake |

---

## Message: `mKD_Error` (0x557 / 1367 Dec)
- **English Translation**: **m KD error**
- **Log Frequency**: 21 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `EKD_Motor_A` | **EKD_Motor_A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 0, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Getriebe_A` | **EKD gearbox A** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Bremse_A` | **EKD_Bremse_A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 2, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Kombi_A` | **EKD Combi A** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_LSM_A` | **EKD_LSM_A** | Bit 4, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Airbag_A` | **EKD Airbag A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 5, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Lenkhilfe_A` | **EKD steering aid A** | Bit 6, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_dyn_LWR_A` | **EKD dyn LWR A** | Bit 7, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Niveau_A` | **EKD_Niveau_A** | Bit 8, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Allrad_A` | **EKD Allrad A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 9, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_ADR_Sensor_A` | **EKD ADR Sensor A** | Bit 10, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_ADR_getrennt` | **EKD ADR separated** | Bit 11, 1b, Intel | Scale: 1.0 | `1`: ADR separate<br>`0`: ADR connected |
| `EKD_Parkbremse_A` | **EKD parking brake A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 12, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_EZS_A` | **EKD EZS A** | Bit 13, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Daempfer_A` | **EKD Damper A**<br>*Note: There is a current (static or sporadic) customer service error memory entry in the damper control error memory* | Bit 14, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Quersperre` | **EKD cross barrier**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 15, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Motor_Slave_A` | **EKD Motor Slave A**<br>*Note: Info fr Diagnose; bei gesetztem Bit befindet sich mindestens ein Kundendienstfehler im Fehlerspeicher des Motorslave* | Bit 16, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_SWA_A` | **EKD SWA A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 17, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_LDW_A` | **EKD LDW A**<br>*Note: If the bit is set, at least one customer service error is entered* | Bit 18, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_RKA_Plus_A` | **EKD RKA Plus A**<br>*Note: 1 = at least one customer service error present in the control unit* | Bit 19, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_PLA_A` | **EKD_PLA_A**<br>*Note: at least one error is entered in the customer service error memory* | Bit 20, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_WFS_KBI` | **EKD WFS KBI**<br>*Note: 1 = at least one customer service error entered in the immobilizer error memory* | Bit 21, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Kombi_KBI` | **EKD Combi KBI** | Bit 22, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_BSG_K` | **EKD BSG K**<br>*Note: 1 = at least one error is entered in the customer service error memory* | Bit 24, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_KSG_K` | **EKD KSG K**<br>*Note: 1 = at least 1 customer service error in the control unit* | Bit 25, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_TSG_FT_K` | **EKD TSG FT K**<br>*Note: 1 = at least 1 customer service error in the control unit, for Audi e.g. Currently only memory errors* | Bit 26, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_TSG_BT_K` | **EKD TSG BT K**<br>*Note: 1 = at least 1 customer service error in the control unit, for Audi e.g. Currently only memory errors* | Bit 27, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_TSG_HL_K` | **EKD TSG HL K**<br>*Note: 1 = at least 1 customer service error in the control unit* | Bit 28, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_TSG_HR_K` | **EKD TSG HR K**<br>*Note: 1 = at least 1 customer service error in the control unit* | Bit 29, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Memory_K` | **EKD_Memory_K**<br>*Note: 1 = at least 1 customer service error is entered in the control unit* | Bit 30, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Dachmodul_K` | **EKD roof module K** | Bit 31, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Zentralelektrik_II_K` | **EKD Central Electrics II K**<br>*Note: Kundendienstfehler Zentralelektrik 2 am CAN-Komfort* | Bit 32, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_RDK_K` | **EKD RDK K** | Bit 33, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_SMLS_K` | **EKD SMLS K**<br>*Note: 1 = at least one customer service error is entered in the error memory* | Bit 34, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Gateway_K` | **EKD Gateway K**<br>*Note: If the bit is set, at least one KD error is stored under the gateway address* | Bit 35, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Clima_K` | **EKD Clima K**<br>*Note: 1 = at least 1 customer service error is entered in the error memory* | Bit 36, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_APS_K` | **EKD APS K**<br>*Note: 1 = at least one error is entered in the customer service error memory* | Bit 37, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_PTC_Heizung_K` | **EKD PTC Heater K**<br>*Note: 1 = mindestens 1 Fehler im Kundendienstfehlerspeicher eingetragen* | Bit 38, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Standhzg_K` | **EKD Standhzg K**<br>*Note: 1 = at least 1 customer service error is entered in the error memory* | Bit 39, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_VSG_K` | **EKD VSG K**<br>*Note: 1 = at least 1 customer service error entry in the control unit* | Bit 40, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_RSE_I` | **EKD RSE I**<br>*Note: Rearseat entertainment customer service error* | Bit 41, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Wischer_K` | **EKD wiper K**<br>*Note: Wiper module customer service error* | Bit 42, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_MDI_I` | **EKD MDI I**<br>*Note: Fehlereintrag vorhanden* | Bit 43, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_AAG_K` | **EKD AAG K**<br>*Note: 1 = at least one customer service error is entered* | Bit 44, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Mem_BF_K` | **EKD Mem passenger K**<br>*Note: 1 = at least 1 customer service error is entered in the control unit* | Bit 45, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Easy_Entry_VF` | **EKD Easy Entry VF**<br>*Note: 1 = at least 1 customer service error is entered in the control unit (static or sporadic)* | Bit 46, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Easy_Entry_VB` | **EKD_Easy_Entry_VB**<br>*Note: 1 = at least 1 customer service error is entered in the control unit (static or sporadic)* | Bit 47, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Heckdeckel_K` | **EKD trunk lid K**<br>*Note: Customer service error memory entry in the control unit* | Bit 48, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Rearview_I` | **EKD Rearview I**<br>*Note: Customer service error* | Bit 49, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Sonderfahrzeug_SG_K` | **EKD_Sonderfahrzeug_SG_K**<br>*Note: 1 = at least 1 customer service error entry in the control unit* | Bit 50, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Tastenmodul_I` | **EKD_Tastenmodul_I**<br>*Note: Fehlereintrag vorhanden* | Bit 51, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Kompass_I` | **EKD Compass I**<br>*Note: Customer service error memory available* | Bit 52, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_WFS_K` | **EKD_WFS_K** | Bit 53, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_GSM_Pager_I` | **EKD GSM Pager I**<br>*Note: Fehlereintrag vorhanden* | Bit 54, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_DSP_I` | **EKD DSP I**<br>*Note: 1 = at least one customer service error is entered in the control unit* | Bit 56, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_DAB_I` | **EKD DAB I**<br>*Note: Fehlereintrag vorhanden* | Bit 57, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Telematik_I` | **EKD Telematics I**<br>*Note: Fehlereintrag vorhanden* | Bit 58, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Navigation_I` | **EKD Navigation I**<br>*Note: Fehlereintrag vorhanden* | Bit 59, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_TV_Tuner_I` | **EKD TV Tuner I**<br>*Note: 1 = mindestens 1 Fehler im Kundendienstfehlerspeicher eingetragen* | Bit 60, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Neigungsmodul` | **EKD tilt module**<br>*Note: Customer service error tilt module on CAN infotainment* | Bit 61, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Radio_I` | **EKD Radio I**<br>*Note: Fehlereintrag vorhanden* | Bit 62, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `EKD_Telefon_I` | **EKD Telephone I**<br>*Note: 1 = at least one customer service error is entered in the control unit* | Bit 63, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |

---

## Message: `mBSG_2` (0x571 / 1393 Dec)
- **English Translation**: **m BSG 2**
- **Log Frequency**: 22 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 6

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `BS2_U_BATT` | **BS2_U_BATT** | Bit 0, 8b, Intel | Scale: 0.05, Offset: 5.0, Unit: 'Unit_Volt' | `255`: Mistake |
| `BS2_Heckscheibe_aus` | **BS2_rear_window_off** | Bit 8, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_Frontscheibe_aus` | **BS2_windscreen_off** | Bit 9, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_Aussenspiegel_aus` | **BS2_exterior_mirror_off** | Bit 10, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_Sitzheizung_aus` | **BS2_seat_heating_off** | Bit 11, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_aus_Lenkradheizung` | **BS2_from_steering_wheel_heating** | Bit 12, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_aus_Wischwasserhzg` | **BS2_from_washer_water_heater** | Bit 13, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_aus_Sitzlueftung` | **BS2_from_seat_ventilation**<br>*Note: 1 = Switching off the seat ventilation is required* | Bit 14, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_Klimaanlage_aus` | **BS2_Klimaanlage_aus** | Bit 15, 1b, Intel | Scale: 1.0 | `1`: Switch off consumers<br>`0`: Basic state |
| `BS2_U_Start_BATT` | **BS2_U_Start_BATT** | Bit 16, 8b, Intel | Scale: 0.05, Offset: 5.0, Unit: 'Unit_Volt' | - |
| `BS2_Lastman_aktiv` | **BS2_Lastman_active**<br>*Note: 1 = Load management is active* | Bit 24, 1b, Intel | Scale: 1.0 | - |
| `BS2_Verbr_ab_aktiv` | **BS2_consumption_from_active**<br>*Note: 1 = requirement that at least one consumer should be switched off* | Bit 25, 1b, Intel | Scale: 1.0 | - |
| `BS2_Notstart` | **BS2_emergency_start**<br>*Note: 1 = Emergency start is carried out* | Bit 26, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Sitzhzg_H` | **BS2_from_Sitzhzg_H**<br>*Note: 1 = Switching off the seat heating on the rear seats is required* | Bit 27, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Steckdosen` | **BS2_from_sockets**<br>*Note: 1 = Switching off the sockets is required* | Bit 28, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Zusatz_Verbr` | **BS2_from_additional_consumption**<br>*Note: 1 = switching off an additional consumer, e.g. umbrella dryer, cool box, ...* | Bit 29, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Infotainment` | **BS2_from_infotainment** | Bit 30, 1b, Intel | Scale: 1.0 | - |
| `BS2_Wake_Up_ACAN` | **BS2_Wake_Up_ACAN** | Bit 31, 1b, Intel | Scale: 1.0 | `0`: no waking ACAN<br>`1`: Awaken ACAN |
| `BS2_aus_PTC_Clima` | **BS2_made_from_PTC_Clima** | Bit 32, 3b, Intel | Scale: 25.0, Unit: 'Unit_PerCent' | - |
| `BS2_KlimaLeistRed` | **BS2_Climate_Leist_Red** | Bit 35, 2b, Intel | Scale: 1.0 | - |
| `BS2_red_Heckscheibe` | **BS2_red_rear_window**<br>*Note: 1 = power reduction of the rear window required, switch off see BS2 rear window off* | Bit 37, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Ablage_Wischer` | **BS2_from_storage_wiper**<br>*Note: Switch off the wiper compartment heater* | Bit 38, 1b, Intel | Scale: 1.0 | - |
| `BS2_aus_Innen_Bel` | **BS2_from_inside_Bel**<br>*Note: 1 = Switching off or reducing the power of the interior and surrounding lighting* | Bit 39, 1b, Intel | Scale: 1.0 | - |
| `BS2_Warn_Steckdosen` | **BS2_Warn_Steckdosen**<br>*Note: 1 = Sockets will be switched off shortly* | Bit 40, 1b, Intel | Scale: 1.0 | - |
| `BS2_Warn_Infotainment` | **BS2_warning_infotainment**<br>*Note: 1 = Infotainment participants will be switched off shortly* | Bit 41, 1b, Intel | Scale: 1.0 | - |
| `BS2_Warn_Zusatz` | **BS2_Warn_Zusatz**<br>*Note: 1 = Additional consumers will be switched off shortly* | Bit 42, 1b, Intel | Scale: 1.0 | - |
| `BS2_Weckursache_ACAN` | **BS2_wake-up_cause_ACAN** | Bit 43, 2b, Intel | Scale: 1.0 | `0`: no EKP advance<br>`2`: Weckursache_StHzg<br>`3`: Door contact alarm cause |
| `BS2_VB_2_Battarie` | **BS2_VB_2_battery**<br>*Note: This bit is coded at the end of the band in the BSG and indicates whether a second battery (e.g. for an auxiliary heater) is installed in the vehicle.* | Bit 45, 1b, Intel | Scale: 1.0 | `0`: Just one battery<br>`1`: second battery installed |
| `BS2_Zust_Start_Ltg` | **BS2_status_start_line** | Bit 46, 1b, Intel | Scale: 1.0 | - |
| `BS2_Mess_Start_Ltg` | **BS2_measuring_start_line** | Bit 47, 1b, Intel | Scale: 1.0 | - |

---

## Message: `mBSG_3` (0x575 / 1397 Dec)
- **English Translation**: **m BSG 3**
- **Log Frequency**: 66 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 4

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `BS3_Klemme_S` | **BS3_terminal_S** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: S Contact active<br>`0`: Basic state |
| `BS3_Klemme_15` | **BS3_terminal_15**<br>*Note: 1 = Klemme 15 Innenraum ist eingeschaltet* | Bit 1, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Klemme_15_aktiv |
| `BS3_Klemme_X` | **BS3_Terminal_X** | Bit 2, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Terminal X active |
| `BS3_Klemme_50` | **BS3_terminal_50** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Terminal 50 active<br>`0`: Basic state |
| `BS3_Klemme_P` | **BS3_terminal_P**<br>*Note: 1 = Terminal P on (parking light)* | Bit 4, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Klemme_P_aktiv |
| `BS3_2_Drehzahl` | **BS3_2_speed** | Bit 5, 1b, Intel | Scale: 1.0 | `1`: Speed ​​increase level 2 required<br>`0`: Basic state |
| `BS3_Klemme_15_Motorraum` | **BS3_terminal_15_engine_compartment**<br>*Note: 1 = Terminal 15 engine compartment is switched on (terminal 14)* | Bit 6, 1b, Intel | Scale: 1.0 | `1`: Terminal 14 active<br>`0`: Basic state |
| `BS3_Ladekontrollampe` | **BS3_charging_indicator_light** | Bit 7, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Terminal L active |
| `BS3_Drehzahlanhebung` | **BS3_speed_increase**<br>*Note: 1 = Anforderung der Drehzahlanhebung (bei nur einer Stufe) oder Anhebung auf 1. Stufe (s. Antrieb BSG_Last)* | Bit 8, 1b, Intel | Scale: 1.0 | `0`: Basic state<br>`1`: Speed ​​increase level 1 required |
| `BS3_Bordnetzbatt` | **BS3_electrical_system_battery**<br>*Note: Shows the status of the on-board network battery (00=OK, 01=critical, 10=discharged, 11=error)* | Bit 9, 2b, Intel | Scale: 1.0 | `1`: critical<br>`2`: discharged<br>`0`: OK<br>`3`: Mistake |
| `BS3_Starterbatt` | **BS3_Starterbatt**<br>*Note: Shows the status of the starter battery (00=OK, 01=critical, 10=discharged, 11=error)* | Bit 11, 2b, Intel | Scale: 1.0 | `1`: critical<br>`2`: discharged<br>`0`: OK<br>`3`: Mistake |
| `BS3_KD_Fehler` | **BS3_KD_error**<br>*Note: 1 = at least one error is entered in the customer service error memory* | Bit 13, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `BS3_LWR_Fehler` | **BS3_LWR_error** | Bit 14, 1b, Intel | Scale: 1.0 | `0`: LWR OK<br>`1`: LWR error |
| `BS3_Haubenkontakt` | **BS3_hood_contact** | Bit 15, 1b, Intel | Scale: 1.0 | `0`: Haube_geschlossen<br>`1`: Haube_offen |
| `BS3_Coming_Home` | **BS3_Coming_Home**<br>*Note: 1 = Coming Home function activated* | Bit 16, 1b, Intel | Scale: 1.0 | - |
| `BS3_Leaving_Home` | **BS3_Leaving_Home**<br>*Note: 1 = Leaving Home Funktion aktiviert* | Bit 17, 1b, Intel | Scale: 1.0 | - |
| `BS3_K_Luefter_ein` | **BS3_K_fan_on** | Bit 18, 1b, Intel | Scale: 1.0 | `0`: no requirement<br>`1`: einschalten |
| `BS3_Ab_Batterie` | **BS3_From_Battery** | Bit 19, 1b, Intel | Scale: 1.0 | `1`: Battery off<br>`0`: Battery on the on-board network |
| `BS3_VP_Taste` | **BS3_VP_button**<br>*Note: 1 = Valet Parking button pressed, evaluation takes place in the receiver* | Bit 20, 1b, Intel | Scale: 1.0 | - |
| `BS3_Verglasung_zu` | **BS3_glazing_too**<br>*Note: Command to close the glazing in the window, e.g. when rain is detected and the window/pane roof is open* | Bit 21, 1b, Intel | Scale: 1.0 | `0`: Keine_Aktion<br>`1`: Close glazing |
| `BS3_PDC_Taster` | **BS3_PDC_button**<br>*Note: 1 = button pressed, evaluation on/off takes place in the parking aid* | Bit 22, 1b, Intel | Scale: 1.0 | - |
| `BS3_IRUE_Taster` | **BS3_IRUE_button**<br>*Note: 1 = Taste IRUE gedrueckt; Bewertung ein/aus erfolgt durch ZKE* | Bit 23, 1b, Intel | Scale: 1.0 | - |
| `BS3_VB_Coming_Home` | **BS3_VB_Coming_Home**<br>*Note: 1 = ComingHome Funktion im SG vorhanden* | Bit 24, 1b, Intel | Scale: 1.0 | - |
| `BS3_VB_Tagesfahrlicht` | **BS3_VB_Tagesfahrlicht**<br>*Note: 1 = Daytime running lights present in the SG* | Bit 25, 1b, Intel | Scale: 1.0 | - |
| `BS3_VB_Fussraumleuchten` | **BS3_VB_footwell_lights**<br>*Note: 1 = Dimmung Fussraumleuchten implementiert* | Bit 26, 1b, Intel | Scale: 1.0 | - |
| `BS3_LED_Heckscheibe` | **BS3_LED_rear_window**<br>*Note: 1 = Heated rear window activated* | Bit 27, 1b, Intel | Scale: 1.0 | - |
| `BS3_LED_Frontscheibe` | **BS3_LED_windshield**<br>*Note: 1 = Heizbare Frontscheibe angesteuert* | Bit 28, 1b, Intel | Scale: 1.0 | - |
| `BS3_LED_Sitze` | **BS3_LED_seats**<br>*Note: 1 = Heated seats activated* | Bit 29, 1b, Intel | Scale: 1.0 | - |
| `BS3_LED_Aussenspiegel` | **BS3_LED_exterior_mirror**<br>*Note: 1 = Heated exterior mirrors activated* | Bit 30, 1b, Intel | Scale: 1.0 | - |
| `BS3_Starterlaubnis` | **BS3_take-off_permit** | Bit 31, 1b, Intel | Scale: 1.0 | `0`: Start not allowed<br>`1`: Start allowed |

---

## Message: `mMotor_10` (0x58C / 1420 Dec)
- **English Translation**: **mMotor_10**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `M10_Anzeige` | **M10_display** | Bit 0, 4b, Intel | Scale: 1.0 | `2`: System error start stop<br>`12`: Engine starts<br>`13`: Kupplung_betaetigt<br>`0`: no display<br>`1`: Start Stop active<br>`15`: Apply the brake<br>`14`: WH to P N<br>`3`: Start the engine manually<br>`5`: Engine running required<br>`9`: Unwanted engine shutdown |
| `M10_Anf_Kl75` | **M10_Anf_Kl75**<br>*Note: Requirements for the BSG/BCM for concepts with starter control by the MSG: During the first start, the MSG uses this signal to request that the KL75 consumers be switched off. (When restarting within the start-stop functionality, the signal remains set* | Bit 4, 1b, Intel | Scale: 1.0 | `0`: Switch off Kl75<br>`1`: Switch on Kl75 |
| `MSG_Remotestart_Betrieb` | **MSG remote start operation** | Bit 5, 1b, Intel | Scale: 1.0 | `1`: RS_Betrieb<br>`0`: no RS operation |
| `M10_SpannungsAnf` | **M10_Voltage_Req**<br>*Note: Request from the motor SG to increase the voltage* | Bit 6, 1b, Intel | Scale: 1.0 | `0`: no requirement<br>`1`: Requirement |
| `M10_UDruckDyn` | **M10_U_pressure_dyn** | Bit 7, 1b, Intel | Scale: 1.0 | `1`: Dyn_immer_kleiner_50mbar<br>`0`: Dyn 1 times larger 50mbar |
| `M10_Status_StSt` | **M10_status_St_St** | Bit 8, 2b, Intel | Scale: 1.0 | `0`: System not available in this KL15 cycle<br>`1`: System active, no release from start stop coordinator<br>`2`: System active, all releases are available<br>`3`: System active at least one release is missing |
| `M10_MotorStopp` | **M10_MotorStopp** | Bit 10, 1b, Intel | Scale: 1.0 | `0`: Motor stop inactive<br>`1`: Motor_Stopp_aktiv |
| `M10_Wiederstart` | **M10_restart**<br>*Note: Engine restart by start-stop coordinator. 'Restart active' is set by the coordinator as soon as the restart is triggered and remains set until the end of the start. (remains 0 at first start)* | Bit 11, 1b, Intel | Scale: 1.0 | `0`: Restart inactive<br>`1`: Restart active |
| `M10_Schubabschaltung` | **M10_Schubabschaltung** | Bit 12, 1b, Intel | Scale: 1.0 | `0`: no thrust barriers<br>`1`: Schubabschaltung |
| `M10_Druck_err_gem` | **M10_pressure_err_acc** | Bit 13, 1b, Intel | Scale: 1.0 | `1`: measured<br>`0`: calculated |
| `M10_Freigabe_Reku` | **M10_Release_Recu** | Bit 14, 2b, Intel | Scale: 1.0 | `3`: RekuModus_aktiv<br>`0`: RekuModus_aus<br>`2`: Empf_U_Absenkung<br>`1`: Rec. U increase |
| `M10_rel_Saugrohrdruck` | **M10_rel_intake_manifold_pressure** | Bit 16, 6b, Intel | Scale: 18.0, Unit: 'Unit_MilliBar' | `63`: Error not available |
| `M10_Fahrbereitschaft` | **M10_ready_to_drive** | Bit 22, 1b, Intel | Scale: 1.0 | `0`: nicht_fahrbereit<br>`1`: fahrbereit |
| `M10_Hybrid` | **M10_hybrid** | Bit 23, 1b, Intel | Scale: 1.0 | `0`: not a hybrid<br>`1`: Hybrid |
| `M10_EM_aktiv` | **M10_EM_aktiv** | Bit 24, 1b, Intel | Scale: 1.0 | `0`: EM_inaktiv<br>`1`: EM active |
| `M10_VM_aktiv` | **M10_VM_active** | Bit 25, 1b, Intel | Scale: 1.0 | `0`: VM inactive<br>`1`: VM active |
| `M10_HYB_Bereitlampe` | **M10_HYB_ready_lamp** | Bit 26, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `M10_HYB_Warnlampe` | **M10_HYB_warning_lamp** | Bit 27, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `M10_HYB_Fehlerlampe` | **M10_HYB_error_lamp** | Bit 28, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `M10_Fehler_HV_Netz` | **M10_Fehler_HV_Netz**<br>*Note: Due to an error, generator operation is not possible in the HV on-board network. The 12 V on-board electrical system is powered solely from the traction battery via the DC/DC converter. In order to be able to maintain this condition for as long as possible, comfort consumers should be protected* | Bit 29, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: no operation possible |
| `M10_EKlKomLeiRed` | **M10_EKl_Kom_Lei_Red** | Bit 30, 2b, Intel | Scale: 1.0 | `0`: no performance limit<br>`1`: Achieves Begr 75<br>`2`: Pay limit 50<br>`3`: Makes allowance 25 |
| `M10_Klimadruck` | **M10_climate_pressure**<br>*Note: Pressure sensor on the engine SG (China model X/Y)* | Bit 32, 8b, Intel | Scale: 0.2, Unit: 'Unit_Bar' | `254`: Init<br>`255`: Mistake |
| `M10_KompAusCode` | **M10_Comp_Off_Code** | Bit 40, 4b, Intel | Scale: 1.0 | `4`: MotManagem_12<br>`2`: Low pressure 3<br>`3`: Outside temp 8<br>`1`: High pressure 1<br>`6`: About 13<br>`0`: no<br>`7`: Undervoltage 10<br>`5`: HD sensor def 17 |
| `M10_StartStopp_Fahrerwunsch` | **M10_Start_Stop_driver_request**<br>*Note: Fahreraktivitt Start/Stopp* | Bit 44, 2b, Intel | Scale: 1.0 | `0`: Init<br>`1`: Stopping prohibited by driver<br>`3`: Stop request by driver<br>`2`: Stop release by driver |
| `M10_Akustik` | **M10_Akustik** | Bit 46, 2b, Intel | Scale: 1.0 | `2`: Acoustics 2<br>`3`: free<br>`0`: no acoustics<br>`1`: Acoustics 1 |
| `M10_Text_1_Hybrid` | **M10_Text_1_Hybrid**<br>*Note: Text 1 (ID TXT 1024.1): Hybrid system error. Visit a workshop (Category 1)* | Bit 48, 1b, Intel | Scale: 1.0 | `1`: Text 1<br>`0`: no text |
| `M10_Text_2_Hybrid` | **M10_Text_2_Hybrid**<br>*Note: Text 2 (ID TXT 1025.1): Hybrid system error. Visit a workshop (category 2)* | Bit 49, 1b, Intel | Scale: 1.0 | `1`: Text 2<br>`0`: no text |
| `M10_Text_3_Hybrid` | **M10_Text_3_Hybrid**<br>*Note: Text 3 (ID TXT 1025.2): Waiting. HV battery is being charged. Logbook* | Bit 50, 1b, Intel | Scale: 1.0 | `0`: no text<br>`1`: Text 3 |
| `M10_Text_4_Hybrid` | **M10_Text_4_Hybrid**<br>*Note: Text 4 (ID TXT 1025.3): Vehicle electrical system undervoltage logbook* | Bit 51, 1b, Intel | Scale: 1.0 | `1`: Text 4<br>`0`: no text |
| `M10_Text_5_Hybrid` | **M10_Text_5_Hybrid**<br>*Note: Text 5 (ID TXT 1025.4): Press starter for longer!* | Bit 52, 1b, Intel | Scale: 1.0 | `0`: no text<br>`1`: Text 5 |
| `M10_Text_6_Hybrid` | **M10_Text_6_Hybrid**<br>*Note: Text 6 Hybrid* | Bit 53, 1b, Intel | Scale: 1.0 | `0`: no text |
| `M10_Text_7_Hybrid` | **M10_Text_7_Hybrid**<br>*Note: Text 7 Hybrid* | Bit 54, 1b, Intel | Scale: 1.0 | `0`: no text |
| `M10_Text_8_Hybrid` | **M10_Text_8_Hybrid**<br>*Note: Text 8 Hybrid* | Bit 55, 1b, Intel | Scale: 1.0 | `0`: no text |
| `M10_ShiftLockLampe` | **M10_shift_lock_lamp**<br>*Note: With automatic start/starter control in the MSG: In automatic vehicles, pressing the brake is a release condition for the start request. (in addition/alternative to the text display)* | Bit 56, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `M10_BMSInfo_gue` | **M10_BMSInfo_gue** | Bit 58, 1b, Intel | Scale: 1.0 | `1`: valid<br>`0`: not valid or outdated |
| `M10_VentilationReq` | **M10_Ventilation_Req**<br>*Note: BMS fordert bei Climatronic die ffnung der Umluftklappe an. Signal wird vom MSG von Hybrid-CAN auf den A-CAN gespiegelt (mBMS_HYB_6, Byte 8, Bit 1 aus Hybrid-CAN DF > V1.5)* | Bit 59, 1b, Intel | Scale: 1.0 | `1`: Open the recirculation flap<br>`0`: Umluftklappe_nicht_oeffnen |
| `M10_BattFanSpd` | **M10_Batt_Fan_Spd** | Bit 60, 4b, Intel | Scale: 10.0, Unit: 'Unit_PerCent' | `15`: Mistake |

---

## Message: `mBremse_10` (0x5B5 / 1461 Dec)
- **English Translation**: **m brake 10**
- **Log Frequency**: 53 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `B10_Checksumme` | **B10_checksum**<br>*Note: Checksum, definition in the CAN specifications* | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `B10_Zaehler` | **B10_counter**<br>*Note: Overflowing message counter, for liveness detection* | Bit 8, 4b, Intel | Scale: 1.0 | - |
| `B10_QB_Wegimp_VL` | **B10_QB_Wegimp_VL** | Bit 12, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Wegimp_VR` | **B10_QB_Wegimp_VR** | Bit 13, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Wegimp_HL` | **B10_QB_Wegimp_HL** | Bit 14, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Wegimp_HR` | **B10_QB_Wegimp_HR** | Bit 15, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_Wegimp_VL` | **B10_Wegimp_VL** | Bit 16, 10b, Intel | Scale: 1.0 | `1022`: Undervoltage<br>`1021`: Initial value<br>`1023`: Sensor error |
| `B10_Wegimp_VR` | **B10_Wegimp_VR** | Bit 26, 10b, Intel | Scale: 1.0 | `1022`: Undervoltage<br>`1023`: Sensor error<br>`1021`: Initial value |
| `B10_Wegimp_HL` | **B10_Wegimp_HL** | Bit 36, 10b, Intel | Scale: 1.0 | `1021`: Initial value<br>`1022`: Undervoltage<br>`1023`: Sensor error |
| `B10_Wegimp_HR` | **B10_Wegimp_HR** | Bit 46, 10b, Intel | Scale: 1.0 | `1022`: Undervoltage<br>`1023`: Sensor error<br>`1021`: Initial value |
| `B10_QB_Fahrtr_VL` | **B10_QB_Driver_VL** | Bit 56, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Fahrtr_VR` | **B10_QB_driver_VR** | Bit 57, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Fahrtr_HL` | **B10_QB_Fahrtr_HL** | Bit 58, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_QB_Fahrtr_HR` | **B10_QB_Driver_HR** | Bit 59, 1b, Intel | Scale: 1.0 | `0`: valid value<br>`1`: Replacement init or error value |
| `B10_Fahrtr_VL` | **B10_Driver_VL**<br>*Note: Fahrtrichtungserkennung Vorderrad links* | Bit 60, 1b, Intel | Scale: 1.0 | `1`: Backward<br>`0`: Forward |
| `B10_Fahrtr_VR` | **B10_Fahrtr_VR**<br>*Note: Direction detection front wheel right* | Bit 61, 1b, Intel | Scale: 1.0 | `1`: Backward<br>`0`: Forward |
| `B10_Fahrtr_HL` | **B10_driver_HL**<br>*Note: Direction detection rear wheel left* | Bit 62, 1b, Intel | Scale: 1.0 | `1`: Backward<br>`0`: Forward |
| `B10_Fahrtr_HR` | **B10_Driver_HR**<br>*Note: Direction detection rear wheel on the right* | Bit 63, 1b, Intel | Scale: 1.0 | `1`: Backward<br>`0`: Forward |

---

## Message: `mMFL_Cmd_` (0x5C3 / 1475 Dec)
- **English Translation**: **m MFL Cmd**
- **Log Frequency**: 21 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 2

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `ML1_Ziel_` | **ML1_Ziel_** | Bit 0, 8b, Intel | Scale: 1.0 | - |
| `ML1_Befehl_` | **ML1_command** | Bit 8, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mNAV_1` (0x604 / 1540 Dec)
- **English Translation**: **m NAV 1**
- **Log Frequency**: 10 occurrences
- **Sender**: `RNS_300_NF` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `NV1_NAV_On` | **NV1_NAV_On** | Bit 0, 1b, Intel | Scale: 1.0 | - |
| `NV1_NAV_mute` | **NV1_NAV_mute**<br>*Note: Mute on/off* | Bit 1, 1b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Wartnton_Geschw` | **NV1_NAV_warning_tone_speed** | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Error_flag` | **NV1_NAV_Error_flag**<br>*Note: Fehlereintrag vorhanden* | Bit 7, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `NV1_NAV_Mode` | **NV1_NAV_mode** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para1` | **NV1_NAV_Para1**<br>*Note: Parameters of the respective mode* | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para2` | **NV1_NAV_Para2**<br>*Note: Parameters of the respective mode* | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para3` | **NV1_NAV_Para3**<br>*Note: Parameters of the respective mode* | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para4` | **NV1_NAV_Para4**<br>*Note: Parameters of the respective mode* | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para5` | **NV1_NAV_Para5**<br>*Note: Parameters of the respective mode* | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `NV1_NAV_Para6` | **NV1_NAV_Para6**<br>*Note: Parameters of the respective mode* | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mEinheiten` (0x60E / 1550 Dec)
- **English Translation**: **m units**
- **Log Frequency**: 11 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 2

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `EH1_Einh_Strck` | **EH1_unit_pcs** | Bit 0, 1b, Intel | Scale: 1.0 | `0`: km<br>`1`: mls |
| `EH1_Einh_Temp` | **EH1_unit_temperature** | Bit 1, 1b, Intel | Scale: 1.0 | `0`: Grade C<br>`1`: Grade F |
| `EH1_Einh_Vol` | **EH1_Unit_Vol** | Bit 2, 1b, Intel | Scale: 1.0 | `1`: gallons<br>`0`: liter |
| `EH1_Einh_Verbr` | **EH1_unit_consumption** | Bit 3, 1b, Intel | Scale: 1.0 | `0`: Route Vol<br>`1`: Vol_Strecke |
| `EH1_Einh_Druck` | **EH1_unit_pressure** | Bit 4, 2b, Intel | Scale: 1.0 | `0`: bear<br>`3`: k Pa<br>`1`: psi<br>`2`: nn |
| `EH1_Datum_Anzeige` | **EH1_Datum_Anzeige**<br>*Note: Date display format (European = 0, American = 1)* | Bit 6, 1b, Intel | Scale: 1.0 | `0`: DD MM YYYY<br>`1`: MM DD YYYY |
| `EH1_Uhr_Anzeige` | **EH1_clock_display** | Bit 7, 1b, Intel | Scale: 1.0 | `0`: 24h number<br>`1`: 12h number |
| `EH1_Profil` | **EH1_profile**<br>*Note: current profile number* | Bit 8, 4b, Intel | Scale: 1.0 | - |
| `EH1_Wochentag` | **EH1_weekday** | Bit 12, 3b, Intel | Scale: 1.0 | `3`: Wed<br>`7`: So<br>`1`: Mo<br>`0`: Init<br>`4`: do<br>`6`: Sat<br>`5`: Ms<br>`2`: Tue |
| `EH1_Verstellung_Strck` | **EH1_adjustment_Strck** | Bit 15, 1b, Intel | Scale: 1.0 | `1`: ja<br>`0`: nein |

---

## Message: `mKombi_K1` (0x621 / 1569 Dec)
- **English Translation**: **m station wagon K1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 7
- **Description**: PQ35

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `KO1_Tankstop` | **KO1_fuel_stop** | Bit 0, 1b, Intel | Scale: 1.0 | `1`: Fuel stop detected |
| `KO1_Tankwarnlampe` | **KO1_Tankwarnlampe**<br>*Note: Driver is warned (currently 7 liters)* | Bit 1, 1b, Intel | Scale: 1.0 | `1`: lamp on<br>`0`: Lamp off |
| `KO1_WaschWasser` | **KO1_washing_water** | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `KO1_MH_Kontakt` | **KO1_MH_contact** | Bit 3, 1b, Intel | Scale: 1.0 | - |
| `KO1_FT_geoeffnet` | **KO1_FT_open**<br>*Note: 1 = Driver's door open* | Bit 4, 1b, Intel | Scale: 1.0 | - |
| `KO1_Handbremse` | **KO1_handbrake** | Bit 5, 1b, Intel | Scale: 1.0 | `1`: angezogen<br>`0`: nicht_angezogen |
| `KO1_AFL` | **KO1_AFL**<br>*Note: Light switch position to AFL* | Bit 6, 1b, Intel | Scale: 1.0 | - |
| `KO1_Klemme_L` | **KO1_terminal_L**<br>*Note: The station wagon has its charging control lamp switched on (receiver: currently Batman), not PQ35/46, not Audi D3/C6* | Bit 7, 1b, Intel | Scale: 1.0 | `0`: Lamp off<br>`1`: lamp on |
| `KO1_Standzeit` | **KO1_service_life** | Bit 8, 15b, Intel | Scale: 4.0, Unit: 'Unit_Secon' | - |
| `KO1_Standzeit_Fehler` | **KO1_Standzeit_Fehler**<br>*Note: Reset service life* | Bit 23, 1b, Intel | Scale: 1.0 | `1`: Terminal 30 was gone<br>`0`: Standzeit_iO |
| `KO1_Tankinhalt` | **KO1_tank_content** | Bit 24, 7b, Intel | Scale: 1.0, Unit: 'Unit_Liter' | `127`: Mistake |
| `KO1_Tankwarnung` | **KO1_tank_warning** | Bit 31, 1b, Intel | Scale: 1.0 | `0`: OK<br>`1`: Tank warning |
| `KO1_WFS_Schluessel` | **KO1_WFS_key** | Bit 32, 4b, Intel | Scale: 1.0 | `0`: invalid |
| `KO1_KD_Fehler_WFS` | **KO1_KD_error_WFS**<br>*Note: 1 = at least one customer service error entered in the immobilizer error memory* | Bit 36, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `KO1_Fernlicht` | **KO1_high_beam** | Bit 37, 1b, Intel | Scale: 1.0 | `1`: Kl56a<br>`0`: out of |
| `KO1_Freigabe_Zuheizer` | **KO1_Freigabe_Zuheizer** | Bit 38, 1b, Intel | Scale: 1.0 | `0`: Additional heater ON<br>`1`: Additional heater OFF |
| `KO1_MFA_vorhanden` | **KO1_MFA_present** | Bit 39, 1b, Intel | Scale: 1.0 | - |
| `KO1_Bel_Displ` | **KO1_Bel_Displ** | Bit 40, 7b, Intel | Scale: 1.0, Unit: 'Unit_PerCent' | `127`: no replacement value |
| `KO1_Sta_Displ` | **KO1_Sta_Displ** | Bit 47, 1b, Intel | Scale: 1.0 | `1`: Terminal 58d not OK<br>`0`: Terminal 58d OK |
| `KO1_Lichtsensor` | **KO1_light_sensor**<br>*Note: Light sensor status according to dimming specification* | Bit 48, 8b, Intel | Scale: 1.0 | `254`: INIT<br>`255`: Mistake |

---

## Message: `mKombi_K2` (0x623 / 1571 Dec)
- **English Translation**: **m station wagon K2**
- **Log Frequency**: 10 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `KO2_DCF` | **KO2_DCF**<br>*Note: 1 = DCF-Signal vorhanden* | Bit 0, 1b, Intel | Scale: 1.0 | - |
| `KO2_Reset` | **KO2_reset**<br>*Note: 1 = Reset the clock, transmitted time is not valid* | Bit 1, 1b, Intel | Scale: 1.0 | - |
| `KO2_24h_Anzeige` | **KO2_24h_display** | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `KO2_WeckzSH_OK` | **KO2_Weckz_SH_OK** | Bit 3, 1b, Intel | Scale: 1.0 | - |
| `KO2_QV` | **KO2_QV**<br>*Note: Adjustment mode combination* | Bit 4, 1b, Intel | Scale: 1.0 | - |
| `KO2_Stunde` | **KO2_hour** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `KO2_Minute` | **KO2_minute** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `KO2_Sekunde` | **KO2_Sekunde** | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `KO2_Tag` | **KO2_day** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `KO2_Monat` | **KO2_Monat** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `KO2_Jahrhundert` | **KO2_Jahrhundert** | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `KO2_Jahr` | **KO2_year** | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mKombi_K4` (0x627 / 1575 Dec)
- **English Translation**: **m station wagon K4**
- **Log Frequency**: 22 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `KO4_Disp_Request` | **KO4_Disp_Request** | Bit 0, 1b, Intel | Scale: 1.0 | - |
| `KO4_Disp_Ack` | **KO4_Disp_Ack** | Bit 1, 1b, Intel | Scale: 1.0 | - |
| `KO4_Disp_Busy` | **KO4_Disp_Busy**<br>*Note: 1 = Display busy (currently set if phone data cannot be displayed, Priority 1 warning)* | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `KO4_code_no_ack` | **KO4_code_no_ack** | Bit 3, 1b, Intel | Scale: 1.0 | - |
| `KO4_Disp_Ft_auf` | **KO4_Disp_Ft_on**<br>*Note: 1 = driver's door open, for coming home function for AFL* | Bit 7, 1b, Intel | Scale: 1.0 | - |
| `KO4_User_field1` | **KO4_User_field1** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field2` | **KO4_User_field2** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field3` | **KO4_User_field3**<br>*Note: SG in the left display segment 2nd line from the top* | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field4` | **KO4_User_field4**<br>*Note: SG im rechten Anzeigesegment 2.Zeile von oben* | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field5` | **KO4_User_field5**<br>*Note: SG in the middle display segment at the top* | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field6` | **KO4_User_field6**<br>*Note: SG in the middle display segment below* | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `KO4_User_field7` | **KO4_User_field7**<br>*Note: SG in the lower display segment* | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mDimmung` (0x635 / 1589 Dec)
- **English Translation**: **m dimming**
- **Log Frequency**: 53 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 3

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `DI1_Display` | **DI1_display** | Bit 0, 7b, Intel | Scale: 1.0, Unit: 'Unit_PerCent' | `127`: Mistake |
| `DI1_Display_def` | **DI1_display_def** | Bit 7, 1b, Intel | Scale: 1.0 | `0`: Terminal 58d OK<br>`1`: Kl_58d_n_i_O |
| `DI1_Schalter` | **DI1_switch** | Bit 8, 7b, Intel | Scale: 1.0, Unit: 'Unit_PerCent' | `127`: Mistake |
| `DI1_Schalter_def` | **DI1_switch_def** | Bit 15, 1b, Intel | Scale: 1.0 | `0`: Terminal 58s OK<br>`1`: Terminal 58 s not OK |
| `DI1_Sensor` | **DI1_Sensor**<br>*Note: Light sensor status according to dimming specification* | Bit 16, 8b, Intel | Scale: 1.0 | `254`: INIT<br>`255`: Mistake |

---

## Message: `mSysteminfo_1` (0x651 / 1617 Dec)
- **English Translation**: **m System info 1**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN dashboard CAN comfort CAN infotainment

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `SY1_CAN_Extern` | **SY1_CAN_external** | Bit 0, 1b, Intel | Scale: 1.0 | `0`: CAN externally separated<br>`1`: CAN externally connected |
| `SY1_Diag_Antrieb` | **SY1_Diag_drive** | Bit 1, 1b, Intel | Scale: 1.0 | `1`: CAN drive in diagnosis<br>`0`: z Currently no drive diagnosis |
| `SY1_Sleep_Komfort` | **SY1_Sleep_comfort**<br>*Note: CAN comfort network is sleeping* | Bit 2, 1b, Intel | Scale: 1.0 | `1`: Bus rest<br>`0`: no bus rest |
| `SY1_Diag_Komfort` | **SY1_Diag_Comfort** | Bit 3, 1b, Intel | Scale: 1.0 | `1`: Diagnostic request detected in CAN Comf<br>`0`: z Currently no comfort diagnosis |
| `SY1_Sleep_Infotainment` | **SY1_Sleep_Infotainment**<br>*Note: CAN-Infotainment-Netzwerk schlft* | Bit 4, 1b, Intel | Scale: 1.0 | `1`: Bus rest<br>`0`: no bus rest |
| `SY1_Diag_Infotainment` | **SY1_Diag_infotainment** | Bit 5, 1b, Intel | Scale: 1.0 | `0`: currently no infotainment diagnosis<br>`1`: Diagnostic request detected in CAN info |
| `SY1_Infotainment` | **SY1_infotainment**<br>*Note: the CAN infotainment is physically separated from the CAN convenience* | Bit 6, 1b, Intel | Scale: 1.0 | `1`: installed<br>`0`: not installed |
| `SY1_Verbauliste_gueltig` | **SY1_installation_list_valid**<br>*Note: Invalid means: Installation information is not yet complete: Gateway not coded* | Bit 7, 1b, Intel | Scale: 1.0 | `1`: valid<br>`0`: invalid |
| `SY1_Klasse` | **SY1_class** | Bit 8, 4b, Intel | Scale: 1.0 | `8`: LT class<br>`3`: A class<br>`9`: L class<br>`1`: A00_class<br>`7`: T class<br>`4`: B class<br>`5`: C class<br>`2`: A0_class<br>`6`: D class<br>`0`: A000_class |
| `SY1_Marke` | **SY1_brand** | Bit 12, 4b, Intel | Scale: 1.0 | `6`: Lamborghini<br>`5`: Bugatti<br>`3`: SK Skoda<br>`0`: VW Volkswagen<br>`7`: Bentley<br>`8`: Rolls-Royce<br>`14`: ford<br>`1`: AU Audi<br>`2`: SE_Seat<br>`15`: Porsche<br>`4`: VN VW commercial vehicle |
| `SY1_Derivat` | **SY1_derivative** | Bit 16, 4b, Intel | Scale: 1.0 | `7`: City Van Pick Up<br>`3`: Hatchback<br>`6`: Off-road<br>`2`: Variant<br>`1`: Notchback utility<br>`5`: Convertible Roadstar Spider<br>`0`: Short tail Multivan<br>`15`: not known<br>`8`: MPV<br>`9`: Other<br>`4`: Coupe sports car |
| `SY1_Generation` | **SY1_generation** | Bit 20, 4b, Intel | Scale: 1.0 | - |
| `SY1_Erweiterung` | **SY1_extension**<br>*Note: Currently not supported in the PQ35/46: 15d for 'not known' is issued* | Bit 24, 4b, Intel | Scale: 1.0 | `5`: open structures<br>`15`: not known<br>`8`: High roof<br>`2`: modified front rear<br>`7`: Flat roof<br>`9`: Other<br>`6`: closed structures<br>`4`: High motorization<br>`3`: Syncro<br>`0`: short wheelbase<br>`1`: langer_Radstand |
| `SY1_Rechtslenker` | **SY1_right-hand_drive** | Bit 28, 1b, Intel | Scale: 1.0 | `0`: Linkslenker<br>`1`: Right-hand drive |
| `SY1_Viertuerer` | **SY1_four-door** | Bit 29, 1b, Intel | Scale: 1.0 | `1`: Four doors or more<br>`0`: Kleiner_vier_Tueren |
| `SY1_Transportmode` | **SY1_transport_mode**<br>*Note: 1 = transport mode active, functional restrictions or changes for vehicle transport* | Bit 30, 1b, Intel | Scale: 1.0 | `0`: nicht_aktiv<br>`1`: active |
| `SY1_KD_Fehler` | **SY1_KD_error**<br>*Note: If the bit is set, at least one KD error is stored under the gateway address* | Bit 31, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `SY1_VersLowCAN_Komfort` | **SY1_Vers_Low_CAN_comfort** | Bit 32, 4b, Intel | Scale: 1.0 | - |
| `SY1_VersHighCAN_Komfort` | **SY1_VersHighCAN_Komfort** | Bit 36, 4b, Intel | Scale: 1.0 | - |
| `SY1_VersLowCAN_Antrieb` | **SY1_VersLowCAN_Antrieb** | Bit 40, 4b, Intel | Scale: 1.0 | - |
| `SY1_VersHighCAN_Antrieb` | **SY1_Vers_High_CAN_drive** | Bit 44, 4b, Intel | Scale: 1.0 | - |
| `SY1_Relais_FAS_Zweig` | **SY1_relay_FAS_branch** | Bit 48, 2b, Intel | Scale: 1.0 | `0`: Relay closed<br>`3`: reserved<br>`1`: Relay opened as planned<br>`2`: Relay opened in case of error |
| `SY1_ELV_Lock_Supply` | **SY1_ELV_Lock_Supply**<br>*Note: Gateway provides an additional release for the ELV (electric steering wheel lock) (currently only PQ46)* | Bit 50, 1b, Intel | Scale: 1.0 | `0`: no release<br>`1`: Release |
| `SY1_QRS_Messmodus` | **SY1_QRS_measurement_mode** | Bit 51, 1b, Intel | Scale: 1.0 | `1`: QRS on<br>`0`: QRS off |
| `SY1_NWDF_gueltig` | **SY1_NWDF_valid**<br>*Note: Validity of network diagnostics enable (byte 7, bit 7)* | Bit 54, 1b, Intel | Scale: 1.0 | `1`: NWDF_Fkt_unterstuetzt<br>`0`: NWDF function not supported |
| `SY1_NWDF` | **SY1_NWDF**<br>*Note: Network diagnostics Release for central activation of network diagnostics* | Bit 55, 1b, Intel | Scale: 1.0 | `1`: Monitoring released<br>`0`: Monitoring not released |
| `SY1_Notbrems_Status` | **SY1_emergency_brake_status** | Bit 56, 1b, Intel | Scale: 1.0 | `0`: keine_Notbremsung<br>`1`: Emergency braking situation |

---

## Message: `mGateway_3` (0x653 / 1619 Dec)
- **English Translation**: **m Gateway 3**
- **Log Frequency**: 22 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 3

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `GW3_Laendervariante` | **GW3_country_variant** | Bit 0, 6b, Intel | Scale: 1.0 | `6`: Saudi Arabia<br>`5`: Japan<br>`0`: Germany<br>`7`: Australia<br>`3`: Kanada<br>`1`: Europe<br>`2`: USA<br>`4`: Great Britain |
| `GW3_Alt_3_Kombi` | **GW3_Obsolete_3_station_wagon** | Bit 6, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GW3_Land_Sprach_empf` | **GW3_Country_Language_recommended**<br>*Note: The countries and language variants are taken from the embassy in combination 3. Since the values ​​in their source message are sent as multiplex information, this bit indicates that the content is not the init value, but rather the information read correctly* | Bit 7, 1b, Intel | Scale: 1.0 | `0`: Content not received<br>`1`: Currently received |
| `GW3_Sprachvariante` | **GW3_Sprachvariante** | Bit 8, 8b, Intel | Scale: 1.0 | `4`: Italienisch<br>`0`: no language variant<br>`6`: Portuguese<br>`11`: Dutch<br>`10`: US English<br>`9`: Chinese<br>`1`: German<br>`5`: Spanish<br>`2`: English<br>`12`: Japanese<br>`13`: Russian<br>`15`: French Canadian<br>`14`: Korean<br>`8`: Czech<br>`3`: French<br>`16`: Swedish<br>`18`: Turkish<br>`17`: Polish |
| `GW3_Motortyp` | **GW3_engine_type** | Bit 16, 6b, Intel | Scale: 1.0 | - |
| `GW3_Alt_5_Motor` | **GW3_Obsolete_5_engine**<br>*Note: outdated signals from message motor 5* | Bit 22, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `GW3_Motortyp_empf` | **GW3_engine_type_recommended** | Bit 23, 1b, Intel | Scale: 1.0 | `1`: Currently received<br>`0`: Content not received |

---

## Message: `mSollverbau_neu` (0x655 / 1621 Dec)
- **English Translation**: **mSollverbau_neu**
- **Log Frequency**: 22 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN dashboard CAN comfort CAN infotainment

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `VBN_Motor_A` | **VBN Engine A**<br>*Note: always 1! (Engine control unit always installed)* | Bit 0, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Getriebe_A` | **VBN gearbox A**<br>*Note: Target installation of transmission control unit* | Bit 1, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Bremse_A` | **VBN brake A**<br>*Note: Target installation of ABS for bad road information* | Bit 2, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Kombi_A` | **VBN station wagon A**<br>*Note: 1 = Kombi am Antriebs-CAN verbaut* | Bit 3, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_LSM_A` | **VBN LSM A**<br>*Note: Target steering angle* | Bit 4, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Airbag_A` | **VBN_Airbag_A** | Bit 5, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Lenkhilfe_A` | **VBN_Lenkhilfe_A** | Bit 6, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_dyn_LWR_A` | **VBN dyn LWR A**<br>*Note: Dynamic headlight range control / AFS* | Bit 7, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Niveau_A` | **VBN level A**<br>*Note: Level control on the CAN drive* | Bit 8, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Allrad_A` | **VBN all-wheel drive A** | Bit 9, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_ADR_Sensor_A` | **VBN ADR Sensor A**<br>*Note: Target installation of ADR control unit* | Bit 10, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_ADR_getrennt` | **VBN ADR separated** | Bit 11, 1b, Intel | Scale: 1.0 | `1`: ADR separate<br>`0`: ADR connected |
| `VBN_Parkbremse_A` | **VBN parking brake A**<br>*Note: Parking brake on the CAN drive or brake SUB-CAN* | Bit 12, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_EZS_A` | **VBN EZS A**<br>*Note: EZS control unit* | Bit 13, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Daempfer_A` | **VBN damper A**<br>*Note: Damper SG on the CAN drive* | Bit 14, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Quersperre` | **VBN cross barrier**<br>*Note: Cross lock in the CAN drive network* | Bit 15, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Motor_Slave_A` | **VBN Motor Slave A**<br>*Note: Motor slave in the CAN drive network* | Bit 16, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_SWA_A` | **VBN SWA A**<br>*Note: SWA lane change assistant* | Bit 17, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_LDW_A` | **VBN LDW A**<br>*Note: LDW / Heading Control on the drive train* | Bit 18, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_RKA_Plus_A` | **VBN RKA Plus A**<br>*Note: RKA-SG (RKA Plus) on the CAN drive* | Bit 19, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_PLA_A` | **VBN PLA A**<br>*Note: PDC / Park steering assistant on the drive train* | Bit 20, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_WFS_KBI` | **VBN WFS KBI**<br>*Note: 1 = Immobilizer on the combination CAN or drive CAN* | Bit 21, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Kombi_KBI` | **VBN station wagon KBI**<br>*Note: 1 = Combi installed on the combination CAN* | Bit 22, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Soll_Ist_OK` | **VBN_Soll_Ist_OK** | Bit 23, 1b, Intel | Scale: 1.0 | `1`: Target installation equals actual installation<br>`0`: Sollverbau_ungleich_Istverbau |
| `VBN_BSG_K` | **VBN BSG K**<br>*Note: Target installation BSG comfort or ILM comfort* | Bit 24, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_KSG_K` | **VBN KSG K**<br>*Note: Target installation ZKE* | Bit 25, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_TSG_FT_K` | **VBN TSG FT K**<br>*Note: Target installation TSG FT* | Bit 26, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_TSG_BT_K` | **VBN TSG BT K**<br>*Note: Sollverbau TSG_BT* | Bit 27, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_TSG_HL_K` | **VBN TSG HL K**<br>*Note: Target installation TSG HL* | Bit 28, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_TSG_HR_K` | **VBN TSG HR K**<br>*Note: Target installation TSG HR* | Bit 29, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Memory_K` | **VBN Memory K**<br>*Note: Target installation memory* | Bit 30, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Dachmodul_K` | **VBN roof module K** | Bit 31, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Zentralelektrik_II_K` | **VBN central electrics II K**<br>*Note: Target installation of central electrics 2 on the CAN comfort* | Bit 32, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_RDK_K` | **VBN RDK K**<br>*Note: Target tire pressure* | Bit 33, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_SMLS_K` | **VBN SMLS K**<br>*Note: Target installation of steering column module/multifunction steering wheel* | Bit 34, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Gateway_K` | **VBN Gateway K**<br>*Note: Target installation of gateway module on the CAN comfort* | Bit 35, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Clima_K` | **VBN Clima K**<br>*Note: Target installation of climate control on the CAN comfort* | Bit 36, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_APS_K` | **VBN APS K**<br>*Note: Sollverbau Einparkhilfe* | Bit 37, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_PTC_Heizung_K` | **VBN PTC Heater K**<br>*Note: 1 = PTC-Heizung verbaut* | Bit 38, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Standhzg_K` | **VBN Standhzg K**<br>*Note: Target installation, auxiliary heating on comfort or infotainment* | Bit 39, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_VSG_K` | **VBN VSG K**<br>*Note: Target installation of convertible top control unit* | Bit 40, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_RSE_I` | **VBN RSE I**<br>*Note: Target installation of rear seat entertainment* | Bit 41, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Wischer_K` | **VBN_Wischer_K** | Bit 42, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_MDI_I` | **VBN MDI I**<br>*Note: Target mobile device interface* | Bit 43, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_AAG_K` | **VBN AAG K**<br>*Note: Target installation of trailer module* | Bit 44, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Mem_BF_K` | **VBN Mem Passenger K**<br>*Note: Target installation of passenger seat memory* | Bit 45, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Easy_Entry_VF` | **VBN Easy Entry VF**<br>*Note: Target installation for Easy Entry driver* | Bit 46, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Easy_Entry_VB` | **VBN Easy Entry VB**<br>*Note: Easy entry passenger* | Bit 47, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Heckdeckel_K` | **VBN trunk lid K**<br>*Note: Verbau des Heckdeckel-Steuergeraetes* | Bit 48, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Rearview_I` | **VBN_Rearview_I**<br>*Note: Target installation, rear view on the infotainment* | Bit 49, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Sonderfahrzeug_SG_K` | **VBN_Sonderfahrzeug_SG_K**<br>*Note: Special vehicle SG* | Bit 50, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Tastenmodul_I` | **VBN key module I**<br>*Note: Target installation of a 10-key keyboard on the CAN infotainment* | Bit 51, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Kompass_I` | **VBN_Kompass_I**<br>*Note: Target installation of compass on CAN infotainment* | Bit 52, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_WFS_K` | **VBN WFS K**<br>*Note: 1 = Wegfahrsperre am CAN-Komfort verbaut* | Bit 53, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_GSM_Pager_I` | **VBN GSM Pager I**<br>*Note: Target installation of GSM pager on CAN infotainment* | Bit 54, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_InfoElektronik` | **VBN Info Electronics**<br>*Note: Target installation of infotainment cockpit on CAN comfort* | Bit 55, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_DSP_I` | **VBN DSP I**<br>*Note: Target installation of DSP on the CAN infotainment* | Bit 56, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_DAB_I` | **VBN DAB I**<br>*Note: Should also be installed for SDARS tuners* | Bit 57, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Telematik_I` | **VBN Telematics I**<br>*Note: Target installation of telematics on the CAN infotainment* | Bit 58, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Navigation_I` | **VBN Navigation I** | Bit 59, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_TV_Tuner_I` | **VBN_TV_Tuner_I**<br>*Note: Target installation of TV tuner on CAN infotainment* | Bit 60, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Neigungsmodul_I` | **VBN inclination module I**<br>*Note: Sollverbau Neigungsmodul am CAN-Infotainment* | Bit 61, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Radio_I` | **VBN Radio I** | Bit 62, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |
| `VBN_Telefon_I` | **VBN Telephone I**<br>*Note: Target installation of telephone on CAN infotainment* | Bit 63, 1b, Intel | Scale: 1.0 | `0`: no target construction<br>`1`: Sollverbau |

---

## Message: `mBEM_02` (0x658 / 1624 Dec)
- **English Translation**: **m BEM 02**
- **Log Frequency**: 107 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `BEM_02_Abschaltstufen` | **BEM 02 shutdown levels** | Bit 0, 3b, Intel | Scale: 1.0 | `1`: Stage1<br>`2`: Stage2<br>`0`: Level0<br>`3`: Stage3 |
| `BEM_STH_Zielzeit` | **BEM STH target time**<br>*Note: Maximal mgliche Zeit fr den Standheizungsbetrieb, um die Startfhigkeit nicht zu gefhrden* | Bit 3, 4b, Intel | Scale: 5.0, Unit: 'Unit_Minut' | `14`: Init<br>`15`: Mistake |
| `BEM_MMI_Vorwarnung` | **BEM MMI advance warning**<br>*Note: Display pre-warning MMI shutdown (initialization value from EEprom)* | Bit 7, 1b, Intel | Scale: 1.0 | `0`: no display<br>`1`: MMI advance warning |
| `BEM_HL_Kontingentierung` | **BEM HL quota**<br>*Note: Performance quotas for heating systems* | Bit 8, 6b, Intel | Scale: 50.0, Offset: -1000.0, Unit: 'Unit_Watt' | - |
| `BEM_Generatordiagnose` | **BEM generator diagnosis** | Bit 16, 2b, Intel | Scale: 1.0 | `1`: Load control on<br>`2`: Generator def<br>`0`: no display |
| `BEM_Red_Innengeblaese` | **BEM Red internal fan** | Bit 18, 2b, Intel | Scale: 1.0 | `3`: Compressor shutdown<br>`0`: no reduction<br>`1`: Reduction level 1<br>`2`: Reduction level 2 |
| `BEM_STH_Einschaltverbot` | **BEM STH switching on ban** | Bit 20, 1b, Intel | Scale: 1.0 | `0`: full availability<br>`1`: cannot be activated |
| `BEM_HL_Regelung_Status` | **BEM HL regulation status** | Bit 21, 3b, Intel | Scale: 1.0 | `3`: Regulation level 3<br>`1`: Regulation level 1<br>`4`: VNA<br>`7`: default<br>`0`: Control inactive<br>`2`: Regulation level 2 |
| `BEM_Ladezustand` | **BEM_Ladezustand**<br>*Note: Display of the SOC in bar graph* | Bit 24, 4b, Intel | Scale: 10.0, Unit: 'Unit_PerCent' | `14`: Init<br>`15`: Mistake |
| `BEM_Batteriediagnose` | **BEM battery diagnostics** | Bit 28, 3b, Intel | Scale: 1.0 | `2`: Battery detected<br>`1`: no release start stop<br>`3`: Battery weak<br>`0`: no display |
| `BEM_DFM` | **BEM_DFM**<br>*Note: Generator utilization level, sent from the generator to the gateway via LIN. The engine control unit regulates the PTC based on this signal, and the energy management in the BSG/BCM calculates the on-board network utilization* | Bit 32, 5b, Intel | Scale: 3.225, Offset: 0.025, Unit: 'Unit_PerCent' | - |
| `BEM_REK_aktiv` | **BEM REK active** | Bit 37, 1b, Intel | Scale: 1.0 | `0`: no recu release<br>`1`: Reku_Freigabe |
| `BEM_EMLIN_ungueltig` | **BEM_EMLIN_ungueltig** | Bit 38, 1b, Intel | Scale: 1.0 | `0`: Signals valid<br>`1`: Signals invalid |
| `BEM_Batt_Ab` | **BEM Batt Ab** | Bit 39, 1b, Intel | Scale: 1.0 | `0`: verbunden<br>`1`: not connected |
| `BEM_UBDM` | **BEM_UBDM**<br>*Note: Batteriespannung, gemessen vom Batteriedatenmodul* | Bit 40, 8b, Intel | Scale: 0.05, Offset: 5.0, Unit: 'Unit_Volt' | - |
| `BEM_UGenSoll` | **BEM UGen Should**<br>*Note: Target voltage specification for the generator, includes temperature-optimized battery charging and recuperation* | Bit 48, 6b, Intel | Scale: 0.1, Offset: 10.6, Unit: 'Unit_Volt' | `63`: Mistake |

---

## Message: `mDiagnose_1` (0x65D / 1629 Dec)
- **English Translation**: **m diagnosis 1**
- **Log Frequency**: 10 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN dashboard CAN comfort CAN infotainment

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `DN1_Verlernzaehler` | **DN1_unlearning_counter** | Bit 0, 8b, Intel | Scale: 1.0 | `255`: Mistake |
| `DN1_KM_Stand` | **DN1_KM_status**<br>*Note: Mileage* | Bit 8, 20b, Intel | Scale: 1.0, Unit: 'Unit_KiloMeter' | - |
| `DN1_Jahr` | **DN1_year** | Bit 28, 7b, Intel | Scale: 1.0, Offset: 2000.0, Unit: 'Unit_Year' | - |
| `DN1_Monat` | **DN1_month** | Bit 35, 4b, Intel | Scale: 1.0, Unit: 'Unit_Month' | `14`: relative date<br>`15`: Special case<br>`13`: invalid<br>`0`: invalid |
| `DN1_Tag` | **DN1_day** | Bit 39, 5b, Intel | Scale: 1.0, Unit: 'Unit_Day' | - |
| `DN1_Stunde` | **DN1_hour**<br>*Note: 18h - 1Fh ungueltig* | Bit 44, 5b, Intel | Scale: 1.0, Unit: 'Unit_Hours' | `31`: invalid<br>`26`: invalid<br>`28`: invalid<br>`30`: invalid<br>`29`: invalid<br>`25`: invalid<br>`24`: invalid<br>`27`: invalid |
| `DN1_Minute` | **DN1_minute**<br>*Note: 3 Ch - 3 Fh invalid* | Bit 49, 6b, Intel | Scale: 1.0, Unit: 'Unit_Minut' | `62`: invalid<br>`63`: invalid<br>`60`: invalid<br>`61`: invalid |
| `DN1_Sekunde` | **DN1_second**<br>*Note: 3 Ch - 3 Fh invalid* | Bit 55, 6b, Intel | Scale: 1.0, Unit: 'Unit_Secon' | `62`: invalid<br>`63`: invalid<br>`60`: invalid<br>`61`: invalid |
| `DN1_alt_Kilometerstand` | **DN1_Outdated_mileage** | Bit 62, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |
| `DN1_alt_Zeit` | **DN1_Obsolete_time** | Bit 63, 1b, Intel | Scale: 1.0 | `1`: veraltet<br>`0`: currently received |

---

## Message: `mFzg_Ident` (0x65F / 1631 Dec)
- **English Translation**: **m Vehicle Ident**
- **Log Frequency**: 53 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8
- **Description**: CAN comfort

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `FI1_MUX` | **FI1_MUX** | Bit 0, 2b, Intel | Scale: 1.0 | - |
| `FI1_Geheimnis_1` | **FI1_Geheimnis_1** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_4` | **FI1_VIN_4** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_11` | **FI1_VIN_11** | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `FI1_Geheimnis_2` | **FI1_Secret_2** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_5` | **FI1_VIN_5** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_12` | **FI1_VIN_12** | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `FI1_Geheimnis_3` | **FI1_Secret_3** | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_6` | **FI1_VIN_6** | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_13` | **FI1_VIN_13** | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `FI1_Geheimnis_4` | **FI1_Secret_4** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_7` | **FI1_VIN_7** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_14` | **FI1_VIN_14** | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_1` | **FI1_VIN_1** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_8` | **FI1_VIN_8** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_15` | **FI1_VIN_15** | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_2` | **FI1_VIN_2** | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_9` | **FI1_VIN_9** | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_16` | **FI1_VIN_16** | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_3` | **FI1_VIN_3** | Bit 56, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_10` | **FI1_VIN_10** | Bit 56, 8b, Intel | Scale: 1.0 | - |
| `FI1_VIN_17` | **FI1_VIN_17** | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mRadio_4` (0x661 / 1633 Dec)
- **English Translation**: **m Radio 4**
- **Log Frequency**: 10 occurrences
- **Sender**: `Radio_2DIN` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `RA4_Radio_on` | **RA4_radio_on** | Bit 0, 1b, Intel | Scale: 1.0 | - |
| `RA4_Show_Radio` | **RA4_Show_Radio** | Bit 1, 1b, Intel | Scale: 1.0 | - |
| `RA4_Radio_mute` | **RA4_radio_mute**<br>*Note: Provision for NF request* | Bit 2, 1b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Master_locked` | **RA4_Radio_Master_locked** | Bit 3, 1b, Intel | Scale: 1.0 | - |
| `RA4_VNC_OFF` | **RA4_VNC_OFF** | Bit 4, 1b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Surround` | **RA4_Radio_Surround**<br>*Note: vorher RA4_Radio_Surround_OFF (1 = Surround ausgeschaltet)* | Bit 5, 1b, Intel | Scale: 1.0 | `0`: inactive<br>`1`: active |
| `RA4_Radio_Wake_Up_Komfort` | **RA4_Radio_Wake_Up_Comfort**<br>*Note: Wake up the comfort CAN* | Bit 6, 1b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Error_flag` | **RA4_Radio_Error_flag**<br>*Note: Fehlereintrag vorhanden* | Bit 7, 1b, Intel | Scale: 1.0 | `1`: Error memory entry<br>`0`: no error memory entry |
| `RA4_Radio_Mode` | **RA4_radio_mode**<br>*Note: Fashion information* | Bit 8, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para1` | **RA4_Radio_Para1**<br>*Note: Parameters of the respective mode* | Bit 16, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para2` | **RA4_Radio_Para2**<br>*Note: Parameters of the respective mode* | Bit 24, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para3` | **RA4_Radio_Para3**<br>*Note: Parameters of the respective mode* | Bit 32, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para4` | **RA4_Radio_Para4**<br>*Note: Parameters of the respective mode* | Bit 40, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para5` | **RA4_Radio_Para5**<br>*Note: Proviso* | Bit 48, 8b, Intel | Scale: 1.0 | - |
| `RA4_Radio_Para6` | **RA4_Radio_Para6**<br>*Note: Proviso* | Bit 56, 8b, Intel | Scale: 1.0 | - |

---

## Message: `mTp_NSL_KOM` (0x6C0 / 1728 Dec)
- **English Translation**: **m Tp NSL COM**
- **Log Frequency**: 11 occurrences
- **Sender**: `Vector__XXX` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `DISP_NSL_KOM` | **DISP NSL COM** | Bit 0, 64b, Intel | Scale: 1.0 | - |

---

## Message: `mTp_KOM_NSL` (0x6C1 / 1729 Dec)
- **English Translation**: **m Tp KOM NSL**
- **Log Frequency**: 11 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `DISP_KOM_NSL` | **DISP COM NSL** | Bit 0, 64b, Intel | Scale: 1.0 | - |

---

## Message: `mTp_TM_KOM` (0x6C2 / 1730 Dec)
- **English Translation**: **m Tp TM COM**
- **Log Frequency**: 105 occurrences
- **Sender**: `Vector__XXX` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `DISP_TM_KOM` | **DISP TM COM** | Bit 0, 64b, Intel | Scale: 1.0 | - |

---

## Message: `BAP_Clima` (0x6DB / 1755 Dec)
- **English Translation**: **BAP_Clima**
- **Log Frequency**: 12 occurrences
- **Sender**: `Gateway_PQ35` | **DLC**: 8

| German Signal Name | English Translation | Details (Bit/Len/Endian) | Scale/Offset/Unit | Values/States |
|---|---|---|---|---|
| `BAP_Data_Clima` | **BAP Data Climate**<br>*Note: FSG: Clima => ASG: RNS, Radio* | Bit 0, 16b, Intel | Scale: 1.0 | - |

---
