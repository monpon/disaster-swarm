import { cn } from "@swarm/ui/lib/utils";

/** Pill toggle. Orange when on. */
export function Switch({
  checked,
  onCheckedChange,
  label,
  size = "md",
  className,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex shrink-0 items-center rounded-full p-0.5 shadow-[inset_0_1px_2px_rgb(0_0_0/0.2)] transition-colors outline-none focus-visible:ring-2 focus-visible:ring-orange/40",
        size === "md" ? "h-[22px] w-[38px]" : "h-5 w-[34px]",
        checked ? "justify-end bg-orange" : "justify-start bg-[#d6d6d2]",
        className,
      )}
    >
      <span
        className={cn(
          "rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.3)]",
          size === "md" ? "size-[18px]" : "size-4",
        )}
      />
    </button>
  );
}
