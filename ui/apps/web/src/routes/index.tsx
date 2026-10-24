import { Button } from "@swarm/ui/components/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import { Mark } from "@/components/icons";
import { Advantages } from "@/components/landing/advantages";
import { Compare } from "@/components/landing/compare";
import { Hero } from "@/components/landing/hero";
import { MapStory } from "@/components/landing/map-story";
import { SplitScreen } from "@/components/landing/split-screen";
import { useStory } from "@/components/landing/story";
import { UnderTheHood } from "@/components/landing/under-the-hood";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Swarm: when every second counts, send the swarm" }] }),
  component: Landing,
});

function Landing() {
  const story = useStory();
  return (
    <div className="min-h-svh bg-white">
      <header className="sticky top-0 z-30 flex h-[68px] items-center gap-6 border-b border-line-soft bg-white/90 px-4 backdrop-blur md:px-16">
        <Link to="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="text-lg font-bold tracking-[-0.02em]">Swarm</span>
        </Link>
        <div className="flex-1" />
        <nav className="hidden items-center gap-7 text-sm font-medium text-[#3a3a38] md:flex">
          <a href="#compare">One vs. many</a>
          <a href="#how">How it works</a>
          <a href="#judges">For judges</a>
        </nav>
        <Button variant="primary" size="md" render={<Link to="/live" />} nativeButton={false}>
          Open the console
        </Button>
      </header>

      <Hero story={story} />

      <section className="flex flex-col items-center gap-4 px-4 pt-28 pb-24 text-center md:pt-36">
        <h2 className="max-w-[980px] text-[36px] leading-[1.08] font-bold tracking-[-0.035em] md:text-[56px]">
          After a building falls, rescuers can&apos;t see inside.
        </h2>
        <p className="max-w-[760px] text-lg leading-8 text-muted md:text-[21px]">Searching one room at a time is slow and dangerous. People inside are waiting.</p>
      </section>

      <Compare story={story} />
      <MapStory story={story} />
      <Advantages story={story} />
      <SplitScreen story={story} />
      <UnderTheHood />

      <section className="px-4 pb-16 md:px-16">
        <div className="flex flex-col gap-8 rounded-3xl bg-[linear-gradient(135deg,#ff6a2e_0%,#e8480c_100%)] px-8 py-14 shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_4px_0_var(--color-orange-deep)] md:flex-row md:items-center md:gap-12 md:px-[72px] md:py-16">
          <div className="flex flex-1 flex-col gap-3">
            <h2 className="text-[40px] leading-[1.05] font-bold tracking-[-0.035em] text-white md:text-[52px]">See the swarm at work.</h2>
            <p className="text-lg leading-7 text-white/90">Built at Cal Hacks. A proof of concept, not a finished product.</p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row md:flex-col">
            <Link
              to="/live"
              className="flex h-14 items-center justify-center gap-2 rounded-xl bg-[linear-gradient(180deg,#fff,#f4f4f3)] px-[26px] text-[17px] font-semibold shadow-[0_3px_0_var(--color-orange-deep),0_8px_18px_rgb(80_20_0/0.25)] active:translate-y-px"
            >
              Open the console
              <ArrowRight className="size-4" />
            </Link>
            <Link to="/incidents/new" className="text-center text-sm font-medium text-white/90 underline-offset-4 hover:underline">
              or start a demo mission
            </Link>
          </div>
        </div>
      </section>

      <footer className="flex flex-col gap-6 border-t border-line-soft px-4 pt-10 pb-14 md:flex-row md:items-center md:px-[100px]">
        <span className="flex items-center gap-2.5">
          <Mark />
          <span className="text-[17px] font-bold tracking-[-0.02em]">Swarm</span>
        </span>
        <span className="flex-1 text-sm text-muted">Search and rescue drones. Cal Hacks proof of concept.</span>
        <nav className="flex gap-6 text-sm text-muted">
          <Link to="/live">Console</Link>
          <Link to="/fleet">Fleet</Link>
          <Link to="/settings/detection">Settings</Link>
        </nav>
      </footer>
    </div>
  );
}
