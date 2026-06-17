#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
import time
import struct
import unittest
import json
import logging
try:
    import can
except ImportError:
    # Minimal mock of python-can for offline execution
    import queue
    import types
    
    class Message:
        def __init__(self, arbitration_id, data, is_extended_id=False):
            self.arbitration_id = arbitration_id
            self.data = bytes(data)
            self.is_extended_id = is_extended_id
            
    class Bus:
        _channels = {}
        
        def __init__(self, interface, channel, bitrate=None):
            self.channel = channel
            if channel not in Bus._channels:
                Bus._channels[channel] = []
            Bus._channels[channel].append(self)
            self.queue = queue.Queue()
            
        def send(self, msg, timeout=None):
            for bus in Bus._channels.get(self.channel, []):
                if bus is not self:
                    bus.queue.put(msg)
                    
        def recv(self, timeout=None):
            try:
                return self.queue.get(timeout=timeout)
            except queue.Empty:
                return None
                
        def shutdown(self):
            if self.channel in Bus._channels:
                if self in Bus._channels[self.channel]:
                    Bus._channels[self.channel].remove(self)

    can_mock = types.ModuleType('can')
    can_mock.Message = Message
    can_mock.Bus = Bus
    sys.modules['can'] = can_mock
    import can

logger = logging.getLogger(__name__)

# Add the parent and sibling directories to sys.path so we can import openpilot_receiver
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.join(project_root, 'tp2'))
from openpilot_receiver import OpenpilotReceiver

class MockZmqPub:
    def __init__(self):
        self.published = []

    def send_multipart(self, parts):
        self.published.append(parts)

class TestOpenpilotTP2(unittest.TestCase):
    def setUp(self):
        self.zmq_pub = MockZmqPub()
        # Create virtual CAN channel for Comma side simulation
        self.comma_bus = can.Bus(interface='virtual', channel='op_test_channel')
        # Create OpenpilotReceiver
        self.receiver = OpenpilotReceiver(
            can_interface='op_test_channel',
            can_interface_type='virtual',
            zmq_pub=self.zmq_pub
        )

    def tearDown(self):
        self.receiver.stop()
        self.comma_bus.shutdown()

    def test_full_flow(self):
        # 1. Start receiver thread
        self.receiver.start()
        
        # 2. Simulate Comma listening for setup request on 0x200
        msg_setup_req = self.comma_bus.recv(timeout=1.0)
        self.assertIsNotNone(msg_setup_req)
        self.assertEqual(msg_setup_req.arbitration_id, 0x200)
        
        # Dest=0C, Opcode=C0, RX=00 10 (invalid), TX=07 03 (0x307 valid), App=01
        data = list(msg_setup_req.data)
        self.assertEqual(data[0], 0x0C)
        self.assertEqual(data[1], 0xC0)
        self.assertEqual(data[4], 0x07)
        self.assertEqual(data[5], 0x03)
        
        # Send Setup Response (Opcode D0) on 0x20C
        # Dest=00, Opcode=D0, RX=07 03 (0x307 valid), TX=00 04 (0x400 valid), App=01
        setup_resp = [0x00, 0xD0, 0x07, 0x03, 0x00, 0x04, 0x01]
        msg_resp = can.Message(arbitration_id=0x20C, data=setup_resp, is_extended_id=False)
        self.comma_bus.send(msg_resp)
        
        # 3. Wait for Parameters Request (A0) on Pi TX ID 0x307
        msg_params_req = self.comma_bus.recv(timeout=1.0)
        self.assertIsNotNone(msg_params_req)
        self.assertEqual(msg_params_req.arbitration_id, 0x307)
        self.assertEqual(msg_params_req.data[0], 0xA0)
        
        # Send Parameters Response (A1) on Pi RX ID 0x400
        params_resp = [0xA1, 0x0F, 0x8A, 0xFF, 0x4A, 0xFF]
        msg_params_resp = can.Message(arbitration_id=0x400, data=params_resp, is_extended_id=False)
        self.comma_bus.send(msg_params_resp)
        
        # Give receiver a tiny moment to process and shift to CONNECTED state
        time.sleep(0.1)
        self.assertTrue(self.receiver.connected)
        
        # 4. Stream Message Type 1 (Fast State & 3 Leads @ 10Hz)
        # engaged=True, lead_detected=True, confidence=0.8 (50/63), speed=65, max_speed=75, lead_dist=42.0
        # steer_angle=12.5 (250 * 0.05), steer_torque=-0.25 (-25 * 0.01)
        # lead0_lat_dist=-1.2m (-12 * 0.1)
        # lead1_dist=15m, lead1_lat_dist=2.3m (23 * 0.1)
        # lead2_dist=28m, lead2_lat_dist=-3.0m (-30 * 0.1 -> 0xE2)
        # Payload: [0x01, 0xF2, 65, 75, 42, 0x00, 0xFA, 0xE7, 0xF4, 15, 23, 28, 0xE2] (13 bytes)
        fast_payload = [0x01, 0xF2, 65, 75, 42, 0x00, 0xFA, 0xE7, 0xF4, 15, 23, 28, 0xE2]
        
        # Frame 1: Opcode 0x20 (more packets)
        f1_data = [0x20, 0x00, 0x0D] + fast_payload[0:5]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f1_data, is_extended_id=False))
        
        # Frame 2: Opcode 0x21 (more packets)
        f2_data = [0x21] + fast_payload[5:12]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f2_data, is_extended_id=False))

        # Frame 3: Opcode 0x32 (last frame)
        f3_data = [0x32] + fast_payload[12:13] + [0, 0, 0, 0, 0, 0, 0]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f3_data, is_extended_id=False))
        
        # Allow receiver to process
        time.sleep(0.1)
        
        # Verify receiver state
        state = self.receiver.state
        self.assertTrue(state['engaged'])
        self.assertTrue(state['lead_detected'])
        self.assertAlmostEqual(state['model_confidence'], 50/63.0)
        self.assertEqual(state['speed'], 65)
        self.assertEqual(state['max_speed'], 75)
        self.assertEqual(state['lead_dist'], 42.0)
        self.assertAlmostEqual(state['lead_lat_dist'], -1.2)
        
        # Verify 3 leads list
        self.assertEqual(len(state['leads']), 3)
        self.assertEqual(state['leads'][0]['dist'], 42.0)
        self.assertAlmostEqual(state['leads'][0]['lat_dist'], -1.2)
        self.assertEqual(state['leads'][1]['dist'], 15.0)
        self.assertAlmostEqual(state['leads'][1]['lat_dist'], 2.3)
        self.assertEqual(state['leads'][2]['dist'], 28.0)
        self.assertAlmostEqual(state['leads'][2]['lat_dist'], -3.0)

        self.assertAlmostEqual(state['steer_angle'], 12.5)
        self.assertAlmostEqual(state['steer_torque'], -0.25)
        
        # Verify ZMQ publication
        self.assertGreater(len(self.zmq_pub.published), 0)
        topic, json_data = self.zmq_pub.published[-1]
        self.assertEqual(topic, b"HUDIY_OPENPILOT")
        decoded = json.loads(json_data.decode('utf-8'))
        self.assertEqual(decoded['speed'], 65)
        self.assertTrue(decoded['engaged'])
        self.assertEqual(len(decoded['leads']), 3)
        self.assertAlmostEqual(decoded['leads'][1]['lat_dist'], 2.3)

        # 5. Stream Message Type 2 (Path/Lanes State @ 10Hz)
        # Shared 6th-order coefficients:
        # a_6 = -2.0e-8 (raw -20000 -> 0xB1E0)
        # a_5 = 1.0e-6  (raw  10000 -> 0x2710)
        # a_4 = -5.0e-5 (raw  -5000 -> 0xEC78)
        # a_3 = 2.0e-4  (raw    200 -> 0x00C8)
        # a_2 = -1.5e-3 (raw   -150 -> 0xFF6A)
        # a_1 = 0.03    (raw    300 -> 0x012C)
        # Offsets: c_p=10 (0x0A), c_0=48 (0x30), c_1=16 (0x10), c_2=-16 (0xF0), c_3=-48 (0xD0), d_0=22 (0x16), d_1=-22 (0xEA)
        # Probs: ll0/ll1: 1/9 (0x19), ll2/ll3: 9/1 (0x91), re0/re1: 9/9 (0x99)
        # Payload (23 bytes)
        path_payload = [
            0x02, 
            0xB1, 0xE0, 
            0x27, 0x10, 
            0xEC, 0x78, 
            0x00, 0xC8, 
            0xFF, 0x6A, 
            0x01, 0x2C, 
            0x0A, 48, 16, 0xF0, 0xD0, 22, 0xEA, 
            0x19, 0x91, 0x99
        ]
        
        # Frame 1: Opcode 0x22 (more packets)
        f1_path = [0x22, 0x00, 0x17] + path_payload[0:5]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f1_path, is_extended_id=False))
        
        # Frame 2: Opcode 0x23 (more packets)
        f2_path = [0x23] + path_payload[5:12]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f2_path, is_extended_id=False))
        
        # Frame 3: Opcode 0x34 (last frame)
        f3_path = [0x34] + path_payload[12:23] + [0, 0, 0, 0]
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=f3_path, is_extended_id=False))
        
        # Allow receiver to process
        time.sleep(0.1)
        
        # Verify reconstructed curve coordinates
        state = self.receiver.state
        self.assertIsNotNone(state['plan'])
        self.assertIsNotNone(state['lane_lines'])
        self.assertIsNotNone(state['road_edges'])
        
        # Verify lane line probs
        self.assertAlmostEqual(state['lane_line_probs'][0], 0.1)
        self.assertAlmostEqual(state['lane_line_probs'][1], 0.9)
        self.assertAlmostEqual(state['lane_line_probs'][2], 0.9)
        self.assertAlmostEqual(state['lane_line_probs'][3], 0.1)
        self.assertAlmostEqual(state['road_edge_probs'][0], 0.9)
        self.assertAlmostEqual(state['road_edge_probs'][1], 0.9)
        
        # Verify some coordinates at index 0 (x=0) and index 32 (x=192)
        a_6 = -2.0e-8
        a_5 = 1.0e-6
        a_4 = -5.0e-5
        a_3 = 2.0e-4
        a_2 = -1.5e-3
        a_1 = 0.03
        
        # At x=0
        self.assertAlmostEqual(state['plan'][0][0], 0.0)
        self.assertAlmostEqual(state['plan'][0][1], 1.0) # c_p = 1.0
        self.assertAlmostEqual(state['lane_lines'][0][0], 4.8) # 0.0 + 4.8
        self.assertAlmostEqual(state['lane_lines'][1][0], 1.6) # 0.0 + 1.6
        self.assertAlmostEqual(state['lane_lines'][2][0], -1.6) # 0.0 - 1.6
        self.assertAlmostEqual(state['lane_lines'][3][0], -4.8) # 0.0 - 4.8
        self.assertAlmostEqual(state['road_edges'][0][0], 2.2) # 0.0 + 2.2
        self.assertAlmostEqual(state['road_edges'][1][0], -2.2) # 0.0 - 2.2
        
        # At x=192.0
        x_val = 192.0
        expected_y_base = (a_6 * (x_val**6) + a_5 * (x_val**5) + a_4 * (x_val**4) + 
                           a_3 * (x_val**3) + a_2 * (x_val**2) + a_1 * x_val)
        self.assertAlmostEqual(state['plan'][32][0], 192.0)
        self.assertAlmostEqual(state['plan'][32][1], expected_y_base + 1.0)
        self.assertAlmostEqual(state['lane_lines'][1][32], expected_y_base + 1.6)

        # 6. Test Keep-Alive Ping Response
        # Send A3 on 0x400
        self.comma_bus.send(can.Message(arbitration_id=0x400, data=[0xA3], is_extended_id=False))
        
        # Expect A1 response on 0x307
        msg_ka_ack = self.comma_bus.recv(timeout=1.0)
        self.assertIsNotNone(msg_ka_ack)
        self.assertEqual(msg_ka_ack.arbitration_id, 0x307)
        self.assertEqual(msg_ka_ack.data[0], 0xA1)

if __name__ == '__main__':
    unittest.main()
