import { cn } from "@swarm/ui/lib/utils";
import { DoorClosed, DoorOpen, TriangleAlert, User, X } from "lucide-react";

import type { FindingKind } from "@/lib/mock";

/** Brand mark: orange tile with a white delta. */
export function Mark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex size-[30px] shrink-0 items-center justify-center rounded-[7px] bg-orange shadow-[inset_0_-2px_0_var(--color-orange-edge)]",
        className,
      )}
    >
      <svg viewBox="0 0 16 16" className="size-4 fill-white" aria-hidden>
        <path d="M8 1.5 14.5 13H1.5Z" />
      </svg>
    </span>
  );
}

/** Top-down quadcopter glyph. */
export function Quad({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth={1.4} className={className} aria-hidden>
      <path d="M3.5 3.5l7 7M10.5 3.5l-7 7" />
      <circle cx="3" cy="3" r="2" />
      <circle cx="11" cy="3" r="2" />
      <circle cx="3" cy="11" r="2" />
      <circle cx="11" cy="11" r="2" />
    </svg>
  );
}

export const findingStyle: Record<FindingKind, { bg: string; ring?: string; Icon: typeof User }> = {
  person: { bg: "bg-person", Icon: User },
  door: { bg: "bg-door", Icon: DoorClosed },
  blockage: { bg: "bg-ink", Icon: X },
  hazard: { bg: "bg-hazard", Icon: TriangleAlert },
  opened: { bg: "bg-white", ring: "shadow-[inset_0_0_0_1.5px_var(--color-door)]", Icon: DoorOpen },
};

export function FindingIcon({ kind, size = "md" }: { kind: FindingKind; size?: "md" | "lg" }) {
  const { bg, ring, Icon } = findingStyle[kind];
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center",
        size === "lg" ? "size-8 rounded-lg" : "size-7 rounded-[7px]",
        bg,
        ring,
      )}
    >
      <Icon className={cn(size === "lg" ? "size-4" : "size-3.5", kind === "opened" ? "text-door" : "text-white")} strokeWidth={2.2} />
    </span>
  );
}
