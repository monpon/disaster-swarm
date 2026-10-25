#!/usr/bin/env python3
"""
Synthetic 240p RGB camera node simulating a libcamera camera stream.
Publishes animated disaster response scenes containing doors, persons, and fires
at 20 FPS to `/camera/image_raw` with CameraInfo and TF transforms for RViz2.
"""

import math
import time

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
import tf2_ros


class MockCameraNode(Node):
    def __init__(self):
        super().__init__("mock_camera_node")

        self.declare_parameter("fps", 20.0)
        self.declare_parameter("camera_topic", "/camera/image_raw")
        self.declare_parameter("frame_id", "camera_optical_frame")

        self.fps = float(self.get_parameter("fps").value)
        self.topic = str(self.get_parameter("camera_topic").value)
        self.frame_id = str(self.get_parameter("frame_id").value)

        # 240p dimensions (320x240)
        self.width = 320
        self.height = 240

        self.image_pub = self.create_publisher(Image, self.topic, qos_profile_sensor_data)
        self.info_pub = self.create_publisher(CameraInfo, "/camera/camera_info", qos_profile_sensor_data)

        # TF broadcaster
        self.tf_broadcaster = tf2_ros.StaticTransformBroadcaster(self)
        self._publish_static_tf()

        self.start_time = time.monotonic()
        self.timer = self.create_timer(1.0 / self.fps, self.publish_frame)
        self.get_logger().info(
            f"Mock 240p libcamera node started: publishing {self.width}x{self.height} RGB at {self.fps} FPS on '{self.topic}'"
        )

    def _publish_static_tf(self):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = "map"
        t.child_frame_id = self.frame_id
        t.transform.translation.x = 0.0
        t.transform.translation.y = 0.0
        t.transform.translation.z = 1.0
        t.transform.rotation.w = 1.0
        self.tf_broadcaster.sendTransform(t)

    def generate_scene(self, t: float) -> np.ndarray:
        """Render a synthetic 240p disaster response scene."""
        frame = np.full((self.height, self.width, 3), 140, dtype=np.uint8)

        # Background room horizon
        cv2.rectangle(frame, (0, 0), (self.width, 175), (155, 155, 165), -1)
        cv2.rectangle(frame, (0, 175), (self.width, self.height), (85, 75, 75), -1)
        cv2.line(frame, (0, 175), (self.width, 175), (60, 50, 50), 2)

        # 1. Door (left)
        cv2.rectangle(frame, (25, 35), (105, 205), (35, 65, 125), -1)
        cv2.rectangle(frame, (25, 35), (105, 205), (15, 25, 45), 2)
        cv2.circle(frame, (38, 125), 4, (230, 230, 230), -1)

        # 2. Moving Person (center, walking sinusoidally)
        person_x = int(145 + 30 * math.sin(t * 1.5))
        # Head
        cv2.circle(frame, (person_x, 75), 14, (190, 190, 190), -1)
        # Torso
        cv2.rectangle(frame, (person_x - 12, 90), (person_x + 12, 155), (140, 70, 40), -1)
        # Arms
        arm_swing = int(8 * math.cos(t * 3.0))
        cv2.line(frame, (person_x - 12, 98), (person_x - 16, 135 + arm_swing), (140, 70, 40), 4)
        cv2.line(frame, (person_x + 12, 98), (person_x + 16, 135 - arm_swing), (140, 70, 40), 4)
        # Legs
        leg_stride = int(10 * math.sin(t * 3.0))
        cv2.line(frame, (person_x - 6, 155), (person_x - 8 + leg_stride, 212), (40, 40, 160), 5)
        cv2.line(frame, (person_x + 6, 155), (person_x + 8 - leg_stride, 212), (40, 40, 160), 5)

        # 3. Fire / Smoke (right)
        flame_h = int(35 + 18 * math.sin(t * 6.0))
        fire_pts = np.array([
            [225, 205],
            [240, 205 - flame_h],
            [252, 175],
            [265, 205 - flame_h - 12],
            [278, 180],
            [290, 205]
        ], np.int32)
        cv2.fillPoly(frame, [fire_pts], (0, 140, 255))
        inner_pts = np.array([
            [238, 205],
            [250, 190 - flame_h // 2],
            [262, 185],
            [275, 205]
        ], np.int32)
        cv2.fillPoly(frame, [inner_pts], (0, 240, 255))

        # Animated smoke puffs rising
        for i in range(3):
            smoke_y = int(140 - ((t * 40 + i * 35) % 110))
            smoke_x = int(255 + 10 * math.sin(t * 2.0 + i))
            smoke_r = int(12 + (140 - smoke_y) * 0.15)
            alpha_overlay = frame.copy()
            cv2.circle(alpha_overlay, (smoke_x, smoke_y), smoke_r, (120, 120, 120), -1)
            cv2.addWeighted(alpha_overlay, 0.4, frame, 0.6, 0, frame)

        # Convert OpenCV BGR to RGB (libcamera RGB888 output format)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def publish_frame(self):
        t = time.monotonic() - self.start_time
        rgb_frame = self.generate_scene(t)

        now = self.get_clock().now().to_msg()

        img_msg = Image()
        img_msg.header.stamp = now
        img_msg.header.frame_id = self.frame_id
        img_msg.height = self.height
        img_msg.width = self.width
        img_msg.encoding = "rgb8"
        img_msg.is_bigendian = 0
        img_msg.step = self.width * 3
        img_msg.data = rgb_frame.tobytes()

        self.image_pub.publish(img_msg)

        # Camera Info
        info_msg = CameraInfo()
        info_msg.header.stamp = now
        info_msg.header.frame_id = self.frame_id
        info_msg.width = self.width
        info_msg.height = self.height
        info_msg.distortion_model = "plumb_bob"
        info_msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        # Pinhole focal length ~250 for 320x240
        info_msg.k = [250.0, 0.0, 160.0, 0.0, 250.0, 120.0, 0.0, 0.0, 1.0]
        info_msg.p = [250.0, 0.0, 160.0, 0.0, 0.0, 250.0, 120.0, 0.0, 0.0, 0.0, 1.0, 0.0]

        self.info_pub.publish(info_msg)


def main(args=None):
    rclpy.init(args=args)
    node = MockCameraNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
