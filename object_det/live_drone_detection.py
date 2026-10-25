#!/usr/bin/env python3
"""
Live Drone Object Detection Feed using YOLOv26m & Turbodrone Video Stream.

Connects to the drone using Turbodrone's protocol adapter, runs local YOLO
inference on each frame with Ultralytics, and serves both:
  1. A native OpenCV desktop GUI window (cv2.imshow) with real-time HUD
  2. An embedded multi-client HTTP MJPEG web server with a dashboard UI
"""

import argparse
import base64
import http.server
import json
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time
import cv2
import numpy as np
REAL_FILE = os.path.realpath(__file__)
SCRIPT_DIR = os.path.dirname(REAL_FILE)

candidate_backend_dirs = [
    os.path.join(SCRIPT_DIR, "turbodrone", "backend"),
    os.path.join(SCRIPT_DIR, "object_det", "turbodrone", "backend"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "object_det", "turbodrone", "backend"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "turbodrone", "backend"),
]

for b_dir in candidate_backend_dirs:
    if os.path.isdir(b_dir) and b_dir not in sys.path:
        sys.path.insert(0, b_dir)


try:
    from protocols.wifi_cam_video_protocol import WifiCamVideoProtocolAdapter
    from protocols.s2x_video_protocol import S2xVideoProtocolAdapter
    from protocols.wifi_uav_video_protocol import WifiUavVideoProtocolAdapter
    from protocols.cooingdv_video_protocol import CooingdvVideoProtocolAdapter
    from protocols.cooingdv_jieli_video_protocol import CooingdvJieliVideoProtocolAdapter
    from protocols.x69_lg_video_protocol import X69LgVideoProtocolAdapter
    from protocols.x69_lg_rtsp_video_protocol import X69LgRtspVideoProtocolAdapter
    from protocols.x69_lg_jpeg_video_protocol import X69LgJpegVideoProtocolAdapter
    from utils.wifi_uav_variants import WIFI_UAV_DRONE_TYPES, resolve_wifi_uav_variant
except ImportError as e:
    sys.stderr.write(f"Error importing Turbodrone protocols: {e}\n")
    sys.exit(1)

try:
    import torch
    from ultralytics import YOLO
except ImportError as e:
    sys.stderr.write(f"Error importing Ultralytics / PyTorch: {e}\n")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DroneDetector")

# Class color palette (BGR)
CLASS_COLORS = {
    "fire": (0, 69, 255),      # Orange-red
    "smoke": (180, 180, 180),  # Light gray
    "person": (0, 255, 128),   # Vibrant spring green
    "door": (255, 191, 0),     # Amber / Sky blue
}
DEFAULT_COLOR = (0, 220, 255)


def resolve_model_path(user_path: Optional[str] = None) -> str:
    """Find the YOLO model file."""
    candidates = []
    if user_path:
        candidates.append(user_path)
    candidates.extend([
        os.path.join(SCRIPT_DIR, "model.pt"),
        os.path.join(SCRIPT_DIR, "..", "model.pt"),
        os.path.join(SCRIPT_DIR, "install", "object_det", "share", "object_det", "models", "model.pt"),
        "model.pt",
    ])
    for path in candidates:
        abs_p = os.path.abspath(path)
        if os.path.isfile(abs_p):
            return abs_p
    raise FileNotFoundError(f"Could not locate YOLO model.pt. Searched: {candidates}")


class MJPEGHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request Handler serving live dashboard and MJPEG stream."""

    server_ref: "LiveFeedServer"

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.server_ref.get_html_dashboard().encode("utf-8"))
        elif self.path == "/stream" or self.path == "/mjpeg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            client_q = self.server_ref.register_client()
            try:
                while self.server_ref.running:
                    try:
                        jpeg_bytes = client_q.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    if jpeg_bytes is None:
                        break
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg_bytes)).encode("ascii") + b"\r\n\r\n"
                    )
                    self.wfile.write(header + jpeg_bytes + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                self.server_ref.unregister_client(client_q)
        elif self.path == "/detections":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = json.dumps(self.server_ref.latest_telemetry)
            self.wfile.write(data.encode("utf-8"))
        elif self.path == "/snapshot":
            frame_bytes = self.server_ref.latest_jpeg
            if frame_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Disposition", "inline; filename=\"drone_detection.jpg\"")
                self.end_headers()
                self.wfile.write(frame_bytes)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence routine HTTP request logging to avoid cluttering CLI
        pass


class LiveFeedServer:
    """Manages HTTP clients and broadcasts annotated JPEG frames."""

    def __init__(self, port: int = 8088):
        self.port = port
        self.running = False
        self.clients: list[queue.Queue] = []
        self.clients_lock = threading.Lock()
        self.latest_jpeg: Optional[bytes] = None
        self.latest_telemetry: Dict = {
            "fps": 0.0,
            "inference_ms": 0.0,
            "detections": [],
            "resolution": "0x0",
            "device": "CPU",
            "timestamp": time.time(),
        }
        self.httpd: Optional[http.server.ThreadingHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None

    def start(self):
        handler_cls = MJPEGHandler
        handler_cls.server_ref = self
        self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", self.port), handler_cls)
        self.httpd.daemon_threads = True
        self.running = True
        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        logger.info(f"Web object detection dashboard online at: http://localhost:{self.port}/")
        logger.info(f"Direct MJPEG stream URL: http://localhost:{self.port}/stream")

    def stop(self):
        self.running = False
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        with self.clients_lock:
            for q in self.clients:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
            self.clients.clear()

    def register_client(self) -> queue.Queue:
        q = queue.Queue(maxsize=3)
        with self.clients_lock:
            self.clients.append(q)
        return q

    def unregister_client(self, q: queue.Queue):
        with self.clients_lock:
            if q in self.clients:
                self.clients.remove(q)

    def publish_frame(self, jpeg_bytes: bytes, telemetry: Dict):
        self.latest_jpeg = jpeg_bytes
        self.latest_telemetry = telemetry
        with self.clients_lock:
            for q in list(self.clients):
                try:
                    q.put_nowait(jpeg_bytes)
                except queue.Full:
                    try:
                        _ = q.get_nowait()
                        q.put_nowait(jpeg_bytes)
                    except Exception:
                        pass

    def get_html_dashboard(self) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Drone Live YOLOv26m Object Detection Feed</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0d1117;
      color: #c9d1d9;
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 20px;
    }}
    header {{
      width: 100%;
      max-width: 960px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid #30363d;
    }}
    h1 {{ font-size: 1.25rem; font-weight: 600; color: #58a6ff; display: flex; align-items: center; gap: 8px; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      font-size: 0.75rem;
      font-weight: 600;
      border-radius: 12px;
      background: #238636;
      color: #fff;
    }}
    .container {{
      width: 100%;
      max-width: 960px;
      display: grid;
      grid-template-columns: 1fr 280px;
      gap: 16px;
    }}
    @media (max-width: 800px) {{
      .container {{ grid-template-columns: 1fr; }}
    }}
    .video-card {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      position: relative;
    }}
    .video-card img {{
      width: 100%;
      height: auto;
      max-height: 70vh;
      object-fit: contain;
      display: block;
      background: #000;
    }}
    .stats-card {{
      background: #161b22;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.9rem;
      padding-bottom: 6px;
      border-bottom: 1px solid #21262d;
    }}
    .stat-value {{ font-family: monospace; font-weight: 700; color: #f0883e; }}
    .det-list {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 250px;
      overflow-y: auto;
    }}
    .det-item {{
      background: #0d1117;
      border-left: 4px solid #58a6ff;
      padding: 6px 10px;
      border-radius: 4px;
      font-size: 0.82rem;
      display: flex;
      justify-content: space-between;
    }}
    .det-fire {{ border-color: #ff4500; color: #ff7b72; }}
    .det-smoke {{ border-color: #b0b0b0; color: #d2a8ff; }}
    .det-person {{ border-color: #00ff7f; color: #7ee787; }}
    .det-door {{ border-color: #00bfff; color: #79c0ff; }}
    .btn {{
      display: inline-block;
      text-align: center;
      background: #21262d;
      border: 1px solid #30363d;
      color: #c9d1d9;
      padding: 8px 12px;
      border-radius: 6px;
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .btn:hover {{ background: #30363d; color: #fff; }}
  </style>
</head>
<body>
  <header>
    <h1>
      <span>🛸</span> Turbodrone YOLOv26m Live Feed
      <span class="badge" id="status-badge">LIVE</span>
    </h1>
    <div style="display:flex; gap: 8px;">
      <a class="btn" href="/snapshot" target="_blank">📷 Save Snapshot</a>
      <a class="btn" href="/stream" target="_blank">🔗 Raw Stream</a>
    </div>
  </header>

  <div class="container">
    <div class="video-card">
      <img id="mjpeg-img" src="/stream" alt="Live Drone Object Detection Stream">
    </div>

    <div class="stats-card">
      <h3 style="font-size: 1rem; color: #8b949e; border-bottom: 1px solid #30363d; padding-bottom: 6px;">Telemetry</h3>
      
      <div class="stat-row">
        <span>FPS</span>
        <span class="stat-value" id="val-fps">--</span>
      </div>
      <div class="stat-row">
        <span>Inference Latency</span>
        <span class="stat-value" id="val-lat">-- ms</span>
      </div>
      <div class="stat-row">
        <span>Resolution</span>
        <span class="stat-value" id="val-res">--</span>
      </div>
      <div class="stat-row">
        <span>Compute Device</span>
        <span class="stat-value" id="val-dev">--</span>
      </div>
      <div class="stat-row">
        <span>Total Detections</span>
        <span class="stat-value" id="val-cnt">0</span>
      </div>

      <h3 style="font-size: 1rem; color: #8b949e; border-bottom: 1px solid #30363d; padding-bottom: 6px;">Live Detections</h3>
      <div class="det-list" id="det-container">
        <div style="color: #6e7681; font-size: 0.85rem;">Waiting for detections...</div>
      </div>
    </div>
  </div>

  <script>
    async function updateTelemetry() {{
      try {{
        const res = await fetch('/detections');
        if (res.ok) {{
          const data = await res.json();
          document.getElementById('val-fps').textContent = data.fps.toFixed(1);
          document.getElementById('val-lat').textContent = data.inference_ms.toFixed(1) + ' ms';
          document.getElementById('val-res').textContent = data.resolution;
          document.getElementById('val-dev').textContent = data.device;
          document.getElementById('val-cnt').textContent = data.detections.length;

          const container = document.getElementById('det-container');
          if (data.detections.length === 0) {{
            container.innerHTML = '<div style="color: #6e7681; font-size: 0.85rem;">No objects detected in frame</div>';
          }} else {{
            let html = '';
            for (const d of data.detections) {{
              const cls = d.class_name.toLowerCase();
              html += `<div class="det-item det-${{cls}}">` +
                      `<strong>${{d.class_name.toUpperCase()}}</strong>` +
                      `<span>${{(d.confidence * 100).toFixed(1)}}%</span>` +
                      `</div>`;
            }}
            container.innerHTML = html;
          }}
        }}
      }} catch (e) {{
        console.warn('Telemetry fetch error', e);
      }}
    }}
    setInterval(updateTelemetry, 300);
  </script>
</body>
</html>
"""


class LiveDroneDetector:
    """Main object detection pipeline connecting drone stream to YOLO."""

    def __init__(
        self,
        drone_type: str = "wifi_cam",
        drone_ip: str = "192.168.4.153",
        control_port: int = 8090,
        video_port: int = 8080,
        model_path: Optional[str] = None,
        conf_thresh: float = 0.15,
        iou_thresh: float = 0.50,
        imgsz: int = 256,
        web_port: int = 8088,
        show_gui: bool = True,
        rotate_degrees: Optional[int] = None,
    ):
        self.drone_type = drone_type
        self.drone_ip = drone_ip
        self.control_port = control_port
        self.video_port = video_port
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self.imgsz = imgsz
        self.web_port = web_port
        self.show_gui = show_gui
        # Default rotation to 270 (-90) for wifi_cam or user override
        self.current_rotation = 270 if rotate_degrees is None else (rotate_degrees % 360)
        self.show_hud = True

        self.running = False
        self.adapter = None
        self.web_server = LiveFeedServer(port=self.web_port)

        # Resolve compute device
        if torch.cuda.is_available():
            self.device = "cuda:0"
            gpu_name = torch.cuda.get_device_name(0)
            logger.info(f"Using GPU device: {self.device} ({gpu_name})")
        else:
            self.device = "cpu"
            torch.set_num_threads(min(4, os.cpu_count() or 2))
            logger.info(f"Using CPU inference (device={self.device})")

        # Available models catalog
        self.available_models = {}
        disaster_weights = resolve_model_path(model_path)
        self.available_models["disaster"] = disaster_weights

        coco_candidates = [
            "/var/home/raameshb/Downloads/yolo26m.pt",
            os.path.join(SCRIPT_DIR, "yolo26m.pt"),
            os.path.join(SCRIPT_DIR, "..", "yolo26m.pt"),
        ]
        for cp in coco_candidates:
            if os.path.isfile(cp):
                self.available_models["coco"] = cp
                break

        self.current_model_key = "disaster"
        self._load_active_model()

    def _load_active_model(self):
        weights = self.available_models[self.current_model_key]
        logger.info(f"Loading YOLO weights ({self.current_model_key}): {weights}")
        self.model = YOLO(weights)
        self.model.to(self.device)
        self.class_names = self.model.names
        logger.info(f"Loaded {len(self.class_names)} classes for [{self.current_model_key}]: {list(self.class_names.values())[:8]}")

        # Warm up
        dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
        self.model(dummy, imgsz=self.imgsz, device=self.device, verbose=False)

    def toggle_model(self):
        keys = list(self.available_models.keys())
        if len(keys) < 2:
            logger.info(f"Only one model available: {keys}")
            return
        cur_idx = keys.index(self.current_model_key)
        self.current_model_key = keys[(cur_idx + 1) % len(keys)]
        logger.info(f"Switching active model to: {self.current_model_key.upper()}")
        self._load_active_model()

    def _init_protocol_adapter(self):
        """Instantiate Turbodrone video adapter with raw 0 rotation (in-memory rotation handled)."""
        logger.info(f"Initializing video adapter for drone type: {self.drone_type}")
        if self.drone_type == "wifi_cam":
            # Pass rotate_degrees=0 so we do fast in-memory rotation allowing live 'r' toggle
            self.adapter = WifiCamVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port,
                rotate_degrees=0,
            )
        elif self.drone_type == "s2x":
            self.adapter = S2xVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port,
            )
        elif self.drone_type in WIFI_UAV_DRONE_TYPES:
            variant = resolve_wifi_uav_variant(self.drone_type)
            self.adapter = WifiUavVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port,
                variant=variant,
            )
        elif self.drone_type == "cooingdv":
            self.adapter = CooingdvVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port,
            )
        elif self.drone_type == "cooingdv_jieli":
            self.adapter = CooingdvJieliVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port or 6666,
            )
        elif self.drone_type == "x69_lg":
            self.adapter = X69LgVideoProtocolAdapter(
                drone_ip=self.drone_ip,
                control_port=self.control_port,
                video_port=self.video_port,
            )
        else:
            raise ValueError(f"Unsupported drone type: {self.drone_type}")

    def annotate_frame(
        self,
        frame_bgr: np.ndarray,
        boxes: List[Dict],
        fps: float,
        latency_ms: float,
    ) -> np.ndarray:
        """Upscale to 640x480 for full-bleed display and draw bounding boxes + clear HUD."""
        h, w = frame_bgr.shape[:2]
        scale = 2
        disp_w, disp_h = w * scale, h * scale
        annotated = cv2.resize(frame_bgr, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)

        # Draw bounding boxes (scaled by scale factor)
        for item in boxes:
            x1, y1, x2, y2 = [int(v * scale) for v in item["box_xyxy"]]
            cls_name = item["class_name"]
            conf = item["confidence"]

            if cls_name.lower() in CLASS_COLORS:
                color = CLASS_COLORS[cls_name.lower()]
            else:
                h_val = abs(hash(cls_name))
                color = ((h_val * 47) % 200 + 40, (h_val * 73) % 200 + 40, (h_val * 113) % 200 + 40)

            # Bounding box rectangle
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

            # Label banner
            label = f"{cls_name.upper()} {conf * 100:.0f}%"
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
            y_label_top = max(0, y1 - th - 6)
            cv2.rectangle(
                annotated,
                (x1, y_label_top),
                (x1 + tw + 6, y_label_top + th + 6),
                color,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (x1 + 3, y_label_top + th + 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )

        # Top HUD Banner
        if self.show_hud:
            hud_h = 28
            overlay = annotated.copy()
            cv2.rectangle(overlay, (0, 0), (disp_w, hud_h), (12, 16, 22), -1)
            cv2.addWeighted(overlay, 0.82, annotated, 0.18, 0, annotated)

            model_name = self.current_model_key.upper()
            hud_text = (
                f"LIVE {disp_w}x{disp_h} | {fps:4.1f} FPS | {latency_ms:4.1f}ms | "
                f"Objs: {len(boxes)} | Conf: {self.conf_thresh:.2f} [+/-] | Rot: {self.current_rotation}deg [r] | Model: {model_name} [m]"
            )
            cv2.putText(
                annotated,
                hud_text,
                (8, 19),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                (245, 245, 245),
                1,
                cv2.LINE_AA,
            )

        return annotated

    def run(self):
        """Main streaming and detection loop."""
        self.running = True
        self._init_protocol_adapter()

        logger.info(f"Starting video stream from drone at {self.drone_ip}:{self.video_port}...")
        self.adapter.start()
        self.web_server.start()

        window_name = "Turbodrone YOLO Live Object Detection Feed"
        if self.show_gui:
            try:
                cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
                logger.info(f"OpenCV GUI window initialized: '{window_name}'")
            except Exception as e:
                logger.warning(f"Could not open GUI window (headless environment?): {e}")
                self.show_gui = False

        fps_calc_time = time.time()
        frame_counter = 0
        current_fps = 0.0

        print("\n" + "=" * 65)
        print("  🛸 TURBODRONE LIVE YOLO OBJECT DETECTION")
        print(f"  • Model:        [{self.current_model_key.upper()}] (classes: {list(self.class_names.values())[:8]})")
        print(f"  • Drone IP:     {self.drone_ip} (type: {self.drone_type})")
        print(f"  • Web Feed:     http://localhost:{self.web_port}/")
        print(f"  • MJPEG Stream: http://localhost:{self.web_port}/stream")
        if self.show_gui:
            print("  • Controls:     '+'/'-' or ']'/'[' = adjust conf | 'r' = rotate | 'm' = switch model")
            print("                  '1','2','3','5','0' = conf presets | 's' = snap | 'q' = quit")
        print("=" * 65 + "\n")

        try:
            while self.running:
                # Fetch newest video frame from drone
                frame = self.adapter.get_frame(timeout=1.0)
                if frame is None:
                    continue

                # Decode JPEG to BGR numpy array
                if hasattr(frame, "data"):
                    img_data = frame.data
                else:
                    img_data = frame

                img_bgr = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
                if img_bgr is None:
                    continue

                # Apply live rotation in memory
                if self.current_rotation == 90:
                    img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
                elif self.current_rotation == 180:
                    img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_180)
                elif self.current_rotation == 270:
                    img_bgr = cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)

                h, w = img_bgr.shape[:2]

                # Run YOLO inference
                t_start = time.perf_counter()
                results = self.model(
                    img_bgr,
                    conf=self.conf_thresh,
                    iou=self.iou_thresh,
                    imgsz=self.imgsz,
                    device=self.device,
                    verbose=False,
                    max_det=300,
                )
                latency_ms = (time.perf_counter() - t_start) * 1000.0

                # Extract detections
                detections = []
                for r in results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0].item())
                        cls_name = self.class_names.get(cls_id, f"cls_{cls_id}")
                        conf = float(box.conf[0].item())
                        xyxy = [float(x) for x in box.xyxy[0].tolist()]
                        detections.append({
                            "class_id": cls_id,
                            "class_name": cls_name,
                            "confidence": round(conf, 4),
                            "box_xyxy": [round(x, 1) for x in xyxy],
                        })

                # Calculate smoothed FPS
                frame_counter += 1
                now = time.time()
                elapsed = now - fps_calc_time
                if elapsed >= 0.5:
                    current_fps = frame_counter / elapsed
                    frame_counter = 0
                    fps_calc_time = now

                # Annotate image
                annotated = self.annotate_frame(img_bgr, detections, current_fps, latency_ms)

                # Encode to JPEG for web streaming
                ok, jpeg_buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok:
                    telemetry = {
                        "fps": current_fps,
                        "inference_ms": latency_ms,
                        "detections": detections,
                        "resolution": f"{annotated.shape[1]}x{annotated.shape[0]}",
                        "device": self.device.upper(),
                        "model": self.current_model_key.upper(),
                        "timestamp": now,
                    }
                    self.web_server.publish_frame(jpeg_buf.tobytes(), telemetry)

                # Display in desktop GUI window if enabled
                if self.show_gui:
                    cv2.imshow(window_name, annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q") or key == 27:  # 'q' or ESC
                        logger.info("Exit requested from OpenCV GUI.")
                        break
                    elif key == ord("s"):
                        snap_name = f"drone_snap_{int(time.time())}.jpg"
                        cv2.imwrite(snap_name, annotated)
                        logger.info(f"Saved snapshot to {snap_name}")
                    elif key == ord("h"):
                        self.show_hud = not self.show_hud
                    elif key == ord("+") or key == ord("=") or key == ord("]"):
                        self.conf_thresh = min(0.95, round(self.conf_thresh + 0.05, 2))
                        logger.info(f"Confidence threshold: {self.conf_thresh:.2f}")
                    elif key == ord("-") or key == ord("_") or key == ord("["):
                        self.conf_thresh = max(0.01, round(self.conf_thresh - 0.05, 2))
                        logger.info(f"Confidence threshold: {self.conf_thresh:.2f}")
                    elif key == ord("r"):
                        self.current_rotation = (self.current_rotation + 90) % 360
                        logger.info(f"Rotation set to: {self.current_rotation}deg")
                    elif key == ord("m"):
                        self.toggle_model()
                    elif key == ord("1"):
                        self.conf_thresh = 0.10
                        logger.info("Confidence set to: 0.10")
                    elif key == ord("2"):
                        self.conf_thresh = 0.20
                        logger.info("Confidence set to: 0.20")
                    elif key == ord("3"):
                        self.conf_thresh = 0.30
                        logger.info("Confidence set to: 0.30")
                    elif key == ord("5"):
                        self.conf_thresh = 0.05
                        logger.info("Confidence set to: 0.05")
                    elif key == ord("0"):
                        self.conf_thresh = 0.02
                        logger.info("Confidence set to: 0.02 (high sensitivity)")
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, stopping...")
        finally:
            self.stop()

    def stop(self):
        """Clean shutdown of camera, network, and servers."""
        if not self.running:
            return
        self.running = False
        logger.info("Shutting down live drone detector...")
        if self.show_gui:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        self.web_server.stop()
        if self.adapter:
            try:
                self.adapter.stop()
            except Exception as e:
                logger.warning(f"Error stopping adapter: {e}")
        logger.info("Live drone detector stopped successfully.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Live Drone Object Detection Feed using YOLOv26m and Turbodrone",
    )
    parser.add_argument(
        "--drone-type",
        type=str,
        default=os.getenv("DRONE_TYPE", "wifi_cam"),
        help="Drone type (wifi_cam, s2x, wifi_uav, cooingdv, x69_lg; default: wifi_cam)",
    )
    parser.add_argument(
        "--drone-ip",
        type=str,
        default=os.getenv("DRONE_IP", "192.168.4.153"),
        help="Drone IP address (default: 192.168.4.153)",
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=int(os.getenv("CONTROL_PORT", "8090")),
        help="Drone control port (default: 8090 for wifi_cam)",
    )
    parser.add_argument(
        "--video-port",
        type=int,
        default=int(os.getenv("VIDEO_PORT", "8080")),
        help="Drone video port (default: 8080 for wifi_cam)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.getenv("YOLO_WEIGHTS", None),
        help="Path to YOLO model.pt (default: auto-detected)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.15,
        help="Confidence threshold for detection (default: 0.15)",
    )
    parser.add_argument(
        "--iou",
        type=float,
        default=0.50,
        help="NMS IoU threshold (default: 0.50)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=256,
        help="Inference image resolution (default: 256)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8088,
        help="Web dashboard and MJPEG port (default: 8088)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Disable desktop OpenCV GUI window (runs web server only)",
    )
    parser.add_argument(
        "--rotate",
        type=int,
        default=None,
        help="Camera rotation degrees (e.g. -90, 0, 90, 180)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    detector = LiveDroneDetector(
        drone_type=args.drone_type,
        drone_ip=args.drone_ip,
        control_port=args.control_port,
        video_port=args.video_port,
        model_path=args.model,
        conf_thresh=args.conf,
        iou_thresh=args.iou,
        imgsz=args.imgsz,
        web_port=args.port,
        show_gui=not args.no_gui,
        rotate_degrees=args.rotate,
    )

    def sig_handler(sig, frame):
        logger.info(f"Signal {sig} trapped, exiting...")
        detector.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    detector.run()


if __name__ == "__main__":
    main()
