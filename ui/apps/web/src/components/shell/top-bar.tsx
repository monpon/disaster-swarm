import { Link, useNavigate } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { useAuth } from "react-oidc-context";

import { displayName } from "@/lib/spacetime-auth";

import { Mark } from "../icons";

/** Console top bar: brand mark, page-specific left content, page actions, avatar. */
export function TopBar({ children, actions }: { children?: ReactNode; actions?: ReactNode }) {
  const navigate = useNavigate();
  const auth = useAuth();
  const name = displayName(auth.user);
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";
  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-line bg-white px-3">
      <Link to="/" aria-label="Home">
        <Mark />
      </Link>
      {children}
      <div className="flex-1" />
      {actions}
      <button
        type="button"
        title={name ? `Sign out ${name}` : "Sign out"}
        aria-label="Sign out"
        onClick={async () => {
          await auth.removeUser();
          await navigate({ to: "/" });
        }}
        className="flex size-[30px] items-center justify-center rounded-full bg-[#e7e7e4] text-xs font-semibold hover:bg-line-strong"
      >
        {initials}
      </button>
    </header>
  );
}
