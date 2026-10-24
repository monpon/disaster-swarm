from dataclasses import asdict, dataclass, fields


@dataclass
class SimConfig:
    seed: int = 1
    n_drones: int = 16

    # Site and building (meters; voxels are 1 m). The site grid spans [0, site_x) x
    # [0, site_y) x [0, site_z); voxel layer z = 0 is the ground.
    site_x: int = 160
    site_y: int = 128
    site_z: int = 24
    building_x: int = 96
    building_y: int = 64
    floors: int = 3
    story: int = 5  # slab-to-slab; 1-voxel slab + 4 m clear
    n_survivors: int = 20

    # Wind (outdoors only; indoors is still air).
    wind_speed: float = 2.0
    wind_dir_deg: float = 30.0
    gust_strength: float = 0.8

    # Loop rates (Hz).
    physics_hz: int = 100
    autopilot_hz: int = 20
    camera_hz: int = 4
    telemetry_hz: int = 5
    master_hz: int = 2

    # Camera feed: low-res RGB-D frames streamed to the master.
    cam_w: int = 48
    cam_h: int = 32
    cam_hfov_deg: float = 90.0
    cam_vfov_deg: float = 64.0
    cam_range: float = 25.0
    cam_mount_tilt_deg: float = 0.0  # fixed camera mount, below the body's forward axis

    # Scan quality: 1.0 within scan_near, 0 at cam_range; proper scan within proper_scan_range.
    scan_near: float = 2.0
    proper_scan_range: float = 8.0

    # Radio.
    link_latency: float = 0.05
    link_dropout: float = 0.02

    # Vehicle.
    battery_wh: float = 20.0
    charge_time_s: float = 40.0
    rtb_reserve: float = 0.12
    max_speed: float = 6.0
    indoor_speed: float = 2.0

    def to_dict(self) -> dict:
        return asdict(self)

    def updated(self, **changes) -> "SimConfig":
        names = {f.name for f in fields(self)}
        clean = {k: type(getattr(self, k))(v) for k, v in changes.items() if k in names}
        return SimConfig(**{**asdict(self), **clean})
