import { cn } from "@swarm/ui/lib/utils";
import { Check } from "lucide-react";

export function Checkbox({
  checked,
  onCheckedChange,
  label,
  className,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex size-4 shrink-0 items-center justify-center rounded outline-none focus-visible:ring-2 focus-visible:ring-orange/40",
        checked ? "bg-orange" : "bg-white shadow-[inset_0_0_0_1.5px_var(--color-line-strong)]",
        className,
      )}
    >
      {checked && <Check className="size-2.5 text-white" strokeWidth={3.5} />}
    </button>
  );
}
