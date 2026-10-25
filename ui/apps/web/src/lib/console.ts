import { useMemo } from "react";

import * as mock from "./mock";
import { clock, liveDrones, liveFindings, liveMessages, liveMission, liveTicks, useLive, type LiveFinding } from "./swarm";

/**
 * What the console screens show: the running simulation's data when it is publishing into SpacetimeDB, the demo mission
 * otherwise. Same shapes either way, so the screens do not care which it is.
 */
export function useConsole() {
  const raw = useLive();
  return useMemo(() => {
    if (raw.connected) {
      return {
        live: true as const,
        raw,
        mission: liveMission(raw),
        drones: liveDrones(raw),
        fleet: liveDrones(raw),
        findings: liveFindings(raw) as LiveFinding[],
        ticks: liveTicks(raw),
        messages: liveMessages(raw),
      };
    }
    return {
      live: false as const,
      raw,
      mission: mock.mission,
      drones: mock.liveDrones,
      fleet: mock.fleet,
      findings: mock.findings as LiveFinding[],
      ticks: mock.timelineEvents,
      messages: mock.crewMessages,
    };
  }, [raw]);
}

export { clock };
