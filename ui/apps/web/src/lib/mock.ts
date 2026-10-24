/**
 * Demo mission data. Stands in for the edge server's live feed until the
 * console is wired to ROS 2. Map coordinates are pixels on the rendered scan
 * (public/assets/cloud.png at 1019x636), produced by scripts/render-assets.
 */

export type FindingKind = "person" | "door" | "blockage" | "hazard" | "opened";

export interface Finding {
  id: string;
  kind: FindingKind;
  title: string;
  detail: string;
  confidence: number | null;
  /** Pin anchor on the scan, if the finding is pinned. */
  pin?: [number, number];
}

export interface Drone {
  id: string;
  room: string;
  airframe: string;
  ip: string;
  battery: number;
  signal: number | null;
  altitude: number;
  status: "ready" | "calibrate" | "charging" | "offline";
  feed: string;
  /** Marker and ground-shadow positions on the scan. */
  marker?: [number, number];
  shadow?: [number, number];
  path?: string;
  holding?: boolean;
}

export const mission = {
  address: "418 Elm St",
  city: "Springfield, IL 62704",
  type: "Structural collapse",
  elapsed: "04:12",
  coverage: 62,
  roomsLeft: 2,
};

export const findings: Finding[] = [
  {
    id: "p1",
    kind: "person",
    title: "Person on floor",
    detail: "Bedroom 1, beside bed. Seen 3 min ago by D2.",
    confidence: 0.94,
    pin: [273.7, 345.7],
  },
  { id: "f2", kind: "door", title: "Closed door to garage", detail: "Hallway. D3 waiting for crew.", confidence: 0.88, pin: [645.6, 427.4] },
  { id: "f3", kind: "blockage", title: "Passage blocked by debris", detail: "Living room to kitchen. Not passable.", confidence: 0.81, pin: [583.1, 284.9] },
  { id: "f4", kind: "hazard", title: "Gas cylinder", detail: "Kitchen, by back door.", confidence: 0.76, pin: [737.8, 328.6] },
  { id: "f5", kind: "opened", title: "Front door opened", detail: "Entry A. Crew entered at 03:58.", confidence: null },
];

export const vitals = { breathing: 26, pulse: 118, movement: "Minimal", seenAt: "04:09" };

export const liveDrones: Drone[] = [
  {
    id: "D1",
    room: "Living room",
    airframe: "E58 with Raspberry Pi 4",
    ip: "192.168.4.11",
    battery: 71,
    signal: -58,
    altitude: 1.2,
    status: "ready",
    feed: "/assets/f1.png",
    marker: [421.8, 188.0],
    shadow: [421.8, 233.6],
    path: "346.1,440.7 402.1,408.4 474.5,362.8 537.0,326.7 484.4,303.9 451.5,246.9 421.8,188.0",
  },
  {
    id: "D2",
    room: "Bedroom 1",
    airframe: "E58 with Raspberry Pi 4",
    ip: "192.168.4.12",
    battery: 64,
    signal: -61,
    altitude: 0.9,
    status: "ready",
    feed: "/assets/f2.png",
    marker: [309.9, 317.2],
    shadow: [309.9, 351.4],
    path: "346.1,452.1 402.1,419.8 474.5,374.2 530.4,338.1 481.1,317.2 428.4,290.6 385.6,315.3 309.9,317.2",
  },
  {
    id: "D3",
    room: "Hallway",
    airframe: "E58 with Raspberry Pi 4",
    ip: "192.168.4.13",
    battery: 58,
    signal: -70,
    altitude: 1.4,
    status: "ready",
    feed: "/assets/f3.png",
    marker: [609.4, 360.9],
    shadow: [609.4, 414.1],
    path: "346.1,433.1 402.1,400.8 481.1,351.4 543.6,322.9 609.4,360.9",
    holding: true,
  },
  {
    id: "D4",
    room: "Kitchen",
    airframe: "E58 with Raspberry Pi 4",
    ip: "192.168.4.14",
    battery: 33,
    signal: -66,
    altitude: 1.1,
    status: "calibrate",
    feed: "/assets/f4.png",
    marker: [678.5, 309.6],
    shadow: [678.5, 351.4],
    path: "346.1,444.5 402.1,412.2 481.1,362.8 550.2,338.1 586.4,347.6 625.9,324.8 678.5,309.6",
  },
];

/** Detection boxes on each feed, in percent of the frame. */
export const feedBoxes: Record<string, { label: string; color: string; text: string; box: [number, number, number, number] }> = {
  D2: { label: "person 0.94", color: "#FF3B2E", text: "#fff", box: [11, 66, 45, 22] },
  D3: { label: "door closed 0.88", color: "#4D8BFF", text: "#fff", box: [43, 29, 14, 40] },
  D4: { label: "gas cylinder 0.76", color: "#F5B400", text: "#151515", box: [67, 41, 10, 39] },
};

export const fleet: Drone[] = [
  ...liveDrones.map((d) => ({ ...d, battery: { D1: 98, D2: 96, D3: 94, D4: 71 }[d.id] ?? d.battery, signal: { D1: -52, D2: -55, D3: -58, D4: -61 }[d.id] ?? d.signal })),
  {
    id: "D5",
    room: "",
    airframe: "Tello EDU with Pi Zero 2",
    ip: "192.168.4.15",
    battery: 34,
    signal: -49,
    altitude: 0,
    status: "charging",
    feed: "/assets/f1.png",
  },
  {
    id: "D6",
    room: "",
    airframe: "Custom 3-inch, Pi 5",
    ip: "Last seen Oct 19",
    battery: 0,
    signal: null,
    altitude: 0,
    status: "offline",
    feed: "/assets/f3.png",
  },
];

export const crewMessages = [
  { id: "m1", at: "04:02", from: "Capt. Reyes", text: "Living room is blocked. Other way in?" },
  {
    id: "m2",
    at: "04:03",
    from: null,
    text: "Go left from the front door, through the hallway, first door on the left. 7 m. Gas cylinder is in the kitchen, not on this route.",
  },
];

/** Timeline ticks, percent along the mission so far. */
export const timelineEvents = [
  { at: 10, color: "var(--color-person)" },
  { at: 26, color: "var(--color-door)" },
  { at: 44, color: "var(--color-ink)" },
  { at: 55, color: "var(--color-hazard)" },
  { at: 94, color: "var(--color-door)" },
];

export const addressResults = [
  { id: "a1", street: "418 Elm St", city: "Springfield, IL 62704", distance: "1.2 mi" },
  { id: "a2", street: "418 Elm Ave", city: "Chatham, IL 62629", distance: "9.8 mi" },
  { id: "a3", street: "418 W Elmwood Dr", city: "Springfield, IL 62711", distance: "4.1 mi" },
  { id: "a4", street: "1120 Monroe St", city: "Springfield, IL 62703", distance: "2.4 mi" },
];

export const recentMissions = [
  { id: "r1", place: "1120 Monroe St, Apt 3B", meta: "Welfare check, Oct 22" },
  { id: "r2", place: "Lincoln Square Offices, fl 4", meta: "Drill, Oct 19" },
  { id: "r3", place: "27 Walnut Ct", meta: "Gas leak, Oct 11" },
];

export const missionTypes = ["Structural collapse", "Earthquake", "Welfare check", "Gas leak", "Other"] as const;

export const detectionClasses = [
  { id: "person", label: "Person", color: "var(--color-person)", enabled: true, threshold: 0.6, speak: true },
  { id: "door", label: "Door, open or closed", color: "var(--color-door)", enabled: true, threshold: 0.5, speak: false },
  { id: "blockage", label: "Blocked passage", color: "var(--color-ink)", enabled: true, threshold: 0.55, speak: true },
  { id: "gas", label: "Gas cylinder", color: "var(--color-hazard)", enabled: true, threshold: 0.5, speak: true },
  { id: "fire", label: "Fire and smoke", color: "#c6c6c2", enabled: false, threshold: 0.7, speak: false },
];

export const edgeServices = [
  { name: "Mapping (visual SLAM)", load: "4 streams, 1.8M points", status: "running" },
  { name: "Object detection", load: "22 ms per frame", status: "running" },
  { name: "Collision avoidance", load: "50 Hz, 0 conflicts", status: "running" },
  { name: "Voice agent", load: "1.4 s reply", status: "degraded" },
  { name: "ROS 2 bridge", load: "4 drones, 31 ms", status: "running" },
] as const;
