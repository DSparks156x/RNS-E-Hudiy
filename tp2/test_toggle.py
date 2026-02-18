import zmq
import json

context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect("tcp://localhost:5558")

print("Sending TOGGLE command...")
socket.send_json({"cmd": "TOGGLE"})
resp = socket.recv_json()
print(f"Response: {resp}")
