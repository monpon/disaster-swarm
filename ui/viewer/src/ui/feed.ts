import { decodeB64, type FeedMessage } from "../types";

/** The selected drone's camera frames exactly as the master received them (RGB + depth). */
export class FeedPanel {
  private rgb = document.getElementById("feed-rgb") as HTMLCanvasElement;
  private depth = document.getElementById("feed-depth") as HTMLCanvasElement;
  private info = document.getElementById("feed-info")!;
  private title = document.getElementById("feed-title")!;
  private panel = document.getElementById("feed-panel")!;

  select(id: number | null): void {
    this.panel.classList.toggle("empty", id === null);
    this.title.textContent = id === null ? "Camera feed" : `Camera feed · D${id}`;
    if (id === null) this.info.textContent = "select a drone";
  }

  show(m: FeedMessage): void {
    if (m.t === null || !m.rgb || !m.depth || !m.w || !m.h) {
      this.info.textContent = "no frames received yet";
      return;
    }
    const { w, h } = m;
    const rgb = new Uint8Array(decodeB64(m.rgb));
    const depth = new Uint8Array(decodeB64(m.depth));
    for (const [canvas, fill] of [
      [this.rgb, (img: Uint8ClampedArray, i: number) => img.set([rgb[3 * i], rgb[3 * i + 1], rgb[3 * i + 2], 255], 4 * i)],
      [
        this.depth,
        (img: Uint8ClampedArray, i: number) => {
          const d = depth[i];
          // Near = warm, far = cool, no return = black.
          img.set(d === 0 ? [0, 0, 0, 255] : [d, Math.round(d * 0.6 + 40), 255 - d, 255], 4 * i);
        },
      ],
    ] as const) {
      canvas.width = w;
      canvas.height = h;
      const g = canvas.getContext("2d")!;
      const img = g.createImageData(w, h);
      for (let i = 0; i < w * h; i++) fill(img.data, i);
      g.putImageData(img, 0, 0);
    }
    const age = m.age ?? 0;
    this.info.innerHTML = `${w}×${h} mono · frame age <b class="${age > 2 ? "bad" : ""}">${age.toFixed(1)} s</b> · ` +
      `${m.jpeg_kb ?? "?"} kB JPEG · ${m.frames?.[0] ?? 0} recv · ${m.frames?.[1] ?? 0} lost · ${m.backlog ?? 0} queued on ESP<br>` +
      `left: camera as received · right: master's monocular depth estimate`;
  }
}
