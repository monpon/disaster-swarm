import { AbsoluteFill } from "remotion";
import { C, Sfx, clamp, interpolate, rise, sans, useSpringAt, useT } from "../components/kit";
import { S6 } from "../timeline";

const v = S6.vo;

function Stat({
  t,
  at,
  value,
  label,
  source,
  detail,
  hero,
}: {
  t: number;
  at: number;
  value: (p: number) => string;
  label: string;
  source: string;
  detail: string;
  hero?: boolean;
}) {
  const s = useSpringAt(t, at, 17);
  const p = rise(t, at, 0.5);
  const count = interpolate(t, [at, at + 1.1], [0, 1], { ...clamp, easing: (x) => 1 - Math.pow(1 - x, 3) });
  return (
    <div
      style={{
        flex: 1,
        borderRadius: 26,
        padding: "52px 46px 44px",
        background: hero ? C.ink : C.white,
        boxShadow: hero ? "none" : `0 0 0 1px ${C.line}`,
        display: "flex",
        flexDirection: "column",
        opacity: p,
        transform: `translateY(${(1 - s) * 50}px)`,
      }}
    >
      <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 104, letterSpacing: "-0.045em", lineHeight: 1, color: hero ? C.orange : C.ink }}>
        {value(count)}
      </span>
      <span style={{ fontFamily: sans, fontWeight: 600, fontSize: 34, letterSpacing: "-0.015em", marginTop: 22, color: hero ? C.white : C.ink }}>
        {label}
      </span>
      <div style={{ marginTop: "auto", paddingTop: 34, borderTop: `1px solid ${hero ? "rgba(255,255,255,0.18)" : C.line}` }}>
        <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 21, color: hero ? C.white : C.ink }}>{source}</div>
        <div style={{ fontFamily: sans, fontSize: 19, marginTop: 6, color: hero ? "rgba(255,255,255,0.6)" : C.muted, lineHeight: 1.35 }}>{detail}</div>
      </div>
    </div>
  );
}

/** Market size, Grand View Research: drone-as-first-responder and the overall drone market, 2026 → 2033. */
function Market({ t, at }: { t: number; at: number }) {
  const rows = [
    { at, label: "Drone-as-first-responder market", from: "$3.5B", to: "$11B", note: "17.7% / yr", hero: true },
    { at: at + 0.5, label: "Global drone market", from: "$96.4B", to: "$182.4B", note: "", hero: false },
  ];
  return (
    <div style={{ display: "flex", gap: 32, marginTop: 28, height: 150 }}>
      {rows.map((r) => {
        const p = rise(t, r.at, 0.45);
        return (
          <div
            key={r.label}
            style={{
              flex: 1,
              minWidth: 0,
              borderRadius: 22,
              padding: "0 34px",
              display: "flex",
              alignItems: "center",
              gap: 20,
              background: r.hero ? C.orange : C.white,
              boxShadow: r.hero ? "none" : `0 0 0 1px ${C.line}`,
              opacity: p,
              transform: `translateY(${(1 - p) * 26}px)`,
            }}
          >
            <span style={{ fontFamily: sans, fontWeight: 600, fontSize: 22, lineHeight: 1.2, width: 170, flexShrink: 0, color: r.hero ? "rgba(255,255,255,0.92)" : C.muted }}>
              {r.label}
            </span>
            <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 54, letterSpacing: "-0.04em", color: r.hero ? C.white : C.ink }}>{r.from}</span>
            <svg viewBox="0 0 40 20" style={{ width: 40, height: 20, flexShrink: 0 }}>
              <path d="M2 10h32M26 3l8 7-8 7" fill="none" stroke={r.hero ? "#fff" : C.ink} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 54, letterSpacing: "-0.04em", color: r.hero ? C.white : C.ink }}>{r.to}</span>
            <span style={{ display: "flex", flexDirection: "column", fontFamily: sans, fontSize: 19, lineHeight: 1.3, whiteSpace: "nowrap", color: r.hero ? "rgba(255,255,255,0.85)" : C.faint }}>
              <span>2026 → 2033</span>
              {r.note && <span style={{ fontWeight: 600 }}>{r.note}</span>}
            </span>
          </div>
        );
      })}
      <div
        style={{
          position: "absolute",
          right: 96,
          bottom: 40,
          fontFamily: sans,
          fontSize: 19,
          color: C.faint,
          opacity: rise(t, at, 0.45),
        }}
      >
        Market size: Grand View Research (2026)
      </div>
    </div>
  );
}

export function S6Research() {
  const t = useT(S6.start);
  const head = rise(t, S6.start + 0.1, 0.6);
  return (
    <AbsoluteFill style={{ background: C.panel, padding: "110px 96px 0" }}>
      <div style={{ opacity: head, transform: `translateY(${(1 - head) * 16}px)` }}>
        <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 22, letterSpacing: "0.12em", color: C.orange, textTransform: "uppercase" }}>
          Research and market
        </div>
        <div style={{ fontFamily: sans, fontWeight: 700, fontSize: 64, letterSpacing: "-0.03em", color: C.ink, marginTop: 10 }}>
          Teams of robots map faster.
        </div>
      </div>
      <div style={{ display: "flex", gap: 32, marginTop: 48, height: 420 }}>
        <Stat
          t={t}
          at={v.sensors}
          hero
          value={(p) => `~${Math.round(50 * p)}%`}
          label="Less indoor mapping time"
          source="Xia et al., Sensors (2024)"
          detail="Collaborative two-ground-robot mapping experiment"
        />
        <Stat
          t={t}
          at={v.sensors + 2.6}
          value={(p) => `${(26.4 * p).toFixed(1)}%`}
          label="Better indoor exploration"
          source="Kim et al., IEEE RA-L (2024)"
          detail="Up to three aerial robots vs. the paper's baseline"
        />
        <Stat
          t={t}
          at={v.cost}
          value={(p) => `$${Math.round(29999 * p).toLocaleString("en-US")}`}
          label="Per specialized indoor drone"
          source="Santa Clara County Sheriff's Office"
          detail="BRINC LEMUR 2 equipment listing, procurement cost"
        />
      </div>
      <Market t={t} at={98.4} />
      <Sfx src="tone.wav" at={v.sensors} start={S6.start} volume={0.35} />
      <Sfx src="tone.wav" at={v.sensors + 2.6} start={S6.start} volume={0.25} />
      <Sfx src="tone.wav" at={v.cost} start={S6.start} volume={0.35} />
      <Sfx src="tone.wav" at={98.4} start={S6.start} volume={0.25} />
    </AbsoluteFill>
  );
}
