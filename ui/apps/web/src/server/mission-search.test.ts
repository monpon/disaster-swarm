import { expect, test } from "bun:test";

import { searchMission } from "./mission-search";

delete process.env.MOSS_PROJECT_ID;

test("keyword fallback finds a finding's route and the reference notes", async () => {
  const docs = [{ id: "finding-c1", text: "Survivor #1: urgent. Floor 1. Route: From the west opening, about 14 meters. Go 9 meters east" }];
  const r = await searchMission(docs, "how do I get to the survivor");
  expect(r.via).toBe("keyword");
  expect(r.hits[0].id).toBe("finding-c1");
  expect((await searchMission(docs, "can the camera see through smoke")).hits.map((h) => h.id)).toContain("ref-limits");
});
