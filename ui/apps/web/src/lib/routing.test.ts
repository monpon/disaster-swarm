import { expect, test } from "bun:test";

import { directions, findPath, routeTo } from "./routing";
import type { Live, Plan } from "./swarm";

/** 12 x 8 floor: a wall at x = 6 with a gap at y = 5, explored everywhere except one unknown strip. */
function plan(): Plan {
  const w = 12, h = 8;
  const f = new Uint8Array(w * h).fill(1);
  for (let y = 0; y < h; y++) f[6 * h + y] = 2;
  f[6 * h + 5] = 1;
  return { x0: 10, y0: 20, w, h, story: 5, floors: [f] };
}

const live = (entries: object[], p: Plan | null = plan()) => ({ plan: p, entries, world: { building: { story: 5 } } }) as unknown as Live;
const door = (x: number, y: number, blocked = false) => ({ id: 1, center: [x, y, 2], normal: [1, 0, 0], side: "west", blocked });

test("path goes through the gap in the wall", () => {
  const p = plan();
  const cells = findPath(p, 0, [1, 1], [10, 1])!;
  expect(cells.some((i) => i === 6 * p.h + 5)).toBe(true);
  expect(cells[0]).toBe(1 * p.h + 1);
  expect(cells.at(-1)).toBe(10 * p.h + 1);
});

test("no path when the gap is blocked", () => {
  const p = plan();
  expect(findPath(p, 0, [1, 1], [10, 1], new Set([6 * p.h + 5]))).toBeNull();
});

test("directions name turns and compass headings", () => {
  const steps = directions([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [4, 1], [4, 2], [4, 3], [4, 4]]);
  expect(steps).toEqual(["Go 4 meters east", "then turn left and go 4 meters north"]);
});

test("routeTo picks the open entrance and reports length", () => {
  const r = routeTo(live([door(11, 21, true), door(12, 21)]), [20, 21, 2]);
  expect(r.found).toBe(true);
  expect(r.lengthM).toBeGreaterThan(8);
  expect(r.steps!.length).toBeGreaterThan(0);
});

test("routeTo says why there is no route", () => {
  expect(routeTo(live([door(11, 21, true)]), [20, 21, 2]).found).toBe(false);
  expect(routeTo(live([], null), [20, 21, 2]).note).toMatch(/floor plan/i);
  expect(routeTo(live([door(11, 21)]), [20, 21, 7]).note).toMatch(/Floor 2/);
});
