/** Where each person sits around the drone in the vitals scene, in metres. */
export const PEOPLE_POS: [number, number][] = [
  [3.1, -0.4],
  [0.2, -3.1],
  [-3.0, 0.6],
];

/** Drone yaw that points its camera (local +x) at person i. */
export function yawFor(i: number) {
  const [x, z] = PEOPLE_POS[i]!;
  return Math.atan2(-z, x);
}
