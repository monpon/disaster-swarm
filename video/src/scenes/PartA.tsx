import { Sequence } from "remotion";
import { FPS } from "../theme";
import { S1, S2, S3, S4, S5, S6 } from "../timeline";
import { S1Problem } from "./S1Problem";
import { S2Limits } from "./S2Limits";
import { S3Breakthrough } from "./S3Breakthrough";
import { S4HowItWorks } from "./S4HowItWorks";
import { S5Advantages } from "./S5Advantages";
import { S6Research } from "./S6Research";

const f = (s: number) => Math.round(s * FPS);

/** Part A: problem, existing limits, the idea, how it works, advantages, research. */
export function PartA() {
  const scenes = [
    [S1, S1Problem],
    [S2, S2Limits],
    [S3, S3Breakthrough],
    [S4, S4HowItWorks],
    [S5, S5Advantages],
    [S6, S6Research],
  ] as const;
  return (
    <>
      {scenes.map(([s, Comp]) => (
        <Sequence key={s.start} from={f(s.start)} durationInFrames={f(s.end - s.start)}>
          <Comp />
        </Sequence>
      ))}
    </>
  );
}
