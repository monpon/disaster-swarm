"""Frame-integrity stats for wifi_cam video datagrams (8-byte header + JPEG chunk).

Header: [0]=frame id, [1]=1 on final chunk, [2]=total chunks, [3]=resolution, [7]=retain.
Chunks carry no index, so a lost chunk shows up as chunk count != total at the final chunk,
or as the frame id changing before a final chunk arrived.
"""
from __future__ import annotations

import time

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
HEADER = 8
CHUNK = 0x5B8


class FrameStats:
    def __init__(self, on_frame=None) -> None:
        self.on_frame = on_frame  # callback(jpeg bytes) for each intact frame
        self.ok = self.bad_count = self.bad_jpeg = self.abandoned = self.ignored = 0
        self.chunks = 0
        self.first_ts = self.last_ts = None
        self._fid = None
        self._n = 0
        self._buf = bytearray()

    def feed(self, pkt: bytes) -> None:
        if len(pkt) <= HEADER:
            self.ignored += 1
            return
        now = time.monotonic()
        self.first_ts = self.first_ts or now
        self.last_ts = now
        fid, final, total = pkt[0], pkt[1], pkt[2]
        if self._fid is not None and fid != self._fid and self._n:
            self.abandoned += 1          # previous frame never saw its final chunk
            self._reset()
        if self._fid is None:
            self._fid = fid
        self.chunks += 1
        self._n += 1
        self._buf += pkt[HEADER:]
        if final == 1 and total > 0:
            if self._n != total:
                self.bad_count += 1
            else:
                # Same rule as turbodrone: JPEG ends at the first EOI in the final chunk
                # (the rest of that chunk is padding).
                chunk = pkt[HEADER:]
                eoi = chunk.find(EOI)
                if eoi < 0:
                    self.bad_jpeg += 1
                else:
                    data = bytes(self._buf[: (self._n - 1) * CHUNK + eoi + 2])
                    if data.startswith(SOI) and data.endswith(EOI):
                        self.ok += 1
                        if self.on_frame:
                            self.on_frame(data)
                    else:
                        self.bad_jpeg += 1
            self._reset()

    def _reset(self) -> None:
        self._fid, self._n, self._buf = None, 0, bytearray()

    @property
    def frames(self) -> int:
        return self.ok + self.bad_count + self.bad_jpeg + self.abandoned

    def summary(self) -> dict:
        span = (self.last_ts - self.first_ts) if self.first_ts and self.last_ts else 0
        return {"frames": self.frames, "ok": self.ok, "bad_count": self.bad_count,
                "bad_jpeg": self.bad_jpeg, "abandoned": self.abandoned,
                "ok_pct": round(100 * self.ok / self.frames, 1) if self.frames else None,
                "ok_fps": round(self.ok / span, 1) if span > 1 else None}
