import { cn } from "@swarm/ui/lib/utils";
import { Link, useLocation } from "@tanstack/react-router";
import { History, Layers, LayoutPanelLeft, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import { Quad } from "../icons";

function RailLink({ to, active, label, children }: { to: string; active: boolean; label: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      aria-label={label}
      title={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex size-9 items-center justify-center rounded-lg transition-colors [&_svg]:size-[18px]",
        active
          ? "bg-white text-orange shadow-[0_0_0_1px_var(--color-line),0_1px_2px_rgb(0_0_0/0.06)]"
          : "text-muted hover:bg-ink/5 hover:text-ink",
      )}
    >
      {children}
    </Link>
  );
}

/** Fixed vertical navigation rail: the console's only chrome-level navigation. */
export function NavRail() {
  const { pathname } = useLocation();
  return (
    <nav className="flex w-[52px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel py-2">
      <RailLink to="/live" active={pathname.startsWith("/live")} label="Live">
        <Layers strokeWidth={1.7} />
      </RailLink>
      <RailLink to="/setup" active={pathname.startsWith("/setup")} label="Mission plan">
        <LayoutPanelLeft strokeWidth={1.7} />
      </RailLink>
      <RailLink to="/fleet" active={pathname.startsWith("/fleet")} label="Drones">
        <Quad />
      </RailLink>
      <span
        title="Replay (coming soon)"
        aria-disabled
        className="flex size-9 cursor-not-allowed items-center justify-center rounded-lg text-faint [&_svg]:size-[18px]"
      >
        <History strokeWidth={1.7} />
      </span>
      <div className="flex-1" />
      <RailLink to="/settings/detection" active={pathname.startsWith("/settings")} label="Settings">
        <SlidersHorizontal strokeWidth={1.7} />
      </RailLink>
    </nav>
  );
}
