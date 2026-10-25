import { Button } from "@swarm/ui/components/button";
import { cn } from "@swarm/ui/lib/utils";
import { BellRing, BookOpen, ChevronDown, ChevronUp, Loader2, Mic, Volume2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { readManaNote, type ManaNote } from "@/lib/building";
import { useConsole } from "@/lib/console";
import { getDetection } from "@/lib/detection";
import { alertFor, missionDocs, routesBrief } from "@/lib/mission-brief";
import { useVoiceAgent, type VoiceState } from "@/lib/use-voice-agent";

const TALK_LABEL: Record<VoiceState, string> = { idle: "Hold to talk", listening: "Listening", thinking: "Thinking", speaking: "Speaking" };

/**
 * Crew radio channel. Collapsing hides the transcript but keeps push-to-talk,
 * which must always be one tap away. Push-to-talk and the text box ask Mayfly's
 * voice agent, which answers aloud and can change what the drones search for.
 */
export function CrewChannel({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const c = useConsole();
  const snapshot = useRef(c);
  snapshot.current = c;
  const consoleState = useCallback(() => {
    const s = snapshot.current;
    return {
      live: s.live,
      mission: s.mission,
      drones: s.drones.slice(0, 12).map((d) => ({ id: d.id, room: d.room, battery: d.battery, status: d.status, mode: (d as { mode?: string }).mode })),
      findings: s.findings.slice(0, 20).map((f) => ({ kind: f.kind, title: f.title, detail: f.detail, confidence: f.confidence })),
      routes: s.live ? routesBrief(s.raw) : [],
    };
  }, []);
  // Building research from Mana, done on the new-mission page: shown at the top of the log and searchable by the agent.
  const [mana, setMana] = useState<ManaNote | null>(null);
  useEffect(() => setMana(readManaNote()), []);
  const docs = useCallback(() => {
    const note = readManaNote();
    const building = (note?.findings ?? []).map((f, i) => ({ id: `mana-${i}`, text: `Building at ${note!.address}, ${f.label}: ${f.text} (source: ${f.source}, via Mana)` }));
    return [...building, ...(snapshot.current.live ? missionDocs(snapshot.current.raw) : [])];
  }, []);
  const agent = useVoiceAgent(consoleState, docs);

  // Proactive voice: with alerts on, say new findings as they appear (people, blocked openings) if their class is set to
  // speak immediately. What is already known when alerts are switched on is not read out.
  const [alerts, setAlerts] = useState(false);
  const seen = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!alerts) {
      seen.current = null;
      return;
    }
    const keyOf = (f: (typeof c.findings)[number]) => f.id;
    if (!seen.current) {
      seen.current = new Set(c.findings.map(keyOf));
      return;
    }
    const classes = getDetection().classes;
    for (const f of c.findings) {
      const key = keyOf(f);
      if (seen.current.has(key)) continue;
      seen.current.add(key);
      const cls = classes.find((x) => x.id === (f.kind === "person" ? "person" : f.kind));
      if (!c.live || !cls?.enabled || !cls.speak) continue;
      const text = alertFor(c.raw, f);
      if (text) agent.announce(text);
    }
  }, [alerts, c, agent]);
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [agent.log.length]);
  const busy = agent.state === "thinking" || agent.state === "speaking";
  return (
    <div className="flex h-full flex-col bg-panel">
      <div className="flex h-10 shrink-0 items-center gap-2 pr-2.5 pl-4">
        <span className="text-[13px] font-semibold">{c.live ? "Mission log" : "Crew channel"}</span>
        <span className="truncate text-xs text-muted">{c.live ? "live from Mayfly" : "Engine 7, 3 connected"}</span>
        <div className="flex-1" />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setAlerts((a) => !a)}
          aria-pressed={alerts}
          aria-label={alerts ? "Turn voice alerts off" : "Turn voice alerts on"}
          title={alerts ? "Voice alerts on: Mayfly speaks new findings" : "Voice alerts off"}
        >
          <BellRing className={alerts ? "text-orange" : "text-muted"} />
        </Button>
        <Button variant="ghost" size="icon" onClick={onToggle} aria-label={collapsed ? "Expand crew channel" : "Collapse crew channel"}>
          {collapsed ? <ChevronUp /> : <ChevronDown />}
        </Button>
      </div>
      {!collapsed && (
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-4 pt-0.5 pb-3">
          {mana && (
            <div className="flex gap-2.5">
              <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] text-muted">Setup</span>
              <div className="flex flex-1 flex-col gap-1 rounded-lg bg-white px-2.5 py-2 text-[13px] leading-[18px] shadow-[0_0_0_1px_var(--color-line)]">
                <span className="flex items-center gap-1.5 text-xs font-semibold">
                  <BookOpen className="size-3 text-orange" strokeWidth={2.5} />
                  Building research from Mana · {mana.address}
                </span>
                {mana.findings.slice(0, 3).map((f) => (
                  <span key={f.label} title={f.source}>
                    <span className="font-semibold">{f.label}.</span> {f.text}
                  </span>
                ))}
              </div>
            </div>
          )}
          {c.messages.map((m) => (
            <div key={m.id} className="flex gap-2.5">
              <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] text-muted">{m.at}</span>
              {m.from ? (
                <div className="flex flex-col gap-px">
                  <span className="text-xs font-semibold">{m.from}</span>
                  <span className="text-[13px] leading-[18px]">{m.text}</span>
                </div>
              ) : (
                <div className="flex-1 rounded-lg bg-white px-2.5 py-2 text-[13px] leading-[18px] shadow-[0_0_0_1px_var(--color-line)]">{m.text}</div>
              )}
            </div>
          ))}
          {agent.log.map((e) => (
            <div key={`agent-${e.id}`} className="flex flex-col gap-1.5">
              {!e.alert && (
                <div className="flex gap-2.5">
                  <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] text-muted">{e.at}</span>
                  <div className="flex flex-col gap-px">
                    <span className="text-xs font-semibold">You</span>
                    <span className="text-[13px] leading-[18px]">{e.q}</span>
                  </div>
                </div>
              )}
              <div className="flex gap-2.5">
                {e.alert ? <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] text-muted">{e.at}</span> : <span className="w-11 shrink-0" />}
                <div
                  className={cn(
                    "flex flex-1 flex-col gap-1 rounded-lg px-2.5 py-2 text-[13px] leading-[18px]",
                    e.error ? "bg-white text-muted shadow-[0_0_0_1px_var(--color-line)]" : "bg-[#2a2a29] text-white",
                  )}
                >
                  <span className={cn("text-xs font-semibold", e.error ? "text-muted" : "text-[#ff8a5c]")}>Mayfly</span>
                  {e.a}
                  {e.changes.length > 0 && <span className="text-xs text-white/70">Changed: {e.changes.join("; ")}</span>}
                </div>
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
      )}
      <form
        className="mt-auto flex shrink-0 gap-2 px-3 pb-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (agent.ask(draft)) setDraft("");
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={agent.state === "thinking"}
          placeholder="Ask Mayfly"
          aria-label="Ask Mayfly"
          className="h-10 min-w-0 flex-1 rounded-lg bg-white px-3 text-[13px] shadow-[inset_0_0_0_1px_var(--color-line-strong),inset_0_1px_2px_rgb(0_0_0/0.06)] outline-none placeholder:text-faint focus:shadow-[inset_0_0_0_1.5px_var(--color-orange)]"
        />
        <Button
          type="button"
          variant="dark"
          size="lg"
          className="h-10 touch-none select-none"
          disabled={busy}
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            agent.start();
          }}
          onPointerUp={agent.stop}
          onPointerCancel={agent.stop}
          onKeyDown={(e) => {
            if ((e.key === " " || e.key === "Enter") && !e.repeat) agent.start();
          }}
          onKeyUp={(e) => {
            if (e.key === " " || e.key === "Enter") agent.stop();
          }}
        >
          {agent.state === "thinking" ? (
            <Loader2 className="animate-spin text-orange" />
          ) : agent.state === "speaking" ? (
            <Volume2 className="text-orange" />
          ) : (
            <Mic className={cn("text-orange", agent.state === "listening" && "animate-pulse")} />
          )}
          {TALK_LABEL[agent.state]}
        </Button>
      </form>
    </div>
  );
}
