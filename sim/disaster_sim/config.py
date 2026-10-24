from dataclasses import dataclass, asdict, fields


@dataclass
class SimConfig:
    seed: int = 1
    n_drones: int = 6

    # World (meters). The world is a square centered on the origin, z is up.
    world_size: float = 200.0
    cell_size: float = 2.0
    n_survivors: int = 15
    max_building_height: float = 32.0

    # Wind: constant mean plus an Ornstein-Uhlenbeck gust process.
    wind_speed: float = 2.0
    wind_dir_deg: float = 30.0
    gust_strength: float = 1.0

    # Loop rates (Hz).
    physics_hz: int = 100
    autopilot_hz: int = 20
    sensor_hz: int = 10
    uplink_hz: int = 5
    master_hz: int = 2

    # Radio link between drones and the master computer.
    link_latency: float = 0.2
    link_dropout: float = 0.05

    # Vehicle.
    battery_wh: float = 15.0
    charge_time_s: float = 40.0
    rtb_reserve: float = 0.12
    max_speed: float = 8.0

    # Mission.
    cruise_alt: float = 36.0
    alt_layer_step: float = 3.0
    n_alt_layers: int = 5
    investigate_agl: float = 12.0

    # Forward-facing camera (gimbal-stabilized: follows heading, fixed downward pitch).
    cam_pitch_deg: float = 35.0
    cam_hfov_deg: float = 90.0
    cam_vfov_deg: float = 60.0
    cam_range: float = 60.0
    detect_range: float = 60.0
    confirm_range: float = 30.0

    # Scan quality: 1.0 within scan_near, 0 at cam_range; a cell counts as properly
    # scanned when measured from within proper_scan_range.
    scan_near: float = 8.0
    proper_scan_range: float = 24.0
    scan_agl: float = 12.0  # height above local structures for close scanning passes

    def to_dict(self) -> dict:
        return asdict(self)

    def updated(self, **changes) -> "SimConfig":
        names = {f.name: f.type for f in fields(self)}
        clean = {}
        for k, v in changes.items():
            if k not in names:
                continue
            current = getattr(self, k)
            clean[k] = type(current)(v)
        return SimConfig(**{**asdict(self), **clean})
