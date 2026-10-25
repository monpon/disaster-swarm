/**
 * The live mission, from SpacetimeDB (module swarm_db, published by the simulator), in the shapes the console already uses.
 *
 * `useLive()` subscribes once per page (in the browser only) and returns the current state; `live.connected` says whether the
 * simulator is publishing. Screens use the live data when it is there and fall back to the demo data in `mock.ts` otherwise, so the
 * console still works with nothing running.
 */
import { useSyncExternalStore } from "react";

import { DbConnection, tables } from "./db/bindings";
import type { Drone, Finding, FindingKind } from "./mock";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;

export interface Plan {
  x0: number;
  y0: number;
  w: number;
  h: number;
  story: number;
  /** One raster per floor, index = x * h + y: 0 unknown, 1 explored, 2 solid. */
  floors: Uint8Array[];
}

/** Metadata of a drone's latest camera frame; the frames themselves go straight to the canvases (see `onFeed`). */
export interface Feed {
  t: number;
  age: number;
  w: number;
  h: number;
}

export interface LiveEvent {
  seq: number;
  t: number;
  level: string;
  text: string;
}

export interface Live {
  connected: boolean;
  world: J | null;
  metrics: J | null;
  drones: J[];
  candidates: J[];
  entries: J[];
  events: LiveEvent[];
  plan: Plan | null;
  feeds: Record<number, Feed>;
}

const EMPTY: Live = { connected: false, world: null, metrics: null, drones: [], candidates: [], entries: [], events: [], plan: null, feeds: {} };

class Store {
  private state: Live = EMPTY;
  private listeners = new Set<() => void>();
  private rows = new Map<string, { text: string; data: Uint8Array }>();
  private events = new Map<number, LiveEvent>();
  private feeds: Record<number, Feed> = {};
  private conn: DbConnection | null = null;
  private feedSeq = new Map<number, number>();
  private bitmaps = new Map<number, ImageBitmap>();
  private feedListeners = new Map<number, Set<(b: ImageBitmap) => void>>();
  private feedSubs = new Map<number, { unsubscribe: () => void }>();
  private wanted: number[] = [];
  private timer: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private readonly id = Math.random().toString(36).slice(2);

  subscribe = (l: () => void) => {
    this.listeners.add(l);
    this.start();
    return () => this.listeners.delete(l);
  };
  getSnapshot = () => this.state;
  getServerSnapshot = () => EMPTY;

  private start(): void {
    if (this.started || typeof window === "undefined") return;
    this.started = true;
    const qs = new URLSearchParams(location.search);
    this.connect(qs.get("stdb") ?? `ws://${location.hostname}:3000`, qs.get("db") ?? "swarm");
    setInterval(() => this.sendSelect(), 4000);
  }

  private connect(uri: string, db: string): void {
    const retry = () => setTimeout(() => this.connect(uri, db), 2000);
    DbConnection.builder()
      .withUri(uri)
      .withDatabaseName(db)
      .onConnect((c) => {
        this.conn = c;
        c.db.entity.onInsert((_x, r) => this.set(r.key, r.text, r.data));
        c.db.entity.onUpdate((_x, _o, r) => this.set(r.key, r.text, r.data));
        c.db.entity.onDelete((_x, r) => {
          this.rows.delete(r.key);
          this.schedule();
        });
        c.db.bulk.onInsert((_x, r) => this.feed(r.key, r.text, r.data));
        c.db.bulk.onUpdate((_x, _o, r) => this.feed(r.key, r.text, r.data));
        c.db.event.onInsert((_x, r) => {
          this.events.set(Number(r.seq), { seq: Number(r.seq), t: r.t, level: r.level, text: r.text });
          this.schedule();
        });
        c.subscriptionBuilder().subscribe([tables.entity, tables.event]);   // the light rows; feeds are subscribed per drone
        this.feedSubs.clear();
        this.syncFeeds();
      })
      .onDisconnect(() => {
        this.conn = null;
        this.state = { ...this.state, connected: false };
        this.emit();
        retry();
      })
      .onConnectError(retry)
      .build();
  }

  private set(key: string, text: string, data: Uint8Array): void {
    this.rows.set(key, { text, data });
    this.schedule();
  }

  private feed(key: string, text: string, data: Uint8Array): void {
    const k = /^feed\/jpg(\d+)$/.exec(key);
    if (!k) return;
    const id = Number(k[1]);
    const m = JSON.parse(text) as Feed;
    const first = !this.feeds[id];
    this.feeds[id] = m;
    if (first) this.schedule();
    const seq = (this.feedSeq.get(id) ?? 0) + 1;
    this.feedSeq.set(id, seq);
    // JPEG frames, decoded off the main thread and handed to the canvases directly: no React render per frame
    void createImageBitmap(new Blob([data.slice()], { type: "image/jpeg" })).then((b) => {
      if (this.feedSeq.get(id) !== seq) return b.close();   // a newer frame already arrived
      this.bitmaps.get(id)?.close();
      this.bitmaps.set(id, b);
      this.feedListeners.get(id)?.forEach((cb) => cb(b));
    });
  }

  /** Call `cb` with each new camera frame of drone `id` (and with the current one at once). Returns the unsubscribe. */
  onFeed(id: number, cb: (b: ImageBitmap) => void): () => void {
    let set = this.feedListeners.get(id);
    if (!set) this.feedListeners.set(id, (set = new Set()));
    set.add(cb);
    const cur = this.bitmaps.get(id);
    if (cur) cb(cur);
    return () => set!.delete(cb);
  }

  private schedule(): void {
    if (this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.rebuild();
    }, 150);
  }

  private json(key: string): J {
    const r = this.rows.get(key);
    return r ? JSON.parse(r.text) : null;
  }

  private list(prefix: string): J[] {
    return [...this.rows.keys()].filter((k) => k.startsWith(prefix)).map((k) => this.json(k)).sort((a, b) => a.id - b.id);
  }

  private rebuild(): void {
    const world = this.json("world");
    const metrics = this.json("metrics");
    let plan: Plan | null = null;
    const floors: Uint8Array[] = [];
    let meta: J = null;
    for (let k = 0; this.rows.has(`plan/${k}`); k++) {
      const r = this.rows.get(`plan/${k}`)!;
      meta = JSON.parse(r.text);
      floors.push(r.data);
    }
    if (meta && floors.length) plan = { ...meta, floors };
    this.state = {
      connected: !!world && !!metrics,
      world,
      metrics,
      drones: this.list("drone/"),
      candidates: this.list("candidate/"),
      entries: this.list("entry/"),
      events: [...this.events.values()].sort((a, b) => a.seq - b.seq),
      plan,
      feeds: { ...this.feeds },
    };
    this.emit();
  }

  private emit(): void {
    for (const l of this.listeners) l();
  }

  /** Ask the simulator for these drones' camera feeds (it publishes only what somebody is watching). */
  watchFeeds(ids: number[]): void {
    this.wanted = ids;
    this.syncFeeds();
    this.sendSelect();
  }

  private syncFeeds(): void {
    const c = this.conn;
    if (!c) return;
    for (const [id, sub] of this.feedSubs) {
      if (!this.wanted.includes(id)) {
        sub.unsubscribe();
        this.feedSubs.delete(id);
        delete this.feeds[id];
        this.bitmaps.get(id)?.close();
        this.bitmaps.delete(id);
      }
    }
    for (const id of this.wanted) {
      if (!this.feedSubs.has(id)) this.feedSubs.set(id, c.subscriptionBuilder().subscribe([`SELECT * FROM bulk WHERE key = 'feed/jpg${id}'`]));
    }
  }

  private sendSelect(): void {
    this.conn?.reducers.submitCmd({ name: "select", args: JSON.stringify({ drones: this.wanted, client: this.id }) });
  }

  /** A command for the simulator: play, pause, speed, step, reset, recall. */
  command(name: string, args: Record<string, unknown> = {}): void {
    this.conn?.reducers.submitCmd({ name, args: JSON.stringify(args) });
  }
}

export const store = new Store();

export function useLive(): Live {
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
}

// ---------------------------------------------------------------- mappings to the console's own shapes

export const droneName = (id: number) => `D${id}`;
export const droneNumber = (name: string) => Number(name.slice(1));

export function clock(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export const floorOf = (live: Live, z: number): number => Math.floor(z / (live.world?.building?.story ?? 5));

export function liveMission(live: Live) {
  const m = live.metrics, w = live.world;
  const preset = w?.presets?.[w?.config?.preset]?.label ?? "Simulated building";
  const targets = 0;
  return {
    address: preset,
    city: "Simulated site",
    type: `Seed ${w?.config?.seed ?? ""}`.trim(),
    elapsed: clock(m?.t ?? 0),
    coverage: Math.round((m?.explored ?? 0) * 100),
    roomsLeft: targets,
  };
}

export function liveDrones(live: Live): (Drone & { n: number; mode: string })[] {
  return live.drones.map((d) => ({
    n: d.id,
    mode: d.mode,
    id: droneName(d.id),
    room: d.crashed ? "Lost" : `Floor ${floorOf(live, d.ep[2]) + 1} · ${d.mode}`,
    airframe: "Simulated quadrotor, 30 cm",
    ip: `${d.hops} hop${d.hops === 1 ? "" : "s"} to base`,
    battery: Math.round(d.soc * 100),
    signal: d.link > 0 ? Math.round(d.snr - 92) : null,   // dBm = SNR over the noise floor
    altitude: Math.round(d.ep[2] * 10) / 10,
    status: d.crashed ? "offline" : d.frozen ? "calibrate" : d.grounded || d.mode === "charging" ? "charging" : "ready",
    feed: "/assets/f1.png",
    holding: d.holding || d.mode === "relay",
  }));
}

export interface LiveFinding extends Finding {
  world?: [number, number, number];
  floor?: number;
  vitals?: { hr: number; rr: number; confidence: number } | null;
  tier?: string;
  drone?: number | null;
}

export function liveFindings(live: Live): LiveFinding[] {
  const out: LiveFinding[] = [];
  const cands = live.candidates.filter((c) => c.confirmed).sort((a, b) => (b.urgency ?? -1) - (a.urgency ?? -1));
  for (const c of cands) {
    const fl = floorOf(live, c.pos[2]);
    out.push({
      id: `c${c.id}`,
      kind: "person",
      title: c.tier ? `Survivor #${c.id}: ${c.tier}` : `Survivor #${c.id}`,
      detail: c.vitals
        ? `Floor ${fl + 1}. Heart rate ${c.vitals.hr}, breathing ${c.vitals.rr}/min (simulated vitals).`
        : `Floor ${fl + 1}. Reading vitals…`,
      confidence: c.urgency >= 0 ? c.urgency / 100 : null,
      world: c.pos,
      floor: fl,
      vitals: c.vitals,
      tier: c.tier,
      drone: c.drone,
    });
  }
  for (const e of live.entries) {
    if (Math.abs(e.normal[2]) > 0.5) continue;
    const fl = floorOf(live, e.center[2]);
    const kind: FindingKind = e.blocked ? "blockage" : "door";
    out.push({
      id: `e${e.id}`,
      kind,
      title: e.blocked ? "Opening blocked by debris" : `Opening #${e.id}`,
      detail: `${e.side}, floor ${fl + 1}, ${Math.round(e.w)} x ${Math.round(e.h)} m.`,
      confidence: null,
      world: e.center,
      floor: fl,
    });
  }
  return out;
}

const KIND_COLOR: Record<string, string> = { person: "var(--color-person)", door: "var(--color-door)", hazard: "var(--color-hazard)" };

/** Ticks for the timeline: where along the mission so far each notable event happened. */
export function liveTicks(live: Live): { at: number; color: string }[] {
  const T = Math.max(live.metrics?.t ?? 1, 1);
  const out: { at: number; color: string }[] = [];
  for (const e of live.events) {
    const kind = /Survivor/.test(e.text) ? "person" : /pening|ntry|inside/.test(e.text) ? "door" : /stuck|lost|crash/.test(e.text) ? "hazard" : null;
    if (kind) out.push({ at: Math.min((e.t / T) * 100, 99), color: KIND_COLOR[kind]! });
  }
  return out;
}

export function liveMessages(live: Live) {
  return live.events.slice(-14).map((e) => ({ id: String(e.seq), at: clock(e.t), from: null as string | null, text: e.text }));
}

/** Fit the plan into a stage of w x h pixels: world (x, y) to stage pixels (north up). */
export function planTransform(plan: Plan, w: number, h: number, margin = 60) {
  const s = Math.min((w - 2 * margin) / plan.w, (h - 2 * margin) / plan.h);
  const ox = (w - plan.w * s) / 2, oy = (h - plan.h * s) / 2;
  return { s, ox, oy, at: (x: number, y: number): [number, number] => [ox + (x - plan.x0) * s, oy + (plan.y0 + plan.h - y) * s] };
}

/** Where the 3D viewer is served (the simulator's server, same host as the database unless `?viewer=` says otherwise). */
export function viewerUrl(): string {
  const qs = new URLSearchParams(location.search);
  const v = qs.get("viewer");
  if (v) return v;
  const db = qs.get("stdb") ?? `ws://${location.hostname}:3000`;
  const base = `http://${new URL(db).hostname}:8000/`;
  return `${base}?embed=cloud&stdb=${encodeURIComponent(db)}&db=${encodeURIComponent(qs.get("db") ?? "swarm")}`;
}
