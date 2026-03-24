#!/usr/bin/env python3
# save_logs.py
# Saves the last 3 minutes of journalctl logs for configured services.

import json
import os
import subprocess
from datetime import datetime

def main():
    # Expand ~ to get the home directory of the current user
    home_dir = os.path.expanduser('~')
    config_path = os.path.join(home_dir, 'config.json')
    
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        return

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error reading config: {e}")
        return

    features = config.get('features', {})
    log_saver = features.get('log_saver', {})
    
    # Default services if not configured
    services = log_saver.get('services', ['dis_service.service', 'tp2_worker.service'])
    if not isinstance(services, list):
        services = [services]

    minutes = log_saver.get('minutes', 3)

    # Create logs directory
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    log_dir = os.path.join(home_dir, 'logs', date_str)
    
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        print(f"Error creating directory {log_dir}: {e}")
        return

    for service in services:
        service_clean = service.replace('.service', '')
        index = 1
        # Find next available number
        while True:
            log_file = os.path.join(log_dir, f"{service_clean}_{index}.log")
            if not os.path.exists(log_file):
                break
            index += 1

        print(f"Collecting logs for {service} -> {log_file}")
        
        # Use sudo journalctl to access service logs
        cmd = ["sudo", "journalctl", "-u", service, "--since", f"{minutes} minutes ago"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Only write if there are logs, or write a note if empty
                with open(log_file, 'w') as f:
                    if result.stdout.strip():
                        f.write(result.stdout)
                    else:
                        f.write(f"--- No logs found for {service} in the last 3 minutes ---")
                print(f"Saved {service} logs to {log_file}")
            else:
                print(f"Error running journalctl for {service}: {result.stderr}")
        except Exception as e:
            print(f"Failed to collect logs for {service}: {e}")

if __name__ == '__main__':
    main()
