#!/usr/bin/env bash
# ==============================================================================
# Run script for OCI/UCI container on NVIDIA GB10 Grace Blackwell Superchip
# Supports NVIDIA Container Toolkit / CDI / Podman / Docker
# ==============================================================================

set -euo pipefail

IMAGE_NAME="${1:-object-det:gb10-arm64}"
CAMERA_TOPIC="${2:-/camera/image_raw}"
CONF_THRES="${3:-0.35}"

echo "=========================================================="
echo " Running ROS 2 YOLO Node on NVIDIA GB10 Superchip"
echo " Image:        ${IMAGE_NAME}"
echo " Camera Topic: ${CAMERA_TOPIC}"
echo " Confidence:   ${CONF_THRES}"
echo "=========================================================="

GPU_FLAGS=()

# Detect container runtime & GPU flags
if command -v podman &>/dev/null; then
    CONTAINER_BIN="podman"
    # GB10 / CDI or standard device flag
    if [ -f "/etc/cdi/nvidia.yaml" ] || [ -d "/var/run/cdi" ]; then
        GPU_FLAGS+=(--device nvidia.com/gpu=all --security-opt label=disable)
    else
        GPU_FLAGS+=(--device /dev/nvidia0:/dev/nvidia0 --device /dev/nvidiactl:/dev/nvidiactl --device /dev/nvidia-modeset:/dev/nvidia-modeset 2>/dev/null || true)
    fi
elif command -v docker &>/dev/null; then
    CONTAINER_BIN="docker"
    GPU_FLAGS+=(--gpus all)
else
    echo "[-] Error: Neither podman nor docker found." >&2
    exit 1
fi

# Add camera devices if available on host
DEV_FLAGS=()
for dev in /dev/video* /dev/media* /dev/dma_heap; do
    if [ -e "$dev" ]; then
        DEV_FLAGS+=(--device "$dev:$dev")
    fi
done

# Run container with host network and IPC for real-time ROS 2 DDS streaming
echo "[+] Launching container with ${CONTAINER_BIN}..."
exec "${CONTAINER_BIN}" run --rm -it \
    --net=host \
    --ipc=host \
    "${GPU_FLAGS[@]}" \
    "${DEV_FLAGS[@]}" \
    -e NVIDIA_VISIBLE_DEVICES=all \
    -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    "${IMAGE_NAME}" \
    ros2 launch object_det detector.launch.py \
        camera_topic:="${CAMERA_TOPIC}" \
        confidence_threshold:="${CONF_THRES}"
