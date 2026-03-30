# TP2 Worker ZMQ API Documentation

## 1. Overview
The TP2 Worker (`tp2_worker.py`) exposes a ZeroMQ (ZMQ) based API to interact with the VAG TP2.0 protocol over a CAN bus interface. It manages connections to multiple automotive modules, polls diagnostic data groups, reads/clears Diagnostic Trouble Codes (DTCs), and broadcasts the results.

### Architecture
The service utilizes three primary ZMQ sockets:
- **Command Request/Reply (REP)**: Used by clients to send commands (e.g., sync groups, request DTCs) and receive immediate acknowledgments or status information.
- **Data Publish (PUB)**: Broadcasts polled diagnostic data, DTC reports, and service status updates to any interested subscribers.
- **System Events Subscribe (SUB)**: Listens for external system events (like ignition status) to automatically enable or disable the service.

### Default IPC Addresses
- **Command (REP)**: `ipc:///run/rnse_control/tp2_cmd.ipc`
- **Publish (PUB)**: `ipc:///run/rnse_control/tp2_stream.ipc`
- **System Events (SUB)**: `ipc:///run/rnse_control/base_events.ipc`

*Note: These paths can be overridden via `config.json`.*

---

## 2. Authentication
ZeroMQ operates at the transport layer and does not utilize standard HTTP authentication (like Bearer tokens or API keys). Access control is typically managed at the OS level by restricting read/write permissions to the `.ipc` socket files in `/run/rnse_control/`.

**Security Considerations:**
- Ensure that the user running the client applications belongs to the group that has read/write permissions for the `/run/rnse_control/` directory.

---

## 3. Command API (REQ/REP)

Clients must use a `ZMQ.REQ` socket to connect to the command address (`ipc:///run/rnse_control/tp2_cmd.ipc`). All requests and responses are standard JSON payloads.

### Get Service Status
**Command**: `STATUS`
**Description**: Retrieves the current status of the TP2 service, including all active module sessions, connected states, and error counts.

**Request Body**:
```json
{
  "cmd": "STATUS"
}
```

**Response**:
```json
{
  "status": "ok",
  "enabled": true,
  "session_count": 1,
  "sessions": [
    {
      "module": 1,
      "connected": true,
      "active": true,
      "client_subs": {},
      "normal_groups_list": [1, 2],
      "low_groups_list": [3],
      "error_count": 0,
      "last_activity": 1678888888.0,
      "group_errors": {},
      "group_cooldowns": {}
    }
  ]
}
```

### Sync Measurement Groups
**Command**: `SYNC`
**Description**: Registers a client's interest in specific measuring blocks (groups) for a specific module. The worker aggregates all client interests and automatically polls these groups. "Normal" groups are polled frequently, as fast as possible; "Low Priority" groups are polled periodically, once every minute.

**Request Body**:
```json
{
  "cmd": "SYNC",
  "client_id": "app_dashboard",
  "module": 1,
  "groups": [1, 3],
  "low_priority_groups": [11, 15]
}
```
*Note: Clients must send a `SYNC` command every < 15 seconds to keep their subscription active. If a client stops sending SYNC, their requested groups are dropped.*

**Response**:
```json
{
  "status": "ok",
  "message": "Synced",
  "active_groups": [1, 3]
}
```

### Request DTCs
**Command**: `READ_DTC`
**Description**: Queues a request to read Diagnostic Trouble Codes (DTCs) from a specific module. The actual DTC data will be published asynchronously over the PUB socket.

**Request Body**:
```json
{
  "cmd": "READ_DTC",
  "module": 1
}
```

**Response**:
```json
{
  "status": "queued",
  "module": 1
}
```

### Clear DTCs
**Command**: `CLEAR_DTC`
**Description**: Queues a request to clear all Diagnostic Trouble Codes from a specific module. Note that clearing DTCs will automatically trigger a subsequent `READ_DTC` to verify they have been cleared.

**Request Body**:
```json
{
  "cmd": "CLEAR_DTC",
  "module": 1
}
```

**Response**:
```json
{
  "status": "queued",
  "module": 1,
  "action": "clear"
}
```

### Clear All Sessions
**Command**: `CLEAR`
**Description**: Marks all active module sessions as inactive. The worker will disconnect from the modules and release the tester IDs.

**Request Body**:
```json
{
  "cmd": "CLEAR"
}
```

**Response**:
```json
{
  "status": "ok",
  "message": "Cleared all"
}
```

### Toggle Service State
**Command**: `TOGGLE`
**Description**: Manually toggles the service between Enabled and Disabled states. Note: This state might be overwritten by Ignition power state changes if the system events monitor is active.

**Request Body**:
```json
{
  "cmd": "TOGGLE"
}
```

**Response**:
```json
{
  "status": "ok",
  "message": "Service Disabled",
  "enabled": false
}
```

**Common Error Response (For all endpoints)**:
```json
{
  "status": "error",
  "message": "Missing module"
}
```

---

## 4. Publish Streams (PUB/SUB)

Clients must use a `ZMQ.SUB` socket connected to the publish address (`ipc:///run/rnse_control/tp2_stream.ipc`). The payloads are multipart messages consisting of `[TOPIC (Bytes), JSON_PAYLOAD (Bytes)]`.

### Topic: `HUDIY_TP2_STATUS`
**Description**: Broadcasts changes to the service's enabled/disabled status (usually triggered by ignition state changes or toggles).
**Payload**:
```json
{
  "enabled": true
}
```

### Topic: `HUDIY_DIAG`
**Description**: Broadcasts diagnostic data (measuring block values) and DTC reports retrieved from modules.

**Payload Variant 1: Measuring Block Data**
```json
{
  "module": 1,
  "group": 3,
  "data": [
    {
      "value": 850.0,
      "unit": "RPM",
      "type": 1
    },
    ...
  ]
}
```


**Payload Variant 2: DTC Report (Success)**
```json
{
  "module": 1,
  "type": "dtc_report",
  "count": 1,
  "dtcs": [
    {
      "code": "0134",
      "code_dec": "00308",
      "status": 35,
      "status_decoded": "Static",
      "freeze_frame_raw": ["12", "00", "04", "01", "34"],
      "freeze_frame": "Decoded freeze frame data string"
    }
  ]
}
```

**Payload Variant 3: DTC Report (Error)**
```json
{
  "module": 1,
  "type": "dtc_report",
  "dtcs": [],
  "error": "Error reading DTCs: Request Rejected (NRC 22)"
}
```

---

## 5. Event Inputs (SUB)

The service monitors external system events to control its lifecycle automatically.

### Topic: `POWER_STATUS`
**Address**: `ipc:///run/rnse_control/base_events.ipc`
**Description**: If `kl15` (Ignition) transitions to `false`, the TP2 service gracefully disconnects from all modules and pauses polling. When `kl15` becomes `true`, polling resumes.
**Expected Payload**:
```json
{
  "kl15": true
}
```

---

## 6. Data Models

### DTC Status Object
```typescript
interface DTC {
  code: string;           // Pure hex format of the code (e.g., "0134")
  code_dec: string;       // 5-digit decimal VAG format (e.g., "00308")
  status: number;         // Raw status byte
  status_decoded: string; // Human-readable status (e.g., "Intermittent", "Static")
  freeze_frame_raw?: string[]; // Optional: Array of hex bytes representing freeze frame
  freeze_frame?: string;       // Optional: Decoded freeze frame string
}
```

### Measuring Block Data Object
```typescript
interface MeasuringBlockData {
  value: number | string;
  unit: string;
  type: number;           // Formula type (e.g., 1=RPM, 5=Temp)
}
```

---

## 7. Error Handling

- **Command Errors**: Return a JSON response with `"status": "error"` and a `"message"` detailing the issue (e.g., "Missing module").
- **CAN/Protocol Errors**: When a module rejects a read or clear command (NRC codes), or times out, the service will attempt automatic fallbacks (for DTCs) or retry.
- **Group Cooldowns**: If a specific measuring block fails to read 3 times in a row, the worker will place that specific group on a 30-second cooldown to prevent spamming the CAN bus with failing requests.
- **Module Disconnections**: If 10 consecutive errors occur on a single module, the worker forces a disconnect and will attempt a clean reconnect on the next cycle.

---

## 8. Code Examples

### Python: Requesting Data & Subscribing to Stream
```python
import zmq
import json
import time
import threading

def subscribe_stream():
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect("ipc:///run/rnse_control/tp2_stream.ipc")
    
    # Subscribe to diagnostic data
    sub.subscribe(b"HUDIY_DIAG")
    
    print("Listening for diagnostic data...")
    while True:
        topic, payload = sub.recv_multipart()
        data = json.loads(payload.decode('utf-8'))
        print(f"Received from {topic.decode()}: {json.dumps(data, indent=2)}")

# Start subscriber thread
t = threading.Thread(target=subscribe_stream, daemon=True)
t.start()

# Sync groups via REQ socket
context = zmq.Context()
req = context.socket(zmq.REQ)
req.connect("ipc:///run/rnse_control/tp2_cmd.ipc")

# Keep syncing every 5 seconds to maintain the subscription
while True:
    request_data = {
        "cmd": "SYNC",
        "client_id": "python_example_client",
        "module": 1,        # 0x01 (Engine)
        "groups": [1, 2],   # Normal priority groups
        "low_priority_groups": [115] # Low priority groups
    }
    
    req.send_json(request_data)
    response = req.recv_json()
    print(f"Sync response: {response}")
    
    time.sleep(5)
```

### Node.js: Reading DTCs
```javascript
const zmq = require('zeromq');

async function run() {
  const req = new zmq.Request();
  req.connect('ipc:///run/rnse_control/tp2_cmd.ipc');

  console.log("Requesting DTCs for Module 0x01...");
  
  const payload = {
    cmd: "READ_DTC",
    module: 1
  };
  
  await req.send(JSON.stringify(payload));
  const [response] = await req.receive();
  
  console.log("Response:", JSON.parse(response.toString()));
  
  // Note: Actual DTC data will arrive on the PUB socket under HUDIY_DIAG
}

run();
```

---

## 9. Rate Limiting / Constraints

- **Maximum Concurrent Modules**: The service restricts the maximum number of simultaneous module connections to 10 (Tester IDs pool: `0x300` to `0x309`). Attempting to connect to an 11th module simultaneously will raise an internal error.
- **Subscription Expiry**: A client must send a `SYNC` command for its desired measuring blocks at least once every **15 seconds**. Failure to do so will result in the worker dropping the requested groups from its polling cycle to conserve CAN bandwidth.
- **Polling Throttling**: The core loop sleeps for `0.01s` between operations, though the underlying TP2 protocol enforces strict timing parameters (T1, T3) that inherently rate-limit CAN bus interactions.
