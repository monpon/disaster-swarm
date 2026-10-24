/**
 * Scroll-story data: one house point cloud where every point knows when the
 * swarm and a single drone would first see it. Produced by
 * scripts/render-assets/story.py. Times are normalized so 1 is when the single
 * drone finishes; the swarm finishes at `swarmEnd`. An illustration of the
 * idea, not a measured result.
 */
import { useEffect, useState } from "react";

/** [screenX, screenY, t, metresX, metresY] */
export type PathPoint = [number, number, number, number, number];

export interface StoryJson {
  swarmEnd: number;
  size: [number, number];
  house: [number, number];
  drones: Record<string, PathPoint[]>;
  solo: PathPoint[];
  events: Record<"person" | "blocked" | "gas" | "door", { at: [number, number]; swarm: number; solo: number; px: [number, number] }>;
  rooms: Record<string, { box: [number, number, number, number]; swarm: number; solo: number }>;
}

export interface Story extends StoryJson {
  count: number;
  x: Float32Array;
  y: Float32Array;
  bin: Uint8Array;
  /** Indices sorted by first-seen time, per search mode. */
  order: { swarm: Uint32Array; solo: Uint32Array };
  seen: { swarm: Float32Array; solo: Float32Array };
}

export type Mode = "swarm" | "solo";

let cache: Promise<Story> | null = null;

async function load(): Promise<Story> {
  const [json, buf] = await Promise.all([
    fetch("/assets/story.json").then((r) => r.json() as Promise<StoryJson>),
    fetch("/assets/story-points.bin").then((r) => r.arrayBuffer()),
  ]);
  const view = new DataView(buf);
  const count = Math.floor(buf.byteLength / 7);
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const bin = new Uint8Array(count);
  const swarm = new Float32Array(count);
  const solo = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const o = i * 7;
    x[i] = view.getUint16(o, true) / 10;
    y[i] = view.getUint16(o + 2, true) / 10;
    bin[i] = view.getUint8(o + 4);
    const s = view.getUint8(o + 5);
    const so = view.getUint8(o + 6);
    swarm[i] = s === 255 ? Infinity : s / 254;
    solo[i] = so === 255 ? Infinity : so / 254;
  }
  const sortBy = (times: Float32Array) => {
    const idx = Array.from({ length: count }, (_, i) => i);
    idx.sort((a, b) => times[a]! - times[b]!);
    return Uint32Array.from(idx);
  };
  return { ...json, count, x, y, bin, seen: { swarm, solo }, order: { swarm: sortBy(swarm), solo: sortBy(solo) } };
}

export function useStory() {
  const [story, setStory] = useState<Story | null>(null);
  useEffect(() => {
    cache ??= load();
    let alive = true;
    cache.then((s) => alive && setStory(s)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return story;
}

/** Position along a path at normalized time t, in screen px and metres. */
export function positionAt(path: PathPoint[], t: number) {
  const first = path[0]!;
  if (t <= first[2]) return { x: first[0], y: first[1], mx: first[3], my: first[4], trail: [first] as PathPoint[] };
  const trail: PathPoint[] = [first];
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1]!;
    const b = path[i]!;
    if (t <= b[2]) {
      const f = (t - a[2]) / Math.max(b[2] - a[2], 1e-6);
      const p: PathPoint = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, t, a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f];
      trail.push(p);
      return { x: p[0], y: p[1], mx: p[3], my: p[4], trail };
    }
    trail.push(b);
  }
  const last = path[path.length - 1]!;
  return { x: last[0], y: last[1], mx: last[3], my: last[4], trail };
}

export function pathsFor(story: Story, mode: Mode) {
  return mode === "swarm" ? Object.values(story.drones) : [story.solo];
}

/** Number of points (in `order`) first seen at or before t. */
export function seenCount(story: Story, mode: Mode, t: number) {
  const times = story.seen[mode];
  const order = story.order[mode];
  let lo = 0;
  let hi = order.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[order[mid]!]! <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Share of the reachable house mapped by time t (the swarm's full map is 100%). */
export function coverage(story: Story, mode: Mode, t: number) {
  return seenCount(story, mode, t) / Math.max(1, seenCount(story, "swarm", Infinity));
}
