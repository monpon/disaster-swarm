import { loadFont as loadSans } from "@remotion/google-fonts/IBMPlexSans";
import { loadFont as loadMono } from "@remotion/google-fonts/IBMPlexMono";

// Same type and palette as the Mayfly website so the video and product read as one brand.
export const sans = loadSans("normal", { weights: ["400", "500", "600", "700"], subsets: ["latin"] }).fontFamily;
export const mono = loadMono("normal", { weights: ["400", "500", "600"], subsets: ["latin"] }).fontFamily;

export const C = {
  ink: "#151515",
  ink2: "#2c2c2b",
  muted: "#5C5C59",
  faint: "#8a8a86",
  line: "#DEDEDB",
  panel: "#F4F4F3",
  map: "#ECECEA",
  white: "#FFFFFF",
  orange: "#FF5A1F",
  orangeEdge: "#C2410C",
  orangeTint: "#FFF1EA",
  person: "#D92D20",
  door: "#2563EB",
  hazard: "#D99400",
  ok: "#16A34A",
};

export const FPS = 30;
export const W = 1920;
export const H = 1080;
