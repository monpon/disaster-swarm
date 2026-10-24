import GUI from "lil-gui";
import type { SimSocket } from "../net";
import type { SimConfig } from "../types";
import type { Layers } from "../scene/drones";

export interface ViewSettings extends Layers {
  fog: boolean;
  truth: boolean;
  droneScale: number;
  syncCameras: boolean;
  frontiers: boolean;
  freshMap: boolean;
  freshFlight: boolean;
  staleAfter: number;
}

export interface ControlHooks {
  onView: (v: ViewSettings) => void;
  onOverview: () => void;
}

/** lil-gui panel: run controls, scenario parameters, and view layers. */
export class ControlPanel {
  readonly gui: GUI;
  readonly view: ViewSettings = {
    paths: true,
    footprints: true,
    links: true,
    trails: true,
    labels: true,
    fog: false,
    truth: true,
    droneScale: 6,
    syncCameras: true,
    frontiers: true,
    freshMap: true,
    freshFlight: false,
    staleAfter: 120,
  };
  private run = { speed: 1, playing: true };
  private scenario = {
    seed: 1,
    n_drones: 6,
    n_survivors: 15,
    wind_speed: 2,
    wind_dir_deg: 30,
    gust_strength: 1,
    link_latency: 0.2,
    link_dropout: 0.05,
    battery_wh: 15,
    cam_pitch_deg: 35,
  };
  private playCtrl;

  constructor(private net: SimSocket, hooks: ControlHooks) {
    this.gui = new GUI({ title: "Mission control", width: 280 });

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
    sim.add(actions, "randomize").name("🎲 New random city");

    const sc = this.gui.addFolder("Scenario (applies on reset)");
    sc.add(this.scenario, "seed", 0, 9999, 1);
    sc.add(this.scenario, "n_drones", 1, 16, 1).name("drones");
    sc.add(this.scenario, "n_survivors", 1, 40, 1).name("survivors");
    sc.add(this.scenario, "battery_wh", 5, 60, 1).name("battery (Wh)");
    sc.add(this.scenario, "cam_pitch_deg", 10, 80, 1).name("camera tilt (°)");
    sc.add(this.scenario, "wind_speed", 0, 10, 0.5).name("wind (m/s)");
    sc.add(this.scenario, "wind_dir_deg", 0, 360, 5).name("wind dir (°)");
    sc.add(this.scenario, "gust_strength", 0, 4, 0.25).name("gusts");
    sc.add(this.scenario, "link_latency", 0, 2, 0.05).name("link latency (s)");
    sc.add(this.scenario, "link_dropout", 0, 0.6, 0.01).name("packet loss");
    sc.close();

    const vw = this.gui.addFolder("View");
    const emit = () => hooks.onView(this.view);
    vw.add(this.view, "syncCameras").name("sync both cameras").onChange(emit);
    vw.add(this.view, "freshMap").name("freshness overlay (map)").onChange(emit);
    vw.add(this.view, "freshFlight").name("freshness overlay (flight)").onChange(emit);
    vw.add(this.view, "staleAfter", 15, 600, 5).name("red after (s)").onChange(emit);
    vw.add(this.view, "droneScale", 1, 15, 0.5).name("drone scale").onChange(emit);
    vw.add(this.view, "footprints").name("camera frustums").onChange(emit);
    vw.add(this.view, "paths").name("planned paths").onChange(emit);
    vw.add(this.view, "frontiers").name("frontier targets (map)").onChange(emit);
    vw.add(this.view, "links").name("uplinks to master").onChange(emit);
    vw.add(this.view, "trails").onChange(emit);
    vw.add(this.view, "labels").onChange(emit);
    vw.add(this.view, "truth").name("survivors (truth)").onChange(emit);
    vw.add(this.view, "fog").name("fog in flight view").onChange(emit);
    vw.add({ overview: () => hooks.onOverview() }, "overview").name("Overview camera");
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

  /** Reflect server state (e.g. after reconnecting or another client's change). */
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
