import { AbsoluteFill, Img, staticFile } from "remotion";
import { C, Mark, sans } from "./components/kit";

/** README / video thumbnail: brand panel beside a real frame of the live console. */
export function Thumbnail() {
  return (
    <AbsoluteFill style={{ background: "linear-gradient(135deg,#ff6a2e 0%,#e8480c 100%)" }}>
      <div style={{ position: "absolute", left: 110, top: 0, bottom: 0, width: 760, display: "flex", flexDirection: "column", justifyContent: "center", gap: 34 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 26 }}>
          <div style={{ borderRadius: 26, boxShadow: "0 0 0 5px rgba(255,255,255,0.95)" }}>
            <Mark size={112} />
          </div>
          <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 132, letterSpacing: "-0.04em", color: C.white }}>Mayfly</span>
        </div>
        <span style={{ fontFamily: sans, fontWeight: 700, fontSize: 66, lineHeight: 1.05, letterSpacing: "-0.03em", color: C.white }}>
          A swarm of small drones that finds people faster.
        </span>
        <span style={{ fontFamily: sans, fontWeight: 500, fontSize: 30, color: "rgba(255,255,255,0.88)" }}>Search and rescue · Cal Hacks 13.0</span>
      </div>
      <div
        style={{
          position: "absolute",
          left: 930,
          top: 170,
          width: 1180,
          height: 664,
          borderRadius: 22,
          overflow: "hidden",
          transform: "rotate(-3deg)",
          boxShadow: "0 40px 90px rgba(60,15,0,0.45)",
        }}
      >
        <Img src={staticFile("web/thumb-console.jpg")} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "0% 50%" }} />
      </div>
    </AbsoluteFill>
  );
}
