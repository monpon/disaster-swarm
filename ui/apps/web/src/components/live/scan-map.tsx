import { Button } from "@swarm/ui/components/button";
import { Segmented } from "@swarm/ui/components/segmented";
import { cn } from "@swarm/ui/lib/utils";
import { ChevronDown, Layers, Minus, Plus, SquareDashed } from "lucide-react";
import { useState } from "react";

import { findings, mission, liveDrones, type Finding } from "@/lib/mock";

import { findingStyle, Quad } from "../icons";
import { Stage } from "../map/stage";

const W = 1019;
const H = 636;
const FENCE = "435,131 928.6,416 566.6,625 73,340";

function DroneMarker({ id, at, selected, holding, onSelect }: { id: string; at: [number, number]; selected: boolean; holding?: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="absolute flex items-center gap-[5px]"
      style={{ left: at[0] - 11, top: at[1] - 11 }}
      aria-label={`Select ${id}`}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-full",
          selected
            ? "size-6 -translate-x-px -translate-y-px bg-orange text-white shadow-[0_0_0_2px_#fff,0_0_0_3.5px_var(--color-orange-edge),0_2px_6px_rgb(194_65_12/0.4)]"
            : "size-[22px] bg-white text-ink shadow-[0_0_0_1.5px_var(--color-ink),0_2px_4px_rgb(0_0_0/0.2)]",
        )}
      >
        <Quad className="size-3.5" />
      </span>
      <span
        className={cn(
          "rounded-[3px] px-1 py-px font-mono text-[11px] font-semibold",
          selected ? "bg-orange-edge text-white" : "bg-white/90 text-ink",
        )}
      >
        {id}
        {holding ? " holding" : ""}
      </span>
    </button>
  );
}

function Pin({ finding, selected, onSelect }: { finding: Finding; selected: boolean; onSelect: () => void }) {
  if (!finding.pin) return null;
  const { bg, Icon } = findingStyle[finding.kind];
  const big = finding.kind === "person";
  const size = big ? 30 : 24;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={finding.title}
      title={finding.title}
      className={cn(
        "absolute flex items-center justify-center rounded-[15px_15px_15px_2px] shadow-[0_0_0_2px_#fff,0_2px_6px_rgb(0_0_0/0.25)] transition-transform hover:scale-110",
        bg,
        selected && "scale-110 shadow-[0_0_0_2px_#fff,0_0_0_5px_rgb(255_90_31/0.45),0_3px_8px_rgb(0_0_0/0.3)]",
      )}
      style={{ left: finding.pin[0] - 14, top: finding.pin[1] - size - 2, width: size, height: size }}
    >
      <Icon className={big ? "size-4 text-white" : "size-3 text-white"} strokeWidth={2.2} />
    </button>
  );
}

export function ScanMap({
  selectedDrone,
  onSelectDrone,
  selectedFinding,
  onSelectFinding,
}: {
  selectedDrone: string;
  onSelectDrone: (id: string) => void;
  selectedFinding: string | null;
  onSelectFinding: (id: string) => void;
}) {
  const [view, setView] = useState<"3d" | "top" | "section">("3d");

  return (
    <div className="relative h-full w-full overflow-hidden bg-map">
      <Stage width={W} height={H}>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="absolute inset-0">
          <polygon points={FENCE} fill="#E3E3E0" />
          <polygon points={FENCE} fill="none" stroke="var(--color-orange)" strokeWidth={1.5} strokeDasharray="8 6" />
        </svg>
        <img src="/assets/cloud.png" alt="Point cloud of the ground floor" width={W} height={H} className="absolute inset-0" draggable={false} />
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="pointer-events-none absolute inset-0">
          {liveDrones.map((d) =>
            d.path ? (
              <polyline
                key={d.id}
                points={d.path}
                fill="none"
                stroke={d.id === selectedDrone ? "var(--color-orange)" : "var(--color-ink)"}
                strokeWidth={d.id === selectedDrone ? 2.5 : 1.5}
                strokeLinejoin="round"
                opacity={d.id === selectedDrone ? 1 : 0.45}
              />
            ) : null,
          )}
          <polyline points="609.4,360.9 662.1,402.7" fill="none" stroke="var(--color-ink)" strokeWidth={1.5} strokeDasharray="4 4" opacity={0.6} />
          {liveDrones.map((d) =>
            d.marker && d.shadow ? (
              <g key={d.id}>
                <line x1={d.marker[0]} y1={d.marker[1]} x2={d.shadow[0]} y2={d.shadow[1]} stroke="var(--color-ink)" strokeDasharray="2 3" opacity={0.6} />
                <ellipse cx={d.shadow[0]} cy={d.shadow[1]} rx={7} ry={3.5} fill="var(--color-ink)" opacity={0.18} />
              </g>
            ) : null,
          )}
        </svg>
        {liveDrones.map((d) =>
          d.marker ? (
            <DroneMarker key={d.id} id={d.id} at={d.marker} holding={d.holding} selected={d.id === selectedDrone} onSelect={() => onSelectDrone(d.id)} />
          ) : null,
        )}
        {findings.map((f) => (
          <Pin key={f.id} finding={f} selected={f.id === selectedFinding} onSelect={() => onSelectFinding(f.id)} />
        ))}
        <span className="absolute rounded bg-ink px-1.5 py-0.5 text-[11px] font-semibold text-white" style={{ left: 356, top: 478 }}>
          Entry A
        </span>
        <span className="absolute rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ink shadow-[0_0_0_1px_var(--color-ink)]" style={{ left: 722, top: 280 }}>
          Entry B
        </span>
      </Stage>

      <div className="absolute inset-x-3 top-3 flex items-center gap-2">
        <Segmented
          tone="dark"
          value={view}
          onChange={setView}
          options={[
            { value: "3d", label: "3D" },
            { value: "top", label: "Top" },
            { value: "section", label: "Section" },
          ]}
        />
        <Button size="sm" className="text-xs font-semibold">
          Ground floor
          <ChevronDown className="text-muted" />
        </Button>
        <div className="flex-1" />
        <Button size="sm" className="text-xs font-semibold">
          <Layers />
          Layers
        </Button>
        <Button size="sm" className="text-xs font-semibold">
          <SquareDashed className="text-orange" />
          Geofence
        </Button>
      </div>

      <div className="absolute inset-x-3 bottom-3 flex items-end gap-4">
        <div className="flex flex-col gap-1.5 rounded-lg bg-white/95 px-3 py-2.5 shadow-[0_0_0_1px_var(--color-line)]">
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-lg font-semibold">{mission.coverage}%</span>
            <span className="text-xs text-muted">mapped, {mission.roomsLeft} rooms left</span>
          </div>
          <div className="h-1 w-[180px] rounded-full bg-[#e3e3e0]">
            <div className="h-1 rounded-full bg-orange" style={{ width: `${mission.coverage}%` }} />
          </div>
        </div>
        <div className="flex flex-col gap-[3px] pb-1">
          <div className="h-1.5 w-[76px] border-[1.5px] border-t-0 border-ink" />
          <span className="font-mono text-[11px]">2 m</span>
        </div>
        <div className="flex-1" />
        <div className="btn-secondary flex flex-col overflow-hidden rounded-lg">
          <button type="button" aria-label="Zoom in" className="flex size-8 items-center justify-center border-b border-line hover:bg-ink/5">
            <Plus className="size-3.5" />
          </button>
          <button type="button" aria-label="Zoom out" className="flex size-8 items-center justify-center border-b border-line hover:bg-ink/5">
            <Minus className="size-3.5" />
          </button>
          <button type="button" aria-label="Reset north" className="flex size-8 items-center justify-center hover:bg-ink/5">
            <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden>
              <path d="M8 1.5 10 8 8 14.5 6 8Z" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
              <path d="M8 1.5 10 8H6Z" fill="var(--color-orange)" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
