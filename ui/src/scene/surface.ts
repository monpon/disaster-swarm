import * as THREE from "three";
import { decodeB64, type SurfaceChunk } from "../types";

const POS_UNIT = 0.01; // must match sim/disaster_sim/surface.py

/** The master's fused surface: triangle chunks from the GX10's TSDF + marching cubes. Each
 * message replaces the mesh of the chunks it names. */
export class SurfaceLayer {
  readonly group = new THREE.Group();
  readonly material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.95,
    metalness: 0,
    side: THREE.DoubleSide,
  });
  private meshes = new Map<number, THREE.Mesh>();

  get count(): number {
    return this.meshes.size;
  }

  apply(chunks: SurfaceChunk[]): void {
    for (const c of chunks) {
      const old = this.meshes.get(c.id);
      if (old) {
        this.group.remove(old);
        old.geometry.dispose();
        this.meshes.delete(c.id);
      }
      if (!c.nv) continue;
      const v16 = new Uint16Array(decodeB64(c.v));
      const pos = new Float32Array(v16.length);
      for (let i = 0; i < v16.length; i++) pos[i] = v16[i] * POS_UNIT;
      const col = new Uint8Array(decodeB64(c.c));
      const idx = c.w ? new Uint32Array(decodeB64(c.f)) : new Uint16Array(decodeB64(c.f));
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("color", new THREE.BufferAttribute(col, 3, true));
      g.setAttribute("normal", new THREE.BufferAttribute(new Int8Array(decodeB64(c.n)), 3, true));
      g.setIndex(new THREE.BufferAttribute(idx, 1));
      const mesh = new THREE.Mesh(g, this.material);
      mesh.frustumCulled = false;
      this.meshes.set(c.id, mesh);
      this.group.add(mesh);
    }
  }

  clear(): void {
    for (const m of this.meshes.values()) {
      this.group.remove(m);
      m.geometry.dispose();
    }
    this.meshes.clear();
  }
}
