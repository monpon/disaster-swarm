import { Button } from "@swarm/ui/components/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import { Mark } from "@/components/icons";
import { Advantages } from "@/components/landing/advantages";
import { Audio } from "@/components/landing/audio";
import { Hero } from "@/components/landing/hero";
import { MapStory } from "@/components/landing/map-story";
import { Pitch } from "@/components/landing/pitch";
import { Race } from "@/components/landing/race";
import { useStory } from "@/components/landing/story";
import { Vitals } from "@/components/landing/vitals";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Mayfly: when every second counts, find them faster" }] }),
  component: Landing,
});

function Landing() {
  const story = useStory();
  return (
    <div className="min-h-svh bg-white">
      <header className="sticky top-0 z-30 flex h-[68px] items-center gap-6 border-b border-line-soft bg-white/90 px-4 backdrop-blur md:px-16">
        <Link to="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="text-lg font-bold tracking-[-0.02em]">Mayfly</span>
        </Link>
        <div className="flex-1" />
        <nav className="hidden items-center gap-7 text-sm font-medium text-[#3a3a38] md:flex">
          <a href="#race">One vs. many</a>
          <a href="#how">How it works</a>
          <a href="#vitals">Checking on people</a>
        </nav>
        <Button variant="primary" size="md" render={<Link to="/live" />} nativeButton={false}>
          Open the console
        </Button>
      </header>

      <Hero />
      <Race story={story} />
      <MapStory story={story} />
      <Vitals />
      <Audio />
      <Advantages story={story} />
      <Pitch />

      <section className="flex flex-col gap-10 px-4 pb-24 md:flex-row md:gap-16 md:px-[100px] md:pb-32">
        <h2 className="w-full max-w-[360px] shrink-0 text-[32px] leading-[38px] font-bold tracking-[-0.02em]">Honest about what it can&apos;t do.</h2>
        <div className="grid flex-1 gap-8 md:grid-cols-3">
          <Honest title="Not for heavy smoke" body="Cameras need light. We built for collapses, earthquakes and welfare checks first." />
          <Honest title="Estimates, not diagnoses" body="Pulse readings come with a confidence and never replace a medic." />
          <Honest title="A person stays in charge" body="The incident commander approves routes and can stop every drone at any time." />
        </div>
      </section>

      <section className="px-4 pb-16 md:px-16">
        <div className="flex flex-col gap-8 rounded-3xl bg-[linear-gradient(135deg,#ff6a2e_0%,#e8480c_100%)] px-8 py-14 shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_4px_0_var(--color-orange-deep)] md:flex-row md:items-center md:gap-12 md:px-[72px] md:py-16">
          <div className="flex flex-1 flex-col gap-3">
            <h2 className="text-[40px] leading-[1.05] font-bold tracking-[-0.035em] text-white md:text-[52px]">Find people faster.</h2>
            <p className="text-lg leading-7 text-white/90">Open the console and watch a search play out, room by room, all at once.</p>
          </div>
          <div className="flex flex-col items-stretch gap-3">
            <Link
              to="/live"
              className="flex h-[54px] items-center justify-center gap-2 rounded-xl bg-[linear-gradient(180deg,#fff,#f4f4f3)] px-[26px] text-[17px] font-semibold shadow-[0_3px_0_var(--color-orange-deep),0_8px_18px_rgb(80_20_0/0.25)] active:translate-y-px"
            >
              Open the console
              <ArrowRight className="size-4" />
            </Link>
            <Link to="/missions/new" className="text-center text-sm font-medium text-white/90 underline-offset-4 hover:underline">
              or start a demo mission
            </Link>
          </div>
        </div>
      </section>

      <footer className="flex flex-col gap-10 border-t border-line-soft px-4 pt-10 pb-14 md:flex-row md:gap-16 md:px-[100px]">
        <div className="flex flex-1 flex-col gap-3">
          <span className="flex items-center gap-2.5">
            <Mark />
            <span className="text-[17px] font-bold tracking-[-0.02em]">Mayfly</span>
          </span>
          <span className="text-sm text-muted">Drone swarms that help rescuers find people faster.</span>
        </div>
        <FooterCol title="Story" links={[["One vs. many", "#race"], ["How it works", "#how"], ["Checking on people", "#vitals"]]} />
        <FooterCol title="Console" links={[["Live map", "/live"], ["Start a mission", "/missions/new"], ["Fleet", "/fleet"]]} />
        <FooterCol title="Settings" links={[["Detection", "/settings/detection"], ["Edge server", "/settings/edge"]]} />
      </footer>
    </div>
  );
}

function Honest({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col gap-2 border-t-2 border-ink pt-4">
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="text-sm leading-[22px] text-muted">{body}</p>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-[13px] font-semibold">{title}</span>
      {links.map(([label, href]) =>
        href.startsWith("#") ? (
          <a key={label} href={href} className="text-sm text-muted hover:text-ink">
            {label}
          </a>
        ) : (
          <Link key={label} to={href} className="text-sm text-muted hover:text-ink">
            {label}
          </Link>
        ),
      )}
    </div>
  );
}
