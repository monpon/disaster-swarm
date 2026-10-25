import { Button } from "@swarm/ui/components/button";
import { Switch } from "@swarm/ui/components/switch";
import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Check, Crosshair, Ellipsis, Plus, Search } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Select } from "@/components/form";
import { Quad } from "@/components/icons";
import { ConsoleBody } from "@/components/shell/console-body";
import { TopBar } from "@/components/shell/top-bar";
import { fleet, type Drone } from "@/lib/mock";

export const Route = createFileRoute("/_app/fleet")({
  head: () => ({ meta: [{ title: "Fleet" }] }),
  component: FleetPage,
});

const statusStyle: Record<Drone["status"], { dot: string; text: string; label: string }> = {
  ready: { dot: "bg-ok", text: "text-[#166534]", label: "Ready" },
  calibrate: { dot: "bg-hazard", text: "font-medium text-[#92600a]", label: "Calibrate IMU" },
  charging: { dot: "bg-door", text: "text-[#1d4ed8]", label: "Charging" },
  offline: { dot: "bg-line-strong", text: "text-faint", label: "Offline" },
};

function FleetPage() {
  const [selected, setSelected] = useState("D4");
  const [query, setQuery] = useState("");
  const drone = fleet.find((d) => d.id === selected) ?? fleet[0]!;
  const rows = fleet.filter((d) => `${d.id} ${d.airframe}`.toLowerCase().includes(query.toLowerCase()));

  return (
    <>
      <TopBar
        actions={
          <Button>
            <Plus />
            Pair drone
          </Button>
        }
      >
        <span className="text-sm font-semibold">Fleet</span>
      </TopBar>
      <ConsoleBody>
        <section className="flex w-[520px] shrink-0 flex-col border-r border-line-strong">
          <div className="flex shrink-0 flex-col gap-3 px-4 pt-[18px] pb-3">
            <div className="flex items-baseline gap-2">
              <h1 className="text-xl font-semibold tracking-[-0.01em]">Drones</h1>
              <span className="text-[13px] text-muted">6 paired, 4 ready</span>
            </div>
            <div className="flex gap-2">
              <label className="flex h-[34px] flex-1 items-center gap-2 rounded-lg bg-white px-2.5 shadow-[inset_0_0_0_1px_var(--color-line-strong)] focus-within:shadow-[inset_0_0_0_1.5px_var(--color-orange)]">
                <Search className="size-3.5 text-faint" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search drones" className="min-w-0 flex-1 text-[13px] outline-none placeholder:text-faint" />
              </label>
              <Select label="Status filter" value="All status" onChange={() => {}} options={["All status", "Ready", "Needs attention", "Offline"]} className="h-[34px] w-[130px]" />
            </div>
          </div>
          <div className="flex h-8 shrink-0 items-center gap-3 border-y border-line bg-panel px-4 text-xs font-medium text-muted">
            <span className="w-2.5" />
            <span className="w-10">ID</span>
            <span className="flex-1">Airframe</span>
            <span className="w-14 text-right">Battery</span>
            <span className="w-16 text-right">Signal</span>
            <span className="w-24">Status</span>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {rows.map((d) => {
              const s = statusStyle[d.status];
              const active = d.id === selected;
              const offline = d.status === "offline";
              return (
                <li key={d.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(d.id)}
                    className={cn(
                      "flex h-12 w-full items-center gap-3 border-b border-line-soft px-4 text-left",
                      active ? "bg-orange-tint shadow-[inset_3px_0_0_var(--color-orange)]" : "hover:bg-panel-2",
                    )}
                  >
                    <span className={cn("size-2.5 shrink-0 rounded-full", s.dot)} />
                    <span className={cn("w-10 font-mono text-[13px] font-semibold", offline && "text-faint")}>{d.id}</span>
                    <span className="flex min-w-0 flex-1 flex-col gap-px">
                      <span className={cn("truncate text-[13px]", offline && "text-faint")}>{d.airframe}</span>
                      <span className="text-xs text-muted">{d.ip}</span>
                    </span>
                    <span className="w-14 text-right font-mono text-[13px]">{offline ? "—" : `${d.battery}%`}</span>
                    <span className="w-16 text-right font-mono text-[13px]">{d.signal ?? "—"}</span>
                    <span className={cn("w-24 text-[13px]", s.text)}>{s.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
        <DroneDetail key={drone.id} drone={drone} />
      </ConsoleBody>
    </>
  );
}

function DroneDetail({ drone }: { drone: Drone }) {
  const [tab, setTab] = useState("Overview");
  const [relay, setRelay] = useState(true);
  const [adapter, setAdapter] = useState(drone.airframe.startsWith("Tello") ? "Tello EDU" : "E58 Wi-Fi camera");
  const needsCal = drone.status === "calibrate";

  return (
    <section className="flex min-w-0 flex-1 flex-col bg-panel-2">
      <div className="flex shrink-0 flex-col gap-3.5 border-b border-line bg-white px-6 pt-[18px]">
        <div className="flex items-center gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-[10px] bg-panel shadow-[inset_0_0_0_1px_var(--color-line)]">
            <Quad className="size-6" />
          </span>
          <div className="flex flex-1 flex-col gap-0.5">
            <div className="flex items-baseline gap-2.5">
              <span className="font-mono text-[22px] font-semibold">{drone.id}</span>
              <span className="text-[15px] font-medium">{drone.airframe}</span>
            </div>
            <span className="text-[13px] text-muted">Paired Oct 3. 41 flights, 2 h 18 min total.</span>
          </div>
          <Button>
            <Crosshair />
            Identify
          </Button>
          <Button size="icon" aria-label="More actions">
            <Ellipsis />
          </Button>
        </div>
        <div role="tablist" className="flex gap-[22px]">
          {["Overview", "Calibration", "Network", "Flight logs"].map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={t === tab}
              onClick={() => setTab(t)}
              className={cn("h-[38px] border-b-2 text-sm", t === tab ? "border-orange font-semibold" : "border-transparent font-medium text-muted hover:text-ink")}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-[18px] overflow-y-auto px-6 py-5">
        {needsCal && (
          <div className="flex items-center gap-3 rounded-[10px] bg-[#fff8e6] px-3.5 py-3 shadow-[inset_0_0_0_1px_#f2d58a]">
            <AlertTriangle className="size-[18px] text-[#b07800]" />
            <div className="flex flex-1 flex-col gap-px">
              <span className="text-sm font-semibold">IMU drift is above the limit</span>
              <span className="text-[13px] text-muted">Set the drone on a level surface, then calibrate. Takes about 30 seconds.</span>
            </div>
            <Button variant="primary">Calibrate</Button>
          </div>
        )}
        <div className="flex gap-4">
          <div className="pane flex w-[380px] shrink-0 flex-col overflow-hidden">
            <div className="relative h-[214px] bg-[#222]">
              <img src={drone.feed} alt={`${drone.id} camera preview`} className="absolute inset-0 size-full object-cover" />
              <span className="absolute top-2.5 left-2.5 flex items-center gap-1.5 rounded bg-black/55 px-1.5 py-0.5 font-mono text-[11px] text-white">
                <span className={cn("size-1.5 rounded-full", drone.status === "offline" ? "bg-faint" : "bg-[#ff3b2e]")} />
                {drone.status === "offline" ? "Offline" : "Live"}
              </span>
            </div>
            <div className="flex h-[38px] items-center px-3">
              <span className="flex-1 text-[13px] font-medium">Camera</span>
              <span className="font-mono text-xs text-muted">640×480 mono, 15 fps</span>
            </div>
          </div>
          <div className="pane flex flex-1 flex-col overflow-hidden">
            <div className="flex h-10 items-center border-b border-line-soft px-3.5">
              <span className="flex-1 text-[13px] font-semibold">Preflight</span>
              <span className="text-xs text-muted">{needsCal ? "5 of 6 passed" : "6 of 6 passed"}</span>
            </div>
            <Check2 label="Motors and props" value="4/4" />
            <Check2 label="Camera stream" value="15 fps" />
            <Check2 label="IMU bias" value={needsCal ? "0.31°/s" : "0.04°/s"} warn={needsCal} />
            <Check2 label="ROS 2 nodes" value="5/5" />
            <Check2 label="Link to edge server" value="31 ms" />
            <Check2 label="Battery health" value="92%" last />
          </div>
        </div>
        <div className="flex gap-4">
          <Card title="Hardware profile">
            <KV label="Adapter">
              <Select label="Adapter" value={adapter} onChange={setAdapter} options={["E58 Wi-Fi camera", "Tello EDU", "MAVLink (PX4/ArduPilot)", "Custom ROS 2"]} className="flex-1" />
            </KV>
            <KV label="Companion">Raspberry Pi 4, 4 GB</KV>
            <KV label="IMU">MPU-6050 at 200 Hz</KV>
            <KV label="Stack version">
              <span className="flex-1 font-mono">0.4.2</span>
              <span className="text-xs font-medium text-orange-edge">Update to 0.4.3</span>
            </KV>
          </Card>
          <Card title="Network">
            <div className="flex h-10 items-center gap-3">
              <span className="flex-1 text-[13px]">Relay ROS 2 traffic</span>
              <Switch checked={relay} onCheckedChange={setRelay} label="Relay ROS 2 traffic" />
            </div>
            <KV label="Mesh SSID">
              <span className="font-mono">swarm-24-1031</span>
            </KV>
            <KV label="Address">
              <span className="font-mono">{drone.ip}</span>
            </KV>
            <KV label="Peers in range">
              <span className="font-mono">D2, D3</span>
            </KV>
          </Card>
        </div>
      </div>
    </section>
  );
}

function Check2({ label, value, warn, last }: { label: string; value: string; warn?: boolean; last?: boolean }) {
  return (
    <div className={cn("flex h-9 items-center gap-2.5 px-3.5", !last && "border-b border-[#f2f2f0]", warn && "bg-[#fffbf0]")}>
      {warn ? <AlertTriangle className="size-3.5 text-[#b07800]" /> : <Check className="size-3.5 text-ok" strokeWidth={2.5} />}
      <span className="flex-1 text-[13px]">{label}</span>
      <span className={cn("font-mono text-xs", warn ? "text-[#92600a]" : "text-muted")}>{value}</span>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="pane flex flex-1 flex-col gap-0.5 p-3.5">
      <span className="pb-2 text-[13px] font-semibold">{title}</span>
      {children}
    </div>
  );
}

function KV({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex h-10 items-center gap-3 text-[13px]">
      <span className="w-[110px] shrink-0 text-muted">{label}</span>
      <span className="flex min-w-0 flex-1 items-center gap-2">{children}</span>
    </div>
  );
}
