#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import signal

# Dependencies are explicitly required for the user's project but this runs using standard libs.

# Base directores to watch for changes
WATCH_DIRS = [
    os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'dis_client')),
    os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'rns-e_can')),
    os.path.normpath(os.path.dirname(__file__))
]

# Processes to launch in mock mode
PROCESSES = [
    [sys.executable, "emulator_service.py"],
    [sys.executable, os.path.join("..", "dis_client", "dis_display.py"), "--mock"],
    [sys.executable, os.path.join("..", "dis_client", "dis_top_display_service.py"), "--mock"]
]

running_procs = []

def start_processes():
    global running_procs
    print("\n[DevRunner] Starting processes...")
    for cmd in PROCESSES:
        # Spawn child process in the dis_emulator directory
        p = subprocess.Popen(cmd, cwd=os.path.abspath(os.path.dirname(__file__)))
        running_procs.append((cmd, p))

def stop_processes():
    global running_procs
    print("\n[DevRunner] Stopping processes...")
    for cmd, p in running_procs:
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            p.kill()
    running_procs = []

def get_latest_mtime():
    """Scan watch directories for the newest modification time of source files."""
    latest = 0
    for d in WATCH_DIRS:
        if not os.path.exists(d): continue
        for root, dirs, files in os.walk(d):
            if '__pycache__' in root or '.git' in root:
                continue
            for f in files:
                if f.endswith('.py') or f.endswith('.json') or f.endswith('.html'):
                    path = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(path)
                        if mtime > latest:
                            latest = mtime
                    except OSError:
                        pass
    return latest

def main():
    print("[DevRunner] Initialization started...")
    start_processes()
    last_mtime = get_latest_mtime()
    
    def signal_handler(sig, frame):
        stop_processes()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("[DevRunner] Watching for file changes (.py, .json, .html). Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1.0)
            current_mtime = get_latest_mtime()
            if current_mtime > last_mtime:
                print("\n[DevRunner] File change detected! Restarting services...")
                last_mtime = current_mtime
                stop_processes()
                time.sleep(0.5)
                start_processes()
                
            # Check if any process died unexpectedly
            for i, (cmd, p) in enumerate(running_procs):
                if p.poll() is not None:
                    print(f"\n[DevRunner] Process {cmd[1]} exited unexpectedly. Restarting all...")
                    stop_processes()
                    time.sleep(0.5)
                    start_processes()
                    break
    except KeyboardInterrupt:
        stop_processes()
    
    print("[DevRunner] Shutdown complete.")

if __name__ == "__main__":
    main()
