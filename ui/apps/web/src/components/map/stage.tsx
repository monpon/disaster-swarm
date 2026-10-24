import { cn } from "@swarm/ui/lib/utils";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * Fixed-size drawing surface scaled to fit its container. Rendered scans and
 * plans carry pixel-space overlays, so the whole stage scales as one piece
 * instead of re-projecting every marker. Pass `content` (x, y, w, h in stage
 * pixels) to fit and center on just that region instead of the full stage.
 */
export function Stage({
  width,
  height,
  children,
  className,
  fit = "contain",
  content,
}: {
  width: number;
  height: number;
  children: ReactNode;
  className?: string;
  fit?: "contain" | "cover";
  content?: [number, number, number, number];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [cx, cy, cw, ch] = content ?? [0, 0, width, height];

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const sx = el.clientWidth / cw;
      const sy = el.clientHeight / ch;
      setScale(fit === "contain" ? Math.min(sx, sy) : Math.max(sx, sy));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [cw, ch, fit]);

  // Shift so the content box's center lands on the container's center.
  const dx = width / 2 - (cx + cw / 2);
  const dy = height / 2 - (cy + ch / 2);

  return (
    <div ref={ref} className={cn("absolute inset-0 overflow-hidden", className)}>
      <div
        className="absolute top-1/2 left-1/2"
        style={{ width, height, transform: `translate(-50%, -50%) scale(${scale}) translate(${dx}px, ${dy}px)` }}
      >
        {children}
      </div>
    </div>
  );
}
