export type Vec3 = [number, number, number];

export interface Box {
  cx: number;
  cy: number;
  sx: number;
  sy: number;
  h: number;
  yaw: number;
  tilt: number;
  kind: "building" | "collapsed" | "rubble";
}

export interface Survivor {
  id: number;
  x: number;
  y: number;
  z: number;
}

export interface WorldInfo {
  size: number;
  cell: number;
  n: number;
  base: [number, number];
  boxes: Box[];
  survivors: Survivor[];
}

export interface SimConfig {
  seed: number;
  n_drones: number;
  wind_speed: number;
  wind_dir_deg: number;
  gust_strength: number;
  link_latency: number;
  link_dropout: number;
  n_survivors: number;
  battery_wh: number;
  cam_pitch_deg: number;
  cam_hfov_deg: number;
  cam_vfov_deg: number;
  cam_range: number;
  [key: string]: number;
}

export type Mode =
  | "idle"
  | "takeoff"
  | "explore"
  | "investigate"
  | "rtb"
  | "landing"
  | "charging"
  | "crashed"
  | "done";

export interface DroneState {
  id: number;
  p: Vec3;
  q: [number, number, number, number]; // w, x, y, z
  v: Vec3;
  soc: number;
  power: number;
  throttle: number;
  mode: Mode;
  avoiding: boolean;
  holding: boolean;
  crashed: boolean;
  grounded: boolean;
  cam_on: boolean;
  agl: number;
  cruise_alt: number;
  target: Vec3 | null;
  path: Vec3[];
  link_age: number | null;
}

export interface Metrics {
  t: number;
  coverage: number;
  found: number;
  survivors: number;
  candidates: number;
  airborne: number;
  crashed: number;
  avg_soc: number;
  uplink_kb: number;
  packet_loss: number;
  wind: [number, number];
  mission_done: boolean;
  mean_age: number;
  stale_frac: number;
  running: boolean;
  speed: number;
  rtf: number;
}

export interface Candidate {
  id: number;
  x: number;
  y: number;
  n: number;
  confirmed: boolean;
  dismissed: boolean;
  drone: number | null;
}

export interface SimEvent {
  t: number;
  text: string;
  level: "info" | "warn" | "error" | "success";
}

export interface MapCells {
  idx: number[];
  s: number[];
  h: number[];
}

export type HistoryPoint = [number, number, number]; // t, coverage, confirmed

export interface WorldMessage {
  type: "world";
  world: WorldInfo;
  config: SimConfig;
  pads: [number, number][];
}

export interface StateMessage {
  type: "state";
  drones: DroneState[];
  metrics: Metrics;
  map: MapCells;
  candidates: Candidate[];
  found: number[];
  frontiers: [number, number, number][]; // x, y, gain
  events: SimEvent[];
  history: HistoryPoint | null;
  seen?: string; // base64 uint16 last-seen grid, sent at 2 Hz
}

export interface SnapshotMessage extends Omit<StateMessage, "type" | "history"> {
  type: "snapshot";
  history: HistoryPoint[];
}

export type ServerMessage = WorldMessage | StateMessage | SnapshotMessage;

export interface CameraModel {
  pitch: number; // radians below horizon
  tanH: number;
  tanV: number;
  range: number;
}

export function cameraModel(cfg: SimConfig | null): CameraModel {
  const deg = Math.PI / 180;
  return {
    pitch: (cfg?.cam_pitch_deg ?? 35) * deg,
    tanH: Math.tan(((cfg?.cam_hfov_deg ?? 90) * deg) / 2),
    tanV: Math.tan(((cfg?.cam_vfov_deg ?? 60) * deg) / 2),
    range: cfg?.cam_range ?? 60,
  };
}

/** Heading (rotation about +z) from a server quaternion [w, x, y, z]. */
export function yawOf(q: [number, number, number, number]): number {
  const [w, x, y, z] = q;
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}

export const MODE_COLORS: Record<Mode, string> = {
  idle: "#8b93a7",
  takeoff: "#5ec8ff",
  explore: "#3ddc97",
  investigate: "#ffb020",
  rtb: "#b48cff",
  landing: "#8f7dff",
  charging: "#4a90e2",
  crashed: "#ff4d4f",
  done: "#9be7c4",
};
