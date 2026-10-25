import { Button } from "@swarm/ui/components/button";
import { Checkbox } from "@swarm/ui/components/checkbox";
import { Switch } from "@swarm/ui/components/switch";
import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute } from "@tanstack/react-router";
import { Cpu } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Select, Slider } from "@/components/form";
import { reviewOptions, setDetection, useDetection, type DetectionClass } from "@/lib/detection";

export const Route = createFileRoute("/_app/settings/detection")({
  head: () => ({ meta: [{ title: "Settings: detection" }] }),
  component: DetectionSettings,
});

function DetectionSettings() {
  // Saved settings are shared with the voice agent; this page edits a draft of them.
  const saved = useDetection();
  const [classes, setClasses] = useState<DetectionClass[]>(saved.classes);
  const [vitals, setVitals] = useState(saved.vitals);
  const [review, setReview] = useState(saved.review);
  const update = (id: string, patch: Partial<DetectionClass>) => setClasses((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const dirty = useMemo(() => {
    let n = classes.filter((c, i) => JSON.stringify(c) !== JSON.stringify(saved.classes[i])).length;
    if (vitals !== saved.vitals) n++;
    if (review !== saved.review) n++;
    return n;
  }, [classes, vitals, review, saved]);

  const discard = () => {
    setClasses(saved.classes);
    setVitals(saved.vitals);
    setReview(saved.review);
  };
  // Saved settings change under the page when they load from storage or the voice agent changes them.
  useEffect(discard, [saved]);

  return (
    <>
      <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-8 py-6">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]">Detection</h1>
          <p className="text-[13px] text-muted">What the swarm looks for, and when it tells the crew.</p>
        </div>
        <div className="pane flex items-center gap-3.5 px-4 py-3.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-panel shadow-[inset_0_0_0_1px_var(--color-line)]">
            <Cpu className="size-[18px]" strokeWidth={1.6} />
          </span>
          <div className="flex flex-1 flex-col gap-px">
            <span className="text-sm font-semibold">Indoor search model v3</span>
            <span className="text-[13px] text-muted">Runs on the edge server. 22 ms per frame at 4 streams.</span>
          </div>
          <Button>Change model</Button>
        </div>
        <div className="pane flex flex-col overflow-hidden">
          <div className="flex h-9 items-center gap-4 border-b border-line bg-panel px-4 text-xs font-medium text-muted">
            <span className="w-10">On</span>
            <span className="flex-1">Class</span>
            <span className="w-60">Minimum confidence</span>
            <span className="w-[120px]">Speak to crew</span>
          </div>
          {classes.map((c, i) => (
            <div key={c.id} className={cn("flex h-[52px] items-center gap-4 px-4", i < classes.length - 1 && "border-b border-line-soft")}>
              <span className="w-10">
                <Switch size="sm" checked={c.enabled} onCheckedChange={(v) => update(c.id, { enabled: v })} label={`Detect ${c.label}`} />
              </span>
              <span className="flex flex-1 items-center gap-2.5">
                <span className="size-[22px] rounded-md" style={{ background: c.enabled ? c.color : "#c6c6c2" }} />
                <span className={cn("text-sm font-medium", !c.enabled && "text-faint")}>{c.label}</span>
              </span>
              <span className="flex w-60 items-center gap-3">
                <Slider label={`${c.label} minimum confidence`} value={c.threshold} disabled={!c.enabled} onChange={(v) => update(c.id, { threshold: v })} />
                <span className={cn("w-9 text-right font-mono text-[13px]", !c.enabled && "text-faint")}>{c.threshold.toFixed(2)}</span>
              </span>
              <span className="flex w-[120px] items-center gap-2">
                <Checkbox checked={c.speak} onCheckedChange={(v) => update(c.id, { speak: v })} label={`Speak ${c.label} to crew`} />
                <span className={cn("text-[13px]", !c.enabled && "text-faint")}>{c.speak ? "Immediately" : "On request"}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="flex gap-4">
          <div className="pane flex flex-1 flex-col gap-2.5 p-4">
            <div className="flex items-center gap-3">
              <span className="flex-1 text-sm font-semibold">Camera vitals</span>
              <Switch checked={vitals} onCheckedChange={setVitals} label="Camera vitals" />
            </div>
            <p className="text-[13px] leading-[19px] text-muted">
              Estimate breathing and pulse when a drone holds on a person. Needs visible skin and light. Readings are estimates, not a medical assessment.
            </p>
            <div className="flex items-center gap-3 pt-1 text-[13px]">
              <span className="flex-1">Hold time before reading</span>
              <span className="font-mono">8 s</span>
            </div>
          </div>
          <div className="pane flex flex-1 flex-col gap-2.5 p-4">
            <span className="text-sm font-semibold">Human review</span>
            <p className="text-[13px] leading-[19px] text-muted">Low-confidence findings wait for the incident commander before they reach the crew.</p>
            <div className="flex items-center gap-3 pt-1 text-[13px]">
              <span className="flex-1">Review below</span>
              <Select label="Review threshold" mono value={review} onChange={setReview} options={reviewOptions} className="w-20" />
            </div>
          </div>
        </div>
      </div>
      <div className="flex h-16 shrink-0 items-center gap-2.5 border-t border-line bg-white px-8">
        {dirty > 0 && <span className="size-2 rounded-full bg-orange" />}
        <span className="flex-1 text-[13px] text-muted">
          {dirty > 0 ? `${dirty} unsaved ${dirty === 1 ? "change" : "changes"}. Applies to the running search.` : "All changes saved."}
        </span>
        <Button onClick={discard} disabled={dirty === 0}>
          Discard
        </Button>
        <Button variant="primary" disabled={dirty === 0} onClick={() => setDetection({ classes, vitals, review })}>
          Save changes
        </Button>
      </div>
    </>
  );
}
