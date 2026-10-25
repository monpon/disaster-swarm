import * as THREE from "three";

const POINT_UNIT = 0.05; // must match sim/disaster_sim/voxelmap.py

/** Growable colored point cloud (one draw call). The master refines points as more views
 * arrive and smooths them on the GX10; updates replace points by id. Positions can show the
 * raw running average or the smoothed cloud; outliers are hidden. */
export class PointCloud {
  readonly points: THREE.Points;
  readonly material: THREE.PointsMaterial;
  private raw = new Float32Array(0);
  private smooth = new Float32Array(0);
  private pos = new Float32Array(0); // what is drawn
  private col = new Uint8Array(0);
  private base = new Uint8Array(0); // observed colors, kept for recoloring
  private flag = new Uint8Array(0);
  private resid = new Uint8Array(0);
  private npass = new Uint8Array(0);
  private vox = new Int32Array(0); // containing voxel (flat index) per point
  count = 0;
  smoothed = true;

  constructor(private shape: [number, number, number], size = 0.3) {
    this.material = new THREE.PointsMaterial({ size, vertexColors: true, sizeAttenuation: true });
    this.points = new THREE.Points(new THREE.BufferGeometry(), this.material);
    this.points.frustumCulled = false;
    this.grow(1 << 16);
  }

  private grow(cap: number): void {
    const f3 = (a: Float32Array, nan: boolean) => {
      const n = new Float32Array(cap * 3);
      if (nan) n.fill(NaN);
      n.set(a.subarray(0, this.count * 3));
      return n;
    };
    const u3 = (a: Uint8Array) => {
      const n = new Uint8Array(cap * 3);
      n.set(a.subarray(0, this.count * 3));
      return n;
    };
    const u1 = (a: Uint8Array) => {
      const n = new Uint8Array(cap);
      n.set(a.subarray(0, this.count));
      return n;
    };
    this.raw = f3(this.raw, true);
    this.smooth = f3(this.smooth, true);
    this.pos = f3(this.pos, true);
    this.col = u3(this.col);
    this.base = u3(this.base);
    this.flag = u1(this.flag);
    this.resid = u1(this.resid);
    this.npass = u1(this.npass);
    const vox = new Int32Array(cap);
    vox.set(this.vox.subarray(0, this.count));
    this.vox = vox;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(this.pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(this.col, 3, true));
    g.setDrawRange(0, this.count);
    this.points.geometry.dispose();
    this.points.geometry = g;
  }

  /** Apply a batch of point updates (ids may be new or existing). */
  update(ids: Uint32Array, raw: Uint16Array, sm: Uint16Array, rgb: Uint8Array, flag: Uint8Array, resid: Uint8Array, npass: Uint8Array): void {
    const n = ids.length;
    if (!n) return;
    let top = 0;
    for (let i = 0; i < n; i++) top = Math.max(top, ids[i] + 1);
    if (top > this.vox.length) this.grow(Math.max(this.vox.length * 2, top));
    const [, sy, sz] = this.shape;
    for (let i = 0; i < n; i++) {
      const k = ids[i];
      for (let a = 0; a < 3; a++) {
        this.raw[3 * k + a] = raw[3 * i + a] * POINT_UNIT;
        this.smooth[3 * k + a] = sm[3 * i + a] * POINT_UNIT;
        this.base[3 * k + a] = rgb[3 * i + a];
      }
      this.flag[k] = flag[i];
      this.resid[k] = resid[i];
      this.npass[k] = npass[i];
      this.vox[k] = (Math.floor(this.raw[3 * k]) * sy + Math.floor(this.raw[3 * k + 1])) * sz + Math.floor(this.raw[3 * k + 2]);
      this.place(k);
      if (!this.painter) for (let a = 0; a < 3; a++) this.col[3 * k + a] = this.base[3 * k + a];
    }
    this.count = Math.max(this.count, top);
    if (this.painter) this.recolor(this.painter);
    this.touch(0, this.count);
  }

  private place(k: number): void {
    const hidden = this.flag[k] & 1;
    const src = this.smoothed ? this.smooth : this.raw;
    for (let a = 0; a < 3; a++) this.pos[3 * k + a] = hidden ? NaN : src[3 * k + a];
  }

  setSmoothed(on: boolean): void {
    if (this.smoothed === on) return;
    this.smoothed = on;
    for (let k = 0; k < this.count; k++) this.place(k);
    this.touch(0, this.count);
  }

  private touch(start: number, n: number): void {
    const g = this.points.geometry;
    const pa = g.getAttribute("position") as THREE.BufferAttribute;
    const ca = g.getAttribute("color") as THREE.BufferAttribute;
    pa.clearUpdateRanges();
    ca.clearUpdateRanges();
    pa.needsUpdate = ca.needsUpdate = true;
    g.setDrawRange(0, this.count);
    void start;
    void n;
  }

  private painter: PointPainter | null = null;

  /** Views per point (0..3 buckets), passes and roughness, for the confidence coloring. */
  confidence(k: number): { views: number; passes: number; rough: number } {
    return { views: (this.flag[k] >> 1) & 3, passes: this.npass[k], rough: this.resid[k] / 255 };
  }

  /** Recolor every point: `fn(voxel, r, g, b, out, pointIndex)` writes 0..255 rgb into `out`. */
  recolor(fn: PointPainter | null): void {
    this.painter = fn;
    const out = new Uint8Array(3);
    for (let i = 0; i < this.count; i++) {
      if (!fn) {
        for (let a = 0; a < 3; a++) this.col[3 * i + a] = this.base[3 * i + a];
        continue;
      }
      fn(this.vox[i], this.base[3 * i], this.base[3 * i + 1], this.base[3 * i + 2], out, i);
      this.col[3 * i] = out[0];
      this.col[3 * i + 1] = out[1];
      this.col[3 * i + 2] = out[2];
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

export type PointPainter = (vox: number, r: number, g: number, b: number, out: Uint8Array, i: number) => void;
