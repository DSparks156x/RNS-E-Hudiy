#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import struct
import logging
import can
from typing import List, Optional, Tuple, Dict, Union

logger = logging.getLogger(__name__)

class TP2Error(Exception):
    pass

class TP2Protocol:
    """
    Implements the VW TP2.0 Transport Protocol over CAN.
    Manages Dynamic Channel Setup, Keep-Alives, Sequence Numbers, and Block Transmission.
    """

    # --- Constants ---
    CAN_BROADCAST_REQ = 0x200
    CAN_BROADCAST_RESP = 0x201
    
    # Timing (ms)
    T1_TIMEOUT = 2500   # Wait for response (Increased from 1000ms)
    T3_INTERVAL = 12    # Inter-frame gap (Matched to ECU_Read.cpp)

    def __init__(self, channel='can0'):
        self.channel = channel
        self.bus = None
        self.tester_id = 0x300 # Standard Tester ID
        self.tx_id = 0x000     # Will be dynamic
        self.rx_id = 0x000     # Will be dynamic
        
        self.block_size = 0    # Negotiated Block Size
        self.t1 = 100          # Timer 1
        self.t3 = 10           # Timer 3
        
        self.seq_tx = 0        # TX Sequence Number (0..F)
        self.seq_rx = 0        # RX Sequence Number (0..F)
        self.connected = False

    def open(self):
        """Opens the CAN Bus interface."""
        try:
            self.bus = can.Bus(interface='socketcan', channel=self.channel, bitrate=100000)
            logger.info(f"TP2: CAN bus {self.channel} opened.")
        except Exception as e:
            logger.error(f"TP2: Failed to open CAN bus: {e}")
            raise TP2Error(e)

    def close(self):
        """Closes the session and bus."""
        if self.connected:
            self.disconnect()
        if self.bus:
            self.bus.shutdown()
            self.bus = None

    def _send(self, arbitration_id, data):
        msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False)
        try:
            logger.info(f"TX: ID={arbitration_id:03X} Data=[{' '.join(f'{b:02X}' for b in data)}]")
            self.bus.send(msg)
            time.sleep(self.t3 / 1000.0) # T3 Delay
        except can.CanError as e:
            logger.error(f"TP2: CAN Send Error: {e}")
            raise TP2Error(e)

    def _recv(self, arbitration_id, timeout_ms=None) -> Optional[List[int]]:
        """Waits for a specific ID."""
        if timeout_ms is None: timeout_ms = self.t1
        
        end_time = time.time() + (timeout_ms / 1000.0)
        while time.time() < end_time:
            msg = self.bus.recv(0.05) # Poll
            if msg:
                # Log everything for debugging
                if msg.arbitration_id == arbitration_id:
                     logger.info(f"RX: ID={msg.arbitration_id:03X} Data=[{' '.join(f'{b:02X}' for b in msg.data)}]")
                     return list(msg.data)
                elif msg.arbitration_id == self.rx_id: # Also log expected RX ID if we filter
                     logger.info(f"RX (Ignored): ID={msg.arbitration_id:03X} Data=[{' '.join(f'{b:02X}' for b in msg.data)}]")
        return None

    def _clear_rx_buffer(self):
        """Drains the CAN buffer of any pending messages."""
        while True:
            msg = self.bus.recv(0.01) # Non-blocking check
            if not msg: break
            # logger.debug(f"TP2: Drained stale msg ID {msg.arbitration_id:X}")

    def connect(self, target_module_id: int) -> bool:
        """
        Performs the TP2.0 Channel Setup.
        target_module_id: e.g. 0x01 (Engine), 0x17 (Instruments)
        """
        logger.info(f"TP2: Connecting to Module 0x{target_module_id:02X}...")
        
        # 1. Broadcast Request (0x200)
        # Format: [DestID, OpCode=C0, 00, 10, 00, 03, 01]
        req = [target_module_id, 0xC0, 0x00, 0x10, 0x00, 0x03, 0x01]
        self._send(self.CAN_BROADCAST_REQ, req)

        # 2. Wait for Response (0x201)
        # Format: [ModID, D0, CommID_Low, CommID_High, RX_ID_Low, RX_ID_High, 00]
        resp = self._recv(self.CAN_BROADCAST_RESP, 1000)
        if not resp:
            logger.error("TP2: No response to connection request.")
            return False
        
        if resp[0] != 0x00 or resp[1] != 0xD0:
            logger.error(f"TP2: Invalid connection response: {resp}")
            return False

        # Parse RX ID (The ID we must Listen to)
        self.rx_id = (resp[5] << 8) + resp[4]
        # Calculate TX ID (The ID we must Send to) - Usually RX_ID - 1 or determined by logic
        
        # Correction:
        # Byte 4/5 is the "CAN-ID for CAN-Response".
        # So ECU sends D0 xx xx xx ID_LO ID_HI.
        # That ID is what we should use to SEND to the ECU.
        self.tx_id = (resp[5] << 8) | resp[4]
        self.rx_id = self.tester_id # We listen on 0x300 (Standard)
        
        logger.info(f"TP2: Dynamic ID Assigned. TX to 0x{self.tx_id:X}, RX on 0x{self.rx_id:X}")

        # 3. Send Timing Parameters (A0)
        # Format: [A0, BlockSize, T1_Low, T1_High, T3, Reserved]
        # BlockSize: 0x0F (15 frames) or 0x00 (Blocksize 0?)
        # vwtp.c: {0xA0, 0x0F, 0x8A, 0xFF, 0x32, 0xFF}
        # T1 = 0x8A = 138 * 1ms = 138ms?
        # T3 = 0x32 = 50 * 100us?
        
        params = [0xA0, 0x0F, 0x8A, 0xFF, 0x32, 0xFF]
        self._send(self.tx_id, params)

        # 4. Wait for Parameter Response (A1)
        # Format: [A1, ...]
        resp = self._recv(self.rx_id, 1000)
        if not resp or resp[0] != 0xA1:
             logger.error(f"TP2: Parameter negotiation failed. Resp: {resp}")
             return False
             
        self.connected = True
        self.seq_tx = 0
        self.seq_rx = 0
        logger.info("TP2: Connected.")
        return True

    def disconnect(self):
        """Sends Disconnect (A8)."""
        if self.tx_id:
            try:
                self._send(self.tx_id, [0xA8])
            except: pass
        self.connected = False
        logger.info("TP2: Disconnected.")

    def send_kvp_request(self, payload: List[int]) -> Optional[List[int]]:
        """
        Sends a KWP2000 payload wrapped in TP2.0 frames and returns the KWP response.
        Handles segmentation (TX) and reassembly (RX).
        """
        if not self.connected: raise TP2Error("Not connected")
        
        # Drain any late/stale packets from previous interactions
        self._clear_rx_buffer()
        
        # --- TX PATH ---
        # Payload Format: [Len, SID, Data...] (If < packet)
        
        full_len = len(payload)
        
        # Standard TP2.0 Rolling Sequence Number
        # We start at 0 (set in connect) and increment.
        
        frame = [0x10 + self.seq_tx, 0x00, full_len] + payload
        
        self.seq_tx = (self.seq_tx + 1) % 16
        self._send(self.tx_id, frame)
        
        # Wait for ACK (B0 + Seq)
        ack = self._wait_ack(self.seq_tx - 1)
        if not ack:
            raise TP2Error("No ACK for Request")

        # --- RX PATH ---
        return self._read_multiframe_response()

    def _wait_ack(self, seq_num):
        """Waits for 0xB0 + (seq+1)."""
        expected = 0xB0 + ((seq_num + 1) % 16)
        msg = self._recv(self.rx_id, self.T1_TIMEOUT)
        if msg and msg[0] == expected:
            return True
        return False

    def _read_multiframe_response(self) -> List[int]:
        """Reassembles incoming KWP response."""
        buffer = []
        expected_len = 0
        
        while True:
            msg = self._recv(self.rx_id, self.T1_TIMEOUT)
            if not msg: raise TP2Error("Timeout waiting for response")
            
            # ACK Packet (B0) - Should not happen here unless keep-alive?
            if (msg[0] & 0xF0) == 0xB0: continue 

            # Keep Alive (A3) - Reply A1
            if msg[0] == 0xA3:
                self._send(self.tx_id, [0xA1])
                continue

            # Disconnect (A8) - Reply A8 and close
            if msg[0] == 0xA8:
                logger.info("TP2: Received Disconnect from ECU.")
                self.disconnect()
                raise TP2Error("Disconnected by ECU")
            
            # Wait Frame (0x9x) - Extend Timeout
            if (msg[0] & 0xF0) == 0x90:
                 logger.warning(f"TP2: Received 0x{msg[0]:02X} (Wait?). Extending timeout.")
                 continue

            seq = msg[0] & 0x0F
            type_ = msg[0] & 0xF0
            
            data_part = []
            
            # If this is the FIRST frame we've accepted, it MUST contain the length.
            # It can be Type 1x (Single/Last) or Type 2x (First of many).
            if expected_len == 0:
                if len(msg) < 4:
                     # Packet too short to contain Length + SID?
                     # Standard Header: [Type, LenHi, LenLo, SID...]
                     continue
                
                expected_len = (msg[1] << 8) + msg[2]
                logger.info(f"TP2: Incoming Block Length: {expected_len}")
                data_part = msg[3:] # Data starts after Length (2 bytes)
            else:
                # Continuation Frame (Type 2x or 1x)
                data_part = msg[1:] # Data starts immediately after header
            
            buffer.extend(data_part)
            
            # If Type is 1x (End of Block), we must segments ACK.
            # In Multi-frame, 2x is "Don't ACK", 1x is "ACK me".
            if type_ == 0x10:
                # Check for underflow if needed, but mostly we just ACK
                self._send(self.tx_id, [0xB0 + ((seq + 1) % 16)])
            
            # Check if we are done
            if expected_len > 0 and len(buffer) >= expected_len:
                return buffer[:expected_len] # Trim any padding if present

    def send_keep_alive(self):
        """Sends Keep-Alive Ping (A3) and waits for response (A1)."""
        if self.tx_id:
            try:
                self._send(self.tx_id, [0xA3])
                resp = self._recv(self.rx_id, self.T1_TIMEOUT)
                
                if not resp:
                    logger.warning("TP2: Keep-Alive timeout.")
                    return False
                    
                if resp[0] == 0xA8:
                     logger.info("TP2: Received Disconnect from ECU during Keep-Alive.")
                     self.disconnect()
                     return False
                     
                if resp[0] != 0xA1 and resp[0] != 0x93: # 0x93 seen in logs
                    logger.warning(f"TP2: Keep-Alive failed. Resp: {resp}")
                    return False
                return True
            except Exception as e:
                logger.error(f"TP2: Keep-Alive Error: {e}")
                return False
        return False
