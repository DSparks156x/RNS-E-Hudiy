# Drive Model Outputs & Visualization Reference

This document provides a comprehensive catalog of all outputs produced by the `pingupilot` / `sunnypilot` drive and vision models (specifically `ModelDataV2`). It details the structure, shapes, reference frames, and visualization strategies for these outputs, which can be extracted from route logs (`rlog.zst`) and used for web interfaces, plotting, or debugging.

---

## 1. Reference Frames & Coordinate Systems

To visualize model outputs accurately, you must align them with the correct spatial coordinate system and temporal/spatial indexing.

### Coordinate System (Device Frame)
The model outputs coordinates in the **Device Frame** (standard ISO vehicle coordinates):
*   **X-axis**: Forward (positive forward)
*   **Y-axis**: Lateral / Left (positive left, negative right)
*   **Z-axis**: Vertical / Up (positive up, negative down)

### Indexing Functions
Unlike linear grids, the model predicts points along quadratic curves for both time and distance:

#### A. Temporal Grid (`T_IDXS` / `T_IDXS_V2`)
Used for planning trajectories (like `plan` and `planplus`) and disengagement timelines.
*   **Length**: 33 points
*   **Span**: 0 to 10 seconds into the future
*   **Formula**:
    $$\text{time}(idx) = 10.0 \times \left(\frac{idx}{32}\right)^2$$
*   **Indices**: `[0.0, 0.0098, 0.039, ..., 8.789, 9.385, 10.0]`

#### B. Spatial Distance Grid (`X_IDXS`)
Used for lane lines and road edges.
*   **Length**: 33 points
*   **Span**: 0 to 192 meters ahead of the camera
*   **Formula**:
    $$\text{distance}(idx) = 192.0 \times \left(\frac{idx}{32}\right)^2$$
*   **Indices**: `[0.0, 0.1875, 0.75, ..., 168.75, 180.18, 192.0]`

---

## 2. Catalog of Model Outputs

These fields are defined in the Cap'n Proto schema (`cereal/log.capnp` -> `ModelDataV2`) and parsed by `selfdrive/modeld/parse_model_outputs.py` (or the split model equivalent in `sunnypilot/modeld_v2/parse_model_outputs_split.py`).

Many outputs are parameterized as **Mixture Density Networks (MDNs)**, yielding both a predicted mean ($\mu$) and an uncertainty standard deviation ($\sigma$).

### A. Trajectories & Paths

#### 1. `plan` (Primary Path)
*   **Shape**: `(33, 15)`
*   **Uncertainty/Std**: `plan_stds` shape `(33, 15)`
*   **Description**: The planned 3D trajectory and dynamics of the vehicle over the next 10 seconds (aligned with `T_IDXS`).
*   **15 Channels Slice Mapping**:
    *   `POSITION` `[0:3]`: $x, y, z$ coordinates (meters)
    *   `VELOCITY` `[3:6]`: $v_x, v_y, v_z$ velocities (m/s)
    *   `ACCELERATION` `[6:9]`: $a_x, a_y, a_z$ accelerations (m/s²)
    *   `T_FROM_CURRENT_EULER` `[9:12]`: predicted orientation Euler angles (roll, pitch, yaw) (radians)
    *   `ORIENTATION_RATE` `[12:15]`: predicted rotation rates (roll rate, pitch rate, yaw rate) (rad/s)

#### 2. `planplus` (Lane Centering Recovery Path)
*   **Shape**: `(33, 15)`
*   **Description**: A supplementary trajectory predicted by some drive models in `pingupilot` / `sunnypilot`. It represents the corrective delta required to stabilize lane centering and recover aggressively from offsets.
*   **Integration**:
    *   The active control path is blended using the parameter `PlanplusControl`:
        $$\text{Blended curvature} = \text{plan} + (\text{PlanplusControl} - 1.0) \times \text{planplus}$$
    *   Alternatively, in the Tinygrad runner, they are added directly:
        $$\text{Outputs} = \text{plan} + \text{planplus}$$

---

### B. Lane Lines & Road Edges

#### 1. `laneLines`
*   **Shape**: `(4, 33, 2)`
*   **Uncertainty/Std**: `laneLineStds` shape `(4, 33, 2)` (variance of lateral offset $y$ and vertical offset $z$)
*   **Description**: Coordinates of the detected lanes ahead, evaluated at the 33 distance coordinates of `X_IDXS`.
*   **The 4 Lines**:
    *   `0`: Left-left (outer left lane line)
    *   `1`: Left (adjacent left lane line)
    *   `2`: Right (adjacent right lane line)
    *   `3`: Right-right (outer right lane line)
*   **2 Channels**:
    *   `0`: lateral offset $y$ (meters)
    *   `1`: vertical height $z$ (meters)

#### 2. `laneLineProbs`
*   **Shape**: `(4,)`
*   **Description**: Softmax/sigmoid confidence probabilities `[0.0, 1.0]` of the existence of each of the 4 lane lines.

#### 3. `roadEdges`
*   **Shape**: `(2, 33, 2)`
*   **Uncertainty/Std**: `roadEdgeStds` shape `(2, 33, 2)`
*   **Description**: Spatial boundary lines of the drivable road edges evaluated at `X_IDXS`.
    *   `0`: Left road edge
    *   `1`: Right road edge
*   **2 Channels**: Lateral offset $y$ and vertical height $z$.

---

### C. Lead Vehicle Detections

#### 1. `leadsV3` (Lead Targets)
*   **Shape**: List of `LeadDataV3` structs (typically contains up to 3 lead hypotheses).
*   **Description**: Trajectories of potential lead vehicles ahead of the car.
*   **Fields**:
    *   `prob`: Probability `[0.0, 1.0]` that this vehicle is the active lead at the current time.
    *   `probTime`: Temporal confidence of tracking.
    *   `t`: List of prediction times `[0.0, 2.0, 4.0, 6.0, 8.0, 10.0]` (Lead time indices).
    *   `x` / `xStd`: Longitudinal distance (m) and standard deviation.
    *   `y` / `yStd`: Lateral offset (m) and standard deviation.
    *   `v` / `vStd`: Absolute velocity of lead vehicle (m/s) and standard deviation.
    *   `a` / `aStd`: Absolute acceleration (m/s²) and standard deviation.

#### 2. `lead_prob`
*   **Shape**: `(3,)`
*   **Description**: Sigmoid probabilities indicating the likelihood of lead vehicles existing in the 3 tracking zones.

---

### D. Vehicle Pose & Camera Calibration

#### 1. `pose`
*   **Shape**: `(6,)`
*   **Uncertainty/Std**: `pose_stds` shape `(6,)`
*   **Description**: The instantaneous movement translation and rotation rates of the camera/vehicle.
    *   `[0:3]`: $v_x, v_y, v_z$ translation rates (m/s)
    *   `[3:6]`: roll, pitch, yaw rotation rates (rad/s)

#### 2. `wide_from_device_euler` (Euler Angles Calibration)
*   **Shape**: `(3,)`
*   **Description**: Pitch, roll, and yaw offset angles (radians) representing the transform from the wide-angle camera sensor frame to the physical vehicle device frame.

#### 3. `road_transform`
*   **Shape**: `(6,)`
*   **Description**: Transform parameters aligning the device pose with the estimated road plane.

---

### E. Driver Intention & State Predictions

#### 1. `desire_pred`
*   **Shape**: `(4, 8)`
*   **Description**: Predicted softmax probabilities for driver desires over a future timeline (at 2, 4, 6, and 8 seconds).
*   **Indices mapping to `Desire` enums**:
    *   `0`: None
    *   `1`: Turn Left (90° cornering)
    *   `2`: Turn Right (90° cornering)
    *   `3`: Lane Change Left
    *   `4`: Lane Change Right
    *   `5`: Keep Left
    *   `6`: Keep Right
    *   `7`: (Reserved / Padding)

#### 2. `desire_state`
*   **Shape**: `(8,)`
*   **Description**: Softmax classification vector of the vehicle's immediate operational desire state.

#### 3. `meta` (Disengagement Predictions)
*   **Shape**: Contains probabilities of driver behaviors and override metrics mapped across temporal intervals.
*   **Mappings (`Meta` class indices)**:
    *   `engagedProb` (`[0:1]`): Probability that autopilot is/should be engaged.
    *   `GAS_DISENGAGE` (`[1:31:6]`): Likelihood of disengagement due to gas pedal over next 2s, 4s, 6s, 8s, 10s.
    *   `BRAKE_DISENGAGE` (`[2:31:6]`): Likelihood of disengagement due to brake pedal.
    *   `STEER_OVERRIDE` (`[3:31:6]`): Likelihood of steering wheel override.
    *   `HARD_BRAKE_3` / `HARD_BRAKE_4` / `HARD_BRAKE_5`: Probability of decelerating harder than $3, 4, \text{or } 5 \text{ m/s}^2$ over the timeline.
    *   `GAS_PRESS` / `BRAKE_PRESS` / `LEFT_BLINKER` / `RIGHT_BLINKER`: Probabilities of basic driver actions over next 0s, 2s, 4s, 6s, 8s, 10s.

---

### F. High-Level Action Directives

These fields reflect the End-to-End (E2E) lateral planner's decisions before sending commands to the actuators:
*   `action.desiredCurvature`: Instantly requested path curvature ($1/\text{radius}$, units $1/\text{m}$).
*   `action.desiredAcceleration`: Target longitudinal acceleration (m/s²).
*   `action.shouldStop`: Boolean flag indicating a predicted stop (e.g. traffic light, stop sign, or lead car).
*   `confidence`: Evaluated classification scale (`green`, `yellow`, `red`) indicating model performance capability.

---

## 3. Visualization Guide

When building dashboards, charts, or overlays, you can map these raw numeric arrays into rich visual elements.

### A. Bird's-Eye View (BEV) Path Mapping
To render the planned path (`plan`), lane lines, and road edges relative to the vehicle on a 2D canvas:
1.  **Extract coordinates**:
    *   For the **Plan**: Use $x = \text{POSITION}[0]$, $y = \text{POSITION}[1]$.
    *   For the **Lane Lines / Edges**: For each point index $i \in [0..32]$, look up the preset forward distance $x = X\_IDXS[i]$. Then extract the lateral offset $y$ from the output matrix.
2.  **Scale and Rotate**: Convert the metric $(x, y)$ coordinate pairs to screen space pixels.
3.  **Color Codes**:
    *   *Plan Path*: Sleek Cyan (`#00f0ff`) or Green (`#00ff7f`).
    *   *Adjacent Lane Lines*: Clean White (`#ffffff`) or Yellow (`#ffd700`).
    *   *Outer Lane Lines / Road Edges*: Muted Grey (`#888888`) or Red (`#ff4d4d`).

```
                [Road Edge Left (Red)]
           \             |             /
            \            |            /
             \   [Lane Line Left]    /
              \    |     |     |    /
               \   |     *     |   /
                \  |    *      |  /
                 \ |   *       | /
                  \|  *        |/
                   | * [Plan]  |
                  [Your Vehicle]
```

### B. Uncertainty Envelopes (Std Dev)
Plotting the standard deviations helps visualize how confident the model is about lane boundaries or its future path (e.g., in low visibility, rain, or sharp turns):
*   For any coordinate point $y_i$ with standard deviation $\sigma_i$:
    *   Upper boundary: $y_{\text{upper}} = y_i + 2\sigma_i$
    *   Lower boundary: $y_{\text{lower}} = y_i - 2\sigma_i$
*   Fill the polygon between $y_{\text{upper}}$ and $y_{\text{lower}}$ with a semi-transparent gradient (alpha `0.1` - `0.2`) to represent the confidence funnel.

### C. Timeline/Heatmap Charts (Meta Predictions)
Create timeline bars or heatmaps representing **Disengagement Probabilities**:
*   X-axis: Timestamps `[2s, 4s, 6s, 8s, 10s]`
*   Y-axis: Event channels (`Steer Override`, `Brake Disengage`, `Gas Disengage`)
*   Map the probability value to a color gradient (e.g., green to red). This alerts developers or drivers where the model expects an upcoming manual takeover.

### D. Desire Timelines
Overlay future desire paths as icons or directional arrows:
*   Read `desire_pred` for $t = [2\text{s}, 4\text{s}, 6\text{s}, 8\text{s}]$.
*   If a category (e.g., `laneChangeLeft`) exceeds a confidence threshold (like $0.5$), highlight a blinking left arrow or lane overlay on the UI corresponding to that timeframe.
