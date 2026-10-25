import { cn } from "@swarm/ui/lib/utils";
import { DoorClosed, Mic, TriangleAlert, User, X } from "lucide-react";
import type { ComponentType } from "react";

import { PointCloud } from "./point-cloud";
import { coverage, type Story } from "./story";
import { range, useAnimatedValue, useScrollProgress } from "./use-scroll-progress";

const STEPS = [
  { title: "Each drone takes a room.", detail: "Four small drones fly in and split up." },
  { title: "What they see joins one map.", detail: "Every view lands in the same picture of the house." },
  { title: "People and dangers get marked.", detail: "No one has to spot them on a screen." },
  { title: "Rescuers hear the way in.", detail: "The safest path goes straight to the crew." },
];

const FINDINGS: { key: keyof Story["events"]; title: string; where: string; color: string; Icon: ComponentType<{ className?: string; strokeWidth?: number }> }[] = [
  { key: "blocked", title: "Blocked doorway", where: "Living room to kitchen", color: "bg-ink", Icon: X },
  { key: "door", title: "Closed door", where: "Hallway to garage", color: "bg-door", Icon: DoorClosed },
  { key: "person", title: "Person on the floor", where: "Bedroom", color: "bg-person", Icon: User },
  { key: "gas", title: "Gas tank", where: "Kitchen", color: "bg-hazard", Icon: TriangleAlert },
];

const FEEDS = ["/assets/f1.png", "/assets/f2.png", "/assets/f3.png", "/assets/f4.png"];
const ROUTE = "365.9,474.1 405.4,451.3 481.1,403.8 517.3,367.7 431.7,322.1 379.1,352.5 303.4,354.4";

/** How far into the search each step plays, as a share of the swarm's run. */
const STEP_TARGET = [0.08, 0.62, 1, 1];

/**
 * Pinned scene: scroll picks the step, and within each step the map and the
 * console panes animate on their own.
 */
export function MapStory({ story }: { story: Story | null }) {
  const { ref, progress } = useScrollProgress<HTMLElement>();
  const end = story?.swarmEnd ?? 0.37;
  const step = Math.min(3, Math.floor(range(progress, 0, 0.92) * 4));
  const t = useAnimatedValue(STEP_TARGET[step]! * end, 1.6);
  const pct = story ? Math.round(coverage(story, "swarm", t) * 100) : 0;
  const routeDraw = useAnimatedValue(step >= 3 ? 1 : 0, 2.2);

  return (
    <section id="how" ref={ref} className="relative h-[340vh]">
      <div className="sticky top-[68px] flex min-h-[calc(100svh-68px)] flex-col items-center justify-center gap-10 px-4 py-12 md:flex-row md:gap-12 md:px-16">
        <div className="flex w-full max-w-[380px] shrink-0 flex-col gap-7">
          <h2 className="text-[36px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[48px]">Together, they build one map.</h2>
          <ol className="flex flex-col gap-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className={cn("flex gap-3.5 transition-opacity duration-300", i === step ? "opacity-100" : "opacity-35")}>
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-full text-[13px] font-bold text-white transition-colors",
                    i === step ? "bg-orange" : "bg-ink",
                  )}
                >
                  {i + 1}
                </span>
                <span className="flex flex-col gap-1">
                  <span className="text-xl leading-7 font-semibold">{s.title}</span>
                  {i === step && <span className="text-base leading-6 text-muted">{s.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="relative aspect-[1019/700] w-full max-w-[920px] flex-1 overflow-hidden rounded-2xl bg-map shadow-[0_0_0_1px_var(--color-line-strong),0_24px_60px_rgb(21_21_21/0.14)]">
          <div className="absolute inset-x-0 top-0 z-10 flex h-11 items-center gap-2.5 border-b border-line bg-white px-3.5">
            <span className="size-[22px] rounded-[5px] bg-orange" />
            <span className="text-[13px] font-semibold">Demo site</span>
            <span className="flex items-center gap-1.5 text-xs font-semibold text-orange-edge">
              <span className="size-[7px] rounded-full bg-person" />
              Live
            </span>
            <div className="flex-1" />
            <span className="text-xs text-muted">Demo console</span>
          </div>
          <div className="absolute inset-x-0 top-11 bottom-0">
            <PointCloud story={story} mode="swarm" t={t}>
              {story && step >= 2 && (
                <>
                  {FINDINGS.map((f) => {
                    const e = story.events[f.key];
                    const on = e.swarm <= t || step >= 3;
                    const big = f.key === "person";
                    return (
                      <span
                        key={f.key}
                        className={cn(
                          "absolute flex items-center justify-center rounded-[15px_15px_15px_2px] text-white shadow-[0_0_0_2px_#fff,0_3px_8px_rgb(0_0_0/0.25)] transition-[opacity,transform] duration-300",
                          f.color,
                          big ? "size-[34px]" : "size-7",
                          on ? "scale-100 opacity-100" : "scale-50 opacity-0",
                        )}
                        style={{ left: e.px[0] - 4, top: e.px[1] - (big ? 38 : 32) }}
                      >
                        <f.Icon className={big ? "size-[18px]" : "size-3.5"} strokeWidth={2.4} />
                      </span>
                    );
                  })}
                </>
              )}
              <svg width={1019} height={636} className="pointer-events-none absolute inset-0">
                <polyline
                  points={story ? `${ROUTE} ${story.events.person.px[0] + 10},${story.events.person.px[1]}` : ROUTE}
                  fill="none"
                  stroke="#151515"
                  strokeWidth={3.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  pathLength={1}
                  strokeDasharray="1 1"
                  strokeDashoffset={1 - routeDraw}
                  opacity={routeDraw > 0 ? 0.9 : 0}
                />
              </svg>
            </PointCloud>
          </div>

          {/* Pane: live feeds slide up while drones fan out. */}
          <div
            className={cn(
              "absolute bottom-3 left-3 z-10 flex gap-1.5 rounded-xl bg-white p-1.5 shadow-[0_0_0_1px_var(--color-line),0_10px_24px_rgb(0_0_0/0.12)] transition-[opacity,transform] duration-500",
              step === 0 ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-6 opacity-0",
            )}
          >
            {FEEDS.map((src, i) => (
              <div key={src} className="relative h-[44px] w-[70px] overflow-hidden rounded-md bg-[#222] md:h-[72px] md:w-[118px]">
                <img src={src} alt="" className="size-full object-cover" />
                <span className="absolute top-1 left-1 rounded bg-black/60 px-1 font-mono text-[10px] text-white">D{i + 1}</span>
              </div>
            ))}
          </div>

          {/* Pane: coverage meter once views start merging. */}
          <div
            className={cn(
              "absolute bottom-3 left-3 z-10 flex flex-col gap-1.5 rounded-lg bg-white/95 px-3 py-2.5 shadow-[0_0_0_1px_var(--color-line)] transition-[opacity,transform] duration-500",
              step >= 1 ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-6 opacity-0",
            )}
          >
            <span className="flex items-baseline gap-1.5">
              <span className="font-mono text-[17px] font-semibold tabular-nums">{pct}%</span>
              <span className="text-xs text-muted">of the house mapped</span>
            </span>
            <span className="h-1 w-[180px] rounded-full bg-[#e3e3e0]">
              <span className="block h-1 rounded-full bg-orange" style={{ width: `${pct}%` }} />
            </span>
          </div>

          {/* Pane: findings slide in from the right. */}
          <div
            className={cn(
              "absolute top-[56px] right-2 z-10 flex w-[190px] origin-top-right flex-col overflow-hidden max-md:[&_span.text-xs]:hidden md:right-3 md:w-[290px] rounded-xl bg-white shadow-[0_0_0_1px_var(--color-line),0_16px_40px_rgb(0_0_0/0.14)] transition-[opacity,transform] duration-500 md:w-[290px]",
              step >= 2 ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-10 opacity-0",
            )}
          >
            <div className="flex h-10 items-center border-b border-line-soft px-3.5 text-[13px] font-semibold">Found so far</div>
            {story &&
              [...FINDINGS]
                .sort((a, b) => story.events[a.key].swarm - story.events[b.key].swarm)
                .filter((f) => story.events[f.key].swarm <= t || step >= 3)
                .map((f) => (
                  <div
                    key={f.key}
                    className={cn(
                      "flex items-center gap-2.5 border-b border-line-soft px-3.5 py-2.5 last:border-b-0",
                      f.key === "person" && "bg-[#fff7f3] shadow-[inset_3px_0_0_var(--color-person)]",
                    )}
                  >
                    <span className={cn("flex size-7 items-center justify-center rounded-[7px] text-white", f.color)}>
                      <f.Icon className="size-3.5" strokeWidth={2.4} />
                    </span>
                    <span className="flex flex-col">
                      <span className={cn("text-sm", f.key === "person" ? "font-semibold" : "font-medium")}>{f.title}</span>
                      <span className="text-xs text-muted">{f.where}</span>
                    </span>
                  </div>
                ))}
          </div>

          {/* Pane: the crew hears the route. */}
          <div
            className={cn(
              "absolute right-2 bottom-2 left-2 z-10 flex items-start gap-3 rounded-xl bg-ink p-3 text-white md:right-3 md:bottom-3 md:left-auto md:max-w-[330px] md:p-3.5 shadow-[0_16px_40px_rgb(0_0_0/0.25)] transition-[opacity,transform] duration-500",
              step >= 3 ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-6 opacity-0",
            )}
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-orange">
              <Mic className="size-4" />
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-xs font-semibold text-[#ff8a5c]">In the crew's earpiece</span>
              <span className="text-[13px] leading-[18px] md:text-[15px] md:leading-[21px]">"Person in the bedroom. Go in the front door, then left. Gas tank is in the kitchen."</span>
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
