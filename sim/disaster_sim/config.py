from dataclasses import asdict, dataclass, fields

# Building types to map. Each sets the footprint, floors, story height and how the interior is divided,
# cluttered and damaged (the site grid is 160 x 128 x 24 m, so floors * story must stay <= 22).
PRESETS = {
    "factory": dict(label="Factory", desc="3 floors, rooms and a big machinery hall, shafts, one blocked dock, a collapsed corner",
                    building_x=96, building_y=64, floors=3, story=5, min_room=8, clutter=1.0, damage=1,
                    broken_windows=0.22, open_plan=False, n_survivors=20),
    "warehouse": dict(label="Warehouse", desc="1 tall floor, a few huge bays packed with shelving, loading docks",
                      building_x=112, building_y=72, floors=1, story=12, min_room=18, clutter=1.7, damage=1,
                      broken_windows=0.0, open_plan=False, n_survivors=16),
    "hangar": dict(label="Hangar", desc="one enormous open hall, 14 m ceiling, machinery and tanks, no interior walls",
                   building_x=104, building_y=80, floors=1, story=14, min_room=40, clutter=0.9, damage=1,
                   broken_windows=0.0, open_plan=True, n_survivors=12),
    "office": dict(label="Office block", desc="4 floors of small rooms and corridors, light furniture, many broken windows",
                   building_x=80, building_y=56, floors=4, story=4, min_room=6, clutter=0.6, damage=1,
                   broken_windows=0.35, open_plan=False, n_survivors=24),
    "hospital": dict(label="Hospital", desc="2 floors, dense ward rooms off corridors, stair shafts, tight doorways",
                     building_x=88, building_y=60, floors=2, story=5, min_room=6, clutter=0.7, damage=1,
                     broken_windows=0.15, open_plan=False, n_survivors=24),
    "collapsed": dict(label="Collapsed factory", desc="the factory after a quake: extra holes through floors, rubble, several blocked entries",
                      building_x=96, building_y=64, floors=3, story=5, min_room=8, clutter=1.6, damage=3,
                      broken_windows=0.45, open_plan=False, n_survivors=20),
}


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
    preset: str = "factory"  # building type, see PRESETS
    min_room: int = 8  # smallest room dimension the floor plan may produce (m)
    clutter: float = 1.0  # furniture / machinery / shelving density
    damage: int = 1  # collapse severity: holes through slabs, rubble, blocked entries
    broken_windows: float = 0.22  # share of upper-floor windows that are broken out
    open_plan: bool = False  # no interior walls: one big hall per floor

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
    cam_w: int = 360
    cam_h: int = 240
    cam_hfov_deg: float = 90.0
    cam_vfov_deg: float = 64.0
    cam_range: float = 100.0  # effectively unlimited: past the far wall of any of the buildings
    cam_mount_tilt_deg: float = 0.0  # fixed camera mount, below the body's forward axis
    jpeg_bytes: int = 14000

    # Central-node perception (simulated stand-ins, see estimation.py).
    vio_drift: float = 0.05  # VIO position random walk, m per sqrt(m) flown
    vio_yaw_drift: float = 0.0012  # VIO heading random walk, rad per sqrt(m) flown
    depth_scale_sigma: float = 0.05  # monocular depth: per-frame scale error (log-normal)
    depth_region_sigma: float = 0.06  # monocular depth: blocky relative error
    depth_max: float = 100.0  # monocular depth is ignored beyond this

    # Scan quality: 1.0 within scan_near, 0 at cam_range; proper scan within proper_scan_range.
    scan_near: float = 2.0
    scan_far: float = 40.0  # scan quality reaches 0 here (independent of how far the camera sees)
    proper_scan_range: float = 14.0

    # Radio.
    link_latency: float = 0.05
    link_dropout: float = 0.02

    # Vehicle.
    battery_wh: float = 2.0  # ~8-10 min for a 150 g drone
    charge_time_s: float = 40.0
    rtb_reserve: float = 0.12
    max_speed: float = 6.0
    indoor_speed: float = 1.5

    # What the master knows before launch. True: the operator's rough footprint of the building
    # (so every drone has a perimeter leg from the first second). False: nothing, and the swarm
    # scouts the site to find it first.
    known_outline: bool = True
    plan_assist: bool = False  # the operator also gives the building plan's openings: doors, docks, windows, hatch (demo)
    scout_alt: float = 6.0
    scout_spacing: float = 16.0
    scout_max_s: float = 600.0  # cap on scouting the site
    operate_max_s: float = 1500.0  # cap on the main mapping phase
    survey_max_s: float = 600.0  # cap on the exterior survey before going in regardless

    # Multi-pass mapping.
    verify_max_s: float = 240.0  # cap on the final verification sweep

    def to_dict(self) -> dict:
        return asdict(self)

    def updated(self, **changes) -> "SimConfig":
        names = {f.name for f in fields(self)}
        clean = {k: type(getattr(self, k))(v) for k, v in changes.items() if k in names}
        base = asdict(self)
        if clean.get("preset", self.preset) != self.preset and clean["preset"] in PRESETS:
            base.update({k: v for k, v in PRESETS[clean["preset"]].items() if k in names})  # a new building type
        return SimConfig(**{**base, **clean})
