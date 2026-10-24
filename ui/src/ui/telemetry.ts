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

function linkColor(mbps: number): string {
  return mbps >= 8 ? "#3ddc97" : mbps >= 2 ? "#e8d44d" : mbps > 0 ? "#ff8c42" : "#ff4d4f";
}

const PHASE_LABEL: Record<string, string> = {
  scout: "0 · SCOUTING SITE",
  operate: "1 · MAPPING",
  verify: "2 · VERIFY PASS",
  complete: "3 · COMPLETE",
};

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
    $("m-phase").textContent = (PHASE_LABEL[m.phase] ?? m.phase) +
      (m.phase === "operate" ? ` · outside ${(m.ext_cov * 100).toFixed(0)}% seen` : "");
    $("m-entries").textContent = `${m.entries_usable}/${m.entries}`;
    $("m-explored").textContent = `${(m.explored * 100).toFixed(1)}%`;
    $("m-scanned").textContent = `${(m.scanned * 100).toFixed(1)}%`;
    $("m-found").textContent = `${m.found}/${m.survivors}`;
    $("m-air").textContent = String(m.airborne);
    $("m-relays").textContent = `${m.relays}/${m.slots}`;
    $("m-losses").textContent = String(m.lost_events);
    $("m-losses").parentElement!.classList.toggle("alert", m.lost_events > 0);
    $("m-lost").textContent = String(m.crashed);
    $("m-lost").parentElement!.classList.toggle("alert", m.crashed > 0);
    const tot = m.frames_ok + m.frames_dropped;
    $("m-drift").textContent = `${m.drift.toFixed(2)} m`;
    $("m-verified").textContent = `${(m.verified * 100).toFixed(1)}%`;
    $("m-align").textContent = `${(m.align_ok * 100).toFixed(0)}% · ${m.align_mm.toFixed(0)} mm`;
    $("m-error").textContent = m.rms_raw === undefined ? "-" :
      `${(m.rms_raw * 100).toFixed(0)} → ${(m.rms_smooth! * 100).toFixed(0)} cm`;
    $("m-smoother").textContent = `${m.smoother} · ${m.smooth_ms.toFixed(0)} ms` +
      (m.mesh.backend === "off" ? "" : ` · mesh ${(m.mesh.tris / 1000).toFixed(0)}k tris`);
    $("m-link").textContent = `${m.radio_mb.toFixed(0)} MB · ${tot ? ((m.frames_dropped / tot) * 100).toFixed(1) : "0.0"}% lost`;
    $("m-rtf").textContent = m.running ? `${m.rtf.toFixed(1)}× (set ${m.speed}×)` : "paused";
    const done = m.phase === "complete";
    $("status-mission").textContent = done ? "MISSION COMPLETE" : m.running ? "LIVE" : "PAUSED";
    $("status-mission").className = done ? "done" : m.running ? "live" : "paused";
  }

  drones(list: DroneState[], selected: number | null): void {
    this.lastDrones = list;
    for (const d of list) {
      let row = this.rows.get(d.id);
      if (!row) {
        row = document.createElement("tr");
        row.innerHTML = `<td class="id"></td><td class="mode"><span class="badge"></span></td>
          <td class="batt"><div class="bar"><div></div></div></td><td class="lnk num"></td><td class="bk num"></td>`;
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
      const lnk = row.querySelector(".lnk") as HTMLElement;
      lnk.textContent = d.grounded ? "—" : d.link > 0 ? `${d.link.toFixed(1)}${d.hops > 1 ? `·${d.hops}h` : ""}${d.holding ? " ⏸" : ""}` : "LOST";
      lnk.title = d.grounded ? "" : `signal to next hop ${d.snr} dB${d.holding ? " · holding at the edge of coverage" : ""}${d.slot ? ` · relay post ${d.slot}` : ""}`;
      lnk.style.color = d.grounded ? "" : linkColor(d.link);
      const bk = row.querySelector(".bk") as HTMLElement;
      bk.textContent = d.grounded ? "" : d.drift.toFixed(1);
      bk.style.color = d.drift > 1.5 ? "#ff8c42" : "";
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
      this.card.innerHTML = `<div class="hint">Click a drone (or a fleet row) to follow it and see its camera feed.<br>
        <kbd>Tab</kbd> real/map/split · <kbd>F</kbd> floor cutaway · <kbd>C</kbd> map coloring<br>
        <kbd>Esc</kbd> stop following · <kbd>O</kbd> overview · <kbd>Space</kbd> play/pause</div>`;
      return;
    }
    this.card.classList.remove("empty");
    const color = MODE_COLORS[d.mode];
    const speed = Math.hypot(...d.v);
    const flags = [
      d.frozen ? "link lost: ESP failsafe hover, awaiting relay" : "",
      d.landing_auto ? "battery flat: auto-landing" : "",
      d.serves !== null ? `relaying D${d.serves}` : "",
      d.crashed ? "CRASHED" : "",
    ]
      .filter(Boolean)
      .map((f) => `<span class="flag">${f}</span>`)
      .join("");
    const route = d.route.length ? d.route.map((n) => (n < 0 ? "M" : `D${n}`)).join(" → ") : "no route";
    this.card.innerHTML = `
      <div class="card-head">
        <span class="dot big" style="background:${color}"></span>
        <span class="card-title">Drone ${d.id}</span>
        <span class="badge" style="color:${color};border-color:${color}66">${d.mode}</span>
      </div>
      <div class="flags">${flags}</div>
      <div class="batt-big"><div style="width:${d.soc * 100}%;background:${battColor(d.soc)}"></div><span>${(d.soc * 100).toFixed(0)}%</span></div>
      <dl>
        <dt>Position</dt><dd>${d.p[0].toFixed(1)}, ${d.p[1].toFixed(1)}, ${d.p[2].toFixed(1)} <small>(true)</small></dd>
        <dt>Estimate</dt><dd>${d.ep[0].toFixed(1)}, ${d.ep[1].toFixed(1)}, ${d.ep[2].toFixed(1)} <small>VIO · drift ${d.drift.toFixed(2)} m</small></dd>
        <dt>Speed</dt><dd>${speed.toFixed(1)} m/s · ${d.power.toFixed(0)} W</dd>
        <dt>Camera</dt><dd>nose-fixed · ${((yawOf(d.q) * 180) / Math.PI).toFixed(0)}° hdg</dd>
        <dt>Link</dt><dd style="color:${linkColor(d.link)}">${d.link > 0 ? `${d.link.toFixed(2)} Mbps` : "disconnected"}</dd>
        <dt>Route</dt><dd>${route}</dd>
        <dt>Frames</dt><dd>${d.frames[0]} sent · ${d.frames[1]} lost · ${d.backlog} queued on ESP</dd>
        <dt>Waypoints</dt><dd>${d.path.length}</dd>
      </dl>`;
  }

  addEvents(evts: SimEvent[]): void {
    for (const e of evts) {
      const li = document.createElement("li");
      li.className = e.level;
      li.innerHTML = `<time>${fmtTime(e.t)}</time>${e.text}`;
      this.events.prepend(li);
    }
    while (this.events.children.length > 150) this.events.lastChild?.remove();
  }

  clearEvents(): void {
    this.events.innerHTML = "";
  }

  connection(ok: boolean): void {
    $("conn").classList.toggle("down", !ok);
    $("conn").title = ok ? "Connected to simulator" : "Disconnected; retrying";
  }
}
