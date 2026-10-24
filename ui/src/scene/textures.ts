import * as THREE from "three";

/**
 * Procedural 1 m tiles per material. Textures are mostly light gray detail: the material's
 * color comes from the per-instance tint, so the master map can tint the same textures
 * with the colors it actually observed.
 */
const SIZE = 64;

type Painter = (g: CanvasRenderingContext2D, rnd: () => number) => void;

function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function noise(g: CanvasRenderingContext2D, rnd: () => number, lo: number, hi: number, n = 900, size = 2): void {
  for (let i = 0; i < n; i++) {
    const v = Math.floor(lo + (hi - lo) * rnd());
    g.fillStyle = `rgb(${v},${v},${v})`;
    g.fillRect(rnd() * SIZE, rnd() * SIZE, size, size);
  }
}

function base(g: CanvasRenderingContext2D, v: number): void {
  g.fillStyle = `rgb(${v},${v},${v})`;
  g.fillRect(0, 0, SIZE, SIZE);
}

const PAINTERS: Record<string, Painter> = {
  asphalt: (g, r) => {
    base(g, 215);
    noise(g, r, 160, 255, 1400, 2);
  },
  concrete: (g, r) => {
    base(g, 232);
    noise(g, r, 195, 255, 1200, 2);
    g.strokeStyle = "rgba(0,0,0,0.12)";
    g.strokeRect(0.5, 0.5, SIZE - 1, SIZE - 1);
  },
  brick: (g, r) => {
    base(g, 250);
    const rows = 4;
    const h = SIZE / rows;
    for (let row = 0; row < rows; row++) {
      const off = row % 2 ? SIZE / 4 : 0;
      for (let c = -1; c < 2; c++) {
        const v = 205 + Math.floor(r() * 50);
        g.fillStyle = `rgb(${v},${v},${v})`;
        g.fillRect(off + c * (SIZE / 2) + 2, row * h + 2, SIZE / 2 - 4, h - 4);
      }
    }
    noise(g, r, 170, 240, 300, 1);
  },
  floor: (g, r) => {
    base(g, 236);
    noise(g, r, 215, 250, 500, 2);
    g.strokeStyle = "rgba(0,0,0,0.18)";
    g.lineWidth = 2;
    g.strokeRect(1, 1, SIZE - 2, SIZE - 2);
  },
  roof: (g) => {
    base(g, 230);
    for (let x = 0; x < SIZE; x += 8) {
      g.fillStyle = "rgba(0,0,0,0.16)";
      g.fillRect(x, 0, 3, SIZE);
      g.fillStyle = "rgba(255,255,255,0.25)";
      g.fillRect(x + 4, 0, 2, SIZE);
    }
  },
  steel: (g, r) => {
    base(g, 225);
    noise(g, r, 205, 245, 300, 3);
    g.strokeStyle = "rgba(0,0,0,0.3)";
    g.lineWidth = 2;
    g.strokeRect(3, 3, SIZE - 6, SIZE - 6);
    g.fillStyle = "rgba(0,0,0,0.4)";
    for (const [x, y] of [[8, 8], [56, 8], [8, 56], [56, 56]]) g.fillRect(x - 2, y - 2, 4, 4);
  },
  shelf: (g) => {
    base(g, 70);
    for (let y = 2; y < SIZE; y += 16) {
      g.fillStyle = "rgb(250,250,250)";
      g.fillRect(0, y, SIZE, 5);
    }
    g.fillStyle = "rgb(235,235,235)";
    g.fillRect(0, 0, 5, SIZE);
    g.fillRect(SIZE - 5, 0, 5, SIZE);
  },
  tank: (g) => {
    const grad = g.createLinearGradient(0, 0, SIZE, 0);
    grad.addColorStop(0, "rgb(190,190,190)");
    grad.addColorStop(0.45, "rgb(255,255,255)");
    grad.addColorStop(1, "rgb(170,170,170)");
    g.fillStyle = grad;
    g.fillRect(0, 0, SIZE, SIZE);
    g.fillStyle = "rgba(0,0,0,0.25)";
    g.fillRect(0, 30, SIZE, 3);
  },
  debris: (g, r) => {
    base(g, 200);
    for (let i = 0; i < 40; i++) {
      const v = 120 + Math.floor(r() * 135);
      g.fillStyle = `rgb(${v},${v},${v})`;
      g.beginPath();
      const x = r() * SIZE;
      const y = r() * SIZE;
      g.moveTo(x, y);
      for (let k = 0; k < 4; k++) g.lineTo(x + (r() - 0.5) * 22, y + (r() - 0.5) * 22);
      g.fill();
    }
  },
  doorframe: (g) => {
    base(g, 255);
    g.fillStyle = "rgb(40,40,40)";
    for (let k = -SIZE; k < SIZE * 2; k += 22) {
      g.beginPath();
      g.moveTo(k, 0);
      g.lineTo(k + 11, 0);
      g.lineTo(k + 11 - SIZE, SIZE);
      g.lineTo(k - SIZE, SIZE);
      g.fill();
    }
  },
  glass: (g) => {
    base(g, 225);
    g.fillStyle = "rgba(255,255,255,0.7)";
    g.beginPath();
    g.moveTo(10, SIZE);
    g.lineTo(30, SIZE);
    g.lineTo(SIZE, 18);
    g.lineTo(SIZE, 0);
    g.fill();
    g.strokeStyle = "rgba(0,0,0,0.35)";
    g.lineWidth = 3;
    g.strokeRect(1.5, 1.5, SIZE - 3, SIZE - 3);
  },
  wood: (g, r) => {
    base(g, 235);
    for (let y = 0; y < SIZE; y += 3) {
      const v = 200 + Math.floor(r() * 55);
      g.fillStyle = `rgb(${v},${v},${v})`;
      g.fillRect(0, y + Math.sin(y) * 1.5, SIZE, 2);
    }
  },
  survivor: (g) => {
    base(g, 255);
  },
  container: (g) => {
    base(g, 225);
    for (let x = 0; x < SIZE; x += 10) {
      g.fillStyle = "rgba(255,255,255,0.45)";
      g.fillRect(x, 0, 4, SIZE);
      g.fillStyle = "rgba(0,0,0,0.18)";
      g.fillRect(x + 6, 0, 2, SIZE);
    }
  },
};

const cache = new Map<string, THREE.Texture>();

export function materialTexture(name: string): THREE.Texture {
  const hit = cache.get(name);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const g = canvas.getContext("2d")!;
  (PAINTERS[name] ?? PAINTERS.concrete)(g, rng(name.length * 7919 + name.charCodeAt(0)));
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.magFilter = THREE.NearestFilter;
  tex.anisotropy = 4;
  cache.set(name, tex);
  return tex;
}
