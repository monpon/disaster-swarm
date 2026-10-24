"""Simulated radio link with fixed latency, jitter and random packet loss."""
from __future__ import annotations

from typing import Any

import numpy as np


class Link:
    def __init__(self, latency: float, dropout: float, rng: np.random.Generator):
        self.latency = latency
        self.dropout = dropout
        self.rng = rng
        self.queue: list[tuple[float, Any]] = []
        self.sent = 0
        self.dropped = 0
        self.bytes = 0

    def send(self, t: float, payload: Any, size: int = 0) -> None:
        self.sent += 1
        self.bytes += size
        if self.rng.random() < self.dropout:
            self.dropped += 1
            return
        jitter = self.rng.uniform(0, 0.25 * self.latency)
        self.queue.append((t + self.latency + jitter, payload))

    def receive(self, t: float) -> list[Any]:
        if not self.queue:
            return []
        ready = [p for (when, p) in self.queue if when <= t]
        self.queue = [(when, p) for (when, p) in self.queue if when > t]
        return ready
