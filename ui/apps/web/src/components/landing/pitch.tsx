import { cn } from "@swarm/ui/lib/utils";
import { Eye, Hand, ListOrdered, Shield, TriangleAlert, User } from "lucide-react";
import type { ComponentType } from "react";

import { usePlayOnView } from "./use-scroll-progress";

const FOUND: { title: string; where: string; tone: "person" | "hazard"; motion: string; Icon: ComponentType<{ className?: string }> }[] = [
  { title: "Person, not moving", where: "Bedroom, beside the bed", tone: "person", motion: "found-breathe", Icon: User },
  { title: "Person, waving", where: "Living room, by the wall", tone: "person", motion: "found-wave", Icon: Hand },
  { title: "Gas tank", where: "Kitchen, keep clear", tone: "hazard", motion: "found-blink", Icon: TriangleAlert },
];

const BEATS = [
  { Icon: Eye, title: "See everyone at once.", body: "Every person and every danger in the building, on one map." },
  { Icon: ListOrdered, title: "Choose who to reach first.", body: "Your crew sets the order. The swarm keeps the picture current." },
  { Icon: Shield, title: "Go in knowing what's there.", body: "Fewer surprises behind closed doors." },
];

/**
 * The why: rescuers spend their time saving people, and decide who needs
 * them first. The found list fills in on its own when the section appears.
 */
export function Pitch() {
  const { ref, progress } = usePlayOnView<HTMLElement>(3600);
  const found = FOUND.filter((_, i) => progress > 0.15 + i * 0.22).length;
  const done = progress >= 1;

  return (
    <section ref={ref} className="flex flex-col gap-16 px-4 py-24 md:px-[100px] md:py-32">
      <div className="flex flex-col gap-12 md:flex-row md:items-center md:gap-16">
        <div className="flex flex-1 flex-col gap-6">
          <h2 className="text-[40px] leading-[1.02] font-bold tracking-[-0.04em] md:text-[64px]">
            Spend your minutes saving people.
            <br />
            <span className="text-orange">Not searching for them.</span>
          </h2>
          <p className="max-w-[560px] text-lg leading-8 text-muted md:text-xl md:leading-[32px]">
            The swarm finds the people and the dangers in a building at the same time, so your crew can decide who to reach first and go straight there.
          </p>
        </div>
        <div className="relative flex w-full max-w-[480px] flex-col gap-3 overflow-hidden rounded-3xl bg-panel p-4 shadow-[0_0_0_1px_var(--color-line-strong),0_24px_60px_rgb(0_0_0/0.12)] md:p-5">
          {progress > 0 && progress < 0.95 && <span aria-hidden className="found-scan pointer-events-none absolute inset-x-0 h-16 bg-linear-to-b from-transparent via-orange/15 to-transparent" />}
          <div className="flex items-center gap-2.5">
            <span className="text-base font-semibold">Found so far</span>
            <span className="flex h-6 items-center gap-1.5 rounded-full bg-white px-2.5 text-xs font-semibold shadow-[inset_0_0_0_1px_var(--color-line)]">
              <span className={cn("size-1.5 rounded-full", done ? "bg-ok" : "found-blink bg-orange")} />
              {done ? "Search complete" : "Searching"}
            </span>
            <span className="flex-1" />
            <span className="font-mono text-2xl leading-none font-semibold tabular-nums">{found}</span>
          </div>
          {FOUND.map((f, i) => {
            const on = progress > 0.15 + i * 0.22;
            return (
              <div
                key={f.title}
                className={cn(
                  "relative flex items-center gap-4 overflow-hidden rounded-2xl bg-white px-4 py-4 shadow-[0_0_0_1px_var(--color-line),0_8px_20px_rgb(0_0_0/0.06)] transition-[opacity,transform,filter] duration-500 ease-out",
                  on ? "translate-x-0 scale-100 opacity-100 blur-0" : "translate-x-8 scale-95 opacity-0 blur-[2px]",
                )}
              >
                {on && <span aria-hidden className="found-sweep pointer-events-none absolute inset-y-0 left-0 w-1/3 -skew-x-12 bg-linear-to-r from-transparent via-orange/20 to-transparent" />}
                <span className="w-6 text-center font-mono text-sm font-semibold text-faint">{i + 1}</span>
                <span className="relative flex size-11 shrink-0 items-center justify-center">
                  {on && <span aria-hidden className={cn("found-ping absolute inset-0 rounded-xl", f.tone === "person" ? "bg-person" : "bg-hazard")} />}
                  <span className={cn("relative flex size-11 items-center justify-center rounded-xl text-white [&_svg]:size-5", f.tone === "person" ? "bg-person" : "bg-hazard")}>
                    <f.Icon className={on ? f.motion : undefined} />
                  </span>
                </span>
                <span className="flex flex-1 flex-col">
                  <span className="text-lg font-semibold">{f.title}</span>
                  <span className="text-sm text-muted">{f.where}</span>
                </span>
              </div>
            );
          })}
          <div className="flex flex-col gap-1.5 pt-1">
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-orange" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <div className="flex items-center text-xs text-muted">
              <span>Building covered</span>
              <span className="flex-1" />
              <span className="font-mono tabular-nums">{Math.round(progress * 100)}%</span>
            </div>
          </div>
          <span className={cn("text-sm font-semibold text-orange-edge transition-[opacity,transform] duration-500", done ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0")}>
            Your crew picks the order.
          </span>
        </div>
      </div>
      <div className="grid gap-8 md:grid-cols-3">
        {BEATS.map((b) => (
          <div key={b.title} className="flex flex-col gap-3 border-t-2 border-ink pt-5">
            <b.Icon className="size-6 text-orange" />
            <h3 className="text-xl font-semibold">{b.title}</h3>
            <p className="text-base leading-6 text-muted">{b.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
