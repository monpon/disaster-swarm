import GUI from "lil-gui";
import type { SimSocket } from "../net";
import type { SimConfig } from "../types";
import type { Layers } from "../scene/drones";
import type { ColorMode } from "../scene/mapview";

export type ViewMode = "real" | "map" | "split";

export interface ViewSettings extends Layers {
  view: ViewMode;
  floor: string; // "all" | "roof off" | "F1".."Fn"
  mapColor: ColorMode;
  staleAfter: number;
  droneScale: number;
  pointSize: number;
  links: boolean;
  mesh: boolean;
  shell: boolean;
  targets: boolean;
  entries: boolean;
  survivorsTruth: boolean;
}

export interface ControlHooks {
  onView: (v: ViewSettings) => void;
  onOverview: () => void;
}

/** lil-gui panel: run controls, scenario parameters, and view layers. */
export class ControlPanel {
  readonly gui: GUI;
  readonly view: ViewSettings = {
    view: "split",
    floor: "all",
    mapColor: "texture",
    staleAfter: 120,
    droneScale: 2.5,
    pointSize: 0.3,
    paths: true,
    frustums: true,
    frustumDepth: 5,
    trails: true,
    labels: true,
    links: true,
    mesh: true,
    shell: true,
    targets: true,
    entries: true,
    survivorsTruth: true,
  };
  private run = { speed: 1, playing: true };
  private scenario = {
    seed: 1,
    n_drones: 16,
    n_survivors: 20,
    battery_wh: 20,
    wind_speed: 2,
    wind_dir_deg: 30,
    gust_strength: 0.8,
    link_dropout: 0.02,
  };
  private playCtrl;
  private floorCtrl;

  constructor(private net: SimSocket, private hooks: ControlHooks) {
    this.gui = new GUI({ title: "Mission control", width: 270 });
    const emit = () => hooks.onView(this.view);

    const sim = this.gui.addFolder("Simulation");
    const actions = {
      playPause: () => this.togglePlay(),
      step: () => net.control("step", { seconds: 0.5 }),
      reset: () => this.reset(),
      randomize: () => {
        this.scenario.seed = Math.floor(Math.random() * 10000);
        this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
        this.reset();
      },
    };
    this.playCtrl = sim.add(actions, "playPause").name("⏸ Pause");
    sim.add(this.run, "speed", [0.25, 0.5, 1, 2, 4, 8]).name("Speed ×").onChange((v: number) => net.control("speed", { value: v }));
    sim.add(actions, "step").name("Step 0.5 s");
    sim.add(actions, "reset").name("↺ Reset mission");
    sim.add(actions, "randomize").name("🎲 New random building");

    const sc = this.gui.addFolder("Scenario (applies on reset)");
    sc.add(this.scenario, "seed", 0, 9999, 1);
    sc.add(this.scenario, "n_drones", 1, 32, 1).name("drones");
    sc.add(this.scenario, "n_survivors", 1, 40, 1).name("survivors");
    sc.add(this.scenario, "battery_wh", 5, 60, 1).name("battery (Wh)");
    sc.add(this.scenario, "wind_speed", 0, 10, 0.5).name("wind (m/s)");
    sc.add(this.scenario, "wind_dir_deg", 0, 360, 5).name("wind dir (°)");
    sc.add(this.scenario, "gust_strength", 0, 4, 0.25).name("gusts");
    sc.add(this.scenario, "link_dropout", 0, 0.5, 0.01).name("packet loss");
    sc.close();

    const vw = this.gui.addFolder("View");
    vw.add(this.view, "view", { "Real building": "real", "Master map": "map", "Split": "split" }).name("view (Tab)").onChange(emit);
    this.floorCtrl = vw.add(this.view, "floor", ["all", "roof off", "F1", "F2", "F3"]).name("cutaway (F)").onChange(emit);
    vw.add(this.view, "mapColor", { "Texture (observed color)": "texture", "Scan quality": "quality", "Freshness": "freshness" })
      .name("map coloring (C)")
      .onChange(emit);
    vw.add(this.view, "staleAfter", 15, 600, 5).name("stale after (s)").onChange(emit);
    vw.add(this.view, "pointSize", 0.05, 1, 0.05).name("map point size (m)").onChange(emit);
    vw.add(this.view, "droneScale", 1, 8, 0.5).name("drone scale").onChange(emit);
    vw.add(this.view, "frustums").name("camera frustums").onChange(emit);
    vw.add(this.view, "frustumDepth", 1, 25, 0.5).name("frustum depth (m)").onChange(emit);
    vw.add(this.view, "paths").name("planned paths").onChange(emit);
    vw.add(this.view, "links").name("routes to master").onChange(emit);
    vw.add(this.view, "mesh").name("peer-to-peer mesh").onChange(emit);
    vw.add(this.view, "trails").onChange(emit);
    vw.add(this.view, "labels").onChange(emit);
    vw.add(this.view, "shell").name("interior shell (map)").onChange(emit);
    vw.add(this.view, "targets").name("frontier targets (map)").onChange(emit);
    vw.add(this.view, "entries").name("entry points (map)").onChange(emit);
    vw.add(this.view, "survivorsTruth").name("survivors (truth)").onChange(emit);
    vw.add({ overview: () => hooks.onOverview() }, "overview").name("Overview camera (O)");
  }

  setFloors(n: number): void {
    const opts = ["all", "roof off", ...Array.from({ length: n }, (_, i) => `F${i + 1}`)];
    this.floorCtrl.options(opts).name("cutaway (F)").onChange(() => this.hooks.onView(this.view));
    if (!opts.includes(this.view.floor)) this.view.floor = "all";
    this.floorCtrl.updateDisplay();
  }

  cycle<K extends "view" | "floor" | "mapColor">(key: K, options: ViewSettings[K][]): void {
    const i = options.indexOf(this.view[key]);
    this.view[key] = options[(i + 1) % options.length];
    this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
    this.hooks.onView(this.view);
  }

  togglePlay(): void {
    this.run.playing = !this.run.playing;
    this.net.control(this.run.playing ? "play" : "pause");
    this.syncPlayLabel();
  }

  private syncPlayLabel(): void {
    this.playCtrl.name(this.run.playing ? "⏸ Pause" : "▶ Play");
  }

  reset(): void {
    this.net.control("reset", { config: this.scenario });
  }

  syncFromServer(cfg: SimConfig | null, running: boolean, speed: number): void {
    if (cfg) {
      for (const k of Object.keys(this.scenario) as (keyof typeof this.scenario)[]) {
        if (k in cfg) this.scenario[k] = cfg[k];
      }
    }
    this.run.playing = running;
    this.run.speed = speed;
    this.syncPlayLabel();
    this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
  }
}
