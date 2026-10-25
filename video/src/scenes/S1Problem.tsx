import { AbsoluteFill, Sequence } from "remotion";
import { C, KenBurns, Stock, Vignette, Watermark, clamp, fadeIn, interpolate, rise, sans, useT } from "../components/kit";
import { S1 } from "../timeline";

const v = S1.vo;

/** Pulsing marker for a person whose location is unknown. */
function Unknown({ x, y, t, at }: { x: number; y: number; t: number; at: number }) {
  const p = rise(t, at, 0.6);
  const pulse = ((t - at) * 0.8) % 1;
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity: p * 0.95 }}>
      <div
        style={{
          position: "absolute",
          left: -64,
          top: -64,
          width: 128,
          height: 128,
          borderRadius: 64,
          border: `2px solid ${C.orange}`,
          transform: `scale(${0.4 + pulse * 1.1})`,
          opacity: 1 - pulse,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: -32,
          top: -32,
          width: 64,
          height: 64,
          borderRadius: 32,
          background: "rgba(255,90,31,0.25)",
          border: `2px solid ${C.orange}`,
          color: C.white,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: sans,
          fontWeight: 700,
          fontSize: 34,
        }}
      >
        ?
      </div>
    </div>
  );
}

export function S1Problem() {
  const t = useT(S1.start);
  // Cut points sit just before each narration line.
  const cuts = [0, v.trapped - 0.2, v.rescue - 0.15, v.fast - 1.0, v.problem - 0.2, S1.end];
  const seg = (i: number) => ({ from: Math.round(cuts[i] * 30), durationInFrames: Math.round((cuts[i + 1] - cuts[i]) * 30) });
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <Sequence {...seg(0)}>
        <Stock src="stock/quake_collapse_01.mp4" t={t} from={cuts[0]} to={cuts[1]} scale={[1.0, 1.1]} />
      </Sequence>
      <Sequence {...seg(1)}>
        <KenBurns src="stock/interior_debris_01.jpg" t={t} from={cuts[1]} to={cuts[2]} scale={[1.08, 1.2]} dark={0.42} origin="50% 60%" />
        <Unknown x={760} y={620} t={t} at={v.nobody} />
        <Unknown x={1230} y={540} t={t} at={v.nobody + 0.35} />
        <Unknown x={1010} y={780} t={t} at={v.nobody + 0.7} />
      </Sequence>
      <Sequence {...seg(2)}>
        <Stock src="stock/rescue_usar_01.mp4" t={t} from={cuts[2]} to={cuts[3]} startFrom={1} />
      </Sequence>
      <Sequence {...seg(3)}>
        <Stock src="stock/rescue_rubble_05.mp4" t={t} from={cuts[3]} to={cuts[4]} startFrom={2} />
      </Sequence>
      <Sequence {...seg(4)}>
        <KenBurns
          src="stock/quake_photo_01.jpg"
          t={t}
          from={cuts[4]}
          to={cuts[5]}
          scale={[1.05, 1.22]}
          dark={interpolate(t, [cuts[4], v.second, cuts[5]], [0.3, 0.45, 0.62], clamp)}
        />
      </Sequence>
      <Vignette strength={0.6} />
      {/* Fade up from black at the very top. */}
      <AbsoluteFill style={{ background: "#000", opacity: 1 - fadeIn(t, 0, 0.8) }} />
      <Watermark opacity={fadeIn(t, 0.6, 0.6)} />
    </AbsoluteFill>
  );
}
