#!/usr/bin/env bash
# ==============================================================================
# Demo Launcher: Mock 240p Libcamera + YOLOv26 Detector + RViz2
# Runs locally in the ROS 2 Jazzy environment
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo " Launching ROS 2 YOLOv26 RViz2 Demo"
echo " 1. Mock Libcamera Node: streaming 240p RGB (320x240)"
echo " 2. YOLO Detector Node:  running model.pt"
echo " 3. RViz2:               visualizing camera & detections"
echo "=========================================================="

# Use distrobox ros2 container if on host without rclpy
if ! command -v ros2 &>/dev/null; then
    echo "[+] Entering ROS 2 Jazzy distrobox environment..."
    exec distrobox enter ros2 -- bash -c "
        export PATH=/usr/local/bin:/usr/bin:/bin:\$PATH
        source /opt/ros/jazzy/setup.bash
        cd '${SCRIPT_DIR}'
        if [ ! -d 'install' ]; then
            colcon build --packages-select object_det
        fi
        source install/setup.bash
        ros2 launch object_det demo.launch.py rviz:=true
    "
else
    source /opt/ros/jazzy/setup.bash
    cd "${SCRIPT_DIR}"
    if [ ! -d "install" ]; then
        colcon build --packages-select object_det
    fi
    source install/setup.bash
    exec ros2 launch object_det demo.launch.py rviz:=true
fi
