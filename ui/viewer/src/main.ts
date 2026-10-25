import "./style.css";
import * as THREE from "three";
import { SimSocket } from "./net";
import { DbNet } from "./db/dbnet";
import { createStage, type Stage } from "./scene/setup";
import { RealView } from "./scene/realview";
import { MapView } from "./scene/mapview";
import { PlanView } from "./scene/planview";
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
// `?embed=cloud`: just the master's point cloud on a transparent background, for the console to frame (it overlays the markers
// itself, from the camera matrix this page posts to its parent).
const embed = new URLSearchParams(location.search).get("embed") === "cloud";
if (embed) {
  document.body.classList.add("embed");
  document.documentElement.style.background = "transparent";
}
const viewsEl = document.getElementById("views")!;
const real = createStage(document.getElementById("view-real")!, undefined, false, true);
const map = createStage(document.getElementById("view-map")!, "#06080d", embed);
for (const st of [real, map]) st.renderer.localClippingEnabled = true;
map.renderer.shadowMap.enabled = false;

const realView = new RealView();
const mapView = new MapView();
const planView = new PlanView();

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
// Data source: SpacetimeDB when the server publishes into it (it says so at /config), else the simulator's websocket.
// `?source=ws` or `?source=db` overrides.
const qs = new URLSearchParams(location.search);
const source = qs.get("source") ?? (await fetch("/config").then((r) => r.json()).then((c) => c.source as string).catch(() => "ws"));
const dbSource = source === "db";
const net = dbSource ? null : new SimSocket((m) => onMessage(m), (ok) => telemetry.connection(ok));
if (net) net.onOpen = () => net.select(swarmReal.selected);
const dbNet = dbSource
  ? new DbNet((m) => onMessage(m), (ok) => telemetry.connection(ok),
              qs.get("stdb") ?? `ws://${location.hostname}:3000`, qs.get("db") ?? "swarm")
  : null;
const ctl = (dbNet ?? net)!;
const panel = new ControlPanel(ctl, {
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
  ctl.select(id);
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
  if (embed) v = { ...v, view: "map", demoClean: false, mapRender: "points", smoothed: true, floor: "all", pointSize: 0.35 };
  viewsEl.className = `mode-${v.view}`;
  document.querySelectorAll<HTMLButtonElement>("#view-switch button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === v.view),
  );
  cut = cutHeight(v);
  planView.visible = v.view === "plan";
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

let triageKey = "";

/** Confirmed survivors, most urgent first, with their (simulated) Presage vitals. */
function renderTriage(cands: Candidate[]): void {
  const rows = cands.filter((c) => c.confirmed).sort((a, b) => ((b.urgency ?? -1) - (a.urgency ?? -1)) || a.id - b.id);
  const key = JSON.stringify(rows.map((c) => [c.id, c.urgency, c.tier, c.vitals?.hr, c.vitals?.rr]));
  if (key === triageKey) return;
  triageKey = key;
  const body = document.getElementById("triage-body")!;
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="dim">no survivors found yet</td></tr>';
    return;
  }
  const story = building?.story ?? 4;
  body.innerHTML = rows.map((c) => {
    const tier = c.tier || "PENDING";
    const label = c.tier ? `${c.tier} ${c.urgency}` : "scanning…";
    return `<tr><td>#${c.id}</td><td>F${Math.floor(c.pos[2] / story) + 1}</td>` +
      `<td class="num">${c.vitals ? c.vitals.hr : "–"}</td><td class="num">${c.vitals ? c.vitals.rr.toFixed(0) : "–"}</td>` +
      `<td><span class="tier ${tier}">${label}</span></td></tr>`;
  }).join("");
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
  renderTriage(candidates);
  if (msg.plan) void planView.setPlan(msg.plan);
  entries = msg.entries;
  planView.draw(drones, entries, candidates);
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
  if (embed) mapView.cloud?.recolor(grey);
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
let worldKey = "";
function onMessage(msg: ServerMessage): void {
  if (msg.type === "world") {
    const key = `${JSON.stringify(msg.config)}|${msg.building.vox.length}`;
    if (key === worldKey) return;   // the same mission's world, already built
    worldKey = key;
  }
  switch (msg.type) {
    case "world":
      pending.length = 0;
      void onWorld(msg.building, msg.config).then(() => {
        if (firstWorld) {
          firstWorld = false;
          if (embed) {
            // a near-isometric view of the whole building
            const [x0, y0, x1, y1] = building!.bbox;
            const size = Math.max(x1 - x0, y1 - y0);
            map.controls.target.set((x0 + x1) / 2, (y0 + y1) / 2, 2);
            map.camera.fov = 28;
            map.camera.updateProjectionMatrix();
            map.camera.position.set((x0 + x1) / 2 - 0.62 * size * 1.9, (y0 + y1) / 2 - 0.78 * size * 1.9, size * 1.45);
            active = map;
          } else {
            rig.overview(true);
            syncCamera(real, map);
          }
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

const VIEWS: ViewMode[] = ["split", "real", "map", "plan"];
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

/** Grey point colours: the console draws the cloud as dark grey dots on its light map. */
function grey(_vox: number, r: number, g: number, b: number, out: Uint8Array): void {
  const l = (0.3 * r + 0.59 * g + 0.11 * b) / 255;
  out[0] = out[1] = out[2] = Math.round(70 + 90 * l);
}

let lastVp = "";
/** Only the cloud shows; tell the parent page how the camera projects so it can place its markers. */
function embedFrame(): void {
  for (const o of [swarmMap.group, commsMap.group]) o.visible = false;
  mapView.group.children.forEach((o) => {
    if (o !== mapView.cloud?.points) o.visible = false;
  });
  const cam = map.camera;
  cam.updateMatrixWorld();
  const vp = new THREE.Matrix4().multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse).toArray();
  const el = map.renderer.domElement;
  const key = `${vp.join(",")}|${el.clientWidth}x${el.clientHeight}`;
  if (key === lastVp) return;
  lastVp = key;
  parent.postMessage({ type: "swarm-cam", vp, w: el.clientWidth, h: el.clientHeight }, "*");
}

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
  if (embed) embedFrame();
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
