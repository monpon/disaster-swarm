import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { decodeB64, type BuildingInfo, type Candidate, type MapDeltas, type MapEntry, type SeenDeltas, type SimConfig } from "../types";
import { siteDressing } from "./realview";
import { PointCloud } from "./pointcloud";
import { SurfaceLayer } from "./surface";
import { VoxelLayer } from "./voxels";

export type ColorMode = "texture" | "quality" | "freshness" | "confidence";

const SEEN_UNITS_PER_S = 2; // must match sim/disaster_sim/protocol.py
const MAX_TARGETS = 600;

const FRESH = new THREE.Color("#3ddc97");
const MID = new THREE.Color("#e8d44d");
const STALE = new THREE.Color("#ff4d4f");
const ANCIENT = new THREE.Color("#7a1a22");
const NEVER = new THREE.Color("#3a4152");

/** Green (just scanned) -> yellow -> red (stale) -> dark red (twice the stale time). */
export function freshnessColor(age: number, staleAfter: number, out = new THREE.Color()): THREE.Color {
  const k = Math.max(age, 0) / staleAfter;
  if (k <= 0.5) return out.copy(FRESH).lerp(MID, k * 2);
  if (k <= 1) return out.copy(MID).lerp(STALE, (k - 0.5) * 2);
  return out.copy(STALE).lerp(ANCIENT, Math.min(k - 1, 1));
}

function qualityColor(q: number, threshold: number, out: THREE.Color): THREE.Color {
  if (q >= threshold) return out.copy(MID).lerp(FRESH, Math.min((q - threshold) / Math.max(1 - threshold, 1e-3) * 1.5, 1));
  return out.copy(STALE).lerp(MID, q / threshold);
}

/** The master's reconstruction, built point by point from the depth pixels the drones sent
 * back. Per-voxel scan quality and freshness (from the master's occupancy map) drive the
 * alternative color modes. */
export class MapView {
  readonly group = new THREE.Group();
  cloud: PointCloud | null = null;
  readonly surf = new SurfaceLayer();
  renderMode: "auto" | "points" | "surface" | "both" = "auto";
  pointSize = 0.3;
  private clip: THREE.Plane[] = [];
  mode: ColorMode = "texture";
  staleAfter = 120;
  layers = { shell: true, targets: true, entries: true };
  private rgb = new Uint16Array(0);
  private q = new Uint8Array(0);
  private seen = new Uint16Array(0);
  // Demo render: the true building's voxels, shown only where the master has scanned (ideal geometry, not the raw mesh)
  private demo: VoxelLayer | null = null;
  private demoVox: Uint8Array | null = null;
  private demoShape: [number, number, number] = [0, 0, 0];
  private demoShown = new Uint8Array(0);
  private demoTints: THREE.Color[] = [];
  demoOn = false;
  private threshold = 0.74;
  private shell = new THREE.Group();
  private dressing: THREE.Group | null = null;
  private targets: THREE.Points;
  private entryGroup = new THREE.Group();
  private entryKeys = "";
  private candGroup = new THREE.Group();
  private candMeshes = new Map<number, THREE.Mesh>();
  private simNow = 0;
  private wallAt = 0;
  private rate = 0;

  constructor() {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_TARGETS * 3), 3));
    geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(MAX_TARGETS * 3), 3));
    this.targets = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ size: 0.7, vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false }),
    );
    this.targets.frustumCulled = false;
    this.group.add(this.shell, this.targets, this.entryGroup, this.candGroup, this.surf.group);
  }

  build(b: BuildingInfo, cfg: SimConfig): void {
    this.clear();
    const n = b.shape[0] * b.shape[1] * b.shape[2];
    this.rgb = new Uint16Array(n);
    this.q = new Uint8Array(n);
    this.seen = new Uint16Array(n);
    const near = Number(cfg.scan_near ?? 2);
    this.threshold = (Number(cfg.scan_far ?? 25) - cfg.proper_scan_range) / (Number(cfg.scan_far ?? 25) - near);
    this.cloud = new PointCloud(b.shape, this.pointSize);
    this.cloud.material.clippingPlanes = this.clip;
    this.surf.material.clippingPlanes = this.clip;
    this.surf.clear();
    this.group.add(this.cloud.points);
    this.dressing = siteDressing(b);
    this.group.add(this.dressing);

    // "Empty map" of the interior: one translucent box per estimated floor.
    const [x0, y0, x1, y1] = b.bbox;
    for (let k = 0; k < b.floors; k++) {
      const box = new THREE.BoxGeometry(x1 - x0, y1 - y0, b.story);
      const fill = new THREE.Mesh(
        box,
        new THREE.MeshBasicMaterial({ color: "#5ec8ff", transparent: true, opacity: 0.025, depthWrite: false, side: THREE.BackSide }),
      );
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(box),
        new THREE.LineBasicMaterial({ color: "#5ec8ff", transparent: true, opacity: 0.22 }),
      );
      for (const o of [fill, edges]) {
        o.position.set((x0 + x1) / 2, (y0 + y1) / 2, k * b.story + b.story / 2);
        this.shell.add(o);
      }
      const el = document.createElement("div");
      el.className = "floor-label";
      el.textContent = `F${k + 1}`;
      const label = new CSS2DObject(el);
      label.position.set(x0 - 1.5, y0 - 1.5, k * b.story + b.story / 2);
      this.shell.add(label);
    }
  }

  setClock(t: number, running: boolean, rtf: number): void {
    this.simNow = t;
    this.wallAt = performance.now();
    this.rate = running ? rtf : 0;
  }

  private now(): number {
    return this.simNow + ((performance.now() - this.wallAt) / 1000) * this.rate;
  }

  setClip(planes: THREE.Plane[]): void {
    this.clip.length = 0;
    this.clip.push(...planes);
    this.demo?.setClip(planes);
  }

  /** Points, surfaces or both. "auto" shows the surface once the GX10 has produced one. */
  setRender(mode: "auto" | "points" | "surface" | "both"): void {
    this.renderMode = mode;
    this.applyRender();
  }

  /** Give the demo render the true voxels (called once the real building is built). */
  setTrueModel(b: BuildingInfo, vox: Uint8Array): void {
    this.demo?.dispose();
    this.demo = new VoxelLayer(b.palette, b.shape, new Set());
    this.demo.setClip(this.clip);
    this.group.add(this.demo.group);
    this.demoVox = vox;
    this.demoShape = b.shape;
    this.demoShown = new Uint8Array(vox.length);
    this.demoTints = b.palette.map((p) => new THREE.Color(p.rgb[0] / 255, p.rgb[1] / 255, p.rgb[2] / 255));
    this.demo.group.visible = this.demoOn;
    if (this.demoOn) this.revealAll();
  }

  /** Switch the demo render on or off: it replaces the raw surface and points while on. */
  setDemo(on: boolean): void {
    if (on === this.demoOn) return;
    this.demoOn = on;
    if (this.demo) this.demo.group.visible = on;
    if (on) this.revealAll();
    this.applyRender();
  }

  private revealAll(): void {
    for (let i = 0; i < this.q.length; i++) if (this.q[i] > 0) this.reveal(i);
    this.demo?.flush();
  }

  /** Show the true voxels around a scanned voxel (one voxel of slack: the master's pose drifts). */
  private reveal(flat: number): void {
    const vox = this.demoVox;
    if (!vox || !this.demo) return;
    const [sx, sy, sz] = this.demoShape;
    const z = flat % sz, y = Math.floor(flat / sz) % sy, x = Math.floor(flat / (sz * sy));
    const at = (a: number, b: number, c: number) => (a < 0 || b < 0 || c < 0 || a >= sx || b >= sy || c >= sz ? 0 : vox[(a * sy + b) * sz + c]);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (let dz = -1; dz <= 1; dz++) {
          const a = x + dx, b = y + dy, c = z + dz;
          if (a < 0 || b < 0 || c < 0 || a >= sx || b >= sy || c >= sz) continue;
          const n = (a * sy + b) * sz + c;
          const m = vox[n];
          if (m === 0 || m === 1 || this.demoShown[n]) continue; // air, or asphalt (the ground is drawn separately)
          if (at(a + 1, b, c) && at(a - 1, b, c) && at(a, b + 1, c) && at(a, b - 1, c) && at(a, b, c + 1) && (c === 0 || at(a, b, c - 1))) continue;
          this.demoShown[n] = 1;
          this.demo.set(n, m, this.demoTints[m]);
        }
      }
    }
  }

  private applyRender(): void {
    if (this.demoOn) {
      this.surf.group.visible = false;
      if (this.cloud) this.cloud.points.visible = false;
      return;
    }
    const hasSurf = this.surf.count > 0;
    const m = this.renderMode === "auto" ? (hasSurf ? "surface" : "points") : this.renderMode;
    this.surf.group.visible = m !== "points";
    if (this.cloud) this.cloud.points.visible = m !== "surface";
  }

  setSmoothed(on: boolean): void {
    this.cloud?.setSmoothed(on);
  }

  setPointSize(size: number): void {
    this.pointSize = size;
    if (this.cloud) this.cloud.material.size = size;
  }

  applyDeltas(m: MapDeltas): void {
    if (!this.cloud) return;
    if (m.n) {
      const idx = new Int32Array(decodeB64(m.idx));
      const rgb = new Uint16Array(decodeB64(m.rgb));
      const q = new Uint8Array(decodeB64(m.q));
      for (let i = 0; i < idx.length; i++) {
        this.rgb[idx[i]] = rgb[i];
        this.q[idx[i]] = q[i];
        if (this.demoOn && q[i] > 0) this.reveal(idx[i]);
      }
      if (this.demoOn) this.demo?.flush();
    }
    if (m.surf?.length) {
      this.surf.apply(m.surf);
      this.applyRender();
    }
    if (m.nu) {
      this.cloud.update(
        new Uint32Array(decodeB64(m.uidx)), new Uint16Array(decodeB64(m.upos)), new Uint16Array(decodeB64(m.uspos)),
        new Uint8Array(decodeB64(m.ucol)), new Uint8Array(decodeB64(m.uflag)), new Uint8Array(decodeB64(m.uresid)),
        new Uint8Array(decodeB64(m.unpass)),
      );
    }
  }

  private painter() {
    if (this.mode === "texture") return null;
    const c = new THREE.Color();
    const now = this.now();
    return (vox: number, _r: number, _g: number, _b: number, out: Uint8Array, i: number) => {
      if (this.mode === "quality") qualityColor(this.q[vox] / 255, this.threshold, c);
      else if (this.mode === "confidence") {
        // green: seen from several passes and flat; red: one pass or rough (thick/doubled surface)
        const k = this.cloud!.confidence(i);
        const score = Math.min(1, (Math.min(k.passes, 3) / 3) * 0.6 + (k.views / 3) * 0.2 + 0.2 - Math.min(k.rough * 4, 0.6));
        qualityColor(Math.max(score, 0), 0.5, c);
      } else {
        const s = this.seen[vox];
        if (s === 0) c.copy(NEVER);
        else freshnessColor(now - (s - 1) / SEEN_UNITS_PER_S, this.staleAfter, c);
      }
      out[0] = c.r * 255;
      out[1] = c.g * 255;
      out[2] = c.b * 255;
    };
  }

  applySeen(s: SeenDeltas): void {
    const idx = new Int32Array(decodeB64(s.idx));
    const t = new Uint16Array(decodeB64(s.t));
    for (let i = 0; i < idx.length; i++) this.seen[idx[i]] = t[i];
  }

  /** Recolor every point (mode change, or freshness aging). */
  recolor(): void {
    this.cloud?.recolor(this.painter());
  }

  setTargets(list: [number, number, number, number][], cut: number): void {
    const pos = this.targets.geometry.getAttribute("position") as THREE.BufferAttribute;
    const col = this.targets.geometry.getAttribute("color") as THREE.BufferAttribute;
    let n = 0;
    for (const [x, y, z, kind] of list) {
      if (n >= MAX_TARGETS || z + 0.5 > cut) continue;
      pos.setXYZ(n, x + 0.5, y + 0.5, z + 0.5);
      if (kind === 0) col.setXYZ(n, 1.0, 0.69, 0.13);
      else col.setXYZ(n, 0.37, 0.78, 1.0);
      n++;
    }
    pos.needsUpdate = col.needsUpdate = true;
    this.targets.geometry.setDrawRange(0, n);
    this.targets.visible = this.layers.targets;
  }

  setEntries(entries: MapEntry[]): void {
    const key = entries.map((e) => `${e.id}:${e.w}:${e.h}:${e.blocked}`).join("|");
    this.entryGroup.visible = this.layers.entries;
    if (key === this.entryKeys) return;
    this.entryKeys = key;
    this.entryGroup.traverse((o) => {
      if (o instanceof CSS2DObject) o.element.remove();
    });
    this.entryGroup.clear();
    for (const e of entries) {
      const color = e.blocked ? "#ff4d4f" : "#f6e05e";
      const [w, h] = [Math.max(e.w, 1), Math.max(e.h, 1)];
      const frame = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, h)),
        new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true }),
      );
      frame.renderOrder = 6;
      frame.position.set(...e.center);
      // Plane faces +z; turn it to face along the entry normal.
      frame.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...e.normal).normalize());
      if (e.side !== "roof") frame.rotateZ(e.normal[0] !== 0 ? Math.PI / 2 : 0);
      const arrow = new THREE.ArrowHelper(new THREE.Vector3(...e.normal), new THREE.Vector3(...e.center).addScaledVector(new THREE.Vector3(...e.normal), -2.5), 2.2, color, 0.7, 0.45);
      const el = document.createElement("div");
      el.className = "entry-label" + (e.blocked ? " blocked" : "");
      el.textContent = `#${e.id} ${e.w.toFixed(0)}×${e.h.toFixed(0)}${e.blocked ? " blocked" : ""}`;
      const label = new CSS2DObject(el);
      label.position.set(e.center[0], e.center[1], e.center[2] + h / 2 + 0.8);
      this.entryGroup.add(frame, arrow, label);
    }
  }

  setCandidates(cands: Candidate[], t: number, cut: number): void {
    for (const c of cands) {
      let m = this.candMeshes.get(c.id);
      if (!m) {
        m = new THREE.Mesh(
          new THREE.SphereGeometry(0.6, 16, 12),
          new THREE.MeshBasicMaterial({ color: "#ffb020", transparent: true, opacity: 0.8, depthTest: false }),
        );
        m.renderOrder = 7;
        this.candMeshes.set(c.id, m);
        this.candGroup.add(m);
      }
      m.position.set(...c.pos);
      const mat = m.material as THREE.MeshBasicMaterial;
      mat.color.set(c.confirmed ? "#3ddc97" : c.dismissed ? "#5a6273" : "#ffb020");
      m.scale.setScalar(c.confirmed ? 1.2 : 0.8 + 0.3 * Math.sin(t * 5 + c.id));
      m.visible = c.pos[2] < cut;
    }
  }

  update(): void {
    this.shell.visible = this.layers.shell;
  }

  clear(): void {
    if (this.cloud) {
      this.group.remove(this.cloud.points);
      this.cloud.dispose();
      this.cloud = null;
    }
    for (const g of [this.shell, this.entryGroup, this.dressing]) {
      g?.traverse((o) => {
        if (o instanceof CSS2DObject) o.element.remove();
      });
    }
    this.shell.clear();
    this.entryGroup.clear();
    this.entryKeys = "";
    if (this.dressing) this.group.remove(this.dressing);
    this.candGroup.clear();
    this.candMeshes.clear();
  }
}
