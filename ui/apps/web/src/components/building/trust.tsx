import { cn } from "@swarm/ui/lib/utils";

import { type Attribute, display, type Trust, trustLabel } from "@/lib/building";

const dot: Record<Trust, string> = {
  verified: "bg-ok",
  record: "bg-ink",
  estimated: "bg-hazard",
  unknown: "bg-faint",
};

/** Small marker for how much to trust a value. Title carries the source. */
export function TrustDot({ trust, source, className }: { trust: Trust; source: string; className?: string }) {
  return <span role="img" aria-label={`${trustLabel[trust]}: ${source}`} title={`${trustLabel[trust]}: ${source}`} className={cn("size-1.5 shrink-0 rounded-full", dot[trust], className)} />;
}

/** Label, value, and trust marker on one row. Unknown values read as muted. */
export function AttributeRow({ a, mono = true }: { a: Attribute; mono?: boolean }) {
  const unknown = a.trust === "unknown";
  return (
    <div className="flex min-h-[30px] items-center gap-2 py-1">
      <dt className="flex-1 text-[13px] text-muted">{a.label}</dt>
      <dd className={cn("text-[13px]", mono && !unknown && "font-mono", unknown && "text-faint italic")}>{display(a)}</dd>
      <TrustDot trust={a.trust} source={a.source} />
    </div>
  );
}

export function TrustLegend() {
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
      {(Object.keys(dot) as Trust[]).map((t) => (
        <span key={t} className="flex items-center gap-1">
          <span className={cn("size-1.5 rounded-full", dot[t])} />
          {trustLabel[t]}
        </span>
      ))}
    </p>
  );
}
