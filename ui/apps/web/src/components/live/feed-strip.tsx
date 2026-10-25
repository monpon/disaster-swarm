import { cn } from "@swarm/ui/lib/utils";
import { ArrowLeft, Maximize2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useConsole } from "@/lib/console";
import { feedBoxes } from "@/lib/mock";
import { droneNumber, store } from "@/lib/swarm";

import { FeedCanvas } from "./feed-canvas";

/** One live feed per drone (the selected one and up to three airborne others), with detection boxes on the demo frames. */
export function FeedStrip({ selected, onSelect, onFocus }: { selected: string; onSelect: (id: string) => void; onFocus: (id: string) => void }) {
  const c = useConsole();
  const shown = c.drones.map((d) => d.id);
  const root = useRef<HTMLDivElement>(null);
  // every drone has a tile, but only the ones scrolled into view (plus the selected one) are streamed
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const ids = [...new Set([selected, ...visible])].map(droneNumber).sort((a, b) => a - b).join(",");

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) =>
        setVisible((prev) => {
          const next = new Set(prev);
          for (const e of es) {
            const id = (e.target as HTMLElement).dataset.drone!;
            if (e.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        }),
      { root: el },
    );
    el.querySelectorAll("[data-drone]").forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, [shown.length]);

  useEffect(() => {
    if (c.live) store.watchFeeds(ids ? ids.split(",").map(Number) : []);
  }, [c.live, ids]);

  return (
    <div ref={root} className="flex h-full gap-2 overflow-x-auto bg-panel p-2.5">
      {shown.map((id) => {
        const d = c.drones.find((x) => x.id === id);
        if (!d) return null;
        const active = d.id === selected;
        const box = c.live ? undefined : feedBoxes[d.id];
        const frame = c.live ? c.raw.feeds[droneNumber(d.id)] : undefined;
        return (
          <button
            key={d.id}
            data-drone={d.id}
            type="button"
            onClick={() => onSelect(d.id)}
            onDoubleClick={() => onFocus(d.id)}
            className={cn(
              "flex min-w-[220px] flex-1 shrink-0 flex-col overflow-hidden rounded-lg bg-white text-left",
              active ? "shadow-[0_0_0_2px_var(--color-orange)]" : "shadow-[0_0_0_1px_var(--color-line)] hover:shadow-[0_0_0_1px_var(--color-line-strong)]",
            )}
          >
            <div className="relative min-h-0 flex-1 bg-[#222]">
              {c.live ? (
                frame ? (
                  <FeedCanvas drone={droneNumber(d.id)} className="absolute inset-0 size-full object-cover" />
                ) : (
                  <span className="absolute inset-0 flex items-center justify-center text-xs text-white/50">waiting for frames…</span>
                )
              ) : (
                <img src={d.feed} alt={`${d.id} camera`} className="absolute inset-0 size-full object-cover" draggable={false} />
              )}
              <span
                className={cn(
                  "absolute top-2 left-2 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold text-white",
                  active ? "bg-orange" : "bg-black/55",
                )}
              >
                {d.id}
              </span>
              <span
                role="button"
                aria-label={`Focus ${d.id}`}
                title="Focus this drone's view"
                onClick={(e) => {
                  e.stopPropagation();
                  onFocus(d.id);
                }}
                className="absolute top-2 right-2 flex size-6 items-center justify-center rounded bg-black/55 text-white hover:bg-black/80"
              >
                <Maximize2 className="size-3.5" />
              </span>
              {box && (
                <div
                  className="absolute rounded-[2px] border-2"
                  style={{ left: `${box.box[0]}%`, top: `${box.box[1]}%`, width: `${box.box[2]}%`, height: `${box.box[3]}%`, borderColor: box.color }}
                >
                  <span
                    className={cn(
                      "absolute -top-[19px] px-1.5 py-px font-mono text-[10px] font-semibold whitespace-nowrap",
                      box.box[0] > 50 ? "-right-0.5" : "-left-0.5",
                    )}
                    style={{ background: box.color, color: box.text }}
                  >
                    {box.label}
                  </span>
                </div>
              )}
            </div>
            <div className="flex h-8 shrink-0 items-center gap-2 px-2.5">
              <span className="flex-1 truncate text-[13px] font-medium">{d.room}</span>
              <span className={cn("font-mono text-xs", d.battery < 40 ? "font-semibold text-orange-edge" : "text-muted")}>{d.battery}%</span>
              <span className="font-mono text-xs text-muted">{d.altitude} m</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

/** One drone's camera on the main screen, in place of the map. */
export function FocusedFeed({ id, onBack }: { id: string; onBack: () => void }) {
  const c = useConsole();
  const fd = c.drones.find((d) => d.id === id);
  if (!fd) return null;
  const frame = c.live ? c.raw.feeds[droneNumber(fd.id)] : undefined;
  return (
    <div className="relative h-full w-full bg-[#111]">
      {c.live ? (
        frame ? <FeedCanvas drone={droneNumber(fd.id)} className="absolute inset-0 size-full object-contain" /> : <span className="absolute inset-0 flex items-center justify-center text-sm text-white/50">waiting for frames…</span>
      ) : (
        <img src={fd.feed} alt={`${fd.id} camera`} className="absolute inset-0 size-full object-contain" draggable={false} />
      )}
      <button type="button" onClick={onBack} className="absolute top-3 left-3 flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-ink shadow-[0_0_0_1px_var(--color-line)] hover:bg-panel">
        <ArrowLeft className="size-3.5" /> Back to map
      </button>
      <span className="absolute top-3 right-3 rounded bg-orange px-2 py-0.5 font-mono text-xs font-semibold text-white">{fd.id}</span>
      <div className="absolute inset-x-0 bottom-0 flex items-center gap-4 bg-gradient-to-t from-black/70 to-transparent px-4 pt-10 pb-3 font-mono text-xs text-white">
        <span className="flex-1 truncate font-sans text-sm font-medium">{fd.room}</span>
        <span>{fd.battery}%</span>
        <span>{fd.altitude} m</span>
        <span>{fd.status}</span>
      </div>
    </div>
  );
}
