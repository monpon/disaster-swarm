import { inflate } from "./realview";
import { MODE_COLORS, type Candidate, type DroneState, type MapEntry } from "../types";

/** The master's live floor plan: a raster per floor (0 unknown, 1 explored free space, 2 solid) with doors, drones, relays and
 * survivors on top. Drawn on a 2D canvas, redrawn on every state message while the plan view is showing. */
export interface PlanData {
  x0: number;
  y0: number;
  w: number;
  h: number;
  story: number;
  floors: string[];
}

const TIER_COLOR: Record<string, string> = { IMMEDIATE: "#ff4d4f", URGENT: "#ffb020", DELAYED: "#3ddc97" };

export class PlanView {
  private canvas = document.getElementById("plan-canvas") as HTMLCanvasElement;
  private tabs = document.getElementById("plan-tabs") as HTMLElement;
  private raster: { x0: number; y0: number; w: number; h: number; story: number; imgs: HTMLCanvasElement[] } | null = null;
  private floor = -1; // -1 = all floors
  private busy = false;
  visible = false;
  private zoom = 1;
  private panX = 0;
  private panY = 0;
  private last: { drones: DroneState[]; entries: MapEntry[]; cands: Candidate[] } = { drones: [], entries: [], cands: [] };

  constructor() {
    new ResizeObserver(() => this.redraw()).observe(this.canvas.parentElement!);
    // zoom with the wheel (about the pointer), drag to pan, double-click to reset
    const cv = this.canvas;
    cv.style.cursor = "grab";
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const box = cv.getBoundingClientRect();
      const sx = e.clientX - box.left, sy = e.clientY - box.top;
      const z0 = this.zoom, z1 = Math.min(Math.max(z0 * Math.exp(-e.deltaY * 0.0015), 0.4), 14);
      const cx = box.width / 2, cy = box.height / 2;
      this.panX = sx - cx - (sx - cx - this.panX) * (z1 / z0);
      this.panY = sy - cy - (sy - cy - this.panY) * (z1 / z0);
      this.zoom = z1;
      this.redraw();
    }, { passive: false });
    let drag: { x: number; y: number } | null = null;
    cv.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      cv.setPointerCapture(e.pointerId);
      cv.style.cursor = "grabbing";
    });
    cv.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.panX += e.clientX - drag.x;
      this.panY += e.clientY - drag.y;
      drag = { x: e.clientX, y: e.clientY };
      this.redraw();
    });
    const end = () => { drag = null; cv.style.cursor = "grab"; };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("dblclick", () => { this.zoom = 1; this.panX = 0; this.panY = 0; this.redraw(); });
    this.tabs.addEventListener("click", (e) => {
      const b = (e.target as HTMLElement).closest("button");
      if (!b) return;
      this.floor = Number(b.dataset.floor);
      this.markTabs();
      this.redraw();
    });
  }

  async setPlan(p: PlanData | null | undefined): Promise<void> {
    if (!p || this.busy) return;
    this.busy = true;
    try {
      const rasters = await Promise.all(p.floors.map((f) => inflate(f)));
      const imgs = rasters.map((r) => {
        const c = document.createElement("canvas");
        c.width = p.w;
        c.height = p.h;
        const ctx = c.getContext("2d")!;
        const img = ctx.createImageData(p.w, p.h);
        for (let x = 0; x < p.w; x++) {
          for (let y = 0; y < p.h; y++) {
            const v = r[x * p.h + y];
            const o = ((p.h - 1 - y) * p.w + x) * 4; // +y is up
            if (v === 1) { img.data[o] = 38; img.data[o + 1] = 86; img.data[o + 2] = 104; img.data[o + 3] = 150; }
            else if (v === 2) { img.data[o] = 232; img.data[o + 1] = 238; img.data[o + 2] = 250; img.data[o + 3] = 255; }
          }
        }
        ctx.putImageData(img, 0, 0);
        return c;
      });
      const rebuild = !this.raster || this.raster.imgs.length !== imgs.length;
      this.raster = { x0: p.x0, y0: p.y0, w: p.w, h: p.h, story: p.story, imgs };
      if (rebuild) this.buildTabs();
      this.redraw();
    } finally {
      this.busy = false;
    }
  }

  private buildTabs(): void {
    const n = this.raster?.imgs.length ?? 0;
    this.tabs.innerHTML = `<button data-floor="-1">All</button>` + Array.from({ length: n }, (_, i) => `<button data-floor="${i}">F${i + 1}</button>`).join("");
    this.floor = Math.min(this.floor, Math.max(n - 1, -1));
    this.markTabs();
  }

  private markTabs(): void {
    this.tabs.querySelectorAll("button").forEach((b) => b.classList.toggle("on", Number((b as HTMLElement).dataset.floor) === this.floor));
  }

  draw(drones: DroneState[], entries: MapEntry[], cands: Candidate[]): void {
    this.last = { drones, entries, cands };
    if (this.visible) this.redraw();
  }

  private redraw(): void {
    const cv = this.canvas;
    const par = cv.parentElement!;
    const dpr = window.devicePixelRatio || 1;
    const W = par.clientWidth, H = par.clientHeight;
    if (!W || !H) return;
    if (cv.width !== W * dpr || cv.height !== H * dpr) {
      cv.width = W * dpr;
      cv.height = H * dpr;
      cv.style.width = `${W}px`;
      cv.style.height = `${H}px`;
    }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const r = this.raster;
    if (!r) {
      ctx.fillStyle = "#8a93a6";
      ctx.font = "13px Inter, sans-serif";
      ctx.fillText("waiting for the master's map…", 24, 40);
      return;
    }
    const n = r.imgs.length;
    const floors = this.floor < 0 ? Array.from({ length: n }, (_, i) => i) : [this.floor];
    // tile the floors (one fills the view; "All" lays them out in the grid that gives the biggest plans)
    let cols = 1, best = 0;
    for (let c = 1; c <= floors.length; c++) {
      const rows = Math.ceil(floors.length / c);
      const sc = Math.min((W - 80 - 30 * (c - 1)) / (c * r.w), (H - 130 - 40 * (rows - 1)) / (rows * r.h));
      if (sc > best) { best = sc; cols = c; }
    }
    const rows = Math.ceil(floors.length / cols);
    const s = best;
    const gapX = 30, gapY = 40;
    const gridW = cols * r.w * s + (cols - 1) * gapX, gridH = rows * r.h * s + (rows - 1) * gapY;
    const inv = 1 / this.zoom;
    ctx.save();
    ctx.translate(W / 2 + this.panX, H / 2 + this.panY);
    ctx.scale(this.zoom, this.zoom);
    ctx.translate(-W / 2, -H / 2);
    ctx.font = `600 ${11 * inv}px 'JetBrains Mono', monospace`;
    floors.forEach((fl, idx) => {
      const ox = (W - gridW) / 2 + (idx % cols) * (r.w * s + gapX);
      const oy = 70 + (H - 130 - gridH) / 2 + Math.floor(idx / cols) * (r.h * s + gapY);
      const px = (x: number) => ox + (x - r.x0) * s;
      const py = (y: number) => oy + (r.y0 + r.h - y) * s;
      ctx.fillStyle = "rgba(94,200,255,0.04)";
      ctx.fillRect(ox, oy, r.w * s, r.h * s);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(r.imgs[fl], ox, oy, r.w * s, r.h * s);
      if (floors.length > 1) {
        ctx.fillStyle = "#cfd6e4";
        ctx.fillText(`F${fl + 1}`, ox, oy - 8 * inv);
      }
      // 10 m grid
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = inv;
      for (let x = Math.ceil(r.x0 / 10) * 10; x < r.x0 + r.w; x += 10) { ctx.beginPath(); ctx.moveTo(px(x), oy); ctx.lineTo(px(x), oy + r.h * s); ctx.stroke(); }
      for (let y = Math.ceil(r.y0 / 10) * 10; y < r.y0 + r.h; y += 10) { ctx.beginPath(); ctx.moveTo(ox, py(y)); ctx.lineTo(ox + r.w * s, py(y)); ctx.stroke(); }
      const onFloor = (z: number) => Math.floor(z / r.story) === fl;
      // openings
      for (const e of this.last.entries) {
        if (!onFloor(e.center[2]) || Math.abs(e.normal[2]) > 0.5) continue;
        const alongY = Math.abs(e.normal[0]) >= Math.abs(e.normal[1]);
        const hw = Math.max(e.w, 1) / 2;
        ctx.strokeStyle = e.blocked ? "#ff4d4f" : "#f6e05e";
        ctx.lineWidth = Math.max(3 * inv, s * 0.5);
        ctx.lineCap = "butt";
        ctx.beginPath();
        if (alongY) { ctx.moveTo(px(e.center[0]), py(e.center[1] - hw)); ctx.lineTo(px(e.center[0]), py(e.center[1] + hw)); }
        else { ctx.moveTo(px(e.center[0] - hw), py(e.center[1])); ctx.lineTo(px(e.center[0] + hw), py(e.center[1])); }
        ctx.stroke();
      }
      // survivors (candidates): confirmed ones in their triage colour
      for (const c of this.last.cands) {
        if ((c.dismissed && !c.confirmed) || !onFloor(c.pos[2])) continue;
        const col = c.confirmed ? (c.tier ? TIER_COLOR[c.tier] ?? "#5ec8ff" : "#5ec8ff") : "#ffb020";
        ctx.fillStyle = col;
        ctx.strokeStyle = "#0b0f17";
        ctx.lineWidth = 2 * inv;
        ctx.beginPath();
        ctx.arc(px(c.pos[0]), py(c.pos[1]), c.confirmed ? Math.max(4 * inv, s * 0.9) : Math.max(3 * inv, s * 0.6), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (c.confirmed) {
          ctx.fillStyle = "#e8edf7";
          ctx.fillText(c.vitals ? `#${c.id} ${c.vitals.hr}/${c.vitals.rr.toFixed(0)}` : `#${c.id}`, px(c.pos[0]) + 8 * inv, py(c.pos[1]) + 4 * inv);
        }
      }
      // drones at the pose the master believes
      for (const d of this.last.drones) {
        if (d.crashed || !onFloor(d.ep[2])) continue;
        const col = MODE_COLORS[d.mode] ?? "#cbd5e1";
        const x = px(d.ep[0]), y = py(d.ep[1]);
        ctx.fillStyle = col;
        ctx.strokeStyle = "#0b0f17";
        ctx.lineWidth = 2 * inv;
        ctx.beginPath();
        ctx.arc(x, y, Math.max(3.5 * inv, s * 0.7), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        if (d.mode === "relay") {
          ctx.strokeStyle = "#5ec8ff";
          ctx.lineWidth = 1.5 * inv;
          ctx.beginPath();
          ctx.arc(x, y, Math.max(8 * inv, s * 1.8), 0, Math.PI * 2);
          ctx.stroke();
        }
        ctx.fillStyle = "#cfd6e4";
        ctx.fillText(String(d.id), x + 6 * inv, y - 5 * inv);
      }
    });
    ctx.restore();
    // title and legend
    ctx.fillStyle = "#cfd6e4";
    ctx.font = "600 12px 'JetBrains Mono', monospace";
    ctx.fillText(`LIVE FLOOR PLAN · ${this.floor < 0 ? "all floors" : `F${this.floor + 1}`} · from the master's map  ·  scroll = zoom, drag = pan, double-click = reset`, 20, 28);
    ctx.font = "11px 'JetBrains Mono', monospace";
    const items: [string, string][] = [["#e8eefa", "wall / solid"], ["#265668", "explored"], ["#f6e05e", "opening"], ["#5ec8ff", "relay ring"],
      ["#ff4d4f", "survivor: immediate"], ["#ffb020", "urgent / candidate"], ["#3ddc97", "delayed"]];
    let lx = 20;
    for (const [c, t] of items) {
      ctx.fillStyle = c;
      ctx.fillRect(lx, H - 30, 10, 10);
      ctx.fillStyle = "#9aa3b5";
      ctx.fillText(t, lx + 15, H - 21);
      lx += 15 + ctx.measureText(t).width + 16;
    }
  }
}
