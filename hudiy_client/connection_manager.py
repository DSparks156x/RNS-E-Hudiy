#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hudiy Connection Manager

Manages the lifecycle of Bluetooth/BLE and Wireless Android Auto based on:
1. Car Ignition status (KL15)
2. Radio active status (RNS-E NM state)
3. Door open / unlock wake temporary connection window (e.g. 15s)
4. Ignition / Radio OFF disconnection

Interactions:
- Linux BlueZ (bluetoothctl power on/off)
- Hudiy API DispatchAction (quit_android_auto, connect_android_auto_wifi)
- ZMQ POWER_STATUS stream from can_base_function.py
"""

import json
import logging
import os
import sys
import subprocess
import threading
import time
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Protobuf message types from common
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    api_path = os.path.join(script_dir, 'api_files')
    if api_path not in sys.path:
        sys.path.insert(0, api_path)
    import common.Api_pb2 as hudiy_api
except ImportError:
    try:
        import Api_pb2 as hudiy_api
    except ImportError:
        hudiy_api = None

MESSAGE_DISPATCH_ACTION = getattr(hudiy_api, 'MESSAGE_DISPATCH_ACTION', 43)


class ManagerState(Enum):
    IDLE_DISCONNECTED = "IDLE_DISCONNECTED"
    WAKE_WINDOW_ACTIVE = "WAKE_WINDOW_ACTIVE"
    ACTIVE_CONNECTED = "ACTIVE_CONNECTED"
    DISCONNECTING = "DISCONNECTING"


class BluetoothController:
    """Manages system Bluetooth adapter power state using bluetoothctl."""

    @staticmethod
    def set_powered(powered: bool) -> bool:
        cmd = ["bluetoothctl", "power", "on" if powered else "off"]
        mode_str = "ON" if powered else "OFF"
        try:
            logger.info(f"BluetoothController: Setting Bluetooth power {mode_str}...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5.0
            )
            if result.returncode == 0:
                logger.info(f"BluetoothController: Bluetooth powered {mode_str} successfully.")
                return True
            else:
                logger.warning(
                    f"BluetoothController: bluetoothctl returned code {result.returncode}: {result.stderr.strip()}"
                )
                return False
        except FileNotFoundError:
            logger.error("BluetoothController: 'bluetoothctl' executable not found.")
            return False
        except subprocess.TimeoutExpired:
            logger.error(f"BluetoothController: Timeout setting Bluetooth power {mode_str}.")
            return False
        except Exception as e:
            logger.error(f"BluetoothController: Error setting Bluetooth power {mode_str}: {e}")
            return False


class ConnectionManager:
    def __init__(self, config_path='~/config.json'):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.enabled: bool = True
        self.connect_on_ignition: bool = True
        self.connect_on_radio: bool = True
        self.door_open_window_seconds: float = 15.0
        self.unlock_wake_window_seconds: float = 15.0
        self.manage_bluetooth: bool = True
        self.manage_android_auto: bool = True
        self.disconnect_delay_seconds: float = 0.0

        self.state: ManagerState = ManagerState.IDLE_DISCONNECTED
        self.lock = threading.Lock()
        self.running: bool = True

        # Vehicle state tracking
        self.kl15: bool = False
        self.kls: bool = False
        self.radio_active: bool = False
        self.bus_active: bool = False
        self.door_open: bool = False
        self.wake_signal: bool = False
        self.initial_sync_done: bool = False

        # Timers
        self.window_timer: Optional[threading.Timer] = None
        self.disconnect_timer: Optional[threading.Timer] = None

        # Hudiy Client reference (set by hudiy_data.py)
        self.hudiy_client = None

        # ZMQ subscriber thread
        self.zmq_thread: Optional[threading.Thread] = None
        self.zmq_address: str = "ipc:///run/rnse_control/base_events.ipc"

        self._load_config()

    def _load_config(self):
        try:
            expanded_path = os.path.expanduser(self.config_path)
            with open(expanded_path, 'r') as f:
                self.config = json.load(f)

            pw_mgmt = self.config.get('features', {}).get('power_management', {})
            cm_cfg = pw_mgmt.get('connection_management', {})

            self.enabled = cm_cfg.get('enabled', True)
            self.connect_on_ignition = cm_cfg.get('connect_on_ignition', True)
            self.connect_on_radio = cm_cfg.get('connect_on_radio', True)
            self.door_open_window_seconds = float(cm_cfg.get('door_open_window_seconds', 15.0))
            self.unlock_wake_window_seconds = float(cm_cfg.get('unlock_wake_window_seconds', 15.0))
            self.manage_bluetooth = cm_cfg.get('manage_bluetooth', True)
            self.manage_android_auto = cm_cfg.get('manage_android_auto', True)
            self.disconnect_delay_seconds = float(cm_cfg.get('disconnect_delay_seconds', 0.0))

            _zmq = self.config.get('interfaces', {}).get('zmq', {})
            self.zmq_address = _zmq.get('system_events', self.zmq_address)

            logger.info(
                f"ConnectionManager Config Loaded: enabled={self.enabled}, "
                f"door_window={self.door_open_window_seconds}s, "
                f"manage_bt={self.manage_bluetooth}, manage_aa={self.manage_android_auto}"
            )
        except Exception as e:
            logger.warning(f"ConnectionManager: Could not load configuration: {e}. Using defaults.")

    def set_hudiy_client(self, client):
        """Sets the Hudiy API client for dispatching actions."""
        with self.lock:
            self.hudiy_client = client
            logger.info("ConnectionManager: Hudiy API client registered.")

    def start(self):
        """Starts the ConnectionManager and its background ZMQ subscriber."""
        if not self.enabled:
            logger.info("ConnectionManager: Feature is disabled in config.")
            return

        self.running = True
        self.zmq_thread = threading.Thread(target=self._zmq_subscriber_loop, daemon=True, name="ConnMgrZMQ")
        self.zmq_thread.start()
        logger.info("ConnectionManager started.")

    def stop(self):
        """Stops the ConnectionManager and cancels pending timers."""
        self.running = False
        with self.lock:
            if self.window_timer:
                self.window_timer.cancel()
                self.window_timer = None
            if self.disconnect_timer:
                self.disconnect_timer.cancel()
                self.disconnect_timer = None
        logger.info("ConnectionManager stopped.")

    # --- Actions ---

    def _enable_connections(self, trigger_reason: str):
        """Enables Bluetooth and optionally triggers Android Auto."""
        logger.info(f"ConnectionManager: Enabling connections (Trigger: {trigger_reason})")
        if self.manage_bluetooth:
            threading.Thread(
                target=BluetoothController.set_powered,
                args=(True,),
                daemon=True
            ).start()

    def _disable_connections(self, trigger_reason: str):
        """Disconnects Android Auto and disables Bluetooth."""
        logger.info(f"ConnectionManager: Disabling connections (Trigger: {trigger_reason})")
        
        # 1. Quit Android Auto projection session
        if self.manage_android_auto and self.hudiy_client:
            try:
                if hudiy_api and hasattr(hudiy_api, 'DispatchAction'):
                    msg = hudiy_api.DispatchAction()
                    msg.action = "quit_android_auto"
                    payload = msg.SerializeToString()
                else:
                    payload = b'\n\x11quit_android_auto'
                self.hudiy_client.send(
                    MESSAGE_DISPATCH_ACTION,
                    0,
                    payload
                )
                logger.info("ConnectionManager: Dispatched 'quit_android_auto' to Hudiy.")
            except Exception as e:
                logger.error(f"ConnectionManager: Failed to dispatch 'quit_android_auto': {e}")

        # 2. Power off Bluetooth adapter
        if self.manage_bluetooth:
            threading.Thread(
                target=BluetoothController.set_powered,
                args=(False,),
                daemon=True
            ).start()

    def _trigger_aa_connect(self):
        """Optionally dispatches connect_android_auto_wifi."""
        if self.manage_android_auto and self.hudiy_client:
            try:
                if hudiy_api and hasattr(hudiy_api, 'DispatchAction'):
                    msg = hudiy_api.DispatchAction()
                    msg.action = "connect_android_auto_wifi"
                    payload = msg.SerializeToString()
                else:
                    payload = b'\n\x18connect_android_auto_wifi'
                self.hudiy_client.send(
                    MESSAGE_DISPATCH_ACTION,
                    0,
                    payload
                )
                logger.info("ConnectionManager: Dispatched 'connect_android_auto_wifi' to Hudiy.")
            except Exception as e:
                logger.debug(f"ConnectionManager: Could not dispatch 'connect_android_auto_wifi': {e}")

    # --- State Machine Handlers ---

    def _start_wake_window(self, duration: float, reason: str):
        """Starts a temporary connection window."""
        if self.window_timer:
            self.window_timer.cancel()

        logger.info(f"ConnectionManager: Starting {duration}s temporary connection window (Reason: {reason})")
        self.state = ManagerState.WAKE_WINDOW_ACTIVE
        self._enable_connections(trigger_reason=f"Wake Window ({reason})")

        self.window_timer = threading.Timer(duration, self._on_wake_window_expired)
        self.window_timer.start()

    def _on_wake_window_expired(self):
        """Called when the temporary wake window timer expires."""
        with self.lock:
            if self.state != ManagerState.WAKE_WINDOW_ACTIVE:
                return

            # Check if condition for staying connected is met
            is_active = (self.connect_on_ignition and self.kl15) or (self.connect_on_radio and self.radio_active)
            if is_active:
                logger.info("ConnectionManager: Wake window expired, but active power state detected. Staying CONNECTED.")
                self.state = ManagerState.ACTIVE_CONNECTED
            else:
                logger.info("ConnectionManager: Wake window expired with no ignition/radio. Disconnecting.")
                self.state = ManagerState.IDLE_DISCONNECTED
                self._disable_connections(trigger_reason="Wake Window Expired")

    def _schedule_disconnect(self, reason: str):
        """Schedules a disconnection with optional delay."""
        if self.disconnect_delay_seconds > 0:
            if self.disconnect_timer:
                self.disconnect_timer.cancel()
            logger.info(f"ConnectionManager: Scheduling disconnect in {self.disconnect_delay_seconds}s (Reason: {reason})")
            self.disconnect_timer = threading.Timer(self.disconnect_delay_seconds, lambda: self._execute_disconnect(reason))
            self.disconnect_timer.start()
        else:
            self._execute_disconnect(reason)

    def _execute_disconnect(self, reason: str):
        with self.lock:
            # Check if active condition returned before disconnect execution
            is_active = (self.connect_on_ignition and self.kl15) or (self.connect_on_radio and self.radio_active)
            if is_active:
                logger.info("ConnectionManager: Disconnect cancelled — active power state restored.")
                self.state = ManagerState.ACTIVE_CONNECTED
                return

            if self.window_timer:
                self.window_timer.cancel()
                self.window_timer = None

            self.state = ManagerState.IDLE_DISCONNECTED
            self._disable_connections(trigger_reason=reason)

    # --- Vehicle Event Processing ---

    def process_power_status(self, pwr: Dict[str, Any]):
        """Processes updated POWER_STATUS from ZMQ."""
        with self.lock:
            if not self.enabled:
                return

            old_kl15 = self.kl15
            old_radio = self.radio_active
            old_wake = self.wake_signal
            old_door_open = self.door_open

            self.kl15 = bool(pwr.get('kl15', False))
            self.kls = bool(pwr.get('kls', False))
            self.radio_active = bool(pwr.get('radio_active', False))
            self.bus_active = bool(pwr.get('bus_active', False))
            self.door_open = bool(pwr.get('door_open', False))
            self.wake_signal = bool(pwr.get('wake_signal', False))
            door_event = bool(pwr.get('door_event', False))

            is_active = (self.connect_on_ignition and self.kl15) or (self.connect_on_radio and self.radio_active)

            # --- Initial Startup Sync ---
            if not self.initial_sync_done:
                self.initial_sync_done = True
                if is_active:
                    logger.info("ConnectionManager: Initial sync — Ignition/Radio ON. Setting ACTIVE_CONNECTED.")
                    self.state = ManagerState.ACTIVE_CONNECTED
                    self._enable_connections(trigger_reason="Initial Startup (Ignition/Radio ON)")
                elif self.door_open or self.bus_active or self.wake_signal:
                    logger.info("ConnectionManager: Initial sync — Bus/Door active without ignition. Starting wake window.")
                    self._start_wake_window(
                        duration=self.door_open_window_seconds,
                        reason="Initial Startup (Bus/Door Active)"
                    )
                else:
                    logger.info("ConnectionManager: Initial sync — Bus quiet, Ignition OFF. Disconnected state.")
                    self.state = ManagerState.IDLE_DISCONNECTED
                    self._disable_connections(trigger_reason="Initial Startup (Quiet Bus)")
                return

            # --- Active State Transitions ---
            if is_active:
                if self.state != ManagerState.ACTIVE_CONNECTED:
                    logger.info(f"ConnectionManager: Ignition/Radio became ON (KL15={self.kl15}, Radio={self.radio_active}). Transitioning to ACTIVE_CONNECTED.")
                    if self.window_timer:
                        self.window_timer.cancel()
                        self.window_timer = None
                    if self.disconnect_timer:
                        self.disconnect_timer.cancel()
                        self.disconnect_timer = None

                    self.state = ManagerState.ACTIVE_CONNECTED
                    self._enable_connections(trigger_reason="Ignition/Radio Turned ON")
                return

            # --- Inactive State (Ignition OFF and Radio OFF) ---
            # If was active and now turned OFF:
            if self.state == ManagerState.ACTIVE_CONNECTED:
                logger.info(f"ConnectionManager: Ignition/Radio turned OFF (KL15={self.kl15}, Radio={self.radio_active}).")
                self._schedule_disconnect(reason="Ignition/Radio Turned OFF")
                return

            # If in IDLE_DISCONNECTED or WAKE_WINDOW_ACTIVE, check for door opening or wake signal rising edge:
            door_opened = door_event or (not old_door_open and self.door_open)
            wake_triggered = (not old_wake and self.wake_signal)

            if door_opened:
                logger.info("ConnectionManager: Door opened event detected while Ignition/Radio OFF.")
                self._start_wake_window(
                    duration=self.door_open_window_seconds,
                    reason="Door Opened"
                )
            elif wake_triggered and self.state == ManagerState.IDLE_DISCONNECTED:
                logger.info("ConnectionManager: Physical Wake/Unlock signal rising edge detected.")
                self._start_wake_window(
                    duration=self.unlock_wake_window_seconds,
                    reason="Unlock/Wake Trigger"
                )

    # --- ZMQ Subscriber Loop ---

    def _zmq_subscriber_loop(self):
        import zmq
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        try:
            sub.connect(self.zmq_address)
            sub.subscribe(b"POWER_STATUS")
            sub.setsockopt(zmq.RCVTIMEO, 1000)
            logger.info(f"ConnectionManager: ZMQ subscriber connected to {self.zmq_address}")

            while self.running:
                try:
                    parts = sub.recv_multipart()
                    if len(parts) == 2 and parts[0] == b"POWER_STATUS":
                        data = json.loads(parts[1].decode('utf-8'))
                        self.process_power_status(data)
                except zmq.Again:
                    continue
                except Exception as e:
                    if self.running:
                        logger.error(f"ConnectionManager: ZMQ recv error: {e}")
                        time.sleep(0.5)
        except Exception as e:
            logger.error(f"ConnectionManager: Failed to initialize ZMQ subscriber: {e}")
        finally:
            sub.close()
            ctx.term()
