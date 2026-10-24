export type Vec3 = [number, number, number];

export interface PaletteEntry {
  id: number;
  name: string;
  rgb: [number, number, number];
}

export interface TrueEntry {
  kind: string;
  center: Vec3;
  normal: Vec3;
  w: number;
  h: number;
  blocked: boolean;
}

export interface Survivor {
  id: number;
  x: number;
  y: number;
  z: number;
}

export interface BuildingInfo {
  shape: Vec3;
  vox: string; // base64 zlib-compressed uint8 material ids, C-order [x][y][z]
  bbox: [number, number, number, number, number]; // x0, y0, x1, y1, roof z
  story: number;
  floors: number;
  palette: PaletteEntry[];
  entries: TrueEntry[];
  survivors: Survivor[];
  base: Vec3;
  pads: [number, number][];
}

export interface SimConfig {
  seed: number;
  n_drones: number;
  n_survivors: number;
  floors: number;
  wind_speed: number;
  wind_dir_deg: number;
  gust_strength: number;
  link_latency: number;
  link_dropout: number;
  battery_wh: number;
  cam_mount_tilt_deg: number;
  cam_hfov_deg: number;
  cam_vfov_deg: number;
  cam_range: number;
  proper_scan_range: number;
  [key: string]: number;
}

export type Mode =
  | "idle"
  | "takeoff"
  | "survey"
  | "wait"
  | "enter"
  | "explore"
  | "investigate"
  | "relay"
  | "rtb"
  | "landing"
  | "charging"
  | "crashed";

export interface DroneState {
  id: number;
  p: Vec3;
  q: [number, number, number, number]; // w, x, y, z
  v: Vec3;
  soc: number;
  power: number;
  throttle: number;
  mode: Mode;
  crashed: boolean;
  grounded: boolean;
  frozen: boolean;
  holding: boolean; // stopped at the edge of coverage by its own link reflex
  snr: number; // measured signal to its next hop (dB)
  slot: number | null; // relay post it occupies // ESP failsafe: lost the command link, sticks centered, holding on optical flow
  landing_auto: boolean; // battery nearly flat: stock firmware landing in place
  ep: Vec3; // master's VIO estimate of the position
  eq: [number, number, number, number]; // master's estimate of the attitude
  drift: number; // |estimate - truth| (m), for display only
  link: number; // Mbps end-to-end
  hops: number;
  route: number[]; // node ids from this drone to the base (-1)
  frames: [number, number]; // delivered, dropped
  backlog: number;
  path: Vec3[];
  serves: number | null;
}

export interface Metrics {
  t: number;
  phase: "scout" | "operate" | "verify" | "complete";
  explored: number;
  scanned: number;
  entries: number;
  entries_usable: number;
  found: number;
  survivors: number;
  candidates: number;
  airborne: number;
  crashed: number;
  relays: number;
  avg_soc: number;
  frames_ok: number;
  frames_dropped: number;
  radio_mb: number;
  mapped_voxels: number;
  wind: [number, number];
  drift: number; // mean VIO position error of airborne drones (m)
  verified: number; // fraction of interior surfaces seen from 2+ separate passes
  align_ok: number; // fraction of frames the master registered against its map
  align_mm: number; // mean size of that correction (mm)
  points: number;
  brakes: number; // emergency brakes from the live frame
  first_inside: number | null; // sim time the first drone got inside
  lost_events: number; // times a drone lost contact
  slots: number; // relay posts planned
  thumbs: number; // frames sent as thumbnails instead of dropped
  ext_cov: number; // share of the building exterior seen so far
  smoother: string; // "cuda" | "cpu"
  smooth_ms: number;
  mesh: { backend: string; tris: number; chunks: number; ms: number };
  rms_raw?: number; // map error vs the true surface (scoring only), raw / smoothed
  rms_smooth?: number;
  ok_raw?: number; // fraction of points within 10 cm
  ok_smooth?: number;
  running: boolean;
  speed: number;
  rtf: number;
  loop_ms: number;
  sys: {
    cpu: number; // whole machine, %
    proc_cpu: number; // this server, % of ONE core
    mem: number; // %
    mem_gb: number;
    mem_total_gb: number;
    gpu: number | null; // %
    gpu_mem: number | null;
    cores: number;
  };
}

export interface MapEntry {
  id: number;
  center: Vec3;
  normal: Vec3;
  w: number;
  h: number;
  side: string;
  blocked: boolean;
}

export interface Candidate {
  id: number;
  pos: Vec3;
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

/** Map voxel deltas: parallel base64 arrays. */
export interface MapDeltas {
  idx: string; // int32 flat voxel index (occupied voxels, new or changed)
  mat: string; // uint8 classified material
  rgb: string; // uint16 rgb565 mean observed color
  q: string; // uint8 best scan quality * 255
  free: string; // int32 voxels now observed free
  n: number;
  // Point updates (new points and refined ones): id, raw and smoothed position in POINT_UNIT
  // (5 cm) units, color, flags (bit0 hidden, bits1-2 confidence 0..3), roughness, pass count.
  uidx: string;
  upos: string;
  uspos: string;
  ucol: string;
  uflag: string;
  uresid: string;
  unpass: string;
  nu: number;
  ptotal: number;
  surf: SurfaceChunk[]; // changed mesh chunks
}

export interface SurfaceChunk {
  id: number;
  nv: number; // vertices (0 clears the chunk)
  v: string; // uint16 x,y,z in 1 cm units
  n: string; // int8 x,y,z normal per vertex (from the smoothed distance field)
  c: string; // uint8 r,g,b per vertex
  f: string; // triangle indices (uint16, or uint32 when `w`)
  w: boolean;
}

export interface SeenDeltas {
  idx: string; // int32
  t: string; // uint16 half-seconds + 1
}

export type HistoryPoint = [number, number, number, number]; // t, explored, scanned, confirmed

export interface WorldMessage {
  type: "world";
  building: BuildingInfo;
  materials: string[];
  config: SimConfig;
}

export interface StateMessage {
  type: "state";
  drones: DroneState[];
  metrics: Metrics;
  map: MapDeltas;
  entries: MapEntry[];
  candidates: Candidate[];
  found: number[];
  mesh: [number, number, number][]; // node a, node b (-1 = base), Mbps
  targets: [number, number, number, number][]; // x, y, z, kind (0 frontier, 1 surface)
  events: SimEvent[];
  history: HistoryPoint | null;
  seen?: SeenDeltas;
}

export interface SnapshotMessage extends Omit<StateMessage, "type" | "history"> {
  type: "snapshot";
  history: HistoryPoint[];
}

export interface FeedMessage {
  type: "feed";
  drone: number;
  t: number | null;
  age?: number;
  w?: number;
  h?: number;
  rgb?: string;
  depth?: string;
  frames?: [number, number];
  backlog?: number;
  jpeg_kb?: number;
}

export type ServerMessage = WorldMessage | StateMessage | SnapshotMessage | FeedMessage;

export interface CameraModel {
  tanH: number;
  tanV: number;
  range: number;
  tilt: number; // fixed mount tilt below the nose (rad)
}

export function cameraModel(cfg: SimConfig | null): CameraModel {
  const deg = Math.PI / 180;
  return {
    tanH: Math.tan(((cfg?.cam_hfov_deg ?? 90) * deg) / 2),
    tanV: Math.tan(((cfg?.cam_vfov_deg ?? 64) * deg) / 2),
    range: cfg?.cam_range ?? 25,
    tilt: (cfg?.cam_mount_tilt_deg ?? 0) * deg,
  };
}

/** Heading (rotation about +z) from a server quaternion [w, x, y, z]. */
export function yawOf(q: [number, number, number, number]): number {
  const [w, x, y, z] = q;
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}

export function decodeB64(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

export const MODE_COLORS: Record<Mode, string> = {
  idle: "#8b93a7",
  takeoff: "#5ec8ff",
  survey: "#4fd1c5",
  wait: "#a0aec0",
  enter: "#f6e05e",
  explore: "#3ddc97",
  investigate: "#ffb020",
  relay: "#ff7ad9",
  rtb: "#b48cff",
  landing: "#8f7dff",
  charging: "#4a90e2",
  crashed: "#ff4d4f",
};
