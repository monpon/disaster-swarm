import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { HistoryPoint } from "../types";

const MAX_POINTS = 2000;

/** Interior explored %, surfaces scanned % and confirmed survivors over mission time. */
export class MissionChart {
  private plot: uPlot;
  private t: number[] = [];
  private exp: number[] = [];
  private scan: number[] = [];
  private found: number[] = [];

  constructor(container: HTMLElement) {
    const opts: uPlot.Options = {
      width: container.clientWidth,
      height: 130,
      legend: { show: true, live: false },
      cursor: { show: false },
      scales: { x: { time: false }, pct: { range: [0, 100] }, found: { range: (_u, _min, max) => [0, Math.max(5, max)] } },
      axes: [
        { stroke: "#7f8aa3", grid: { stroke: "#1f2738", width: 1 }, ticks: { stroke: "#1f2738" }, size: 28, font: "10px Inter, system-ui", values: (_u, v) => v.map((s) => `${Math.round(s)}s`) },
        { scale: "pct", stroke: "#7f8aa3", grid: { stroke: "#1f2738", width: 1 }, ticks: { show: false }, size: 34, font: "10px Inter, system-ui", values: (_u, v) => v.map((s) => `${s}%`) },
        { scale: "found", side: 1, stroke: "#ffb020", grid: { show: false }, ticks: { show: false }, size: 26, font: "10px Inter, system-ui" },
      ],
      series: [
        {},
        { label: "explored", scale: "pct", stroke: "#5ec8ff", width: 2, fill: "rgba(94,200,255,0.06)" },
        { label: "scanned", scale: "pct", stroke: "#3ddc97", width: 2 },
        { label: "survivors", scale: "found", stroke: "#ffb020", width: 2, paths: uPlot.paths.stepped!({ align: 1 }) },
      ],
    };
    this.plot = new uPlot(opts, [[], [], [], []], container);
    new ResizeObserver(() => this.plot.setSize({ width: container.clientWidth, height: 130 })).observe(container);
  }

  reset(points: HistoryPoint[] = []): void {
    this.t = points.map((p) => p[0]);
    this.exp = points.map((p) => p[1] * 100);
    this.scan = points.map((p) => p[2] * 100);
    this.found = points.map((p) => p[3]);
    this.redraw();
  }

  push(p: HistoryPoint | null): void {
    if (!p) return;
    if (this.t.length && p[0] <= this.t[this.t.length - 1]) return;
    this.t.push(p[0]);
    this.exp.push(p[1] * 100);
    this.scan.push(p[2] * 100);
    this.found.push(p[3]);
    if (this.t.length > MAX_POINTS) {
      const n = this.t.length;
      const keep = (_: number, i: number) => i % 2 === 0 || i > n - 200;
      this.t = this.t.filter(keep);
      this.exp = this.exp.filter(keep);
      this.scan = this.scan.filter(keep);
      this.found = this.found.filter(keep);
    }
    this.redraw();
  }

  private redraw(): void {
    this.plot.setData([this.t, this.exp, this.scan, this.found]);
  }
}
