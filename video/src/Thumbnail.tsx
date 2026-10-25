import { AbsoluteFill, Img, staticFile } from "remotion";
import { C, Mark, sans } from "./components/kit";

// Page tone sampled to match the console's map background so the 3D map bleeds into it.
const BG = "#ECECEA";

const MASK =
  "linear-gradient(90deg, transparent 0%, #000 22%, #000 100%), linear-gradient(180deg, #000 0%, #000 82%, transparent 100%)";

/** README / YouTube / Devpost thumbnail: one big headline beside the live 3D map finding a person. */
export function Thumbnail() {
  return (
    <AbsoluteFill style={{ background: BG, fontFamily: sans, overflow: "hidden" }}>
      {/* Hero visual: the live 3D map, faded into the page on its left edge. */}
      <Img
        src={staticFile("thumb/map.jpg")}
        style={{
          position: "absolute",
          left: 800,
          top: 250,
          width: 1340,
          height: 670,
          objectFit: "cover",
          WebkitMaskImage: MASK,
          maskImage: MASK,
          WebkitMaskComposite: "source-in",
          maskComposite: "intersect",
        }}
      />

      {/* The finding the map surfaced. */}
      <div
        style={{
          position: "absolute",
          left: 1230,
          top: 96,
          width: 620,
          borderRadius: 22,
          overflow: "hidden",
          background: C.white,
          boxShadow: "0 24px 60px rgba(40,20,10,0.22), 0 0 0 1px rgba(0,0,0,0.06)",
          borderLeft: `10px solid ${C.person}`,
        }}
      >
        <Img src={staticFile("thumb/finding.jpg")} style={{ display: "block", width: "100%" }} />
      </div>

      {/* Our real drone. */}
      <div
        style={{
          position: "absolute",
          left: 1560,
          top: 730,
          width: 290,
          height: 290,
          borderRadius: "50%",
          overflow: "hidden",
          border: `10px solid ${C.white}`,
          boxShadow: `0 0 0 6px ${C.orange}, 0 26px 60px rgba(40,20,10,0.3)`,
        }}
      >
        <Img src={staticFile("thumb/drone.jpg")} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>

      {/* Left column: wordmark, headline, subline. */}
      <div style={{ position: "absolute", left: 104, top: 96, display: "flex", alignItems: "center", gap: 24 }}>
        <Mark size={96} />
        <span style={{ fontWeight: 700, fontSize: 92, letterSpacing: "-0.04em", color: C.ink, lineHeight: 1 }}>Mayfly</span>
      </div>

      <div
        style={{
          position: "absolute",
          left: 96,
          top: 300,
          fontWeight: 700,
          fontSize: 178,
          lineHeight: 0.98,
          letterSpacing: "-0.045em",
          color: C.ink,
        }}
      >
        Drones go
        <br />
        in <span style={{ color: C.orange }}>first.</span>
      </div>

      <div style={{ position: "absolute", left: 104, top: 700, width: 720, fontWeight: 500, fontSize: 44, lineHeight: 1.2, color: C.ink2, letterSpacing: "-0.01em" }}>
        Cheap drones map the collapse so rescuers know where people are.
      </div>

      <div
        style={{
          position: "absolute",
          left: 104,
          top: 920,
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 26px",
          borderRadius: 999,
          background: C.ink,
          color: C.white,
          fontWeight: 600,
          fontSize: 32,
        }}
      >
        <span style={{ width: 14, height: 14, borderRadius: 7, background: C.orange }} />
        Cal Hacks 13.0
      </div>
    </AbsoluteFill>
  );
}
