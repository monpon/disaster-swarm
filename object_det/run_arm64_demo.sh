#!/usr/bin/env bash
# ==============================================================================
# ARM64 Emulated Demo: Run ARM64 Container with Host RViz2
# Architecture: linux/arm64 (aarch64 via QEMU user emulation)
# Simulates the NVIDIA GB10 Grace Blackwell onboard drone node
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${1:-object-det:gb10-arm64}"

echo "=========================================================="
echo " Starting ARM64 Emulated Demo for NVIDIA GB10 Superchip"
echo " Target Architecture: linux/arm64 (aarch64 via QEMU)"
echo " Image:               ${IMAGE_NAME}"
echo "=========================================================="

# 1. Build ARM64 container if not present
if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    echo "[+] Building ARM64 container image under emulation..."
    "${SCRIPT_DIR}/build_container.sh" "${IMAGE_NAME}"
fi

# 2. Launch ARM64 container running detector node and mock camera
echo "[+] Starting ARM64 container on host DDS network (domain 0)..."
podman run --rm -it \
    --arch arm64 \
    --net=host \
    --ipc=host \
    -v "${SCRIPT_DIR}/config:/ros2_ws/src/object_det/config:ro" \
    "${IMAGE_NAME}" \
    ros2 launch object_det demo.launch.py rviz:=false &

CONTAINER_PID=$!
trap "kill ${CONTAINER_PID} 2>/dev/null || true" EXIT

echo "[+] Waiting for ARM64 node to publish detections..."
sleep 4

echo "[+] Launching RViz2 ground station on host to visualize ARM64 stream..."
if command -v rviz2 &>/dev/null; then
    rviz2 -d "${SCRIPT_DIR}/config/demo.rviz"
else
    distrobox enter ros2 -- bash -c "
        source /opt/ros/jazzy/setup.bash
        rviz2 -d '${SCRIPT_DIR}/config/demo.rviz'
    "
fi

wait "${CONTAINER_PID}"
