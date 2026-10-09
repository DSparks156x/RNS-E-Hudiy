#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Audi DIS (Cluster) DDP Protocol Driver - native193PU review candidate
#
# Application0B records are reason-coded replies, distinct from TP ACK9n/Bn.
# Native193PU-derived masks and command-family negotiation are documented in
# ddp_application.py. Unknown capability fields remain opaque.
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
from ddp_application import ClusterCapabilities, CapabilityObservation, WindowStatus, ApplicationReply, validate_priority
from ddp_transport import PeerTransportParameters

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

    # Compatibility names from the old driver. These are negative application
    #replies (reason3 for57; reason1 for00), never benign success ACKs.
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
        # Content requests are distinct from transport readiness.
        self.presentation_request_generation = 0
        self.dis_mode = DisMode.UNKNOWN
        self.i_am_opener = False
        self.last_ka_sent = 0.0
        self._last_ka_sent_monotonic = 0.0
        self.send_seq_num = 0
        self.screen_released_by_cluster = False

        # For _recv_specific to store stray packets
        self._last_received_ack = None
        self._last_received_data = None
        self._data_inbox = deque()
        self._last_screen_status = None
        self._receive_seq_num = 0
        self._receive_buffer = bytearray()
        self._transport_ack_inbox = deque()
        self._pending_transport_block = False
        self.peer_transport_parameters = None

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
        if new_state == DDPState.SESSION_ACTIVE:
            self.send_seq_num = 0
            self._data_inbox.clear()
            self._last_screen_status = None
            self._last_received_ack = None
            self._reset_receive_transport()
            self._reset_application_session()
            self.peer_transport_parameters = None

        if new_state == DDPState.READY and old_state == DDPState.PAUSED:
            logger.info("Resuming from PAUSE.")
        
        if new_state in [DDPState.DISCONNECTED, DDPState.PAUSED]:
            self.screen_released_by_cluster = True
        
        # Reset context on disconnection
        if new_state == DDPState.DISCONNECTED:
            self._data_inbox.clear()
            self._last_screen_status = None
            self._reset_receive_transport()
            self._reset_application_session()
            self.peer_transport_parameters = None
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
        if expected_payload[0] == 0x09:
            try:
                observed = CapabilityObservation.parse(data[1:],
                    getattr(self, '_application_mode', None),
                    getattr(self, 'cluster_capabilities', None))
            except ValueError as exc:
                logger.warning('Rejected capabilities: %s', exc)
                return False
            if not observed.eligible:
                return False
            # Receive-time observation owns queue/history/generation changes.
            #Matching the response again must not queue a duplicate20.
            self.cluster_capabilities = observed.selected
            if observed.decoded is not None:
                self.capability_record = list(observed.decoded.raw)
            return True
        if expected_payload[0] == 0x30 and len(expected_payload) == 5:
            matches = len(data) == 6 and data[1] == 0x30
            if matches:
                self.geometry_record = list(data[1:])
            return matches
        if expected_payload[0] == 0x21:
            if ((getattr(self, '_initial_application_handshake', False)
                    or getattr(self, '_initial_setup_request_boundary', None) is not None)
                    and not self._application_record_after_boundary(data,
                        getattr(self, '_initial_setup_request_boundary', None))):
                # A distinct but queued old21 cannot confirm a later20.
                return False
            self.application_setup_record = None
            self.application_setup_full = None
            try:
                self.application_setup_record = validate_priority(
                    data[1:], full=len(expected_payload) >= 3 and expected_payload[2] == 0x10)
                self.application_setup_full = len(expected_payload) >= 3 and expected_payload[2] == 0x10
                if getattr(self, '_initial_application_handshake', False):
                    # Correlate21 with the generation captured before its20
                    #send, not a newer09 prefetched during the ACK wait.
                    self._confirmed_capability_generation = getattr(self, '_initial_setup_request_generation', None)
                return True
            except ValueError as exc:
                logger.warning('Rejected application setup: %s', exc)
                return False
        return data[1:] == expected_payload

    def _reset_application_session(self):
        for request in getattr(self, '_deferred_capability_setups', ()):
            if request['result'] == 'pending':
                request['result'] = 'session-reset'
        self._deferred_capability_setups = deque()
        self._capability_generation = 0
        self._confirmed_capability_generation = None
        self._initial_setup_request_generation = None
        self._initial_setup_request_boundary = None
        self.last_capability_record = None
        for request in getattr(self, '_deferred_application_requests', ()):
            request['result'] = 'session-reset'
        self._deferred_application_requests = deque()
        self._application_session_generation = getattr(self, '_application_session_generation', 0) + 1
        self._application_receive_serial = 0
        self._received_application_records = deque(maxlen=128)
        self._last_window_status_token = None
        self._application_request_invalidated = False
        self._application_request_generation = 0
        self._application_submode = None
        self._initial_application_handshake = False
        self._opening_response_scope = False
        self._initial_mode_request_scope = None
        self._geometry_compatibility_scope = None
        self._geometry_compatibility_records = {}
        self._observed_white_compound_fork_record = None
        self.cluster_capabilities = None
        self.capability_record = None
        self.geometry_record = None
        self.application_setup_record = None
        self.application_setup_full = None
        self._application_setup_pending = False
        self._application_recovery_request = None
        self.last_application_exchange = None
        self._application_mode = None
        self._application_recovery_count = 0
        self.last_application_reply = None
        self.last_unknown_application_record = None
        self.application_error_generation = getattr(self, 'application_error_generation', 0)
        self._last_window_status = None

    def _observe_application_payload(self, payload, *, receive_token=None):
        """Record errors/status while a transport wait is in progress."""
        if not payload:
            return
        if payload[0] < 0x20 and payload[0] % 2 == 0:
            self._queue_application_request(payload)
            return
        if self._is_unhandled_high_request(payload):
            self._queue_application_request(payload)
            return
        if payload[0] in (0x53, 0x5B, 0x7B):
            # Actual8055A82E routes7B05 through special release/reclaim;
            # every other7B value falls through80554AB4, just like53/5B.
            # No negotiated-family equality guard exists in this caller.
            try:
                status = WindowStatus.parse(payload)
            except ValueError as exc:
                logger.warning('Malformed window status: %s payload%s', exc, payload)
                self._last_window_status_token = None
                self._set_state(DDPState.PAUSED)
                return
            previous = getattr(self, '_last_window_status', None)
            self._last_window_status = status
            self._last_window_status_token = receive_token
            self._last_screen_status = status.value
            if status.outcome != 'granted':
                self.screen_released_by_cluster = True
                if self.state in (DDPState.READY, DDPState.PAUSED):
                    if status.outcome == 'available':
                        if (self.state == DDPState.READY and previous is not None
                                and previous.outcome == 'granted'):
                            self.state_generation = getattr(self, 'state_generation', 0) + 1
                        self._set_state(DDPState.READY if getattr(self, 'application_setup_record', None) is not None
                                        and not getattr(self, '_application_setup_pending', False)
                                        else DDPState.PAUSED)
                    else:
                        self._set_state(DDPState.PAUSED)
            logger.info('Window status%02X value%02X: %s', status.family, status.value, status.outcome)
        elif payload[0] == 0x0B:
            reply = None
            try:
                reply = ApplicationReply.parse(payload)
            except ValueError as exc:
                logger.warning('Malformed application reply: %s payload%s', exc, payload)
                self.last_unknown_application_record = tuple(payload)
                self.last_application_reply = None
            else:
                self.last_application_reply = reply
                if not hasattr(self, 'application_reply_history'):
                    self.application_reply_history = deque(maxlen=32)
                self.application_reply_history.append(reply)
                logger.warning('Application reply reason%02X (%s), command%02X subcommand%s raw%s',
                               reply.reason, reply.meaning, reply.command, reply.subcommand, reply.raw)
            self.application_error_generation = getattr(self, 'application_error_generation', 0) + 1
            if self.state in (DDPState.INITIALIZING, DDPState.READY, DDPState.PAUSED):
                self.application_setup_record = None
                self._application_setup_pending = True
                self.screen_released_by_cluster = True
                # Malformed new input must not reuse a previous typed reply.
                # Its raw sentinel makes deferred recovery close failclosed.
                self._application_recovery_request = reply if reply is not None else tuple(payload)
                self._set_state(DDPState.PAUSED)

        elif payload[0] == 0x09:
            self._observe_capabilities(payload)

    def _observe_capabilities(self, payload):
        """Keep raw09 separate from the last VALID typed format/context.

        Native8055A4EE retains configuration/ownership words even when a new
        setup is queued. This host preserves those records, but revokes its
        render/claim generation until a fresh21 confirms the queued20.
        """
        try:
            observed = CapabilityObservation.parse(payload,
                getattr(self, '_application_mode', None),
                getattr(self, 'cluster_capabilities', None))
        except ValueError as exc:
            logger.warning('Malformed capability observation: %s', exc)
            return
        if not hasattr(self, 'capability_observation_history'):
            self.capability_observation_history = deque(maxlen=32)
        item = dict(raw=observed.raw, disposition=observed.disposition,
                    eligible=observed.eligible, queued_at=time.monotonic(),
                    session=getattr(self, '_application_session_generation', 0),
                    generation=getattr(self, '_capability_generation', 0),
                    family=observed.selected.command_family if observed.selected else None,
                    result='ignored' if not observed.eligible else 'pending')
        self.last_capability_record = observed.raw
        self.capability_observation_history.append(item)
        if not observed.eligible:
            return
        self.cluster_capabilities = observed.selected
        if observed.decoded is not None:
            self.capability_record = list(observed.decoded.raw)
        self._capability_generation = item['generation'] + 1
        item['generation'] = self._capability_generation
        if getattr(self, '_initial_application_handshake', False):
            # The existing RED/WHITE profile already sends the queued20.
            item['result'] = 'initialization-profile'
            return
        self.screen_released_by_cluster = True
        self._last_window_status = None
        self._last_screen_status = None
        self._application_request_invalidated = True
        self._application_setup_pending = True
        # Invalidate a graphics block even if already paused/initializing.
        self.state_generation = getattr(self, 'state_generation', 0) + 1
        if self.state in (DDPState.READY, DDPState.PAUSED):
            self._set_state(DDPState.PAUSED)
        if not hasattr(self, '_deferred_capability_setups'):
            self._deferred_capability_setups = deque()
        if len(self._deferred_capability_setups) >= 32:
            item['result'] = 'queue-overflow'
            # A raw recovery sentinel closes safely in the polling worker.
            self._application_recovery_request = observed.raw
            return
        item['full'] = getattr(self, 'application_setup_full', None) is True
        self._deferred_capability_setups.append(item)

    def renderer_command_family(self):
        caps = getattr(self, 'cluster_capabilities', None)
        return caps.command_family if caps is not None else None

    def renderer_ready(self, family=0x52):
        # Keep the generic52 renderer default. Native7A is a separate raw
        #consumer; stock80554AB4 advances its presentation only for profile0.
        return (family in (0x52, 0x7A)
                and self.renderer_command_family() == family
                and (family != 0x7A or getattr(self, 'application_setup_full', None) is False)
                and getattr(self, 'application_setup_record', None) is not None
                and not getattr(self, '_application_setup_pending', False)
                and not getattr(self, '_application_request_invalidated', False)
                and getattr(self, '_application_mode', None) != 2)

    def _queue_application_request(self, payload):
        """Observe native even requests without transmitting inside TP waits.

        Replies describe RNSE, never echo the cluster's opaque09 tail. Mode
        changes are visible immediately so stale rendering cannot continue.
        The32-entry FIFO is bounded host policy; native queue safety is not
        inherited. Transport duplicate suppression runs before this function.
        """
        if not hasattr(self, '_deferred_application_requests'):
            self._deferred_application_requests = deque()
        if not hasattr(self, 'incoming_application_history'):
            self.incoming_application_history = deque(maxlen=32)
        item = dict(request=tuple(payload), reply=None, result='queued',
                    session=getattr(self, '_application_session_generation', 0), followup=None,
                    queued_at=time.monotonic())
        self.incoming_application_history.append(item)
        if len(payload) > 128 or len(self._deferred_application_requests) >= 32:
            item['result'] = 'request-bound-exceeded'
            self.close_session()
            raise DDPHandshakeError('Incoming application request exceeds bounded native/FIFO extent')
        opcode = payload[0]
        previous_mode = getattr(self, '_application_mode', None)
        caps = getattr(self, 'cluster_capabilities', None)
        if opcode == 0:
            if len(payload) >= 2:
                self._application_submode = 0
            if len(payload) < 2 or payload[1] not in (1, 2):
                item['reply'] = (0x0B, 3, 0)
            else:
                self._application_mode = payload[1]
                item['reply'] = (1, payload[1], 0)
                self._invalidate_application_request()
                if payload[1] == 1:
                    # Native phase10+knownformat advances to9 (20); other
                    # mode1 transitions phase3 (08). Track equivalent mode2
                    # origin rather than inventing a wall-time phase value.
                    item['followup'] = 'setup' if previous_mode == 2 and caps is not None else 'capability-setup'
        elif opcode == 8:
            if previous_mode != 1:
                item['reply'] = (0x0B, 2, 8)
            elif caps is None:
                item['result'] = 'native-silent-unset-format'
            else:
                item['reply'] = (9, 0x20 if caps.format_code == 0x20 else 0x10,
                                 0, 0x50, 0, 0x10, 0x20, 0x21, 0x22, 0x23, 0)
        elif opcode == 0x14:
            item['reply'] = (0x15, 1, 1, 2, 0, 0)
            self.application_setup_record = None
            self.application_setup_full = None
            self.geometry_record = None
            self._application_recovery_request = None
            self._invalidate_application_request()
        else:
            item['reply'] = (0x0B, 1, opcode)
        item['application_generation'] = getattr(self, '_application_request_generation', 0)
        if item['reply'] is not None:
            self._deferred_application_requests.append(item)

    def _invalidate_application_request(self):
        self._application_request_generation = getattr(self, '_application_request_generation', 0) + 1
        self.screen_released_by_cluster = True
        self._last_window_status = None
        self._last_screen_status = None
        self._application_request_invalidated = True
        self._application_setup_pending = True
        previous_generation = getattr(self, 'state_generation', 0)
        if self.state in (DDPState.READY, DDPState.PAUSED):
            self._set_state(DDPState.PAUSED)
        if getattr(self, 'state_generation', 0) == previous_generation:
            self.state_generation = previous_generation + 1

    def _send_application_control_record(self, payload):
        """Bounded native control message; preserve its TP continuation boundary."""
        if self.state == DDPState.DISCONNECTED or getattr(self, '_pending_transport_block', False):
            raise DDPHandshakeError('No safe transport context for deferred application reply')
        if not 1 <= len(payload) <= 128:
            raise DDPHandshakeError('Application control reply outside native message bound')
        profile = self._transport_settings()
        cap = min(15, profile.max_unacked_frames, max(1, profile.max_message_bytes // 7))
        peer = getattr(self, 'peer_transport_parameters', None)
        if peer is not None:
            cap = min(cap, peer.host_ack_block_cap)
        frames, _ = segment_message(bytes(payload), self.send_seq_num,
                                    block_size=cap, length_prefixed=False)
        error_generation = getattr(self, 'application_error_generation', 0)
        block = []
        for frame in frames:
            block.append(frame)
            if frame[0] >> 4 in (0, 1):
                self._send_acknowledged_block(block)
                block = []
                if getattr(self, 'application_error_generation', 0) != error_generation:
                    raise DDPHandshakeError('Peer rejected deferred application control reply')
                if self.dis_mode == DisMode.WHITE:
                    time.sleep(profile.white_post_message_delay_s)
        return True

    def _drain_application_requests(self):
        """One deferred reply/followup per polling turn; no recursive ACK sends."""
        if (getattr(self, '_servicing_application_request', False)
                or getattr(self, '_pending_transport_block', False)
                or getattr(self, '_application_recovery_request', None) is not None
                or self.state == DDPState.DISCONNECTED):
            return False
        pending = getattr(self, '_deferred_application_requests', None)
        if not pending:
            return False
        item = pending.popleft()
        if item['session'] != getattr(self, '_application_session_generation', 0):
            item['result'] = 'stale-session'
            return True
        self._servicing_application_request = True
        try:
            if time.monotonic() - item['queued_at'] > 10.0:
                raise DDPHandshakeError('Deferred application reply exceeded10s host deadline')
            self._send_application_control_record(item['reply'])
            item['result'] = 'transport-acknowledged'
            if item['followup'] is not None:
                if item['application_generation'] != getattr(self, '_application_request_generation', 0):
                    item['result'] = 'reply-acknowledged-followup-superseded'
                    return True
                self._set_state(DDPState.INITIALIZING)
                if item['followup'] == 'capability-setup':
                    self._exchange_application([8], [9])
                if not self._reconfigure_application():
                    raise DDPHandshakeError('Mode request followup setup failed')
                self._application_request_invalidated = False
                item['result'] = 'reply-and-setup-confirmed'
            return True
        except DDPError as exc:
            item.update(result='session-closed' if self.state == DDPState.DISCONNECTED else 'send-or-followup-error',
                        error=str(exc))
            if self.state != DDPState.DISCONNECTED:
                try:
                    self.close_session()
                except DDPError as close_error:
                    item['close_error'] = str(close_error)
            return False
        finally:
            self._servicing_application_request = False

    def window_status(self, payload):
        return WindowStatus.parse(payload)

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
        self._last_ka_sent_monotonic = 0.0
        self.screen_released_by_cluster = True
        self._last_received_ack = None
        self._last_received_data = None
        self._data_inbox.clear()
        self._last_screen_status = None
        self._reset_receive_transport()
        self._reset_application_session()
        self.peer_transport_parameters = None
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
            
            # A fresh opening request cannot establish sequence continuity of
            #an existing session. Close, then negotiate through the normal path.
            if data[0] == 0xA0 and 2 <= len(data) <= 8 and self.state != DDPState.DISCONNECTED:
                logger.warning("New session open during active session; closing before reopen")
                self.close_session()
                return True

            # Cluster Ping (0xA3 or 0xA3 00, etc.)
            if data[0] == self.KA_KEEP_PING[0]:
                logger.debug(f"Cluster sent Keep-Alive {data} -> replying A1")
                reply = self.KA_RED_ACCEPT if self.dis_mode == DisMode.RED else self.KA_WHITE_ACCEPT
                self.send_can(self.tx_id, reply)
                return True
            
            # Cluster Pong (to our Ping)
            if (self._session_record_matches(data, self.KA_WHITE_ACCEPT if self.dis_mode == DisMode.WHITE
                                             else self.KA_RED_ACCEPT) and self.i_am_opener):
                logger.debug("Cluster replied A1 to our A3")
                return True
            
            # Ignore unhandled 0xA_ packets
            return True # Assume it was session-related

        # Stock80633E78 masks header&0x90: F shares B's ready behavior.
        # Retain raw bit0x40; its independent semantic meaning is unproved.
        if msg_type_prefix in (self.PKT_TYPE_ACK, 0xF0):
            logger.debug(f"<- Received ACK {data[0]:02X}")
            self._last_received_ack = data
            if getattr(self, '_pending_transport_block', False):
                self._transport_ack_inbox.append(list(data))
            return True

        # --- Type 0x0_, 0x1_, 0x2_ (Data) ---
        if msg_type_prefix in (0x00, 0x10, 0x20, 0x30):
            return False  # Sequence validation/reassembly precede application dispatch.

        # D shares 9's not-ready delay and sequence behavior in stock.
        if msg_type_prefix in (0x90, 0xD0):
            logger.debug("Receiver not-ready ACK %02X", data[0])
            self._last_received_ack = data
            if getattr(self, '_pending_transport_block', False):
                self._transport_ack_inbox.append(list(data))
            return True

        logger.warning(f"Unknown unhandled packet type {data[0]:02X}")
        return True # Treat as handled to avoid breaking loops

    def _reset_receive_transport(self):
        """A new fixed-channel session starts both RX sequence and message assembly."""
        self._receive_seq_num = 0
        self._receive_buffer = bytearray()
        self._transport_ack_inbox = deque()
        self._pending_transport_block = False

    @staticmethod
    def _session_record_matches(data, expected):
        if not expected or expected[0] not in (0xA0, 0xA1) or not data or data[0] != expected[0]:
            return False
        try:
            parameters = PeerTransportParameters.parse(data)
        except ValueError:
            return False
        # Preserve the observed short-red / long-white profile split; other
        #fields are peer parameters, not an exact welcome-message fingerprint.
        return parameters.legacy == (len(expected) < 6)

    def _accept_peer_transport(self, data):
        self.peer_transport_parameters = PeerTransportParameters.parse(data)
        peer = self.peer_transport_parameters
        logger.info('TP peer BS%u native-cap%u host-cap%u legacy%s pacing-raw%s counter-ticks%u',
                    peer.block_size_raw, peer.native_block_size, peer.host_ack_block_cap,
                    peer.legacy, peer.pacing_raw, peer.pacing_counter_ticks)
        if peer.block_size_raw == 0:
            logger.info('Peer BS0: native16-frame boundary, further limited by host safety caps')

    def _receive_application_frame(self, data):
        """Return a whole application record, acknowledging the next required nibble.

        Stock193PU function80633E78 appends only the expected sequence. Opcodes0/1
        request an ACK;1/3 finalize. Repeated/out-of-order frames never append.
        The returned synthetic final header preserves the existing data[1:] ABI.
        """
        if not hasattr(self, '_receive_buffer'):
            self._reset_receive_transport()
        opcode, sequence = classify_frame(data)
        if opcode not in (0, 1, 2, 3) or not 2 <= len(data) <= 8:
            self.close_session()
            raise DDPHandshakeError('Malformed fixed-channel application frame')
        if sequence != self._receive_seq_num:
            if opcode in (0, 1):
                self.send_can(self.tx_id, [0xB0 | self._receive_seq_num])
            return None
        self._receive_seq_num = (sequence + 1) & 15
        if len(self._receive_buffer) + len(data) - 1 > 0xFFFF:
            self.close_session()
            raise DDPHandshakeError('Application receive message exceeds65535 bytes')
        self._receive_buffer.extend(data[1:])
        if opcode in (0, 1):
            self.send_can(self.tx_id, [0xB0 | self._receive_seq_num])
        if opcode not in (1, 3):
            return None
        record = [data[0]] + list(self._receive_buffer)
        self._receive_buffer.clear()
        return record

    def _application_receive_boundary(self):
        return (getattr(self, '_application_session_generation', 0),
                getattr(self, '_application_receive_serial', 0))

    def _application_record_token(self, data):
        # Exact object identity, not equality of bytes or a TP sequence nibble.
        for record, token in getattr(self, '_received_application_records', ()):
            if record is data:
                return token
        return None

    def _application_record_after_boundary(self, data, boundary):
        token = self._application_record_token(data)
        return bool(boundary is not None and token is not None and token[0] == boundary[0]
                    == getattr(self, '_application_session_generation', 0)
                    and token[1] > boundary[1])

    def _retain_data(self, data):
        """Sequence-check/ACK once and retain only complete application records."""
        data = self._receive_application_frame(data)
        if data is None:
            return
        if (self._is_ignored_application_record(data[1:])
                and not self._accept_opening_response(data[1:])):
            # Stock normal receive retires these records without app effects.
            # Keep them out of the inbox during ACK prefetch as well as waits.
            logger.debug('Ignored normal application opcode%02X length%u', data[1], len(data)-1)
            return
        self._application_receive_serial = getattr(self, '_application_receive_serial', 0) + 1
        token = self._application_receive_boundary()
        if not hasattr(self, '_received_application_records'):
            self._received_application_records = deque(maxlen=128)
        self._received_application_records.append((data, token))
        mode_compatibility = self._reserve_initial_mode_record(data)
        # Only explicit observed opening-profile expectations reserve30.
        # Store this exact complete record, never authorize a matching future
        #payload or all traffic in an initialization mode/phase.
        scope = getattr(self, '_geometry_compatibility_scope', None)
        # The observed white opening layout has a seven-byte52-family
        #capability prefix followed by one of the declared five-byte geometries.
        #Capability metadata varies by cluster; an exact bench fingerprint
        #rejects other units before setup. Keep the full09 observation and bind
        #this opening role to this received object, never to arbitrary09 tails.
        if (scope == 'white common configuration/fork'
                and getattr(self, '_initial_application_handshake', False)
                and self.state == DDPState.INITIALIZING
                and self.dis_mode == DisMode.WHITE
                and getattr(self, '_application_mode', None) == 1
                and len(data) == 13 and data[1:3] == [0x09, 0x20]
                and data[8:] in ([0x30,0x39,0x00,0x30,0x00],
                                [0x30,0x39,0x00,0x32,0x00])):
            self._observed_white_compound_fork_record = data
        if scope == 'white common configuration/fork' and data[1:2] == [9]:
            self._geometry_compatibility_scope = None
            scope = None
        if (scope is not None and data[1:2] == [0x30]
                and getattr(self, '_initial_application_handshake', False)
                and self.state == DDPState.INITIALIZING):
            records = getattr(self, '_geometry_compatibility_records', None)
            if records is None:
                records = self._geometry_compatibility_records = {}
            if len(records) >= 4:
                self.close_session()
                raise DDPHandshakeError('Opening-profile geometry reservation bound exceeded')
            records[id(data)] = data
            self._geometry_compatibility_scope = None
        elif not mode_compatibility:
            self._observe_application_payload(data[1:], receive_token=token)
        if data[1:] == DDPMessages.CMD_REINIT_REQ and self.state == DDPState.READY:
            self._set_state(DDPState.PAUSED)
        if len(self._data_inbox) >= 128:
            self._set_state(DDPState.DISCONNECTED)
            raise DDPHandshakeError("Application receive queue overflow")
        self._data_inbox.append(data)

    def _recv_specific(self, expected_data, timeout_ms):
        deadline = time.monotonic() + timeout_ms / 1000.0
        waiting_open = bool(expected_data and expected_data[0] in (0xA0, 0xA1))
        while time.monotonic() < deadline:
            if self._flashing_inhibited():
                return None
            waiting_ack = len(expected_data) == 1 and expected_data[0] >> 4 == 0xB
            if waiting_ack and getattr(self, '_transport_ack_inbox', None):
                data = self._transport_ack_inbox.popleft()
            else:
                data = self._recv(min(0.05, max(0, deadline-time.monotonic())))
            if not data:
                continue
            if data == expected_data or self._session_record_matches(data, expected_data):
                return data
            if waiting_open and self.state == DDPState.DISCONNECTED:
                # Before a known A0/A1 exchange there is no receive sequence.
                # Ignore stale data/keepalives without ACKing or executing them.
                if data == self.KA_CLOSE:
                    return None
                continue
            if (len(expected_data) == 1 and expected_data[0] >> 4 == 0xB
                    and len(data) == 1 and data[0] >> 4 in (0x9, 0xB, 0xD, 0xF)):
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
        initial_generation = getattr(self, 'state_generation', 0)
        profile = self._transport_settings()
        not_ready_count = ack_retry_count = block_retry_count = 0
        if not hasattr(self, '_receive_buffer'):
            self._reset_receive_transport()
        if self._pending_transport_block:
            self.close_session()
            raise DDPAckTimeoutError('Nested acknowledged transport block')
        self._pending_transport_block = True
        self._transport_ack_inbox.clear()

        def fail(reason):
            # Unknown receive progress cannot safely start a different message.
            self.close_session()
            raise DDPAckTimeoutError(reason)

        def interrupted():
            return (self.state != initial_state or
                    getattr(self, 'state_generation', 0) != initial_generation)

        try:
            while True:
                for frame in resend:
                    if interrupted():
                        fail('Session or display state changed during a block')
                    self.send_can(self.tx_id, list(frame))
                    self.send_seq_num = ((frame[0] & self.PKT_SEQ_MASK) + 1) & 0xF
                reply = self._recv_specific(expected, 1000)
                if interrupted():
                    # The peer may retain a graphics prefix or may have accepted
                    # an unacknowledged final frame. A later2F must not complete
                    # that abandoned message. Reopen instead of guessing progress.
                    fail('Session or display state changed during ACK wait')
                if not reply:
                    ack_retry_count += 1
                    if ack_retry_count > profile.max_ack_retries:
                        fail(f'No ACK {expected[0]:02X} after bounded retries')
                    resend = (block[-1],)
                    continue
                opcode, sequence = classify_frame(reply)
                if opcode not in (0x9, 0xB, 0xD, 0xF) or len(reply) != 1:
                    fail('Malformed transport acknowledgment')
                if opcode in (0x9, 0xD):
                    not_ready_count += 1
                    if not_ready_count > profile.max_not_ready_retries:
                        fail('Receiver remained not ready after bounded retries')
                    self._wait_receiver_delay(profile.receiver_not_ready_wait_s)
                    if interrupted():
                        fail('Session or display state changed during receiver wait')
                    if self._transport_ack_inbox:
                        # A later ACK/status may supersede this9n while waiting.
                        # Consume it before replaying an earlier requested prefix.
                        resend = ()
                        continue
                if sequence == expected[0] & self.PKT_SEQ_MASK:
                    return
                offset = next((i for i, frame in enumerate(block)
                               if frame[0] & self.PKT_SEQ_MASK == sequence), None)
                if offset is None:
                    fail('Receiver requested a sequence outside the pending block')
                block_retry_count += 1
                if block_retry_count > profile.max_not_ready_retries:
                    fail('Receiver repeatedly requested block retransmission')
                resend = block[offset:]
        finally:
            self._pending_transport_block = False
            self._transport_ack_inbox.clear()

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
                if not self._data_inbox:
                    continue
                data = self._data_inbox.popleft()
            records = getattr(self, '_geometry_compatibility_records', {})
            geometry_compatibility = records.pop(id(data), None) is data
            if (self._is_ignored_application_record(data[1:])
                    and not self._accept_opening_response(data[1:])):
                # A15 prefetched during the first opening boundary may still
                #be queued after that exact boundary ends. No renewed deadline.
                continue
            if (len(data) > 1 and (data[1] < 0x20 and data[1] % 2 == 0
                                  or self._is_unhandled_high_request(data[1:]) and not geometry_compatibility)
                    and not (getattr(self, '_initial_application_handshake', False)
                             and data[1:] == [0, 1])):
                # Queries may arrive during initialization response waits.
                # Mode/reset changes invalidate that old exchange; reopening
                #is safer than consuming its response as a new configuration.
                if data[1] == 0x14 or (data[1] == 0 and len(data) >= 3 and data[2] in (1, 2)):
                    raise DDPHandshakeError('Peer restarted application during a response exchange')
                self._drain_application_requests()
                if self.state == DDPState.DISCONNECTED:
                    return None
                continue
            # Screen statuses are asynchronous during initialization. They do
            # not replace its capability/geometry response or reset its deadline.
            if self.state == DDPState.INITIALIZING and len(data) >= 3:
                payload = data[1:]
                if payload[0] in (0x53, 0x5B, 0x7B):
                    try:
                        WindowStatus.parse(payload)
                    except ValueError:
                        pass
                    else:
                        continue
            return data
        return None

    @staticmethod
    def _is_ignored_application_record(payload):
        """Normal8055A42C ignores low/high odd unknowns and allE0..FF."""
        return bool(payload and (payload[0] >= 0xE0
                    or payload[0] % 2 == 1 and payload[0] not in
                    (0x09,0x0B,0x21,0x53,0x5B,0x7B)))

    def _accept_opening_response(self, payload):
        """Observed15 welcome only at the first15-send/response boundary."""
        return bool(payload and payload[0] == 0x15
                    and getattr(self, '_opening_response_scope', False)
                    and getattr(self, '_initial_application_handshake', False)
                    and self.state == DDPState.INITIALIZING)

    def _reserve_initial_mode_record(self, data):
        """One exact00 01 at each observed opening/fork response role."""
        scope = getattr(self, '_initial_mode_request_scope', None)
        if not (scope is not None and getattr(self, '_initial_application_handshake', False)
                and self.state == DDPState.INITIALIZING):
            return False
        if data[1:] == [0, 1]:
            self._initial_mode_request_scope = None
            return True
        if scope == 'fork' and data[1:2] in ([9], [0x30]):
            self._initial_mode_request_scope = None
        return False

    @staticmethod
    def _is_unhandled_high_request(payload):
        """8055A42C→8055A82E: even20..DF except known2E."""
        return bool(payload and 0x20 <= payload[0] < 0xE0
                    and payload[0] % 2 == 0 and payload[0] != 0x2E)

    def _expect_profile_geometry(self, label):
        """One30 at an explicit opening-profile boundary, including ACK prefetch."""
        if not (getattr(self, '_initial_application_handshake', False)
                and self.state == DDPState.INITIALIZING):
            raise DDPHandshakeError('Geometry compatibility requires an explicit opening profile')
        self._geometry_compatibility_scope = label

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
        application_error_generation = getattr(self, 'application_error_generation', 0)
        frames_per_block = min(15, profile.max_unacked_frames,
                               max(1, profile.max_message_bytes // 7))
        peer = getattr(self, 'peer_transport_parameters', None)
        if peer is not None:
            frames_per_block = min(frames_per_block, peer.host_ack_block_cap)
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
                    if getattr(self, 'application_error_generation', 0) != application_error_generation:
                        logger.error('Application rejected a command during graphics transmission')
                        return False
                    # Preserve the cluster's pacing at every acknowledged
                    # block, including continuation blocks within a message.
                    if pacing and self.dis_mode == DisMode.WHITE:
                        time.sleep(profile.white_post_message_delay_s)
        except (DDPAckTimeoutError, DDPHandshakeError) as e:
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
        detect_deadline = time.monotonic() + 1.0
        data = self._recv_specific(self.KA_WHITE_OPEN, 1000)
        if data and self._session_record_matches(data, self.KA_WHITE_OPEN):
            logger.info("Cluster opened -> sending A1")
            if not self._retire_passive_white_opening_retries(data, detect_deadline):
                return False
            self.send_can(self.tx_id, self.KA_WHITE_ACCEPT)
            self.i_am_opener = False
            self._set_state(DDPState.SESSION_ACTIVE)
            self.dis_mode = DisMode.WHITE
            self._accept_peer_transport(data)
            return True
        return False

    def _white_dis_active_open(self) -> bool:
        """(Private) Actively initiates the White DIS session by sending A0."""
        logger.info("ACTIVE WHITE: Sending A0...")
        self.send_can(self.tx_id, self.KA_WHITE_OPEN)
        data = self._recv_specific(self.KA_WHITE_ACCEPT, 500)
        if data:
            logger.info("A1 received")
            self.i_am_opener = True
            self._set_state(DDPState.SESSION_ACTIVE)
            self.dis_mode = DisMode.WHITE
            self._accept_peer_transport(data)
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
            peer_open = self._recv_specific(self.KA_RED_ACCEPT, 500)
            if not peer_open:
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
            self._accept_peer_transport(peer_open)
            return True

        except Exception as e:
            logger.error(f"RED DIS: Handshake failed with error: {e}")
            return False

    def _retire_passive_white_opening_retries(self, opening, detect_deadline):
        """Establish a bounded receive boundary BEFORE accepting passive A0.

        Byte-identical retries already available before our A1 belong to an
        unaccepted opening. Other A0 requests and A8 make acceptance ambiguous.
        Stale pre-session data/ACK/keepalive records are ignored without ACK or
        application observation, as in the disconnected opening wait. These
        32-frame/100ms limits are host bounds, not inferred peer timers.
        """
        if self.state != DDPState.DISCONNECTED:
            return False
        deadline = min(detect_deadline, time.monotonic() + 0.100)
        received = 0
        while True:
            if self._flashing_inhibited() or time.monotonic() >= deadline:
                logger.warning('Passive white opening drain lost its receive deadline')
                return False
            data = self._recv(0)
            if (self.state != DDPState.DISCONNECTED or self._flashing_inhibited()
                    or time.monotonic() >= deadline):
                logger.warning('Passive white opening drain exceeded its receive deadline')
                return False
            if not data:
                return True
            received += 1
            if received > 32:
                logger.warning('Passive white opening drain exceeded32 queued frames')
                return False
            if data == opening:
                logger.debug('Retiring queued passive white opening retry before A1')
                continue
            if data == self.KA_CLOSE or data[0] == 0xA0:
                logger.warning('Conflicting session control before passive white acceptance')
                return False
            logger.debug('Ignoring stale pre-acceptance frame without ACK or application execution')

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
        start = time.monotonic()
        stale_session_closed = False
        while time.monotonic() - start < 1.5:
            if self._flashing_inhibited():
                return False
            data = self._recv(0.1) # Poll every 100ms
            if not data:
                continue
            
            # --- Red DIS Detection ---
            if data == self.KA_RED_PRESENT:
                logger.info("Found Red DIS broadcast (A0 07 00).")
                return self._red_dis_open()
                
            # --- White DIS (Passive) Detection ---
            if self._session_record_matches(data, self.KA_WHITE_OPEN):
                logger.info("Found White DIS passive open (A0 0F...).")
                if not self._retire_passive_white_opening_retries(data, start + 1.5):
                    return False
                self.send_can(self.tx_id, self.KA_WHITE_ACCEPT)
                self.i_am_opener = False
                self._set_state(DDPState.SESSION_ACTIVE)
                self.dis_mode = DisMode.WHITE
                self._accept_peer_transport(data)
                return True
            
            # --- Existing Session (A3 Ping) Detection ---
            if data[0] == self.KA_KEEP_PING[0]:
                if not stale_session_closed:
                    # A restarted process cannot infer either sequence nibble
                    # from a keepalive. Close once, await fresh A0, then use the
                    # normal active-white fallback if the peer remains passive.
                    logger.warning('Stale session keepalive; closing before clean reopen')
                    self.send_can(self.tx_id, self.KA_CLOSE)
                    self._reset_receive_transport()
                    self._reset_application_session()
                    stale_session_closed = True
                continue
        
        # --- No broadcast detected ---
        # Assume White DIS, try Active Open
        logger.info("No Red DIS broadcast. Assuming White DIS, attempting Active Open.")
        return self._white_dis_active_open()

    def close_session(self):
        """Actively closes the DDP session by sending A8 (Hard Close)."""
        if self.state != DDPState.DISCONNECTED:
            logger.info("Actively closing session (sending A8)...")
            try:
                self.send_can(self.tx_id, self.KA_CLOSE)
            finally:
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
        # Arm before the causative send: its ACK wait may prefetch the15
        #welcome. This one first-response role is an observed peer exception,
        #not native normal receive or a general INITIALIZING exemption.
        self._opening_response_scope = True
        self._initial_mode_request_scope = 'first-response'
        try:
            self.send_data_packet([0x15, 0x01, 0x01, 0x02, 0x00, 0x00])
            logger.info("Init Step 1 (Capabilities Query) sent!")
            data = self._recv_and_ack_data(1000)
        finally:
            self._opening_response_scope = False
            self._initial_mode_request_scope = None
        if not data:
             raise DDPHandshakeError("Init Step 1 timeout: No response from cluster.")
        
        # Detection: Standard mode responds with 0x09 (Nav), High-Res uses 0x15 (Telem)
        if len(data) < 2:
            raise DDPHandshakeError("Truncated initialization capabilities response")
        if data[1] == 0x15:
            logger.info("Detected HIGH-RES (Telem/Phone) Mode via 0x15 response.")
        elif not self.payload_is(data, self.PL["PL_LOG_3"]):
            raise DDPHandshakeError(f"Unexpected application start response: {data}")
        
        logger.info("Init 2/x passed!")

        if self.dis_mode == DisMode.WHITE:
            self._expect_profile_geometry('white common configuration/fork')
        self._initial_mode_request_scope = 'fork'
        self.send_data_packet([0x01, 0x01, 0x00]) # Step 3
        self._application_mode = 1
        logger.info("Init 3/x passed!")

        if self.dis_mode == DisMode.RED:
            self._expect_profile_geometry('red common capability query/geometry')
        self.send_data_packet([0x08]) # Step 4
        logger.info("Init 4/x passed!")

    def _run_init_steps(self, steps):
        """Run an observed handshake profile, validating each receive boundary.

        Transport ACKs/status interruptions are handled by the shared receiver;
        the profile describes only application records and their wire order.
        """
        for step_index, (label, outbound, expected_names) in enumerate(steps):
            exchange = dict(command=tuple(outbound) if outbound is not None else None,
                            expected=tuple(tuple(self.PL.get(name) or ()) for name in expected_names),
                            profile_step=label, attempt=1,
                            timeout_ms=0 if outbound is not None else 1000,
                            result='pending', response=None)
            self.last_application_exchange = exchange
            if not hasattr(self, 'application_exchange_history'):
                self.application_exchange_history = deque(maxlen=32)
            self.application_exchange_history.append(exchange)
            if self.state == DDPState.DISCONNECTED:
                exchange['result'] = 'session-closed'
                raise DDPHandshakeError(f"Session closed before {label}")
            if outbound is not None:
                if outbound[0] == 0x20:
                    self._initial_setup_request_boundary = self._application_receive_boundary()
                if (getattr(self, '_initial_application_handshake', False)
                        and outbound[0] == 0x20):
                    self._initial_setup_request_generation = getattr(self, '_capability_generation', 0)
                if step_index + 1 < len(steps):
                    next_label, next_outbound, next_names = steps[step_index + 1]
                    if next_outbound is None and any(
                            (self.PL.get(name) or [])[:1] == [0x30] for name in next_names):
                        self._expect_profile_geometry(next_label)
                try:
                    self.send_data_packet(list(outbound))
                except DDPError as exc:
                    exchange.update(result='send-error', error=str(exc))
                    raise
                exchange['result'] = 'sent'
            else:
                try:
                    data = self._recv_and_ack_data(1000)
                except DDPError as exc:
                    exchange.update(result='receive-error', error=str(exc))
                    raise
                if self.state == DDPState.DISCONNECTED:
                    exchange['result'] = 'session-closed'
                    raise DDPHandshakeError(f"Session closed during {label}")
                exchange['response'] = tuple(data[1:]) if data is not None else None
                if not any(self.payload_is(data, self.PL.get(name))
                           for name in expected_names):
                    exchange['result'] = 'timeout' if data is None else 'unexpected-response'
                    raise DDPHandshakeError(
                        f"{label}: expected {expected_names}, received {data}")
                exchange['result'] = 'accepted'
            logger.info("Initialization %s complete", label)

    def _exchange_application(self, command, expected, *, send_first=True):
        """Bounded host request/response tracking; no native tick/ms inference.

        The response command identifies the exchange. Status records are
        asynchronous; an application0B is never a successful response.
        Three attempts/1000ms each are host policy. No transport nibble reset.
        """
        for attempt in range(1, 4):
            exchange = dict(command=tuple(command), expected=tuple(expected),
                            attempt=attempt, timeout_ms=1000, result='pending', response=None)
            self.last_application_exchange = exchange
            if not hasattr(self, 'application_exchange_history'):
                self.application_exchange_history = deque(maxlen=32)
            self.application_exchange_history.append(exchange)
            if send_first or attempt > 1:
                if command[0] == 0x20:
                    self._initial_setup_request_boundary = self._application_receive_boundary()
                if (getattr(self, '_initial_application_handshake', False)
                        and command[0] == 0x20):
                    self._initial_setup_request_generation = getattr(self, '_capability_generation', 0)
                try:
                    self.send_data_packet(list(command))
                except DDPError as exc:
                    exchange.update(result='send-error', error=str(exc))
                    raise
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if self.state == DDPState.DISCONNECTED:
                    exchange['result'] = 'session-closed'
                    raise DDPHandshakeError('Session closed during application exchange')
                try:
                    data = self._recv_and_ack_data(max(1, int((deadline-time.monotonic())*1000)))
                except DDPError as exc:
                    exchange.update(result='receive-error', error=str(exc))
                    raise
                if self.state == DDPState.DISCONNECTED:
                    exchange['result'] = 'session-closed'
                    raise DDPHandshakeError('Session closed during application response wait')
                if data is None:
                    break
                payload = data[1:]
                exchange['response'] = tuple(payload)
                if payload and payload[0] == 0x30:
                    if len(payload) != 5:
                        exchange['result'] = 'malformed-geometry'
                        raise DDPHandshakeError('Malformed geometry record from receive adapter')
                    exchange['result'] = 'unexpected-geometry'
                    raise DDPHandshakeError('Geometry is only accepted at explicit opening-profile boundaries')
                if payload and payload[0] == 0x0B:
                    exchange['result'] = 'application-error'
                    raise DDPHandshakeError(f'Application rejected command{command}: {payload}')
                if payload and payload[0] == 0x09 and expected[0] != 0x09:
                    # Its receive observer either queued another20 or ignored
                    #a short/wrong-mode09. It never replaces the required21.
                    continue
                # Native09 mode1/len>=6 schedules20 even if the format byte
                #is unknown; the last valid typed family is retained separately.
                capability_response = (expected and expected[0] == 0x09
                    and payload and payload[0] == 0x09
                    and CapabilityObservation.parse(payload,
                        getattr(self, '_application_mode', None),
                        getattr(self, 'cluster_capabilities', None)).eligible)
                matches = capability_response if expected[0] == 0x09 else self.payload_is(data, list(expected))
                if matches:
                    if capability_response:
                        # Keep the record recognizer useful to callers whose
                        #offline/adapter receiver did not invoke the observer.
                        #Eligible unknown formats retain old typed data without
                        #inventing a family.
                        self.payload_is(data, list(expected))
                    exchange['result'] = 'accepted'
                    return True
                exchange['result'] = 'unexpected-response'
                raise DDPHandshakeError(f'Expected application{expected}, received{payload}')
            exchange['result'] = 'timeout'
        raise DDPHandshakeError(f'Application command{command} exhausted three response deadlines')

    def _init_path_b_white(self, capability_query_pending=False):
        """Observed short white-cluster initialization profile."""
        # Common start already sends08 before consuming the geometry fork.
        # Its09 remains outstanding; sending08 again can leave a second09
        # queued where the later20 exchange expects21.
        self._exchange_application([8], [9], send_first=not capability_query_pending)
        self._exchange_application([0x20,0x3B,0xA0,0], [0x21,0x3B,0xA0,0])

    def _init_path_c_white(self):
        """Observed long white-cluster profile, including geometry variants."""
        self._run_init_steps([
            ('white configuration', (0x01, 0x01, 0), ()),
            ('white geometry', None, ('PL_LOG_14', 'PL_LOG_14_ALT')),
            ('white capability query', (0x08,), ()),
            ('white capabilities', None, ('PL_LOG_18', 'PL_LOG_18_ALT')),
            ('white application setup', (0x20, 0x3B, 0xA0, 0), ()),
            ('white geometry confirmation', None, ('PL_LOG_21', 'PL_LOG_21_ALT')),
            ('white application confirmation', None, ('PL_LOG_23',)),
            ('white application repeat', (0x20, 0x3B, 0xA0, 0), ()),
            ('white application repeat confirmation', None, ('PL_LOG_27',)),
            ('white initial release', (0x33,), ()),
            ('white final release', (0x33,), ()),
        ])

    def _init_path_red(self):
        """Observed red-cluster short profile."""
        self._run_init_steps([
            ('red geometry', None, ('PL_LOG_14',)),
            ('red application setup', (0x20, 0x3B, 0xA0, 0), ()),
            ('red application confirmation', None, ('PL_LOG_23',)),
            ('red initial release', (0x33,), ()),
        ])

    def _require_initialization_confirmation(self, error_generation):
        """Host publication guard, including records prefetched at final ACKs."""
        if (self.state != DDPState.INITIALIZING
                or getattr(self, 'application_error_generation', 0) != error_generation
                or getattr(self, 'cluster_capabilities', None) is None
                or getattr(self, 'application_setup_record', None) is None
                or getattr(self, '_application_setup_pending', False)
                or getattr(self, '_confirmed_capability_generation', None)
                   != getattr(self, '_capability_generation', 0)):
            raise DDPHandshakeError('Initialization lacks current uninterrupted09/20/21 confirmation')

    def perform_initialization(self) -> bool:
        """
        Performs the complex DDP initialization handshake (Step 2).
        This must be called after a session is active (Step 1).
        """
        logger.info(f"Starting DDP Step 2 Initialization for {self.dis_mode.name} DIS...")
        self._set_state(DDPState.INITIALIZING)
        self.send_seq_num = 0
        self._last_screen_status = None
        self._initial_setup_request_generation = None
        self._initial_setup_request_boundary = None
        self._confirmed_capability_generation = None
        initial_error_generation = getattr(self, 'application_error_generation', 0)

        if self.dis_mode == DisMode.UNKNOWN:
             logger.error("DIS mode is unknown. Cannot perform initialization.")
             self._set_state(DDPState.DISCONNECTED)
             return False

        # Get correct payloads for our DIS type
        self.PL = self._get_init_payloads()
        self._initial_application_handshake = True

        try:
            # --- Common Start ---
            self._init_common_start()

            # --- Handshake Fork ---
            # Wait for the packet that determines which path to take
            data = self._recv_and_ack_data(1000)
            self._initial_mode_request_scope = None
            if data is None: raise DDPHandshakeError("Timed out waiting for handshake fork packet.")
            
            # Handle out-of-order PL_LOG_5 (seen in some logs)
            if self.payload_is(data, self.PL["PL_LOG_5"]):
                logger.info("Handshake Fork: Got out-of-order packet (PL 00 01). Accepting.")
                data = self._recv_and_ack_data(1000)
                if data is None: raise DDPHandshakeError("Timed out after out-of-order packet.")

            logger.info('Initialization fork payload: %s',
                        ' '.join(f'{byte:02X}' for byte in data[1:]))

            # Exact complete record reserved at its common-fork receive
            #boundary. Its09 is already observed, so use the existing short
            #white20/21 exchange without another01/08 or geometry wait.
            compound = getattr(self, '_observed_white_compound_fork_record', None)
            self._observed_white_compound_fork_record = None
            if compound is data:
                logger.info('White opening: combined capability/geometry reply; using direct setup')
                self.geometry_record = list(data[8:])
                self._exchange_application([0x20,0x3B,0xA0,0], [0x21,0x3B,0xA0,0])

            # --- Path B (White Short) ---
            elif self.payload_is(data, self.PL["PL_LOG_14"]) and self.dis_mode == DisMode.WHITE:
                self._geometry_compatibility_scope = None
                self._init_path_b_white(capability_query_pending=True)
            
            # --- Path C (White Long) or Path Red ---
            elif self.payload_is(data, self.PL["PL_LOG_11"]) or self.payload_is(data, self.PL.get("PL_LOG_11_ALT")):
                if self.payload_is(data, self.PL.get("PL_LOG_11_ALT")):
                    logger.info("Handshake Fork: Got PL_LOG_11 (ALT)")
                else:
                    logger.info("Handshake Fork: Got PL_LOG_11 (Regular)")
                if self.dis_mode == DisMode.RED:
                    self._init_path_red()
                else:
                    self._geometry_compatibility_scope = None
                    self._init_path_c_white()
            
            else:
                raise DDPHandshakeError(f"Handshake fork failed. Got unhandled packet {data}")

            self._require_initialization_confirmation(initial_error_generation)

            # --- Final Keep-Alive Exchange ---
            logger.info("Sending final A3 Keep-Alive to complete handshake...")
            self.send_can(self.tx_id, self.KA_KEEP_PING)
            
            reply = self.KA_RED_ACCEPT if self.dis_mode == DisMode.RED else self.KA_WHITE_ACCEPT
            if not self._recv_specific(reply, 1000):
                raise DDPHandshakeError(f"Did not receive final {reply} ACK")
            # Final control waits can prefetch application records. Never
            #publishREADY over a late error, interrupted state or newer09.
            self._require_initialization_confirmation(initial_error_generation)
            
            logger.info(f"DDP Initialization COMPLETE")
            status = getattr(self, '_last_window_status', None)
            self._set_state(DDPState.PAUSED if status is not None
                            and status.outcome in ('fault', 'unavailable')
                            else DDPState.READY)
            self.last_ka_sent = time.time()
            self._last_ka_sent_monotonic = time.monotonic()
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
            self._initial_application_handshake = False
            self._opening_response_scope = False
            self._initial_mode_request_scope = None
            self._initial_setup_request_generation = None
            self._initial_setup_request_boundary = None
            self._geometry_compatibility_scope = None
            self._geometry_compatibility_records = {}
            self._observed_white_compound_fork_record = None
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
        
        # Keep the public wall timestamp for diagnostics; elapsed scheduling
        # uses a separate monotonic clock so time synchronization cannot
        # suppress or prematurely trigger keepalive traffic.
        if self.i_am_opener and time.monotonic() - getattr(self, '_last_ka_sent_monotonic', 0.0) > 2.0:
            logger.debug("Sending A3 Keep-Alive")
            self.send_can(self.tx_id, self.KA_KEEP_PING)
            self.last_ka_sent = time.time()
            self._last_ka_sent_monotonic = time.monotonic()

    def poll_bus_events(self):
        """
        Main polling function. This must be called continuously.
        Handles background traffic, status interrupts (Busy/Free), and Re-Init requests.
        """
        if self._flashing_inhibited():
            return
        if self.state == DDPState.DISCONNECTED:
            return

        if (getattr(self, '_application_recovery_request', None) is not None
                and not getattr(self, '_pending_transport_block', False)
                and not self._data_inbox):
            self._recover_application()
            return
        if self._drain_application_requests():
            return
        if self.state == DDPState.DISCONNECTED:
            return

        # Transport sequencing/reassembly must run for polling as well as waits.
        if self._data_inbox:
            data = self._data_inbox.popleft()
        else:
            data = self._recv(0)
            if not data:
                return
            if self._handle_incoming_packet(data):
                return
            self._retain_data(data)
            if not self._data_inbox:
                return
            data = self._data_inbox.popleft()
        already_acked = True
        is_background_packet = False

        self._handle_application_payload(data[1:])

    def _handle_application_payload(self, payload):
        """Dispatch complete, already transport-acknowledged records."""
        if payload and (payload[0] < 0x20 and payload[0] % 2 == 0
                        or self._is_unhandled_high_request(payload)):
            # Already queued exactly once by the receive observer.
            self._drain_application_requests()
            return
        if payload and payload[0] in (0x53, 0x5B, 0x7B):
            # Observation already ran at receive time, including ACK waits.
            #7B05 is a stock special: reset presentation ownership and allow
            #an existing application request to reclaim; never invent a new
            #user selection/presentation generation.
            if payload[:2] == [0x7B, 0x05]:
                self.screen_released_by_cluster = True
                if (self.state in (DDPState.READY, DDPState.PAUSED)
                        and getattr(self, 'application_setup_record', None) is not None
                        and not getattr(self, '_application_setup_pending', False)):
                    self._set_state(DDPState.READY)
            return
        if payload and payload[0] == 0x0B:
            # Not benign graphics-success ACKs: native reason1/2/3 denote
            #unsupported command, incompatible context, invalid parameters.
            # Observer already invalidated setup and queued deferred recovery.
            # Consume this record before polling starts any new exchange.
            return
        if payload == DDPMessages.CMD_REINIT_REQ:
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
            # Publish only an application request acknowledged by the
            # transport. Initial READY and unsolicited status changes
            # must never masquerade as cluster app selection.
            self.presentation_request_generation = getattr(
                self, "presentation_request_generation", 0) + 1
            status = getattr(self, '_last_window_status', None)
            if (getattr(self, 'application_setup_record', None) is not None
                    and not getattr(self, '_application_setup_pending', False)
                    and (status is None or status.outcome not in ('fault', 'unavailable'))):
                self._set_state(DDPState.READY)
            elif self.state != DDPState.DISCONNECTED:
                self._set_state(DDPState.PAUSED)
            return
        if payload and payload[0] == 0x09:
            # Eligible09 queued setup at receive time. Short/wrong-mode09
            #adds no request and preserves the current configuration.
            if getattr(self, '_application_setup_pending', False):
                self._reconfigure_application()
            return
        self.last_unknown_application_record = tuple(payload)
        logger.warning('Unhandled application record%s; transport ACK does not mean application acceptance', payload)

    def _reconfigure_application(self):
        """Native eligible09 schedules20; require21 for EACH queued request.

        Queue32, age10s and at most32 requests per drain are bounded host
        policies. Unknown-first still completes control setup with no renderer.
        Transport nibbles are preserved; ownership must be claimed anew.
        """
        if self.state == DDPState.DISCONNECTED:
            return False
        if getattr(self, '_pending_transport_block', False):
            return False
        if getattr(self, '_servicing_capability_setups', False):
            return False
        pending = getattr(self, '_deferred_capability_setups', None)
        if pending is None:
            pending = self._deferred_capability_setups = deque()
        if not pending:
            # Mode01 phase9 can request setup directly without another09.
            pending.append(dict(generation=getattr(self, '_capability_generation', 0),
                full=getattr(self, 'application_setup_full', None) is True,
                queued_at=time.monotonic(), result='pending', raw=None))
        self._set_state(DDPState.INITIALIZING)
        self._servicing_capability_setups = True
        item = None
        try:
            completed = 0
            while pending:
                item = pending[0]
                if completed >= 32 or time.monotonic() - item['queued_at'] > 10.0:
                    raise DDPHandshakeError('Capability setup exceeded bounded host drain/deadline')
                priority = 0x10 if item['full'] else 0xA0
                self._exchange_application([0x20,0x3B,priority,0], [0x21,0x3B,priority,0])
                if self.state == DDPState.DISCONNECTED:
                    raise DDPHandshakeError('Session closed during capability setup')
                pending.popleft()
                item['result'] = 'setup-confirmed'
                self._confirmed_capability_generation = item['generation']
                completed += 1
            self._application_setup_pending = False
            self._application_request_invalidated = False
            status = getattr(self, '_last_window_status', None)
            self._set_state(DDPState.PAUSED if
                            getattr(self, 'cluster_capabilities', None) is None
                            or (status is not None and status.outcome in ('fault', 'unavailable'))
                            else DDPState.READY)
            return True
        except DDPError as exc:
            if item is not None:
                item.update(result='setup-error', error=str(exc))
            logger.warning('Application reconfiguration failed: %s', exc)
            try:
                self.close_session()
            except DDPError as close_error:
                logger.warning('Reconfiguration close failed: %s', close_error)
            return False
        finally:
            self._servicing_capability_setups = False

    def _recover_application(self):
        """Deferred command-aware recovery with bounded request deadlines.

        Stock mode1 reason02 sends01; other errors retry08 or ask presentation
        to redraw. This client re-negotiates capabilities/setup before allowing
        a redraw, rather than replaying a rejected graphics command. Unknown
        low/extended references close safely; no unknown command is invented.
        """
        reply = getattr(self, '_application_recovery_request', None)
        if reply is None or getattr(self, '_pending_transport_block', False):
            return False
        self._application_recovery_request = None
        self._set_state(DDPState.INITIALIZING)
        try:
            # Bound repeated recovery/redraw/error cycles within one session,
            #not just the inner response wait. Rejected graphics are never
            #automatically resent here; persistent peer errors close safely.
            count = getattr(self, '_application_recovery_count', 0)
            if count >= 3:
                raise DDPHandshakeError('Application recovery episode budget exhausted')
            self._application_recovery_count = count + 1
            if not isinstance(reply, ApplicationReply):
                raise DDPHandshakeError('Malformed application reply has no safe recovery command')
            if reply.reason == 2:
                # All currently implemented client profiles negotiated mode1
                #with subtype0. Alternate modes require a separate proof.
                if getattr(self, '_application_mode', None) != 1:
                    raise DDPHandshakeError('Reason02 recovery is only proved for mode1')
                self.send_data_packet([1,1,0])
            elif reply.command != 8 and not 0x20 <= reply.command <= 0xDF:
                raise DDPHandshakeError('No proved recovery for this application reference')
            self._exchange_application([8], [9])
            return self._reconfigure_application()
        except DDPError as exc:
            logger.warning('Application recovery failed: %s raw%s', exc, getattr(reply, 'raw', reply))
            try:
                self.close_session()
            except DDPError as close_error:
                logger.warning('Application recovery close failed: %s', close_error)
            return False
