import { cn } from "@swarm/ui/lib/utils";
import { Ear, Mic } from "lucide-react";

import { range, useScrollProgress } from "./use-scroll-progress";

const LINES: { from: "swarm" | "crew"; text: string }[] = [
  { from: "swarm", text: "Person found in the bedroom. Breathing about 26, pulse about 118." },
  { from: "crew", text: "What's the fastest way to them?" },
  { from: "swarm", text: "Front door, then left. About 7 meters. The gas tank is in the kitchen, not on this route." },
  { from: "crew", text: "Hallway's blocked." },
  { from: "swarm", text: "Got it. Go through the living room instead. The new route is on the map." },
];

const BARS = 36;

/**
 * Pinned scene: the conversation in a rescuer's earpiece plays line by line
 * as the visitor scrolls, with the waveform following whoever is talking.
 */
export function Audio() {
  const { ref, progress } = useScrollProgress<HTMLElement>();
  const pos = range(progress, 0.05, 0.92) * LINES.length;
  const current = Math.min(LINES.length - 1, Math.floor(pos));
  const within = pos - current;
  const speaker = LINES[current]!.from;
  const talking = within < 0.8;

  return (
    <section ref={ref} className="relative h-[300vh] bg-ink text-white">
      <div className="sticky top-[68px] flex h-[calc(100svh-68px)] flex-col justify-center gap-8 px-4 py-10 md:flex-row md:items-center md:gap-16 md:px-16">
        <div className="flex w-full max-w-[460px] flex-col gap-6">
          <div className="flex flex-col gap-3">
            <h2 className="text-[34px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[52px]">Rescuers just listen.</h2>
            <p className="text-base leading-7 text-[#bdbdb8] md:text-lg">
              The swarm talks to the crew through their earpiece. Hands stay free. They can ask questions out loud, and the answer comes from the live map.
            </p>
          </div>
          <div className="flex flex-col gap-4 rounded-[20px] bg-[#232322] p-5 shadow-[0_0_0_1px_#2f2f2e]">
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  "flex size-11 items-center justify-center rounded-full transition-colors",
                  speaker === "swarm" ? "bg-orange text-white" : "bg-white text-ink",
                )}
              >
                {speaker === "swarm" ? <Ear className="size-5" /> : <Mic className="size-5" />}
              </span>
              <span className="flex flex-col">
                <span className="text-sm font-semibold">{speaker === "swarm" ? "Swarm speaking" : "Crew speaking"}</span>
                <span className="text-xs text-[#a3a3a0]">Engine 7 crew channel</span>
              </span>
            </div>
            <div className="flex h-16 items-center gap-[3px]" aria-hidden>
              {Array.from({ length: BARS }, (_, i) => {
                const wave = Math.abs(Math.sin(i * 0.9 + pos * 18) * Math.cos(i * 0.37 - pos * 7));
                const h = talking ? Math.round(10 + wave * 54) : 4;
                return (
                  <span
                    key={i}
                    className={cn("w-full rounded-full transition-[height] duration-100", speaker === "swarm" ? "bg-orange" : "bg-white")}
                    style={{ height: h }}
                  />
                );
              })}
            </div>
          </div>
        </div>
        <ol className="flex w-full max-w-[560px] flex-col gap-3">
          {LINES.map((line, i) => {
            const shown = i < current || (i === current && within > 0.05);
            return (
              <li
                key={line.text}
                className={cn(
                  "flex flex-col gap-1 rounded-2xl px-4 py-3 transition-[opacity,transform] duration-500",
                  line.from === "swarm" ? "mr-8 bg-[#2a2a29]" : "ml-8 bg-white text-ink",
                  shown ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0",
                  i < current && "opacity-60",
                )}
              >
                <span className={cn("text-xs font-semibold", line.from === "swarm" ? "text-[#ff8a5c]" : "text-muted")}>
                  {line.from === "swarm" ? "Swarm" : "Capt. Reyes"}
                </span>
                <span className="text-[15px] leading-[22px] md:text-base">{line.text}</span>
              </li>
            );
          })}
          <li className="pt-1 text-xs text-[#8a8a86]">Example conversation.</li>
        </ol>
      </div>
    </section>
  );
}
