import { useSyncExternalStore } from "react";

import { detectionClasses } from "./mock";
import { store } from "./swarm";

/**
 * What the drones look for: one row per detector class, plus camera vitals and the human-review threshold. Shared by the
 * detection settings page and the voice agent, kept in the browser, and sent to the simulator when it is running.
 */
export type DetectionClass = (typeof detectionClasses)[number];

export interface DetectionSettings {
  classes: DetectionClass[];
  vitals: boolean;
  review: string;
}

export const reviewOptions = ["0.60", "0.70", "0.80", "0.90"];

export const defaultDetection: DetectionSettings = { classes: detectionClasses, vitals: true, review: "0.80" };

const KEY = "mayfly.detection";
let state = defaultDetection;
let loaded = false;
const listeners = new Set<() => void>();

function load(): void {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as Partial<DetectionSettings> | null;
    if (saved?.classes) state = { ...defaultDetection, ...saved };
  } catch {
    // private window or a stale shape: the defaults are fine
  }
}

export function getDetection(): DetectionSettings {
  load();
  return state;
}

/** Replace the settings: remembered in this browser, and pushed to the simulator if one is live. */
export function setDetection(next: DetectionSettings): void {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage blocked: the settings still hold for this session
  }
  if (store.getSnapshot().connected) store.command("detection", detectionCommand(next));
  for (const l of listeners) l();
}

/** The simulator's view of the settings: its detector only reports people, so the person row is what it acts on. */
export function detectionCommand(s: DetectionSettings) {
  const person = s.classes.find((c) => c.id === "person");
  return {
    person: { enabled: person?.enabled ?? true, threshold: person?.threshold ?? 0.45 },
    classes: s.classes.map(({ id, enabled, threshold }) => ({ id, enabled, threshold })),
    vitals: s.vitals,
  };
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useDetection(): DetectionSettings {
  return useSyncExternalStore(subscribe, getDetection, () => defaultDetection);
}
