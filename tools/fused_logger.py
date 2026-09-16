#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fused_logger.py
Vehicle CAN & KWP2000 Data Fusion Logger for Haldex tuning & chassis dynamics.

Features:
- Subscribes to raw CAN stream (can_stream.ipc) with hardware timestamps.
- Logs full 16 raw bytes of Haldex frames (0x679 & 0x6DD) alongside post-decoded signals.
- Ingests powertrain IDs: 0x4A0 (all 4 wheel speeds), 0x0C2 (steering angle/rate),
  0x1A0 (BLS, ABS, ESP), 0x280 (RPM, throttle), 0x288 (engine torque/coolant),
  0x4A8 (yaw rate), 0x428 (accel), 0x67A (mode command burst).
- Subscribes to KWP2000 diagnostic stream (tp2_stream.ipc).
- Event marker system for in-cockpit tags ("understeer", "launch", "brake", etc.).
- Multi-threaded non-blocking CSV writer (queue-buffered to prevent dropped frames).
- Supports both standalone CLI execution and IPC/programmatic control from Hudiy Dataview.
"""

import os
import sys
import csv
import time
import json
import struct
import queue
import logging
import argparse
import threading
import select
from datetime import datetime
from typing import Optional, Dict, Any, List
import zmq

# Add parent and rns-e_can directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rns-e_can"))
try:
    from haldex_manager import decode_0x6dd, decode_0x679, MODE_NAMES
except ImportError:
    MODE_NAMES = {0: "Stock", 1: "Performance", 2: "Competition"}

logger = logging.getLogger("FusedLogger")

# --- Standard CSV Header ---
CSV_COLUMNS = [
    "timestamp",
    "datetime",
    "event_marker",
    "raw_0x679",
    "raw_0x6dd",
    "haldex_mode",
    "haldex_mode_name",
    "haldex_token_ok",
    "b08_torque_nm",
    "a7c_slip_torque_nm",
    "a74_ref_torque_nm",
    "a72_ceiling_nm",
    "c06_proactive_ref",
    "c22_pre_refgen",
    "yaw_model_or_b1a",
    "hold_a7e_timer",
    "speed_fl_kmh",
    "speed_fr_kmh",
    "speed_rl_kmh",
    "speed_rr_kmh",
    "steer_angle_deg",
    "steer_rate_deg_s",
    "measured_yaw_rate_deg_s",
    "long_accel_m_s2",
    "engine_rpm",
    "throttle_pct",
    "engine_torque_nm",
    "engine_coolant_c",
    "brake_light_switch",
    "abs_active",
    "esp_active",
    "kwp_data"
]


class VehicleSignalDecoder:
    """Decodes standard PQ35 powertrain messages forwarded to infotainment."""

    @staticmethod
    def decode_0x4a0_wheels(data: bytes) -> Dict[str, float]:
        """0x4A0 Bremsen_3: 4 wheel speeds (15-bit each, scale 0.01 km/h)."""
        if len(data) < 8:
            return {}
        try:
            # Little-endian 16-bit words, bit 0 is reserved/direction
            w0, w1, w2, w3 = struct.unpack('<HHHH', data[:8])
            fl = (w0 >> 1) * 0.01
            fr = (w1 >> 1) * 0.01
            rl = (w2 >> 1) * 0.01
            rr = (w3 >> 1) * 0.01
            return {
                'speed_fl_kmh': round(fl, 2),
                'speed_fr_kmh': round(fr, 2),
                'speed_rl_kmh': round(rl, 2),
                'speed_rr_kmh': round(rr, 2)
            }
        except Exception:
            return {}

    @staticmethod
    def decode_0x0c2_steering(data: bytes) -> Dict[str, float]:
        """0x0C2 Lenkwinkel: steering angle & rate."""
        if len(data) < 4:
            return {}
        try:
            # Bytes 0-1: Angle (bits 0-14 value, bit 15 sign: 1 = negative)
            angle_raw = data[0] | (data[1] << 8)
            angle_val = (angle_raw & 0x7FFF) * 0.04375
            if angle_raw & 0x8000:
                angle_val = -angle_val

            # Bytes 2-3: Rate (bits 16-30 value, bit 31 sign)
            rate_raw = data[2] | (data[3] << 8)
            rate_val = (rate_raw & 0x7FFF) * 0.04375
            if rate_raw & 0x8000:
                rate_val = -rate_val

            return {
                'steer_angle_deg': round(angle_val, 2),
                'steer_rate_deg_s': round(rate_val, 2)
            }
        except Exception:
            return {}

    @staticmethod
    def decode_0x1a0_brakes(data: bytes) -> Dict[str, int]:
        """0x1A0 Bremsen_1: ABS, ESP, BLS flags."""
        if len(data) < 2:
            return {}
        try:
            byte0 = data[0]
            byte1 = data[1]
            abs_active = 1 if (byte0 & 0x04) else 0
            esp_active = 1 if (byte0 & 0x10) else 0
            bls = 1 if (byte1 & 0x08) else 0
            return {
                'brake_light_switch': bls,
                'abs_active': abs_active,
                'esp_active': esp_active
            }
        except Exception:
            return {}

    @staticmethod
    def decode_0x280_engine(data: bytes) -> Dict[str, float]:
        """0x280 Motor_1: RPM & Throttle."""
        if len(data) < 6:
            return {}
        try:
            # Bytes 2-3: RPM (scale 0.25)
            rpm = (data[2] | (data[3] << 8)) * 0.25
            # Byte 5: Throttle pedal (scale 0.4 %)
            throttle = data[5] * 0.4
            return {
                'engine_rpm': round(rpm, 1),
                'throttle_pct': round(throttle, 1)
            }
        except Exception:
            return {}

    @staticmethod
    def decode_0x288_engine(data: bytes) -> Dict[str, float]:
        """0x288 Motor_2: Torque & Coolant."""
        if len(data) < 3:
            return {}
        try:
            # Byte 1: Coolant (scale 0.75, offset -48 C)
            coolant = data[1] * 0.75 - 48.0
            # Byte 2: Driver requested torque / load (scale 0.39 %)
            torque = data[2] * 0.39
            return {
                'engine_coolant_c': round(coolant, 1),
                'engine_torque_nm': round(torque, 1)
            }
        except Exception:
            return {}

    @staticmethod
    def decode_0x4a8_yaw(data: bytes) -> Dict[str, float]:
        """0x4A8 Bremsen_5: Yaw Rate."""
        if len(data) < 2:
            return {}
        try:
            val = (data[0] | ((data[1] & 0x3F) << 8)) * 0.01
            # Check sign
            if data[1] & 0x40:
                val = -val
            return {'measured_yaw_rate_deg_s': round(val, 2)}
        except Exception:
            return {}

    @staticmethod
    def decode_0x428_accel(data: bytes) -> Dict[str, float]:
        """0x428 Bremsen_8: Longitudinal Acceleration."""
        if len(data) < 7:
            return {}
        try:
            raw = (data[6] & 0x03) << 8 | data[5]
            accel = raw * 0.03125 - 16.0
            return {'long_accel_m_s2': round(accel, 2)}
        except Exception:
            return {}


class FusedLogger:
    """
    Multi-threaded logger capturing CAN telemetry, powertrain metrics, and KWP data.
    """
    def __init__(self, output_path: str, config_path: Optional[str] = None):
        self.output_path = os.path.expanduser(output_path)
        self.config = self._load_config(config_path)

        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        self.can_stream_addr = _zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
        self.tp2_stream_addr = _zmq.get('tp2_stream', 'ipc:///run/rnse_control/tp2_stream.ipc')
        self.cmd_addr = 'ipc:///run/rnse_control/fused_logger_cmd.ipc'

        self.running = False
        self.recording = False
        self.record_queue = queue.Queue(maxsize=10000)
        self.state_lock = threading.Lock()

        # Telemetry State Snapshots
        self.state: Dict[str, Any] = {
            'raw_0x679': '',
            'raw_0x6dd': '',
            'haldex_mode': 0,
            'haldex_mode_name': 'Stock',
            'haldex_token_ok': 0,
            'b08_torque_nm': 0.0,
            'a7c_slip_torque_nm': 0.0,
            'a74_ref_torque_nm': 0.0,
            'a72_ceiling_nm': 0.0,
            'c06_proactive_ref': 0,
            'c22_pre_refgen': 0,
            'yaw_model_or_b1a': 0,
            'hold_a7e_timer': 0,
            'speed_fl_kmh': 0.0,
            'speed_fr_kmh': 0.0,
            'speed_rl_kmh': 0.0,
            'speed_rr_kmh': 0.0,
            'steer_angle_deg': 0.0,
            'steer_rate_deg_s': 0.0,
            'measured_yaw_rate_deg_s': 0.0,
            'long_accel_m_s2': 0.0,
            'engine_rpm': 0.0,
            'throttle_pct': 0.0,
            'engine_torque_nm': 0.0,
            'engine_coolant_c': 0.0,
            'brake_light_switch': 0,
            'abs_active': 0,
            'esp_active': 0,
            'kwp_data': ''
        }

        # Event markers waiting to be stamped onto the next emitted row
        self.pending_markers: List[str] = []
        self.stats = {
            'frames_received': 0,
            'rows_written': 0,
            'start_time': 0.0,
            'markers_logged': 0
        }

        self.context = zmq.Context()

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        paths = []
        if config_path:
            paths.append(os.path.expanduser(config_path))
        paths.extend([
            os.path.expanduser('~/config.json'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
        ])
        for p in paths:
            if os.path.isfile(p):
                try:
                    with open(p, 'r') as f:
                        return json.load(f)
                except Exception:
                    pass
        return {}

    def add_marker(self, note: str):
        """Inject a timestamped driver marker."""
        with self.state_lock:
            self.pending_markers.append(note)
            self.stats['markers_logged'] += 1
        logger.info(f"*** EVENT MARKER TAGGED: {note} ***")
        # Immediately queue an event snapshot
        self._queue_snapshot(event_override=note)

    def _queue_snapshot(self, event_override: Optional[str] = None):
        """Capture current state vector and place in CSV queue."""
        if not self.recording:
            return

        now = time.time()
        dt_str = datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        with self.state_lock:
            marker = event_override or ("; ".join(self.pending_markers) if self.pending_markers else "")
            if not event_override:
                self.pending_markers.clear()

            row = [
                f"{now:.6f}",
                dt_str,
                marker,
                self.state['raw_0x679'],
                self.state['raw_0x6dd'],
                self.state['haldex_mode'],
                self.state['haldex_mode_name'],
                self.state['haldex_token_ok'],
                self.state['b08_torque_nm'],
                self.state['a7c_slip_torque_nm'],
                self.state['a74_ref_torque_nm'],
                self.state['a72_ceiling_nm'],
                self.state['c06_proactive_ref'],
                self.state['c22_pre_refgen'],
                self.state['yaw_model_or_b1a'],
                self.state['hold_a7e_timer'],
                self.state['speed_fl_kmh'],
                self.state['speed_fr_kmh'],
                self.state['speed_rl_kmh'],
                self.state['speed_rr_kmh'],
                self.state['steer_angle_deg'],
                self.state['steer_rate_deg_s'],
                self.state['measured_yaw_rate_deg_s'],
                self.state['long_accel_m_s2'],
                self.state['engine_rpm'],
                self.state['throttle_pct'],
                self.state['engine_torque_nm'],
                self.state['engine_coolant_c'],
                self.state['brake_light_switch'],
                self.state['abs_active'],
                self.state['esp_active'],
                self.state['kwp_data']
            ]

        try:
            self.record_queue.put_nowait(row)
        except queue.Full:
            pass  # Avoid memory bloat if disk stalls

    def _csv_writer_worker(self):
        """Dedicated background thread: writes rows to disk with buffered flushing."""
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        is_new_file = not os.path.exists(self.output_path) or os.path.getsize(self.output_path) == 0

        logger.info(f"CSV Writer opened: {self.output_path}")
        with open(self.output_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if is_new_file:
                writer.writerow(CSV_COLUMNS)
                f.flush()

            last_flush = time.time()
            rows_since_flush = 0

            while self.running or not self.record_queue.empty():
                try:
                    row = self.record_queue.get(timeout=0.2)
                    writer.writerow(row)
                    self.stats['rows_written'] += 1
                    rows_since_flush += 1

                    now = time.time()
                    if rows_since_flush >= 50 or (now - last_flush >= 1.0):
                        f.flush()
                        last_flush = now
                        rows_since_flush = 0
                except queue.Empty:
                    if rows_since_flush > 0:
                        f.flush()
                        last_flush = time.time()
                        rows_since_flush = 0

        logger.info("CSV Writer finished.")

    def _can_subscriber_worker(self):
        """Ingests all CAN messages and decodes them."""
        sub = self.context.socket(zmq.SUB)
        sub.set_hwm(5000)
        try:
            sub.connect(self.can_stream_addr)
            # Subscribe to target IDs
            for prefix in [
                b"CAN_679", b"CAN_0x679",
                b"CAN_6DD", b"CAN_0x6DD",
                b"CAN_67A", b"CAN_0x67A",
                b"CAN_4A0", b"CAN_0x4A0",
                b"CAN_0C2", b"CAN_0x0C2", b"CAN_C2",
                b"CAN_1A0", b"CAN_0x1A0",
                b"CAN_280", b"CAN_0x280",
                b"CAN_288", b"CAN_0x288",
                b"CAN_4A8", b"CAN_0x4A8",
                b"CAN_428", b"CAN_0x428"
            ]:
                sub.subscribe(prefix)
            logger.info(f"CAN Ingestion connected to {self.can_stream_addr}")
        except Exception as e:
            logger.error(f"Failed to connect CAN subscription: {e}")
            return

        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(200))
                if sub in events:
                    while True:
                        try:
                            topic, msg_bytes = sub.recv_multipart(flags=zmq.NOBLOCK)
                            topic_str = topic.decode('utf-8', errors='ignore').upper()
                            msg_dict = json.loads(msg_bytes.decode('utf-8'))
                            payload_hex = msg_dict.get('data_hex', '')
                            data_bytes = bytes.fromhex(payload_hex)
                            self.stats['frames_received'] += 1

                            should_snapshot = False

                            with self.state_lock:
                                # 1. Haldex 0x679 (Yaw & Uncensored Torque B08)
                                if "679" in topic_str:
                                    self.state['raw_0x679'] = payload_hex
                                    if len(data_bytes) >= 8:
                                        b1a = struct.unpack('<h', data_bytes[0:2])[0]
                                        c06, c22, b08 = struct.unpack('<HHH', data_bytes[2:8])
                                        self.state['yaw_model_or_b1a'] = b1a
                                        self.state['c06_proactive_ref'] = c06
                                        self.state['c22_pre_refgen'] = c22
                                        self.state['b08_torque_nm'] = round(b08 * 0.0625, 2)
                                    should_snapshot = True

                                # 2. Haldex 0x6DD (State & Slip Integrator A7C)
                                elif "6DD" in topic_str:
                                    self.state['raw_0x6dd'] = payload_hex
                                    if len(data_bytes) >= 8:
                                        a72, a74, a7c, status = struct.unpack('<HHHH', data_bytes[:8])
                                        mode = status & 0x03
                                        self.state['a72_ceiling_nm'] = round(a72 * 0.0625, 2)
                                        self.state['a74_ref_torque_nm'] = round(a74 * 0.0625, 2)
                                        self.state['a7c_slip_torque_nm'] = round(a7c * 0.0625, 2)
                                        self.state['haldex_mode'] = mode
                                        self.state['haldex_mode_name'] = MODE_NAMES.get(mode, str(mode))
                                        self.state['haldex_token_ok'] = (status >> 6) & 0x01
                                        self.state['hold_a7e_timer'] = (status >> 8) & 0xFF
                                    should_snapshot = True

                                # 3. Mode Change Burst (0x67A)
                                elif "67A" in topic_str:
                                    if len(data_bytes) >= 5:
                                        cmd_mode = data_bytes[2]
                                        ctr = data_bytes[4]
                                        marker = f"MODE_CMD_BURST: mode={cmd_mode} ({MODE_NAMES.get(cmd_mode, 'Unknown')}) ctr={ctr}"
                                        self.pending_markers.append(marker)
                                        should_snapshot = True

                                # 4. Four Wheel Speeds (0x4A0)
                                elif "4A0" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x4a0_wheels(data_bytes))

                                # 5. Steering Angle & Rate (0x0C2)
                                elif "0C2" in topic_str or "C2" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x0c2_steering(data_bytes))

                                # 6. Brakes & ESP (0x1A0)
                                elif "1A0" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x1a0_brakes(data_bytes))

                                # 7. Engine RPM & Throttle (0x280)
                                elif "280" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x280_engine(data_bytes))

                                # 8. Engine Torque & Coolant (0x288)
                                elif "288" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x288_engine(data_bytes))

                                # 9. Measured Yaw Rate (0x4A8)
                                elif "4A8" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x4a8_yaw(data_bytes))

                                # 10. Longitudinal Accel (0x428)
                                elif "428" in topic_str:
                                    self.state.update(VehicleSignalDecoder.decode_0x428_accel(data_bytes))

                            # Emit a row on every Haldex frame (50 Hz rate) or event marker
                            if should_snapshot:
                                self._queue_snapshot()

                        except zmq.Again:
                            break
            except Exception as e:
                if self.running:
                    logger.debug(f"CAN sub worker: {e}")
                    time.sleep(0.05)

        sub.close()

    def _tp2_subscriber_worker(self):
        """Ingests KWP2000 diagnostic stream from tp2_stream.ipc."""
        sub = self.context.socket(zmq.SUB)
        sub.set_hwm(1000)
        try:
            sub.connect(self.tp2_stream_addr)
            sub.subscribe(b"HUDIY_DIAG")
            logger.info(f"TP2 Ingestion connected to {self.tp2_stream_addr}")
        except Exception as e:
            logger.warning(f"Could not connect TP2 subscription: {e}")
            return

        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(500))
                if sub in events:
                    topic, msg_bytes = sub.recv_multipart(flags=zmq.NOBLOCK)
                    diag = json.loads(msg_bytes.decode('utf-8'))
                    mod = diag.get('module')
                    grp = diag.get('group')
                    data = diag.get('data', [])
                    simplified = {f"m{mod}_g{grp}_i{i}": d.get('value') for i, d in enumerate(data)}
                    with self.state_lock:
                        self.state['kwp_data'] = json.dumps(simplified)
            except zmq.Again:
                pass
            except Exception as e:
                if self.running:
                    logger.debug(f"TP2 sub error: {e}")
                    time.sleep(0.1)

        sub.close()

    def _command_server_worker(self):
        """Handles external IPC commands (start, stop, marker, status)."""
        sock = self.context.socket(zmq.REP)
        try:
            sock.bind(self.cmd_addr)
            logger.info(f"Logger command server bound to {self.cmd_addr}")
        except Exception as e:
            logger.warning(f"Could not bind logger command socket: {e}")
            return

        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(500))
                if sock in events:
                    msg = sock.recv_json()
                    cmd = msg.get('cmd', '').upper()
                    resp = {'status': 'ok'}

                    if cmd == 'START':
                        out = msg.get('output')
                        if out:
                            self.output_path = os.path.expanduser(out)
                        self.start_recording()
                        resp['recording'] = True
                        resp['output'] = self.output_path
                    elif cmd == 'STOP':
                        self.stop_recording()
                        resp['recording'] = False
                        resp['rows_written'] = self.stats['rows_written']
                    elif cmd == 'MARKER':
                        note = msg.get('note', 'Driver Event')
                        self.add_marker(note)
                        resp['marker'] = note
                    elif cmd == 'STATUS':
                        resp['status_data'] = self.get_status()
                    else:
                        resp = {'status': 'error', 'message': f"Unknown command {cmd}"}

                    sock.send_json(resp)
            except Exception as e:
                if self.running:
                    logger.debug(f"Logger cmd server error: {e}")
                    time.sleep(0.05)

        sock.close()

    def start_recording(self):
        self.recording = True
        self.stats['start_time'] = time.time()
        logger.info(f"=== RECORDING STARTED -> {self.output_path} ===")

    def stop_recording(self):
        self.recording = False
        logger.info(f"=== RECORDING STOPPED. Total rows: {self.stats['rows_written']} ===")

    def get_status(self) -> Dict[str, Any]:
        with self.state_lock:
            return {
                'recording': self.recording,
                'output_path': self.output_path,
                'frames_received': self.stats['frames_received'],
                'rows_written': self.stats['rows_written'],
                'markers_logged': self.stats['markers_logged'],
                'uptime_sec': round(time.time() - self.stats['start_time'], 1) if self.recording else 0,
                'haldex_mode': self.state['haldex_mode'],
                'b08_torque_nm': self.state['b08_torque_nm'],
                'a7c_slip_torque_nm': self.state['a7c_slip_torque_nm']
            }

    def start(self):
        """Starts all background worker threads."""
        self.running = True
        self.stats['start_time'] = time.time()

        t_writer = threading.Thread(target=self._csv_writer_worker, daemon=True, name="Logger-CSV")
        t_can = threading.Thread(target=self._can_subscriber_worker, daemon=True, name="Logger-CAN")
        t_tp2 = threading.Thread(target=self._tp2_subscriber_worker, daemon=True, name="Logger-TP2")
        t_cmd = threading.Thread(target=self._command_server_worker, daemon=True, name="Logger-CMD")

        t_writer.start()
        t_can.start()
        t_tp2.start()
        t_cmd.start()

        self.start_recording()

    def stop(self):
        """Graceful termination and queue flush."""
        logger.info("Stopping FusedLogger...")
        self.stop_recording()
        self.running = False
        time.sleep(0.5)
        self.context.term()


def main():
    default_log_dir = os.path.expanduser("~/logs")
    os.makedirs(default_log_dir, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_filename = os.path.join(default_log_dir, f"haldex_run_{timestamp_str}.csv")

    parser = argparse.ArgumentParser(description="Vehicle CAN + KWP2000 Data Fusion Logger")
    parser.add_argument("-o", "--output", default=default_filename, help=f"Output CSV filepath (default: {default_filename})")
    parser.add_argument("-t", "--duration", type=float, default=None, help="Record duration in seconds (default: manual Ctrl+C)")
    parser.add_argument("-m", "--marker", type=str, default=None, help="Initial event marker label")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (Logger) %(message)s'
    )

    logger_app = FusedLogger(output_path=args.output)
    logger_app.start()

    if args.marker:
        logger_app.add_marker(args.marker)

    print("\n" + "=" * 60)
    print(" FUSED VEHICLE LOGGER RUNNING")
    print(f" Logging to: {args.output}")
    print(" Controls:")
    print("   - Type a note and press ENTER to tag an in-flight marker")
    print("   - Press 'u' + ENTER for [UNDERSTEER]")
    print("   - Press 'o' + ENTER for [OVERSTEER]")
    print("   - Press 'l' + ENTER for [LAUNCH]")
    print("   - Press Ctrl+C to stop recording and exit")
    print("=" * 60 + "\n")

    start_time = time.time()
    try:
        while True:
            # Check duration limit
            if args.duration and (time.time() - start_time >= args.duration):
                logger.info(f"Target duration of {args.duration}s reached.")
                break

            # Check stdin for keyboard markers (non-blocking)
            if sys.stdin in select.select([sys.stdin], [], [], 0.1)[0]:
                line = sys.stdin.readline().strip()
                if line:
                    tag = line
                    if line.lower() == 'u':
                        tag = "UNDERSTEER"
                    elif line.lower() == 'o':
                        tag = "OVERSTEER"
                    elif line.lower() == 'l':
                        tag = "LAUNCH"
                    logger_app.add_marker(f"DRIVER: {tag}")

    except KeyboardInterrupt:
        print("\nStopping logger...")
    finally:
        logger_app.stop()
        print(f"Log saved successfully to: {args.output}")


if __name__ == '__main__':
    main()
