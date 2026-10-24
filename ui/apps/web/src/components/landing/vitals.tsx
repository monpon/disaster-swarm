import { cn } from "@swarm/ui/lib/utils";
import { Check } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";

import { usePlayOnView } from "./use-scroll-progress";

const VitalsScene = lazy(() => import("./vitals-scene").then((m) => ({ default: m.VitalsScene })));

const PULSE = 88;
const PLAY_MS = 6500;

/**
 * A drone sweeps the room, locks onto someone waving by the wall, and the
 * result is one check mark and one number. Plays on its own when in view.
 */
export function Vitals() {
  const { ref, progress } = usePlayOnView<HTMLElement>(PLAY_MS);
  const lock = Math.min(1, Math.max(0, (progress - 0.58) / 0.08));
  const read = Math.min(1, Math.max(0, (progress - 0.68) / 0.22));
  const done = read >= 1;
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <section id="vitals" ref={ref} className="flex flex-col items-center gap-8 px-4 py-20 md:px-16 md:py-24">
      <div className="flex flex-col items-center gap-2 text-center">
        <h2 className="text-[34px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[48px]">It checks on people, too.</h2>
        <p className="max-w-[620px] text-base text-muted md:text-lg">When a drone finds someone, it reads their pulse from the camera.</p>
      </div>
      <div className="grid w-full max-w-[1040px] items-stretch gap-5 md:grid-cols-[1.4fr_1fr]">
        <div className="relative aspect-[4/3] overflow-hidden rounded-[20px] bg-panel shadow-[0_0_0_1px_var(--color-line)] md:aspect-auto md:min-h-[400px]">
          {mounted && (
            <Suspense fallback={null}>
              <VitalsScene phase={progress} lock={lock} />
            </Suspense>
          )}
          <span className="absolute top-3 left-3 flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs font-semibold shadow-[0_0_0_1px_var(--color-line)]">
            <span className={cn("size-1.5 rounded-full", lock > 0.5 ? "bg-orange" : "bg-faint")} />
            {lock > 0.5 ? "Locked on" : "Scanning"}
          </span>
        </div>
        <div className="flex flex-col items-center justify-center gap-5 rounded-[20px] bg-white p-8 text-center shadow-[0_0_0_1px_var(--color-line)]">
          <span
            className={cn(
              "flex size-20 items-center justify-center rounded-full transition-all duration-500",
              done ? "scale-100 bg-orange text-white shadow-[0_0_0_10px_rgb(255_90_31/0.15)]" : "scale-90 bg-panel text-faint",
            )}
          >
            <Check className="size-10" strokeWidth={3} />
          </span>
          <span className="flex items-baseline gap-2">
            <span className="text-[88px] leading-none font-bold tracking-[-0.04em] tabular-nums">{read > 0 ? Math.round(PULSE * read) : "–"}</span>
            <span className="text-lg font-medium text-muted">bpm</span>
          </span>
          <span className="text-base text-muted">{done ? "Pulse read. Sent to the crew." : lock > 0.5 ? "Reading…" : "Looking for people…"}</span>
          <span className="text-xs text-faint">Example output. An estimate, not a diagnosis.</span>
        </div>
      </div>
    </section>
  );
}
