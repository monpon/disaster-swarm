import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";
import events from "../data/events.json";
import { C, Logo, Sfx, Wordmark, clamp, interpolate, rise, sans, useT } from "../components/kit";
import { B } from "../timeline";

// The take is 1600x900 CSS px captured at 2x (75.6 s; scene starts in B). Card geometry on the 1920x1080 canvas:
const CARD = { x: 48, y: 112, w: 1520, h: 855 };
const K = CARD.w / 1600;

// Camera keyframes [take seconds, focus x, focus y (CSS px), zoom]. Repeated
// points are holds; the camera eases between consecutive points.
const KF: [number, number, number, number][] = [
  [0, 800, 450, 1],
  [21.0, 800, 450, 1],
  [21.6, 1358, 551, 1.7],
  [22.5, 1358, 551, 1.7],
  [23.1, 800, 450, 1],
  [23.3, 800, 450, 1],
  [23.8, 230, 450, 1.55],
  [26.1, 230, 450, 1.55],
  [26.6, 800, 450, 1],
  [26.8, 800, 450, 1],
  [27.2, 1416, 443, 1.9],
  [27.7, 1416, 500, 1.9],
  [28.1, 1416, 700, 1.6],
  [28.8, 1416, 700, 1.6],
  [29.6, 800, 450, 1],
  [35.7, 800, 450, 1],
  [36.1, 640, 800, 1.4],
  [39.9, 640, 800, 1.4],
  [40.6, 634, 360, 1.3],
  [45.4, 634, 360, 1.3],
  [46.0, 300, 560, 1.7],
  [47.9, 300, 560, 1.7],
  [48.5, 1408, 240, 2.0],
  [50.3, 1408, 240, 2.0],
  [50.9, 500, 380, 1.7],
  [52.6, 500, 380, 1.7],
  [53.2, 1408, 342, 2.3],
  [55.0, 1408, 342, 2.3],
  [55.8, 1340, 380, 1.55],
  [63.9, 1340, 380, 1.55],
  [64.6, 1348, 398, 2.1],
  [66.9, 1348, 398, 2.1],
  [67.5, 1408, 773, 1.9],
  [70.3, 1408, 773, 1.9],
  [71.3, 800, 450, 1],
  [75.6, 800, 450, 1],
];

const inOut = (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);

function camera(t: number) {
  let i = KF.findIndex((k) => k[0] > t);
  if (i === -1) return KF[KF.length - 1];
  if (i === 0) return KF[0];
  const a = KF[i - 1];
  const b = KF[i];
  const p = inOut((t - a[0]) / (b[0] - a[0]));
  // Interpolate zoom in log space so zoom speed feels even.
  const z = Math.exp(Math.log(a[3]) + (Math.log(b[3]) - Math.log(a[3])) * p);
  return [t, a[1] + (b[1] - a[1]) * p, a[2] + (b[2] - a[2]) * p, z] as const;
}

type Note = { from: number; to: number; title: string; items: { at: number; label: string; logo?: { src: string; at: number; height: number } }[] };
const NOTES: Note[] = [
  { from: B.s10, to: B.s11, title: "New mission", items: [{ at: 23.9, label: "Building" }, { at: 24.9, label: "Earthquake" }] },
  {
    from: B.s11,
    to: B.s12,
    title: "Setup",
    items: [
      { at: 26.8, label: "Floor plan" },
      { at: 27.3, label: "4 drones" },
      { at: 28.3, label: "Launch" },
    ],
  },
  {
    from: B.s12,
    to: B.s13,
    title: "Live",
    items: [
      { at: 31.5, label: "3D map" },
      { at: 32.1, label: "Feeds" },
      { at: 32.7, label: "Findings" },
    ],
  },
  {
    from: B.s13,
    to: B.s14,
    title: "Feeds",
    items: [
      { at: 36.0, label: "4 drones" },
      { at: 37.0, label: "4 rooms" },
      { at: 38.2, label: "Live detections", logo: { src: "ultralytics.svg", at: 38.7, height: 26 } },
    ],
  },
  {
    from: B.s14,
    to: B.s15,
    title: "3D map",
    items: [
      { at: 41.0, label: "One shared map" },
      { at: 42.0, label: "Drone paths" },
      { at: 46.1, label: "62% mapped" },
    ],
  },
  {
    from: B.s15,
    to: B.s16,
    title: "Survivor",
    items: [
      { at: 49.8, label: "Person on floor" },
      { at: 51.0, label: "On the map" },
      { at: 53.3, label: "Breathing + pulse", logo: { src: "presage.png", at: 54.0, height: 30 } },
    ],
  },
  {
    from: B.s16,
    to: B.s17,
    title: "Hazards",
    items: [
      { at: 59.9, label: "Blocked passage" },
      { at: 61.2, label: "Closed door" },
      { at: 62.4, label: "Gas cylinder" },
    ],
  },
  {
    from: B.s17,
    to: B.s18,
    title: "Crew",
    items: [
      { at: 65.6, label: "Route" },
      { at: 67.7, label: "Crew channel" },
    ],
  },
];

function Notes({ t }: { t: number }) {
  return (
    <div style={{ position: "absolute", left: CARD.x + CARD.w + 40, top: CARD.y + 96, width: 1920 - (CARD.x + CARD.w + 40) - 32 }}>
      {NOTES.map((n) => {
        const vis = rise(t, n.from + 0.2, 0.45) * (1 - rise(t, n.to - 0.35, 0.3));
        if (vis <= 0) return null;
        return (
          <div key={n.title} style={{ position: "absolute", inset: 0, opacity: vis }}>
            <div style={{ fontFamily: sans, fontWeight: 600, fontSize: 17, letterSpacing: "0.12em", textTransform: "uppercase", color: C.orange }}>
              {n.title}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 22, marginTop: 20 }}>
              {n.items.map((it) => {
                const p = rise(t, it.at, 0.45);
                return (
                  <div key={it.label} style={{ opacity: p, transform: `translateX(${(1 - p) * -16}px)` }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <div style={{ width: 9, height: 9, borderRadius: 2, background: C.orange, flexShrink: 0 }} />
                      <span style={{ fontFamily: sans, fontWeight: 600, fontSize: 27, letterSpacing: "-0.015em", color: C.ink, lineHeight: 1.15 }}>
                        {it.label}
                      </span>
                    </div>
                    {it.logo && (
                      <div
                        style={{
                          marginTop: 12,
                          marginLeft: 21,
                          opacity: rise(t, it.logo.at, 0.45),
                          transform: `translateY(${(1 - rise(t, it.logo.at, 0.45)) * 12}px)`,
                        }}
                      >
                        <Logo src={it.logo.src} height={it.logo.height} color="native" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Small tag on the vitals: the readings in this demo are not from a real person. */
function DemoTag({ t }: { t: number }) {
  const r = (events as { name: string; box?: { x: number; y: number; w: number; h: number } }[]).find((e) => e.name === "rect:vitals")?.box;
  if (!r) return null;
  const p = rise(t, 52.9, 0.35) * (1 - rise(t, 55.4, 0.3));
  return (
    <div
      style={{
        position: "absolute",
        left: r.x + r.w - 76,
        top: r.y - 4,
        padding: "1px 5px",
        borderRadius: 4,
        background: C.ink,
        color: C.white,
        fontFamily: sans,
        fontWeight: 600,
        fontSize: 8.5,
        letterSpacing: "0.04em",
        opacity: p,
      }}
    >
      DEMO DATA
    </div>
  );
}

export function PartB() {
  const t = useT(0);
  const [, cx, cy, z] = camera(t);
  const s = K * z;
  const tx = Math.min(0, Math.max(CARD.w - 1600 * s, CARD.w / 2 - cx * s));
  const ty = Math.min(0, Math.max(CARD.h - 900 * s, CARD.h / 2 - cy * s));
  const intro = interpolate(t, [0, 0.6], [0, 1], clamp);
  const clicks = (events as { name: string; t: number }[]).filter((e) => e.name === "click");
  return (
    <AbsoluteFill style={{ background: C.map }}>
      <div style={{ position: "absolute", left: CARD.x + CARD.w + 40, top: CARD.y, opacity: intro }}>
        <Wordmark size={34} />
      </div>
      <div
        style={{
          position: "absolute",
          left: CARD.x,
          top: CARD.y,
          width: CARD.w,
          height: CARD.h,
          borderRadius: 18,
          overflow: "hidden",
          background: C.white,
          boxShadow: `0 0 0 1px ${C.line}, 0 30px 80px rgba(0,0,0,0.12)`,
        }}
      >
        <div style={{ position: "absolute", left: 0, top: 0, width: 1600, height: 900, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}>
          <OffthreadVideo src={staticFile("rec/partB.mp4")} muted style={{ width: 1600, height: 900 }} />
          <DemoTag t={t} />
        </div>
      </div>
      <Notes t={t} />
      {clicks.map((c) => (
        <Sfx key={c.t} src="click.wav" at={c.t + 0.09} start={0} volume={0.35} />
      ))}
    </AbsoluteFill>
  );
}
