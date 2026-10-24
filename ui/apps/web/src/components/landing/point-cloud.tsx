import { useEffect, useRef, type ReactNode } from "react";

import { Stage } from "../map/stage";
import { pathsFor, positionAt, seenCount, type Mode, type Story } from "./story";

const W = 1019;
const H = 636;
const DPR = 2;
const BIN_COLORS = ["#b8b8b3", "#8a8a86", "#5c5c59", "#282826"];
/** How long (normalized time) a freshly seen point glows orange. */
const FRESH = 0.018;

/**
 * The house as the drones see it at time t: points appear when first seen,
 * glowing orange briefly, with each drone's trail and position on top.
 * Children render in the same 1019x636 pixel space (pins, labels).
 */
export function PointCloud({
  story,
  mode,
  t,
  trails = true,
  drones = true,
  className,
  fit = "contain",
  children,
}: {
  story: Story | null;
  mode: Mode;
  t: number;
  trails?: boolean;
  drones?: boolean;
  className?: string;
  /** "cover" crops the empty margin around the house to zoom in. */
  fit?: "contain" | "cover";
  children?: ReactNode;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx || !story) return;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const order = story.order[mode];
    const seen = story.seen[mode];
    const n = seenCount(story, mode, t);
    const size = 1.6;
    for (let b = 0; b < BIN_COLORS.length; b++) {
      ctx.fillStyle = BIN_COLORS[b]!;
      for (let k = 0; k < n; k++) {
        const i = order[k]!;
        if (story.bin[i] !== b || t - seen[i]! < FRESH) continue;
        ctx.fillRect(story.x[i]! - size / 2, story.y[i]! - size / 2, size, size);
      }
    }
    for (let k = n - 1; k >= 0; k--) {
      const i = order[k]!;
      const age = t - seen[i]!;
      if (age >= FRESH) break;
      ctx.fillStyle = `rgba(255, 90, 31, ${0.35 + 0.65 * (1 - age / FRESH)})`;
      ctx.fillRect(story.x[i]! - 1.1, story.y[i]! - 1.1, 2.2, 2.2);
    }

    const paths = pathsFor(story, mode);
    if (trails) {
      ctx.strokeStyle = "rgba(255, 90, 31, 0.75)";
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      for (const path of paths) {
        const { trail } = positionAt(path, t);
        ctx.beginPath();
        trail.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
        ctx.stroke();
      }
    }
    if (drones) {
      for (const path of paths) {
        const { x, y } = positionAt(path, t);
        ctx.fillStyle = "rgba(255, 90, 31, 0.18)";
        ctx.beginPath();
        ctx.arc(x, y, 16, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.beginPath();
        ctx.arc(x, y, 9.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#ff5a1f";
        ctx.beginPath();
        ctx.arc(x, y, 6.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, [story, mode, t, trails, drones]);

  return (
    <Stage width={W} height={H} className={className} fit={fit}>
      <canvas ref={canvas} width={W * DPR} height={H * DPR} style={{ width: W, height: H }} className="absolute inset-0" aria-hidden />
      {children}
    </Stage>
  );
}
