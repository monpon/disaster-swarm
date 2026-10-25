"""Optional video downscaler for the relay: reassemble wifi_cam JPEG frames, shrink, re-chunk.

Output uses the drone's own packet format (8-byte header + 0x5B8-byte chunks, final chunk marked),
so existing clients decode it unchanged. The drone link itself is unaffected: the drone still sends
full-size frames; this only reduces what goes out to clients.
"""
from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

HEADER, CHUNK = 8, 0x5B8
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class FrameAssembler:
    """Same completeness rule as drone_link.video.FrameStats and turbodrone."""

    def __init__(self) -> None:
        self._fid = None
        self._n = 0
        self._buf = bytearray()

    def feed(self, pkt: bytes):
        """Return (jpeg_bytes, header[3:8]) when a frame completes intact, else None."""
        if len(pkt) <= HEADER:
            return None
        fid, final, total = pkt[0], pkt[1], pkt[2]
        if self._fid is not None and fid != self._fid:
            self._reset()                      # previous frame lost its final chunk
        self._fid = fid
        self._n += 1
        self._buf += pkt[HEADER:]
        if final == 1 and total > 0:
            ok = self._n == total
            chunk = pkt[HEADER:]
            eoi = chunk.find(EOI)
            data = bytes(self._buf[: (self._n - 1) * CHUNK + eoi + 2]) if eoi >= 0 else b""
            self._reset()
            if ok and data.startswith(SOI) and data.endswith(EOI):
                return data, bytes(pkt[3:8])
        return None

    def _reset(self) -> None:
        self._fid, self._n, self._buf = None, 0, bytearray()


def jpeg_size(data: bytes):
    """(width, height) from the SOF marker without decoding."""
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def downscale(jpeg: bytes, size: tuple[int, int], quality: int) -> bytes:
    im = Image.open(io.BytesIO(jpeg))
    im.draft("RGB", size)                      # DCT-domain shrink: cheap on small CPUs
    if im.size != size:
        im = im.resize(size, Image.BILINEAR)
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()


def chunk_frame(jpeg: bytes, fid: int, hdr5: bytes) -> list[bytes]:
    parts = [jpeg[i:i + CHUNK] for i in range(0, len(jpeg), CHUNK)]
    total = len(parts)
    return [bytes([fid & 0xFF, 1 if i == total - 1 else 0, total]) + hdr5 + p for i, p in enumerate(parts)]


class Transcoder:
    """One worker thread, latest-frame-wins: if a frame is still being processed, new ones are dropped."""

    def __init__(self, size=(320, 240), quality=60, max_backlog=2) -> None:
        self.size, self.quality, self.max_backlog = size, quality, max_backlog
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending = 0
        self.fid = 0
        self.stats = {"frames_in": 0, "frames_out": 0, "frames_dropped_busy": 0,
                      "bytes_in": 0, "bytes_out": 0, "ms_total": 0.0, "native": None}

    def submit(self, jpeg: bytes, hdr5: bytes, emit) -> None:
        st = self.stats
        st["frames_in"] += 1
        st["bytes_in"] += len(jpeg)
        if st["native"] is None:
            st["native"] = jpeg_size(jpeg)
        if self.pending >= self.max_backlog:
            st["frames_dropped_busy"] += 1
            return
        self.pending += 1

        def work():
            t0 = time.perf_counter()
            try:
                small = downscale(jpeg, self.size, self.quality)
                self.fid = (self.fid + 1) & 0xFF
                pkts = chunk_frame(small, self.fid, hdr5)
                st["frames_out"] += 1
                st["bytes_out"] += len(small)
                st["ms_total"] += (time.perf_counter() - t0) * 1000
                emit(pkts)
            finally:
                self.pending -= 1
        self.pool.submit(work)

    def summary(self) -> dict:
        st, n = self.stats, max(self.stats["frames_out"], 1)
        return {**st, "ms_per_frame": round(st["ms_total"] / n, 2),
                "bytes_in_per_frame": st["bytes_in"] // max(st["frames_in"], 1),
                "bytes_out_per_frame": st["bytes_out"] // n}
