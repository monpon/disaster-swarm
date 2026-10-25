import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import React from "react";
import { C, Sfx, clamp, ease, fadeIn, interpolate, rise, useT } from "../components/kit";
import { S3 } from "../timeline";

const v = S3.vo;
// floor.mp4 is the live console (1840x1034). Its main drone-camera view sits here:
const CAM = { x: 218, y: 48, w: 1056, h: 790 };
// Seconds into floor.mp4 where the console shows a different drone's camera.
const VIEWS = [24, 50, 54, 64, 68, 76, 86, 88, 98];
const SNAP0 = 40.8;
const SNAP = 0.43;

/** Shows one region of floor.mp4 scaled to fill the frame. */
function ConsoleCrop({ from, region, style }: { from: number; region: { x: number; y: number; w: number; h: number }; style?: React.CSSProperties }) {
  const k = Math.max(1920 / region.w, 1080 / region.h);
  return (
    <div style={{ position: "absolute", overflow: "hidden", ...style }}>
      <OffthreadVideo
        src={staticFile("rec/floor.mp4")}
        startFrom={Math.round(from * 30)}
        muted
        style={{
          position: "absolute",
          width: 1840 * k,
          height: 1034 * k,
          left: -region.x * k + (1920 - region.w * k) / 2,
          top: -region.y * k + (1080 - region.h * k) / 2,
          maxWidth: "none",
        }}
      />
    </div>
  );
}

/** "What if we could search an entire building": the console's drone cameras expand and snap past. */
function CameraSnaps({ t }: { t: number }) {
  const expand = interpolate(t, [40.25, 40.8], [0, 1], { ...clamp, easing: ease });
  // A feed tile grows out of the overview into a full-frame camera view.
  const tile = {
    left: interpolate(expand, [0, 1], [1360, 0]),
    top: interpolate(expand, [0, 1], [700, 0]),
    width: interpolate(expand, [0, 1], [440, 1920]),
    height: interpolate(expand, [0, 1], [330, 1080]),
    borderRadius: interpolate(expand, [0, 1], [14, 0]),
  };
  const i = Math.min(VIEWS.length - 1, Math.max(0, Math.floor((t - SNAP0) / SNAP)));
  const local = t - SNAP0 - i * SNAP;
  const punch = t < SNAP0 ? 1 : interpolate(local, [0, 0.18], [1.07, 1], { ...clamp, easing: ease });
  return (
    <AbsoluteFill style={{ background: "#111" }}>
      <AbsoluteFill style={{ transform: `scale(${interpolate(t, [S3.start, 40.8], [1.0, 1.08], clamp)})` }}>
        <ConsoleCrop from={0} region={{ x: 46, y: 48, w: 1400, h: 790 }} style={{ inset: 0 }} />
      </AbsoluteFill>
      {t >= 40.25 && (
        <div style={{ position: "absolute", ...tile, overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.45)" }}>
          {t < SNAP0 ? (
            <ConsoleCrop from={VIEWS[0]} region={CAM} style={{ left: 0, top: 0, width: 1920, height: 1080, transform: `scale(${tile.width / 1920})`, transformOrigin: "0 0" }} />
          ) : (
            VIEWS.map((v0, k) => (
              <Sequence key={k} from={Math.round((SNAP0 + k * SNAP - S3.start) * 30)} durationInFrames={k === VIEWS.length - 1 ? 60 : Math.round(SNAP * 30)} layout="none">
                <ConsoleCrop from={v0} region={CAM} style={{ inset: 0, transform: `scale(${k === i ? punch : 1})` }} />
              </Sequence>
            ))
          )}
        </div>
      )}
      {t >= SNAP0 && <AbsoluteFill style={{ background: "#fff", opacity: interpolate(local, [0, 0.07], [0.22, 0], clamp) }} />}
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
      <CameraSnaps t={t} />
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
      <Sfx src="whoosh.wav" at={40.25} start={S3.start} volume={0.16} />
      {VIEWS.map((_, k) => (
        <Sfx key={k} src="click.wav" at={SNAP0 + k * SNAP} start={S3.start} volume={0.22} />
      ))}
      <Sfx src="whoosh.wav" at={v.notOne - 0.4} start={S3.start} volume={0.18} />
    </AbsoluteFill>
  );
}
