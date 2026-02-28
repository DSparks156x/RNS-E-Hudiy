import zmq
import json
import time

context = zmq.Context()
sock = context.socket(zmq.PUSH)
sock.connect("tcp://127.0.0.1:5557")

print("Sending clear...")
sock.send_json({"command": "clear"})
time.sleep(0.1)

print("Sending test text A...")
sock.send_json({
    "command": "draw_text",
    "text": "Audi",
    "x": 0,
    "y": 0,
    "flags": 0x06
})
time.sleep(0.1)

print("Sending commit...")
sock.send_json({"command": "commit"})
print("Done.")
