import * as THREE from "three";
import type { MapCells, WorldInfo } from "../types";
import { freshnessColor, type Freshness } from "./freshness";

const UNKNOWN_RGBA = [8, 11, 18, 225];
const FREE_RGBA = [40, 170, 140, 22];
const OBSTACLE_RGBA = [255, 120, 80, 40];
const FRESH_ALPHA = 120;

/**
 * Ground overlay for the flight view, driven by the master's global map. It can show
 * fog of war (unmapped ground darkened), freshness (time since a drone last saw each
 * cell), or both.
 */
export class FogLayer {
  readonly mesh: THREE.Mesh;
  private data: Uint8Array<ArrayBuffer>;
  private texture: THREE.DataTexture;
  private known: Uint8Array<ArrayBuffer>; // cell state, numpy C-order [ix, iy]
  private color = new THREE.Color();
  n: number;
  fog = false;
  freshness = false;

  constructor(world: WorldInfo) {
    this.n = world.n;
    this.data = new Uint8Array(this.n * this.n * 4);
    this.known = new Uint8Array(this.n * this.n);
    this.texture = new THREE.DataTexture(this.data, this.n, this.n, THREE.RGBAFormat);
    this.texture.magFilter = THREE.LinearFilter;
    this.texture.minFilter = THREE.LinearFilter;
    const mat = new THREE.MeshBasicMaterial({
      map: this.texture,
      transparent: true,
      depthWrite: false,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(world.size, world.size), mat);
    this.mesh.position.z = 0.15;
    this.mesh.renderOrder = 2;
    this.paint(null, 1);
  }

  /** Record cells; indices are numpy C-order over [ix, iy]. Returns true if anything changed. */
  apply(cells: MapCells): boolean {
    const { idx, s } = cells;
    for (let k = 0; k < idx.length; k++) this.known[idx[k]] = s[k];
    return idx.length > 0;
  }

  isKnown(ix: number, iy: number): boolean {
    if (ix < 0 || iy < 0 || ix >= this.n || iy >= this.n) return false;
    return this.known[ix * this.n + iy] !== 0;
  }

  /** Repaint every cell for the current modes. */
  paint(fresh: Freshness | null, staleAfter: number): void {
    const n = this.n;
    const useFresh = this.freshness && fresh?.ready;
    const now = fresh?.now() ?? 0;
    for (let ix = 0; ix < n; ix++) {
      for (let iy = 0; iy < n; iy++) {
        const flat = ix * n + iy;
        const t = (iy * n + ix) * 4; // texture rows run along y
        const st = this.known[flat];
        if (st === 0) {
          if (this.fog) this.data.set(UNKNOWN_RGBA, t);
          else this.data[t + 3] = 0;
          continue;
        }
        const age = useFresh ? fresh!.age(flat, now) : -1;
        if (age >= 0) {
          freshnessColor(age, staleAfter, this.color);
          this.data[t] = this.color.r * 255;
          this.data[t + 1] = this.color.g * 255;
          this.data[t + 2] = this.color.b * 255;
          this.data[t + 3] = FRESH_ALPHA;
        } else if (this.fog) {
          this.data.set(st === 2 ? OBSTACLE_RGBA : FREE_RGBA, t);
        } else {
          this.data[t + 3] = 0;
        }
      }
    }
    this.texture.needsUpdate = true;
    this.mesh.visible = this.fog || this.freshness;
  }

  dispose(): void {
    this.texture.dispose();
    (this.mesh.material as THREE.Material).dispose();
    this.mesh.geometry.dispose();
  }
}
