"""Stand-in for esp32/relay.py to test live.py without hardware.

On stream start (42 76) to 127.0.0.1:8080 it streams chunked JPEG test frames in
the E58 format back to the sender, and sends synthetic IMU batches (18-byte
records, as the relay does) to the sender's IP on UDP 9101. The synthetic board
slides 0.3 m back and forth along x with 1 s pauses.

    python drone_control/imu/fake_relay.py &
    python drone_control/imu/live.py --relay 127.0.0.1
"""
import math
import socket
import struct
import subprocess
import threading
import time

CHUNK = 0x5B8
IMU_PORT = 9101


def test_frames(n=30):
    """n tiny JPEGs (moving bar) rendered by ffmpeg once at startup."""
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=15:duration={n / 15}",
         "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "6", "-"], capture_output=True, check=True).stdout
    frames, start = [], 0
    while (soi := out.find(b"\xff\xd8", start)) >= 0:
        eoi = out.find(b"\xff\xd9", soi)
        frames.append(out[soi:eoi + 2])
        start = eoi + 2
    return frames


def datagrams(fid, jpeg):
    parts = [jpeg[i:i + CHUNK] for i in range(0, len(jpeg), CHUNK)]
    for i, part in enumerate(parts):
        final = i == len(parts) - 1
        payload = part + (b"\x00" * (CHUNK - len(part)) if final else b"")   # final chunk is padded
        yield bytes([fid & 255, 1 if final else 0, len(parts), 1, 0, 0, 0, 0]) + payload


def imu_record(t_us, a, g):
    raw = [round(a[0] * 8192), round(a[1] * 8192), round(a[2] * 8192), 0,
           round(g[0] * 65.5), round(g[1] * 65.5), round(g[2] * 65.5)]
    return (t_us & 0xFFFFFFFF).to_bytes(4, "little") + struct.pack(">7h", *raw)


def accel_x(t):
    """Min-jerk 0.3 m slides: 1 s move, 1 s pause, alternating direction, after 3 s still."""
    if t < 3:
        return 0.0
    cycle, s = divmod(t - 3, 2.0)
    if s >= 1.0:
        return 0.0
    sign = 1 if int(cycle) % 2 == 0 else -1
    return sign * 0.3 * (60 * s - 180 * s ** 2 + 120 * s ** 3) / 9.80665


def main():
    video = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    video.bind(("127.0.0.1", 8080))
    imu = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    frames = test_frames()
    client = [None]

    def stream():
        fid = 0
        while True:
            if client[0]:
                for d in datagrams(fid, frames[fid % len(frames)]):
                    video.sendto(d, client[0])
                fid += 1
            time.sleep(1 / 15)

    def imu_stream():
        t0 = time.monotonic()
        batch = b""
        while True:
            t = time.monotonic() - t0
            batch += imu_record(int(t * 1e6), (accel_x(t), 0.0, 1.0), (0.3, -0.2, 0.1))
            if len(batch) == 18 * 10:
                if client[0]:
                    imu.sendto(batch, (client[0][0], IMU_PORT))
                batch = b""
            time.sleep(0.01)

    threading.Thread(target=stream, daemon=True).start()
    threading.Thread(target=imu_stream, daemon=True).start()
    print("fake relay on 127.0.0.1:8080", flush=True)
    while True:
        data, addr = video.recvfrom(64)
        if data == b"\x42\x76":
            client[0] = addr


if __name__ == "__main__":
    main()
