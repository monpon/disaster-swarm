import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { decodeB64, type BuildingInfo } from "../types";
import { realTint, materialTexture } from "./textures";
import { VoxelLayer } from "./voxels";

const ASPHALT = 1;
const SURVIVOR = 13;

export async function inflate(b64: string): Promise<Uint8Array> {
  const stream = new Blob([decodeB64(b64)]).stream().pipeThrough(new DecompressionStream("deflate"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Ground, landing pads and the master's antenna mast; shared by both views. */
export function siteDressing(b: BuildingInfo): THREE.Group {
  const g = new THREE.Group();
  const [sx, sy] = b.shape;
  const gw = sx + 120, gh = sy + 120;
  const asphaltTex = materialTexture("asphalt").clone();   // weathered asphalt: a grain tile every 2 m instead of one flat colour
  asphaltTex.wrapS = asphaltTex.wrapT = THREE.RepeatWrapping;
  asphaltTex.repeat.set(gw / 2, gh / 2);
  asphaltTex.needsUpdate = true;
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(gw, gh),
    new THREE.MeshStandardMaterial({ color: realTint(b.palette[ASPHALT]), map: asphaltTex, roughness: 0.95 }),
  );
  ground.position.set(sx / 2, sy / 2, 1);
  ground.receiveShadow = true;
  g.add(ground);
  const grid = new THREE.GridHelper(Math.max(sx, sy) + 40, (Math.max(sx, sy) + 40) / 8, "#4a5060", "#3a404d");
  grid.rotation.x = Math.PI / 2;
  grid.position.set(sx / 2, sy / 2, 1.01);
  (grid.material as THREE.Material).transparent = true;
  (grid.material as THREE.Material).opacity = 0.12;
  g.add(grid);

  const padMat = new THREE.MeshStandardMaterial({ color: "#2f3a4f", roughness: 0.8 });
  const ringMat = new THREE.MeshBasicMaterial({ color: "#5ec8ff" });
  for (const [x, y] of b.pads) {
    const pad = new THREE.Mesh(new THREE.BoxGeometry(2.2, 2.2, 0.1), padMat);
    pad.position.set(x, y, 1.05);
    pad.receiveShadow = true;
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.75, 0.85, 24), ringMat);
    ring.position.set(x, y, 1.11);
    g.add(pad, ring);
  }

  const [bx, by, bz] = b.base;
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.25, bz - 1, 8).rotateX(Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: "#c9d2e3", metalness: 0.4, roughness: 0.4 }));
  mast.position.set(bx, by, 1 + (bz - 1) / 2);
  mast.castShadow = true;
  const dish = new THREE.Mesh(new THREE.SphereGeometry(0.6, 16, 12), new THREE.MeshBasicMaterial({ color: "#5ec8ff" }));
  dish.position.set(bx, by, bz);
  const hut = new THREE.Mesh(new THREE.BoxGeometry(4, 3, 2.4), new THREE.MeshStandardMaterial({ color: "#39445a" }));
  hut.position.set(bx - 3, by, 2.2);
  hut.castShadow = true;
  const el = document.createElement("div");
  el.className = "site-label";
  el.textContent = "MASTER";
  const label = new CSS2DObject(el);
  label.position.set(bx, by, bz + 1.5);
  g.add(mast, dish, hut, label);
  return g;
}

/** The true building: every exposed solid voxel, textured by material. */
export class RealView {
  readonly group = new THREE.Group();
  layer: VoxelLayer | null = null;
  vox: Uint8Array | null = null;
  private markers: { obj: THREE.Mesh; id: number }[] = [];
  private people: { obj: THREE.Group; z: number }[] = [];
  private dressing: THREE.Group | null = null;

  async build(b: BuildingInfo): Promise<void> {
    this.clear();
    const vox = await inflate(b.vox);
    this.vox = vox;
    const [sx, sy, sz] = b.shape;
    const layer = new VoxelLayer(b.palette, b.shape, new Set([SURVIVOR]));
    const c = new THREE.Color();
    const tints = b.palette.map((p) => realTint(p));
    const at = (x: number, y: number, z: number) =>
      x < 0 || y < 0 || z < 0 || x >= sx || y >= sy || z >= sz ? 0 : vox[(x * sy + y) * sz + z];
    for (let x = 0; x < sx; x++) {
      for (let y = 0; y < sy; y++) {
        for (let z = 0; z < sz; z++) {
          const m = vox[(x * sy + y) * sz + z];
          if (m === 0 || m === ASPHALT) continue;
          if (at(x + 1, y, z) && at(x - 1, y, z) && at(x, y + 1, z) && at(x, y - 1, z) && at(x, y, z + 1) && (z === 0 || at(x, y, z - 1)))
            continue; // fully enclosed
          // a little ambient occlusion (voxels tucked into corners and under overhangs are darker) and a stable per-voxel
          // variation, so large surfaces do not read as one flat colour
          let solid = 0;
          for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) if (dx || dy || dz) solid += at(x + dx, y + dy, z + dz) ? 1 : 0;
          const ao = 1 - 0.4 * Math.max(0, solid / 26 - 0.4);
          const h = Math.imul(Math.imul(x + 1, 73856093) ^ Math.imul(y + 1, 19349663) ^ Math.imul(z + 1, 83492791), 2654435761) >>> 0;
          const jitter = 0.94 + 0.12 * (h / 4294967296);
          layer.set((x * sy + y) * sz + z, m, c.copy(tints[m]).multiplyScalar(ao * jitter));
        }
      }
    }
    layer.flush();
    this.layer = layer;
    this.group.add(layer.group);
    this.dressing = siteDressing(b);
    this.group.add(this.dressing);

    for (const s of b.survivors) {
      if (s.prims?.length) {   // the person themself: capsules for head, torso, arms, legs
        const fig = new THREE.Group();
        const up = new THREE.Vector3(0, 1, 0);
        for (const [ax, ay, az, bx, by, bz, rad, cr, cg, cb] of s.prims) {
          const a = new THREE.Vector3(ax, ay, az), d = new THREE.Vector3(bx - ax, by - ay, bz - az);
          const len = Math.max(d.length(), 0.001);
          const mesh = new THREE.Mesh(
            new THREE.CapsuleGeometry(rad, len, 4, 10),
            new THREE.MeshStandardMaterial({ color: new THREE.Color(cr / 255, cg / 255, cb / 255), roughness: 0.85, clippingPlanes: this.layer?.clip }),
          );
          mesh.position.copy(a).addScaledVector(d, 0.5);
          mesh.quaternion.setFromUnitVectors(up, d.clone().normalize());
          mesh.castShadow = true;
          fig.add(mesh);
        }
        this.group.add(fig);
        this.people.push({ obj: fig, z: s.z });
      }
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.9, 1.15, 32),
        new THREE.MeshBasicMaterial({ color: "#ff3040", transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide }),
      );
      ring.position.set(s.x + 0.5, s.y + 0.5, s.z + 0.05);
      ring.renderOrder = 5;
      this.markers.push({ obj: ring, id: s.id });
      this.group.add(ring);
    }
  }

  updateMarkers(found: number[], t: number, cut: number, show: boolean): void {
    for (const p of this.people) p.obj.visible = p.z + 0.5 < cut;
    for (const { obj, id } of this.markers) {
      const isFound = found.includes(id);
      (obj.material as THREE.MeshBasicMaterial).color.set(isFound ? "#3ddc97" : "#ff3040");
      obj.scale.setScalar(1 + 0.25 * Math.sin(t * 4 + id));
      obj.visible = show && obj.position.z < cut;
    }
  }

  clear(): void {
    if (this.layer) {
      this.group.remove(this.layer.group);
      this.layer.dispose();
      this.layer = null;
    }
    if (this.dressing) {
      this.dressing.traverse((o) => {
        if (o instanceof CSS2DObject) o.element.remove();
      });
      this.group.remove(this.dressing);
    }
    for (const m of this.markers) this.group.remove(m.obj);
    this.markers = [];
    for (const p of this.people) this.group.remove(p.obj);
    this.people = [];
  }
}
