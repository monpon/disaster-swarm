"""Loopback end-to-end: DroneLink -> relay -> FakeDrone. No hardware, no root."""
import asyncio
import json
import socket
import threading
import time

from drone_link import DroneLink
from relay.fake_drone import FakeDrone
from relay.relay import Relay
from relay.telemetry import Sinks, Telemetry, decode_rc, fake_imu_enricher, host_enricher

DRONE_V, DRONE_C, LISTEN_V, LISTEN_C, TELE = 28080, 28090, 28081, 28091, 29100


def _run_relay(loop, relay):
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(relay.run())
    except (asyncio.CancelledError, RuntimeError):  # RuntimeError: loop.stop() at teardown
        pass


def test_end_to_end_forwarding_and_telemetry():
    tele_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tele_sock.bind(("127.0.0.1", TELE))
    tele_sock.settimeout(0.3)

    drone = FakeDrone("127.0.0.2", DRONE_V, DRONE_C).start()
    relay = Relay("127.0.0.2", {"video": (LISTEN_V, DRONE_V), "cmd": (LISTEN_C, DRONE_C)}, "127.0.0.1", "0.0.0.0",
                  Telemetry([host_enricher, fake_imu_enricher]), Sinks(("127.0.0.1", TELE), None, False), 0.25)
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_relay, args=(loop, relay), daemon=True)
    t.start()
    time.sleep(0.3)

    link = DroneLink("127.0.0.1", rate_hz=40, mode="short", video_port=LISTEN_V, cmd_port=LISTEN_C)
    link.set_axes(roll=90, pitch=110, throttle=128, yaw=150)
    link.start()
    time.sleep(0.5)
    link.takeoff()
    time.sleep(1.5)

    link.close()
    drone.close()
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)

    snaps = []
    tele_sock.settimeout(0.2)
    try:
        while True:
            snaps.append(json.loads(tele_sock.recvfrom(65535)[0]))
    except socket.timeout:
        pass

    # 1. video reached the client through the relay, unmodified in size
    assert link.stats.rx_packets > 50, link.stats
    assert 1472 in link.stats.rx_sizes
    # 2. RC reached the drone byte-for-byte and the takeoff flag survived
    assert len(drone.rc) > 20
    decoded = [decode_rc(d) for d, _ in drone.rc]
    assert all(d and (d["roll"], d["pitch"], d["yaw"]) == (90, 110, 150) for d in decoded)
    assert any(d["flags"] & 0x01 for d in decoded)
    # 3. telemetry stream carries counters, decoded RC and added info
    assert snaps, "no telemetry received"
    last = snaps[-1]
    assert last["relay"]["video_pkts"] > 50 and last["relay"]["rc_pkts"] > 20
    assert last["relay"]["sessions"] == 1
    assert last["rc"]["roll"] == 90
    assert last["extra"]["imu"]["fake"] is True and "cpu_temp_c" in last["extra"]["host"] or "load1" in last["extra"]["host"]
    assert [s["seq"] for s in snaps] == sorted(s["seq"] for s in snaps)


if __name__ == "__main__":
    test_end_to_end_forwarding_and_telemetry()
    print("ok")
