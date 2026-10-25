import { cn } from "@swarm/ui/lib/utils";
import { Eye, ListOrdered, Shield, TriangleAlert, User } from "lucide-react";
import type { ComponentType } from "react";

import { usePlayOnView } from "./use-scroll-progress";

const FOUND: { title: string; where: string; tone: "person" | "hazard"; Icon: ComponentType<{ className?: string }> }[] = [
  { title: "Person, not moving", where: "Bedroom, beside the bed", tone: "person", Icon: User },
  { title: "Person, waving", where: "Living room, by the wall", tone: "person", Icon: User },
  { title: "Gas tank", where: "Kitchen, keep clear", tone: "hazard", Icon: TriangleAlert },
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
  const { ref, progress } = usePlayOnView<HTMLElement>(2600);

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
        <div className="flex w-full max-w-[460px] flex-col gap-3">
          <span className="text-sm font-semibold text-muted">Found so far</span>
          {FOUND.map((f, i) => {
            const on = progress > 0.15 + i * 0.22;
            return (
              <div
                key={f.title}
                className={cn(
                  "flex items-center gap-4 rounded-2xl bg-white px-4 py-3.5 shadow-[0_0_0_1px_var(--color-line),0_8px_20px_rgb(0_0_0/0.06)] transition-[opacity,transform] duration-500",
                  on ? "translate-x-0 opacity-100" : "translate-x-6 opacity-0",
                )}
              >
                <span className="w-6 text-center font-mono text-sm font-semibold text-faint">{i + 1}</span>
                <span className={cn("flex size-10 items-center justify-center rounded-xl text-white [&_svg]:size-5", f.tone === "person" ? "bg-person" : "bg-hazard")}>
                  <f.Icon />
                </span>
                <span className="flex flex-1 flex-col">
                  <span className="text-base font-semibold">{f.title}</span>
                  <span className="text-sm text-muted">{f.where}</span>
                </span>
              </div>
            );
          })}
          <span className={cn("pt-1 text-sm font-medium text-orange-edge transition-opacity duration-500", progress >= 1 ? "opacity-100" : "opacity-0")}>
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
