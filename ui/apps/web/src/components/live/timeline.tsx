import { Pause, Play } from "lucide-react";
import { useState } from "react";

import { mission, timelineEvents } from "@/lib/mock";

/** Mission scrubber. Ticks mark findings; the orange head is "now". */
export function Timeline() {
  const [playing, setPlaying] = useState(true);
  return (
    <div className="flex h-11 shrink-0 items-center gap-3 border-t border-line-strong bg-white px-3">
      <button
        type="button"
        onClick={() => setPlaying((p) => !p)}
        aria-label={playing ? "Pause" : "Play"}
        className="btn-secondary flex size-7 items-center justify-center rounded-[7px]"
      >
        {playing ? <Pause className="size-3 fill-ink" /> : <Play className="size-3 fill-ink" />}
      </button>
      <div className="relative h-7 flex-1">
        <div className="absolute inset-x-0 top-[13px] h-0.5 bg-line" />
        <div className="absolute top-[13px] left-0 h-0.5 w-[96%] bg-ink" />
        {timelineEvents.map((e) => (
          <div key={e.at} className="absolute top-[7px] h-3.5 w-0.5" style={{ left: `${e.at}%`, background: e.color }} />
        ))}
        <div className="absolute top-1.5 left-[96%] size-4 -translate-x-1/2 rounded-full border-2 border-white bg-orange shadow-[0_0_0_1px_var(--color-orange-edge)]" />
      </div>
      <span className="text-xs font-semibold text-orange-edge">Live</span>
      <span className="font-mono text-xs font-medium">{mission.elapsed}</span>
    </div>
  );
}
