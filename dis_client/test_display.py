import sys
sys.path.append('.')
from dis_display import DisplayEngine
import threading
import time
import zmq
import json

engine = DisplayEngine(config_path='../config.json', mock=True)
engine.nav_active = True
engine.switch_to_app('app_nav')

t = threading.Thread(target=engine.run)
t.daemon = True
t.start()

# We can't bind 5559 if the emulator is running on Windows.
# BUT we don't need to if we just inject exactly the same call directly.
time.sleep(1) # wait for engine to start

topic = b'HUDIY_NAV'
data = {'maneuver_type': 1, 'distance': '500 m', 'description': 'Main St'}

# Inject exactly how the while True loop does:
engine.current_app.update_hudiy(topic, data)

print("NAV VIEW Output:", engine.apps['app_nav'].get_view())
print("Description:", engine.apps['app_nav'].description)
print("Distance Label:", engine.apps['app_nav'].distance_label)
