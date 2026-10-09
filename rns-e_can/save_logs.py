#!/usr/bin/env python3
# save_logs.py
# Saves recent service journals and snapshots of the raw Hudiy API capture.

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
    ClientEventHandler = object


API_CAPTURE_PATH = '~/logs/hudiy-api/hudiy-api-events.log'


def save_api_captures(log_dir, index=1):
    """Snapshot complete JSON-lines events without modifying the live capture."""
    path = os.path.abspath(os.path.expanduser(API_CAPTURE_PATH))
    stem, extension = os.path.splitext(path)
    saved = []
    for source in (stem + '-previous' + (extension or '.log'), path):
        try:
            with open(source, 'rb') as handle:
                # Fix the endpoint at open time. A simultaneous append/rotation
                # cannot make this snapshot grow indefinitely or mix files.
                data = handle.read(os.fstat(handle.fileno()).st_size)
            data = data[:data.rfind(b'\n') + 1]
            if not data:
                continue
            basename = os.path.splitext(os.path.basename(source))[0]
            file_index = index
            while True:
                destination = os.path.join(log_dir, f'{basename}_{file_index}.log')
                try:
                    with open(destination, 'xb') as output:
                        output.write(data)
                    break
                except FileExistsError:
                    file_index += 1
            saved.append(destination)
            print(f'Saved raw Hudiy API capture to {destination}')
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f'Could not snapshot raw Hudiy API capture {source}: {exc}')
    if not saved:
        print(f'No raw Hudiy API capture found at {path}; service journals do not contain raw API fields.')
    return saved

class SaveLogsEventHandler(ClientEventHandler):
    def __init__(self, date_str, index):
        super().__init__()
        self.date_str = date_str
        self.index = index
        self.toast_channel_id = None
        self.running = True

    def on_hello_response(self, client, message):
        try:
            # Register toast channel instead of status icon
            req = hudiy_api.RegisterToastChannelRequest()
            req.name = "Log Saver"
            req.description = "Notifications for saved logs"
            client.send(hudiy_api.MESSAGE_REGISTER_TOAST_CHANNEL_REQUEST, 0, req.SerializeToString())
        except Exception as e:
            print(f"Error registering toast channel: {e}")
            self.running = False

    def on_register_toast_channel_response(self, client, message):
        if message.result == hudiy_api.RegisterToastChannelResponse.REGISTER_TOAST_CHANNEL_RESULT_OK:
            self.toast_channel_id = message.id
            try:
                # Show toast with date and increment
                msg = hudiy_api.ShowToast()
                msg.channel_id = self.toast_channel_id
                msg.message = f"Logs saved: {self.date_str} #{self.index}"
                msg.icon_name = "save"
                msg.icon_font_family = "Material Symbols Rounded"
                client.send(hudiy_api.MESSAGE_SHOW_TOAST, 0, msg.SerializeToString())
                
                # Start a timer to unregister the channel and exit after 3 seconds (gives time for toast to be sent)
                threading.Timer(5.0, self.unregister_and_exit, [client]).start()
            except Exception as e:
                print(f"Error showing toast: {e}")
                self.running = False
        else:
            print("Failed to register Toast Channel")
            self.running = False

    def unregister_and_exit(self, client):
        try:
            if self.toast_channel_id is not None:
                unreg = hudiy_api.UnregisterToastChannel()
                unreg.id = self.toast_channel_id
                client.send(hudiy_api.MESSAGE_UNREGISTER_TOAST_CHANNEL, 0, unreg.SerializeToString())
        except Exception as e:
            print(f"Error unregistering toast channel: {e}")
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
        
    date_dir = os.path.join(log_dir_base, date_str)
    
    try:
        os.makedirs(date_dir, exist_ok=True)
        # Reserve one folder for the entire button press. Atomic mkdir prevents
        # simultaneous saves from mixing journals and API captures together.
        index = 1
        while True:
            log_dir = os.path.join(date_dir, str(index))
            try:
                os.mkdir(log_dir)
                break
            except FileExistsError:
                index += 1
    except Exception as e:
        print(f"Error creating saved-log directory under {date_dir}: {e}")
        return

    any_saved = False
    for service in services:
        service_clean = service.replace('.service', '')
        log_file = os.path.join(log_dir, f"{service_clean}_{index}.log")

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
                        f.write(f"--- No logs found for {service} in the last {minutes} minutes ---")
                print(f"Saved {service} logs to {log_file}")
            else:
                print(f"Error running journalctl for {service}: {result.stderr}")
        except Exception as e:
            print(f"Failed to collect logs for {service}: {e}")

    any_saved = bool(save_api_captures(log_dir, index)) or any_saved
    if any_saved and Client is not None:
        print("Triggering Hudiy status icon...")
        client = Client("save_logs")
        handler = SaveLogsEventHandler(date_str, index)
        client.set_event_handler(handler)
        try:
            client.connect('127.0.0.1', 44405)
            # Run event loop until handler says stop
            while handler.running:
                if not client.wait_for_message():
                    break
            client.disconnect()
            print("Hudiy notification triggered successfully.")
        except Exception as e:
            print(f"Failed to show Hudiy notification: {e}")


if __name__ == '__main__':
    main()
