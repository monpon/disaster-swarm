import numpy as np

from disaster_sim.config import SimConfig
from disaster_sim.control import FlightController
from disaster_sim.mapping import FREE, OBSTACLE, UNKNOWN, OccupancyGrid
from disaster_sim.physics import QuadrotorFleet
from disaster_sim.planner import astar, blocked_mask, find_frontiers
from disaster_sim.sensors import Camera
from disaster_sim.sim import Simulation
from disaster_sim.world import generate_world


def fly(setpoints, seconds=15.0, wind=(3.0, 1.0, 0.0), dt=0.01):
    n = len(setpoints)
    fleet = QuadrotorFleet(n, np.zeros((n, 3)))
    fc = FlightController(n)
    fc.armed[:] = True
    fc.pos_sp[:] = setpoints
    for _ in range(int(seconds / dt)):
        fc.update(fleet, dt)
        fleet.step(dt, np.array(wind))
    return fleet


def test_hover_holds_altitude_in_wind():
    fleet = fly([[0, 0, 10]])
    assert np.allclose(fleet.pos[0], [0, 0, 10], atol=0.1)
    assert np.linalg.norm(fleet.vel[0]) < 0.05
    assert not fleet.crashed.any()


def test_reaches_waypoint():
    fleet = fly([[40, -30, 25]], seconds=20)
    assert np.linalg.norm(fleet.pos[0] - [40, -30, 25]) < 0.3


def test_astar_avoids_obstacles():
    blocked = np.zeros((30, 30), dtype=bool)
    blocked[10, 0:25] = True  # wall with a gap at the top
    path = astar(blocked, (5, 5), (15, 5))
    assert path is not None
    for a, b in zip(path, path[1:]):
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2 + 1
        xs = np.rint(np.linspace(a[0], b[0], n)).astype(int)
        ys = np.rint(np.linspace(a[1], b[1], n)).astype(int)
        assert not blocked[xs, ys].any()


def test_blocked_mask_respects_altitude():
    g = OccupancyGrid(10)
    g.state[5, 5], g.height[5, 5] = OBSTACLE, 20.0
    assert blocked_mask(g, 20.0)[5, 5]
    assert not blocked_mask(g, 30.0)[5, 5]


def test_grid_merge_keeps_first_observation():
    a, b = OccupancyGrid(8), OccupancyGrid(8)
    m = np.zeros((8, 8), dtype=bool)
    m[0:2, 0:2] = True
    a.observe(m, np.full((8, 8), 5.0, dtype=np.float32), tick=1)
    m2 = np.zeros((8, 8), dtype=bool)
    m2[1:3, 1:3] = True
    b.observe(m2, np.zeros((8, 8), dtype=np.float32), tick=2)
    added = a.merge(b, tick=3)
    assert added == 3  # (1,1) was already known to a
    assert a.state[1, 1] == OBSTACLE and a.state[2, 2] == FREE
    assert a.state[5, 5] == UNKNOWN


def test_frontiers_surround_known_region():
    g = OccupancyGrid(40)
    g.state[15:25, 15:25] = FREE
    fr = find_frontiers(g)
    assert fr
    for f in fr:
        assert g.state[f.ix, f.iy] == UNKNOWN


def test_forward_camera_sees_ahead_not_behind():
    world = generate_world(SimConfig(seed=1))
    cam = Camera(world, np.random.default_rng(0), SimConfig())
    pos = np.array([world.base[0], world.base[1], 30.0])
    mask = cam.view(pos, 0.0)  # facing +x
    assert mask is not None
    ix, iy = np.nonzero(mask)
    xs, _ = world.cell_center(ix, iy)
    assert (xs > pos[0]).mean() > 0.95


def test_short_mission_runs_without_crashes():
    sim = Simulation(SimConfig(seed=2, n_drones=4))
    sim.advance(60)
    m = sim.metrics()
    assert m["crashed"] == 0
    assert m["coverage"] > 0.05
    assert m["airborne"] == 4
