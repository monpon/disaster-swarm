import * as THREE from "three";
import type { PaletteEntry } from "../types";
import { FINISH, materialTexture } from "./textures";

const BOX = new THREE.BoxGeometry(1, 1, 1);
const tmpM = new THREE.Matrix4();

/** One growable InstancedMesh of unit cubes per material; voxels added/removed by flat index. */
export class VoxelLayer {
  readonly group = new THREE.Group();
  private meshes: (THREE.InstancedMesh | null)[];
  private owners: Int32Array[]; // slot -> voxel flat index, per material
  private slotOf = new Map<number, number>(); // voxel -> (mat << 24) | slot
  private mats: THREE.MeshStandardMaterial[];
  private dirty = new Set<number>();
  readonly clip: THREE.Plane[] = [];

  constructor(
    private palette: PaletteEntry[],
    private shape: [number, number, number],
    emissive: Set<number> = new Set(),
  ) {
    this.meshes = palette.map(() => null);
    this.owners = palette.map(() => new Int32Array(0));
    this.mats = palette.map((p) => {
      const m = new THREE.MeshStandardMaterial({
        map: materialTexture(p.name),
        roughness: (FINISH[p.name] ?? [0.85, 0])[0],
        metalness: (FINISH[p.name] ?? [0.85, 0])[1],
        clippingPlanes: this.clip,
        clipShadows: true,
      });
      if (emissive.has(p.id)) {
        m.emissive = new THREE.Color(p.rgb[0] / 255, p.rgb[1] / 255, p.rgb[2] / 255);
        m.emissiveIntensity = 0.8;
      }
      return m;
    });
  }

  get count(): number {
    return this.slotOf.size;
  }

  has(flat: number): boolean {
    return this.slotOf.has(flat);
  }

  materialOf(flat: number): number {
    const v = this.slotOf.get(flat);
    return v === undefined ? -1 : v >>> 24;
  }

  setClip(planes: THREE.Plane[]): void {
    this.clip.length = 0;
    this.clip.push(...planes);
  }

  private ensure(mat: number, need: number): THREE.InstancedMesh {
    let mesh = this.meshes[mat];
    const cap = mesh ? mesh.instanceMatrix.count : 0;
    if (mesh && need <= cap) return mesh;
    const next = new THREE.InstancedMesh(BOX, this.mats[mat], Math.max(256, cap * 2, need));
    next.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    next.castShadow = true;
    next.receiveShadow = true;
    next.frustumCulled = false;
    next.setColorAt(0, new THREE.Color(1, 1, 1));
    const owners = new Int32Array(next.instanceMatrix.count);
    if (mesh) {
      (next.instanceMatrix.array as Float32Array).set(mesh.instanceMatrix.array as Float32Array);
      (next.instanceColor!.array as Float32Array).set(mesh.instanceColor!.array as Float32Array);
      next.count = mesh.count;
      owners.set(this.owners[mat]);
      this.group.remove(mesh);
      mesh.dispose();
    } else {
      next.count = 0;
    }
    this.owners[mat] = owners;
    this.meshes[mat] = next;
    this.group.add(next);
    return next;
  }

  /** Add or move a voxel to material `mat` with tint `color`. */
  set(flat: number, mat: number, color: THREE.Color): void {
    const cur = this.slotOf.get(flat);
    if (cur !== undefined && cur >>> 24 === mat) {
      this.meshes[mat]!.setColorAt(cur & 0xffffff, color);
      this.dirty.add(mat);
      return;
    }
    if (cur !== undefined) this.remove(flat);
    const mesh = this.ensure(mat, (this.meshes[mat]?.count ?? 0) + 1);
    const slot = mesh.count++;
    const [, sy, sz] = this.shape;
    const x = Math.floor(flat / (sy * sz));
    const r = flat - x * sy * sz;
    const y = Math.floor(r / sz);
    const z = r - y * sz;
    tmpM.makeTranslation(x + 0.5, y + 0.5, z + 0.5);
    mesh.setMatrixAt(slot, tmpM);
    mesh.setColorAt(slot, color);
    this.owners[mat][slot] = flat;
    this.slotOf.set(flat, (mat << 24) | slot);
    this.dirty.add(mat);
  }

  setColor(flat: number, color: THREE.Color): void {
    const cur = this.slotOf.get(flat);
    if (cur === undefined) return;
    const mat = cur >>> 24;
    this.meshes[mat]!.setColorAt(cur & 0xffffff, color);
    this.dirty.add(mat);
  }

  remove(flat: number): void {
    const cur = this.slotOf.get(flat);
    if (cur === undefined) return;
    const mat = cur >>> 24;
    const slot = cur & 0xffffff;
    const mesh = this.meshes[mat]!;
    const last = --mesh.count;
    if (slot !== last) {
      // Move the last instance into the freed slot.
      mesh.getMatrixAt(last, tmpM);
      mesh.setMatrixAt(slot, tmpM);
      const c = new THREE.Color();
      mesh.getColorAt(last, c);
      mesh.setColorAt(slot, c);
      const moved = this.owners[mat][last];
      this.owners[mat][slot] = moved;
      this.slotOf.set(moved, (mat << 24) | slot);
    }
    this.slotOf.delete(flat);
    this.dirty.add(mat);
  }

  /** Visit every voxel (flat index, material). */
  forEach(fn: (flat: number, mat: number) => void): void {
    for (const [flat, v] of this.slotOf) fn(flat, v >>> 24);
  }

  /** Push pending instance changes to the GPU. */
  flush(): void {
    for (const mat of this.dirty) {
      const mesh = this.meshes[mat];
      if (!mesh) continue;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
    this.dirty.clear();
  }

  clear(): void {
    for (const m of this.meshes) {
      if (m) {
        this.group.remove(m);
        m.dispose();
      }
    }
    this.meshes = this.palette.map(() => null);
    this.owners = this.palette.map(() => new Int32Array(0));
    this.slotOf.clear();
  }

  dispose(): void {
    this.clear();
    this.mats.forEach((m) => m.dispose());
  }
}
