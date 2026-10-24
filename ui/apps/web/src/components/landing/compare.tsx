import { cn } from "@swarm/ui/lib/utils";

import type { Story } from "./story";
import { roomsDone, TopDownHouse } from "./top-down";
import { range, useScrollProgress } from "./use-scroll-progress";

/**
 * Pinned scene: one drone and the swarm search the same house on the same
 * clock, driven by scroll. The swarm finishes; the lone drone is still going.
 */
export function Compare({ story }: { story: Story | null }) {
  const { ref, progress } = useScrollProgress<HTMLElement>();
  const end = story?.swarmEnd ?? 0.37;
  const t = range(progress, 0.08, 0.88) * end;
  const total = story ? Object.keys(story.rooms).length : 7;

  return (
    <section id="compare" ref={ref} className="relative h-[260vh] bg-panel">
      <div className="sticky top-[68px] flex min-h-[calc(100svh-68px)] flex-col items-center justify-center gap-6 px-4 py-8 md:px-16">
        <div className="flex flex-col items-center gap-2 text-center">
          <h2 className="text-[36px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[56px]">One drone vs. the swarm.</h2>
          <p className="text-lg text-muted md:text-[19px]">Same house. Same moment. Keep scrolling.</p>
        </div>
        <div className="flex w-full max-w-[860px] items-center gap-3">
          <span className="text-xs font-medium text-muted">Launch</span>
          <div className="h-1.5 flex-1 rounded-full bg-line">
            <div className="h-1.5 rounded-full bg-ink" style={{ width: `${(t / end) * 100}%` }} />
          </div>
          <span className="text-xs font-medium text-muted">Swarm finishes</span>
        </div>
        {story && (
          <div className="grid w-full max-w-[1150px] grid-cols-2 gap-3 md:gap-7">
            <Card
              title="One drone"
              count={`${roomsDone(story, "solo", t)} of ${total} rooms`}
              status={t >= end - 1e-3 ? "Still searching. Nobody found yet." : "Searching one room at a time."}
            >
              <TopDownHouse story={story} mode="solo" t={t} />
            </Card>
            <Card
              highlight
              title="The swarm"
              count={`${roomsDone(story, "swarm", t)} of ${total} rooms`}
              status={
                t >= end - 1e-3
                  ? "Done. Person found in the bedroom."
                  : story.events.person.swarm <= t
                    ? "Person found in the bedroom."
                    : "Searching every room at once."
              }
              alert={story.events.person.swarm <= t}
            >
              <TopDownHouse story={story} mode="swarm" t={t} />
            </Card>
          </div>
        )}
        <p className="text-sm text-faint">Illustration of the idea, not a measured result.</p>
      </div>
    </section>
  );
}

function Card({
  title,
  count,
  status,
  highlight,
  alert,
  children,
}: {
  title: string;
  count: string;
  status: string;
  highlight?: boolean;
  alert?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-2xl bg-white p-3 md:gap-5 md:rounded-[20px] md:p-7",
        highlight ? "shadow-[0_0_0_2px_var(--color-orange),0_20px_40px_rgb(194_65_12/0.12)]" : "shadow-[0_0_0_1px_var(--color-line)]",
      )}
    >
      <div className="flex flex-col gap-0.5 md:flex-row md:items-baseline md:gap-3">
        <h3 className="flex-1 text-lg font-bold tracking-[-0.02em] md:text-[28px]">{title}</h3>
        <span className={cn("text-xs font-semibold tabular-nums md:text-base", highlight ? "text-orange-edge" : "text-muted")}>{count}</span>
      </div>
      <div className="mx-auto w-full max-w-[448px]">{children}</div>
      <div className={cn("flex min-h-11 items-center gap-2.5 rounded-[10px] px-2.5 py-2 md:px-3.5", alert ? "bg-orange-tint" : "bg-panel")}>
        <span className={cn("size-2.5 shrink-0 rounded-full", alert ? "bg-person" : "bg-[#b0b0ac]")} />
        <span className={cn("text-xs md:text-base", alert ? "font-semibold" : "font-medium text-muted")}>{status}</span>
      </div>
    </div>
  );
}
