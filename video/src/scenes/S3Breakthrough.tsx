import { AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile } from "remotion";
import React from "react";
import { C, Sfx, clamp, ease, fadeIn, interpolate, rise, useT } from "../components/kit";
import { S3 } from "../timeline";

const v = S3.vo;
// Paper mockups of the console (public/paper, 1920x1200). m1 opens the scene; the rest snap past.
const MOCKS = ["m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"];
const SNAP0 = 40.8;
const SNAP = 0.5;

function Mock({ name, style }: { name: string; style?: React.CSSProperties }) {
  return <Img src={staticFile(`paper/${name}.jpg`)} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover", objectPosition: "50% 0%", ...style }} />;
}

/** "What if we could search an entire building": the console mockups push in, then snap past one after another. */
function MockupSnaps({ t }: { t: number }) {
  const i = Math.min(MOCKS.length - 1, Math.max(0, Math.floor((t - SNAP0) / SNAP)));
  const local = t - SNAP0 - i * SNAP;
  const punch = interpolate(local, [0, 0.18], [1.06, 1], { ...clamp, easing: ease });
  return (
    <AbsoluteFill style={{ background: C.white }}>
      {t < SNAP0 ? (
        <Mock name="m1" style={{ transform: `scale(${interpolate(t, [S3.start, SNAP0], [1.0, 1.1], { ...clamp, easing: ease })})`, transformOrigin: "40% 35%" }} />
      ) : (
        <Mock name={MOCKS[i]} style={{ transform: `scale(${punch})` }} />
      )}
      {t >= SNAP0 && <AbsoluteFill style={{ background: "#fff", opacity: interpolate(local, [0, 0.07], [0.3, 0], clamp) }} />}
    </AbsoluteFill>
  );
}

export function S3Breakthrough() {
  const t = useT(S3.start);
  const raceIn = fadeIn(t, v.notOne - 0.3, 0.5);
  // Emphasis moves from the lone drone to the swarm as the narration does.
  const focusSwarm = rise(t, v.swarm, 0.6);
  return (
    <AbsoluteFill style={{ background: C.white }}>
      <MockupSnaps t={t} />
      <Sequence from={Math.round((v.notOne - 0.3 - S3.start) * 30)}>
        <AbsoluteFill style={{ opacity: raceIn, background: C.white }}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              transform: `scale(${interpolate(t, [v.notOne, v.swarm, S3.end], [1.0, 1.0, 1.06], clamp)})`,
              transformOrigin: `${50 + focusSwarm * 22}% 60%`,
            }}
          >
            <OffthreadVideo src={staticFile("rec/race.mp4")} startFrom={36} muted style={{ position: "absolute", left: 96, top: 54, width: 1728, height: 972 }} />
          </div>
        </AbsoluteFill>
      </Sequence>
      {MOCKS.map((_, k) => (
        <Sfx key={k} src="click.wav" at={SNAP0 + k * SNAP} start={S3.start} volume={0.22} />
      ))}
      <Sfx src="whoosh.wav" at={v.notOne - 0.4} start={S3.start} volume={0.18} />
    </AbsoluteFill>
  );
}
