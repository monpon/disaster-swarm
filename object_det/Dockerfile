# syntax=docker/dockerfile:1
# ==============================================================================
# OCI/UCI Container Image for ROS 2 YOLO Object Detection
# Target Hardware: NVIDIA GB10 Grace Blackwell Superchip (ARMv9.2 CPU + Blackwell GPU)
# Target Architecture: linux/arm64 (aarch64)
# Base OS: Ubuntu 24.04 (Noble Numbat) / ROS 2 Jazzy Jalisco
# ==============================================================================

FROM --platform=linux/arm64 ubuntu:24.04 AS runtime

ARG TARGETPLATFORM=linux/arm64
ARG DEBIAN_FRONTEND=noninteractive

# Standard Open Container Initiative (OCI) and UCI Metadata Labels
LABEL org.opencontainers.image.title="ros2-yolo-detector-gb10" \
      org.opencontainers.image.description="ROS 2 YOLOv26 object detector node for 240p camera stream on NVIDIA GB10 Grace Blackwell ARM64" \
      org.opencontainers.image.vendor="Disaster Swarm Team" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.architecture="arm64" \
      org.opencontainers.image.hardware="NVIDIA GB10 Grace Blackwell Superchip" \
      org.opencontainers.image.licenses="MIT"

# NVIDIA Container Toolkit / CDI Environment Configuration
# Configures GPU visibility and driver capabilities for Blackwell architecture (sm_120 / sm_121)
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    TORCH_CUDA_ARCH_LIST="12.0;12.1" \
    ROS_DISTRO=jazzy \
    PYTHONUNBUFFERED=1 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

# Install foundational packages, locales, and Python build environment
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    locales \
    software-properties-common \
    build-essential \
    python3 \
    python3-pip \
    python3-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && locale-gen en_US en_US.UTF-8 \
    && update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

# Add official ROS 2 Jazzy repository
RUN add-apt-repository universe \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=arm64 signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu noble main" > /etc/apt/sources.list.d/ros2.list

# Install ROS 2 Jazzy base, vision_msgs, and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-ros-base \
    ros-jazzy-vision-msgs \
    ros-jazzy-sensor-msgs \
    ros-jazzy-std-msgs \
    ros-jazzy-image-transport \
    python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch for ARM64 with CUDA acceleration and Ultralytics
RUN python3 -m pip install --no-cache-dir --break-system-packages \
    torch \
    torchvision \
    --index-url https://download.pytorch.org/whl/cu128 || \
    python3 -m pip install --no-cache-dir --break-system-packages torch torchvision

RUN python3 -m pip install --no-cache-dir --break-system-packages \
    ultralytics \
    opencv-python-headless \
    numpy

# Set up ROS 2 workspace
WORKDIR /ros2_ws/src/object_det

# Copy source code, configurations, and trained weights
COPY package.xml setup.py setup.cfg ./
COPY resource/ ./resource/
COPY object_det/ ./object_det/
COPY launch/ ./launch/
COPY config/ ./config/
COPY model.pt ./model.pt

# Build the ROS 2 package
WORKDIR /ros2_ws
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release"

# Entrypoint script to source ROS 2 environments
RUN echo '#!/bin/bash\n\
set -e\n\
source /opt/ros/jazzy/setup.bash\n\
if [ -f /ros2_ws/install/setup.bash ]; then\n\
    source /ros2_ws/install/setup.bash\n\
fi\n\
exec "$@"' > /entrypoint.sh && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "object_det", "detector.launch.py"]
