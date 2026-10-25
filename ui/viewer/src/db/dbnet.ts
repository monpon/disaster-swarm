import { DbConnection, tables } from "./bindings";
import type { ServerMessage, SimEvent } from "../types";

type Handler = (msg: ServerMessage) => void;

/** The live state, from SpacetimeDB instead of the simulator's websocket: subscribes to the `entity`, `event` tables of the
 * `swarm_db` module and re-assembles the same messages the viewer already consumes (world, snapshot/state). Row changes are
 * coalesced to one message per animation frame. Commands go back through the `submit_cmd` reducer. */
export class DbNet {
  onOpen: (() => void) | null = null;
  private conn: DbConnection | null = null;
  private rows = new Map<string, { text: string; data: Uint8Array }>();
  private parsed = new Map<string, { text: string; value: unknown }>();
  private events = new Map<number, SimEvent>();
  private sentEvents = 0;
  private dirty = new Set<string>();
  private worldText = "";
  private first = true;
  private scheduled = false;
  private mapKeys = new Set<string>();   // map rows (vox/pt/seen/mesh) changed since the last flush
  private feedKeys = new Set<string>();
  private selected: number | null = null;
  private readonly id = Math.random().toString(36).slice(2);

  constructor(
    private readonly onMessage: Handler,
    private readonly onStatus: (ok: boolean) => void,
    private readonly uri: string,
    private readonly db: string,
  ) {
    this.connect();
  }

  private connect(): void {
    DbConnection.builder()
      .withUri(this.uri)
      .withDatabaseName(this.db)
      .onConnect((c) => {
        this.conn = c;
        this.onStatus(true);
        for (const t of [c.db.entity, c.db.bulk]) {   // the light and the heavy rows share one key space
          t.onInsert((_ctx, r) => this.set(r.key, r.text, r.data));
          t.onUpdate((_ctx, _o, r) => this.set(r.key, r.text, r.data));
          t.onDelete((_ctx, r) => {
            this.rows.delete(r.key);
            this.dirty.add(r.key);
            this.schedule();
          });
        }
        c.db.event.onInsert((_ctx, r) => {
          this.events.set(Number(r.seq), { t: r.t, level: r.level as SimEvent["level"], text: r.text });
          this.schedule();
        });
        c.subscriptionBuilder().subscribe([tables.entity, tables.bulk, tables.event]);
        this.sendSelect();
        this.onOpen?.();
      })
      .onDisconnect(() => {
        this.conn = null;
        this.onStatus(false);
        setTimeout(() => this.connect(), 1500);
      })
      .onConnectError(() => {
        this.onStatus(false);
        setTimeout(() => this.connect(), 1500);
      })
      .build();
  }

  private set(key: string, text: string, data: Uint8Array): void {
    this.rows.set(key, { text, data });
    if (/^(vox|pt|seen|mesh)\//.test(key)) this.mapKeys.add(key);
    else if (/^feed\/\d+$/.test(key)) this.feedKeys.add(key);   // (feed/jpg<N> rows are the console's)
    else this.dirty.add(key);
    this.schedule();
  }

  private schedule(): void {
    if (this.scheduled) return;
    this.scheduled = true;
    requestAnimationFrame(() => {
      this.scheduled = false;
      this.flush();
    });
  }

  private json<T>(key: string): T | undefined {
    const r = this.rows.get(key);
    if (!r) return undefined;
    const hit = this.parsed.get(key);
    if (hit && hit.text === r.text) return hit.value as T;
    const value = JSON.parse(r.text) as T;
    this.parsed.set(key, { text: r.text, value });
    return value;
  }

  private list<T extends { id: number }>(prefix: string): T[] {
    const out: T[] = [];
    for (const k of this.rows.keys()) if (k.startsWith(prefix)) out.push(this.json<T>(k)!);
    return out.sort((a, b) => a.id - b.id);
  }

  private flush(): void {
    const world = this.rows.get("world");
    if (!world) return;
    if (world.text !== this.worldText) {   // a new mission
      this.worldText = world.text;
      this.first = true;
      this.sentEvents = 0;
      this.parsed.clear();
      this.mapKeys.clear();
      for (const k of this.rows.keys()) if (/^(vox|pt|seen|mesh)\//.test(k)) this.mapKeys.add(k);   // rows that arrived before the world
      this.dirty.add("plan/");
      this.onMessage(JSON.parse(world.text) as ServerMessage);
    }
    const metrics = this.json<Record<string, unknown>>("metrics");
    if (!metrics) return;
    this.flushFeed();
    const planChanged = [...this.dirty].some((k) => k.startsWith("plan/")) || this.first;
    this.dirty.clear();
    const seqs = [...this.events.keys()].sort((a, b) => a - b);
    const fresh = seqs.slice(this.sentEvents).map((s) => this.events.get(s)!);
    this.sentEvents = seqs.length;
    const planFloors: string[] = [];
    let planMeta: Record<string, number> | undefined;
    if (planChanged) {
      for (let k = 0; this.rows.has(`plan/${k}`); k++) {
        const r = this.rows.get(`plan/${k}`)!;
        planMeta = JSON.parse(r.text);
        let bin = "";
        for (let i = 0; i < r.data.length; i += 0x8000) bin += String.fromCharCode(...r.data.subarray(i, i + 0x8000));
        planFloors.push(btoa(bin));
      }
    }
    const msg: Record<string, unknown> = {
      type: this.first ? "snapshot" : "state",
      drones: this.list("drone/"),
      metrics,
      ...this.buildMap(metrics),
      entries: this.list("entry/"),
      candidates: this.list("candidate/"),
      found: this.json("found") ?? [],
      mesh: this.json("links") ?? [],
      targets: this.json("targets") ?? [],
      events: fresh,
      history: this.first ? (this.json("history_all") ?? []) : (this.json("history") ?? null),
    };
    if (planMeta && planFloors.length) msg.plan = { ...planMeta, floors: planFloors };
    this.first = false;
    this.onMessage(msg as unknown as ServerMessage);
  }

  /** The 3D map from the rows that changed: voxel blocks, point blocks, scan freshness and mesh chunks, in the delta shapes the
   * map view already applies. */
  private buildMap(metrics: Record<string, unknown>): { map: unknown; seen?: unknown } {
    const vi: number[] = [], vr: number[] = [], vq: number[] = [];
    const pid: number[] = [], ppos: number[] = [], psm: number[] = [], pcol: number[] = [], pfl: number[] = [], pre: number[] = [], pnp: number[] = [];
    const si: number[] = [], st: number[] = [];
    const surf: unknown[] = [];
    for (const key of this.mapKeys) {
      const r = this.rows.get(key);
      if (!r) continue;
      const [kind, bs] = key.split("/");
      const b = Number(bs);
      const d = r.data.slice();   // a fresh buffer: typed views need aligned offsets
      if (kind === "vox") {
        const rgb = new Uint16Array(d.buffer, 0, 4096), q = d.subarray(8192, 8192 + 4096);
        for (let i = 0; i < 4096; i++) if (q[i]) { vi.push(b * 4096 + i); vr.push(rgb[i]); vq.push(q[i]); }
      } else if (kind === "seen") {
        const t = new Uint16Array(d.buffer, 0, 4096);
        for (let i = 0; i < 4096; i++) if (t[i]) { si.push(b * 4096 + i); st.push(t[i]); }
      } else if (kind === "pt") {
        const PB = 64;   // points per block (see stdb.py)
        const oPos = PB, oSm = oPos + PB * 6, oCol = oSm + PB * 6, oFlag = oCol + PB * 3;
        const valid = d.subarray(0, PB), pos = new Uint16Array(d.buffer, oPos, PB * 3), sm = new Uint16Array(d.buffer, oSm, PB * 3);
        const col = d.subarray(oCol, oCol + PB * 3), flag = d.subarray(oFlag, oFlag + PB), resid = d.subarray(oFlag + PB, oFlag + 2 * PB), npass = d.subarray(oFlag + 2 * PB, oFlag + 3 * PB);
        for (let i = 0; i < PB; i++) {
          if (!valid[i]) continue;
          pid.push(b * PB + i);
          for (let a = 0; a < 3; a++) { ppos.push(pos[3 * i + a]); psm.push(sm[3 * i + a]); pcol.push(col[3 * i + a]); }
          pfl.push(flag[i]); pre.push(resid[i]); pnp.push(npass[i]);
        }
      } else {
        const m = JSON.parse(r.text) as { nv: number; w: boolean; lv: number; ln: number; lc: number; lf: number };
        if (!m.nv) { surf.push({ id: b, nv: 0 }); continue; }
        let o = 0;
        const take = (n: number) => { const s = d.slice(o, o + n); o += n; return s; };
        const v = take(m.lv), n = take(m.ln), c = take(m.lc), f = take(m.lf);
        surf.push({ id: b, nv: m.nv, w: m.w, v, n, c, f });
      }
    }
    this.mapKeys.clear();
    const map = {
      idx: new Int32Array(vi), rgb: new Uint16Array(vr), q: new Uint8Array(vq), mat: new Uint8Array(0), free: new Int32Array(0), n: vi.length,
      uidx: new Uint32Array(pid), upos: new Uint16Array(ppos), uspos: new Uint16Array(psm), ucol: new Uint8Array(pcol),
      uflag: new Uint8Array(pfl), uresid: new Uint8Array(pre), unpass: new Uint8Array(pnp), nu: pid.length,
      ptotal: Number(metrics.points ?? 0), surf,
    };
    return { map, ...(si.length ? { seen: { idx: new Int32Array(si), t: new Uint16Array(st) } } : {}) };
  }

  /** Camera feeds of the drone this viewer has selected. */
  private flushFeed(): void {
    for (const key of this.feedKeys) {
      const d = Number(key.split("/")[1]);
      const r = this.rows.get(key);
      if (!r || d !== this.selected) continue;
      const m = JSON.parse(r.text) as { t: number; age: number; w: number; h: number; frames: number[]; backlog: number; jpeg_kb: number };
      const buf = r.data.slice();
      this.onMessage({ type: "feed", drone: d, ...m, rgb: buf.subarray(0, m.w * m.h * 3), depth: buf.subarray(m.w * m.h * 3) } as unknown as ServerMessage);
    }
    this.feedKeys.clear();
  }

  private beat: ReturnType<typeof setInterval> | null = null;

  /** Tell the simulator which drone's camera this viewer wants (it publishes feeds only for drones somebody is watching). */
  select(drone: number | null): void {
    this.selected = drone;
    this.feedKeys.clear();
    this.sendSelect();
    if (!this.beat) this.beat = setInterval(() => this.sendSelect(), 4000);
  }

  private sendSelect(): void {
    this.conn?.reducers.submitCmd({ name: "select", args: JSON.stringify({ drone: this.selected, client: this.id }) });
  }

  control(cmd: string, extra: Record<string, unknown> = {}): void {
    this.conn?.reducers.submitCmd({ name: cmd, args: JSON.stringify(extra) });
  }
}
