// Master timeline in seconds (~3:52 total). Parts A and B follow the recorded
// narration (public/audio/narration.wav, word times in vo/real/words.json).
export const PART_A = { start: 0, end: 102.3 };
export const PART_B = { start: 102.3, end: 177.9 };
export const PART_C_LEN = 49;
export const PART_D_LEN = 5.5;

export const S1 = {
  start: 0,
  end: 22.4,
  vo: { imagine: 1.68, quake: 3.0, trapped: 6.5, nobody: 8.6, rescue: 10.76, fast: 14.52, problem: 15.14, inside: 16.74, second: 18.52 },
};
export const S2 = {
  start: 22.4,
  end: 39.1,
  vo: { today: 22.8, mapping: 27.1, slow: 30.46, expensive: 31.82, oneTwo: 34.06, victims: 35.76 },
};
export const S3 = {
  start: 39.1,
  end: 52.9,
  vo: { asked: 39.42, whatIf: 40.86, fraction: 43.7, notOne: 45.22, notTwo: 46.5, swarm: 47.9 },
};
export const S4 = {
  start: 52.9,
  end: 73.0,
  vo: { spreads: 53.14, noPilot: 57.6, map: 59.99, people: 64.35, vitals: 66.6, blocked: 69.83, danger: 71.5 },
};
export const S5 = {
  start: 73.0,
  end: 87.7,
  vo: { changes: 73.21, faster: 75.19, cheaper: 78.09, autonomous: 83.67 },
};
export const S6 = {
  start: 87.7,
  end: 102.3,
  vo: { backs: 87.85, sensors: 89.41, cost: 97.09 },
};

// Part B scene starts, relative to the website take (take t=0 is PART_B.start).
export const B = {
  s7: 0,
  s8: 10.4,
  s9: 20.8,
  s10: 23.2,
  s11: 26.7,
  s12: 31.2,
  s13: 35.6,
  s14: 40.5,
  s15: 48.6,
  s16: 55.5,
  s17: 63.7,
  s18: 70.9,
  end: 75.6,
};

// Part D cues, relative to its start (on-screen only; no recorded line).
export const D = { lives: 0.2, every: 1.9, brand: 3.2 };
