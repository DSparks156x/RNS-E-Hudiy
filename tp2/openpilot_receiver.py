#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time
import struct
import logging
import threading
import json
import can

logger = logging.getLogger(__name__)

class OpenpilotReceiver(threading.Thread):
    """
    Manages the TP2.0 connection setup and receives data streaming
    from the Comma (module 0x0C) to update Openpilot visualization state.
    """
    def __init__(self, can_interface='can0', can_interface_type='socketcan', zmq_pub=None, pub_lock=None):
        super().__init__()
        self.can_interface = can_interface
        self.can_interface_type = can_interface_type
        self.zmq_pub = zmq_pub
        self.pub_lock = pub_lock
        
        self.daemon = True
        self._running = True
        
        # Openpilot state dictionary
        self.state = {
            'engaged': False,
            'steer_angle': 0.0,
            'steer_torque': 0.0,
            'model_confidence': 1.0,
            'speed': 0,
            'max_speed': 0,
            'lead_dist': 0.0,
            'lead_lat_dist': 0.0,
            'lead_detected': False,
            'leads': [],
            'plan': None,
            'lane_lines': None,
            'lane_line_probs': [0.0, 0.0, 0.0, 0.0],
            'road_edges': None,
            'road_edge_probs': [0.0, 0.0]
        }
        
        # Connection state
        self.connected = False
        self.bus = None
        self.pi_tx_id = 0x67A
        self.pi_rx_id = 0x6DA
        self.last_send_time = 0.0
        self.last_recv_time = 0.0
        
        # Reassembly buffer
        self.rx_buffer = bytearray()
        self.expected_len = 0

    def stop(self):
        self._running = False

    def _send_can(self, arbitration_id, data):
        if not self.bus:
            return
        msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False)
        try:
            self.bus.send(msg, timeout=0.5)
            self.last_send_time = time.time()
            logger.debug(f"OP RX Send: ID={arbitration_id:03X} Data=[{' '.join(f'{b:02X}' for b in data)}]")
        except Exception as e:
            logger.error(f"OP RX Send Error: {e}")
            self.connected = False

    def _publish_state(self):
        if not self.zmq_pub:
            return
        payload = dict(self.state)
        payload['timestamp'] = time.time()
        try:
            serialized = json.dumps(payload).encode('utf-8')
            if self.pub_lock:
                with self.pub_lock:
                    self.zmq_pub.send_multipart([b"HUDIY_OPENPILOT", serialized])
            else:
                self.zmq_pub.send_multipart([b"HUDIY_OPENPILOT", serialized])
        except Exception as e:
            logger.error(f"OP RX ZMQ Publish Error: {e}")

    def _handle_payload(self, payload):
        if not payload:
            return
            
        msg_type = payload[0]
        
        if msg_type == 0x01:
            # Message Type 1: Fast State (10Hz)
            if len(payload) < 8:
                logger.warning(f"OP RX: Invalid length for Fast State message: {len(payload)}")
                return
                
            flags = payload[1]
            engaged = bool(flags & 0x80)
            lead_detected = bool(flags & 0x40)
            model_confidence = (flags & 0x3F) / 63.0
            
            speed = payload[2]
            max_speed = payload[3]
            lead_dist = float(payload[4])
            
            try:
                steer_angle = struct.unpack(">h", bytes(payload[5:7]))[0] * 0.05
                steer_torque = struct.unpack(">b", bytes([payload[7]]))[0] * 0.01
            except Exception as e:
                logger.error(f"OP RX: Steer decode error: {e}")
                return

            lead0_lat_dist = 0.0
            leads = []
            
            if len(payload) >= 9:
                try:
                    lead0_lat_dist = struct.unpack(">b", bytes([payload[8]]))[0] * 0.1
                except Exception as e:
                    logger.error(f"OP RX: Lead0 lateral offset decode error: {e}")
            
            if lead_detected and lead_dist > 2.0:
                leads.append({
                    'dist': lead_dist,
                    'lat_dist': lead0_lat_dist,
                    'detected': True
                })
                
            if len(payload) >= 13:
                try:
                    lead1_dist = float(payload[9])
                    lead1_lat_dist = struct.unpack(">b", bytes([payload[10]]))[0] * 0.1
                    lead2_dist = float(payload[11])
                    lead2_lat_dist = struct.unpack(">b", bytes([payload[12]]))[0] * 0.1
                    
                    if lead1_dist > 2.0:
                        leads.append({
                            'dist': lead1_dist,
                            'lat_dist': lead1_lat_dist,
                            'detected': True
                        })
                    if lead2_dist > 2.0:
                        leads.append({
                            'dist': lead2_dist,
                            'lat_dist': lead2_lat_dist,
                            'detected': True
                        })
                except Exception as e:
                    logger.error(f"OP RX: Lead1/2 decode error: {e}")
                
            self.state.update({
                'engaged': engaged,
                'lead_detected': lead_detected,
                'model_confidence': model_confidence,
                'speed': speed,
                'max_speed': max_speed,
                'lead_dist': lead_dist,
                'lead_lat_dist': lead0_lat_dist,
                'leads': leads,
                'steer_angle': steer_angle,
                'steer_torque': steer_torque
            })
            
            self._publish_state()
            
        elif msg_type == 0x02:
            # Message Type 2: Path/Lanes State (10Hz)
            if len(payload) < 23:
                logger.warning(f"OP RX: Invalid length for Path/Lanes message: {len(payload)}")
                return
                
            try:
                # Unpack 6th-order shared coefficients
                a_6 = struct.unpack(">h", bytes(payload[1:3]))[0] * 1e-12
                a_5 = struct.unpack(">h", bytes(payload[3:5]))[0] * 1e-10
                a_4 = struct.unpack(">h", bytes(payload[5:7]))[0] * 1e-8
                a_3 = struct.unpack(">h", bytes(payload[7:9]))[0] * 1e-6
                a_2 = struct.unpack(">h", bytes(payload[9:11]))[0] * 1e-5
                a_1 = struct.unpack(">h", bytes(payload[11:13]))[0] * 1e-4
                
                # Unpack lateral offsets (scale 0.1m)
                c_p = struct.unpack(">b", bytes([payload[13]]))[0] * 0.1
                c_0 = struct.unpack(">b", bytes([payload[14]]))[0] * 0.1
                c_1 = struct.unpack(">b", bytes([payload[15]]))[0] * 0.1
                c_2 = struct.unpack(">b", bytes([payload[16]]))[0] * 0.1
                c_3 = struct.unpack(">b", bytes([payload[17]]))[0] * 0.1
                
                d_0 = struct.unpack(">b", bytes([payload[18]]))[0] * 0.1
                d_1 = struct.unpack(">b", bytes([payload[19]]))[0] * 0.1
                
                # Unpack probabilities (4-bit scale 0.1)
                prob_ll0 = (payload[20] >> 4) * 0.1
                prob_ll1 = (payload[20] & 0x0F) * 0.1
                prob_ll2 = (payload[21] >> 4) * 0.1
                prob_ll3 = (payload[21] & 0x0F) * 0.1
                prob_re0 = (payload[22] >> 4) * 0.1
                prob_re1 = (payload[22] & 0x0F) * 0.1
            except Exception as e:
                logger.error(f"OP RX: Curve parameters decode error: {e}")
                return
                
            # Reconstruct 33-point curves
            x_idxs = [192.0 * ((i / 32.0) ** 2) for i in range(33)]
            
            plan = []
            lane_lines = [[], [], [], []]
            road_edges = [[], []]
            
            for x in x_idxs:
                # Evaluate 6th-order polynomial baseline
                y_base = (a_6 * (x ** 6) + a_5 * (x ** 5) + a_4 * (x ** 4) +
                          a_3 * (x ** 3) + a_2 * (x ** 2) + a_1 * x)
                
                plan.append([x, y_base + c_p, 0.0])
                lane_lines[0].append(y_base + c_0)
                lane_lines[1].append(y_base + c_1)
                lane_lines[2].append(y_base + c_2)
                lane_lines[3].append(y_base + c_3)
                road_edges[0].append(y_base + d_0)
                road_edges[1].append(y_base + d_1)
                
            self.state.update({
                'plan': plan,
                'lane_lines': lane_lines,
                'lane_line_probs': [prob_ll0, prob_ll1, prob_ll2, prob_ll3],
                'road_edges': road_edges,
                'road_edge_probs': [prob_re0, prob_re1]
            })
            
            self._publish_state()

    def run(self):
        logger.info("OpenpilotReceiver background thread started.")
        
        while self._running:
            if not self.connected:
                # Cleanup if necessary
                if self.bus:
                    try:
                        self.bus.shutdown()
                    except:
                        pass
                    self.bus = None
                
                # Attempt to open CAN interface
                try:
                    self.bus = can.Bus(interface=self.can_interface_type, channel=self.can_interface, bitrate=100000)
                except Exception as e:
                    logger.error(f"OP RX: Failed to open CAN bus: {e}")
                    time.sleep(5.0)
                    continue
                
                logger.info(f"OP RX: Handshaking with Comma on 0x{self.pi_tx_id:03X}/0x{self.pi_rx_id:03X}...")
                
                # Send Parameters Request (A0) on pi_tx_id
                # Block size: 0x0F, T1: 0x8A (138ms), T3: 0x0A (1ms)
                params_req = [0xA0, 0x0F, 0x8A, 0xFF, 0x0A, 0xFF]
                try:
                    self._send_can(self.pi_tx_id, params_req)
                except Exception as e:
                    logger.error(f"OP RX: Handshake send failed: {e}")
                    time.sleep(2.0)
                    continue
                
                # Wait for Parameters Response (A1) on pi_rx_id
                start_wait = time.time()
                handshake_success = False
                while time.time() - start_wait < 1.5:
                    try:
                        msg = self.bus.recv(timeout=0.1)
                        if msg and msg.arbitration_id == self.pi_rx_id:
                            data = list(msg.data)
                            if len(data) >= 1 and data[0] == 0xA1:
                                handshake_success = True
                                break
                    except Exception as e:
                        logger.error(f"OP RX: Handshake recv error: {e}")
                        break
                        
                if not handshake_success:
                    logger.warning("OP RX: Handshake timed out or refused. Retrying in 5 seconds...")
                    time.sleep(5.0)
                    continue
                    
                # Setup completed successfully!
                self.connected = True
                self.last_recv_time = time.time()
                self.rx_buffer = bytearray()
                self.expected_len = 0
                logger.info("OP RX: Channel fully opened.")
                
            # Channel is active: poll and receive frames
            try:
                msg = self.bus.recv(timeout=0.1)
                now = time.time()
                
                # Handle connection timeout (no packets for 3 seconds)
                if now - self.last_recv_time > 3.0:
                    logger.warning("OP RX: Connection timeout. Disconnecting...")
                    self.connected = False
                    continue
                
                # Send periodic keep-alive to appease the gateway
                if now - self.last_send_time > 2.0:
                    # Send keep-alive A3 on pi_tx_id
                    self._send_can(self.pi_tx_id, [0xA3])
                
                if msg:
                    if msg.arbitration_id == self.pi_rx_id:
                        self.last_recv_time = now
                        data = list(msg.data)
                        if not data:
                            continue
                            
                        opcode_byte = data[0]
                        opcode = opcode_byte & 0xF0
                        seq = opcode_byte & 0x0F
                        
                        # 1. Keep Alive Ping (A3) -> Respond with Keep Alive Ack (A1)
                        if opcode_byte == 0xA3:
                            self._send_can(self.pi_tx_id, [0xA1])
                            continue
                            
                        # 2. Keep Alive Response (A1) -> Just update timestamp
                        if opcode_byte == 0xA1:
                            continue
                            
                        # 3. Disconnect request from Comma (A8)
                        if opcode_byte == 0xA8:
                            logger.info("OP RX: Comma requested disconnect.")
                            self.connected = False
                            continue
                            
                        # 4. Data Frames (Opcodes 0x00, 0x10, 0x20, 0x30)
                        # Reassembly logic:
                        if opcode == 0x00 or opcode == 0x20:
                            # Start or Continuation Frame
                            if len(self.rx_buffer) == 0:
                                # First frame must have length prefix (2 bytes)
                                if len(data) >= 3:
                                    self.expected_len = (data[1] << 8) | data[2]
                                    self.rx_buffer.extend(data[3:])
                            else:
                                self.rx_buffer.extend(data[1:])
                                
                        elif opcode == 0x10 or opcode == 0x30:
                            # Last Frame
                            if len(self.rx_buffer) == 0:
                                # Single-frame message
                                if len(data) >= 3:
                                    self.expected_len = (data[1] << 8) | data[2]
                                    payload = data[3:3 + self.expected_len]
                                    self._handle_payload(payload)
                            else:
                                self.rx_buffer.extend(data[1:])
                                if len(self.rx_buffer) >= self.expected_len:
                                    payload = list(self.rx_buffer[:self.expected_len])
                                    self._handle_payload(payload)
                            
                            # Clean reassembly state
                            self.rx_buffer = bytearray()
                            self.expected_len = 0
                            
                            # Send ACK if sender is waiting for ACK (Opcodes 0x00 / 0x10)
                            if opcode == 0x10:
                                ack_seq = (seq + 1) % 16
                                self._send_can(self.pi_tx_id, [0xB0 | ack_seq])
                                
            except Exception as e:
                logger.error(f"OP RX: Loop error: {e}")
                self.connected = False
                time.sleep(1.0)
                
        # Thread exit cleanup
        if self.connected and self.bus:
            try:
                # Send disconnect
                self._send_can(self.pi_tx_id, [0xA8])
            except:
                pass
        if self.bus:
            try:
                self.bus.shutdown()
            except:
                pass
            self.bus = None
