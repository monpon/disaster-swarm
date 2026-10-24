import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { MODE_COLORS, type CameraModel, type Candidate, type DroneState, type MapCells, type WorldInfo } from "../types";
import type { SwarmView } from "./drones";
import { FrustumView } from "./frustum";
import { freshnessColor, type Freshness } from "./freshness";

const UNKNOWN = [9, 12, 19, 255];
const FREE = [38, 48, 66, 255];
const MAX_FRONTIERS = 512;
const MAX_PATH_POINTS = 64;

// Height colormap for obstacle columns (meters -> color).
const STOPS: [number, THREE.Color][] = [
  [0, new THREE.Color("#2b7a78")],
  [6, new THREE.Color("#3ddc97")],
  [16, new THREE.Color("#e8d44d")],
  [28, new THREE.Color("#ff8c42")],
  [42, new THREE.Color("#ff4d6d")],
];

function heightColor(h: number, out = new THREE.Color()): THREE.Color {
  for (let i = 1; i < STOPS.length; i++) {
    if (h <= STOPS[i][0]) {
      const [h0, c0] = STOPS[i - 1];
      const [h1, c1] = STOPS[i];
      return out.copy(c0).lerp(c1, (h - h0) / (h1 - h0));
    }
  }
  return out.copy(STOPS[STOPS.length - 1][1]);
}

interface MapDrone {
  marker: THREE.Group;
  arrow: THREE.Mesh;
  arrowMat: THREE.MeshBasicMaterial;
  drop: THREE.Line;
  frustum: FrustumView;
  path: THREE.Line;
  pathMat: THREE.LineDashedMaterial;
  label: CSS2DObject;
  labelEl: HTMLDivElement;
  mode: string;
}

/** The master's view of the world: only what the drones have reported, built up live. */
export class MapView {
  readonly group = new THREE.Group();
  private world!: WorldInfo;
  private data!: Uint8Array<ArrayBuffer>;
  private texture!: THREE.DataTexture;
  private obstacles!: THREE.InstancedMesh;
  private frontierMesh!: THREE.InstancedMesh;
  private drones = new Map<number, MapDrone>();
  private candidates = new Map<number, THREE.Group>();
  private confirmed = new Map<number, THREE.Group>();
  private camera: CameraModel = { pitch: 0.61, tanH: 1, tanV: 0.58, range: 60 };
  private dummy = new THREE.Object3D();
  private color = new THREE.Color();
  private cellState!: Int8Array; // numpy C-order [ix, iy]
  private cellHeight!: Float32Array;
  private instCell!: Int32Array; // obstacle instance -> flat cell index
  private painted = false;
  knownCells = 0;
  obstacleCells = 0;
  layers = { frontiers: true, frustums: true, paths: true, labels: true };

  build(world: WorldInfo, pads: [number, number][], cam: CameraModel): void {
    this.dispose();
    this.world = world;
    this.camera = cam;
    const n = world.n;
    this.knownCells = 0;
    this.obstacleCells = 0;
    this.cellState = new Int8Array(n * n);
    this.cellHeight = new Float32Array(n * n);
    this.instCell = new Int32Array(n * n);
    this.painted = false;

    this.data = new Uint8Array(n * n * 4);
    for (let i = 0; i < n * n; i++) this.data.set(UNKNOWN, i * 4);
    this.texture = new THREE.DataTexture(this.data, n, n, THREE.RGBAFormat);
    this.texture.magFilter = THREE.NearestFilter;
    this.texture.needsUpdate = true;
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(world.size, world.size),
      new THREE.MeshBasicMaterial({ map: this.texture }),
    );
    this.group.add(ground);

    const grid = new THREE.GridHelper(world.size, n / 5, "#1c2433", "#141a26");
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.03;
    this.group.add(grid);

    const border = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.PlaneGeometry(world.size, world.size)),
      new THREE.LineBasicMaterial({ color: "#3a4a66" }),
    );
    border.position.z = 0.05;
    this.group.add(border);

    const box = new THREE.BoxGeometry(1, 1, 1).translate(0, 0, 0.5);
    this.obstacles = new THREE.InstancedMesh(
      box,
      new THREE.MeshStandardMaterial({ roughness: 0.8, metalness: 0.05 }),
      n * n,
    );
    this.obstacles.count = 0;
    this.obstacles.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.obstacles.frustumCulled = false;
    this.group.add(this.obstacles);

    this.frontierMesh = new THREE.InstancedMesh(
      new THREE.OctahedronGeometry(1, 0),
      new THREE.MeshBasicMaterial({ color: "#ffb020", transparent: true, opacity: 0.85 }),
      MAX_FRONTIERS,
    );
    this.frontierMesh.count = 0;
    this.frontierMesh.frustumCulled = false;
    this.group.add(this.frontierMesh);

    // Base station and pads (known to the master from the start).
    const padMat = new THREE.MeshBasicMaterial({ color: "#5ec8ff", transparent: true, opacity: 0.6 });
    for (const [x, y] of pads) {
      const pad = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.5, 4, 1, Math.PI / 4), padMat);
      pad.position.set(x, y, 0.1);
      this.group.add(pad);
    }
    const station = new THREE.Mesh(
      new THREE.CylinderGeometry(0.8, 0.8, 12, 12).rotateX(Math.PI / 2).translate(0, 0, 6),
      new THREE.MeshBasicMaterial({ color: "#5ec8ff" }),
    );
    station.position.set(world.base[0] - 14, world.base[1], 0);
    this.group.add(station);
  }

  applyCells(cells: MapCells): void {
    const { idx, s, h } = cells;
    if (!idx.length) return;
    const n = this.world.n;
    const c = this.world.cell;
    const half = this.world.size / 2;
    for (let k = 0; k < idx.length; k++) {
      const ix = Math.floor(idx[k] / n);
      const iy = idx[k] % n;
      const t = (iy * n + ix) * 4;
      this.knownCells++;
      this.cellState[idx[k]] = s[k];
      this.cellHeight[idx[k]] = h[k];
      if (s[k] === 2) {
        heightColor(h[k], this.color);
        this.data.set([this.color.r * 90, this.color.g * 90, this.color.b * 90, 255], t);
        this.dummy.position.set(-half + (ix + 0.5) * c, -half + (iy + 0.5) * c, 0);
        this.dummy.scale.set(c * 0.94, c * 0.94, Math.max(h[k], 0.2));
        this.dummy.updateMatrix();
        const i = this.obstacles.count++;
        this.instCell[i] = idx[k];
        this.obstacles.setMatrixAt(i, this.dummy.matrix);
        this.obstacles.setColorAt(i, this.color);
        this.obstacleCells++;
      } else {
        this.data.set(FREE, t);
      }
    }
    this.texture.needsUpdate = true;
    this.obstacles.instanceMatrix.needsUpdate = true;
    if (this.obstacles.instanceColor) this.obstacles.instanceColor.needsUpdate = true;
  }

  /** Recolor ground and obstacle columns by time since last seen (or restore height colors). */
  paintFreshness(fresh: Freshness, staleAfter: number, enabled: boolean): void {
    if (!this.world) return;
    const on = enabled && fresh.ready;
    if (!on && !this.painted) return;
    const n = this.world.n;
    const now = fresh.now();
    const c = this.color;
    for (let flat = 0; flat < n * n; flat++) {
      const st = this.cellState[flat];
      if (st === 0) continue;
      const ix = Math.floor(flat / n);
      const iy = flat - ix * n;
      const t = (iy * n + ix) * 4;
      const age = on ? fresh.age(flat, now) : -1;
      if (age >= 0) {
        freshnessColor(age, staleAfter, c);
        const k = st === 2 ? 110 : 150;
        this.data[t] = c.r * k;
        this.data[t + 1] = c.g * k;
        this.data[t + 2] = c.b * k;
      } else if (st === 2) {
        heightColor(this.cellHeight[flat], c);
        this.data.set([c.r * 90, c.g * 90, c.b * 90, 255], t);
      } else {
        this.data.set(FREE, t);
      }
    }
    for (let i = 0; i < this.obstacles.count; i++) {
      const flat = this.instCell[i];
      const age = on ? fresh.age(flat, now) : -1;
      if (age >= 0) freshnessColor(age, staleAfter, c);
      else heightColor(this.cellHeight[flat], c);
      this.obstacles.setColorAt(i, c);
    }
    this.texture.needsUpdate = true;
    if (this.obstacles.instanceColor) this.obstacles.instanceColor.needsUpdate = true;
    this.painted = on;
  }

  update(states: DroneState[], swarm: SwarmView, frontiers: [number, number, number][],
         candidates: Candidate[], time: number): void {
    this.updateDrones(states, swarm);
    this.updateFrontiers(frontiers, time);
    this.updateCandidates(candidates, time);
  }

  private updateDrones(states: DroneState[], swarm: SwarmView): void {
    const seen = new Set<number>();
    for (const s of states) {
      seen.add(s.id);
      let d = this.drones.get(s.id);
      if (!d) d = this.addDrone(s);
      const view = swarm.get(s.id);
      if (!view) continue;
      const pos = view.pos;
      const yaw = view.yaw();
      if (d.mode !== s.mode) {
        d.mode = s.mode;
        const col = MODE_COLORS[s.mode];
        d.arrowMat.color.set(col);
        d.frustum.setColor(col);
        d.pathMat.color.set(col);
        d.labelEl.style.borderColor = col;
      }
      d.marker.position.copy(pos);
      d.arrow.rotation.z = yaw;
      d.labelEl.classList.toggle("crashed", s.crashed);
      d.labelEl.classList.toggle("selected", swarm.selected === s.id);
      d.label.visible = this.layers.labels;

      const dropAttr = d.drop.geometry.getAttribute("position") as THREE.BufferAttribute;
      dropAttr.setXYZ(0, pos.x, pos.y, pos.z);
      dropAttr.setXYZ(1, pos.x, pos.y, pos.z - s.agl);
      dropAttr.needsUpdate = true;

      d.frustum.group.visible = this.layers.frustums && s.cam_on;
      if (d.frustum.group.visible) d.frustum.update(pos, yaw, s.agl);

      d.path.visible = this.layers.paths && s.path.length > 0;
      if (d.path.visible) {
        const attr = d.path.geometry.getAttribute("position") as THREE.BufferAttribute;
        attr.setXYZ(0, pos.x, pos.y, pos.z);
        const m = Math.min(s.path.length, MAX_PATH_POINTS - 1);
        for (let i = 0; i < m; i++) attr.setXYZ(i + 1, s.path[i][0], s.path[i][1], s.path[i][2]);
        attr.needsUpdate = true;
        d.path.geometry.setDrawRange(0, m + 1);
        d.path.computeLineDistances();
      }
    }
    for (const [id, d] of this.drones) {
      if (!seen.has(id)) {
        this.removeDrone(d);
        this.drones.delete(id);
      }
    }
  }

  private addDrone(s: DroneState): MapDrone {
    const col = MODE_COLORS[s.mode];
    const marker = new THREE.Group();
    const arrowMat = new THREE.MeshBasicMaterial({ color: col });
    // Flat arrowhead pointing along +x (heading).
    const shape = new THREE.Shape();
    shape.moveTo(3.2, 0);
    shape.lineTo(-1.8, 2.0);
    shape.lineTo(-0.8, 0);
    shape.lineTo(-1.8, -2.0);
    shape.closePath();
    const arrow = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: 0.5, bevelEnabled: false }), arrowMat);
    marker.add(arrow);

    const labelEl = document.createElement("div");
    labelEl.className = "drone-label";
    labelEl.textContent = `D${s.id}`;
    labelEl.style.borderColor = col;
    const label = new CSS2DObject(labelEl);
    label.center.set(0.5, 1.8);
    marker.add(label);

    const dropGeo = new THREE.BufferGeometry();
    dropGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    const drop = new THREE.Line(dropGeo, new THREE.LineBasicMaterial({ color: "#8b93a7", transparent: true, opacity: 0.35 }));
    drop.frustumCulled = false;

    const frustum = new FrustumView(this.camera, col, 0.1);

    const pathGeo = new THREE.BufferGeometry();
    pathGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_PATH_POINTS * 3), 3));
    const pathMat = new THREE.LineDashedMaterial({ color: col, dashSize: 2, gapSize: 1.5 });
    const path = new THREE.Line(pathGeo, pathMat);
    path.frustumCulled = false;

    this.group.add(marker, drop, frustum.group, path);
    const d: MapDrone = { marker, arrow, arrowMat, drop, frustum, path, pathMat, label, labelEl, mode: s.mode };
    this.drones.set(s.id, d);
    return d;
  }

  private removeDrone(d: MapDrone): void {
    d.marker.remove(d.label);
    d.labelEl.remove();
    this.group.remove(d.marker, d.drop, d.frustum.group, d.path);
    d.frustum.dispose();
  }

  private updateFrontiers(frontiers: [number, number, number][], time: number): void {
    const m = this.layers.frontiers ? Math.min(frontiers.length, MAX_FRONTIERS) : 0;
    for (let i = 0; i < m; i++) {
      const [x, y, gain] = frontiers[i];
      const sz = 0.7 + Math.min(Math.sqrt(gain) * 0.25, 1.6);
      this.dummy.position.set(x, y, 2.5 + 0.6 * Math.sin(time * 2 + i));
      this.dummy.rotation.set(0, 0, time + i);
      this.dummy.scale.set(sz, sz, sz * 1.4);
      this.dummy.updateMatrix();
      this.frontierMesh.setMatrixAt(i, this.dummy.matrix);
    }
    this.dummy.rotation.set(0, 0, 0);
    this.frontierMesh.count = m;
    this.frontierMesh.instanceMatrix.needsUpdate = true;
  }

  private updateCandidates(candidates: Candidate[], time: number): void {
    for (const c of candidates) {
      if (c.confirmed) {
        this.candidates.get(c.id)?.removeFromParent();
        this.candidates.delete(c.id);
        if (!this.confirmed.has(c.id)) {
          const g = beacon("#3ddc97");
          g.position.set(c.x, c.y, 0.2);
          this.group.add(g);
          this.confirmed.set(c.id, g);
        }
        continue;
      }
      if (c.dismissed) {
        this.candidates.get(c.id)?.removeFromParent();
        this.candidates.delete(c.id);
        continue;
      }
      let g = this.candidates.get(c.id);
      if (!g) {
        g = ring("#ffb020");
        this.group.add(g);
        this.candidates.set(c.id, g);
      }
      g.position.set(c.x, c.y, 0.2);
      g.scale.setScalar(1 + 0.25 * Math.sin(time * 4));
    }
  }

  dispose(): void {
    for (const d of this.drones.values()) this.removeDrone(d);
    this.drones.clear();
    this.candidates.clear();
    this.confirmed.clear();
    this.group.traverse((o) => (o as THREE.Mesh).geometry?.dispose());
    this.group.clear();
    this.texture?.dispose();
  }
}

function ring(color: string): THREE.Group {
  const g = new THREE.Group();
  g.add(new THREE.Mesh(
    new THREE.RingGeometry(2.2, 2.9, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthWrite: false }),
  ));
  return g;
}

function beacon(color: string): THREE.Group {
  const g = ring(color);
  g.add(new THREE.Mesh(
    new THREE.CylinderGeometry(0.4, 0.4, 30, 12, 1, true).rotateX(Math.PI / 2).translate(0, 0, 15),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.4, depthWrite: false }),
  ));
  g.add(new THREE.Mesh(
    new THREE.SphereGeometry(1.0, 16, 12).translate(0, 0, 1),
    new THREE.MeshBasicMaterial({ color }),
  ));
  return g;
}
