import GUI from "lil-gui";
/** What the panel needs from the data source: a way to send commands (websocket or SpacetimeDB). */
type SimSocket = { control(cmd: string, extra?: Record<string, unknown>): void };
import type { SimConfig } from "../types";
import type { Layers } from "../scene/drones";
import type { ColorMode } from "../scene/mapview";

export type ViewMode = "real" | "map" | "split" | "plan";

export interface ViewSettings extends Layers {
  view: ViewMode;
  floor: string; // "all" | "roof off" | "F1".."Fn"
  demoClean: boolean; // demo render: the building's ideal geometry, revealed where the swarm has scanned
  mapColor: ColorMode;
  staleAfter: number;
  droneScale: number;
  pointSize: number;
  smoothed: boolean;
  mapRender: "auto" | "points" | "surface" | "both";
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

/** Building types the generator offers (the server's PRESETS in sim/disaster_sim/config.py). */
const BUILDINGS: Record<string, { label: string; desc: string; survivors: number }> = {
  factory: { label: "Factory", survivors: 20, desc: "3 floors, rooms + machinery hall, shafts, a blocked dock, a collapsed corner" },
  warehouse: { label: "Warehouse", survivors: 16, desc: "1 tall floor, a few huge bays packed with shelving, loading docks" },
  hangar: { label: "Hangar", survivors: 12, desc: "one enormous open hall, 14 m ceiling, machinery, no interior walls" },
  office: { label: "Office block", survivors: 24, desc: "4 floors of small rooms and corridors, many broken windows" },
  hospital: { label: "Hospital", survivors: 24, desc: "2 floors, dense ward rooms off corridors, tight doorways" },
  collapsed: { label: "Collapsed factory", survivors: 20, desc: "after a quake: holes through floors, rubble, several blocked entries" },
};

/** lil-gui panel: run controls, scenario parameters, and view layers. */
export class ControlPanel {
  readonly gui: GUI;
  readonly view: ViewSettings = {
    view: "split",
    floor: "all",
    demoClean: false,
    mapColor: "texture",
    staleAfter: 120,
    droneScale: 2.5,
    pointSize: 0.3,
    smoothed: true,
    mapRender: "auto",
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
    preset: "factory",
    n_drones: 16,
    n_survivors: 20,
    known_outline: true,
    plan_assist: false,
    battery_wh: 2,
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

    // What to map and with how many drones. Everything here applies when you press "Apply and restart".
    const ms = this.gui.addFolder("Mission setup");
    const about = { text: BUILDINGS[this.scenario.preset].desc };
    const aboutCtrl = ms.add(about, "text").name("about").disable();
    ms.add(this.scenario, "preset", Object.fromEntries(Object.entries(BUILDINGS).map(([k, v]) => [v.label, k])))
      .name("building type")
      .onChange((k: string) => {
        about.text = BUILDINGS[k].desc;
        this.scenario.n_survivors = BUILDINGS[k].survivors;
        aboutCtrl.updateDisplay();
        this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
      });
    ms.add(this.scenario, "n_drones", 1, 32, 1).name("number of drones");
    ms.add(this.scenario, "n_survivors", 1, 40, 1).name("survivors");
    ms.add(this.scenario, "known_outline").name("master knows outline");
    ms.add(this.scenario, "plan_assist").name("building plan given (openings known)");
    ms.add({
      demo: () => {
        this.scenario.known_outline = true;
        this.scenario.plan_assist = true;
        this.scenario.battery_wh = 8;
        this.view.demoClean = true;
        this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
        emit();
        this.reset();
        this.run.speed = 8;
        net.control("speed", { value: 8 });
      },
    }, "demo").name("▶ Demo preset (plan-assisted + clean render)");
    ms.add(this.scenario, "seed", 0, 9999, 1).name("random seed");
    ms.add({ apply: () => this.reset() }, "apply").name("↺ Apply and restart");

    const sc = this.gui.addFolder("Conditions (applies on reset)");
    sc.add(this.scenario, "battery_wh", 0.5, 10, 0.5).name("battery (Wh)");
    sc.add(this.scenario, "wind_speed", 0, 10, 0.5).name("wind (m/s)");
    sc.add(this.scenario, "wind_dir_deg", 0, 360, 5).name("wind dir (°)");
    sc.add(this.scenario, "gust_strength", 0, 4, 0.25).name("gusts");
    sc.add(this.scenario, "link_dropout", 0, 0.5, 0.01).name("packet loss");
    sc.close();

    const vw = this.gui.addFolder("View");
    vw.add(this.view, "view", { "Real building": "real", "Master map": "map", "Split": "split", "Floor plan (2D, live)": "plan" }).name("view (Tab)").onChange(emit);
    this.floorCtrl = vw.add(this.view, "floor", ["all", "roof off", "F1", "F2", "F3"]).name("cutaway (F)").onChange(emit);
    vw.add(this.view, "mapColor", { "Texture (observed color)": "texture", "Scan quality": "quality", "Freshness": "freshness", "Confidence (passes / roughness)": "confidence" })
      .name("map coloring (C)")
      .onChange(emit);
    vw.add(this.view, "staleAfter", 15, 600, 5).name("stale after (s)").onChange(emit);
    vw.add(this.view, "mapRender", { "Auto (surface when available)": "auto", "Points": "points", "Surface": "surface", "Surface + points": "both" })
      .name("map render")
      .onChange(emit);
    vw.add(this.view, "demoClean").name("DEMO: clean model (revealed by scan)").onChange(emit);
    vw.add(this.view, "smoothed").name("smoothed cloud (off = raw)").onChange(emit);
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
        if (k in cfg) (this.scenario as Record<string, unknown>)[k] = cfg[k];
      }
    }
    this.run.playing = running;
    this.run.speed = speed;
    this.syncPlayLabel();
    this.gui.controllersRecursive().forEach((c) => c.updateDisplay());
  }
}
