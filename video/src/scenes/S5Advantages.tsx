import { AbsoluteFill } from "remotion";
import { C, Cite, Logo, Sfx, rise, sans, useSpringAt, useT } from "../components/kit";
import { S5 } from "../timeline";

const v = S5.vo;

function Icon({ kind }: { kind: "fast" | "cost" | "auto" }) {
  const common = { fill: "none", stroke: C.orange, strokeWidth: 2.4, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg viewBox="0 0 48 48" style={{ width: 64, height: 64 }}>
      {kind === "fast" && (
        <>
          <circle cx="26" cy="26" r="16" {...common} />
          <path d="M26 16v10l7 5M4 18h8M2 26h8M4 34h8" {...common} />
        </>
      )}
      {kind === "cost" && (
        <>
          <rect x="6" y="12" width="36" height="24" rx="4" {...common} />
          <circle cx="24" cy="24" r="5" {...common} />
          <path d="M12 18v0M36 30v0" {...common} />
        </>
      )}
      {kind === "auto" && (
        <>
          <path d="M14 14l20 20M34 14L14 34" {...common} />
          <circle cx="12" cy="12" r="6" {...common} />
          <circle cx="36" cy="12" r="6" {...common} />
          <circle cx="12" cy="36" r="6" {...common} />
          <circle cx="36" cy="36" r="6" {...common} />
        </>
      )}
    </svg>
  );
}

function Column({
  t,
  at,
  n,
  icon,
  title,
  sub,
  logos,
}: {
  t: number;
  at: number;
  n: number;
  icon: "fast" | "cost" | "auto";
  title: string;
  sub: string;
  logos?: { src: string; at: number; height: number }[];
}) {
  const s = useSpringAt(t, at, 16);
  const p = rise(t, at, 0.5);
  return (
    <div
      style={{
        flex: 1,
        height: 480,
        borderRadius: 26,
        background: n === 1 ? C.ink : C.white,
        boxShadow: n === 1 ? "none" : `0 0 0 1px ${C.line}, 0 20px 50px rgba(0,0,0,0.06)`,
        padding: "56px 48px",
        display: "flex",
        flexDirection: "column",
        gap: 22,
        opacity: p,
        transform: `translateY(${(1 - s) * 60}px)`,
      }}
    >
      <Icon kind={icon} />
      <span style={{ fontFamily: sans, fontWeight: 600, fontSize: 22, color: n === 1 ? "rgba(255,255,255,0.55)" : C.faint }}>0{n}</span>
      <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 76, letterSpacing: "-0.035em", lineHeight: 1, color: n === 1 ? C.orange : C.ink }}>
        {title}
      </span>
      <span style={{ fontFamily: sans, fontWeight: 500, fontSize: 32, letterSpacing: "-0.01em", color: n === 1 ? C.white : C.muted }}>{sub}</span>
      {logos && (
        <div style={{ display: "flex", gap: 28, alignItems: "center", marginTop: "auto" }}>
          {logos.map((l) => {
            const q = rise(t, l.at, 0.5);
            return (
              <div key={l.src} style={{ opacity: q, transform: `translateY(${(1 - q) * 14}px)` }}>
                <Logo src={l.src} height={l.height} color={n === 1 ? "white" : "ink"} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Fourth benefit: responders stay safer and keep their time and energy for the rescue. */
function Responders({ t, at }: { t: number; at: number }) {
  const p = rise(t, at, 0.5);
  return (
    <div
      style={{
        marginTop: 36,
        height: 120,
        borderRadius: 22,
        background: C.orange,
        display: "flex",
        alignItems: "center",
        gap: 28,
        padding: "0 48px",
        opacity: p,
        transform: `translateY(${(1 - p) * 30}px)`,
      }}
    >
      <svg viewBox="0 0 48 48" style={{ width: 58, height: 58, flexShrink: 0 }}>
        <path d="M24 5 40 11v12c0 10-7 17-16 20C15 40 8 33 8 23V11Z" fill="none" stroke="#fff" strokeWidth={3} strokeLinejoin="round" />
        <path d="M16.5 24l5 5 10-11" fill="none" stroke="#fff" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 52, letterSpacing: "-0.03em", color: C.white }}>Safer responders</span>
      <span style={{ fontFamily: sans, fontWeight: 500, fontSize: 32, color: "rgba(255,255,255,0.9)" }}>Time and energy saved for the rescue</span>
    </div>
  );
}

export function S5Advantages() {
  const t = useT(S5.start);
  return (
    <AbsoluteFill style={{ background: C.panel, padding: "0 96px", justifyContent: "center" }}>
      <div style={{ display: "flex", gap: 36 }}>
        <Column t={t} at={v.faster} n={1} icon="fast" title="Faster" sub="Many drones at once" />
        <Column
          t={t}
          at={v.cheaper}
          n={2}
          icon="cost"
          title="Cheaper"
          sub="Small drones, one computer"
          logos={[{ src: "raspberry-pi.svg", at: v.cheaper + 1.4, height: 46 }]}
        />
        <Column
          t={t}
          at={v.autonomous}
          n={3}
          icon="auto"
          title="Autonomous"
          sub="No pilot per drone"
          logos={[{ src: "ros.svg", at: v.autonomous + 1.2, height: 34 }]}
        />
      </div>
      <Responders t={t} at={v.autonomous + 1.6} />
      <Sfx src="tone.wav" at={v.faster} start={S5.start} volume={0.35} />
      <Sfx src="tone.wav" at={v.autonomous + 1.6} start={S5.start} volume={0.3} />
      <Sfx src="tone.wav" at={v.cheaper} start={S5.start} volume={0.35} />
      <Sfx src="tone.wav" at={v.cheaper + 1.4} start={S5.start} volume={0.25} />
      <Sfx src="tone.wav" at={v.autonomous} start={S5.start} volume={0.35} />
      <Sfx src="tone.wav" at={v.autonomous + 1.2} start={S5.start} volume={0.25} />
      <Cite t={t} at={v.cheaper + 1.4} out={S5.end - 0.4}>
        Low-cost drone control: Richards et al., marshallrichards/turbodrone, GitHub (2026)
      </Cite>
    </AbsoluteFill>
  );
}
