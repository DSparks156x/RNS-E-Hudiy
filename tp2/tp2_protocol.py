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
        # Standard: RX_ID is what ECU transmits on. TX_ID is what we send on.
        # Actually logic is: ECU Tells us its TX_ID.
        # So self.rx_id = (resp[5]<<8)|resp[4].
        # The ID we transmit on is usually self.rx_id - 1? Or assigned?
        # VWTP.c says: ecuId = (msg.payload[5]<<8) | msg.payload[4];
        # This implementation calls it "ecuId".
        self.tx_id = self.rx_id # The ID we send TO.
        # Wait, if we send TO this id, we receive on?
        # Let's adjust based on vwtp.c:
        # msg.id = ecuId; (For sending parameters)
        # CAN_SetFilter0(testerId); (For receiving) -> testerId is 0x300 usually.
        # So we SEND to the dynamic ID provided, and we RECEIVE on 0x300 + logic?
        # Actually, TP2 uses dynamic IDs for both directions usually.
        # Re-reading vwtp.c:
        # testerId = 0x300;
        # CAN_SetFilter0(testerId);
        # So the ECU replies to 0x300?
        # Let's assume RX_ID = 0x300 for now if vwtp.c uses it.
        # BUT: The response 0xD0 contains "RX_ID". Is that what the ECU receives on?
        
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
        # Actually KWP over TP2.0 usually:
        # Frame 1: [10+Seq, Len_MSB, Len_LSB, SID, Data...] ???
        # Wait, vwtp.c:
        # msg.len = 5 + kwpMessage[0];
        # msg.payload[0] = 0x10 | nextSN;
        # msg.payload[1] = 0x00;
        # msg.payload[2] = 0x02 + kwpMessage[0]; // Length includes 2 bytes (SID+Param?)?
        
        # Let's follow the standard:
        # Single Frame: Not supported in TP2.0? It seems everything is "Wait for ACK".
        # vwtp.c logic: "SEND_REQUEST" uses 0x1x (First Frame) always?
        # Yes, 0x1N is "Last frame of block, expecting ACK".
        # 0x2N is "Intermediate frame, no ACK".
        # 0x0N is "Single Frame"? Not in TP2.0?
        # vwtp.c only uses 0x10 | nextSN.
        
        # We will wrap the KWP payload.
        # KWP Payload = [SID, Args...]
        # We need to prepend Length?
        # vwtp.c prepends 2 bytes of length? No, it puts length in byte 1/2 of CAN frame.
        
        # Simplified Logic (Short Request - all we need for now):
        # Frame: [0x10 + Seq, 0x00, Length, SID, Args, ...]
        
        # vwtp.c Logic:
        # msg.payload[0] = 0x10 | nextSN;
        # msg.payload[1] = 0x00;
        # msg.payload[2] = 0x02 + kwpMessage[0]; // KWP Len + 2 (SID+Param count?? or just fixed offset?)
        # Wait, if kwpMessage[0] is length of params? 
        # vwtp.c: msg.payload[3] = SID; msg.payload[4] = parameter; 
        # then loops i=0 to kwpMessage[0].
        # It seems vwtp.c treats kwpMessage[0] as "Extra Data Length".
        # Total Length = 1 (SID) + 1 (Param) + Extra Data? 
        # No, let's look at `VWTP_KWP2000Message(SID, parameter, kwpMessage)`
        # It takes SID and Parameter explicitly.
        
        # In our case, `payload` is `[SID, Param, ...]`.
        # So `len(payload)` IS the total KWP length.
        
        # If vwtp.c sets `msg.payload[2] = 0x02 + data_len`, effectively:
        # It includes the SID and Parameter byte in the length if they are separate?
        # Actually vwtp.c code shows:
        # msg.payload[3] = SID;
        # msg.payload[4] = parameter;
        # ... copy rest ...
        # This implies standard KWP frame is:
        # Byte 0: 10+Seq
        # Byte 1: 00
        # Byte 2: LENGTH
        # Byte 3: SID
        # Byte 4: Data...
        
        # IF vwtp.c adds 2, maybe the length byte *should* capture the length of KWP data?
        # IF `kwpMessage` is just the extra data...
        # Standard TP2.0 says Byte 2 is "Length of data field".
        # If payload is [SID, Arg], length is 2.
        
        # Let's try sending EXACTLY what vwtp.c does if we assume our payload is the whole KWP msg.
        # But wait, vwtp.c logic `0x02 + kwpMessage[0]` where kwpMessage[0] is length of *extra* data?
        # If we send `21 01` (SID=21, Param=01), `kwpMessage` would be empty/zero?
        # Then `0x02 + 0` = 2.
        # So Length Byte = 2.
        # This matches `len([0x21, 0x01])`.
        
        # So `full_len = len(payload)` SHOULD be correct if payload is `[21, 01]`.
        # UNLESS... we need to account for valid data length in `vwtp.c`?
        # "msg.len = 5 + kwpMessage[0]" -> 5 + 0 = 5 CAN bytes.
        # [10, 00, 02, 21, 01].
        
        # Let's verify what we are sending. 
        # `frame = [0x10 + self.seq_tx, 0x00, full_len] + payload`
        # `full_len = 2`.
        # `frame` = `[10, 00, 02, 21, 01]`.
        # `_send` adds no padding.
        # `can.Message(DLC=5, data=[...])`.
        
        # This looks correct.
        # Why did it fail?
        # 1. Sequence number? (Reset to 0 on connect).
        # 2. Maybe `0x00` byte (Byte 1) should be something else? `vwtp.c` sets it to `0x00`.
        # 3. Maybe the ECU needs PADDING for the KWP packet itself even if TP2 doesn't?
        # vwtp.c: `msg.len = 5 + kw...`. It sends short CAN frame.
        
        # Wait, look at `send_kvp_request` logic again.
        # We perform `_send` then `_wait_ack`.
        # The ACK comes.
        # Then we `_read_multiframe_response`.
        
        # In `_read_multiframe_response`:
        # `msg = self._recv(...)`
        # If the ECU is "Busy", does it send a "Wait" frame?
        # 0x90? We saw warnings of `Tp2: Received 0x93 (Type 9?)`.
        # In the log: `TP2: Keep-Alive failed. Resp: [147]`. 147 = 0x93.
        # We handled that in KeepAlive.
        # BUT, did we handle it in `_read_multiframe_response`?
        # Yes, we added: `elif (type_ & 0xF0) == 0x90:` -> `pass`.
        # If we `pass`, we loop again.
        # If the ECU sends `0x93` repeatedly, we loop forever until timeout.
        # Maybe `0x93` means "Wait"?
        
        full_len = len(payload)
        
        # EXPERIMENTAL: For `21 01` specifically, some ECUs might expect standard length?
        # Or maybe the sequence number is wrong?
        # self.seq_tx starts at 0.
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

            seq = msg[0] & 0x0F
            type_ = msg[0] & 0xF0
            
            # Start/Last Frame (0x10) or Intermediate (0x20)
            if type_ == 0x10:
                # First packet contains length
                # Bytes: [Type+Seq, Len_MSB, Len_LSB, Data...]
                if len(msg) < 4:
                     # Packet too short?
                     continue
                
                cur_len = (msg[1] << 8) + msg[2]
                if expected_len == 0: expected_len = cur_len
                
                data_part = msg[3:]
                
                # Append data (only up to expected_len)
                needed = expected_len - len(buffer)
                if len(data_part) > needed:
                    data_part = data_part[:needed]
                
                buffer.extend(data_part)
                
                # Check if we are done
                if len(buffer) >= expected_len:
                    # Send ACK before returning
                    self._send(self.tx_id, [0xB0 + ((seq + 1) % 16)])
                    return buffer
                else:
                    # Still need more data? 
                    # For 0x1x, this implies it's the LAST frame of a block. 
                    # If we don't have enough data yet, something is wrong or it's a multi-block transfer.
                    # But 0x1x usually means "End of Block".
                    # Let's just ACK and wait for more blocks?
                    # vwtp.c logic: "Wait for ACK".
                    # If we are RECEIVING, we send ACK.
                    self._send(self.tx_id, [0xB0 + ((seq + 1) % 16)])
                
            elif type_ == 0x20:
                # Intermediate Frame
                # Bytes: [Type+Seq, Data...]
                data_part = msg[1:]
                buffer.extend(data_part)
                
            elif (type_ & 0xF0) == 0x90:
                # 0x9x might be a variant?
                logger.warning(f"TP2: Received 0x{msg[0]:02X} (Wait?). Extending timeout.")
                # Reset timeout since the ECU is alive but busy
                end_time = time.time() + (self.T1_TIMEOUT / 1000.0)
                pass
            
            else:
                 logger.warning(f"TP2: Unknown frame type {msg[0]:02X}")

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
