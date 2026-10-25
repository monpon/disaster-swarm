"""Detector service: runs the Ultralytics model on batches of camera frames sent by the simulator over a local socket.

Run with an environment that has ultralytics + a CUDA torch (kept separate from the simulator's, so neither can break the
other):   python object_det/serve.py [--port 8765] [--model object_det/model.pt]
Protocol (multiprocessing.connection, localhost only): receive (shape, bytes) = n RGB uint8 frames, send back a list with
one (k, 6) array per frame: x1, y1, x2, y2, confidence, class (0 fire, 1 smoke, 2 person, 3 door).
"""
import argparse
import os
import sys
from multiprocessing.connection import Listener

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--model", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pt"))
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=320)
    args = ap.parse_args()
    from ultralytics import YOLO
    model = YOLO(args.model)
    model.predict(np.zeros((240, 320, 3), np.uint8), imgsz=args.imgsz, verbose=False, device=0)  # warm up
    listener = Listener(("127.0.0.1", args.port), authkey=b"swarm-detector")
    print(f"detector ready on 127.0.0.1:{args.port} ({args.model}; classes {model.names})", flush=True)
    while True:
        conn = listener.accept()
        try:
            while True:
                shape, buf = conn.recv()
                frames = np.frombuffer(buf, dtype=np.uint8).reshape(shape)
                bgr = [np.ascontiguousarray(f[:, :, ::-1]) for f in frames]   # ultralytics reads arrays as BGR
                res = model.predict(bgr, imgsz=args.imgsz, conf=args.conf, verbose=False, device=0, half=True)
                conn.send([np.c_[r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy()] for r in res])
        except (EOFError, ConnectionError):
            continue
        finally:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
