import { cn } from "@swarm/ui/lib/utils";
import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

/** Raised native select that matches the secondary button. */
export function Select({
  value,
  onChange,
  options,
  label,
  mono = false,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  label: string;
  mono?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("btn-secondary relative flex h-8 items-center rounded-[7px]", className)}>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn("h-full w-full appearance-none bg-transparent pr-7 pl-2.5 text-[13px] font-medium outline-none", mono && "font-mono font-normal")}
      >
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-3 text-muted" />
    </span>
  );
}

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex items-baseline">
        <h2 className="flex-1 text-[13px] font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Row({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="flex-1 text-[13px] text-muted">{label}</span>
      {children}
    </div>
  );
}

/** Thin slider styled like the design: ink fill on a grey track. */
export function Slider({ value, onChange, disabled, label }: { value: number; onChange: (v: number) => void; disabled?: boolean; label: string }) {
  return (
    <input
      type="range"
      min={0}
      max={1}
      step={0.05}
      value={value}
      disabled={disabled}
      aria-label={label}
      onChange={(e) => onChange(Number(e.target.value))}
      className="slider h-4 flex-1 cursor-pointer appearance-none bg-transparent disabled:cursor-not-allowed"
      style={{ "--fill": `${value * 100}%`, "--tone": disabled ? "#c6c6c2" : "#151515" } as React.CSSProperties}
    />
  );
}
