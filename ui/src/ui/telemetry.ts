import { MODE_COLORS, yawOf, type DroneState, type Metrics, type SimEvent } from "../types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

function fmtTime(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function battColor(soc: number): string {
  return soc > 0.5 ? "#3ddc97" : soc > 0.25 ? "#ffb020" : "#ff4d4f";
}

/** Header metrics, fleet table, selected-drone card and event log. */
export class Telemetry {
  private fleetBody = $("fleet-body");
  private card = $("drone-card");
  private events = $("events");
  private rows = new Map<number, HTMLTableRowElement>();
  private lastDrones: DroneState[] = [];

  constructor(private onPick: (id: number) => void) {}

  metrics(m: Metrics): void {
    $("m-time").textContent = fmtTime(m.t);
    $("m-cov").textContent = `${(m.coverage * 100).toFixed(1)}%`;
    $("m-found").textContent = `${m.found}/${m.survivors}`;
    $("m-air").textContent = String(m.airborne);
    $("m-lost").textContent = String(m.crashed);
    $("m-lost").parentElement!.classList.toggle("alert", m.crashed > 0);
    const ws = Math.hypot(m.wind[0], m.wind[1]);
    const wd = (Math.atan2(m.wind[1], m.wind[0]) * 180) / Math.PI;
    $("m-wind").innerHTML = `${ws.toFixed(1)} m/s <span class="wind-arrow" style="transform:rotate(${-wd}deg)">→</span>`;
    $("m-fresh").textContent = `avg ${m.mean_age.toFixed(0)}s · ${(m.stale_frac * 100).toFixed(0)}% >120s`;
    $("m-link").textContent = `${m.uplink_kb.toFixed(0)} kB · ${(m.packet_loss * 100).toFixed(1)}% loss`;
    $("m-rtf").textContent = m.running ? `${m.rtf.toFixed(1)}× (set ${m.speed}×)` : "paused";
    $("status-mission").textContent = m.mission_done ? "MISSION COMPLETE" : m.running ? "LIVE" : "PAUSED";
    $("status-mission").className = m.mission_done ? "done" : m.running ? "live" : "paused";
  }

  drones(list: DroneState[], selected: number | null): void {
    this.lastDrones = list;
    for (const d of list) {
      let row = this.rows.get(d.id);
      if (!row) {
        row = document.createElement("tr");
        row.innerHTML = `<td class="id"></td><td class="mode"><span class="badge"></span></td>
          <td class="batt"><div class="bar"><div></div></div></td><td class="alt num"></td><td class="spd num"></td>`;
        row.addEventListener("click", () => this.onPick(d.id));
        this.fleetBody.appendChild(row);
        this.rows.set(d.id, row);
      }
      const color = MODE_COLORS[d.mode];
      row.classList.toggle("selected", d.id === selected);
      row.classList.toggle("crashed", d.crashed);
      (row.querySelector(".id") as HTMLElement).innerHTML = `<span class="dot" style="background:${color}"></span>D${d.id}`;
      const badge = row.querySelector(".badge") as HTMLElement;
      badge.textContent = d.mode;
      badge.style.color = color;
      badge.style.borderColor = color + "66";
      const bar = row.querySelector(".bar > div") as HTMLElement;
      bar.style.width = `${d.soc * 100}%`;
      bar.style.background = battColor(d.soc);
      (row.querySelector(".alt") as HTMLElement).textContent = d.p[2].toFixed(0);
      (row.querySelector(".spd") as HTMLElement).textContent = Math.hypot(...d.v).toFixed(1);
    }
    for (const [id, row] of this.rows) {
      if (!list.some((d) => d.id === id)) {
        row.remove();
        this.rows.delete(id);
      }
    }
    this.renderCard(selected);
  }

  renderCard(selected: number | null): void {
    const d = this.lastDrones.find((x) => x.id === selected);
    if (!d) {
      this.card.classList.add("empty");
      this.card.innerHTML = `<div class="hint">Click a drone (or a fleet row) to follow it.<br>
        <kbd>Esc</kbd> stop following · <kbd>O</kbd> overview · <kbd>Space</kbd> play/pause</div>`;
      return;
    }
    this.card.classList.remove("empty");
    const color = MODE_COLORS[d.mode];
    const speed = Math.hypot(...d.v);
    const flags = [d.avoiding ? "obstacle reflex" : "", d.holding ? "separation hold" : "", d.crashed ? "CRASHED" : ""]
      .filter(Boolean)
      .map((f) => `<span class="flag">${f}</span>`)
      .join("");
    const link = d.link_age === null ? "—" : `${(d.link_age * 1000).toFixed(0)} ms`;
    this.card.innerHTML = `
      <div class="card-head">
        <span class="dot big" style="background:${color}"></span>
        <span class="card-title">Drone ${d.id}</span>
        <span class="badge" style="color:${color};border-color:${color}66">${d.mode}</span>
      </div>
      <div class="flags">${flags}</div>
      <div class="batt-big"><div style="width:${d.soc * 100}%;background:${battColor(d.soc)}"></div><span>${(d.soc * 100).toFixed(0)}%</span></div>
      <dl>
        <dt>Altitude</dt><dd>${d.p[2].toFixed(1)} m <small>(${d.agl.toFixed(1)} AGL)</small></dd>
        <dt>Speed</dt><dd>${speed.toFixed(1)} m/s</dd>
        <dt>Position</dt><dd>${d.p[0].toFixed(0)}, ${d.p[1].toFixed(0)}</dd>
        <dt>Power</dt><dd>${d.power.toFixed(0)} W · ${(d.throttle * 100).toFixed(0)}% thr</dd>
        <dt>Cruise layer</dt><dd>${d.cruise_alt.toFixed(0)} m</dd>
        <dt>Target</dt><dd>${d.target ? `${d.target[0].toFixed(0)}, ${d.target[1].toFixed(0)}` : "—"}</dd>
        <dt>Waypoints</dt><dd>${d.path.length}</dd>
        <dt>Camera</dt><dd>${d.cam_on ? `forward · ${((yawOf(d.q) * 180) / Math.PI).toFixed(0)}° hdg` : "off"}</dd>
        <dt>Last uplink</dt><dd>${link}</dd>
      </dl>`;
  }

  addEvents(evts: SimEvent[]): void {
    for (const e of evts) {
      const li = document.createElement("li");
      li.className = e.level;
      li.innerHTML = `<time>${fmtTime(e.t)}</time>${e.text}`;
      this.events.prepend(li);
    }
    while (this.events.children.length > 120) this.events.lastChild?.remove();
  }

  clearEvents(): void {
    this.events.innerHTML = "";
  }

  connection(ok: boolean): void {
    $("conn").classList.toggle("down", !ok);
    $("conn").title = ok ? "Connected to simulator" : "Disconnected; retrying";
  }
}
