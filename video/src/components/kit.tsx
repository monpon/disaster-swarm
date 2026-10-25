import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import { Audio } from "@remotion/media";
import { C, mono, sans } from "../theme";

/** Absolute timeline seconds inside a Sequence that started at `start`. */
export function useT(start: number) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return frame / fps + start;
}

export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0→1 over `dur` seconds starting at `at`, eased out. */
export function rise(t: number, at: number, dur = 0.6) {
  return interpolate(t, [at, at + dur], [0, 1], { ...clamp, easing: ease });
}

/** Spring-driven 0→1 starting at `at` (seconds). */
export function useSpringAt(t: number, at: number, damping = 18) {
  const { fps } = useVideoConfig();
  return spring({ frame: Math.round((t - at) * fps), fps, config: { damping, mass: 0.6, stiffness: 140 } });
}

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.233,
        background: C.orange,
        boxShadow: `inset 0 ${-size / 15}px 0 ${C.orangeEdge}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <svg viewBox="0 0 16 16" style={{ width: size * 0.53, height: size * 0.53 }}>
        <path d="M8 1.5 14.5 13H1.5Z" fill="#fff" />
      </svg>
    </div>
  );
}

export function Wordmark({ size = 30, color = C.ink }: { size?: number; color?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: size * 0.33 }}>
      <Mark size={size} />
      <span style={{ fontFamily: sans, fontWeight: 700, fontSize: size * 0.82, letterSpacing: "-0.02em", color }}>Mayfly</span>
    </div>
  );
}

const GRADE = "saturate(0.72) contrast(1.06) brightness(0.82)";

/** Slow push-in on a still photo. */
export function KenBurns({
  src,
  t,
  from,
  to,
  scale = [1.04, 1.14],
  origin = "50% 50%",
  dark = 0,
  grade = true,
}: {
  src: string;
  t: number;
  from: number;
  to: number;
  scale?: [number, number];
  origin?: string;
  dark?: number;
  grade?: boolean;
}) {
  const s = interpolate(t, [from, to], scale, clamp);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${s})`,
          transformOrigin: origin,
          filter: grade ? GRADE : undefined,
        }}
      />
      {dark > 0 && <AbsoluteFill style={{ background: `rgba(0,0,0,${dark})` }} />}
    </AbsoluteFill>
  );
}

/** Graded stock clip with a gentle push so cuts never feel static. */
export function Stock({
  src,
  t,
  from,
  to,
  startFrom = 0,
  rate = 1,
  scale = [1.02, 1.08],
  dark = 0,
  origin = "50% 50%",
}: {
  src: string;
  t: number;
  from: number;
  to: number;
  startFrom?: number;
  rate?: number;
  scale?: [number, number];
  dark?: number;
  origin?: string;
}) {
  const s = interpolate(t, [from, to], scale, clamp);
  return (
    <AbsoluteFill style={{ overflow: "hidden", background: "#000" }}>
      <OffthreadVideo
        src={staticFile(src)}
        muted
        playbackRate={rate}
        startFrom={Math.round(startFrom * 30)}
        style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${s})`, transformOrigin: origin, filter: GRADE }}
      />
      {dark > 0 && <AbsoluteFill style={{ background: `rgba(0,0,0,${dark})` }} />}
    </AbsoluteFill>
  );
}

export function Vignette({ strength = 0.55 }: { strength?: number }) {
  return (
    <AbsoluteFill
      style={{ background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,${strength}) 100%)`, pointerEvents: "none" }}
    />
  );
}

/** Plays a sound effect from public/sfx at absolute time `at`. */
export function Sfx({ src, at, start, volume = 0.5 }: { src: string; at: number; start: number; volume?: number }) {
  const { fps } = useVideoConfig();
  return (
    <Sequence from={Math.round((at - start) * fps)} layout="none">
      <Audio src={staticFile(`sfx/${src}`)} volume={volume} />
    </Sequence>
  );
}

/** Logo rendered as a single flat colour so mixed brand assets sit together. */
export function Logo({ src, height = 26, color = "white" }: { src: string; height?: number; color?: "white" | "ink" | "native" }) {
  const filter = color === "white" ? "brightness(0) invert(1)" : color === "ink" ? "brightness(0) saturate(100%)" : undefined;
  return <Img src={staticFile(`stock/logos/${src}`)} style={{ height, width: "auto", filter, opacity: color === "ink" ? 0.86 : 1 }} />;
}

export type BulletItem = {
  at: number;
  label: string;
  /** Logos that slide in nested under the bullet, each with a tone. */
  logos?: { src: string; at: number; height?: number; native?: boolean }[];
  mark?: "x" | "check" | "dot";
};

/** Terse feature bullets; logos slide in underneath with a soft tone. */
export function Bullets({
  items,
  t,
  start,
  dark = false,
  size = 40,
  gap = 34,
}: {
  items: BulletItem[];
  t: number;
  start: number;
  dark?: boolean;
  size?: number;
  gap?: number;
}) {
  const fg = dark ? C.white : C.ink;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap }}>
      {items.map((it) => {
        const p = rise(t, it.at, 0.55);
        const markColor = it.mark === "x" ? "#ff6b4a" : C.orange;
        return (
          <div key={it.label} style={{ opacity: p, transform: `translateX(${(1 - p) * -28}px)` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <BulletMark kind={it.mark ?? "dot"} color={markColor} size={size * 0.62} />
              <span style={{ fontFamily: sans, fontWeight: 600, fontSize: size, letterSpacing: "-0.02em", color: fg, lineHeight: 1.1 }}>
                {it.label}
              </span>
            </div>
            {it.logos && (
              <div style={{ display: "flex", alignItems: "center", gap: 30, marginTop: 16, marginLeft: size * 0.62 + 18 }}>
                {it.logos.map((l) => {
                  const q = rise(t, l.at, 0.5);
                  return (
                    <div key={l.src} style={{ opacity: q, transform: `translateY(${(1 - q) * 16}px)` }}>
                      <Logo src={l.src} height={l.height ?? 28} color={l.native ? "native" : dark ? "white" : "ink"} />
                    </div>
                  );
                })}
              </div>
            )}
            {it.logos?.map((l) => <Sfx key={l.src} src="tone.wav" at={l.at} start={start} volume={0.32} />)}
          </div>
        );
      })}
    </div>
  );
}

function BulletMark({ kind, color, size }: { kind: "x" | "check" | "dot"; color: string; size: number }) {
  if (kind === "dot") return <div style={{ width: size * 0.42, height: size * 0.42, borderRadius: 3, background: color, margin: size * 0.29 }} />;
  return (
    <svg viewBox="0 0 24 24" style={{ width: size, height: size, flexShrink: 0 }}>
      {kind === "x" ? (
        <path d="M6 6l12 12M18 6L6 18" stroke={color} strokeWidth={3.2} strokeLinecap="round" />
      ) : (
        <path d="M4.5 12.5l5 5L19.5 7" stroke={color} strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      )}
    </svg>
  );
}

/** Bottom-of-screen citation strip. */
export function Cite({ children, t, at, out, dark = false }: { children: React.ReactNode; t: number; at: number; out?: number; dark?: boolean }) {
  const p = rise(t, at, 0.5) * (out ? 1 - rise(t, out, 0.4) : 1);
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        right: 80,
        bottom: 34,
        fontFamily: sans,
        fontSize: 21,
        color: dark ? "rgba(255,255,255,0.62)" : C.muted,
        opacity: p,
        letterSpacing: "0.005em",
      }}
    >
      {children}
    </div>
  );
}

/** Brand mark over stock-footage-only shots. */
export function Watermark({ opacity = 1 }: { opacity?: number }) {
  return (
    <div style={{ position: "absolute", left: 64, top: 52, opacity, filter: "drop-shadow(0 2px 10px rgba(0,0,0,0.45))" }}>
      <Wordmark size={40} color={C.white} />
    </div>
  );
}

export const fadeIn = (t: number, at: number, dur = 0.4) => interpolate(t, [at, at + dur], [0, 1], clamp);
export const fadeOut = (t: number, at: number, dur = 0.4) => interpolate(t, [at, at + dur], [1, 0], clamp);

export { AbsoluteFill, Img, Sequence, interpolate, staticFile };
export { C, mono, sans };
