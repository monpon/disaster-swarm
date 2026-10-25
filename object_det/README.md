# ROS 2 YOLO Object Detection Node (`object_det`)

A high-performance ROS 2 node built to process **240p RGB camera streams from libcamera** and run inference using **YOLO with `model.pt` via the Ultralytics library**, broadcasting detected object classes and bounding boxes.

Packaged as both a standard ROS 2 package and an **OCI/UCI container image targeting ARM64**, optimized for the **NVIDIA GB10 Grace Blackwell Superchip** (DGX Spark, ASUS Ascent GX10, MediaTek GB10).

---

## 1. Features & Architecture

- **240p Camera Stream Ingestion**: Subscribes to `sensor_msgs/msg/Image` (default topic `/camera/image_raw`) from `libcamera_ros`, `camera_ros`, or `v4l2_camera` with `SensorDataQoS` (Best-effort, volatile) for zero-lag live streaming.
- **Pure-NumPy Image Decoding**: Direct byte buffer conversion without binary `cv_bridge` NumPy 1.x vs 2.x ABI conflicts.
- **YOLO Disaster Response Model (`model.pt`)**:
  - `0`: `fire`
  - `1`: `smoke`
  - `2`: `person`
  - `3`: `door`
- **Multi-Format Broadcasting**:
  1. **Standard ROS 2 Vision Messages**: `vision_msgs/msg/Detection2DArray` on `/detections` (center coordinates, width/height, class ID, confidence score).
  2. **JSON Stream**: `std_msgs/msg/String` on `/detections/json` for web UI (`disaster-swarm/ui`), telemetry relays, and lightweight consumers.
  3. **Annotated Image**: `sensor_msgs/msg/Image` on `/detections/annotated_image` for RViz2 / Foxglove Studio / rqt visualization.
- **NVIDIA GB10 Blackwell Acceleration**: Full CUDA acceleration targeting Blackwell Tensor Cores (`sm_120`/`sm_121`) with automatic fallback to CPU.

---

## 2. Topic Interfaces

### Subscribed Topics
| Topic | Message Type | Description |
|---|---|---|
| `/camera/image_raw` | `sensor_msgs/msg/Image` | 240p RGB/BGR stream from libcamera node |

### Published Topics
| Topic | Message Type | Description |
|---|---|---|
| `detections` | `vision_msgs/msg/Detection2DArray` | Standard bounding boxes and detected class hypotheses |
| `detections/json` | `std_msgs/msg/String` | Structured JSON detections payload |
| `detections/annotated_image` | `sensor_msgs/msg/Image` | Camera frames with bounding boxes & class labels overlaid |

#### JSON Payload Schema (`detections/json`):
```json
{
  "timestamp": 1729780000.123,
  "frame_id": "camera_optical_frame",
  "frame_seq": 42,
  "image_width": 320,
  "image_height": 240,
  "inference_time_ms": 14.8,
  "count": 2,
  "detections": [
    {
      "id": 0,
      "class_id": 0,
      "class_name": "fire",
      "confidence": 0.912,
      "box_xyxy": [45.2, 80.0, 110.5, 160.3],
      "box_xywh": [77.85, 120.15, 65.3, 80.3],
      "box_normalized_xywh": [0.2433, 0.5006, 0.2041, 0.3346]
    }
  ]
}
```

---

## 3. Configuration Parameters

Configurable via `config/params.yaml` or launch arguments:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `camera_topic` | `string` | `/camera/image_raw` | Input camera topic from libcamera |
| `model_path` | `string` | `model.pt` | Path to YOLO model weights |
| `confidence_threshold` | `float` | `0.35` | Minimum confidence score (0.0 - 1.0) |
| `iou_threshold` | `float` | `0.45` | NMS IoU threshold |
| `imgsz` | `int` | `256` | Inference image size (multiple of 32 for 240p) |
| `device` | `string` | `""` | Compute device (`"cuda:0"`, `"cpu"`, or empty for auto) |
| `publish_detections` | `bool` | `true` | Publish `Detection2DArray` |
| `publish_json` | `bool` | `true` | Publish JSON string |
| `publish_annotated_image` | `bool` | `true` | Publish annotated image frames |
| `drop_stale_frames` | `bool` | `true` | Drop intermediate frames when inference is running |

---

## 4. Local Build & Run

### Build with Colcon
```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select object_det
source install/setup.bash
```

### Launch the Detector
```bash
# Default (subscribes to /camera/image_raw)
ros2 launch object_det detector.launch.py

# Custom topic or confidence threshold
ros2 launch object_det detector.launch.py \
    camera_topic:=/libcamera/image_raw \
---

---

## 5. Live Drone Feed Object Detection (Turbodrone)

Stream live video directly from a connected Turbodrone (e.g. WiFi_CAM drone at `192.168.4.153`, S2x, or WiFi UAV) and run local YOLO inference with real-time bounding box annotations:

```bash
# Launch live detector (opens OpenCV desktop window & starts web dashboard)
./run_live_feed.sh
```

Or directly with custom parameters:
```bash
python3 live_drone_detection.py \
    --drone-type wifi_cam \
    --drone-ip 192.168.4.153 \
    --conf 0.35 \
    --port 8088
```

### Viewing Interfaces:
1. **Desktop GUI Window**: Native OpenCV window with real-time HUD overlays, latency, FPS, and bounding boxes.
   - Keys: `q` to quit, `s` to save screenshot, `h` to toggle HUD, `+`/`-` to adjust confidence threshold live.
2. **Web Dashboard**: Open `http://localhost:8088/` in any browser for a dark-themed live monitoring dashboard.
3. **Raw MJPEG Stream**: Direct stream at `http://localhost:8088/stream` (embeddable in web apps or VLC).
4. **JSON Detections API**: Real-time telemetry and bounding boxes at `http://localhost:8088/detections`.

## 6. Live RViz2 Demo (Synthetic Hardware-Free Stream)

A complete demo suite is included that runs without physical camera hardware. It simulates a 240p RGB libcamera feed containing moving persons, doors, and animated fires/smoke:

```bash
# Launch Mock Camera + YOLOv26 Detector + RViz2 GUI in one command
./run_rviz_demo.sh
```

Or manually via ROS 2 launch:
```bash
ros2 launch object_det demo.launch.py rviz:=true
```

### RViz2 Displays Included in `config/demo.rviz`:
- **Raw 240p Camera View**: Direct feed from `/camera/image_raw`.
- **YOLO Detections (Annotated)**: Real-time bounding boxes with detected class names and confidence percentages from `/detections/annotated_image`.
- **TF Coordinate Frame**: Synchronized `camera_optical_frame` relative to `map`.

---

## 7. ARM64 Emulated Demo (Simulating NVIDIA GB10 on x86)

You can test the exact ARM64 container on your x86 workstation via QEMU user emulation:

```bash
# Runs the ARM64 container under QEMU emulation while launching host RViz2 to visualize
./run_arm64_demo.sh
```

---

## 8. ARM64 OCI/UCI Container for NVIDIA GB10 Superchip
# Using Docker Buildx
docker buildx build --platform linux/arm64 -f Dockerfile -t object-det:gb10-arm64 --load .
```

### Run on NVIDIA GB10 Superchip
Run with full GPU acceleration, host networking (for ROS 2 DDS communication), and device access:
```bash
./run_container.sh object-det:gb10-arm64 /camera/image_raw 0.35
```

Or run via `podman`/`docker` CLI directly:
```bash
podman run --rm -it \
    --net=host \
    --ipc=host \
    --device nvidia.com/gpu=all \
    --security-opt label=disable \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    object-det:gb10-arm64 \
    ros2 launch object_det detector.launch.py camera_topic:=/camera/image_raw
```

---

## 9. Pairing with a Libcamera Node

To stream 240p RGB from a Raspberry Pi camera or CSI/USB camera via `camera_ros` (libcamera driver):
```bash
ros2 run camera_ros camera_node --ros-args \
    -p width:=320 \
    -p height:=240 \
    -p format:="RGB888" \
    -r /camera/image_raw:=/camera/image_raw
```
The detector node will instantly ingest the 240p frames and publish the detected classes and bounding boxes.
