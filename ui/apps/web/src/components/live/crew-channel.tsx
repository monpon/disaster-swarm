import { Button } from "@swarm/ui/components/button";
import { ChevronDown, ChevronUp, Mic } from "lucide-react";

import { crewMessages } from "@/lib/mock";

/**
 * Crew radio channel. Collapsing hides the transcript but keeps push-to-talk,
 * which must always be one tap away.
 */
export function CrewChannel({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <div className="flex h-full flex-col bg-panel">
      <div className="flex h-10 shrink-0 items-center gap-2 pr-2.5 pl-4">
        <span className="text-[13px] font-semibold">Crew channel</span>
        <span className="truncate text-xs text-muted">Engine 7, 3 connected</span>
        <div className="flex-1" />
        <Button variant="ghost" size="icon" onClick={onToggle} aria-label={collapsed ? "Expand crew channel" : "Collapse crew channel"}>
          {collapsed ? <ChevronUp /> : <ChevronDown />}
        </Button>
      </div>
      {!collapsed && (
        <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-4 pt-0.5 pb-3">
          {crewMessages.map((m) => (
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
        </div>
      )}
      <div className="mt-auto flex shrink-0 gap-2 px-3 pb-3">
        <input
          placeholder="Message crew"
          className="h-10 min-w-0 flex-1 rounded-lg bg-white px-3 text-[13px] shadow-[inset_0_0_0_1px_var(--color-line-strong),inset_0_1px_2px_rgb(0_0_0/0.06)] outline-none placeholder:text-faint focus:shadow-[inset_0_0_0_1.5px_var(--color-orange)]"
        />
        <Button variant="dark" size="lg" className="h-10">
          <Mic className="text-orange" />
          Hold to talk
        </Button>
      </div>
    </div>
  );
}
