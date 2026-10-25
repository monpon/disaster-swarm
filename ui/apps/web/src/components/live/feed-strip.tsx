import { cn } from "@swarm/ui/lib/utils";

import { feedBoxes, liveDrones } from "@/lib/mock";

/** One live mono feed per drone, with detection boxes drawn over the frame. */
export function FeedStrip({ selected, onSelect }: { selected: string; onSelect: (id: string) => void }) {
  return (
    <div className="flex h-full gap-2 overflow-x-auto bg-panel p-2.5">
      {liveDrones.map((d) => {
        const active = d.id === selected;
        const box = feedBoxes[d.id];
        return (
          <button
            key={d.id}
            type="button"
            onClick={() => onSelect(d.id)}
            className={cn(
              "flex min-w-[200px] flex-1 flex-col overflow-hidden rounded-lg bg-white text-left",
              active ? "shadow-[0_0_0_2px_var(--color-orange)]" : "shadow-[0_0_0_1px_var(--color-line)] hover:shadow-[0_0_0_1px_var(--color-line-strong)]",
            )}
          >
            <div className="relative min-h-0 flex-1 bg-[#222]">
              <img src={d.feed} alt={`${d.id} camera`} className="absolute inset-0 size-full object-cover" draggable={false} />
              <span
                className={cn(
                  "absolute top-2 left-2 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold text-white",
                  active ? "bg-orange" : "bg-black/55",
                )}
              >
                {d.id}
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
