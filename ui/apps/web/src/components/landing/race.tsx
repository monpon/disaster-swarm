import { cn } from "@swarm/ui/lib/utils";
import { RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { CloudPins, PointCloud } from "./point-cloud";
import { roomsDone, type Story } from "./story";
import { usePlayOnView } from "./use-scroll-progress";

const PLAY_MS = 9000;

/**
 * One drone and the swarm search the same house side by side. Plays on its
 * own when it comes into view; the swarm finishes while the lone drone is
 * still going.
 */
export function Race({ story }: { story: Story | null }) {
  const { ref, progress, restart } = usePlayOnView<HTMLElement>(PLAY_MS);
  const end = story?.swarmEnd ?? 0.37;
  // Short beat before launch so the empty house registers.
  const t = Math.max(0, (progress - 0.06) / 0.94) * end;
  const total = story ? Object.keys(story.rooms).length : 7;
  const done = progress >= 1;
  const found = story ? story.events.person.swarm <= t : false;
  const launch = Math.min(1, progress / 0.08);

  return (
    <section id="race" ref={ref} className="flex flex-col items-center gap-8 px-4 py-24 md:px-16 md:py-28">
      <div className="flex flex-col items-center gap-3 text-center">
        <h2 className="max-w-[900px] text-[36px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[56px]">One drone searches room by room. The swarm splits up.</h2>
        <p className="text-lg text-muted md:text-[19px]">Same house. Same moment.</p>
      </div>
      <div className="flex w-full max-w-[760px] items-center gap-3">
        <span className="text-xs font-medium text-muted">Launch</span>
        <div className="h-1.5 flex-1 rounded-full bg-line">
          <div className="h-1.5 rounded-full bg-ink" style={{ width: `${progress * 100}%` }} />
        </div>
        <button type="button" onClick={restart} className="flex items-center gap-1.5 text-xs font-semibold text-muted hover:text-ink" aria-label="Replay">
          <RotateCcw className="size-3.5" />
          Replay
        </button>
      </div>
      <div className="grid w-full max-w-[1240px] gap-4 md:grid-cols-2 md:gap-6">
        <MapCard
          title="One drone"
          stat={`${story ? roomsDone(story, "solo", t) : 0} of ${total} rooms`}
          status={done ? "Still searching. Nobody found yet." : "Searching one room at a time."}
        >
          <PointCloud story={story} mode="solo" t={t} droneScale={launch}>
            <CloudPins story={story} mode="solo" t={t} />
          </PointCloud>
        </MapCard>
        <MapCard
          highlight
          title="The swarm"
          stat={`${story ? roomsDone(story, "swarm", t) : 0} of ${total} rooms`}
          status={done ? "Done. Person found in the bedroom." : found ? "Person found in the bedroom." : "Searching every room at once."}
          alert={found}
        >
          <PointCloud story={story} mode="swarm" t={t} droneScale={launch}>
            <CloudPins story={story} mode="swarm" t={t} />
          </PointCloud>
        </MapCard>
      </div>
      <p className="text-sm text-faint">Illustration of the idea, not a measured result.</p>
    </section>
  );
}

function MapCard({
  title,
  stat,
  status,
  alert,
  highlight,
  children,
}: {
  title: string;
  stat: string;
  status: string;
  alert?: boolean;
  highlight?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "relative aspect-[4/3] overflow-hidden rounded-[20px] bg-map",
        highlight ? "shadow-[0_0_0_2px_var(--color-orange),0_20px_40px_rgb(194_65_12/0.12)]" : "shadow-[0_0_0_1px_var(--color-line)]",
      )}
    >
      <div className="absolute inset-x-0 top-[14%] bottom-[14%]">{children}</div>
      <div className="absolute inset-x-3 top-3 flex items-start gap-2">
        <span className="rounded-lg bg-white px-3 py-1.5 text-lg font-bold shadow-[0_0_0_1px_var(--color-line)] md:text-xl">{title}</span>
        <div className="flex-1" />
        <span
          className={cn(
            "rounded-lg bg-white px-2.5 py-1.5 text-sm font-semibold tabular-nums shadow-[0_0_0_1px_var(--color-line)]",
            highlight ? "text-orange-edge" : "text-muted",
          )}
        >
          {stat}
        </span>
      </div>
      <div className="absolute inset-x-3 bottom-3">
        <span
          className={cn(
            "inline-flex items-center gap-2 rounded-[10px] px-3 py-2 text-sm md:text-[15px]",
            alert ? "bg-orange-tint font-semibold" : "bg-white font-medium text-muted shadow-[0_0_0_1px_var(--color-line)]",
          )}
        >
          <span className={cn("size-2.5 shrink-0 rounded-full", alert ? "bg-person" : "bg-[#b0b0ac]")} />
          {status}
        </span>
      </div>
    </div>
  );
}
