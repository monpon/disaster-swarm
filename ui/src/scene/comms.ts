import * as THREE from "three";
import type { DroneState, Vec3 } from "../types";

const MAX_LINKS = 600;

/** Capacity (Mbps) -> link color: strong green, usable yellow, weak orange. */
function linkColor(mbps: number, out: THREE.Color): THREE.Color {
  if (mbps >= 8) return out.set("#3ddc97");
  if (mbps >= 2) return out.set("#e8d44d");
  return out.set("#ff8c42");
}

function segments(opacity: number): THREE.LineSegments {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_LINKS * 6), 3));
  geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(MAX_LINKS * 6), 3));
  const l = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity, depthTest: false }));
  l.frustumCulled = false;
  return l;
}

/**
 * Radio: the peer-to-peer mesh (every usable drone-drone / drone-base link, faint), the
 * hop each drone's traffic actually takes toward the master (bright), and the selected
 * drone's full route (white).
 */
export class CommsLayer {
  readonly group = new THREE.Group();
  readonly mesh = segments(0.14);
  readonly routes = segments(0.6);
  private route: THREE.Line;

  constructor() {
    this.mesh.renderOrder = 7;
    this.routes.renderOrder = 8;
    const rgeo = new THREE.BufferGeometry();
    rgeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(48 * 3), 3));
    this.route = new THREE.Line(rgeo, new THREE.LineBasicMaterial({ color: "#ffffff", depthTest: false, transparent: true }));
    this.route.renderOrder = 9;
    this.route.frustumCulled = false;
    this.group.add(this.mesh, this.routes, this.route);
  }

  private fill(lines: THREE.LineSegments, edges: [THREE.Vector3, THREE.Vector3, number][]): void {
    const p = lines.geometry.getAttribute("position") as THREE.BufferAttribute;
    const c = lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    const col = new THREE.Color();
    let n = 0;
    for (const [a, b, mbps] of edges) {
      if (n >= MAX_LINKS) break;
      linkColor(mbps, col);
      p.setXYZ(2 * n, a.x, a.y, a.z);
      p.setXYZ(2 * n + 1, b.x, b.y, b.z);
      c.setXYZ(2 * n, col.r, col.g, col.b);
      c.setXYZ(2 * n + 1, col.r, col.g, col.b);
      n++;
    }
    p.needsUpdate = c.needsUpdate = true;
    lines.geometry.setDrawRange(0, 2 * n);
  }

  update(
    drones: DroneState[],
    mesh: [number, number, number][],
    pos: Map<number, THREE.Vector3>,
    base: Vec3,
    selected: number | null,
  ): void {
    const baseV = new THREE.Vector3(...base);
    const at = (id: number) => (id < 0 ? baseV : pos.get(id));

    const meshEdges: [THREE.Vector3, THREE.Vector3, number][] = [];
    for (const [a, b, mbps] of mesh) {
      const pa = at(a);
      const pb = at(b);
      if (pa && pb) meshEdges.push([pa, pb, mbps]);
    }
    this.fill(this.mesh, meshEdges);

    const hops: [THREE.Vector3, THREE.Vector3, number][] = [];
    for (const d of drones) {
      if (d.crashed || d.grounded || d.route.length < 2) continue;
      const a = pos.get(d.id);
      const b = at(d.route[1]);
      if (a && b) hops.push([a, b, d.link]);
    }
    this.fill(this.routes, hops);

    const sel = drones.find((d) => d.id === selected);
    const rp = this.route.geometry.getAttribute("position") as THREE.BufferAttribute;
    let k = 0;
    if (sel && !sel.crashed && sel.route.length > 1) {
      for (const id of sel.route.slice(0, 48)) {
        const v = at(id);
        if (v) rp.setXYZ(k++, v.x, v.y, v.z);
      }
    }
    rp.needsUpdate = true;
    this.route.geometry.setDrawRange(0, k);
  }
}
