import { useEffect, useRef, useState } from "react";

import { coverage, type Story } from "./story";

function useInView<T extends HTMLElement>(threshold = 0.4) {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([entry]) => entry?.isIntersecting && setInView(true), { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return { ref, inView };
}

/** Faster. Cheaper. Autonomous. In that order, with speed given the most room. */
export function Advantages({ story }: { story: Story | null }) {
  const { ref, inView } = useInView<HTMLDivElement>();
  // How much of the house one drone has covered when the swarm finishes, from the illustration.
  const solo = story ? Math.max(0.08, coverage(story, "solo", story.swarmEnd)) : 0.4;

  return (
    <section className="flex flex-col gap-5 px-4 py-24 md:px-16 md:py-32">
      <div ref={ref} className="flex flex-col gap-10 rounded-3xl bg-ink p-8 md:flex-row md:items-center md:gap-12 md:p-14">
        <div className="flex flex-1 flex-col gap-4">
          <span className="font-mono text-sm font-semibold text-[#ff8a5c]">1</span>
          <h2 className="text-[80px] leading-[0.9] font-bold tracking-[-0.05em] text-orange md:text-[128px]">Faster.</h2>
          <p className="max-w-[540px] text-xl leading-8 text-white md:text-2xl md:leading-[34px]">
            Many drones search at once, instead of one drone searching everything. More drones, more rooms checked at the same time.
          </p>
        </div>
        <div className="flex w-full max-w-[440px] flex-col gap-5">
          <Bar label="One drone" fill={inView ? solo : 0} tone="bg-[#5c5c59]" />
          <Bar label="The swarm" fill={inView ? 1 : 0} tone="bg-orange" />
          <span className="text-[13px] text-faint">How much of the house is searched by the time the swarm is done. Illustration, not a measurement.</span>
        </div>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <Advantage n="2" title="Cheaper.">
          Lots of small, low-cost drones share one powerful computer, instead of one very expensive drone. That could make searching more affordable.
        </Advantage>
        <Advantage n="3" title="Autonomous.">
          The drones fly and explore on their own. Rescuers don&apos;t have to steer each one.
        </Advantage>
      </div>
    </section>
  );
}

function Bar({ label, fill, tone }: { label: string; fill: number; tone: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm text-[#a3a3a0]">{label}</span>
      <div className="flex h-11 items-center rounded-[10px] bg-[#2c2c2b] p-1.5">
        <div className={`h-8 rounded-[7px] transition-[width] duration-[1600ms] ease-out ${tone}`} style={{ width: `${fill * 100}%` }} />
      </div>
    </div>
  );
}

function Advantage({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3.5 rounded-3xl bg-panel p-8 md:p-11">
      <span className="font-mono text-sm font-semibold text-orange-edge">{n}</span>
      <h2 className="text-[56px] leading-none font-bold tracking-[-0.045em] md:text-[72px]">{title}</h2>
      <p className="text-lg leading-[30px] text-muted md:text-xl">{children}</p>
    </div>
  );
}
