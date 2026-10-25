#!/usr/bin/env python3
"""
Complete demo launch file:
1. Launches mock_camera_node (simulating 240p libcamera stream with moving objects)
2. Launches yolo_detector_node (YOLO inference with model.pt)
3. Launches RViz2 with preconfigured raw camera and annotated detection displays
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("object_det") if "object_det" in os.environ.get("AMENT_PREFIX_PATH", "") else "."
    rviz_config_path = os.path.join(pkg_share, "config", "demo.rviz")
    if not os.path.exists(rviz_config_path):
        rviz_config_path = os.path.join(os.path.dirname(__file__), "..", "config", "demo.rviz")

    default_model_path = os.path.join(pkg_share, "models", "model.pt")
    if not os.path.exists(default_model_path):
        default_model_path = "model.pt"

    return LaunchDescription([
        # Arguments
        DeclareLaunchArgument(
            "rviz",
            default_value="true",
            description="Whether to launch RViz2"
        ),
        DeclareLaunchArgument(
            "confidence_threshold",
            default_value="0.25",
            description="Minimum confidence score for detections"
        ),
        DeclareLaunchArgument(
            "model_path",
            default_value=default_model_path,
            description="Path to model weights"
        ),

        # 1. Mock 240p Libcamera Node
        Node(
            package="object_det",
            executable="mock_camera_node",
            name="mock_camera_node",
            output="screen",
            parameters=[{
                "fps": 20.0,
                "camera_topic": "/camera/image_raw",
                "frame_id": "camera_optical_frame",
            }],
        ),

        # 2. YOLO Detector Node
        Node(
            package="object_det",
            executable="detector_node",
            name="yolo_detector_node",
            output="screen",
            parameters=[{
                "camera_topic": "/camera/image_raw",
                "model_path": LaunchConfiguration("model_path"),
                "confidence_threshold": LaunchConfiguration("confidence_threshold"),
                "publish_annotated_image": True,
                "publish_detections": True,
                "publish_json": True,
            }],
        ),

        # 3. RViz2 Display
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            output="screen",
            arguments=["-d", rviz_config_path],
            condition=IfCondition(LaunchConfiguration("rviz")),
        ),
    ])
