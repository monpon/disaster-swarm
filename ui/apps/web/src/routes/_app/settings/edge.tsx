import { Button } from "@swarm/ui/components/button";
import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute } from "@tanstack/react-router";
import { Server } from "lucide-react";

import { edgeServices } from "@/lib/mock";

export const Route = createFileRoute("/_app/settings/edge")({
  head: () => ({ meta: [{ title: "Settings: edge server" }] }),
  component: EdgeSettings,
});

const usage = [
  { label: "GPU", value: "61%", unit: "", fill: 61 },
  { label: "Memory", value: "42", unit: "of 128 GB", fill: 33 },
  { label: "Temperature", value: "64", unit: "°C", fill: 58 },
  { label: "Storage free", value: "1.2", unit: "TB", fill: 30 },
];

function EdgeSettings() {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-8 py-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]">Edge server</h1>
        <p className="text-[13px] text-muted">Runs mapping, detection and voice on site. Drones connect to it over the mesh.</p>
      </div>
      <div className="pane flex items-center gap-3.5 p-4">
        <span className="flex size-11 items-center justify-center rounded-[10px] bg-ink">
          <Server className="size-[22px] text-orange" strokeWidth={1.5} />
        </span>
        <div className="flex flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold">ASUS Ascent GX10</span>
            <span className="flex h-5 items-center gap-1.5 rounded-full bg-[#eef8f1] px-2 text-xs font-medium text-[#166534]">
              <span className="size-1.5 rounded-full bg-ok" />
              Online
            </span>
          </div>
          <span className="text-[13px] text-muted">Engine 7 rig. Up 6 h 12 min. 10.0.7.2</span>
        </div>
        <Button>Restart services</Button>
      </div>
      <div className="flex gap-3">
        {usage.map((u) => (
          <div key={u.label} className="pane flex flex-1 flex-col gap-2 px-4 py-3.5">
            <span className="text-xs text-muted">{u.label}</span>
            <span className="flex items-baseline gap-1">
              <span className="font-mono text-[22px] font-semibold">{u.value}</span>
              {u.unit && <span className="text-[13px] text-muted">{u.unit}</span>}
            </span>
            <div className="h-1 rounded-full bg-[#e3e3e0]">
              <div className="h-1 rounded-full bg-ink" style={{ width: `${u.fill}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="pane flex flex-col overflow-hidden">
        <div className="flex h-9 items-center gap-4 border-b border-line bg-panel px-4 text-xs font-medium text-muted">
          <span className="flex-1">Service</span>
          <span className="w-[200px]">Load</span>
          <span className="w-[100px]">Status</span>
          <span className="w-[60px]" />
        </div>
        {edgeServices.map((s, i) => (
          <div key={s.name} className={cn("flex h-[46px] items-center gap-4 px-4", i < edgeServices.length - 1 && "border-b border-line-soft")}>
            <span className="flex-1 text-sm">{s.name}</span>
            <span className="w-[200px] font-mono text-[13px] text-muted">{s.load}</span>
            <span className="flex w-[100px] items-center gap-1.5 text-[13px]">
              <span className={cn("size-[7px] rounded-full", s.status === "running" ? "bg-ok" : "bg-hazard")} />
              {s.status === "running" ? "Running" : "Degraded"}
            </span>
            <button type="button" className="w-[60px] text-right text-[13px] font-medium text-orange-edge hover:underline">
              Logs
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
