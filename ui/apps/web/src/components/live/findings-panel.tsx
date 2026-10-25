import { Button } from "@swarm/ui/components/button";
import { cn } from "@swarm/ui/lib/utils";
import { CornerUpRight } from "lucide-react";
import { useState } from "react";

import { useConsole } from "@/lib/console";
import { vitals as demoVitals } from "@/lib/mock";
import { scanOf, type LiveFinding as Finding } from "@/lib/swarm";

import { FindingIcon } from "../icons";
import { FeedCanvas } from "./feed-canvas";

type Tab = "findings" | "drones" | "log";

function Tabs({ tab, onChange, counts }: { tab: Tab; onChange: (tab: Tab) => void; counts: { findings: number; drones: number } }) {
  const items: { id: Tab; label: string; count?: number }[] = [
    { id: "findings", label: "Findings", count: counts.findings },
    { id: "drones", label: "Drones", count: counts.drones },
    { id: "log", label: "Log" },
  ];
  return (
    <div role="tablist" className="flex h-11 shrink-0 items-end gap-5 border-b border-line px-4">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={tab === item.id}
          onClick={() => onChange(item.id)}
          className={cn(
            "flex h-11 items-center gap-1.5 border-b-2 text-sm",
            tab === item.id ? "border-orange font-semibold text-ink" : "border-transparent font-medium text-muted hover:text-ink",
          )}
        >
          {item.label}
          {item.count !== undefined && <span className="font-mono text-xs font-normal text-muted">{item.count}</span>}
        </button>
      ))}
    </div>
  );
}

function ExpandedPerson({ finding }: { finding: Finding }) {
  const c = useConsole();
  const [reached, setReached] = useState(false);
  const live = c.live;
  const vitals = live ? { breathing: finding.vitals?.rr ?? 0, pulse: finding.vitals?.hr ?? 0, movement: finding.tier ? finding.tier.toLowerCase() : "assessing", seenAt: c.mission.elapsed } : demoVitals;
  const frame = live && finding.drone != null ? c.raw.feeds[finding.drone] : undefined;
  return (
    <div className="flex flex-col gap-3.5 border-b border-[#f3d9cc] bg-[#fff7f3] px-4 pt-3.5 pb-4 shadow-[inset_3px_0_0_var(--color-person)]">
      <div className="flex items-start gap-3">
        <FindingIcon kind="person" size="lg" />
        <div className="flex flex-1 flex-col gap-0.5">
          <span className="text-base font-semibold">{finding.title}</span>
          <span className="text-[13px] text-muted">{finding.detail}</span>
        </div>
        <span className="font-mono text-xs font-medium">{Math.round((finding.confidence ?? 0) * 100)}%</span>
      </div>
      {live ? (
        frame && (
          <div className="relative h-[132px] overflow-hidden rounded-lg bg-[#222]">
            <FeedCanvas drone={finding.drone!} className="size-full object-cover" />
            <span className="absolute right-2 bottom-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[11px] text-white">live</span>
          </div>
        )
      ) : (
        <div className="relative h-[132px] overflow-hidden rounded-lg bg-[#222]">
          <img src="/assets/f2.png" alt="Snapshot of the person from D2" className="absolute top-[-200px] left-[-30px] h-[338px] w-[600px] max-w-none" />
          <div className="absolute top-[30px] left-[38px] h-[78px] w-[272px] border-2 border-[#FF3B2E]" />
          <span className="absolute right-2 bottom-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[11px] text-white">{vitals.seenAt}</span>
        </div>
      )}
      <div className="flex gap-6">
        <Vital label="Breathing" value={vitals.breathing} unit="/min" />
        <Vital label="Pulse" value={vitals.pulse} unit="bpm" />
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-muted">{live ? "Triage" : "Movement"}</span>
          <span className="pt-1 text-[15px] font-semibold">{vitals.movement}</span>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="primary" className="flex-1">
          <CornerUpRight />
          Send route to crew
        </Button>
        <Button onClick={() => setReached((r) => !r)}>{reached ? "Reached" : "Mark reached"}</Button>
      </div>
    </div>
  );
}

function Vital({ label, value, unit }: { label: string; value: number; unit: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted">{label}</span>
      <span className="flex items-baseline gap-1">
        <span className="font-mono text-[22px] font-semibold">{value}</span>
        <span className="text-xs text-muted">{unit}</span>
      </span>
    </div>
  );
}

function FindingRow({ finding, onSelect }: { finding: Finding; onSelect: () => void }) {
  return (
    <button type="button" onClick={onSelect} className="flex w-full items-center gap-3 border-b border-line-soft px-4 py-2.5 text-left hover:bg-panel-2">
      <FindingIcon kind={finding.kind} />
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="text-sm font-medium">{finding.title}</span>
        <span className="text-xs text-muted">{finding.detail}</span>
      </span>
      <span className="w-10 shrink-0 text-right font-mono text-xs text-muted">
        {finding.confidence !== null ? `${Math.round(finding.confidence * 100)}%` : ""}
      </span>
    </button>
  );
}

function DroneRows() {
  const c = useConsole();
  return (
    <div className="flex flex-col">
      {c.live && c.raw.real && (
        <div className="flex h-12 items-center gap-3 border-b border-line-soft bg-door/10 px-4">
          <span className={cn("size-2 rounded-full", c.raw.real.fresh ? "bg-ok" : "bg-line-strong")} />
          <span className="font-mono text-[13px] font-semibold">REAL</span>
          <span className="flex-1 text-[13px]">E58 via relay · {c.raw.real.fresh ? (c.raw.real.control?.state ?? "watching") : "offline"}</span>
          <span className="font-mono text-xs text-muted">{Math.round(c.raw.real.imu?.hz ?? 0)} Hz</span>
        </div>
      )}
      {c.drones.map((d) => (
        <div key={d.id} className="flex h-12 items-center gap-3 border-b border-line-soft px-4">
          <span className={cn("size-2 rounded-full", d.status === "calibrate" ? "bg-hazard" : "bg-ok")} />
          <span className="w-8 font-mono text-[13px] font-semibold">{d.id}</span>
          <span className="flex-1 text-[13px]">{d.room}</span>
          {scanOf(d) != null && <span className="animate-pulse rounded bg-person px-1.5 py-0.5 font-mono text-[11px] font-semibold text-white">scanning #{scanOf(d)}</span>}
          <span className={cn("font-mono text-xs", d.battery < 40 ? "font-semibold text-orange-edge" : "text-muted")}>{d.battery}%</span>
          <span className="w-12 text-right font-mono text-xs text-muted">{d.signal}</span>
        </div>
      ))}
    </div>
  );
}

export function FindingsPanel({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const [tab, setTab] = useState<Tab>("findings");
  const c = useConsole();
  const findings = c.findings;
  return (
    <div className="flex h-full flex-col">
      <Tabs tab={tab} onChange={setTab} counts={{ findings: findings.length, drones: c.drones.length }} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "findings" &&
          findings.map((f) =>
            f.id === selected && f.kind === "person" ? (
              <ExpandedPerson key={f.id} finding={f} />
            ) : (
              <FindingRow key={f.id} finding={f} onSelect={() => onSelect(f.id === selected ? null : f.id)} />
            ),
          )}
        {tab === "drones" && <DroneRows />}
        {tab === "log" &&
          (c.live ? (
            <div className="flex flex-col gap-1.5 p-4">
              {c.messages.map((m) => (
                <p key={m.id} className="text-[13px]"><span className="mr-2 font-mono text-[11px] text-muted">{m.at}</span>{m.text}</p>
              ))}
            </div>
          ) : (
            <p className="p-4 text-[13px] text-muted">Mission log streams here once the edge server is connected.</p>
          ))}
      </div>
    </div>
  );
}
