import zmq
import json
import time
import random

context = zmq.Context()
pub = context.socket(zmq.PUB)
# Bind to the same address as the worker to simulate it, or connect if it's a sub...
# Wait, worker BINDS to tcp://*:5557, so we should CONNECT to the SUB address of hudiy_data?
# No, hudiy_data subscribes to tcp://localhost:5557.
# So we need to bind to 5557. But the real worker might be bound there.
# If real worker is running, we can't bind.
# We should probably just inject into the IPC if possible, or stop the real worker.

# Actually, hudiy_data subscribes to `metrics_stream` or `tp2_stream`. 
# Config matches tp2_stream in config.json
ipc_addr = "ipc:///run/rnse_control/tp2_stream.ipc"
pub.bind(ipc_addr)

print(f"Simulating TP2 Data on {ipc_addr} (Group 1)...")

while True:
    data = {
        "module": 1,
        "group": 1,
        "data": [
            {"value": f"{random.randint(800, 3000)}", "unit": " /min"},
            {"value": f"{random.randint(80, 105)}", "unit": " °C"},
            {"value": "0.0", "unit": " %"},
            {"value": "10000", "unit": "1110"}
        ]
    }
    msg = [b'HUDIY_DIAG', json.dumps(data).encode('utf-8')]
    pub.send_multipart(msg)
    print(f"Sent: {data['data'][0]['value']}")
    time.sleep(0.5)
