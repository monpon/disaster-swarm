import { Button } from "@swarm/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ArrowDown } from "lucide-react";
import { useEffect, useState } from "react";

import { PointCloud } from "./point-cloud";
import type { Story } from "./story";
import { usePrefersReducedMotion } from "./use-scroll-progress";

const PLAY_MS = 7000;
const HOLD_MS = 2500;

/** Loops the swarm mapping the house, so the idea lands before any scrolling. */
function useLoopClock(end: number, enabled: boolean) {
  const [t, setT] = useState(enabled ? 0 : end);
  useEffect(() => {
    if (!enabled) {
      setT(end);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const e = (now - start) % (PLAY_MS + HOLD_MS);
      setT(Math.min(1, e / PLAY_MS) * end);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [end, enabled]);
  return t;
}

export function Hero({ story }: { story: Story | null }) {
  const reduced = usePrefersReducedMotion();
  const end = story?.swarmEnd ?? 0.37;
  const t = useLoopClock(end, !reduced && story !== null);
  const done = t >= end - 1e-3;

  return (
    <section className="flex flex-col items-center gap-5 px-4 pt-10 pb-10 md:gap-6 md:px-16 md:pt-12">
      <span className="rounded-full bg-panel px-3 py-1 text-[13px] font-medium text-muted shadow-[inset_0_0_0_1px_var(--color-line)]">
        Search and rescue drones. A Cal Hacks proof of concept.
      </span>
      <h1 className="text-center text-[44px] leading-[0.98] font-bold tracking-[-0.045em] sm:text-[64px] lg:text-[84px]">
        When Every Second Counts,
        <br />
        <span className="text-orange">Send the Swarm.</span>
      </h1>
      <p className="max-w-[720px] text-center text-lg leading-8 text-muted md:text-[20px] md:leading-[30px]">
        Instead of one expensive drone searching alone, we send a team of small, smart drones. They fly on their own, search together, and build a map to help
        rescuers find people faster.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button variant="primary" size="xl" render={<a href="#compare" />} nativeButton={false}>
          See how it works
          <ArrowDown />
        </Button>
        <Button size="xl" className="font-medium" render={<Link to="/live" />} nativeButton={false}>
          Open the console
        </Button>
      </div>
      <div className="relative mt-2 aspect-[1240/520] w-full max-w-[1240px] overflow-hidden rounded-[20px] bg-map">
        <PointCloud story={story} mode="swarm" t={t} />
        <div className="absolute bottom-4 left-4 flex h-10 items-center gap-2.5 rounded-[10px] bg-white px-3.5 shadow-[0_0_0_1px_var(--color-line),0_6px_16px_rgb(0_0_0/0.08)] md:bottom-6 md:left-6">
          <span className="size-2.5 rounded-full bg-orange" />
          <span className="text-[15px] font-semibold">{done ? "4 drones, 1 shared map" : "4 drones searching at once"}</span>
        </div>
      </div>
    </section>
  );
}
