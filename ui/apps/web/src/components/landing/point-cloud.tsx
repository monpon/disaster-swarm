import { useEffect, useRef, type ReactNode } from "react";

import { Stage } from "../map/stage";
import { pathsFor, positionAt, seenCount, type Mode, type Story } from "./story";

const W = 1019;
const H = 636;
const DPR = 2;
const BIN_COLORS = ["#b8b8b3", "#8a8a86", "#5c5c59", "#282826"];
/** The house plus drone and pin headroom, in stage pixels. Views fit to this, not the canvas. */
const HOUSE_BOX: [number, number, number, number] = [50, 90, 920, 560];
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
  droneScale = 1,
  children,
}: {
  /** 0..1 pop-in scale for the drone models. */
  droneScale?: number;
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
        drawQuad(ctx, x, y, droneScale, t * 900);
      }
    }
  }, [story, mode, t, trails, drones, droneScale]);

  return (
    <Stage width={W} height={H} className={className} fit={fit} content={fit === "contain" ? HOUSE_BOX : undefined}>
      <canvas ref={canvas} width={W * DPR} height={H * DPR} style={{ width: W, height: H }} className="absolute inset-0" aria-hidden />
      {children}
    </Stage>
  );
}

/**
 * Isometric quadcopter: ground shadow and altitude line, X-frame body, four
 * rotor discs with a blade that turns with the timeline, and a camera nose.
 */
function drawQuad(ctx: CanvasRenderingContext2D, x: number, y: number, scale: number, spin: number) {
  if (scale <= 0.01) return;
  const s = scale * 1.25;
  // Shadow on the floor, roughly 1.2 m below.
  ctx.save();
  ctx.strokeStyle = "rgba(21,21,21,0.35)";
  ctx.setLineDash([2, 3]);
  ctx.beginPath();
  ctx.moveTo(x, y + 6 * s);
  ctx.lineTo(x, y + 44);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = `rgba(21,21,21,${0.18 * scale})`;
  ctx.beginPath();
  ctx.ellipse(x, y + 46, 12 * s, 5 * s, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s, s);
  // Halo so the drone reads against dense points.
  ctx.fillStyle = "rgba(255,90,31,0.16)";
  ctx.beginPath();
  ctx.ellipse(0, 0, 21, 13, 0, 0, Math.PI * 2);
  ctx.fill();
  // Arms on the iso plane (x stretched, y squashed).
  const arms: [number, number][] = [
    [-12, -5],
    [12, -5],
    [-12, 5],
    [12, 5],
  ];
  ctx.strokeStyle = "#151515";
  ctx.lineWidth = 2.6;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(arms[0]![0], arms[0]![1]);
  ctx.lineTo(arms[3]![0], arms[3]![1]);
  ctx.moveTo(arms[1]![0], arms[1]![1]);
  ctx.lineTo(arms[2]![0], arms[2]![1]);
  ctx.stroke();
  for (const [ax, ay] of arms) {
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.strokeStyle = "rgba(21,21,21,0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.ellipse(ax, ay, 7.5, 3.6, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = "#ff5a1f";
    ctx.lineWidth = 1.6;
    const a = (spin * Math.PI) / 180;
    ctx.beginPath();
    ctx.moveTo(ax - Math.cos(a) * 7, ay - Math.sin(a) * 3.4);
    ctx.lineTo(ax + Math.cos(a) * 7, ay + Math.sin(a) * 3.4);
    ctx.stroke();
  }
  // Body and camera.
  ctx.fillStyle = "#ff5a1f";
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.ellipse(0, 0, 6.5, 4, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#151515";
  ctx.beginPath();
  ctx.arc(0, 3, 1.8, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

const PIN_STYLE: Record<string, { bg: string; label: string }> = {
  person: { bg: "#d92d20", label: "Person" },
  blocked: { bg: "#151515", label: "Blocked" },
  gas: { bg: "#d99400", label: "Gas" },
  door: { bg: "#2563eb", label: "Door" },
};

/** Finding pins that rise out of the map once the given search has seen them. */
export function CloudPins({ story, mode, t, labels = false }: { story: Story | null; mode: Mode; t: number; labels?: boolean }) {
  if (!story) return null;
  return (
    <>
      {(Object.keys(story.events) as (keyof Story["events"])[]).map((key) => {
        const e = story.events[key];
        const on = e[mode] <= t;
        const style = PIN_STYLE[key]!;
        const big = key === "person";
        return (
          <span
            key={key}
            className="absolute flex items-center gap-1.5 transition-[opacity,transform] duration-500 ease-out"
            style={{
              left: e.px[0] - 4,
              top: e.px[1] - (big ? 44 : 36),
              opacity: on ? 1 : 0,
              transform: on ? "translateY(0) scale(1)" : "translateY(18px) scale(0.4)",
            }}
          >
            <span
              className="flex items-center justify-center rounded-[16px_16px_16px_3px] text-white shadow-[0_0_0_2.5px_#fff,0_4px_10px_rgb(0_0_0/0.3)]"
              style={{ background: style.bg, width: big ? 36 : 28, height: big ? 36 : 28 }}
            >
              <PinGlyph kind={key} size={big ? 18 : 14} />
            </span>
            {labels && (
              <span className="rounded-md bg-white px-2 py-0.5 text-[13px] font-semibold whitespace-nowrap text-ink shadow-[0_2px_8px_rgb(0_0_0/0.15)]">
                {style.label}
              </span>
            )}
          </span>
        );
      })}
    </>
  );
}

function PinGlyph({ kind, size }: { kind: string; size: number }) {
  const p = { width: size, height: size, viewBox: "0 0 16 16", fill: "none", stroke: "#fff", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (kind === "person")
    return (
      <svg {...p}>
        <circle cx="8" cy="4.6" r="2.4" />
        <path d="M3.4 14c0-3 2.1-5 4.6-5s4.6 2 4.6 5" />
      </svg>
    );
  if (kind === "blocked")
    return (
      <svg {...p} strokeWidth={2.4}>
        <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
      </svg>
    );
  if (kind === "gas")
    return (
      <svg {...p}>
        <path d="M8 2.5 14 13H2Z" />
        <path d="M8 7v2.5" />
      </svg>
    );
  return (
    <svg {...p}>
      <rect x="3.5" y="2" width="9" height="12.5" rx="1" />
    </svg>
  );
}
