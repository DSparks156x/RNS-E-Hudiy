#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
haldex_manager.py
Manages Haldex Gen4 AWD mode switching, persistence, reconciliation, and telemetry.

Architecture:
- Sends mode change bursts over CAN ID 0x67A via can_send.ipc (5 frames, 20ms apart).
- Subscribes to can_stream.ipc to decode 0x6DA and 0x679 telemetry @ 50 Hz.
- Reconciles active vs desired mode (~1 Hz self-limiting retry loop).
- Handles persistence according to config.json:
    - If "default_mode" is configured (0, 1, or 2), resets to that mode on startup.
    - If "default_mode" is null/blank, restores last used mode on startup and saves changes.
- Exposes ZMQ REP command socket (haldex_cmd.ipc) and ZMQ PUB status socket (haldex_status.ipc).
"""

import os
import sys
import json
import time
import struct
import logging
import threading
import signal
from typing import Optional, Dict, Any, List, Tuple
import zmq
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flasher.traffic import flashing_mode_enabled

# --- Mode Constants ---
MODE_STOCK = 0
MODE_PERFORMANCE = 1
MODE_COMPETITION = 2

MODE_NAMES = {
    MODE_STOCK: "Stock",
    MODE_PERFORMANCE: "Performance",
    MODE_COMPETITION: "Competition"
}

CAN_ID_MODE_CMD = 0x67A
CAN_ID_HALDEX_TELEMETRY_YAW = 0x679
CAN_ID_HALDEX_TELEMETRY_STATE = 0x6DA

MODE_COMMAND_HEADERS = {
    MODE_STOCK: bytes.fromhex("5AA5"),
    MODE_PERFORMANCE: bytes.fromhex("A55A"),
    MODE_COMPETITION: bytes.fromhex("3CC3"),
}

logger = logging.getLogger("HaldexManager")


def build_mode_frame(mode: int) -> Tuple[int, str]:
    """
    Build one compact 7316 0x67A mode command. The mode is encoded entirely
    by bytes 0-1; Haldex ignores bytes 2-7 for recognized headers.
    """
    mode = int(mode)
    if mode not in MODE_COMMAND_HEADERS:
        raise ValueError(f"Invalid mode {mode}. Expected 0, 1, or 2.")
    data_bytes = MODE_COMMAND_HEADERS[mode] + bytes(6)
    return CAN_ID_MODE_CMD, data_bytes.hex()


def build_mode_burst(mode: int, count: int = 5) -> List[Tuple[int, str]]:
    """Build the recommended five-copy 0x67A command burst."""
    frame = build_mode_frame(mode)
    return [frame] * max(1, int(count))


def decode_0x6da(payload_hex: str) -> Optional[Dict[str, Any]]:
    """
    Decode one page of the 7316 0x6DA telemetry stream. Byte 0 is 0xD0|page,
    byte 1 carries compact status, and bytes 2..7 contain three LE words.
    """
    try:
        data = bytes.fromhex(payload_hex)
        if len(data) != 8 or data[0] & 0xF8 != 0xD0:
            return None
        page = data[0] & 0x07
        if page > 6:
            return None
        status = data[1]
        words = struct.unpack('<HHH', data[2:8])
        mode = status & 0x03
        decoded = {
            'page': page,
            'mode': mode,
            'mode_name': MODE_NAMES.get(mode, f"Unknown ({mode})"),
            'selector': (status >> 2) & 0x07,
            'force_zero': bool((status >> 5) & 0x01),
            'token_ok': bool((status >> 6) & 0x01),
            'abs_braking': bool((status >> 7) & 0x01),
        }
        signed = lambda value: value - 0x10000 if value & 0x8000 else value
        if page == 0:
            decoded.update({
                'a72_raw': words[0], 'a72_nm': round(words[0] * 0.0625, 2),
                'a74_raw': words[1], 'a74_nm': round(words[1] * 0.0625, 2),
                'a7c_raw': words[2], 'a7c_nm': round(words[2] * 0.0625, 2),
            })
        elif page == 1:
            measured_yaw = signed(words[2])
            decoded.update({'c9e_demanded_accel': signed(words[0]),
                            'c9c_actual_accel': signed(words[1]),
                            'measured_yaw_raw': measured_yaw,
                            'measured_yaw_deg_s': round(measured_yaw / 17.87, 3)})
        elif page == 2:
            decoded.update({'b26_lateral_feedforward': signed(words[0]),
                            'bc4_curvature': words[1],
                            'bb6_computed_axle_slip': signed(words[2])})
        elif page == 3:
            decoded.update({'wheel_vl_kmh': round(words[0] * 0.005, 3),
                            'wheel_vr_kmh': round(words[1] * 0.005, 3),
                            'wheel_hl_kmh': round(words[2] * 0.005, 3)})
        elif page == 4:
            decoded.update({'wheel_hr_kmh': round(words[0] * 0.005, 3),
                            'lat_accel_measured': signed(words[1]),
                            'throttle': words[2] & 0xFF,
                            'bls': (words[2] >> 8) & 0xFF})
        elif page == 5:
            decoded.update({'hold_a7e': words[0], 'c12_high_gear_factor': words[1],
                            'target_gear_word': words[2],
                            'target_gear': words[2] & 0xFF})
        elif page == 6:
            decoded.update({'c3a_slip_energy': words[0],
                            'c26_energy_ceiling': words[1],
                            'afe_fault_ceiling': words[2]})
        return decoded
    except Exception as e:
        logger.debug(f"Error decoding 0x6DA: {e}")
        return None


def decode_0x679(payload_hex: str) -> Optional[Dict[str, Any]]:
    """
    Decode 0x679 yaw/torque telemetry frame (DLC 8, little-endian):
      bytes 0-1: model yaw (s16, 17.87 counts/deg/s)
      bytes 2-3: C06 (u16, raw proactive reference)
      bytes 4-5: C22 (u16, pre-RefGen reference)
      bytes 6-7: B08 (u16, real commanded coupling torque uncensored, 0.0625 Nm/count)
    """
    try:
        data = bytes.fromhex(payload_hex)
        if len(data) != 8:
            return None

        model_yaw_raw = struct.unpack('<h', data[0:2])[0]
        c06, c22, b08_raw = struct.unpack('<HHH', data[2:8])

        return {
            'model_yaw_raw': model_yaw_raw,
            'model_yaw_deg_s': round(model_yaw_raw / 17.87, 3),
            'c06': c06,
            'c22': c22,
            'b08_raw': b08_raw,
            'b08_nm': round(b08_raw * 0.0625, 2)
        }
    except Exception as e:
        logger.debug(f"Error decoding 0x679: {e}")
        return None


class HaldexManager:
    """
    Autonomous state machine managing mode transmission, telemetry, and persistence.
    """
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.haldex_cfg = self.config.get('haldex', {})

        # Settings
        self.burst_count = int(self.haldex_cfg.get('burst_count', 5))
        self.burst_interval = float(self.haldex_cfg.get('burst_interval_ms', 20)) / 1000.0
        self.default_mode = self.haldex_cfg.get('default_mode')
        self.persistence_file = os.path.expanduser(
            self.haldex_cfg.get('persistence_file', '~/.hudiy/haldex_mode.json')
        )

        # ZMQ Addresses
        _zmq = self.config.get('interfaces', {}).get('zmq', {})
        self.can_send_addr = _zmq.get('send_address', 'ipc:///run/rnse_control/can_send.ipc')
        self.can_stream_addr = _zmq.get('can_raw_stream', 'ipc:///run/rnse_control/can_stream.ipc')
        self.cmd_addr = _zmq.get('haldex_command', 'ipc:///run/rnse_control/haldex_cmd.ipc')
        self.status_addr = _zmq.get('haldex_status', 'ipc:///run/rnse_control/haldex_status.ipc')

        # State Variables
        self.desired_mode = MODE_STOCK
        self.active_mode: Optional[int] = None
        self.last_telemetry_state: Dict[str, Any] = {}
        self.last_telemetry_yaw: Dict[str, Any] = {}
        self.last_telemetry_time: float = 0.0
        self.last_switch_time: float = 0.0
        self.last_reconcile_attempt: float = 0.0
        self.inhibited: bool = False
        self.state_lock = threading.Lock()
        self.burst_lock = threading.Lock()
        self.diagnostic_owner = "recovery-required" if os.path.exists(os.path.expanduser("~/.hudiy/haldex_recovery_required.json")) else None
        if self.diagnostic_owner:
            self.inhibited = True
        self.previous_inhibited = False

        # Determine initial mode on startup
        self._init_desired_mode()

        # Threading & Control
        self.running = True
        self.context = zmq.Context()
        self.can_push_sock: Optional[zmq.Socket] = None
        self.can_sub_sock: Optional[zmq.Socket] = None
        self.cmd_sock: Optional[zmq.Socket] = None
        self.status_pub_sock: Optional[zmq.Socket] = None

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        paths = []
        if config_path:
            paths.append(os.path.expanduser(config_path))
        paths.extend([
            os.path.expanduser('~/config.json'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json'),
            '/etc/rnse_control/config.json'
        ])
        for p in paths:
            if os.path.isfile(p):
                try:
                    with open(p, 'r') as f:
                        logger.info(f"Loaded config from {p}")
                        return json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to parse {p}: {e}")
        return {}

    def _init_desired_mode(self):
        """
        Evaluate default_mode vs persistence_file:
        - If default_mode is specified (0, 1, 2): force that mode.
        - If default_mode is null/empty: load last mode from persistence file.
        """
        if self.default_mode is not None and str(self.default_mode).strip() != "":
            try:
                m = int(self.default_mode)
                if m in (MODE_STOCK, MODE_PERFORMANCE, MODE_COMPETITION):
                    self.desired_mode = m
                    logger.info(f"Startup: Using configured default_mode = {m} ({MODE_NAMES[m]})")
                    return
            except ValueError:
                pass

        # If left blank, restore from persistence file
        saved = self._read_persisted_mode()
        if saved is not None and saved in (MODE_STOCK, MODE_PERFORMANCE, MODE_COMPETITION):
            self.desired_mode = saved
            logger.info(f"Startup: Restored last used mode = {saved} ({MODE_NAMES[saved]})")
        else:
            self.desired_mode = MODE_STOCK
            logger.info(f"Startup: No persisted mode found, defaulting to Stock (0)")

    def _read_persisted_mode(self) -> Optional[int]:
        if not os.path.exists(self.persistence_file):
            return None
        try:
            with open(self.persistence_file, 'r') as f:
                data = json.load(f)
                return data.get('saved_mode')
        except Exception as e:
            logger.warning(f"Could not read persistence file {self.persistence_file}: {e}")
            return None

    def _save_persisted_mode(self, mode: int):
        """Save mode if default_mode is not explicitly locking it."""
        if self.default_mode is not None and str(self.default_mode).strip() != "":
            return  # Config mandates static default; do not persist

        try:
            os.makedirs(os.path.dirname(self.persistence_file), exist_ok=True)
            temp_path = f"{self.persistence_file}.tmp"
            with open(temp_path, 'w') as f:
                json.dump({
                    'saved_mode': mode,
                    'mode_name': MODE_NAMES.get(mode, "Unknown"),
                    'updated_at': time.time()
                }, f, indent=2)
            os.replace(temp_path, self.persistence_file)
            logger.debug(f"Persisted mode {mode} to {self.persistence_file}")
        except Exception as e:
            logger.error(f"Failed to persist mode {mode}: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive status dictionary."""
        with self.state_lock:
            active = self.active_mode
            desired = self.desired_mode
            synced = (active == desired) if active is not None else False
            now = time.time()
            online = (now - self.last_telemetry_time < 2.0) if self.last_telemetry_time > 0 else False

            status_str = "offline"
            if online:
                if synced:
                    status_str = "synced"
                elif now - self.last_switch_time < 0.4:
                    status_str = "switching"
                else:
                    status_str = "reconciling"

            return {
                'status': status_str,
                'desired_mode': desired,
                'desired_name': MODE_NAMES.get(desired, "Unknown"),
                'active_mode': active,
                'active_name': MODE_NAMES.get(active, "Unknown") if active is not None else None,
                'token_ok': self.last_telemetry_state.get('token_ok', False),
                'b08_torque_nm': self.last_telemetry_yaw.get('b08_nm', 0.0),
                'a7c_slip_nm': self.last_telemetry_state.get('a7c_nm', 0.0),
                'a72_ceiling_nm': self.last_telemetry_state.get('a72_nm', 0.0),
                'yaw_model_counts': self.last_telemetry_yaw.get('model_yaw_raw', 0),
                'hold_a7e': self.last_telemetry_state.get('hold_a7e', 0),
                'last_telemetry_age': round(now - self.last_telemetry_time, 2) if self.last_telemetry_time else None,
                'last_switch_time': self.last_switch_time,
                'inhibited': self.inhibited
            }

    def _publish_status(self):
        """Publish status snapshot over ZMQ PUB."""
        if not self.status_pub_sock:
            return
        try:
            status = self.get_status()
            payload = json.dumps(status).encode('utf-8')
            self.status_pub_sock.send_multipart([b"HALDEX_STATUS", payload], flags=zmq.NOBLOCK)
        except Exception:
            pass

    def send_mode_burst(self, mode: int):
        with self.burst_lock:
            return self._send_mode_burst_locked(mode)

    def _send_mode_burst_locked(self, mode: int):
        """Send burst of 0x67A frames spaced by burst_interval via can_send.ipc."""
        if self.inhibited or flashing_mode_enabled():
            logger.info("send_mode_burst skipped: HaldexManager is inhibited (ECU flashing in progress).")
            return

        if not self.can_push_sock:
            logger.warning("can_send socket not initialized, cannot send burst")
            return

        with self.state_lock:
            burst = build_mode_burst(mode, count=self.burst_count)
            self.last_switch_time = time.time()

        logger.info(f"Sending {len(burst)}x 0x67A burst for Mode {mode} ({MODE_NAMES.get(mode, 'Unknown')})...")
        for can_id, hex_data in burst:
            try:
                self.can_push_sock.send_multipart([
                    str(can_id).encode('utf-8'),
                    hex_data.encode('utf-8')
                ])
                time.sleep(self.burst_interval)
            except Exception as e:
                logger.error(f"Failed to send 0x67A frame: {e}")
                break

    def set_mode(self, mode: int) -> Dict[str, Any]:
        """Request a mode change."""
        mode = int(mode)
        if mode not in (MODE_STOCK, MODE_PERFORMANCE, MODE_COMPETITION):
            raise ValueError(f"Invalid mode {mode}. Expected 0, 1, or 2.")

        with self.state_lock:
            self.desired_mode = mode
            self._save_persisted_mode(mode)

        self.send_mode_burst(mode)
        self._publish_status()
        return self.get_status()

    def cycle_mode(self) -> Dict[str, Any]:
        """Cycle mode: Stock -> Performance -> Competition -> Stock."""
        with self.state_lock:
            next_mode = (self.desired_mode + 1) % 3
        return self.set_mode(next_mode)

    def _can_listener_worker(self):
        """Worker thread: listens to CAN stream for 0x6DA and 0x679."""
        sub = self.context.socket(zmq.SUB)
        sub.set_hwm(2000)
        try:
            sub.connect(self.can_stream_addr)
            sub.subscribe(b"CAN_6DA")
            sub.subscribe(b"CAN_0x6DA")
            sub.subscribe(b"CAN_679")
            sub.subscribe(b"CAN_0x679")
            logger.info(f"Subscribed to CAN telemetry at {self.can_stream_addr}")
        except Exception as e:
            logger.error(f"CAN sub connect error: {e}")
            return

        self.can_sub_sock = sub
        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(200))
                if sub in events:
                    while True:
                        try:
                            topic, msg_bytes = sub.recv_multipart(flags=zmq.NOBLOCK)
                            topic_str = topic.decode('utf-8', errors='ignore')
                            msg_dict = json.loads(msg_bytes.decode('utf-8'))
                            payload_hex = msg_dict.get('data_hex', '')

                            if '6DA' in topic_str:
                                decoded = decode_0x6da(payload_hex)
                                if decoded:
                                    with self.state_lock:
                                        self.active_mode = decoded['mode']
                                        self.last_telemetry_state.update(decoded)
                                        self.last_telemetry_time = time.time()
                            elif '679' in topic_str:
                                decoded = decode_0x679(payload_hex)
                                if decoded:
                                    with self.state_lock:
                                        self.last_telemetry_yaw = decoded
                                        self.last_telemetry_time = time.time()
                        except zmq.Again:
                            break
            except Exception as e:
                if self.running:
                    logger.debug(f"CAN listener loop: {e}")
                    time.sleep(0.05)

        sub.close()

    def _reconciliation_worker(self):
        """
        Worker thread: self-limiting reconciliation loop (~1 Hz check).
        Re-sends burst if reported active_mode does not match desired_mode.
        """
        logger.info("Reconciliation worker started.")
        while self.running:
            time.sleep(0.5)
            now = time.time()

            with self.state_lock:
                inhibited = self.inhibited
                active = self.active_mode
                desired = self.desired_mode
                switch_age = now - self.last_switch_time
                reconcile_age = now - self.last_reconcile_attempt

            if inhibited:
                continue

            # If telemetry is present and active mode does not match desired mode
            if active is not None and active != desired:
                # Wait at least 350 ms after a burst for debounce/latch before considering retry
                if switch_age >= 0.35 and reconcile_age >= 1.0:
                    logger.warning(
                        f"Mode discrepancy detected: active={active} ({MODE_NAMES.get(active, 'Unknown')}), "
                        f"desired={desired} ({MODE_NAMES.get(desired, 'Unknown')}). Re-sending burst..."
                    )
                    self.last_reconcile_attempt = now
                    self.send_mode_burst(desired)

            self._publish_status()

    def quiesce(self, token, recovery_resume=False):
        with self.burst_lock:
            if not isinstance(token, str) or not token:
                raise ValueError("Missing diagnostic owner")
            recovery_marker = os.path.exists(os.path.expanduser(
                "~/.hudiy/haldex_recovery_required.json"))
            recovery_takeover = recovery_resume is True and recovery_marker
            if (self.diagnostic_owner not in (None, token, "recovery-required")
                    and not recovery_takeover):
                raise RuntimeError("Haldex already owned")
            if self.diagnostic_owner is None:
                self.previous_inhibited = self.inhibited
            elif self.diagnostic_owner == "recovery-required" or recovery_takeover:
                logger.info("Resuming incomplete flash under diagnostic owner %s", token)
            self.diagnostic_owner = token
            self.inhibited = True
            self._drain_mode_queue(token)
        return {'quiescent': True, 'owner': token}

    def _drain_mode_queue(self, token):
        if len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError("Invalid owner token")
        endpoint = 'ipc:///run/rnse_control/haldex_barrier_' + token + '.ipc'
        reply = self.context.socket(zmq.PULL)
        reply.setsockopt(zmq.LINGER, 0)
        reply.setsockopt(zmq.RCVTIMEO, 5000)
        try:
            reply.bind(endpoint)
            self.can_push_sock.send_multipart([b'BARRIER', token.encode(), endpoint.encode()])
            response = reply.recv_json()
            if response.get('token') != token or response.get('quiescent') is not True:
                raise RuntimeError("CAN sender did not acknowledge queue drain")
        finally:
            reply.close()
            try:
                os.unlink(endpoint[len('ipc://'):])
            except OSError:
                pass

    def _command_server_worker(self):
        """Worker thread: handles JSON IPC commands on haldex_cmd.ipc."""
        cmd_sock = self.context.socket(zmq.REP)
        try:
            cmd_sock.bind(self.cmd_addr)
            logger.info(f"Haldex command socket bound to {self.cmd_addr}")
        except Exception as e:
            logger.error(f"Failed to bind command socket {self.cmd_addr}: {e}")
            return

        self.cmd_sock = cmd_sock
        poller = zmq.Poller()
        poller.register(cmd_sock, zmq.POLLIN)

        while self.running:
            try:
                events = dict(poller.poll(500))
                if cmd_sock in events:
                    req_bytes = cmd_sock.recv()
                    req = json.loads(req_bytes.decode('utf-8'))
                    cmd = req.get('cmd', '').upper()

                    resp = {'status': 'ok'}
                    if cmd == 'QUIESCE':
                        resp.update(self.quiesce(
                            req.get('owner'), req.get('recovery_resume') is True))
                    elif cmd == 'RELEASE':
                        with self.burst_lock:
                            if req.get('owner') != self.diagnostic_owner:
                                raise RuntimeError("Diagnostic owner mismatch")
                            if req.get('recovery_required') is True:
                                self.inhibited = True
                                self.diagnostic_owner = "recovery-required"
                            else:
                                self.inhibited = self.previous_inhibited
                                self.diagnostic_owner = None
                    elif self.diagnostic_owner and cmd not in ('STATUS', 'GET_STATUS'):
                        resp = {'status': 'error', 'message': 'Exclusive diagnostics in progress'}
                    elif cmd == 'CYCLE':
                        resp['data'] = self.cycle_mode()
                    elif cmd == 'SET_MODE':
                        mode = req.get('mode', 0)
                        resp['data'] = self.set_mode(mode)
                    elif cmd == 'GET_STATUS' or cmd == 'STATUS':
                        resp['data'] = self.get_status()
                    elif cmd in ('SET_INHIBIT', 'INHIBIT', 'PAUSE'):
                        val = req.get('inhibit', True) if cmd == 'SET_INHIBIT' else True
                        with self.state_lock:
                            self.inhibited = bool(val)
                        resp['inhibited'] = self.inhibited
                        resp['data'] = self.get_status()
                        logger.info(f"HaldexManager inhibited: {self.inhibited}")
                        self._publish_status()
                    elif cmd in ('RESUME', 'UNINHIBIT'):
                        with self.state_lock:
                            self.inhibited = False
                        resp['inhibited'] = False
                        resp['data'] = self.get_status()
                        logger.info("HaldexManager uninhibited/resumed.")
                        self._publish_status()
                    else:
                        resp = {'status': 'error', 'message': f"Unknown command '{cmd}'"}

                    cmd_sock.send_json(resp)
            except Exception as e:
                if self.running:
                    try:
                        cmd_sock.send_json({"status": "error", "message": str(e)})
                    except Exception:
                        pass
                    logger.debug(f"Command worker loop: {e}")
                    time.sleep(0.05)

        cmd_sock.close()

    def start(self):
        """Start manager threads and initialize CAN transmission."""
        logger.info("Starting HaldexManager...")

        # Initialize CAN PUSH socket
        try:
            self.can_push_sock = self.context.socket(zmq.PUSH)
            self.can_push_sock.connect(self.can_send_addr)
            logger.info(f"Connected to CAN send socket at {self.can_send_addr}")
        except Exception as e:
            logger.error(f"Failed to connect to {self.can_send_addr}: {e}")

        # Initialize Status Publisher socket
        try:
            self.status_pub_sock = self.context.socket(zmq.PUB)
            self.status_pub_sock.bind(self.status_addr)
            logger.info(f"Status publisher bound to {self.status_addr}")
        except Exception as e:
            logger.warning(f"Could not bind status socket {self.status_addr}: {e}")

        # Start background threads
        t_listener = threading.Thread(target=self._can_listener_worker, daemon=True, name="Haldex-CAN-Listener")
        t_reconcile = threading.Thread(target=self._reconciliation_worker, daemon=True, name="Haldex-Reconciliation")
        t_cmd = threading.Thread(target=self._command_server_worker, daemon=True, name="Haldex-Command")

        t_listener.start()
        t_reconcile.start()
        t_cmd.start()

        # Send initial startup burst
        logger.info(f"Transmitting initial startup mode {self.desired_mode} ({MODE_NAMES[self.desired_mode]})...")
        self.send_mode_burst(self.desired_mode)

    def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping HaldexManager...")
        self.running = False
        if self.can_push_sock:
            self.can_push_sock.close()
        if self.status_pub_sock:
            self.status_pub_sock.close()
        self.context.term()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (Haldex) %(message)s'
    )
    manager = HaldexManager()

    def handle_sig(sig, frame):
        manager.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    manager.start()
    while manager.running:
        time.sleep(1)


if __name__ == '__main__':
    main()
