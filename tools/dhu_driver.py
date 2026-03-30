import subprocess
import time
import math
import threading
import sys
import os
import msvcrt

# Path to DHU
local_app_data = os.environ.get('LOCALAPPDATA', '')
DHU_PATH = os.path.join(local_app_data, r"Android\Sdk\extras\google\auto\desktop-head-unit.exe")
DHU_DIR = os.path.dirname(DHU_PATH)

# Initial position (Default: rando fort collins costco near a roundabout)
START_LAT = 40.520387
START_LON = -104.988262
lat = START_LAT
lon = START_LON
heading = 0.0 # degrees
speed = 0.0 # m/s
max_speed = 100.0 # m/s (approx 144 km/h)

running = True

# Start DHU
extra_args = sys.argv[1:]
if "-c" not in extra_args:
    default_config = os.path.join(DHU_DIR, "config", "default.ini")
    if os.path.exists(default_config):
        extra_args = ["-c", default_config] + extra_args

args = [DHU_PATH] + extra_args
print(f"Starting DHU: {' '.join(args)}")

try:
    process = subprocess.Popen(
        args,
        cwd=DHU_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1
    )
except Exception as e:
    print(f"Failed to start DHU: {e}")
    sys.exit(1)

def output_loop():
    while running and process.poll() is None:
        try:
            line = process.stdout.readline()
            if not line:
                break
            
            clean = line.strip()
            while clean.startswith(">"):
                clean = clean.lstrip(">").strip()
                
            if clean:
                print(f"\r\033[K[DHU] {clean}")
        except Exception:
            break

out_thread = threading.Thread(target=output_loop, daemon=True)
out_thread.start()

def send_command(cmd):
    if process.poll() is not None:
        return
    try:
        process.stdin.write(cmd + "\n")
        process.stdin.flush()
    except Exception as e:
        pass

def physics_loop():
    global lat, lon, heading, speed, running
    
    last_time = time.time()
    while running and process.poll() is None:
        current_time = time.time()
        dt = current_time - last_time
        last_time = current_time
        
        # update location based on speed and heading
        if speed != 0:
            # 0 deg = North (+lat), 90 deg = East (+lon)
            rad = math.radians(heading)
            
            dy = math.cos(rad) * speed * dt
            dx = math.sin(rad) * speed * dt
            
            # 1 deg lat ≈ 111,320m
            # 1 deg lon ≈ 111,320m * cos(lat)
            lat += dy / 111320.0
            lon += dx / (111320.0 * math.cos(math.radians(lat)))
            
        # Send location and compass updates continuously
        # Format: location lat long [accuracy] [altitude] [speed] [bearing]
        send_command(f"location {lat:.6f} {lon:.6f} 5 0 {speed:.2f} {heading:.2f}")
        send_command(f"compass {heading:.2f} 0 0")
        
        time.sleep(0.03)
    
    running = False

physics_thread = threading.Thread(target=physics_loop, daemon=True)
physics_thread.start()

print("\n" + "="*50)
print("              DHU DRIVER STARTED")
print("="*50)
print("Controls:")
print("  W : Accelerate (+1 m/s)")
print("  S : Decelerate / Reverse (-1 m/s)")
print("  A : Steer Left (-5 deg)")
print("  D : Steer Right (+5 deg)")
print("Space: Brake (Stop immediately)")
print("  R : Reset to start position")
print("  Q : Quit")
print("="*50 + "\n")

status_str = ""
while running and process.poll() is None:
    if msvcrt.kbhit():
        key = msvcrt.getch().lower()
        if key == b'q':
            running = False
            break
        elif key == b'x':  # hard exit just in case
            running = False
            break
        elif key == b'w':
            speed = min(speed + 1.0, max_speed)
            if speed > 0 and speed <= 1.0:
                 # Just started moving, update immediately
                 send_command(f"location {lat:.6f} {lon:.6f} 5 0 {speed:.2f} {heading:.2f}")
                 send_command(f"compass {heading:.2f} 0 0")
        elif key == b's':
            speed = max(speed - 1.0, -10.0) # max reverse speed
        elif key == b'a':
            heading = (heading - 5.0) % 360.0
            if speed == 0:
                send_command(f"compass {heading:.2f} 0 0")
        elif key == b'd':
            heading = (heading + 5.0) % 360.0
            if speed == 0:
                send_command(f"compass {heading:.2f} 0 0")
        elif key == b' ':
            speed = 0.0
            send_command(f"location {lat:.6f} {lon:.6f} 5 0 {speed:.2f} {heading:.2f}")
        elif key == b'r':
            lat = START_LAT
            lon = START_LON
            heading = 0.0
            speed = 0.0
            send_command(f"location {lat:.6f} {lon:.6f} 5 0 {speed:.2f} {heading:.2f}")
            send_command(f"compass {heading:.2f} 0 0")
    
    # Simple status print (carriage return to overwrite line)
    new_status = f"\r> Speed: {speed:5.1f} m/s | Heading: {heading:5.1f}° | Lat: {lat:9.5f}  Lon: {lon:10.5f}   "
    if new_status != status_str:
        print(new_status, end="", flush=True)
        status_str = new_status
        
    time.sleep(0.05)

print("\nExiting...")
running = False
if process.poll() is None:
    process.terminate()
