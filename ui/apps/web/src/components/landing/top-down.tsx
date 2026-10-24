import { pathsFor, positionAt, type Mode, type Story } from "./story";

/**
 * Bird's-eye floor plan: rooms fill orange with a check once searched, drones
 * are dots, and the person appears when found. Built for a five-second read.
 */
export function TopDownHouse({ story, mode, t }: { story: Story; mode: Mode; t: number }) {
  const [w, h] = story.house;
  const found = story.events.person[mode] <= t;
  return (
    <svg viewBox={`-0.1 -0.1 ${w + 0.2} ${h + 0.2}`} className="h-auto w-full" role="img" aria-label={`${mode === "swarm" ? "Four drones" : "One drone"} searching a house`}>
      {Object.entries(story.rooms).map(([name, r]) => {
        const [x1, y1, x2, y2] = r.box;
        const done = r[mode] <= t;
        const cx = (x1 + x2) / 2;
        const cy = (y1 + y2) / 2;
        return (
          <g key={name}>
            <rect
              x={x1}
              y={y1}
              width={x2 - x1}
              height={y2 - y1}
              fill={done ? "#ffe7db" : "#efefed"}
              stroke={done ? "#ff5a1f" : "#d6d6d2"}
              strokeWidth={0.06}
              style={{ transition: "fill 300ms, stroke 300ms" }}
            />
            {done ? (
              <path
                d={`M${cx - 0.28} ${cy + 0.02} l0.2 0.2 l0.4 -0.42`}
                fill="none"
                stroke="#c2410c"
                strokeWidth={0.12}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ) : (
              <text x={cx} y={cy + 0.18} textAnchor="middle" fontSize={0.5} fontWeight={600} fill="#b0b0ac">
                ?
              </text>
            )}
          </g>
        );
      })}
      {found && (
        <g transform={`translate(${story.events.person.at[0]} ${story.events.person.at[1]})`}>
          <circle r={0.55} fill="#d92d20" stroke="#fff" strokeWidth={0.12} />
          <circle cy={-0.14} r={0.13} fill="#fff" />
          <path d="M-0.24 0.3c0-0.18 0.1-0.3 0.24-0.3s0.24 0.12 0.24 0.3" fill="#fff" />
        </g>
      )}
      {pathsFor(story, mode).map((path, i) => {
        const p = positionAt(path, t);
        return (
          <g key={i}>
            <polyline points={p.trail.map((q) => `${q[3]},${q[4]}`).join(" ")} fill="none" stroke="#ff5a1f" strokeOpacity={0.45} strokeWidth={0.07} strokeLinejoin="round" />
            <circle cx={p.mx} cy={p.my} r={0.36} fill="#ff5a1f" stroke="#fff" strokeWidth={0.1} />
          </g>
        );
      })}
    </svg>
  );
}

export function roomsDone(story: Story, mode: Mode, t: number) {
  return Object.values(story.rooms).filter((r) => r[mode] <= t).length;
}
