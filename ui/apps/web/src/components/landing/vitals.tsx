import { cn } from "@swarm/ui/lib/utils";
import { lazy, Suspense, useEffect, useState } from "react";

import { range, useScrollProgress } from "./use-scroll-progress";
import { yawFor } from "./vitals-geometry";

const VitalsScene = lazy(() => import("./vitals-scene").then((m) => ({ default: m.VitalsScene })));

type Box = [number, number, number, number]; // left, top, width, height in %

const PEOPLE: {
  label: string;
  frame: string;
  face?: Box;
  chest: Box;
  breathing: { value: number | null; conf: number };
  pulse: { value: number | null; conf: number };
  outcome: string;
  tone: "ok" | "partial";
}[] = [
  {
    label: "Lying on the floor",
    frame: "/assets/person-lying.png",
    face: [72, 66, 9, 13],
    chest: [33, 64, 30, 18],
    breathing: { value: 26, conf: 0.82 },
    pulse: { value: 118, conf: 0.71 },
    outcome: "Readings and location sent to the crew.",
    tone: "ok",
  },
  {
    label: "Sitting against a wall",
    frame: "/assets/person-sitting.png",
    face: [40, 25, 10, 15],
    chest: [38, 39, 15, 22],
    breathing: { value: 20, conf: 0.86 },
    pulse: { value: 96, conf: 0.78 },
    outcome: "Readings and location sent to the crew.",
    tone: "ok",
  },
  {
    label: "Partly under debris",
    frame: "/assets/person-debris.png",
    chest: [26, 69, 30, 14],
    breathing: { value: 14, conf: 0.41 },
    pulse: { value: null, conf: 0 },
    outcome: "Face not visible, so no pulse. The crew is told what is missing, not shown a guess.",
    tone: "partial",
  },
];

/**
 * Pinned scene: a 3D drone turns to each person in turn, and the panel shows
 * what its camera sees and what Presage reads from it. Example output only.
 */
export function Vitals() {
  const { ref, progress } = useScrollProgress<HTMLElement>();
  const seg = Math.min(PEOPLE.length - 1e-6, progress * PEOPLE.length);
  const k = Math.floor(seg);
  const local = seg - k;
  const turn = range(local, 0.72, 1);
  const yaw = k < PEOPLE.length - 1 ? lerpAngle(yawFor(k), yawFor(k + 1), turn * turn * (3 - 2 * turn)) : yawFor(k);
  const lock = range(local, 0.06, 0.2) * (1 - range(local, 0.7, 0.8));
  const read = range(local, 0.18, 0.5);
  const person = PEOPLE[k]!;
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <section id="vitals" ref={ref} className="relative h-[420vh] bg-map">
      <div className="sticky top-[68px] flex h-[calc(100svh-68px)] flex-col gap-6 px-4 py-8 md:px-16 md:py-10">
        <div className="flex flex-col items-center gap-2 text-center">
          <h2 className="text-[32px] leading-[1.05] font-bold tracking-[-0.035em] md:text-[52px]">It checks on people, too.</h2>
          <p className="max-w-[760px] text-base text-muted md:text-lg">
            When a drone finds someone, it holds still and uses Presage to estimate breathing and pulse from the camera. Estimates, not a diagnosis.
          </p>
        </div>
        <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[1.15fr_1fr]">
          <div className="relative min-h-[260px] overflow-hidden rounded-[20px] bg-[#f4f4f3] shadow-[0_0_0_1px_var(--color-line)]">
            {mounted && (
              <Suspense fallback={null}>
                <VitalsScene yaw={yaw} focus={k} lock={lock} />
              </Suspense>
            )}
            <div className="absolute top-3 left-3 flex gap-1.5">
              {PEOPLE.map((p, i) => (
                <span
                  key={p.label}
                  className={cn(
                    "rounded-full px-2.5 py-1 text-xs font-semibold transition-colors",
                    i === k ? "bg-orange text-white" : "bg-white text-muted shadow-[0_0_0_1px_var(--color-line)]",
                  )}
                >
                  {p.label}
                </span>
              ))}
            </div>
          </div>
          <div className="flex min-h-0 flex-col gap-4">
            <div className="relative aspect-[16/10] overflow-hidden rounded-[16px] bg-[#222] shadow-[0_0_0_1px_var(--color-line)]">
              {PEOPLE.map((p, i) => (
                <img
                  key={p.frame}
                  src={p.frame}
                  alt={i === k ? `Drone camera view: person ${p.label.toLowerCase()}` : ""}
                  className="absolute inset-0 size-full object-cover transition-opacity duration-500"
                  style={{ opacity: i === k ? 1 : 0 }}
                />
              ))}
              <span className="absolute top-2.5 left-2.5 flex items-center gap-1.5 rounded bg-black/60 px-2 py-0.5 font-mono text-[11px] text-white">
                <span className="size-1.5 rounded-full bg-[#ff3b2e]" />
                D2 camera, holding still
              </span>
              {person.face && <Roi box={person.face} label="face" on={read > 0.05} />}
              <Roi box={person.chest} label="chest motion" on={read > 0.2} />
            </div>
            <div className="flex flex-col gap-3.5 rounded-[16px] bg-white p-4 shadow-[0_0_0_1px_var(--color-line)] md:p-5">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">Presage reading</span>
                <span className="rounded bg-panel px-1.5 py-0.5 text-[11px] font-medium text-muted">Example output</span>
                <div className="flex-1" />
                <span className="text-xs text-muted">{read < 1 ? "Reading…" : "Done"}</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Reading label="Breathing" unit="/min" value={person.breathing.value} conf={person.breathing.conf} k={read} />
                <Reading label="Pulse" unit="bpm" value={person.pulse.value} conf={person.pulse.conf} k={read} />
              </div>
              <div
                className={cn(
                  "flex items-start gap-2 rounded-[10px] px-3 py-2.5 text-sm transition-opacity duration-300",
                  person.tone === "ok" ? "bg-orange-tint font-medium" : "bg-[#fff8e6] font-medium",
                  read >= 0.95 ? "opacity-100" : "opacity-0",
                )}
              >
                <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", person.tone === "ok" ? "bg-orange" : "bg-hazard")} />
                {person.outcome}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Roi({ box, label, on }: { box: Box; label: string; on: boolean }) {
  return (
    <div
      className="absolute border-2 border-[#ff3b2e] transition-[opacity,transform] duration-300"
      style={{ left: `${box[0]}%`, top: `${box[1]}%`, width: `${box[2]}%`, height: `${box[3]}%`, opacity: on ? 1 : 0, transform: on ? "scale(1)" : "scale(1.3)" }}
    >
      <span className="absolute -top-[19px] -left-0.5 bg-[#ff3b2e] px-1.5 font-mono text-[10px] font-semibold whitespace-nowrap text-white">{label}</span>
    </div>
  );
}

function Reading({ label, unit, value, conf, k }: { label: string; unit: string; value: number | null; conf: number; k: number }) {
  const shown = value === null ? null : Math.round(value * Math.min(1, k * 1.15));
  const confShown = conf * Math.min(1, k * 1.15);
  return (
    <div className="flex flex-col gap-1.5 rounded-[10px] bg-panel px-3.5 py-3">
      <span className="text-xs text-muted">{label}</span>
      <span className="flex items-baseline gap-1">
        <span className="font-mono text-[30px] leading-none font-semibold tabular-nums">{shown === null ? "—" : shown}</span>
        <span className="text-xs text-muted">{shown === null ? "no reading" : unit}</span>
      </span>
      <span className="flex items-center gap-2">
        <span className="h-1 flex-1 rounded-full bg-[#e3e3e0]">
          <span className={cn("block h-1 rounded-full", conf < 0.5 ? "bg-hazard" : "bg-ink")} style={{ width: `${confShown * 100}%` }} />
        </span>
        <span className="w-16 text-right font-mono text-[11px] text-muted">{value === null ? "—" : `conf ${confShown.toFixed(2)}`}</span>
      </span>
    </div>
  );
}

function lerpAngle(a: number, b: number, k: number) {
  let d = b - a;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return a + d * k;
}
