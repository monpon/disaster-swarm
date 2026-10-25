import type { Live } from "./swarm";
import { clock, floorOf, liveFindings, type LiveFinding } from "./swarm";
import { routeTo, speakRoute, type Route } from "./routing";

/** What Mayfly can say or look up about the mission: routes to findings, searchable documents, spoken alerts. */

const routeOf = (live: Live, f: LiveFinding): Route | null => (f.kind === "person" && f.world ? routeTo(live, f.world) : null);

/** One short document per finding (with its route) and per recent event, for the voice agent's search. */
export function missionDocs(live: Live): { id: string; text: string }[] {
  const docs = liveFindings(live).map((f) => {
    const r = routeOf(live, f);
    const where = f.world ? ` Position ${f.world.map((v) => Math.round(v)).join(", ")}.` : "";
    return { id: `finding-${f.id}`, text: `${f.title}. ${f.detail}${where}${r ? ` Route: ${speakRoute(r)}` : ""}` };
  });
  for (const e of live.events.slice(-40)) docs.push({ id: `event-${e.seq}`, text: `At ${clock(e.t)}: ${e.text}` });
  return docs;
}

/** Routes for the people found so far, small enough to sit in every prompt. */
export function routesBrief(live: Live) {
  return liveFindings(live)
    .filter((f) => f.kind === "person")
    .map((f) => ({ finding: f.title, floor: f.floor === undefined ? undefined : f.floor + 1, route: routeOf(live, f) }));
}

/** The sentence to say when a finding first appears; null when it is not worth interrupting for. */
export function alertFor(live: Live, f: LiveFinding): string | null {
  if (f.kind === "person") {
    const r = routeOf(live, f);
    return `${f.title.replace("#", "number ")} found on floor ${(f.floor ?? floorOf(live, f.world?.[2] ?? 0)) + 1}. ${r ? speakRoute(r) : ""}`.trim();
  }
  if (f.kind === "blockage") return `${f.title}. ${f.detail}`;
  return null;
}
