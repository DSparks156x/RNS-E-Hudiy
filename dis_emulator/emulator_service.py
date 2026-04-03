#!/usr/bin/env python3
import zmq
import json
import logging
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO
import os
import threading
import time
import sys
import io
from PIL import Image

# Add dis_client to path for dis_image
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, '..', 'dis_client'))
import dis_image

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

@socketio.on('set_dis_state')
def test_set_dis_state(data):
    if 'bridge' in globals():
        state = data.get('state', 'READY')
        bridge.current_dis_state = state
        logger.info(f"Emulator DIS state manually set to: {state}")
        # Immediate broadcast to feel responsive
        bridge.status_pub.send_string(f"DIS_STATE {state}")

@socketio.on('mock_input')
def test_mock_input(data):
    if 'bridge' in globals():
        bridge.send_mock_can(data)

@socketio.on('mock_hudiy')
def test_mock_hudiy(data):
    if 'bridge' in globals():
        bridge.send_mock_hudiy(data)

@socketio.on('next_track')
def test_next_track():
    if 'bridge' in globals():
        bridge.next_track()

@socketio.on('prev_track')
def test_prev_track():
    if 'bridge' in globals():
        bridge.prev_track()

@socketio.on('custom_image')
def test_custom_image(data):
    if 'bridge' in globals():
        path = data.get('path')
        bridge.send_custom_image(path)

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

        self.current_dis_state = "READY"
        
        # Playlist state
        self.album_covers_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'teststuff', 'albumcovers')
        self.playlist = [
            {
                "title": "One More Time",
                "artist": "Daft Punk",
                "album": "Discovery",
                "file": "Daft_Punk-Discovery.png"
            },
            {
                "title": "Around the World",
                "artist": "Daft Punk",
                "album": "Alive 2007",
                "file": "Daft_Punk_Alive_2007.JPG"
            },
            {
                "title": "Everlong",
                "artist": "Foo Fighters",
                "album": "The Colour And The Shape",
                "file": "FooFighters-TheColourAndTheShape.jpg"
            },
            {
                "title": "Every Breath You Take",
                "artist": "The Police",
                "album": "Synchronicity",
                "file": "ThePolice.jpg"
            }
        ]
        self.current_track_idx = 0

    def send_mock_can(self, data):
        btn = data.get('btn')
        state = data.get('state')
        hex_data = "000000"
        topic = b"CAN_0x2C1"
        
        if state == "pressed":
            if btn == "up":
                hex_data = "000020"
            elif btn == "down":
                hex_data = "000010"
        elif state == "clicked":
            topic = b"CAN_0x5C3"
            if btn == "mfsw_up":
                hex_data = "000B"
            elif btn == "mfsw_down":
                hex_data = "000C"
            elif btn == "mfsw_click":
                hex_data = "0008"
                
        msg = {
            'data_hex': hex_data,
            'dlc': len(hex_data) // 2
        }
        try:
            self.pub_socket.send_multipart([topic, json.dumps(msg).encode()])
            logger.debug(f"Mocked CAN input sent: {btn} {state} to {topic}")
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

    def next_track(self):
        self.current_track_idx = (self.current_track_idx + 1) % len(self.playlist)
        self.send_current_track()

    def prev_track(self):
        self.current_track_idx = (self.current_track_idx - 1) % len(self.playlist)
        self.send_current_track()

    def send_current_track(self):
        track = self.playlist[self.current_track_idx]
        logger.info(f"Emulator: Switching to track {self.current_track_idx}: {track['title']}")
        
        # 1. Send Media Metadata
        self.send_mock_hudiy({
            'topic': 'HUDIY_MEDIA',
            'payload': {
                'title': track['title'],
                'artist': track['artist'],
                'album': track['album'],
                'position': '0:00',
                'duration': '3:45',
                'playing': True,
                'source_id': 3,
                'source_label': 'Bluetooth'
            }
        })
        
        # 3. Synchronize Web UI
        socketio.emit('track_changed', {
            'title': track['title'],
            'artist': track['artist'],
            'album': track['album']
        })
        
        # 2. Process and Send Cover Art
        img_path = os.path.join(self.album_covers_dir, track['file'])
        self.send_image_file(img_path, is_new_track=True)

    def send_custom_image(self, path):
        if not path or not os.path.exists(path):
            logger.error(f"Custom image path not found: {path}")
            socketio.emit('dis_command', {'command': 'debug_log', 'text': f"Error: File not found: {path}"})
            return
        
        logger.info(f"Emulator: Sending custom image: {path}")
        self.send_image_file(path, is_new_track=False)

    def send_image_file(self, path, is_new_track=False):
        try:
            img = Image.open(path)
            processed = dis_image.process_image(img)
            bitmap = dis_image.image_to_bitmap(processed)
            
            cover_data = {
                'bitmap_hex': bitmap.hex(),
                'is_new_track': is_new_track,
                'timestamp': time.time()
            }
            self.hudiy_pub.send_multipart([b'HUDIY_COVERART', json.dumps(cover_data).encode('utf-8')])
            logger.info(f"Emulator: Published Cover Art for {os.path.basename(path)}")
        except Exception as e:
            logger.error(f"Failed to process image {path}: {e}")
            socketio.emit('dis_command', {'command': 'debug_log', 'text': f"Error: Processing failed: {e}"})

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
                    self.status_pub.send_string(f"DIS_STATE {self.current_dis_state}")
                    last_status_time = now
                    
                time.sleep(0.05)
                socks = dict(poller.poll(50))
                
                if self.draw_socket in socks:
                    while True:
                        try:
                            cmd = self.draw_socket.recv_json(flags=zmq.NOBLOCK)
                            socketio.emit('dis_command', cmd)
                            
                            # Closed-loop feedback for frame flow control
                            if cmd.get('command') == 'commit' and 'seq' in cmd:
                                seq = cmd['seq']
                                # Use NOBLOCK to ensure the bridge doesn't stall if the status channel is flooded
                                self.status_pub.send_string(f"DRAW_ACK {seq}", flags=zmq.NOBLOCK)
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
