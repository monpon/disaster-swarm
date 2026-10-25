import { Composition, Sequence, AbsoluteFill, staticFile } from "remotion";
import { Audio } from "@remotion/media";
import { FPS, H, W } from "./theme";
import { PART_A, PART_B, PART_C_LEN, PART_D_LEN, S1, S2, S3, S4, S5, S6 } from "./timeline";
import { S1Problem } from "./scenes/S1Problem";
import { S2Limits } from "./scenes/S2Limits";
import { S3Breakthrough } from "./scenes/S3Breakthrough";
import { S4HowItWorks } from "./scenes/S4HowItWorks";
import { S5Advantages } from "./scenes/S5Advantages";
import { S6Research } from "./scenes/S6Research";
import { PartB } from "./scenes/PartB";
import { Closing } from "./scenes/Closing";
import { PartC } from "./scenes/PartC";
import { Thumbnail } from "./Thumbnail";

const f = (s: number) => Math.round(s * FPS);
const LEN_B = PART_B.end - PART_B.start;
const TOTAL = PART_A.end + LEN_B + PART_C_LEN + PART_D_LEN;

function PartA() {
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

type Props = { music: boolean; vo: boolean };

/** Music sits under the recorded narration (Parts A–C) and comes up to full for the closing. */
function musicLevel(t: number, vo: boolean, cStart: number, dStart: number) {
  if (!vo) return 1;
  const ramp = (x: number, a: number, b: number) => Math.min(1, Math.max(0, (x - a) / (b - a)));
  const under = 0.3;
  return under + (1 - under) * ramp(t, dStart - 0.3, dStart + 0.3);
}

function Full({ music, vo }: Props) {
  const bStart = PART_A.end;
  const cStart = bStart + LEN_B;
  const dStart = cStart + PART_C_LEN;
  return (
    <AbsoluteFill style={{ background: "#000" }}>
      <PartA />
      <Sequence from={f(bStart)} durationInFrames={f(LEN_B)}>
        <PartB />
      </Sequence>
      <Sequence from={f(cStart)} durationInFrames={f(PART_C_LEN)}>
        <PartC />
      </Sequence>
      <Sequence from={f(dStart)} durationInFrames={f(PART_D_LEN)}>
        <Closing />
      </Sequence>
      {music && <Audio src={staticFile("audio/music.wav")} volume={(fr) => musicLevel(fr / FPS, vo, cStart, dStart)} />}
      {vo && <Audio src={staticFile("audio/narration.wav")} />}
      {vo && (
        <Sequence from={f(cStart)} layout="none">
          <Audio src={staticFile("audio/partC.wav")} />
        </Sequence>
      )}
    </AbsoluteFill>
  );
}

export function Root() {
  return (
    <>
      <Composition id="Full" component={Full} durationInFrames={f(TOTAL)} fps={FPS} width={W} height={H} defaultProps={{ music: true, vo: true }} />
      <Composition id="PartA" component={PartA} durationInFrames={f(PART_A.end)} fps={FPS} width={W} height={H} />
      <Composition id="PartB" component={PartB} durationInFrames={f(LEN_B)} fps={FPS} width={W} height={H} />
      <Composition id="PartC" component={PartC} durationInFrames={f(PART_C_LEN)} fps={FPS} width={W} height={H} />
      <Composition id="Thumbnail" component={Thumbnail} durationInFrames={1} fps={FPS} width={W} height={H} />
      <Composition id="PartD" component={Closing} durationInFrames={f(PART_D_LEN)} fps={FPS} width={W} height={H} />
    </>
  );
}
