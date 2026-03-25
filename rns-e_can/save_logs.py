#!/usr/bin/env python3
# save_logs.py
# Saves the last 3 minutes of journalctl logs for configured services.

import json
import os
import subprocess
import sys
import threading
from datetime import datetime

# --- Add hudiy_client to Python path ---
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    api_path = os.path.join(os.path.dirname(script_dir), 'hudiy_client', 'api_files')
    if not os.path.exists(api_path):
        # Fallback for alternative structures
        api_path = os.path.join(script_dir, '..', 'hudiy_client', 'api_files')
    sys.path.insert(0, api_path)
    
    from common.Client import Client, ClientEventHandler
    import common.Api_pb2 as hudiy_api
except ImportError as e:
    print(f"Warning: Could not import Hudiy client libraries: {e}")
    Client = None # Fail gracefully if Hudiy libraries are missing

class SaveLogsEventHandler(ClientEventHandler):
    def __init__(self):
        super().__init__()
        self.icon_id = None
        self.running = True

    def on_hello_response(self, client, message):
        try:
            req = hudiy_api.RegisterStatusIconRequest()
            req.description = "Logs Saved"
            req.icon_name = "save"
            req.icon_font_family = "Material Symbols Rounded"
            client.send(hudiy_api.MESSAGE_REGISTER_STATUS_ICON_REQUEST, 0, req.SerializeToString())
        except Exception as e:
            print(f"Error registering icon: {e}")
            self.running = False

    def on_register_status_icon_response(self, client, message):
        if message.result == 1:  # REGISTER_STATUS_ICON_RESULT_OK
            self.icon_id = message.id
            try:
                msg = hudiy_api.ChangeStatusIconState()
                msg.id = self.icon_id
                msg.visible = True
                client.send(hudiy_api.MESSAGE_CHANGE_STATUS_ICON_STATE, 0, msg.SerializeToString())
                # Start a timer to hide and unregister the icon after 1 second
                threading.Timer(1.0, self.hide_and_exit, [client]).start()
            except Exception as e:
                print(f"Error showing icon: {e}")
                self.running = False
        else:
            print("Failed to register Status Icon")
            self.running = False

    def hide_and_exit(self, client):
        try:
            if self.icon_id is not None:
                # Hide
                msg = hudiy_api.ChangeStatusIconState()
                msg.id = self.icon_id
                msg.visible = False
                client.send(hudiy_api.MESSAGE_CHANGE_STATUS_ICON_STATE, 0, msg.SerializeToString())

                # Unregister
                unreg = hudiy_api.UnregisterStatusIcon()
                unreg.id = self.icon_id
                client.send(hudiy_api.MESSAGE_UNREGISTER_STATUS_ICON, 0, unreg.SerializeToString())
        except Exception as e:
            print(f"Error hiding/unregistering icon: {e}")
        finally:
            self.running = False

def main():

    # Expand ~ to get the home directory of the current user
    home_dir = os.path.expanduser('~')
    config_path = os.path.join(home_dir, 'config.json')
    
    if not os.path.exists(config_path):
        if os.path.exists('/home/pi/config.json'):
            home_dir = '/home/pi'
            config_path = os.path.join(home_dir, 'config.json')
        else:
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
    log_dir_base = log_saver.get('log_directory', os.path.join(home_dir, 'logs'))
    if log_dir_base.startswith('~/'):
        log_dir_base = os.path.join(home_dir, log_dir_base[2:])
    elif log_dir_base == '~':
        log_dir_base = home_dir
        
    log_dir = os.path.join(log_dir_base, date_str)
    
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        print(f"Error creating directory {log_dir}: {e}")
        return

    any_saved = False
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
                any_saved = True
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

    if any_saved and Client is not None:
        print("Triggering Hudiy status icon...")
        client = Client("save_logs")
        handler = SaveLogsEventHandler()
        client.set_event_handler(handler)
        try:
            client.connect('127.0.0.1', 44405)
            # Run event loop until handler says stop
            while handler.running:
                if not client.wait_for_message():
                    break
            client.disconnect()
            print("Hudiy icon triggered successfully.")
        except Exception as e:
            print(f"Failed to show Hudiy icon: {e}")


if __name__ == '__main__':
    main()
