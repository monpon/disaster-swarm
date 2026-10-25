import type { DocumentInfo, MossClient } from "@inferedge/moss";

/**
 * Retrieval for the voice agent: what the mission knows (findings with their routes, the event log) plus Mayfly's
 * reference notes, searched with Moss when MOSS_PROJECT_ID and MOSS_PROJECT_KEY are set. Without them, or if Moss
 * fails, a keyword match over the same documents answers instead, so the agent works either way.
 */

export interface MissionDoc {
  id: string;
  text: string;
}

const INDEX = process.env.MOSS_INDEX ?? "mayfly-mission";

const REFERENCE: MissionDoc[] = [
  { id: "ref-detector", text: "Detector: a YOLO model trained for disaster response finds fire, smoke, people and doors in every drone camera frame. Each detection has a confidence from 0 to 1." },
  { id: "ref-threshold", text: "Minimum confidence per class: raising it means fewer false alarms but a higher chance of missing something; lowering it finds more but with more false alarms. For people, a miss is worse than a false alarm." },
  { id: "ref-vitals", text: "Camera vitals: when a drone holds on a person it estimates breathing and pulse from the camera. Needs visible skin and light. These are estimates for triage, never a medical assessment; a medic decides." },
  { id: "ref-review", text: "Human review: findings below the review threshold wait for the incident commander before they reach the crew." },
  { id: "ref-routes", text: "Routes: Mayfly finds the shortest way from an open entrance to a person through the mapped floor plan, avoiding walls and blocked openings. Stretches nobody has mapped yet are called out. Stairs are not on the map, so routes are per floor." },
  { id: "ref-limits", text: "Limits: cameras need light, so heavy smoke blinds the drones. The incident commander approves routes and can stop every drone at any time. Mayfly never steers drones by voice." },
  { id: "ref-triage", text: "Triage tiers on a survivor come from the vitals reading and urgency score; a survivor still reading vitals has no tier yet." },
];

export interface Hit {
  id: string;
  text: string;
  score: number;
}

let moss: MossClient | null = null;
let mossReady: Promise<void> | null = null;
let mossDown = false;
const synced = new Map<string, string>();

export const hasMoss = () => !!(process.env.MOSS_PROJECT_ID && process.env.MOSS_PROJECT_KEY) && !mossDown;

async function sync(docs: DocumentInfo[]): Promise<void> {
  // Loaded on first use: its ONNX runtime is a native binary that serverless hosts do not ship, and importing it at
  // the top would take every route down. If it fails to load, searchMission falls back to keyword search.
  if (!moss) {
    const { MossClient } = await import("@inferedge/moss");
    moss = new MossClient(process.env.MOSS_PROJECT_ID!, process.env.MOSS_PROJECT_KEY!);
  }
  const changed = docs.filter((d) => synced.get(d.id) !== d.text);
  if (!mossReady) {
    mossReady = (async () => {
      const existing = await moss!.listIndexes();
      if (!existing.some((i) => i.name === INDEX)) await moss!.createIndex(INDEX, docs);
      else if (changed.length) await moss!.addDocs(INDEX, changed);
      await moss!.loadIndex(INDEX);
      for (const d of docs) synced.set(d.id, d.text);
    })();
    mossReady.catch(() => (mossReady = null));
    return mossReady;
  }
  await mossReady;
  if (changed.length) {
    await moss.addDocs(INDEX, changed);
    await moss.loadIndex(INDEX);
    for (const d of changed) synced.set(d.id, d.text);
  }
}

const words = (s: string) => (s.toLowerCase().match(/[a-z0-9]+/g) ?? []).map((w) => (w.length > 3 ? w.replace(/s$/, "") : w));

const STOP = new Set(["the", "and", "how", "what", "does", "can", "you", "for", "get", "are", "with", "that", "this", "from", "was", "has", "have", "who", "where", "when", "any", "there"]);

function keyword(docs: MissionDoc[], query: string, topK: number): Hit[] {
  const asked = /\b(get to|reach|way to|directions?|navigate|path|go to)\b/i.test(query) ? `${query} route` : query;   // "how do I get to" asks for a route
  const q = new Set(words(asked).filter((w) => w.length > 2 && !STOP.has(w)));
  return docs
    .map((d) => {
      const dw = words(d.text);
      const hits = dw.filter((w) => q.has(w)).length;
      return { id: d.id, text: d.text, score: hits / Math.sqrt(dw.length + 1) };
    })
    .filter((h) => h.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);
}

/** Search the mission documents; `via` says which engine answered. */
export async function searchMission(mission: MissionDoc[], query: string, topK = 4): Promise<{ via: "moss" | "keyword"; hits: Hit[] }> {
  const docs = [...REFERENCE, ...mission];
  if (hasMoss()) {
    try {
      await sync(docs);
      const r = await moss!.query(INDEX, query, { topK });
      return { via: "moss", hits: r.docs.map((d) => ({ id: d.id, text: d.text, score: Math.round(d.score * 100) / 100 })) };
    } catch (e) {
      console.error("Moss failed, falling back to keyword search:", e);
      mossDown = true;
      setTimeout(() => (mossDown = false), 60_000);
    }
  }
  return { via: "keyword", hits: keyword(docs, query, topK) };
}
