import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile } from "remotion";
import { C, Logo, Sfx, clamp, fadeIn, interpolate, rise, useT } from "../components/kit";
import { Arrow, Box, HAND, INK, Note, drawP } from "../components/sketch";
import { PART_C_LEN } from "../timeline";

// Beat starts and word cues, in seconds from the start of Part C (public/audio/partC.wav).
const c = {
  stack: 0,
  rust: 2.1,
  cuda: 2.4,
  nvrtc: 3.5,
  pyo3: 5.0,
  map: 6.2,
  cams: 6.9,
  depth: 8.2,
  tsdf: 8.9,
  res: 10.0,
  align: 11.7,
  aligner: 12.8,
  planes: 13.7,
  dual: 16.0,
  walls: 17.2,
  radio: 19.4,
  lossy: 21.7,
  fly: 23.0,
  detect: 24.7,
  yolo: 26.1,
  tuned: 27.2,
  humans: 29.6,
  fires: 30.1,
  doors: 30.7,
  next: 31.9,
  comms: 32.4,
  stream: 42.3,
  extra: 45.4,
};

const PAPER = "#fbfbf9";
const sec = (s: number) => Math.round(s * 30);

/** Hand-written chip that pops in on a narration word. */
function Chip({ t, at, children, accent, size = 40 }: { t: number; at: number; children: string; accent?: boolean; size?: number }) {
  const p = rise(t, at, 0.35);
  return (
    <div
      style={{
        alignSelf: "flex-start",
        padding: "10px 22px",
        borderRadius: 12,
        border: `3px solid ${accent ? C.orange : INK}`,
        background: accent ? "rgba(255,90,31,0.10)" : "#fff",
        fontFamily: HAND,
        fontSize: size,
        color: accent ? C.orangeEdge : INK,
        opacity: p,
        transform: `translateY(${(1 - p) * 14}px) rotate(${accent ? -1.5 : 0.8}deg)`,
      }}
    >
      {children}
    </div>
  );
}

/** Rounded frame holding screen footage, slightly tilted like a pinned screenshot. */
function Frame({
  children,
  t,
  at,
  x = 760,
  y = 150,
  w = 1060,
  h = 596,
  tilt = 1,
}: {
  children: React.ReactNode;
  t: number;
  at: number;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  tilt?: number;
}) {
  const p = rise(t, at, 0.5);
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: w,
        height: h,
        borderRadius: 16,
        overflow: "hidden",
        background: "#111",
        boxShadow: "0 22px 60px rgba(0,0,0,0.22), 0 0 0 3px #1e1e1e",
        opacity: p,
        transform: `rotate(${tilt}deg) scale(${0.96 + p * 0.04})`,
      }}
    >
      {children}
    </div>
  );
}

function Title({ t, at, children }: { t: number; at: number; children: string }) {
  return <div style={{ fontFamily: HAND, fontSize: 30, color: C.orangeEdge, opacity: rise(t, at, 0.4), marginBottom: 26 }}>{children}</div>;
}

function Column({ children }: { children: React.ReactNode }) {
  return <div style={{ position: "absolute", left: 110, top: 190, width: 600, display: "flex", flexDirection: "column", gap: 22 }}>{children}</div>;
}

// ---- Beats 1–2: the simulator core, over real screen footage ----
function Stack({ t }: { t: number }) {
  const mapOn = t >= c.map;
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <Column>
        <Title t={t} at={0.2}>
          {mapOn ? "Mapping" : "Under the hood"}
        </Title>
        {!mapOn ? (
          <>
            <Chip t={t} at={c.rust} accent>
              Rust
            </Chip>
            <Chip t={t} at={c.cuda}>
              CUDA kernels
            </Chip>
            <Chip t={t} at={c.nvrtc}>
              built with NVRTC
            </Chip>
            <Chip t={t} at={c.pyo3}>
              PyO3 → Python
            </Chip>
          </>
        ) : (
          <>
            <Chip t={t} at={c.cams}>
              Drone cameras
            </Chip>
            <Chip t={t} at={c.depth}>
              Depth
            </Chip>
            <Chip t={t} at={c.tsdf} accent>
              TSDF map
            </Chip>
            <Chip t={t} at={c.res}>
              20 cm voxels
            </Chip>
          </>
        )}
      </Column>
      <Frame t={t} at={0.1}>
        {!mapOn ? (
          <OffthreadVideo src={staticFile("rec/sim_tl.mp4")} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <Sequence from={sec(c.map)} layout="none">
            <OffthreadVideo src={staticFile("rec/floor.mp4")} startFrom={sec(1)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </Sequence>
        )}
      </Frame>
    </AbsoluteFill>
  );
}

// ---- Beat 3: keeping the map straight (hand-drawn) ----
function Align({ t }: { t: number }) {
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <Note x={110} y={160} t={t} at={c.align} size={34} color={C.orangeEdge}>
          Keeping the map straight
        </Note>
        <Box x={110} y={300} w={330} h={150} t={t} at={c.align + 0.1} seed={31} label="Frames + depth" sub="every drone" />
        <Arrow x1={450} y1={375} x2={600} y2={375} t={t} at={c.aligner - 0.3} seed={32} />
        <Box x={610} y={290} w={400} h={170} t={t} at={c.aligner} seed={33} accent label="Frame-to-TSDF aligner" fill="rgba(255,90,31,0.10)" />
        <Box x={610} y={560} w={400} h={130} t={t} at={c.planes} seed={34} label="Landmark planes" sub="walls · roof" />
        <Arrow x1={810} y1={555} x2={810} y2={470} t={t} at={c.planes + 0.3} seed={35} />
        <Note x={1040} y={260} t={t} at={c.planes + 0.8} size={26}>
          no pose drift
        </Note>
        <Arrow x1={1020} y1={375} x2={1170} y2={375} t={t} at={c.planes + 1.0} seed={36} />
        <Box x={1180} y={290} w={330} h={170} t={t} at={c.planes + 1.3} seed={37} label="TSDF map" sub="20 cm" />
        <Arrow x1={1345} y1={470} x2={1345} y2={560} t={t} at={c.dual - 0.2} seed={38} />
        <Box x={1180} y={570} w={330} h={130} t={t} at={c.dual} seed={39} accent label="Dual contouring" fill="rgba(255,90,31,0.10)" />
        <Arrow x1={1520} y1={635} x2={1600} y2={635} t={t} at={c.walls - 0.2} seed={40} />
        <Note x={1610} y={620} t={t} at={c.walls} size={30}>
          flat walls
        </Note>
        <Note x={1610} y={662} t={t} at={c.walls + 0.7} size={30}>
          open doorways
        </Note>
      </svg>
    </AbsoluteFill>
  );
}

/** Small top-down quadcopter doodle. */
function Quad({ x, y, p }: { x: number; y: number; p: number }) {
  return (
    <g opacity={p} stroke={INK} strokeWidth={2.4} fill="none">
      <path d={`M${x - 18} ${y - 18} L${x + 18} ${y + 18} M${x + 18} ${y - 18} L${x - 18} ${y + 18}`} />
      {[
        [-1, -1],
        [1, -1],
        [-1, 1],
        [1, 1],
      ].map(([dx, dy], i) => (
        <circle key={i} cx={x + dx * 20} cy={y + dy * 20} r={11} />
      ))}
      <rect x={x - 7} y={y - 7} width={14} height={14} rx={3} fill={C.orange} stroke="none" />
    </g>
  );
}

// ---- Beat 4: radio model + the real drone ----
const MASTER = { x: 520, y: 560 };
const QUADS: [number, number][] = [
  [200, 330],
  [520, 270],
  [840, 330],
  [900, 660],
  [520, 850],
  [150, 700],
];
function Radio({ t }: { t: number }) {
  const photo = rise(t, c.radio + 1.0, 0.5);
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <Note x={110} y={160} t={t} at={c.radio} size={34} color={C.orangeEdge}>
          Drones ↔ master
        </Note>
        {QUADS.map(([x, y], i) => {
          const p = drawP(t, c.radio + 0.1 + i * 0.08, 0.4);
          // Packets travel each link; some drop, as in the lossy radio model.
          const k = (((t - c.lossy) * 1.6 + i * 0.37) % 1 + 1) % 1;
          const show = t > c.lossy;
          const lost = i % 3 === 1;
          const px = x + (MASTER.x - x) * k;
          const py = y + (MASTER.y - y) * k;
          return (
            <g key={i}>
              <line x1={x} y1={y} x2={MASTER.x} y2={MASTER.y} stroke={INK} strokeWidth={2} strokeDasharray="10 9" opacity={p * 0.55} />
              <Quad x={x} y={y} p={p} />
              {show && !(lost && k > 0.55) && <circle cx={px} cy={py} r={7} fill={C.orange} />}
              {show && lost && k > 0.55 && (
                <text x={px} y={py + 8} fontFamily={HAND} fontSize={30} fill={C.person} textAnchor="middle">
                  ×
                </text>
              )}
            </g>
          );
        })}
        <Box x={MASTER.x - 110} y={MASTER.y - 55} w={220} h={110} t={t} at={c.radio + 0.5} seed={41} accent label="Master" fill="rgba(255,90,31,0.12)" />
        <Note x={300} y={1000} t={t} at={c.lossy} size={30}>
          lossy · delayed radio model
        </Note>
      </svg>
      {/* The team's drone: an E58 with the ESP32-S3 relay on top. */}
      <div
        style={{
          position: "absolute",
          left: 1120,
          top: 210,
          width: 680,
          padding: 16,
          paddingBottom: 70,
          background: "#fff",
          boxShadow: "0 18px 44px rgba(0,0,0,0.2)",
          transform: `rotate(2.5deg) translateY(${(1 - photo) * 40}px)`,
          opacity: photo,
        }}
      >
        <Img src={staticFile("team/drone_photo.jpg")} style={{ width: "100%", height: 486, objectFit: "cover" }} />
        <div style={{ position: "absolute", left: 22, bottom: 16, fontFamily: HAND, fontSize: 32, color: INK }}>our drone: E58 + ESP32-S3</div>
      </div>
    </AbsoluteFill>
  );
}

// ---- Beat 5: drone footage (vertical clip, blurred fill behind) ----
function Fly({ t }: { t: number }) {
  return (
    <Sequence from={sec(c.fly)} layout="none">
      <FlyInner t={t} />
    </Sequence>
  );
}
function FlyInner({ t }: { t: number }) {
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <AbsoluteFill style={{ filter: "blur(40px) brightness(0.55)", transform: "scale(1.2)" }}>
        <OffthreadVideo src={staticFile("team/drone_flight.mp4")} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: (1920 - 608) / 2,
          top: 0,
          width: 608,
          height: 1080,
          transform: `scale(${interpolate(t, [c.fly, c.detect], [1, 1.05], clamp)})`,
        }}
      >
        <OffthreadVideo src={staticFile("team/drone_flight.mp4")} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
    </AbsoluteFill>
  );
}

// ---- Beat 6: detection ----
const FEEDS = [
  { src: "web/f2.png", box: [35, 50, 30, 22], label: "person 0.94", color: "#FF3B2E" },
  { src: "web/f3.png", box: [43, 23, 14, 42], label: "door closed 0.88", color: "#2563EB" },
  { src: "web/f4.png", box: [66, 30, 10, 34], label: "gas cylinder 0.76", color: "#D99400" },
];
function Detect({ t }: { t: number }) {
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <Column>
        <Title t={t} at={c.detect}>
          Object detection
        </Title>
        <div style={{ display: "flex", alignItems: "center", gap: 20, opacity: rise(t, c.yolo, 0.4) }}>
          <span style={{ fontFamily: HAND, fontSize: 64, color: INK }}>YOLO26</span>
          <Logo src="ultralytics.svg" height={40} color="native" />
        </div>
        <Chip t={t} at={c.tuned}>
          fine-tuned, custom dataset
        </Chip>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <Chip t={t} at={c.humans} accent size={34}>
            humans
          </Chip>
          <Chip t={t} at={c.fires} accent size={34}>
            fires
          </Chip>
          <Chip t={t} at={c.doors} accent size={34}>
            closed doors
          </Chip>
        </div>
      </Column>
      {FEEDS.map((f, i) => {
        const p = rise(t, c.yolo + 0.3 + i * 0.5, 0.45);
        const bp = rise(t, c.yolo + 0.8 + i * 0.5, 0.3);
        return (
          <div
            key={f.src}
            style={{
              position: "absolute",
              left: 820 + (i % 2) * 520,
              top: 150 + i * 270,
              width: 500,
              height: 300,
              borderRadius: 12,
              overflow: "hidden",
              boxShadow: "0 14px 36px rgba(0,0,0,0.25), 0 0 0 3px #1e1e1e",
              opacity: p,
              transform: `rotate(${i % 2 ? 1.5 : -1.2}deg) translateY(${(1 - p) * 30}px)`,
              background: "#222",
            }}
          >
            <Img src={staticFile(f.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            <div
              style={{
                position: "absolute",
                left: `${f.box[0]}%`,
                top: `${f.box[1]}%`,
                width: `${f.box[2]}%`,
                height: `${f.box[3]}%`,
                border: `3px solid ${f.color}`,
                opacity: bp,
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: -26,
                  left: -3,
                  background: f.color,
                  color: "#fff",
                  fontFamily: "monospace",
                  fontSize: 15,
                  fontWeight: 700,
                  padding: "2px 6px",
                  whiteSpace: "nowrap",
                }}
              >
                {f.label}
              </span>
            </div>
          </div>
        );
      })}
      <div style={{ position: "absolute", left: 110, bottom: 34, fontFamily: HAND, fontSize: 20, color: "#777", opacity: rise(t, c.yolo, 0.4) }}>
        Jocher et al., Ultralytics YOLO26, arXiv:2606.03748 (2026) · Sapkota et al., arXiv:2509.25164 (2025)
      </div>
    </AbsoluteFill>
  );
}

// ---- Beat 7: what's next ----
function Roadmap({ t }: { t: number }) {
  const items = [
    { at: c.comms + 0.2, label: "Two-way survivor comms", accent: true },
    { at: c.stream, label: "Faster data streams", accent: true },
    { at: c.extra, label: "Hardware per environment" },
    { at: c.extra + 0.6, label: "YOLO-World open-vocab detection" },
    { at: c.extra + 1.2, label: "Ground robots: Boston Dynamics Spot" },
  ];
  const crew = 1 - rise(t, c.extra + 1.0, 0.4);
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      <div style={{ position: "absolute", left: 110, top: 150 }}>
        <div style={{ fontFamily: HAND, fontSize: 88, color: INK }}>Next up</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 30, marginTop: 44 }}>
          {items.map((it) => {
            const p = rise(t, it.at, 0.45);
            return (
              <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 20, opacity: p, transform: `translateX(${(1 - p) * -24}px)` }}>
                <svg width={34} height={34} viewBox="0 0 34 34">
                  <path
                    d="M6 18 L14 26 L29 8"
                    fill="none"
                    stroke={C.orange}
                    strokeWidth={4}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    pathLength={1}
                    strokeDasharray="1 1"
                    strokeDashoffset={1 - p}
                  />
                </svg>
                <span style={{ fontFamily: HAND, fontSize: it.accent ? 50 : 40, color: it.accent ? INK : "#444" }}>{it.label}</span>
              </div>
            );
          })}
        </div>
      </div>
      {/* While two-way comms and streaming are described: the live console today. */}
      <div style={{ opacity: crew }}>
        <Frame t={t} at={c.comms + 0.6} x={1080} y={230} w={740} h={420} tilt={1.5}>
          <Sequence from={sec(c.comms)} layout="none">
            <OffthreadVideo src={staticFile("rec/floor.mp4")} startFrom={sec(40)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </Sequence>
        </Frame>
      </div>
      {[
        { src: "stock/spot_02.jpg", x: 1080, y: 150, r: -4 },
        { src: "stock/spot_01.jpg", x: 1300, y: 470, r: 3 },
      ].map((ph, i) => {
        const p = rise(t, c.extra + 1.2 + i * 0.25, 0.5);
        return (
          <div
            key={ph.src}
            style={{
              position: "absolute",
              left: ph.x,
              top: ph.y,
              width: 560,
              height: 400,
              padding: 14,
              background: "#fff",
              boxShadow: "0 14px 34px rgba(0,0,0,0.18)",
              transform: `rotate(${ph.r}deg) translateY(${(1 - p) * 40}px)`,
              opacity: p,
            }}
          >
            <Img src={staticFile(ph.src)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          </div>
        );
      })}
      <div style={{ position: "absolute", left: 110, bottom: 34, fontFamily: HAND, fontSize: 19, color: "#777", opacity: rise(t, c.extra + 0.6, 0.4) }}>
        Cheng et al., “YOLO-World,” arXiv:2401.17270 (2024) · Spot photos: USAF (public domain), Jonte (CC BY-SA 4.0)
      </div>
    </AbsoluteFill>
  );
}

const BEATS: [number, number, (p: { t: number }) => React.ReactNode][] = [
  [c.stack, c.align, Stack],
  [c.align, c.radio, Align],
  [c.radio, c.fly, Radio],
  [c.fly, c.detect, Fly],
  [c.detect, c.next, Detect],
  [c.next, PART_C_LEN, Roadmap],
];

export function PartC() {
  const t = useT(0);
  return (
    <AbsoluteFill style={{ background: PAPER }}>
      {BEATS.map(([a, b, Beat], i) => {
        if (t < a - 0.15 || t > b + 0.15) return null;
        const o = i === 0 ? 1 : fadeIn(t, a - 0.12, 0.24);
        return (
          <AbsoluteFill key={i} style={{ opacity: o }}>
            <Beat t={t} />
          </AbsoluteFill>
        );
      })}
      <Sfx src="whoosh.wav" at={c.fly - 0.2} start={0} volume={0.18} />
      <Sfx src="tone.wav" at={c.yolo} start={0} volume={0.25} />
      <Sfx src="tone.wav" at={c.extra + 1.2} start={0} volume={0.25} />
      <AbsoluteFill style={{ background: "#000", opacity: interpolate(t, [PART_C_LEN - 0.3, PART_C_LEN], [0, 1], clamp) }} />
    </AbsoluteFill>
  );
}
