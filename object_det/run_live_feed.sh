#!/usr/bin/env bash
# Launch Live Drone YOLOv26m Object Detection Feed
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Auto-detect drone IP and default settings if not provided
DRONE_TYPE="${DRONE_TYPE:-wifi_cam}"
DRONE_IP="${DRONE_IP:-192.168.4.153}"
CONTROL_PORT="${CONTROL_PORT:-8090}"
VIDEO_PORT="${VIDEO_PORT:-8080}"
WEB_PORT="${WEB_PORT:-8088}"

echo "=========================================================="
echo " Starting Live YOLO Object Detection on Drone Stream"
echo " Drone Type:   $DRONE_TYPE"
echo " Drone IP:     $DRONE_IP (video: $VIDEO_PORT, ctrl: $CONTROL_PORT)"
echo " Web Viewer:   http://localhost:$WEB_PORT/"
echo " Stream URL:   http://localhost:$WEB_PORT/stream"
echo "=========================================================="

exec python3 "$SCRIPT_DIR/live_drone_detection.py" \
    --drone-type "$DRONE_TYPE" \
    --drone-ip "$DRONE_IP" \
    --control-port "$CONTROL_PORT" \
    --video-port "$VIDEO_PORT" \
    --port "$WEB_PORT" \
    "$@"
