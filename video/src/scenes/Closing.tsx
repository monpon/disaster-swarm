import { AbsoluteFill, Sequence } from "remotion";
import { C, Mark, Sfx, Stock, Vignette, Watermark, clamp, fadeIn, interpolate, rise, sans, useSpringAt, useT } from "../components/kit";
import { D, PART_D_LEN } from "../timeline";

/** Part D: "When lives are on the line… every second counts." Then the Mayfly brand and the site's promise. */
export function Closing() {
  const t = useT(0);
  const lives = rise(t, D.lives, 0.4);
  const every = rise(t, D.every, 0.35);
  const brand = fadeIn(t, D.brand - 0.15, 0.3);
  const mark = useSpringAt(t, D.brand, 12);
  const word = rise(t, D.brand + 0.2, 0.5);
  const tag = rise(t, D.brand + 0.6, 0.5);
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Sequence durationInFrames={Math.round((D.every + 0.2) * 30)}>
        <Stock src="stock/rescue_isar_03.mp4" t={t} from={0} to={D.every} startFrom={3} scale={[1.12, 1.18]} dark={0.4} origin="50% 55%" />
        <Vignette strength={0.7} />
        <Watermark />
        <div
          style={{
            position: "absolute",
            left: 120,
            bottom: 130,
            fontFamily: sans,
            fontWeight: 700,
            fontSize: 96,
            letterSpacing: "-0.035em",
            color: C.white,
            opacity: lives,
            transform: `translateY(${(1 - lives) * 20}px)`,
            textShadow: "0 4px 24px rgba(0,0,0,0.5)",
          }}
        >
          When lives are on the line,
        </div>
      </Sequence>
      <AbsoluteFill style={{ background: C.ink, opacity: fadeIn(t, D.every - 0.1, 0.2), alignItems: "center", justifyContent: "center" }}>
        <div
          style={{
            fontFamily: sans,
            fontWeight: 700,
            fontSize: 150,
            letterSpacing: "-0.04em",
            color: C.white,
            opacity: every,
            transform: `scale(${interpolate(t, [D.every, D.brand], [1.0, 1.05], clamp)})`,
          }}
        >
          every second counts.
        </div>
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          opacity: brand,
          background: "linear-gradient(135deg,#ff6a2e 0%,#e8480c 100%)",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          gap: 44,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 34 }}>
          <div style={{ transform: `scale(${mark})`, filter: "drop-shadow(0 10px 24px rgba(80,20,0,0.35))" }}>
            <div style={{ borderRadius: 34, boxShadow: "0 0 0 6px rgba(255,255,255,0.95)" }}>
              <Mark size={150} />
            </div>
          </div>
          <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 170, letterSpacing: "-0.035em", color: C.white, opacity: word }}>Mayfly</span>
        </div>
        <span
          style={{
            fontFamily: sans,
            fontWeight: 600,
            fontSize: 64,
            letterSpacing: "-0.02em",
            color: C.white,
            opacity: tag,
            transform: `translateY(${(1 - tag) * 20}px)`,
          }}
        >
          Send the swarm.
        </span>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "#000", opacity: interpolate(t, [PART_D_LEN - 0.5, PART_D_LEN], [0, 1], clamp) }} />
      <Sfx src="hit.wav" at={D.every} start={0} volume={0.3} />
      <Sfx src="tone_hi.wav" at={D.brand} start={0} volume={0.5} />
    </AbsoluteFill>
  );
}
