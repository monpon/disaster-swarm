"""An RC-only link: the same packets and flags as drone_link.DroneLink, but it never asks for video, listens for none, and
never sends the stream-stop on close, so it can share a client address with the live video page without disturbing it."""
from __future__ import annotations

import threading

from drone_link.link import DroneLink


class ControlLink(DroneLink):
    def start(self) -> None:
        t = threading.Thread(target=self._tx_loop, name="rc-tx", daemon=True)
        t.start()
        self._threads = [t]

    def close(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=1.0)
        self.sock.close()
