#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Audi DIS (Cluster) DDP Protocol Driver - V2.8
#
# Changes in V2.8:
# - FIX: Added handler for Red DIS "Graphics ACK" packet [0x0B, 0x01, 0x00].
#   This suppresses the "Received unexpected data packet" warning on Red Clusters.
#
import time
import logging
import sys
from pathlib import Path
from dataclasses import dataclass
from collections import deque

# Shared gate for every application CAN transmitter (installed beside flasher/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flasher.traffic import transmission_guard
from flasher.vag_protocols.tp2 import build_ack, build_data_frame, classify_frame, segment_message

import can
from typing import List, Optional
from enum import Enum, auto

# Get the logger for this module
logger = logging.getLogger(__name__)

# --- Custom Exceptions ---

class DDPError(Exception):
    """Base exception for DDP errors."""
    pass

class DDPCANError(DDPError):
    """Error related to CAN bus setup or communication."""
    pass

class DDPAckTimeoutError(DDPError):
    """Raised when an ACK is not received in time."""
    pass

class DDPHandshakeError(DDPError):
    """Raised when a handshake or initialization step fails."""
    pass


@dataclass(frozen=True)
class DDPTransportProfile:
    """Observed cluster limits, kept separate from generic TP2 semantics."""
    frame_gap_s: float = 0.002
    max_message_bytes: int = 42  # Legacy name: ACK-block byte budget.
    max_unacked_frames: int = 6
    white_post_message_delay_s: float = 0.020
    receiver_not_ready_wait_s: float = 0.100
    max_not_ready_retries: int = 5
    max_ack_retries: int = 2

    def __post_init__(self):
        if (self.frame_gap_s < 0 or self.white_post_message_delay_s < 0
                or self.receiver_not_ready_wait_s < 0):
            raise ValueError("DDP pacing delays cannot be negative")
        if self.max_message_bytes < 1 or self.max_unacked_frames < 1:
            raise ValueError("DDP framing limits must be positive")
        if self.max_not_ready_retries < 0 or self.max_ack_retries < 0:
            raise ValueError("DDP retry limits cannot be negative")


DEFAULT_DDP_TRANSPORT = DDPTransportProfile()


# --- Protocol State & Mode ---

class DDPState(Enum):
    """Defines the connection state."""
    DISCONNECTED = auto()
    SESSION_ACTIVE = auto()  # Keep-Alive (A-packets) session is open
    INITIALIZING = auto()    # DDP (B/1x/2x packets) handshake in progress
    READY = auto()           # Ready to send/receive data frames
    PAUSED = auto()          # Cluster claimed screen (Warning/Menu)

class DisMode(Enum):
    """Defines the detected cluster type."""
    UNKNOWN = auto()
    WHITE = auto()
    RED = auto()

# --- Message Constants ---

class DDPMessages:
    """Constants for specific DDP protocol messages."""
    # Cluster is busy (Warning/Menu active)
    STAT_BUSY_HALF       = [0x53, 0x84]
    STAT_BUSY_WARN_HALF  = [0x53, 0x04]
    STAT_BUSY_FULL       = [0x53, 0x88]
    STAT_BUSY_WARN_FULL  = [0x53, 0x08]

    # Cluster is free (Warning cleared)
    STAT_FREE_HALF       = [0x53, 0x05]
    STAT_FREE_FULL       = [0x53, 0x0A]

    # Graphics Acknowledgments (Benign)
    STAT_GRAPHIC_ACK_WHITE = [0x0B, 0x03, 0x57]
    STAT_GRAPHIC_ACK_RED   = [0x0B, 0x01, 0x00]

    # Re-Initialization Request (Sent by Cluster)
    CMD_REINIT_REQ       = [0x2E] 
    # Re-Initialization Confirmation (We send this back)
    CMD_REINIT_CONF      = [0x2F]


class DDPProtocol:
    """
    Handles the low-level DDP protocol state machine and CAN bus communication.
    Supports both White and Red DIS clusters via auto-detection.
    """

    # --- CAN & Protocol Constants ---
    CAN_PACING_DELAY_S = 0.002  # Mirrors DEFAULT_DDP_TRANSPORT for compatibility.

    # -- Keep-Alive (KA) Payloads --
    KA_WHITE_OPEN = [0xA0, 0x0F, 0x8A, 0xFF, 0x4A, 0xFF]  # Session Open Request
    KA_WHITE_ACCEPT = [0xA1, 0x0F, 0x8A, 0xFF, 0x4A, 0xFF] # Session Accept / Pong
    KA_KEEP_PING = [0xA3]                                  # Keep-Alive Ping (We send)
    KA_CLOSE = [0xA8]                                      # Session Close

    KA_RED_PRESENT = [0xA0, 0x07, 0x00]                    # Cluster broadcast
    KA_RED_OPEN = [0xA1, 0x0F]                             # Our reply to PRESENT
    KA_RED_ACCEPT = [0xA1, 0x0F]                           # Cluster reply to PING

    # -- DDP Packet Type Masks --
    PKT_TYPE_MASK = 0xF0
    PKT_SEQ_MASK = 0x0F
    PKT_TYPE_DATA_END = 0x10  # 0x1x (end of frame, expects ACK)
    PKT_TYPE_DATA_BODY = 0x20 # 0x2x (frame body, no ACK)
    PKT_TYPE_ACK = 0xB0       # 0xBx (ACK)
    
    # -- Block Limits --
    # Vlad's Limit: Clusters corrupt data if >6 frames (42 bytes) are sent without ACK.
    MAX_BYTES_PER_BLOCK = 42  # Mirrors DEFAULT_DDP_TRANSPORT for compatibility.

    def __init__(self, config: dict):
        self.cfg = config
        self.transport_profile = DDPTransportProfile(
            frame_gap_s=float(config.get(
                'ddp_frame_gap_s', DEFAULT_DDP_TRANSPORT.frame_gap_s)),
            max_message_bytes=int(config.get(
                'ddp_max_message_bytes', DEFAULT_DDP_TRANSPORT.max_message_bytes)),
            max_unacked_frames=int(config.get(
                'ddp_max_unacked_frames', DEFAULT_DDP_TRANSPORT.max_unacked_frames)),
            white_post_message_delay_s=float(config.get(
                'ddp_white_post_message_delay_s',
                DEFAULT_DDP_TRANSPORT.white_post_message_delay_s)),
        )
        self.state = DDPState.DISCONNECTED
        self.state_generation = 0
        self.dis_mode = DisMode.UNKNOWN
        self.i_am_opener = False
        self.last_ka_sent = 0.0
        self.send_seq_num = 0
        self.screen_released_by_cluster = False

        # For _recv_specific to store stray packets
        self._last_received_ack = None
        self._last_received_data = None
        self._data_inbox = deque()
        self._last_screen_status = None

        self.channel = config.get('can_channel', 'can0')
        self.bitrate = config.get('can_bitrate', 100000)
        
        # Allow overriding DDP IDs for modules like Telephone (0x6C5/0x6C4)
        # Defaults to Navigation (0x6C0/0x6C1)
        self.tx_id = config.get('ddp_tx_id', 0x6C0)
        self.rx_id = config.get('ddp_rx_id', 0x6C1)
        self.rx_mask = config.get('ddp_rx_mask', 0x7FF)
        
        logger.debug(f"CAN config: {{'bitrate': {self.bitrate}, 'interface': 'socketcan', 'channel': '{self.channel}', 'tx': 0x{self.tx_id:X}, 'rx': 0x{self.rx_id:X}}}")
        
        self.bus = None
        if not self.reconnect_bus():
            raise DDPCANError(f"Failed to open CAN bus on {self.channel}")

    def _transport_settings(self):
        """Return the explicit DDP-on-TP2 compatibility settings."""
        return getattr(self, 'transport_profile', DEFAULT_DDP_TRANSPORT)

    def reconnect_bus(self) -> bool:
        """Closes and re-opens the CAN bus interface to recover from network/socket errors."""
        logger.info("Attempting to reconnect CAN bus...")
        if hasattr(self, 'bus') and self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception as e:
                logger.warning(f"Error shutting down old CAN bus: {e}")
            self.bus = None

        try:
            self.bus = can.Bus(
                interface='socketcan',
                channel=self.channel,
                bitrate=self.bitrate,
                timeout=0.01  # Non-blocking
            )
            self.bus.set_filters([
                {"can_id": self.rx_id, "can_mask": self.rx_mask, "extended": False}
            ])
            logger.info("CAN bus reconnected successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to reconnect CAN bus on '{self.channel}': {e}")
            logger.error(f"Make sure '{self.channel}' is up (e.g., sudo ip link set {self.channel} up type can bitrate {self.bitrate})")
            return False

    def __del__(self):
        """Shuts down the CAN bus connection on exit."""
        if hasattr(self, 'bus') and self.bus is not None:
            logger.debug("Shutting down CAN bus.")
            try:
                self.bus.shutdown()
            except:
                pass

    # --- State and Helper Functions ---
    def _set_state(self, new_state: DDPState):
        """Centralized state transition function."""
        if self.state == new_state:
            return
        
        logger.info(f"State transition: {self.state.name} -> {new_state.name}")
        old_state = self.state
        self.state = new_state
        self.state_generation = getattr(self, "state_generation", 0) + 1

        if new_state == DDPState.READY and old_state == DDPState.PAUSED:
            logger.info("Resuming from PAUSE.")
        
        if new_state in [DDPState.DISCONNECTED, DDPState.PAUSED]:
            self.screen_released_by_cluster = True
        
        # Reset context on disconnection
        if new_state == DDPState.DISCONNECTED:
            self._data_inbox.clear()
            self._last_screen_status = None
            self.dis_mode = DisMode.UNKNOWN
            self.i_am_opener = False
            self.send_seq_num = 0
            # Shutdown and clear the bus to guarantee a fresh socket on next session open
            if hasattr(self, 'bus') and self.bus is not None:
                try:
                    self.bus.shutdown()
                except Exception as e:
                    logger.debug(f"Error shutting down CAN bus during disconnect: {e}")
                self.bus = None
            # Wait for cluster to finish clean up
            time.sleep(1.2)

    def payload_is(self, data: List[int], expected_payload: List[int]) -> bool:
        """Helper to check payload regardless of the sequence number (first byte)."""
        if not data or len(data) < 1: return False
        if not expected_payload:
            return False
        # Capability/geometry fields vary with cluster and selected service.
        # Recognize the observed command shape; retain its actual values.
        if expected_payload[0] == 0x09 and len(expected_payload) == 7:
            matches = len(data) == 8 and data[1] == 0x09
            if matches:
                self.capability_record = list(data[1:])
            return matches
        if expected_payload[0] == 0x30 and len(expected_payload) == 5:
            matches = len(data) == 6 and data[1] == 0x30
            if matches:
                self.geometry_record = list(data[1:])
            return matches
        return data[1:] == expected_payload

    # --- Low-Level CAN & DDP I/O ---

    def _flashing_inhibited(self):
        """Abandon the session without transmitting a disconnect or stale retries."""
        with transmission_guard() as allowed:
            if allowed:
                return False
        self._reset_for_flashing()
        return True

    def _reset_for_flashing(self):
        if self.state != DDPState.DISCONNECTED:
            self.state_generation = getattr(self, "state_generation", 0) + 1
        self.state = DDPState.DISCONNECTED
        self.dis_mode = DisMode.UNKNOWN
        self.i_am_opener = False
        self.send_seq_num = 0
        self.last_ka_sent = 0.0
        self.screen_released_by_cluster = True
        self._last_received_ack = None
        self._last_received_data = None
        self._data_inbox.clear()
        self._last_screen_status = None
        if self.bus is not None:
            try:
                self.bus.shutdown()
            finally:
                self.bus = None

    def send_can(self, can_id: int, data: List[int]):
        """Sends a raw CAN message to the bus with pacing and Error 105 retry."""
        if self._flashing_inhibited():
            raise DDPCANError("Flashing Mode inhibits DIS transmissions")
        if not hasattr(self, 'bus') or self.bus is None:
            logger.warning("CAN bus not initialized. Attempting to reconnect...")
            if not self.reconnect_bus():
                raise DDPCANError("CAN bus not initialized.")
        data_hex = ' '.join(f'{b:02X}' for b in data)
        logger.debug("-> 0x%03X: %s", can_id, data_hex)
        
        max_retries = 10
        retry_delay = 0.05 # 50ms
        
        for attempt in range(max_retries):
            try:
                msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=False)
                with transmission_guard() as allowed:
                    if not allowed:
                        self._reset_for_flashing()
                        raise DDPCANError("Flashing Mode inhibits DIS transmissions")
                    self.bus.send(msg, timeout=0.5)
                frame_gap = self._transport_settings().frame_gap_s
                if frame_gap > 0:
                    time.sleep(frame_gap)
                return # Success
            except Exception as e:
                # 105 is 'No buffer space available' on SocketCAN
                if "105" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"CAN Buffer Full (Error 105), retry {attempt+1}/{max_retries}...")
                    time.sleep(retry_delay)
                    continue
                
                logger.error(f"CAN Send Error: {e}")
                raise DDPCANError(f"CAN Send Error: {e}")

    def _recv(self, timeout_s: float = 0.01) -> Optional[List[int]]:
        """Receives and logs a single CAN message from the bus (ID)."""
        if not hasattr(self, 'bus') or self.bus is None:
            logger.warning("CAN bus not initialized. Attempting to reconnect...")
            if not self.reconnect_bus():
                return None
        try:
            msg = self.bus.recv(timeout_s)
            if msg:
                if msg.arbitration_id == self.rx_id:
                    data = list(msg.data)
                    logger.debug("<- 0x%03X: %s", self.rx_id, ' '.join(f'{b:02X}' for b in data))
                    time.sleep(self._transport_settings().frame_gap_s)
                    return data
            return None
        except (can.CanError, OSError) as e:
            logger.error(f"CAN Receive Error: {e}")
            raise DDPCANError(f"CAN Receive Error: {e}")

    def send_ack(self, received_seq_num: int):
        """Sends a DDP ACK (0xB0 + seq+1) for a received packet."""
        ack_packet = list(build_ack(received_seq_num))
        logger.debug(f"Sending ACK {ack_packet[0]:02X}")
        self.send_can(self.tx_id, ack_packet)

    def _handle_incoming_packet(self, data: List[int]) -> bool:
        """
        Central handler for all "background" packets (Keep-Alives, ACKs, etc.).
        Returns True if the packet was handled, False if it's a data packet.
        """
        if not data:
            return False

        opcode, _ = classify_frame(data)
        msg_type_prefix = opcode << 4
        
        # --- Type 0xA_ (Session Control) ---
        if msg_type_prefix == 0xA0:
            if data == self.KA_CLOSE:
                logger.warning("Cluster sent A8 (Close) -> closing session")
                self._set_state(DDPState.DISCONNECTED)
                return True
            
            # Session drop detection
            if data == self.KA_RED_PRESENT and self.dis_mode == DisMode.RED and self.state == DDPState.READY:
                logger.warning("Red DIS broadcast detected while READY. Session dropped.")
                self._set_state(DDPState.DISCONNECTED)
                return True

            # Cluster Ping (0xA3 or 0xA3 00, etc.)
            if data[0] == self.KA_KEEP_PING[0]:
                logger.debug(f"Cluster sent Keep-Alive {data} -> replying A1")
                reply = self.KA_RED_ACCEPT if self.dis_mode == DisMode.RED else self.KA_WHITE_ACCEPT
                self.send_can(self.tx_id, reply)
                return True
            
            # Cluster Pong (to our Ping)
            if (data == self.KA_WHITE_ACCEPT or data == self.KA_RED_ACCEPT) and self.i_am_opener:
                logger.debug("Cluster replied A1 to our A3")
                return True
            
            # Ignore unhandled 0xA_ packets
            return True # Assume it was session-related

        # --- Type 0xB_ (ACK) ---
        if msg_type_prefix == self.PKT_TYPE_ACK:
            logger.debug(f"<- Received ACK {data[0]:02X}")
            self._last_received_ack = data # Store for _recv_specific
            return True

        # --- Type 0x0_, 0x1_, 0x2_ (Data) ---
        if msg_type_prefix in [0x00, self.PKT_TYPE_DATA_END, self.PKT_TYPE_DATA_BODY]:
            # Check for benign Graphics ACKs starting with 0x0B or 0x1B
            payload = data[1:]
            if payload == DDPMessages.STAT_GRAPHIC_ACK_WHITE or payload == DDPMessages.STAT_GRAPHIC_ACK_RED:
                logger.debug(f"<- Swallowing background Graphics ACK {payload}")
                if msg_type_prefix in [0x00, self.PKT_TYPE_DATA_END]:
                    self.send_ack(data[0] & self.PKT_SEQ_MASK)
                return True
            return False # Not handled, it's data for the caller

        # --- Type 0x9_ (transport ACK, receiver not ready) ---
        if msg_type_prefix == 0x90:
            logger.debug("Receiver not-ready ACK %02X", data[0])
            self._last_received_ack = data
            return True

        logger.warning(f"Unknown unhandled packet type {data[0]:02X}")
        return True # Treat as handled to avoid breaking loops

    def _retain_data(self, data):
        """ACK once and retain application packets arriving during any wait."""
        opcode, sequence = classify_frame(data)
        if opcode in (0, 1):
            self.send_ack(sequence)
        if len(data) == 3 and data[1] == 0x53:
            self._last_screen_status = data[2]
            if data[2] in (0x04, 0x08, 0x84, 0x88) and self.state == DDPState.READY:
                self._set_state(DDPState.PAUSED)
            elif data[1:] in (DDPMessages.STAT_FREE_HALF, DDPMessages.STAT_FREE_FULL):
                # Match normal FREE dispatch before the ACK wait can allow
                # more graphics. Initialization statuses remain asynchronous.
                self.screen_released_by_cluster = True
                if self.state in (DDPState.READY, DDPState.PAUSED):
                    self._set_state(DDPState.PAUSED)
        if data[1:] == DDPMessages.CMD_REINIT_REQ and self.state == DDPState.READY:
            self._set_state(DDPState.PAUSED)
        if len(self._data_inbox) >= 128:
            self._set_state(DDPState.DISCONNECTED)
            raise DDPHandshakeError("Application receive queue overflow")
        self._data_inbox.append(data)

    def _recv_specific(self, expected_data, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            data = self._recv(min(0.05, max(0, deadline-time.monotonic())))
            if not data:
                continue
            if data == expected_data:
                return data
            if (len(expected_data) == 1 and expected_data[0] >> 4 == 0xB
                    and len(data) == 1 and data[0] >> 4 in (0x9, 0xB)):
                # The sequence identifies the receiver's next required frame.
                # The block sender validates it before accepting or replaying.
                return data
            if not self._handle_incoming_packet(data):
                self._retain_data(data)
            if self.state == DDPState.DISCONNECTED:
                return None
        return None

    def _wait_receiver_delay(self, delay_s):
        """Keep servicing status/session traffic during transport backpressure."""
        deadline = time.perf_counter() + delay_s
        while time.perf_counter() < deadline:
            if self._flashing_inhibited():
                return
            remaining = deadline - time.perf_counter()
            data = self._recv(min(.01, max(0, remaining)))
            if data and not self._handle_incoming_packet(data):
                self._retain_data(data)
            if self.state == DDPState.DISCONNECTED:
                return

    def _send_acknowledged_block(self, block):
        """Retain one block for sequence-directed TP2 retransmission.

        SAE J2819 sections 6.2.4--6.2.6: a matching 9n accepts data but imposes
        T_Wait; an earlier n asks to replay from n. A missing ACK repeats only
        the ACK-request frame. Neither condition changes screen ownership.
        """
        block = tuple(bytes(frame) for frame in block)
        expected = list(build_ack(block[-1][0] & self.PKT_SEQ_MASK))
        resend = block
        initial_state = self.state
        profile = self._transport_settings()
        not_ready_count = ack_retry_count = block_retry_count = 0

        def fail(reason):
            # Unknown receive progress cannot safely start a different message.
            self.close_session()
            raise DDPAckTimeoutError(reason)

        while True:
            for frame in resend:
                if self.state != initial_state:
                    raise DDPAckTimeoutError("Session or display state changed during a block")
                self.send_can(self.tx_id, list(frame))
                self.send_seq_num = ((frame[0] & self.PKT_SEQ_MASK) + 1) & 0xF
            reply = self._recv_specific(expected, 1000)
            if self.state != initial_state:
                raise DDPAckTimeoutError("Session or display state changed during ACK wait")
            if not reply:
                ack_retry_count += 1
                if ack_retry_count > profile.max_ack_retries:
                    fail(f"No ACK {expected[0]:02X} after bounded retries")
                logger.warning("Missing ACK %02X; repeating its request frame", expected[0])
                resend = (block[-1],)
                continue
            opcode, sequence = classify_frame(reply)
            if opcode not in (0x9, 0xB) or len(reply) != 1:
                fail("Malformed transport acknowledgment")
            if opcode == 0x9:
                not_ready_count += 1
                if not_ready_count > profile.max_not_ready_retries:
                    fail("Receiver remained not ready after bounded retries")
                logger.info("Receiver not ready at sequence %X; waiting %.3fs",
                            sequence, profile.receiver_not_ready_wait_s)
                self._wait_receiver_delay(profile.receiver_not_ready_wait_s)
                if self.state != initial_state:
                    raise DDPAckTimeoutError("Session or display state changed during receiver wait")
            if sequence == expected[0] & self.PKT_SEQ_MASK:
                return
            offset = next((i for i, frame in enumerate(block)
                           if frame[0] & self.PKT_SEQ_MASK == sequence), None)
            if offset is None:
                fail("Receiver requested a sequence outside the pending block")
            block_retry_count += 1
            if block_retry_count > profile.max_not_ready_retries:
                fail("Receiver repeatedly requested block retransmission")
            logger.info("Retransmitting %d retained frames from sequence %X",
                        len(block)-offset, sequence)
            resend = block[offset:]

    def _recv_and_ack_data(self, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if self._data_inbox:
                data = self._data_inbox.popleft()
            else:
                data = self._recv(min(0.05, max(0, deadline-time.monotonic())))
                if not data:
                    continue
                if self._handle_incoming_packet(data):
                    if self.state == DDPState.DISCONNECTED:
                        return None
                    continue
                self._retain_data(data)
                data = self._data_inbox.popleft()
            # Screen statuses are asynchronous during initialization. They do
            # not replace its capability/geometry response or reset its deadline.
            if self.state == DDPState.INITIALIZING and len(data) == 3 and data[1] == 0x53:
                continue
            return data
        return None

    def send_data_packet(self, data: List[int], is_multi_packet_frame_body: bool = False):
        """
        Sends a single DDP data packet.
        Handles sequence numbers and waits for ACK on 0x1x (end-of-frame) packets.
        Raises DDPAckTimeoutError on failure.
        """
        opcode = 2 if is_multi_packet_frame_body else 1
        packet = list(build_data_frame(bytes(data), self.send_seq_num, opcode))
        
        if is_multi_packet_frame_body:
            self.send_can(self.tx_id, packet)
            self.send_seq_num = (self.send_seq_num + 1) % 16
            return # 0x2x packets are not ACKed
        self._send_acknowledged_block([packet])

    # --- Public API Methods ---

    def send_ddp_frame(self, payload: List[int], pacing: bool = True) -> bool:
        """Send one graphics message, ACKing continuation blocks as needed.

        The historical max_message_bytes setting is an ACK-block byte budget.
        It must not insert a message end inside an application command. The
        0x0 continuation frame requests an ACK; only the final frame uses 0x1.
        """
        if self.state != DDPState.READY:
            logger.warning("Attempted to send frame while not READY. Ignoring.")
            return False
        if not payload:
            return True

        profile = self._transport_settings()
        frames_per_block = min(15, profile.max_unacked_frames,
                               max(1, profile.max_message_bytes // 7))
        frames, _ = segment_message(
            bytes(payload), self.send_seq_num,
            block_size=frames_per_block, length_prefixed=False)
        try:
            block = []
            for frame in frames:
                if self.state != DDPState.READY:
                    return False
                block.append(frame)
                if frame[0] >> 4 in (0, 1):
                    self._send_acknowledged_block(block)
                    block = []
                    # Preserve the cluster's pacing at every acknowledged
                    # block, including continuation blocks within a message.
                    if pacing and self.dis_mode == DisMode.WHITE:
                        time.sleep(profile.white_post_message_delay_s)
        except DDPAckTimeoutError as e:
            logger.error(f"DDP Frame ACK timeout: {e}. Session might be unstable.")
            return False
        except DDPCANError as e:
            logger.error(f"CAN hardware error: {e}. Session closing.")
            self._set_state(DDPState.DISCONNECTED)
            return False
        return True

    def _white_dis_passive_open(self) -> bool:
        """(Private) Waits for the White DIS Cluster to initiate (sends A0)."""
        logger.info("PASSIVE WHITE: Waiting for cluster A0...")
        data = self._recv_specific(self.KA_WHITE_OPEN, 1000)
        if data == self.KA_WHITE_OPEN:
            logger.info("Cluster opened -> sending A1")
            self.send_can(self.tx_id, self.KA_WHITE_ACCEPT)
            self.i_am_opener = False
            self._set_state(DDPState.SESSION_ACTIVE)
            self.dis_mode = DisMode.WHITE
            return True
        return False

    def _white_dis_active_open(self) -> bool:
        """(Private) Actively initiates the White DIS session by sending A0."""
        logger.info("ACTIVE WHITE: Sending A0...")
        self.send_can(self.tx_id, self.KA_WHITE_OPEN)
        if self._recv_specific(self.KA_WHITE_ACCEPT, 500):
            logger.info("A1 received")
            self.i_am_opener = True
            self._set_state(DDPState.SESSION_ACTIVE)
            self.dis_mode = DisMode.WHITE
            return True
        return False

    def _red_dis_open(self) -> bool:
        """(Private) Performs the handshake for an Old Red DIS cluster."""
        logger.info("RED DIS: Detected cluster broadcast. Starting Red DIS handshake.")
        
        try:
            # Step 1: Send A1 0F
            logger.info("RED DIS: Sending A1 0F...")
            self.send_can(self.tx_id, self.KA_RED_OPEN)
            
            # Step 2: Send A3 right after
            logger.info("RED DIS: Sending A3...")
            self.send_can(self.tx_id, self.KA_KEEP_PING)
            
            # Step 3: Wait for cluster's A1 0F reply
            if not self._recv_specific(self.KA_RED_ACCEPT, 500):
                raise DDPHandshakeError("Cluster did not reply with A1 0F")
            logger.info("RED DIS: Received A1 0F reply from cluster.")
            
            # Step 4: Exchange A3 / A1 0F four times
            for i in range(4):
                logger.info(f"RED DIS: Sending A3 (Loop {i+1}/4)...")
                self.send_can(self.tx_id, self.KA_KEEP_PING)
                if not self._recv_specific(self.KA_RED_ACCEPT, 500):
                    raise DDPHandshakeError(f"Cluster did not reply on loop {i+1}")
                logger.info(f"RED DIS: Received A1 0F (Loop {i+1}/4).")
            
            logger.info("RED DIS: Handshake complete. Session is active.")
            self.i_am_opener = True
            self._set_state(DDPState.SESSION_ACTIVE)
            self.dis_mode = DisMode.RED
            return True

        except Exception as e:
            logger.error(f"RED DIS: Handshake failed with error: {e}")
            return False

    def detect_and_open_session(self) -> bool:
        """
        Detects cluster type (Red or White) and establishes a Keep-Alive session.
        This is Step 1 of the connection.
        """
        if self._flashing_inhibited():
            return False
        if self.state != DDPState.DISCONNECTED:
            logger.warning("Session already open.")
            return True
            
        logger.info("Detecting cluster type (Red or White)...")
        
        # Listen for 1.5 seconds to see what's on the bus
        start = time.time()
        while time.time() - start < 1.5:
            data = self._recv(0.1) # Poll every 100ms
            if not data:
                continue
            
            # --- Red DIS Detection ---
            if data == self.KA_RED_PRESENT:
                logger.info("Found Red DIS broadcast (A0 07 00).")
                return self._red_dis_open()
                
            # --- White DIS (Passive) Detection ---
            if data == self.KA_WHITE_OPEN:
                logger.info("Found White DIS passive open (A0 0F...).")
                self.send_can(self.tx_id, self.KA_WHITE_ACCEPT)
                self.i_am_opener = False
                self._set_state(DDPState.SESSION_ACTIVE)
                self.dis_mode = DisMode.WHITE
                return True
            
            # --- Existing Session (A3 Ping) Detection ---
            if data[0] == self.KA_KEEP_PING[0]:
                logger.info("Found existing session via A3 ping. Replying A1.")
                # If we haven't seen RED PRESENT, assume WHITE for the ACK
                reply = self.KA_RED_ACCEPT if self.dis_mode == DisMode.RED else self.KA_WHITE_ACCEPT
                self.send_can(self.tx_id, reply)
                self.i_am_opener = False # We are joining an existing session
                self._set_state(DDPState.SESSION_ACTIVE)
                if self.dis_mode == DisMode.UNKNOWN:
                    self.dis_mode = DisMode.WHITE # Default assumption if unknown
                return True
        
        # --- No broadcast detected ---
        # Assume White DIS, try Active Open
        logger.info("No Red DIS broadcast. Assuming White DIS, attempting Active Open.")
        return self._white_dis_active_open()

    def close_session(self):
        """Actively closes the DDP session by sending A8 (Hard Close)."""
        if self.state != DDPState.DISCONNECTED:
            logger.info("Actively closing session (sending A8)...")
            self.send_can(self.tx_id, self.KA_CLOSE)
            self._set_state(DDPState.DISCONNECTED)

    def release_screen(self) -> bool:
        """
        Sends a 'Release Screen' command (0x33) to the cluster.
        """
        if self.state != DDPState.READY:
            logger.warning("Cannot release screen, session not READY.")
            return False
        
        logger.info("Releasing DIS screen to Bordcomputer (sending 0x33)...")
        payload = [0x33]
        try:
            self.send_data_packet(payload, is_multi_packet_frame_body=False)
            logger.info("Screen released. Session remains open.")
            return True
        except (DDPAckTimeoutError, DDPCANError) as e:
            logger.error(f"Failed to send release screen packet: {e}. Session may be dead.")
            self._set_state(DDPState.DISCONNECTED)
            return False

    # --- Initialization (Step 2) ---

    def _get_init_payloads(self) -> dict:
        """Returns the correct set of payloads based on self.dis_mode."""
        PL_LOG_3 = [0x00, 0x01]
        PL_LOG_5 = [0x00, 0x01]
        PL_LOG_23_COMMON = [0x21, 0x3B, 0xA0, 0x00]

        if self.dis_mode == DisMode.WHITE:
            logger.debug("Using WHITE DIS payload set.")
            return {
                "PL_LOG_3": PL_LOG_3,
                "PL_LOG_5": PL_LOG_5,
                "PL_LOG_11": [0x09, 0x20, 0x0B, 0x50, 0x0A, 0x24, 0x50],
                "PL_LOG_11_ALT": [0x09, 0x20, 0x0B, 0x50, 0x09, 0x24, 0x4A], # Alternate White Cluster
                "PL_LOG_14": [0x30, 0x39, 0x00, 0x30, 0x00],
                "PL_LOG_14_ALT": [0x30, 0x39, 0x00, 0x32, 0x00], # Alternate White Cluster
                "PL_LOG_18": [0x09, 0x20, 0x0B, 0x50, 0x0A, 0x24, 0x50],
                "PL_LOG_18_ALT": [0x09, 0x20, 0x0B, 0x50, 0x09, 0x24, 0x4A], # Alternate White Cluster
                "PL_LOG_21": [0x30, 0x39, 0x00, 0x30, 0x00],
                "PL_LOG_21_ALT": [0x30, 0x39, 0x00, 0x32, 0x00], # Alternate White Cluster
                "PL_LOG_23": PL_LOG_23_COMMON,
                "PL_LOG_27": [0x21, 0x3B, 0xA0, 0x00]
            }
        else: # DisMode.RED
            logger.debug("Using RED DIS payload set.")
            return {
                "PL_LOG_3": PL_LOG_3,
                "PL_LOG_5": PL_LOG_5,
                "PL_LOG_11": [0x09, 0x20, 0x0B, 0x50, 0x00, 0x32, 0x44],
                "PL_LOG_14": [0x30, 0x33, 0x00, 0x31, 0x00],
                "PL_LOG_23": PL_LOG_23_COMMON,
                # Other payloads not needed for the shorter Red path
                "PL_LOG_18": [],
                "PL_LOG_21": [],
                "PL_LOG_27": []
            }

    def _init_common_start(self):
        """Sends the first 4 packets common to all handshakes."""
        # Step 1: Query capabilities
        self.send_data_packet([0x15, 0x01, 0x01, 0x02, 0x00, 0x00])
        logger.info("Init Step 1 (Capabilities Query) sent!")

        # Step 2: Receive capabilities response
        data = self._recv_and_ack_data(1000)
        if not data:
             raise DDPHandshakeError("Init Step 1 timeout: No response from cluster.")
        
        # Detection: Standard mode responds with 0x09 (Nav), High-Res uses 0x15 (Telem)
        if data[1] == 0x15:
            logger.info("Detected HIGH-RES (Telem/Phone) Mode via 0x15 response.")
        elif not self.payload_is(data, self.PL["PL_LOG_3"]):
            logger.warning(f"Step 2 unexpected payload: got {data}, expected {self.PL['PL_LOG_3']}. Proceeding anyway.")
        
        logger.info("Init 2/x passed!")

        self.send_data_packet([0x01, 0x01, 0x00]) # Step 3
        logger.info("Init 3/x passed!")

        self.send_data_packet([0x08]) # Step 4
        logger.info("Init 4/x passed!")

    def _init_path_b_white(self):
        """Handles the short White DIS handshake path."""
        logger.info("Following Path B (White Short)...")
        self.send_data_packet([0x20, 0x3B, 0xA0, 0x00]) # Step 5
        logger.info("Init 5/x (Path B) passed!")

    def _init_path_c_white(self):
        """Handles the long White DIS handshake path."""
        logger.info("Following Path C (White Long)...")
        self.send_data_packet([0x01, 0x01, 0x00]) # Step 5
        logger.info("Init 5/x passed!")
        
        data = self._recv_and_ack_data(1000) # Step 6
        if self.payload_is(data, self.PL["PL_LOG_14"]):
            logger.info("Init 6/x passed (Regular)!")
        elif self.payload_is(data, self.PL.get("PL_LOG_14_ALT")):
            logger.info("Init 6/x passed (ALT)!")
        else:
            raise DDPHandshakeError(f"Step 6 failed: wait PL {self.PL['PL_LOG_14']}, got {data}")
        
        self.send_data_packet([0x08]) # Step 7
        logger.info("Init 7/x passed!")

        data = self._recv_and_ack_data(1000) # Step 8
        if self.payload_is(data, self.PL["PL_LOG_18"]):
            logger.info("Init 8/x passed (Regular)!")
        elif self.payload_is(data, self.PL.get("PL_LOG_18_ALT")):
            logger.info("Init 8/x passed (ALT)!")
        else:
            raise DDPHandshakeError(f"Step 8 failed: wait PL {self.PL['PL_LOG_18']}, got {data}")

        self.send_data_packet([0x20, 0x3B, 0xA0, 0x00]) # Step 9
        logger.info("Init 9/x passed!")

        data = self._recv_and_ack_data(1000) # Step 10
        if self.payload_is(data, self.PL["PL_LOG_21"]):
            logger.info("Init 10/x passed (Regular)!")
        elif self.payload_is(data, self.PL.get("PL_LOG_21_ALT")):
            logger.info("Init 10/x passed (ALT)!")
        else:
            raise DDPHandshakeError(f"Step 10 failed: wait PL {self.PL['PL_LOG_21']}, got {data}")

        data = self._recv_and_ack_data(1000) # Step 11
        if not self.payload_is(data, self.PL["PL_LOG_23"]):
            raise DDPHandshakeError(f"Step 11 failed: wait PL {self.PL['PL_LOG_23']}, got {data}")
        logger.info("Init 11/x passed!")

        self.send_data_packet([0x20, 0x3B, 0xA0, 0x00]) # Step 12
        logger.info("Init 12/x passed!")

        data = self._recv_and_ack_data(1000) # Step 13
        if not self.payload_is(data, self.PL["PL_LOG_27"]):
            raise DDPHandshakeError(f"Step 13 failed: wait PL {self.PL['PL_LOG_27']}, got {data}")
        logger.info("Init 13/x passed!")

        self.send_data_packet([0x33]) # Step 14
        logger.info("Init 14/x passed!")

        self.send_data_packet([0x33]) # Step 15
        logger.info("Init 15/x passed!")

    def _init_path_red(self):
        """Handles the Red DIS handshake path."""
        logger.info("Following RED DIS Short Path...")
        data = self._recv_and_ack_data(1000) # Wait for PL_LOG_14
        if not self.payload_is(data, self.PL["PL_LOG_14"]):
            raise DDPHandshakeError(f"RED Path failed (Step 2): wait PL {self.PL['PL_LOG_14']}, got {data}")
        logger.info("Init 2/x (Red) passed!")
        
        self.send_data_packet([0x20, 0x3B, 0xA0, 0x00]) # Send 13 20...
        logger.info("Init 3/x (Red) passed!")

        data = self._recv_and_ack_data(1000) # Wait for PL_LOG_23
        if not self.payload_is(data, self.PL["PL_LOG_23"]):
            raise DDPHandshakeError(f"RED Path failed (Step 4): wait PL {self.PL['PL_LOG_23']}, got {data}")
        logger.info("Init 4/x (Red) passed!")
        
        self.send_data_packet([0x33]) # Send 14 33
        logger.info("Init 5/x (Red) passed!")

    def perform_initialization(self) -> bool:
        """
        Performs the complex DDP initialization handshake (Step 2).
        This must be called after a session is active (Step 1).
        """
        logger.info(f"Starting DDP Step 2 Initialization for {self.dis_mode.name} DIS...")
        self._set_state(DDPState.INITIALIZING)
        self.send_seq_num = 0
        self._last_screen_status = None

        if self.dis_mode == DisMode.UNKNOWN:
             logger.error("DIS mode is unknown. Cannot perform initialization.")
             self._set_state(DDPState.DISCONNECTED)
             return False

        # Get correct payloads for our DIS type
        self.PL = self._get_init_payloads()

        try:
            # --- Common Start ---
            self._init_common_start()

            # --- Handshake Fork ---
            # Wait for the packet that determines which path to take
            data = self._recv_and_ack_data(1000)
            if data is None: raise DDPHandshakeError("Timed out waiting for handshake fork packet.")
            
            # Handle out-of-order PL_LOG_5 (seen in some logs)
            if self.payload_is(data, self.PL["PL_LOG_5"]):
                logger.info("Handshake Fork: Got out-of-order packet (PL 00 01). Accepting.")
                data = self._recv_and_ack_data(1000)
                if data is None: raise DDPHandshakeError("Timed out after out-of-order packet.")

            # --- Path B (White Short) ---
            if self.payload_is(data, self.PL["PL_LOG_14"]) and self.dis_mode == DisMode.WHITE:
                self._init_path_b_white()
            
            # --- Path C (White Long) or Path Red ---
            elif self.payload_is(data, self.PL["PL_LOG_11"]) or self.payload_is(data, self.PL.get("PL_LOG_11_ALT")):
                if self.payload_is(data, self.PL.get("PL_LOG_11_ALT")):
                    logger.info("Handshake Fork: Got PL_LOG_11 (ALT)")
                else:
                    logger.info("Handshake Fork: Got PL_LOG_11 (Regular)")
                if self.dis_mode == DisMode.RED:
                    self._init_path_red()
                else:
                    self._init_path_c_white()
            
            else:
                raise DDPHandshakeError(f"Handshake fork failed. Got unhandled packet {data}")

            # --- Final Keep-Alive Exchange ---
            logger.info("Sending final A3 Keep-Alive to complete handshake...")
            self.send_can(self.tx_id, self.KA_KEEP_PING)
            
            reply = self.KA_RED_ACCEPT if self.dis_mode == DisMode.RED else self.KA_WHITE_ACCEPT
            if not self._recv_specific(reply, 1000):
                raise DDPHandshakeError(f"Did not receive final {reply} ACK")
            
            logger.info(f"DDP Initialization COMPLETE")
            self._set_state(DDPState.READY)
            if self._last_screen_status in (0x04, 0x08, 0x84, 0x88):
                self._set_state(DDPState.PAUSED)
            self.last_ka_sent = time.time()
            return True

        except (DDPHandshakeError, DDPAckTimeoutError) as e:
            logger.warning(f"Handshake Error (Timeout or Break): {e}")
            if self.state == DDPState.DISCONNECTED:
                logger.warning("Session was explicitly closed/disconnected. Aborting initialization.")
                return False
            self.was_handshake_assumed = False
            self.close_session()
            return False
        except DDPCANError as e:
            self.was_handshake_assumed = False
            logger.error(f"Handshake Hardware Error: {e}")
            self._set_state(DDPState.DISCONNECTED)
            return False
        finally:
            if self.state == DDPState.READY and not getattr(self, 'was_handshake_assumed', False):
                 self.was_handshake_assumed = False # Handshake was clean
            # Clean up payload dict
            if hasattr(self, 'PL'):
                del self.PL

    # --- Main Loop Functions ---

    def send_keepalive_if_needed(self):
        """Sends an A3 Keep-Alive ping if we are the opener and 2s have passed."""
        if self._flashing_inhibited():
            return
        # We must allow Keep-Alives even when PAUSED, to prevent session drop
        if self.state not in [DDPState.READY, DDPState.PAUSED]:
            return
        
        if self.i_am_opener and time.time() - self.last_ka_sent > 2.0:
            logger.debug("Sending A3 Keep-Alive")
            self.send_can(self.tx_id, self.KA_KEEP_PING)
            self.last_ka_sent = time.time()

    def poll_bus_events(self):
        """
        Main polling function. This must be called continuously.
        Handles background traffic, status interrupts (Busy/Free), and Re-Init requests.
        """
        if self._flashing_inhibited():
            return
        if self.state == DDPState.DISCONNECTED:
            return

        # Retained packets were already acknowledged at receive time.
        already_acked = bool(self._data_inbox)
        data = self._data_inbox.popleft() if already_acked else self._recv(0)
        if not data:
            return
            
        # 1. Handle Keep-Alives / Background ACKs / Session Logic
        is_background_packet = self._handle_incoming_packet(data)

        # 2. Process Data Packets (Status Updates / Re-Init Requests)
        if not is_background_packet:
            opcode, msg_seq = classify_frame(data)
            msg_type = opcode << 4
            payload = data[1:]
            if len(payload) == 2 and payload[0] == 0x53:
                self._last_screen_status = payload[1]

            # We must ALWAYS ACK data packets (Type 0x00 or 0x10) immediately,
            # regardless of whether we handle the content.
            if not already_acked and msg_type in [0x00, self.PKT_TYPE_DATA_END]:
                self.send_ack(msg_seq)

            # --- DETECT PAUSE (Cluster Claims Screen) ---
            if payload in [DDPMessages.STAT_BUSY_WARN_HALF, DDPMessages.STAT_BUSY_WARN_FULL, DDPMessages.STAT_BUSY_HALF, DDPMessages.STAT_BUSY_FULL]:
                
                if self.state != DDPState.PAUSED:
                    logger.warning(f"Cluster INTERRUPT (Status {payload}). Pausing...")
                    self._set_state(DDPState.PAUSED)
                    # Urgent Ping to keep session alive during warning
                    self.send_can(self.tx_id, self.KA_KEEP_PING)

            # --- DETECT FREE (Cluster Releases Screen) ---
            elif payload in [DDPMessages.STAT_FREE_HALF, DDPMessages.STAT_FREE_FULL]:
                logger.info(f"Cluster Status FREE ({payload}). Waiting for Re-Init Request (2E)...")
                self.screen_released_by_cluster = True
                self._set_state(DDPState.PAUSED)
                # Wait for 0x2E before another ownership request.

            # --- HANDLE RE-INIT (Resume Sequence) ---
            elif payload == DDPMessages.CMD_REINIT_REQ:
                logger.info("Received Re-Init Request (2E). Sending Confirm (2F).")
                self.screen_released_by_cluster = True
                
                # Acknowledgment of 2F completes confirmation; it does not
                # itself claim the display. The service will request ownership.
                try:
                    self.send_data_packet(DDPMessages.CMD_REINIT_CONF)
                except DDPError:
                    # The ACK wait may already have processed A8 or closed
                    # an exhausted session. Preserve that reconnect state.
                    if self.state != DDPState.DISCONNECTED:
                        self._set_state(DDPState.PAUSED)
                    return
                if self._last_screen_status not in (0x04, 0x08, 0x84, 0x88):
                    self._set_state(DDPState.READY)

            # --- HANDLE GRAPHICS ACKS (BENIGN) ---
            elif payload == DDPMessages.STAT_GRAPHIC_ACK_WHITE or payload == DDPMessages.STAT_GRAPHIC_ACK_RED:
                logger.debug(f"Cluster confirmed graphics update ({payload}). Ignoring.")

            # --- HANDLE ACTIVE GRAPHICS STATUS (BENIGN) ---
            elif len(payload) >= 2 and payload[0] == 0x53 and (payload[1] & 0x80) != 0:
                logger.debug(f"Cluster status: Graphics Claim active ({payload}). Ignoring.")

            else:
                logger.warning(f"Received unexpected data packet: {data}. (ACK sent).")
