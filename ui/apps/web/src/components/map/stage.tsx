import { cn } from "@swarm/ui/lib/utils";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * Fixed-size drawing surface scaled to fit its container. Rendered scans and
 * plans carry pixel-space overlays, so the whole stage scales as one piece
 * instead of re-projecting every marker.
 */
export function Stage({
  width,
  height,
  children,
  className,
  fit = "contain",
}: {
  width: number;
  height: number;
  children: ReactNode;
  className?: string;
  fit?: "contain" | "cover";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const sx = el.clientWidth / width;
      const sy = el.clientHeight / height;
      setScale(fit === "contain" ? Math.min(sx, sy) : Math.max(sx, sy));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [width, height, fit]);

  return (
    <div ref={ref} className={cn("absolute inset-0 overflow-hidden", className)}>
      <div
        className="absolute top-1/2 left-1/2"
        style={{ width, height, transform: `translate(-50%, -50%) scale(${scale})` }}
      >
        {children}
      </div>
    </div>
  );
}
