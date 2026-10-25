import { cn } from "@swarm/ui/lib/utils";
import type { ReactNode } from "react";

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
}

/**
 * Segmented control. `tone="dark"` fills the active segment with ink (map
 * toolbars); the default lifts it as a white chip (forms, top bar).
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  tone = "light",
  stretch = false,
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  tone?: "light" | "dark";
  stretch?: boolean;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      className={cn(
        "flex items-center gap-0.5 rounded-lg p-[3px]",
        tone === "dark"
          ? "bg-white shadow-[0_0_0_1px_var(--color-line-strong),0_1px_2px_rgb(0_0_0/0.08)]"
          : "bg-panel shadow-[inset_0_0_0_1px_var(--color-line)]",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "flex h-[26px] items-center justify-center gap-1.5 rounded-[5px] px-2.5 text-xs whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-orange/40",
              stretch && "h-[30px] flex-1 text-[13px]",
              active
                ? tone === "dark"
                  ? "bg-ink font-semibold text-white"
                  : "bg-white font-semibold text-ink shadow-[0_1px_2px_rgb(0_0_0/0.12),0_0_0_1px_rgb(0_0_0/0.06)]"
                : "font-medium text-muted hover:text-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
