import * as THREE from "three";

const SEEN_UNITS_PER_S = 2; // must match sim/disaster_sim/protocol.py

const FRESH = new THREE.Color("#3ddc97");
const MID = new THREE.Color("#e8d44d");
const STALE = new THREE.Color("#ff4d4f");
const ANCIENT = new THREE.Color("#7a1a22");

/** Green (just seen) -> yellow -> red (stale) -> dark red (twice the stale time). */
export function freshnessColor(age: number, staleAfter: number, out = new THREE.Color()): THREE.Color {
  const k = Math.max(age, 0) / staleAfter;
  if (k <= 0.5) return out.copy(FRESH).lerp(MID, k * 2);
  if (k <= 1) return out.copy(MID).lerp(STALE, (k - 0.5) * 2);
  return out.copy(STALE).lerp(ANCIENT, Math.min(k - 1, 1));
}

/**
 * The master's per-cell "last seen by any drone camera" times, plus a sim clock that keeps
 * advancing between server updates so colors age smoothly.
 */
export class Freshness {
  private seen: Uint16Array | null = null;
  private simT = 0;
  private wallT = 0;
  private rate = 0;

  setSeen(b64: string): void {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    this.seen = new Uint16Array(bytes.buffer);
  }

  setClock(simT: number, running: boolean, rtf: number): void {
    this.simT = simT;
    this.wallT = performance.now();
    this.rate = running ? rtf : 0;
  }

  reset(): void {
    this.seen = null;
    this.simT = 0;
  }

  now(): number {
    return this.simT + ((performance.now() - this.wallT) / 1000) * this.rate;
  }

  /** Age in seconds of a cell (numpy C-order flat index), or -1 if never seen. */
  age(flat: number, now = this.now()): number {
    const q = this.seen?.[flat] ?? 0;
    return q === 0 ? -1 : now - (q - 1) / SEEN_UNITS_PER_S;
  }

  get ready(): boolean {
    return this.seen !== null;
  }
}
