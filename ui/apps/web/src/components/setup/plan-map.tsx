import { Button } from "@swarm/ui/components/button";
import { Segmented } from "@swarm/ui/components/segmented";
import { ArrowUp, Ban, ChevronDown } from "lucide-react";
import { useState } from "react";

import { Stage } from "../map/stage";

const W = 1019;
const H = 848;

const rooms: [string, number, number][] = [
  ["Living room", 240, 236],
  ["Kitchen", 568, 318],
  ["Den", 788, 228],
  ["Hallway", 700, 378],
  ["Bedroom 1", 180, 446],
  ["Entry", 516, 596],
  ["Garage", 760, 540],
];

const sectors: [string, number, number, string][] = [
  ["D1", 138, 330, "bg-orange"],
  ["D2", 138, 640, "bg-[#ff8a5c]"],
  ["D3", 846, 376, "bg-ink"],
  ["D4", 428, 640, "bg-muted"],
];

const handles: [number, number][] = [
  [92, 117],
  [916, 117],
  [916, 694],
  [92, 694],
];

/** Prior floor plan with the geofence, no-fly zone, entries and drone sectors. */
export function PlanMap() {
  const [tool, setTool] = useState<"select" | "geofence" | "noFly" | "entry">("geofence");
  return (
    <div
      className="relative h-full w-full overflow-hidden bg-[#f7f7f6]"
      style={{
        backgroundImage: "linear-gradient(#ededeb 1px, transparent 1px), linear-gradient(90deg, #ededeb 1px, transparent 1px)",
        backgroundSize: "27.5px 27.5px",
      }}
    >
      <Stage width={W} height={H}>
        <img src="/assets/plan.png" alt="Ground floor plan" width={W} height={H} className="absolute inset-0" draggable={false} />
        <div className="absolute rounded-sm border-2 border-dashed border-orange" style={{ left: 97, top: 122, width: 826, height: 578 }} />
        {handles.map(([x, y]) => (
          <div key={`${x}-${y}`} className="absolute size-3 rounded-[2px] border-2 border-orange bg-white" style={{ left: x, top: y }} />
        ))}
        <span className="absolute font-mono text-xs font-medium text-orange-edge" style={{ left: 484, top: 96 }}>
          15.0 m
        </span>
        <span className="absolute font-mono text-xs font-medium text-orange-edge" style={{ left: 934, top: 402 }}>
          10.5 m
        </span>
        {rooms.map(([name, x, y]) => (
          <span key={name} className="absolute text-[13px] font-medium text-muted" style={{ left: x, top: y }}>
            {name}
          </span>
        ))}
        {sectors.map(([id, x, y, bg]) => (
          <span key={id} className={`absolute rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold text-white ${bg}`} style={{ left: x, top: y }}>
            {id}
          </span>
        ))}
        <span className="absolute flex items-center gap-1 rounded-[5px] bg-person px-1.5 py-0.5 text-xs font-semibold text-white" style={{ left: 740, top: 566 }}>
          <Ban className="size-2.5" strokeWidth={3} />
          No-fly
        </span>
        <span
          className="absolute flex h-[26px] items-center gap-1.5 rounded-md bg-ink pr-2.5 pl-1.5 text-xs font-semibold text-white shadow-[0_2px_0_#000]"
          style={{ left: 496, top: 708 }}
        >
          <span className="flex size-4 items-center justify-center rounded bg-orange">
            <ArrowUp className="size-2.5" strokeWidth={3} />
          </span>
          Entry A, launch
        </span>
        <span className="absolute rounded-md bg-white px-2 py-0.5 text-xs font-semibold shadow-[0_0_0_1px_var(--color-ink)]" style={{ left: 562, top: 70 }}>
          Entry B
        </span>
      </Stage>
      <div className="absolute top-3 left-3 flex items-center gap-2">
        <Segmented
          tone="dark"
          value={tool}
          onChange={setTool}
          options={[
            { value: "select", label: "Select" },
            { value: "geofence", label: "Geofence" },
            { value: "noFly", label: "No-fly" },
            { value: "entry", label: "Entry" },
          ]}
        />
        <Button size="sm" className="text-xs font-semibold">
          Ground floor
          <ChevronDown className="text-muted" />
        </Button>
      </div>
    </div>
  );
}
