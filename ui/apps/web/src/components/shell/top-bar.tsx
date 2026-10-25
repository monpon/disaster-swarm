import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Mark } from "../icons";

/** Console top bar: brand mark, page-specific left content, page actions, avatar. */
export function TopBar({ children, actions }: { children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-white px-3">
      <Link to="/" aria-label="Home">
        <Mark />
      </Link>
      {children}
      <div className="flex-1" />
      {actions}
      <span className="flex size-[30px] items-center justify-center rounded-full bg-[#e7e7e4] text-xs font-semibold">JR</span>
    </header>
  );
}
