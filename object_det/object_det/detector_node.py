#!/usr/bin/env python3
"""
ROS 2 YOLOv26 Object Detection Node.

Subscribes to a 240p RGB camera stream (from libcamera_ros or camera_ros),
runs inference using Ultralytics YOLO with model.pt (optimized for NVIDIA GB10
Grace Blackwell Superchip or CPU), and broadcasts detected object classes and
bounding boxes via standard vision_msgs/msg/Detection2DArray, JSON summary,
and annotated visualization frames.
"""

import json
import os
import sys
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import Image
from std_msgs.msg import String

# Optional vision_msgs support
try:
    from vision_msgs.msg import (
        BoundingBox2D,
        Detection2D,
        Detection2DArray,
        ObjectHypothesis,
        ObjectHypothesisWithPose,
    )
    HAS_VISION_MSGS = True
except ImportError:
    HAS_VISION_MSGS = False

# Ultralytics YOLO
try:
    import torch
    from ultralytics import YOLO
    HAS_ULTRALYTICS = True
except ImportError as e:
    HAS_ULTRALYTICS = False
    ULTRALYTICS_IMPORT_ERROR = str(e)


def ros_image_to_cv2(msg: Image) -> np.ndarray:
    """
    Convert a sensor_msgs/msg/Image to a BGR OpenCV NumPy array.
    Uses pure-NumPy buffer unpacking to avoid NumPy 1.x vs 2.x ABI mismatches
    commonly seen with binary cv_bridge distributions.
    """
    encoding = msg.encoding.lower()
    raw_data = bytes(msg.data)
    height = msg.height
    width = msg.width

    if encoding in ("rgb8", "rgb"):
        arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 3))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    elif encoding in ("bgr8", "bgr"):
        return np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 3))
    elif encoding in ("rgba8", "rgba"):
        arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 4))
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    elif encoding in ("bgra8", "bgra"):
        arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 4))
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    elif encoding in ("mono8", "8uc1"):
        arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width))
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    elif encoding in ("yuv422", "yuv422_yuy2", "yuyv"):
        arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, 2))
        return cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_YUY2)
    else:
        # Generic fallback: assume 3-channel 8-bit
        try:
            arr = np.frombuffer(raw_data, dtype=np.uint8).reshape((height, width, -1))
            if arr.shape[2] == 3:
                return arr
        except Exception as err:
            raise ValueError(f"Unsupported image encoding '{msg.encoding}': {err}") from err
        raise ValueError(f"Unsupported image encoding '{msg.encoding}'")


def cv2_to_ros_image(img_bgr: np.ndarray, header=None) -> Image:
    """Convert an OpenCV BGR image to a sensor_msgs/msg/Image."""
    msg = Image()
    if header is not None:
        msg.header = header
    msg.height, msg.width = img_bgr.shape[:2]
    msg.encoding = "bgr8"
    msg.is_bigendian = 0
    channels = 1 if img_bgr.ndim == 2 else img_bgr.shape[2]
    msg.step = msg.width * channels * img_bgr.dtype.itemsize
    msg.data = img_bgr.tobytes()
    return msg


class YoloDetectorNode(Node):
    """ROS 2 Node for YOLOv26 object detection on 240p camera stream."""

    def __init__(self):
        super().__init__("yolo_detector_node")

        # Parameter declarations
        self.declare_parameter("model_path", "model.pt")
        self.declare_parameter("camera_topic", "/camera/image_raw")
        self.declare_parameter("confidence_threshold", 0.35)
        self.declare_parameter("iou_threshold", 0.45)
        self.declare_parameter("imgsz", 256)  # Closest multiple of 32 for 240p
        self.declare_parameter("device", "")   # "cuda:0", "cpu", or empty for auto
        self.declare_parameter("publish_detections", True)
        self.declare_parameter("publish_json", True)
        self.declare_parameter("publish_annotated_image", True)
        self.declare_parameter("detection_topic", "detections")
        self.declare_parameter("json_topic", "detections/json")
        self.declare_parameter("annotated_topic", "detections/annotated_image")
        self.declare_parameter("drop_stale_frames", True)

        # Retrieve parameter values
        self.model_path_param = self.get_parameter("model_path").value
        self.camera_topic = self.get_parameter("camera_topic").value
        self.conf_threshold = float(self.get_parameter("confidence_threshold").value)
        self.iou_threshold = float(self.get_parameter("iou_threshold").value)
        self.imgsz = int(self.get_parameter("imgsz").value)
        self.device_param = str(self.get_parameter("device").value)
        self.pub_detections = bool(self.get_parameter("publish_detections").value)
        self.pub_json = bool(self.get_parameter("publish_json").value)
        self.pub_annotated = bool(self.get_parameter("publish_annotated_image").value)
        self.detection_topic = self.get_parameter("detection_topic").value
        self.json_topic = self.get_parameter("json_topic").value
        self.annotated_topic = self.get_parameter("annotated_topic").value
        self.drop_stale_frames = bool(self.get_parameter("drop_stale_frames").value)

        self.get_logger().info("Initializing YOLO Detector Node...")

        if not HAS_ULTRALYTICS:
            self.get_logger().error(f"Failed to import Ultralytics: {ULTRALYTICS_IMPORT_ERROR}")
            raise RuntimeError("Ultralytics library is required but not installed.")

        # Determine compute device (optimizing for GB10 Blackwell GPU / CUDA)
        if self.device_param:
            self.device = self.device_param
        elif torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            self.device = "cuda:0"
            self.get_logger().info(f"NVIDIA GPU detected: {device_name} -> using {self.device}")
        else:
            self.device = "cpu"
            self.get_logger().info("No CUDA GPU detected -> falling back to CPU")

        # Resolve model path
        resolved_model_path = self._resolve_model_path(self.model_path_param)
        self.get_logger().info(f"Loading YOLO weights from: {resolved_model_path}")
        self.model = YOLO(resolved_model_path)

        # Log detected model classes
        self.class_names = self.model.names if hasattr(self.model, "names") else {}
        self.get_logger().info(f"Model classes loaded: {self.class_names}")

        # Warm up the model with a 240p dummy frame
        self._warmup_model()

        # Publishers
        if self.pub_detections:
            if HAS_VISION_MSGS:
                self.det_publisher = self.create_publisher(
                    Detection2DArray,
                    self.detection_topic,
                    10
                )
                self.get_logger().info(f"Publishing Detection2DArray on: '{self.detection_topic}'")
            else:
                self.get_logger().warn(
                    "vision_msgs not available on this system. "
                    "Skipping Detection2DArray publisher (JSON publisher remains active)."
                )
                self.det_publisher = None
        else:
            self.det_publisher = None

        if self.pub_json:
            self.json_publisher = self.create_publisher(
                String,
                self.json_topic,
                10
            )
            self.get_logger().info(f"Publishing JSON detections on: '{self.json_topic}'")
        else:
            self.json_publisher = None

        if self.pub_annotated:
            self.annotated_publisher = self.create_publisher(
                Image,
                self.annotated_topic,
                1
            )
            self.get_logger().info(f"Publishing annotated images on: '{self.annotated_topic}'")
        else:
            self.annotated_publisher = None

        # Camera subscriber with SensorData QoS for live low-latency stream
        cam_qos = qos_profile_sensor_data
        self.subscription = self.create_subscription(
            Image,
            self.camera_topic,
            self.image_callback,
            cam_qos
        )
        self.get_logger().info(
            f"Subscribed to camera stream on: '{self.camera_topic}' (SensorDataQoS)"
        )

        # Processing state tracking
        self._is_processing = False
        self._frame_count = 0
        self._warned_resolution = False

    def _resolve_model_path(self, path: str) -> str:
        """Find model weights file relative to cwd, package share, or absolute path."""
        candidates = [
            path,
            os.path.abspath(path),
            os.path.join(os.getcwd(), path),
            os.path.join(os.path.dirname(__file__), "..", path),
            os.path.join(os.path.dirname(__file__), "..", "models", path),
        ]
        # Also check ament index if available
        try:
            from ament_index_python.packages import get_package_share_directory
            share_dir = get_package_share_directory("object_det")
            candidates.extend([
                os.path.join(share_dir, path),
                os.path.join(share_dir, "models", path),
            ])
        except Exception:
            pass

        for cand in candidates:
            if os.path.isfile(cand):
                return os.path.abspath(cand)

        return path

    def _warmup_model(self):
        """Warm up model to compile CUDA graphs / kernel caches before first real frame."""
        try:
            dummy_img = np.zeros((240, 320, 3), dtype=np.uint8)
            self.model.predict(
                source=dummy_img,
                imgsz=self.imgsz,
                conf=self.conf_threshold,
                device=self.device,
                verbose=False
            )
            self.get_logger().info("Model warmup completed successfully.")
        except Exception as e:
            self.get_logger().warn(f"Model warmup encountered warning/error: {e}")

    def image_callback(self, msg: Image):
        """Process incoming 240p camera frames and broadcast detections."""
        if self.drop_stale_frames and self._is_processing:
            # Drop frame to keep real-time sync with live camera stream
            return

        self._is_processing = True
        try:
            self._process_frame(msg)
        finally:
            self._is_processing = False

    def _process_frame(self, msg: Image):
        start_time = time.monotonic()
        self._frame_count += 1

        # Check resolution (warn if not 240p)
        if msg.height != 240 and not self._warned_resolution:
            self.get_logger().warn(
                f"Camera stream resolution is {msg.width}x{msg.height}, expected height 240p."
            )
            self._warned_resolution = True

        # Convert ROS Image to OpenCV BGR array
        try:
            cv_img = ros_image_to_cv2(msg)
        except Exception as err:
            self.get_logger().error(f"Image conversion failed: {err}")
            return

        img_h, img_w = cv_img.shape[:2]

        # Run YOLO inference
        results = self.model.predict(
            source=cv_img,
            imgsz=self.imgsz,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            verbose=False
        )

        detections_data = []
        vision_msgs_array = Detection2DArray()
        vision_msgs_array.header = msg.header

        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes

            if boxes is not None and len(boxes) > 0:
                for idx, box in enumerate(boxes):
                    cls_id = int(box.cls[0].item())
                    cls_name = self.class_names.get(cls_id, str(cls_id))
                    conf = float(box.conf[0].item())

                    xyxy = [round(float(v), 2) for v in box.xyxy[0].tolist()]
                    xywh = [round(float(v), 2) for v in box.xywh[0].tolist()]
                    xc, yc, bw, bh = xywh

                    # Record structured detection dictionary
                    det_dict = {
                        "id": idx,
                        "class_id": cls_id,
                        "class_name": cls_name,
                        "confidence": round(conf, 4),
                        "box_xyxy": xyxy,
                        "box_xywh": xywh,
                        "box_normalized_xywh": [
                            round(xc / img_w, 4),
                            round(yc / img_h, 4),
                            round(bw / img_w, 4),
                            round(bh / img_h, 4),
                        ],
                    }
                    detections_data.append(det_dict)

                    # Build vision_msgs Detection2D if enabled
                    if self.det_publisher is not None:
                        d2d = Detection2D()
                        d2d.header = msg.header
                        d2d.id = f"{cls_name}_{idx}"

                        # BoundingBox2D (center x, y and size x, y)
                        d2d.bbox.center.position.x = float(xc)
                        d2d.bbox.center.position.y = float(yc)
                        d2d.bbox.size_x = float(bw)
                        d2d.bbox.size_y = float(bh)

                        # Object hypothesis
                        hyp = ObjectHypothesisWithPose()
                        if hasattr(hyp, "hypothesis"):
                            hyp.hypothesis.class_id = str(cls_name)
                            hyp.hypothesis.score = float(conf)
                        else:
                            # Older vision_msgs fallback
                            setattr(hyp, "id", str(cls_name))
                            setattr(hyp, "score", float(conf))
                        d2d.results.append(hyp)

                        vision_msgs_array.detections.append(d2d)

        elapsed_ms = (time.monotonic() - start_time) * 1000.0

        # Broadcast standard Detection2DArray
        if self.det_publisher is not None:
            self.det_publisher.publish(vision_msgs_array)

        # Broadcast JSON detections summary
        if self.json_publisher is not None:
            stamp_sec = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            json_payload = {
                "timestamp": stamp_sec,
                "frame_id": msg.header.frame_id,
                "frame_seq": self._frame_count,
                "image_width": img_w,
                "image_height": img_h,
                "inference_time_ms": round(elapsed_ms, 2),
                "count": len(detections_data),
                "detections": detections_data,
            }
            str_msg = String()
            str_msg.data = json.dumps(json_payload)
            self.json_publisher.publish(str_msg)

        # Broadcast annotated image
        if self.annotated_publisher is not None and self.annotated_publisher.get_subscription_count() > 0:
            if results and len(results) > 0:
                annotated_bgr = results[0].plot()
            else:
                annotated_bgr = cv_img

            ann_msg = cv2_to_ros_image(annotated_bgr, header=msg.header)
            self.annotated_publisher.publish(ann_msg)

        # Periodic debug logging
        if self._frame_count % 30 == 0 or len(detections_data) > 0:
            det_summary = ", ".join([f"{d['class_name']}:{d['confidence']:.2f}" for d in detections_data])
            self.get_logger().info(
                f"[Frame {self._frame_count}] {len(detections_data)} object(s) detected "
                f"({elapsed_ms:.1f}ms): [{det_summary}]"
            )


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = YoloDetectorNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    except Exception as e:
        print(f"Node execution failed: {e}", file=sys.stderr)
        raise
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
