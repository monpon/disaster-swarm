#!/usr/bin/env bash
# ==============================================================================
# Build script for OCI/UCI container targeted at NVIDIA GB10 Grace Blackwell (ARM64)
# ==============================================================================

set -euo pipefail

IMAGE_NAME="${1:-object-det:gb10-arm64}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo " Building OCI Container for NVIDIA GB10 Superchip (ARM64)"
echo " Image tag: ${IMAGE_NAME}"
echo " Source:    ${SCRIPT_DIR}"
echo "=========================================================="

if command -v podman &>/dev/null; then
    echo "[+] Using podman build..."
    podman build \
        --platform linux/arm64 \
        --file "${SCRIPT_DIR}/Dockerfile" \
        --tag "${IMAGE_NAME}" \
        "${SCRIPT_DIR}"
elif command -v docker &>/dev/null; then
    echo "[+] Using docker buildx..."
    docker buildx build \
        --platform linux/arm64 \
        --file "${SCRIPT_DIR}/Dockerfile" \
        --tag "${IMAGE_NAME}" \
        --load \
        "${SCRIPT_DIR}"
else
    echo "[-] Error: Neither podman nor docker found on system PATH." >&2
    exit 1
fi

echo "=========================================================="
echo " Container build complete: ${IMAGE_NAME}"
echo " To run on GB10 superchip, execute: ./run_container.sh ${IMAGE_NAME}"
echo "=========================================================="
