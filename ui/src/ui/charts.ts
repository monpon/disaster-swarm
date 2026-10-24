import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { HistoryPoint } from "../types";

const MAX_POINTS = 2000;

/** Coverage % and confirmed survivors over mission time. */
export class MissionChart {
  private plot: uPlot;
  private t: number[] = [];
  private cov: number[] = [];
  private found: number[] = [];

  constructor(container: HTMLElement) {
    const opts: uPlot.Options = {
      width: container.clientWidth,
      height: 130,
      legend: { show: true, live: false },
      cursor: { show: false },
      scales: { x: { time: false }, cov: { range: [0, 100] }, found: { range: (_u, _min, max) => [0, Math.max(5, max)] } },
      axes: [
        { stroke: "#7f8aa3", grid: { stroke: "#1f2738", width: 1 }, ticks: { stroke: "#1f2738" }, size: 28, font: "10px Inter, system-ui", values: (_u, v) => v.map((s) => `${Math.round(s)}s`) },
        { scale: "cov", stroke: "#3ddc97", grid: { stroke: "#1f2738", width: 1 }, ticks: { show: false }, size: 34, font: "10px Inter, system-ui", values: (_u, v) => v.map((s) => `${s}%`) },
        { scale: "found", side: 1, stroke: "#ffb020", grid: { show: false }, ticks: { show: false }, size: 26, font: "10px Inter, system-ui" },
      ],
      series: [
        {},
        { label: "coverage", scale: "cov", stroke: "#3ddc97", width: 2, fill: "rgba(61,220,151,0.08)" },
        { label: "survivors", scale: "found", stroke: "#ffb020", width: 2, paths: uPlot.paths.stepped!({ align: 1 }) },
      ],
    };
    this.plot = new uPlot(opts, [[], [], []], container);
    new ResizeObserver(() => this.plot.setSize({ width: container.clientWidth, height: 130 })).observe(container);
  }

  reset(points: HistoryPoint[] = []): void {
    this.t = points.map((p) => p[0]);
    this.cov = points.map((p) => p[1] * 100);
    this.found = points.map((p) => p[2]);
    this.redraw();
  }

  push(p: HistoryPoint | null): void {
    if (!p) return;
    if (this.t.length && p[0] <= this.t[this.t.length - 1]) return;
    this.t.push(p[0]);
    this.cov.push(p[1] * 100);
    this.found.push(p[2]);
    if (this.t.length > MAX_POINTS) {
      // Decimate older history to keep the chart light.
      const n = this.t.length;
      const keep = (_: number, i: number) => i % 2 === 0 || i > n - 200;
      this.t = this.t.filter(keep);
      this.cov = this.cov.filter(keep);
      this.found = this.found.filter(keep);
    }
    this.redraw();
  }

  private redraw(): void {
    this.plot.setData([this.t, this.cov, this.found]);
  }
}
