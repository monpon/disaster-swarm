import { cn } from "@swarm/ui/lib/utils";
import { DoorClosed, Gamepad2, Radio, Sparkles, TriangleAlert, User } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

import { PointCloud } from "./point-cloud";
import type { Story } from "./story";
import { roomsDone } from "./top-down";
import { range, useScrollProgress } from "./use-scroll-progress";

/** Radio traffic in the one-drone setup, revealed as fractions of the swarm's run. */
const RADIO = [
  { at: 0.05, who: "Dispatcher", text: "Pilot, start at the front door." },
  { at: 0.3, who: "Pilot", text: "In the hallway. Hard to see much." },
  { at: 0.55, who: "Dispatcher", text: "Anyone there? Check the kitchen next." },
  { at: 0.8, who: "Pilot", text: "Turning around. Something on the floor, can't tell what." },
];

const FLAGS: { key: keyof Story["events"]; text: string; drone: string; color: string; Icon: ComponentType<{ className?: string }> }[] = [
  { key: "person", text: "Person found, bedroom", drone: "drone 2", color: "bg-person", Icon: User },
  { key: "gas", text: "Gas tank, kitchen", drone: "drone 4", color: "bg-hazard", Icon: TriangleAlert },
  { key: "door", text: "Closed door, hallway", drone: "drone 3", color: "bg-door", Icon: DoorClosed },
];

const FEEDS = [
  { src: "/assets/f1.png" },
  { src: "/assets/f2.png", box: "left-[11%] top-[64%] w-[46%] h-[24%] border-[#FF3B2E]", key: "person" as const },
  { src: "/assets/f3.png", box: "left-[43%] top-[29%] w-[14%] h-[40%] border-[#4D8BFF]", key: "door" as const },
  { src: "/assets/f4.png", box: "left-[67%] top-[41%] w-[10%] h-[39%] border-[#F5B400]", key: "gas" as const },
];

/**
 * Pinned split screen: today's setup (one drone, a pilot on the sticks, a
 * dispatcher on the radio) against the swarm that flies itself and flags
 * dangers on its own. Both sides run on the same scroll-driven clock.
 */
export function SplitScreen({ story }: { story: Story | null }) {
  const { ref, progress } = useScrollProgress<HTMLElement>();
  const end = story?.swarmEnd ?? 0.37;
  const f = range(progress, 0.06, 0.86);
  const t = f * end;
  const total = story ? Object.keys(story.rooms).length : 7;

  return (
    <section ref={ref} className="relative h-[300vh] bg-panel">
      <div className="sticky top-[68px] flex min-h-[calc(100svh-68px)] flex-col justify-center gap-8 px-4 py-12 md:px-16">
        <div className="flex flex-col items-center gap-2 text-center">
          <h2 className="text-[36px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[56px]">Who is doing the work?</h2>
          <p className="max-w-[720px] text-lg text-muted md:text-[19px]">Today, one pilot flies one drone while a dispatcher asks what they see. The swarm flies itself and points out dangers.</p>
        </div>
        <div className="grid gap-5 lg:grid-cols-2">
          <Side
            title="One drone, one pilot"
            tag={
              <>
                <Gamepad2 className="size-4" /> Steered by hand
              </>
            }
            cloud={<PointCloud story={story} mode="solo" t={t} fit="cover" />}
            rooms={story ? `${roomsDone(story, "solo", t)} of ${total} rooms` : ""}
          >
            <div className="flex gap-3">
              <div className="relative h-[92px] w-[150px] shrink-0 overflow-hidden rounded-lg bg-[#222]">
                <img src="/assets/f3.png" alt="" className="size-full object-cover" />
                <span className="absolute top-1.5 left-1.5 rounded bg-black/60 px-1.5 text-[11px] text-white">Pilot's only view</span>
              </div>
              <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
                {RADIO.map((r) => (
                  <li
                    key={r.at}
                    className={cn("flex gap-2 text-sm leading-5 transition-opacity duration-300", f >= r.at ? "opacity-100" : "opacity-0")}
                  >
                    <Radio className="mt-0.5 size-3.5 shrink-0 text-muted" />
                    <span>
                      <span className="font-semibold text-muted">{r.who}: </span>
                      {r.text}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <Footer dot="bg-[#b0b0ac]" text="One room at a time. Dangers spotted by eye." />
          </Side>
          <Side
            highlight
            title="The swarm"
            tag={
              <>
                <Sparkles className="size-4" /> Flies itself
              </>
            }
            cloud={<PointCloud story={story} mode="swarm" t={t} fit="cover" />}
            rooms={story ? `${roomsDone(story, "swarm", t)} of ${total} rooms` : ""}
          >
            <div className="flex gap-3">
              <div className="grid h-[92px] w-[150px] shrink-0 grid-cols-2 gap-0.5 overflow-hidden rounded-lg bg-ink p-0.5">
                {FEEDS.map((feed) => (
                  <div key={feed.src} className="relative overflow-hidden rounded-[3px]">
                    <img src={feed.src} alt="" className="size-full object-cover" />
                    {feed.box && story && story.events[feed.key].swarm <= t && <div className={cn("absolute border", feed.box)} />}
                  </div>
                ))}
              </div>
              <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
                {FLAGS.map((flag) => {
                  const on = story ? story.events[flag.key].swarm <= t : false;
                  return (
                    <li key={flag.key} className={cn("flex items-center gap-2 transition-[opacity,transform] duration-300", on ? "translate-x-0 opacity-100" : "translate-x-2 opacity-0")}>
                      <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-md text-white [&_svg]:size-3.5", flag.color)}>
                        <flag.Icon />
                      </span>
                      <span className="flex-1 truncate text-sm font-medium">{flag.text}</span>
                      <span className="hidden text-xs text-muted sm:inline">flagged by {flag.drone}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
            <Footer dot="bg-orange" text="Every room at once. Dangers flagged automatically." strong />
          </Side>
        </div>
        <p className="text-center text-sm text-faint">Illustration of the idea, not a measured result.</p>
      </div>
    </section>
  );
}

function Side({
  title,
  tag,
  cloud,
  rooms,
  highlight,
  children,
}: {
  title: string;
  tag: ReactNode;
  cloud: ReactNode;
  rooms: string;
  highlight?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-[20px] bg-white",
        highlight ? "shadow-[0_0_0_2px_var(--color-orange),0_20px_40px_rgb(194_65_12/0.12)]" : "shadow-[0_0_0_1px_var(--color-line)]",
      )}
    >
      <div className="flex h-14 items-center gap-3 border-b border-line-soft px-5">
        <h3 className="flex-1 text-xl font-bold">{title}</h3>
        <span className={cn("flex items-center gap-1.5 text-[13px] font-semibold", highlight ? "text-orange-edge" : "text-muted")}>{tag}</span>
      </div>
      <div className="relative aspect-[1019/520] bg-map">
        {cloud}
        <span className="absolute top-3 left-3 rounded-md bg-white px-2 py-1 text-[13px] font-semibold tabular-nums shadow-[0_0_0_1px_var(--color-line)]">{rooms}</span>
      </div>
      <div className="flex flex-col gap-3 px-5 pt-4 pb-5">{children}</div>
    </div>
  );
}

function Footer({ dot, text, strong }: { dot: string; text: string; strong?: boolean }) {
  return (
    <div className="flex items-center gap-2 pt-1">
      <span className={cn("size-2 rounded-full", dot)} />
      <span className={cn("text-sm", strong ? "font-medium" : "text-muted")}>{text}</span>
    </div>
  );
}
