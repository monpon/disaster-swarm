import type { ReactNode } from "react";

import { NavRail } from "./nav-rail";

/** Everything below the top bar: the nav rail plus the page's panes. */
export function ConsoleBody({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1">
      <NavRail />
      {children}
    </div>
  );
}
