import { Button } from "@swarm/ui/components/button";
import { Checkbox } from "@swarm/ui/components/checkbox";
import { Segmented } from "@swarm/ui/components/segmented";
import { Switch } from "@swarm/ui/components/switch";
import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowUp, ChevronDown } from "lucide-react";
import { useState } from "react";

import { Row, Section, Select } from "@/components/form";
import { PlanMap } from "@/components/setup/plan-map";
import { ConsoleBody } from "@/components/shell/console-body";
import { TopBar } from "@/components/shell/top-bar";
import { fleet, mission } from "@/lib/mock";

export const Route = createFileRoute("/_app/setup")({
  head: () => ({ meta: [{ title: `Mission setup: ${mission.address}` }] }),
  component: SetupPage,
});

const facts: [string, string, boolean?][] = [
  ["Floors", "2"],
  ["Floor area", "152 m²"],
  ["Construction", "Wood frame, 1962"],
  ["Utilities", "Natural gas", true],
];

function SetupPage() {
  const [building, setBuilding] = useState<"house" | "office" | "apartment">("house");
  const [selected, setSelected] = useState<Record<string, boolean>>({ D1: true, D2: true, D3: true, D4: true });
  const [pattern, setPattern] = useState("Split by room");
  const [returnAt, setReturnAt] = useState("25%");
  const [remap, setRemap] = useState(true);
  const candidates = fleet.slice(0, 4);
  const count = Object.values(selected).filter(Boolean).length;

  return (
    <>
      <TopBar>
        <button type="button" className="flex h-[34px] items-center gap-2 rounded-lg px-2.5 shadow-[inset_0_0_0_1px_var(--color-line)] hover:bg-panel">
          <span className="text-sm font-semibold">{mission.address}</span>
          <span className="text-[13px] text-muted">New mission</span>
          <ChevronDown className="size-3 text-muted" />
        </button>
      </TopBar>
      <ConsoleBody>
        <div className="relative min-w-0 flex-1">
          <PlanMap />
        </div>
        <aside className="flex w-[368px] shrink-0 flex-col border-l border-line-strong bg-white">
          <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-4 py-[18px]">
            <h1 className="text-xl font-semibold tracking-[-0.01em]">Mission setup</h1>
            <Section title="Building">
              <Segmented
                stretch
                value={building}
                onChange={setBuilding}
                options={[
                  { value: "house", label: "House" },
                  { value: "office", label: "Office floor" },
                  { value: "apartment", label: "Apartment" },
                ]}
              />
              <dl className="flex flex-col">
                {facts.map(([k, v, warn], i) => (
                  <div key={k} className={cn("flex h-[30px] items-center", i < facts.length - 1 && "border-b border-line-soft")}>
                    <dt className="flex-1 text-[13px] text-muted">{k}</dt>
                    <dd className={cn("text-[13px]", warn && "font-medium text-orange-edge", k === "Floor area" || k === "Floors" ? "font-mono" : "")}>{v}</dd>
                  </div>
                ))}
              </dl>
            </Section>
            <Section title="Drones" aside={<span className="text-xs text-muted">{count} of 4 ready</span>}>
              <div className="flex flex-col overflow-hidden rounded-lg shadow-[0_0_0_1px_var(--color-line)]">
                {candidates.map((d, i) => (
                  <div key={d.id} className={cn("flex h-[38px] items-center gap-2.5 px-3", i < candidates.length - 1 && "border-b border-line-soft")}>
                    <Checkbox
                      checked={selected[d.id] ?? false}
                      onCheckedChange={(v) => setSelected((s) => ({ ...s, [d.id]: v }))}
                      label={`Include ${d.id}`}
                    />
                    <span className="w-7 font-mono text-[13px] font-semibold">{d.id}</span>
                    <span className="flex-1 truncate text-[13px] text-muted">
                      E58 + Pi 4{d.status === "calibrate" ? ", IMU recal" : ""}
                    </span>
                    <span className="w-11 text-right font-mono text-xs">{d.battery}%</span>
                    <span className={cn("size-2 rounded-full", d.status === "calibrate" ? "bg-hazard" : "bg-ok")} />
                  </div>
                ))}
              </div>
            </Section>
            <Section title="Search">
              <Row label="Pattern">
                <Select label="Search pattern" value={pattern} onChange={setPattern} options={["Split by room", "Frontier first", "Corridors first"]} className="w-[170px]" />
              </Row>
              <Row label="Return at battery">
                <Select label="Return at battery" mono value={returnAt} onChange={setReturnAt} options={["20%", "25%", "30%", "35%"]} className="w-[170px]" />
              </Row>
              <Row label="Keep remapping after crew enters">
                <Switch checked={remap} onCheckedChange={setRemap} label="Keep remapping after crew enters" />
              </Row>
            </Section>
          </div>
          <div className="flex shrink-0 flex-col gap-2.5 border-t border-line-strong bg-panel px-4 pt-3.5 pb-4">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[13px] text-muted">Full coverage in about</span>
              <span className="font-mono text-[13px] font-semibold">3:40</span>
            </div>
            <div className="flex gap-2">
              <Button size="lg">Simulate</Button>
              <Button variant="primary" size="lg" className="flex-1" disabled={count === 0} render={<Link to="/live" />} nativeButton={false}>
                <ArrowUp />
                Launch {count} drones
              </Button>
            </div>
          </div>
        </aside>
      </ConsoleBody>
    </>
  );
}
