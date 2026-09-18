#!/usr/bin/env python3
"""Profile-driven CAN and diagnostic logging for Hudiy DataView.

The logger is deliberately independent of Flask and the DataView UI.  A profile
decides which messages it accepts, how they update state, and when a CSV row is
emitted.  This keeps today's Haldex-oriented fused log while allowing future
DataView screens to register purpose-built profiles without another service.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import queue
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

try:
    import zmq
except ImportError:  # Decoding and profile tests do not require the Pi capture runtime.
    zmq = None


logger = logging.getLogger(__name__)

HALDEX_STATE_ID = 0x6DA
HALDEX_YAW_ID = 0x679
HALDEX_MODE_COMMAND_ID = 0x67A
MODE_NAMES = {0: "Stock", 1: "Performance", 2: "Competition"}

# Gateway/navigation messages actually present in PQ35_46_ICAN.dbc.
ICAN_BRAKES_TRANSMISSION_ID = 0x359
ICAN_GATEWAY_SPEED_ID = 0x351
ICAN_ENGINE_ID = 0x35B
ICAN_STEERING_ID = 0x3C3
ICAN_NAVIGATION_YAW_ID = 0x2A1
ICAN_AMBIENT_ID = 0x527
ICAN_ENGINE_AUX_ID = 0x555

META_COLUMNS = (
    "timestamp", "datetime", "event_marker", "source", "can_id",
)


def _raw_key(can_id: int) -> str:
    return f"raw_0x{can_id:03x}"


def _decode_ican_brakes_transmission(data: bytes) -> Dict[str, Any]:
    if len(data) < 8:
        return {}
    bits = int.from_bytes(data[:8], "little")
    return {
        "vehicle_speed_kmh": round(((bits >> 9) & 0x7FFF) * 0.01, 2),
        "vehicle_speed_from_abs": (bits >> 8) & 0x01,
        "front_axle_path_pulses": (bits >> 24) & 0x07FF,
        "path_pulse_status": (bits >> 35) & 0x01,
        "path_pulse_error": (bits >> 39) & 0x01,
        "path_pulses_per_revolution": (bits >> 40) & 0x3F,
        "brake_light_switch": (bits >> 47) & 0x01,
        "abs_active": (bits >> 50) & 0x01,
        "esp_active": (bits >> 58) & 0x01,
        "selector_position": (bits >> 60) & 0x0F,
    }


def _decode_ican_gateway_speed(data: bytes) -> Dict[str, Any]:
    if len(data) < 3:
        return {}
    bits = int.from_bytes(data[:3], "little")
    return {"gateway_vehicle_speed_kmh": round(((bits >> 9) & 0x7FFF) * 0.01, 2)}


def _decode_ican_steering(data: bytes) -> Dict[str, Any]:
    if len(data) < 4:
        return {}

    def signed_measurement(raw: int) -> float:
        value = (raw & 0x7FFF) * 0.04375
        return round(-value if raw & 0x8000 else value, 2)

    angle, rate = struct.unpack("<HH", data[:4])
    return {
        "steer_angle_deg": signed_measurement(angle),
        "steer_rate_deg_s": signed_measurement(rate),
    }


def _decode_ican_engine(data: bytes) -> Dict[str, Any]:
    if len(data) < 5:
        return {}
    return {
        "engine_rpm": round(struct.unpack("<H", data[1:3])[0] * 0.25, 1),
        "engine_coolant_c": round(data[3] * 0.75 - 48.0, 1),
        "engine_brake_switch": data[4] & 0x01,
    }


def _decode_ican_navigation_yaw(data: bytes) -> Dict[str, Any]:
    if len(data) < 2:
        return {}
    raw = (data[0] | (data[1] << 8)) & 0x3FFF
    invalid = raw == 0x3FFF or bool(data[1] & 0x40)
    value = raw * 0.01
    return {
        "measured_yaw_rate_deg_s": "" if invalid else round(value if data[1] & 0x80 else -value, 2),
        "measured_yaw_valid": int(not invalid),
    }


def _decode_ican_ambient(data: bytes) -> Dict[str, Any]:
    if len(data) < 6:
        return {}
    return {"ambient_temp_c": round(data[5] * 0.5 - 50.0, 1)}


def _decode_ican_engine_aux(data: bytes) -> Dict[str, Any]:
    if len(data) < 8:
        return {}
    return {
        "boost_pressure_mbar": float(data[4] * 20),
        "engine_oil_temp_c": float(data[7] - 60),
    }


def _decode_haldex_yaw(data: bytes) -> Dict[str, Any]:
    if len(data) != 8:
        return {}
    model_yaw, proactive, pre_refgen, torque = struct.unpack("<hHHH", data[:8])
    return {
        "model_yaw_raw": model_yaw,
        "model_yaw_deg_s": round(model_yaw / 17.87, 3),
        "c06_proactive_ref": proactive,
        "c22_pre_refgen": pre_refgen,
        "b08_torque_nm": round(torque * 0.0625, 2),
    }


def _decode_haldex_state(data: bytes) -> Dict[str, Any]:
    if len(data) != 8 or data[0] & 0xF8 != 0xD0:
        return {}
    page = data[0] & 0x07
    if page > 6:
        return {}
    status = data[1]
    words = struct.unpack("<HHH", data[2:8])

    def signed(raw: int) -> int:
        return raw - 0x10000 if raw & 0x8000 else raw

    decoded: Dict[str, Any] = {
        "haldex_page": page,
        "haldex_page_rate_hz": 12.5 if page == 1 else 6.25,
        "haldex_mode": status & 0x03,
        "haldex_mode_name": MODE_NAMES.get(status & 0x03, str(status & 0x03)),
        "haldex_selector_b1cc": (status >> 2) & 0x07,
        "haldex_force_zero_a78": (status >> 5) & 0x01,
        "haldex_token_ok": (status >> 6) & 0x01,
        "haldex_abs_braking": (status >> 7) & 0x01,
    }
    if page == 0:
        ceiling, reference, slip = words
        decoded.update({
            "a72_ceiling_nm": round(ceiling * 0.0625, 2),
            "a74_ref_torque_nm": round(reference * 0.0625, 2),
            "a7c_slip_torque_nm": round(slip * 0.0625, 2),
        })
    elif page == 1:
        measured_yaw = signed(words[2])
        decoded.update({
            "c9e_demanded_accel_raw": signed(words[0]),
            "c9c_actual_accel_raw": signed(words[1]),
            "haldex_measured_yaw_raw": measured_yaw,
            "haldex_measured_yaw_deg_s": round(measured_yaw / 17.87, 3),
        })
    elif page == 2:
        decoded.update({
            "b26_lateral_feedforward_raw": signed(words[0]),
            "bc4_curvature_raw": words[1],
            "bb6_computed_axle_slip_raw": signed(words[2]),
        })
    elif page == 3:
        decoded.update({
            "wheel_vl_kmh": round(words[0] * 0.01, 2),
            "wheel_vr_kmh": round(words[1] * 0.01, 2),
            "wheel_hl_kmh": round(words[2] * 0.01, 2),
        })
    elif page == 4:
        decoded.update({
            "wheel_hr_kmh": round(words[0] * 0.01, 2),
            "lat_accel_measured_raw": signed(words[1]),
            "haldex_throttle_raw": words[2] & 0xFF,
            "haldex_bls_raw": (words[2] >> 8) & 0xFF,
        })
    elif page == 5:
        decoded.update({
            "hold_a7e_timer": words[0],
            "c10_liftoff_hold_raw": words[1],
            "cd4_axle_ratio_adaptation_raw": signed(words[2]),
        })
    elif page == 6:
        decoded.update({
            "c3a_slip_energy_raw": words[0],
            "c26_energy_ceiling_raw": words[1],
            "afe_fault_ceiling_raw": words[2],
        })
    return decoded


Decoder = Callable[[bytes], Dict[str, Any]]


@dataclass(frozen=True)
class MeasuringGroup:
    """One TP2/KWP measuring group the logger owns while recording."""

    module: int
    group: int
    priority: str = "normal"
    value_count: int = 4

    @property
    def key(self) -> str:
        return f"m{self.module:02x}_g{self.group}"


@dataclass(frozen=True)
class LogProfile:
    """Declarative description of a CSV logging use case."""

    name: str
    description: str
    columns: Sequence[str]
    can_decoders: Mapping[int, Decoder]
    snapshot_can_ids: frozenset[int]
    raw_can_ids: frozenset[int]
    measuring_groups: tuple[MeasuringGroup, ...] = ()
    include_diagnostics: bool = True
    capture_all_can: bool = False
    event_rows: bool = False

    @property
    def can_ids(self) -> frozenset[int]:
        return frozenset(self.can_decoders) | self.raw_can_ids | self.snapshot_can_ids


DEFAULT_HALDEX_MEASURING_GROUPS: tuple[MeasuringGroup, ...] = ()

HALDEX_CAN_IDS = frozenset({
    HALDEX_YAW_ID, HALDEX_STATE_ID, HALDEX_MODE_COMMAND_ID,
    ICAN_BRAKES_TRANSMISSION_ID, ICAN_GATEWAY_SPEED_ID, ICAN_ENGINE_ID, ICAN_STEERING_ID,
    ICAN_NAVIGATION_YAW_ID, ICAN_AMBIENT_ID, ICAN_ENGINE_AUX_ID,
})

HALDEX_SIGNAL_COLUMNS = (
    "haldex_page", "haldex_page_rate_hz", "haldex_mode", "haldex_mode_name",
    "haldex_selector_b1cc", "haldex_force_zero_a78", "haldex_token_ok",
    "haldex_abs_braking",
    "b08_torque_nm", "a7c_slip_torque_nm", "a74_ref_torque_nm",
    "a72_ceiling_nm", "c06_proactive_ref", "c22_pre_refgen",
    "model_yaw_raw", "model_yaw_deg_s",
    "c9e_demanded_accel_raw", "c9c_actual_accel_raw",
    "haldex_measured_yaw_raw", "haldex_measured_yaw_deg_s",
    "b26_lateral_feedforward_raw", "bc4_curvature_raw",
    "bb6_computed_axle_slip_raw",
    "wheel_vl_kmh", "wheel_vr_kmh", "wheel_hl_kmh", "wheel_hr_kmh",
    "lat_accel_measured_raw", "haldex_throttle_raw", "haldex_bls_raw",
    "hold_a7e_timer", "c10_liftoff_hold_raw", "cd4_axle_ratio_adaptation_raw",
    "c3a_slip_energy_raw", "c26_energy_ceiling_raw", "afe_fault_ceiling_raw",
    "vehicle_speed_kmh", "gateway_vehicle_speed_kmh", "vehicle_speed_from_abs",
    "front_axle_path_pulses", "path_pulse_status", "path_pulse_error",
    "path_pulses_per_revolution", "steer_angle_deg", "steer_rate_deg_s",
    "measured_yaw_rate_deg_s", "measured_yaw_valid", "engine_rpm",
    "boost_pressure_mbar", "engine_coolant_c", "engine_oil_temp_c", "ambient_temp_c",
    "brake_light_switch", "engine_brake_switch", "abs_active", "esp_active",
    "selector_position",
    "diagnostic_data",
)

def _measuring_group_columns(groups: Sequence[MeasuringGroup]) -> tuple[str, ...]:
    columns = []
    for measurement in groups:
        columns.append(f"{measurement.key}_timestamp")
        for index in range(measurement.value_count):
            columns.extend((f"{measurement.key}_i{index}", f"{measurement.key}_i{index}_unit"))
    return tuple(columns)


def _haldex_profile(groups: Sequence[MeasuringGroup]) -> LogProfile:
    groups = tuple(groups)
    return LogProfile(
        name="haldex",
        description="Fused Haldex telemetry, relevant ICAN signals, and selected measuring groups",
        columns=(META_COLUMNS + tuple(_raw_key(can_id) for can_id in sorted(HALDEX_CAN_IDS))
                 + HALDEX_SIGNAL_COLUMNS + _measuring_group_columns(groups)),
        can_decoders={
            HALDEX_YAW_ID: _decode_haldex_yaw,
            HALDEX_STATE_ID: _decode_haldex_state,
            ICAN_BRAKES_TRANSMISSION_ID: _decode_ican_brakes_transmission,
            ICAN_GATEWAY_SPEED_ID: _decode_ican_gateway_speed,
            ICAN_ENGINE_ID: _decode_ican_engine,
            ICAN_STEERING_ID: _decode_ican_steering,
            ICAN_NAVIGATION_YAW_ID: _decode_ican_navigation_yaw,
            ICAN_AMBIENT_ID: _decode_ican_ambient,
            ICAN_ENGINE_AUX_ID: _decode_ican_engine_aux,
        },
        snapshot_can_ids=frozenset({HALDEX_YAW_ID, HALDEX_STATE_ID, HALDEX_MODE_COMMAND_ID}),
        raw_can_ids=HALDEX_CAN_IDS,
        measuring_groups=groups,
    )


HALDEX_PROFILE = _haldex_profile(DEFAULT_HALDEX_MEASURING_GROUPS)

RAW_CAN_PROFILE = LogProfile(
    name="raw_can",
    description="One event row per CAN frame, plus optional diagnostic events",
    columns=META_COLUMNS + ("can_topic", "dlc", "data_hex", "diagnostic_data"),
    can_decoders={},
    snapshot_can_ids=frozenset(),
    raw_can_ids=frozenset(),
    capture_all_can=True,
    event_rows=True,
)


class DataLogger:
    """Owns capture subscriptions and creates one independently writable session at a time."""

    _STOP = object()

    def __init__(self, config: Optional[Mapping[str, Any]] = None,
                 profiles: Iterable[LogProfile] = (HALDEX_PROFILE, RAW_CAN_PROFILE)):
        self.config = dict(config or {})
        settings = self.config.get("data_logger", {})
        zmq_settings = self.config.get("interfaces", {}).get("zmq", {})
        self.can_stream_addr = zmq_settings.get(
            "can_raw_stream", "ipc:///run/rnse_control/can_stream.ipc")
        self.tp2_stream_addr = zmq_settings.get(
            "tp2_stream", "ipc:///run/rnse_control/tp2_stream.ipc")
        self.log_directory = os.path.abspath(os.path.expanduser(
            settings.get("log_directory", "~/logs")))
        self.default_profile = settings.get("default_profile", "haldex")
        self.queue_size = max(100, int(settings.get("queue_size", 10000)))

        self.profiles: Dict[str, LogProfile] = {}
        for profile in profiles:
            self.register_profile(profile)
        configured_groups = settings.get("profiles", {}).get("haldex", {}).get("measuring_groups")
        if configured_groups is not None and "haldex" in self.profiles:
            groups = self._parse_measuring_groups(configured_groups)
            self.profiles["haldex"] = _haldex_profile(groups)
        if self.default_profile not in self.profiles:
            self.default_profile = "haldex"

        self._lock = threading.RLock()
        self._context: Optional[zmq.Context] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._writer_thread: Optional[threading.Thread] = None
        self._write_queue: Optional[queue.Queue] = None
        self._running = False
        self._recording = False
        self._profile = self.profiles[self.default_profile]
        self._state: Dict[str, Any] = {}
        self._output_path = ""
        self._started_at = 0.0
        self._last_error = ""
        self._stats = self._new_stats()

    @staticmethod
    def _parse_int(value: Any) -> int:
        return int(value, 0) if isinstance(value, str) else int(value)

    @classmethod
    def _parse_measuring_groups(cls, entries: Any) -> tuple[MeasuringGroup, ...]:
        if not isinstance(entries, list):
            raise ValueError("data_logger profile measuring_groups must be a list")
        groups = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("Each measuring-group entry must be an object")
            module = cls._parse_int(entry.get("module"))
            value_count = max(1, int(entry.get("value_count", 4)))
            normal = entry.get("groups", [])
            low = entry.get("low_priority_groups", [])
            for priority, values in (("normal", normal), ("low", low)):
                if not isinstance(values, list):
                    raise ValueError("groups and low_priority_groups must be lists")
                for value in values:
                    group = cls._parse_int(value)
                    key = (module, group)
                    if key in seen:
                        raise ValueError(f"Duplicate measuring group {module:#04x}:{group}")
                    seen.add(key)
                    groups.append(MeasuringGroup(module, group, priority, value_count))
        return tuple(groups)

    @staticmethod
    def _new_stats() -> Dict[str, int]:
        return {"frames_received": 0, "rows_written": 0, "markers_logged": 0, "dropped_rows": 0}

    def register_profile(self, profile: LogProfile) -> None:
        if not profile.name or not profile.columns:
            raise ValueError("A logging profile needs a name and CSV columns")
        self.profiles[profile.name] = profile

    def start(self) -> None:
        """Start passive capture. Recording remains off until start_recording()."""
        if zmq is None:
            raise RuntimeError("pyzmq is required for live DataView logging")
        with self._lock:
            if self._running:
                return
            self._running = True
            self._context = zmq.Context()
            self._capture_thread = threading.Thread(
                target=self._capture_worker, name="DataLogger-Capture", daemon=True)
            self._capture_thread.start()

    def close(self) -> None:
        self.stop_recording()
        with self._lock:
            self._running = False
            context = self._context
            capture_thread = self._capture_thread
        if capture_thread and capture_thread.is_alive():
            capture_thread.join(timeout=1.0)
        if context is not None:
            context.term()
        with self._lock:
            self._context = None
            self._capture_thread = None

    def _default_output_path(self, profile_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(self.log_directory, f"{profile_name}_{timestamp}.csv")

    def start_recording(self, profile_name: Optional[str] = None,
                        output_path: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if self._recording:
                raise RuntimeError("A logging session is already recording")
            name = profile_name or self.default_profile
            if name not in self.profiles:
                raise ValueError(f"Unknown logger profile: {name}")
            self._profile = self.profiles[name]
            self._state = {}
            self._stats = self._new_stats()
            self._started_at = time.time()
            self._last_error = ""
            self._output_path = os.path.abspath(os.path.expanduser(
                output_path or self._default_output_path(name)))
            if os.path.exists(self._output_path):
                raise ValueError(f"Refusing to overwrite existing log: {self._output_path}")
            self._write_queue = queue.Queue(maxsize=self.queue_size)
            self._recording = True
            self._writer_thread = threading.Thread(
                target=self._writer_worker,
                args=(self._output_path, self._profile.columns, self._write_queue),
                name="DataLogger-CSV", daemon=True)
            self._writer_thread.start()
            logger.info("Data logger started profile=%s output=%s", name, self._output_path)
            return self.get_status()

    def stop_recording(self) -> Dict[str, Any]:
        with self._lock:
            if not self._recording:
                return self.get_status()
            self._recording = False
            write_queue = self._write_queue
            writer_thread = self._writer_thread
        if write_queue is not None:
            write_queue.put(self._STOP)
        if writer_thread and writer_thread.is_alive():
            writer_thread.join(timeout=5.0)
        with self._lock:
            self._write_queue = None
            self._writer_thread = None
            logger.info("Data logger stopped rows=%d output=%s",
                        self._stats["rows_written"], self._output_path)
            return self.get_status()

    def add_marker(self, note: str) -> bool:
        note = str(note).strip()
        if not note:
            raise ValueError("Marker text cannot be empty")
        with self._lock:
            if not self._recording:
                return False
            self._stats["markers_logged"] += 1
            self._emit_locked(source="marker", event_marker=note)
        return True

    def ingest_can(self, can_id: int, data: bytes, timestamp: Optional[float] = None,
                   topic: str = "") -> None:
        """Ingest a parsed CAN frame. Public to keep capture and tests decoupled."""
        can_id = int(can_id)
        with self._lock:
            if not self._recording:
                return
            profile = self._profile
            if not profile.capture_all_can and can_id not in profile.can_ids:
                return
            self._stats["frames_received"] += 1
            if profile.event_rows:
                self._emit_locked(
                    timestamp=timestamp, source="can", can_id=can_id,
                    extra={"can_topic": topic or f"CAN_{can_id:03X}",
                           "dlc": len(data), "data_hex": data.hex()})
                return

            if can_id in profile.raw_can_ids:
                self._state[_raw_key(can_id)] = data.hex()
            decoder = profile.can_decoders.get(can_id)
            if decoder:
                self._state.update(decoder(data))
            event_marker = ""
            if can_id == HALDEX_MODE_COMMAND_ID and len(data) >= 5:
                mode = data[2]
                event_marker = (
                    f"MODE_CMD_BURST: mode={mode} "
                    f"({MODE_NAMES.get(mode, 'Unknown')}) ctr={data[4]}")
            if can_id in profile.snapshot_can_ids:
                self._emit_locked(timestamp=timestamp, source="can", can_id=can_id,
                                  event_marker=event_marker)

    def ingest_diagnostic(self, diagnostic: Mapping[str, Any],
                          timestamp: Optional[float] = None) -> None:
        with self._lock:
            if not self._recording or not self._profile.include_diagnostics:
                return
            try:
                module = self._parse_int(diagnostic.get("module"))
                group = self._parse_int(diagnostic.get("group"))
            except (TypeError, ValueError):
                return
            configured = {(item.module, item.group): item for item in self._profile.measuring_groups}
            measurement = configured.get((module, group))
            if not self._profile.event_rows and measurement is None:
                return
            values = diagnostic.get("data", [])
            sample_time = float(timestamp) if timestamp is not None else time.time()
            key = f"m{module:02x}_g{group}"
            simplified = []
            for index, item in enumerate(values):
                if not isinstance(item, Mapping):
                    continue
                simplified.append({"value": item.get("value"), "unit": item.get("unit", "")})
                self._state[f"{key}_i{index}"] = item.get("value")
                self._state[f"{key}_i{index}_unit"] = item.get("unit", "")
            self._state[f"{key}_timestamp"] = f"{sample_time:.6f}"
            diagnostics = json.loads(self._state.get("diagnostic_data") or "{}")
            diagnostics[f"{module:02X}:{group}"] = {
                "timestamp": sample_time, "data": simplified,
            }
            encoded = json.dumps(diagnostics, separators=(",", ":"), sort_keys=True)
            self._state["diagnostic_data"] = encoded
            if self._profile.event_rows:
                self._emit_locked(timestamp=sample_time, source="diagnostic",
                                  extra={"diagnostic_data": encoded})

    def _emit_locked(self, timestamp: Optional[float] = None, source: str = "",
                     can_id: Optional[int] = None, event_marker: str = "",
                     extra: Optional[Mapping[str, Any]] = None) -> None:
        if not self._recording or self._write_queue is None:
            return
        sample_time = float(timestamp) if timestamp is not None else time.time()
        row = dict(self._state)
        row.update({
            "timestamp": f"{sample_time:.6f}",
            "datetime": datetime.fromtimestamp(sample_time).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "event_marker": event_marker,
            "source": source,
            "can_id": f"0x{can_id:03X}" if can_id is not None else "",
        })
        if extra:
            row.update(extra)
        try:
            self._write_queue.put_nowait(row)
        except queue.Full:
            self._stats["dropped_rows"] += 1

    def _writer_worker(self, output_path: str, columns: Sequence[str],
                       write_queue: queue.Queue) -> None:
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "x", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                last_flush = time.monotonic()
                pending = 0
                while True:
                    item = write_queue.get()
                    if item is self._STOP:
                        break
                    writer.writerow(item)
                    with self._lock:
                        self._stats["rows_written"] += 1
                    pending += 1
                    now = time.monotonic()
                    if pending >= 50 or now - last_flush >= 1.0:
                        handle.flush()
                        pending = 0
                        last_flush = now
                handle.flush()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._recording = False
            logger.exception("Data logger writer failed")

    @staticmethod
    def _topic_can_id(topic: bytes, message: Mapping[str, Any]) -> Optional[int]:
        arbitration_id = message.get("arbitration_id")
        if arbitration_id is not None:
            try:
                return int(arbitration_id)
            except (TypeError, ValueError):
                pass
        text = topic.decode("ascii", errors="ignore").upper()
        if not text.startswith("CAN_"):
            return None
        value = text[4:]
        if value.startswith("0X"):
            value = value[2:]
        try:
            return int(value, 16)
        except ValueError:
            return None

    def _capture_worker(self) -> None:
        assert self._context is not None
        can_socket = self._context.socket(zmq.SUB)
        diagnostic_socket = self._context.socket(zmq.SUB)
        can_socket.setsockopt(zmq.LINGER, 0)
        diagnostic_socket.setsockopt(zmq.LINGER, 0)
        can_socket.set_hwm(10000)
        diagnostic_socket.set_hwm(1000)
        can_socket.connect(self.can_stream_addr)
        can_socket.subscribe(b"CAN_")
        diagnostic_socket.connect(self.tp2_stream_addr)
        diagnostic_socket.subscribe(b"HUDIY_DIAG")
        poller = zmq.Poller()
        poller.register(can_socket, zmq.POLLIN)
        poller.register(diagnostic_socket, zmq.POLLIN)
        logger.info("Data logger capture connected to %s and %s",
                    self.can_stream_addr, self.tp2_stream_addr)
        try:
            while self._running:
                events = dict(poller.poll(200))
                if can_socket in events:
                    while True:
                        try:
                            topic, payload = can_socket.recv_multipart(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        try:
                            message = json.loads(payload.decode("utf-8"))
                            can_id = self._topic_can_id(topic, message)
                            if can_id is not None:
                                self.ingest_can(
                                    can_id, bytes.fromhex(message.get("data_hex", "")),
                                    message.get("timestamp"), topic.decode("ascii", errors="ignore"))
                        except (TypeError, ValueError, json.JSONDecodeError):
                            logger.debug("Discarding malformed CAN logger message", exc_info=True)
                if diagnostic_socket in events:
                    try:
                        _topic, payload = diagnostic_socket.recv_multipart(flags=zmq.NOBLOCK)
                        self.ingest_diagnostic(json.loads(payload.decode("utf-8")))
                    except (zmq.Again, ValueError, json.JSONDecodeError):
                        logger.debug("Discarding malformed diagnostic logger message", exc_info=True)
        finally:
            can_socket.close()
            diagnostic_socket.close()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            status = {
                "recording": self._recording,
                "profile": self._profile.name,
                "available_profiles": [
                    {"name": profile.name, "description": profile.description}
                    for profile in self.profiles.values()
                ],
                "measuring_groups": [
                    {"module": item.module, "group": item.group, "priority": item.priority}
                    for item in self._profile.measuring_groups
                ],
                "output_path": self._output_path,
                **self._stats,
                "uptime_sec": round(time.time() - self._started_at, 1) if self._recording else 0,
                "last_error": self._last_error,
                "haldex_mode": self._state.get("haldex_mode", 0),
                "b08_torque_nm": self._state.get("b08_torque_nm", 0.0),
                "a7c_slip_torque_nm": self._state.get("a7c_slip_torque_nm", 0.0),
            }
            return status
