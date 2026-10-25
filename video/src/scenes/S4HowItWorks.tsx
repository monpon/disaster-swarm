import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";
import { Bullets, C, Cite, Mark, fadeIn, fadeOut, rise, sans, useT } from "../components/kit";
import { S4 } from "../timeline";

const v = S4.vo;

/** Rounded media frame that matches the website's card style. */
function Card({ children, opacity = 1, scale = 1, top = 150, height = 687 }: { children: React.ReactNode; opacity?: number; scale?: number; top?: number; height?: number }) {
  return (
    <div
      style={{
        position: "absolute",
        left: 830,
        top,
        width: 1000,
        height,
        borderRadius: 22,
        overflow: "hidden",
        background: C.white,
        boxShadow: `0 0 0 1px ${C.line}, 0 30px 70px rgba(0,0,0,0.10)`,
        opacity,
        transform: `scale(${scale})`,
      }}
    >
      {children}
    </div>
  );
}

export function S4HowItWorks() {
  const t = useT(S4.start);
  const vitalsOn = fadeIn(t, v.vitals - 0.25, 0.35) * fadeOut(t, v.blocked - 0.25, 0.35);
  const cardIn = rise(t, S4.start, 0.7);
  return (
    <AbsoluteFill style={{ background: C.panel }}>
      <div style={{ position: "absolute", left: 96, top: 120, display: "flex", alignItems: "center", gap: 14, opacity: cardIn }}>
        <Mark size={34} />
        <span style={{ fontFamily: sans, fontWeight: 600, fontSize: 22, letterSpacing: "0.12em", color: C.orange, textTransform: "uppercase" }}>
          How Mayfly works
        </span>
      </div>
      <div style={{ position: "absolute", left: 96, top: 210, width: 700 }}>
        <Bullets
          t={t}
          start={S4.start}
          size={40}
          gap={22}
          items={[
            { at: v.spreads + 0.3, label: "Parallel search" },
            { at: v.noPilot + 0.2, label: "No pilots" },
            { at: v.map + 0.4, label: "One live 3D map" },
            { at: v.people + 0.2, label: "Trapped people", logos: [{ src: "ultralytics.svg", at: v.people + 0.7, height: 34, native: true }] },
            { at: v.vitals + 0.2, label: "Vitals", logos: [{ src: "presage.png", at: v.vitals + 0.8, height: 40, native: true }] },
            { at: v.blocked + 0.2, label: "Blocked paths" },
            { at: v.danger + 0.2, label: "Hazards" },
          ]}
        />
      </div>
      {/* The website's own "build one map" story, scrolled steadily. */}
      <Card opacity={cardIn} scale={0.97 + cardIn * 0.03}>
        <OffthreadVideo src={staticFile("rec/mapstory.mp4")} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </Card>
      {/* Presage pulse read from the website's vitals section. */}
      <Sequence from={Math.round((v.vitals - 0.3 - S4.start) * 30)} durationInFrames={Math.round((v.blocked - v.vitals + 0.4) * 30)}>
        <AbsoluteFill style={{ left: 800, background: C.panel, opacity: vitalsOn }} />
        <Card opacity={vitalsOn} top={268} height={452}>
          <OffthreadVideo src={staticFile("rec/vitals.mp4")} startFrom={126} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Card>
      </Sequence>
      <Cite t={t} at={v.map + 0.4} out={S4.end - 0.4}>
        Collaborative mapping: Lajoie &amp; Beltrame, “Swarm-SLAM,” IEEE RA-L (2023) · Detection: Jocher et al., “Ultralytics YOLO26” (2026)
      </Cite>
    </AbsoluteFill>
  );
}
