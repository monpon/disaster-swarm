#!/usr/bin/env python3
"""Launch file for YOLOv26 object detector node."""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("object_det") if "object_det" in os.environ.get("AMENT_PREFIX_PATH", "") else "."
    default_model_path = os.path.join(pkg_share, "models", "model.pt") if os.path.exists(os.path.join(pkg_share, "models", "model.pt")) else "model.pt"

    return LaunchDescription([
        # Launch Arguments
        DeclareLaunchArgument(
            "camera_topic",
            default_value="/camera/image_raw",
            description="Topic name for the 240p RGB camera input stream from libcamera"
        ),
        DeclareLaunchArgument(
            "model_path",
            default_value=default_model_path,
            description="Path to the YOLO model.pt weights file"
        ),
        DeclareLaunchArgument(
            "confidence_threshold",
            default_value="0.35",
            description="Minimum confidence threshold for detections (0.0 to 1.0)"
        ),
        DeclareLaunchArgument(
            "iou_threshold",
            default_value="0.45",
            description="Intersection-over-Union threshold for NMS"
        ),
        DeclareLaunchArgument(
            "device",
            default_value="",
            description="Torch compute device ('cuda:0', 'cpu', or '' for auto-detect)"
        ),
        DeclareLaunchArgument(
            "publish_annotated_image",
            default_value="true",
            description="Whether to publish annotated debug image stream"
        ),
        DeclareLaunchArgument(
            "publish_json",
            default_value="true",
            description="Whether to publish JSON detections summary"
        ),
        DeclareLaunchArgument(
            "publish_detections",
            default_value="true",
            description="Whether to publish vision_msgs/Detection2DArray"
        ),

        # YOLO Detector Node
        Node(
            package="object_det",
            executable="detector_node",
            name="yolo_detector_node",
            output="screen",
            parameters=[{
                "camera_topic": LaunchConfiguration("camera_topic"),
                "model_path": LaunchConfiguration("model_path"),
                "confidence_threshold": LaunchConfiguration("confidence_threshold"),
                "iou_threshold": LaunchConfiguration("iou_threshold"),
                "device": LaunchConfiguration("device"),
                "publish_annotated_image": LaunchConfiguration("publish_annotated_image"),
                "publish_json": LaunchConfiguration("publish_json"),
                "publish_detections": LaunchConfiguration("publish_detections"),
            }],
        ),
    ])
