import * as THREE from "three";
import type { Box, Candidate, WorldInfo } from "../types";
import type { FogLayer } from "./fog";

const COLORS = {
  ground: "#1b2231",
  outside: "#121722",
  building: "#6a7486",
  collapsed: "#8a5f4b",
  rubble: "#6e5e4e",
  edge: "#9fb3cf",
  pad: "#2b3446",
  padMark: "#e6edf7",
  station: "#c8d3e6",
  truth: "#ff5d73",
  found: "#3ddc97",
  candidate: "#ffb020",
};

interface BoxView {
  box: Box;
  mesh: THREE.Mesh;
  edges: THREE.LineSegments;
  solid: THREE.Material;
  ix: number;
  iy: number;
  revealed: boolean;
}

interface Marker {
  group: THREE.Group;
  ring: THREE.Mesh;
}

export class WorldView {
  readonly group = new THREE.Group();
  readonly antenna = new THREE.Vector3();
  private boxes: BoxView[] = [];
  private ghost = new THREE.MeshStandardMaterial({
    color: "#3a4458",
    transparent: true,
    opacity: 0.12,
    depthWrite: false,
  });
  private truthGroup = new THREE.Group();
  private candidates = new Map<number, Marker>();
  private foundGroup = new THREE.Group();
  private found = new Map<number, Marker>();
  private world!: WorldInfo;
  showTruth = true;
  ghosting = false; // ghost structures the master has not mapped yet

  build(world: WorldInfo, pads: [number, number][]): void {
    this.dispose();
    this.world = world;
    const g = this.group;

    const outside = new THREE.Mesh(
      new THREE.PlaneGeometry(world.size * 4, world.size * 4),
      new THREE.MeshStandardMaterial({ color: COLORS.outside, roughness: 1 }),
    );
    outside.position.z = -0.05;
    outside.receiveShadow = true;
    g.add(outside);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(world.size, world.size),
      new THREE.MeshStandardMaterial({ color: COLORS.ground, roughness: 0.95 }),
    );
    ground.receiveShadow = true;
    g.add(ground);

    const grid = new THREE.GridHelper(world.size, world.size / 10, "#2c3850", "#222b3d");
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.02;
    g.add(grid);

    for (const b of world.boxes) this.addBox(b);

    // Landing pads and the master ground station.
    const padGeo = new THREE.CircleGeometry(1.6, 32);
    const padMat = new THREE.MeshStandardMaterial({ color: COLORS.pad });
    const ringGeo = new THREE.RingGeometry(1.3, 1.5, 32);
    const ringMat = new THREE.MeshBasicMaterial({ color: COLORS.padMark });
    for (const [x, y] of pads) {
      const pad = new THREE.Mesh(padGeo, padMat);
      pad.position.set(x, y, 0.05);
      pad.receiveShadow = true;
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.position.set(x, y, 0.07);
      g.add(pad, ring);
    }
    const [bx, by] = world.base;
    const sx = bx - 14;
    const sy = by;
    const station = new THREE.Mesh(
      new THREE.BoxGeometry(5, 3.5, 2.6),
      new THREE.MeshStandardMaterial({ color: COLORS.station, roughness: 0.6 }),
    );
    station.position.set(sx, sy, 1.3);
    station.castShadow = true;
    const mast = new THREE.Mesh(
      new THREE.CylinderGeometry(0.15, 0.25, 10, 8).rotateX(Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: "#9aa6ba", metalness: 0.6, roughness: 0.4 }),
    );
    mast.position.set(sx, sy, 7.6);
    const beacon = new THREE.Mesh(
      new THREE.SphereGeometry(0.6, 16, 12),
      new THREE.MeshBasicMaterial({ color: "#5ec8ff" }),
    );
    beacon.position.set(sx, sy, 12.8);
    this.antenna.set(sx, sy, 12.8);
    g.add(station, mast, beacon);

    // Ground-truth survivors (hidden unless debugging).
    const body = new THREE.CapsuleGeometry(0.35, 1.0, 4, 8).rotateX(Math.PI / 2);
    const truthMat = new THREE.MeshBasicMaterial({ color: COLORS.truth });
    for (const s of world.survivors) {
      const m = new THREE.Mesh(body, truthMat);
      m.position.set(s.x, s.y, s.z + 0.85);
      this.truthGroup.add(m);
    }
    this.truthGroup.visible = this.showTruth;
    g.add(this.truthGroup, this.foundGroup);
  }

  private addBox(b: Box): void {
    const color = b.kind === "building" ? COLORS.building : b.kind === "collapsed" ? COLORS.collapsed : COLORS.rubble;
    const solid = new THREE.MeshStandardMaterial({
      color,
      roughness: b.kind === "building" ? 0.75 : 1,
      flatShading: b.kind !== "building",
    });
    const geo = new THREE.BoxGeometry(b.sx, b.sy, b.h);
    geo.translate(0, 0, b.h / 2); // pivot at base so collapsed buildings lean naturally
    const mesh = new THREE.Mesh(geo, this.ghost);
    mesh.position.set(b.cx, b.cy, 0);
    mesh.rotation.set(b.tilt, b.tilt * 0.5, b.yaw);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: 0.12 }),
    );
    mesh.add(edges);
    this.group.add(mesh);
    const c = this.world.cell;
    const half = this.world.size / 2;
    this.boxes.push({
      box: b,
      mesh,
      edges,
      solid,
      ix: Math.floor((b.cx + half) / c),
      iy: Math.floor((b.cy + half) / c),
      revealed: false,
    });
  }

  /** Turn ghosted structures solid once the master's map covers them. */
  reveal(fog: FogLayer): void {
    for (const v of this.boxes) {
      const show = !this.ghosting || fog.isKnown(v.ix, v.iy);
      if (show === v.revealed) continue;
      v.revealed = show;
      v.mesh.material = show ? v.solid : this.ghost;
      v.mesh.castShadow = show;
      (v.edges.material as THREE.LineBasicMaterial).opacity = show ? 0.35 : 0.12;
    }
  }

  setVisibility(truth: boolean, ghosting: boolean, fog: FogLayer | null): void {
    this.showTruth = truth;
    this.ghosting = ghosting;
    this.truthGroup.visible = truth;
    if (fog) this.reveal(fog);
  }

  updateMarkers(candidates: Candidate[], foundIds: number[], time: number): void {
    for (const c of candidates) {
      if (c.confirmed || c.dismissed) {
        const m = this.candidates.get(c.id);
        if (m) {
          this.group.remove(m.group);
          this.candidates.delete(c.id);
        }
        continue;
      }
      let m = this.candidates.get(c.id);
      if (!m) {
        m = makeMarker(COLORS.candidate, false);
        this.candidates.set(c.id, m);
        this.group.add(m.group);
      }
      m.group.position.set(c.x, c.y, 0.3);
    }
    for (const id of foundIds) {
      if (this.found.has(id)) continue;
      const s = this.world.survivors.find((v) => v.id === id);
      if (!s) continue;
      const m = makeMarker(COLORS.found, true);
      m.group.position.set(s.x, s.y, s.z + 0.3);
      this.found.set(id, m);
      this.foundGroup.add(m.group);
    }
    const pulse = 1 + 0.25 * Math.sin(time * 4);
    for (const m of this.candidates.values()) m.ring.scale.setScalar(pulse);
    for (const m of this.found.values()) m.ring.scale.setScalar(1 + 0.15 * Math.sin(time * 2));
  }

  dispose(): void {
    this.group.traverse((o) => {
      const mesh = o as THREE.Mesh;
      mesh.geometry?.dispose();
    });
    this.group.clear();
    this.truthGroup = new THREE.Group();
    this.foundGroup = new THREE.Group();
    this.boxes = [];
    this.candidates.clear();
    this.found.clear();
  }
}

function makeMarker(color: string, beacon: boolean): Marker {
  const group = new THREE.Group();
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(2.2, 2.8, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthWrite: false }),
  );
  ring.renderOrder = 3;
  group.add(ring);
  if (beacon) {
    const column = new THREE.Mesh(
      new THREE.CylinderGeometry(0.35, 0.35, 40, 12, 1, true).rotateX(Math.PI / 2).translate(0, 0, 20),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false }),
    );
    const person = new THREE.Mesh(
      new THREE.CapsuleGeometry(0.35, 1.0, 4, 8).rotateX(Math.PI / 2).translate(0, 0, 0.85),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.4 }),
    );
    group.add(column, person);
  }
  return { group, ring };
}
