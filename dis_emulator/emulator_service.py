#!/usr/bin/env python3
import zmq
import json
import logging
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO
import os
import threading
import time

# Configuration
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.json')
REFERENCES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references', 'dis display references')
DIS_CLIENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dis_client')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (DIS Emulator) %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')



@socketio.on('connect')
def test_connect():
    logger.info("Client connected to Socket.IO")

@socketio.on('disconnect')
def test_disconnect():
    logger.info("Client disconnected from Socket.IO")

@socketio.on('mock_input')
def test_mock_input(data):
    if 'bridge' in globals():
        bridge.send_mock_can(data)

@socketio.on('mock_hudiy')
def test_mock_hudiy(data):
    if 'bridge' in globals():
        bridge.send_mock_hudiy(data)

class EmulatorBridge:
    def __init__(self, config_path):
        try:
            with open(config_path) as f:
                self.config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            self.config = {
                'zmq': {
                    'dis_draw': 'tcp://*:5557'
                }
            }
            
        self.context = zmq.Context()
        self.draw_socket = self.context.socket(zmq.PULL)
        
        # Try configured address
        addr = None
        try:
            # Check new structure: interfaces.zmq.dis_draw
            addr = self.config.get('interfaces', {}).get('zmq', {}).get('dis_draw')
            # Check old structure if new one is missing
            if not addr:
                addr = self.config.get('zmq', {}).get('dis_draw')
            
            if addr:
                self.draw_socket.bind(addr)
                logger.info(f"ZMQ Listener bound to {addr}")
        except Exception as e:
            logger.warning(f"Could not bind to configured address ({addr}): {e}")

        # Always try to bind TCP 5557 for emulator convenience
        try:
            tcp_addr = "tcp://127.0.0.1:5557"
            self.draw_socket.bind(tcp_addr)
            logger.info(f"ZMQ Listener also bound to {tcp_addr}")
        except Exception as e:
            logger.debug(f"TCP 5557 bind skipped (likely already bound): {e}")
            
        # Pub socket for mock client inputs
        self.pub_socket = self.context.socket(zmq.PUB)
        try:
            self.pub_socket.bind("tcp://127.0.0.1:5558")
            logger.info("ZMQ Mock CAN Publisher bound to tcp://127.0.0.1:5558")
        except Exception as e:
            logger.error(f"Failed to bind mock PUB: {e}")

        # Pub socket for mock hudiy streams
        self.hudiy_pub = self.context.socket(zmq.PUB)
        try:
            self.hudiy_pub.bind("tcp://127.0.0.1:5559")
            logger.info("ZMQ Mock Hudiy Publisher bound to tcp://127.0.0.1:5559")
        except Exception as e:
            logger.error(f"Failed to bind mock Hudiy PUB: {e}")

        self.log_socket = self.context.socket(zmq.PULL)
        try:
            self.log_socket.bind("tcp://127.0.0.1:5560")
            logger.info("ZMQ Mock Log Receiver bound to tcp://127.0.0.1:5560")
        except Exception as e:
            logger.debug(f"TCP 5560 bind skipped: {e}")

        # Status Pub for DIS_STATE (Paused/Ready)
        self.status_pub = self.context.socket(zmq.PUB)
        try:
            self.status_pub.bind("tcp://127.0.0.1:5562")
            logger.info("ZMQ Mock Status Publisher bound to tcp://127.0.0.1:5562")
        except Exception as e:
            logger.error(f"Failed to bind mock status PUB: {e}")

    def send_mock_can(self, data):
        btn = data.get('btn')
        state = data.get('state')
        hex_data = "000000"
        
        if state == "pressed":
            if btn == "up":
                hex_data = "000020"
            elif btn == "down":
                hex_data = "000010"
                
        msg = {'data_hex': hex_data}
        try:
            self.pub_socket.send_multipart([b"CAN_0x2C1", json.dumps(msg).encode()])
            logger.debug(f"Mocked CAN input sent: {btn} {state}")
        except Exception as e:
            logger.error(f"Failed to send mock CAN: {e}")

    def send_mock_hudiy(self, data):
        topic = data.get('topic', '').encode('utf-8')
        payload = data.get('payload', {})
        try:
            self.hudiy_pub.send_multipart([topic, json.dumps(payload).encode('utf-8')])
            logger.debug(f"Mocked Hudiy data sent to {topic}")
        except Exception as e:
            logger.error(f"Failed to send mock Hudiy: {e}")

    def run(self):
        logger.info("ZMQ Bridge Thread Started")
        
        # We poll to prevent blocking either socket
        poller = zmq.Poller()
        poller.register(self.draw_socket, zmq.POLLIN)
        poller.register(self.log_socket, zmq.POLLIN)
        
        last_status_time = 0
        while True:
            try:
                now = time.time()
                # Status Heartbeat (1s)
                if now - last_status_time > 1.0:
                    self.status_pub.send_string("DIS_STATE READY")
                    last_status_time = now
                    
                time.sleep(0.05)
                socks = dict(poller.poll(50))
                
                if self.draw_socket in socks:
                    while True:
                        try:
                            cmd = self.draw_socket.recv_json(flags=zmq.NOBLOCK)
                            socketio.emit('dis_command', cmd)
                        except zmq.Again:
                            break
                        except Exception as e:
                            logger.error(f"Error parsing JSON command: {e}")
                            break
                            
                if self.log_socket in socks:
                    while True:
                        try:
                            txt = self.log_socket.recv_string(flags=zmq.NOBLOCK)
                            socketio.emit('dis_command', {'command': 'debug_log', 'text': txt})
                        except zmq.Again:
                            break
                            
            except Exception as e:
                logger.error(f"ZMQ Bridge Error: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    # Try references dir first
    if os.path.exists(os.path.join(REFERENCES_DIR, filename)):
        return send_from_directory(REFERENCES_DIR, filename)
    # Then dis_client (for icons.py etc if needed, though we'll likely bundle icon data)
    return send_from_directory(DIS_CLIENT_DIR, filename)

if __name__ == '__main__':
    bridge = EmulatorBridge(CONFIG_PATH)
    t = threading.Thread(target=bridge.run, daemon=True)
    t.start()
    
    logger.info("Starting Web Emulator at http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
