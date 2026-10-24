import { Button } from "@swarm/ui/components/button";
import { cn } from "@swarm/ui/lib/utils";
import { Link } from "@tanstack/react-router";
import { ArrowDown } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { CloudPins, PointCloud } from "./point-cloud";
import { roomsDone, type Story } from "./story";
import { range, usePrefersReducedMotion, useScrollProgress } from "./use-scroll-progress";

const PLAY_MS = 7000;
const HOLD_MS = 2500;

/**
 * Loops the swarm mapping the house while the visitor sits on the hero. When
 * paused it holds its last value, so scrolling away never jumps the map.
 */
function useLoopClock(end: number, enabled: boolean) {
  const [t, setT] = useState(end);
  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      setT(Math.min(1, ((now - start) % (PLAY_MS + HOLD_MS)) / PLAY_MS) * end);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [end, enabled]);
  return t;
}

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const ease = (k: number) => k * k * (3 - 2 * k);

/**
 * One pinned scene from hero to race. The hero's map plays on its own; as the
 * visitor scrolls, the headline lifts away, the swarm's map slides to the
 * right and rewinds to empty, a lone drone's map slides in on the left, and
 * then both search the same house on the same scroll-driven clock.
 */
export function HeroRace({ story }: { story: Story | null }) {
  const { ref, progress: p } = useScrollProgress<HTMLElement>();
  const reduced = usePrefersReducedMotion();
  const end = story?.swarmEnd ?? 0.37;
  const atTop = p < 0.01;
  const loopT = useLoopClock(end, !reduced && story !== null && atTop);

  const lift = ease(range(p, 0.04, 0.2)); // map moves aside and rewinds
  const fade = range(p, 0.02, 0.11); // hero copy leaves first
  const intro = range(p, 0.12, 0.22); // caption swap
  const race = range(p, 0.3, 0.9);
  const heroT = reduced ? end : loopT;
  const swarmT = race > 0 ? race * end : lerp(heroT, 0, lift);
  const soloT = race * end;
  const total = story ? Object.keys(story.rooms).length : 7;
  const done = race >= 0.999;
  const personFound = story ? story.events.person.swarm <= swarmT && race > 0 : false;

  return (
    <section ref={ref} className="relative h-[560vh]">
      <div className="sticky top-[68px] h-[calc(100svh-68px)] overflow-hidden">
        {/* Hero copy lifts away. */}
        <div
          className="absolute inset-x-0 top-0 flex flex-col items-center gap-4 px-4 pt-8 md:gap-5 md:pt-10"
          style={{ opacity: 1 - fade, transform: `translateY(${-60 * fade}px)`, pointerEvents: fade > 0.5 ? "none" : undefined }}
        >
          <span className="rounded-full bg-panel px-3 py-1 text-[13px] font-medium text-muted shadow-[inset_0_0_0_1px_var(--color-line)]">
            Search and rescue drones. A Cal Hacks proof of concept.
          </span>
          <h1 className="text-center text-[40px] leading-[0.98] font-bold tracking-[-0.045em] sm:text-[60px] lg:text-[80px]">
            When Every Second Counts,
            <br />
            <span className="text-orange">Send the Swarm.</span>
          </h1>
          <p className="max-w-[700px] text-center text-base leading-7 text-muted md:text-[19px] md:leading-[29px]">
            Instead of one expensive drone searching alone, we send a team of small, smart drones. They fly on their own, search together, and build a map to help
            rescuers find people faster.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Button variant="primary" size="xl" render={<a href="#how" />} nativeButton={false}>
              See how it works
              <ArrowDown />
            </Button>
            <Button size="xl" className="font-medium" render={<Link to="/live" />} nativeButton={false}>
              Open the console
            </Button>
          </div>
        </div>

        {/* Race captions fade in where the hero copy was. */}
        <div
          className="absolute inset-x-0 top-0 flex flex-col items-center gap-2 px-4 pt-6 text-center md:pt-8"
          style={{ opacity: intro, transform: `translateY(${16 * (1 - intro)}px)` }}
        >
          <h2 className="text-[30px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[52px]">
            {race > 0 ? "One drone vs. the swarm." : "After a building falls, rescuers can't see inside."}
          </h2>
          <p className="text-base text-muted md:text-lg">
            {race > 0 ? "Same house. Same clock. Keep scrolling." : "Searching one room at a time is slow and dangerous."}
          </p>
          <div className="mt-2 flex w-full max-w-[720px] items-center gap-3" style={{ opacity: race > 0 ? 1 : 0 }}>
            <span className="text-xs font-medium text-muted">Launch</span>
            <div className="h-1.5 flex-1 rounded-full bg-line">
              <div className="h-1.5 rounded-full bg-ink" style={{ width: `${race * 100}%` }} />
            </div>
            <span className="text-xs font-medium text-muted">Swarm finishes</span>
          </div>
        </div>

        {/* The maps. Positions interpolate from one centered hero map to a split. */}
        <div
          className="absolute inset-x-3 bottom-3 md:inset-x-16 md:bottom-6"
          style={{ top: `${lerp(54, 23, lift)}%` }}
        >
          <MapCard
            style={{ left: 0, width: "49%", opacity: lift, transform: `translateX(${-40 * (1 - lift)}px)` }}
            title="One drone"
            stat={`${roomsDone(story ?? fallback, "solo", soloT)} of ${total} rooms`}
            status={done ? "Still searching. Nobody found yet." : "Searching one room at a time."}
            showMeta={race > 0}
          >
            <PointCloud story={story} mode="solo" t={soloT} droneScale={race > 0 ? 1 : lift}>
              <CloudPins story={story} mode="solo" t={race > 0 ? soloT : -1} />
            </PointCloud>
          </MapCard>
          <MapCard
            highlight={lift > 0.5}
            style={{ left: `${lerp(0, 51, lift)}%`, width: `${lerp(100, 49, lift)}%` }}
            title="The swarm"
            stat={`${roomsDone(story ?? fallback, "swarm", swarmT)} of ${total} rooms`}
            status={done ? "Done. Person found in the bedroom." : personFound ? "Person found in the bedroom." : "Searching every room at once."}
            alert={personFound}
            showMeta={race > 0}
            heroBadge={lift < 0.5 ? (swarmT >= end - 1e-3 ? "4 drones, 1 shared map" : "4 drones searching at once") : undefined}
          >
            <PointCloud story={story} mode="swarm" t={swarmT}>
              <CloudPins story={story} mode="swarm" t={race > 0 ? swarmT : lift < 0.3 ? swarmT : -1} labels={lift < 0.5} />
            </PointCloud>
          </MapCard>
          <p className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 text-xs text-faint" style={{ opacity: race > 0 ? 1 : 0 }}>
            Illustration of the idea, not a measured result.
          </p>
        </div>
      </div>
    </section>
  );
}

const fallback = { rooms: {} } as unknown as Story;

function MapCard({
  style,
  title,
  stat,
  status,
  alert,
  highlight,
  showMeta,
  heroBadge,
  children,
}: {
  style: React.CSSProperties;
  title: string;
  stat: string;
  status: string;
  alert?: boolean;
  highlight?: boolean;
  showMeta: boolean;
  heroBadge?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "absolute top-0 bottom-5 overflow-hidden rounded-[20px] bg-map transition-shadow duration-300",
        highlight && "shadow-[0_0_0_2px_var(--color-orange),0_20px_40px_rgb(194_65_12/0.12)]",
      )}
      style={style}
    >
      {children}
      <div className="absolute inset-x-3 top-3 flex items-start gap-2 transition-opacity duration-300" style={{ opacity: showMeta ? 1 : 0 }}>
        <span className="rounded-lg bg-white px-2.5 py-1.5 text-base font-bold shadow-[0_0_0_1px_var(--color-line)] md:text-lg">{title}</span>
        <div className="flex-1" />
        <span className={cn("rounded-lg bg-white px-2.5 py-1.5 text-xs font-semibold tabular-nums shadow-[0_0_0_1px_var(--color-line)] md:text-sm", highlight ? "text-orange-edge" : "text-muted")}>
          {stat}
        </span>
      </div>
      <div className="absolute inset-x-3 bottom-3 flex transition-opacity duration-300" style={{ opacity: showMeta ? 1 : 0 }}>
        <span className={cn("flex items-center gap-2 rounded-[10px] px-3 py-2 text-xs md:text-[15px]", alert ? "bg-orange-tint font-semibold" : "bg-white font-medium text-muted shadow-[0_0_0_1px_var(--color-line)]")}>
          <span className={cn("size-2.5 shrink-0 rounded-full", alert ? "bg-person" : "bg-[#b0b0ac]")} />
          {status}
        </span>
      </div>
      {heroBadge && (
        <span className="absolute bottom-4 left-4 flex h-10 items-center gap-2.5 rounded-[10px] bg-white px-3.5 text-[15px] font-semibold shadow-[0_0_0_1px_var(--color-line),0_6px_16px_rgb(0_0_0/0.08)]">
          <span className="size-2.5 rounded-full bg-orange" />
          {heroBadge}
        </span>
      )}
    </div>
  );
}
