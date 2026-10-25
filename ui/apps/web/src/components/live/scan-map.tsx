import { Button } from "@swarm/ui/components/button";
import { Segmented } from "@swarm/ui/components/segmented";
import { cn } from "@swarm/ui/lib/utils";
import { ChevronDown, Layers, Minus, Plus, SquareDashed } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useConsole } from "@/lib/console";
import { droneName, floorOf, planTransform, scanOf, viewerUrl, type Plan } from "@/lib/swarm";
import type { Finding } from "@/lib/mock";

import { findingStyle, Quad } from "../icons";
import { Stage } from "../map/stage";

const W = 1019;
const H = 636;
const FENCE = "435,131 928.6,416 566.6,625 73,340";

function DroneMarker({ id, at, selected, holding, scanning, onSelect }: { id: string; at: [number, number]; selected: boolean; holding?: boolean; scanning?: number | null; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="absolute flex items-center gap-[5px]"
      style={{ left: at[0] - 11, top: at[1] - 11 }}
      aria-label={`Select ${id}`}
    >
      {scanning != null && <span className="absolute top-0 left-0 size-[22px] animate-ping rounded-full bg-person/60" />}
      <span
        className={cn(
          "relative flex items-center justify-center rounded-full",
          scanning != null && "shadow-[0_0_0_3px_var(--color-person)]",
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
        {scanning != null ? ` scanning #${scanning}` : holding ? " holding" : ""}
      </span>
    </button>
  );
}

/** The explored floor plan of one floor (unknown dark, explored light, walls ink), drawn through the same transform as the markers. */
function PlanCanvas({ plan, floor }: { plan: Plan; floor: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    const z = plan.floors[floor];
    if (!c || !z) return;
    let stale = false;
    // the rasters are zlib-compressed in the database
    new Response(new Blob([z as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate")))
      .arrayBuffer()
      .then((buf) => {
        if (!stale) draw(c, new Uint8Array(buf));
      });
    return () => {
      stale = true;
    };
  }, [plan, floor]);
  const draw = (c: HTMLCanvasElement, r: Uint8Array) => {
    const t = planTransform(plan, W, H);
    const off = document.createElement("canvas");
    off.width = plan.w;
    off.height = plan.h;
    const og = off.getContext("2d")!;
    const img = og.createImageData(plan.w, plan.h);
    for (let x = 0; x < plan.w; x++) {
      for (let y = 0; y < plan.h; y++) {
        const v = r[x * plan.h + y]!;
        const o = ((plan.h - 1 - y) * plan.w + x) * 4;
        const col = v === 2 ? [38, 38, 36] : v === 1 ? [243, 243, 240] : [0, 0, 0];
        img.data[o] = col[0]!; img.data[o + 1] = col[1]!; img.data[o + 2] = col[2]!;
        img.data[o + 3] = v === 0 ? 0 : 255;
      }
    }
    og.putImageData(img, 0, 0);
    const g = c.getContext("2d")!;
    g.clearRect(0, 0, W, H);
    g.imageSmoothingEnabled = false;
    g.drawImage(off, t.ox, t.oy, plan.w * t.s, plan.h * t.s);
  };
  return <canvas ref={ref} width={W} height={H} className="absolute inset-0" />;
}

type Cam = { vp: number[]; w: number; h: number };

/** World (x, y, z) to pixels in the 3D frame, from the view-projection matrix the viewer posts (column-major, z up). */
function project(cam: Cam, p: [number, number, number]): [number, number] | undefined {
  const m = cam.vp;
  const x = m[0]! * p[0] + m[4]! * p[1] + m[8]! * p[2] + m[12]!;
  const y = m[1]! * p[0] + m[5]! * p[1] + m[9]! * p[2] + m[13]!;
  const w = m[3]! * p[0] + m[7]! * p[1] + m[11]! * p[2] + m[15]!;
  if (w <= 0) return undefined;
  return [((x / w + 1) / 2) * cam.w, ((1 - y / w) / 2) * cam.h];
}

/** The master's point cloud (the viewer, embedded and transparent) framed like the console's own map: light ground, dashed
 * geofence, and the drone markers, survivor pins and entry labels laid over it. */
function Cloud3D({
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
  const c = useConsole();
  const [cam, setCam] = useState<Cam | null>(null);
  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.data?.type === "swarm-cam") setCam({ vp: e.data.vp, w: e.data.w, h: e.data.h });
    };
    window.addEventListener("message", on);
    return () => window.removeEventListener("message", on);
  }, []);
  const bb = c.raw.world?.building?.bbox as number[] | undefined;
  const at = (p: [number, number, number]) => (cam ? project(cam, p) : undefined);
  const fence = cam && bb ? ([[bb[0]! - 8, bb[1]! - 8], [bb[2]! + 8, bb[1]! - 8], [bb[2]! + 8, bb[3]! + 8], [bb[0]! - 8, bb[3]! + 8]] as const).map(([x, y]) => at([x, y, 0])) : [];
  const pts = fence.every(Boolean) ? fence.map((p) => p!.join(",")).join(" ") : null;
  return (
    <>
      {pts && (
        <svg className="pointer-events-none absolute inset-0 size-full">
          <polygon points={pts} fill="#E3E3E0" />
          <polygon points={pts} fill="none" stroke="var(--color-orange)" strokeWidth={1.5} strokeDasharray="8 6" />
        </svg>
      )}
      <iframe src={viewerUrl()} title="3D map" className="absolute inset-0 size-full border-0" />
      <div className="pointer-events-none absolute inset-0 [&>*]:pointer-events-auto">
        {cam &&
          c.raw.drones
            .filter((d) => !d.crashed)
            .map((d) => {
              const p = at(d.ep as [number, number, number]);
              return p ? (
                <DroneMarker key={d.id} id={droneName(d.id)} at={p} scanning={scanOf(d)} holding={d.holding || d.mode === "relay"} selected={droneName(d.id) === selectedDrone} onSelect={() => onSelectDrone(droneName(d.id))} />
              ) : null;
            })}
        {cam &&
          c.findings.map((f) => {
            const p = f.world && at(f.world);
            return p ? <Pin key={f.id} finding={{ ...f, pin: p }} selected={f.id === selectedFinding} onSelect={() => onSelectFinding(f.id)} /> : null;
          })}
        {cam &&
          c.raw.entries
            .filter((e) => Math.abs(e.normal[2]) <= 0.5)
            .map((e) => {
              const p = at(e.center);
              return p ? (
                <span key={e.id} className="absolute rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ink shadow-[0_0_0_1px_var(--color-ink)]" style={{ left: p[0] + 6, top: p[1] - 8 }}>
                  {e.blocked ? "Blocked" : `Entry ${e.id}`}
                </span>
              ) : null;
            })}
      </div>
    </>
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
  const c = useConsole();
  const [floor, setFloor] = useState(0);
  const plan = c.live ? c.raw.plan : null;
  const nFloors = plan?.floors.length ?? 1;
  const fl = Math.min(floor, nFloors - 1);
  const T = useMemo(() => (plan ? planTransform(plan, W, H) : null), [plan]);
  const at = (w: [number, number, number]): [number, number] | undefined => (T ? T.at(w[0], w[1]) : undefined);
  const liveDrones = c.live ? c.drones.map((d) => ({ ...d, marker: undefined as [number, number] | undefined, path: undefined as string | undefined, shadow: undefined as [number, number] | undefined })) : c.drones;
  const findings = c.live
    ? c.findings.filter((f) => f.floor === fl && f.world).map((f) => ({ ...f, pin: at(f.world!) }))
    : c.findings;
  const mission = c.mission;
  const drones = c.live
    ? c.raw.drones
        .filter((d) => !d.crashed && floorOf(c.raw, d.ep[2]) === fl)
        .map((d) => ({ id: droneName(d.id), marker: at(d.ep as [number, number, number]), holding: d.holding || d.mode === "relay", scan: scanOf(d) }))
    : liveDrones.map((d) => ({ id: d.id, marker: (d as { marker?: [number, number] }).marker, holding: d.holding, scan: null as number | null }));
  const entries = c.live ? c.raw.entries.filter((e) => Math.abs(e.normal[2]) <= 0.5 && floorOf(c.raw, e.center[2]) === fl) : [];

  return (
    <div className="relative h-full w-full overflow-hidden bg-map">
      {view === "3d" && c.live && (
        <Cloud3D selectedDrone={selectedDrone} onSelectDrone={onSelectDrone} selectedFinding={selectedFinding} onSelectFinding={onSelectFinding} />
      )}
      <Stage width={W} height={H} className={view === "3d" && c.live ? "hidden" : undefined}>
        {c.live ? (
          plan ? (
            <PlanCanvas plan={plan} floor={fl} />
          ) : (
            <span className="absolute inset-0 flex items-center justify-center text-sm text-muted">Waiting for the first map…</span>
          )
        ) : (
          <>
            <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="absolute inset-0">
              <polygon points={FENCE} fill="#E3E3E0" />
              <polygon points={FENCE} fill="none" stroke="var(--color-orange)" strokeWidth={1.5} strokeDasharray="8 6" />
            </svg>
            <img src="/assets/cloud.png" alt="Point cloud of the ground floor" width={W} height={H} className="absolute inset-0" draggable={false} />
          </>
        )}
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="pointer-events-none absolute inset-0">
          {!c.live && liveDrones.map((d) =>
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
          {!c.live && <polyline points="609.4,360.9 662.1,402.7" fill="none" stroke="var(--color-ink)" strokeWidth={1.5} strokeDasharray="4 4" opacity={0.6} />}
          {!c.live && liveDrones.map((d) =>
            d.marker && d.shadow ? (
              <g key={d.id}>
                <line x1={d.marker[0]} y1={d.marker[1]} x2={d.shadow[0]} y2={d.shadow[1]} stroke="var(--color-ink)" strokeDasharray="2 3" opacity={0.6} />
                <ellipse cx={d.shadow[0]} cy={d.shadow[1]} rx={7} ry={3.5} fill="var(--color-ink)" opacity={0.18} />
              </g>
            ) : null,
          )}
        </svg>
        {drones.map((d) =>
          d.marker ? (
            <DroneMarker key={d.id} id={d.id} at={d.marker} holding={d.holding} scanning={d.scan} selected={d.id === selectedDrone} onSelect={() => onSelectDrone(d.id)} />
          ) : null,
        )}
        {findings.map((f) => (
          <Pin key={f.id} finding={f} selected={f.id === selectedFinding} onSelect={() => onSelectFinding(f.id)} />
        ))}
        {c.live ? (
          entries.map((e) => {
            const p = at(e.center);
            return p ? (
              <span key={e.id} className="absolute rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ink shadow-[0_0_0_1px_var(--color-ink)]" style={{ left: p[0] + 6, top: p[1] - 8 }}>
                {e.blocked ? "Blocked" : `Entry ${e.id}`}
              </span>
            ) : null;
          })
        ) : (
          <>
            <span className="absolute rounded bg-ink px-1.5 py-0.5 text-[11px] font-semibold text-white" style={{ left: 356, top: 478 }}>
              Entry A
            </span>
            <span className="absolute rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ink shadow-[0_0_0_1px_var(--color-ink)]" style={{ left: 722, top: 280 }}>
              Entry B
            </span>
          </>
        )}
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
        <Button size="sm" className="text-xs font-semibold" onClick={() => setFloor((fl + 1) % nFloors)}>
          {fl === 0 ? "Ground floor" : `Floor ${fl + 1}`}
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
