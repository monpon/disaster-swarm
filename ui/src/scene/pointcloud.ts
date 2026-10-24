import * as THREE from "three";

const POINT_UNIT = 0.05; // must match sim/disaster_sim/voxelmap.py

/** Growable colored point cloud (one draw call), appended to as the master fuses frames. */
export class PointCloud {
  readonly points: THREE.Points;
  readonly material: THREE.PointsMaterial;
  private pos = new Float32Array(0);
  private col = new Uint8Array(0);
  private base = new Uint8Array(0); // observed colors, kept for recoloring
  private vox = new Int32Array(0); // containing voxel (flat index) per point
  count = 0;

  constructor(private shape: [number, number, number], size = 0.3) {
    this.material = new THREE.PointsMaterial({ size, vertexColors: true, sizeAttenuation: true });
    this.points = new THREE.Points(new THREE.BufferGeometry(), this.material);
    this.points.frustumCulled = false;
    this.grow(1 << 16);
  }

  private grow(cap: number): void {
    const pos = new Float32Array(cap * 3);
    const col = new Uint8Array(cap * 3);
    const base = new Uint8Array(cap * 3);
    const vox = new Int32Array(cap);
    pos.set(this.pos.subarray(0, this.count * 3));
    col.set(this.col.subarray(0, this.count * 3));
    base.set(this.base.subarray(0, this.count * 3));
    vox.set(this.vox.subarray(0, this.count));
    this.pos = pos;
    this.col = col;
    this.base = base;
    this.vox = vox;
    const geo = this.points.geometry;
    geo.dispose();
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3, true));
    g.setDrawRange(0, this.count);
    this.points.geometry = g;
  }

  /** Append points: xyz in 5 cm units, rgb bytes. */
  append(xyz: Uint16Array, rgb: Uint8Array): void {
    const n = rgb.length / 3;
    if (!n) return;
    if (this.count + n > this.vox.length) this.grow(Math.max(this.vox.length * 2, this.count + n));
    const [, sy, sz] = this.shape;
    for (let i = 0; i < n; i++) {
      const k = this.count + i;
      const x = xyz[3 * i] * POINT_UNIT;
      const y = xyz[3 * i + 1] * POINT_UNIT;
      const z = xyz[3 * i + 2] * POINT_UNIT;
      this.pos[3 * k] = x;
      this.pos[3 * k + 1] = y;
      this.pos[3 * k + 2] = z;
      this.vox[k] = (Math.floor(x) * sy + Math.floor(y)) * sz + Math.floor(z);
    }
    this.base.set(rgb, this.count * 3);
    this.col.set(rgb, this.count * 3);
    const start = this.count;
    this.count += n;
    const g = this.points.geometry;
    const pa = g.getAttribute("position") as THREE.BufferAttribute;
    const ca = g.getAttribute("color") as THREE.BufferAttribute;
    pa.clearUpdateRanges();
    ca.clearUpdateRanges();
    pa.addUpdateRange(start * 3, n * 3);
    ca.addUpdateRange(start * 3, n * 3);
    pa.needsUpdate = ca.needsUpdate = true;
    g.setDrawRange(0, this.count);
  }

  /** Recolor every point: `fn(voxel, observedRgb, out)` writes 0..255 rgb into `out`. */
  recolor(fn: ((vox: number, r: number, g: number, b: number, out: Uint8Array) => void) | null): void {
    if (!fn) {
      this.col.set(this.base.subarray(0, this.count * 3));
    } else {
      const out = new Uint8Array(3);
      for (let i = 0; i < this.count; i++) {
        fn(this.vox[i], this.base[3 * i], this.base[3 * i + 1], this.base[3 * i + 2], out);
        this.col[3 * i] = out[0];
        this.col[3 * i + 1] = out[1];
        this.col[3 * i + 2] = out[2];
      }
    }
    const ca = this.points.geometry.getAttribute("color") as THREE.BufferAttribute;
    ca.clearUpdateRanges();
    ca.needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.material.dispose();
  }
}
