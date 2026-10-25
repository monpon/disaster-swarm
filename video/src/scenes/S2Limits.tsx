import { AbsoluteFill } from "remotion";
import { Bullets, C, KenBurns, Sfx, Vignette, fadeIn, rise, sans, useT } from "../components/kit";
import { S2 } from "../timeline";

const v = S2.vo;

/** Narration keyword stamped on the photo: SLOW, EXPENSIVE, 1–2 per team. */
function Stamp({ t, at, label, top }: { t: number; at: number; label: string; top: number }) {
  const p = rise(t, at, 0.35);
  return (
    <div
      style={{
        position: "absolute",
        left: 72,
        top,
        opacity: p,
        transform: `translateY(${(1 - p) * 14}px) scale(${0.96 + p * 0.04})`,
        padding: "12px 22px",
        borderRadius: 12,
        background: "rgba(21,21,21,0.82)",
        boxShadow: `inset 0 0 0 2px ${C.orange}`,
        fontFamily: sans,
        fontWeight: 700,
        fontSize: 46,
        letterSpacing: "0.02em",
        color: C.white,
      }}
    >
      {label}
    </div>
  );
}

export function S2Limits() {
  const t = useT(S2.start);
  const panelIn = rise(t, S2.start, 0.7);
  return (
    <AbsoluteFill style={{ background: C.ink }}>
      {/* Left: the big specialized drone. */}
      <div style={{ position: "absolute", left: 0, top: 0, width: 760, height: 1080, overflow: "hidden" }}>
        <KenBurns src="stock/drone_elios_01.jpg" t={t} from={S2.start} to={S2.end} scale={[1.06, 1.18]} origin="55% 45%" dark={0.12} />
        <Vignette strength={0.5} />
        <Stamp t={t} at={v.slow} label="SLOW" top={640} />
        <Stamp t={t} at={v.expensive} label="EXPENSIVE" top={740} />
        <Stamp t={t} at={v.oneTwo} label="1–2 PER TEAM" top={840} />
      </div>
      {/* Right: what existing solutions lack, with the competitors nested under it. */}
      <div
        style={{
          position: "absolute",
          left: 760,
          top: 0,
          width: 1160,
          height: 1080,
          padding: "0 110px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          opacity: panelIn,
          transform: `translateX(${(1 - panelIn) * 40}px)`,
        }}
      >
        <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 22, letterSpacing: "0.12em", color: C.orange, textTransform: "uppercase" }}>
          Existing solutions
        </div>
        <div style={{ fontFamily: sans, fontWeight: 700, fontSize: 64, letterSpacing: "-0.03em", color: C.white, marginTop: 14, marginBottom: 64 }}>
          One drone. One pilot.
        </div>
        <Bullets
          dark
          t={t}
          start={S2.start}
          size={40}
          gap={44}
          items={[
            {
              at: v.today + 1.3,
              label: "No parallel search",
              mark: "x",
              logos: [
                { src: "brinc.svg", at: v.today + 1.9, height: 30 },
                { src: "flyability.svg", at: v.today + 2.4, height: 30 },
                { src: "skydio.svg", at: v.today + 2.9, height: 28 },
              ],
            },
            { at: v.today + 4.1, label: "Limited indoor mapping", mark: "x" },
            { at: v.today + 5.1, label: "Manual victim + hazard spotting", mark: "x" },
          ]}
        />
      </div>
      <Sfx src="hit.wav" at={v.slow} start={S2.start} volume={0.22} />
      <Sfx src="hit.wav" at={v.expensive} start={S2.start} volume={0.22} />
      <Sfx src="hit.wav" at={v.oneTwo} start={S2.start} volume={0.22} />
      <AbsoluteFill style={{ background: "#000", opacity: 1 - fadeIn(t, S2.start, 0.5) }} />
    </AbsoluteFill>
  );
}
