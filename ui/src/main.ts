import "./style.css";
import * as THREE from "three";
import { SimSocket } from "./net";
import { createStage, type Stage } from "./scene/setup";
import { WorldView } from "./scene/world";
import { FogLayer } from "./scene/fog";
import { SwarmView } from "./scene/drones";
import { MapView } from "./scene/mapview";
import { Freshness } from "./scene/freshness";
import { CameraRig } from "./ui/camera";
import { ControlPanel, type ViewSettings } from "./ui/controls";
import { Telemetry } from "./ui/telemetry";
import { MissionChart } from "./ui/charts";
import {
  cameraModel,
  type Candidate,
  type DroneState,
  type ServerMessage,
  type SimConfig,
  type SnapshotMessage,
  type StateMessage,
} from "./types";

// Left: the real world with the drones flying. Right: the master's fused map, built live.
const flight = createStage(document.getElementById("view-flight")!);
const map = createStage(document.getElementById("view-map")!, "#06080d");
map.renderer.shadowMap.enabled = false;

const worldView = new WorldView();
const swarm = new SwarmView();
flight.scene.add(worldView.group, swarm.group);
const mapView = new MapView();
map.scene.add(mapView.group);

let fog: FogLayer | null = null;
const fresh = new Freshness();
let lastPaint = 0;
let config: SimConfig | null = null;
let candidates: Candidate[] = [];
let found: number[] = [];
let drones: DroneState[] = [];
let frontiers: [number, number, number][] = [];

const telemetry = new Telemetry((id) => rig.follow(id));
const chart = new MissionChart(document.getElementById("chart")!);
const net = new SimSocket(onMessage, (ok) => telemetry.connection(ok));
const panel = new ControlPanel(net, {
  onView: applyView,
  onOverview: () => {
    active = flight;
    rig.overview();
  },
});
const rig = new CameraRig(flight, swarm, (id) => {
  active = flight;
  telemetry.renderCard(id);
});

// Camera sync: whichever view the user last touched drives the other.
let active: Stage = flight;
flight.controls.addEventListener("start", () => (active = flight));
map.controls.addEventListener("start", () => {
  active = map;
  if (panel.view.syncCameras) rig.unfollow();
});

function syncCamera(src: Stage, dst: Stage): void {
  dst.camera.position.copy(src.camera.position);
  dst.controls.target.copy(src.controls.target);
  dst.camera.quaternion.copy(src.camera.quaternion);
}

function applyView(v: ViewSettings): void {
  swarm.setScale(v.droneScale);
  if (fog) {
    fog.fog = v.fog;
    fog.freshness = v.freshFlight;
    fog.paint(fresh, v.staleAfter);
  }
  mapView.paintFreshness(fresh, v.staleAfter, v.freshMap);
  document.getElementById("legend-fresh")!.style.display = v.freshMap ? "" : "none";
  document.getElementById("legend-fresh-max")!.textContent = `${v.staleAfter}s`;
  worldView.setVisibility(v.truth, v.fog, fog);
  Object.assign(mapView.layers, { frontiers: v.frontiers, frustums: v.footprints, paths: v.paths, labels: v.labels });
}

function applyState(msg: StateMessage | SnapshotMessage): void {
  swarm.sync(msg.drones);
  if (fog && fog.apply(msg.map)) worldView.reveal(fog);
  mapView.applyCells(msg.map);
  if (msg.seen) fresh.setSeen(msg.seen);
  fresh.setClock(msg.metrics.t, msg.metrics.running, msg.metrics.rtf);
  drones = msg.drones;
  candidates = msg.candidates;
  found = msg.found;
  frontiers = msg.frontiers;
  telemetry.metrics(msg.metrics);
  telemetry.drones(msg.drones, swarm.selected);
  telemetry.addEvents(msg.events);
  document.getElementById("map-stats")!.textContent =
    `${mapView.knownCells.toLocaleString()} cells mapped · ${mapView.obstacleCells.toLocaleString()} obstacle · ` +
    `${frontiers.length} frontiers · ${candidates.filter((c) => c.confirmed).length} survivors`;
}

function onMessage(msg: ServerMessage): void {
  switch (msg.type) {
    case "world": {
      config = msg.config;
      const cam = cameraModel(config);
      swarm.clear();
      swarm.camera = cam;
      worldView.build(msg.world, msg.pads);
      mapView.build(msg.world, msg.pads, cam);
      if (fog) {
        flight.scene.remove(fog.mesh);
        fog.dispose();
      }
      fog = new FogLayer(msg.world);
      fresh.reset();
      flight.scene.add(fog.mesh);
      rig.unfollow();
      telemetry.clearEvents();
      applyView(panel.view);
      break;
    }
    case "snapshot":
      chart.reset(msg.history);
      applyState(msg);
      panel.syncFromServer(config, msg.metrics.running, msg.metrics.speed);
      break;
    case "state":
      applyState(msg);
      chart.push(msg.history);
      break;
  }
}

window.addEventListener("keydown", (e) => {
  if ((e.target as HTMLElement).tagName === "INPUT") return;
  if (e.code === "Space") {
    e.preventDefault();
    panel.togglePlay();
  } else if (e.key === "Escape") {
    rig.unfollow();
  } else if (e.key === "o" || e.key === "O") {
    active = flight;
    rig.overview();
  } else if (/^[0-9]$/.test(e.key)) {
    const id = Number(e.key);
    if (swarm.get(id)) rig.follow(id);
  }
});

const clock = new THREE.Clock();
function frame(): void {
  const dt = Math.min(clock.getDelta(), 0.1);
  const t = clock.elapsedTime;
  if (panel.view.syncCameras && active === map) {
    map.controls.update();
    syncCamera(map, flight);
  } else {
    rig.update();
    if (panel.view.syncCameras) syncCamera(flight, map);
    else map.controls.update();
  }
  swarm.update(dt, worldView.antenna, panel.view);
  worldView.updateMarkers(candidates, found, t);
  mapView.update(drones, swarm, frontiers, candidates, t);
  // Freshness colors age continuously; repaint the grids a few times a second.
  if (performance.now() - lastPaint > 200) {
    lastPaint = performance.now();
    const v = panel.view;
    mapView.paintFreshness(fresh, v.staleAfter, v.freshMap);
    if (fog && (v.freshFlight || v.fog)) fog.paint(fresh, v.staleAfter);
  }
  for (const st of [flight, map]) {
    st.renderer.render(st.scene, st.camera);
    st.labels.render(st.scene, st.camera);
  }
  requestAnimationFrame(frame);
}
frame();
