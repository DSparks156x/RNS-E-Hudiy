import zmq
import json
import time

def stress_test():
    ctx = zmq.Context()
    draw = ctx.socket(zmq.PUSH)
    # Connect to the default dis_draw address (ipc or tcp)
    # Using the one from the project's config might be better, but we'll try to find it.
    
    # We'll use the emulator port if we're testing locally
    addr = "tcp://127.0.0.1:5557"
    print(f"Connecting to {addr}...")
    draw.connect(addr)
    
    print("Flooding 100 commands...")
    for i in range(100):
        draw.send_json({
            'command': 'draw_text',
            'text': f"Burst {i}",
            'x': 0,
            'y': 1,
            'flags': 0x06
        })
    
    # Final state
    draw.send_json({
        'command': 'draw_text',
        'text': "FINAL STATE",
        'x': 0,
        'y': 1,
        'flags': 0x06
    })
    draw.send_json({'command': 'commit'})
    
    print("Sent. If optimized, dis_service should skip the first 100 and jump to 'FINAL STATE'.")

if __name__ == "__main__":
    stress_test()
