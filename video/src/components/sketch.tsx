import React from "react";
import rough from "roughjs";
import { continueRender, delayRender, getStaticFiles, Img, OffthreadVideo, staticFile } from "remotion";
import { C, clamp, ease, interpolate } from "./kit";

// Excalidraw look: rough.js strokes plus the Virgil hand-drawn font.
export const HAND = "Virgil";
const fontHandle = delayRender("Virgil font");
const face = new FontFace(HAND, `url(${staticFile("fonts/Virgil-Regular.woff2")})`);
face
  .load()
  .then((f) => {
    (document.fonts as unknown as { add: (f: FontFace) => void }).add(f);
    continueRender(fontHandle);
  })
  .catch(() => continueRender(fontHandle));

const gen = rough.generator();
export const INK = "#1e1e1e";

type Paths = { d: string; stroke: string; strokeWidth: number; fill?: string }[];

function toPaths(drawable: ReturnType<typeof gen.rectangle>): Paths {
  return gen.toPaths(drawable).map((p) => ({ d: p.d, stroke: p.stroke, strokeWidth: p.strokeWidth, fill: p.fill }));
}

/** Draw-on progress for a shape that starts at `at` and takes `dur` seconds. */
export const drawP = (t: number, at: number, dur = 0.6) => interpolate(t, [at, at + dur], [0, 1], { ...clamp, easing: ease });

function Strokes({ paths, p, dashed }: { paths: Paths; p: number; dashed?: boolean }) {
  if (p <= 0) return null;
  return (
    <>
      {paths.map((s, i) =>
        s.fill && s.fill !== "none" ? (
          <path key={i} d={s.d} fill={s.fill} stroke="none" opacity={p} />
        ) : (
          <path
            key={i}
            d={s.d}
            fill="none"
            stroke={s.stroke}
            strokeWidth={s.strokeWidth}
            strokeLinecap="round"
            pathLength={dashed ? undefined : 1}
            strokeDasharray={dashed ? "14 10" : "1 1"}
            strokeDashoffset={dashed ? undefined : 1 - p}
            opacity={dashed ? p : 1}
          />
        ),
      )}
    </>
  );
}

export function Box({
  x,
  y,
  w,
  h,
  t,
  at,
  seed,
  label,
  sub,
  accent,
  fill,
  dashed,
  size = 30,
  children,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  t: number;
  at: number;
  seed: number;
  label?: string;
  sub?: string;
  accent?: boolean;
  fill?: string;
  dashed?: boolean;
  size?: number;
  children?: React.ReactNode;
}) {
  const stroke = accent ? C.orange : INK;
  const paths = React.useMemo(
    () =>
      toPaths(
        gen.rectangle(x, y, w, h, {
          seed,
          roughness: 1.3,
          bowing: 1.2,
          stroke,
          strokeWidth: accent ? 3 : 2.4,
          fill,
          fillStyle: "hachure",
          hachureGap: 9,
          fillWeight: 1.2,
          strokeLineDash: dashed ? [14, 10] : undefined,
        }),
      ),
    [x, y, w, h, seed, stroke, fill, dashed, accent],
  );
  const p = drawP(t, at);
  const tp = drawP(t, at + 0.25, 0.4);
  return (
    <g>
      <Strokes paths={paths} p={p} dashed={dashed} />
      {(label || children) && (
        <foreignObject x={x} y={y} width={w} height={h} opacity={tp}>
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              fontFamily: HAND,
              color: accent ? C.orangeEdge : INK,
              padding: 12,
              boxSizing: "border-box",
              lineHeight: 1.15,
            }}
          >
            {label && <div style={{ fontSize: size }}>{label}</div>}
            {sub && <div style={{ fontSize: size * 0.68, opacity: 0.7, marginTop: 6 }}>{sub}</div>}
            {children}
          </div>
        </foreignObject>
      )}
    </g>
  );
}

/** Hand-drawn arrow along a gentle curve from (x1,y1) to (x2,y2). */
export function Arrow({
  x1,
  y1,
  x2,
  y2,
  t,
  at,
  seed,
  bend = 0,
  label,
  labelDy = -18,
  accent,
  dashed,
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  t: number;
  at: number;
  seed: number;
  bend?: number;
  label?: string;
  labelDy?: number;
  accent?: boolean;
  dashed?: boolean;
}) {
  const stroke = accent ? C.orange : INK;
  const mx = (x1 + x2) / 2 - (y2 - y1) * bend;
  const my = (y1 + y2) / 2 + (x2 - x1) * bend;
  const { body, head } = React.useMemo(() => {
    const opts = { seed, roughness: 1.1, stroke, strokeWidth: 2.6, strokeLineDash: dashed ? [12, 9] : undefined };
    const body = toPaths(gen.curve([[x1, y1], [mx, my], [x2, y2]], opts));
    const ang = Math.atan2(y2 - my, x2 - mx);
    const a1 = ang + Math.PI * 0.84;
    const a2 = ang - Math.PI * 0.84;
    const L = 22;
    const head = toPaths(gen.linearPath([[x2 + Math.cos(a1) * L, y2 + Math.sin(a1) * L], [x2, y2], [x2 + Math.cos(a2) * L, y2 + Math.sin(a2) * L]], { ...opts, strokeLineDash: undefined }));
    return { body, head };
  }, [x1, y1, x2, y2, mx, my, seed, stroke, dashed]);
  const p = drawP(t, at, 0.55);
  const hp = drawP(t, at + 0.45, 0.2);
  return (
    <g>
      <Strokes paths={body} p={p} dashed={dashed} />
      <Strokes paths={head} p={hp} />
      {label && (
        <text x={mx} y={my + labelDy} textAnchor="middle" fontFamily={HAND} fontSize={22} fill={accent ? C.orangeEdge : "#555"} opacity={drawP(t, at + 0.3, 0.4)}>
          {label}
        </text>
      )}
    </g>
  );
}

export function Note({ x, y, t, at, children, size = 24, color = "#555", anchor = "start" }: { x: number; y: number; t: number; at: number; children: string; size?: number; color?: string; anchor?: "start" | "middle" | "end" }) {
  return (
    <text x={x} y={y} fontFamily={HAND} fontSize={size} fill={color} textAnchor={anchor} opacity={drawP(t, at, 0.4)}>
      {children}
    </text>
  );
}

const files = new Set(getStaticFiles().map((f) => f.name));

/**
 * Slot for team media (drone photo, flight video, simulator screenshot).
 * Shows the file from public/team when it exists, else a labelled dashed placeholder.
 */
export function MediaSlot({ x, y, w, h, t, at, seed, file, label }: { x: number; y: number; w: number; h: number; t: number; at: number; seed: number; file: string; label: string }) {
  const path = `team/${file}`;
  const has = files.has(path);
  const p = drawP(t, at, 0.5);
  if (!has) {
    return (
      <Box x={x} y={y} w={w} h={h} t={t} at={at} seed={seed} dashed size={24} label={label} sub={`public/${path}`} fill="rgba(0,0,0,0.035)" />
    );
  }
  const video = /\.(mp4|webm|mov)$/i.test(file);
  return (
    <g opacity={p}>
      <foreignObject x={x} y={y} width={w} height={h}>
        <div style={{ width: "100%", height: "100%", borderRadius: 10, overflow: "hidden", boxShadow: "0 6px 18px rgba(0,0,0,0.15)" }}>
          {video ? (
            <OffthreadVideo src={staticFile(path)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            <Img src={staticFile(path)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          )}
        </div>
      </foreignObject>
      <Box x={x} y={y} w={w} h={h} t={t} at={at} seed={seed} />
    </g>
  );
}
