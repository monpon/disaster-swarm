import "./style.css";
import * as THREE from "three";
import { SimSocket } from "./net";
import { createStage, type Stage } from "./scene/setup";
import { RealView } from "./scene/realview";
import { MapView } from "./scene/mapview";
import { SwarmView } from "./scene/drones";
import { CommsLayer } from "./scene/comms";
import { CameraRig } from "./ui/camera";
import { ControlPanel, type ViewMode, type ViewSettings } from "./ui/controls";
import { Telemetry } from "./ui/telemetry";
import { MissionChart } from "./ui/charts";
import { FeedPanel } from "./ui/feed";
import {
  cameraModel,
  type BuildingInfo,
  type Candidate,
  type DroneState,
  type MapEntry,
  type ServerMessage,
  type SimConfig,
  type SnapshotMessage,
  type StateMessage,
} from "./types";

// Left: the real building with the drones flying. Right: the master's reconstruction.
const viewsEl = document.getElementById("views")!;
const real = createStage(document.getElementById("view-real")!);
const map = createStage(document.getElementById("view-map")!, "#06080d");
for (const st of [real, map]) st.renderer.localClippingEnabled = true;
map.renderer.shadowMap.enabled = false;

const realView = new RealView();
const mapView = new MapView();

/** Surface any failure on the page and report it to the server log. */
function report(text: string): void {
  try {
    navigator.sendBeacon("/clienterr", text);
  } catch {
    /* ignore */
  }
}
window.addEventListener("error", (e) => {
  report(`error: ${e.message} @ ${e.filename}:${e.lineno}`);
  let b = document.getElementById("err-banner");
  if (!b) {
    b = document.createElement("div");
    b.id = "err-banner";
    b.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99;background:#7a1a22;color:#fff;padding:6px 10px;font:12px monospace";
    document.body.appendChild(b);
  }
  b.textContent = `Viewer error: ${e.message}`;
});
window.addEventListener("unhandledrejection", (e) => report(`rejection: ${String(e.reason?.stack ?? e.reason)}`));
let nMsgs = 0;
setInterval(() => report(`diag: msgs=${nMsgs} cloud=${mapView.cloud?.count ?? "none"} view=${new URLSearchParams(location.search).toString()}`), 10000);
const swarmReal = new SwarmView();
const swarmMap = new SwarmView();
const commsReal = new CommsLayer();
const commsMap = new CommsLayer();
real.scene.add(realView.group, swarmReal.group, commsReal.group);
map.scene.add(mapView.group, swarmMap.group, commsMap.group);

let building: BuildingInfo | null = null;
let config: SimConfig | null = null;
let drones: DroneState[] = [];
let candidates: Candidate[] = [];
let entries: MapEntry[] = [];
let targets: [number, number, number, number][] = [];
let mesh: [number, number, number][] = [];
let found: number[] = [];
let cut = Infinity;
let lastRecolor = 0;
let worldToken = 0;
const pending: (StateMessage | SnapshotMessage)[] = [];

const telemetry = new Telemetry((id) => rig.follow(id));
const chart = new MissionChart(document.getElementById("chart")!);
const feed = new FeedPanel();
const net = new SimSocket(onMessage, (ok) => telemetry.connection(ok));
net.onOpen = () => net.select(swarmReal.selected);
const panel = new ControlPanel(net, {
  onView: applyView,
  onOverview: () => {
    active = real;
    rig.overview();
  },
});
const rig = new CameraRig(real, [swarmReal, swarmMap], (id) => {
  active = real;
  telemetry.renderCard(id);
  feed.select(id);
  net.select(id);
}, [map]);
feed.select(null);

// Camera sync: whichever view the user last touched drives the other.
let active: Stage = real;
real.controls.addEventListener("start", () => (active = real));
map.controls.addEventListener("start", () => {
  active = map;
  rig.unfollow();
});

function syncCamera(src: Stage, dst: Stage): void {
  dst.camera.position.copy(src.camera.position);
  dst.controls.target.copy(src.controls.target);
  dst.camera.quaternion.copy(src.camera.quaternion);
}

function cutHeight(v: ViewSettings): number {
  if (!building) return Infinity;
  if (v.floor === "all") return Infinity;
  if (v.floor === "roof off") return building.bbox[4];
  return Number(v.floor.slice(1)) * building.story;
}

function applyView(v: ViewSettings): void {
  viewsEl.className = `mode-${v.view}`;
  document.querySelectorAll<HTMLButtonElement>("#view-switch button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === v.view),
  );
  cut = cutHeight(v);
  const planes = Number.isFinite(cut) ? [new THREE.Plane(new THREE.Vector3(0, 0, -1), cut)] : [];
  realView.layer?.setClip(planes);
  mapView.setClip(planes);
  mapView.setPointSize(v.pointSize);
  mapView.setSmoothed(v.smoothed);
  mapView.setRender(v.mapRender);
  mapView.setDemo(v.demoClean);
  document.getElementById("demo-badge")!.style.display = v.demoClean ? "" : "none";
  document.getElementById("cut-label")!.textContent = v.floor === "all" ? "" : `cutaway: ${v.floor}`;
  for (const s of [swarmReal, swarmMap]) s.setScale(v.droneScale);
  for (const c of [commsReal, commsMap]) {
    c.routes.visible = v.links;
    c.mesh.visible = v.mesh;
  }
  Object.assign(mapView.layers, { shell: v.shell, targets: v.targets, entries: v.entries });
  mapView.staleAfter = v.staleAfter;
  if (mapView.mode !== v.mapColor) {
    mapView.mode = v.mapColor;
    mapView.recolor();
  }
  document.querySelectorAll<HTMLElement>(".legend [data-mode]").forEach((el) => {
    el.style.display = el.dataset.mode === v.mapColor ? "" : "none";
  });
  document.getElementById("legend-stale")!.textContent = `${v.staleAfter}s`;
}

function applyState(msg: StateMessage | SnapshotMessage): void {
  swarmReal.sync(msg.drones);
  // The map view shows where the master believes each drone is (its VIO estimate).
  swarmMap.sync(msg.drones.map((d) => ({ ...d, p: d.ep, q: d.eq })));
  mapView.setClock(msg.metrics.t, msg.metrics.running, msg.metrics.rtf);
  mapView.applyDeltas(msg.map);
  if (msg.seen) mapView.applySeen(msg.seen);
  drones = msg.drones;
  candidates = msg.candidates;
  entries = msg.entries;
  targets = msg.targets;
  mesh = msg.mesh ?? [];
  found = msg.found;
  mapView.setEntries(entries);
  telemetry.metrics(msg.metrics);
  telemetry.drones(msg.drones, swarmReal.selected);
  telemetry.addEvents(msg.events);
  const frontier = targets.filter((t) => t[3] === 0).length;
  document.getElementById("map-stats")!.textContent =
    `${msg.map.ptotal.toLocaleString()} points · ${entries.length} entries · ` +
    `${frontier} frontier / ${targets.length - frontier} surface targets · ${candidates.filter((c) => c.confirmed).length} survivors`;
}

async function onWorld(b: BuildingInfo, cfg: SimConfig): Promise<void> {
  const token = ++worldToken;
  building = b;
  config = cfg;
  const cam = cameraModel(cfg);
  for (const s of [swarmReal, swarmMap]) {
    s.clear();
    s.camera = cam;
  }
  mapView.build(b, cfg);
  await realView.build(b);
  if (token !== worldToken) return;
  if (realView.vox) mapView.setTrueModel(b, realView.vox);
  const [x0, y0, x1, y1] = b.bbox;
  rig.overviewTarget.set((x0 + x1) / 2, (y0 + y1) / 2, 2);
  rig.overviewPos.set(x0 - 45, y0 - 60, 85);
  panel.setFloors(b.floors);
  rig.unfollow();
  feed.select(null);
  telemetry.clearEvents();
  applyView(panel.view);
  // States that arrived while the building was decompressing.
  for (const m of pending.splice(0)) handleState(m);
}

function handleState(msg: StateMessage | SnapshotMessage): void {
  nMsgs++;
  if (msg.type === "snapshot") {
    chart.reset(msg.history);
    applyState(msg);
    panel.syncFromServer(config, msg.metrics.running, msg.metrics.speed);
  } else {
    applyState(msg);
    chart.push(msg.history);
  }
}

let firstWorld = true;
function onMessage(msg: ServerMessage): void {
  switch (msg.type) {
    case "world":
      pending.length = 0;
      void onWorld(msg.building, msg.config).then(() => {
        if (firstWorld) {
          firstWorld = false;
          rig.overview(true);
          syncCamera(real, map);
        }
      });
      break;
    case "snapshot":
    case "state":
      if (!realView.layer || pending.length) pending.push(msg);
      else handleState(msg);
      break;
    case "feed":
      if (msg.drone === swarmReal.selected) feed.show(msg);
      break;
  }
}

const VIEWS: ViewMode[] = ["split", "real", "map"];
document.querySelectorAll<HTMLButtonElement>("#view-switch button").forEach((b) =>
  b.addEventListener("click", () => {
    panel.view.view = b.dataset.view as ViewMode;
    panel.gui.controllersRecursive().forEach((c) => c.updateDisplay());
    applyView(panel.view);
  }),
);

window.addEventListener("keydown", (e) => {
  if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "SELECT") return;
  if (e.code === "Space") {
    e.preventDefault();
    panel.togglePlay();
  } else if (e.key === "Tab") {
    e.preventDefault();
    panel.cycle("view", VIEWS);
  } else if (e.key === "f" || e.key === "F") {
    const floors = building ? Array.from({ length: building.floors }, (_, i) => `F${i + 1}`) : [];
    panel.cycle("floor", ["all", "roof off", ...floors.reverse()]);
  } else if (e.key === "c" || e.key === "C") {
    panel.cycle("mapColor", ["texture", "quality", "freshness", "confidence"]);
  } else if (e.key === "Escape") {
    rig.unfollow();
  } else if (e.key === "o" || e.key === "O") {
    active = real;
    rig.overview();
  } else if (/^[0-9]$/.test(e.key)) {
    const id = Number(e.key);
    if (swarmReal.get(id)) rig.follow(id);
  }
});

const visible = (st: Stage) => st.renderer.domElement.parentElement!.clientWidth > 0;

const clock = new THREE.Clock();
function frame(): void {
  const dt = Math.min(clock.getDelta(), 0.1);
  const t = clock.elapsedTime;
  if (active === map && rig.following === null) {
    map.controls.update();
    syncCamera(map, real);
  } else {
    rig.update();
    syncCamera(real, map);
  }
  const v = panel.view;
  swarmReal.update(dt, v);
  swarmMap.update(dt, v);
  if (building) {
    commsReal.update(drones, mesh, swarmReal.positions(), building.base, swarmReal.selected);
    commsMap.update(drones, mesh, swarmMap.positions(), building.base, swarmMap.selected);
  }
  realView.updateMarkers(found, t, cut, v.survivorsTruth);
  mapView.setTargets(targets, cut);
  mapView.setCandidates(candidates, t, cut);
  mapView.update();
  // Freshness colors age continuously; repaint a few times a second.
  if (v.mapColor === "freshness" && performance.now() - lastRecolor > 500) {
    lastRecolor = performance.now();
    mapView.recolor();
  }
  for (const st of [real, map]) {
    if (!visible(st)) continue;
    st.renderer.render(st.scene, st.camera);
    st.labels.render(st.scene, st.camera);
  }
  requestAnimationFrame(frame);
}
frame();
