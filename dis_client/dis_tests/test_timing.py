import sys

# Simulation of dis_service.py batching logic to prove frame counts
def simulate_frame(rows):
    current_payload = []
    blocks_sent = 0
    total_bytes_sent = 0
    pacing_delays = 0
    
    # Simulate clip command (7 bytes)
    p = [0x52, 0x05, 0x00, 0, 0, 64, 48]
    
    for i in range(rows):
        # Simulate 1 row draw command (5 byte header + 8 bytes data)
        p += [0x55, 11, 0x02, 0x00, i] + [0]*8
        
    # Simulate reset command (7 bytes)
    p += [0x52, 0x05, 0x00, 0, 0, 0x40, 0x3D]

    # This is how `dis_service.py` batches commands
    chunks = [p[i:i + 42] for i in range(0, len(p), 42)]
    
    print(f"Total payload size: {len(p)} bytes")
    print(f"Number of 42-byte DDP blocks: {len(chunks)}")
    print(f"Number of 20ms pacing delays: {len(chunks)}")
    print(f"Total pacing delay overhead: {len(chunks) * 20}ms")

if __name__ == "__main__":
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"Simulating a delta update of {rows} changed rows...")
    simulate_frame(rows)
