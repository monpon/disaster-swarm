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
    telemetry_hz: int = 20  # ESP IMU batches (and the master's stick-command rate)
    master_hz: int = 2

    # Camera feed: monocular JPEG frames forwarded by the ESP. The master analyzes them at
    # cam_w x cam_h (the wire stream is ~320x240 JPEG of about jpeg_bytes per frame).
    cam_w: int = 48
    cam_h: int = 32
    cam_hfov_deg: float = 90.0
    cam_vfov_deg: float = 64.0
    cam_range: float = 25.0
    cam_mount_tilt_deg: float = 0.0  # fixed camera mount, below the body's forward axis
    jpeg_bytes: int = 12000

    # Central-node perception (simulated stand-ins, see estimation.py).
    vio_drift: float = 0.05  # VIO position random walk, m per sqrt(m) flown
    vio_yaw_drift: float = 0.0012  # VIO heading random walk, rad per sqrt(m) flown
    depth_scale_sigma: float = 0.05  # monocular depth: per-frame scale error (log-normal)
    depth_region_sigma: float = 0.06  # monocular depth: blocky relative error
    depth_max: float = 12.0  # monocular depth is ignored beyond this

    # Scan quality: 1.0 within scan_near, 0 at cam_range; proper scan within proper_scan_range.
    scan_near: float = 2.0
    proper_scan_range: float = 8.0

    # Radio.
    link_latency: float = 0.05
    link_dropout: float = 0.02

    # Vehicle.
    battery_wh: float = 2.0  # ~8-10 min for a 150 g drone
    charge_time_s: float = 40.0
    rtb_reserve: float = 0.12
    max_speed: float = 6.0
    indoor_speed: float = 1.5

    # What the master knows before launch: nothing about the building (it scouts for it). Set
    # known_outline to hand it the footprint instead.
    known_outline: bool = False
    scout_alt: float = 6.0
    scout_spacing: float = 16.0
    scout_max_s: float = 600.0  # cap on scouting the site
    survey_max_s: float = 600.0  # cap on the exterior survey before going in regardless

    # Multi-pass mapping.
    verify_max_s: float = 240.0  # cap on the final verification sweep

    def to_dict(self) -> dict:
        return asdict(self)

    def updated(self, **changes) -> "SimConfig":
        names = {f.name for f in fields(self)}
        clean = {k: type(getattr(self, k))(v) for k, v in changes.items() if k in names}
        return SimConfig(**{**asdict(self), **clean})
