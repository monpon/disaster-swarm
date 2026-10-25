import { floorOf, type Live, type Plan } from "./swarm";

/**
 * Routes for the crew: A* over the live floor plan (1 m cells: 0 unknown, 1 explored, 2 solid), from the nearest open
 * entrance on the survivor's floor to the survivor. Unknown cells are allowed but cost extra, and the answer says how
 * much of the way is unmapped. Stairs are not on the plan, so a route is only found on the floor the entrance is on.
 */

export interface Route {
  found: boolean;
  /** Why there is no route, or a caution about this one. */
  note?: string;
  lengthM?: number;
  /** Meters of the route through cells no drone has seen yet. */
  unmappedM?: number;
  from?: string;
  /** Spoken-style turn by turn directions. */
  steps?: string[];
  /** World (x, y) of each cell on the way, for drawing. */
  path?: [number, number][];
}

const UNKNOWN_COST = 4;
const DIRS: [number, number][] = [
  [1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1],
];
const COMPASS = ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"];

type Opening = { id: number; center: number[]; side: string; blocked: boolean };

/** Heading of a step in 45 degree steps, 0 = east (+x), 2 = north (+y). */
const heading = (dx: number, dy: number): number => ((Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) % 8) + 8) % 8;

class Heap {
  private a: [number, number][] = [];
  get size() { return this.a.length; }
  push(k: number, v: number) {
    const a = this.a;
    a.push([k, v]);
    for (let i = a.length - 1; i > 0; ) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop(): number {
    const a = this.a;
    const top = a[0][1];
    const last = a.pop()!;
    if (a.length) {
      a[0] = last;
      for (let i = 0; ; ) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

/** A* on one floor raster; `blocked` cells are walls and blocked openings. Returns cell indices start..goal, or null. */
export function findPath(plan: Plan, floor: number, start: [number, number], goal: [number, number], blocked: Set<number> = new Set()): number[] | null {
  const img = plan.floors[floor];
  if (!img) return null;
  const { w, h } = plan;
  const idx = (x: number, y: number) => x * h + y;
  const ok = (x: number, y: number) => x >= 0 && y >= 0 && x < w && y < h && img[idx(x, y)] !== 2 && !blocked.has(idx(x, y));
  const snap = ([x, y]: [number, number]): [number, number] | null => {
    for (let r = 0; r <= 3; r++) {
      for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++) if (Math.max(Math.abs(dx), Math.abs(dy)) === r && ok(x + dx, y + dy)) return [x + dx, y + dy];
    }
    return null;
  };
  const s = snap(start), g = snap(goal);
  if (!s || !g) return null;
  const si = idx(...s), gi = idx(...g);
  const cost = new Float64Array(w * h).fill(Infinity);
  const from = new Int32Array(w * h).fill(-1);
  const heap = new Heap();
  cost[si] = 0;
  heap.push(0, si);
  const octile = (x: number, y: number) => {
    const dx = Math.abs(x - g[0]), dy = Math.abs(y - g[1]);
    return Math.max(dx, dy) + (Math.SQRT2 - 1) * Math.min(dx, dy);
  };
  while (heap.size) {
    const i = heap.pop();
    if (i === gi) break;
    const x = Math.floor(i / h), y = i % h;
    for (const [dx, dy] of DIRS) {
      const nx = x + dx, ny = y + dy;
      if (!ok(nx, ny)) continue;
      if (dx && dy && (!ok(x + dx, y) || !ok(x, y + dy))) continue;   // no cutting wall corners
      const ni = idx(nx, ny);
      const c = cost[i] + (dx && dy ? Math.SQRT2 : 1) * (img[ni] === 1 ? 1 : UNKNOWN_COST);
      if (c < cost[ni]) {
        cost[ni] = c;
        from[ni] = i;
        heap.push(c + octile(nx, ny), ni);
      }
    }
  }
  if (from[gi] < 0 && si !== gi) return null;
  const out = [gi];
  for (let i = gi; from[i] >= 0; i = from[i]) out.push(from[i]);
  return out.reverse();
}

/** Turn a cell path into short directions: runs of one heading, short wiggles folded in, turns as left or right. */
export function directions(cells: [number, number][]): string[] {
  const runs: { dir: number; len: number }[] = [];
  for (let i = 1; i < cells.length; i++) {
    const dx = cells[i][0] - cells[i - 1][0], dy = cells[i][1] - cells[i - 1][1];
    const d = heading(dx, dy), step = Math.hypot(dx, dy);
    const last = runs[runs.length - 1];
    if (last && last.dir === d) last.len += step;
    else runs.push({ dir: d, len: step });
  }
  // a one or two meter jog between two longer runs is a wobble of the grid, not a turn
  for (let i = 1; i < runs.length - 1; i++) {
    if (runs[i].len < 2 && runs[i - 1].dir === runs[i + 1].dir) {
      runs[i - 1].len += runs[i].len + runs[i + 1].len;
      runs.splice(i, 2);
      i--;
    }
  }
  const steps: string[] = [];
  runs.forEach((r, i) => {
    const m = Math.max(1, Math.round(r.len));
    const unit = `${m} meter${m === 1 ? "" : "s"}`;
    if (i === 0) return void steps.push(`Go ${unit} ${COMPASS[r.dir]}`);
    const turn = ((r.dir - runs[i - 1].dir + 12) % 8) - 4;   // -4..3: positive is a left (counterclockwise) turn
    const how = turn === 0 ? "keep going" : Math.abs(turn) >= 3 ? "turn around" : `turn ${turn > 0 ? "left" : "right"}${Math.abs(turn) === 1 ? " a little" : ""}`;
    steps.push(`then ${how} and go ${unit} ${COMPASS[r.dir]}`);
  });
  return steps;
}

const cellOf = (plan: Plan, x: number, y: number): [number, number] => [Math.floor(x) - plan.x0, Math.floor(y) - plan.y0];

/** Cells within `r` meters of a point, so a blocked opening stays blocked. */
function disc(plan: Plan, cx: number, cy: number, r: number, into: Set<number>) {
  const [x, y] = cellOf(plan, cx, cy);
  for (let dx = -r; dx <= r; dx++) for (let dy = -r; dy <= r; dy++) {
    if (dx * dx + dy * dy <= r * r && x + dx >= 0 && y + dy >= 0 && x + dx < plan.w && y + dy < plan.h) into.add((x + dx) * plan.h + y + dy);
  }
}

/** The way in for a target: open entrances on its floor, the one with the shortest route wins. */
export function routeTo(live: Live, target: [number, number, number]): Route {
  const plan = live.plan;
  if (!plan) return { found: false, note: "No floor plan yet." };
  const floor = floorOf(live, target[2]);
  if (!plan.floors[floor]) return { found: false, note: `Floor ${floor + 1} is not on the plan yet.` };
  const openings: Opening[] = live.entries.filter((e) => Math.abs(e.normal[2]) < 0.5 && floorOf(live, e.center[2]) === floor);
  const blocked = new Set<number>();
  for (const e of openings) if (e.blocked) disc(plan, e.center[0], e.center[1], 1, blocked);
  const open = openings.filter((e) => !e.blocked);
  if (!open.length) {
    return { found: false, note: floor > 0 ? `Floor ${floor + 1} has no mapped way in yet. Stairs are not on the map.` : "No open entrance is mapped yet." };
  }
  const goal = cellOf(plan, target[0], target[1]);
  let best: { cells: number[]; e: Opening } | null = null;
  for (const e of open) {
    const cells = findPath(plan, floor, cellOf(plan, e.center[0], e.center[1]), goal, blocked);
    if (cells && (!best || cells.length < best.cells.length)) best = { cells, e };
  }
  if (!best) return { found: false, note: "No clear way through the mapped part of the building yet." };
  const img = plan.floors[floor];
  const xy = best.cells.map((i): [number, number] => [Math.floor(i / plan.h), i % plan.h]);
  let len = 0, unmapped = 0;
  for (let i = 1; i < xy.length; i++) {
    const step = Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]);
    len += step;
    if (img[best.cells[i]] !== 1) unmapped += step;
  }
  return {
    found: true,
    lengthM: Math.round(len),
    unmappedM: Math.round(unmapped),
    from: `the ${best.e.side} opening, floor ${floor + 1}`,
    steps: directions(xy),
    path: xy.map(([x, y]) => [x + plan.x0, y + plan.y0]),
    note: unmapped >= 3 ? `About ${Math.round(unmapped)} meters of this route is not mapped yet.` : undefined,
  };
}

/** One sentence per route, as it would be spoken. */
export function speakRoute(r: Route): string {
  if (!r.found) return r.note ?? "No route yet.";
  return `From ${r.from}, about ${r.lengthM} meters. ${r.steps!.join(", ")}. ${r.note ?? ""}`.trim();
}
